"""TDD for HARNESS/vcfeval_scorer.py: a reproducible, auditable rtg vcfeval scoring path.

The qualification scored F1 ad-hoc; the benchmark objective requires scoring be reproducible and
auditable, so the command builder and the summary parser are pure and tested here. The subprocess call
runs on the Studio and is not unit-tested.
"""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(_ROOT / "HARNESS")]

import vcfeval_scorer as VS  # noqa: E402

# An rtg vcfeval summary.txt (whitespace-aligned), matching the HG002 chr20 qualification numbers.
SUMMARY = """Threshold  True-pos-baseline  True-pos-call  False-pos  False-neg  Precision  Sensitivity  F-measure
   30.000              81720          81720        612        869     0.9926       0.9895     0.9910
    None              81835          81835        807        754     0.9902       0.9909     0.9906
"""


def test_command_is_pinned_and_confined():
    cmd = VS.vcfeval_command(truth="truth.vcf.gz", query="q.vcf.gz", bed="conf.bed",
                             sdf="GRCh38.sdf", out_dir="/sbox/vcfeval", rtg="rtg")
    assert cmd[:2] == ["rtg", "vcfeval"]
    j = " ".join(cmd)
    assert "--baseline=truth.vcf.gz" in j or "-b" in cmd
    assert "--calls=q.vcf.gz" in j or "-c" in cmd
    assert "GRCh38.sdf" in j and "conf.bed" in j and "/sbox/vcfeval" in j


def test_parse_none_row_is_default_headline():
    r = VS.parse_vcfeval_summary(SUMMARY)
    assert r["precision"] == 0.9902
    assert r["recall"] == 0.9909
    assert r["f1"] == 0.9906
    assert r["fp"] == 807 and r["fn"] == 754 and r["tp"] == 81835


def test_parse_can_select_threshold_row():
    r = VS.parse_vcfeval_summary(SUMMARY, row="30.000")
    assert r["f1"] == 0.9910 and r["fp"] == 612


def test_parse_missing_row_returns_none():
    assert VS.parse_vcfeval_summary(SUMMARY, row="99.9") is None


def test_parse_empty_is_none():
    assert VS.parse_vcfeval_summary("") is None


def test_f1_consistent_with_precision_recall():
    r = VS.parse_vcfeval_summary(SUMMARY)
    p, rec = r["precision"], r["recall"]
    f1 = 2 * p * rec / (p + rec)
    assert abs(f1 - r["f1"]) < 0.001
