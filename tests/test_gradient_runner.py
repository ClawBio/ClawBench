"""TDD for the Exp 1 constraint-gradient runner.

Five conditions over the held-out variants. Conditions 1-3 let the model emit a class
(stochastic); condition 4 (skill-execution) makes the model supply structured evidence that
validate_evidence checks (fail-closed, ClinVar-blinded) and acmg_engine.classify combines
deterministically; condition 5 is the answer-supplied control. The truth label must never
enter a prompt. The model is an injected adapter so the harness is deterministic.
"""
from __future__ import annotations

import json

import gradient_runner as G
from test_evidence_schema import valid_submission


VARIANT = {
    "variant_id": "V1",
    "genomic_context": {"chrom": "17", "pos": 43093454, "ref": "G", "alt": "A",
                        "build": "GRCh38", "gene": "BRCA1", "consequence": "stop_gained"},
    "truth": {"clnsig": "Pathogenic", "review_stars": 3},
}


def test_conditions_constant():
    assert G.CONDITIONS == ["free_prompted", "retrieval_augmented", "skill_reasoning",
                            "skill_execution", "answer_supplied"]


# ---- prompt hygiene: truth must never leak --------------------------------------
def test_prompt_is_independent_of_truth():
    # the real invariant: the prompt cannot depend on the held-out truth value
    v_path = {**VARIANT, "truth": {"clnsig": "Pathogenic", "review_stars": 3}}
    v_benign = {**VARIANT, "truth": {"clnsig": "Benign", "review_stars": 3}}
    for cond in ("free_prompted", "retrieval_augmented", "skill_reasoning", "skill_execution"):
        assert (G.build_prompt(cond, v_path, skill_md="S", retrieved_context="C")
                == G.build_prompt(cond, v_benign, skill_md="S", retrieved_context="C"))


def test_prompt_has_context_not_truth_fields():
    p = G.build_prompt("free_prompted", VARIANT)
    assert "BRCA1" in p          # genomic context the model may see
    assert "clnsig" not in p     # no truth-bearing field
    assert "review_stars" not in p


def test_prompt_includes_condition_specific_material():
    assert "SKILLDOC" in G.build_prompt("skill_reasoning", VARIANT, skill_md="SKILLDOC")
    assert "RETRIEVED" in G.build_prompt("retrieval_augmented", VARIANT, retrieved_context="RETRIEVED")


# ---- output parsing ------------------------------------------------------------
def test_parse_class_valid():
    cls, codes, ok = G.parse_class_output('{"classification": "Likely pathogenic", "evidence_codes": ["PVS1"]}')
    assert ok and cls == "Likely Pathogenic" and codes == ["PVS1"]


def test_parse_class_missing_is_format_fail():
    cls, codes, ok = G.parse_class_output('{"notes": "unsure"}')
    assert ok is False and cls is None


def test_parse_class_garbage_is_format_fail():
    assert G.parse_class_output("not json")[2] is False


# ---- per-condition runs --------------------------------------------------------
def test_free_prompted_run():
    adapter = lambda cond, prompt: '{"classification": "Pathogenic", "evidence_codes": ["PVS1", "PM2"]}'
    r = G.run_one("free_prompted", VARIANT, adapter, reference_codes=["PVS1", "PM2"])
    assert r["scoreable"] and r["predicted_class"] == "Pathogenic"
    assert r["label"]["exact"] is True
    assert r["criteria"]["f1"] == 1.0


def test_format_fail_run():
    adapter = lambda cond, prompt: "I think it is bad"
    r = G.run_one("free_prompted", VARIANT, adapter)
    assert r["format_ok"] is False and r["scoreable"] is False
    assert r["category"] == "format_fail"


def test_skill_execution_valid_submission():
    sub = valid_submission(mode="clinvar_blinded", truth="clinvar")
    sub["variant_id"] = "V1"
    sub["genomic_context"] = VARIANT["genomic_context"]
    adapter = lambda cond, prompt: json.dumps(sub)
    r = G.run_one("skill_execution", VARIANT, adapter, reference_codes=["PM2", "PP3"])
    assert r["scoreable"] is True
    assert r["predicted_class"] in {"Likely Pathogenic", "Uncertain Significance", "Pathogenic"}
    assert "f1" in r["criteria"]


def test_skill_execution_blinding_enforced():
    # a model that tries to use a ClinVar assertion code in blinded mode is rejected by the runner
    sub = valid_submission(mode="clinvar_blinded", truth="clinvar")
    sub["variant_id"] = "V1"
    sub["genomic_context"] = VARIANT["genomic_context"]
    sub["submitted_evidence_codes"].append(
        {"code": "PP5", "strength": "supporting", "source_type": "clinvar",
         "source_id": "VCV1", "rationale": "reputable source pathogenic", "confidence": 0.8})
    adapter = lambda cond, prompt: json.dumps(sub)
    r = G.run_one("skill_execution", VARIANT, adapter)
    assert r["scoreable"] is False and r["category"] == "invalid"
    assert any(e["error_code"] == "DISALLOWED_CLINVAR_CRITERION" for e in r["validity_errors"])


def test_skill_execution_forged_mode_rejected():
    # harness assigns clinvar_blinded; a submission declaring sensitivity mode is rejected
    sub = valid_submission(mode="clinvar_unblinded_sensitivity", truth=None)
    sub["variant_id"] = "V1"
    sub["genomic_context"] = VARIANT["genomic_context"]
    adapter = lambda cond, prompt: json.dumps(sub)
    r = G.run_one("skill_execution", VARIANT, adapter, mode="clinvar_blinded")
    assert r["scoreable"] is False
    assert any(e["error_code"] == "MODE_STATUS_MISMATCH" for e in r["validity_errors"])


def test_answer_supplied_control_is_perfect():
    adapter = lambda cond, prompt: (_ for _ in ()).throw(AssertionError("adapter must not be called"))
    r = G.run_one("answer_supplied", VARIANT, adapter)
    assert r["scoreable"] and r["predicted_class"] == "Pathogenic"
    assert r["label"]["exact"] is True


# ---- grid + summary ------------------------------------------------------------
def test_run_grid_and_summarise():
    v2 = {**VARIANT, "variant_id": "V2", "truth": {"clnsig": "Benign", "review_stars": 2}}
    adapters = {"fake": lambda cond, prompt: '{"classification": "Pathogenic"}'}
    results = G.run_grid([VARIANT, v2], ["free_prompted", "answer_supplied"], adapters)
    assert len(results) == 4  # 2 variants x 2 conditions x 1 model
    summary = G.summarise(results)
    assert set(summary) == {"free_prompted", "answer_supplied"}
    assert summary["answer_supplied"]["exact_accuracy"] == 1.0   # control is perfect
    assert summary["free_prompted"]["exact_accuracy"] == 0.5     # right on V1, wrong on V2
    assert "format_fail_rate" in summary["free_prompted"]
