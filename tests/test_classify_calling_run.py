"""TDD for the calling-gradient failure classifier (Exp 2 gradient).

Implements the pre-registered eight-category taxonomy and the five-dimension trustworthiness scorecard
(accuracy, reproducibility, provenance, pinning, taxonomy-cleanliness). A run record carries the
emitted command plus booleans/metrics from executing it; the classifier returns the label set and the
scorecard deterministically, so the gradient is measured, not narrated.
"""
from __future__ import annotations

import classify_calling_run as C


def _clean_skill_run():
    return {
        "arm": "skill_execution",
        "command": ("nextflow run nf-core/sarek -r 3.8.1 -profile docker -c arm64.config "
                    "--fasta GRCh38.chr20.fasta --tools haplotypecaller --step mapping"),
        "provenance_present": True, "vcf_present": True, "exit_ok": True,
        "f1": 0.9906, "reproducible": True,
        "params": {"aligner": "bwa-mem2", "caller": "haplotypecaller", "ploidy": 2},
    }


def _baseline():
    return {"f1": 0.99, "margin": 0.02, "params": {"aligner": "bwa-mem2", "caller": "haplotypecaller", "ploidy": 2}}


def test_reference_build_detection():
    assert C.detect_reference_build("--fasta GRCh38.chr20.fasta") == "GRCh38"
    assert C.detect_reference_build("bwa mem hg19.fa r.fq") == "GRCh37"
    assert C.detect_reference_build("bwa mem ref.fa r.fq") == "unknown"


def test_pinned_execution_detection():
    assert C.has_pinned_execution("nextflow run nf-core/sarek -r 3.8.1 -profile docker") is True
    assert C.has_pinned_execution("docker run tool@sha256:" + "a" * 64 + " bwa mem") is True
    assert C.has_pinned_execution("bwa mem ref.fa r.fq | bcftools call -mv") is False
    assert C.has_pinned_execution("docker run biocontainers/bwa:latest") is False


def test_germline_caller_status():
    assert C.germline_caller_status("gatk HaplotypeCaller") == "ok"
    assert C.germline_caller_status("bcftools mpileup | bcftools call -mv") == "ok"
    assert C.germline_caller_status("gatk Mutect2 -tumor x") == "somatic_only"
    assert C.germline_caller_status("bwa mem | samtools sort") == "none"


def test_clean_skill_run_has_no_labels_and_is_trustworthy():
    r = C.classify_calling_run(_clean_skill_run(), _baseline())
    assert r["labels"] == []
    sc = r["scorecard"]
    assert sc["trustworthy"] is True
    assert sc["accuracy_ok"] and sc["reproducible_ok"] and sc["provenance_ok"] and sc["pinning_ok"]
    assert sc["taxonomy_clean"] is True


def test_free_arm_accumulates_expected_labels():
    free = {
        "arm": "free",
        "command": "bwa mem hg19.fa HG002_R1.fq HG002_R2.fq | bcftools call -mv > out.vcf",
        "provenance_present": False, "vcf_present": True, "exit_ok": True,
        "f1": 0.94, "reproducible": False,
        "params": {"aligner": "bwa", "caller": "bcftools", "ploidy": 2},
    }
    labels = set(C.classify_calling_run(free, _baseline())["labels"])
    assert "reference_build_error" in labels      # hg19
    assert "container_version_error" in labels     # raw host tools, no container
    assert "missing_provenance" in labels
    assert "non_reproducible" in labels
    assert "accuracy_degradation" in labels        # 0.94 < 0.97
    assert C.classify_calling_run(free, _baseline())["scorecard"]["trustworthy"] is False


def test_incomplete_workflow_when_no_vcf():
    r = {"arm": "free", "command": "bwa mem GRCh38.fa r.fq | samtools sort",
         "provenance_present": False, "vcf_present": False, "exit_ok": False,
         "f1": None, "reproducible": None, "params": {}}
    labels = set(C.classify_calling_run(r, _baseline())["labels"])
    assert "incomplete_workflow" in labels
    assert "tool_selection_error" in labels        # no germline caller present
    assert "accuracy_degradation" not in labels    # cannot measure accuracy without a VCF


def test_parameter_drift_from_baseline_params():
    r = _clean_skill_run()
    r["arm"] = "free"; r["params"] = {"aligner": "bwa-mem2", "caller": "haplotypecaller", "ploidy": 1}
    labels = set(C.classify_calling_run(r, _baseline())["labels"])
    assert "parameter_drift" in labels             # ploidy 1 vs baseline 2


def test_tool_selection_error_somatic_caller():
    r = _clean_skill_run()
    r["arm"] = "free"; r["command"] = "gatk Mutect2 -I HG002.bam -tumor HG002 -O out.vcf"
    labels = set(C.classify_calling_run(r, _baseline())["labels"])
    assert "tool_selection_error" in labels
