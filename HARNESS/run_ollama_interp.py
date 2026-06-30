"""Run the Exp1 interpretation gradient with a LOCAL OPEN-WEIGHT model (Ollama), free + reproducible.

Proof that the open-weight interpretation arm works end-to-end: held-out variants -> build_prompt ->
local model (qwen via Ollama) -> validate_evidence (fail-closed, ClinVar-blinded) -> deterministic
combine -> score. Runs skill_execution and free_prompted on a small held-out sample so the
open-vs-frontier contrast (format-compliance, safety, accuracy) is visible. Run from repo root.

Usage: python3 HARNESS/run_ollama_interp.py [N] [model]
No import-time IO.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(_ROOT / "HARNESS"), str(_ROOT / "SKILLS" / "clinical-variant-reporter")]

import gradient_runner as G  # noqa: E402
import model_adapters as MA  # noqa: E402

MANIFEST = _ROOT / "TRUTH" / "clinvar" / "heldout_manifest.json"
CONDITIONS = ["free_prompted", "skill_execution"]


def load_variants(n: int) -> list[dict]:
    d = json.loads(MANIFEST.read_text())
    recs = d.get("variants") or next(x for x in d.values() if isinstance(x, list))
    return [{"variant_id": v["variant_id"], "genomic_context": v["genomic_context"],
             "truth": {"clnsig": v["truth"]["clnsig"], "review_stars": v["truth"]["review_stars"]}}
            for v in recs[:n]]


def main() -> None:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 12
    model = sys.argv[2] if len(sys.argv) > 2 else "qwen3.6:35b-mlx"
    adapter = MA.ollama_adapter(model, MA.OllamaClient())
    variants = load_variants(n)
    print(f"open-weight interpretation arm: model={model}, n={len(variants)} held-out variants")

    results = []
    for i, v in enumerate(variants, 1):
        for cond in CONDITIONS:
            try:
                r = G.run_one(cond, v, adapter, model=model, mode="clinvar_blinded")
            except MA.RateLimitExhausted as e:
                r = {"condition": cond, "variant_id": v["variant_id"], "error": str(e),
                     "scoreable": False}
            results.append(r)
        print(f"  [{i}/{len(variants)}] {v['variant_id']} truth={v['truth']['clnsig']}")

    summary = G.summarise(results)
    print(f"\n{'condition':16} {'exact':>6} {'danger':>7} {'fmtfail':>8}  (n={len(variants)})")
    for cond in CONDITIONS:
        s = summary.get(cond, {})
        print(f"{cond:16} {s.get('exact_accuracy', float('nan')):6.2f} "
              f"{s.get('dangerous_error_rate', float('nan')):7.2f} "
              f"{s.get('format_fail_rate', float('nan')):8.2f}")

    out = {"model": model, "n": len(variants), "summary":
           {c: summary.get(c, {}) for c in CONDITIONS}}
    (_ROOT / "RESULTS" / "exp1_ollama_interp.json").write_text(json.dumps(out, indent=2, default=str) + "\n")
    print("\nwrote RESULTS/exp1_ollama_interp.json")
    print("NOTE: held-out manifest variants carry thin evidence_context; this proves the open-weight")
    print("arm runs end-to-end and is format/safety-scoreable, not a powered accuracy result.")


if __name__ == "__main__":
    main()
