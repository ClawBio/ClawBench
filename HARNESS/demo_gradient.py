#!/usr/bin/env python3
"""End-to-end demo of the Exp 1 constraint gradient on the held-out manifest.

Proves the whole pipeline connects: held-out variants -> 5 conditions -> validate_evidence
(blinding) -> acmg_engine.classify -> score_acmg -> per-condition summary. The "model" here is
a trivial deterministic stub adapter (NOT a real LLM); swap in an Anthropic/OpenAI/clawbio
adapter for a real run. Illustrative only.

Run: python3 HARNESS/demo_gradient.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(_ROOT / "HARNESS"), str(_ROOT / "SKILLS" / "clinical-variant-reporter")]

import gradient_runner as G  # noqa: E402


def stub_adapter(condition: str, prompt: str) -> str:
    """A deterministic stand-in for a model. Class-emitting conditions guess Pathogenic;
    skill-execution emits a small, non-ClinVar, schema-valid evidence packet."""
    if condition in G._CLASS_EMITTING:
        return json.dumps({"classification": "Pathogenic", "evidence_codes": ["PVS1", "PM2"]})
    if condition == "skill_execution":
        # variant_id/genomic_context are filled per-variant by the caller's closure below
        return json.dumps(stub_adapter.submission)
    return ""


def main() -> None:
    manifest = json.loads((_ROOT / "TRUTH" / "clinvar" / "heldout_manifest.json").read_text())
    variants = [{"variant_id": v["variant_id"], "genomic_context": v["genomic_context"],
                 "truth": {"clnsig": v["truth"]["clnsig"], "review_stars": v["truth"]["review_stars"]}}
                for v in manifest["variants"]]
    if not variants:
        print("held-out manifest has no variants (expected until real ClinVar is ingested).")
        return

    results = []
    for v in variants:
        stub_adapter.submission = {
            "variant_id": v["variant_id"], "genomic_context": v["genomic_context"],
            "submitted_evidence_codes": [
                {"code": "PVS1", "strength": "very_strong", "source_type": "computational",
                 "source_id": "VEP", "rationale": "null variant in a LoF gene", "confidence": 0.9},
                {"code": "PM2", "strength": "moderate", "source_type": "population_frequency",
                 "source_id": "gnomAD:v4.1", "rationale": "absent from population databases", "confidence": 0.8}],
            "abstentions": [{"code": "PS3", "rationale": "no functional data"}],
            "benchmark_mode": "clinvar_blinded", "clinvar_blinded_status": True,
            "benchmark_truth_source": "clinvar"}
        for cond in G.CONDITIONS:
            results.append(G.run_one(cond, v, stub_adapter, model="stub",
                                     reference_codes=["PVS1", "PM2"], mode="clinvar_blinded"))

    summary = G.summarise(results)
    print(f"{'condition':22} {'exact':>6} {'3-class':>7} {'danger':>7} {'critF1':>7} {'fmtfail':>7}")
    for cond in G.CONDITIONS:
        s = summary[cond]
        cf1 = s["mean_criteria_f1"]
        print(f"{cond:22} {s['exact_accuracy']:6.2f} {s['three_class_accuracy']:7.2f} "
              f"{s['dangerous_error_rate']:7.2f} {('--' if cf1 is None else f'{cf1:.2f}'):>7} "
              f"{s['format_fail_rate']:7.2f}")
    print(f"\n(stub model, {len(variants)} held-out variants; illustrative not scientific)")


if __name__ == "__main__":
    main()
