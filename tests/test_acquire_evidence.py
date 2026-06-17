"""TDD for the oracle acquisition module.

Condition B ("agentic fetch") of the acquisition arm. The oracle deterministically retrieves REAL
non-ClinVar evidence (VEP: consequence detail, SIFT/PolyPhen/CADD/AlphaMissense, REVEL; protein
change; transcript context) and assembles an enriched evidence_context. It measures the CEILING of
acquisition: complete, real evidence, so a null result cannot be blamed on weak retrieval.

Two invariants are tested hard:
  1. The PP3/BP4 strength recommendation follows the ClinGen SVI calibration of a SINGLE predictor
     (REVEL, Pejaver 2022, PMID 36413997). Other predictors are corroborating context only.
  2. No ClinVar / clinical-significance field can survive into the evidence_context (truth-leakage).
"""
from __future__ import annotations

import acquire_evidence as Q


# ---- REVEL -> ACMG calibration (Pejaver 2022 SVI bidirectional thresholds) ------
def test_revel_pathogenic_strength_bands():
    assert Q.revel_to_acmg(0.95)["code"] == "PP3"
    assert Q.revel_to_acmg(0.95)["strength"] == "strong"
    assert Q.revel_to_acmg(0.80)["strength"] == "moderate"
    assert Q.revel_to_acmg(0.65)["strength"] == "supporting"
    assert Q.revel_to_acmg(0.65)["code"] == "PP3"


def test_revel_benign_strength_bands():
    assert Q.revel_to_acmg(0.20)["code"] == "BP4"
    assert Q.revel_to_acmg(0.20)["strength"] == "supporting"
    assert Q.revel_to_acmg(0.10)["strength"] == "supporting"  # benign-moderate band collapses (no BP4 moderate in 2015)
    assert Q.revel_to_acmg(0.01)["strength"] == "strong"
    assert Q.revel_to_acmg(0.01)["code"] == "BP4"


def test_revel_indeterminate_and_missing_return_none():
    assert Q.revel_to_acmg(0.50) is None
    assert Q.revel_to_acmg(0.643) is None
    assert Q.revel_to_acmg(None) is None


def test_revel_boundaries_inclusive():
    assert Q.revel_to_acmg(0.932)["strength"] == "strong"
    assert Q.revel_to_acmg(0.773)["strength"] == "moderate"
    assert Q.revel_to_acmg(0.644)["strength"] == "supporting"
    assert Q.revel_to_acmg(0.290)["code"] == "BP4"
    assert Q.revel_to_acmg(0.016)["strength"] == "strong"


def test_revel_call_carries_basis_citation():
    call = Q.revel_to_acmg(0.95)
    assert "REVEL" in call["basis"] and "0.95" in call["basis"]
    assert "Pejaver" in call["basis"]


# ---- canonical transcript selection --------------------------------------------
def test_pick_canonical_prefers_canonical_flag():
    tcs = [{"transcript_id": "X", "consequence_terms": ["missense_variant"]},
           {"transcript_id": "Y", "canonical": 1, "consequence_terms": ["missense_variant"]}]
    assert Q.pick_canonical_consequence(tcs)["transcript_id"] == "Y"


def test_pick_canonical_falls_back_to_mane_then_first_missense():
    tcs = [{"transcript_id": "X", "consequence_terms": ["intron_variant"]},
           {"transcript_id": "Y", "mane_select": "NM_1", "consequence_terms": ["missense_variant"]}]
    assert Q.pick_canonical_consequence(tcs)["transcript_id"] == "Y"
    tcs2 = [{"transcript_id": "Z", "consequence_terms": ["missense_variant"]}]
    assert Q.pick_canonical_consequence(tcs2)["transcript_id"] == "Z"
    assert Q.pick_canonical_consequence([]) is None


# ---- ClinVar / truth-leakage scrubbing -----------------------------------------
def test_scrub_removes_clinvar_significance_everywhere():
    rec = {"transcript_consequences": [{"transcript_id": "X", "consequence_terms": ["missense_variant"]}],
           "colocated_variants": [{"id": "rs1", "clin_sig": ["pathogenic"], "clin_sig_allele": "A:pathogenic"},
                                  {"id": "VCV000001", "var_synonyms": {"ClinVar": ["VCV1"]}}]}
    scrubbed = Q.scrub_clinvar(rec)
    blob = repr(scrubbed).lower()
    assert "clin_sig" not in blob
    assert "pathogenic" not in blob
    assert "clinvar" not in blob
    assert "vcv" not in blob
    # legitimate VEP content survives
    assert scrubbed["transcript_consequences"][0]["transcript_id"] == "X"


# ---- enriched evidence_context assembly ----------------------------------------
def _fake_vep(*, revel=0.95, am=("likely_pathogenic", 0.99)):
    return {"transcript_consequences": [{
        "transcript_id": "ENST_canon", "canonical": 1, "mane_select": "NM_9.9",
        "gene_symbol": "GENEX", "consequence_terms": ["missense_variant"],
        "amino_acids": "R/H", "protein_start": 175,
        "sift_score": 0.0, "sift_prediction": "deleterious",
        "polyphen_score": 0.98, "polyphen_prediction": "probably_damaging",
        "cadd_phred": 32.0, "revel": revel,
        "alphamissense": {"am_class": am[0], "am_pathogenicity": am[1]},
    }]}


def test_build_evidence_context_preserves_thin_and_adds_insilico():
    thin = {"molecular_consequence": "missense_variant", "population_max_af": 1e-5}
    tc = Q.pick_canonical_consequence(_fake_vep()["transcript_consequences"])
    ev = Q.build_evidence_context(thin, tc)
    # thin fields preserved exactly (Condition A subset still present)
    assert ev["molecular_consequence"] == "missense_variant"
    assert ev["population_max_af"] == 1e-5
    # in-silico block present and real
    ins = ev["in_silico"]
    assert ins["revel"] == 0.95
    assert ins["revel_acmg"]["code"] == "PP3" and ins["revel_acmg"]["strength"] == "strong"
    assert ins["alphamissense_class"] == "likely_pathogenic"
    assert ins["cadd_phred"] == 32.0
    # protein context
    assert ev["protein_change"] == "p.R175H"
    assert ev["transcript_id"] == "ENST_canon"
    # single-predictor guidance is explicit
    assert "single" in ev["in_silico_note"].lower()
    # the model is told how to express a licensed strength upgrade (else fail-closed rejects it)
    assert "strength_basis" in ev["in_silico_note"]


def test_acquire_one_orchestrates_and_is_leakage_free():
    variant = {"variant_id": "V1",
               "genomic_context": {"chrom": "1", "pos": 100, "ref": "A", "alt": "T",
                                   "build": "GRCh38", "gene": "GENEX"},
               "evidence_context": {"molecular_consequence": "missense_variant", "population_max_af": None},
               "truth": {"clnsig": "Pathogenic"}}
    enriched = Q.acquire_one(variant, fetch=lambda *a, **k: _fake_vep())
    assert enriched["evidence_context"]["in_silico"]["revel"] == 0.95
    assert enriched["acquisition"]["fetched"] is True
    # truth is never echoed into evidence_context
    assert "clnsig" not in repr(enriched["evidence_context"]).lower()
    # the original thin variant is not mutated
    assert "in_silico" not in variant["evidence_context"]


def test_acquire_one_handles_no_missense_consequence_gracefully():
    variant = {"variant_id": "V2",
               "genomic_context": {"chrom": "1", "pos": 100, "ref": "A", "alt": "T",
                                   "build": "GRCh38", "gene": "GENEX"},
               "evidence_context": {"molecular_consequence": "missense_variant", "population_max_af": None},
               "truth": {"clnsig": "Pathogenic"}}
    enriched = Q.acquire_one(variant, fetch=lambda *a, **k: {"transcript_consequences": []})
    assert enriched["acquisition"]["fetched"] is False
    # falls back to thin evidence_context (no in_silico)
    assert "in_silico" not in enriched["evidence_context"]
