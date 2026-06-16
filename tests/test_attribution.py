"""TDD for per-variant layer attribution.

Converts model performance into layer attribution per (variant, model) from skill_execution replicates:
- safety_clean        : no dangerous Pathogenic<->Benign miscall across reps
- combiner_sensitive  : the modal class differs between the Richards rule combiner and Tavtigian points
- assignment_unstable : the model's proposed code SETS differ across replicates
- evidence_insufficient: truth is definitive but even the points combiner yields VUS
"""
from __future__ import annotations

import attribution as A


def _rec(vid, model, rep, pred, truth, codes):
    return {"variant_id": vid, "model": model, "condition": "skill_execution", "rep": rep,
            "scoreable": True, "predicted_class": pred, "truth_class": truth,
            "proposed_codes": [{"code": c, "strength": s} for c, s in codes]}


def test_combiner_sensitive_lof():
    # rule caps PVS1+PM2 at LP; points = 10 = Pathogenic -> combiner-sensitive, evidence sufficient
    recs = [_rec("V1", "m", r, "Likely Pathogenic", "Pathogenic",
                 [("PVS1", "very_strong"), ("PM2", "moderate")]) for r in range(3)]
    a = A.attribute_one(recs)
    assert a["rule_class"] == "Likely Pathogenic" and a["points_class"] == "Pathogenic"
    assert a["flags"]["combiner_sensitive"] is True
    assert a["flags"]["evidence_insufficient"] is False
    assert a["flags"]["assignment_unstable"] is False
    assert a["flags"]["safety_clean"] is True


def test_not_combiner_sensitive_when_both_agree():
    recs = [_rec("V2", "m", r, "Benign", "Benign", [("BA1", "stand_alone")]) for r in range(3)]
    a = A.attribute_one(recs)
    assert a["flags"]["combiner_sensitive"] is False


def test_assignment_unstable():
    recs = [_rec("V3", "m", 0, "Likely Pathogenic", "Pathogenic", [("PVS1", "very_strong"), ("PM2", "moderate")]),
            _rec("V3", "m", 1, "Likely Pathogenic", "Pathogenic", [("PVS1", "very_strong")]),
            _rec("V3", "m", 2, "Likely Pathogenic", "Pathogenic", [("PVS1", "very_strong"), ("PM2", "moderate")])]
    a = A.attribute_one(recs)
    assert a["flags"]["assignment_unstable"] is True


def test_evidence_insufficient():
    # truth Pathogenic but model only assigns PM2 (2 points) -> points = VUS -> insufficient
    recs = [_rec("V4", "m", r, "Uncertain Significance", "Pathogenic", [("PM2", "moderate")]) for r in range(3)]
    a = A.attribute_one(recs)
    assert a["points_class"] == "Uncertain Significance"
    assert a["flags"]["evidence_insufficient"] is True


def test_dangerous_not_safety_clean():
    recs = [_rec("V5", "m", 0, "Pathogenic", "Benign", [("PVS1", "very_strong")]),
            _rec("V5", "m", 1, "Benign", "Benign", [("BA1", "stand_alone")])]
    a = A.attribute_one(recs)
    assert a["flags"]["dangerous"] is True and a["flags"]["safety_clean"] is False


def test_attribute_and_breadth():
    recs = []
    recs += [_rec("L1", "m", r, "Likely Pathogenic", "Pathogenic", [("PVS1", "very_strong"), ("PM2", "moderate")]) for r in range(3)]
    recs += [_rec("M1", "m", r, "Uncertain Significance", "Uncertain Significance", [("PM2", "moderate")]) for r in range(3)]
    meta = {"L1": {"tier": "A", "consequence": "frameshift_variant"},
            "M1": {"tier": "B", "consequence": "missense_variant"}}
    atts = A.attribute(recs, meta)
    assert len(atts) == 2
    br = A.breadth(atts, "consequence", "combiner_sensitive")
    assert br["frameshift_variant"][2] == 1.0    # LoF combiner-sensitive
    assert br["missense_variant"][2] == 0.0       # missense (VUS==VUS) not combiner-sensitive here
