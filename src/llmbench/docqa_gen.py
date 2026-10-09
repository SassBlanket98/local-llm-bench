"""Seeded synthetic handbook generator for doc QA tasks."""

from __future__ import annotations

import random
import re
from typing import Any

SEED = 42

FACTS = [
    ("employee_id_format", "EMP-{4 digits}", "EMP-####"),
    ("vacation_days", "20", "25"),
    ("remote_days_per_week", "2", "3"),
    ("support_email", "help@acme.internal", "care@acme.internal"),
    ("office_city", "Portland", "Seattle"),
    ("expense_limit_usd", "500", "750"),
    ("badge_color", "blue", "green"),
    ("oncall_rotation_weeks", "1", "2"),
    ("training_budget_usd", "1200", "1500"),
    ("security_patch_sla_days", "14", "7"),
    ("parking_lot", "North", "South"),
    ("holiday_bonus_pct", "3", "5"),
]


def _filler_para(rng: random.Random, tag: int) -> str:
    return (
        "This paragraph repeats operational guidance for archival completeness. "
        f"Teams should cross-check the handbook index before filing tickets. "
        f"Reference tag {tag}-{rng.randint(1000, 9999)}.\n\n"
    )


def _distribute_filler(rng: random.Random, count: int, slots: int, base_tag: int) -> list[str]:
    """Split count filler paragraphs across slots (at least one per slot when count >= slots)."""
    if count <= 0:
        return [""] * slots
    per = count // slots
    extra = count % slots
    out: list[str] = []
    for i in range(slots):
        n = per + (1 if i < extra else 0)
        out.append("".join(_filler_para(rng, base_tag + i * 17 + j) for j in range(n)))
    return out


def _build_handbook(target_tokens: int, extra_paragraphs: int) -> tuple[str, dict[str, str]]:
    """Build one handbook candidate; RNG is fixed from target so probes are deterministic."""
    rng = random.Random(SEED + target_tokens)
    latest: dict[str, str] = {}
    n_first = int(extra_paragraphs * 0.7)
    n_last = extra_paragraphs - n_first
    first_fill = _distribute_filler(rng, n_first, len(FACTS), 100)
    last_fill = _distribute_filler(rng, n_last, len(FACTS), 900)

    parts: list[str] = ["# Acme Corp Employee Handbook (2026 edition)\n\n"]
    for i, (key, old, _new) in enumerate(FACTS):
        parts.append(f"## {key.replace('_', ' ').title()}\n")
        parts.append(f"Original policy: {old}.\n\n")
        parts.append(first_fill[i])
        latest[key] = old

    parts.append("\n# Updated policies (effective Q2 2026)\n\n")
    for i, (key, old, new) in enumerate(FACTS):
        parts.append(f"## {key.replace('_', ' ').title()} (revised)\n")
        parts.append(f"The current value is {new}. (Previously {old}.)\n\n")
        parts.append(last_fill[i])
        latest[key] = new

    return "".join(parts), latest


def handbook_for_target_tokens(target_tokens: int, tokenize_fn) -> tuple[str, dict[str, str]]:
    """Build handbook; tokenize_fn(text)->token count via server /tokenize."""
    lo, hi = 0, 200_000
    best_text = ""
    best_latest: dict[str, str] = {}

    while lo <= hi:
        mid = (lo + hi) // 2
        candidate, latest = _build_handbook(target_tokens, mid)
        n = tokenize_fn(candidate)
        if n <= target_tokens:
            best_text, best_latest = candidate, latest
            lo = mid + 1
        else:
            hi = mid - 1

    if not best_text:
        best_text, best_latest = _build_handbook(target_tokens, 0)
    return best_text, best_latest


def normalize_answer(text: str) -> str:
    t = text.strip().casefold()
    t = re.sub(r"\s+", " ", t)
    t = re.sub(r"[.,;:!?\"']", "", t)
    return t


def questions(latest: dict[str, str]) -> list[dict[str, Any]]:
    """Six questions per handbook: 3 lookup, 2 multi-fact, 1 latest wins."""
    return [
        {
            "q": "What is the current support contact email?",
            "expected": latest["support_email"],
            "kind": "lookup",
        },
        {
            "q": "How many vacation days are currently allowed?",
            "expected": latest["vacation_days"],
            "kind": "lookup",
        },
        {
            "q": "What color are employee badges now?",
            "expected": latest["badge_color"],
            "kind": "lookup",
        },
        {
            "q": "Give office city and remote days per week (format: city, N).",
            "expected": f"{latest['office_city']}, {latest['remote_days_per_week']}",
            "kind": "multi",
        },
        {
            "q": "Give expense limit USD and training budget USD separated by a slash.",
            "expected": f"{latest['expense_limit_usd']}/{latest['training_budget_usd']}",
            "kind": "multi",
        },
        {
            "q": "What is the security patch SLA in days under the latest policy?",
            "expected": latest["security_patch_sla_days"],
            "kind": "latest",
        },
    ]
