"""GIAB truth ingestion (Exp 2, Phase 1). Runs on the Mac Studio external volume.

Downloads and verifies the wholesale ground-truth artefacts named in TRUTH/MANIFEST.yaml (reference
fasta, GA4GH stratifications tarball, per-sample benchmark VCF and confident BED), records sha256 to
MANIFEST.lock.yaml, and fails closed on checksum mismatch.

Guardrails (all enforced before any write):
  * external-disk only: refuses to write under the internal/boot volume (use --allow-internal only in
    tests). Default workdir is the external work volume.
  * free-disk floor: fails closed if the workdir has < 500 GB free (configurable).
  * dry-run: --dry-run prints the plan and writes nothing.
  * content hashing: every artefact is sha256'd; re-runs verify against the lock.
Network is injected (downloader) so the logic is testable offline. No side effects at import.

On the host:
  python3 HARNESS/giab_ingest.py --manifest TRUTH/MANIFEST.yaml \
      --workdir /Volumes/CPM-20Tb/CLAWBENCH --components reference,strat,bed [--dry-run]
"""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path
from urllib.request import urlretrieve

import yaml

import ingest_truth as it  # reuse sha256, load_manifest, ManifestMismatch

DEFAULT_WORKDIR = "/Volumes/CPM-20Tb/CLAWBENCH"
MIN_FREE_BYTES = 500 * 10**9  # 500 GB floor


class InternalDiskError(Exception):
    """Raised when a write would land on the internal/boot volume."""


class DiskGuardError(Exception):
    """Raised when the workdir has insufficient free space."""


def is_internal_path(path) -> bool:
    """True if the path is on the internal/boot volume. External data volumes mount under /Volumes/
    (excluding the boot volume 'Macintosh HD')."""
    s = str(path)
    if s.startswith("/Volumes/") and not s.startswith("/Volumes/Macintosh HD"):
        return False
    return True


def assert_external_workdir(path, allow_internal: bool = False) -> None:
    if allow_internal:
        return
    if is_internal_path(path):
        raise InternalDiskError(
            f"refusing to write to internal disk: {path}. Use an external volume (default {DEFAULT_WORKDIR})."
        )


def _nearest_existing(path) -> Path:
    p = Path(path)
    while not p.exists() and p != p.parent:
        p = p.parent
    return p


def _volume_root(path):
    """The external volume mount point for a /Volumes/<name>/... path, else None."""
    parts = Path(path).parts
    if len(parts) >= 3 and parts[1] == "Volumes":
        return Path("/Volumes") / parts[2]
    return None


def assert_free_disk(path, min_bytes: int = MIN_FREE_BYTES, usage=shutil.disk_usage) -> None:
    probe = _nearest_existing(path)
    try:
        free = usage(str(probe)).free
    except (FileNotFoundError, OSError) as exc:
        raise DiskGuardError(f"cannot check free space at {path} (volume mounted?): {exc}")
    if free < min_bytes:
        raise DiskGuardError(
            f"free disk on {path} is {free/10**9:.0f} GB, below the {min_bytes/10**9:.0f} GB floor."
        )


def plan(manifest: dict, workdir, components=("reference", "strat", "bed")) -> list[dict]:
    """Build the list of artefacts to ingest for the requested components (pure, no IO).
    components subset of {reference, strat, vcf, bed}. The full per-sample VCF is excluded by default
    (chr20 dev derives it by remote range; include 'vcf' only for full-genome work)."""
    workdir = str(workdir).rstrip("/")
    out: list[dict] = []
    if "reference" in components:
        for e in manifest.get("reference", []) or []:
            out.append({"id": e["id"], "kind": "reference", "url": e["url"],
                        "dest": f"{workdir}/{e['dest']}", "sha256": e.get("sha256")})
    if "strat" in components:
        for e in manifest.get("stratifications", []) or []:
            out.append({"id": e["id"], "kind": "strat", "url": e["url"],
                        "dest": f"{workdir}/{e['dest']}", "sha256": e.get("sha256")})
    for s in manifest.get("giab_samples", []) or []:
        sid = s["id"]
        if "vcf" in components and s.get("vcf"):
            out.append({"id": f"{sid}_vcf", "kind": "vcf", "url": s["vcf"],
                        "dest": f"{workdir}/truth/{sid}.vcf.gz", "sha256": s.get("vcf_sha256")})
        if "bed" in components and s.get("bed"):
            out.append({"id": f"{sid}_bed", "kind": "bed", "url": s["bed"],
                        "dest": f"{workdir}/truth/{sid}.bed", "sha256": s.get("bed_sha256")})
    return out


def _load_lock(lock_path: Path) -> dict:
    if lock_path.exists():
        return yaml.safe_load(lock_path.read_text()) or {}
    return {}


def ingest(manifest: dict, workdir, *, components=("reference", "strat", "bed"),
           downloader=urlretrieve, dry_run: bool = False, min_free: int = MIN_FREE_BYTES,
           usage=shutil.disk_usage, allow_internal: bool = False) -> dict:
    """Ingest the planned artefacts with all guardrails. Returns a summary dict."""
    assert_external_workdir(workdir, allow_internal=allow_internal)
    assert_free_disk(workdir, min_bytes=min_free, usage=usage)  # fail closed even in dry-run

    items = plan(manifest, workdir, components=components)
    if dry_run:
        return {"dry_run": True, "workdir": str(workdir), "plan": items}

    workdir = Path(workdir)
    lock_path = workdir / "MANIFEST.lock.yaml"
    lock = _load_lock(lock_path)
    artifacts: dict = {}
    for art in items:
        dest = Path(art["dest"])
        rel = str(dest.relative_to(workdir))
        if not dest.exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
            downloader(art["url"], str(dest))
        digest = it.sha256(dest)
        expected = art["sha256"] or lock.get(rel)
        if expected:
            if digest != expected:
                raise it.ManifestMismatch(f"{rel}: expected {expected}, got {digest}")
            status = "verified"
        else:
            status = "recorded"
        lock[rel] = digest
        artifacts[rel] = {"status": status, "sha256": digest, "kind": art["kind"]}

    lock_path.write_text(yaml.safe_dump(lock, sort_keys=True))
    return {"dry_run": False, "workdir": str(workdir), "artifacts": artifacts}


def main() -> None:
    ap = argparse.ArgumentParser(description="Ingest + verify GIAB truth artefacts (external disk only)")
    ap.add_argument("--manifest", required=True, type=Path)
    ap.add_argument("--workdir", default=DEFAULT_WORKDIR)
    ap.add_argument("--components", default="reference,strat,bed",
                    help="comma-separated subset of reference,strat,vcf,bed")
    ap.add_argument("--min-free-gb", type=int, default=500)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--allow-internal", action="store_true", help="testing only; bypass external guard")
    args = ap.parse_args()

    vroot = _volume_root(args.workdir)
    if vroot is not None and not vroot.exists() and not args.allow_internal:
        raise SystemExit(f"external volume not mounted: {vroot} (workdir {args.workdir})")

    manifest = it.load_manifest(args.manifest)
    res = ingest(manifest, args.workdir, components=tuple(args.components.split(",")),
                 dry_run=args.dry_run, min_free=args.min_free_gb * 10**9,
                 allow_internal=args.allow_internal)
    if res["dry_run"]:
        print(f"DRY RUN, workdir {res['workdir']}, {len(res['plan'])} artefacts planned:")
        for p in res["plan"]:
            print(f"  [{p['kind']:9}] {p['url']}  ->  {p['dest']}")
    else:
        for rel, info in sorted(res["artifacts"].items()):
            print(f"  {info['status']:9} [{info['kind']:9}] {rel}  {info['sha256'][:12]}")
        print(f"{len(res['artifacts'])} artefacts; lock at {res['workdir']}/MANIFEST.lock.yaml")


if __name__ == "__main__":
    main()
