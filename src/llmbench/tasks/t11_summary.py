"""Incident report summarisation with fact coverage and word limit."""

from __future__ import annotations

import json
import re

from llmbench.core import PROJECT_ROOT, Chat, Result
from llmbench.summary_gen import incident_report

ID = "summary"
TITLE = "Document summary"
TESTS = "Cover 10 key facts from a long incident report within 200 words"
CATEGORY = "docs"

FIXTURE = PROJECT_ROOT / "fixtures" / "summary_incident.json"
MAX_WORDS = 200
HARD_CAP = 260


def _word_count(text: str) -> int:
    return len(re.findall(r"\S+", text.strip()))


def _fact_hits(text: str, patterns: list[str]) -> bool:
    hay = text.casefold()
    for p in patterns:
        if re.search(p, hay, re.IGNORECASE):
            return True
    return False


def run(model: str, calibration: bool = False) -> Result:
    _ = calibration
    spec = json.loads(FIXTURE.read_text())
    chat = Chat(model)
    report = incident_report()
    prompt = (
        f"Summarise the incident report below in at most {MAX_WORDS} words. "
        "Cover the timeline, impact, root cause, and remediation.\n\n"
        f"{report}"
    )
    summary = chat.ask(prompt)
    words = _word_count(summary)
    if words > HARD_CAP:
        return chat.result(False, 0.0, f"over word cap ({words}>{HARD_CAP})", summary)

    hits = sum(1 for f in spec["facts"] if _fact_hits(summary, f["patterns"]))
    score = hits / len(spec["facts"])
    return chat.result(
        hits == len(spec["facts"]) and words <= MAX_WORDS,
        score,
        f"{hits}/{len(spec['facts'])} facts, {words} words",
        summary,
    )
