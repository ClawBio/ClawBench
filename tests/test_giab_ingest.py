"""TDD for GIAB truth ingestion (Exp 2, Phase 1).

Runs on the Mac Studio external volume, never the internal disk. Guardrails under test: external-disk
enforcement, fail-closed free-disk floor (500 GB default), dry-run, content hashing, fail-closed
checksum verification. Network is injected so the logic is testable offline; no real download here.
"""
from __future__ import annotations

import types

import giab_ingest as GI
import pytest


def test_external_path_detection():
    assert GI.is_internal_path("/Users/x/dev/CLAWBENCH") is True
    assert GI.is_internal_path("/System/Volumes/Data/x") is True
    assert GI.is_internal_path("/Volumes/Macintosh HD/x") is True
    assert GI.is_internal_path("/Volumes/CPM-20Tb/CLAWBENCH") is False


def test_assert_external_workdir_rejects_internal():
    with pytest.raises(GI.InternalDiskError):
        GI.assert_external_workdir("/Users/x/CLAWBENCH")
    GI.assert_external_workdir("/Volumes/CPM-20Tb/CLAWBENCH")  # no raise


def test_free_disk_floor_fail_closed():
    small = lambda p: types.SimpleNamespace(total=1 << 50, used=1 << 50, free=100 * 10**9)  # 100 GB
    big = lambda p: types.SimpleNamespace(total=20 * 10**12, used=6 * 10**12, free=14 * 10**12)
    with pytest.raises(GI.DiskGuardError):
        GI.assert_free_disk("/Volumes/CPM-20Tb", min_bytes=500 * 10**9, usage=small)
    GI.assert_free_disk("/Volumes/CPM-20Tb", min_bytes=500 * 10**9, usage=big)  # no raise


def test_free_disk_unmounted_volume_is_clean_guard_error():
    # if the volume is not mounted, disk_usage raises FileNotFoundError; the guard must convert it
    def boom(p):
        raise FileNotFoundError(p)
    with pytest.raises(GI.DiskGuardError):
        GI.assert_free_disk("/Volumes/NOT-MOUNTED/x", min_bytes=500 * 10**9, usage=boom)


def _manifest():
    return {
        "reference_build": "GRCh38",
        "reference": [{"id": "ref", "url": "http://x/ref.fa.gz", "dest": "reference/ref.fa.gz", "sha256": None}],
        "stratifications": [{"id": "strat", "url": "http://x/strat.tar.gz", "dest": "giab/strat/strat.tar.gz", "sha256": None}],
        "giab_samples": [
            {"id": "HG002", "ancestry": "AJ", "vcf": "http://x/HG002.vcf.gz", "bed": "http://x/HG002.bed"},
            {"id": "HG005", "ancestry": "EAS", "vcf": "http://x/HG005.vcf.gz", "bed": "http://x/HG005.bed"},
        ],
    }


def test_plan_lists_components_with_dest_under_workdir():
    plan = GI.plan(_manifest(), "/Volumes/CPM-20Tb/CLAWBENCH", components=("reference", "strat", "bed"))
    kinds = {p["kind"] for p in plan}
    assert kinds == {"reference", "strat", "bed"}            # full vcf excluded (range-extracted later)
    dests = {p["dest"] for p in plan}
    assert all(d.startswith("/Volumes/CPM-20Tb/CLAWBENCH/") for d in dests)
    assert any(p["id"] == "HG002_bed" for p in plan)


def test_plan_can_include_full_vcf_for_full_genome():
    plan = GI.plan(_manifest(), "/Volumes/CPM-20Tb/CLAWBENCH", components=("vcf",))
    assert {p["kind"] for p in plan} == {"vcf"}
    assert any(p["id"] == "HG005_vcf" for p in plan)


def test_dry_run_downloads_nothing_and_returns_plan():
    calls = []
    dl = lambda url, dest: calls.append((url, dest))
    res = GI.ingest(_manifest(), "/Volumes/CPM-20Tb/CLAWBENCH", components=("reference", "bed"),
                    downloader=dl, dry_run=True, usage=lambda p: types.SimpleNamespace(free=14 * 10**12))
    assert calls == []                                       # nothing downloaded
    assert res["dry_run"] is True
    assert len(res["plan"]) == 3                             # ref + 2 sample beds


def test_ingest_fails_closed_on_low_disk_even_in_dry_run():
    with pytest.raises(GI.DiskGuardError):
        GI.ingest(_manifest(), "/Volumes/CPM-20Tb/CLAWBENCH", components=("reference",),
                  downloader=lambda u, d: None, dry_run=True,
                  usage=lambda p: types.SimpleNamespace(free=10 * 10**9))


def test_ingest_writes_and_verifies_hashes(tmp_path):
    # use tmp_path as a stand-in workdir; bypass the external guard explicitly for the test
    payload = {}
    def dl(url, dest):
        from pathlib import Path
        Path(dest).parent.mkdir(parents=True, exist_ok=True)
        Path(dest).write_bytes(b"data:" + url.encode())
    res = GI.ingest(_manifest(), str(tmp_path), components=("bed",), downloader=dl, dry_run=False,
                    allow_internal=True, usage=lambda p: types.SimpleNamespace(free=14 * 10**12))
    assert res["dry_run"] is False
    assert all(v["sha256"] for v in res["artifacts"].values())
    assert (tmp_path / "MANIFEST.lock.yaml").exists()
    # second run verifies against the just-written lock and stays consistent
    res2 = GI.ingest(_manifest(), str(tmp_path), components=("bed",), downloader=dl, dry_run=False,
                     allow_internal=True, usage=lambda p: types.SimpleNamespace(free=14 * 10**12))
    assert all(v["status"] == "verified" for v in res2["artifacts"].values())
