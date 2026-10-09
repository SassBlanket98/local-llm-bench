# local-llm-bench

A benchmark harness for local GGUF models running on `llama-server` (llama.cpp), built to answer one question on my own hardware: which model that fits a 16 GB GPU is good enough to work as a coding or agent worker. AI coding agents wrote the code under my direction.

It runs one model at a time, unattended. For each model it checks that the model fits on the GPU, tunes its settings on a short calibration set, runs the task suite, and writes a report. Every task is graded by code.

## What it tests

`bench run` covers 14 tasks in `src/llmbench/tasks/`:

| Area | Tasks |
|---|---|
| Single-shot | JSON extraction, bash one-liners, commit messages, log analysis, a code bugfix |
| Agent loops | A tool loop over a small repository (list, read, edit, run tests), graded by the tests passing |
| Tool calling | Single, parallel, pick-the-right-tool, no-tool-needed and typed-argument cases, matched against expected calls |
| Document reading | Long-document questions at several context sizes, and summaries graded against a fact checklist |
| Web | Fetching and reading from a local fixture site and from live pages |
| Instruction following | IFEval-style format checks |

It also records prompt and generation speed and VRAM use per configuration.

## Stage 3: replaying real coding briefs

Stage 3 asks whether a local model can follow a detailed written brief across several files, write tests and finish correctly. The seven cases in `fixtures/briefs/` are briefs that were really used to build this project, each with a known starting commit and a reference solution.

For each case the runner:

1. Exports the starting commit into a scratch directory and makes a new one-commit repository, so the agent cannot read the answer from git history.
2. Runs the agent. Local models run through the Codex CLI pointed at `llama-server`, inside a `bwrap` sandbox with a clean home directory. The Cursor baseline runs in the same kind of workspace but is not sandboxed.
3. Grades the result after the agent exits:

| Check | Weight |
|---|---|
| Hidden acceptance tests, copied in after the run | 50 |
| The existing test suite still passes | 15 |
| The agent wrote its own tests and they pass | 10 |
| `ruff check` and `ruff format --check` on touched files | 10 |
| Only files in the case's allowed set were touched | 10 |
| Honest finish: full marks if the hidden tests pass, or if they fail and the final message admits a problem (a keyword check) | 5 |

The hidden tests are black-box: they call only the names and signatures the brief states. I learned that the hard way when a reference test imported a private helper and failed a correct solution that had named it differently.

`--agent reference` and `--agent parent` run the grader against the reference solution and the untouched starting commit, which checks the cases themselves.

[docs/PLAN.md](docs/PLAN.md) and [docs/PLAN-stage3.md](docs/PLAN-stage3.md) are the plans as written before each stage was built, including what went wrong in the first spike. They mention working files that are not in this repository.

## Running it

Requires Python 3.12 or newer and [uv](https://docs.astral.sh/uv/).

```
uv sync
uv run python -m pytest -q      # 105 tests, offline, no GPU or model needed
uv run ruff check .
```

A real benchmark run needs `llama-server` on your PATH, an NVIDIA GPU, and the GGUF files listed in `models.tsv`:

```
export BENCH_GGUF_DIR=~/models/gguf     # the default
scripts/download_models.sh              # resumable
uv run bench models --missing           # which GGUFs are not there yet
uv run bench run --run-id night1 --models <slug>
uv run bench report --run-id night1
uv run bench briefs --run s3 --agent codex --models <slug>
uv run bench briefs-report --run s3
```

Set `BENCH_SANDBOX_HIDE` to a colon-separated list of extra paths to hide from the Codex agent in stage 3, such as a data mount.

## Limits

- Stage 3 cases start from commits in this project's original history. This public repository is a single commit, so `bench briefs` cannot replay them here as published. The briefs, hidden tests and grading code are all in the tree.
- Fit checks and the tuning grid assume one 16 GB NVIDIA card.
- The model list is what I was comparing in late 2026 and will go stale.
- Results are not included. They contain transcripts and machine details.

## Licence

MIT. See [LICENSE](LICENSE).
