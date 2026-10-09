"""Tests for the `bench models` listing command."""

from __future__ import annotations

import argparse
from pathlib import Path

from llmbench.cli import cmd_models


def _write_manifest(path: Path, rows: list[tuple[str, str, str]]) -> None:
    path.write_text("".join(f"{slug}\t{repo}\t{gguf}\n" for slug, repo, gguf in rows))


def _run_capture(
    manifest: Path, gguf_dir: Path, missing: bool = False
) -> list[tuple[str, str, bool]]:
    ns = argparse.Namespace(manifest=str(manifest), gguf_dir=str(gguf_dir), missing=missing)
    import io
    from contextlib import redirect_stdout

    buf = io.StringIO()
    with redirect_stdout(buf):
        cmd_models(ns)
    out = buf.getvalue().strip()
    if not out:
        return []
    return [tuple(line.split("\t")) for line in out.splitlines()]


def test_lists_every_model_with_existence(tmp_path: Path):
    gguf_dir = tmp_path / "ggufs"
    gguf_dir.mkdir()
    manifest = tmp_path / "models.tsv"
    _write_manifest(
        manifest,
        [
            ("qwen-smoke", "unsloth/Qwen3.5-0.8B-GGUF", "Qwen3.5-0.8B-Q8_0.gguf"),
            ("ornith", "ornith-ai/Ornith-1.5-9B-GGUF", "Ornith-1.5-9B-Q8_0.gguf"),
        ],
    )
    (gguf_dir / "Qwen3.5-0.8B-Q8_0.gguf").write_text("not really a model")

    rows = _run_capture(manifest, gguf_dir, missing=False)

    assert len(rows) == 2
    by_slug = {slug: (gguf, exists) for slug, gguf, exists in rows}
    assert by_slug["qwen-smoke"] == ("Qwen3.5-0.8B-Q8_0.gguf", "yes")
    assert by_slug["ornith"] == ("Ornith-1.5-9B-Q8_0.gguf", "no")


def test_missing_flag_only_shows_absent_files(tmp_path: Path):
    gguf_dir = tmp_path / "ggufs"
    gguf_dir.mkdir()
    manifest = tmp_path / "models.tsv"
    _write_manifest(
        manifest,
        [
            ("present-model", "repo/present", "Present-Q8_0.gguf"),
            ("absent-model", "repo/absent", "Absent-Q8_0.gguf"),
        ],
    )
    (gguf_dir / "Present-Q8_0.gguf").write_text("here")

    rows = _run_capture(manifest, gguf_dir, missing=True)

    assert len(rows) == 1
    assert rows[0][0] == "absent-model"
    assert rows[0][2] == "no"


def test_empty_manifest_reports_nothing(tmp_path: Path):
    gguf_dir = tmp_path / "ggufs"
    gguf_dir.mkdir()
    manifest = tmp_path / "models.tsv"
    _write_manifest(manifest, [])

    import io
    from contextlib import redirect_stdout

    buf = io.StringIO()
    with redirect_stdout(buf):
        cmd_models(
            argparse.Namespace(manifest=str(manifest), gguf_dir=str(gguf_dir), missing=False)
        )
    assert buf.getvalue().strip() == "no models"


def test_missing_flag_on_empty_manifest(tmp_path: Path):
    gguf_dir = tmp_path / "ggufs"
    gguf_dir.mkdir()
    manifest = tmp_path / "models.tsv"
    _write_manifest(manifest, [])

    import io
    from contextlib import redirect_stdout

    buf = io.StringIO()
    with redirect_stdout(buf):
        cmd_models(argparse.Namespace(manifest=str(manifest), gguf_dir=str(gguf_dir), missing=True))
    assert buf.getvalue().strip() == "no missing models"
