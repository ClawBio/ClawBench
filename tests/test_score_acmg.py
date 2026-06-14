"""Tests for score_acmg: deterministic-combine -> classify -> score vs truth.

Scores the V1-analogue arm: label concordance, ACMG criteria-level concordance (which
defeats label memorisation), abstention scoring (abstention is safe, not wrong), and the
lethal-class contrast (a dangerous P<->B miscall vs a safe undercall to VUS).
"""
from __future__ import annotations

import score_acmg as S
from test_evidence_schema import valid_submission


# ---- class normalisation -------------------------------------------------------
def test_normalise_class_variants():
    assert S.normalise_class("VUS") == "Uncertain Significance"
    assert S.normalise_class("Likely pathogenic") == "Likely Pathogenic"
    assert S.normalise_class("P") == "Pathogenic"
    assert S.normalise_class("benign") == "Benign"


# ---- label scoring -------------------------------------------------------------
def test_label_exact_match():
    s = S.label_scores("Pathogenic", "Pathogenic")
    assert s["exact"] is True and s["dangerous_miscall"] is False


def test_dangerous_miscall_p_called_benign():
    s = S.label_scores("Benign", "Pathogenic")
    assert s["exact"] is False
    assert s["dangerous_miscall"] is True


def test_safe_undercall_to_vus():
    s = S.label_scores("Uncertain Significance", "Pathogenic")
    assert s["dangerous_miscall"] is False
    assert s["category"] == "safe_undercall"


def test_concordant_tier_p_vs_lp():
    s = S.label_scores("Likely Pathogenic", "Pathogenic")
    assert s["exact"] is False
    assert s["same_direction"] is True
    assert s["dangerous_miscall"] is False


# ---- criteria-level concordance ------------------------------------------------
def test_criteria_scores():
    s = S.criteria_scores(["PVS1", "PM2"], ["PVS1", "PS1"])
    assert s["precision"] == 0.5
    assert s["recall"] == 0.5
    assert s["f1"] == 0.5
    assert abs(s["jaccard"] - 1 / 3) < 1e-9


def test_criteria_scores_perfect():
    s = S.criteria_scores(["PVS1", "PM2"], ["PM2", "PVS1"])
    assert s["f1"] == 1.0 and s["jaccard"] == 1.0


def test_criteria_scores_empty_reference():
    s = S.criteria_scores([], [])
    assert s["f1"] == 1.0  # nothing to find, nothing asserted -> perfect by convention


# ---- abstention scoring (abstention is safe, not wrong) ------------------------
def test_abstention_correct_when_reference_absent():
    s = S.abstention_scores(["PS3"], ["PVS1"])
    assert s["correct_abstentions"] == 1
    assert s["missed_applicable"] == 0


def test_abstention_missed_when_reference_present():
    s = S.abstention_scores(["PVS1"], ["PVS1"])
    assert s["missed_applicable"] == 1


# ---- per-variant scoring -------------------------------------------------------
def test_score_variant_valid_submission():
    sub = valid_submission(mode="dev", truth=None)
    sub["submitted_evidence_codes"] = [
        {"code": "PVS1", "strength": "very_strong", "source_type": "computational",
         "source_id": "VEP", "rationale": "canonical splice null", "confidence": 0.95},
        {"code": "PM2", "strength": "moderate", "source_type": "population_frequency",
         "source_id": "gnomAD", "rationale": "absent", "confidence": 0.8},
    ]
    sub["abstentions"] = []
    r = S.score_variant(sub, truth_class="Pathogenic", reference_codes=["PVS1", "PM2"])
    assert r["scoreable"] is True
    assert r["predicted_class"] == "Likely Pathogenic"  # PVS1+PM1-class -> LP per combining rules
    assert r["label"]["dangerous_miscall"] is False
    assert r["criteria"]["f1"] == 1.0


def test_score_variant_invalid_submission_is_unscoreable():
    sub = valid_submission()
    sub["submitted_evidence_codes"][0]["confidence"] = 1.5  # invalid
    r = S.score_variant(sub, truth_class="Pathogenic")
    assert r["scoreable"] is False
    assert r["predicted_class"] is None
    assert r["category"] == "invalid"
    assert any(e["error_code"] == "CONFIDENCE_OUT_OF_RANGE" for e in r["validity_errors"])


# ---- aggregation ---------------------------------------------------------------
def test_aggregate_metrics():
    scored = [
        {"scoreable": True, "predicted_class": "Pathogenic", "truth_class": "Pathogenic",
         "label": {"exact": True, "dangerous_miscall": False, "category": "exact"},
         "criteria": {"f1": 1.0}, "abstention": {"abstained": 0}},
        {"scoreable": True, "predicted_class": "Benign", "truth_class": "Pathogenic",
         "label": {"exact": False, "dangerous_miscall": True, "category": "dangerous_miscall"},
         "criteria": {"f1": 0.0}, "abstention": {"abstained": 0}},
        {"scoreable": False, "predicted_class": None, "truth_class": "Pathogenic",
         "label": {}, "criteria": {}, "abstention": {}, "category": "invalid"},
    ]
    agg = S.aggregate(scored)
    assert agg["n"] == 3
    assert agg["n_scoreable"] == 2
    assert agg["exact_accuracy"] == 0.5
    assert agg["dangerous_error_rate"] == 0.5
    assert agg["invalid_rate"] == 1 / 3
    assert abs(agg["mean_criteria_f1"] - 0.5) < 1e-9
