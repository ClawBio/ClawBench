"""Exp 2 calling-gradient driver (runs ON the Mac Studio).

For each saved agent emission (RESULTS/exp2_agent_arms.jsonl): vet() it (auditable dimension), execute
it TWICE in fresh per-run sandboxes via the permissive confined runner (sign-off amendment 2026-06-20),
locate the produced VCF, score it with rtg vcfeval against the GIAB chr20 truth, check genotype
reproducibility across the two runs, then assemble + classify into the five-plus-audit scorecard.

free_agent runs native (bwa/gatk, no Docker). skill_reasoning needs Docker (gated). Use --arm to pick.
--plan prints the per-run plan without executing. Run from the repo root on the Studio.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(_ROOT / "HARNESS")]

import classify_calling_run as CC  # noqa: E402
import repro_enforcer as RE  # noqa: E402
import sandbox_executor as SE  # noqa: E402
import vcfeval_scorer as VS  # noqa: E402

CB = os.environ.get("CB", "/Volumes/CPM-20Tb/CLAWBENCH-WORK")
SAMPLE = "HG002"
# chr20 dev conditions (pre-registered run order: HG002 chr20 first, expand only if arms separate)
REF = f"{CB}/refs/GRCh38.chr20.fasta"
R1 = f"{CB}/fastq/{SAMPLE}.chr20.R1.fastq.gz"
R2 = f"{CB}/fastq/{SAMPLE}.chr20.R2.fastq.gz"
BED = f"{CB}/truth/{SAMPLE}.chr20.bed"  # per-sample GIAB confident region
SDF = f"{CB}/refs/GRCh38.sdf"
TRUTH = f"{CB}/truth/{SAMPLE}.chr20.vcf.gz"  # frozen chr20 GIAB truth
BIN = f"{CB}/conda/envs/giab/bin"
BASELINE = {"f1": 0.99, "margin": 0.02,
            "params": {"aligner": "bwa-mem2", "caller": "haplotypecaller", "ploidy": 2}}
INPUT_ROOTS = [f"{CB}/fastq", f"{CB}/refs", f"{CB}/truth"]


RESOLVE = False  # set by --resolve: drop NXF_OFFLINE so the agent's pinned pipeline/containers resolve


def inject_env(outdir: str) -> dict:
    """The calling vars both arms reference; injected so a run fails on its OWN merits, not on an
    undefined-path error. Names cover the common variants models emit."""
    env = {"SAMPLE": SAMPLE, "THREADS": "8", "OUTDIR": outdir, "OUTPUT_DIR": outdir, "WORKDIR": outdir,
           "REF": REF, "REFERENCE": REF, "FASTA": REF, "REF_FASTA": REF,
           "R1": R1, "R2": R2, "FASTQ_R1": R1, "FASTQ_R2": R2, "READ1": R1, "READ2": R2,
           # point nextflow at the shared cache holding pre-pulled pinned nf-core/sarek.
           "NXF_HOME": f"{CB}/.nextflow"}
    # Finding 1 (airgap): NXF_OFFLINE stays true (scrubbed_env) -> only validated cached versions run.
    # Finding 2 (--resolve): allow nextflow to resolve the agent's pinned pipeline+containers (network
    # for provisioning only; the agent's own script still cannot curl/ssh via the prescan).
    if RESOLVE:
        env["NXF_OFFLINE"] = "false"
    return env


def _bash_runner(timeout):
    def _run(script_path, *, cwd, env, timeout=timeout):
        try:
            p = subprocess.run(["/bin/bash", script_path], cwd=cwd, env=env, timeout=timeout,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            Path(cwd, "run.log").write_bytes(p.stdout or b"")
            return {"exit_ok": p.returncode == 0, "returncode": p.returncode, "timed_out": False}
        except subprocess.TimeoutExpired as e:
            Path(cwd, "run.log").write_bytes((e.stdout or b"") + b"\n[TIMEOUT]\n")  # keep partial log
            return {"exit_ok": False, "returncode": None, "timed_out": True}
    return _run


def _find_vcf(sandbox: str):
    hits = sorted(glob.glob(f"{sandbox}/**/*.vcf.gz", recursive=True) +
                  glob.glob(f"{sandbox}/**/*.vcf", recursive=True))
    # prefer a final/filtered call set over intermediates
    hits.sort(key=lambda p: (("recal" in p) + ("filter" in p) + ("haplotype" in p)), reverse=True)
    return hits[0] if hits else None


def _read_vcf_text(path):
    if path.endswith(".gz"):
        return subprocess.run([f"{BIN}/bcftools", "view", path], stdout=subprocess.PIPE).stdout.decode()
    return Path(path).read_text()


def _score(vcf, sandbox):
    out_dir = f"{sandbox}/vcfeval"
    shutil.rmtree(out_dir, ignore_errors=True)
    cmd = VS.vcfeval_command(truth=TRUTH, query=vcf, bed=BED, sdf=SDF, out_dir=out_dir, threads=8,
                             rtg=f"{BIN}/rtg")
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    summ = Path(out_dir, "summary.txt")
    return VS.parse_vcfeval_summary(summ.read_text()) if summ.exists() else None


def execute_one(emitted, run_id, timeout):
    """Run the agent's bash once in a fresh sandbox; return (exec_result, vcf_path)."""
    sandbox = f"{CB}/sandbox/{run_id}"
    shutil.rmtree(sandbox, ignore_errors=True)
    Path(sandbox, "tmp").mkdir(parents=True, exist_ok=True)
    Path(sandbox, "run.sh").write_text(emitted.replace("```bash", "").replace("```", ""))
    exec_result = SE.run_script(emitted.replace("```bash", "").replace("```", ""),
                                sandbox_root=sandbox, input_roots=INPUT_ROOTS,
                                env_vars=inject_env(sandbox), base_env=dict(os.environ),
                                bin_dirs=[BIN, "/usr/local/bin", "/usr/bin", "/bin"], timeout=timeout,
                                runner=_bash_runner(timeout))
    return exec_result, (_find_vcf(sandbox) if exec_result.get("executed") else None), sandbox


def process_record(rec, timeout):
    emitted = rec["emitted"]
    vet = SE.vet(emitted, sandbox_root=f"{CB}/sandbox/{rec['run_id']}_a", input_roots=INPUT_ROOTS)
    ea, vcf_a, sbox_a = execute_one(emitted, f"{rec['run_id']}_a", timeout)
    eb, vcf_b, _ = execute_one(emitted, f"{rec['run_id']}_b", timeout)
    score = _score(vcf_a, sbox_a) if vcf_a else None
    repro = None
    if vcf_a and vcf_b:
        repro = RE.genotype_identical(_read_vcf_text(vcf_a), _read_vcf_text(vcf_b))
    prov_present = bool(glob.glob(f"{CB}/sandbox/{rec['run_id']}_a/**/provenance*.json", recursive=True))
    run = CC.assemble_run_record(arm=rec["arm"], sample=SAMPLE, rep=rec["rep"], emitted=emitted,
                                 auditable=vet["accepted"], provenance_present=prov_present,
                                 exec_result=ea, vcf_present=bool(vcf_a), repro_result=repro, score=score)
    return CC.scorecard_with_audit(run, BASELINE) | {"run_id": rec["run_id"], "f1": run["f1"],
                                                     "exec_a": ea, "vcf_a": vcf_a}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--emissions", default=str(_ROOT / "RESULTS" / "exp2_agent_arms.jsonl"))
    ap.add_argument("--arm", choices=["free_agent", "skill_reasoning", "all"], default="free_agent")
    ap.add_argument("--out", default=str(_ROOT / "RESULTS" / "exp2_gradient_scorecard.jsonl"))
    ap.add_argument("--timeout", type=int, default=3 * 3600)
    ap.add_argument("--resolve", action="store_true",
                    help="Finding 2: drop NXF_OFFLINE so the agent's pinned pipeline/containers resolve")
    ap.add_argument("--plan", action="store_true")
    a = ap.parse_args()
    global RESOLVE
    RESOLVE = a.resolve
    if RESOLVE:
        print("MODE: resolve (NXF_OFFLINE off; agent pinned pipeline/containers may be fetched)")

    recs = [json.loads(l) for l in open(a.emissions)]
    if a.arm != "all":
        recs = [r for r in recs if r["arm"] == a.arm]
    print(f"{len(recs)} runs; arm={a.arm}; REF={REF}; TRUTH={TRUTH}")
    if a.plan:
        for r in recs:
            print(f"  PLAN {r['run_id']}: vet+exec x2 -> vcfeval -> repro -> classify")
        return
    results = []
    for r in recs:
        print(f"[run] {r['run_id']} ...", flush=True)
        res = process_record(r, a.timeout)
        sc = res["scorecard"]
        print(f"  -> auditable={sc['auditable']} pinned={sc['pinning_ok']} prov={sc['provenance_ok']} "
              f"f1={res['f1']} repro={sc['reproducible_ok']} trustworthy={sc['trustworthy']} "
              f"labels={res['labels']}", flush=True)
        results.append(res)
    with open(a.out, "a") as f:
        for r in results:
            f.write(json.dumps({k: v for k, v in r.items() if k != "exec_a"}) + "\n")
    print(f"wrote {len(results)} scorecards -> {a.out}")


if __name__ == "__main__":
    main()
