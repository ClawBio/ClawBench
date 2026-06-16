"""Run the ClawBench Exp 1 Tier-A pilot: 3 models x 3 conditions x N reps over the pilot variants.

Resumable (JSONL checkpoint keyed by model|variant|condition|rep), bounded concurrency, and
rate-limit failures recorded as category 'ratelimit' (never miscounted as format failures).
Conditions: free_prompted, skill_reasoning, skill_execution (no RAG, no answer-supplied control yet).

Run a live smoke first:  python3 HARNESS/run_pilot.py --smoke 2
Then the full pilot:      python3 HARNESS/run_pilot.py --reps 5
Finalize endpoints only:  python3 HARNESS/run_pilot.py --finalize
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(_ROOT / "HARNESS"), str(_ROOT / "SKILLS" / "clinical-variant-reporter")]

import gradient_runner as G  # noqa: E402
import model_adapters as MA  # noqa: E402
import pilot_endpoints as PE  # noqa: E402

# Each pilot model's cutoff is <= the slice boundary 2025-11-29 (so the slice is blinded to it).
# claude-sonnet-4-5-20250929: the original claude-sonnet-4 is retired from the API; Sonnet 4.5 was
# RELEASED 2025-09-29 (< boundary), and release date is a hard upper bound on training cutoff.
PILOT_MODELS = {
    "gpt-5.2": ("openai", "gpt-5.2"),
    "claude-sonnet-4-5": ("anthropic", "claude-sonnet-4-5-20250929"),
    "gemini-2.5-pro": ("google", "gemini-2.5-pro"),
}
PILOT_CONDITIONS = ["free_prompted", "skill_reasoning", "skill_execution"]
ENV_PATH = Path.home() / "dev" / "AGENTIC-AI" / ".env"


def load_pilot_variants(pilot_file: Path, manifest_file: Path):
    pilot = json.loads(pilot_file.read_text())
    manifest = json.loads(manifest_file.read_text())
    by_id = {v["variant_id"]: v for v in manifest["variants"]}
    out = []
    for pv in pilot["variants"]:
        m = by_id[pv["variant_id"]]
        out.append({"variant_id": pv["variant_id"], "genomic_context": m["genomic_context"],
                    "evidence_context": {"molecular_consequence": pv.get("consequence"),
                                         "population_max_af": pv.get("max_af")},
                    "truth": {"clnsig": m["truth"]["clnsig"], "review_stars": m["truth"]["review_stars"]},
                    "tier": pv["tier"]})
    return out


def _key(r):
    return f'{r["model"]}|{r["variant_id"]}|{r["condition"]}|{r["rep"]}'


def _slim(rec: dict) -> dict:
    keep = {k: rec.get(k) for k in ("model", "condition", "variant_id", "rep", "scoreable",
                                    "format_ok", "predicted_class", "truth_class", "category")}
    keep["label"] = rec.get("label", {})
    keep["criteria"] = rec.get("criteria", {})
    if not rec.get("format_ok"):
        keep["raw"] = (rec.get("raw") or "")[:200]
    return keep


def run(pilot_variants, models, conditions, reps, checkpoint: Path, skill_md, workers=9, log_every=50):
    done = set()
    if checkpoint.exists():
        for line in checkpoint.read_text().splitlines():
            if line.strip():
                try:
                    done.add(_key(json.loads(line)))
                except ValueError:
                    pass
    adapters = MA.make_adapters(ENV_PATH, models)

    tasks = []
    for label in models:
        for v in pilot_variants:
            for cond in conditions:
                for rep in range(reps):
                    k = f'{label}|{v["variant_id"]}|{cond}|{rep}'
                    if k not in done:
                        tasks.append((label, v, cond, rep))
    print(f"{len(tasks)} calls to make ({len(done)} already done)")

    lock = threading.Lock()
    counter = {"n": 0}
    fh = open(checkpoint, "a")

    def work(task):
        label, v, cond, rep = task
        adapter = adapters[label]
        try:
            rec = G.run_one(cond, v, adapter, model=label, mode="clinvar_blinded",
                            truth_source="clinvar", skill_md=skill_md)
        except MA.RateLimitExhausted as e:
            rec = {"variant_id": v["variant_id"], "model": label, "condition": cond,
                   "scoreable": False, "format_ok": False, "predicted_class": None,
                   "truth_class": v["truth"]["clnsig"], "category": "ratelimit",
                   "label": {}, "criteria": {}, "raw": str(e)[:200]}
        except Exception as e:  # any other API/infra error: record, never crash the run
            rec = {"variant_id": v["variant_id"], "model": label, "condition": cond,
                   "scoreable": False, "format_ok": False, "predicted_class": None,
                   "truth_class": v["truth"]["clnsig"], "category": "error",
                   "label": {}, "criteria": {}, "raw": f"{type(e).__name__}: {e}"[:200]}
        rec["rep"] = rep
        with lock:
            fh.write(json.dumps(_slim(rec)) + "\n")
            fh.flush()
            counter["n"] += 1
            if counter["n"] % log_every == 0:
                print(f"  ...{counter['n']}/{len(tasks)} done")

    with ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(work, tasks))
    fh.close()
    print(f"run complete: {counter['n']} new calls")


def finalize(checkpoint: Path, results_dir: Path, title: str):
    records = [json.loads(l) for l in checkpoint.read_text().splitlines() if l.strip()]
    cells = PE.endpoints_by_cell(records)
    out = {f"{m}|{c}": v for (m, c), v in cells.items()}
    results_dir.mkdir(parents=True, exist_ok=True)
    (results_dir / "exp1_pilot_endpoints.json").write_text(json.dumps(out, indent=2))
    (results_dir / "exp1_pilot_endpoints.md").write_text(PE.render_markdown(cells, title=title))
    print(PE.render_markdown(cells, title=title))
    return cells


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pilot", type=Path, default=_ROOT / "TRUTH/clinvar/pilot_tier_a_v1.json")
    ap.add_argument("--manifest", type=Path, default=_ROOT / "TRUTH/clinvar/heldout_manifest.json")
    ap.add_argument("--checkpoint", type=Path, default=_ROOT / "RESULTS/pilot_runs.jsonl")
    ap.add_argument("--results-dir", type=Path, default=_ROOT / "RESULTS")
    ap.add_argument("--skill-md", type=Path, default=_ROOT / "SKILLS/clinical-variant-reporter/SKILL.md")
    ap.add_argument("--reps", type=int, default=5)
    ap.add_argument("--workers", type=int, default=9)
    ap.add_argument("--smoke", type=int, default=0, help="run only the first N variants at reps=1")
    ap.add_argument("--finalize", action="store_true", help="only recompute endpoints from checkpoint")
    args = ap.parse_args()

    if args.finalize:
        finalize(args.checkpoint, args.results_dir, title="pilot")
        return

    variants = load_pilot_variants(args.pilot, args.manifest)
    skill_md = args.skill_md.read_text()
    reps = args.reps
    title = "pilot"
    if args.smoke:
        variants = variants[:args.smoke]
        reps = 1
        args.checkpoint = args.results_dir / "pilot_smoke.jsonl"
        title = "pilot-smoke"
        print(f"SMOKE: {len(variants)} variants x {len(PILOT_CONDITIONS)} conditions x 1 rep x {len(PILOT_MODELS)} models")

    run(variants, PILOT_MODELS, PILOT_CONDITIONS, reps, args.checkpoint, skill_md, workers=args.workers)
    finalize(args.checkpoint, args.results_dir,
             title="pilot-smoke" if args.smoke else "pilot")


if __name__ == "__main__":
    main()
