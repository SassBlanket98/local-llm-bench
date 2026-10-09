6. **report.md perf numbers are unrounded** (`21544.062533461827 tok/s`): round tok/s to integers,
   ms to 1 decimal, in both report.md and report.html.


## Interface (acceptance tests call exactly these)
- `llmbench.report._fmt_tok_s(x) -> str` (integer, e.g. "21544") and `llmbench.report._fmt_ms(x) -> str` (one decimal, e.g. "12.3"), used for every perf number in report.md and report.html.
