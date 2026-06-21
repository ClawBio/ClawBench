"""Reproducible, auditable rtg vcfeval scoring for Exp 2 (replaces ad-hoc qualification scoring).

The command builder and the summary parser are pure (tested on fixtures); the subprocess call runs on
the Studio. rtg vcfeval compares a query VCF to the GIAB baseline within the confident BED using the
reference SDF, and writes summary.txt. We parse the 'None' (unfiltered) row as the headline by default.
No side effects at import.
"""
from __future__ import annotations


def vcfeval_command(*, truth, query, bed, sdf, out_dir, threads=1, rtg="rtg") -> list[str]:
    """Build the rtg vcfeval argv. Baseline = GIAB truth; calls = query; evaluation = confident BED;
    template = reference SDF; output dir must be inside the run sandbox."""
    return [rtg, "vcfeval",
            f"--baseline={truth}", f"--calls={query}", f"--evaluation-regions={bed}",
            f"--template={sdf}", f"--output={out_dir}", f"--threads={threads}"]


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _i(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def parse_vcfeval_summary(text_or_path, row: str = "None") -> dict | None:
    """Parse rtg vcfeval summary.txt; return the requested threshold row as
    {precision, recall, f1, tp, fp, fn, threshold} or None if absent/empty.

    Columns: Threshold True-pos-baseline True-pos-call False-pos False-neg Precision Sensitivity F-measure
    """
    text = _read(text_or_path)
    if not text or not text.strip():
        return None
    for line in text.splitlines():
        c = line.split()
        if len(c) < 8 or c[0].lower().startswith("threshold"):
            continue
        if c[0] != row:
            continue
        return {"threshold": c[0], "tp": _i(c[1]), "fp": _i(c[3]), "fn": _i(c[4]),
                "precision": _f(c[5]), "recall": _f(c[6]), "f1": _f(c[7])}
    return None


def _read(text_or_path) -> str:
    s = str(text_or_path)
    if "\n" not in s and len(s) < 4096:
        try:
            with open(text_or_path) as fh:
                return fh.read()
        except (OSError, ValueError):
            return s
    return s
