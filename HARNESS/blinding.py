"""ClinVar-blinded benchmark mode for ClawBench Exp 1 (validity fix F1).

The clinical-variant-reporter skill's PS1/PP5/BP6 criteria read ClinVar assertion
status directly. When ClinVar is the scoring ground truth, that is circular: the
skill would be reading the answer key. This module enforces a strict blinding
policy so the executed skill never sees ClinVar as evidence, while ClinVar is
retained downstream only as an external reference label.

Manuscript claim this supports:
  "To avoid circular evaluation, ClinVar-derived assertion criteria were disabled
   during primary benchmarking. ClinVar classifications were retained only as
   external reference labels for scoring, never as evidence available to the
   executing skill."

The pinned skill (SKILLS/clinical-variant-reporter, ClawBio commit d25071be) is not
modified; blinding is applied as a harness-side transformation.
"""
from __future__ import annotations

from dataclasses import replace

from acmg_engine import (
    EvidenceCriterion,
    VariantEvidence,
    classify,
    evaluate_criteria,
)

PRIMARY_MODE = "clinvar_blinded"
SENSITIVITY_MODE = "clinvar_unblinded_sensitivity"
VALID_MODES = (PRIMARY_MODE, SENSITIVITY_MODE)

# Always disabled under blinding (PP5/BP6 deprecated by ClinGen SVI; PS1 here is
# ClinVar-only). Reported verbatim in blinded_criteria_removed, canonical order.
BLINDED_POLICY_CODES = ("PS1", "PP5", "BP6")
_ALWAYS_DISABLED = frozenset({"PP5", "BP6"})
_CLINVAR_GATED = frozenset({"PS1"})


def blind_evidence(ev: VariantEvidence) -> VariantEvidence:
    """Return a copy of the evidence with ClinVar assertion fields removed.

    Does not mutate the caller's object. After this, PS1/PP5/BP6 cannot trigger
    from ClinVar because their only evidence source is gone.
    """
    return replace(ev, clinvar_significance="", clinvar_review_stars=0)


def _is_clinvar_sourced(criterion: EvidenceCriterion) -> bool:
    return "clinvar" in (criterion.source or "").lower()


def _strip_blinded(criteria: list[EvidenceCriterion]) -> tuple[list[EvidenceCriterion], list[str]]:
    """Drop ClinVar-derived assertion criteria. Returns (kept, removed_policy_codes).

    PS1 is dropped only when ClinVar-sourced (rule: disabled unless supported by
    non-ClinVar evidence). PP5/BP6 are always dropped. The reported removed list is
    the policy set, so the audit trail is explicit per variant.
    """
    kept: list[EvidenceCriterion] = []
    for c in criteria:
        if c.code in _ALWAYS_DISABLED:
            continue
        if c.code in _CLINVAR_GATED and _is_clinvar_sourced(c):
            continue
        kept.append(c)
    return kept, list(BLINDED_POLICY_CODES)


def classify_with_mode(ev: VariantEvidence, mode: str) -> dict:
    """Classify a variant under the given benchmark mode.

    Returns a dict with the final class, the triggered criteria codes, the blinded
    policy codes removed, and an explicit flag recording whether ClinVar was usable
    as evidence. The ClinVar label itself stays out of this path; scoring joins it
    separately as external truth.
    """
    if mode not in VALID_MODES:
        raise ValueError(f"unknown benchmark_mode {mode!r}; expected one of {VALID_MODES}")

    if mode == SENSITIVITY_MODE:
        criteria = evaluate_criteria(ev)
        removed: list[str] = []
        clinvar_used = bool(ev.clinvar_significance)
    else:  # PRIMARY_MODE
        criteria = evaluate_criteria(blind_evidence(ev))
        criteria, removed = _strip_blinded(criteria)
        clinvar_used = False

    triggered = [c.code for c in criteria if c.triggered]
    return {
        "benchmark_mode": mode,
        "classification": classify(criteria),
        "triggered_criteria": triggered,
        "blinded_criteria_removed": removed,
        "clinvar_used_as_evidence": clinvar_used,
    }
