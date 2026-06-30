"""TDD for the effect-size provenance gate (ClawBio/ClawBench#3, L1) - deterministic fixture.

The gate resolves every association entry a skill emits against a citation oracle
(GWAS Catalog + PubMed) and FAILS CLOSED when the cited paper does not actually support
the (variant, trait, ancestry, effect) claim. "Cited but wrong" is the same hazard as
"missing". A correct-but-uncatalogued citation (GWAS Catalog does not index every primary
paper) is flagged for human sign-off rather than hard-blocked.

These cases come from ancestry-risk-profiler (PR #297), resolved against PubMed during the
2026-06 audit. The fixture oracle encodes ground truth so the test is deterministic and
needs no network; test_provenance_snapshot.py exercises the same logic on the real
committed GWAS Catalog/PubMed snapshot.
"""
from __future__ import annotations

import validate_provenance as VP


# rsid -> real study records. Comments give the real paper each PMID resolves to.
CATALOG = {
    # TCF7L2 / type 2 diabetes. Grant 2006 (16415884, EUR); Cho 2011 (22158537, EAS).
    "rs7903146": [
        {"efo_id": "EFO_0001360", "trait": "type 2 diabetes", "pmid": "16415884",
         "ancestries": ["EUR"], "or_value": 1.45},
        {"efo_id": "EFO_0001360", "trait": "type 2 diabetes", "pmid": "22158537",
         "ancestries": ["EAS"], "or_value": 1.40},
    ],
    # APOE / Alzheimer's. Lambert 2013 IGAP (24162737, EUR) - NOT a T2D paper.
    "rs429358": [
        {"efo_id": "EFO_0000249", "trait": "Alzheimer disease", "pmid": "24162737",
         "ancestries": ["EUR"], "or_value": 3.2},
    ],
    # FGFR2 / breast cancer. Easton 2007 (17529973, EUR).
    "rs2981582": [
        {"efo_id": "EFO_0000305", "trait": "breast carcinoma", "pmid": "17529973",
         "ancestries": ["EUR"], "or_value": 1.26},
    ],
    # PCSK9 / LDL cholesterol. Kathiresan 2008 (18193044, EUR). The 9p21 MI paper (17478679)
    # does not report this variant.
    "rs11591147": [
        {"efo_id": "EFO_0004611", "trait": "LDL cholesterol", "pmid": "18193044",
         "ancestries": ["EUR"], "or_value": 0.6},
    ],
    # APOL1 / chronic kidney disease. GWAS Catalog links this to PAGE (31178898), NOT to the
    # original Genovese 2010 paper (20647424) - a real coverage gap.
    "rs73885319": [
        {"efo_id": "EFO_0003086", "trait": "chronic kidney disease", "pmid": "31178898",
         "ancestries": ["AFR"], "or_value": None},
    ],
}

# PMIDs that resolve in PubMed (none is a typo).
RESOLVABLE = {
    "16415884", "22158537", "23945395", "17478679", "27005778", "20566908", "20647424",
    "24162737", "17529973", "18193044", "31178898",
}

# Real PubMed title topic terms. The wrong citations are deliberately off-topic for their
# claimed trait; 20647424 (correct Genovese) overlaps "kidney".
TOPIC_TERMS = {
    "20566908": {"health", "professional", "perspective", "disability", "head", "neck", "cancer"},
    "20647424": {"association", "trypanolytic", "apol1", "variants", "kidney", "african", "americans"},
    "22158537": {"meta", "analysis", "loci", "type", "diabetes", "east", "asians"},
    "23945395": {"genome", "association", "three", "novel", "loci", "type", "diabetes"},
    "27005778": {"genome", "circulating", "metabolites", "loci", "systemic", "effects", "lpa"},
    "17478679": {"common", "variant", "chromosome", "9p21", "risk", "myocardial", "infarction"},
    "16415884": {"variant", "transcription", "factor", "tcf7l2", "gene", "diabetes"},
}


class FixtureOracle:
    def pmid_exists(self, pmid: str) -> bool:
        return pmid in RESOLVABLE

    def associations_for(self, rsid: str) -> list[dict]:
        return CATALOG.get(rsid, [])

    def pubmed_topic_terms(self, pmid: str) -> set[str]:
        return TOPIC_TERMS.get(pmid, set())


ORACLE = FixtureOracle()


def _entry(rsid, efo, trait, ancestry, pmid, or_value=1.4):
    return {
        "variant": {"rsid": rsid},
        "trait": {"label": trait, "efo_id": efo},
        "ancestry": ancestry,
        "effect": {"measure": "OR", "value": or_value},
        "source": {"pmid": pmid},
    }


def _code(entry):
    return VP.validate_entry(entry, ORACLE)["error_code"]


# --- The six audit PMIDs ------------------------------------------------------

def test_correct_citation_passes():
    f = VP.validate_entry(
        _entry("rs7903146", "EFO_0001360", "type 2 diabetes", "EUR", "16415884", 1.45), ORACLE)
    assert f["valid"] is True and f["error_code"] is None


def test_apol1_headneck_cancer_pmid_rejected():
    # Flagship: 20566908 is a head-and-neck-cancer survey, cited as Genovese APOL1.
    assert _code(_entry("rs73885319", "EFO_0003086", "chronic kidney disease",
                        "AFR", "20566908", 1.89)) == "PMID_STUDY_MISMATCH"


def test_east_asian_t2d_paper_cited_for_alzheimers_rejected():
    assert _code(_entry("rs429358", "EFO_0000249", "Alzheimer disease",
                        "SAS", "22158537", 2.7)) == "PMID_STUDY_MISMATCH"


def test_metabolomics_paper_cited_for_breast_cancer_rejected():
    assert _code(_entry("rs2981582", "EFO_0000305", "breast carcinoma",
                        "AFR", "27005778", 1.11)) == "PMID_STUDY_MISMATCH"


def test_japanese_t2d_paper_cited_for_alzheimers_rejected():
    assert _code(_entry("rs429358", "EFO_0000249", "Alzheimer disease",
                        "EAS", "23945395", 2.8)) == "PMID_STUDY_MISMATCH"


def test_9p21_mi_paper_cited_for_pcsk9_rejected():
    assert _code(_entry("rs11591147", "EFO_0004611", "LDL cholesterol",
                        "EUR", "17478679", 0.61)) == "PMID_STUDY_MISMATCH"


# --- Coverage gap: correct primary paper GWAS Catalog has not indexed --------

def test_correct_but_uncatalogued_primary_is_topic_warning():
    # Genovese 2010 (20647424) genuinely reports APOL1/kidney, but GWAS Catalog links the
    # variant to PAGE instead. The gate must WARN for sign-off, not hard-block.
    f = VP.validate_entry(
        _entry("rs73885319", "EFO_0003086", "chronic kidney disease", "AFR", "20647424", 1.89),
        ORACLE)
    assert f["error_code"] == "TOPIC_MATCH_LOW"
    assert f["severity"] == "warn" and f["valid"] is True


# --- Other error codes (full validator surface) -------------------------------

def test_unresolvable_pmid():
    assert _code(_entry("rs7903146", "EFO_0001360", "type 2 diabetes",
                        "EUR", "99999999", 1.45)) == "PMID_UNRESOLVABLE"


def test_ancestry_mismatch():
    assert _code(_entry("rs7903146", "EFO_0001360", "type 2 diabetes",
                        "SAS", "16415884", 1.45)) == "ANCESTRY_MISMATCH"


def test_effect_out_of_range():
    assert _code(_entry("rs7903146", "EFO_0001360", "type 2 diabetes",
                        "EUR", "16415884", 9.8)) == "EFFECT_OUT_OF_RANGE"


def test_assoc_not_found_when_variant_absent_and_topic_off():
    # Variant not in catalog; PMID topic (head-and-neck cancer) does not overlap the trait.
    assert _code(_entry("rs99999999", "EFO_0001360", "type 2 diabetes",
                        "EUR", "20566908", 1.4)) == "ASSOC_NOT_FOUND"


def test_topic_match_low_is_warning_not_block():
    # Variant absent from catalog, but the PMID's topic overlaps the trait label: advisory.
    f = VP.validate_entry(
        _entry("rs99999999", "EFO_0001360", "diabetes", "EUR", "16415884", 1.4), ORACLE)
    assert f["error_code"] == "TOPIC_MATCH_LOW"
    assert f["severity"] == "warn" and f["valid"] is True


def test_schema_invalid_entry_is_caught():
    f = VP.validate_entry({"variant": {"rsid": "rs7903146"}}, ORACLE)
    assert f["valid"] is False and f["error_code"] == "SCHEMA_INVALID"


def test_validate_panel_summarises_and_never_raises():
    panel = [
        _entry("rs7903146", "EFO_0001360", "type 2 diabetes", "EUR", "16415884", 1.45),
        _entry("rs73885319", "EFO_0003086", "chronic kidney disease", "AFR", "20566908", 1.89),
    ]
    report = VP.validate_panel(panel, ORACLE)
    assert report["n_entries"] == 2
    assert report["n_blocking"] == 1
    assert report["passed"] is False


def test_error_codes_are_declared():
    for code in ("PMID_UNRESOLVABLE", "ASSOC_NOT_FOUND", "PMID_STUDY_MISMATCH",
                 "ANCESTRY_MISMATCH", "EFFECT_OUT_OF_RANGE", "TOPIC_MATCH_LOW",
                 "SCHEMA_INVALID"):
        assert code in VP.ERROR_CODES
