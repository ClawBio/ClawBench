#!/usr/bin/env bash
# LEAN SMOKE VALIDATION (1 rep, 1 execution) of execution behaviour on native x86 Linux -- NOT the
# replicated benchmark. It answers two yes/no questions only: does free_agent execute and produce a
# real F1 under native GATK (no arm64/Rosetta confound), and does skill_reasoning still fail version
# coherence on native Linux? The full replicated experiment (reps + reproducibility + CIs) is reserved
# for the final benchmark run. Speed here is for decision clarity, not statistical precision.
set -euo pipefail
export MAMBA_ROOT_PREFIX="$HOME/micromamba"
export GIAB_BIN="$HOME/micromamba/envs/giab/bin"
export PATH="$GIAB_BIN:/usr/local/bin:/usr/bin:/bin:$HOME/.local/bin:$PATH"
CBWORK="${CBWORK:-/workspaces/cbwork}"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"
export CB="$CBWORK"

docker info >/dev/null 2>&1 || { echo "Docker not ready (docker-in-docker). Re-run after the container finishes provisioning."; exit 1; }
for p in "$CBWORK/refs/GRCh38.chr20.fasta" "$CBWORK/truth/HG002.chr20.vcf.gz" "$CBWORK/fastq/HG002.chr20.R1.fastq.gz" "$CBWORK/refs/GRCh38.sdf"; do
  [ -e "$p" ] || { echo "missing $p -- run scripts/codespace_data.sh first"; exit 1; }
done

echo "===== ARM: free_agent (native x86 bwa/gatk; 1 rep, 1 execution) ====="
GIAB_BIN="$GIAB_BIN" python HARNESS/exp2_driver.py --arm free_agent --reps 1 --single --timeout 5400 \
  --out "$REPO/RESULTS/codespace_free_scorecard.jsonl" || true

echo "===== ARM: skill_reasoning (resolution allowed; 1 rep, 1 execution) ====="
GIAB_BIN="$GIAB_BIN" python HARNESS/exp2_driver.py --arm skill_reasoning --resolve --reps 1 --single --timeout 14400 \
  --out "$REPO/RESULTS/codespace_skill_resolved.jsonl" || true

echo "===== SCORECARDS ====="
for f in codespace_free_scorecard codespace_skill_resolved; do
  echo "--- $f ---"; cat "$REPO/RESULTS/$f.jsonl" 2>/dev/null || echo "(none)"
done
