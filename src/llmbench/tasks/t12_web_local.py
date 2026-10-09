"""Multi-hop QA over a local static HTML fixture site."""

from __future__ import annotations

import json
import socket
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from llmbench.core import PROJECT_ROOT, Chat, Result, call_args, extract_json
from llmbench.web_fetch import fetch_local

ID = "web_local"
TITLE = "Web fetch (local)"
TESTS = "Multi-hop navigation on fixture site; JSON answers graded exactly"
CATEGORY = "web"

FIXTURE = PROJECT_ROOT / "fixtures" / "web_local.json"
SITE = PROJECT_ROOT / "fixtures" / "site"
MAX_FETCHES = 12


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _load_pages() -> dict[str, str]:
    pages: dict[str, str] = {}
    for p in SITE.rglob("*.html"):
        rel = "/" + str(p.relative_to(SITE)).replace("\\", "/")
        if rel.endswith("/index.html"):
            rel = rel[: -len("index.html")] or "/"
        pages[rel] = p.read_text()
    return pages


def _norm_scalar(v: Any) -> Any:
    if isinstance(v, str):
        return v.strip().casefold()
    if isinstance(v, bool):
        return v
    if isinstance(v, int):
        return v
    if isinstance(v, float):
        return int(v) if v.is_integer() else v
    return v


def _answers_match(expected: dict[str, Any], actual: Any) -> bool:
    if not isinstance(actual, dict):
        return False
    for key, exp_val in expected.items():
        if key not in actual:
            return False
        if _norm_scalar(actual[key]) != _norm_scalar(exp_val):
            return False
    return True


def _run_question(
    model: str,
    case: dict[str, Any],
    base: str,
    fetch_url,
    tools: list[dict],
) -> tuple[bool, str, str]:
    chat = Chat(model)
    chat.messages.append(
        {
            "role": "user",
            "content": f"{case['question']} Start from {base}/index.html if needed.",
        }
    )
    final = ""
    for _ in range(MAX_FETCHES + 2):
        msg = chat.send(tools=tools, tool_choice="auto")
        tcs = msg.get("tool_calls") or []
        if not tcs:
            final = msg.get("content") or ""
            break
        for tc in tcs:
            args = call_args(tc)
            chat.tool_result(
                tc.get("id") or "fetch",
                "fetch_url",
                fetch_url(str(args.get("url", base))),
            )
    try:
        ans = extract_json(final)
    except ValueError:
        ans = None
    ok = _answers_match(case["expected"], ans)
    preview = final[:500]
    return ok, preview, f"got {ans!r}"


def run(model: str, calibration: bool = False) -> Result:
    _ = calibration
    cases = json.loads(FIXTURE.read_text())
    pages = _load_pages()
    port = _free_port()
    base = f"http://127.0.0.1:{port}"
    handler = partial(SimpleHTTPRequestHandler, directory=str(SITE))
    httpd = ThreadingHTTPServer(("127.0.0.1", port), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()

    def make_fetch():
        fetches = 0

        def fetch_url(url: str) -> str:
            nonlocal fetches
            if fetches >= MAX_FETCHES:
                return json.dumps({"error": "fetch limit reached"})
            fetches += 1
            return json.dumps(fetch_local(url, base, pages))

        return fetch_url

    tools = [
        {
            "type": "function",
            "function": {
                "name": "fetch_url",
                "description": "Fetch page title, visible text and links",
                "parameters": {
                    "type": "object",
                    "properties": {"url": {"type": "string"}},
                    "required": ["url"],
                },
            },
        }
    ]

    correct = 0
    logs: list[str] = []

    for i, case in enumerate(cases):
        ok, preview, detail = _run_question(model, case, base, make_fetch(), tools)
        correct += int(ok)
        logs.append(f"q{i + 1}: {'ok' if ok else 'fail'} {detail}\nmodel_text[:500]={preview!r}")

    httpd.shutdown()
    score = correct / len(cases) if cases else 0.0
    # Transcript for suite is written from chat registry; attach grade summary in output.
    return Result(
        passed=correct == len(cases),
        score=round(score, 3),
        notes=f"{correct}/{len(cases)} correct",
        output="\n".join(logs),
    )
