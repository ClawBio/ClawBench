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
import time
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
# Google arm uses gemini-2.5-flash: gemini-2.5-pro has a hard 1,000 requests/model/day cap on this
# project (too low for the ~3,465-call arm), while Flash has quota AND is the cohort model in
# model_cutoffs.yaml (cutoff 2025-01-31, < slice boundary 2025-11-29, so blinded).
PILOT_MODELS = {
    "gpt-5.2": ("openai", "gpt-5.2"),
    "claude-sonnet-4-5": ("anthropic", "claude-sonnet-4-5-20250929"),
    "gemini-2.5-flash": ("google", "gemini-2.5-flash"),
}
# Open-weight arm: local models served by Ollama (free, offline, frozen weights). The open/frontier
# contrast is a Phase-A deliverable; these run on the SAME pilot variants for an apples-to-apples join.
OPEN_MODELS = {
    "qwen3.6-35b": ("ollama", "qwen3.6:35b-mlx"),
    "qwen2.5-72b": ("ollama", "qwen2.5:72b-instruct-q4_K_M"),
}
MODELS_REGISTRY = {**PILOT_MODELS, **OPEN_MODELS}
PILOT_CONDITIONS = ["free_prompted", "skill_reasoning", "skill_execution"]
ENV_PATH = Path.home() / "dev" / "AGENTIC-AI" / ".env"

# Per-model throttle: Gemini Tier-1 has tight RPM/TPM limits, so cap its concurrency and space its
# call-starts; the others run wide open. Local Ollama models serialise on one machine, so cap their
# concurrency low (the 72B is memory-heavy -> 1) to avoid thrash. Spacing is enforced across workers.
MODEL_THROTTLE = {
    "gemini-2.5-flash": {"concurrency": 4, "min_interval": 0.3},
    "gpt-5.2": {"concurrency": 4, "min_interval": 0.2},
    "qwen3.6-35b": {"concurrency": 1, "min_interval": 0.0},  # MLX serialises; >1 only adds overhead
    "qwen2.5-72b": {"concurrency": 1, "min_interval": 0.0},
    "_default": {"concurrency": 6, "min_interval": 0.0},
}


class _Gate:
    def __init__(self, concurrency, min_interval):
        self.sem = threading.Semaphore(concurrency)
        self.min_interval = min_interval
        self._lock = threading.Lock()
        self._next = 0.0

    def __enter__(self):
        self.sem.acquire()
        if self.min_interval:
            with self._lock:
                now = time.monotonic()
                slot = max(now, self._next)
                self._next = slot + self.min_interval
            wait = slot - time.monotonic()
            if wait > 0:
                time.sleep(wait)
        return self

    def __exit__(self, *a):
        self.sem.release()


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
    if "clinvar_codes_stripped" in rec:
        keep["clinvar_codes_stripped"] = rec["clinvar_codes_stripped"]
    if "proposed_codes" in rec:
        keep["proposed_codes"] = rec["proposed_codes"]
    if rec.get("validity_errors"):
        keep["validity_error_codes"] = [e.get("error_code") for e in rec["validity_errors"]]
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
    gates = {label: _Gate(**MODEL_THROTTLE.get(label, MODEL_THROTTLE["_default"])) for label in models}

    # interleave models (variant-major) so all providers progress together and any per-model quota
    # issue surfaces early rather than 2/3 of the way through.
    tasks = []
    for v in pilot_variants:
        for cond in conditions:
            for rep in range(reps):
                for label in models:
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
            with gates[label]:
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
    ap.add_argument("--checkpoint", type=Path, default=_ROOT / "RESULTS/pilot_v2_runs.jsonl")
    ap.add_argument("--results-dir", type=Path, default=_ROOT / "RESULTS")
    ap.add_argument("--skill-md", type=Path, default=_ROOT / "SKILLS/clinical-variant-reporter/SKILL.md")
    ap.add_argument("--reps", type=int, default=5)
    ap.add_argument("--conditions", default=None, help="comma-separated subset of conditions (default: all 3)")
    ap.add_argument("--workers", type=int, default=9)
    ap.add_argument("--models", default=None,
                    help="comma-separated label subset of MODELS_REGISTRY (default: the 3 frontier "
                         "models). E.g. --models qwen3.6-35b for the open-weight arm.")
    ap.add_argument("--smoke", type=int, default=0, help="run only the first N variants at reps=1")
    ap.add_argument("--finalize", action="store_true", help="only recompute endpoints from checkpoint")
    args = ap.parse_args()

    if args.finalize:
        finalize(args.checkpoint, args.results_dir, title="pilot")
        return

    if args.models:
        models = {label: MODELS_REGISTRY[label] for label in args.models.split(",")}
    else:
        models = PILOT_MODELS

    variants = load_pilot_variants(args.pilot, args.manifest)
    skill_md = args.skill_md.read_text()
    reps = args.reps
    conditions = args.conditions.split(",") if args.conditions else PILOT_CONDITIONS
    title = "pilot"
    if args.smoke:
        variants = variants[:args.smoke]
        reps = 1
        args.checkpoint = args.results_dir / "pilot_smoke.jsonl"
        title = "pilot-smoke"
        print(f"SMOKE: {len(variants)} variants x {len(PILOT_CONDITIONS)} conditions x 1 rep x {len(models)} models")

    run(variants, models, conditions, reps, args.checkpoint, skill_md, workers=args.workers)
    finalize(args.checkpoint, args.results_dir,
             title="pilot-smoke" if args.smoke else "pilot")


if __name__ == "__main__":
    main()
