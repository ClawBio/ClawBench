"""TDD for HARNESS/equity_walkback.py: the honest per-ancestry recompute (hostile review S3.3).

The published F1-invariance claim hides a precision / false-positive-rate gradient. This module pools
counts within an ancestry and reports precision, recall, F1, AND fp-per-TP with Wilson CIs, plus the
per-metric spread, so the claim can be restricted to what the data supports.
"""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(_ROOT / "HARNESS")]

import equity_walkback as EW  # noqa: E402

# the chr20 ancestry table (HG001 EUR, HG002/HG003 AJ, HG005 EAS)
ROWS = [
    {"sample": "HG001", "ancestry": "EUR", "TP": 78513, "FP": 825, "FN": 636},
    {"sample": "HG002", "ancestry": "AJ", "TP": 81835, "FP": 807, "FN": 754},
    {"sample": "HG003", "ancestry": "AJ", "TP": 80200, "FP": 946, "FN": 594},
    {"sample": "HG005", "ancestry": "EAS", "TP": 76592, "FP": 1063, "FN": 432},
]


def test_per_ancestry_pools_counts():
    pa = EW.per_ancestry(ROWS)
    assert set(pa) == {"EUR", "AJ", "EAS"}
    # AJ pools HG002+HG003
    assert pa["AJ"]["TP"] == 81835 + 80200
    assert pa["AJ"]["FP"] == 807 + 946


def test_fp_per_tp_gradient_disfavours_eas():
    pa = EW.per_ancestry(ROWS)
    assert abs(pa["EAS"]["fp_per_tp"] - 0.01388) < 1e-4
    assert abs(pa["EUR"]["fp_per_tp"] - 0.01051) < 1e-4
    # the documented gradient: EAS has the highest false-positive burden
    assert pa["EAS"]["fp_per_tp"] > pa["AJ"]["fp_per_tp"] > pa["EUR"]["fp_per_tp"]


def test_precision_recall_f1_values():
    pa = EW.per_ancestry(ROWS)
    assert abs(pa["EAS"]["precision"] - 0.98631) < 1e-4
    assert abs(pa["EAS"]["recall"] - 0.99439) < 1e-4
    assert abs(pa["EUR"]["precision"] - 0.98960) < 1e-4


def test_f1_spread_hides_precision_spread():
    # THE central point: F1 looks invariant, precision and fp-rate do not.
    pa = EW.per_ancestry(ROWS)
    f1_spread = EW.metric_spread(pa, "f1")
    prec_spread = EW.metric_spread(pa, "precision")
    fppt_spread = EW.metric_spread(pa, "fp_per_tp")
    assert f1_spread < 0.001
    assert prec_spread > 0.003
    assert prec_spread > 5 * f1_spread          # precision spread is many times the F1 spread
    assert fppt_spread > 5 * f1_spread


def test_worst_ancestry_by_metric():
    pa = EW.per_ancestry(ROWS)
    assert EW.worst(pa, "precision") == "EAS"
    assert EW.worst(pa, "fp_per_tp") == "EAS"   # highest fp_per_tp is worst


def test_wilson_ci_brackets_point_estimate():
    lo, hi = EW.wilson_ci(76592, 76592 + 1063)   # EAS precision
    assert lo < 0.98631 < hi
    assert 0.0 <= lo < hi <= 1.0


def test_claim_is_restricted_and_honest():
    pa = EW.per_ancestry(ROWS)
    claim = EW.honest_claim(pa)
    low = claim.lower()
    assert "three giab ancestries" in low or "three ancestries" in low
    assert "precision" in low or "false-positive" in low or "false positive" in low
    # must NOT assert blanket ancestry-invariance
    assert "ancestry-invariant" not in low and "ancestry invariant" not in low
