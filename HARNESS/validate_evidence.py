"""Fail-closed validator for ClawBench ACMG evidence submissions.

A model may PROPOSE structured ACMG evidence, but it may not smuggle classification,
circular truth-derived assertions, unsupported strength changes, or malformed ACMG
logic into the deterministic execution path. Every rejection is machine-readable:

    {"valid": false,
     "error_code": "DISALLOWED_CLINVAR_CRITERION",
     "field": "submitted_evidence_codes[2].code",
     "message": "PP5 is disabled in clinvar_blinded mode."}

Layers: (1) strict JSON parse (rejects NaN/Infinity, duplicate keys, non-object root,
excessive nesting); (2) a single iterative structural scan (verdict keys/text anywhere,
non-finite numbers, non-string keys) that cannot recurse-crash; (3) jsonschema Draft 2020-12
against SCHEMAS/acmg_evidence_schema.json; (4) a semantic layer enforcing the cross-field
invariants. The whole entry point is exception-guarded so it can never raise.

Hardened against the adversarial-verify-evidence-layer workflow (12 empirical bypasses).
No side effects at import time: the schema and the combiner are loaded lazily.
"""
from __future__ import annotations

import functools
import hashlib
import json
import math
import re
import unicodedata
from pathlib import Path

import acmg_vocabulary as voc

_REPO = Path(__file__).resolve().parents[1]
_SCHEMA_PATH = _REPO / "SCHEMAS" / "acmg_evidence_schema.json"
_MAX_DEPTH = 64  # far beyond any legitimate ACMG submission; rejects nesting attacks

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

_VERDICT_KEYS = frozenset({
    "classification", "acmg_class", "acmg_classification", "final_call",
    "final_classification", "verdict", "tier", "suggested_tier", "implied_class",
    "pathogenicity", "clinical_significance", "clinsig", "class",
})

# Free-text patterns that assert an overall 5-tier verdict (covert classification channel),
# scanned across EVERY string field, not just rationale.
_VERDICT_PATTERNS = [
    re.compile(r"(?i)final\s+classification"),
    re.compile(r"(?i)overall\s+(classification|class)\b"),
    re.compile(r"(?i)\bclassif(?:y|ied)\b[^.]{0,30}\bas\b[^.]{0,25}\b(pathogenic|benign|likely|vus|uncertain|lp|lb|class|tier)\b"),
    re.compile(r"(?i)\bclass\s*[:=]?\s*(?:[1-5]|[IVX]{1,3})\b"),
    re.compile(r"(?i)\btier\s*[:=]?\s*(?:[1-5]|[IVX]{1,3})\b"),
    re.compile(r"(?i)\bverdict\b"),
    re.compile(r"(?i)\bthe\s+variant\s+is\s+(likely\s+)?(pathogenic|benign)\b"),
    re.compile(r"(?i)\breport(?:ed|s)?\s+(?:it|this(?:\s+variant)?)\s+as\s+(lp|lb|vus|pathogenic|benign|likely\s+\w+)\b"),
    re.compile(r"(?i)should\s+(be\s+)?(output|classified|called?|reported)\b[^.]{0,30}\b(class|tier|pathogenic|benign|vus|lp|lb)\b"),
    re.compile(r"(?i)^\s*(likely\s+pathogenic|pathogenic|likely\s+benign|benign|vus|uncertain\s+significance|lp|lb|p[1-5])\s*\.?\s*$"),
]


# Negation cues; a verdict-direction trigger preceded by one of these in a short window
# is a legitimate "does NOT support the opposite direction" phrasing, not a direction flip.
_NEG = re.compile(r"(?i)\b(not|no|never|without|cannot|can.?t|don.?t|does\s?n.?t|did\s?n.?t|"
                  r"fails?\s+to|insufficient|lack\w*|absence|too\s+\w+\s+to|unlikely)\b")


def _fold(s: str) -> str:
    """NFKC-normalise and drop format/zero-width (Cf) characters so verdict scans cannot
    be evaded with fullwidth forms, ligatures, circled/superscript digits, roman-numeral
    codepoints, or zero-width splitters. (Homoglyph confusables are out of scope here; the
    structured verdict-key channel is closed regardless, and rationale text never reaches
    the deterministic class.)"""
    stripped = "".join(ch for ch in s if unicodedata.category(ch) != "Cf")
    return unicodedata.normalize("NFKC", stripped)


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
        out += f"[{p}]" if isinstance(p, int) else (f".{p}" if out else str(p))
    return out or "<root>"


def _max_depth(obj) -> int:
    """Iterative max nesting depth (no recursion)."""
    m, stack = 0, [(obj, 0)]
    while stack:
        node, d = stack.pop()
        if d > m:
            m = d
        if isinstance(node, dict):
            for v in node.values():
                stack.append((v, d + 1))
        elif isinstance(node, list):
            for v in node:
                stack.append((v, d + 1))
    return m


# ---- strict parse --------------------------------------------------------------
def _strict_load(text: str):
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
    except RecursionError:
        # json's native scanner recurses; very deep nesting raises before our depth guard.
        return None, [_err("SCHEMA_STRUCTURE", "<root>", "nesting too deep to parse")]
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
    if _max_depth(obj) > _MAX_DEPTH:
        return None, [_err("SCHEMA_STRUCTURE", "<root>", f"nesting exceeds maximum depth {_MAX_DEPTH}")]
    return obj, []


# ---- single iterative structural scan ------------------------------------------
def _structural_scan(obj) -> list[dict]:
    """One non-recursive pass: verdict keys, verdict text in any string, non-finite
    numbers, non-string keys. Cannot raise on adversarial nesting or odd key types."""
    errs: list[dict] = []
    stack = [((), obj)]
    while stack:
        path, node = stack.pop()
        if isinstance(node, dict):
            for k, v in node.items():
                if not isinstance(k, str):
                    errs.append(_err("SCHEMA_STRUCTURE", _json_path(path),
                                     f"non-string object key {k!r}"))
                    child = path + (str(k),)
                else:
                    if _fold(k).lower() in _VERDICT_KEYS:
                        errs.append(_err("MODEL_SUPPLIED_CLASSIFICATION", _json_path(path + (k,)),
                                         f"verdict-bearing key '{k}' is forbidden; the combiner owns the class"))
                    child = path + (k,)
                stack.append((child, v))
        elif isinstance(node, list):
            for i, v in enumerate(node):
                stack.append((path + (i,), v))
        elif isinstance(node, float):
            if not math.isfinite(node):
                errs.append(_err("NON_SERIALISABLE_VALUE", _json_path(path), f"non-finite number {node}"))
        elif isinstance(node, str):
            folded = _fold(node)
            if any(p.search(node) or p.search(folded) for p in _VERDICT_PATTERNS):
                errs.append(_err("MODEL_SUPPLIED_CLASSIFICATION", _json_path(path),
                                 "free-text asserts an overall classification; the combiner owns the class"))
    return errs


def _schema_errors(obj) -> list[dict]:
    out = []
    for e in _validator().iter_errors(obj):
        if e.validator == "required" and "benchmark_truth_source" in e.message:
            continue  # -> TRUTH_SOURCE_REQUIRED
        if e.validator == "additionalProperties" and any(k in e.message for k in _VERDICT_KEYS):
            continue  # -> MODEL_SUPPLIED_CLASSIFICATION
        out.append(_err("SCHEMA_STRUCTURE", _json_path(e.absolute_path), e.message))
    return out


# ---- semantic layer ------------------------------------------------------------
def _as_str(v) -> str:
    return v if isinstance(v, str) else ""


def _semantic_errors(obj: dict, expected_mode: str | None) -> list[dict]:
    errs: list[dict] = []
    mode = obj.get("benchmark_mode")
    status = obj.get("clinvar_blinded_status")
    truth = obj.get("benchmark_truth_source")
    evidence = obj.get("submitted_evidence_codes")
    abstentions = obj.get("abstentions")

    if not isinstance(mode, str):
        return errs

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

    clinvar_on = voc.clinvar_checks_enabled(mode)
    evidence_codes: list[str] = []

    if isinstance(evidence, list):
        if isinstance(abstentions, list) and not evidence and not abstentions:
            errs.append(_err("EMPTY_NONRESPONSE", "submitted_evidence_codes",
                             "asserting no evidence AND no abstentions is a non-response"))
        seen: set[str] = set()
        for i, item in enumerate(evidence):
            if not isinstance(item, dict):
                continue
            fp = f"submitted_evidence_codes[{i}]"
            code = item.get("code")
            strength = item.get("strength")
            src_t = _as_str(item.get("source_type"))
            src_id = item.get("source_id")
            rationale = _as_str(item.get("rationale"))
            conf = item.get("confidence")
            basis = item.get("strength_basis")

            if isinstance(code, str):
                if not voc.is_valid_code(code):
                    errs.append(_err("INVALID_ACMG_CODE", f"{fp}.code", f"'{code}' is not an ACMG/AMP 2015 code"))
                else:
                    evidence_codes.append(code)
                    if code in seen:
                        errs.append(_err("DUPLICATE_CODE", f"{fp}.code", f"code '{code}' appears more than once"))
                    seen.add(code)

                    if isinstance(strength, str) and strength in voc.STRENGTHS:
                        st = voc.strength_status(code, strength)
                        if st == "invalid":
                            errs.append(_err("UNSUPPORTED_STRENGTH_UPGRADE", f"{fp}.strength",
                                             f"strength '{strength}' is not permitted for {code} "
                                             f"(allowed: {voc.allowed_strengths(code)})"))
                        elif st == "needs_basis" and not voc.has_content(basis):
                            errs.append(_err("UNSUPPORTED_STRENGTH_UPGRADE", f"{fp}.strength",
                                             f"{code} upgraded to '{strength}' without a substantive strength_basis; "
                                             "ClinGen-endorsed upgrades require an explicit basis"))

                    adm = voc.ADMISSIBLE_SOURCE_TYPES.get(code)
                    if adm and src_t and src_t not in adm:
                        errs.append(_err("SOURCE_CODE_INCOMPATIBLE", f"{fp}.source_type",
                                         f"source_type '{src_t}' is not admissible for {code} (expected one of {sorted(adm)})"))

                    if _direction_flip(code, rationale):
                        errs.append(_err("DIRECTION_OVERRIDE", f"{fp}.rationale",
                                         f"{code} is {voc.direction(code)} evidence; rationale asserts the opposite direction"))

                    if clinvar_on:
                        errs += _leakage_errors(code, src_t, _as_str(src_id), rationale, truth, fp)

            if isinstance(conf, (int, float)) and not isinstance(conf, bool):
                if math.isfinite(conf) and not (0.0 <= float(conf) <= 1.0):
                    errs.append(_err("CONFIDENCE_OUT_OF_RANGE", f"{fp}.confidence",
                                     f"confidence {conf} is outside [0, 1]"))
            if not voc.has_content(src_id):
                errs.append(_err("EMPTY_SOURCE_ID", f"{fp}.source_id",
                                 "source_id must be a non-empty, checkable identifier"))

    if isinstance(abstentions, list):
        seen_abs: set[str] = set()
        for i, item in enumerate(abstentions):
            fp = f"abstentions[{i}]"
            if not isinstance(item, dict) or "code" not in item:
                errs.append(_err("MALFORMED_ABSTENTION", fp, "abstention must be {code, rationale}"))
                continue
            code = item.get("code")
            if not isinstance(code, str) or not voc.is_valid_code(code):
                errs.append(_err("INVALID_ACMG_CODE", f"{fp}.code", f"abstention on non-ACMG code '{code}'"))
                continue
            if code in seen_abs:
                errs.append(_err("DUPLICATE_CODE", f"{fp}.code", f"abstention on '{code}' appears more than once"))
            seen_abs.add(code)
            if code in evidence_codes:
                errs.append(_err("ABSTENTION_CONFLICTS_WITH_ASSERTION", f"{fp}.code",
                                 f"'{code}' is both asserted and abstained on"))
            if clinvar_on and code in voc.ASSERTION_CODES:
                errs.append(_err("DISALLOWED_CLINVAR_CRITERION", f"{fp}.code",
                                 f"{code} is a ClinVar-assertion code and is out of scope in '{mode}', even as an abstention"))
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
    if truth:
        fam = voc.circular_source_family(src_t, src_id, rationale, truth)
        if fam:
            return [_err("TRUTH_LABEL_LEAKAGE", f"{fp}.source_type",
                         f"evidence source '{fam}' overlaps the benchmark truth label '{truth}' and is not allowed in primary mode.")]
    return []


def _direction_flip(code: str, rationale: str) -> bool:
    if not rationale:
        return False
    opp = "benign" if voc.direction(code) == "pathogenic" else "pathogenic"
    pat = re.compile(rf"(?i)(toward|support\w*|count\w*|treat\w*|use\w*\s+as)\b[^.]{{0,20}}\b{opp}\b")
    for m in pat.finditer(rationale):
        # a negation just before the trigger ("do not support a pathogenic effect") is a
        # legitimate benign/pathogenic rationale, not a direction flip.
        window = rationale[max(0, m.start() - 30):m.start()]
        if _NEG.search(window):
            continue
        return True
    return False


# ---- derived truth-label check (invariant 10) ----------------------------------
def source_evidence_is_truth_label(item: dict, truth_source: str) -> bool:
    """Derived (not self-reported): does this evidence item's provenance overlap the truth label?"""
    code = item.get("code")
    src_t = _as_str(item.get("source_type"))
    src_id = _as_str(item.get("source_id"))
    rationale = _as_str(item.get("rationale"))
    if code in voc.ASSERTION_CODES:
        return True
    # ClinVar provenance is intrinsically truth-derived for any classification truth label,
    # not only when the active truth family contains ClinVar.
    if voc.is_clinvar_sourced(src_t, src_id, rationale):
        return True
    return bool(voc.circular_source_family(src_t, src_id, rationale, truth_source))


def _derived(obj: dict) -> dict:
    truth = obj.get("benchmark_truth_source") or "clinvar"
    per: dict[str, bool] = {}
    for item in obj.get("submitted_evidence_codes", []):
        if isinstance(item, dict) and isinstance(item.get("code"), str) and voc.is_valid_code(item["code"]):
            per[item["code"]] = source_evidence_is_truth_label(item, truth)
    return {"truth_source_assumed": truth,
            "any_source_is_truth_label": any(per.values()),
            "source_evidence_is_truth_label": per}


# ---- canonicalisation + hash ---------------------------------------------------
def _canonical(obj: dict) -> dict:
    norm = dict(obj)
    ev = obj.get("submitted_evidence_codes")
    if isinstance(ev, list):
        norm["submitted_evidence_codes"] = sorted(
            ev, key=lambda x: x.get("code", "") if isinstance(x, dict) else "")
    ab = obj.get("abstentions")
    if isinstance(ab, list):
        norm["abstentions"] = sorted(ab, key=lambda x: x.get("code", "") if isinstance(x, dict) else "")
    return norm


def _hash(norm: dict) -> str:
    blob = json.dumps(norm, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    return hashlib.sha256(blob.encode()).hexdigest()


# ---- public API ----------------------------------------------------------------
def _validate(obj: dict, expected_mode: str | None) -> dict:
    if _max_depth(obj) > _MAX_DEPTH:
        return {"valid": False, "errors": [_err("SCHEMA_STRUCTURE", "<root>", f"nesting exceeds maximum depth {_MAX_DEPTH}")],
                "normalized": None, "content_hash": None}
    errors: list[dict] = []
    for layer in (lambda: _structural_scan(obj),
                  lambda: _schema_errors(obj),
                  lambda: _semantic_errors(obj, expected_mode)):
        try:
            errors += layer()
        except Exception as exc:  # a layer crash must not discard other findings
            errors.append(_err("SCHEMA_STRUCTURE", "<root>", f"validation layer error: {type(exc).__name__}: {exc}"))
    if errors:
        return {"valid": False, "errors": errors, "normalized": None, "content_hash": None}
    norm = _canonical(obj)
    return {"valid": True, "errors": [], "normalized": norm, "content_hash": _hash(norm), "derived": _derived(obj)}


def validate_evidence(obj: dict, expected_mode: str | None = None) -> dict:
    """Validate an already-parsed submission dict. Never raises (fail-closed)."""
    try:
        if not isinstance(obj, dict):
            return {"valid": False, "errors": [_err("PARSE_ERROR", "<root>", "submission must be a JSON object")],
                    "normalized": None, "content_hash": None}
        return _validate(obj, expected_mode)
    except Exception as exc:  # absolute guarantee: a rejection is always machine-readable
        return {"valid": False, "errors": [_err("PARSE_ERROR", "<root>", f"validator exception: {type(exc).__name__}: {exc}")],
                "normalized": None, "content_hash": None}


def validate_evidence_json(text: str, expected_mode: str | None = None) -> dict:
    """Validate a raw JSON string (also catches NaN/Infinity, duplicate keys, deep nesting)."""
    obj, parse_errors = _strict_load(text)
    if parse_errors:
        return {"valid": False, "errors": parse_errors, "normalized": None, "content_hash": None}
    return validate_evidence(obj, expected_mode=expected_mode)


def to_criteria(submission: dict):
    """Bridge a VALIDATED submission to acmg_engine.EvidenceCriterion list for classify().

    Direction is taken from the canonical vocabulary, never from the model.
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
