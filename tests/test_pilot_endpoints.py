"""TDD for the pilot primary endpoints: label/criteria concordance, dangerous-misclass rate,
abstention rate, and between-run variance (the trust signal)."""
from __future__ import annotations

import pilot_endpoints as PE


def rec(model, cond, vid, rep, predicted, truth, dangerous=False, f1=None,
        scoreable=True, format_ok=True, category="exact"):
    return {"model": model, "condition": cond, "variant_id": vid, "rep": rep,
            "scoreable": scoreable, "format_ok": format_ok,
            "predicted_class": predicted, "truth_class": truth,
            "label": {"exact": predicted == truth, "dangerous_miscall": dangerous},
            "criteria": ({"f1": f1} if f1 is not None else {}),
            "category": category}


def _exec_records():
    # execution: identical predictions across 3 reps -> zero variance, perfect agreement
    out = []
    for vid, (pred, truth) in {"V1": ("Pathogenic", "Pathogenic"), "V2": ("Benign", "Benign")}.items():
        for rep in range(3):
            out.append(rec("m", "skill_execution", vid, rep, pred, truth, f1=1.0))
    return out


def _free_records():
    # free: predictions wobble across reps -> nonzero variance, imperfect agreement
    seq = {"V1": ["Pathogenic", "Likely Pathogenic", "Pathogenic"],
           "V2": ["Benign", "Pathogenic", "Benign"]}  # V2 rep1 is a dangerous miscall
    out = []
    for vid, preds in seq.items():
        truth = "Pathogenic" if vid == "V1" else "Benign"
        for rep, p in enumerate(preds):
            out.append(rec("m", "free_prompted", vid, rep, p, truth,
                           dangerous=(p in ("Pathogenic", "Likely Pathogenic")) and truth == "Benign"))
    return out


def test_execution_has_zero_variance_and_full_agreement():
    cells = PE.endpoints_by_cell(_exec_records())
    c = cells[("m", "skill_execution")]
    assert c["replicate_agreement"] == 1.0
    assert c["accuracy_std"] == 0.0
    assert c["label_concordance"] == 1.0
    assert c["criteria_f1"] == 1.0
    assert c["dangerous_rate"] == 0.0


def test_free_has_nonzero_variance_and_a_dangerous_miscall():
    cells = PE.endpoints_by_cell(_free_records())
    c = cells[("m", "free_prompted")]
    assert c["replicate_agreement"] < 1.0          # reps disagree on both variants
    assert c["accuracy_std"] > 0.0
    assert c["dangerous_rate"] > 0.0               # V2 rep1 Benign->Pathogenic


def test_abstention_rate_counts_vus():
    recs = [rec("m", "free_prompted", "V1", r, "Uncertain Significance", "Pathogenic") for r in range(2)]
    recs += [rec("m", "free_prompted", "V2", r, "Pathogenic", "Pathogenic") for r in range(2)]
    c = PE.endpoints_by_cell(recs)[("m", "free_prompted")]
    assert c["abstention_rate"] == 0.5


def test_ratelimit_and_format_fail_excluded_from_scoreable():
    recs = [rec("m", "skill_execution", "V1", 0, "Pathogenic", "Pathogenic"),
            rec("m", "skill_execution", "V1", 1, None, "Pathogenic", scoreable=False,
                format_ok=False, category="ratelimit"),
            rec("m", "skill_execution", "V1", 2, None, "Pathogenic", scoreable=False,
                format_ok=False, category="format_fail")]
    c = PE.endpoints_by_cell(recs)[("m", "skill_execution")]
    assert c["n"] == 3 and c["n_scoreable"] == 1
    assert c["ratelimit_rate"] == 1 / 3
    assert c["format_fail_rate"] == 1 / 3


def test_directional_safety_and_assignment_stability():
    def r(vid, rep, pred, truth, codes, tcm):
        dang = (pred in PE.ACTIONABLE and truth in PE.BENIGN) or (pred in PE.BENIGN and truth in PE.ACTIONABLE)
        return {"model": "m", "condition": "skill_execution", "variant_id": vid, "rep": rep,
                "scoreable": True, "format_ok": True, "predicted_class": pred, "truth_class": truth,
                "label": {"exact": pred == truth, "dangerous_miscall": dang, "three_class_match": tcm},
                "criteria": {}, "category": "x", "proposed_codes": [{"code": c} for c in codes]}
    recs = [r("VB", rep, "Benign", "Benign", ["BA1"], True) for rep in range(3)]      # stable, benign
    recs += [r("VP", 0, "Likely Pathogenic", "Pathogenic", ["PVS1", "PM2"], True),    # actionable, UNSTABLE codes
             r("VP", 1, "Likely Pathogenic", "Pathogenic", ["PVS1"], True),
             r("VP", 2, "Likely Pathogenic", "Pathogenic", ["PVS1", "PM2"], True)]
    c = PE.endpoints_by_cell(recs)[("m", "skill_execution")]
    assert c["benign_concordance"] == 1.0
    assert c["actionable_binary"] == 1.0          # truth-actionable variant placed in actionable (LP)
    assert c["overcall_rate"] == 0.0              # benign variant not over-called
    assert c["three_class_concordance"] == 1.0
    assert c["assignment_set_agreement"] == 0.5   # VB stable, VP not -> 1 of 2
    assert 0 < c["assignment_jaccard"] < 1


def test_render_markdown_has_gradient_table():
    cells = PE.endpoints_by_cell(_exec_records() + _free_records())
    md = PE.render_markdown(cells, title="pilot")
    assert "skill_execution" in md and "free_prompted" in md
    assert "replicate_agreement" in md or "variance" in md.lower()
