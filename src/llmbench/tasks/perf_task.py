"""Perf is run by orchestrator via llmbench.perf, not the task suite loop."""

ID = "perf"
TITLE = "Performance probe"
TESTS = "Prompt/gen throughput and TTFT (orchestrator-only)"
CATEGORY = "perf"
