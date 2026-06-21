"""TDD for GA4GH-stratified scoring (Exp 2).

hap.py with --stratification emits an extended.csv with one row per (Type, Subset). We parse it into
per-stratum metrics and expose the GA4GH difficulty strata that matter for variant calling
(low-complexity, segmental duplications, MHC, homopolymers), where callers typically lose accuracy.
"""
from __future__ import annotations

import stratified_scorer as ST


_EXTENDED_CSV = """Type,Subset,Subset.Size,Subset.IS_CONF.Size,METRIC.Recall,METRIC.Precision,METRIC.F1_Score
SNP,*,3200000000,2800000000,0.9900,0.9950,0.9925
SNP,GRCh38_notinalllowmappabilityandsegdupregions,2700000000,2500000000,0.9970,0.9980,0.9975
SNP,GRCh38_AllTandemRepeatsandHomopolymers_slop5,120000000,90000000,0.8200,0.8600,0.8395
SNP,GRCh38_segdups,90000000,60000000,0.7400,0.8100,0.7734
SNP,GRCh38_MHC,5000000,4800000,0.9100,0.9300,0.9199
INDEL,*,3200000000,2800000000,0.9200,0.9400,0.9299
INDEL,GRCh38_AllTandemRepeatsandHomopolymers_slop5,120000000,90000000,0.6300,0.7000,0.6632
"""


def test_parse_extended_indexes_by_type_and_subset():
    m = ST.parse_happy_extended(_EXTENDED_CSV)
    assert ("SNP", "GRCh38_segdups") in m
    assert abs(m[("SNP", "GRCh38_segdups")]["f1"] - 0.7734) < 1e-6
    assert m[("SNP", "GRCh38_segdups")]["size"] == 90000000


def test_difficulty_strata_filter_matches_ga4gh_categories():
    m = ST.parse_happy_extended(_EXTENDED_CSV)
    strat = ST.difficulty_strata(m, "SNP")
    keys = set(strat)
    # homopolymer/tandem-repeat, segdup and MHC strata are surfaced; the genome-wide '*' is excluded
    assert any("Homopolymer" in k or "TandemRepeats" in k for k in keys)
    assert any("segdup" in k for k in keys)
    assert any("MHC" in k for k in keys)
    assert "*" not in keys


def test_hardest_stratum_is_reported():
    m = ST.parse_happy_extended(_EXTENDED_CSV)
    name, metrics = ST.hardest_stratum(m, "SNP")
    assert name == "GRCh38_segdups"            # lowest F1 among SNP difficulty strata
    assert metrics["f1"] < 0.78


def test_easy_vs_hard_gap():
    m = ST.parse_happy_extended(_EXTENDED_CSV)
    gap = ST.easy_hard_gap(m, "SNP")
    # genome-wide F1 minus hardest-stratum F1 (0.9925 - 0.7734)
    assert abs(gap - (0.9925 - 0.7734)) < 1e-6
