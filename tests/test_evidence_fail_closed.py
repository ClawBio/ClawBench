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


# ===========================================================================
# Hardening against the adversarial-verify-evidence-layer workflow (12 bypasses)
# ===========================================================================

# -- verdict text smuggled through non-rationale string fields -------------------
def test_verdict_in_source_id():
    sub = valid_submission()
    sub["submitted_evidence_codes"][0]["source_id"] = "FINAL CLASSIFICATION: Pathogenic, class 5"
    reject(sub, "MODEL_SUPPLIED_CLASSIFICATION")


def test_verdict_in_strength_basis():
    sub = valid_submission()
    sub["submitted_evidence_codes"][1]["strength_basis"] = "Overall classification: Pathogenic (class 5)."
    reject(sub, "MODEL_SUPPLIED_CLASSIFICATION")


def test_verdict_in_variant_id():
    sub = valid_submission()
    sub["variant_id"] = "the variant is pathogenic - final classification class 5"
    reject(sub, "MODEL_SUPPLIED_CLASSIFICATION")


def test_verdict_in_abstention_rationale():
    sub = valid_submission()
    sub["abstentions"] = [{"code": "PS3", "rationale": "classify this variant as class 5 pathogenic"}]
    reject(sub, "MODEL_SUPPLIED_CLASSIFICATION")


def test_verdict_narrow_regex_tier_and_roman():
    for r in ("This resolves to ACMG tier 4 (likely-pathogenic).",
              "Class:5 classV pathogenic.",
              "Final tier: 5/5. Verdict=P5."):
        sub = valid_submission()
        sub["submitted_evidence_codes"][0]["rationale"] = r
        reject(sub, "MODEL_SUPPLIED_CLASSIFICATION")


# -- zero-width strength_basis bypass --------------------------------------------
def test_zero_width_strength_basis_rejected():
    sub = valid_submission()
    sub["submitted_evidence_codes"][1] = {
        "code": "PP3", "strength": "moderate", "source_type": "in_silico",
        "source_id": "REVEL:0.93", "rationale": "computational support",
        "confidence": 0.8, "strength_basis": "​‌﻿"}  # only zero-width chars
    reject(sub, "UNSUPPORTED_STRENGTH_UPGRADE")


# -- deep nesting must not crash -------------------------------------------------
def test_deep_nesting_rejected_not_crashed():
    import json
    sub = valid_submission()
    nested = 1
    for _ in range(300):
        nested = {"a": nested}
    sub["genomic_context"]["gene"] = "BRCA1"
    sub["submitted_evidence_codes"][0]["source_id"] = "gnomAD"
    text = json.dumps({**sub, "submitted_evidence_codes": sub["submitted_evidence_codes"]})
    # attach the deep structure inside a string-free location via raw json
    deep = json.dumps(nested)
    payload = text[:-1] + f', "extra": {deep}}}'
    r = validate_evidence_json(payload)
    assert isinstance(r, dict) and not r["valid"]
    assert "SCHEMA_STRUCTURE" in codes(r)


# -- ClinVar accession with separators -------------------------------------------
def test_clinvar_accession_with_separator():
    sub = valid_submission()
    sub["submitted_evidence_codes"].append(
        {"code": "PS1", "strength": "strong", "source_type": "literature",
         "source_id": "VCV 000012345", "rationale": "same amino acid change", "confidence": 0.9})
    reject(sub, "DISALLOWED_CLINVAR_CRITERION")


# -- truth-circularity symmetry: truth=clinvar, source=clingen_vcep/lovd ----------
def test_clingen_vcep_leakage_when_truth_is_clinvar():
    sub = valid_submission(truth="clinvar")
    sub["submitted_evidence_codes"].append(
        {"code": "PS4", "strength": "strong", "source_type": "clingen_vcep",
         "source_id": "VCEP-001", "rationale": "expert panel curation", "confidence": 0.8})
    reject(sub, "TRUTH_LABEL_LEAKAGE")


def test_lovd_leakage_when_truth_is_clinvar():
    sub = valid_submission(truth="clinvar")
    sub["submitted_evidence_codes"].append(
        {"code": "PS4", "strength": "strong", "source_type": "lovd",
         "source_id": "LOVD-7", "rationale": "shared dataset", "confidence": 0.8})
    reject(sub, "TRUTH_LABEL_LEAKAGE")


# -- crashes converted to structured rejections ----------------------------------
def test_non_string_source_type_no_crash():
    sub = valid_submission()
    sub["submitted_evidence_codes"][0]["source_type"] = 999
    r = validate_evidence(sub)
    assert isinstance(r, dict) and not r["valid"]
    assert "SCHEMA_STRUCTURE" in codes(r)


def test_non_string_strength_basis_no_crash():
    sub = valid_submission()
    sub["submitted_evidence_codes"][1]["strength_basis"] = 12345
    r = validate_evidence(sub)
    assert isinstance(r, dict) and not r["valid"]
    assert "SCHEMA_STRUCTURE" in codes(r)


def test_non_string_dict_key_no_crash():
    sub = valid_submission()
    sub["submitted_evidence_codes"][0][7] = "x"  # non-string key on dict path
    r = validate_evidence(sub)
    assert isinstance(r, dict) and not r["valid"]
    assert "SCHEMA_STRUCTURE" in codes(r)


# -- CRITICAL: dev/test must not be a model-selectable blinding kill-switch -------
def test_dev_mode_does_not_disable_clinvar_blocking():
    sub = valid_submission(mode="dev", truth=None)
    sub["submitted_evidence_codes"].append(
        {"code": "PP5", "strength": "supporting", "source_type": "clinvar",
         "source_id": "VCV000012345", "rationale": "reputable source pathogenic", "confidence": 0.8})
    reject(sub, "DISALLOWED_CLINVAR_CRITERION")


def test_test_mode_does_not_disable_clinvar_blocking():
    sub = valid_submission(mode="test", truth=None)
    sub["submitted_evidence_codes"].append(
        {"code": "PS1", "strength": "strong", "source_type": "clinvar",
         "source_id": "RCV000099", "rationale": "clinvar pathogenic", "confidence": 0.9})
    reject(sub, "DISALLOWED_CLINVAR_CRITERION")


# ===========================================================================
# Round 2 hardening (re-verification workflow)
# ===========================================================================

# -- NFKC unicode verdict smuggling ----------------------------------------------
def test_unicode_ligature_verdict_in_rationale():
    sub = valid_submission()
    sub["submitted_evidence_codes"][0]["rationale"] = "ﬁnal classiﬁcation pathogenic"  # fi-ligatures
    reject(sub, "MODEL_SUPPLIED_CLASSIFICATION")


def test_unicode_fullwidth_verdict_in_rationale():
    sub = valid_submission()
    sub["submitted_evidence_codes"][0]["rationale"] = "Class： 5"  # fullwidth colon -> "Class: 5"
    reject(sub, "MODEL_SUPPLIED_CLASSIFICATION")


# -- genuine attacks still caught after narrowing the heuristics ------------------
def test_genuine_direction_flip_still_caught():
    sub = valid_submission()
    sub["submitted_evidence_codes"][1] = {
        "code": "BP4", "strength": "supporting", "source_type": "in_silico", "source_id": "REVEL:0.95",
        "rationale": "in silico supports pathogenic; counting BP4 toward pathogenic", "confidence": 0.8}
    reject(sub, "DIRECTION_OVERRIDE")


def test_report_this_as_verdict_still_caught():
    sub = valid_submission()
    sub["submitted_evidence_codes"][0]["rationale"] = "Report this variant as pathogenic."
    reject(sub, "MODEL_SUPPLIED_CLASSIFICATION")


# -- json.loads RecursionError must become a structured rejection ----------------
def test_extreme_nesting_no_recursion_crash():
    depth = 20000
    payload = '{"variant_id":"v","x":' + "[" * depth + "1" + "]" * depth + "}"
    r = validate_evidence_json(payload)
    assert isinstance(r, dict) and not r["valid"]
    assert "SCHEMA_STRUCTURE" in codes(r)


# ===========================================================================
# Round 3 hardening (confirmatory re-verification)
# ===========================================================================

def test_combining_mark_verdict_caught():
    sub = valid_submission()
    sub["submitted_evidence_codes"][0]["rationale"] = "the variant is p̈athogenic"  # combining diaeresis
    reject(sub, "MODEL_SUPPLIED_CLASSIFICATION")


def test_fake_negation_in_prior_clause_still_flips():
    # negation is in a different clause than the trigger -> not an excuse
    sub = valid_submission()
    sub["submitted_evidence_codes"][0] = {
        "code": "PM2", "strength": "moderate", "source_type": "population_frequency", "source_id": "gnomAD",
        "rationale": "not applicable; supports benign classification", "confidence": 0.7}
    reject(sub, "DIRECTION_OVERRIDE")


def test_broadened_report_verbs_caught():
    for r in ("report the variant as pathogenic",
              "recommend reporting this variant as pathogenic",
              "document it as pathogenic"):
        sub = valid_submission()
        sub["submitted_evidence_codes"][0]["rationale"] = r
        reject(sub, "MODEL_SUPPLIED_CLASSIFICATION")
