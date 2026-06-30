"""Generate the honest per-ancestry equity table + restricted claim from the chr20 ancestry data.

Replaces the F1-invariance overclaim (hostile review S3.3). Reads the executed-arm ancestry TSV,
recomputes per-ancestry precision/recall/F1/fp-per-TP with Wilson CIs and per-metric spreads, and
writes a manuscript-citable table + the restricted claim. Run from repo root. No import-time IO.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(_ROOT / "HARNESS")]

import equity_walkback as EW  # noqa: E402

TSV = _ROOT / "RESULTS" / "exp2_ancestry_table_chr20.tsv"
OUT_MD = _ROOT / "RESULTS" / "exp2_equity_walkback.md"
OUT_JSON = _ROOT / "RESULTS" / "exp2_equity_walkback.json"


def read_rows(tsv: Path) -> list[dict]:
    lines = [l for l in tsv.read_text().splitlines() if l.strip()]
    header = lines[0].split("\t")
    rows = []
    for ln in lines[1:]:
        rec = dict(zip(header, ln.split("\t")))
        rows.append({"sample": rec["sample"], "ancestry": rec["ancestry"],
                     "TP": int(rec["TP"]), "FP": int(rec["FP"]), "FN": int(rec["FN"])})
    return rows


def render(pa: dict) -> str:
    order = [a for a in ("EUR", "AJ", "EAS") if a in pa] + [a for a in pa if a not in ("EUR", "AJ", "EAS")]
    L = ["# Exp2 equity: honest per-ancestry recompute (chr20)", "",
         "Replaces the F1-invariance claim. Counts pooled within ancestry; Wilson 95% CIs.", "",
         "| Ancestry | n samples | precision (95% CI) | recall | F1 | FP per TP |",
         "|----------|-----------|--------------------|--------|----|-----------|"]
    for a in order:
        v = pa[a]
        lo, hi = v["precision_ci"]
        L.append(f"| {a} | {v['n_samples']} | {v['precision']:.4f} ({lo:.4f}-{hi:.4f}) | "
                 f"{v['recall']:.4f} | {v['f1']:.4f} | {v['fp_per_tp']*100:.3f}% |")
    L += ["",
          f"- F1 spread: {EW.metric_spread(pa,'f1')*100:.2f}%  (looks invariant)",
          f"- precision spread: {EW.metric_spread(pa,'precision')*100:.2f}%",
          f"- FP-per-TP spread: {EW.metric_spread(pa,'fp_per_tp')*100:.2f}%  "
          f"(~{EW.metric_spread(pa,'fp_per_tp')/EW.metric_spread(pa,'f1'):.0f}x the F1 spread)",
          f"- worst ancestry by FP burden: {EW.worst(pa,'fp_per_tp')}",
          "", "## Restricted claim (replaces the overclaim)", "", EW.honest_claim(pa), ""]
    return "\n".join(L)


def main() -> None:
    rows = read_rows(TSV)
    pa = EW.per_ancestry(rows)
    OUT_JSON.write_text(json.dumps(
        {"per_ancestry": pa,
         "spreads": {m: EW.metric_spread(pa, m) for m in ("f1", "precision", "recall", "fp_per_tp")},
         "claim": EW.honest_claim(pa)}, indent=2) + "\n")
    md = render(pa)
    OUT_MD.write_text(md)
    print(md)
    print("wrote RESULTS/exp2_equity_walkback.{md,json}")


if __name__ == "__main__":
    main()
