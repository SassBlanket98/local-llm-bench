"""Load models.tsv manifests."""

from __future__ import annotations

from pathlib import Path

from llmbench.server import DEFAULT_GGUF_DIR


def load_manifest(path: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        slug, repo, gguf = parts[0], parts[1], parts[2]
        note = parts[3] if len(parts) > 3 else ""
        rows.append({"slug": slug, "repo": repo, "gguf_file": gguf, "note": note})
    return rows


def gguf_path(row: dict[str, str], gguf_dir: Path | None = None) -> Path:
    base = gguf_dir or DEFAULT_GGUF_DIR
    return base / row["gguf_file"]
