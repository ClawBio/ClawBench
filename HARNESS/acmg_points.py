"""Tavtigian/ClinGen Bayesian points combiner (Tavtigian et al. 2018/2020).

An alternative deterministic combiner to the Richards-2015 rule-counting one in acmg_engine. Used to
decompose the pilot's systematic Pathogenic->Likely-Pathogenic shift: the rule combiner caps PVS1+PM2
at Likely Pathogenic, whereas points score it 8+2=10 = Pathogenic. Re-scoring the same model-assigned
codes through points tells us how much of the gap is ACMG thresholding (combiner) vs missing evidence.

Point magnitudes by strength; benign codes negate. Direction comes from the canonical vocabulary.
Class bins (Tavtigian 2020): P >= 10, LP 6..9, VUS 0..5, LB -1..-6, B <= -7. No side effects at import.
"""
from __future__ import annotations

import acmg_vocabulary as voc

_MAGNITUDE = {"very_strong": 8, "strong": 4, "moderate": 2, "supporting": 1, "stand_alone": 8}


def points_for(code: str, strength: str) -> int:
    if code not in voc.VALID_CODES or strength not in _MAGNITUDE:
        return 0
    sign = 1 if voc.direction(code) == "pathogenic" else -1
    return sign * _MAGNITUDE[strength]


def classify_points(total: int) -> str:
    if total >= 10:
        return "Pathogenic"
    if total >= 6:
        return "Likely Pathogenic"
    if total >= 0:
        return "Uncertain Significance"
    if total >= -6:
        return "Likely Benign"
    return "Benign"


def classify_codes(codes):
    """codes: iterable of {code, strength}. Returns (class, total_points)."""
    total = sum(points_for(c.get("code"), c.get("strength")) for c in codes if isinstance(c, dict))
    return classify_points(total), total
