"""Variant-calling scorer (Exp 2): compare a query VCF to a GIAB benchmark within the confident BED.

GA4GH comparison via hap.py (or rtg vcfeval in a GA4GH-compatible mode). This module separates the
command builder and the output parser (both pure and tested) from the subprocess call, which shells
out on the compute host (Mac Studio / Linux) and is not unit-tested here. No side effects at import.

hap.py run (on the host):
  hap.py TRUTH.vcf.gz QUERY.vcf.gz -f CONF.bed -r REF.fa -o OUT_PREFIX --threads N \
         [--stratification strat.tsv]
emits OUT_PREFIX.summary.csv and (with --stratification) OUT_PREFIX.extended.csv.
"""
from __future__ import annotations

import csv
import io

_METRIC = {"recall": "METRIC.Recall", "precision": "METRIC.Precision", "f1": "METRIC.F1_Score"}


def happy_command(*, truth, query, bed, ref, out_prefix, threads=1, stratification=None,
                  happy="hap.py"):
    """Build the hap.py argv (pure; the host runs it). Confident regions via -f, reference via -r."""
    cmd = [happy, str(truth), str(query), "-f", str(bed), "-r", str(ref),
           "-o", str(out_prefix), "--threads", str(threads)]
    if stratification:
        cmd += ["--stratification", str(stratification)]
    return cmd


def _to_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _to_int(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def parse_happy_summary(text_or_path, filt="PASS"):
    """Parse a hap.py summary.csv into {Type: {recall, precision, f1, truth_total, fp, fn}}.

    Selects the requested Filter rows (PASS by default; ALL also valid). Never invents a Type row
    that is absent from the file."""
    text = _read(text_or_path)
    out = {}
    for row in csv.DictReader(io.StringIO(text)):
        if row.get("Filter") != filt:
            continue
        t = row.get("Type")
        if not t:
            continue
        out[t] = {
            "recall": _to_float(row.get(_METRIC["recall"])),
            "precision": _to_float(row.get(_METRIC["precision"])),
            "f1": _to_float(row.get(_METRIC["f1"])),
            "truth_total": _to_int(row.get("TRUTH.TOTAL")),
            "fn": _to_int(row.get("TRUTH.FN")),
            "fp": _to_int(row.get("QUERY.FP")),
        }
    return out


def overall_f1(metrics: dict) -> float:
    """Single F1 weighted by TRUTH.TOTAL across types (not a naive mean), since SNPs vastly outnumber
    indels and an unweighted mean would over-represent the harder indel class."""
    num = den = 0.0
    for t, m in metrics.items():
        w = m.get("truth_total") or 0
        if m.get("f1") is not None and w:
            num += m["f1"] * w
            den += w
    return num / den if den else 0.0


def _read(text_or_path) -> str:
    s = str(text_or_path)
    if "\n" in s or "," in s:   # already content
        return s
    with open(s) as fh:
        return fh.read()
