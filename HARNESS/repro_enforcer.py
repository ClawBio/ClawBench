"""repro-enforcer: the ClawBench reproducibility trust instrument (Exp 2, Phase 3).

Two calling runs are reproducible if they share identical pins AND, in the chosen mode, identical
output: `genotype` (default) compares genotypes within the confident region, ignoring header noise,
record order, and GT allele order/phase; `byte` requires byte-identical files. No side effects at import.
"""
from __future__ import annotations

import hashlib
import re

_PIN_FIELDS = ("sarek_version", "reference_sha256", "container_digests")
_SPLIT = re.compile(r"[/|]")


def normalise_gt(gt: str) -> str:
    """Order- and phase-insensitive genotype string: '1/0' and '0|1' both become '0/1'."""
    alleles = [a for a in _SPLIT.split(gt.strip()) if a != ""]
    return "/".join(sorted(alleles))


def parse_vcf_genotypes(text: str):
    """Set of (chrom, pos:int, ref, alt, normalised GT) from a VCF, using the first sample column."""
    out = set()
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        c = line.split("\t")
        if len(c) < 10:
            continue
        chrom, pos, ref, alt, fmt, sample = c[0], c[1], c[3], c[4], c[8], c[9]
        keys = fmt.split(":")
        vals = sample.split(":")
        gt = vals[keys.index("GT")] if "GT" in keys else vals[0]
        out.add((chrom, int(pos), ref, alt, normalise_gt(gt)))
    return out


def genotype_identical(a_text: str, b_text: str) -> dict:
    a, b = parse_vcf_genotypes(a_text), parse_vcf_genotypes(b_text)
    only_a, only_b = a - b, b - a
    return {"identical": not only_a and not only_b,
            "only_a": len(only_a), "only_b": len(only_b),
            "shared": len(a & b)}


def _sha256(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for blk in iter(lambda: fh.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()


def byte_identical(path_a, path_b) -> bool:
    return _sha256(path_a) == _sha256(path_b)


def same_pins(prov_a: dict, prov_b: dict) -> bool:
    return all(prov_a.get(k) == prov_b.get(k) for k in _PIN_FIELDS)


def enforce(run_a: dict, run_b: dict, mode: str = "genotype") -> dict:
    """run_x = {"vcf": <text> or path, "provenance": <pins dict>}. Returns a reproducibility verdict.
    Pins must match first; then output identity is checked in the chosen mode."""
    if not same_pins(run_a.get("provenance", {}), run_b.get("provenance", {})):
        return {"reproducible": False, "reason": "pin_mismatch", "mode": mode}
    if mode == "byte":
        ok = byte_identical(run_a["vcf"], run_b["vcf"])
        return {"reproducible": ok, "reason": None if ok else "byte_diff", "mode": mode}
    g = genotype_identical(run_a["vcf"], run_b["vcf"])
    return {"reproducible": g["identical"], "reason": None if g["identical"] else "genotype_diff",
            "mode": mode, "detail": g}
