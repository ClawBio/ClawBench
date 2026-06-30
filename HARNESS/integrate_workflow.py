"""End-to-end workflow integration: bind Exp2 (calling) to Exp1 (interpretation).

The integrated ClawBench paper's unifying contribution (hostile review S3.5): a single end-to-end
accuracy number conflates failures that originate in DIFFERENT workflow layers. This module joins,
per GIAB/ClinVar-overlap variant, the CALLING outcome with the INTERPRETATION attribution into one
end-to-end label that attributes WHERE the failure originates, so the two halves form one framework
rather than two papers sharing a slogan.

Inputs are injected and decoupled from the scorers, so the join is deterministic and testable before
any real VCF is produced:
- calling_outcomes[variant_key] = {"vcfeval": "TP"|"FP"|"FN", "gt_match": bool}  (gt_match defaults
  True for a TP; a TP with gt_match False is allele-correct but genotype-wrong).
- interp_attributions[variant_key] = an Exp1 attribute_one record: {"flags": {dangerous, safety_clean,
  evidence_insufficient, assignment_unstable, combiner_sensitive}, "truth", "rule_class"}.
- overlap_keys = the variants that are BOTH GIAB-confident AND in the held-out ClinVar interpretation
  slice (the only variants where end-to-end attribution is meaningful).

Variant keys must be normalised consistently upstream (e.g. CHROM:POS:REF:ALT on GRCh38); that
normalisation is an adapter concern, not this module's. No import-time IO.

Honest pipeline semantics:
- a variant only REACHES interpretation if called correctly (TP, genotype-matching);
- FN (missed) and FP (phantom) are calling-layer outcomes that never reach interpretation;
- a TP with a wrong genotype is a calling error that PROPAGATES into interpretation.
"""
from __future__ import annotations

from collections import Counter

# rate-limiting interpretation layer, most-severe first (mirrors the Exp1 six-layer order:
# safety dominates; among uncertainty layers, sufficiency -> assignment -> combiner threshold).
_INTERP_PRIORITY = [
    ("dangerous", "dangerous", "dangerous_misclass"),
    ("evidence_insufficient", "evidence_insufficient", "interpretation_evidence_insufficient"),
    ("assignment_unstable", "assignment_unstable", "interpretation_assignment"),
    ("combiner_sensitive", "combiner_sensitive", "interpretation_combiner"),
]


def _interp_layer(flags: dict) -> tuple[str, str]:
    """Return (layer, endtoend_label) for a correctly-called variant from its interpretation flags.
    Clean = safe, sufficient, stable, combiner-insensitive."""
    for flag, layer, label in _INTERP_PRIORITY:
        if flags.get(flag):
            return layer, label
    return "clean", "clean"


def classify_variant_endtoend(calling: dict | None, interp: dict | None) -> dict:
    """Join one variant's calling outcome and interpretation attribution into an end-to-end label."""
    outcome = (calling or {}).get("vcfeval")

    # calling-layer outcomes that never reach interpretation
    if calling is None or outcome == "FN":
        return {"calling_outcome": "FN" if outcome == "FN" else None,
                "reached_interpretation": False, "interpretation_layer": None,
                "endtoend_label": "calling_miss"}
    if outcome == "FP":
        return {"calling_outcome": "FP", "reached_interpretation": False,
                "interpretation_layer": None, "endtoend_label": "calling_false_positive"}

    # TP: a wrong genotype is a calling error that propagates into interpretation
    if outcome == "TP" and calling.get("gt_match", True) is False:
        return {"calling_outcome": "TP", "reached_interpretation": True,
                "interpretation_layer": None, "endtoend_label": "genotype_propagation"}

    # correctly called -> attribute to an interpretation layer
    if interp is None:
        return {"calling_outcome": outcome, "reached_interpretation": True,
                "interpretation_layer": None, "endtoend_label": "interpretation_unscored"}
    layer, label = _interp_layer(interp.get("flags", {}) or {})
    return {"calling_outcome": outcome, "reached_interpretation": True,
            "interpretation_layer": layer, "endtoend_label": label}


def join_workflow(calling_outcomes: dict, interp_attributions: dict, overlap_keys) -> dict:
    """Join over the overlap set; return per-variant end-to-end records, a label histogram, the overlap
    size, and how many variants reached interpretation."""
    per_variant = {}
    for key in overlap_keys:
        per_variant[key] = classify_variant_endtoend(
            calling_outcomes.get(key), interp_attributions.get(key))
    summary = Counter(v["endtoend_label"] for v in per_variant.values())
    reached = sum(1 for v in per_variant.values() if v["reached_interpretation"])
    return {"per_variant": per_variant, "summary": summary,
            "n_overlap": len(per_variant), "reached_interpretation": reached}
