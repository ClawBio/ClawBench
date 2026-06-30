"""End-to-end test of the provenance gate against the REAL committed GWAS Catalog + PubMed
snapshot (TRUTH/gwas_catalog/snapshot.json), via CachedOracle. Offline and deterministic.

Refresh the snapshot with: python scripts/build_provenance_snapshot.py

This proves the gate works on real catalog data, not just the hand-built fixture:
- the flagship APOL1 citation (20566908 = a head-and-neck-cancer survey) is hard-blocked;
- the correct primary paper that GWAS Catalog has not indexed (Genovese 2010, 20647424) is
  flagged for sign-off rather than false-rejected;
- a genuinely catalogued (variant, trait, ancestry, PMID, effect) tuple passes.
"""
from __future__ import annotations

import json
from pathlib import Path

import validate_provenance as VP

_SNAPSHOT = Path(VP.__file__).resolve().parents[1] / "TRUTH" / "gwas_catalog" / "snapshot.json"


def _snap():
    with open(_SNAPSHOT) as fh:
        return json.load(fh)


def _entry(rsid, efo, label, ancestry, pmid, value):
    return {"variant": {"rsid": rsid}, "trait": {"label": label, "efo_id": efo},
            "ancestry": ancestry, "effect": {"measure": "OR", "value": value},
            "source": {"pmid": pmid}}


def test_snapshot_present_and_nonempty():
    snap = _snap()
    assert snap["associations"], "snapshot has no associations - rebuild it"
    assert "20566908" in snap["pmid_titles"] and "20647424" in snap["pmid_titles"]


def test_real_catalogued_tuple_passes():
    snap = _snap()
    oracle = VP.CachedOracle(_SNAPSHOT)
    # Pick any real record with an OR and a concrete ancestry, and cite it exactly.
    rec = next(r for recs in snap["associations"].values() for r in recs
               if r.get("or_value") and r.get("ancestries"))
    rsid = next(rs for rs, recs in snap["associations"].items() if rec in recs)
    f = VP.validate_entry(
        _entry(rsid, rec["efo_id"], rec["trait"], rec["ancestries"][0],
               rec["pmid"], rec["or_value"]), oracle)
    assert f["valid"] is True, f
    assert f["error_code"] is None


def test_flagship_apol1_headneck_pmid_is_blocked_on_real_data():
    oracle = VP.CachedOracle(_SNAPSHOT)
    # 20566908 (head-and-neck-cancer survey) cited for APOL1/chronic kidney disease.
    f = VP.validate_entry(
        _entry("rs73885319", "MONDO_0005300", "chronic kidney disease", "AFR", "20566908", 1.89),
        oracle)
    assert f["valid"] is False
    assert f["error_code"] in ("PMID_STUDY_MISMATCH", "ASSOC_NOT_FOUND")


def test_correct_genovese_paper_is_signoff_not_block_on_real_data():
    oracle = VP.CachedOracle(_SNAPSHOT)
    # Genovese 2010 (20647424) really reports APOL1/kidney, but GWAS Catalog links the
    # variant to PAGE/MVP instead - a coverage gap, not a fabrication.
    f = VP.validate_entry(
        _entry("rs73885319", "MONDO_0005300", "chronic kidney disease", "AFR", "20647424", 1.89),
        oracle)
    assert f["error_code"] == "TOPIC_MATCH_LOW"
    assert f["severity"] == "warn" and f["valid"] is True


def test_cached_oracle_pmid_exists():
    oracle = VP.CachedOracle(_SNAPSHOT)
    assert oracle.pmid_exists("20566908") is True
    assert oracle.pmid_exists("99999999") is False


def test_panel_on_real_snapshot_blocks_flagship():
    oracle = VP.CachedOracle(_SNAPSHOT)
    panel = [
        _entry("rs73885319", "MONDO_0005300", "chronic kidney disease", "AFR", "20566908", 1.89),
        _entry("rs73885319", "MONDO_0005300", "chronic kidney disease", "AFR", "20647424", 1.89),
    ]
    report = VP.validate_panel(panel, oracle)
    assert report["n_entries"] == 2
    assert report["n_blocking"] == 1   # the head-and-neck-cancer cite
    assert report["n_warnings"] == 1   # the uncatalogued-but-correct Genovese cite
    assert report["passed"] is False
