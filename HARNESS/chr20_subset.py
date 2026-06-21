"""chr20 development-truth subsetting (Exp 2, Phase 1).

Derives the chr20 dev truth (benchmark VCF + confident BED) from the genome-wide GIAB benchmark.
The VCF is extracted by REMOTE RANGE (bcftools reads the indexed URL and pulls only chr20, so the
genome-wide file is never downloaded to the full internal disk); the BED is streamed and filtered to
the target chromosome. Every derived artefact is hashed and recorded in a frozen manifest. Dry-run
and the external-disk / free-disk guards (shared with giab_ingest) are enforced. No import-time IO.

On the host:
  python3 HARNESS/chr20_subset.py --manifest TRUTH/MANIFEST.yaml \
      --workdir /Volumes/CPM-20Tb/CLAWBENCH --region chr20 [--dry-run]
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from urllib.request import urlopen

import ingest_truth as it
import giab_ingest as GI

DEFAULT_WORKDIR = GI.DEFAULT_WORKDIR


def bcftools_region_cmd(src_url_or_path, *, region="chr20", out, bcftools="bcftools") -> list[str]:
    """argv for a remote-range region extraction to a bgzipped VCF. bcftools reads the indexed source
    (URL or path) and writes only `region`, so no genome-wide download is required."""
    return [bcftools, "view", "-r", region, "-Oz", "-o", str(out), str(src_url_or_path)]


def filter_bed(in_stream, out_stream, chrom="chr20") -> int:
    """Write only the lines of a BED whose first column equals `chrom`. Skips comments/track/blank.
    Returns the number of intervals written."""
    n = 0
    for line in in_stream:
        s = line.strip()
        if not s or s.startswith("#") or s.startswith("track") or s.startswith("browser"):
            continue
        if s.split("\t", 1)[0] == chrom:
            out_stream.write(line if line.endswith("\n") else line + "\n")
            n += 1
    return n


def plan_subset(samples, workdir, *, region="chr20") -> list[dict]:
    """Pure plan: the chr20 VCF + BED outputs for each sample (no IO)."""
    workdir = str(workdir).rstrip("/")
    out: list[dict] = []
    for s in samples:
        sid = s["id"]
        if s.get("vcf"):
            out.append({"id": f"{sid}_vcf", "kind": "vcf", "src": s["vcf"], "region": region,
                        "out": f"{workdir}/truth/{sid}.{region}.vcf.gz"})
        if s.get("bed"):
            out.append({"id": f"{sid}_bed", "kind": "bed", "src": s["bed"], "region": region,
                        "out": f"{workdir}/truth/{sid}.{region}.bed"})
    return out


def _sha256_bytes_of_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for blk in iter(lambda: fh.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()


def _default_bed_fetcher(url):
    return urlopen(url)  # stream; filter_bed reads it line by line


def subset(samples, workdir, *, region="chr20", dry_run=False, runner=None,
           bed_fetcher=_default_bed_fetcher, min_free=GI.MIN_FREE_BYTES, usage=None,
           allow_internal=False) -> dict:
    """Derive chr20 truth for each sample. `runner(cmd)` executes bcftools (injected for testing);
    `bed_fetcher(url)` returns a text stream of the genome-wide BED. Hashes every output and writes a
    frozen manifest."""
    import shutil
    usage = usage or shutil.disk_usage
    GI.assert_external_workdir(workdir, allow_internal=allow_internal)
    GI.assert_free_disk(workdir, min_bytes=min_free, usage=usage)

    items = plan_subset(samples, workdir, region=region)
    if dry_run:
        return {"dry_run": True, "workdir": str(workdir), "plan": items}

    if runner is None:
        import subprocess
        runner = lambda cmd: subprocess.run(cmd, check=True)

    artifacts: dict = {}
    for art in items:
        out = Path(art["out"])
        out.parent.mkdir(parents=True, exist_ok=True)
        if art["kind"] == "vcf":
            runner(bcftools_region_cmd(art["src"], region=region, out=out))
        else:  # bed: stream + filter
            stream = bed_fetcher(art["src"])
            text = stream.read()
            if isinstance(text, bytes):
                text = text.decode()
            import io as _io
            buf = _io.StringIO()
            filter_bed(_io.StringIO(text), buf, chrom=region)
            out.write_text(buf.getvalue())
        rel = str(out.relative_to(Path(workdir)))
        artifacts[rel] = {"kind": art["kind"], "sha256": _sha256_bytes_of_file(out)}

    freeze = {"schema_version": 1, "name": f"giab_{region}_truth_freeze",
              "region": region, "artifacts": artifacts}
    canonical = json.dumps(artifacts, sort_keys=True, separators=(",", ":"))
    freeze["content_hash"] = hashlib.sha256(canonical.encode()).hexdigest()
    (Path(workdir) / f"{region}_truth_freeze.json").write_text(json.dumps(freeze, indent=2))
    return {"dry_run": False, "workdir": str(workdir), "artifacts": artifacts,
            "content_hash": freeze["content_hash"]}


def main() -> None:
    ap = argparse.ArgumentParser(description="Derive chr20 dev truth by remote range (external disk only)")
    ap.add_argument("--manifest", required=True, type=Path)
    ap.add_argument("--workdir", default=DEFAULT_WORKDIR)
    ap.add_argument("--region", default="chr20")
    ap.add_argument("--min-free-gb", type=int, default=500)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--allow-internal", action="store_true", help="testing only")
    args = ap.parse_args()

    vroot = GI._volume_root(args.workdir)
    if vroot is not None and not vroot.exists() and not args.allow_internal:
        raise SystemExit(f"external volume not mounted: {vroot} (workdir {args.workdir})")

    manifest = it.load_manifest(args.manifest)
    samples = manifest.get("giab_samples", []) or []
    res = subset(samples, args.workdir, region=args.region, dry_run=args.dry_run,
                 min_free=args.min_free_gb * 10**9, allow_internal=args.allow_internal)
    if res["dry_run"]:
        print(f"DRY RUN, workdir {res['workdir']}, {len(res['plan'])} chr20 artefacts planned:")
        for p in res["plan"]:
            verb = "bcftools view -r" if p["kind"] == "vcf" else "stream+filter"
            print(f"  [{p['kind']:3}] {verb} {p['region']}  {p['src']}  ->  {p['out']}")
    else:
        for rel, info in sorted(res["artifacts"].items()):
            print(f"  [{info['kind']:3}] {rel}  {info['sha256'][:12]}")
        print(f"{len(res['artifacts'])} artefacts; freeze content_hash {res['content_hash'][:16]}")


if __name__ == "__main__":
    main()
