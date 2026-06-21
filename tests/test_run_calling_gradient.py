"""TDD for the calling constraint-gradient runner (Exp 2, Phase 4 scaffold), execution-mocked.

Mirrors the Exp 1 gradient: free_prompted (agent emits a calling command from its prior),
skill_reasoning (agent configures after reading SKILL.md), skill_execution (agent invokes the validated
pinned nfcore-sarek-wrapper), and a best-practice reference. No Nextflow runs: every arm yields a
dry-run plan. The trust signal is whether an arm is pinned and reproducibility-capable.
"""
from __future__ import annotations

import run_calling_gradient as G


def _pinned():
    return {
        "sarek_version": "3.8.1", "nxf_ver": "25.10.2", "fasta": "/cb/reference/GRCh38.fasta",
        "reference_sha256": "a" * 64, "tools": "haplotypecaller", "step": "mapping",
        "intervals_bed": "/cb/truth/HG002.chr20.bed", "skip_tools": "baserecalibrator",
        "extra_config": "/cb/arm64.config", "wes": False,
    }


def _samples():
    return [{"id": "HG002", "ancestry": "AJ", "samplesheet": "HG002.csv",
             "inputs": [{"path": "HG002_R1.fq.gz", "sha256": "c" * 64}]}]


def test_samplesheet_csv_germline_shape():
    csv = G.samplesheet_csv("HG002", "/fq/HG002.R1.fastq.gz", "/fq/HG002.R2.fastq.gz")
    lines = csv.strip().splitlines()
    assert lines[0] == "patient,sample,lane,fastq_1,fastq_2"
    assert lines[1].startswith("HG002,HG002,L001,/fq/HG002.R1.fastq.gz,/fq/HG002.R2.fastq.gz")


def test_build_tasks_covers_conditions_models_reps():
    tasks = G.build_tasks(_samples(), models=["m1"], conditions=G.CONDITIONS, reps=2)
    # 1 sample x 4 conditions x 1 model x 2 reps
    assert len(tasks) == len(G.CONDITIONS) * 2
    assert {t["condition"] for t in tasks} == set(G.CONDITIONS)


def test_skill_execution_arm_is_pinned_with_full_provenance():
    plan = G.plan_arm("skill_execution", _samples()[0], adapter=lambda cond, prompt: "ignored",
                      config=_pinned(), arch="arm64_local", now="2026-06-18T00:00:00Z")
    assert plan["pinned"] is True
    assert plan["command"][:3] == ["nextflow", "run", "nf-core/sarek"]
    assert plan["provenance"]["content_hash"]
    assert plan["dry_run"] is True


def test_reference_arm_is_pinned():
    plan = G.plan_arm("reference", _samples()[0], adapter=lambda cond, prompt: "ignored",
                      config=_pinned(), arch="linux_x86", now="t")
    assert plan["pinned"] is True


def test_free_prompted_arm_uses_agent_and_is_unpinned():
    seen = {}
    def adapter(cond, prompt):
        seen["cond"] = cond
        return "bwa mem ref.fa r1.fq | bcftools call -mv > out.vcf"   # agent's raw plan
    plan = G.plan_arm("free_prompted", _samples()[0], adapter=adapter, config=_pinned(),
                      arch="arm64_local", now="t")
    assert seen["cond"] == "free_prompted"
    assert plan["pinned"] is False
    assert "raw_command" in plan and "bwa" in plan["raw_command"]
    assert "nextflow" not in plan.get("raw_command", "")


def test_skill_reasoning_reads_skill_md_and_is_agent_emitted():
    captured = {}
    def adapter(cond, prompt):
        captured["prompt"] = prompt
        return "nextflow run nf-core/sarek -r 3.8.1 ..."  # agent-emitted, not the validated wrapper
    plan = G.plan_arm("skill_reasoning", _samples()[0], adapter=adapter, config=_pinned(),
                      arch="arm64_local", now="t", skill_md="PINNING CONTRACT ...")
    assert "PINNING CONTRACT" in captured["prompt"]
    assert plan["pinned"] is False   # agent-emitted command is not the validated, pin-checked run


def test_no_arm_executes_in_scaffold():
    ran = []
    for cond in G.CONDITIONS:
        G.plan_arm(cond, _samples()[0], adapter=lambda c, p: "x", config=_pinned(),
                   arch="arm64_local", now="t", runner=lambda cmd: ran.append(cmd))
    assert ran == []
