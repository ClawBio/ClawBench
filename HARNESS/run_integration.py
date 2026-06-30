"""Run the Exp2<->Exp1 end-to-end integration on the validated arm's REAL VCFs (no x86, no re-calling).

For each GIAB sample with a vcfeval evaluation on disk, compute the CALLING-layer outcome (TP/FN) for
every held-out ClinVar variant that is also a GIAB-confident truth variant, then feed it through the
integrate_workflow join. The interpretation layer is left pending here (interp=None) -- it is an API
run, scoped by the overlap size this script reports. Reads only files already on disk. Run from repo
root. No import-time IO.
"""
from __future__ import annotations

import collections
import json
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(_ROOT / "HARNESS")]

import integrate_workflow as IW  # noqa: E402

CB = Path("/Volumes/CPM-20Tb/CLAWBENCH-WORK")
MANIFEST = _ROOT / "TRUTH" / "clinvar" / "heldout_manifest.json"
SAMPLES = ["HG001", "HG002", "HG003", "HG005"]
BCFTOOLS = "/opt/homebrew/bin/bcftools"


def _norm(c: str) -> str:
    return c[3:] if c.startswith("chr") else c


def clinvar_chr20() -> dict:
    d = json.loads(MANIFEST.read_text())
    recs = next(x for x in d.values() if isinstance(x, list))
    out = {}
    for r in recs:
        gc = r["genomic_context"]
        if str(gc["chrom"]) == "20":
            out[(int(gc["pos"]), gc["ref"], gc["alt"])] = r["truth"]["clnsig"]
    return out


def _load_keys(vcf: Path) -> set:
    if not vcf.exists():
        return set()
    p = subprocess.run([BCFTOOLS, "view", "-H", str(vcf)], capture_output=True, text=True)
    keys = set()
    for ln in p.stdout.splitlines():
        c = ln.split("\t")
        if _norm(c[0]) == "20":
            keys.add((int(c[1]), c[3], c[4]))
    return keys


def main() -> None:
    cv = clinvar_chr20()
    print(f"held-out ClinVar variants on chr20: {len(cv)}")
    per_sample = {}
    pooled_truth = collections.Counter()
    for s in SAMPLES:
        edir = CB / "results" / f"eval_{s}"
        tp = _load_keys(edir / "tp-baseline.vcf.gz")
        fn = _load_keys(edir / "fn.vcf.gz")
        if not tp and not fn:
            print(f"  {s}: no eval on disk, skipped")
            continue
        calling = {}
        for k in cv:
            if k in tp:
                calling[k] = {"vcfeval": "TP", "gt_match": True}
            elif k in fn:
                calling[k] = {"vcfeval": "FN"}
        joined = IW.join_workflow(calling, {}, overlap_keys=list(calling))  # interp pending
        per_sample[s] = {"overlap": len(calling),
                         "calling": dict(collections.Counter(v["vcfeval"] for v in calling.values())),
                         "truth_mix": dict(collections.Counter(cv[k] for k in calling)),
                         "endtoend": dict(joined["summary"])}
        for k in calling:
            pooled_truth[cv[k]] += 1
        print(f"  {s}: overlap={len(calling)} calling={per_sample[s]['calling']} "
              f"truth={per_sample[s]['truth_mix']}")

    distinct = set()
    for s in SAMPLES:
        edir = CB / "results" / f"eval_{s}"
        for k in cv:
            if k in _load_keys(edir / "tp-baseline.vcf.gz") or k in _load_keys(edir / "fn.vcf.gz"):
                distinct.add(k)
    out = {"clinvar_chr20": len(cv), "per_sample": per_sample,
           "distinct_overlap_variants": len(distinct),
           "pooled_truth_mix": dict(pooled_truth)}
    (_ROOT / "RESULTS" / "exp2_integration_chr20.json").write_text(json.dumps(out, indent=2) + "\n")
    print(f"\ndistinct ClinVar variants scoreable for BOTH calling+interp (chr20, any sample): "
          f"{len(distinct)}")
    print(f"pooled truth-label mix: {dict(pooled_truth)}")
    print("wrote RESULTS/exp2_integration_chr20.json")


if __name__ == "__main__":
    main()
