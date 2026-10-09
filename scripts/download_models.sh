#!/usr/bin/env bash
# Download the GGUFs listed in models.tsv into $MODEL_DIR (resumable, skips completed files).
set -euo pipefail
MODEL_DIR=${MODEL_DIR:-$HOME/models/gguf}
cd "$(dirname "$0")/.."
mkdir -p "$MODEL_DIR"
grep -v '^#' models.tsv | while IFS=$'\t' read -r slug repo file _; do
  dest="$MODEL_DIR/$file"
  expected=$(curl -sf "https://huggingface.co/api/models/$repo/tree/main" |
    python3 -c "import json,sys;print(next((f['size'] for f in json.load(sys.stdin) if f['path']=='$file'),0))")
  if [[ -f $dest && $(stat -c%s "$dest") == "$expected" ]]; then echo "ok   $slug"; continue; fi
  echo "get  $slug ($((expected/1024/1024)) MiB)"
  curl -sfL -C - --retry 5 -o "$dest" "https://huggingface.co/$repo/resolve/main/$file" ||
    { echo "FAIL $slug"; continue; }
  [[ $(stat -c%s "$dest") == "$expected" ]] && echo "done $slug" || echo "SIZE MISMATCH $slug"
done
