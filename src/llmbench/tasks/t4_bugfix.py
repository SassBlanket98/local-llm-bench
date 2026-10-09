"""Bug fix: repair a module from its failing tests; graded by visible + hidden pytest runs."""

from __future__ import annotations

import re
import sys
import tempfile
from pathlib import Path

from llmbench.core import Chat, Grade, Result, extract_code, graded_run, sandbox_run

ID = "bugfix"
TITLE = "Bug fix against tests"
TESTS = "Finds three subtle bugs (boundaries, remainders, float cents); hidden tests catch hacks"
CATEGORY = "coding_loop"

SOURCE = '''\
def tier_discount(subtotal: float) -> float:
    """Discount rate: 0% under 100, 5% from 100 up to (not incl.) 500, 10% from 500 up."""
    if subtotal > 500:
        return 0.10
    if subtotal > 100:
        return 0.05
    return 0.0


def split_bill(total_cents: int, people: int) -> list[int]:
    """Split total_cents across people as evenly as possible.

    Earlier people pay any leftover cents; the parts must always sum to total_cents.
    """
    share = total_cents // people
    return [share] * people


def parse_price(text: str) -> int:
    """Parse strings like '$1,234.50' or '19.9' into integer cents."""
    cleaned = text.replace("$", "").replace(",", "").strip()
    return int(float(cleaned) * 100)
'''

VISIBLE_TESTS = """\
from pricing import parse_price, split_bill, tier_discount


def test_tiers():
    assert tier_discount(50) == 0.0
    assert tier_discount(100) == 0.05
    assert tier_discount(250) == 0.05
    assert tier_discount(500) == 0.10


def test_split_even():
    assert split_bill(900, 3) == [300, 300, 300]


def test_split_remainder():
    assert split_bill(100, 3) == [34, 33, 33]


def test_parse():
    assert parse_price("$1,234.50") == 123450
    assert parse_price("0.29") == 29
"""

HIDDEN_TESTS = """\
from pricing import parse_price, split_bill, tier_discount


def test_hidden_tiers():
    assert tier_discount(99.99) == 0.0
    assert tier_discount(499.99) == 0.05
    assert tier_discount(10_000) == 0.10


def test_hidden_split():
    for total, n in [(7, 3), (1, 4), (1001, 7), (0, 5)]:
        parts = split_bill(total, n)
        assert sum(parts) == total and len(parts) == n
        assert max(parts) - min(parts) <= 1
        assert parts == sorted(parts, reverse=True)


def test_hidden_parse():
    assert parse_price("19.9") == 1990
    assert parse_price("$0.57") == 57
    assert parse_price("4.35") == 435
    assert parse_price(" $2,000 ") == 200000
"""

PROMPT = f"""Some tests are failing for this module. Fix the bugs in pricing.py so the tests \
pass, keeping behaviour otherwise as documented. Do not special-case test inputs.

Reply with the complete corrected pricing.py in a single ```python code block.

pricing.py:
```python
{SOURCE}```

test_pricing.py:
```python
{VISIBLE_TESTS}```
"""


def _pytest(workdir: Path, test_file: str) -> tuple[int, int, str]:
    proc = sandbox_run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", test_file],
        workdir,
        timeout=60,
    )
    out = proc.stdout + proc.stderr
    passed = int(m.group(1)) if (m := re.search(r"(\d+) passed", out)) else 0
    failed = int(m.group(1)) if (m := re.search(r"(\d+) failed", out)) else 0
    errors = int(m.group(1)) if (m := re.search(r"(\d+) error", out)) else 0
    return passed, passed + failed + errors or 1, out


def grade(out: str) -> Grade:
    code = extract_code(out, "python")
    if not code:
        return Grade(
            False,
            0,
            "no python code block in reply",
            out,
            "Reply with the complete pricing.py in a single ```python code block.",
        )
    with tempfile.TemporaryDirectory() as d:
        wd = Path(d)
        (wd / "pricing.py").write_text(code)
        (wd / "test_pricing.py").write_text(VISIBLE_TESTS)
        (wd / "test_hidden.py").write_text(HIDDEN_TESTS)
        vp, vt, vout = _pytest(wd, "test_pricing.py")
        hp, ht, hout = _pytest(wd, "test_hidden.py")
    score = (vp + hp) / (vt + ht)
    notes = f"visible {vp}/{vt}, hidden {hp}/{ht}"
    if hp < ht:
        notes += "; hidden failures: " + ", ".join(re.findall(r"FAILED \S+::(\w+)", hout))
    # Like a real run: the model sees the visible test output, never the hidden tests.
    fb = None
    if vp < vt:
        fb = (
            "The tests still fail:\n```\n" + vout[-3000:] + "\n```\nFix pricing.py and reply "
            "with the complete file in a single ```python code block."
        )
    return Grade(vp == vt and hp == ht, score, notes, out, fb)


def run(model: str, calibration: bool = False) -> Result:
    _ = calibration
    return graded_run(Chat(model), PROMPT, grade)
