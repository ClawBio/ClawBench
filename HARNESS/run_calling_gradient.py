"""Calling constraint-gradient runner (Exp 2, Phase 4 scaffold), execution-mocked.

Mirrors the Exp 1 gradient on the variant-calling task:
  free_prompted   the agent emits a calling command from its prior (no validated skill)
  skill_reasoning the agent configures after reading the nfcore-sarek-wrapper SKILL.md
  skill_execution the agent invokes the validated, pinned nfcore-sarek-wrapper
  reference       the best-practice pinned default execution (the gold arm)
No Nextflow runs here: every arm yields a dry-run plan. The trust signal is whether an arm is pinned
and reproducibility-capable. The model adapter and the (future) runner are injected. No import-time IO.
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(_ROOT / "HARNESS"), str(_ROOT / "SKILLS" / "nfcore-sarek-wrapper")]

import run_sarek as RS  # noqa: E402

CONDITIONS = ["free_prompted", "skill_reasoning", "skill_execution", "reference"]
_AGENT_EMITTED = {"free_prompted", "skill_reasoning"}

_BASE_PROMPT = ("You are calling germline short variants from FASTQ for GIAB sample {sid}. "
                "Produce the command(s) to go from FASTQ to a VCF restricted to the benchmark region.")


def samplesheet_csv(sample_id, r1, r2, lane="L001") -> str:
    """nf-core/sarek germline input sheet (patient,sample,lane,fastq_1,fastq_2) for one sample."""
    return f"patient,sample,lane,fastq_1,fastq_2\n{sample_id},{sample_id},{lane},{r1},{r2}\n"


def write_samplesheet(path, sample_id, r1, r2, lane="L001"):
    from pathlib import Path
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(samplesheet_csv(sample_id, r1, r2, lane))
    return str(path)


def build_tasks(samples, *, models, conditions=CONDITIONS, reps=1) -> list[dict]:
    tasks = []
    for s in samples:
        for cond in conditions:
            for m in models:
                for rep in range(reps):
                    tasks.append({"condition": cond, "sample": s["id"], "model": m, "rep": rep})
    return tasks


def _free_prompt(sample, skill_md: str = "") -> str:
    p = _BASE_PROMPT.format(sid=sample["id"])
    if skill_md:
        p += "\n\nApply the rules in this skill specification:\n" + skill_md
    return p


def plan_arm(condition, sample, *, adapter, config, arch, now, skill_md: str = "", runner=None,
             work_dir=None, dry_run=True, outdir=None) -> dict:
    """Build (and, when dry_run=False, execute) one arm. skill_execution and reference go through the
    validated pinned wrapper (pinned=True, full provenance); the agent-emitted arms capture the raw
    command (pinned=False, because an agent-authored command is not pin-validated)."""
    outdir = outdir or f"work/{sample['id']}/{condition}"
    if condition in ("skill_execution", "reference"):
        res = RS.run(config, samplesheet=sample.get("samplesheet", f"{sample['id']}.csv"),
                     outdir=outdir, arch=arch, inputs=sample.get("inputs", []), work_dir=work_dir,
                     dry_run=dry_run, runner=runner, now=now)
        return {"condition": condition, "sample": sample["id"], "pinned": True, "dry_run": True,
                "command": res["command"], "provenance": res["provenance"],
                "source": "validated_wrapper" if condition == "skill_execution" else "reference_default"}
    if condition in _AGENT_EMITTED:
        prompt = _free_prompt(sample, skill_md=skill_md if condition == "skill_reasoning" else "")
        raw = adapter(condition, prompt)
        return {"condition": condition, "sample": sample["id"], "pinned": False, "dry_run": True,
                "raw_command": raw, "source": "agent_emitted"}
    raise ValueError(f"unknown condition {condition!r}")
