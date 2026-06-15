"""Benchmark qualification panel: stratify the held-out variants by ACMG automatability.

A held-out set is not homogeneous. Some variants are reachable to their truth class from purely
structured, NON-ClinVar evidence; others fundamentally require human-level evidence (segregation,
functional studies, literature). Conflating them invites the reviewer question "are these informative
cases or VUS-by-default?". This module tiers each variant from its ClinVar molecular consequence (MC)
and population allele frequency, so performance can be read per tier and a drop in Tier C localises
to evidence ACQUISITION, not execution.

Tier A (fully automatable): LoF consequence (PVS1) OR common (BA1, AF>=5%).
Tier B (partially automatable): missense / inframe / protein-altering (PM2 + PP3/BP4) OR BS1 (1-5%).
Tier C (human-level evidence): synonymous / intronic / UTR / non-coding / underdetermined.
ClinVar-assertion criteria (PS1/PM5/PP5/BP6) are deliberately NOT counted as available, because they
are blinded in primary mode. No side effects at import.
"""
from __future__ import annotations

# Molecular-consequence severity, most -> least severe (ClinVar MC term vocabulary).
_SEVERITY = [
    "nonsense", "stop_gained", "frameshift_variant",
    "splice_acceptor_variant", "splice_donor_variant",
    "initiator_codon_variant", "start_lost", "stop_lost",
    "inframe_insertion", "inframe_deletion", "protein_altering_variant",
    "missense_variant", "splice_region_variant", "synonymous_variant",
    "5_prime_UTR_variant", "3_prime_UTR_variant",
    "intron_variant", "non-coding_transcript_variant",
    "genic_upstream_transcript_variant", "genic_downstream_transcript_variant",
    "no_sequence_alteration",
]
_RANK = {t: i for i, t in enumerate(_SEVERITY)}

_LOF = frozenset({"nonsense", "stop_gained", "frameshift_variant",
                  "splice_acceptor_variant", "splice_donor_variant",
                  "initiator_codon_variant", "start_lost"})
_INTERPRETED = frozenset({"missense_variant", "inframe_insertion", "inframe_deletion",
                          "protein_altering_variant", "stop_lost", "splice_region_variant"})

EXPECTED_CEILING = {"A": "high", "B": "moderate", "C": "lower"}
TIER_RULE = ("A: AF>=5% (BA1) or LoF consequence (PVS1). "
             "B: 1%<=AF<5% (BS1) or missense/inframe/protein-altering. "
             "C: synonymous/intronic/UTR/non-coding/underdetermined. "
             "ClinVar-assertion criteria (PS1/PM5/PP5/BP6) excluded (blinded in primary mode).")


def varid_to_int(variant_id) -> int | None:
    if variant_id is None:
        return None
    s = str(variant_id).upper().replace("VCV", "").lstrip("0") or "0"
    return int(s) if s.isdigit() else None


def most_severe_consequence(mc_field) -> str | None:
    if not mc_field:
        return None
    terms = []
    for item in str(mc_field).split(","):
        term = item.split("|")[-1].strip()
        if term:
            terms.append(term)
    if not terms:
        return None
    return min(terms, key=lambda t: _RANK.get(t, len(_SEVERITY) + 1))


def parse_af(info: dict) -> float | None:
    vals = []
    for k in ("AF_ESP", "AF_EXAC", "AF_TGP"):
        v = info.get(k)
        if v not in (None, "", "."):
            try:
                vals.append(float(v))
            except ValueError:
                pass
    return max(vals) if vals else None


def assign_tier(consequence, max_af):
    if max_af is not None and max_af >= 0.05:
        return ("A", "BA1_common_af>=5%")
    if consequence in _LOF:
        return ("A", f"PVS1_{consequence}")
    if max_af is not None and max_af >= 0.01:
        return ("B", "BS1_af>=1%")
    if consequence in _INTERPRETED:
        return ("B", f"interpreted_{consequence}")
    return ("C", f"human_evidence_{consequence or 'unknown'}")


def parse_info(info_str: str) -> dict:
    out = {}
    for item in info_str.split(";"):
        if "=" in item:
            k, v = item.split("=", 1)
            out[k] = v
    return out


def iter_clinvar_vcf(path):
    """Stream (variation_id:int, consequence, max_af, clnvc) from a ClinVar VCF (ID col = VariationID)."""
    import gzip
    opener = gzip.open if str(path).endswith(".gz") else open
    with opener(path, "rt") as fh:
        for line in fh:
            if line.startswith("#"):
                continue
            cols = line.rstrip("\n").split("\t")
            if len(cols) < 8 or not cols[2].isdigit():
                continue
            info = parse_info(cols[7])
            yield (int(cols[2]), most_severe_consequence(info.get("MC")),
                   parse_af(info), info.get("CLNVC"))


def features_from_vcf(path, wanted_ids: set[int]) -> dict:
    feats = {}
    for vid, consequence, max_af, clnvc in iter_clinvar_vcf(path):
        if vid in wanted_ids:
            feats[vid] = {"consequence": consequence, "max_af": max_af, "clnvc": clnvc}
    return feats


def build_panel(manifest: dict, features_by_varid: dict) -> dict:
    counts = {"A": 0, "B": 0, "C": 0}
    by_tier_class: dict[str, dict[str, int]] = {"A": {}, "B": {}, "C": {}}
    unknown = 0
    out_variants = []

    for v in manifest.get("variants", []):
        vid = varid_to_int(v["variant_id"])
        feat = features_by_varid.get(vid)
        consequence = feat["consequence"] if feat else None
        max_af = feat["max_af"] if feat else None
        tier, reason = assign_tier(consequence, max_af)
        if consequence is None:
            unknown += 1
        counts[tier] += 1
        clnsig = v.get("truth", {}).get("clnsig")
        by_tier_class[tier][clnsig] = by_tier_class[tier].get(clnsig, 0) + 1
        out_variants.append({
            "variant_id": v["variant_id"],
            "gene": v.get("genomic_context", {}).get("gene"),
            "clnsig": clnsig,
            "review_stars": v.get("truth", {}).get("review_stars"),
            "reclassified": v.get("reclassified", False),
            "consequence": consequence,
            "max_af": max_af,
            "in_clinvar_vcf": feat is not None,
            "tier": tier,
            "tier_reason": reason,
        })

    return {
        "version": "qualification_panel_v1",
        "source_manifest_content_hash": manifest.get("content_hash"),
        "tier_rule": TIER_RULE,
        "expected_ceiling": EXPECTED_CEILING,
        "counts": counts,
        "unknown_consequence": unknown,
        "by_tier_class": by_tier_class,
        "variants": out_variants,
    }


def select_pilot(panel: dict, per_class_cap: int = 80, tier: str = "A") -> list[dict]:
    """Deterministic, class-stratified pilot from one tier (a non-trivial class mix)."""
    by_class: dict[str, list] = {}
    for v in panel["variants"]:
        if v["tier"] == tier:
            by_class.setdefault(v["clnsig"], []).append(v)
    picked = []
    for clnsig in sorted(by_class):
        picked += sorted(by_class[clnsig], key=lambda v: v["variant_id"])[:per_class_cap]
    return sorted(picked, key=lambda v: (v["clnsig"], v["variant_id"]))
