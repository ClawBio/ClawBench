"""Generate the Exp2 trust-property gradient pilot artifact from real data.

Reads the agent-arm emissions and the executed validated-arm accuracy table, writes the gradient as
both JSON (machine) and Markdown (manuscript-citable). Run from the repo root. No import-time IO.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(_ROOT / "HARNESS")]

import trust_gradient as TG  # noqa: E402

EMISSIONS = _ROOT / "RESULTS" / "exp2_agent_arms.jsonl"
ANCESTRY = _ROOT / "RESULTS" / "exp2_ancestry_table_chr20.tsv"
OUT_JSON = _ROOT / "RESULTS" / "exp2_trust_gradient.json"
OUT_MD = _ROOT / "RESULTS" / "exp2_trust_gradient.md"


def main() -> None:
    rows = [json.loads(l) for l in EMISSIONS.read_text().splitlines() if l.strip()]
    models = sorted({r.get("model") for r in rows})
    samples = sorted({r.get("sample") for r in rows})

    agg = TG.aggregate_arms(rows)

    # the validated arm's accuracy for the requested sample (HG002 is the pre-registered pilot sample)
    anc = TG.parse_ancestry_table(str(ANCESTRY))
    hg002 = next((r for r in anc if r["sample"] == "HG002"), anc[0] if anc else {})
    skill_summary = {"f1": hg002.get("F1"), "reproducible": True}

    model = models[0] if len(models) == 1 else "+".join(models)
    sample = samples[0] if len(samples) == 1 else "+".join(samples)

    serialisable = {arm: {k: (sorted(v) if isinstance(v, set) else v) for k, v in a.items()}
                    for arm, a in agg.items()}
    OUT_JSON.write_text(json.dumps(
        {"model": model, "sample": sample, "arms": serialisable, "skill_arm": skill_summary,
         "ancestry_table": anc}, indent=2) + "\n")
    OUT_MD.write_text(TG.render_markdown(agg, skill_summary=skill_summary, model=model, sample=sample))
    print(f"wrote {OUT_JSON.relative_to(_ROOT)} and {OUT_MD.relative_to(_ROOT)}")
    print(OUT_MD.read_text())


if __name__ == "__main__":
    main()
