"""Single source of truth for the Exp1 held-out dataset numbers, regenerated from the locked manifest.

The manuscript reported an inconsistent breakdown (100,104 - 92,955 - 208 = 6,941, not the stated
6,929): candidate/excluded counts from the 2025-11-28 build were combined with the frozen build's
held-out count. This module recomputes from the frozen manifest, cross-checks the recorded counts
against the records, and RAISES on inconsistency, so every quantitative dataset claim regenerates from
data and the conflation cannot recur. No import-time IO.
"""
from __future__ import annotations


def _records(manifest: dict) -> list:
    if "variants" in manifest and isinstance(manifest["variants"], list):
        return manifest["variants"]
    return next(x for x in manifest.values() if isinstance(x, list))


def dataset_stats(manifest: dict, *, strict: bool = True) -> dict:
    """Return the canonical dataset numbers, recomputed from the manifest records and cross-checked
    against the recorded counts. With strict=True (default) an inconsistency raises ValueError; with
    strict=False the inconsistency is reported (consistent=False) and derived_held_out exposes the
    number the candidate/excluded counts actually imply."""
    counts = manifest["counts"]
    excluded = counts["excluded"]
    records = _records(manifest)

    candidates = counts["candidates"]
    excluded_total = sum(excluded.values())
    derived_held_out = candidates - excluded_total          # what the breakdown actually implies
    held_out_from_records = len(records)
    reclassified_from_records = sum(1 for r in records if r.get("reclassified"))

    consistent = (counts["held_out"] == held_out_from_records == derived_held_out
                  and counts["reclassified"] == reclassified_from_records)

    if strict and not consistent:
        raise ValueError(
            f"Exp1 dataset numbers inconsistent: candidates {candidates} - excluded {excluded_total} "
            f"= {derived_held_out}, but counts.held_out={counts['held_out']} and "
            f"len(records)={held_out_from_records}; reclassified recorded {counts['reclassified']} vs "
            f"records {reclassified_from_records}. Two builds are conflated; use ONE build's full "
            f"breakdown.")

    return {
        "effective_cutoff": manifest.get("effective_cutoff"),
        "safety_margin_days": manifest.get("safety_margin_days"),
        "min_review_stars": manifest.get("min_review_stars"),
        "content_hash": manifest.get("content_hash"),
        "candidates": candidates,
        "excluded": dict(excluded),
        "excluded_total": excluded_total,
        "derived_held_out": derived_held_out,
        "held_out": counts["held_out"],
        "held_out_from_records": held_out_from_records,
        "reclassified": counts["reclassified"],
        "reclassified_from_records": reclassified_from_records,
        "consistent": consistent,
    }


def manuscript_sentence(stats: dict) -> str:
    """The corrected, internally-consistent dataset sentence for the manuscript."""
    pre = stats["excluded"]["pre_cutoff"]
    miss = stats["excluded"]["missing_or_ambiguous_date"]
    return (
        f"Of {stats['candidates']:,} candidate ClinVar variants (>= {stats['min_review_stars']} review "
        f"stars, GRCh38), {pre:,} were excluded as pre-cutoff and {miss:,} for a missing or ambiguous "
        f"first-availability date, leaving {stats['held_out']:,} temporally blinded held-out variants "
        f"({stats['reclassified']:,} reclassified) whose current label first became available after the "
        f"effective cutoff of {stats['effective_cutoff']} (max model cutoff + "
        f"{stats['safety_margin_days']}-day margin)."
    )
