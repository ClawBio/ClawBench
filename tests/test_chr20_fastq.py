"""TDD for chr20 FASTQ extraction (Exp 2, Phase 1b), execution-mocked.

Streams ONLY chr20 reads from the GIAB Illumina 300x novoalign BAMs by remote range (samtools -X with
a locally-fetched .bai), downsamples 300x -> ~30x reproducibly (fixed seed), and converts to paired
FASTQ for sarek. The fraction maths and the samtools pipeline are pure and tested; samtools shells out
on the host. External-disk + free-disk guards (shared with giab_ingest), dry-run, and output hashing.
"""
from __future__ import annotations

import io
import types

import chr20_fastq as CF


def test_downsample_fraction():
    assert abs(CF.downsample_fraction(300, 30) - 0.1) < 1e-9
    assert CF.downsample_fraction(30, 30) == 1.0
    assert CF.downsample_fraction(30, 60) == 1.0          # never upsample beyond the source


def test_subsample_arg_encodes_seed_and_fraction():
    # samtools -s FLOAT: integer part = seed, fractional part = fraction kept
    assert CF.subsample_arg(0.1, seed=42) == "42.1000"
    assert CF.subsample_arg(0.05, seed=7) == "7.0500"
    assert CF.subsample_arg(1.0, seed=42) is None         # no downsampling when keeping everything


def test_extract_pipeline_builds_region_downsample_fastq():
    cmd = CF.extract_pipeline(bam="https://x/HG002.bam", bai="HG002.bai", region="chr20",
                              sub="42.1000", out_r1="HG002.r1.fq.gz", out_r2="HG002.r2.fq.gz",
                              threads=8)
    assert "samtools view -X" in cmd
    assert "-s 42.1000" in cmd
    assert "https://x/HG002.bam" in cmd and "HG002.bai" in cmd and "chr20" in cmd
    assert "samtools collate" in cmd
    assert "samtools fastq" in cmd
    assert "-1 HG002.r1.fq.gz" in cmd and "-2 HG002.r2.fq.gz" in cmd


def test_extract_pipeline_omits_subsample_when_none():
    cmd = CF.extract_pipeline(bam="b", bai="i", region="chr20", sub=None,
                              out_r1="r1", out_r2="r2", threads=4)
    # no downsample flag in the view stage (note: 'samtools fastq -s /dev/null' is the singleton file)
    assert "samtools view -X -u b i chr20" in cmd
    assert "-s 42" not in cmd


def test_plan_lists_paired_outputs_under_workdir():
    aln = [{"id": "HG002", "bam": "https://x/HG002.bam"}]
    plan = CF.plan(aln, "/Volumes/CPM-20Tb/CLAWBENCH", region="chr20")
    p = plan[0]
    assert p["out_r1"].endswith("HG002.chr20.R1.fastq.gz")
    assert p["out_r2"].endswith("HG002.chr20.R2.fastq.gz")
    assert p["bai_url"] == "https://x/HG002.bam.bai"
    assert p["out_r1"].startswith("/Volumes/CPM-20Tb/CLAWBENCH/")


def test_dry_run_downloads_nothing_runs_nothing(tmp_path):
    aln = [{"id": "HG002", "bam": "https://x/HG002.bam"}]
    dl, run = [], []
    res = CF.extract(aln, str(tmp_path), region="chr20", source_x=300, target_x=30, dry_run=True,
                     downloader=lambda u, d: dl.append(u), runner=lambda c: run.append(c),
                     usage=lambda p: types.SimpleNamespace(free=14 * 10**12), allow_internal=True)
    assert dl == [] and run == []
    assert res["dry_run"] is True
    assert res["plan"][0]["sub"] == "42.1000"             # 30/300 downsample encoded


def test_extract_skips_already_extracted_samples(tmp_path):
    # pre-create non-empty paired FASTQ for HG002; extract must NOT re-run it
    (tmp_path / "fastq").mkdir()
    (tmp_path / "fastq" / "HG002.chr20.R1.fastq.gz").write_bytes(b"@r\nACGT\n+\nIIII\n")
    (tmp_path / "fastq" / "HG002.chr20.R2.fastq.gz").write_bytes(b"@r\nACGT\n+\nIIII\n")
    ran = []
    aln = [{"id": "HG002", "bam": "https://x/HG002.bam"}]
    res = CF.extract(aln, str(tmp_path), region="chr20", source_x=300, target_x=30, dry_run=False,
                     downloader=lambda u, d: None, runner=lambda c: ran.append(c),
                     usage=lambda p: types.SimpleNamespace(free=14 * 10**12), allow_internal=True)
    assert ran == []                                       # skipped, nothing executed
    assert any(a.get("skipped") for a in res["artifacts"].values())


def test_extract_fetches_bai_runs_pipeline_and_hashes(tmp_path):
    aln = [{"id": "HG002", "bam": "https://x/HG002.bam"}]
    def dl(url, dest):
        from pathlib import Path
        Path(dest).parent.mkdir(parents=True, exist_ok=True); Path(dest).write_bytes(b"BAI")
    def run(cmd):                                          # fake samtools: write tiny fastqs
        import re
        from pathlib import Path
        for flag in ("-1", "-2"):
            m = re.search(flag + r" (\S+)", cmd)
            Path(m.group(1)).write_bytes(b"@r\nACGT\n+\nIIII\n")
    res = CF.extract(aln, str(tmp_path), region="chr20", source_x=300, target_x=30, dry_run=False,
                     downloader=dl, runner=run,
                     usage=lambda p: types.SimpleNamespace(free=14 * 10**12), allow_internal=True)
    arts = res["artifacts"]
    assert all(a["sha256"] for a in arts.values())
    assert any(k.endswith("HG002.chr20.R1.fastq.gz") for k in arts)
    assert (tmp_path / "chr20_fastq_freeze.json").exists()
