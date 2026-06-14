"""Fail-closed tests: one per threat-model case from the acmg-evidence-contract workflow.

Core invariant: a model may PROPOSE evidence but may not smuggle classification,
circular ClinVar/truth assertions, unsupported strength changes, or malformed ACMG
logic into the execution path. Each test asserts the submission is rejected with the
correct machine-readable error_code.
"""
from __future__ import annotations

import copy

from validate_evidence import validate_evidence, validate_evidence_json
from test_evidence_schema import valid_submission


def codes(result) -> set[str]:
    return {e["error_code"] for e in result["errors"]}


def reject(sub, expected, expected_mode=None):
    r = validate_evidence(sub, expected_mode=expected_mode)
    assert r["valid"] is False
    assert expected in codes(r), f"expected {expected}, got {codes(r)}"
    assert r["normalized"] is None and r["content_hash"] is None
    return r


# ---- Rule 1: no model-supplied classification ----------------------------------
def test_classification_top_level_field():
    sub = valid_submission()
    sub["classification"] = "Pathogenic"
    reject(sub, "MODEL_SUPPLIED_CLASSIFICATION")


def test_classification_in_rationale():
    sub = valid_submission()
    sub["submitted_evidence_codes"][0]["rationale"] = (
        "Absent from gnomAD. Therefore the FINAL CLASSIFICATION is Likely Pathogenic (class 4).")
    reject(sub, "MODEL_SUPPLIED_CLASSIFICATION")


def test_classification_extra_toplevel_keys():
    sub = valid_submission()
    sub["acmg_class"] = 4
    sub["final_call"] = "LP"
    reject(sub, "MODEL_SUPPLIED_CLASSIFICATION")


def test_classification_per_evidence_extra_key():
    sub = valid_submission()
    sub["submitted_evidence_codes"][0]["implied_class"] = "Pathogenic"
    sub["submitted_evidence_codes"][0]["suggested_tier"] = 5
    reject(sub, "MODEL_SUPPLIED_CLASSIFICATION")


# ---- Rule 2: no ClinVar / truth-label evidence in primary mode -----------------
def test_pp5_blocked_in_blinded():
    sub = valid_submission()
    sub["submitted_evidence_codes"].append(
        {"code": "PP5", "strength": "supporting", "source_type": "literature",
         "source_id": "PMID:99999999", "rationale": "reputable source reports pathogenic", "confidence": 0.8})
    reject(sub, "DISALLOWED_CLINVAR_CRITERION")


def test_bp6_blocked_in_blinded():
    sub = valid_submission()
    sub["submitted_evidence_codes"].append(
        {"code": "BP6", "strength": "supporting", "source_type": "database",
         "source_id": "db", "rationale": "reputable source reports benign", "confidence": 0.7})
    reject(sub, "DISALLOWED_CLINVAR_CRITERION")


def test_source_type_clinvar_on_any_code_blocked():
    sub = valid_submission()
    sub["submitted_evidence_codes"].append(
        {"code": "PS4", "strength": "strong", "source_type": "clinvar",
         "source_id": "VCV000012345", "rationale": "case-control enrichment", "confidence": 0.85})
    reject(sub, "DISALLOWED_CLINVAR_CRITERION")


def test_ps1_from_clinvar_blocked():
    sub = valid_submission()
    sub["submitted_evidence_codes"].append(
        {"code": "PS1", "strength": "strong", "source_type": "clinvar",
         "source_id": "RCV000054321", "rationale": "same amino acid change established pathogenic", "confidence": 0.9})
    reject(sub, "DISALLOWED_CLINVAR_CRITERION")


def test_pm5_from_clinvar_blocked():
    sub = valid_submission()
    sub["submitted_evidence_codes"].append(
        {"code": "PM5", "strength": "moderate", "source_type": "clinvar",
         "source_id": "VCV000067890", "rationale": "different pathogenic change at residue", "confidence": 0.75})
    reject(sub, "DISALLOWED_CLINVAR_CRITERION")


def test_clinvar_relabelled_as_literature_blocked():
    sub = valid_submission()
    sub["submitted_evidence_codes"].append(
        {"code": "PS1", "strength": "strong", "source_type": "literature",
         "source_id": "ClinVar VCV000012345", "rationale": "per ClinVar this AA change is pathogenic", "confidence": 0.9})
    reject(sub, "DISALLOWED_CLINVAR_CRITERION")


def test_truth_label_leakage_non_clinvar_source():
    # truth source is LOVD; evidence sourced from LOVD is circular -> general leakage error
    sub = valid_submission(truth="lovd")
    sub["submitted_evidence_codes"].append(
        {"code": "PS4", "strength": "strong", "source_type": "lovd",
         "source_id": "LOVD-0001", "rationale": "prevalence per LOVD shared dataset", "confidence": 0.8})
    reject(sub, "TRUTH_LABEL_LEAKAGE")


# ---- Rule 4: invalid codes -----------------------------------------------------
def test_invalid_acmg_code():
    sub = valid_submission()
    sub["submitted_evidence_codes"][0]["code"] = "PX9"
    reject(sub, "INVALID_ACMG_CODE")


def test_noncanonical_code_token_is_structural():
    sub = valid_submission()
    sub["submitted_evidence_codes"][0]["code"] = "pm 2"
    reject(sub, "SCHEMA_STRUCTURE")


# ---- Rule 5: unsupported strength upgrades --------------------------------------
def test_pm2_upgraded_to_strong():
    sub = valid_submission()
    sub["submitted_evidence_codes"][0]["strength"] = "strong"  # PM2 cap is moderate
    reject(sub, "UNSUPPORTED_STRENGTH_UPGRADE")


def test_pp3_to_moderate_without_basis():
    sub = valid_submission()
    sub["submitted_evidence_codes"][1]["strength"] = "moderate"  # PP3 upgrade needs basis
    reject(sub, "UNSUPPORTED_STRENGTH_UPGRADE")


def test_direction_flip_rationale():
    sub = valid_submission()
    sub["submitted_evidence_codes"][1] = {
        "code": "BP4", "strength": "supporting", "source_type": "in_silico",
        "source_id": "REVEL:0.95", "rationale": "in silico supports pathogenic; counting BP4 toward pathogenic",
        "confidence": 0.8}
    reject(sub, "DIRECTION_OVERRIDE")


# ---- Rule 6: well-formed / serialisable / hashable -----------------------------
def test_confidence_too_high():
    sub = valid_submission()
    sub["submitted_evidence_codes"][0]["confidence"] = 1.5
    reject(sub, "CONFIDENCE_OUT_OF_RANGE")


def test_confidence_negative():
    sub = valid_submission()
    sub["submitted_evidence_codes"][0]["confidence"] = -0.2
    reject(sub, "CONFIDENCE_OUT_OF_RANGE")


def test_confidence_wrong_type_is_structural():
    sub = valid_submission()
    sub["submitted_evidence_codes"][0]["confidence"] = "high"
    reject(sub, "SCHEMA_STRUCTURE")


def test_confidence_nan_json():
    text = (
        '{"variant_id":"v","genomic_context":{"chrom":"1","pos":1,"ref":"A","alt":"G","build":"GRCh38"},'
        '"submitted_evidence_codes":[{"code":"PM2","strength":"moderate","source_type":"population_frequency",'
        '"source_id":"gnomAD","rationale":"absent","confidence":NaN}],"abstentions":[],'
        '"benchmark_mode":"clinvar_blinded","clinvar_blinded_status":true,"benchmark_truth_source":"clinvar"}')
    r = validate_evidence_json(text)
    assert not r["valid"] and "NON_SERIALISABLE_VALUE" in codes(r)


def test_infinity_nested_in_rationale_json():
    text = (
        '{"variant_id":"v","genomic_context":{"chrom":"1","pos":1,"ref":"A","alt":"G","build":"GRCh38"},'
        '"submitted_evidence_codes":[{"code":"PM2","strength":"moderate","source_type":"population_frequency",'
        '"source_id":"gnomAD","rationale":{"nested":[Infinity]},"confidence":0.7}],"abstentions":[],'
        '"benchmark_mode":"clinvar_blinded","clinvar_blinded_status":true,"benchmark_truth_source":"clinvar"}')
    r = validate_evidence_json(text)
    assert not r["valid"] and "NON_SERIALISABLE_VALUE" in codes(r)


def test_duplicate_top_level_keys_json():
    text = (
        '{"variant_id":"v","genomic_context":{"chrom":"1","pos":1,"ref":"A","alt":"G","build":"GRCh38"},'
        '"submitted_evidence_codes":[],"submitted_evidence_codes":[{"code":"PS1","strength":"strong",'
        '"source_type":"clinvar","source_id":"VCV1","rationale":"x","confidence":0.9}],"abstentions":[],'
        '"benchmark_mode":"clinvar_blinded","clinvar_blinded_status":true,"benchmark_truth_source":"clinvar"}')
    r = validate_evidence_json(text)
    assert not r["valid"] and "DUPLICATE_KEY" in codes(r)


def test_duplicate_codes_conflicting_strength():
    sub = valid_submission()
    sub["submitted_evidence_codes"] = [
        {"code": "PM2", "strength": "moderate", "source_type": "population_frequency",
         "source_id": "gnomAD", "rationale": "absent", "confidence": 0.7},
        {"code": "PM2", "strength": "supporting", "source_type": "population_frequency",
         "source_id": "gnomAD", "rationale": "absent", "confidence": 0.6},
    ]
    reject(sub, "DUPLICATE_CODE")


def test_duplicate_codes_identical():
    sub = valid_submission()
    item = {"code": "PP3", "strength": "supporting", "source_type": "in_silico",
            "source_id": "REVEL:0.9", "rationale": "deleterious", "confidence": 0.8}
    sub["submitted_evidence_codes"] = [item, copy.deepcopy(item)]
    reject(sub, "DUPLICATE_CODE")


def test_payload_not_object_json():
    r = validate_evidence_json('[{"code":"PM2"}]')
    assert not r["valid"] and "PARSE_ERROR" in codes(r)


def test_non_finite_via_overflow_json():
    text = (
        '{"variant_id":"v","genomic_context":{"chrom":"1","pos":1,"ref":"A","alt":"G","build":"GRCh38"},'
        '"submitted_evidence_codes":[{"code":"PM2","strength":"moderate","source_type":"population_frequency",'
        '"source_id":"gnomAD","rationale":"absent","confidence":1e400}],"abstentions":[],'
        '"benchmark_mode":"clinvar_blinded","clinvar_blinded_status":true,"benchmark_truth_source":"clinvar"}')
    r = validate_evidence_json(text)
    assert not r["valid"] and "NON_SERIALISABLE_VALUE" in codes(r)


# ---- Rule 3: abstentions -------------------------------------------------------
def test_code_asserted_and_abstained():
    sub = valid_submission()
    sub["abstentions"] = [{"code": "PM2", "rationale": "also abstaining"}]
    reject(sub, "ABSTENTION_CONFLICTS_WITH_ASSERTION")


def test_malformed_abstention_missing_code():
    sub = valid_submission()
    sub["abstentions"] = [{"rationale": "not sure"}]
    reject(sub, "MALFORMED_ABSTENTION")


def test_abstention_on_invalid_code():
    sub = valid_submission()
    sub["abstentions"] = [{"code": "PZ7", "rationale": "abstaining on a fake code"}]
    reject(sub, "INVALID_ACMG_CODE")


def test_abstention_on_clinvar_code_in_blinded():
    sub = valid_submission()
    sub["abstentions"] = [{"code": "PP5", "rationale": "abstaining on reputable-source code"}]
    reject(sub, "DISALLOWED_CLINVAR_CRITERION")


# ---- mode integrity ------------------------------------------------------------
def test_mode_status_mismatch():
    sub = valid_submission()
    sub["clinvar_blinded_status"] = False  # contradicts clinvar_blinded
    reject(sub, "MODE_STATUS_MISMATCH")


def test_forged_mode_vs_harness():
    sub = valid_submission(mode="clinvar_unblinded_sensitivity", truth=None)
    reject(sub, "MODE_STATUS_MISMATCH", expected_mode="clinvar_blinded")


def test_invalid_strength_enum_is_structural():
    sub = valid_submission()
    sub["submitted_evidence_codes"][0]["strength"] = "super_strong"
    reject(sub, "SCHEMA_STRUCTURE")


# ---- completeness / provenance -------------------------------------------------
def test_missing_evidence_field_is_structural():
    sub = valid_submission()
    del sub["submitted_evidence_codes"]
    reject(sub, "SCHEMA_STRUCTURE")


def test_both_empty_is_nonresponse():
    sub = valid_submission()
    sub["submitted_evidence_codes"] = []
    sub["abstentions"] = []
    reject(sub, "EMPTY_NONRESPONSE")


def test_empty_source_id():
    sub = valid_submission()
    sub["submitted_evidence_codes"][0]["source_id"] = "   "
    reject(sub, "EMPTY_SOURCE_ID")


def test_code_source_type_incompatible():
    sub = valid_submission()
    sub["submitted_evidence_codes"][0] = {
        "code": "PM2", "strength": "moderate", "source_type": "functional",
        "source_id": "assay-7", "rationale": "allele frequency from wet-lab assay", "confidence": 0.7}
    reject(sub, "SOURCE_CODE_INCOMPATIBLE")


def test_truth_source_required_in_primary():
    sub = valid_submission(truth=None)  # clinvar_blinded but no truth source
    reject(sub, "TRUTH_SOURCE_REQUIRED")


def test_evidence_wrong_container_type():
    sub = valid_submission()
    sub["abstentions"] = "none"
    reject(sub, "SCHEMA_STRUCTURE")


def test_missing_evidence_subfield():
    sub = valid_submission()
    del sub["submitted_evidence_codes"][0]["source_id"]
    reject(sub, "SCHEMA_STRUCTURE")
