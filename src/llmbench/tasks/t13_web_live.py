"""Live HTTPS fetch QA on stable public facts."""

from __future__ import annotations

import json

import httpx

from llmbench.core import PROJECT_ROOT, Chat, Result, call_args, extract_json, merged_result
from llmbench.tasks.t12_web_local import _answers_match
from llmbench.web_fetch import fetch_live

ID = "web_live"
TITLE = "Web fetch (live)"
TESTS = "Stable public facts via HTTPS; skipped if network down"
CATEGORY = "web_live"

FIXTURE = PROJECT_ROOT / "fixtures" / "web_live.json"
MAX_FETCHES = 8


def run(model: str, calibration: bool = False) -> Result:
    _ = calibration
    cases = json.loads(FIXTURE.read_text())
    chats: list[Chat] = []
    logs: list[str] = []
    correct = 0
    try:
        with httpx.Client(follow_redirects=True, timeout=15.0) as client:
            client.get("https://www.example.com")
    except httpx.HTTPError:
        return Chat(model).result(
            True,
            0.0,
            "skipped (network down)",
            "network unavailable",
            skipped=True,
            nondeterministic=True,
        )

    def fetch_url(url: str, client: httpx.Client, counter: list[int]) -> str:
        if counter[0] >= MAX_FETCHES:
            return json.dumps({"error": "fetch limit"})
        counter[0] += 1
        try:
            return json.dumps(fetch_live(url, client))
        except httpx.HTTPError as e:
            return json.dumps({"error": str(e)})

    tools = [
        {
            "type": "function",
            "function": {
                "name": "fetch_url",
                "description": "Fetch HTTPS page (title, text, links)",
                "parameters": {
                    "type": "object",
                    "properties": {"url": {"type": "string"}},
                    "required": ["url"],
                },
            },
        }
    ]

    with httpx.Client(follow_redirects=True, timeout=15.0) as client:
        for i, case in enumerate(cases):
            counter = [0]
            chat = Chat(model)  # questions are independent
            chats.append(chat)
            chat.messages.append(
                {
                    "role": "user",
                    "content": f"{case['question']} Hint: {case.get('url_hint', '')}",
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
                        fetch_url(str(args.get("url", case.get("url_hint", ""))), client, counter),
                    )
            try:
                ans = extract_json(final)
            except ValueError:
                ans = {}
            accepted = case.get("accepted") or [case["expected"]]
            ok = any(_answers_match(a, ans) for a in accepted)
            correct += int(ok)
            logs.append(f"q{i + 1}: {'ok' if ok else 'fail'} got {ans} | {final[:300]!r}")

    score = correct / len(cases) if cases else 0.0
    if not chats:
        chats.append(Chat(model))
    return merged_result(
        chats,
        correct == len(cases),
        score,
        f"{correct}/{len(cases)} correct",
        "\n".join(logs),
        nondeterministic=True,
    )
