"""bench run / bench report — llama-server bake-off orchestrator."""

from __future__ import annotations

import argparse
import json
import statistics
import time
import traceback
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from llmbench import core
from llmbench.briefs import cmd_briefs
from llmbench.briefs_report import write_report
from llmbench.manifest import gguf_path, load_manifest
from llmbench.perf import run_perf
from llmbench.presets import preset_for
from llmbench.report import render_run_report
from llmbench.run_util import atomic_write_json, load_json_if_complete, suite_complete
from llmbench.server import (
    LlamaServer,
    ServerConfig,
    _vram_mib,
    probe_fit,
    server_config_from_dict,
)
from llmbench.tasks import CATEGORY_WEIGHTS, TASKS
from llmbench.tune import run_tune

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RESULTS = PROJECT_ROOT / "results"
TASK_TIMEOUT_S = 20 * 60


def _log_run(run_dir: Path, msg: str) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    line = f"{datetime.now().astimezone().isoformat(timespec='seconds')} {msg}\n"
    with (run_dir / "run.log").open("a") as f:
        f.write(line)


def _apply_tuned(slug: str, model_dir: Path) -> tuple[ServerConfig, dict]:
    tuned = json.loads((model_dir / "tuned.json").read_text())
    cfg = server_config_from_dict({**tuned["server"], "slug": slug})
    core.CONFIG["sampling"] = tuned.get("sampling") or {}
    return cfg, tuned


def _run_task(task, model: str, rep: int) -> tuple[dict, str]:
    t0 = time.monotonic()
    core.clear_task_chats()
    # Enforced in Chat.send: a thread can't be killed, so the task stops at its next request.
    core.DEADLINE = t0 + TASK_TIMEOUT_S
    try:
        r = task.run(model, False)
    except core.TaskTimeout:
        r = core.Result(False, 0.0, f"task timeout {TASK_TIMEOUT_S // 60}m", "timeout")
    except Exception as e:  # noqa: BLE001 - a crash is a fail, not a reason to stop the run
        r = core.Result(False, 0.0, f"harness error: {e}", traceback.format_exc())
    finally:
        core.DEADLINE = None
    r.seconds = r.seconds or round(time.monotonic() - t0, 1)
    length_stops = sum(c.length_stops for c in core.TASK_CHATS)
    transcript = core.format_task_transcript(r)
    record = asdict(r) | {
        "tok_s": round(r.tok_s, 1),
        "category": task.CATEGORY,
        "length_stops": length_stops,
    }
    return record, transcript


def _write_summary(model_dir: Path, slug: str, suite: dict) -> None:
    lines = [f"# {slug} summary\n"]
    for tid, runs in suite.get("tasks", {}).items():
        mean = statistics.mean(r["score"] for r in runs)
        lines.append(f"- **{tid}**: mean score {mean:.3f} ({len(runs)} reps)")
    (model_dir / "summary.md").write_text("\n".join(lines) + "\n")


MIN_FREE_VRAM_MIB = 14000


def _wait_for_free_vram(run_dir: Path, slug: str, timeout_s: int = 600) -> None:
    """A leftover server would make every fit probe OOM and mark models unfit; wait it out."""
    deadline = time.monotonic() + timeout_s
    while True:
        used, total = _vram_mib()
        if total - used >= MIN_FREE_VRAM_MIB:
            return
        if time.monotonic() > deadline:
            _log_run(run_dir, f"WARNING only {total - used} MiB free before {slug}; running anyway")
            return
        time.sleep(15)


def cmd_run(args: argparse.Namespace) -> None:
    run_dir = RESULTS / args.run_id
    manifest = load_manifest(Path(args.manifest))
    if args.models:
        want = set(args.models.split(","))
        manifest = [m for m in manifest if m["slug"] in want]

    reps = args.reps if args.reps is not None else (1 if args.stage == 1 else 3)
    core.RETRIES = 1

    for row in manifest:
        slug = row["slug"]
        model_dir = run_dir / slug
        model_dir.mkdir(parents=True, exist_ok=True)
        gguf = gguf_path(row)
        _log_run(run_dir, f"start {slug}")
        _wait_for_free_vram(run_dir, slug)

        fit_path = model_dir / "fit.json"
        if load_json_if_complete(fit_path, ("run_config",)):
            fit = json.loads(fit_path.read_text())
            _log_run(run_dir, f"skip fit {slug}")
        else:
            fit = probe_fit(slug, gguf, model_dir)
        if fit["run_config"].get("unfit"):
            _log_run(run_dir, f"skip unfit {slug}")
            continue

        rc = fit["run_config"]
        base_cfg = ServerConfig(
            slug=slug,
            gguf_path=gguf,
            ctx=int(rc["ctx"]),
            cache_type=str(rc["cache_type"]),
            reasoning="off",
        )

        if args.reuse_tuned:
            src = RESULTS / args.reuse_tuned / slug / "tuned.json"
            if src.is_file():
                tuned = json.loads(src.read_text())
                atomic_write_json(model_dir / "tuned.json", tuned)
                _log_run(run_dir, f"reuse tuned from {args.reuse_tuned}")
            else:
                run_tune(slug, base_cfg, model_dir, preset_for(slug))
        elif not load_json_if_complete(model_dir / "tuned.json", ("server",)):
            try:
                run_tune(slug, base_cfg, model_dir, preset_for(slug))
            except Exception as e:  # noqa: BLE001
                _log_run(run_dir, f"tune failed for {slug}: {e}; using vendor preset")
                preset = preset_for(slug)
                reasoning = "auto" if preset.get("thinking") == "toggle" else "off"
                from llmbench.server import config_to_dict

                atomic_write_json(
                    model_dir / "tuned.json",
                    {
                        "slug": slug,
                        "variant": "vendor_fallback",
                        "server": {
                            **config_to_dict(base_cfg),
                            "reasoning": reasoning,
                            "gguf_path": str(base_cfg.gguf_path),
                        },
                        "sampling": preset.get("sampling") or {},
                    },
                )
        else:
            _log_run(run_dir, f"skip tune {slug}")

        cfg, tuned = _apply_tuned(slug, model_dir)
        suite_path = model_dir / "suite.json"
        task_ids = [t.ID for t in TASKS]

        if suite_complete(suite_path, task_ids, reps):
            suite = json.loads(suite_path.read_text())
            _log_run(run_dir, f"skip suite {slug}")
            _write_summary(model_dir, slug, suite)
        else:
            suite = load_json_if_complete(suite_path) or {
                "slug": slug,
                "reps": reps,
                "tasks": {},
            }
            with LlamaServer(cfg, model_dir, tag="suite") as srv:
                core.CONFIG["base_url"] = srv.base_url
                core.CONFIG["model"] = cfg.alias
                for task in TASKS:
                    runs = suite["tasks"].get(task.ID, [])
                    while len(runs) < reps:
                        rep = len(runs) + 1
                        _log_run(run_dir, f"suite {slug} {task.ID} rep {rep}")
                        rdict, transcript = _run_task(task, cfg.alias, rep)
                        runs.append(rdict)
                        (model_dir / "transcripts" / f"{task.ID}-{rep}.txt").parent.mkdir(
                            parents=True, exist_ok=True
                        )
                        (model_dir / "transcripts" / f"{task.ID}-{rep}.txt").write_text(transcript)
                        suite["tasks"][task.ID] = runs
                        atomic_write_json(suite_path, suite)

            _write_summary(model_dir, slug, suite)

        perf_path = model_dir / "perf.json"
        if load_json_if_complete(perf_path, ("prompts",)):
            _log_run(run_dir, f"skip perf {slug}")
        else:
            with LlamaServer(cfg, model_dir, tag="perf") as srv:
                core.CONFIG["base_url"] = srv.base_url
                core.CONFIG["model"] = cfg.alias
                run_perf(perf_path, srv.vram_used_mib, srv.vram_free_mib, srv.all_on_gpu)

        _log_run(run_dir, f"done {slug}")


def cmd_report(args: argparse.Namespace) -> None:
    run_dir = RESULTS / args.run_id
    if args.pick is not None:
        ranked = _rank_models(run_dir)
        print(",".join(ranked[: args.pick]))
        return

    html, md = render_run_report(run_dir, top=args.top)
    html_path = run_dir / "report.html"
    md_path = run_dir / "report.md"
    html_path.write_text(html)
    md_path.write_text(md)
    print(f"wrote {html_path} and {md_path}")


def cmd_models(args: argparse.Namespace) -> None:
    manifest = load_manifest(Path(args.manifest))
    gguf_dir = Path(args.gguf_dir) if args.gguf_dir else None
    rows = []
    for row in manifest:
        gguf = gguf_path(row, gguf_dir)
        rows.append((row["slug"], row["gguf_file"], gguf.is_file()))
    if args.missing:
        rows = [r for r in rows if not r[2]]
    if not rows:
        print("no missing models" if args.missing else "no models")
        return
    for slug, gguf_file, exists in rows:
        print(f"{slug}\t{gguf_file}\t{'yes' if exists else 'no'}")


def _rank_models(run_dir: Path) -> list[str]:
    scores: list[tuple[str, float]] = []
    for model_dir in sorted(run_dir.iterdir()):
        if not model_dir.is_dir():
            continue
        suite_path = model_dir / "suite.json"
        data = load_json_if_complete(suite_path, ("tasks",))
        if not data:
            continue
        scores.append((model_dir.name, _weighted_score(data)))
    scores.sort(key=lambda x: -x[1])
    return [s for s, _ in scores]


def _weighted_score(suite: dict) -> float:
    by_cat: dict[str, list[float]] = {}
    for task in TASKS:
        runs = suite.get("tasks", {}).get(task.ID) or []
        if not runs:
            continue
        by_cat.setdefault(task.CATEGORY, []).append(statistics.mean(r["score"] for r in runs))
    total_w = 0.0
    total = 0.0
    for cat, w in CATEGORY_WEIGHTS.items():
        if cat in by_cat:
            total += w * statistics.mean(by_cat[cat])
            total_w += w
    return total / total_w if total_w else 0.0


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    run_p = sub.add_parser("run", help="fit, tune, suite and perf per model")
    run_p.add_argument("--run-id", required=True)
    run_p.add_argument("--models", default="")
    run_p.add_argument("--manifest", default=str(PROJECT_ROOT / "models.tsv"))
    run_p.add_argument("--reps", type=int, default=None)
    run_p.add_argument("--stage", type=int, default=1, choices=(1, 2))
    run_p.add_argument("--reuse-tuned", default="")

    rep_p = sub.add_parser("report", help="aggregate HTML/MD report")
    rep_p.add_argument("--run-id", required=True)
    rep_p.add_argument("--top", type=int, default=7)
    rep_p.add_argument("--pick", type=int, default=None)

    briefs_p = sub.add_parser("briefs", help="run stage-3 brief cases")
    briefs_p.add_argument("--run", required=True, dest="run_id")
    briefs_p.add_argument(
        "--agent", required=True, choices=("codex", "cursor", "reference", "parent")
    )
    briefs_p.add_argument("--models", default="")
    briefs_p.add_argument("--cases", default="")
    briefs_p.add_argument("--reps", type=int, default=2)
    briefs_p.add_argument("--timeout-min", type=int, default=60)

    briefs_rep_p = sub.add_parser("briefs-report", help="aggregate brief run report.md")
    briefs_rep_p.add_argument("--run", required=True, dest="run_id")

    models_p = sub.add_parser("models", help="list models and whether their GGUF exists")
    models_p.add_argument("--gguf-dir", default="", help="override the GGUF directory")
    models_p.add_argument(
        "--missing", action="store_true", help="only show models whose GGUF is missing"
    )

    args = ap.parse_args()
    if args.cmd == "run":
        cmd_run(args)
    elif args.cmd == "report":
        cmd_report(args)
    elif args.cmd == "briefs":
        cases = [c.strip() for c in args.cases.split(",") if c.strip()] or None
        cmd_briefs(
            args.run_id,
            args.agent,
            models=args.models,
            cases_filter=cases,
            reps=args.reps,
            timeout_min=args.timeout_min,
        )
    elif args.cmd == "briefs-report":
        path = write_report(args.run_id)
        print(f"wrote {path}")
    elif args.cmd == "models":
        cmd_models(args)
    else:
        cmd_report(args)


if __name__ == "__main__":
    main()
