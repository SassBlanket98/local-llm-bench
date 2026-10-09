"""BFCL-style single-turn tool calling."""

from __future__ import annotations

import json

from llmbench.core import PROJECT_ROOT, Chat, Result, merged_result
from llmbench.toolcall_match import grade_case_detail

ID = "toolcall"
TITLE = "Tool calling (BFCL-style)"
TESTS = "Simple, multi-choice, parallel, irrelevance and typed argument cases"
CATEGORY = "tool_calling"

FIXTURE = PROJECT_ROOT / "fixtures" / "toolcall.json"


def _cases(calibration: bool) -> list[dict]:
    cases = json.loads(FIXTURE.read_text())
    return cases[:10] if calibration else cases


def run(model: str, calibration: bool = False) -> Result:
    cases = _cases(calibration)
    passed = 0
    lines: list[str] = []
    chats: list[Chat] = []

    for i, case in enumerate(cases):
        # Cases are independent; a shared history would leave unanswered tool calls behind.
        chat = Chat(model)
        chats.append(chat)
        chat.messages.append({"role": "user", "content": case["prompt"]})
        msg = chat.send(tools=case["tools"], tool_choice="auto")
        ok, reason = grade_case_detail(case, msg)
        passed += int(ok)
        line = f"case {i + 1} ({case['kind']}): {'PASS' if ok else 'FAIL'}"
        if not ok:
            line += f" — {reason}"
        lines.append(line)

    score = passed / len(cases) if cases else 0.0
    return merged_result(
        chats,
        passed == len(cases),
        score,
        f"{passed}/{len(cases)} cases passed",
        "\n".join(lines),
    )
