"""Exp 1 constraint-gradient runner: the five conditions over held-out variants.

The gradient relocates correctness from the stochastic model into an executed skill:
  1 free_prompted        model classifies from its prior
  2 retrieval_augmented  model classifies with retrieved guideline/population/in-silico text
  3 skill_reasoning      model reads the clinical-variant-reporter SKILL.md and reasons to a class
  4 skill_execution      model supplies structured ACMG evidence; validate_evidence enforces the
                         contract (fail-closed, ClinVar-blinded) and acmg_engine.classify combines
                         deterministically  (the V1-analogue executed arm)
  5 answer_supplied      truth label supplied (the 100% ceiling; a control, not a result)

The model is an INJECTED adapter `adapter(condition, prompt) -> str`, so the harness is
deterministic and testable; the real run wires an Anthropic/OpenAI/clawbio adapter. The truth
label is never placed in a prompt: build_prompt sees only the variant's genomic context.
No side effects at import time.
"""
from __future__ import annotations

import json
import re

import acmg_vocabulary as voc
import score_acmg as SC
from validate_evidence import to_criteria, validate_evidence  # noqa: F401 (to_criteria via score)

CONDITIONS = ["free_prompted", "retrieval_augmented", "skill_reasoning",
              "skill_execution", "answer_supplied"]
_CLASS_EMITTING = {"free_prompted", "retrieval_augmented", "skill_reasoning"}

_BASE_INSTRUCTION = (
    "You are assessing a germline variant under the ACMG/AMP 2015 framework. "
    "Use ONLY the information provided below; do not look the variant up by identity."
)


def _context_block(variant: dict) -> str:
    gc = dict(variant.get("genomic_context", {}))
    # defensive: never echo any truth-bearing field even if a caller mis-nests it
    for k in ("clnsig", "truth", "classification", "review_stars"):
        gc.pop(k, None)
    return json.dumps(gc, sort_keys=True)


def _evidence_block(variant: dict) -> str:
    ev = variant.get("evidence_context", {}) or {}
    cons = ev.get("molecular_consequence") or "unknown"
    af = ev.get("population_max_af")
    af_str = "not observed in population databases" if af in (None, "") else str(af)
    return f"  molecular_consequence: {cons}\n  population_max_allele_frequency: {af_str}"


_CLASS_VOCAB = "Pathogenic | Likely Pathogenic | Uncertain Significance | Likely Benign | Benign"


def build_prompt(condition: str, variant: dict, *, skill_md: str = "", retrieved_context: str = "") -> str:
    head = (f"{_BASE_INSTRUCTION}\nVariant (GRCh38): {_context_block(variant)}\n"
            f"Structured evidence available (non-ClinVar):\n{_evidence_block(variant)}\n")
    if condition == "free_prompted":
        return head + (f'Classify under ACMG/AMP. Return JSON {{"classification": <{_CLASS_VOCAB}>, '
                       '"evidence_codes": [ACMG codes you would apply]}.')
    if condition == "retrieval_augmented":
        return (head + f"Retrieved reference material:\n{retrieved_context}\n"
                f'Return JSON {{"classification": <{_CLASS_VOCAB}>, "evidence_codes": [...]}}.')
    if condition == "skill_reasoning":
        return (head + f"Apply the rules in this skill specification:\n{skill_md}\n"
                f'Return JSON {{"classification": <{_CLASS_VOCAB}>, "evidence_codes": [...]}}.')
    if condition == "skill_execution":
        return (head + "Do NOT output a classification; a validated skill will combine your evidence "
                "deterministically. Assign ONLY ACMG/AMP evidence codes you can justify FROM THE "
                "STRUCTURED EVIDENCE ABOVE. ClinVar / prior-classification evidence is forbidden "
                "(PP5, BP6, and PS1/PM5 sourced from ClinVar must not be used).\n"
                "strength is one of: very_strong, strong, moderate, supporting (benign codes: "
                "stand_alone, strong, supporting).\n"
                "source_type is one of: population_frequency, computational, in_silico, functional, "
                "segregation, de_novo, case_control, phenotype, literature, other.\n"
                'Return JSON ONLY: {"submitted_evidence_codes": [{"code": "PVS1", "strength": "very_strong", '
                '"source_type": "computational", "source_id": "...", "rationale": "...", "confidence": 0.9}], '
                '"abstentions": [{"code": "PS3", "rationale": "no functional data"}]}.')
    raise ValueError(f"unknown condition {condition!r}")


def loads_lenient(raw):
    """Parse JSON that a real model may wrap in markdown fences or surround with prose."""
    if not isinstance(raw, str):
        raise ValueError("not a string")
    s = raw.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", s, re.DOTALL)
    if m:
        s = m.group(1).strip()
    try:
        return json.loads(s)
    except ValueError:
        i, j = s.find("{"), s.rfind("}")
        if i != -1 and j > i:
            return json.loads(s[i:j + 1])
        raise


def parse_class_output(raw: str):
    """Parse a class-emitting condition's output. Returns (class|None, codes|None, format_ok)."""
    try:
        obj = loads_lenient(raw)
    except (ValueError, TypeError):
        return (None, None, False)
    if not isinstance(obj, dict):
        return (None, None, False)
    cls = None
    for k in ("classification", "class", "acmg_class", "acmg_classification", "call"):
        if obj.get(k) is not None:
            cls = obj[k]
            break
    if cls is None:
        return (None, None, False)
    try:
        cls = SC.normalise_class(cls)
    except ValueError:
        return (None, None, False)
    codes = obj.get("evidence_codes") or obj.get("codes")
    if codes is not None and not isinstance(codes, list):
        codes = None
    return (cls, codes, True)


def _strip_clinvar_codes(codes: list, mode: str):
    """In a blinded mode, remove ClinVar-derived codes the model fabricated (it was not given
    ClinVar). Returns (kept, stripped_codes). Mirrors the validator's leakage rule so the kept set
    passes validation and the model is scored on its legitimate, non-ClinVar evidence only."""
    if not voc.clinvar_checks_enabled(mode):
        return list(codes), []
    kept, stripped = [], []
    for c in codes:
        if not isinstance(c, dict):
            kept.append(c)
            continue
        code = c.get("code")
        clinvar = voc.is_clinvar_sourced(c.get("source_type", ""), c.get("source_id", ""), c.get("rationale", ""))
        if code in voc.ASSERTION_CODES or clinvar:
            stripped.append(code)
        else:
            kept.append(c)
    return kept, stripped


def _strip_clinvar_abstentions(abstentions: list, mode: str):
    """In blinded mode, drop abstentions on ClinVar-assertion codes (PP5/BP6), which the validator
    rejects. Returns (kept, stripped_codes)."""
    if not voc.clinvar_checks_enabled(mode):
        return list(abstentions), []
    kept, stripped = [], []
    for a in abstentions:
        if isinstance(a, dict) and a.get("code") in voc.ASSERTION_CODES:
            stripped.append(a.get("code"))
        else:
            kept.append(a)
    return kept, stripped


def _format_fail(variant, condition, model, truth, raw):
    return {"variant_id": variant["variant_id"], "model": model, "condition": condition,
            "format_ok": False, "scoreable": False, "predicted_class": None, "truth_class": truth,
            "category": "format_fail", "label": {}, "criteria": {}, "abstention": {},
            "raw": (raw or "")[:500]}


def run_one(condition, variant, adapter, *, model="model", reference_codes=None,
            mode="clinvar_blinded", truth_source="clinvar", skill_md="", retrieved_context=""):
    truth = SC.normalise_class(variant["truth"]["clnsig"])

    if condition == "answer_supplied":
        label = SC.label_scores(truth, truth)
        return {"variant_id": variant["variant_id"], "model": model, "condition": condition,
                "format_ok": True, "scoreable": True, "predicted_class": truth, "truth_class": truth,
                "category": label["category"], "label": label, "criteria": {}, "abstention": {}}

    prompt = build_prompt(condition, variant, skill_md=skill_md, retrieved_context=retrieved_context)
    raw = adapter(condition, prompt)

    if condition in _CLASS_EMITTING:
        cls, codes, ok = parse_class_output(raw)
        if not ok:
            return _format_fail(variant, condition, model, truth, raw)
        label = SC.label_scores(cls, truth)
        criteria = (SC.criteria_scores(codes, reference_codes)
                    if (codes is not None and reference_codes is not None) else {})
        proposed = [{"code": c} for c in (codes or []) if isinstance(c, str)]
        return {"variant_id": variant["variant_id"], "model": model, "condition": condition,
                "format_ok": True, "scoreable": True, "predicted_class": cls, "truth_class": truth,
                "category": label["category"], "label": label, "criteria": criteria, "abstention": {},
                "proposed_codes": proposed, "raw": (raw or "")[:500]}

    if condition == "skill_execution":
        try:
            partial = loads_lenient(raw)
        except (ValueError, TypeError):
            return _format_fail(variant, condition, model, truth, raw)
        if not isinstance(partial, dict):
            return _format_fail(variant, condition, model, truth, raw)
        # In blinded mode, STRIP ClinVar-derived (fabricated) codes rather than rejecting the whole
        # submission: the model loses that evidence and falls back to its legit codes (usually VUS),
        # which is the trust architecture's predicted outcome. The strip count is itself a finding.
        raw_codes = partial.get("submitted_evidence_codes", []) or []
        # full per-code provenance (audit-complete): code + strength + source + rationale
        proposed = [{"code": c.get("code"), "strength": c.get("strength"),
                     "source_type": c.get("source_type"), "source_id": c.get("source_id"),
                     "rationale": (c.get("rationale") or "")[:160]}
                    for c in raw_codes if isinstance(c, dict)]
        kept, stripped = _strip_clinvar_codes(raw_codes, mode)
        kept_abst, stripped_abst = _strip_clinvar_abstentions(partial.get("abstentions", []) or [], mode)
        submission = {
            "variant_id": variant["variant_id"],
            "genomic_context": variant["genomic_context"],
            "submitted_evidence_codes": kept,
            "abstentions": kept_abst,
            "benchmark_mode": mode,
            "clinvar_blinded_status": voc.expected_blinded_status(mode),
            "benchmark_truth_source": truth_source,
        }
        scored = SC.score_variant(submission, variant["truth"]["clnsig"],
                                  reference_codes=reference_codes, expected_mode=mode)
        scored.update({"variant_id": variant["variant_id"], "model": model, "condition": condition,
                       "format_ok": True, "clinvar_codes_stripped": len(stripped) + len(stripped_abst),
                       "proposed_codes": proposed, "raw": (raw or "")[:500]})
        return scored

    raise ValueError(f"unknown condition {condition!r}")


def run_grid(variants, conditions, adapters: dict, *, reference_codes_by_variant=None,
             mode="clinvar_blinded", truth_source="clinvar", skill_md="", retrieved_context=""):
    """Run variant x condition x model. adapters maps model name -> adapter callable.
    reference_codes_by_variant maps variant_id -> reference ACMG code list (optional)."""
    results = []
    for variant in variants:
        ref = (reference_codes_by_variant or {}).get(variant["variant_id"])
        for condition in conditions:
            for model, adapter in adapters.items():
                results.append(run_one(condition, variant, adapter, model=model,
                                       reference_codes=ref, mode=mode, truth_source=truth_source,
                                       skill_md=skill_md, retrieved_context=retrieved_context))
    return results


def summarise(results) -> dict:
    """Per-condition aggregate (via score_acmg.aggregate) plus the format-fail rate."""
    by_cond: dict[str, list] = {}
    for r in results:
        by_cond.setdefault(r["condition"], []).append(r)
    out = {}
    for cond, group in by_cond.items():
        agg = SC.aggregate(group)
        n = len(group)
        agg["format_fail_rate"] = sum(1 for r in group if not r.get("format_ok")) / n if n else 0.0
        out[cond] = agg
    return out
