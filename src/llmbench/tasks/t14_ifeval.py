"""IFEval-style verifiable instruction constraints."""

from __future__ import annotations

import json

from llmbench.core import PROJECT_ROOT, Chat, Result, merged_result
from llmbench.ifeval_checks import check_constraints

ID = "ifeval"
TITLE = "Instruction following"
TESTS = "Verifiable format, length, casing, keyword and JSON constraints"
CATEGORY = "instruction_following"

FIXTURE = PROJECT_ROOT / "fixtures" / "ifeval.json"


def _prompts(calibration: bool) -> list[dict]:
    items = json.loads(FIXTURE.read_text())
    return items[:8] if calibration else items


def run(model: str, calibration: bool = False) -> Result:
    items = _prompts(calibration)
    chats: list[Chat] = []
    ok_total = 0
    constraint_total = 0
    notes: list[str] = []

    for i, item in enumerate(items):
        # Each item tests its own constraints; earlier prompts must not leak in.
        chat = Chat(model)
        chats.append(chat)
        text = chat.ask(item["prompt"])
        ok, total = check_constraints(text, item["constraints"])
        ok_total += ok
        constraint_total += total
        notes.append(f"prompt {i + 1}: {ok}/{total} constraints")

    score = ok_total / constraint_total if constraint_total else 0.0
    return merged_result(
        chats,
        score == 1.0,
        score,
        f"{ok_total}/{constraint_total} constraints satisfied",
        "\n".join(notes),
    )
