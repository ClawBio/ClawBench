"""TDD for ClinVar-blinded benchmark mode (validity fix F1).

Rule (clinvar_blinded, primary benchmark mode):
  - clinvar_significance nulled before evidence evaluation
  - PS1 disabled unless supported by non-ClinVar evidence
  - PP5 always disabled
  - BP6 always disabled
  - ClinVar label retained only as external truth, never as input evidence
  - output records blinded_criteria_removed = [PS1, PP5, BP6]

clinvar_unblinded_sensitivity is a control: nothing removed.
"""
from __future__ import annotations

import pytest

import blinding
from acmg_engine import VariantEvidence


def _clinvar_pathogenic_missense() -> VariantEvidence:
    # ClinVar P/3-star missense, absent from gnomAD -> would fire PS1, PP5, PM2 unblinded.
    return VariantEvidence(
        chrom="chr17", pos=43045712, ref="C", alt="T",
        gene="BRCA1", consequence="missense_variant", is_missense=True,
        clinvar_significance="Pathogenic", clinvar_review_stars=3,
        gnomad_af=None,
    )


def test_modes_constants():
    assert blinding.PRIMARY_MODE == "clinvar_blinded"
    assert blinding.SENSITIVITY_MODE == "clinvar_unblinded_sensitivity"
    assert set(blinding.BLINDED_POLICY_CODES) == {"PS1", "PP5", "BP6"}


def test_blind_evidence_nulls_clinvar():
    ev = _clinvar_pathogenic_missense()
    b = blinding.blind_evidence(ev)
    assert b.clinvar_significance == ""
    assert b.clinvar_review_stars == 0
    # original is untouched (no mutation of caller's object)
    assert ev.clinvar_significance == "Pathogenic"


def test_unblinded_fires_clinvar_criteria():
    res = blinding.classify_with_mode(_clinvar_pathogenic_missense(), blinding.SENSITIVITY_MODE)
    assert "PS1" in res["triggered_criteria"]
    assert "PP5" in res["triggered_criteria"]
    assert res["blinded_criteria_removed"] == []
    assert res["clinvar_used_as_evidence"] is True


def test_blinded_removes_clinvar_criteria():
    res = blinding.classify_with_mode(_clinvar_pathogenic_missense(), blinding.PRIMARY_MODE)
    for code in ("PS1", "PP5", "BP6"):
        assert code not in res["triggered_criteria"]
    assert res["blinded_criteria_removed"] == ["PS1", "PP5", "BP6"]
    assert res["clinvar_used_as_evidence"] is False


def test_blinded_keeps_non_clinvar_criteria():
    # PM2 (gnomAD absent) is not ClinVar-derived and must survive blinding.
    res = blinding.classify_with_mode(_clinvar_pathogenic_missense(), blinding.PRIMARY_MODE)
    assert "PM2" in res["triggered_criteria"]


def test_blinded_classification_independent_of_clinvar_label():
    # Same non-ClinVar evidence, opposite ClinVar labels -> identical blinded result.
    base = dict(chrom="chr1", pos=100, ref="A", alt="G", gene="X",
                consequence="missense_variant", is_missense=True, gnomad_af=None)
    a = VariantEvidence(**base, clinvar_significance="Pathogenic", clinvar_review_stars=3)
    b = VariantEvidence(**base, clinvar_significance="Benign", clinvar_review_stars=3)
    ra = blinding.classify_with_mode(a, blinding.PRIMARY_MODE)
    rb = blinding.classify_with_mode(b, blinding.PRIMARY_MODE)
    assert ra["classification"] == rb["classification"]
    assert ra["triggered_criteria"] == rb["triggered_criteria"]


def test_unknown_mode_raises():
    with pytest.raises(ValueError):
        blinding.classify_with_mode(_clinvar_pathogenic_missense(), "bogus")
