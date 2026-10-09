"""Multi-step agent fixing planted bugs in small Python repos."""

from __future__ import annotations

import json
import re
import shutil
import tempfile
from pathlib import Path

from llmbench.core import PROJECT_ROOT, Chat, Result, call_args, sandbox_run

ID = "agent_repo"
TITLE = "Agent repo repair"
TESTS = "Tool loop over pytest projects with 1–3 planted bugs; graded by tests passing"
CATEGORY = "agentic"

REPOS = PROJECT_ROOT / "fixtures" / "agent_repos"
MAX_STEPS = 25

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "list_dir",
            "description": "List directory entries",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a file",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write entire file content",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "replace_in_file",
            "description": "Replace first occurrence of old with new in file",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "old": {"type": "string"},
                    "new": {"type": "string"},
                },
                "required": ["path", "old", "new"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_tests",
            "description": "Run pytest in the repo sandbox",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]

PROMPT = """You are fixing a broken Python package. Use tools to explore, edit source files \
(not tests/), and run_tests until pytest passes. Reply DONE when all tests pass."""


def _tool(root: Path, name: str, args: dict) -> str:
    try:
        if name == "run_tests":
            proc = sandbox_run(
                [
                    "uv",
                    "run",
                    "pytest",
                    "-q",
                    "-p",
                    "no:cacheprovider",
                ],
                root,
                timeout=120,
                env={"PYTHONDONTWRITEBYTECODE": "1"},
            )
            out = (proc.stdout + proc.stderr).splitlines()[-60:]
            return "\n".join(out) or f"exit {proc.returncode}"
        rel = str(args.get("path", "."))
        target = (root / rel).resolve()
        if not target.is_relative_to(root):
            return "error: path outside repo"
        if name == "list_dir":
            return "\n".join(sorted(p.name + ("/" if p.is_dir() else "") for p in target.iterdir()))
        if name == "read_file":
            return target.read_text()
        if name == "write_file":
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(str(args["content"]))
            return "ok"
        if name == "replace_in_file":
            text = target.read_text()
            old, new = str(args["old"]), str(args["new"])
            if old not in text:
                return "error: old string not found"
            target.write_text(text.replace(old, new, 1))
            return "ok"
        return f"error: unknown tool {name}"
    except (OSError, KeyError) as e:
        return f"error: {e}"


def _pytest_env() -> dict[str, str]:
    return {"PYTHONDONTWRITEBYTECODE": "1"}


def _pytest_cmd() -> list[str]:
    return ["uv", "run", "pytest", "-q", "-p", "no:cacheprovider"]


def _snapshot_tests(root: Path) -> dict[str, bytes]:
    out: dict[str, bytes] = {}
    tests = root / "tests"
    if not tests.is_dir():
        return out
    for p in tests.rglob("*"):
        if not p.is_file():
            continue
        if "__pycache__" in p.parts or p.suffix == ".pyc":
            continue
        out[str(p.relative_to(root))] = p.read_bytes()
    return out


def _tests_pass(root: Path) -> tuple[float, str]:
    proc = sandbox_run(_pytest_cmd(), root, timeout=120, env=_pytest_env())
    out = proc.stdout + proc.stderr
    if proc.returncode == 0:
        return 1.0, out[-2000:]
    m = re.search(r"(\d+) passed", out)
    passed = int(m.group(1)) if m else 0
    failed_m = re.search(r"(\d+) failed", out)
    failed = int(failed_m.group(1)) if failed_m else 0
    tests = passed + failed or max(passed, 1)
    return passed / tests, out[-2000:]


def _tests_touched(root: Path, before: dict[str, bytes]) -> bool:
    after = _snapshot_tests(root)
    for rel, data in before.items():
        if after.get(rel) != data:
            return True
    for rel in after:
        if rel not in before:
            return True
    return False


def _run_repo(chat: Chat, root: Path) -> tuple[float, str]:
    before = _snapshot_tests(root)
    chat.messages.append({"role": "user", "content": PROMPT})
    transcript: list[str] = []
    for step in range(MAX_STEPS):
        msg = chat.send(tools=TOOLS)
        tcs = msg.get("tool_calls") or []
        if not tcs:
            if "done" in (msg.get("content") or "").casefold():
                break
            continue
        for tc in tcs:
            fn = tc["function"]
            args = call_args(tc)
            transcript.append(f"{fn['name']}({json.dumps(args)[:200]})")
            chat.tool_result(tc.get("id") or fn["name"], fn["name"], _tool(root, fn["name"], args))
    if _tests_touched(root, before):
        return 0.0, "modified tests/ — score 0\n" + "\n".join(transcript)
    score, out = _tests_pass(root)
    return score, out + "\n" + "\n".join(transcript)


def run(model: str, calibration: bool = False) -> Result:
    chat = Chat(model)
    levels = ("easy",) if calibration else ("easy", "medium", "hard")
    scores: list[float] = []
    logs: list[str] = []

    for level in levels:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shutil.copytree(REPOS / level, root, dirs_exist_ok=True)
            score, log = _run_repo(chat, root)
            scores.append(score)
            logs.append(f"=== {level} score={score:.2f} ===\n{log}")

    mean = sum(scores) / len(scores) if scores else 0.0
    return chat.result(mean == 1.0, mean, f"mean repo score {mean:.2f}", "\n\n".join(logs))
