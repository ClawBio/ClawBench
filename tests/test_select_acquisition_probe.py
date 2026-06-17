"""TDD for the acquisition-arm probe selector.

Selects a frozen set of rare missense variants for the acquisition experiment: definitive (non-VUS)
variants enriched for the evidence_insufficient layer (where thin consequence+AF evidence cannot
classify), plus a few VUS negative controls. Reuses the held-out manifest's genomic context so the
oracle fetch (VEP/gnomAD) has coordinates. Deterministic: no randomness, stable ordering.
"""
from __future__ import annotations

import select_acquisition_probe as S


def _manifest_by_id():
    def mk(vid, chrom, pos, ref, alt, gene, clnsig, stars=2):
        return {"variant_id": vid,
                "genomic_context": {"chrom": chrom, "pos": pos, "ref": ref, "alt": alt,
                                    "build": "GRCh38", "gene": gene},
                "truth": {"clnsig": clnsig, "review_stars": stars}}
    return {m["variant_id"]: m for m in [
        mk("P1", "1", 100, "A", "T", "BRCA1", "Pathogenic"),
        mk("P2", "1", 200, "C", "G", "BRCA2", "Pathogenic"),
        mk("LP1", "2", 100, "A", "T", "TP53", "Likely Pathogenic"),
        mk("LB1", "3", 100, "A", "T", "MLH1", "Likely Benign"),
        mk("B1", "4", 100, "A", "T", "MSH2", "Benign"),
        mk("U1", "5", 100, "A", "T", "PTEN", "Uncertain Significance"),
        mk("U2", "5", 200, "C", "G", "PTEN", "Uncertain Significance"),
    ]}


def _probe_variants():
    def mk(vid, af, clnsig):
        return {"variant_id": vid, "consequence": "missense_variant", "max_af": af, "clnsig": clnsig}
    return [mk("P1", None, "Pathogenic"), mk("P2", 1e-5, "Pathogenic"),
            mk("LP1", None, "Likely Pathogenic"), mk("LB1", 8e-4, "Likely Benign"),
            mk("B1", 5e-5, "Benign"), mk("U1", None, "Uncertain Significance"),
            mk("U2", None, "Uncertain Significance")]


def test_join_recovers_genomic_context():
    joined = S.join_genomic_context(_probe_variants(), _manifest_by_id())
    p1 = next(v for v in joined if v["variant_id"] == "P1")
    assert p1["genomic_context"]["gene"] == "BRCA1"
    assert p1["genomic_context"]["chrom"] == "1"
    # evidence_context carries the thin fields the runner expects
    assert p1["evidence_context"]["molecular_consequence"] == "missense_variant"
    assert p1["evidence_context"]["population_max_af"] is None
    # truth comes from the manifest (authoritative)
    assert p1["truth"]["clnsig"] == "Pathogenic"


def test_join_raises_on_missing_manifest_entry():
    probe = _probe_variants() + [{"variant_id": "GHOST", "consequence": "missense_variant",
                                  "max_af": None, "clnsig": "Pathogenic"}]
    try:
        S.join_genomic_context(probe, _manifest_by_id())
        assert False, "expected KeyError for variant absent from manifest"
    except KeyError as e:
        assert "GHOST" in str(e)


def test_ei_variants_for_model_filters_by_model_and_flag():
    att = [
        {"variant_id": "P1", "model": "claude-sonnet-4-5", "flags": {"evidence_insufficient": True}},
        {"variant_id": "P2", "model": "claude-sonnet-4-5", "flags": {"evidence_insufficient": False}},
        {"variant_id": "LP1", "model": "gpt-5.2", "flags": {"evidence_insufficient": True}},
    ]
    ei = S.ei_variants_for_model(att, "claude-sonnet-4-5")
    assert ei == {"P1"}


def test_select_prefers_ei_and_is_deterministic():
    joined = S.join_genomic_context(_probe_variants(), _manifest_by_id())
    ei = {"P2"}  # P2 is evidence_insufficient, P1 is not
    sel = S.select_probe(joined, ei, per_class=1, vus_controls=1)
    sel_ids = [v["variant_id"] for v in sel]
    # one per definitive class (ei-preferred for Pathogenic -> P2 over P1) + 1 VUS control
    assert "P2" in sel_ids and "P1" not in sel_ids
    assert "LP1" in sel_ids and "LB1" in sel_ids and "B1" in sel_ids
    assert sum(1 for v in sel if v["truth"]["clnsig"] == "Uncertain Significance") == 1
    # deterministic: same call, same order
    assert [v["variant_id"] for v in S.select_probe(joined, ei, per_class=1, vus_controls=1)] == sel_ids


def test_select_no_vus_in_definitive_quota():
    joined = S.join_genomic_context(_probe_variants(), _manifest_by_id())
    sel = S.select_probe(joined, set(), per_class=5, vus_controls=0)
    assert all(v["truth"]["clnsig"] != "Uncertain Significance" for v in sel)


def test_freeze_is_checksummed_and_reproducible():
    joined = S.join_genomic_context(_probe_variants(), _manifest_by_id())
    sel = S.select_probe(joined, {"P2"}, per_class=1, vus_controls=1)
    f1 = S.freeze(sel, model="claude-sonnet-4-5")
    f2 = S.freeze(sel, model="claude-sonnet-4-5")
    assert f1["content_hash"] == f2["content_hash"]
    assert f1["schema_version"] == 1
    assert f1["counts"]["selected"] == len(sel)
    assert f1["selection_model"] == "claude-sonnet-4-5"
    # changing the set changes the hash
    f3 = S.freeze(sel[:-1], model="claude-sonnet-4-5")
    assert f3["content_hash"] != f1["content_hash"]
