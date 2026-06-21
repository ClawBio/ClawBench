# Mac Studio compute-gate provisioning (ClawBench Exp 2: GIAB variant calling)

Probed 2026-06-17 over SSH (`ssh -i ~/.ssh/id_macstudio superintelligent@100.100.64.11`).

## Starting state (what the probe found)
- Internal disk full: 12 GiB free of 1.8 TiB. Do NOT put data or tool caches on the internal volume.
- External volumes: `/Volumes/CPM-16Tb` (889 GiB free, 95% full) and `/Volumes/CPM-20Tb` (14 TiB free, 25% full).
  **Work volume = `/Volumes/CPM-20Tb`.**
- Architecture: arm64 (Apple Silicon). Relevant to containers (see the sarek caveat).
- Tools present: java, python3 only. Absent: nextflow, docker, singularity, apptainer, hap.py, rtg,
  samtools, bcftools, tabix, bgzip. No Homebrew.
- CLAWBENCH is not yet on the Studio.

## Work area
```
export CB=/Volumes/CPM-20Tb/CLAWBENCH-WORK
mkdir -p "$CB"/{repo,refs,truth,fastq,work,results,conda}
# point all tool/data caches at the external volume (internal is full)
export NXF_HOME="$CB/.nextflow"  CONDA_PKGS_DIRS="$CB/conda/pkgs"  TMPDIR="$CB/tmp"
```
Clone the repo onto the external volume (git over the existing remote):
```
git -C "$CB/repo" clone <origin> CLAWBENCH   # or sync from GitHub; do not place under ~ (internal full)
```

## Toolchain (bioconda via micromamba; no Homebrew needed, no sudo)
micromamba is the cleanest no-sudo route and keeps everything on the external volume.
```
# install micromamba into the work volume
cd "$CB" && curl -Ls https://micro.mamba.pm/api/micromamba/osx-arm64/latest | tar -xvj bin/micromamba
export MAMBA_ROOT_PREFIX="$CB/conda"
"$CB/bin/micromamba" create -y -p "$CB/conda/envs/giab" -c bioconda -c conda-forge \
    samtools bcftools htslib tabix nextflow openjdk=17
"$CB/bin/micromamba" activate "$CB/conda/envs/giab"
```
samtools/bcftools/htslib/nextflow are arm64-native via conda-forge/bioconda; this is the low-risk part.

## hap.py vs rtg vcfeval (the scorer)
hap.py has no maintained arm64 conda build and is normally run from its Docker image. Two options:
- **Preferred on arm64: `rtg vcfeval`** (RTG Tools). Pure Java, arm64-clean, installs without containers:
  `"$CB/conda/envs/giab"` add `rtg-tools` from bioconda, or download the RTG Tools zip (Java) directly.
  Our scorer (`HARNESS/score_calls.py`) parses GA4GH-style output; wire it to vcfeval's summary.
- Fallback: hap.py via Docker (`pkrusche/hap.py`) under emulation, only if Docker is installed.
Decision needed: default to **rtg vcfeval** to avoid containers for scoring; reserve Docker for sarek only.

## The container question for nf-core/sarek (the real friction)
sarek needs a container runtime, and most nf-core process containers are amd64. On arm64 macOS:
- Docker Desktop runs amd64 images under emulation (works for chr20 dev, slow; licence considerations).
- apptainer/singularity are not native on macOS (need a Linux VM), so not recommended here.
Recommended path, in order of preference:
1. **Docker Desktop on the Studio** for chr20 dev calling (emulated amd64; acceptable for chr20).
2. If emulation is too slow or Docker is unwanted, run the **calling stage on the Linux workstation
   fallback** (native amd64 + Docker/Singularity), keeping truth/scoring/analysis on the Studio.
3. Cloud only for Phase 7 full-genome confirmation.
This decision blocks Phases 3, 4, 6, 7 (the calling stages); Phases 1, 2, 5 do not need it.

## Reference + GIAB data (on the external volume)
Run the truth ingestion (Phase 1) here, not on the MacBook (MacBook is at 98% disk):
```
"$CB/conda/envs/giab"  # active
python3 HARNESS/ingest_truth.py --manifest TRUTH/MANIFEST.yaml --dest "$CB/truth"
# then build chr20 dev subsets + freeze (Phase 1 build script, forthcoming)
```
Reference fasta (~900 MB gz), stratifications tarball, and 5 sample VCF+BED land under `$CB/truth`.
chr20 FASTQ: extract chr20 reads from the GIAB 30x BAM per sample with samtools on this volume
(internal disk cannot hold the BAMs).

## Provisioned state (2026-06-18, done over SSH)
Work area: `/Volumes/CPM-20Tb/CLAWBENCH-WORK` (CB). Internal disk untouched (caches redirected;
`~/.nextflow` is 0 B). conda env: `$CB/conda/envs/giab` (micromamba, osx-arm64).
- Tools (arm64-native): samtools 1.23.1, bcftools 1.23.1, htslib/tabix/bgzip 1.23, nextflow 26.04.3,
  openjdk 23.0.2 (Zulu; `bin/java` symlinked to `lib/jvm/bin/java` so nextflow + rtg find it),
  python 3.11.15, pytest, pyyaml, **rtg-tools 3.13** (chosen scorer).
- Repo synced to `$CB/repo/CLAWBENCH`; the 8 Exp 2 test files pass on the Studio (49 passed, env python).
- nf-core/sarek 3.8.1 pulled (rev 4bd2948f98), assets on the external volume.
- Reference GRCh38 ingested (886 MB); sha256 in `$CB/MANIFEST.lock.yaml`
  (3c8def6d325c5d1e...). RTG SDF built at `$CB/refs/GRCh38.sdf` (195 seqs, 3.1 Gbp) -> vcfeval ready.
- chr20 dev truth frozen: 4 samples x VCF+BED (HG001 EUR, HG002/HG003 AJ, HG005 EAS),
  `$CB/chr20_truth_freeze.json` content_hash 8144732925adaf3e (copied to repo TRUTH/).
- Manifest fix applied: HG005 BED was `_noinconsistent.bed` (404); corrected to `_benchmark.bed`.

Remaining (not automatable over SSH / deliberately deferred):
- **Container runtime for sarek (Docker Desktop) is NOT installed** (GUI install). This is the one
  blocker for the actual calling stage. Decision stands: Docker Desktop on the Studio (emulated amd64,
  chr20 dev) vs run the calling stage on a Linux/cloud host. Truth + scoring + prep are fully ready here.
- GA4GH stratifications tarball (large, genome-wide) and chr20 FASTQ (extract from GIAB 30x BAMs):
  deferred; fetch when needed (FASTQ is required before the first calling run).

## Checklist (tick before declaring the gate clear)
- [ ] Work area on `/Volumes/CPM-20Tb`; caches redirected off the internal volume
- [ ] CLAWBENCH cloned to the external volume; tests pass with the conda env's python
- [ ] micromamba env `giab`: samtools, bcftools, htslib, tabix, nextflow, java
- [ ] scorer engine chosen and installed (rtg vcfeval preferred; hap.py/Docker fallback)
- [ ] sarek container strategy decided (Docker Desktop on Studio vs Linux-workstation calling)
- [ ] `nextflow run nf-core/sarek -profile test` completes on a tiny test (smoke)
- [ ] GIAB reference + stratifications + 5 sample VCF/BED ingested + locked on the external volume
- [ ] chr20 FASTQ subsets extracted per sample
```
```
