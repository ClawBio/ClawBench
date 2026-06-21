"""Ancestry-equity scorer (Exp 2): the ClawBio equity-scorer trust instrument.

GIAB spans three ancestries (HG001 EUR; HG002/HG003 AJ; HG005 EAS). A trustworthy calling pipeline
should reach accuracy that does not depend on ancestry. This scorer reduces per-sample F1 to a
per-ancestry mean, the cross-ancestry spread (max minus min), and an equity verdict against a
tolerance. No side effects at import.
"""
from __future__ import annotations

from collections import defaultdict


def equity(by_sample: dict, tolerance: float = 0.01) -> dict:
    """by_sample maps sample_id -> {"ancestry": str, "f1": float}. Returns per-ancestry mean F1,
    the spread, the worst ancestry, and whether the spread is within tolerance. Requires at least
    two ancestries, since equity is a between-group statement and is undefined for one group."""
    groups = defaultdict(list)
    for s, rec in by_sample.items():
        anc = rec.get("ancestry")
        f1 = rec.get("f1")
        if anc is None or f1 is None:
            continue
        groups[anc].append(f1)
    if len(groups) < 2:
        raise ValueError(f"equity requires >=2 ancestries; got {sorted(groups)}")
    by_anc = {anc: sum(v) / len(v) for anc, v in groups.items()}
    hi = max(by_anc.values())
    lo = min(by_anc.values())
    worst = min(by_anc, key=by_anc.get)
    spread = hi - lo
    return {
        "by_ancestry": by_anc,
        "spread": spread,
        "worst_ancestry": worst,
        "tolerance": tolerance,
        "equitable": spread <= tolerance,
    }
