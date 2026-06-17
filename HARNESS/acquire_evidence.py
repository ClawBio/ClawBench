"""Oracle acquisition module: Condition B of the acquisition arm.

Deterministically retrieves REAL non-ClinVar evidence for each probe variant from Ensembl VEP REST
(consequence detail, SIFT/PolyPhen/CADD/AlphaMissense, REVEL, protein change, transcript context)
and assembles an enriched evidence_context. This is the CEILING of acquisition: complete, real
evidence, so a null result (no shrink in evidence_insufficient) cannot be blamed on weak retrieval.

Two hard invariants:
  1. The PP3/BP4 strength recommendation follows the ClinGen SVI calibration of a SINGLE predictor
     (REVEL, Pejaver et al. 2022, Am J Hum Genet, PMID 36413997). AlphaMissense/CADD/SIFT/PolyPhen
     are corroborating context only; ClinGen forbids stacking multiple in-silico predictors as
     independent PP3/BP4 lines.
  2. No ClinVar / clinical-significance field survives into the evidence_context (scrub_clinvar plus
     the downstream validator's leakage rules are belt-and-braces).

The truth label is never fetched or echoed. Network calls live behind an injectable `fetch`; the
pure logic is fully testable offline. No side effects at import; run main() to build the cache.

Run: python3 HARNESS/acquire_evidence.py
"""
from __future__ import annotations

import hashlib
import json
import re
import time
import urllib.request
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]

_VEP_URL = ("https://rest.ensembl.org/vep/human/region/{chrom}:{pos}-{pos}/{alt}"
            "?content-type=application/json&REVEL=1&AlphaMissense=1&CADD=1&canonical=1&mane=1")

# Pejaver et al. 2022 (PMID 36413997) ClinGen SVI bidirectional REVEL thresholds.
# Pathogenic (PP3): supporting >=0.644, moderate >=0.773, strong >=0.932.
# Benign (BP4): the 2015 framework has no benign-moderate level (vocab allows BP4 supporting|strong),
# so the published benign-moderate band (<=0.183) is collapsed into BP4 supporting; strong <=0.016.
_PP3 = ((0.932, "strong"), (0.773, "moderate"), (0.644, "supporting"))
_BP4_STRONG = 0.016
_BP4_SUPPORTING = 0.290
_REVEL_CITE = "Pejaver 2022, ClinGen SVI, PMID 36413997"

# Keys / markers that can carry ClinVar or clinical-significance provenance. Stripped recursively.
_CLINVAR_KEY = re.compile(r"(?i)(clin_sig|clinical_significance|clinvar|clnsig|var_synonyms|pubmed|phenotype)")
_CLINVAR_VAL = re.compile(r"(?i)(clinvar|\b(?:vcv|rcv|scv)[\s._-]*0*\d|pathogenic|benign|likely)")


def revel_to_acmg(revel):
    """Map a REVEL score to a single calibrated PP3/BP4 evidence line, or None if indeterminate
    or missing. Strength follows Pejaver 2022 (see module docstring)."""
    if revel is None:
        return None
    try:
        r = float(revel)
    except (TypeError, ValueError):
        return None
    for thr, strength in _PP3:
        if r >= thr:
            return {"code": "PP3", "strength": strength,
                    "basis": f"REVEL={r} -> PP3 {strength} ({_REVEL_CITE})"}
    if r <= _BP4_STRONG:
        return {"code": "BP4", "strength": "strong",
                "basis": f"REVEL={r} -> BP4 strong ({_REVEL_CITE})"}
    if r <= _BP4_SUPPORTING:
        return {"code": "BP4", "strength": "supporting",
                "basis": f"REVEL={r} -> BP4 supporting ({_REVEL_CITE})"}
    return None  # indeterminate zone 0.291..0.643


def pick_canonical_consequence(transcript_consequences):
    """Choose one representative consequence: canonical flag, else MANE Select, else first missense,
    else first present. Returns the consequence dict or None."""
    tcs = list(transcript_consequences or [])
    if not tcs:
        return None
    for t in tcs:
        if t.get("canonical") == 1:
            return t
    for t in tcs:
        if t.get("mane_select"):
            return t
    for t in tcs:
        if "missense_variant" in (t.get("consequence_terms") or []):
            return t
    return tcs[0]


def _scrub(obj):
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if _CLINVAR_KEY.search(str(k)):
                continue
            if isinstance(v, str) and _CLINVAR_VAL.search(v):
                continue
            out[k] = _scrub(v)
        return out
    if isinstance(obj, list):
        cleaned = [_scrub(v) for v in obj]
        return [v for v in cleaned
                if not (isinstance(v, str) and _CLINVAR_VAL.search(v))]
    return obj


def scrub_clinvar(vep_record: dict) -> dict:
    """Recursively strip any ClinVar / clinical-significance provenance from a VEP record before it
    can reach the model. Legitimate annotation fields (scores, predictions, transcript ids) survive."""
    return _scrub(vep_record)


def _protein_change(tc: dict):
    aa = tc.get("amino_acids")
    pos = tc.get("protein_start")
    if aa and pos is not None and "/" in str(aa):
        ref_aa, alt_aa = str(aa).split("/", 1)
        return f"p.{ref_aa}{pos}{alt_aa}"
    return None


def build_evidence_context(thin: dict, consequence: dict) -> dict:
    """Assemble the enriched evidence_context: the thin fields (consequence + AF) PLUS a real
    in-silico block with a single calibrated PP3/BP4 recommendation and corroborating predictors."""
    ev = {"molecular_consequence": thin.get("molecular_consequence"),
          "population_max_af": thin.get("population_max_af")}
    revel = consequence.get("revel")
    am = consequence.get("alphamissense") or {}
    ev["in_silico"] = {
        "revel": revel,
        "revel_acmg": revel_to_acmg(revel),
        "alphamissense_class": am.get("am_class"),
        "alphamissense_score": am.get("am_pathogenicity"),
        "cadd_phred": consequence.get("cadd_phred"),
        "sift_prediction": consequence.get("sift_prediction"),
        "sift_score": consequence.get("sift_score"),
        "polyphen_prediction": consequence.get("polyphen_prediction"),
        "polyphen_score": consequence.get("polyphen_score"),
    }
    ev["in_silico_note"] = ("ClinGen SVI: apply PP3/BP4 from a SINGLE calibrated predictor (REVEL, "
                            "see revel_acmg). The other predictors are corroborating context, not "
                            "independent PP3/BP4 lines. To apply PP3/BP4 above its supporting "
                            "baseline you MUST add a \"strength_basis\" field on that evidence code "
                            "citing the calibration, e.g. \"strength_basis\": \"REVEL=0.95, Pejaver "
                            "2022 PMID 36413997\"; without it the upgrade is rejected fail-closed.")
    pc = _protein_change(consequence)
    if pc:
        ev["protein_change"] = pc
    if consequence.get("transcript_id"):
        ev["transcript_id"] = consequence["transcript_id"]
    if consequence.get("mane_select"):
        ev["mane_select"] = consequence["mane_select"]
    return ev


def fetch_vep(chrom, pos, ref, alt, *, timeout=30, retries=4, sleep=time.sleep):
    """Live Ensembl VEP REST call (canonical/MANE + REVEL/AlphaMissense/CADD). Retries transient
    errors. Returns the parsed first record dict. Injectable in acquire_one for offline tests."""
    url = _VEP_URL.format(chrom=chrom, pos=pos, alt=alt)
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "clawbench-acquisition/1.0"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = json.loads(r.read().decode())
            return data[0] if isinstance(data, list) and data else {}
        except Exception as exc:  # noqa: BLE001
            last = exc
            if attempt < retries - 1:
                sleep(2.0 * (2 ** attempt))
                continue
            raise
    raise RuntimeError(str(last))


def acquire_one(variant: dict, *, fetch=fetch_vep) -> dict:
    """Fetch -> scrub -> pick canonical -> assemble enriched evidence_context. Returns a NEW variant
    dict (the thin input is not mutated). On no usable consequence, falls back to thin evidence."""
    gc = variant["genomic_context"]
    raw = fetch(gc["chrom"], gc["pos"], gc["ref"], gc["alt"])
    scrubbed = scrub_clinvar(raw or {})
    tc = pick_canonical_consequence(scrubbed.get("transcript_consequences"))
    enriched = {
        "variant_id": variant["variant_id"],
        "genomic_context": dict(gc),
        "truth": dict(variant.get("truth", {})),
        "tier": variant.get("tier", "B"),
    }
    if tc is None:
        enriched["evidence_context"] = dict(variant["evidence_context"])
        enriched["acquisition"] = {"fetched": False, "reason": "no_transcript_consequence"}
        return enriched
    enriched["evidence_context"] = build_evidence_context(variant["evidence_context"], tc)
    enriched["acquisition"] = {"fetched": True, "source": "ensembl_vep_rest",
                               "transcript_id": tc.get("transcript_id"),
                               "revel_acmg": enriched["evidence_context"]["in_silico"]["revel_acmg"]}
    return enriched


def main() -> None:
    probe = json.loads((_ROOT / "TRUTH/clinvar/acquisition_probe_v1.json").read_text())
    enriched = []
    for v in probe["variants"]:
        e = acquire_one(v)
        enriched.append(e)
        rc = e["acquisition"].get("revel_acmg")
        tag = f"{rc['code']} {rc['strength']}" if rc else ("indeterminate" if e["acquisition"]["fetched"] else "NO-FETCH")
        print(f"  {v['variant_id']:>16} {v['truth']['clnsig']:>18}  ->  {tag}")
        time.sleep(0.34)  # be polite to the public REST endpoint
    canonical = json.dumps([e["evidence_context"] for e in enriched], sort_keys=True, separators=(",", ":"))
    cache = {
        "schema_version": 1,
        "name": "acquisition_cache_v1",
        "source": "ensembl_vep_rest (REVEL, AlphaMissense, CADD; canonical/MANE)",
        "calibration": _REVEL_CITE,
        "probe_content_hash": probe["content_hash"],
        "content_hash": hashlib.sha256(canonical.encode()).hexdigest(),
        "variants": enriched,
    }
    out = _ROOT / "TRUTH/clinvar/acquisition_cache_v1.json"
    out.write_text(json.dumps(cache, indent=2))
    n_fetch = sum(1 for e in enriched if e["acquisition"]["fetched"])
    print(f"wrote {out.relative_to(_ROOT)}: {n_fetch}/{len(enriched)} fetched; "
          f"content_hash {cache['content_hash'][:16]}...")


if __name__ == "__main__":
    main()
