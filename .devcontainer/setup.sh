#!/usr/bin/env bash
# postCreate: install the native linux-64 bioinformatics toolchain (no emulation, no arm64 GATK issue).
# Heavy data prep + the run are separate scripts (scripts/codespace_data.sh, codespace_run.sh) so their
# output is visible and iterable rather than buried in container creation.
set -euo pipefail

MM="$HOME/.local/bin/micromamba"
export MAMBA_ROOT_PREFIX="$HOME/micromamba"
ENV="$MAMBA_ROOT_PREFIX/envs/giab"

if [ ! -x "$MM" ]; then
  echo ">> installing micromamba (linux-64)"
  mkdir -p "$HOME/.local/bin"
  curl -Ls https://micro.mamba.pm/api/micromamba/linux-64/latest | tar -xj -C /tmp bin/micromamba
  mv /tmp/bin/micromamba "$MM"
fi

if [ ! -d "$ENV" ]; then
  echo ">> creating giab env (samtools/bcftools/nextflow/rtg/bwa/gatk4/fastp, native x86)"
  "$MM" create -y -p "$ENV" -c bioconda -c conda-forge \
    samtools bcftools htslib tabix nextflow rtg-tools bwa bwa-mem2 gatk4 fastp \
    openjdk=17 python=3.11 pyyaml pytest
fi

# make the env + micromamba available in every shell
grep -q 'micromamba/envs/giab/bin' "$HOME/.bashrc" 2>/dev/null || cat >> "$HOME/.bashrc" <<'RC'
export MAMBA_ROOT_PREFIX=$HOME/micromamba
export PATH=$HOME/micromamba/envs/giab/bin:$HOME/.local/bin:$PATH
export CBWORK=${CBWORK:-/workspaces/cbwork}
RC

echo ">> env ready. Next:"
echo "   bash scripts/codespace_data.sh   # fetch + normalise GIAB chr20 data (public, reproducible)"
echo "   bash scripts/codespace_run.sh     # run free + skill_reasoning arms, print scorecards"
