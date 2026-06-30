"""TDD for HARNESS/recalibrate_consistent.py: PM2-strength isolated within one convention frame."""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(_ROOT / "HARNESS")]

import recalibrate_consistent as RC  # noqa: E402


def test_rescore_overrides_only_pm2():
    codes = [{"code": "PM2", "strength": "supporting"}, {"code": "PP3", "strength": "strong"}]
    # PP3 strong (+4) + PM2 supporting (+1) = +5 -> VUS; PM2 moderate (+2) -> +6 -> Likely Pathogenic
    assert RC.rescore(codes, "supporting") == "Uncertain Significance"
    assert RC.rescore(codes, "moderate") == "Likely Pathogenic"
    # PP3 strength untouched by the override
    assert codes[1]["strength"] == "strong"


def test_pathogenic_recovers_benign_regresses_direction_coupled():
    # one pathogenic-side variant (PM2+PP3 strong) and one benign-side (PM2+BP4 moderate), 1 rep each
    rows = [
        {"arm": "enriched", "variant_id": "P1", "truth_class": "Pathogenic",
         "proposed_codes": [{"code": "PM2", "strength": "supporting"}, {"code": "PP3", "strength": "strong"}]},
        {"arm": "enriched", "variant_id": "B1", "truth_class": "Benign",
         "proposed_codes": [{"code": "PM2", "strength": "supporting"}, {"code": "BP4", "strength": "moderate"}]},
    ]
    out = RC.analyze(rows)
    assert out["n_definitive"] == 2
    assert out["recover_pathogenic"] == 1     # PM2->moderate rescues the pathogenic variant
    assert out["regress_benign"] == 1         # PM2->moderate breaks the benign variant
    assert out["recover_benign"] == 0 and out["regress_pathogenic"] == 0


def test_ignores_non_enriched_arm_and_vus_controls():
    rows = [
        {"arm": "thin", "variant_id": "P1", "truth_class": "Pathogenic", "proposed_codes": []},
        {"arm": "enriched", "variant_id": "V1", "truth_class": "Uncertain Significance",
         "proposed_codes": [{"code": "PM2", "strength": "supporting"}]},
    ]
    out = RC.analyze(rows)
    assert out["n_definitive"] == 0           # thin arm skipped, VUS control not definitive
