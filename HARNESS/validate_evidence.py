"""Fail-closed validator for ClawBench ACMG evidence submissions.

A model may PROPOSE structured ACMG evidence, but it may not smuggle classification,
circular truth-derived assertions, unsupported strength changes, or malformed ACMG
logic into the deterministic execution path. Every rejection is machine-readable:

    {"valid": false,
     "error_code": "DISALLOWED_CLINVAR_CRITERION",
     "field": "submitted_evidence_codes[2].code",
     "message": "PP5 is disabled in clinvar_blinded mode."}

Layers: (1) strict JSON parse (rejects NaN/Infinity, duplicate keys, non-object root);
(2) structural validation via jsonschema Draft 2020-12 against SCHEMAS/acmg_evidence_schema.json;
(3) a semantic layer enforcing the cross-field invariants below. All errors are collected,
not just the first, so a submission is fully auditable.

No side effects at import time: the schema and the combiner are loaded lazily.
"""
from __future__ import annotations

import functools
import hashlib
import json
import math
import re
from pathlib import Path

import acmg_vocabulary as voc

_REPO = Path(__file__).resolve().parents[1]
_SCHEMA_PATH = _REPO / "SCHEMAS" / "acmg_evidence_schema.json"

# Stable error-code vocabulary (each maps to one invariant; see README/audit doc).
ERROR_CODES = (
    "PARSE_ERROR",
    "DUPLICATE_KEY",
    "NON_SERIALISABLE_VALUE",
    "SCHEMA_STRUCTURE",
    "MODEL_SUPPLIED_CLASSIFICATION",
    "INVALID_ACMG_CODE",
    "DUPLICATE_CODE",
    "UNSUPPORTED_STRENGTH_UPGRADE",
    "DISALLOWED_CLINVAR_CRITERION",
    "TRUTH_LABEL_LEAKAGE",
    "DIRECTION_OVERRIDE",
    "CONFIDENCE_OUT_OF_RANGE",
    "EMPTY_SOURCE_ID",
    "SOURCE_CODE_INCOMPATIBLE",
    "MALFORMED_ABSTENTION",
    "ABSTENTION_CONFLICTS_WITH_ASSERTION",
    "MODE_STATUS_MISMATCH",
    "TRUTH_SOURCE_REQUIRED",
    "EMPTY_NONRESPONSE",
)

# Verdict-bearing keys that must never appear anywhere in a submission.
_VERDICT_KEYS = frozenset({
    "classification", "acmg_class", "acmg_classification", "final_call",
    "final_classification", "verdict", "tier", "suggested_tier", "implied_class",
    "pathogenicity", "clinical_significance", "clinsig", "class",
})

# Rationale patterns that assert an overall verdict (covert classification channel).
_VERDICT_PATTERNS = [
    re.compile(r"(?i)final\s+classification"),
    re.compile(r"(?i)overall\s+(classification|class)\b"),
    re.compile(r"(?i)\bclassify\s+(this|the)?\s*variant\s+as\b"),
    re.compile(r"(?i)\bclass\s+[1-5]\b"),
    re.compile(r"(?i)\bthe\s+variant\s+is\s+(likely\s+)?(pathogenic|benign)\b"),
    re.compile(r"(?i)should\s+(be\s+)?(output|classified|called?)\b.*\b(class|tier|pathogenic|benign|vus)\b"),
    re.compile(r"(?i)^\s*(likely\s+pathogenic|pathogenic|likely\s+benign|benign|vus|uncertain\s+significance)\s*\.?\s*$"),
]


def _err(code: str, field: str, message: str) -> dict:
    return {"valid": False, "error_code": code, "field": field, "message": message}


@functools.lru_cache(maxsize=1)
def _schema() -> dict:
    with open(_SCHEMA_PATH) as fh:
        return json.load(fh)


@functools.lru_cache(maxsize=1)
def _validator():
    from jsonschema import Draft202012Validator
    return Draft202012Validator(_schema())


def _json_path(parts) -> str:
    out = ""
    for p in parts:
        out += f"[{p}]" if isinstance(p, int) else (f".{p}" if out else p)
    return out or "<root>"


# ---- strict parse --------------------------------------------------------------
def _strict_load(text: str):
    """Parse JSON rejecting NaN/Infinity and duplicate keys. Returns (obj, errors)."""
    dups: list[str] = []

    def pairs_hook(pairs):
        seen = set()
        for k, _ in pairs:
            if k in seen:
                dups.append(k)
            seen.add(k)
        return dict(pairs)

    def reject_const(token):
        raise ValueError(f"non-finite JSON constant: {token}")

    try:
        obj = json.loads(text, object_pairs_hook=pairs_hook, parse_constant=reject_const)
    except ValueError as exc:
        msg = str(exc)
        if "non-finite" in msg:
            return None, [_err("NON_SERIALISABLE_VALUE", "<root>", msg)]
        return None, [_err("PARSE_ERROR", "<root>", f"not valid JSON: {msg}")]
    if dups:
        return None, [_err("DUPLICATE_KEY", "<root>",
                           f"duplicate key(s) in payload: {sorted(set(dups))}; ambiguous parse")]
    if not isinstance(obj, dict):
        return None, [_err("PARSE_ERROR", "<root>", "top-level value must be a JSON object")]
    return obj, []


def _nonfinite_errors(obj, path=()) -> list[dict]:
    """Catch inf/nan that slip past parse_constant (e.g. 1e400 -> inf)."""
    errs: list[dict] = []
    if isinstance(obj, float) and not math.isfinite(obj):
        errs.append(_err("NON_SERIALISABLE_VALUE", _json_path(path), f"non-finite number {obj}"))
    elif isinstance(obj, dict):
        for k, v in obj.items():
            errs += _nonfinite_errors(v, path + (k,))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            errs += _nonfinite_errors(v, path + (i,))
    return errs


def _verdict_key_errors(obj, path=()) -> list[dict]:
    errs: list[dict] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k.lower() in _VERDICT_KEYS:
                errs.append(_err("MODEL_SUPPLIED_CLASSIFICATION", _json_path(path + (k,)),
                                 f"verdict-bearing key '{k}' is forbidden; the combiner owns the class"))
            errs += _verdict_key_errors(v, path + (k,))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            errs += _verdict_key_errors(v, path + (i,))
    return errs


def _schema_errors(obj) -> list[dict]:
    out = []
    for e in _validator().iter_errors(obj):
        # Defer to better-named semantic codes for a few cases.
        if e.validator == "required" and "benchmark_truth_source" in e.message:
            continue  # -> TRUTH_SOURCE_REQUIRED
        if e.validator == "additionalProperties" and any(k in e.message for k in _VERDICT_KEYS):
            continue  # -> MODEL_SUPPLIED_CLASSIFICATION
        out.append(_err("SCHEMA_STRUCTURE", _json_path(e.absolute_path), e.message))
    return out


# ---- semantic layer ------------------------------------------------------------
def _semantic_errors(obj: dict, expected_mode: str | None) -> list[dict]:
    errs: list[dict] = []
    mode = obj.get("benchmark_mode")
    status = obj.get("clinvar_blinded_status")
    truth = obj.get("benchmark_truth_source")
    evidence = obj.get("submitted_evidence_codes")
    abstentions = obj.get("abstentions")

    if not isinstance(mode, str):
        return errs  # structural error already reported; mode-dependent checks can't run

    # mode integrity
    if expected_mode is not None and mode != expected_mode:
        errs.append(_err("MODE_STATUS_MISMATCH", "benchmark_mode",
                         f"submission mode '{mode}' != harness-assigned mode '{expected_mode}'; "
                         "mode is set by the harness, not the model"))
    if isinstance(status, bool) and status != voc.expected_blinded_status(mode):
        errs.append(_err("MODE_STATUS_MISMATCH", "clinvar_blinded_status",
                         f"clinvar_blinded_status={status} contradicts benchmark_mode '{mode}'"))
    if voc.requires_truth_source(mode) and not truth:
        errs.append(_err("TRUTH_SOURCE_REQUIRED", "benchmark_truth_source",
                         f"benchmark_truth_source is required in primary mode '{mode}'"))

    leakage_on = voc.runs_leakage_checks(mode)
    evidence_codes: list[str] = []

    if isinstance(evidence, list):
        # non-response guard
        if isinstance(abstentions, list) and not evidence and not abstentions:
            errs.append(_err("EMPTY_NONRESPONSE", "submitted_evidence_codes",
                             "asserting no evidence AND no abstentions is a non-response"))
        seen_codes: set[str] = set()
        for i, item in enumerate(evidence):
            if not isinstance(item, dict):
                continue  # structural error already reported
            fp = f"submitted_evidence_codes[{i}]"
            code = item.get("code")
            strength = item.get("strength")
            src_t = item.get("source_type", "") or ""
            src_id = item.get("source_id", "")
            rationale = item.get("rationale", "") or ""
            conf = item.get("confidence")
            basis = (item.get("strength_basis") or "").strip()

            if isinstance(code, str):
                if not voc.is_valid_code(code):
                    errs.append(_err("INVALID_ACMG_CODE", f"{fp}.code",
                                     f"'{code}' is not an ACMG/AMP 2015 code"))
                else:
                    evidence_codes.append(code)
                    if code in seen_codes:
                        errs.append(_err("DUPLICATE_CODE", f"{fp}.code",
                                         f"code '{code}' appears more than once"))
                    seen_codes.add(code)

                    # strength validity vs the code's ladder
                    if isinstance(strength, str) and strength in voc.STRENGTHS:
                        st = voc.strength_status(code, strength)
                        if st == "invalid":
                            errs.append(_err("UNSUPPORTED_STRENGTH_UPGRADE", f"{fp}.strength",
                                             f"strength '{strength}' is not permitted for {code} "
                                             f"(allowed: {voc.allowed_strengths(code)})"))
                        elif st == "needs_basis" and not basis:
                            errs.append(_err("UNSUPPORTED_STRENGTH_UPGRADE", f"{fp}.strength",
                                             f"{code} upgraded to '{strength}' without a strength_basis; "
                                             "ClinGen-endorsed upgrades require an explicit basis"))

                    # admissible source_type for the code
                    adm = voc.ADMISSIBLE_SOURCE_TYPES.get(code)
                    if adm and src_t and src_t not in adm:
                        errs.append(_err("SOURCE_CODE_INCOMPATIBLE", f"{fp}.source_type",
                                         f"source_type '{src_t}' is not admissible for {code} "
                                         f"(expected one of {sorted(adm)})"))

                    # direction-flip rationale (structural direction comes from the vocab)
                    if isinstance(rationale, str) and _direction_flip(code, rationale):
                        errs.append(_err("DIRECTION_OVERRIDE", f"{fp}.rationale",
                                         f"{code} is {voc.direction(code)} evidence; rationale asserts the opposite direction"))

                    # circularity / blinding
                    if leakage_on:
                        errs += _leakage_errors(code, src_t, src_id, rationale, truth, fp)

            if conf is not None and isinstance(conf, (int, float)) and not isinstance(conf, bool):
                if not (0.0 <= float(conf) <= 1.0):
                    errs.append(_err("CONFIDENCE_OUT_OF_RANGE", f"{fp}.confidence",
                                     f"confidence {conf} is outside [0, 1]"))
            if isinstance(src_id, str) and not src_id.strip():
                errs.append(_err("EMPTY_SOURCE_ID", f"{fp}.source_id",
                                 "source_id must be a non-empty, checkable identifier"))

    # abstentions
    if isinstance(abstentions, list):
        seen_abs: set[str] = set()
        for i, item in enumerate(abstentions):
            fp = f"abstentions[{i}]"
            if not isinstance(item, dict) or "code" not in item:
                errs.append(_err("MALFORMED_ABSTENTION", fp, "abstention must be {code, rationale}"))
                continue
            code = item.get("code")
            if not isinstance(code, str) or not voc.is_valid_code(code):
                errs.append(_err("INVALID_ACMG_CODE", f"{fp}.code",
                                 f"abstention on non-ACMG code '{code}'"))
                continue
            if code in seen_abs:
                errs.append(_err("DUPLICATE_CODE", f"{fp}.code",
                                 f"abstention on '{code}' appears more than once"))
            seen_abs.add(code)
            if code in evidence_codes:
                errs.append(_err("ABSTENTION_CONFLICTS_WITH_ASSERTION", f"{fp}.code",
                                 f"'{code}' is both asserted and abstained on"))
            if leakage_on and code in voc.ASSERTION_CODES:
                errs.append(_err("DISALLOWED_CLINVAR_CRITERION", f"{fp}.code",
                                 f"{code} is a ClinVar-assertion code and is out of scope in '{mode}', "
                                 "even as an abstention"))
    return errs


def _leakage_errors(code, src_t, src_id, rationale, truth, fp) -> list[dict]:
    if code in voc.ASSERTION_CODES:
        return [_err("DISALLOWED_CLINVAR_CRITERION", f"{fp}.code",
                     f"{code} is a ClinVar-assertion criterion and is disabled in primary (blinded) mode.")]
    clinvar_sourced = voc.is_clinvar_sourced(src_t, src_id, rationale)
    if code in voc.CLINVAR_GATED_CODES and clinvar_sourced:
        return [_err("DISALLOWED_CLINVAR_CRITERION", f"{fp}.source_type",
                     f"{code} sourced from ClinVar leaks the held-out label; disabled in primary mode.")]
    if clinvar_sourced:
        return [_err("DISALLOWED_CLINVAR_CRITERION", f"{fp}.source_type",
                     f"{code} has ClinVar provenance; the executing skill must not see ClinVar as evidence.")]
    fam = voc.circular_source_family(src_t, src_id, rationale, truth) if truth else None
    if fam:
        return [_err("TRUTH_LABEL_LEAKAGE", f"{fp}.source_type",
                     f"evidence source '{fam}' overlaps the benchmark truth label '{truth}' and is not allowed in primary mode.")]
    return []


def _direction_flip(code: str, rationale: str) -> bool:
    opp = "benign" if voc.direction(code) == "pathogenic" else "pathogenic"
    return bool(re.search(rf"(?i)(toward|support\w*|count\w*|treat\w*|count.*as|use\w*\s+as)\b[^.]{{0,20}}\b{opp}\b", rationale))


def _verdict_text_errors(obj: dict) -> list[dict]:
    errs: list[dict] = []
    ev = obj.get("submitted_evidence_codes")
    if isinstance(ev, list):
        for i, item in enumerate(ev):
            if isinstance(item, dict):
                r = item.get("rationale")
                if isinstance(r, str) and any(p.search(r) for p in _VERDICT_PATTERNS):
                    errs.append(_err("MODEL_SUPPLIED_CLASSIFICATION",
                                     f"submitted_evidence_codes[{i}].rationale",
                                     "rationale asserts an overall classification; the combiner owns the class"))
    return errs


# ---- canonicalisation + hash ---------------------------------------------------
def _canonical(obj: dict) -> dict:
    norm = dict(obj)
    ev = obj.get("submitted_evidence_codes")
    if isinstance(ev, list):
        norm["submitted_evidence_codes"] = sorted(
            ev, key=lambda x: x.get("code", "") if isinstance(x, dict) else "")
    ab = obj.get("abstentions")
    if isinstance(ab, list):
        norm["abstentions"] = sorted(
            ab, key=lambda x: x.get("code", "") if isinstance(x, dict) else "")
    return norm


def _hash(norm: dict) -> str:
    blob = json.dumps(norm, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    return hashlib.sha256(blob.encode()).hexdigest()


# ---- public API ----------------------------------------------------------------
def validate_evidence(obj: dict, expected_mode: str | None = None) -> dict:
    """Validate an already-parsed submission dict. Returns the result contract."""
    errors: list[dict] = []
    errors += _nonfinite_errors(obj)
    errors += _verdict_key_errors(obj)
    errors += _schema_errors(obj)
    errors += _verdict_text_errors(obj)
    errors += _semantic_errors(obj, expected_mode)
    if errors:
        return {"valid": False, "errors": errors, "normalized": None, "content_hash": None}
    norm = _canonical(obj)
    return {"valid": True, "errors": [], "normalized": norm, "content_hash": _hash(norm)}


def validate_evidence_json(text: str, expected_mode: str | None = None) -> dict:
    """Validate a raw JSON string (also catches NaN/Infinity and duplicate keys)."""
    obj, parse_errors = _strict_load(text)
    if parse_errors:
        return {"valid": False, "errors": parse_errors, "normalized": None, "content_hash": None}
    return validate_evidence(obj, expected_mode=expected_mode)


def to_criteria(submission: dict):
    """Bridge a VALIDATED submission to acmg_engine.EvidenceCriterion list for classify().

    Direction is taken from the canonical vocabulary, never from the model. Raises if the
    submission was not validated (contains an invalid code).
    """
    import sys
    skill_dir = _REPO / "SKILLS" / "clinical-variant-reporter"
    if str(skill_dir) not in sys.path:
        sys.path.insert(0, str(skill_dir))
    from acmg_engine import EvidenceCriterion

    out = []
    for item in submission.get("submitted_evidence_codes", []):
        code = item["code"]
        if not voc.is_valid_code(code):
            raise ValueError(f"to_criteria called on unvalidated submission: bad code {code}")
        out.append(EvidenceCriterion(
            code=code,
            triggered=True,
            strength=item["strength"],
            direction=voc.direction(code),
            source=f"{item.get('source_type', '')}:{item.get('source_id', '')}",
            detail=item.get("rationale", ""),
        ))
    return out
