"""chr20 FASTQ extraction (Exp 2, Phase 1b). Runs on the Mac Studio external volume.

Streams only chr20 reads from the GIAB Illumina 300x novoalign GRCh38 BAMs by remote range (samtools
-X with a locally-fetched .bai, so the full ~250 GB BAM is never downloaded), downsamples 300x to a
target ~30x reproducibly (fixed seed), and writes paired FASTQ for nf-core/sarek. Every output is
hashed; external-disk + free-disk guards (shared with giab_ingest), dry-run supported. No import-time IO.

On the host (samtools on PATH):
  python3 HARNESS/chr20_fastq.py --manifest TRUTH/MANIFEST.yaml --workdir /Volumes/CPM-20Tb/CLAWBENCH \
      --region chr20 --target-x 30 [--dry-run]
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from urllib.request import urlretrieve

import ingest_truth as it
import giab_ingest as GI

DEFAULT_WORKDIR = GI.DEFAULT_WORKDIR
SEED = 42  # fixed for reproducible downsampling


def downsample_fraction(source_x: float, target_x: float) -> float:
    """Fraction of reads to keep to go from source coverage to target; never above 1.0 (no upsample)."""
    return min(target_x / source_x, 1.0) if source_x else 1.0


def subsample_arg(fraction: float, seed: int = SEED):
    """samtools -s value: integer part = seed, fractional part = fraction kept. None if keeping all."""
    if fraction >= 1.0:
        return None
    return f"{seed + fraction:.4f}"


def extract_pipeline(*, bam, bai, region, sub, out_r1, out_r2, threads=4,
                     collate_prefix="collate_tmp", samtools="samtools") -> str:
    """The shell pipeline: range-read chr20 -> (optional downsample) -> collate -> paired FASTQ."""
    s = f"-s {sub} " if sub else ""
    view = f"{samtools} view -X -u {s}{bam} {bai} {region}"
    collate = f"{samtools} collate -u -O -@ {threads} - {collate_prefix}"
    fastq = (f"{samtools} fastq -@ {threads} -1 {out_r1} -2 {out_r2} "
             f"-0 /dev/null -s /dev/null -n -")
    return f"{view} | {collate} | {fastq}"


def plan(alignments, workdir, *, region="chr20") -> list[dict]:
    workdir = str(workdir).rstrip("/")
    out = []
    for a in alignments:
        sid, bam = a["id"], a["bam"]
        out.append({"id": sid, "bam": bam, "bai_url": bam + ".bai", "region": region,
                    "bai_local": f"{workdir}/truth/{sid}.bam.bai",
                    "out_r1": f"{workdir}/fastq/{sid}.{region}.R1.fastq.gz",
                    "out_r2": f"{workdir}/fastq/{sid}.{region}.R2.fastq.gz"})
    return out


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for blk in iter(lambda: fh.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()


def extract(alignments, workdir, *, region="chr20", source_x=300, target_x=30, dry_run=False,
            downloader=urlretrieve, runner=None, threads=4, min_free=GI.MIN_FREE_BYTES, usage=None,
            allow_internal=False) -> dict:
    """Per sample: fetch the .bai locally, stream+downsample chr20 to paired FASTQ, hash outputs."""
    import shutil
    usage = usage or shutil.disk_usage
    GI.assert_external_workdir(workdir, allow_internal=allow_internal)
    GI.assert_free_disk(workdir, min_bytes=min_free, usage=usage)

    frac = downsample_fraction(source_x, target_x)
    sub = subsample_arg(frac)
    items = plan(alignments, workdir, region=region)
    for p in items:
        p["sub"] = sub
    if dry_run:
        return {"dry_run": True, "workdir": str(workdir), "fraction": frac, "plan": items}

    if runner is None:
        import subprocess
        runner = lambda cmd: subprocess.run(["bash", "-c", cmd], check=True)

    artifacts = {}
    for p in items:
        # idempotent: skip a sample whose paired FASTQ already exists and is non-empty
        r1e, r2e = Path(p["out_r1"]), Path(p["out_r2"])
        if r1e.exists() and r2e.exists() and r1e.stat().st_size > 0 and r2e.stat().st_size > 0:
            for key in ("out_r1", "out_r2"):
                f = Path(p[key]); artifacts[str(f.relative_to(Path(workdir)))] = {
                    "sha256": _sha256(f), "sample": p["id"], "skipped": True}
            continue
        bai = Path(p["bai_local"]); bai.parent.mkdir(parents=True, exist_ok=True)
        if not bai.exists():
            downloader(p["bai_url"], str(bai))
        Path(p["out_r1"]).parent.mkdir(parents=True, exist_ok=True)
        cmd = extract_pipeline(bam=p["bam"], bai=str(bai), region=region, sub=sub,
                               out_r1=p["out_r1"], out_r2=p["out_r2"], threads=threads,
                               collate_prefix=f"{Path(p['out_r1']).parent}/collate_{p['id']}")
        runner(cmd)
        for key in ("out_r1", "out_r2"):
            f = Path(p[key])
            rel = str(f.relative_to(Path(workdir)))
            artifacts[rel] = {"sha256": _sha256(f), "sample": p["id"]}

    freeze = {"schema_version": 1, "name": f"giab_{region}_fastq_freeze", "region": region,
              "source_coverage_x": source_x, "target_coverage_x": target_x,
              "downsample_fraction": frac, "seed": SEED, "artifacts": artifacts}
    canonical = json.dumps(artifacts, sort_keys=True, separators=(",", ":"))
    freeze["content_hash"] = hashlib.sha256(canonical.encode()).hexdigest()
    (Path(workdir) / f"{region}_fastq_freeze.json").write_text(json.dumps(freeze, indent=2))
    return {"dry_run": False, "workdir": str(workdir), "fraction": frac, "artifacts": artifacts,
            "content_hash": freeze["content_hash"]}


def main() -> None:
    ap = argparse.ArgumentParser(description="Extract chr20 FASTQ by remote range (external disk only)")
    ap.add_argument("--manifest", required=True, type=Path)
    ap.add_argument("--workdir", default=DEFAULT_WORKDIR)
    ap.add_argument("--region", default="chr20")
    ap.add_argument("--target-x", type=int, default=30)
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--min-free-gb", type=int, default=500)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--allow-internal", action="store_true", help="testing only")
    args = ap.parse_args()

    vroot = GI._volume_root(args.workdir)
    if vroot is not None and not vroot.exists() and not args.allow_internal:
        raise SystemExit(f"external volume not mounted: {vroot}")

    manifest = it.load_manifest(args.manifest)
    fq = manifest.get("fastq", {})
    alns = fq.get("alignments", []) or []
    if not alns:
        raise SystemExit("manifest fastq.alignments is empty")
    res = extract(alns, args.workdir, region=args.region, source_x=fq.get("source_coverage_x", 300),
                  target_x=args.target_x, threads=args.threads, dry_run=args.dry_run,
                  min_free=args.min_free_gb * 10**9, allow_internal=args.allow_internal)
    if res["dry_run"]:
        print(f"DRY RUN, workdir {res['workdir']}, downsample fraction {res['fraction']:.4f}:")
        for p in res["plan"]:
            print(f"  [{p['id']}] range {p['region']} from {p['bam']}")
            print(f"          -> {p['out_r1']} , {p['out_r2']}")
    else:
        for rel, info in sorted(res["artifacts"].items()):
            print(f"  {info['sample']}  {rel}  {info['sha256'][:12]}")
        print(f"freeze content_hash {res['content_hash'][:16]}")


if __name__ == "__main__":
    main()
