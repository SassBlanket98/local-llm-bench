"""Verifiable constraint checkers for IFEval-style prompts."""

from __future__ import annotations

import json
import re
from collections.abc import Callable

Checker = Callable[[str, dict], bool]


def _word_count(text: str) -> int:
    return len(re.findall(r"\S+", text.strip()))


def check_word_count_range(text: str, spec: dict) -> bool:
    n = _word_count(text)
    return int(spec["min"]) <= n <= int(spec["max"])


def check_bullet_count(text: str, spec: dict) -> bool:
    bullets = re.findall(r"(?m)^\s*[-*•]\s+\S", text)
    need = int(spec["count"])
    return len(bullets) == need


def check_all_lowercase(text: str, _spec: dict) -> bool:
    letters = [c for c in text if c.isalpha()]
    return bool(letters) and all(c.islower() for c in letters)


def check_must_include_keywords(text: str, spec: dict) -> bool:
    hay = text.casefold()
    return all(kw.casefold() in hay for kw in spec["keywords"])


def check_forbidden_words(text: str, spec: dict) -> bool:
    hay = text.casefold()
    return not any(w.casefold() in hay for w in spec["words"])


def check_json_only(text: str, spec: dict) -> bool:
    stripped = text.strip()
    try:
        obj = json.loads(stripped)
    except json.JSONDecodeError:
        return False
    if spec.get("keys"):
        return isinstance(obj, dict) and set(spec["keys"]).issubset(obj)
    return True


def check_section_headers(text: str, spec: dict) -> bool:
    for h in spec["headers"]:
        if h not in text:
            return False
    return True


def check_ends_with_phrase(text: str, spec: dict) -> bool:
    phrase = spec["phrase"]
    return text.strip().casefold().endswith(phrase.casefold())


CHECKERS: dict[str, Checker] = {
    "word_count_range": check_word_count_range,
    "bullet_count": check_bullet_count,
    "all_lowercase": check_all_lowercase,
    "must_include_keywords": check_must_include_keywords,
    "forbidden_words": check_forbidden_words,
    "json_only": check_json_only,
    "section_headers": check_section_headers,
    "ends_with_phrase": check_ends_with_phrase,
}


def check_constraints(text: str, constraints: list[dict]) -> tuple[int, int]:
    ok = 0
    for c in constraints:
        fn = CHECKERS[c["type"]]
        if fn(text, c):
            ok += 1
    return ok, len(constraints)
