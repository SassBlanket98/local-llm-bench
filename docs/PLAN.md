# llama.cpp bench v2: plan

> This is the plan as written before the work was built, kept for the reasoning. The code is the current behaviour. It refers to working files (`docs/BRIEF-*.md`, `research/`) and commits that are not in the public repository; the per-case briefs are in `fixtures/briefs/`.

Goal: tune, then benchmark, the 20 models in `models.tsv` on one RTX 5070 Ti (16 GB), one model at a time,
unattended overnight, then pick the top 7 with strengths and weaknesses.

## 0. Backend swap (Ollama -> llama-server)
- `server.py`: start `llama-server` for one config (gguf path, ctx, cache-type-k/v, flash-attn on, `--jinja`,
  `-ngl 99`, `--no-mmap`?, port), wait for `/health`, record VRAM from `nvidia-smi` (process + total), kill on exit.
  Fail the config if any layer is not offloaded or free VRAM < 0.5 GiB.
- `core.Chat` talks OpenAI-compatible `/v1/chat/completions` (tools, tool_choice, sampling params, reasoning
  toggle via chat_template_kwargs). Capture `timings` (prompt tok/s, gen tok/s) per call.
- Keep existing grading, sandbox and retries.

## 1. Tuning pass per model ("best settings")
Short calibration set (~8 fast tasks drawn from the suite, 2 reps). Grid, pruned by fit:
- context: 32k (required), 64k, 128k if they fit; KV f16 vs q8_0
- sampling: vendor-recommended (from model card) + 2 variants (e.g. lower temp; thinking on/off if supported)
- system prompt: one shared bench prompt; family-specific tweaks only where the template requires them
Pick: highest calibration score; ties -> faster; then largest context that keeps that score.
Save `tuned.json` per model. Speculative decoding is out of scope for v2 (speed only).

## 2. Full suite per model (with tuned config)
Deterministic graders only; every task N=3 reps; per-task timeout.
| Category | Tasks |
|---|---|
| Single-shot | extract JSON, bash one-liner, commit message, code bugfix (existing t2/t5/t7/t4) |
| Single-task loop | bugfix with test-feedback retries (existing retry mechanism) |
| Multi-step agentic | tool loop over a small repo: list/read/edit/run-tests tools, 5-15 steps, graded by tests passing |
| Tool calling | BFCL-style: single, parallel, multiple-choice-of-tool, no-tool-needed (irrelevance), typed args |
| Document reading | long-doc QA at 8k/16k/32k (needle + multi-fact), summaries graded by fact checklist |
| Web fetch | `fetch_url` against a local static fixture site (deterministic, multi-hop) |
| Web fetch (live) | `fetch_url` on the real web, stable-fact questions; flagged non-deterministic, low weight |
| Instruction following | IFEval-style verifiable constraints (format, length, casing, forbidden words) |
| Performance | prompt tok/s, gen tok/s, TTFT, VRAM, at 2k and 30k prompt |

## 3. Orchestration
`bench run --all`: for each model: tune -> suite -> write `results/<run>/<model>/` (tuned.json, per-task JSON,
transcripts, summary.md) -> kill server -> next. Resumable: skips models with a complete summary.
Logs to `results/<run>/run.log`. Runs as a background job.

## Staging
- Stage 1 (night 1): all 20 models, fit + tuning + suite at 1 rep.
- Stage 2 (night 2): top 10 from stage 1, reusing tuned configs, suite at 3 reps. Top 7 picked from stage 2.

## 4. Aggregation
`bench-report`: per-category scores (mean of reps, with spread), weighted overall, speed; HTML report
(reuse report.py). Top 7 overall + best per category. Narrative strengths/weaknesses written after review.

## Done bar
ruff clean; unit tests for graders and server manager pass; end-to-end run on 2 small models
(lfm2.5-2.6b, qwen3.5-4b) completes, resumes after a kill, and produces the report; Codex review.
