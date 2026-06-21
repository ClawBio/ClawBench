"""TDD for the nfcore-sarek-wrapper skill (Exp 2), real-execution wiring.

The wrapper builds a fully pinned germline command + provenance and refuses to run unless the pipeline
version, Nextflow version, reference, and region are pinned (for sarek, pipeline + Nextflow versions
pin the per-process containers). Execution goes through an injected runner; the default runner sets
NXF_VER. Dry-run emits the plan only.
"""
from __future__ import annotations

import run_sarek as RS
import pytest


def _pinned():
    return {
        "sarek_version": "3.8.1",
        "nxf_ver": "25.10.2",
        "fasta": "/cb/reference/GRCh38.fasta",
        "reference_sha256": "a" * 64,
        "tools": "haplotypecaller",
        "step": "mapping",
        "intervals_bed": "/cb/truth/HG002.chr20.bed",
        "skip_tools": "baserecalibrator",
        "extra_config": "/cb/arm64.config",
        "wes": False,
    }


def test_validate_pins_accepts_fully_pinned():
    RS.validate_pins(_pinned())


def test_validate_pins_fails_closed_on_unpinned():
    for mutate in (
        lambda c: c.update(sarek_version="latest"),
        lambda c: c.update(nxf_ver=None),
        lambda c: c.update(nxf_ver="latest"),
        lambda c: c.update(fasta=None),
        lambda c: c.update(reference_sha256=None),
        lambda c: c.update(intervals_bed=None),
        lambda c: c.update(container_digests={"sarek": "quay.io/nf-core/sarek:3.8.1"}),  # tag, not digest
    ):
        cfg = _pinned()
        mutate(cfg)
        with pytest.raises(RS.UnpinnedError):
            RS.validate_pins(cfg)


def test_profile_for_arch():
    assert RS.profile_for_arch("arm64_local")["engine"] == "docker"
    assert "rosetta" in RS.profile_for_arch("arm64_local")["note"].lower()
    assert RS.profile_for_arch("cloud")["profile"] not in ("docker",)
    with pytest.raises(ValueError):
        RS.profile_for_arch("windows")


def test_nextflow_command_is_a_real_germline_run():
    cmd = RS.nextflow_command(_pinned(), samplesheet="HG002.csv", outdir="out/HG002",
                              arch="arm64_local", work_dir="/Volumes/ramdisk/HG002")
    s = " ".join(cmd)
    assert cmd[:3] == ["nextflow", "run", "nf-core/sarek"]
    assert "-r" in cmd and "3.8.1" in s
    assert "-profile" in cmd and "docker" in s
    assert "-c" in cmd and "/cb/arm64.config" in s          # the --platform=linux/amd64 config
    assert "--input" in s and "HG002.csv" in s
    assert "-w" in cmd and "/Volumes/ramdisk/HG002" in s    # RAM-disk work dir
    assert "--tools" in s and "haplotypecaller" in s
    assert "--intervals" in s and "HG002.chr20.bed" in s
    assert "--fasta" in s and "GRCh38.fasta" in s and "--igenomes_ignore" in s
    assert "--skip_tools" in s and "baserecalibrator" in s


def test_build_provenance_complete_and_deterministic():
    inputs = [{"path": "HG002.R1.fastq.gz", "sha256": "c" * 64}]
    p1 = RS.build_provenance(_pinned(), inputs=inputs, arch="arm64_local", samplesheet="s.csv",
                             outdir="o", now="2026-06-19T00:00:00Z", work_dir="/Volumes/ramdisk/HG002")
    p2 = RS.build_provenance(_pinned(), inputs=inputs, arch="arm64_local", samplesheet="s.csv",
                             outdir="o", now="2026-06-19T00:00:00Z", work_dir="/Volumes/ramdisk/HG002")
    assert p1["content_hash"] == p2["content_hash"]
    for k in ("sarek_version", "nxf_ver", "fasta", "reference_sha256", "intervals_bed", "command", "work_dir"):
        assert k in p1


def test_run_dry_run_emits_plan_without_executing():
    ran = []
    res = RS.run(_pinned(), samplesheet="s.csv", outdir="o", arch="arm64_local",
                 inputs=[], work_dir="/Volumes/ramdisk/HG002", dry_run=True,
                 runner=lambda cmd: ran.append(cmd), now="t")
    assert ran == []
    assert res["dry_run"] is True
    assert res["nxf_ver"] == "25.10.2"


def test_run_fails_closed_before_executing_when_unpinned():
    ran = []
    cfg = _pinned(); cfg["nxf_ver"] = None
    with pytest.raises(RS.UnpinnedError):
        RS.run(cfg, samplesheet="s.csv", outdir="o", arch="arm64_local", inputs=[], dry_run=False,
               runner=lambda cmd: ran.append(cmd), now="t")
    assert ran == []


def test_run_writes_provenance_before_executing():
    events = []
    RS.run(_pinned(), samplesheet="s.csv", outdir="o", arch="linux_x86", inputs=[],
           work_dir="/w", dry_run=False, runner=lambda cmd: events.append("run"),
           provenance_writer=lambda prov: events.append("prov"), now="t")
    assert events == ["prov", "run"]
