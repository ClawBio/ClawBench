"""Tier 3 sensitivity analysis + manifest freeze for the held-out ClinVar slice.

Reviewer-proofing: report how many held-out variants survive as the blinding margin past the latest
confirmed model cutoff is widened (0 / 30 / 90 / 180 days). A held-out set that stays large and
stable across margins removes a reviewer's strongest temporal-leakage attack. One streaming pass
gathers the candidate superset at the loosest boundary (latest cutoff + 0d); each margin is then a
cheap re-build over the same records. With --freeze-margin it also writes the frozen manifest.

Run: python3 HARNESS/cutoff_sensitivity.py --build-date 2026-06-15 --freeze-margin 90
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "HARNESS"))

import build_heldout_clinvar_slice as B  # noqa: E402
import run_build_heldout as R  # noqa: E402
import slice_summary as SS  # noqa: E402
import yaml  # noqa: E402

MARGINS = [0, 30, 90, 180]


def _min_headroom(summary) -> int | None:
    vals = [e.get("headroom_days_to_earliest_label") for e in summary["blinding"]["per_model"].values()
            if e.get("headroom_days_to_earliest_label") is not None]
    return min(vals) if vals else None


def _freeze(manifest, out_manifest: Path, results_dir: Path):
    B.write_manifest(manifest, out_manifest)
    file_sha = hashlib.sha256(out_manifest.read_bytes()).hexdigest()
    out_manifest.with_suffix(".sha256").write_text(f"{file_sha}  {out_manifest.name}\n")
    summary = SS.summarise_slice(manifest)
    summary["manifest_file_sha256"] = file_sha
    (results_dir / "exp1_heldout_slice_summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    (results_dir / "exp1_heldout_slice_summary.md").write_text(SS.render_markdown(summary))
    return file_sha


def main() -> None:
    ap = argparse.ArgumentParser(description="Held-out slice cutoff sensitivity + freeze")
    ap.add_argument("--variant-summary", type=Path, default=_ROOT / "TRUTH/clinvar/variant_summary.txt.gz")
    ap.add_argument("--submission-summary", type=Path, default=_ROOT / "TRUTH/clinvar/submission_summary.txt.gz")
    ap.add_argument("--cutoffs", type=Path, default=_ROOT / "TRUTH/clinvar/model_cutoffs.yaml")
    ap.add_argument("--out-manifest", type=Path, default=_ROOT / "TRUTH/clinvar/heldout_manifest.json")
    ap.add_argument("--results-dir", type=Path, default=_ROOT / "RESULTS")
    ap.add_argument("--assembly", default="GRCh38")
    ap.add_argument("--build-date", required=True)
    ap.add_argument("--freeze-margin", type=int, default=None, help="if set, freeze the manifest at this margin")
    ap.add_argument("--genes", default=None)
    args = ap.parse_args()

    doc = yaml.safe_load(open(args.cutoffs))
    cutoffs = B.load_cutoffs(args.cutoffs)
    min_stars = doc.get("min_review_stars", 2)
    genes = {g.strip() for g in args.genes.split(",")} if args.genes else None

    latest = max(B.parse_date(c) for c in cutoffs.values())
    print(f"latest confirmed cutoff {latest.isoformat()} (boundary-setting model); gathering candidates at margin 0")
    records = R.gather_records(args.variant_summary, args.submission_summary, latest, min_stars,
                               args.assembly, genes, progress=True)

    sweep = []
    frozen_sha = None
    for m in MARGINS:
        manifest = B.build_slice(records, cutoffs, min_stars=min_stars, safety_margin_days=m,
                                 build_date=args.build_date)
        summary = SS.summarise_slice(manifest)
        row = {"margin_days": m, "effective_cutoff": manifest["effective_cutoff"],
               "held_out": manifest["counts"]["held_out"],
               "reclassified": manifest["counts"]["reclassified"],
               "earliest_label": summary["blinding"]["earliest_label_first_available"],
               "min_headroom_days_past_latest_cutoff": _min_headroom(summary)}
        sweep.append(row)
        if args.freeze_margin is not None and m == args.freeze_margin:
            frozen_sha = _freeze(manifest, args.out_manifest, args.results_dir)

    latest_iso = latest.isoformat()
    report = {
        "latest_confirmed_cutoff": latest_iso,
        "candidate_superset_size": len(records),
        "margins": sweep,
        "frozen_margin_days": args.freeze_margin,
        "frozen_manifest_sha256": frozen_sha,
    }
    args.results_dir.mkdir(parents=True, exist_ok=True)
    (args.results_dir / "exp1_cutoff_sensitivity.json").write_text(json.dumps(report, indent=2))

    L = ["# ClawBench Exp 1 — cutoff sensitivity analysis (Tier 3)", "",
         f"Latest confirmed model cutoff (boundary): **{latest_iso}** (GPT-5.2, high confidence). "
         "Held-out variants must have their current label first-available strictly after "
         "effective_cutoff = this boundary + margin.", "",
         f"Candidate superset (at margin 0): {len(records):,}", "",
         "| margin (days) | effective cutoff | held out | reclassified | earliest label | min headroom past latest cutoff |",
         "|---|---|---|---|---|---|"]
    for r in sweep:
        L.append(f"| {r['margin_days']} | {r['effective_cutoff']} | {r['held_out']:,} | "
                 f"{r['reclassified']:,} | {r['earliest_label']} | {r['min_headroom_days_past_latest_cutoff']} |")
    L += ["", f"Frozen manifest margin: **{args.freeze_margin} days**"
          + (f" (sha256 `{frozen_sha[:16]}…`)" if frozen_sha else ""), ""]
    (args.results_dir / "exp1_cutoff_sensitivity.md").write_text("\n".join(L))

    print("\nmargin | effective | held_out | reclassified | min_headroom")
    for r in sweep:
        print(f"  {r['margin_days']:>3}d | {r['effective_cutoff']} | {r['held_out']:>7,} | "
              f"{r['reclassified']:>5,} | {r['min_headroom_days_past_latest_cutoff']}")
    if frozen_sha:
        print(f"\nfrozen at margin {args.freeze_margin}: sha256 {frozen_sha[:12]}")


if __name__ == "__main__":
    main()
