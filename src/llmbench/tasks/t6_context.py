"""Long-context code reasoning: trace a value across 4 files hidden in a ~20K-token codebase."""

from __future__ import annotations

import random

from llmbench.core import Chat, Grade, Result, extract_json, graded_run

ID = "context"
TITLE = "Long-context code tracing"
TESTS = "Follows imports across a ~20K-token codebase, dodges a decoy constant, does the maths"
CATEGORY = "docs"

# Answer: backoff_delay(3) = min(1.5 * 3**3, 20) = 20, then x SYNC_DELAY_SCALE 2 = 40.
# Decoy factor 2 gives 24; forgetting the cap gives 81; forgetting the scale gives 20.
NEEDLES = {
    "app/config/retry.py": '''\
"""Retry timing defaults shared by all network clients."""

BASE_DELAY_S = 1.5
MAX_DELAY_S = 20
MAX_ATTEMPTS = 6
''',
    "app/config/tuning.py": '''\
"""Tunables loaded at import time. Changing these requires a restart."""

BACKOFF_FACTOR = 3
POOL_SIZE = 16
''',
    "app/legacy/tuning_old.py": '''\
"""DEPRECATED: pre-2025 tunables, kept for the migration script only. Not imported anywhere."""

BACKOFF_FACTOR = 2
MAX_DELAY_S = 60
''',
    "app/net/backoff.py": '''\
"""Exponential backoff helper."""

from app.config.retry import BASE_DELAY_S, MAX_DELAY_S
from app.config.tuning import BACKOFF_FACTOR


def backoff_delay(attempt: int) -> float:
    """Delay before the next try, given a zero-based attempt index."""
    return min(BASE_DELAY_S * (BACKOFF_FACTOR ** attempt), MAX_DELAY_S)
''',
    "app/workers/constants.py": '''\
"""Worker-level constants."""

SYNC_DELAY_SCALE = 2
SYNC_BATCH = 200
''',
    "app/workers/sync_worker.py": '''\
"""Pulls remote changes and applies them locally."""

import time

from app.config.retry import MAX_ATTEMPTS
from app.net.backoff import backoff_delay
from app.workers.constants import SYNC_DELAY_SCALE


def run_sync(client, store) -> None:
    for attempt in range(MAX_ATTEMPTS):  # attempt is zero-based
        try:
            store.apply(client.pull())
            return
        except ConnectionError:
            time.sleep(backoff_delay(attempt) * SYNC_DELAY_SCALE)
    raise RuntimeError("sync failed")
''',
}

PROMPT = """Below is a Python codebase. Question: when `run_sync` in \
app/workers/sync_worker.py fails on attempt index 3 (zero-based), exactly how many seconds \
does it sleep before the next try? Trace every constant to where it is actually defined and \
imported.

Reply with only JSON: {"seconds": <number>, "files": ["<paths you used>"]}

"""

WORDS = [
    "invoice",
    "order",
    "user",
    "cart",
    "report",
    "cache",
    "token",
    "session",
    "ledger",
    "audit",
    "export",
    "import",
    "shipment",
    "payment",
    "refund",
    "coupon",
    "profile",
    "webhook",
    "metric",
    "queue",
    "schedule",
]
VERBS = [
    "load",
    "save",
    "build",
    "parse",
    "render",
    "validate",
    "merge",
    "sync",
    "fetch",
    "compute",
    "format",
    "resolve",
]


def _filler(rnd: random.Random, path: str) -> str:
    noun = path.rsplit("/", 1)[1].removesuffix(".py")
    out = [f'"""Helpers for {noun} handling."""', "", "from __future__ import annotations", ""]
    for _ in range(rnd.randint(5, 8)):
        verb, obj = rnd.choice(VERBS), rnd.choice(WORDS)
        n = rnd.randint(2, 40)
        out += [
            "",
            f"def {verb}_{obj}(items: list[dict], limit: int = {n}) -> list[dict]:",
            f'    """{verb.capitalize()} {obj} records, at most {n} at a time."""',
            "    result = []",
            "    for item in items[:limit]:",
            f'        if item.get("{obj}_id") is None:',
            "            continue",
            f'        item["{rnd.choice(WORDS)}_ts"] = item.get("updated", 0) + {rnd.randint(1, 900)}',
            "        result.append(item)",
            "    return result",
        ]
    if rnd.random() < 0.3:  # sprinkle look-alike constants
        out += ["", f"RETRY_{rnd.choice(WORDS).upper()}_S = {rnd.randint(1, 30)}"]
    return "\n".join(out) + "\n"


def build_codebase(seed: int = 11) -> str:
    rnd = random.Random(seed)
    files: dict[str, str] = {}
    for pkg in ["api", "billing", "core", "reports", "storage", "jobs", "util"]:
        for noun in rnd.sample(WORDS, 6):
            files[f"app/{pkg}/{noun}.py"] = _filler(rnd, f"app/{pkg}/{noun}.py")
    files.update(NEEDLES)
    order = sorted(files)
    rnd.shuffle(order)
    return "\n".join(f"### FILE: {p}\n{files[p]}" for p in order)


NEED = {
    "app/config/retry.py",
    "app/config/tuning.py",
    "app/net/backoff.py",
    "app/workers/constants.py",
}


def grade(out: str) -> Grade:
    try:
        ans = extract_json(out)
        secs = float(ans.get("seconds"))
        files = {str(f) for f in ans.get("files", [])}
    except (ValueError, TypeError, AttributeError):
        return Grade(
            False,
            0,
            "reply not valid JSON with a number",
            out,
            "Your reply was not valid JSON with a numeric seconds field. "
            "Reply again with only the JSON object.",
        )
    cited = len(NEED & files)
    used_decoy = "app/legacy/tuning_old.py" in files
    diagnosis = {
        24.0: "used decoy factor 2",
        81.0: "missed MAX_DELAY_S cap",
        20.0: "missed SYNC_DELAY_SCALE",
        108.0: "decoy + no cap",
    }.get(secs, "")
    ok = abs(secs - 40) < 1e-6
    score = 0.8 * ok + 0.2 * cited / len(NEED)
    notes = (
        f"answered {secs:g}s ({'ok' if ok else 'want 40' + (', ' + diagnosis if diagnosis else '')}); "
        f"cited {cited}/4 key files" + ("; cited decoy" if used_decoy else "")
    )
    return Grade(ok, score, notes, out)


def run(model: str, calibration: bool = False) -> Result:
    _ = calibration
    return graded_run(Chat(model), PROMPT + build_codebase(), grade)
