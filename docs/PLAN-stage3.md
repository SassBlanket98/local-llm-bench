# Stage 3 plan: can a local model replace Composer as the plan-following worker?

> This is the plan as written before the work was built, kept for the reasoning. The code is the current behaviour. It refers to working files (`docs/BRIEF-*.md`, `research/`) and commits that are not in the public repository; the per-case briefs are in `fixtures/briefs/`.

## Question
Given a detailed brief of the kind Cursor gets (no design decisions left), can a local model on the
5070 Ti implement it across files, write/run tests and finish correctly, as often as
`composer-2.5-fast`? Stages 1-2 didn't test this: their agent repos are 1-3 files and IFEval checks
formatting, not sticking to a plan.

## Test cases: replay real briefs
Every item in `docs/BRIEF-fix1.md` and the whole of `docs/BRIEF-fix2.md` has a commit Cursor produced,
each with the unit tests it wrote. That gives 7 cases, each with a known parent commit and a
reference solution:

| Case | Brief | Parent | Reference commit | Reference tests |
|---|---|---|---|---|
| snapshot | fix1 #1 | c7edcb7 | ce87ae8 | tests/test_agent_repo_snapshot.py |
| docqa-gen | fix1 #2 | ce87ae8 | 3967c6e | tests/test_docqa_gen.py |
| web-site | fix1 #3 | 3967c6e | d93a1bd | tests/test_web_local_grade.py |
| gpu-fit | fix1 #4 | d93a1bd | 9450c1e | tests/test_server_fit.py |
| transcripts | fix1 #5 | 9450c1e | d186d9c | tests/test_transcript.py |
| rounding | fix1 #6 | d186d9c | deefdeb | tests/test_report_rounding.py |
| toolcall | fix2 (all) | 140703e | 4ebc6e6..92d5d34 | tests/test_toolcall_match.py |

Each case runs from its parent commit and gets only its own item, not the rest of the brief file.

### Workspace (no peeking at the answer)
The repo's `.git` holds the future commits, so an agent could `git show` the answer. Each run gets
`git archive <parent> | tar -x` into a scratch dir, then a fresh `git init` plus one commit. No history,
no remote. Remove `results/` and the brief file for later rounds (`BRIEF-fix2.md` at the fix1 parents
doesn't exist yet anyway). `uv sync` is done before the agent starts, so time isn't spent on installs.

### Grading (deterministic, run after the agent exits)
| Check | Weight | How |
|---|---|---|
| Hidden acceptance tests | 50 | Reference tests copied in after the run and run with pytest. I'll trim each file to the behaviour its brief item specifies (names/signatures the brief states), so a correct solution with different internals isn't failed. Score = fraction passed. |
| No regressions | 15 | The parent's existing test suite still passes. |
| Own tests written | 10 | The brief asks for unit tests: new/changed test file exists, and its tests pass. |
| ruff clean | 10 | `ruff check` + `ruff format --check` on touched files. |
| Stayed in scope | 10 | Files touched ⊆ the case's allowed set (from the reference diff plus test files); each extra file costs points. |
| Honest finish | 5 | The agent's final message doesn't claim done when hidden tests fail. |

Also recorded: wall time, prompt/gen tokens, steps, and whether it hit the step or time limit.

## Agent harness
The model needs a real coding agent around it, the same one for every local model:
1. **Spike first (30 min):** `codex exec` with a custom OpenAI-compatible provider pointed at
   llama-server (`--jinja`, Ornith, 128k ctx), on the `rounding` case. Codex is already installed,
   runs unattended, and sandboxes shell commands. Check that it can read, edit and run pytest in the
   workspace, and that tool calls round-trip through llama-server's chat template.
2. If Codex can't talk to llama-server cleanly, fall back to a small built-in agent loop in llmbench
   (tools: list_dir, read_file, write_file, replace_in_file, run_shell with a timeout, finish), reusing
   `t9_agent_repo`'s loop. It's less realistic, but deterministic and fully under our control.
Limits per run: 60 min wall, 150 steps, 128k ctx (every candidate fits 128k on GPU).

**Composer baseline:** `cursor-agent -p --force --model composer-2.5-fast` in an identical workspace,
1 rep per case (7 runs of Cursor usage). Grok isn't included: the question is Composer's job.

### Spike result (2026-09-28): Codex works
- llama-server build 11146 serves `/v1/responses`, so Codex runs with a custom provider
  (`wire_api = "responses"`, `base_url = http://127.0.0.1:<port>/v1`) and a **separate `CODEX_HOME`**
  holding only that config. The user's own `~/.codex` (AGENTS.md, hooks, plugins, memories) must not
  leak into the model's context.
- `codex exec ... < /dev/null`: without closing stdin it waits forever on "Reading additional input".
- Ornith + Codex finished the `rounding` case in ~17 min / 60k tokens: correct change, its own
  tests, 43 passed, ruff clean.
- `uv run` fails inside Codex's workspace-write sandbox (uv cache lock outside the workspace). Set
  `UV_CACHE_DIR=<workspace>/.uv-cache` or mention `.venv/bin/` in the prompt.
- Cursor's reference test for `rounding` imports private helpers (`_fmt_tok_s`) the brief never
  named, so it errored on Ornith's correct `_fmt_speed`. **Hidden tests must be black-box:** call
  only names and signatures the brief states, or go through the public output (e.g. render the report
  and check its text). Reference tests are a starting point, rewritten per case.
- Timing: at ~17 min for the smallest case, 7 cases × 3 reps × 2 models is ~15-20 h. Run 2 reps per
  model in the first night and add the third only if the scores are close.

## Models
- **Ornith 1.5 9B** (stage 2 winner) and **Spark X2.5 4B** (best instruction following), tuned configs
  from stage 2, ctx raised to 128k.
- **Optional third:** a ~30B MoE (3B active) with experts offloaded to CPU. It's the biggest class
  that runs here at usable speed, and plan-following is where extra size should show. Needs a quick
  fit and speed check first (target ≥ 25 tok/s at 64k).
- 3 reps per case per local model. Estimate: 7 cases × 3 reps × 2 models ≈ 42 runs at 5-20 min ≈
  7-10 h, one overnight run. Add ~4 h for the MoE.

## Output
`results/stage3/<model>/<case>-<rep>/` (diff, agent log, grade.json), and a report with the pass rate
per case against Composer, time per case, and a verdict: "use local model X for briefs like Y".

## Build steps
1. Harness spike (me, by hand) and a decision on Codex vs the built-in loop.
2. Case manifest `fixtures/briefs/*.toml` (parent SHA, brief text, allowed files, hidden tests) and
   trimmed hidden tests (me: this is judgment work, done case by case).
3. `bench briefs` runner: workspace export, agent launch, grading, resumable like `bench run`.
   Implemented by Cursor from a brief, verified against the done bar.
4. Dry run: the reference commit's code must score ~100 on every case, and the unmodified parent must
   score low. This proves the graders before any model runs.
5. Composer baseline, then the overnight local run, then the report.

## Done bar
ruff clean; unit tests for the graders; dry run passes (reference ≈ 100, parent low, on all 7 cases);
one full case completes end to end for each model; Codex review.

## Known limits
- All 7 cases come from one Python repo, built on the same day. The results say "briefs like these",
  not every project. Adding briefs from other repos would be a follow-up.
- Composer gets 1 rep, so its score is noisier than the local models'.
