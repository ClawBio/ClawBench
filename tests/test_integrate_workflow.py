"""TDD for HARNESS/integrate_workflow.py: the end-to-end binding of Exp2 (calling) and Exp1
(interpretation).

The integrated paper's unifying claim (hostile review S3.5): a scalar end-to-end accuracy conflates
distinct failure modes across the workflow. This module JOINS each GIAB/ClinVar-overlap variant's
CALLING outcome (TP/FP/FN, genotype match) with its INTERPRETATION attribution (the Exp1
attribute_one flags) into a single end-to-end label that says WHERE in the workflow the failure
originates. Inputs are injected (decoupled from the scorers), so the join is deterministic and
testable before any real VCF exists.

Honest pipeline semantics:
- a variant only REACHES interpretation if it was called correctly (TP, genotype-matching);
- FN (missed) and FP (phantom) are calling-layer outcomes that never reach interpretation;
- a TP with a wrong genotype is a calling error that PROPAGATES into interpretation.
"""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(_ROOT / "HARNESS")]

import integrate_workflow as IW  # noqa: E402


def _interp(*, dangerous=False, safety_clean=True, evidence_insufficient=False,
            assignment_unstable=False, combiner_sensitive=False, truth="Pathogenic", rule_class="Pathogenic"):
    return {"flags": {"dangerous": dangerous, "safety_clean": safety_clean,
                      "evidence_insufficient": evidence_insufficient,
                      "assignment_unstable": assignment_unstable,
                      "combiner_sensitive": combiner_sensitive},
            "truth": truth, "rule_class": rule_class}


# ---- calling-layer outcomes never reach interpretation ----
def test_fn_is_calling_miss():
    r = IW.classify_variant_endtoend({"vcfeval": "FN"}, None)
    assert r["endtoend_label"] == "calling_miss"
    assert r["reached_interpretation"] is False


def test_fp_is_calling_false_positive():
    r = IW.classify_variant_endtoend({"vcfeval": "FP"}, None)
    assert r["endtoend_label"] == "calling_false_positive"
    assert r["reached_interpretation"] is False


def test_absent_calling_record_is_calling_miss():
    r = IW.classify_variant_endtoend(None, _interp())
    assert r["endtoend_label"] == "calling_miss"
    assert r["reached_interpretation"] is False


# ---- a wrong genotype propagates calling error into interpretation ----
def test_tp_genotype_mismatch_is_genotype_propagation():
    r = IW.classify_variant_endtoend({"vcfeval": "TP", "gt_match": False}, _interp())
    assert r["endtoend_label"] == "genotype_propagation"
    assert r["reached_interpretation"] is True


# ---- correctly called variants are attributed to an interpretation layer ----
def test_tp_clean_is_clean():
    r = IW.classify_variant_endtoend({"vcfeval": "TP", "gt_match": True}, _interp())
    assert r["endtoend_label"] == "clean"
    assert r["interpretation_layer"] == "clean"
    assert r["reached_interpretation"] is True


def test_tp_dangerous_is_dangerous_misclass():
    r = IW.classify_variant_endtoend({"vcfeval": "TP", "gt_match": True},
                                     _interp(dangerous=True, safety_clean=False))
    assert r["endtoend_label"] == "dangerous_misclass"
    assert r["interpretation_layer"] == "dangerous"


def test_tp_evidence_insufficient():
    r = IW.classify_variant_endtoend({"vcfeval": "TP", "gt_match": True},
                                     _interp(evidence_insufficient=True))
    assert r["endtoend_label"] == "interpretation_evidence_insufficient"
    assert r["interpretation_layer"] == "evidence_insufficient"


def test_interpretation_layer_priority_order():
    # dangerous > evidence_insufficient > assignment_unstable > combiner_sensitive
    r = IW.classify_variant_endtoend(
        {"vcfeval": "TP", "gt_match": True},
        _interp(assignment_unstable=True, combiner_sensitive=True))
    assert r["interpretation_layer"] == "assignment_unstable"


def test_tp_reached_but_unattributed_when_no_interp():
    r = IW.classify_variant_endtoend({"vcfeval": "TP", "gt_match": True}, None)
    assert r["reached_interpretation"] is True
    assert r["interpretation_layer"] is None
    assert r["endtoend_label"] == "interpretation_unscored"


def test_tp_defaults_gt_match_true_when_absent():
    r = IW.classify_variant_endtoend({"vcfeval": "TP"}, _interp())
    assert r["reached_interpretation"] is True and r["endtoend_label"] == "clean"


# ---- join over the overlap set ----
def test_join_only_scores_overlap_keys():
    calling = {"v1": {"vcfeval": "TP", "gt_match": True}, "v2": {"vcfeval": "FN"},
               "v3": {"vcfeval": "TP", "gt_match": True}}
    interp = {"v1": _interp(), "v3": _interp(evidence_insufficient=True)}
    out = IW.join_workflow(calling, interp, overlap_keys=["v1", "v2"])
    assert out["n_overlap"] == 2
    assert set(out["per_variant"]) == {"v1", "v2"}          # v3 excluded (not in overlap)
    assert out["summary"]["clean"] == 1 and out["summary"]["calling_miss"] == 1
    assert out["reached_interpretation"] == 1


def test_join_decomposes_a_scalar_wrong():
    # THE CONTRIBUTION: three variants all "wrong" under scalar accuracy get THREE different
    # end-to-end attributions, localising the failure to distinct workflow layers.
    calling = {"a": {"vcfeval": "FN"},
               "b": {"vcfeval": "TP", "gt_match": False},
               "c": {"vcfeval": "TP", "gt_match": True}}
    interp = {"b": _interp(), "c": _interp(evidence_insufficient=True)}
    out = IW.join_workflow(calling, interp, overlap_keys=["a", "b", "c"])
    labels = {k: v["endtoend_label"] for k, v in out["per_variant"].items()}
    assert labels == {"a": "calling_miss", "b": "genotype_propagation",
                      "c": "interpretation_evidence_insufficient"}
    assert len(set(labels.values())) == 3


def test_join_shape():
    out = IW.join_workflow({}, {}, overlap_keys=[])
    assert set(out) >= {"per_variant", "summary", "n_overlap", "reached_interpretation"}
    assert out["n_overlap"] == 0
