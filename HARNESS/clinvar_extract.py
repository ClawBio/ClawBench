"""Extract normalised ClinVar records for the held-out slice builder.

variant_summary.txt gives the current aggregate classification, review status, and GRCh38
coordinates, but NOT first-appearance dates or per-variant history. submission_summary.txt gives
one row per submission (DateLastEvaluated, ClinicalSignificance, Submitter), from which we derive:
  - date_created   = earliest dated submission (a lower bound on when any label existed)
  - history        = [{date, clnsig}] across dated submissions (lets the slice builder establish
                     when the CURRENT label first appeared, and detect reclassification)
  - submitters     = unique submitter list
The two are joined on VariationID. ClinVar's date formats are normalised to strict ISO so the slice
builder's strict parser accepts them. ReviewStatus is mapped to the standard 0-4 star levels.

Output records are valid input to build_heldout_clinvar_slice.build_slice. No side effects at import.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import gzip
import json
from collections import defaultdict
from pathlib import Path

# Standard ClinVar review-status -> star mapping.
_STAR_BY_STATUS = {
    "practice guideline": 4,
    "reviewed by expert panel": 3,
    "criteria provided, multiple submitters, no conflicts": 2,
    "criteria provided, single submitter": 1,
    "criteria provided, conflicting classifications": 1,
    "criteria provided, conflicting interpretations": 1,
    "no assertion criteria provided": 0,
    "no assertion provided": 0,
    "no classification provided": 0,
    "no classifications from unflagged records": 0,
}

_DATE_FORMATS = ("%Y-%m-%d", "%Y/%m/%d", "%b %d, %Y", "%b %d %Y", "%d %b %Y")


def review_status_to_stars(status) -> int:
    return _STAR_BY_STATUS.get((status or "").strip().lower(), 0)


def parse_clinvar_date(s) -> str | None:
    """Normalise a ClinVar date to strict ISO YYYY-MM-DD, or None if missing/unparseable."""
    if not isinstance(s, str):
        return None
    s = s.strip()
    if not s or s == "-":
        return None
    for fmt in _DATE_FORMATS:
        try:
            return dt.datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _g(row: dict, *names, default=""):
    for n in names:
        if row.get(n) not in (None, ""):
            return row[n]
    return default


def build_record(vs_row: dict, sub_rows: list[dict]) -> dict:
    varid = _g(vs_row, "VariationID", "#VariationID")
    variant_id = f"VCV{int(varid):09d}" if str(varid).isdigit() else str(varid)

    submitters, history, dates = set(), [], []
    for s in sub_rows:
        name = _g(s, "Submitter", "SubmitterName")
        if name:
            submitters.add(name)
        d = parse_clinvar_date(_g(s, "DateLastEvaluated", "DateCreated"))
        if d is not None:
            history.append({"date": d, "clnsig": _g(s, "ClinicalSignificance")})
            dates.append(d)
    history.sort(key=lambda h: (h["date"], h["clnsig"]))

    try:
        pos = int(_g(vs_row, "PositionVCF", "Start", default="0"))
    except (TypeError, ValueError):
        pos = 0

    return {
        "variant_id": variant_id,
        "chrom": _g(vs_row, "Chromosome"),
        "pos": pos,
        "ref": _g(vs_row, "ReferenceAlleleVCF", "ReferenceAllele"),
        "alt": _g(vs_row, "AlternateAlleleVCF", "AlternateAllele"),
        "build": _g(vs_row, "Assembly"),
        "gene": _g(vs_row, "GeneSymbol"),
        "clnsig": _g(vs_row, "ClinicalSignificance"),
        "review_stars": review_status_to_stars(_g(vs_row, "ReviewStatus")),
        "date_created": min(dates) if dates else None,
        "date_last_evaluated": parse_clinvar_date(_g(vs_row, "LastEvaluated")),
        "submitters": sorted(submitters),
        "history": history,
    }


def extract(vs_rows, sub_rows, assembly: str = "GRCh38", min_stars: int = 0,
            genes: set[str] | None = None) -> list[dict]:
    subs_by_var: dict[str, list] = defaultdict(list)
    for s in sub_rows:
        subs_by_var[str(_g(s, "VariationID", "#VariationID"))].append(s)

    records = []
    for vs in vs_rows:
        if _g(vs, "Assembly") != assembly:
            continue
        if genes and _g(vs, "GeneSymbol") not in genes:
            continue
        if review_status_to_stars(_g(vs, "ReviewStatus")) < min_stars:
            continue
        varid = str(_g(vs, "VariationID", "#VariationID"))
        records.append(build_record(vs, subs_by_var.get(varid, [])))
    return records


# ---- TSV readers (gzip-aware, comment-tolerant) --------------------------------
def _open(path: Path):
    return gzip.open(path, "rt") if str(path).endswith(".gz") else open(path)


def read_tsv(path: Path, key_column: str):
    """Yield dict rows. Skips '##' comment lines; the header line may start with a single '#'."""
    with _open(path) as fh:
        header = None
        rows = []
        for line in fh:
            if header is None:
                if line.startswith("##"):
                    continue
                header = line.lstrip("#").rstrip("\n").split("\t")
                if key_column not in header:
                    header = None  # not the header yet; keep scanning
                continue
            rows.append(dict(zip(header, line.rstrip("\n").split("\t"))))
    return rows


def main() -> None:
    ap = argparse.ArgumentParser(description="Extract normalised ClinVar records for the held-out slice")
    ap.add_argument("--variant-summary", required=True, type=Path)
    ap.add_argument("--submission-summary", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--assembly", default="GRCh38")
    ap.add_argument("--min-stars", type=int, default=2)
    ap.add_argument("--genes", default=None, help="comma-separated gene allowlist")
    args = ap.parse_args()

    vs_rows = read_tsv(args.variant_summary, "ClinicalSignificance")
    sub_rows = read_tsv(args.submission_summary, "ClinicalSignificance")
    genes = {g.strip() for g in args.genes.split(",")} if args.genes else None
    records = extract(vs_rows, sub_rows, assembly=args.assembly, min_stars=args.min_stars, genes=genes)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w") as fh:
        json.dump(records, fh, indent=2, ensure_ascii=False)
    dated = sum(1 for r in records if r["date_created"])
    print(f"{len(records)} records ({args.assembly}, >= {args.min_stars} stars); "
          f"{dated} have a derivable date_created -> {args.out}")


if __name__ == "__main__":
    main()
