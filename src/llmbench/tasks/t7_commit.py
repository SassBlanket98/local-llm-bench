"""Instruction following: a commit message under eight hard, machine-checked rules."""

from __future__ import annotations

import re

from llmbench.core import Chat, Grade, Result, graded_run

ID = "rules"
TITLE = "Strict instruction following"
TESTS = "Summarises a diff into a commit message that obeys 8 exact formatting rules"
CATEGORY = "single_shot"

DIFF = '''\
diff --git a/app/config.py b/app/config.py
@@ -1,14 +1,31 @@
 import os
+import re
+
+_UNITS = {"s": 1, "m": 60, "h": 3600}
+
+
+def parse_timeout(value: str) -> int:
+    """Parse '30', '30s', '5m' or '1h' into seconds."""
+    m = re.fullmatch(r"\\s*(\\d+)\\s*([smh]?)\\s*", value)
+    if not m:
+        raise ValueError(f"bad timeout: {value!r}")
+    return int(m.group(1)) * _UNITS.get(m.group(2) or "s")
+

 def load_config() -> dict:
     return {
         "db_url": os.environ["DB_URL"],
-        "timeout": int(os.environ.get("TIMEOUT", "30")),
+        "timeout": parse_timeout(os.environ.get("TIMEOUT", "30s")),
         "workers": int(os.environ.get("WORKERS", "4")),
     }
diff --git a/tests/test_config.py b/tests/test_config.py
@@ -0,0 +1,12 @@
+import pytest
+from app.config import parse_timeout
+
+
+@pytest.mark.parametrize("raw,secs", [("30", 30), ("30s", 30), ("5m", 300), ("1h", 3600)])
+def test_parse_timeout(raw, secs):
+    assert parse_timeout(raw) == secs
+
+
+def test_parse_timeout_rejects_garbage():
+    with pytest.raises(ValueError):
+        parse_timeout("soon")
'''

PROMPT = f"""Write a git commit message for this diff. Rules, all mandatory:

1. Subject line at most 50 characters.
2. Subject starts with a capital letter and uses the imperative mood ("Add", not "Added"/"Adds").
3. Subject does not end with a period.
4. Second line is blank.
5. Body: 2 to 4 bullet points, each starting with "- ".
6. Every body line at most 72 characters.
7. Mention `parse_timeout` by name somewhere.
8. Output only the message: no code fences, no emoji, no preamble, never "This commit".

{DIFF}"""

EMOJI = re.compile("[\U0001f300-\U0001faff☀-➿]")


def check(msg: str) -> dict[str, bool]:
    lines = msg.strip("\n").split("\n")
    subject = lines[0] if lines else ""
    body = lines[2:]
    first = subject.split()[0] if subject.split() else ""
    bullets = [ln for ln in body if ln.startswith("- ")]
    return {
        "subject <= 50": 0 < len(subject) <= 50,
        "capitalised imperative": first[:1].isupper()
        and not re.search(r"(ed|ing)$", first)
        and not (first.endswith("s") and not first.endswith("ss")),
        "no trailing period": not subject.endswith("."),
        "blank line 2": len(lines) > 2 and lines[1] == "",
        "2-4 bullets": 2 <= len(bullets) <= 4
        and all(ln.startswith(("- ", "  ")) for ln in body if ln.strip()),
        "body lines <= 72": all(len(ln) <= 72 for ln in body),
        "mentions parse_timeout": "parse_timeout" in msg,
        "clean output": "```" not in msg
        and not EMOJI.search(msg)
        and "this commit" not in msg.lower(),
    }


def grade(out: str) -> Grade:
    checks = check(out)
    failed = [k for k, v in checks.items() if not v]
    score = sum(checks.values()) / len(checks)
    notes = f"{sum(checks.values())}/{len(checks)} rules" + (
        f"; broke: {', '.join(failed)}" if failed else ""
    )
    # Equivalent to running a commit-msg linter and pasting its complaints.
    fb = (
        (
            "A commit-msg lint rejected it for: "
            + ", ".join(failed)
            + ". Reply again with only the corrected message."
        )
        if failed
        else None
    )
    return Grade(not failed, score, notes, out, fb)


def run(model: str, calibration: bool = False) -> Result:
    _ = calibration
    return graded_run(Chat(model), PROMPT, grade)
