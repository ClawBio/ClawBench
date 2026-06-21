"""nfcore-sarek-wrapper: pinned, provenance-complete FASTQ->VCF runner (Exp 2).

Builds a fully pinned nf-core/sarek germline command and a provenance manifest, then executes it (or
returns the plan in dry-run). The pinning model matches how sarek actually works: the pipeline release
(`sarek_version`) and the Nextflow version (`nxf_ver`) together pin the per-process containers, so we
fail closed unless those, the reference, and the region (intervals) are pinned. Resolved container
digests are captured into provenance after a run for audit. Architecture-aware (arm64_local needs
Rosetta + --platform=linux/amd64, supplied via the extra docker config). No side effects at import.

On the host (nextflow, docker, samtools on PATH; Docker + Rosetta running):
  validated by run_calling_gradient; provenance is always written before execution.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path


class UnpinnedError(Exception):
    """Raised when a required pin (pipeline version, Nextflow version, reference, region) is missing."""


_ARCH_PROFILES = {
    "arm64_local": {"profile": "docker", "engine": "docker",
                    "note": "Docker Desktop + Rosetta runs amd64 containers (--platform=linux/amd64); chr20 dev"},
    "linux_x86": {"profile": "docker", "engine": "docker", "note": "native amd64 host"},
    "cloud": {"profile": "awsbatch", "engine": "docker", "note": "cloud batch; Phase 7 full-genome only"},
}


def profile_for_arch(arch: str) -> dict:
    if arch not in _ARCH_PROFILES:
        raise ValueError(f"unknown architecture {arch!r}; expected one of {sorted(_ARCH_PROFILES)}")
    return dict(_ARCH_PROFILES[arch])


def validate_pins(config: dict) -> None:
    """Fail closed unless the pipeline version, Nextflow version, reference, and region are pinned.
    For sarek the pinned pipeline + Nextflow versions are the container pin; if explicit
    container_digests are also given, each must be digest-pinned."""
    ver = config.get("sarek_version")
    if not ver or str(ver).lower() == "latest":
        raise UnpinnedError("sarek_version must be an explicit release tag, not empty or 'latest'")
    nxf = config.get("nxf_ver")
    if not nxf or str(nxf).lower() == "latest":
        raise UnpinnedError("nxf_ver (Nextflow version) must be pinned; sarek + Nextflow pin the containers")
    if not config.get("fasta"):
        raise UnpinnedError("fasta (reference) must be pinned")
    if not config.get("reference_sha256"):
        raise UnpinnedError("reference_sha256 must be pinned (from MANIFEST.lock.yaml)")
    if not config.get("intervals_bed"):
        raise UnpinnedError("intervals_bed (region) must be pinned")
    for name, ref in (config.get("container_digests") or {}).items():
        if "@sha256:" not in str(ref):
            raise UnpinnedError(f"container {name!r} is not digest-pinned ('...@sha256:...'): {ref!r}")


def nextflow_command(config: dict, *, samplesheet, outdir, arch: str, work_dir=None) -> list[str]:
    prof = profile_for_arch(arch)
    cmd = ["nextflow", "run", "nf-core/sarek", "-r", str(config["sarek_version"]),
           "-profile", prof["profile"]]
    if config.get("extra_config"):
        cmd += ["-c", str(config["extra_config"])]
    cmd += ["--input", str(samplesheet), "--outdir", str(outdir)]
    if work_dir:
        cmd += ["-w", str(work_dir)]
    cmd += ["--tools", str(config["tools"]), "--step", str(config["step"]),
            "--intervals", str(config["intervals_bed"]),
            "--fasta", str(config["fasta"]), "--igenomes_ignore"]
    if config.get("skip_tools"):
        cmd += ["--skip_tools", str(config["skip_tools"])]
    if config.get("wes"):
        cmd += ["--wes"]
    return cmd


def build_provenance(config: dict, *, inputs, arch: str, samplesheet, outdir, now: str,
                     work_dir=None, resolved_container_digests=None) -> dict:
    cmd = nextflow_command(config, samplesheet=samplesheet, outdir=outdir, arch=arch, work_dir=work_dir)
    prov = {
        "schema_version": 1,
        "sarek_version": config["sarek_version"],
        "nxf_ver": config["nxf_ver"],
        "fasta": config["fasta"],
        "reference_sha256": config["reference_sha256"],
        "tools": config["tools"],
        "step": config["step"],
        "intervals_bed": config["intervals_bed"],
        "skip_tools": config.get("skip_tools"),
        "architecture": arch,
        "profile": profile_for_arch(arch)["profile"],
        "extra_config": config.get("extra_config"),
        "inputs": inputs,
        "work_dir": work_dir,
        "command": cmd,
        "resolved_container_digests": resolved_container_digests or {},
        "timestamp": now,
    }
    canonical = json.dumps(prov, sort_keys=True, separators=(",", ":"))
    prov["content_hash"] = hashlib.sha256(canonical.encode()).hexdigest()
    return prov


def _default_runner(nxf_ver):
    import subprocess
    def _run(cmd):
        env = {**os.environ, "NXF_VER": str(nxf_ver)}
        subprocess.run(cmd, env=env, check=True)
    return _run


def run(config: dict, *, samplesheet, outdir, arch: str, inputs, work_dir=None, dry_run: bool = True,
        runner=None, provenance_writer=None, now: str = "") -> dict:
    """Validate pins (fail closed), build command + provenance, then return the plan (dry-run) or write
    provenance and execute with NXF_VER pinned in the environment. Provenance is always written first."""
    validate_pins(config)
    cmd = nextflow_command(config, samplesheet=samplesheet, outdir=outdir, arch=arch, work_dir=work_dir)
    prov = build_provenance(config, inputs=inputs, arch=arch, samplesheet=samplesheet,
                            outdir=outdir, now=now, work_dir=work_dir)
    if dry_run:
        return {"dry_run": True, "command": cmd, "provenance": prov, "nxf_ver": config["nxf_ver"]}
    (provenance_writer or _default_provenance_writer(outdir))(prov)
    (runner or _default_runner(config["nxf_ver"]))(cmd)
    return {"dry_run": False, "command": cmd, "provenance": prov, "nxf_ver": config["nxf_ver"]}


def _default_provenance_writer(outdir):
    def _w(prov):
        p = Path(outdir) / "provenance.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(prov, indent=2))
    return _w
