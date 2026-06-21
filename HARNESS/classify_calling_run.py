"""Failure-taxonomy classifier + trustworthiness scorecard for the Exp 2 calling gradient.

Implements the pre-registered eight-category taxonomy (FAILURE-TAXONOMY-PREREG.md) and the
five-dimension trustworthiness scorecard (accuracy, reproducibility, provenance, pinning,
taxonomy-cleanliness). Inputs are a run record (the emitted command plus booleans/metrics from
executing it) and a baseline; outputs are deterministic, so the gradient is measured, not narrated.
Command parsing uses documented heuristics for the categories that need them (the pre-registration
flags these). No side effects at import.
"""
from __future__ import annotations

import re

_GRCH38 = re.compile(r"(?i)(grch38|hg38)")
_GRCH37 = re.compile(r"(?i)(grch37|hg19|\bb37\b)")
_DIGEST = re.compile(r"@sha256:[0-9a-f]{12,}")
_PINNED_NF = re.compile(r"(?i)nextflow\s+run\s+\S+\s+-r\s+\S+.*-profile\s+(docker|singularity|podman|apptainer)")
_LATEST = re.compile(r"(?i):latest\b")
_GERMLINE = re.compile(r"(?i)(haplotypecaller|deepvariant|freebayes|strelka(?!.*somatic)|bcftools\s+call|octopus)")
_SOMATIC = re.compile(r"(?i)(mutect2|strelka.*somatic|varscan\s+somatic|-tumor\b|--tumou?r\b)")


def detect_reference_build(command: str) -> str:
    if _GRCH38.search(command or ""):
        return "GRCh38"
    if _GRCH37.search(command or ""):
        return "GRCh37"
    return "unknown"


def has_pinned_execution(command: str) -> bool:
    """Pinned if run via a pinned-version nf-core pipeline under a container profile, or every tool is
    a digest-pinned image. A `:latest` tag or bare host tools are not pinned."""
    c = command or ""
    if _LATEST.search(c):
        return False
    if _PINNED_NF.search(c):
        return True
    if _DIGEST.search(c):
        return True
    return False


def germline_caller_status(command: str) -> str:
    """'ok' if a germline short-variant caller is present; 'somatic_only' if only a somatic caller;
    'none' if no recognised caller."""
    c = command or ""
    germ = bool(_GERMLINE.search(c))
    som = bool(_SOMATIC.search(c))
    if germ:
        return "ok"
    if som:
        return "somatic_only"
    return "none"


def _result_affecting_drift(run_params, base_params) -> bool:
    if not run_params or not base_params:
        return False
    keys = ("aligner", "caller", "ploidy")
    return any(run_params.get(k) != base_params.get(k) for k in keys if k in base_params)


def classify_calling_run(run: dict, baseline: dict) -> dict:
    """Return {labels: sorted[str], scorecard: {...}} for one run record."""
    cmd = run.get("command", "")
    labels = set()

    if detect_reference_build(cmd) != "GRCh38":
        labels.add("reference_build_error")
    pinned = has_pinned_execution(cmd)
    if not pinned:
        labels.add("container_version_error")
    provenance = bool(run.get("provenance_present"))
    if not provenance:
        labels.add("missing_provenance")
    complete = bool(run.get("vcf_present")) and bool(run.get("exit_ok"))
    if not complete:
        labels.add("incomplete_workflow")
    if run.get("reproducible") is False:
        labels.add("non_reproducible")
    f1 = run.get("f1")
    margin = baseline.get("margin", 0.02)
    if f1 is not None and f1 < baseline.get("f1", 0.99) - margin:
        labels.add("accuracy_degradation")
    if germline_caller_status(cmd) in ("somatic_only", "none"):
        labels.add("tool_selection_error")
    if _result_affecting_drift(run.get("params"), baseline.get("params")):
        labels.add("parameter_drift")

    accuracy_ok = f1 is not None and f1 >= baseline.get("f1", 0.99) - margin
    scorecard = {
        "accuracy": f1,
        "accuracy_ok": accuracy_ok,
        "reproducible_ok": run.get("reproducible") is True,
        "provenance_ok": provenance,
        "pinning_ok": pinned,
        "taxonomy_clean": len(labels) == 0,
    }
    scorecard["trustworthy"] = all([
        scorecard["accuracy_ok"], scorecard["reproducible_ok"], scorecard["provenance_ok"],
        scorecard["pinning_ok"], scorecard["taxonomy_clean"]])
    return {"arm": run.get("arm"), "labels": sorted(labels), "scorecard": scorecard}


def assemble_run_record(*, arm, sample, rep, emitted, auditable, provenance_present,
                        exec_result, vcf_present, repro_result, score, params=None) -> dict:
    """Compose the per-run record the classifier consumes, from the raw execution artefacts. `command`
    is the agent's emitted text (so the command-level detectors run on what the agent actually wrote);
    `auditable` is the strict no-shell vet() verdict carried as a scored dimension (sign-off amendment
    2026-06-20). Execution fields come from the permissive runner + scorer + repro instrument."""
    exec_result = exec_result or {}
    exit_ok = bool(exec_result.get("executed")) and bool(exec_result.get("exit_ok"))
    f1 = (score or {}).get("f1") if score else None
    reproducible = repro_result.get("identical") if repro_result else None
    return {"arm": arm, "sample": sample, "rep": rep, "command": emitted,
            "auditable": bool(auditable), "provenance_present": bool(provenance_present),
            "vcf_present": bool(vcf_present), "exit_ok": exit_ok,
            "reproducible": reproducible, "f1": f1, "params": params,
            "exec_blocked": exec_result.get("reason"), "exec_blocks": exec_result.get("blocks", [])}


def scorecard_with_audit(run: dict, baseline: dict) -> dict:
    """classify_calling_run + the `auditable` dimension folded into the scorecard and the trustworthy
    gate (a run is trustworthy only if it is ALSO auditable)."""
    res = classify_calling_run(run, baseline)
    auditable = bool(run.get("auditable"))
    res["scorecard"]["auditable"] = auditable
    res["scorecard"]["trustworthy"] = bool(res["scorecard"]["trustworthy"] and auditable)
    return res
