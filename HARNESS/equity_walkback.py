"""Honest per-ancestry recompute for Exp2 (hostile review S3.3).

The published claim ("ancestry-invariant, 0.05% F1 spread") rests on a metric that HIDES a
false-positive-rate gradient: F1 is nearly flat across the three GIAB ancestries, but precision and
false-positives-per-true-positive are not, and the East Asian sample carries the highest FP burden.
This module pools counts within an ancestry and reports precision / recall / F1 / fp-per-TP with
Wilson confidence intervals and the per-metric spread, so the claim can be restricted to what the
data supports. It also states GIAB's ancestry limits (no African or South Asian) and that any equity
property here is a property of sarek + GIAB, not of the agentic layer. No import-time IO.
"""
from __future__ import annotations

import math
from collections import defaultdict

# GIAB covers only these three; the honest claim must say so.
GIAB_ANCESTRIES = ("EUR", "AJ", "EAS")
GIAB_MISSING = ("African", "South Asian", "Indigenous American", "admixed")


def _f1(p, r):
    return 0.0 if (p + r) == 0 else 2 * p * r / (p + r)


def per_ancestry(rows: list[dict]) -> dict:
    """Pool TP/FP/FN counts by ancestry (summing samples), then derive metrics. Pooling counts is the
    correct aggregation across samples of one ancestry (not averaging per-sample rates)."""
    agg = defaultdict(lambda: {"TP": 0, "FP": 0, "FN": 0, "samples": []})
    for r in rows:
        a = agg[r["ancestry"]]
        a["TP"] += int(r["TP"]); a["FP"] += int(r["FP"]); a["FN"] += int(r["FN"])
        a["samples"].append(r.get("sample"))
    out = {}
    for anc, a in agg.items():
        tp, fp, fn = a["TP"], a["FP"], a["FN"]
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        out[anc] = {"TP": tp, "FP": fp, "FN": fn, "n_samples": len(a["samples"]),
                    "precision": precision, "recall": recall, "f1": _f1(precision, recall),
                    "fp_per_tp": fp / tp if tp else 0.0,
                    "precision_ci": wilson_ci(tp, tp + fp), "recall_ci": wilson_ci(tp, tp + fn)}
    return out


def metric_spread(per_anc: dict, metric: str) -> float:
    vals = [v[metric] for v in per_anc.values()]
    return max(vals) - min(vals)


def worst(per_anc: dict, metric: str) -> str:
    """Worst ancestry for a metric: lowest for precision/recall/f1, highest for fp_per_tp (a cost)."""
    higher_is_worse = metric in ("fp_per_tp", "FP", "FN")
    return (max if higher_is_worse else min)(per_anc, key=lambda a: per_anc[a][metric])


def wilson_ci(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion k/n (95% by default)."""
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = (z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def honest_claim(per_anc: dict) -> str:
    """The restricted, defensible claim that replaces the F1-invariance overclaim."""
    f1_s = metric_spread(per_anc, "f1")
    prec_s = metric_spread(per_anc, "precision")
    fppt_s = metric_spread(per_anc, "fp_per_tp")
    w = worst(per_anc, "fp_per_tp")
    return (
        f"Across the three GIAB ancestries tested on chr20 (EUR, AJ, EAS) the validated wrapper shows "
        f"no large F1 difference (spread {f1_s*100:.2f}%). This F1 stability hides a precision / "
        f"false-positive gradient: precision spread is {prec_s*100:.2f}% and false-positives-per-true-"
        f"positive spread is {fppt_s*100:.2f}% (~{fppt_s/f1_s:.0f}x the F1 spread), with the {w} sample "
        f"carrying the highest false-positive burden. We therefore claim only no-large-F1-difference "
        f"across these three ancestries, not ancestry invariance. GIAB does not include "
        f"{', '.join(GIAB_MISSING[:2])} or other underrepresented populations, so coverage is narrow; "
        f"and any equity property here is a property of nf-core/sarek + GIAB, not of the agentic layer."
    )
