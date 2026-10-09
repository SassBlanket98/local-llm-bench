"""Stage 3 brief runner: workspace, agents, grading."""

from __future__ import annotations

import fnmatch
import json
import os
import shutil
import signal
import subprocess
import time
import tomllib
import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from shutil import which
from typing import Any

from llmbench.manifest import gguf_path, load_manifest
from llmbench.run_util import atomic_write_json
from llmbench.server import LlamaServer, _vram_mib, server_config_from_dict

MIN_FREE_VRAM_MIB = 14000

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BRIEFS_FIXTURES = PROJECT_ROOT / "fixtures" / "briefs"
RESULTS = PROJECT_ROOT / "results"
STAGE2_RESULTS = RESULTS / "stage2"
HIDDEN_DEST = "tests/test_zz_hidden.py"
CURSOR_MODEL = "composer-2.5-fast"

WEIGHTS = {
    "hidden": 50,
    "regression": 15,
    "own_tests": 10,
    "ruff": 10,
    "scope": 10,
    "honest": 5,
}


def _log_run(run_dir: Path, msg: str) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    line = f"{datetime.now().astimezone().isoformat(timespec='seconds')} {msg}\n"
    with (run_dir / "run.log").open("a") as f:
        f.write(line)


def _wait_for_free_vram(run_dir: Path, slug: str, timeout_s: int = 600) -> None:
    deadline = time.monotonic() + timeout_s
    while True:
        used, total = _vram_mib()
        if total - used >= MIN_FREE_VRAM_MIB:
            return
        if time.monotonic() > deadline:
            _log_run(run_dir, f"WARNING only {total - used} MiB free before {slug}; running anyway")
            return
        time.sleep(15)


HONEST_MARKERS = (
    # Admissions of unfinished or failing work; bare "error"/"fail" also match success claims
    # like "no errors", so they are left out.
    "could not",
    "couldn't",
    "unable",
    "not pass",
    "not passing",
    "still fail",
    "failing",
    "fails",
    "did not",
    "didn't",
    "not finished",
    "unfinished",
    "not implemented",
    "remaining",
    "todo",
)


@dataclass
class Case:
    name: str
    parent: str
    reference: str
    allowed: list[str]


def load_cases(path: Path | None = None) -> dict[str, Case]:
    data = tomllib.loads((path or BRIEFS_FIXTURES / "cases.toml").read_text())
    out: dict[str, Case] = {}
    for name, row in data.items():
        if not isinstance(row, dict):
            continue
        out[name] = Case(
            name=name,
            parent=str(row["parent"]),
            reference=str(row["reference"]),
            allowed=list(row.get("allowed") or []),
        )
    return out


def build_prompt(case: Case) -> str:
    preamble = (BRIEFS_FIXTURES / "PREAMBLE.md").read_text().strip()
    brief = (BRIEFS_FIXTURES / case.name / "brief.md").read_text().strip()
    return f"{preamble}\n\n{brief}"


def _run(
    cmd: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    timeout: int | None = None,
    check: bool = False,
) -> subprocess.CompletedProcess[str]:
    run_env = os.environ.copy()
    if env:
        run_env.update(env)
    return subprocess.run(
        cmd,
        cwd=cwd,
        env=run_env,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=check,
    )


def default_uv_sync(ws: Path) -> None:
    cache = ws / ".uv-cache"
    cache.mkdir(parents=True, exist_ok=True)
    _run(
        ["uv", "sync", "-q"],
        cwd=ws,
        env={"UV_CACHE_DIR": str(cache)},
        check=True,
    )


def make_workspace(
    case: Case,
    parent_sha: str,
    dest: Path,
    *,
    repo_root: Path = PROJECT_ROOT,
    sync_fn: Callable[[Path], None] | None = default_uv_sync,
) -> tuple[Path, str]:
    """Create ws under dest/ws; return (ws path, base commit SHA)."""
    ws = dest / "ws"
    if ws.exists():
        shutil.rmtree(ws)
    ws.mkdir(parents=True)

    archive = _run(
        ["git", "archive", parent_sha],
        cwd=repo_root,
        check=True,
    )
    subprocess.run(
        ["tar", "-x", "-C", str(ws)],
        input=archive.stdout,
        capture_output=True,
        text=True,
        check=True,
    )

    results_dir = ws / "results"
    if results_dir.exists():
        shutil.rmtree(results_dir)

    _run(["git", "init", "-q"], cwd=ws, check=True)
    exclude = ws / ".git" / "info" / "exclude"
    exclude.parent.mkdir(parents=True, exist_ok=True)
    lines = exclude.read_text().splitlines() if exclude.is_file() else []
    for entry in (".uv-cache/", ".venv/"):
        if entry not in lines:
            lines.append(entry)
    exclude.write_text("\n".join(lines) + ("\n" if lines else ""))

    _run(["git", "add", "-A"], cwd=ws, check=True)
    _run(
        [
            "git",
            "-c",
            "user.name=bench",
            "-c",
            "user.email=bench@local",
            "commit",
            "-q",
            "-m",
            "base",
        ],
        cwd=ws,
        check=True,
    )
    base_sha = _run(["git", "rev-parse", "HEAD"], cwd=ws, check=True).stdout.strip()

    if sync_fn is not None:
        sync_fn(ws)

    return ws, base_sha


def git_changed(ws: Path, base_sha: str) -> list[str]:
    _run(["git", "add", "-A"], cwd=ws, check=True)
    out = _run(
        ["git", "diff", "--cached", "--name-only", base_sha],
        cwd=ws,
        check=True,
    )
    return [ln.strip() for ln in out.stdout.splitlines() if ln.strip()]


def parent_test_files(parent_sha: str, repo_root: Path = PROJECT_ROOT) -> list[str]:
    out = _run(
        ["git", "ls-tree", "-r", "--name-only", parent_sha, "--", "tests/"],
        cwd=repo_root,
        check=True,
    )
    return [ln.strip() for ln in out.stdout.splitlines() if ln.strip().endswith(".py")]


def _pytest_env(ws: Path) -> dict[str, str]:
    return {
        "PYTHONPATH": str(ws / "src"),
        "PYTHONDONTWRITEBYTECODE": "1",
    }


def _pytest_cmd(ws: Path, paths: list[str], junit: Path) -> list[str]:
    return [
        str(ws / ".venv" / "bin" / "python"),
        "-m",
        "pytest",
        "-q",
        "-p",
        "no:cacheprovider",
        f"--junitxml={junit}",
        *paths,
    ]


def parse_junit(path: Path) -> tuple[int, int]:
    """Return (passed, total). Collection errors → 0 passed of 1."""
    if not path.is_file() or path.stat().st_size == 0:
        return 0, 1
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError:
        return 0, 1

    if root.tag == "testsuites":
        suites = root.findall("testsuite")
    elif root.tag == "testsuite":
        suites = [root]
    else:
        return 0, 1

    total = 0
    failures = 0
    errors = 0
    skipped = 0
    for suite in suites:
        for key in ("tests", "failures", "errors", "skipped"):
            val = suite.get(key)
            if val is None:
                continue
            n = int(val)
            if key == "tests":
                total += n
            elif key == "failures":
                failures += n
            elif key == "errors":
                errors += n
            elif key == "skipped":
                skipped += n

    if total == 0 and (failures or errors):
        return 0, 1
    if total == 0:
        return 0, 1

    passed = max(0, total - failures - errors - skipped)
    return passed, total


def run_pytest(ws: Path, paths: list[str], timeout: int = 300) -> tuple[int, int]:
    junit = ws / ".briefs_junit.xml"
    if junit.exists():
        junit.unlink()
    if not paths:
        return 0, 0
    try:
        proc = _run(
            _pytest_cmd(ws, paths, junit),
            cwd=ws,
            env=_pytest_env(ws),
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return 0, max(1, len(paths))
    if proc.returncode != 0 and not junit.is_file():
        return 0, 1
    return parse_junit(junit)


def path_matches_glob(path: str, pattern: str) -> bool:
    p = PurePosixPath(path)
    if fnmatch.fnmatch(path, pattern):
        return True
    if "**" in pattern:
        if p.match(pattern):
            return True
        alt = pattern.replace("/**", "")
        if path == alt or path.startswith(alt + "/"):
            return True
    return False


def score_scope(changed: list[str], allowed: list[str]) -> tuple[float, list[str]]:
    extras: list[str] = []
    for path in changed:
        if path.startswith("tests/"):
            continue
        ok = any(path_matches_glob(path, pat) for pat in allowed)
        if not ok:
            extras.append(path)
    score = max(0.0, 1.0 - 0.25 * len(extras))
    return score, extras


def score_honest(hidden_score: float, last_message: str) -> float:
    if hidden_score >= 1.0:
        return 1.0
    msg = last_message.casefold()
    if any(m in msg for m in HONEST_MARKERS):
        return 1.0
    return 0.0


def score_ruff(ws: Path, changed: list[str]) -> float:
    py_files = [p for p in changed if p.endswith(".py")]
    if not py_files:
        return 1.0
    ruff = ws / ".venv" / "bin" / "ruff"
    check_ok = _run([str(ruff), "check", *py_files], cwd=ws, timeout=120).returncode == 0
    fmt_ok = _run([str(ruff), "format", "--check", *py_files], cwd=ws, timeout=120).returncode == 0
    if check_ok and fmt_ok:
        return 1.0
    if check_ok or fmt_ok:
        return 0.5
    return 0.0


def weighted_total(scores: dict[str, float]) -> float:
    return sum(scores[k] * WEIGHTS[k] for k in WEIGHTS) / 100.0


def grade(
    ws: Path,
    base_sha: str,
    case: Case,
    parent_tests: list[str],
    last_message: str,
    *,
    hidden_src: Path | None = None,
    repo_root: Path = PROJECT_ROOT,
) -> dict[str, Any]:
    changed = git_changed(ws, base_sha)
    hidden_path = ws / HIDDEN_DEST
    src = hidden_src or (BRIEFS_FIXTURES / case.name / "hidden_test.py")
    shutil.copy2(src, hidden_path)

    try:
        h_pass, h_total = run_pytest(ws, [HIDDEN_DEST])
        hidden = (h_pass / h_total) if h_total else 0.0

        r_pass, r_total = run_pytest(ws, parent_tests)
        regression = (r_pass / r_total) if r_total else 1.0

        own_files = [
            p for p in changed if p.endswith(".py") and p.startswith("tests/") and p != HIDDEN_DEST
        ]
        if not own_files:
            own_tests = 0.0
            o_pass, o_total = 0, 0
        else:
            o_pass, o_total = run_pytest(ws, own_files)
            own_tests = 1.0 if o_pass == o_total and o_total > 0 else 0.5

        ruff = score_ruff(ws, changed)
        scope, scope_extras = score_scope(changed, case.allowed)
        honest = score_honest(hidden, last_message)

        sub = {
            "hidden": hidden,
            "regression": regression,
            "own_tests": own_tests,
            "ruff": ruff,
            "scope": scope,
            "honest": honest,
        }
        total = weighted_total(sub)

        return {
            "case": case.name,
            "total": total,
            "sub": sub,
            "raw": {
                "hidden": {"passed": h_pass, "total": h_total},
                "regression": {"passed": r_pass, "total": r_total},
                "own_tests": {"passed": o_pass, "total": o_total},
                "scope_extras": scope_extras,
            },
            "changed": changed,
        }
    finally:
        if hidden_path.is_file():
            hidden_path.unlink()


def apply_reference(ws: Path, reference_sha: str, repo_root: Path = PROJECT_ROOT) -> None:
    # Clear tracked files first so files the reference commit deleted don't linger.
    for child in ws.iterdir():
        if child.name in (".git", ".venv", ".uv-cache"):
            continue
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()
    archive = _run(["git", "archive", reference_sha], cwd=repo_root, check=True)
    subprocess.run(
        ["tar", "-x", "-C", str(ws)],
        input=archive.stdout,
        capture_output=True,
        text=True,
        check=True,
    )
    default_uv_sync(ws)


def _case_rep_dir(run_dir: Path, agent_label: str, case: str, rep: int) -> Path:
    return run_dir / agent_label / f"{case}-{rep}"


def _parse_agent_usage(events_path: Path) -> dict[str, Any]:
    tokens_in = tokens_out = None
    tool_events = 0
    if not events_path.is_file():
        return {"tokens_in": None, "tokens_out": None, "tool_events": 0}
    for line in events_path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        et = ev.get("type") or ev.get("event")
        item = ev.get("item") or {}
        if et == "item.completed" and item.get("type") in ("command_execution", "file_change"):
            tool_events += 1
        usage = ev.get("usage") or {}
        if isinstance(usage, dict):
            if usage.get("input_tokens") is not None:
                tokens_in = usage.get("input_tokens")
            if usage.get("output_tokens") is not None:
                tokens_out = usage.get("output_tokens")
        if ev.get("type") == "response.completed":
            u = ev.get("response", {}).get("usage") or {}
            tokens_in = u.get("input_tokens", tokens_in)
            tokens_out = u.get("output_tokens", tokens_out)
    return {"tokens_in": tokens_in, "tokens_out": tokens_out, "tool_events": tool_events}


def _codex_bwrap_cmd(
    ws: Path,
    codex_home: Path,
    codex_bin: Path,
    prompt: str,
    case_rep: Path,
    timeout_min: int,
) -> list[str]:
    home = Path.home()
    uv_python = home / ".local/share/uv/python"
    args = [
        "bwrap",
        "--ro-bind",
        "/",
        "/",
        "--dev",
        "/dev",
        "--proc",
        "/proc",
        "--tmpfs",
        "/tmp",
        "--tmpfs",
        str(home),
    ]
    # Extra paths to hide from the agent, e.g. a data mount: BENCH_SANDBOX_HIDE=/mnt/data:/srv/x
    for hidden in filter(None, os.environ.get("BENCH_SANDBOX_HIDE", "").split(":")):
        args += ["--tmpfs", hidden]
    args += ["--ro-bind", str(codex_bin), str(codex_bin)]
    if uv_python.exists():
        args += ["--ro-bind", str(uv_python), str(uv_python)]
    # case_rep holds ws, codex-home and last_message.txt; all must be writable past the $HOME tmpfs.
    args += [
        "--bind",
        str(case_rep),
        str(case_rep),
        "--chdir",
        str(ws),
        "--unshare-all",
        "--share-net",
        "--die-with-parent",
        "--",
        "env",
        f"CODEX_HOME={codex_home}",
        f"UV_CACHE_DIR={ws}/.uv-cache",
        str(codex_bin),
        "exec",
        "--skip-git-repo-check",
        "--json",
        "-o",
        str(case_rep / "last_message.txt"),
        "-C",
        str(ws),
        prompt,
    ]
    return args


def run_codex_agent(
    ws: Path,
    case_rep: Path,
    prompt: str,
    alias: str,
    port: int,
    timeout_min: int,
) -> dict[str, Any]:
    codex_home = case_rep / "codex-home"
    if codex_home.exists():
        shutil.rmtree(codex_home)
    codex_home.mkdir(parents=True)
    cfg = f"""model = "{alias}"
model_provider = "llamacpp"
model_reasoning_effort = "medium"
approval_policy = "never"
sandbox_mode = "danger-full-access"
[model_providers.llamacpp]
name = "llama.cpp"
base_url = "http://127.0.0.1:{port}/v1"
wire_api = "responses"
"""
    (codex_home / "config.toml").write_text(cfg)

    codex_bin = Path(which("codex") or "")
    if not codex_bin.is_file():
        raise FileNotFoundError("codex binary not found on PATH")

    cmd = _codex_bwrap_cmd(ws, codex_home, codex_bin, prompt, case_rep, timeout_min)
    t0 = time.monotonic()
    timed_out = False
    exit_code = None
    with (
        (case_rep / "agent.jsonl").open("w") as out_jsonl,
        (case_rep / "agent.err").open("w") as err_f,
        open(os.devnull, "rb") as devnull,
    ):
        proc = subprocess.Popen(
            cmd,
            stdin=devnull,
            stdout=out_jsonl,
            stderr=err_f,
            start_new_session=True,
            text=False,
        )
        try:
            proc.wait(timeout=timeout_min * 60)
            exit_code = proc.returncode
        except subprocess.TimeoutExpired:
            timed_out = True
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                proc.kill()
            proc.wait(timeout=30)
            exit_code = -9

    wall_s = round(time.monotonic() - t0, 1)
    usage = _parse_agent_usage(case_rep / "agent.jsonl")
    last_message = ""
    lm = case_rep / "last_message.txt"
    if lm.is_file():
        last_message = lm.read_text(errors="replace")
    return {
        "wall_s": wall_s,
        "timed_out": timed_out,
        "exit_code": exit_code,
        "last_message": last_message,
        **usage,
    }


def run_cursor_agent(ws: Path, case_rep: Path, prompt: str, timeout_min: int) -> dict[str, Any]:
    agent_json = case_rep / "agent.json"
    cmd = [
        "cursor-agent",
        "-p",
        "--trust",
        "--force",
        "--model",
        CURSOR_MODEL,
        "--output-format",
        "json",
        "--workspace",
        str(ws),
        prompt,
    ]
    t0 = time.monotonic()
    timed_out = False
    try:
        proc = _run(cmd, timeout=timeout_min * 60)
        exit_code = proc.returncode
        agent_json.write_text(proc.stdout)
        (case_rep / "agent.err").write_text(proc.stderr)
    except subprocess.TimeoutExpired:
        timed_out = True
        exit_code = 124
        agent_json.write_text("")
        (case_rep / "agent.err").write_text("timed out")

    wall_s = round(time.monotonic() - t0, 1)
    last_message = ""
    if agent_json.is_file() and agent_json.stat().st_size:
        try:
            data = json.loads(agent_json.read_text())
            if isinstance(data, dict):
                last_message = str(data.get("result") or data.get("text") or "")
        except json.JSONDecodeError:
            last_message = agent_json.read_text(errors="replace")
    (case_rep / "last_message.txt").write_text(last_message)
    return {
        "wall_s": wall_s,
        "timed_out": timed_out,
        "exit_code": exit_code,
        "last_message": last_message,
        "tokens_in": None,
        "tokens_out": None,
        "tool_events": 0,
    }


def _write_grade(
    case_rep: Path, base_sha: str, case: Case, agent_meta: dict, grade_data: dict
) -> None:
    record = {
        **grade_data,
        "base_sha": base_sha,
        "wall_s": agent_meta.get("wall_s"),
        "timed_out": agent_meta.get("timed_out", False),
        "exit_code": agent_meta.get("exit_code"),
        "tokens_in": agent_meta.get("tokens_in"),
        "tokens_out": agent_meta.get("tokens_out"),
        "tool_events": agent_meta.get("tool_events", 0),
    }
    atomic_write_json(case_rep / "grade.json", record)


def _run_one_case_rep(
    run_dir: Path,
    agent: str,
    agent_label: str,
    case: Case,
    rep: int,
    *,
    timeout_min: int,
    server_port: int | None = None,
    server_alias: str | None = None,
) -> None:
    case_rep = _case_rep_dir(run_dir, agent_label, case.name, rep)
    grade_path = case_rep / "grade.json"
    if grade_path.is_file():
        return

    case_rep.mkdir(parents=True, exist_ok=True)
    _log_run(run_dir, f"start {agent_label} {case.name} rep {rep}")

    ws, base_sha = make_workspace(case, case.parent, case_rep)
    parent_tests = parent_test_files(case.parent)
    prompt = build_prompt(case)

    if agent == "parent":
        agent_meta = {
            "wall_s": 0.0,
            "timed_out": False,
            "exit_code": 0,
            "last_message": "",
            "tokens_in": None,
            "tokens_out": None,
            "tool_events": 0,
        }
    elif agent == "reference":
        apply_reference(ws, case.reference)
        agent_meta = {
            "wall_s": 0.0,
            "timed_out": False,
            "exit_code": 0,
            "last_message": "",
            "tokens_in": None,
            "tokens_out": None,
            "tool_events": 0,
        }
    elif agent == "codex":
        if server_port is None or server_alias is None:
            raise RuntimeError("codex requires llama-server")
        agent_meta = run_codex_agent(ws, case_rep, prompt, server_alias, server_port, timeout_min)
    elif agent == "cursor":
        agent_meta = run_cursor_agent(ws, case_rep, prompt, timeout_min)
    else:
        raise ValueError(f"unknown agent {agent}")

    last_message = agent_meta.get("last_message") or ""
    g = grade(ws, base_sha, case, parent_tests, last_message)
    _write_grade(case_rep, base_sha, case, agent_meta, g)
    _log_run(run_dir, f"done {agent_label} {case.name} rep {rep} total={g['total']:.3f}")


def _load_tuned_server(slug: str, manifest_row: dict[str, Any]) -> tuple[Any, dict]:
    tuned_path = STAGE2_RESULTS / slug / "tuned.json"
    tuned = json.loads(tuned_path.read_text())
    server_dict = {**tuned["server"], "slug": slug, "ctx": 131072}
    cfg = server_config_from_dict(server_dict, gguf=gguf_path(manifest_row))
    return cfg, tuned


def cmd_briefs(
    run_id: str,
    agent: str,
    *,
    models: str = "",
    cases_filter: list[str] | None = None,
    reps: int = 2,
    timeout_min: int = 60,
) -> None:
    run_dir = RESULTS / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    all_cases = load_cases()
    case_names = cases_filter if cases_filter else sorted(all_cases.keys())

    if agent == "codex":
        if not models.strip():
            raise SystemExit("--models required for codex")
        slugs = [s.strip() for s in models.split(",") if s.strip()]
    elif agent == "cursor":
        slugs = [CURSOR_MODEL]
    elif agent in ("reference", "parent"):
        slugs = [agent]
    else:
        raise SystemExit(f"unknown agent {agent}")

    manifest_by_slug = {m["slug"]: m for m in load_manifest(PROJECT_ROOT / "models.tsv")}

    for slug in slugs:
        if agent == "codex":
            _wait_for_free_vram(run_dir, slug)
            row = manifest_by_slug.get(slug)
            if not row:
                raise SystemExit(f"unknown model slug {slug}")
            cfg, tuned = _load_tuned_server(slug, row)
            model_run_dir = run_dir / slug
            model_run_dir.mkdir(parents=True, exist_ok=True)
            atomic_write_json(model_run_dir / "tuned.json", tuned)
            with LlamaServer(cfg, model_run_dir, tag="briefs") as srv:
                for case_name in case_names:
                    case = all_cases[case_name]
                    for rep in range(1, reps + 1):
                        _run_one_case_rep(
                            run_dir,
                            agent,
                            slug,
                            case,
                            rep,
                            timeout_min=timeout_min,
                            server_port=int(srv.port),
                            server_alias=cfg.alias,
                        )
        else:
            label = CURSOR_MODEL if agent == "cursor" else agent
            for case_name in case_names:
                case = all_cases[case_name]
                for rep in range(1, reps + 1):
                    _run_one_case_rep(
                        run_dir,
                        agent,
                        label,
                        case,
                        rep,
                        timeout_min=timeout_min,
                    )
