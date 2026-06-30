"""TDD for HARNESS/pathogenic_integration.py: pathogenic end-to-end attribution (execution-light).

GIAB genomes are benign-dominated, so the call-and-interpret overlap had no pathogenic cases. This
module selects pathogenic / likely-pathogenic held-out variants, takes their REAL interpretation
attribution (from an Exp1 skill_execution run), and overlays a CONTROLLED calling outcome (default:
correct call, since the qualified control arm calls GIAB truth at ~0.99; optional injected FN /
genotype-mismatch to exercise the cross-layer labels), then joins via integrate_workflow. The calling
overlay is a labelled positive control, NOT a measurement of caller performance on pathogenic variants.
"""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(_ROOT / "HARNESS"), str(_ROOT / "SKILLS" / "clinical-variant-reporter")]

import pathogenic_integration as PI  # noqa: E402

TIER_A = [
    {"variant_id": "V1", "clnsig": "Pathogenic"},
    {"variant_id": "V2", "clnsig": "Likely Pathogenic"},
    {"variant_id": "V3", "clnsig": "Benign"},
]


def _rec(vid, predicted, truth, rep, codes=None):
    return {"condition": "skill_execution", "variant_id": vid, "model": "m", "rep": rep,
            "scoreable": True, "predicted_class": predicted, "truth_class": truth,
            "proposed_codes": codes or []}


def test_selects_only_pathogenic():
    assert PI.pathogenic_variant_ids(TIER_A) == {"V1", "V2"}


def test_calling_overlay_defaults_to_correct_call():
    ov = PI.calling_overlay({"V1", "V2"})
    assert ov["V1"] == {"vcfeval": "TP", "gt_match": True}


def test_calling_overlay_injects_failures():
    ov = PI.calling_overlay({"V1", "V2"}, fn_ids={"V2"})
    assert ov["V2"] == {"vcfeval": "FN"}
    ov2 = PI.calling_overlay({"V1"}, gt_mismatch_ids={"V1"})
    assert ov2["V1"] == {"vcfeval": "TP", "gt_match": False}


def test_dangerous_pathogenic_miscall_is_dangerous_misclass():
    # V1 is truth=Pathogenic but interpreted Benign across reps -> dangerous; correctly called (TP)
    interp = [_rec("V1", "Benign", "Pathogenic", 0), _rec("V1", "Benign", "Pathogenic", 1)]
    out = PI.pathogenic_integration(TIER_A, interp)
    assert out["per_variant"]["V1"]["endtoend_label"] == "dangerous_misclass"


def test_called_miss_overrides_interpretation():
    # V2 interpreted fine, but injected as a calling FN -> calling_miss (never reaches interpretation)
    interp = [_rec("V2", "Likely Pathogenic", "Likely Pathogenic", 0),
              _rec("V2", "Likely Pathogenic", "Likely Pathogenic", 1)]
    out = PI.pathogenic_integration(TIER_A, interp, fn_ids={"V2"})
    assert out["per_variant"]["V2"]["endtoend_label"] == "calling_miss"


def test_only_pathogenic_variants_appear():
    interp = [_rec("V1", "Pathogenic", "Pathogenic", 0), _rec("V3", "Benign", "Benign", 0)]
    out = PI.pathogenic_integration(TIER_A, interp)
    assert set(out["per_variant"]) <= {"V1", "V2"}     # V3 (benign) excluded
    assert "V3" not in out["per_variant"]


def test_summary_counts_labels():
    interp = [_rec("V1", "Benign", "Pathogenic", 0), _rec("V1", "Benign", "Pathogenic", 1),
              _rec("V2", "Likely Pathogenic", "Likely Pathogenic", 0),
              _rec("V2", "Likely Pathogenic", "Likely Pathogenic", 1)]
    out = PI.pathogenic_integration(TIER_A, interp, fn_ids={"V2"})
    assert out["summary"]["dangerous_misclass"] == 1
    assert out["summary"]["calling_miss"] == 1
