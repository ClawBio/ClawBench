#!/usr/bin/env bash
# Fetch + normalise the GIAB chr20 pilot data from PUBLIC sources into the exact layout exp2_driver.py
# expects. Fully reproducible (no private upload). Idempotent: each step skips if its output exists.
#   refs/GRCh38.fasta(.fai)  refs/GRCh38.chr20.fasta(.fai)  refs/GRCh38.sdf  refs/chr20.bed
#   truth/HG002.chr20.vcf.gz(.tbi)  truth/HG002.chr20.bed
#   fastq/HG002.chr20.R1.fastq.gz  fastq/HG002.chr20.R2.fastq.gz
set -euo pipefail
export MAMBA_ROOT_PREFIX="$HOME/micromamba"
export PATH="$HOME/micromamba/envs/giab/bin:$HOME/.local/bin:$PATH"
CBWORK="${CBWORK:-/workspaces/cbwork}"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "$CBWORK"/{refs,fastq,truth,sandbox,.nextflow}
cd "$REPO"

REF_URL="https://ftp-trace.ncbi.nlm.nih.gov/ReferenceSamples/giab/release/references/GRCh38/GCA_000001405.15_GRCh38_no_alt_analysis_set.fasta.gz"
TVCF="https://ftp-trace.ncbi.nlm.nih.gov/ReferenceSamples/giab/release/AshkenazimTrio/HG002_NA24385_son/NISTv4.2.1/GRCh38/HG002_GRCh38_1_22_v4.2.1_benchmark.vcf.gz"
TBED="https://ftp-trace.ncbi.nlm.nih.gov/ReferenceSamples/giab/release/AshkenazimTrio/HG002_NA24385_son/NISTv4.2.1/GRCh38/HG002_GRCh38_1_22_v4.2.1_benchmark_noinconsistent.bed"

echo ">> [1/6] reference"
if [ ! -s "$CBWORK/refs/GRCh38.fasta" ]; then
  curl -L "$REF_URL" -o "$CBWORK/refs/GRCh38.fasta.gz"
  gunzip -f "$CBWORK/refs/GRCh38.fasta.gz"
fi
[ -s "$CBWORK/refs/GRCh38.fasta.fai" ] || samtools faidx "$CBWORK/refs/GRCh38.fasta"

echo ">> [2/6] chr20 reference subset + dict"
if [ ! -s "$CBWORK/refs/GRCh38.chr20.fasta" ]; then
  samtools faidx "$CBWORK/refs/GRCh38.fasta" chr20 > "$CBWORK/refs/GRCh38.chr20.fasta"
  samtools faidx "$CBWORK/refs/GRCh38.chr20.fasta"
fi
LEN=$(cut -f2 "$CBWORK/refs/GRCh38.chr20.fasta.fai")
printf "chr20\t0\t%s\n" "$LEN" > "$CBWORK/refs/chr20.bed"

echo ">> [3/6] RTG SDF (vcfeval template, full reference for contig match)"
[ -d "$CBWORK/refs/GRCh38.sdf" ] || rtg format -o "$CBWORK/refs/GRCh38.sdf" "$CBWORK/refs/GRCh38.fasta"

echo ">> [4/6] HG002 truth, restricted to chr20"
if [ ! -s "$CBWORK/truth/HG002.chr20.vcf.gz" ]; then
  curl -L "$TVCF" -o "$CBWORK/truth/HG002.full.vcf.gz"
  curl -L "$TVCF.tbi" -o "$CBWORK/truth/HG002.full.vcf.gz.tbi" || tabix -p vcf "$CBWORK/truth/HG002.full.vcf.gz"
  bcftools view -r chr20 -Oz -o "$CBWORK/truth/HG002.chr20.vcf.gz" "$CBWORK/truth/HG002.full.vcf.gz"
  tabix -p vcf "$CBWORK/truth/HG002.chr20.vcf.gz"
fi
if [ ! -s "$CBWORK/truth/HG002.chr20.bed" ]; then
  curl -L "$TBED" -o "$CBWORK/truth/HG002.full.bed"
  awk '$1=="chr20"' "$CBWORK/truth/HG002.full.bed" > "$CBWORK/truth/HG002.chr20.bed"
fi

echo ">> [5/6] HG002 chr20 FASTQ (remote-range stream from public 300x BAM -> 30x; HG002 only)"
if [ ! -s "$CBWORK/fastq/HG002.chr20.R1.fastq.gz" ]; then
  python - "$REPO/TRUTH/MANIFEST.yaml" "$CBWORK/HG002_only_manifest.yaml" <<'PY'
import sys, yaml
m = yaml.safe_load(open(sys.argv[1]))
m["fastq"]["alignments"] = [a for a in m["fastq"]["alignments"] if a["id"] == "HG002"]
yaml.safe_dump(m, open(sys.argv[2], "w"))
PY
  python HARNESS/chr20_fastq.py --manifest "$CBWORK/HG002_only_manifest.yaml" --workdir "$CBWORK" \
    --region chr20 --target-x 30 --allow-internal --min-free-gb 5
fi

echo ">> [6/6] pre-pull validated nf-core/sarek 3.8.1"
NXF_HOME="$CBWORK/.nextflow" nextflow pull nf-core/sarek -r 3.8.1 || echo "(sarek pull deferred; resolve mode will fetch)"

echo ">> data ready under $CBWORK"
ls -lh "$CBWORK"/refs "$CBWORK"/truth "$CBWORK"/fastq
