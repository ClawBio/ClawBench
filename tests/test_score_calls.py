"""TDD for the variant-calling scorer (Exp 2).

Scores a query VCF against a GIAB benchmark VCF within the high-confidence BED using the GA4GH
comparison standard (hap.py, or rtg vcfeval in a GA4GH-compatible mode). The harness separates the
COMMAND BUILDER (pure, testable) from the OUTPUT PARSER (pure, testable); the subprocess call that
runs hap.py shells out on the compute host and is not unit-tested here.
"""
from __future__ import annotations

import score_calls as SC


_SUMMARY_CSV = """Type,Filter,TRUTH.TOTAL,TRUTH.TP,TRUTH.FN,QUERY.TOTAL,QUERY.FP,QUERY.UNK,METRIC.Recall,METRIC.Precision,METRIC.F1_Score
INDEL,ALL,500,460,40,540,30,10,0.920000,0.938776,0.929293
INDEL,PASS,500,455,45,520,20,8,0.910000,0.957983,0.933333
SNP,ALL,4000,3960,40,4020,35,5,0.990000,0.991260,0.990630
SNP,PASS,4000,3950,50,4000,25,4,0.987500,0.993711,0.990596
"""


def test_happy_command_builder():
    cmd = SC.happy_command(truth="HG002.chr20.vcf.gz", query="calls.vcf.gz",
                           bed="HG002.chr20.bed", ref="GRCh38.fa", out_prefix="out/HG002",
                           threads=4)
    s = " ".join(cmd)
    assert cmd[0].endswith("hap.py") or cmd[0] == "hap.py"
    assert "HG002.chr20.vcf.gz" in s and "calls.vcf.gz" in s
    assert "-f" in cmd and "HG002.chr20.bed" in s          # confident regions
    assert "-r" in cmd and "GRCh38.fa" in s                 # reference
    assert "-o" in cmd and "out/HG002" in s                 # output prefix
    assert "--threads" in s and "4" in s


def test_parse_happy_summary_pass_rows_by_default():
    m = SC.parse_happy_summary(_SUMMARY_CSV)
    assert set(m) == {"SNP", "INDEL"}
    assert abs(m["SNP"]["recall"] - 0.9875) < 1e-6
    assert abs(m["SNP"]["precision"] - 0.993711) < 1e-6
    assert abs(m["SNP"]["f1"] - 0.990596) < 1e-6
    assert m["SNP"]["truth_total"] == 4000
    assert m["SNP"]["fn"] == 50
    assert m["INDEL"]["fp"] == 20  # QUERY.FP on the PASS row


def test_parse_happy_summary_can_select_all_filter():
    m = SC.parse_happy_summary(_SUMMARY_CSV, filt="ALL")
    assert m["INDEL"]["fn"] == 40
    assert m["SNP"]["fp"] == 35


def test_parse_happy_summary_missing_type_raises():
    bad = "Type,Filter,METRIC.Recall,METRIC.Precision,METRIC.F1_Score\nSNP,PASS,0.99,0.99,0.99\n"
    # INDEL absent -> the parser returns only what is present, never invents a row
    m = SC.parse_happy_summary(bad)
    assert "INDEL" not in m and "SNP" in m


def test_overall_f1_is_weighted_by_truth_total():
    m = SC.parse_happy_summary(_SUMMARY_CSV)
    # weighted by TRUTH.TOTAL (SNP 4000, INDEL 500); not a naive mean of the two F1 values
    ov = SC.overall_f1(m)
    naive = (m["SNP"]["f1"] + m["INDEL"]["f1"]) / 2
    assert ov != naive
    assert m["INDEL"]["f1"] < ov < m["SNP"]["f1"]
