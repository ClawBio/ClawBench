"""TDD for the ClinVar extractor: variant_summary + submission_summary -> normalised records.

The held-out slice builder needs provable first-availability, which variant_summary.txt cannot
give (no history, no first date). This extractor joins submission_summary (per-submission dates,
classifications, submitters) to derive date_created, history, and submitters, normalises ClinVar's
date formats to strict ISO, and maps ReviewStatus to star levels. Its output is valid input to
build_heldout_clinvar_slice.build_slice.
"""
from __future__ import annotations

import clinvar_extract as X
import build_heldout_clinvar_slice as B


# ---- star mapping --------------------------------------------------------------
def test_review_status_to_stars():
    assert X.review_status_to_stars("practice guideline") == 4
    assert X.review_status_to_stars("reviewed by expert panel") == 3
    assert X.review_status_to_stars("criteria provided, multiple submitters, no conflicts") == 2
    assert X.review_status_to_stars("criteria provided, single submitter") == 1
    assert X.review_status_to_stars("criteria provided, conflicting classifications") == 1
    assert X.review_status_to_stars("no assertion criteria provided") == 0
    assert X.review_status_to_stars("something unknown") == 0


# ---- date normalisation to strict ISO ------------------------------------------
def test_parse_clinvar_date_formats():
    assert X.parse_clinvar_date("2025-09-01") == "2025-09-01"
    assert X.parse_clinvar_date("2025/09/01") == "2025-09-01"
    assert X.parse_clinvar_date("Sep 01, 2025") == "2025-09-01"
    assert X.parse_clinvar_date("Sep 1, 2025") == "2025-09-01"
    assert X.parse_clinvar_date("-") is None
    assert X.parse_clinvar_date("") is None
    assert X.parse_clinvar_date("garbage") is None
    assert X.parse_clinvar_date(None) is None


def test_parsed_dates_accepted_by_slice_builder():
    # the extractor's ISO output must satisfy the slice builder's strict parser
    iso = X.parse_clinvar_date("Sep 01, 2025")
    assert B.parse_date(iso) is not None


# ---- record assembly -----------------------------------------------------------
def _vs(varid="12345", clnsig="Pathogenic", review="reviewed by expert panel", assembly="GRCh38"):
    return {"VariationID": varid, "GeneSymbol": "BRCA1", "ClinicalSignificance": clnsig,
            "LastEvaluated": "2026-03-01", "ReviewStatus": review, "Assembly": assembly,
            "Chromosome": "17", "PositionVCF": "43093454",
            "ReferenceAlleleVCF": "G", "AlternateAlleleVCF": "A"}


def _sub(varid="12345", clnsig="Pathogenic", date="2026-03-01", submitter="LabX"):
    return {"VariationID": varid, "ClinicalSignificance": clnsig, "DateLastEvaluated": date,
            "ReviewStatus": "criteria provided, single submitter", "Submitter": submitter}


def test_build_record_merges_submissions():
    subs = [_sub(date="2024-05-01", clnsig="Uncertain significance", submitter="LabA"),
            _sub(date="2026-03-01", clnsig="Pathogenic", submitter="LabB"),
            _sub(date="2026-03-01", clnsig="Pathogenic", submitter="LabA")]
    r = X.build_record(_vs(), subs)
    assert r["clnsig"] == "Pathogenic"
    assert r["review_stars"] == 3
    assert r["chrom"] == "17" and r["pos"] == 43093454 and r["ref"] == "G" and r["alt"] == "A"
    assert r["build"] == "GRCh38"
    assert r["date_created"] == "2024-05-01"            # earliest submission date
    assert r["submitters"] == ["LabA", "LabB"]          # unique, sorted
    assert r["history"][0] == {"date": "2024-05-01", "clnsig": "Uncertain significance"}
    assert {"date": "2026-03-01", "clnsig": "Pathogenic"} in r["history"]
    assert r["variant_id"] == "VCV000012345"


def test_build_record_no_dated_submissions_leaves_date_created_none():
    subs = [_sub(date="-", clnsig="Pathogenic")]
    r = X.build_record(_vs(), subs)
    assert r["date_created"] is None
    assert r["history"] == []   # undated submissions cannot anchor history


# ---- extract: join + assembly filter -------------------------------------------
def test_extract_joins_and_filters_assembly():
    vs_rows = [_vs(varid="1"), _vs(varid="2", assembly="GRCh37")]
    sub_rows = [_sub(varid="1", date="2026-01-01"), _sub(varid="2", date="2026-01-01")]
    recs = X.extract(vs_rows, sub_rows, assembly="GRCh38")
    ids = {r["variant_id"] for r in recs}
    assert ids == {"VCV000000001"}     # GRCh37 row excluded


def test_extract_output_feeds_slice_builder():
    vs_rows = [_vs(varid="7", clnsig="Pathogenic")]
    sub_rows = [_sub(varid="7", date="2026-02-01", clnsig="Pathogenic")]
    recs = X.extract(vs_rows, sub_rows, assembly="GRCh38")
    m = B.build_slice(recs, {"model": "2025-01-01"}, min_stars=2, safety_margin_days=0,
                      build_date="t")
    assert m["counts"]["held_out"] == 1
    assert m["variants"][0]["truth"]["clnsig"] == "Pathogenic"
