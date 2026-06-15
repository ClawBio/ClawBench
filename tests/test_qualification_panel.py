"""TDD for the benchmark qualification panel: stratify held-out variants by ACMG automatability.

Tier A (fully automatable from NON-ClinVar structured sources): LoF (PVS1) or common (BA1, AF>=5%).
Tier B (partially automatable): missense/inframe (PM2+PP3/BP4) or BS1 (1%<=AF<5%).
Tier C (human-level evidence): synonymous/intronic/UTR/underdetermined.
ClinVar-assertion criteria (PS1/PM5/PP5/BP6) are NOT counted as available, because they are blinded
in primary mode.
"""
from __future__ import annotations

import qualification_panel as Q


def test_varid_to_int():
    assert Q.varid_to_int("VCV000012345") == 12345
    assert Q.varid_to_int("12345") == 12345
    assert Q.varid_to_int("notanid") is None


def test_most_severe_consequence():
    assert Q.most_severe_consequence("SO:0001583|missense_variant,SO:0001627|intron_variant") == "missense_variant"
    assert Q.most_severe_consequence("SO:0001589|frameshift_variant,SO:0001583|missense_variant") == "frameshift_variant"
    assert Q.most_severe_consequence("SO:0001819|synonymous_variant") == "synonymous_variant"
    assert Q.most_severe_consequence("") is None


def test_parse_af():
    info = {"AF_EXAC": "0.06", "AF_TGP": "0.02"}
    assert Q.parse_af(info) == 0.06
    assert Q.parse_af({"AF_ESP": "0.001"}) == 0.001
    assert Q.parse_af({}) is None


def test_assign_tier():
    assert Q.assign_tier("missense_variant", 0.06)[0] == "A"      # BA1 common overrides consequence
    assert Q.assign_tier("frameshift_variant", None)[0] == "A"    # PVS1
    assert Q.assign_tier("splice_acceptor_variant", None)[0] == "A"
    assert Q.assign_tier("missense_variant", None)[0] == "B"
    assert Q.assign_tier("inframe_deletion", None)[0] == "B"
    assert Q.assign_tier("intron_variant", 0.02)[0] == "B"        # BS1
    assert Q.assign_tier("synonymous_variant", None)[0] == "C"
    assert Q.assign_tier("intron_variant", None)[0] == "C"
    assert Q.assign_tier(None, None)[0] == "C"


def _manifest():
    def v(vid, gene, clnsig, stars=2):
        return {"variant_id": vid, "genomic_context": {"gene": gene},
                "truth": {"clnsig": clnsig, "review_stars": stars}, "reclassified": False}
    return {"content_hash": "abc", "variants": [
        v("VCV000000001", "BRCA1", "Pathogenic"),       # frameshift -> A
        v("VCV000000002", "TP53", "Likely Pathogenic"),  # missense -> B
        v("VCV000000003", "CFTR", "Benign"),             # synonymous -> C
        v("VCV000000004", "MYOC", "Benign"),             # missense + common -> A (BA1)
    ]}


def _features():
    return {
        1: {"consequence": "frameshift_variant", "max_af": None},
        2: {"consequence": "missense_variant", "max_af": None},
        3: {"consequence": "synonymous_variant", "max_af": None},
        4: {"consequence": "missense_variant", "max_af": 0.07},
    }


def test_build_panel():
    panel = Q.build_panel(_manifest(), _features())
    by_id = {v["variant_id"]: v for v in panel["variants"]}
    assert by_id["VCV000000001"]["tier"] == "A"
    assert by_id["VCV000000002"]["tier"] == "B"
    assert by_id["VCV000000003"]["tier"] == "C"
    assert by_id["VCV000000004"]["tier"] == "A"
    assert panel["counts"] == {"A": 2, "B": 1, "C": 1}
    assert panel["by_tier_class"]["A"]["Pathogenic"] == 1
    assert panel["expected_ceiling"]["A"] == "high"


def test_missing_features_tier_c_unknown():
    panel = Q.build_panel(_manifest(), {})  # no features at all
    assert all(v["tier"] == "C" for v in panel["variants"])
    assert panel["unknown_consequence"] == 4
    assert panel["counts"]["C"] == 4


def test_select_pilot_stratified_and_deterministic():
    manifest = {"content_hash": "x", "variants": [
        {"variant_id": f"VCV{i:09d}", "genomic_context": {"gene": "G"},
         "truth": {"clnsig": "Pathogenic" if i % 2 else "Benign", "review_stars": 2}, "reclassified": False}
        for i in range(1, 41)]}
    feats = {i: {"consequence": "frameshift_variant", "max_af": None} for i in range(1, 41)}  # all Tier A
    panel = Q.build_panel(manifest, feats)
    pilot = Q.select_pilot(panel, per_class_cap=5, tier="A")
    assert len(pilot) == 10                       # 5 Pathogenic + 5 Benign
    assert pilot == Q.select_pilot(panel, per_class_cap=5, tier="A")  # deterministic
    classes = {p["clnsig"] for p in pilot}
    assert classes == {"Pathogenic", "Benign"}
