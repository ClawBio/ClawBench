"""Build the held-out ClinVar slice for ClawBench Exp 1 (temporal memorisation control).

Core claim protected:
  "The model cannot have learned the benchmark label during pretraining, and the executing
   skill cannot read it during inference."

This module enforces the FIRST half (temporal): a variant enters the held-out slice only if
its CURRENT classification first became available AFTER the latest model training cutoff (plus
a safety margin), at >= a minimum review-star level, with an unambiguous, parseable date. It
fails closed: any variant whose label date is missing, ambiguous, or predates the cutoff is
excluded and accounted for, never silently admitted. The SECOND half (the executing skill must
not read the label) is enforced by HARNESS/validate_evidence.py, which blocks ClinVar as
evidence in primary mode. Here the label is segregated into a `truth` block flagged as a
scoring artefact, never placed in the genomic context the model sees.

Inputs are normalised ClinVar records (one per variant; produced upstream from variant_summary
which carries DateLastEvaluated / ReviewStatus / ClinicalSignificance / Submitter / history).
No side effects at import time.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path

import yaml

_USABLE = {
    "pathogenic": "Pathogenic",
    "likely pathogenic": "Likely Pathogenic",
    "uncertain significance": "Uncertain Significance",
    "likely benign": "Likely Benign",
    "benign": "Benign",
}
_ACTIONABLE = {"Pathogenic", "Likely Pathogenic"}
_BENIGN = {"Benign", "Likely Benign"}


def normalise_clnsig(s) -> str | None:
    """Canonical 5-tier label, or None for unusable assertions (conflicting, not provided,
    slash-combos, drug response, risk factor, etc.). Crisp truth only."""
    if s is None:
        return None
    return _USABLE.get(str(s).strip().lower())


def _group(c: str) -> str:
    if c in _ACTIONABLE:
        return "actionable"
    if c in _BENIGN:
        return "benign"
    return "uncertain"


def parse_date(s) -> dt.date | None:
    """Strict ISO YYYY-MM-DD only. Partial/garbage/missing -> None (treated as ambiguous)."""
    if not isinstance(s, str) or len(s) != 10 or s[4] != "-" or s[7] != "-":
        return None
    try:
        return dt.date.fromisoformat(s)
    except ValueError:
        return None


def load_cutoffs(path: Path) -> dict:
    with open(path) as fh:
        doc = yaml.safe_load(fh)
    models = doc.get("models", {}) if isinstance(doc, dict) else {}
    return {m: meta["cutoff"] for m, meta in models.items()}


def effective_cutoff(cutoffs: dict, safety_margin_days: int = 0) -> dt.date:
    """Latest model cutoff plus a safety margin. Fails closed on empty/invalid cutoffs."""
    dates = []
    for model, value in (cutoffs or {}).items():
        d = parse_date(value)
        if d is None:
            raise ValueError(f"cutoff for {model!r} is missing or not a strict ISO date: {value!r}")
    dates = [parse_date(v) for v in cutoffs.values()]
    if not dates:
        raise ValueError("no model cutoffs provided; cannot build a blinded slice")
    return max(dates) + dt.timedelta(days=safety_margin_days)


def _label_first_available(rec: dict, current: str):
    """Earliest date the CURRENT label appeared. Returns a date, None (no date), or
    'AMBIGUOUS' (a matching history entry has an unparseable date -> fail closed)."""
    matched = []
    for h in rec.get("history", []) or []:
        if normalise_clnsig(h.get("clnsig")) == current:
            d = parse_date(h.get("date"))
            if d is None:
                return "AMBIGUOUS"
            matched.append(d)
    if matched:
        return min(matched)
    return parse_date(rec.get("date_last_evaluated"))


def _reclassification(rec: dict, current: str):
    """If history shows an earlier label in a different tier-group, return (True, from, to)."""
    dated = []
    for h in rec.get("history", []) or []:
        c = normalise_clnsig(h.get("clnsig"))
        d = parse_date(h.get("date"))
        if c and d:
            dated.append((d, c))
    if not dated:
        return (False, None, None)
    dated.sort()
    earliest = dated[0][1]
    if _group(earliest) != _group(current):
        return (True, earliest, current)
    return (False, None, None)


def _entry_hash(entry: dict) -> str:
    payload = {k: v for k, v in entry.items() if k != "entry_hash"}
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(blob.encode()).hexdigest()


def build_slice(records: list[dict], cutoffs: dict, min_stars: int = 2,
                safety_margin_days: int = 0, build_date: str = "unspecified",
                strict: bool = False) -> dict:
    cutoff = effective_cutoff(cutoffs, safety_margin_days)
    excluded = {"pre_cutoff": 0, "below_min_stars": 0, "unusable_label": 0,
                "missing_or_ambiguous_date": 0}
    variants: list[dict] = []
    reclassified_n = 0

    for rec in records:
        current = normalise_clnsig(rec.get("clnsig"))
        if current is None:
            excluded["unusable_label"] += 1
            continue
        stars = rec.get("review_stars", 0)
        if not isinstance(stars, int) or stars < min_stars:
            excluded["below_min_stars"] += 1
            continue
        first = _label_first_available(rec, current)
        if first is None or first == "AMBIGUOUS":
            excluded["missing_or_ambiguous_date"] += 1
            if strict and first == "AMBIGUOUS":
                raise ValueError(f"ambiguous history date for {rec.get('variant_id')}")
            continue
        if first <= cutoff:
            excluded["pre_cutoff"] += 1
            continue

        reclassified, from_c, to_c = _reclassification(rec, current)
        if reclassified:
            reclassified_n += 1
        entry = {
            "variant_id": rec["variant_id"],
            "genomic_context": {
                "chrom": rec["chrom"], "pos": rec["pos"], "ref": rec["ref"],
                "alt": rec["alt"], "build": rec["build"], "gene": rec.get("gene", ""),
            },
            "truth": {
                "clnsig": current,
                "review_stars": stars,
                "date_last_evaluated": rec.get("date_last_evaluated"),
                "label_first_available": first.isoformat(),
                "submitters": rec.get("submitters", []),
                "history": rec.get("history", []),
            },
            "reclassified": reclassified,
            "from_class": from_c,
            "to_class": to_c,
        }
        entry["entry_hash"] = _entry_hash(entry)
        variants.append(entry)

    variants.sort(key=lambda v: v["variant_id"])
    content_hash = hashlib.sha256(
        json.dumps([v["entry_hash"] for v in variants], sort_keys=True).encode()).hexdigest()

    return {
        "schema_version": 1,
        "principle": ("The model cannot have learned the benchmark label during pretraining, "
                      "and the executing skill cannot read it during inference."),
        "label_is_scoring_artefact_only": True,
        "immutable": True,
        "effective_cutoff": cutoff.isoformat(),
        "safety_margin_days": safety_margin_days,
        "min_review_stars": min_stars,
        "model_cutoffs": cutoffs,
        "build_date": build_date,
        "counts": {
            "candidates": len(records),
            "held_out": len(variants),
            "reclassified": reclassified_n,
            "excluded": excluded,
        },
        "content_hash": content_hash,
        "variants": variants,
    }


def load_records(path: Path) -> list[dict]:
    with open(path) as fh:
        return json.load(fh)


def write_manifest(manifest: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as fh:
        json.dump(manifest, fh, indent=2, ensure_ascii=False)


def main() -> None:
    ap = argparse.ArgumentParser(description="Build the held-out ClinVar slice (temporal blinding)")
    ap.add_argument("--records", required=True, type=Path, help="normalised ClinVar records JSON")
    ap.add_argument("--cutoffs", required=True, type=Path, help="model_cutoffs.yaml")
    ap.add_argument("--out", required=True, type=Path, help="heldout_manifest.json")
    ap.add_argument("--build-date", default="unspecified", help="ISO date stamp (not hashed)")
    ap.add_argument("--min-stars", type=int, default=None)
    ap.add_argument("--strict", action="store_true", help="raise on ambiguous history dates")
    args = ap.parse_args()

    with open(args.cutoffs) as fh:
        doc = yaml.safe_load(fh)
    min_stars = args.min_stars if args.min_stars is not None else doc.get("min_review_stars", 2)
    margin = doc.get("safety_margin_days", 0)
    cutoffs = load_cutoffs(args.cutoffs)
    records = load_records(args.records)

    manifest = build_slice(records, cutoffs, min_stars=min_stars,
                           safety_margin_days=margin, build_date=args.build_date, strict=args.strict)
    write_manifest(manifest, args.out)
    c = manifest["counts"]
    print(f"effective cutoff {manifest['effective_cutoff']} (+{margin}d margin), min {min_stars} stars")
    print(f"held_out {c['held_out']}/{c['candidates']} (reclassified {c['reclassified']}); "
          f"excluded {c['excluded']}")
    print(f"content_hash {manifest['content_hash'][:12]}  -> {args.out}")


if __name__ == "__main__":
    main()
