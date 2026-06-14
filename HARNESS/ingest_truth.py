"""Fetch and verify ClawBench ground-truth artifacts from TRUTH/MANIFEST.yaml.

Fails closed on checksum mismatch. When an artifact has no expected sha256 in the
manifest, the computed hash is recorded to MANIFEST.lock.yaml so the next run verifies.

No side effects at import time (per project standards). Network access is injected as
the `downloader` argument so the core logic is testable offline.
"""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
from urllib.request import urlretrieve

import yaml


class ManifestMismatch(Exception):
    """Raised when a downloaded file's sha256 does not match the manifest."""


def sha256(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def load_manifest(path: Path) -> dict:
    with open(path) as fh:
        return yaml.safe_load(fh)


def flatten_artifacts(manifest: dict) -> list[dict]:
    """Normalise the manifest's heterogeneous sections into {id, url, dest, sha256}."""
    arts: list[dict] = []
    for section in ("reference", "stratifications", "clinvar"):
        for entry in manifest.get(section, []) or []:
            arts.append(
                {
                    "id": entry["id"],
                    "url": entry["url"],
                    "dest": entry["dest"],
                    "sha256": entry.get("sha256"),
                }
            )
    for sample in manifest.get("giab_samples", []) or []:
        sid = sample["id"]
        for kind, ext in (("vcf", "vcf.gz"), ("bed", "bed")):
            if sample.get(kind):
                arts.append(
                    {
                        "id": f"{sid}_{kind}",
                        "url": sample[kind],
                        "dest": f"giab/{sid}.{ext}",
                        "sha256": sample.get(f"{kind}_sha256"),
                    }
                )
    return arts


def ingest(manifest: dict, dest_root: Path, downloader=urlretrieve) -> dict:
    """Download (if missing), verify or record sha256 for each artifact. Fails closed."""
    dest_root = Path(dest_root)
    summary: dict = {}
    lock: dict = {}
    for art in flatten_artifacts(manifest):
        dest = dest_root / art["dest"]
        if not dest.exists():
            downloader(art["url"], str(dest))
        digest = sha256(dest)
        expected = art["sha256"]
        if expected:
            if digest != expected:
                raise ManifestMismatch(
                    f"{art['dest']}: expected {expected}, got {digest}"
                )
            status = "verified"
        else:
            status = "recorded"
        lock[art["dest"]] = digest
        summary[art["dest"]] = {"status": status, "sha256": digest}

    lock_path = dest_root / "MANIFEST.lock.yaml"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "w") as fh:
        yaml.safe_dump(lock, fh, sort_keys=True)
    return summary


def main() -> None:
    ap = argparse.ArgumentParser(description="Fetch + verify ClawBench truth artifacts")
    ap.add_argument("--manifest", required=True, type=Path)
    ap.add_argument("--dest", required=True, type=Path)
    args = ap.parse_args()

    manifest = load_manifest(args.manifest)
    summary = ingest(manifest, args.dest)
    for dest, info in sorted(summary.items()):
        print(f"{info['status']:9} {dest}  {info['sha256'][:12]}")
    print(f"{len(summary)} artifacts; lock written to {args.dest / 'MANIFEST.lock.yaml'}")


if __name__ == "__main__":
    main()
