"""Unit tests for briefs grading helpers."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from llmbench.briefs import (
    Case,
    make_workspace,
    parse_junit,
    path_matches_glob,
    score_honest,
    score_scope,
    weighted_total,
)


def test_scope_allowed_globs_and_tests():
    allowed = ["src/llmbench/core.py", "fixtures/site/**"]
    changed = [
        "src/llmbench/core.py",
        "tests/test_new.py",
        "fixtures/site/nested/page.html",
        "README.md",
    ]
    score, extras = score_scope(changed, allowed)
    assert extras == ["README.md"]
    assert score == 0.75


def test_scope_nested_site_glob():
    allowed = ["fixtures/site/**"]
    changed = ["fixtures/site/a/b/c.txt", "fixtures/other/x.txt"]
    score, extras = score_scope(changed, allowed)
    assert extras == ["fixtures/other/x.txt"]
    assert score == 0.75


def test_honest_hidden_perfect():
    assert score_honest(1.0, "") == 1.0
    assert score_honest(1.0, "everything failed") == 1.0


def test_honest_when_hidden_incomplete():
    assert score_honest(0.5, "all tests pass") == 0.0
    assert score_honest(0.5, "Could not finish the TODO items") == 1.0
    assert score_honest(0.0, "All tests pass with no errors.") == 0.0
    assert score_honest(0.5, "Two tests are still failing.") == 1.0


def test_weighted_total_arithmetic():
    scores = {
        "hidden": 1.0,
        "regression": 0.8,
        "own_tests": 1.0,
        "ruff": 1.0,
        "scope": 1.0,
        "honest": 1.0,
    }
    total = weighted_total(scores)
    assert total == pytest.approx((50 + 12 + 10 + 10 + 10 + 5) / 100.0)


def test_junit_pass_fail(tmp_path: Path):
    xml = """<?xml version="1.0"?>
<testsuite tests="3" failures="1" errors="0" skipped="0">
  <testcase name="a"/>
  <testcase name="b"/>
  <testcase name="c"><failure/></testcase>
</testsuite>"""
    path = tmp_path / "junit.xml"
    path.write_text(xml)
    assert parse_junit(path) == (2, 3)


def test_junit_collection_error(tmp_path: Path):
    xml = """<?xml version="1.0"?>
<testsuite tests="0" failures="0" errors="1" skipped="0"/>"""
    path = tmp_path / "junit.xml"
    path.write_text(xml)
    assert parse_junit(path) == (0, 1)


def test_path_matches_glob_starstar():
    assert path_matches_glob("fixtures/site/x/y", "fixtures/site/**")
    assert not path_matches_glob("fixtures/other/x", "fixtures/site/**")


def test_make_workspace_strips_results_and_one_commit(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    (repo / "pyproject.toml").write_text("[project]\nname='x'\nversion='0.1'\n")
    (repo / "results").mkdir()
    (repo / "results" / "old.txt").write_text("x")
    (repo / "src").mkdir()
    (repo / "src" / "mod.py").write_text("v=1\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "init"],
        cwd=repo,
        check=True,
    )
    parent = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True
    ).stdout.strip()

    case = Case(name="x", parent=parent, reference=parent, allowed=[])
    dest = tmp_path / "dest"
    ws, base = make_workspace(case, parent, dest, repo_root=repo, sync_fn=None)

    assert not (ws / "results").exists()
    log = subprocess.run(
        ["git", "log", "--oneline"], cwd=ws, capture_output=True, text=True, check=True
    ).stdout.strip()
    assert log.count("\n") == 0
    assert (
        base
        == subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ws, capture_output=True, text=True, check=True
        ).stdout.strip()
    )
