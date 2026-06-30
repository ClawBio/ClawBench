"""Run the pathogenic end-to-end attribution on a real Exp1 interpretation checkpoint (execution-light).

Reads the Tier-A pilot (for pathogenic/LP ids + truth) and an interpretation run checkpoint (default:
the open-weight arm's pilot_openweight_v1.jsonl), restricts to pathogenic/LP variants, overlays a
controlled calling outcome, and joins. Works on a partial checkpoint (reports whatever pathogenic
variants have skill_execution attributions so far). Reads JSONL only -- no GPU. Run from repo root.

Usage: python3 HARNESS/run_pathogenic_integration.py [checkpoint.jsonl]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(_ROOT / "HARNESS"), str(_ROOT / "SKILLS" / "clinical-variant-reporter")]

import pathogenic_integration as PI  # noqa: E402

TIER_A = _ROOT / "TRUTH" / "clinvar" / "pilot_tier_a_v1.json"
DEFAULT_CKPT = _ROOT / "RESULTS" / "pilot_openweight_v1.jsonl"
OUT = _ROOT / "RESULTS" / "exp_pathogenic_integration.json"


def main() -> None:
    ckpt = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_CKPT
    tier_a = json.loads(TIER_A.read_text())
    tier_a_records = tier_a["variants"] if "variants" in tier_a else tier_a
    if not ckpt.exists():
        print(f"no interpretation checkpoint at {ckpt} yet (run #10 first); pathogenic integration "
              f"is ready and will populate when interpretation records exist.")
        return
    recs = [json.loads(l) for l in ckpt.read_text().splitlines() if l.strip()]
    skex = [r for r in recs if r.get("condition") == "skill_execution"]

    pids = PI.pathogenic_variant_ids(tier_a_records)
    have = {r["variant_id"] for r in skex if r.get("variant_id") in pids}
    print(f"pathogenic/LP Tier-A variants: {len(pids)}; with skill_execution records so far: {len(have)}")
    if not have:
        print("no pathogenic skill_execution records yet; rerun after #10 progresses.")
        return

    out = PI.pathogenic_integration(tier_a_records, skex)
    summary = dict(out["summary"])
    OUT.write_text(json.dumps({"n_pathogenic_with_interp": out["n_overlap"], "summary": summary,
                               "per_variant": out["per_variant"]}, indent=2, default=str) + "\n")
    print(f"\npathogenic end-to-end attribution (n={out['n_overlap']}, controlled correct-call overlay):")
    for label, n in sorted(summary.items(), key=lambda kv: -kv[1]):
        print(f"  {label}: {n}")
    dm = summary.get("dangerous_misclass", 0)
    print(f"\nDANGEROUS misclassifications of pathogenic variants: {dm}/{out['n_overlap']} "
          f"({'SAFE: none' if dm == 0 else 'FLAG'})")
    print(f"wrote {OUT.relative_to(_ROOT)}")


if __name__ == "__main__":
    main()
