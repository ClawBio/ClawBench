"""TDD for chr20 truth subsetting (Exp 2, Phase 1).

Derives the chr20 development truth (VCF + confident BED) from the GIAB benchmark, preferring
remote-range extraction so genome-wide files are never downloaded to the (full) internal disk. The
command builders and the BED stream-filter are pure and tested; the bcftools call shells out on the
host. Every derived artefact is hashed; dry-run is supported.
"""
from __future__ import annotations

import io
import types

import chr20_subset as CS


def test_bcftools_region_cmd_uses_remote_range():
    cmd = CS.bcftools_region_cmd("http://x/HG002.vcf.gz", region="chr20",
                                 out="/Volumes/CPM-20Tb/CLAWBENCH/truth/HG002.chr20.vcf.gz")
    s = " ".join(cmd)
    assert cmd[0] == "bcftools" and "view" in cmd
    assert "-r" in cmd and "chr20" in s
    assert "-Oz" in cmd                                   # bgzipped output
    assert "http://x/HG002.vcf.gz" in s                   # reads the remote URL directly (range)
    assert s.strip().endswith("HG002.chr20.vcf.gz") or "-o" in cmd


def test_filter_bed_keeps_only_target_chrom():
    bed = "chr1\t10\t20\nchr20\t100\t200\nchr20\t300\t400\nchr2\t5\t6\n"
    out = io.StringIO()
    n = CS.filter_bed(io.StringIO(bed), out, chrom="chr20")
    lines = [l for l in out.getvalue().splitlines() if l.strip()]
    assert n == 2
    assert all(l.startswith("chr20\t") for l in lines)


def test_filter_bed_ignores_comments_and_blank():
    bed = "# header\n\nchr20\t1\t2\ntrack name=x\nchr20\t3\t4\n"
    out = io.StringIO()
    n = CS.filter_bed(io.StringIO(bed), out, chrom="chr20")
    assert n == 2


def test_plan_subset_lists_vcf_and_bed_outputs():
    samples = [{"id": "HG002", "vcf": "http://x/HG002.vcf.gz", "bed": "http://x/HG002.bed"}]
    plan = CS.plan_subset(samples, "/Volumes/CPM-20Tb/CLAWBENCH", region="chr20")
    outs = {p["out"] for p in plan}
    assert any(o.endswith("HG002.chr20.vcf.gz") for o in outs)
    assert any(o.endswith("HG002.chr20.bed") for o in outs)
    assert all(o.startswith("/Volumes/CPM-20Tb/CLAWBENCH/") for o in outs)


def test_dry_run_does_not_execute_or_write(tmp_path):
    ran = []
    samples = [{"id": "HG002", "vcf": "http://x/HG002.vcf.gz", "bed": "http://x/HG002.bed"}]
    res = CS.subset(samples, str(tmp_path), region="chr20", dry_run=True,
                    runner=lambda cmd: ran.append(cmd),
                    bed_fetcher=lambda url: io.StringIO("chr20\t1\t2\n"),
                    usage=lambda p: types.SimpleNamespace(free=14 * 10**12), allow_internal=True)
    assert ran == []
    assert res["dry_run"] is True
    assert len(res["plan"]) == 2
    assert not list(tmp_path.iterdir())                   # nothing written


def test_subset_hashes_every_derived_artefact(tmp_path):
    samples = [{"id": "HG002", "vcf": "http://x/HG002.vcf.gz", "bed": "http://x/HG002.bed"}]
    def runner(cmd):                                       # fake bcftools: write a tiny output file
        out = cmd[cmd.index("-o") + 1] if "-o" in cmd else cmd[-1]
        from pathlib import Path
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_bytes(b"\x1f\x8b" + b"vcfdata")    # pretend bgzip
    res = CS.subset(samples, str(tmp_path), region="chr20", dry_run=False, runner=runner,
                    bed_fetcher=lambda url: io.StringIO("chr1\t1\t2\nchr20\t10\t20\n"),
                    usage=lambda p: types.SimpleNamespace(free=14 * 10**12), allow_internal=True)
    arts = res["artifacts"]
    assert all(a["sha256"] for a in arts.values())
    assert any(k.endswith("HG002.chr20.bed") for k in arts)
    assert (tmp_path / "chr20_truth_freeze.json").exists()
