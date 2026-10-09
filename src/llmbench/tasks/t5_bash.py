"""Shell scripting: write a duplicate-file finder, executed in a sandbox and diffed exactly."""

from __future__ import annotations

import tempfile
from pathlib import Path

from llmbench.core import SANDBOX_WORK, Chat, Grade, Result, extract_code, graded_run, sandbox_run

ID = "bash"
TITLE = "Bash script, executed"
TESTS = "Writes a real script run on real files: spaces in names, empty files, exact output format"
CATEGORY = "single_shot"

PROMPT = """Write a bash script `dupes.sh` that takes one argument, a directory, and reports \
files with identical contents anywhere under it (recursively).

Requirements:
- Compare by SHA-256 of contents. Ignore empty files.
- Print each group of duplicates as one path per line, paths relative to the given \
directory (no leading "./"), sorted within the group.
- Order groups by their first path. Separate groups with exactly one blank line; no \
blank line at the start or end. Print nothing else.
- Must handle file names containing spaces.
- Start with a shebang and `set -euo pipefail`.

Reply with the script in a single ```bash code block."""

DATA = {
    "a.txt": b"hello\n",
    "b/a copy.txt": b"hello\n",
    "c/deep/x.txt": b"hello\n",
    "d.txt": b"world\n",
    "e.txt": b"world\n",
    "g h.txt": b"world\n",
    "f.txt": b"unique\n",
    "empty1": b"",
    "sub/empty2": b"",
    "h.bin": bytes(range(256)),
    "z/solo.bin": bytes(range(255, -1, -1)),
}

EXPECTED = "a.txt\nb/a copy.txt\nc/deep/x.txt\n\nd.txt\ne.txt\ng h.txt"


def _groups(text: str) -> set[frozenset[str]]:
    return {
        frozenset(line.strip().removeprefix("./") for line in block.splitlines() if line.strip())
        for block in text.strip().split("\n\n")
        if block.strip()
    }


def grade(out: str) -> Grade:
    script = extract_code(out, "bash") or extract_code(out, "sh")
    if not script:
        return Grade(
            False,
            0,
            "no bash code block in reply",
            out,
            "Reply with the script in a single ```bash code block.",
        )
    with tempfile.TemporaryDirectory() as d:
        wd = Path(d)
        (wd / "dupes.sh").write_text(script)
        for rel, blob in DATA.items():
            (wd / "data" / rel).parent.mkdir(parents=True, exist_ok=True)
            (wd / "data" / rel).write_bytes(blob)
        proc = sandbox_run(["bash", "dupes.sh", f"{SANDBOX_WORK}/data"], wd, timeout=30)
        got, err, rc = proc.stdout, proc.stderr.strip(), proc.returncode

    header_ok = script.lstrip().startswith("#!") and "set -euo pipefail" in script
    # One final newline is fine; anything else trailing breaks "no blank line at the end".
    exact = got in (EXPECTED, EXPECTED + "\n") and rc == 0
    same_groups = _groups(got) == _groups(EXPECTED)
    score = 1.0 if exact else 0.5 if same_groups else 0.0
    score = score * 0.9 + 0.1 * header_ok
    if exact:
        notes = "exact output"
    elif same_groups:
        notes = "right groups, format off"
    else:
        notes = f"wrong output (rc={rc})" + (f"; stderr: {err[:160]}" if err else "")
    if not header_ok:
        notes += "; missing shebang/set -euo pipefail"
    # A crash or missing header is visible to anyone running it; a wrong answer is not.
    problems = []
    if rc != 0:
        problems.append(
            f"it exited with status {rc}"
            + (f" and stderr:\n{err[:1500]}" if err else " and no stderr")
        )
    if not header_ok:
        problems.append("it is missing the shebang or `set -euo pipefail`")
    fb = (
        (
            "I ran your script on a test directory and "
            + "; ".join(problems)
            + ". Fix it and reply with the full script in a single ```bash code block."
        )
        if problems
        else None
    )
    output = f"{out}\n\n--- script stdout (rc={rc}) ---\n{got}" + (
        f"\n--- stderr ---\n{err}" if err else ""
    )
    return Grade(exact and header_ok, score, notes, output, fb)


def run(model: str, calibration: bool = False) -> Result:
    _ = calibration
    return graded_run(Chat(model), PROMPT, grade)
