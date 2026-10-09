"""Load per-model sampling presets from presets.toml."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

PRESETS_PATH = Path(__file__).resolve().parents[2] / "presets.toml"


def load_presets(path: Path | None = None) -> dict[str, dict[str, Any]]:
    data = tomllib.loads((path or PRESETS_PATH).read_text())
    return {k: v for k, v in data.items() if not k.startswith("_")}


def preset_for(slug: str, path: Path | None = None) -> dict[str, Any]:
    presets = load_presets(path)
    if slug not in presets:
        return {
            "thinking": "none",
            "sampling": {"temperature": 0.7, "top_p": 0.95},
        }
    return presets[slug]
