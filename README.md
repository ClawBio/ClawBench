# ClawBench

The open, GIAB-grounded benchmark for **trustworthy agentic genomics**.

ClawBench tests whether the trust result from the founding study (Corpas et al., *Trustworthy agentic
genomics through versioned skill libraries*) generalises across the canonical genomic workflow. It
benchmarks the [ClawBio](https://github.com/ClawBio/ClawBio) skill library against Genome in a Bottle (GIAB)
ground truth, under a five-condition constraint gradient that relocates correctness from the model into an
executed, versioned skill.

> Founding citation (do not supersede pre-DOI): Corpas et al., bioRxiv 2026, BIORXIV/2026/731523.

## Thesis under test
Trustworthiness is a property of pipeline architecture, not of the model. Executing validated logic as code
makes the mapping exact, auditable, and model-invariant, confining residual error to one input-interpretation
step. ClawBench asks whether this holds for variant interpretation (VCF to ACMG class) and for variant
calling (FASTQ to VCF), two tasks that fail in structurally different ways.

## The constraint gradient (per task, per skill)
1. free-prompted, 2. retrieval-augmented, 3. skill-reasoning (model reads the SKILL.md),
4. skill-execution (`clawbio.py run <skill>`; validated code computes the answer), 5. answer-supplied control.

## Experiments (Phase 1)
- **Exp 1 Interpretation** — skill `clinical-variant-reporter` (ACMG/AMP 2015, 28 criteria). Truth: ClinVar
  2-star+/expert-panel, held-out post-model-cutoff slice, anchored to GIAB genotypes. Scored on label
  concordance AND ACMG criteria-level concordance.
- **Exp 2 FASTQ to VCF** — skill `nfcore-sarek-wrapper` (nf-core/sarek 3.8.1). Truth: GIAB v4.2.1
  high-confidence calls, scored with hap.py/vcfeval, stratified by GA4GH genome-stratification regions.
  Compute: chr20 for development, a few full genomes to confirm.

Trust instruments are themselves ClawBio skills: `repro-enforcer` (checksum manifest + pinned env =
auditability) and `equity-scorer` (ancestry/population stratification = population-invariance).

## Layout
```
TRUTH/      GIAB + ClinVar truth; MANIFEST.yaml is authoritative, data fetched not committed
HARNESS/    constraint-gradient runner + scorers (hap.py/vcfeval, ACMG concordance)
SKILLS/     pinned refs of the ClawBio skills under test
EVALS/      one file per eval
RESULTS/    per-condition raw + aggregated JSON
FIGURES/    data-bound figure scripts (no simulated data)
tests/      red/green TDD for harness + scorers
```

## Quick start
```bash
# fetch + verify the GIAB chr20 dev truth set (fails closed on checksum mismatch)
python3 HARNESS/ingest_truth.py --manifest TRUTH/MANIFEST.yaml --dest TRUTH
```

License: MIT.
