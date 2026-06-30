"""Consistent-convention re-score of the calibration arm (peer-review #2: PM2 convention mixing).

The original calibration finding ("strength assignment is direction-coupled") compared a baseline in
which the model applied PM2 at supporting (the 2020/SVI convention) against an intervention that
licensed PM2 at moderate (the 2015 baseline), while PP3/BP4 used the 2020 calibrated strengths
throughout. A reviewer asked whether the trade-off is an artefact of mixing convention versions.

This module isolates the PM2-strength variable WITHIN a single convention frame, deterministically:
it takes the enriched-arm code sets the model actually submitted (no new model calls), holds every
non-PM2 code at its submitted calibrated strength, and re-scores under PM2=supporting vs PM2=moderate.
If pathogenic-side variants recover and benign-side variants regress under this clean comparison, the
direction-coupling is a property of the directional arithmetic, not of the convention mix. No
import-time IO.
"""
from __future__ import annotations

import collections

import acmg_points as AP

DEFINITIVE = {"Pathogenic", "Likely Pathogenic", "Benign", "Likely Benign"}
PATHO = {"Pathogenic", "Likely Pathogenic"}
VUS = "Uncertain Significance"


def rescore(proposed_codes, pm2_strength: str) -> str:
    """Classify a submitted code set, overriding ONLY PM2's strength; all other codes keep their
    submitted (calibrated) strength. Returns the points-combiner class."""
    codes = []
    for c in proposed_codes or []:
        if not isinstance(c, dict) or not c.get("code"):
            continue
        codes.append({"code": c["code"],
                      "strength": pm2_strength if c["code"] == "PM2" else c.get("strength")})
    return AP.classify_codes(codes)[0]


def _variant_insufficient(reps, pm2_strength: str) -> bool:
    truth = reps[0].get("truth_class")
    classes = [rescore(r.get("proposed_codes", []), pm2_strength) for r in reps]
    modal = collections.Counter(classes).most_common(1)[0][0]
    return truth in DEFINITIVE and modal == VUS


def analyze(rows, arm: str = "enriched") -> dict:
    """Re-score the enriched arm under the two PM2 strengths and tally recover/regress by direction."""
    by_var = collections.defaultdict(list)
    for r in rows:
        if r.get("arm") == arm:
            by_var[r["variant_id"]].append(r)
    out = {"n_definitive": 0, "insuff_pm2_supporting": 0, "insuff_pm2_moderate": 0,
           "recover_pathogenic": 0, "recover_benign": 0, "regress_pathogenic": 0, "regress_benign": 0}
    for reps in by_var.values():
        truth = reps[0].get("truth_class")
        if truth not in DEFINITIVE:
            continue
        out["n_definitive"] += 1
        sup = _variant_insufficient(reps, "supporting")
        mod = _variant_insufficient(reps, "moderate")
        out["insuff_pm2_supporting"] += sup
        out["insuff_pm2_moderate"] += mod
        side = "pathogenic" if truth in PATHO else "benign"
        if sup and not mod:          # moving PM2 to moderate RESOLVED it
            out[f"recover_{side}"] += 1
        if mod and not sup:          # moving PM2 to moderate BROKE it
            out[f"regress_{side}"] += 1
    return out
