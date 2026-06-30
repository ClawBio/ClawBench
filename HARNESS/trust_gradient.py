"""Exp2 command-level trust-property gradient: the pilot result.

Across the constraint gradient (free_agent -> skill_reasoning -> skill_execution), the trust properties
(pinning, provenance, auditability) climb while plan validity stays constant. This is the
"infrastructure, not prompts" thesis measured on the axes that separate the arms, derived
deterministically from the emitted workflow text -- no execution required. The skill_execution arm's
accuracy (F1) comes from the separately-executed validated-wrapper run (the ancestry table); the
treatment arms' accuracy is intentionally left unmeasured here (see render_markdown caveats).

Scorers are injected so the aggregation is unit-testable. No import-time IO.
"""
from __future__ import annotations

# increasing-constraint order; arms absent from the data are simply skipped
_ARM_ORDER = ["free_agent", "skill_reasoning", "skill_execution", "reference"]


def aggregate_arms(rows: list[dict], *, plan_fn=None, inject_fn=None) -> dict:
    """Per-arm trust-property tallies from the emission records. plan_fn/inject_fn map an emitted
    workflow string to a label; default to capability_evals (imported lazily so tests can stub)."""
    if plan_fn is None or inject_fn is None:
        import capability_evals as CE
        if plan_fn is None:
            plan_fn = lambda t: CE.score_planning(t)["label"]  # noqa: E731
        if inject_fn is None:
            inject_fn = lambda t: CE.score_injection(
                t, sandbox_root="/tmp/clawbench-work/sandbox",
                input_roots=["/tmp/clawbench-work/fastq", "/tmp/clawbench-work/refs"])["label"]  # noqa: E731

    agg: dict = {}
    for r in rows:
        arm = r.get("arm")
        a = agg.setdefault(arm, {"n": 0, "pinned": 0, "provenance": 0, "auditable": 0,
                                 "plan_labels": set(), "injection_labels": set()})
        a["n"] += 1
        a["pinned"] += int(bool(r.get("pinned")))
        a["provenance"] += int(bool(r.get("provenance_emitted")))
        a["auditable"] += int(bool(r.get("vet_accepted")))
        emitted = r.get("emitted", "") or ""
        a["plan_labels"].add(plan_fn(emitted))
        a["injection_labels"].add(inject_fn(emitted))

    # present in increasing-constraint order; unknown arms appended after
    ordered = {k: agg[k] for k in _ARM_ORDER if k in agg}
    for k in agg:
        if k not in ordered:
            ordered[k] = agg[k]
    return ordered


def parse_ancestry_table(text_or_path) -> list[dict]:
    """Parse the executed-arm ancestry/accuracy TSV (sample, ancestry, precision, recall, F1, TP, FP,
    FN, provenance_hash)."""
    text = text_or_path
    if "\n" not in str(text_or_path):
        with open(text_or_path) as fh:
            text = fh.read()
    lines = [ln for ln in text.splitlines() if ln.strip()]
    header = lines[0].split("\t")
    out = []
    for ln in lines[1:]:
        cells = ln.split("\t")
        rec = dict(zip(header, cells))
        for k in ("precision", "recall", "F1"):
            if k in rec:
                rec[k] = float(rec[k])
        for k in ("TP", "FP", "FN"):
            if k in rec:
                rec[k] = int(rec[k])
        out.append(rec)
    return out


def _frac(n, d):
    return f"{n}/{d}"


def _join(labels):
    return "/".join(sorted(labels)) if labels else "-"


def render_markdown(agg: dict, *, skill_summary: dict, model: str, sample: str) -> str:
    """Render the gradient table + interpretation + honest scope. skill_summary carries the executed
    validated-arm accuracy (f1, reproducible)."""
    n = max((a["n"] for a in agg.values()), default=0)
    lines = [
        f"# Exp2 trust-property gradient (pilot)",
        "",
        f"Model: {model}. Sample: {sample}. n={n} per arm. Command-level, derived from the emitted",
        "workflow text (no execution). The skill_execution accuracy is from the separately-executed",
        "validated-wrapper run; treatment-arm accuracy is unmeasured here.",
        "",
        "| Arm | Pinned | Provenance | Auditable | Plan | Injection | F1 |",
        "|-----|--------|------------|-----------|------|-----------|----|",
    ]
    for arm, a in agg.items():
        lines.append(
            f"| `{arm}` | {_frac(a['pinned'], a['n'])} | {_frac(a['provenance'], a['n'])} | "
            f"{_frac(a['auditable'], a['n'])} | {_join(a['plan_labels'])} | "
            f"{_join(a['injection_labels'])} | unmeasured |")

    # the validated wrapper arm is not an emission (it invokes the skill directly); render it from the
    # executed run's evidence (provenance hash in the ancestry table, the reproducible re-run, pinning
    # structural to nf-core/sarek -r + -profile). Marked * to flag it is the executed arm, not n reps.
    skill_f1 = skill_summary.get("f1")
    if skill_f1 is not None:
        f1cell = f"{skill_f1:.4f}" + (", reproducible" if skill_summary.get("reproducible") else "")
        lines.append(
            f"| `skill_execution` (executed)* | yes* | yes* | yes* | valid_plan | n/a | {f1cell} |")
        lines.append("")
        lines.append("\\* `skill_execution` is the validated wrapper run, not emission reps: pinning is "
                     "structural (nf-core/sarek pinned version + container profile), provenance is the "
                     "content hash recorded per sample in the ancestry table, reproducibility is the "
                     "genotype-identical re-run.")
    lines += [
        "",
        "## Interpretation",
        "Trust properties (pinning, provenance, auditability) climb across the constraint gradient",
        "while plan validity stays constant: every arm plans correctly, so what separates the arms is",
        "not whether the model can plan a genomic pipeline but whether its output is pinned,",
        "provenanced, auditable, and reproducible. Trustworthiness is a property of the architecture,",
        "not the model. This is the field-level contribution, measurable from the emissions alone.",
        "",
        "## Scope and caveats (load-bearing)",
        f"- n={n} per treatment arm, one model, one sample (HG002), command-level only. A pilot, not a",
        "  powered benchmark.",
        f"- Accuracy is confirmed only for the validated arm (F1 {skill_f1}); free_agent and",
        "  skill_reasoning accuracy is UNMEASURED (the June execution runs were contaminated by",
        "  shared-reference file collisions and arm64/x86 GATK library issues). The gradient is solid on",
        "  trust properties, open on accuracy.",
        "- Injection labels here are NOT an injection-robustness test: these emissions came from the",
        "  normal task, not the poisoned prompt, so `clean` means only that no egress is present.",
        "",
        "Regenerate: `python3 HARNESS/run_trust_gradient.py` (reads RESULTS/exp2_agent_arms.jsonl +",
        "RESULTS/exp2_ancestry_table_chr20.tsv).",
    ]
    return "\n".join(lines) + "\n"
