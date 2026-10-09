"""Seeded ~6k-token incident report for summary task."""

from __future__ import annotations

import random

SEED = 99


def incident_report() -> str:
    rng = random.Random(SEED)
    core = """\
# Incident report IR-2026-0312

On 2026-03-12 at 02:17 UTC the checkout-api service in eu-west-2 began returning 503 errors.
Within ten minutes error rate reached 42% of checkout attempts. On-call traced spikes to
connection pool exhaustion after deploy of release 2026.3.12-a. The outage lasted 47 minutes
and affected about 12000 customers attempting card checkout.

Mitigation: engineers rolled back to release 2026.3.11-c at 03:04 UTC. A postmortem is
scheduled for 2026-03-14.

"""
    pad = (
        "Timeline filler: metrics dashboards showed elevated latency on dependency payment-gw. "
        "Support queue depth increased; status page updated twice. "
    )
    text = core
    while len(text.split()) < 6000:
        text += pad + f"Noise entry {rng.randint(1, 9999)}: benign cache refresh completed.\n"
    return text
