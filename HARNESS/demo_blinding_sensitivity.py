#!/usr/bin/env python3
"""Sensitivity demonstration: how much ClinVar circularity inflates classification.

Runs the pinned clinical-variant-reporter demo panel through both benchmark modes
and reports how many variants change class once ClinVar-derived assertion criteria
(PS1/PP5/BP6) are blinded. This is the control analysis behind the manuscript claim
that ClinVar must be held out as truth, not used as evidence.

Run: python3 HARNESS/demo_blinding_sensitivity.py
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "HARNESS"))
sys.path.insert(0, str(_ROOT / "SKILLS" / "clinical-variant-reporter"))

import blinding  # noqa: E402
from clinical_variant_reporter import (  # noqa: E402
    build_evidence_from_cache,
    load_demo_evidence_cache,
    parse_vcf,
)


def main() -> None:
    skill = _ROOT / "SKILLS" / "clinical-variant-reporter"
    recs = parse_vcf(skill / "example_data" / "giab_acmg_panel.vcf")
    cache = load_demo_evidence_cache()

    changed = 0
    print(f"{'gene':8} {'unblinded':22} {'blinded':22} fired_clinvar_criteria")
    for r in recs:
        ev = build_evidence_from_cache(r, cache)
        u = blinding.classify_with_mode(ev, blinding.SENSITIVITY_MODE)
        b = blinding.classify_with_mode(ev, blinding.PRIMARY_MODE)
        fired = [c for c in blinding.BLINDED_POLICY_CODES if c in u["triggered_criteria"]]
        if u["classification"] != b["classification"]:
            changed += 1
            print(f"{ev.gene:8} {u['classification']:22} {b['classification']:22} {fired}")
    pct = 100 * changed / len(recs) if recs else 0
    print(f"\n{changed}/{len(recs)} ({pct:.0f}%) variants change class when ClinVar evidence is blinded.")


if __name__ == "__main__":
    main()
