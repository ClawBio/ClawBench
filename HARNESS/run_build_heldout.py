"""Orchestrate the real held-out slice: stream ClinVar TSVs -> extract -> build slice -> manifest
-> sha256 -> RESULTS summary (json + md). Memory-safe two-pass streaming over the large files.

Pass 1 streams variant_summary, keeping only candidates that COULD be admissible (GRCh38, >= min
stars, usable label, and current label last-evaluated after the cutoff OR undated). This is a
necessary condition (LastEvaluated >= first-available), so it never drops an admissible variant.
Pass 2 streams submission_summary, keeping only submissions for those candidate VariationIDs.
The slice builder then applies the sufficient temporal test (first-availability strictly after the
effective cutoff) per variant.

Run: python3 HARNESS/run_build_heldout.py
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "HARNESS"))

import build_heldout_clinvar_slice as B  # noqa: E402
import clinvar_extract as X  # noqa: E402
import slice_summary as SS  # noqa: E402
import yaml  # noqa: E402


def _passes_prefilter(vs, cutoff_date, min_stars, assembly, genes):
    if X._g(vs, "Assembly") != assembly:
        return False
    if X.review_status_to_stars(X._g(vs, "ReviewStatus")) < min_stars:
        return False
    if B.normalise_clnsig(X._g(vs, "ClinicalSignificance")) is None:
        return False
    if genes and X._g(vs, "GeneSymbol") not in genes:
        return False
    le_iso = X.parse_clinvar_date(X._g(vs, "LastEvaluated"))
    if le_iso is not None:
        le = B.parse_date(le_iso)
        if le is not None and le <= cutoff_date:
            return False  # current label last-evaluated on/before cutoff -> cannot be new
    return True


def gather_records(variant_summary_path, submission_summary_path, prefilter_cutoff_date,
                   min_stars, assembly="GRCh38", genes=None, progress=False) -> list[dict]:
    """Two-pass memory-safe streaming: candidate variant_summary rows whose LastEvaluated is after
    prefilter_cutoff_date (a NECESSARY condition for admission; never drops an admissible variant),
    then only their submissions, normalised into records via clinvar_extract.build_record."""
    cands: dict[str, dict] = {}
    seen = 0
    for vs in X.iter_tsv(variant_summary_path, "ClinicalSignificance"):
        seen += 1
        if progress and seen % 1_000_000 == 0:
            print(f"  ...scanned {seen:,} variant_summary rows, {len(cands):,} candidates")
        if _passes_prefilter(vs, prefilter_cutoff_date, min_stars, assembly, genes):
            cands[str(X._g(vs, "VariationID"))] = vs
    if progress:
        print(f"pass 1: {len(cands):,} candidates from {seen:,} variant_summary rows")

    subs: dict[str, list] = defaultdict(list)
    cand_ids = set(cands)
    for s in X.iter_tsv(submission_summary_path, "ClinicalSignificance"):
        vid = str(X._g(s, "VariationID", "#VariationID"))
        if vid in cand_ids:
            subs[vid].append(s)
    if progress:
        print(f"pass 2: collected submissions for {len(subs):,} candidates")
    return [X.build_record(vs, subs.get(vid, [])) for vid, vs in cands.items()]


def main() -> None:
    ap = argparse.ArgumentParser(description="Build the real held-out ClinVar slice")
    ap.add_argument("--variant-summary", type=Path, default=_ROOT / "TRUTH/clinvar/variant_summary.txt.gz")
    ap.add_argument("--submission-summary", type=Path, default=_ROOT / "TRUTH/clinvar/submission_summary.txt.gz")
    ap.add_argument("--cutoffs", type=Path, default=_ROOT / "TRUTH/clinvar/model_cutoffs.yaml")
    ap.add_argument("--out-manifest", type=Path, default=_ROOT / "TRUTH/clinvar/heldout_manifest.json")
    ap.add_argument("--results-dir", type=Path, default=_ROOT / "RESULTS")
    ap.add_argument("--assembly", default="GRCh38")
    ap.add_argument("--build-date", required=True, help="ISO date stamp for the build (not hashed)")
    ap.add_argument("--genes", default=None, help="comma-separated gene allowlist")
    args = ap.parse_args()

    doc = yaml.safe_load(open(args.cutoffs))
    cutoffs = B.load_cutoffs(args.cutoffs)
    min_stars = doc.get("min_review_stars", 2)
    margin = doc.get("safety_margin_days", 0)
    cutoff_date = B.effective_cutoff(cutoffs, margin)
    genes = {g.strip() for g in args.genes.split(",")} if args.genes else None
    print(f"effective cutoff {cutoff_date.isoformat()} (+{margin}d), min {min_stars} stars, assembly {args.assembly}")

    records = gather_records(args.variant_summary, args.submission_summary, cutoff_date,
                             min_stars, args.assembly, genes, progress=True)
    manifest = B.build_slice(records, cutoffs, min_stars=min_stars, safety_margin_days=margin,
                             build_date=args.build_date)
    B.write_manifest(manifest, args.out_manifest)

    raw = args.out_manifest.read_bytes()
    file_sha = hashlib.sha256(raw).hexdigest()
    args.out_manifest.with_suffix(".sha256").write_text(f"{file_sha}  {args.out_manifest.name}\n")

    summary = SS.summarise_slice(manifest)
    summary["manifest_file_sha256"] = file_sha
    args.results_dir.mkdir(parents=True, exist_ok=True)
    (args.results_dir / "exp1_heldout_slice_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False))
    (args.results_dir / "exp1_heldout_slice_summary.md").write_text(SS.render_markdown(summary))

    c = manifest["counts"]
    print(f"\nheld_out {c['held_out']:,} / candidates {c['candidates']:,} "
          f"(reclassified {c['reclassified']:,}); excluded {c['excluded']}")
    print(f"manifest content_hash {manifest['content_hash'][:12]}  file sha256 {file_sha[:12]}")
    print(f"earliest held-out label: {summary['blinding']['earliest_label_first_available']}, "
          f"all post-date all cutoffs: {summary['blinding']['all_labels_postdate_all_model_cutoffs']}")


if __name__ == "__main__":
    main()
