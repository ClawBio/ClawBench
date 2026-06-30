"""TDD for the effect-size provenance gate (ClawBio/ClawBench#3, L1).

The gate resolves every association entry a skill emits against a citation oracle
(GWAS Catalog + PubMed) and FAILS CLOSED when the cited paper does not actually
support the (variant, trait, ancestry, effect) claim. "Cited but wrong" is the
same safety hazard as "missing".

These cases are the six high-reuse PMIDs from ancestry-risk-profiler (PR #297),
resolved against PubMed during the 2026-06 audit. Five are wrong; one is correct.
The fixture oracle below encodes the GROUND TRUTH for each (which real study
actually reports the variant/trait/ancestry), so the test is deterministic and
needs no network. The live network oracle (validate_provenance.LiveOracle) is the
remaining build target tracked in the issue.
"""
from __future__ import annotations

import validate_provenance as VP


# --- Ground-truth catalog: rsid -> list of real study records -----------------
# Each record is one GWAS Catalog study: which trait (EFO), which PMID actually
# reported it, in which ancestry, with what effect. Comments give the real paper.
CATALOG = {
    # TCF7L2 / type 2 diabetes. Grant 2006 (PMID 16415884, EUR) is the discovery
    # study; Cho 2011 (PMID 22158537) replicated it in East Asians.
    "rs7903146": [
        {"efo_id": "EFO_0001360", "trait": "type 2 diabetes", "pmid": "16415884",
         "ancestries": {"EUR"}, "or_value": 1.45},
        {"efo_id": "EFO_0001360", "trait": "type 2 diabetes", "pmid": "22158537",
         "ancestries": {"EAS"}, "or_value": 1.40},
    ],
    # APOE / Alzheimer's. Lambert 2013 IGAP (PMID 24162737, EUR). NOT a T2D paper.
    "rs429358": [
        {"efo_id": "EFO_0000249", "trait": "Alzheimer disease", "pmid": "24162737",
         "ancestries": {"EUR"}, "or_value": 3.2},
    ],
    # FGFR2 / breast cancer. Easton 2007 (PMID 17529973, EUR).
    "rs2981582": [
        {"efo_id": "EFO_0000305", "trait": "breast carcinoma", "pmid": "17529973",
         "ancestries": {"EUR"}, "or_value": 1.26},
    ],
    # PCSK9 / LDL cholesterol. Kathiresan 2008 (PMID 18193044, EUR). The 9p21 MI
    # paper (17478679) does not report this variant.
    "rs11591147": [
        {"efo_id": "EFO_0004611", "trait": "LDL cholesterol", "pmid": "18193044",
         "ancestries": {"EUR"}, "or_value": 0.6},
    ],
    # APOL1 / chronic kidney disease. Genovese 2010 Science 329:841 is PMID
    # 20413513 (AFR). The cited 20566908 is a head-and-neck-cancer survey.
    "rs73885319": [
        {"efo_id": "EFO_0003086", "trait": "chronic kidney disease", "pmid": "20413513",
         "ancestries": {"AFR"}, "or_value": 1.89},
    ],
}

# PMIDs that resolve in PubMed (all six are real papers; none is a typo). A
# fabricated/typo id is anything not listed here.
RESOLVABLE = {
    "16415884", "22158537", "23945395", "17478679", "27005778", "20566908",
    "24162737", "17529973", "18193044", "20413513",
}

# Minimal PubMed topic terms for the topic-fallback path (variants absent from
# the catalog). 20566908 is head-and-neck cancer, deliberately off-topic.
TOPIC_TERMS = {
    "20566908": {"head", "neck", "cancer", "disability"},
    "16415884": {"transcription", "factor", "diabetes", "tcf7l2"},
}


class FixtureOracle:
    """Deterministic stand-in for the GWAS Catalog + PubMed live oracle."""

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
    # rs7903146 / T2D / EUR / Grant 2006 (16415884): variant, trait, ancestry,
    # PMID and effect all line up.
    f = VP.validate_entry(
        _entry("rs7903146", "EFO_0001360", "type 2 diabetes", "EUR", "16415884", 1.45),
        ORACLE,
    )
    assert f["valid"] is True
    assert f["error_code"] is None


def test_apol1_headneck_cancer_pmid_rejected():
    # Flagship: 20566908 is a head-and-neck-cancer survey, cited as Genovese APOL1.
    assert _code(_entry("rs73885319", "EFO_0003086", "chronic kidney disease",
                        "AFR", "20566908", 1.89)) == "PMID_STUDY_MISMATCH"


def test_east_asian_t2d_paper_cited_for_alzheimers_rejected():
    # 22158537 is an East Asian T2D GWAS, cited as the SAS source for APOE/Alzheimer's.
    assert _code(_entry("rs429358", "EFO_0000249", "Alzheimer disease",
                        "SAS", "22158537", 2.7)) == "PMID_STUDY_MISMATCH"


def test_metabolomics_paper_cited_for_breast_cancer_rejected():
    # 27005778 is a circulating-metabolites GWAS, cited as the AFR breast-cancer source.
    assert _code(_entry("rs2981582", "EFO_0000305", "breast carcinoma",
                        "AFR", "27005778", 1.11)) == "PMID_STUDY_MISMATCH"


def test_japanese_t2d_paper_cited_for_alzheimers_rejected():
    # 23945395 is a Japanese T2D GWAS (3 loci), cited as EAS source for APOE/Alzheimer's.
    assert _code(_entry("rs429358", "EFO_0000249", "Alzheimer disease",
                        "EAS", "23945395", 2.8)) == "PMID_STUDY_MISMATCH"


def test_9p21_mi_paper_cited_for_pcsk9_rejected():
    # 17478679 is the 9p21 myocardial-infarction paper, reused for PCSK9 (rs11591147).
    assert _code(_entry("rs11591147", "EFO_0004611", "LDL cholesterol",
                        "EUR", "17478679", 0.61)) == "PMID_STUDY_MISMATCH"


# --- Other error codes (full validator surface) -------------------------------

def test_unresolvable_pmid():
    assert _code(_entry("rs7903146", "EFO_0001360", "type 2 diabetes",
                        "EUR", "99999999", 1.45)) == "PMID_UNRESOLVABLE"


def test_ancestry_mismatch():
    # Correct paper & trait, but Grant 2006 is EUR; entry claims SAS.
    assert _code(_entry("rs7903146", "EFO_0001360", "type 2 diabetes",
                        "SAS", "16415884", 1.45)) == "ANCESTRY_MISMATCH"


def test_effect_out_of_range():
    # Correct paper/trait/ancestry, but OR 9.8 vs catalog 1.45.
    assert _code(_entry("rs7903146", "EFO_0001360", "type 2 diabetes",
                        "EUR", "16415884", 9.8)) == "EFFECT_OUT_OF_RANGE"


def test_assoc_not_found_when_variant_absent_and_topic_off():
    # Variant not in catalog; PMID topic (head-and-neck cancer) does not overlap trait.
    assert _code(_entry("rs99999999", "EFO_0001360", "type 2 diabetes",
                        "EUR", "20566908", 1.4)) == "ASSOC_NOT_FOUND"


def test_topic_match_low_is_warning_not_block():
    # Variant absent from catalog, but the PMID's topic overlaps the trait label:
    # advisory (needs human sign-off), not an auto-block.
    f = VP.validate_entry(
        _entry("rs99999999", "EFO_0001360", "diabetes", "EUR", "16415884", 1.4),
        ORACLE,
    )
    assert f["error_code"] == "TOPIC_MATCH_LOW"
    assert f["severity"] == "warn"
    assert f["valid"] is True


def test_schema_invalid_entry_is_caught():
    bad = {"variant": {"rsid": "rs7903146"}}  # missing required trait/ancestry/effect/source
    f = VP.validate_entry(bad, ORACLE)
    assert f["valid"] is False
    assert f["error_code"] == "SCHEMA_INVALID"


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
