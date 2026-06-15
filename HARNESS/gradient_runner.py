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


def build_prompt(condition: str, variant: dict, *, skill_md: str = "", retrieved_context: str = "") -> str:
    ctx = _context_block(variant)
    if condition == "free_prompted":
        return (f"{_BASE_INSTRUCTION}\nVariant: {ctx}\n"
                'Return JSON {"classification": <Pathogenic|Likely Pathogenic|Uncertain Significance|'
                'Likely Benign|Benign>, "evidence_codes": [ACMG codes you would apply]}.')
    if condition == "retrieval_augmented":
        return (f"{_BASE_INSTRUCTION}\nRetrieved reference material:\n{retrieved_context}\n"
                f"Variant: {ctx}\n"
                'Return JSON {"classification": <5-tier>, "evidence_codes": [...]}.')
    if condition == "skill_reasoning":
        return (f"{_BASE_INSTRUCTION}\nApply the rules in this skill specification:\n{skill_md}\n"
                f"Variant: {ctx}\n"
                'Return JSON {"classification": <5-tier>, "evidence_codes": [...]}.')
    if condition == "skill_execution":
        return (f"{_BASE_INSTRUCTION}\nDo NOT output a classification. Output ONLY the structured ACMG "
                "evidence you can justify; a validated skill will combine it deterministically. "
                "ClinVar assertion evidence is not permitted.\n"
                f"Variant: {ctx}\n"
                "Return the evidence-submission JSON per the ClawBench ACMG evidence schema "
                "(submitted_evidence_codes[], abstentions[], benchmark_mode, clinvar_blinded_status, "
                "benchmark_truth_source, variant_id, genomic_context).")
    raise ValueError(f"unknown condition {condition!r}")


def parse_class_output(raw: str):
    """Parse a class-emitting condition's output. Returns (class|None, codes|None, format_ok)."""
    try:
        obj = json.loads(raw)
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
        return {"variant_id": variant["variant_id"], "model": model, "condition": condition,
                "format_ok": True, "scoreable": True, "predicted_class": cls, "truth_class": truth,
                "category": label["category"], "label": label, "criteria": criteria, "abstention": {},
                "raw": (raw or "")[:500]}

    if condition == "skill_execution":
        try:
            submission = json.loads(raw)
        except (ValueError, TypeError):
            return _format_fail(variant, condition, model, truth, raw)
        if not isinstance(submission, dict):
            return _format_fail(variant, condition, model, truth, raw)
        scored = SC.score_variant(submission, variant["truth"]["clnsig"],
                                  reference_codes=reference_codes, expected_mode=mode)
        scored.update({"variant_id": variant["variant_id"], "model": model, "condition": condition,
                       "format_ok": True, "raw": (raw or "")[:500]})
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
