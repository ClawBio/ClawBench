"""Happy-path, structural, hashing and combiner-bridge tests for the evidence contract."""
from __future__ import annotations

import copy

import pytest

import acmg_vocabulary as voc
from validate_evidence import (
    ERROR_CODES,
    to_criteria,
    validate_evidence,
)
from acmg_engine import classify


def valid_submission(mode="clinvar_blinded", truth="clinvar"):
    sub = {
        "variant_id": "chr17-43045712-C-T",
        "genomic_context": {
            "chrom": "chr17", "pos": 43045712, "ref": "C", "alt": "T",
            "build": "GRCh38", "gene": "BRCA1", "consequence": "missense_variant",
        },
        "submitted_evidence_codes": [
            {"code": "PM2", "strength": "moderate", "source_type": "population_frequency",
             "source_id": "gnomAD:v4.1", "rationale": "absent from gnomAD", "confidence": 0.8},
            {"code": "PP3", "strength": "supporting", "source_type": "in_silico",
             "source_id": "REVEL:0.92", "rationale": "computational support for deleterious effect", "confidence": 0.7},
        ],
        "abstentions": [{"code": "PS3", "rationale": "no functional data available"}],
        "benchmark_mode": mode,
        "clinvar_blinded_status": voc.expected_blinded_status(mode),
    }
    if truth is not None:
        sub["benchmark_truth_source"] = truth
    return sub


# ---- vocabulary integrity ------------------------------------------------------
def test_vocab_has_28_codes():
    assert len(voc.VALID_CODES) == 28


def test_modulatable_codes_match_clingen_set():
    up = {c for c in voc.VALID_CODES if voc.is_modulatable_up(c)}
    assert up == {"PS2", "PM6", "PP1", "PP3", "PP4", "BP4"}


def test_clinvar_derived_codes():
    cv = {c for c in voc.VALID_CODES if voc.is_clinvar_derived(c)}
    assert cv == {"PS1", "PM5", "PP5", "BP6"}


# ---- happy path ----------------------------------------------------------------
def test_valid_submission_passes():
    r = validate_evidence(valid_submission())
    assert r["valid"] is True, r["errors"]
    assert r["errors"] == []
    assert isinstance(r["content_hash"], str) and len(r["content_hash"]) == 64


def test_sensitivity_mode_allows_clinvar_evidence():
    # control arm: PP5 is permitted because leakage checks are off
    sub = valid_submission(mode="clinvar_unblinded_sensitivity", truth=None)
    sub["submitted_evidence_codes"].append(
        {"code": "PP5", "strength": "supporting", "source_type": "clinvar",
         "source_id": "VCV000012345", "rationale": "reputable source reports pathogenic", "confidence": 0.6})
    r = validate_evidence(sub)
    assert r["valid"] is True, r["errors"]


def test_endorsed_strength_upgrade_with_basis_passes():
    sub = valid_submission()
    sub["submitted_evidence_codes"][1] = {
        "code": "PP3", "strength": "moderate", "source_type": "in_silico",
        "source_id": "REVEL:0.93", "rationale": "calibrated in silico support",
        "confidence": 0.8, "strength_basis": "Pejaver 2022 REVEL>=0.773 (PP3_Moderate)"}
    r = validate_evidence(sub)
    assert r["valid"] is True, r["errors"]


def test_dev_mode_optional_truth_source():
    sub = valid_submission(mode="dev", truth=None)
    r = validate_evidence(sub)
    assert r["valid"] is True, r["errors"]


# ---- determinism / hashing -----------------------------------------------------
def test_hash_is_order_invariant():
    a = valid_submission()
    b = copy.deepcopy(a)
    b["submitted_evidence_codes"].reverse()
    ra, rb = validate_evidence(a), validate_evidence(b)
    assert ra["valid"] and rb["valid"]
    assert ra["content_hash"] == rb["content_hash"]


def test_hash_changes_with_content():
    a = validate_evidence(valid_submission())
    c = valid_submission()
    c["submitted_evidence_codes"][0]["strength"] = "supporting"  # PM2 downgrade
    assert a["content_hash"] != validate_evidence(c)["content_hash"]


# ---- structural rejections (jsonschema layer) ----------------------------------
def test_missing_required_field_is_structural():
    sub = valid_submission()
    del sub["variant_id"]
    r = validate_evidence(sub)
    assert not r["valid"]
    assert any(e["error_code"] == "SCHEMA_STRUCTURE" for e in r["errors"])


def test_unknown_nonverdict_toplevel_key_is_structural():
    sub = valid_submission()
    sub["notes"] = "freeform"
    r = validate_evidence(sub)
    assert not r["valid"]
    assert any(e["error_code"] == "SCHEMA_STRUCTURE" for e in r["errors"])


def test_evidence_must_be_a_list():
    sub = valid_submission()
    sub["submitted_evidence_codes"] = sub["submitted_evidence_codes"][0]
    r = validate_evidence(sub)
    assert not r["valid"]
    assert any(e["error_code"] == "SCHEMA_STRUCTURE" for e in r["errors"])


# ---- combiner bridge -----------------------------------------------------------
def test_to_criteria_direction_from_vocab_then_classify():
    sub = valid_submission(mode="dev", truth=None)
    sub["submitted_evidence_codes"] = [
        {"code": "PVS1", "strength": "very_strong", "source_type": "computational",
         "source_id": "VEP", "rationale": "canonical splice null variant", "confidence": 0.95},
        {"code": "PS1", "strength": "strong", "source_type": "literature",
         "source_id": "PMID:12345678", "rationale": "same amino acid change established in literature", "confidence": 0.9},
    ]
    sub["abstentions"] = []
    r = validate_evidence(sub)
    assert r["valid"], r["errors"]
    criteria = to_criteria(sub)
    assert {c.code for c in criteria} == {"PVS1", "PS1"}
    assert all(c.direction == "pathogenic" for c in criteria)
    assert classify(criteria) == "Pathogenic"


def test_derived_truth_label_flag_false_for_clean_submission():
    r = validate_evidence(valid_submission())
    assert r["valid"], r["errors"]
    assert r["derived"]["any_source_is_truth_label"] is False


def test_derived_truth_label_flag_true_for_clinvar_evidence_in_control():
    # sensitivity mode permits ClinVar evidence; the derived check still flags it as truth-derived
    sub = valid_submission(mode="clinvar_unblinded_sensitivity", truth=None)
    sub["submitted_evidence_codes"].append(
        {"code": "PP5", "strength": "supporting", "source_type": "clinvar",
         "source_id": "VCV000012345", "rationale": "reputable source reports pathogenic", "confidence": 0.6})
    r = validate_evidence(sub)
    assert r["valid"], r["errors"]
    assert r["derived"]["any_source_is_truth_label"] is True
    assert r["derived"]["source_evidence_is_truth_label"]["PP5"] is True
    assert r["derived"]["source_evidence_is_truth_label"]["PM2"] is False


def test_error_codes_are_in_published_vocabulary():
    sub = valid_submission()
    sub["submitted_evidence_codes"][0]["confidence"] = 1.5
    r = validate_evidence(sub)
    for e in r["errors"]:
        assert e["error_code"] in ERROR_CODES
        assert set(e) == {"valid", "error_code", "field", "message"}
