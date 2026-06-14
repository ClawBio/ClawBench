import hashlib
from pathlib import Path

import pytest

import ingest_truth as it


def test_sha256_known(tmp_path):
    f = tmp_path / "x.bin"
    f.write_bytes(b"hello")
    assert it.sha256(f) == hashlib.sha256(b"hello").hexdigest()


def test_load_manifest_real():
    manifest = Path(__file__).resolve().parents[1] / "TRUTH" / "MANIFEST.yaml"
    m = it.load_manifest(manifest)
    assert m["reference_build"] == "GRCh38"
    ids = {s["id"] for s in m["giab_samples"]}
    assert {"HG001", "HG002", "HG005"} <= ids


def test_flatten_includes_vcf_and_bed():
    m = {
        "reference": [{"id": "ref", "url": "http://x/ref.fa.gz", "dest": "reference/ref.fa.gz", "sha256": None}],
        "giab_samples": [
            {"id": "HG002", "ancestry": "AJ", "vcf": "http://x/h2.vcf.gz", "bed": "http://x/h2.bed"}
        ],
    }
    arts = it.flatten_artifacts(m)
    dests = {a["dest"] for a in arts}
    assert "reference/ref.fa.gz" in dests
    assert "giab/HG002.vcf.gz" in dests
    assert "giab/HG002.bed" in dests


def _fake_downloader(payload):
    def _dl(url, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_bytes(payload)
    return _dl


def test_ingest_records_lock_when_no_expected(tmp_path):
    m = {"reference": [{"id": "ref", "url": "http://x/ref", "dest": "reference/ref", "sha256": None}]}
    summary = it.ingest(m, tmp_path, downloader=_fake_downloader(b"data"))
    assert summary["reference/ref"]["status"] == "recorded"
    lock = it.load_manifest(tmp_path / "MANIFEST.lock.yaml")
    assert lock["reference/ref"] == hashlib.sha256(b"data").hexdigest()


def test_ingest_fails_closed_on_mismatch(tmp_path):
    bad = "0" * 64
    m = {"reference": [{"id": "ref", "url": "http://x/ref", "dest": "reference/ref", "sha256": bad}]}
    with pytest.raises(it.ManifestMismatch):
        it.ingest(m, tmp_path, downloader=_fake_downloader(b"data"))


def test_ingest_verifies_existing_without_download(tmp_path):
    payload = b"already-here"
    good = hashlib.sha256(payload).hexdigest()
    dest = tmp_path / "reference" / "ref"
    dest.parent.mkdir(parents=True)
    dest.write_bytes(payload)

    def _boom(url, path):
        raise AssertionError("downloader must not be called for an existing verified file")

    m = {"reference": [{"id": "ref", "url": "http://x/ref", "dest": "reference/ref", "sha256": good}]}
    summary = it.ingest(m, tmp_path, downloader=_boom)
    assert summary["reference/ref"]["status"] == "verified"
