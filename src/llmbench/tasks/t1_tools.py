"""Multi-step tool use: explore a config repo with tools, respect overrides, ignore decoys."""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

from llmbench.core import Chat, Grade, Result, call_args, extract_json, graded_run

ID = "tools"
TITLE = "Agentic tool use"
TESTS = "Drives list/read/search tools over several turns, follows an override rule, skips decoys"
CATEGORY = "agentic"

FILES = {
    "services/api.yaml": "name: api\nlisten:\n  host: 0.0.0.0\n  port: 8080\nlimits:\n  max_connections: 500\n",
    "services/billing.yaml": "name: billing\nlisten:\n  host: 0.0.0.0\n  port: 8443\nlimits:\n  max_connections: 100\n",
    "services/metrics.yaml": "name: metrics\nlisten:\n  host: 127.0.0.1\n  port: 9090\nlimits:\n  max_connections: 50\n",
    "services/legacy-billing.yaml.disabled": "name: legacy-billing\nlisten:\n  port: 8443\nlimits:\n  max_connections: 40\n",
    "overrides/README.md": "Files here are merged over services/<name>.yaml at deploy time.\nA key in <name>.local.yaml always wins over the base file.\n",
    "overrides/api.local.yaml": "limits:\n  max_connections: 800\n",
    "overrides/billing.local.yaml": "limits:\n  max_connections: 250\n",
    "docs/ports.md": "# Port map (last updated 2023)\n\n- billing: 8443, max 64 connections\n- api: 8080\n",
}

PROMPT = """You are working in a repository of service deployment configs. Use the tools to \
investigate; do not guess.

Question: which service is configured to listen on port 8443, and what is its effective \
max_connections once overrides are applied? Ignore disabled files.

When you are done, reply with only JSON: {"service": "<name>", "max_connections": <int>}"""

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "list_dir",
            "description": "List entries in a directory (relative path, '.' for root).",
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
            "description": "Read a text file (relative path).",
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
            "name": "search",
            "description": "Search all files for a literal string; returns path:line:text matches.",
            "parameters": {
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
        },
    },
]

MAX_TURNS = 15
JSON_FB = "Your reply was not valid JSON. Reply again with only the JSON object described above."


def _tool(root: Path, name: str, args: dict) -> str:
    try:
        if name == "search":
            out = subprocess.run(
                ["grep", "-rnF", "--", str(args["text"]), "."],
                cwd=root,
                capture_output=True,
                text=True,
                check=False,
            ).stdout
            return out.strip() or "(no matches)"
        target = (root / str(args.get("path", "."))).resolve()
        if not target.is_relative_to(root):
            return "error: path outside repo"
        if name == "list_dir":
            return "\n".join(sorted(p.name + ("/" if p.is_dir() else "") for p in target.iterdir()))
        if name == "read_file":
            return target.read_text()
        return f"error: unknown tool {name}"
    except (OSError, KeyError) as e:
        return f"error: {e}"


def run(model: str, calibration: bool = False) -> Result:
    _ = calibration
    with tempfile.TemporaryDirectory() as d:
        root = Path(d).resolve()
        for rel, text in FILES.items():
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            (root / rel).write_text(text)

        chat = Chat(model)
        calls: list[str] = []

        def respond(prompt: str) -> str:
            """Send a user turn, then service tool calls until the model answers in text."""
            chat.messages.append({"role": "user", "content": prompt})
            for _ in range(MAX_TURNS):
                msg = chat.send(tools=TOOLS)
                tcs = msg.get("tool_calls") or []
                if not tcs:
                    return msg.get("content", "")
                for tc in tcs:
                    fn = tc["function"]
                    args = call_args(tc)
                    calls.append(f"{fn['name']}({json.dumps(args)})")
                    chat.tool_result(
                        tc.get("id") or fn.get("name", "call"),
                        fn["name"],
                        _tool(root, fn["name"], args),
                    )
            return ""

        def grade(final: str) -> Grade:
            output = f"{final}\n\n--- tool calls so far ---\n" + "\n".join(calls)
            try:
                ans = extract_json(final)
                svc_ok = str(ans.get("service", "")).lower() == "billing"
                mc_ok = int(ans.get("max_connections", -1)) == 250
            except (ValueError, TypeError, AttributeError):
                return Grade(False, 0, "final answer not valid JSON", output, JSON_FB)
            if not calls:
                return Grade(False, 0, "answered without using any tools", output)
            notes = (
                f"{len(calls)} tool calls; service {'ok' if svc_ok else 'WRONG'}; "
                f"max_connections {ans.get('max_connections')} "
                f"({'ok' if mc_ok else 'expected 250'})"
            )
            return Grade(svc_ok and mc_ok, 0.5 * svc_ok + 0.5 * mc_ok, notes, output)

        return graded_run(chat, PROMPT, grade, respond)
