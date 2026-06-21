#!/usr/bin/env bash
# Run the agent arms on native x86 Linux (no emulation, native GATK). Confirms the chr20 pilot result
# without the arm64/Rosetta confounds: free_agent executes natively; skill_reasoning is retested with
# resolution (Finding 2). Produces clean F1 for whatever actually executes.
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

echo "===== ARM: free_agent (native x86 bwa/gatk) ====="
GIAB_BIN="$GIAB_BIN" python HARNESS/exp2_driver.py --arm free_agent --timeout 5400 \
  --out "$REPO/RESULTS/codespace_free_scorecard.jsonl" || true

echo "===== ARM: skill_reasoning (resolution allowed; Finding 2 on native Linux) ====="
GIAB_BIN="$GIAB_BIN" python HARNESS/exp2_driver.py --arm skill_reasoning --resolve --timeout 14400 \
  --out "$REPO/RESULTS/codespace_skill_resolved.jsonl" || true

echo "===== SCORECARDS ====="
for f in codespace_free_scorecard codespace_skill_resolved; do
  echo "--- $f ---"; cat "$REPO/RESULTS/$f.jsonl" 2>/dev/null || echo "(none)"
done
