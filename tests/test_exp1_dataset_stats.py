"""TDD for HARNESS/exp1_dataset_stats.py: regenerate Exp1 dataset numbers from the locked manifest
and fail loudly on internal inconsistency (the 6,929-vs-6,941 conflation, review).

The frozen v1.0 manifest is internally consistent: candidates - sum(excluded) == held_out == len(records),
and recorded reclassified == reclassified counted from records. The manuscript bug conflated two builds
(candidate/excluded counts from the 2025-11-28 build that yields 6,941, with the frozen build's 6,929).
This module is the single source of truth and a guardrail.
"""
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(_ROOT / "HARNESS")]

import exp1_dataset_stats as DS  # noqa: E402

# the frozen v1.0 build (internally consistent: 166437 - 159300 - 208 = 6929)
FROZEN = {
    "effective_cutoff": "2025-11-29", "safety_margin_days": 90, "min_review_stars": 2,
    "content_hash": "8d745d32",
    "counts": {"candidates": 166437, "held_out": 6929, "reclassified": 206,
               "excluded": {"pre_cutoff": 159300, "below_min_stars": 0, "unusable_label": 0,
                            "missing_or_ambiguous_date": 208, "malformed": 0}},
    "variants": [{"reclassified": (i < 206)} for i in range(6929)],
}

# the conflated build the manuscript reported: 2025-11-28 candidate/excluded counts (-> 6941) but
# the frozen held_out of 6929. 100104 - 92955 - 208 = 6941, not 6929.
CONFLATED = {
    "effective_cutoff": "2025-11-29", "safety_margin_days": 90, "min_review_stars": 2,
    "counts": {"candidates": 100104, "held_out": 6929, "reclassified": 206,
               "excluded": {"pre_cutoff": 92955, "below_min_stars": 0, "unusable_label": 0,
                            "missing_or_ambiguous_date": 208, "malformed": 0}},
    "variants": [{"reclassified": (i < 206)} for i in range(6929)],
}


def test_frozen_build_is_consistent():
    s = DS.dataset_stats(FROZEN)
    assert s["held_out"] == 6929
    assert s["reclassified"] == 206
    assert s["candidates"] == 166437
    assert s["derived_held_out"] == 6929          # candidates - sum(excluded)
    assert s["consistent"] is True


def test_recompute_from_records_matches_counts():
    s = DS.dataset_stats(FROZEN)
    assert s["held_out_from_records"] == 6929
    assert s["reclassified_from_records"] == 206


def test_conflated_build_raises():
    # the guardrail: candidate/excluded counts that imply 6941 but claim 6929 must be rejected
    with pytest.raises(ValueError) as e:
        DS.dataset_stats(CONFLATED)
    assert "6941" in str(e.value) or "6929" in str(e.value) or "consist" in str(e.value).lower()


def test_nonstrict_reports_without_raising():
    s = DS.dataset_stats(CONFLATED, strict=False)
    assert s["consistent"] is False
    assert s["derived_held_out"] == 6941          # exposes the true implied number


def test_manuscript_sentence_uses_consistent_numbers():
    s = DS.dataset_stats(FROZEN)
    sent = DS.manuscript_sentence(s)
    assert "166,437" in sent and "159,300" in sent and "6,929" in sent
    assert "100,104" not in sent and "92,955" not in sent
