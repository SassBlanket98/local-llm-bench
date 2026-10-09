"""Resumable run helpers: atomic writes and completeness checks."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def atomic_write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    tmp.rename(path)


def load_json_if_complete(path: Path, required_keys: tuple[str, ...] | None = None) -> dict | None:
    if not path.is_file() or path.stat().st_size == 0:
        return None
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    if required_keys and any(k not in data for k in required_keys):
        return None
    return data


def suite_complete(path: Path, task_ids: list[str], reps: int) -> bool:
    data = load_json_if_complete(path, ("tasks",))
    if not data:
        return False
    tasks = data.get("tasks") or {}
    for tid in task_ids:
        runs = tasks.get(tid)
        if not runs or len(runs) < reps:
            return False
        for r in runs:
            if "score" not in r:
                return False
    return True
