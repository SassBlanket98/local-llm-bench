"""Long-document QA at ~8k, ~16k and ~30k tokens."""

from __future__ import annotations

import httpx

from llmbench import core
from llmbench.core import CONFIG, Chat, Result
from llmbench.docqa_gen import handbook_for_target_tokens, normalize_answer, questions

ID = "docqa"
TITLE = "Document QA"
TESTS = "Planted facts in synthetic handbook; lookup, multi-fact and latest-value questions"
CATEGORY = "docs"

TARGETS = (8000, 16000, 24000)


def _tokenize(text: str) -> int:
    base = str(CONFIG["base_url"])
    with httpx.Client(base_url=base, timeout=60.0) as client:
        r = client.post("/tokenize", json={"content": text})
        r.raise_for_status()
        data = r.json()
        if "tokens" in data:
            return len(data["tokens"])
        return int(data.get("n_tokens") or data.get("count") or 0)


def _lengths(calibration: bool) -> tuple[int, ...]:
    return (8000,) if calibration else TARGETS


def run(model: str, calibration: bool = False) -> Result:
    correct = 0
    total = 0
    log: list[str] = []
    eval_tokens = 0
    eval_seconds = 0.0
    t0 = __import__("time").monotonic()

    for target in _lengths(calibration):
        doc, latest = handbook_for_target_tokens(target, _tokenize)
        qs = questions(latest)
        for item in qs:
            total += 1
            chat = Chat(model)
            prompt = (
                "Read the handbook below and answer with ONLY the exact answer, no explanation.\n\n"
                f"Question: {item['q']}\n\n--- HANDBOOK ---\n{doc}"
            )
            prev_max = core.CONFIG.get("max_tokens", 8192)
            core.CONFIG["max_tokens"] = 256
            try:
                ans = chat.ask(prompt)
            finally:
                core.CONFIG["max_tokens"] = prev_max
            eval_tokens += chat.eval_tokens
            eval_seconds += chat.eval_seconds
            chat.close()
            ok = normalize_answer(ans) == normalize_answer(item["expected"])
            correct += int(ok)
            log.append(f"{target} tok {item['kind']}: {'ok' if ok else 'fail'} (got {ans!r})")

    score = correct / total if total else 0.0
    return Result(
        passed=correct == total,
        score=round(score, 3),
        notes=f"{correct}/{total} correct",
        output="\n".join(log),
        seconds=round(__import__("time").monotonic() - t0, 1),
        eval_tokens=eval_tokens,
        eval_seconds=eval_seconds,
    )
