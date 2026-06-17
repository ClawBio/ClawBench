"""TDD for the acquisition-arm run harness (task building + resumability).

Paired design: every probe variant is run under skill_execution in BOTH arms — thin (Condition A,
consequence+AF) and enriched (Condition B, oracle evidence) — for the same model and rep range, so
the only difference between arms is the evidence payload. The live model call is exercised by the
smoke run; here we lock the deterministic task set + checkpoint dedup.
"""
from __future__ import annotations

import run_acquisition_probe as R


def _thin():
    return [{"variant_id": "V1", "evidence_context": {"molecular_consequence": "missense_variant",
                                                      "population_max_af": None}},
            {"variant_id": "V2", "evidence_context": {"molecular_consequence": "missense_variant",
                                                      "population_max_af": 1e-5}}]


def _enriched():
    return [{"variant_id": "V1", "evidence_context": {"molecular_consequence": "missense_variant",
                                                      "population_max_af": None, "in_silico": {"revel": 0.9}}},
            {"variant_id": "V2", "evidence_context": {"molecular_consequence": "missense_variant",
                                                      "population_max_af": 1e-5, "in_silico": {"revel": 0.1}}}]


def test_build_tasks_covers_both_arms_all_reps():
    tasks = R.build_tasks(_thin(), _enriched(), reps=3, done=set(), model="m")
    # 2 variants x 2 arms x 3 reps = 12
    assert len(tasks) == 12
    arms = {t[0] for t in tasks}
    assert arms == {"thin", "enriched"}
    # enriched tasks carry the in_silico payload; thin do not
    enr = [t for t in tasks if t[0] == "enriched"]
    assert all("in_silico" in t[1]["evidence_context"] for t in enr)
    thin = [t for t in tasks if t[0] == "thin"]
    assert all("in_silico" not in t[1]["evidence_context"] for t in thin)


def test_build_tasks_skips_done():
    done = {R.task_key("m", "V1", "thin", 0), R.task_key("m", "V2", "enriched", 2)}
    tasks = R.build_tasks(_thin(), _enriched(), reps=3, done=done, model="m")
    assert len(tasks) == 10
    keys = {R.task_key("m", t[1]["variant_id"], t[0], t[2]) for t in tasks}
    assert R.task_key("m", "V1", "thin", 0) not in keys
    assert R.task_key("m", "V2", "enriched", 2) not in keys


def test_task_key_distinguishes_arm():
    assert R.task_key("m", "V1", "thin", 0) != R.task_key("m", "V1", "enriched", 0)
    assert R.task_key("m", "V1", "calibrated", 0) != R.task_key("m", "V1", "enriched", 0)


def test_calibrated_arm_adds_pm2_note_without_mutating_input():
    enr = _enriched()[0]
    cal = R.calibrated_evidence_context(enr)
    assert "pm2_strength_note" in cal["evidence_context"]
    assert "moderate" in cal["evidence_context"]["pm2_strength_note"].lower()
    # the enriched in-silico evidence is preserved
    assert "in_silico" in cal["evidence_context"]
    # input not mutated
    assert "pm2_strength_note" not in enr["evidence_context"]


def test_build_tasks_includes_calibrated_arm_when_provided():
    tasks = R.build_tasks(_thin(), _enriched(), reps=2, done=set(), model="m",
                          calibrated_variants=[R.calibrated_evidence_context(v) for v in _enriched()])
    # 2 variants x 3 arms x 2 reps = 12
    assert len(tasks) == 12
    assert {t[0] for t in tasks} == {"thin", "enriched", "calibrated"}
    cal = [t for t in tasks if t[0] == "calibrated"]
    assert all("pm2_strength_note" in t[1]["evidence_context"] for t in cal)


def test_build_tasks_raises_on_variant_set_mismatch():
    thin = _thin()
    enriched = _enriched()[:1]  # missing V2
    try:
        R.build_tasks(thin, enriched, reps=1, done=set(), model="m")
        assert False, "expected mismatch to raise"
    except ValueError as e:
        assert "V2" in str(e)
