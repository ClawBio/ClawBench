# nfcore-sarek-wrapper

A ClawBio skill that runs the germline short-variant calling workflow (FASTQ to VCF) by executing
nf-core/sarek under a fully pinned, provenance-complete, reproducible contract. This is the executed
skill arm of the ClawBench Exp 2 constraint gradient: it relocates calling correctness out of the
stochastic agent and into validated, version-locked code.

## What it does
Given a sample sheet of FASTQ inputs, a pinned reference, and a pinned interval (region) BED, it builds
and runs `nextflow run nf-core/sarek` with a pinned pipeline version, pinned container digests, and a
fixed parameter set, then emits the called VCF plus a provenance manifest sufficient to reproduce the
run bit-for-bit (or, at minimum, genotype-for-genotype).

## Pinning contract (fail-closed)
A run is refused unless ALL of the following are pinned:
- `sarek_version`: an explicit release tag (for example `3.8.1`). Never `latest`.
- `reference_id` + `reference_sha256`: the reference is identified and checksummed (from MANIFEST.lock.yaml).
- `container_digests`: every process container is a digest pin (`...@sha256:...`), never a mutable tag.
- `intervals_bed`: the region is pinned (chr20 for development; whole-genome for confirmation).
The validator (`validate_pins`) raises before any command is built if any pin is missing.

## Architecture profiles
The skill is architecture-aware via an explicit flag:
- `arm64_local`: Mac Studio. Docker Desktop runs amd64 process containers under emulation
  (`--platform linux/amd64`). Acceptable for chr20 development; slow for whole genomes.
- `linux_x86`: native Docker or Singularity on a Linux host. Preferred for whole-genome runs.
- `cloud`: a batch executor profile for Phase 7 full-genome confirmation only.
Scoring uses RTG vcfeval by default (arm64-clean, no container); hap.py is an optional cloud cross-check.

## Provenance manifest (required before any run)
Every run first writes a provenance manifest capturing: sarek_version, genome, reference id + sha256,
container engine + digests, parameters, intervals (region), architecture, input FASTQs + sha256, the
exact nextflow command, tool versions, and a content hash over the above. A run without a written
provenance manifest is refused.

## Reproducibility modes
- `genotype` (default): two runs are reproducible if they yield identical genotypes within the confident
  region (chrom, pos, ref, alt, normalised GT), ignoring header and record-order noise.
- `byte` (optional): two runs produce byte-identical output. Stricter; not all callers guarantee it.
The `repro-enforcer` instrument checks the chosen mode and that both runs share identical pins.

## Invocation (host; execution is mocked until the compute gate is cleared)
```
python3 SKILLS/nfcore-sarek-wrapper/run_sarek.py \
  --config config.pinned.json --samplesheet samplesheet.csv \
  --outdir /Volumes/CPM-20Tb/CLAWBENCH/work/HG002 --arch arm64_local --dry-run
```
Drop `--dry-run` only on a provisioned host (nextflow + container runtime present).
