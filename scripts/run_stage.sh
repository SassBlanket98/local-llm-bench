#!/usr/bin/env bash
# Run one bench stage over models.tsv in order, waiting for each GGUF download to finish.
# Usage: scripts/run_stage.sh RUN_ID [extra bench args...]
set -euo pipefail
cd "$(dirname "$0")/.."
run_id=$1; shift
dl_log=research/download.log
mkdir -p "results/$run_id"
grep -v '^#' models.tsv | cut -f1 | while read -r slug; do
  until grep -qE "^(done|ok) +$slug\$" "$dl_log"; do
    if grep -qE "^(FAIL|SIZE MISMATCH) +$slug\$" "$dl_log"; then echo "$(date +%T) skip $slug (download failed)"; continue 2; fi
    sleep 60
  done
  echo "$(date +%T) start $slug"
  uv run bench run --run-id "$run_id" --manifest models.tsv --models "$slug" "$@" || echo "$(date +%T) bench exited $? for $slug"
done
echo "$(date +%T) stage done"
uv run bench report --run-id "$run_id"
