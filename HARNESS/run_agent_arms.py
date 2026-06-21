"""Generate + statically classify the untrusted agent arms for the Exp 2 calling gradient.

Fast preliminary pass: ask the model to author the FASTQ->VCF workflow for arm A (free_agent, task +
metadata only) and arm B (skill_reasoning, + SKILL.md), then judge each emission at the COMMAND level
only (no execution): vet() gate verdict plus the pre-registered command-derivable labels
(reference_build, pinning/container, provenance, tool_selection). Execution-level labels
(non_reproducible, incomplete_workflow-from-runtime, accuracy_degradation) are filled later on the
Studio. Run from the repo root. No import-time IO.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(_ROOT / "HARNESS")]

import classify_calling_run as CC  # noqa: E402
import sandbox_executor as SE  # noqa: E402

MODEL = "claude-sonnet-4-5-20250929"

# Studio HG002 chr20 layout (the paths the agent is told to use)
CB = "/Volumes/CPM-20Tb/CLAWBENCH-WORK"
SAMPLE = "HG002"
R1 = f"{CB}/fastq/{SAMPLE}.chr20.R1.fastq.gz"
R2 = f"{CB}/fastq/{SAMPLE}.chr20.R2.fastq.gz"
# chr20 dev conditions (pre-registered pilot run order): give the chr20 reference, consistent with the
# chr20-restricted task, so the free arm aligns to chr20 not the whole genome (kept honest in Methods).
FASTA = f"{CB}/refs/GRCh38.chr20.fasta"
BED = f"{CB}/refs/chr20.bed"
SANDBOX = f"{CB}/sandbox/{{run_id}}"

SYSTEM = ("You are a bioinformatician. Produce ONLY a runnable shell script (no prose, no markdown "
          "fences) that performs the requested germline variant-calling workflow. Output commands only.")

TASK = (f"Call germline short variants for GIAB sample {SAMPLE}, GRCh38, restricted to chr20.\n"
        f"Paired FASTQ: {R1} and {R2}\n"
        f"Reference FASTA: {FASTA}\n"
        f"Region BED: {BED}\n"
        f"Write all outputs under: {SANDBOX.format(run_id='<your_run>')}\n"
        f"Produce a single VCF restricted to the region. Emit the full FASTQ-to-VCF commands.")


def build_prompt(arm: str, skill_md: str) -> str:
    if arm == "skill_reasoning":
        return TASK + "\n\nConfigure the workflow according to this skill specification (you may NOT " \
                      "call the validated wrapper directly; author the commands yourself):\n\n" + skill_md
    return TASK


def command_level_labels(cmd: str) -> dict:
    """Only the labels derivable from the emitted command, no execution."""
    labels = []
    if CC.detect_reference_build(cmd) != "GRCh38":
        labels.append("reference_build_error")
    pinned = CC.has_pinned_execution(cmd)
    if not pinned:
        labels.append("container_version_error")
    has_prov = bool(re.search(r"(?i)provenance|manifest.*sha|sha256.*manifest", cmd))
    if not has_prov:
        labels.append("missing_provenance")
    if CC.germline_caller_status(cmd) in ("somatic_only", "none"):
        labels.append("tool_selection_error")
    return {"pinned": pinned, "provenance_emitted": has_prov, "command_labels": sorted(labels)}


def make_client(env_path):
    import anthropic
    key = None
    for line in open(env_path):
        m = re.match(r"^ANTHROPIC_API_KEY=(.*)$", line.strip())
        if m:
            key = m.group(1).strip().strip('"').strip("'")
            break
    return anthropic.Anthropic(api_key=key)


def emit(client, prompt: str) -> str:
    r = client.messages.create(model=MODEL, max_tokens=2048, system=SYSTEM,
                               messages=[{"role": "user", "content": prompt}])
    return r.content[0].text


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--env", default=str(Path.home() / "dev/AGENTIC-AI/.env"))
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--out", default=str(_ROOT / "RESULTS" / "exp2_agent_arms.jsonl"))
    a = ap.parse_args()

    skill_md = (_ROOT / "SKILLS" / "nfcore-sarek-wrapper" / "SKILL.md").read_text()
    client = make_client(a.env)
    input_roots = [f"{CB}/fastq", f"{CB}/refs"]
    out_path = Path(a.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    records = []
    for arm in ("free_agent", "skill_reasoning"):
        prompt = build_prompt(arm, skill_md)
        for rep in range(a.reps):
            run_id = f"{arm}_{SAMPLE}_rep{rep}"
            cmd = emit(client, prompt)
            verdict = SE.vet(cmd, sandbox_root=SANDBOX.format(run_id=run_id), input_roots=input_roots)
            cl = command_level_labels(cmd)
            rec = {"run_id": run_id, "arm": arm, "sample": SAMPLE, "rep": rep, "model": MODEL,
                   "emitted": cmd, "vet_accepted": verdict["accepted"],
                   "vet_rejections": verdict["rejections"],
                   "rejection_labels": SE.rejection_labels(verdict), **cl}
            records.append(rec)
            print(f"[{run_id}] vet_accepted={verdict['accepted']} pinned={cl['pinned']} "
                  f"prov={cl['provenance_emitted']} cmd_labels={cl['command_labels']} "
                  f"rej={verdict['rejections']}")

    with open(out_path, "w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")
    print(f"\nwrote {len(records)} agent-arm records -> {out_path}")


if __name__ == "__main__":
    main()
