"""TDD for the acquisition-arm analysis (layer-category assignment + A->B transitions).

The primary endpoint is the change in per-variant layer attribution between the thin (Condition A)
and enriched (Condition B) arms, in particular whether the evidence_insufficient layer shrinks.
attribute_one (tested separately) produces the flags; here we collapse flags to one ordered layer
category per (variant, arm) and tabulate the thin->enriched transitions.
"""
from __future__ import annotations

import analyze_acquisition as AZ


def _att(truth, *, points_class, safety_clean=True, evidence_insufficient=False,
         combiner_sensitive=False, assignment_unstable=False):
    return {"truth": truth, "rule_class": points_class, "points_class": points_class,
            "flags": {"safety_clean": safety_clean, "dangerous": not safety_clean,
                      "evidence_insufficient": evidence_insufficient,
                      "combiner_sensitive": combiner_sensitive,
                      "assignment_unstable": assignment_unstable}}


def test_category_precedence():
    assert AZ.attribution_category(_att("Pathogenic", points_class="Uncertain Significance",
                                        evidence_insufficient=True)) == "evidence_insufficient"
    assert AZ.attribution_category(_att("Pathogenic", points_class="Pathogenic",
                                        safety_clean=False)) == "dangerous"
    # resolved: definitive truth reached a definitive points class, not flagged insufficient
    assert AZ.attribution_category(_att("Pathogenic", points_class="Likely Pathogenic")) == "resolved"
    # combiner-sensitivity ranks above assignment instability
    assert AZ.attribution_category(_att("Pathogenic", points_class="Likely Pathogenic",
                                        combiner_sensitive=True)) == "combiner_sensitive"
    assert AZ.attribution_category(_att("Pathogenic", points_class="Likely Pathogenic",
                                        assignment_unstable=True)) == "assignment_unstable"


def test_vus_controls_categorised_separately():
    assert AZ.attribution_category(_att("Uncertain Significance",
                                        points_class="Uncertain Significance")) == "vus_correct"
    assert AZ.attribution_category(_att("Uncertain Significance",
                                        points_class="Likely Pathogenic")) == "vus_overcall"


def test_transition_matrix_counts_pairs():
    pairs = [("evidence_insufficient", "resolved"),
             ("evidence_insufficient", "resolved"),
             ("evidence_insufficient", "evidence_insufficient"),
             ("evidence_insufficient", "assignment_unstable")]
    m = AZ.transition_matrix(pairs)
    assert m[("evidence_insufficient", "resolved")] == 2
    assert m[("evidence_insufficient", "evidence_insufficient")] == 1
    assert m[("evidence_insufficient", "assignment_unstable")] == 1


def _ev(af, revel_acmg):
    return {"population_max_af": af, "in_silico": {"revel_acmg": revel_acmg}}


def test_ceiling_pathogenic_needs_pp3_strong_to_reach_lp():
    # PM2 moderate (2) + PP3 strong (4) = 6 -> Likely Pathogenic (resolvable)
    assert AZ.ceiling_points_class(_ev(3e-5, {"code": "PP3", "strength": "strong"})) == "Likely Pathogenic"
    # PM2 moderate (2) + PP3 moderate (2) = 4 -> still VUS (not resolvable on non-ClinVar evidence)
    assert AZ.ceiling_points_class(_ev(None, {"code": "PP3", "strength": "moderate"})) == "Uncertain Significance"


def test_ceiling_benign_bp4_alone_reaches_lb_without_contradictory_pm2():
    # BP4 supporting (-1) alone -> Likely Benign; an ideal agent does NOT add PM2 against a benign signal
    assert AZ.ceiling_points_class(_ev(1e-5, {"code": "BP4", "strength": "supporting"})) == "Likely Benign"


def test_ceiling_indeterminate_stays_vus():
    assert AZ.ceiling_points_class(_ev(1e-5, None)) == "Uncertain Significance"


def test_resolution_rate_on_evidence_insufficient():
    # of definitive variants that were evidence_insufficient under thin, fraction no longer so under enriched
    pairs = [("evidence_insufficient", "resolved"),
             ("evidence_insufficient", "evidence_insufficient"),
             ("evidence_insufficient", "assignment_unstable"),
             ("resolved", "resolved")]  # not ei under thin -> excluded from denominator
    res = AZ.resolution_rate(pairs)
    assert res["n_thin_ei"] == 3
    assert res["n_resolved"] == 2  # left evidence_insufficient (->resolved and ->assignment_unstable)
    assert abs(res["rate"] - 2 / 3) < 1e-9
