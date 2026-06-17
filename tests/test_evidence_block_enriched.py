"""TDD for the enriched evidence block (acquisition arm Condition B rendering).

Condition A (thin) must render BYTE-IDENTICALLY to the pre-acquisition pilot so the baseline stays
bit-for-bit reproducible; the acquisition difference lives entirely in the evidence payload, never
in the prompt template. Condition B additionally renders the in-silico predictors and the single
calibrated PP3/BP4 recommendation (with its strength_basis citation).
"""
from __future__ import annotations

import gradient_runner as G


THIN = {"variant_id": "V1",
        "genomic_context": {"chrom": "1", "pos": 100, "ref": "A", "alt": "T", "build": "GRCh38", "gene": "GENEX"},
        "evidence_context": {"molecular_consequence": "missense_variant", "population_max_af": 1e-5}}

ENRICHED = {"variant_id": "V2",
            "genomic_context": THIN["genomic_context"],
            "evidence_context": {
                "molecular_consequence": "missense_variant", "population_max_af": 1e-5,
                "protein_change": "p.R175H", "transcript_id": "ENST_canon", "mane_select": "NM_9.9",
                "in_silico": {
                    "revel": 0.95, "revel_acmg": {"code": "PP3", "strength": "strong",
                                                  "basis": "REVEL=0.95 -> PP3 strong (Pejaver 2022, ClinGen SVI, PMID 36413997)"},
                    "alphamissense_class": "likely_pathogenic", "alphamissense_score": 0.99,
                    "cadd_phred": 32.0, "sift_prediction": "deleterious", "sift_score": 0.0,
                    "polyphen_prediction": "probably_damaging", "polyphen_score": 0.98},
                "in_silico_note": ("ClinGen SVI: apply PP3/BP4 from a SINGLE calibrated predictor "
                                   "(REVEL, see revel_acmg). Strength upgrades require strength_basis.")}}


def test_thin_block_is_byte_identical_to_legacy_format():
    # the exact two-line block the pre-acquisition pilot produced
    expected = ("  molecular_consequence: missense_variant\n"
                "  population_max_allele_frequency: 1e-05")
    assert G._evidence_block(THIN) == expected


def test_thin_prompt_unchanged_for_skill_execution():
    # Condition A skill_execution prompt must not change shape when no enrichment is present
    p = G.build_prompt("skill_execution", THIN)
    # "in_silico" appears in the base template as a source_type option; the enrichment-specific
    # markers must NOT appear for a thin variant
    assert "in_silico_predictors" not in p
    assert "REVEL" not in p
    assert "molecular_consequence: missense_variant" in p


def test_enriched_block_carries_calibrated_recommendation():
    block = G._evidence_block(ENRICHED)
    # thin lines still present
    assert "molecular_consequence: missense_variant" in block
    assert "population_max_allele_frequency: 1e-05" in block
    # in-silico predictors rendered
    assert "REVEL" in block and "0.95" in block
    assert "PP3" in block and "strong" in block
    assert "Pejaver 2022" in block  # strength_basis citation available to the model
    # PP3 strong is an upgrade -> the block makes copying strength_basis mechanical
    assert "strength_basis" in block
    assert "AlphaMissense" in block and "likely_pathogenic" in block
    assert "CADD" in block
    assert "p.R175H" in block
    # single-predictor guidance present
    assert "single" in block.lower() or "SINGLE" in block


def test_pm2_strength_note_renders_when_present():
    v = {"evidence_context": {"molecular_consequence": "missense_variant", "population_max_af": None,
                              "in_silico": {"revel": 0.95, "revel_acmg": {"code": "PP3", "strength": "strong",
                                                                          "basis": "REVEL=0.95"}},
                              "pm2_strength_note": "PM2: absence supports the moderate 2015 baseline here."}}
    block = G._evidence_block(v)
    assert "moderate 2015 baseline" in block
    assert "PM2" in block


def test_pm2_strength_note_absent_for_plain_enriched():
    v = {"evidence_context": {"molecular_consequence": "missense_variant", "population_max_af": None,
                              "in_silico": {"revel": 0.95, "revel_acmg": {"code": "PP3", "strength": "strong",
                                                                          "basis": "REVEL=0.95"}}}}
    block = G._evidence_block(v)
    assert "2015 baseline" not in block


def test_enriched_indeterminate_revel_states_no_call():
    v = {"evidence_context": {"molecular_consequence": "missense_variant", "population_max_af": None,
                              "in_silico": {"revel": 0.5, "revel_acmg": None,
                                            "alphamissense_class": "ambiguous", "alphamissense_score": 0.5,
                                            "cadd_phred": 12.0}}}
    block = G._evidence_block(v)
    assert "REVEL" in block and "0.5" in block
    # makes clear no calibrated PP3/BP4 is licensed
    assert "no calibrated" in block.lower() or "indeterminate" in block.lower()
