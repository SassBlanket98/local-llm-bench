"""Structured extraction: messy support emails into strict JSON, graded field by field."""

from __future__ import annotations

from llmbench.core import Chat, Grade, Result, extract_json, graded_run

ID = "extract"
TITLE = "Structured extraction"
TESTS = "Turns messy emails into schema-exact JSON; applies rules, normalises, avoids traps"
CATEGORY = "single_shot"

EMAILS = """\
=== EMAIL 1 ===
Subject: Re: [TCK-40213] Blender arrived cracked
From: Maria Okonkwo <maria.o@example.com>

Hi, the ProBlend 900 I ordered arrived with a cracked jug. I'd like a replacement jug sent
please, not a refund. Order total was $129.99.
Thanks, Maria

=== EMAIL 2 ===
Subject: URGENT - charged twice
From: accounts@hollowayfarms.example

Ticket TCK-40218. This is Tom Holloway's assistant writing on his behalf. Tom was charged
twice for his AquaPure filter subscription this month ($34.00 each). Please refund the
duplicate charge ASAP.
- Priya (for Tom Holloway)

=== EMAIL 3 ===
Subject: question about warranty
From: Ken Watanabe <kenw@example.org>

Hello, does the warranty on the TrailCam X2 cover water damage? Just asking before I buy a
second one. Ticket number is tck-40225 i think.
Ken

=== EMAIL 4 ===
Subject: [TCK-40229] dashboard down
From: Dana Whitfield <dana@whitfield-logistics.example>

Our SyncHub Pro dashboard has been down for the whole team since 9am, nothing loads at all.
We need someone on this now.
Dana

=== EMAIL 5 ===
Subject: cancellation TCK-40240
From: Sam Reyes <sam.reyes@example.net>

Please cancel my Lumen Cloud Backup subscription at the end of this billing period. No
refund needed, I've had my use out of it. Thanks!
Sam Reyes
"""

PROMPT = f"""Extract one record per email below. Reply with only a JSON array, one object per \
email in order, with exactly these keys:

- ticket_id: string, uppercase, like "TCK-12345"
- customer_name: full name of the customer (not of anyone writing on their behalf)
- priority: "high" if the customer says urgent/ASAP or reports an outage; "low" if they are \
only asking a question; otherwise "medium"
- product: product name as written in the email
- action: one of "refund", "replacement", "cancel", "info", "support"
- refund_amount: number the customer explicitly asks to have refunded, else null

{EMAILS}"""

GOLD = [
    {
        "ticket_id": "TCK-40213",
        "customer_name": "Maria Okonkwo",
        "priority": "medium",
        "product": "ProBlend 900",
        "action": "replacement",
        "refund_amount": None,
    },
    {
        "ticket_id": "TCK-40218",
        "customer_name": "Tom Holloway",
        "priority": "high",
        "product": "AquaPure filter subscription",
        "action": "refund",
        "refund_amount": 34.0,
    },
    {
        "ticket_id": "TCK-40225",
        "customer_name": "Ken Watanabe",
        "priority": "low",
        "product": "TrailCam X2",
        "action": "info",
        "refund_amount": None,
    },
    {
        "ticket_id": "TCK-40229",
        "customer_name": "Dana Whitfield",
        "priority": "high",
        "product": "SyncHub Pro",
        "action": "support",
        "refund_amount": None,
    },
    {
        "ticket_id": "TCK-40240",
        "customer_name": "Sam Reyes",
        "priority": "medium",
        "product": "Lumen Cloud Backup",
        "action": "cancel",
        "refund_amount": None,
    },
]


def _match(key: str, got: object, want: object) -> bool:
    if key == "refund_amount":
        if want is None:
            return got is None
        try:
            return abs(float(got) - float(want)) < 0.005  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return False
    g, w = str(got).strip().lower(), str(want).lower()
    if key == "product":  # accept "AquaPure filter" for "AquaPure filter subscription" etc.
        return g == w or (len(g) >= 6 and (g in w or w in g))
    return g == w


def grade(out: str) -> Grade:
    try:
        recs = extract_json(out)
        assert isinstance(recs, list)
    except (ValueError, AssertionError):
        return Grade(
            False, 0, "no JSON array in reply", out, "Reply again with only the JSON array."
        )

    total = sum(len(g) for g in GOLD)
    right, misses = 0, []
    for i, gold in enumerate(GOLD):
        rec = recs[i] if i < len(recs) and isinstance(recs[i], dict) else {}
        for k, v in gold.items():
            # A missing key never counts as a correct null.
            if k in rec and _match(k, rec[k], v):
                right += 1
            else:
                misses.append(f"#{i + 1} {k}={rec.get(k, '<missing>')!r} (want {v!r})")
    extra_keys = {k for r in recs if isinstance(r, dict) for k in r} - set(GOLD[0])
    notes = f"{right}/{total} fields" + (f"; misses: {'; '.join(misses)}" if misses else "")
    if extra_keys:
        notes += f"; extra keys {sorted(extra_keys)}"
    if len(recs) != len(GOLD):
        notes += f"; {len(recs)} records (want {len(GOLD)})"
    # Schema problems are checkable without knowing the answers; wrong values are not.
    schema = []
    if len(recs) != len(GOLD):
        schema.append(f"expected {len(GOLD)} records, got {len(recs)}")
    if extra_keys:
        schema.append(f"unexpected keys {sorted(extra_keys)}")
    if any(not isinstance(r, dict) for r in recs):
        schema.append("every record must be a JSON object")
    missing = {k for r in recs if isinstance(r, dict) for k in GOLD[0] if k not in r}
    if missing:
        schema.append(f"records missing keys {sorted(missing)}")
    fb = (
        (
            "Schema check failed: " + "; ".join(schema) + ". Reply again with only the corrected "
            "JSON array."
        )
        if schema
        else None
    )
    score = right / total
    ok = score >= 0.9 and not extra_keys and len(recs) == len(GOLD)
    return Grade(ok, score, notes, out, fb)


def run(model: str, calibration: bool = False) -> Result:
    _ = calibration
    return graded_run(Chat(model), PROMPT, grade)
