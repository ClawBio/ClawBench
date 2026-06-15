"""Build the qualification panel + Tier-A pilot from the frozen held-out manifest + ClinVar VCF.

Outputs:
  TRUTH/clinvar/qualification_panel_v1.json   all held-out variants tiered (A/B/C)
  TRUTH/clinvar/pilot_tier_a_v1.json          deterministic class-stratified Tier-A pilot (first run)
  RESULTS/exp1_qualification_panel_summary.md tier x N x class x expected-ceiling report

Run: python3 HARNESS/run_qualification_panel.py --pilot-per-class-cap 60
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "HARNESS"))

import qualification_panel as Q  # noqa: E402


def _render_md(panel: dict, pilot: dict) -> str:
    c = panel["counts"]
    total = sum(c.values())
    L = ["# ClawBench Exp 1 — qualification panel v1", "",
         "Stratifies the frozen held-out set by ACMG automatability so performance is read per tier; "
         "a drop in Tier C localises to evidence acquisition, not execution.", "",
         f"Source held-out manifest content_hash: `{panel['source_manifest_content_hash']}`", "",
         f"Tier rule: {panel['tier_rule']}", "",
         "## Tiers", "",
         "| Tier | N | % | expected ceiling |", "|---|---|---|---|"]
    for t in ("A", "B", "C"):
        pct = 100 * c[t] / total if total else 0
        L.append(f"| {t} | {c[t]:,} | {pct:.1f}% | {panel['expected_ceiling'][t]} |")
    L += ["", f"Total: {total:,}; consequence unavailable (ClinVar VCF miss): {panel['unknown_consequence']:,}", "",
          "## Tier x classification", "",
          "| Tier | " + " | ".join(_CLASSES) + " |", "|---|" + "---|" * len(_CLASSES)]
    for t in ("A", "B", "C"):
        row = panel["by_tier_class"][t]
        L.append(f"| {t} | " + " | ".join(str(row.get(cl, 0)) for cl in _CLASSES) + " |")
    L += ["", "## Tier-A pilot (first run)", "",
          f"- N = {pilot['n']} (per-class cap {pilot['per_class_cap']})",
          f"- class mix: {pilot['class_counts']}",
          f"- reclassified included: {pilot['reclassified_n']}", ""]
    return "\n".join(L)


_CLASSES = ["Pathogenic", "Likely Pathogenic", "Uncertain Significance", "Likely Benign", "Benign"]


def main() -> None:
    ap = argparse.ArgumentParser(description="Build qualification panel + Tier-A pilot")
    ap.add_argument("--manifest", type=Path, default=_ROOT / "TRUTH/clinvar/heldout_manifest.json")
    ap.add_argument("--vcf", type=Path, default=_ROOT / "TRUTH/clinvar/clinvar_GRCh38.vcf.gz")
    ap.add_argument("--panel-out", type=Path, default=_ROOT / "TRUTH/clinvar/qualification_panel_v1.json")
    ap.add_argument("--pilot-out", type=Path, default=_ROOT / "TRUTH/clinvar/pilot_tier_a_v1.json")
    ap.add_argument("--results-dir", type=Path, default=_ROOT / "RESULTS")
    ap.add_argument("--pilot-per-class-cap", type=int, default=60)
    args = ap.parse_args()

    manifest = json.loads(args.manifest.read_text())
    wanted = {Q.varid_to_int(v["variant_id"]) for v in manifest["variants"]} - {None}
    print(f"held-out variants: {len(manifest['variants']):,}; resolving consequences from ClinVar VCF...")
    feats = Q.features_from_vcf(args.vcf, wanted)
    print(f"matched {len(feats):,}/{len(wanted):,} in the ClinVar VCF")

    panel = Q.build_panel(manifest, feats)
    args.panel_out.write_text(json.dumps(panel, indent=2, ensure_ascii=False))

    pilot_variants = Q.select_pilot(panel, per_class_cap=args.pilot_per_class_cap, tier="A")
    class_counts: dict[str, int] = {}
    for v in pilot_variants:
        class_counts[v["clnsig"]] = class_counts.get(v["clnsig"], 0) + 1
    pilot = {
        "version": "pilot_tier_a_v1",
        "tier": "A",
        "per_class_cap": args.pilot_per_class_cap,
        "n": len(pilot_variants),
        "class_counts": class_counts,
        "reclassified_n": sum(1 for v in pilot_variants if v["reclassified"]),
        "source_manifest_content_hash": manifest.get("content_hash"),
        "variants": pilot_variants,
    }
    args.pilot_out.write_text(json.dumps(pilot, indent=2, ensure_ascii=False))

    args.results_dir.mkdir(parents=True, exist_ok=True)
    (args.results_dir / "exp1_qualification_panel_summary.md").write_text(_render_md(panel, pilot))

    c = panel["counts"]
    print(f"\nTier A {c['A']:,} | Tier B {c['B']:,} | Tier C {c['C']:,} "
          f"(unknown consequence {panel['unknown_consequence']:,})")
    for t in ("A", "B", "C"):
        print(f"  Tier {t} by class: {panel['by_tier_class'][t]}")
    print(f"\npilot Tier-A: n={pilot['n']} class_mix={class_counts} reclassified={pilot['reclassified_n']}")


if __name__ == "__main__":
    main()
