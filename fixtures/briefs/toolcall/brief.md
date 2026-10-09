## Problem (verified)
`fixtures/toolcall.json` + `src/llmbench/toolcall_match.py` fail correct calls. On Ornith-1.5-9B
(a strong tool-calling model) 11/20 cases fail with fresh chats, e.g.:
- case 5 expects `to_unit: "kilometers"`; the prompt says "km" and the model sends "km".
- case 11 prompt says "NYC", expects `"New York"`.
- case 6 expects the literal `"next Friday"` for a date.
- case 18 expects `attendees: []` that the prompt never mentions.
- `args_match` is exact dict equality, so any extra optional argument fails.
Prompts are terse fragments ("Book flight Paris next Friday") rather than requests.

## Goal
A fair BFCL-style test: a correct call passes, a wrong call fails, independent of harmless wording.

## Changes
1. Fixture format (rewrite all 20 cases, same kind mix: 5 simple, 5 multiple, 4 parallel,
   3 irrelevance, 3 typed):
   - Prompts are natural full-sentence requests that state every required value unambiguously
     (absolute dates like 2026-10-09, explicit units, full city names).
   - Tool schemas mark `required` properly; optional params have defaults described.
   - `expected[i].arguments` maps each param to a LIST of acceptable values, e.g.
     `"to_unit": ["km", "kilometers", "kilometer"]`, `"location": ["New York", "New York City",
     "NYC", "New York, NY"]`. Numbers accept int/float equality.
   - Optional params may be listed under `"optional": {"param": [acceptable values]}`; if the model
     supplies them they must match one; if absent that's fine.
   - Any param not in the schema = fail. A required param missing = fail.
   - "multiple" cases: include 3 distractor tools whose descriptions overlap plausibly.
   - "parallel": 2-3 calls, order-insensitive; the model may also emit them across one message only.
   - "irrelevance": the request can't be served by the given tools (not just chit-chat); pass iff no
     tool call.
   - "typed": exercise int, enum, array of strings, nested object; arrays compare as multisets after
     normalisation unless the fixture sets `"ordered": true`.
2. Matcher (`toolcall_match.py`): implement the above. String normalisation: strip, casefold,
   collapse whitespace, strip trailing punctuation. Keep `grade_case(case, msg) -> bool` signature.
   Return also a short reason string via a new `grade_case_detail(case, msg) -> (bool, str)` and
   use it in `t8_toolcall` so each case line says why it failed.
3. Tests (`tests/test_toolcall_match.py`): for EVERY fixture case, a hand-written correct call that
   passes, and at least one wrong call that fails (wrong function, wrong value, missing required,
   unknown param). Plus parallel order-insensitivity and optional-param handling.
4. Report: add a `length_stops` column (sum over the model's suite runs; the runner already records
   `length_stops` per run in suite.json) to report.md and report.html, labelled "hit max_tokens".

## Out of scope
Everything else. Don't touch other tasks, server.py, core.py.
No model runs needed; no downloads; stay inside this repo.

## Done bar
`uv run ruff check . && uv run ruff format --check .` clean; `uv run pytest` green. Commit per item
on the current branch. Finish with: commits, test count, and a table of the 20 cases (kind, prompt).

## Interface (acceptance tests call exactly these)
- `llmbench.toolcall_match.grade_case(case, msg) -> bool` and `grade_case_detail(case, msg) -> tuple[bool, str]`.
- `msg` is an OpenAI assistant message: `{"role": "assistant", "content": ..., "tool_calls": [{"type": "function", "function": {"name": str, "arguments": <JSON string>}}]}`.
- Case format: `{"kind", "prompt", "tools": [OpenAI tool schemas], "expected": [{"name", "arguments": {param: [acceptable values]}, "optional": {param: [acceptable values]}, "ordered"?: bool}]}`; irrelevance cases have `"expected": []`.
