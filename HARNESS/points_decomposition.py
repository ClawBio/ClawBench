"""Decompose the pilot's Pathogenic->Likely-Pathogenic shift: combiner conservatism vs evidence deprivation.

Re-scores each skill_execution record's model-assigned codes through the Tavtigian/ClinGen points
combiner (acmg_points) and compares to the Richards rule combiner (the predicted_class already in the
record) and to truth. The question: of the truth=Pathogenic variants the rule combiner capped at Likely
Pathogenic, how many does the points combiner recover to Pathogenic (combiner conservatism) vs leave
below P (evidence deprivation)?

Run: python3 HARNESS/points_decomposition.py
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "HARNESS"))
import acmg_points as P  # noqa: E402
import acmg_vocabulary as voc  # noqa: E402


def _kept(codes):
    # drop fabricated ClinVar-assertion codes (PP5/BP6) to match blinded scoring; proposed_codes lack
    # source provenance, so clinvar-sourced PS1/PM5 cannot be re-detected here (noted as a limitation).
    return [c for c in codes if isinstance(c, dict) and c.get("code") not in voc.ASSERTION_CODES]


def analyse(checkpoint: Path) -> dict:
    rows = [json.loads(l) for l in checkpoint.read_text().splitlines() if l.strip()]
    se = [r for r in rows if r["condition"] == "skill_execution" and r.get("scoreable") and "proposed_codes" in r]
    out = {"n_skill_execution": len(se), "by_model": {}}
    for model in sorted({r["model"] for r in se}) + ["ALL"]:
        sub = [r for r in se if model == "ALL" or r["model"] == model]
        rule_exact = sum(1 for r in sub if r["predicted_class"] == r["truth_class"])
        pts_exact = sum(1 for r in sub if P.classify_codes(_kept(r["proposed_codes"]))[0] == r["truth_class"])
        gap = [r for r in sub if r["truth_class"] == "Pathogenic" and r["predicted_class"] == "Likely Pathogenic"]
        recovered = sum(1 for r in gap if P.classify_codes(_kept(r["proposed_codes"]))[0] == "Pathogenic")
        pat = [r for r in sub if r["truth_class"] == "Pathogenic"]
        out["by_model"][model] = {
            "n": len(sub),
            "rule_5tier_exact": rule_exact / len(sub) if sub else None,
            "points_5tier_exact": pts_exact / len(sub) if sub else None,
            "lp_gap_n": len(gap),
            "lp_gap_recovered_to_P": recovered,
            "lp_gap_recovery_rate": recovered / len(gap) if gap else None,
            "truth_pathogenic_rule_mix": dict(Counter(r["predicted_class"] for r in pat)),
            "truth_pathogenic_points_mix": dict(Counter(P.classify_codes(_kept(r["proposed_codes"]))[0] for r in pat)),
        }
    return out


def main() -> None:
    rep = analyse(_ROOT / "RESULTS/pilot_v2_runs.jsonl")
    (_ROOT / "RESULTS/exp1_points_decomposition.json").write_text(json.dumps(rep, indent=2))
    a = rep["by_model"]["ALL"]
    print(f"skill_execution n={rep['n_skill_execution']}")
    print(f"5-tier exact: rule {a['rule_5tier_exact']*100:.0f}% vs points {a['points_5tier_exact']*100:.0f}%")
    print(f"LP->P gap (truth=P, rule=LP): n={a['lp_gap_n']}, recovered by points {a['lp_gap_recovered_to_P']} "
          f"({a['lp_gap_recovery_rate']*100:.0f}%)")
    print(f"truth=Pathogenic rule  mix: {a['truth_pathogenic_rule_mix']}")
    print(f"truth=Pathogenic points mix: {a['truth_pathogenic_points_mix']}")


if __name__ == "__main__":
    main()
