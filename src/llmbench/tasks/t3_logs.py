"""Log triage: find the real root cause in ~500 lines of noisy syslog, past red herrings."""

from __future__ import annotations

import json
import random
import re
from datetime import datetime, timedelta

from llmbench.core import Chat, Grade, Result, extract_json, graded_run

ID = "logs"
TITLE = "Log root-cause analysis"
TESTS = "Reads ~12K tokens of noisy syslog, traces a causal chain, ignores scary-looking decoys"
CATEGORY = "single_shot"

HOST = "web01"
DAY = datetime(2026, 9, 21, 2, 0, 0)  # noqa: DTZ001 - syslog has no tz

# The real chain. The remote target has been flaky since 02:15 (a hint), the 03:00 backup
# falls back to local disk, fills it, and Postgres dies on ENOSPC.
CHAIN = [
    (
        "02:15:07",
        "backup-agent[812]",
        "remote target backup.internal:873 unreachable (connect timeout)",
    ),
    ("03:00:01", "CRON[4410]", "(root) CMD (/usr/local/bin/nightly-backup.sh)"),
    (
        "03:00:02",
        "nightly-backup.sh[4411]",
        "remote target unreachable, falling back to local dir /var/lib/postgresql/backups",
    ),
    (
        "03:00:03",
        "nightly-backup.sh[4411]",
        "pg_dumpall started -> /var/lib/postgresql/backups/full-20260921.sql",
    ),
    ("03:04:30", "disk-monitor[655]", "WARNING /var/lib/postgresql usage 91%"),
    ("03:09:55", "disk-monitor[655]", "CRITICAL /var/lib/postgresql usage 99%"),
    (
        "03:10:21",
        "postgres[1022]",
        'PANIC:  could not write to file "pg_wal/xlogtemp.1022": No space left on device',
    ),
    ("03:10:21", "postgres[1022]", "LOG:  database system is shut down"),
    (
        "03:10:40",
        "app[2201]",
        "ERROR sqlalchemy.exc.OperationalError: connection to server at 127.0.0.1:5432 refused",
    ),
]

PROMPT = """The app on this host started returning 502s overnight. Below is the syslog. Find the \
root cause.

Reply with only JSON:
{"root_cause": "<one or two sentences>", "trigger_timestamp": "HH:MM:SS of the event that \
set the failure in motion", "evidence": ["<exact log lines you relied on>", ...]}

LOG:
"""


def build_log(seed: int = 7) -> str:
    rnd = random.Random(seed)
    lines: list[tuple[datetime, str]] = []
    t = DAY
    paths = ["/", "/api/orders", "/api/cart", "/static/app.js", "/healthz", "/api/users/me"]
    while t < DAY + timedelta(hours=2):
        t += timedelta(seconds=rnd.randint(8, 22))
        down = t >= DAY.replace(hour=3, minute=10, second=41)
        r = rnd.random()
        if r < 0.55:
            status = 502 if down and rnd.random() < 0.9 else 200
            ip = f"198.51.100.{rnd.randint(2, 250)}"
            msg = f'{ip} - - "GET {rnd.choice(paths)} HTTP/1.1" {status} {rnd.randint(200, 9000)}'
            if status == 502:
                msg += (
                    ' upstream: "http://127.0.0.1:8000" connect() failed (111: Connection refused)'
                )
            lines.append((t, f"nginx[901]: {msg}"))
        elif r < 0.65:
            lines.append((t, f"systemd[1]: Started session-{rnd.randint(100, 999)}.scope."))
        elif r < 0.72:
            lines.append(
                (t, f"CRON[{rnd.randint(3000, 3999)}]: (www-data) CMD (php /var/www/cron.php)")
            )
        elif r < 0.80:
            lines.append((t, f"app[2201]: INFO request handled in {rnd.randint(4, 180)}ms"))
        elif r < 0.86:
            lines.append(
                (
                    t,
                    f"kernel: [UFW BLOCK] IN=eth0 SRC=192.0.2.{rnd.randint(2, 250)} DPT={rnd.choice([23, 445, 3389])}",
                )
            )
        else:
            lines.append(
                (
                    t,
                    f"systemd-timesyncd[540]: Synchronized to time server 10.0.0.{rnd.randint(1, 4)}:123.",
                )
            )

    # Decoy 1: an SSH brute-force burst that looks alarming but is unrelated.
    t = DAY.replace(hour=2, minute=41)
    for _ in range(40):
        t += timedelta(seconds=rnd.randint(1, 20))
        user = rnd.choice(["admin", "oracle", "test", "ubuntu"])
        pid, port = rnd.randint(5000, 5999), rnd.randint(30000, 60000)
        msg = f"sshd[{pid}]: Failed password for invalid user {user} from 203.0.113.45 port {port} ssh2"
        lines.append((t, msg))
    # Decoy 2: certbot and an OOM-ish memory warning in an unrelated service.
    lines.append(
        (
            DAY.replace(hour=2, minute=30, second=12),
            "certbot[3120]: Cert not yet due for renewal; renewal skipped",
        )
    )
    lines.append(
        (
            DAY.replace(hour=3, minute=2, second=48),
            "kernel: redis-server[1400]: memory usage high (82%), consider maxmemory",
        )
    )
    for hms, proc, msg in CHAIN:
        h, m, s = map(int, hms.split(":"))
        lines.append((DAY.replace(hour=h, minute=m, second=s), f"{proc}: {msg}"))

    lines.sort(key=lambda x: x[0])
    return "\n".join(f"{ts:%b %d %H:%M:%S} {HOST} {msg}" for ts, msg in lines)


def grade(out: str, log: str) -> Grade:
    try:
        ans = extract_json(out)
        cause = str(ans.get("root_cause", "")).lower()
        ts = str(ans.get("trigger_timestamp", ""))
        evidence = [str(e) for e in ans.get("evidence", [])]
    except (ValueError, AttributeError):
        return Grade(
            False,
            0,
            "reply not valid JSON",
            out,
            "Your reply was not valid JSON. Reply again with only the JSON object.",
        )

    quoted_ok = [e for e in evidence if len(e) > 15 and e.strip() in log]
    checks = {
        "blames disk space": bool(re.search(r"disk|space|full|enospc", cause)),
        "links it to the backup": "backup" in cause,
        "no decoy blamed": not re.search(r"ssh|brute|certbot|certificate|redis", cause),
        "evidence is real (>=2 lines verbatim)": len(quoted_ok) >= 2,
    }
    ts_hit = re.search(r"\d\d:\d\d:\d\d", ts)
    ts = ts_hit.group(0) if ts_hit else ts
    if ts in {"03:00:01", "03:00:02", "03:00:03", "02:15:07"}:
        ts_score, ts_note = 1.0, "ok"
    elif ts in {"03:04:30", "03:09:55", "03:10:21"}:
        ts_score, ts_note = 0.5, "downstream symptom"
    else:
        ts_score, ts_note = 0.0, "wrong"
    score = (sum(checks.values()) + ts_score) / (len(checks) + 1)
    failed = [k for k, v in checks.items() if not v]
    notes = f"trigger {ts} ({ts_note})" + (f"; failed: {', '.join(failed)}" if failed else "")
    # Only verifiable without the answer: whether quoted evidence exists in the log.
    fake = [e for e in evidence if e not in quoted_ok]
    fb = None
    if len(quoted_ok) < 2:
        fb = (
            "These evidence lines do not appear verbatim in the log: "
            + json.dumps(fake)
            + ". Re-check the log and reply again with only the JSON, "
            "quoting lines exactly."
        )
    return Grade(score >= 0.8 and checks["blames disk space"], score, notes, out, fb)


def run(model: str, calibration: bool = False) -> Result:
    _ = calibration
    log = build_log()
    return graded_run(Chat(model), PROMPT + log, lambda out: grade(out, log))
