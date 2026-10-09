import json
import re
from pathlib import Path

from llmbench.summary_gen import incident_report

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "summary_incident.json"


def test_good_summary_hits_facts():
    spec = json.loads(FIXTURE.read_text())
    good = (
        "At 02:17 UTC checkout-api in eu-west-2 hit 42% errors from connection pool exhaustion "
        "after deploy 2026.3.12-a; ~12000 customers for 47 minutes; rollback mitigation; "
        "postmortem scheduled."
    )
    hits = sum(
        1 for f in spec["facts"] if any(re.search(p, good, re.IGNORECASE) for p in f["patterns"])
    )
    assert hits >= 8


def test_bad_summary_misses():
    bad = "Something broke briefly."
    spec = json.loads(FIXTURE.read_text())
    hits = sum(
        1 for f in spec["facts"] if any(re.search(p, bad, re.IGNORECASE) for p in f["patterns"])
    )
    assert hits < 3


def test_incident_report_seeded():
    assert incident_report() == incident_report()
