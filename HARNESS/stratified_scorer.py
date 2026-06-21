"""GA4GH-stratified scoring (Exp 2): per-difficulty-stratum accuracy from hap.py extended.csv.

Callers lose accuracy in difficult genomic regions (low-complexity, tandem repeats and homopolymers,
segmental duplications, the MHC). The GA4GH stratification BEDs partition the genome into these
strata; hap.py --stratification reports metrics per stratum. We surface the difficulty strata and the
genome-wide-to-hardest gap, which is where an agentic caller's competence is really tested.
No side effects at import.
"""
from __future__ import annotations

import csv
import io

_METRIC = {"recall": "METRIC.Recall", "precision": "METRIC.Precision", "f1": "METRIC.F1_Score"}

# substrings identifying the GA4GH difficulty strata of interest (v3.x naming)
_DIFFICULTY = ("Homopolymer", "TandemRepeats", "segdup", "MHC", "lowmappability", "lowcomplexity")
_GENOME_WIDE = "*"


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def parse_happy_extended(text_or_path):
    """Parse hap.py extended.csv into {(Type, Subset): {recall, precision, f1, size}}."""
    text = _read(text_or_path)
    out = {}
    for row in csv.DictReader(io.StringIO(text)):
        t, subset = row.get("Type"), row.get("Subset")
        if not t or subset is None:
            continue
        out[(t, subset)] = {
            "recall": _f(row.get(_METRIC["recall"])),
            "precision": _f(row.get(_METRIC["precision"])),
            "f1": _f(row.get(_METRIC["f1"])),
            "size": int(float(row["Subset.Size"])) if row.get("Subset.Size") else None,
        }
    return out


def difficulty_strata(parsed: dict, vtype: str) -> dict:
    """The difficulty strata for one variant type, keyed by subset name (genome-wide '*' excluded)."""
    return {subset: m for (t, subset), m in parsed.items()
            if t == vtype and subset != _GENOME_WIDE
            and any(tok.lower() in subset.lower() for tok in _DIFFICULTY)}


def hardest_stratum(parsed: dict, vtype: str):
    """(subset, metrics) with the lowest F1 among the difficulty strata for this type."""
    strat = difficulty_strata(parsed, vtype)
    if not strat:
        return (None, None)
    name = min(strat, key=lambda s: (strat[s]["f1"] if strat[s]["f1"] is not None else 1.0))
    return name, strat[name]


def easy_hard_gap(parsed: dict, vtype: str):
    """Genome-wide F1 minus hardest-difficulty-stratum F1 for this type (None if unavailable)."""
    gw = parsed.get((vtype, _GENOME_WIDE), {}).get("f1")
    _, hard = hardest_stratum(parsed, vtype)
    if gw is None or not hard or hard.get("f1") is None:
        return None
    return gw - hard["f1"]


def _read(text_or_path) -> str:
    s = str(text_or_path)
    if "\n" in s or "," in s:
        return s
    with open(s) as fh:
        return fh.read()
