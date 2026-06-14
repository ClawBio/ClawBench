"""TDD for the held-out ClinVar slice builder (temporal blinding for Exp 1).

Core claim protected: the model cannot have learned the benchmark label during pretraining
(temporal: label first available AFTER the latest model cutoff), and the executing skill cannot
read it during inference (handled separately by validate_evidence blinding). Fail closed on any
variant whose label date is missing/ambiguous or whose current label predates the cutoff.
"""
from __future__ import annotations

import datetime as dt

import build_heldout_clinvar_slice as B


CUTOFFS = {"model_a": "2024-01-01", "model_b": "2024-06-01"}


def rec(vid, clnsig, stars, date, history=None, gene="BRCA1"):
    return {
        "variant_id": vid, "chrom": "17", "pos": 43045712, "ref": "C", "alt": "T",
        "build": "GRCh38", "gene": gene,
        "clnsig": clnsig, "review_stars": stars, "date_last_evaluated": date,
        "submitters": ["LabX"], "history": history or [],
    }


# ---- cutoff + date primitives --------------------------------------------------
def test_effective_cutoff_is_latest_plus_margin():
    assert B.effective_cutoff(CUTOFFS, safety_margin_days=0) == dt.date(2024, 6, 1)
    assert B.effective_cutoff(CUTOFFS, safety_margin_days=30) == dt.date(2024, 7, 1)


def test_empty_cutoffs_fail_closed():
    import pytest
    with pytest.raises(ValueError):
        B.effective_cutoff({}, safety_margin_days=0)


def test_parse_date_strict():
    assert B.parse_date("2024-06-01") == dt.date(2024, 6, 1)
    assert B.parse_date("2024-06") is None      # partial -> ambiguous
    assert B.parse_date("2024") is None
    assert B.parse_date("") is None
    assert B.parse_date("garbage") is None
    assert B.parse_date(None) is None


# ---- admission rules -----------------------------------------------------------
def _build(records, **kw):
    return B.build_slice(records, CUTOFFS, safety_margin_days=0, build_date="2026-06-14", **kw)


def test_post_cutoff_two_star_admitted():
    m = _build([rec("V1", "Pathogenic", 2, "2025-01-01")])
    ids = {v["variant_id"] for v in m["variants"]}
    assert "V1" in ids
    assert m["counts"]["held_out"] == 1


def test_pre_cutoff_excluded():
    m = _build([rec("V2", "Pathogenic", 3, "2024-01-01")])  # before 2024-06-01 cutoff
    assert m["counts"]["held_out"] == 0
    assert m["counts"]["excluded"]["pre_cutoff"] == 1


def test_low_stars_excluded():
    m = _build([rec("V3", "Pathogenic", 1, "2025-01-01")])
    assert m["counts"]["held_out"] == 0
    assert m["counts"]["excluded"]["below_min_stars"] == 1


def test_unusable_clnsig_excluded():
    m = _build([rec("V4", "Conflicting interpretations of pathogenicity", 2, "2025-01-01")])
    assert m["counts"]["held_out"] == 0
    assert m["counts"]["excluded"]["unusable_label"] == 1


def test_missing_date_fail_closed():
    m = _build([rec("V5", "Pathogenic", 3, None)])
    assert m["counts"]["held_out"] == 0
    assert m["counts"]["excluded"]["missing_or_ambiguous_date"] == 1


def test_ambiguous_partial_date_fail_closed():
    m = _build([rec("V5b", "Pathogenic", 3, "2025-09")])
    assert m["counts"]["held_out"] == 0
    assert m["counts"]["excluded"]["missing_or_ambiguous_date"] == 1


# ---- reclassification / discordance subset -------------------------------------
def test_reclassification_detected_and_admitted():
    r = rec("V6", "Pathogenic", 3, "2025-01-01",
            history=[{"date": "2023-01-01", "clnsig": "Uncertain significance"},
                     {"date": "2025-01-01", "clnsig": "Pathogenic"}])
    m = _build([r])
    v = next(v for v in m["variants"] if v["variant_id"] == "V6")
    assert v["reclassified"] is True
    assert v["from_class"] == "Uncertain Significance"
    assert v["to_class"] == "Pathogenic"
    assert m["counts"]["reclassified"] == 1


def test_label_existed_before_cutoff_excluded():
    # current label is Pathogenic but Pathogenic already existed pre-cutoff (re-affirmed later)
    r = rec("V7", "Pathogenic", 3, "2025-01-01",
            history=[{"date": "2023-01-01", "clnsig": "Pathogenic"},
                     {"date": "2025-01-01", "clnsig": "Pathogenic"}])
    m = _build([r])
    assert m["counts"]["held_out"] == 0
    assert m["counts"]["excluded"]["pre_cutoff"] == 1


# ---- truth/evidence separation + provenance ------------------------------------
def test_truth_is_segregated_and_no_clinvar_evidence():
    m = _build([rec("V8", "Pathogenic", 3, "2025-01-01")])
    assert m["label_is_scoring_artefact_only"] is True
    v = next(v for v in m["variants"] if v["variant_id"] == "V8")
    assert "truth" in v and v["truth"]["clnsig"] == "Pathogenic"
    assert v["truth"]["review_stars"] == 3
    assert v["truth"]["submitters"] == ["LabX"]
    # the truth block carries the label; the genomic_context the model sees has no clinvar/label
    assert "clnsig" not in v["genomic_context"]
    assert "truth" not in v["genomic_context"]


def test_history_and_dates_preserved():
    r = rec("V9", "Pathogenic", 3, "2025-01-01",
            history=[{"date": "2023-01-01", "clnsig": "Uncertain significance"},
                     {"date": "2025-01-01", "clnsig": "Pathogenic"}])
    m = _build([r])
    v = next(v for v in m["variants"] if v["variant_id"] == "V9")
    assert v["truth"]["history"] == r["history"]
    assert v["truth"]["label_first_available"] == "2025-01-01"


# ---- immutability / checksums --------------------------------------------------
def test_deterministic_content_hash_and_entry_hashes():
    recs = [rec("V10", "Pathogenic", 2, "2025-01-01"), rec("V11", "Benign", 2, "2025-02-01")]
    m1 = _build(recs)
    m2 = _build(list(reversed(recs)))
    assert m1["content_hash"] == m2["content_hash"]  # order-invariant, deterministic
    assert all(len(v["entry_hash"]) == 64 for v in m1["variants"])
    assert m1["immutable"] is True


def test_counts_total_accounting():
    recs = [
        rec("A", "Pathogenic", 2, "2025-01-01"),                 # held out
        rec("B", "Pathogenic", 3, "2024-01-01"),                 # pre-cutoff
        rec("C", "Pathogenic", 1, "2025-01-01"),                 # low stars
        rec("D", "not provided", 2, "2025-01-01"),               # unusable
        rec("E", "Pathogenic", 2, None),                         # missing date
    ]
    m = _build(recs)
    c = m["counts"]
    assert c["candidates"] == 5
    assert c["held_out"] == 1
    excluded_total = sum(c["excluded"].values())
    assert c["held_out"] + excluded_total == c["candidates"]
