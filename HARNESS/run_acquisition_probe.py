"""Run the acquisition arm: skill_execution x 2 arms x N reps for one model over the probe set.

Paired design. Each frozen probe variant is classified twice:
  * arm "thin"     (Condition A): evidence_context = consequence + AF only (re-run, so the prompt is
                    today's template, not the older pilot run) — the baseline.
  * arm "enriched" (Condition B): evidence_context = the oracle's real non-ClinVar annotations.
The ONLY difference between arms is the evidence payload, so any change in the per-variant layer
attribution is attributable to acquisition. Resumable (JSONL checkpoint keyed model|variant|arm|rep).

Smoke first:  python3 HARNESS/run_acquisition_probe.py --smoke 2
Full run:     python3 HARNESS/run_acquisition_probe.py --reps 5
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

MODEL = "claude-sonnet-4-5"
MODEL_SPEC = {"claude-sonnet-4-5": ("anthropic", "claude-sonnet-4-5-20250929")}
ENV_PATH = Path.home() / "dev" / "AGENTIC-AI" / ".env"


# Strength-calibration arm: the benchmark's deterministic combiner scores by ACMG 2015 strength
# baselines (PM2 = moderate). Models often apply the ClinGen SVI 2020 downgrade (PM2 = supporting),
# which is defensible but one point short of the combiner's convention. This note aligns the model's
# PM2 strength with the combiner; it does NOT dictate direction or whether PM2 applies.
PM2_NOTE = ("PM2 strength (this benchmark scores by ACMG 2015 baselines): absence from or rarity in "
            "population databases applies PM2 at its MODERATE baseline (2 points). Do not apply the "
            "ClinGen SVI 2020 downgrade to supporting in this benchmark; use moderate when PM2 applies "
            "unless there is a specific reason to downgrade.")


def task_key(model: str, variant_id: str, arm: str, rep: int) -> str:
    return f"{model}|{variant_id}|{arm}|{rep}"


def calibrated_evidence_context(enriched_variant: dict) -> dict:
    """A copy of an enriched variant with the PM2 strength-calibration note added (the calibrated arm).
    The enriched in-silico evidence is preserved; the input is not mutated."""
    out = dict(enriched_variant)
    ec = dict(enriched_variant.get("evidence_context", {}))
    ec["pm2_strength_note"] = PM2_NOTE
    out["evidence_context"] = ec
    return out


def build_tasks(thin_variants, enriched_variants, calibrated_variants=None, *, reps, done: set, model: str):
    """Deterministic (arm, variant, rep) task list across arms, skipping checkpointed keys. Raises if
    the enriched arm does not cover the thin variant set (a probe/cache integrity failure)."""
    thin_ids = [v["variant_id"] for v in thin_variants]
    enr_by_id = {v["variant_id"]: v for v in enriched_variants}
    missing = [vid for vid in thin_ids if vid not in enr_by_id]
    if missing:
        raise ValueError(f"enriched cache missing variants present in probe: {missing}")
    arms = [("thin", thin_variants), ("enriched", [enr_by_id[vid] for vid in thin_ids])]
    if calibrated_variants is not None:
        cal_by_id = {v["variant_id"]: v for v in calibrated_variants}
        arms.append(("calibrated", [cal_by_id[vid] for vid in thin_ids]))
    tasks = []
    for arm, variants in arms:
        for v in variants:
            for rep in range(reps):
                if task_key(model, v["variant_id"], arm, rep) not in done:
                    tasks.append((arm, v, rep))
    return tasks


def _slim(rec: dict, arm: str) -> dict:
    keep = {k: rec.get(k) for k in ("model", "condition", "variant_id", "rep", "scoreable",
                                    "format_ok", "predicted_class", "truth_class", "category")}
    keep["arm"] = arm
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


def run(thin_variants, enriched_variants, *, reps, checkpoint: Path, skill_md, workers=6,
        calibrated_variants=None):
    done = set()
    if checkpoint.exists():
        for line in checkpoint.read_text().splitlines():
            if line.strip():
                try:
                    r = json.loads(line)
                    done.add(task_key(r["model"], r["variant_id"], r["arm"], r["rep"]))
                except (ValueError, KeyError):
                    pass
    tasks = build_tasks(thin_variants, enriched_variants, calibrated_variants,
                        reps=reps, done=done, model=MODEL)
    print(f"{len(tasks)} calls to make ({len(done)} already done)")
    adapter = MA.make_adapters(ENV_PATH, MODEL_SPEC)[MODEL]

    lock = threading.Lock()
    counter = {"n": 0}
    fh = open(checkpoint, "a")

    def work(task):
        arm, v, rep = task
        try:
            rec = G.run_one("skill_execution", v, adapter, model=MODEL, mode="clinvar_blinded",
                            truth_source="clinvar", skill_md=skill_md)
        except MA.RateLimitExhausted as e:
            rec = {"variant_id": v["variant_id"], "model": MODEL, "condition": "skill_execution",
                   "scoreable": False, "format_ok": False, "predicted_class": None,
                   "truth_class": v["truth"]["clnsig"], "category": "ratelimit", "raw": str(e)[:200]}
        except Exception as e:  # noqa: BLE001 -- record, never crash the run
            rec = {"variant_id": v["variant_id"], "model": MODEL, "condition": "skill_execution",
                   "scoreable": False, "format_ok": False, "predicted_class": None,
                   "truth_class": v["truth"]["clnsig"], "category": "error",
                   "raw": f"{type(e).__name__}: {e}"[:200]}
        rec["rep"] = rep
        with lock:
            fh.write(json.dumps(_slim(rec, arm)) + "\n")
            fh.flush()
            counter["n"] += 1
            if counter["n"] % 20 == 0:
                print(f"  ...{counter['n']}/{len(tasks)} done")

    with ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(work, tasks))
    fh.close()
    print(f"run complete: {counter['n']} new calls")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", type=Path, default=_ROOT / "TRUTH/clinvar/acquisition_probe_v1.json")
    ap.add_argument("--cache", type=Path, default=_ROOT / "TRUTH/clinvar/acquisition_cache_v1.json")
    ap.add_argument("--checkpoint", type=Path, default=_ROOT / "RESULTS/acquisition_probe_runs.jsonl")
    ap.add_argument("--skill-md", type=Path, default=_ROOT / "SKILLS/clinical-variant-reporter/SKILL.md")
    ap.add_argument("--reps", type=int, default=5)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--smoke", type=int, default=0, help="run only the first N variants at reps=1")
    ap.add_argument("--calibrate", action="store_true",
                    help="also run the PM2-moderate strength-calibration arm")
    args = ap.parse_args()

    probe = json.loads(args.probe.read_text())
    cache = json.loads(args.cache.read_text())
    if cache.get("probe_content_hash") != probe.get("content_hash"):
        raise SystemExit("cache/probe content_hash mismatch: regenerate the acquisition cache")
    thin = probe["variants"]
    # enriched cache entries already carry evidence_context/genomic_context/truth in runner shape
    enriched = cache["variants"]
    calibrated = [calibrated_evidence_context(v) for v in enriched] if args.calibrate else None
    skill_md = args.skill_md.read_text()
    reps = args.reps
    checkpoint = args.checkpoint
    if args.smoke:
        thin = thin[:args.smoke]
        ids = {v["variant_id"] for v in thin}
        enriched = [v for v in enriched if v["variant_id"] in ids]
        if calibrated is not None:
            calibrated = [v for v in calibrated if v["variant_id"] in ids]
        reps = 1
        checkpoint = _ROOT / "RESULTS/acquisition_smoke.jsonl"
        print(f"SMOKE: {len(thin)} variants x {'3' if calibrated else '2'} arms x 1 rep")

    run(thin, enriched, reps=reps, checkpoint=checkpoint, skill_md=skill_md, workers=args.workers,
        calibrated_variants=calibrated)


if __name__ == "__main__":
    main()
