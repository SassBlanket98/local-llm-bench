"""Per-model calibration tuning over sampling and reasoning variants."""

from __future__ import annotations

import copy
import statistics
import time
from pathlib import Path
from typing import Any

from llmbench import core
from llmbench.presets import preset_for
from llmbench.run_util import atomic_write_json, load_json_if_complete
from llmbench.server import LlamaServer, ServerConfig, config_to_dict
from llmbench.tasks import t2_extract, t4_bugfix, t8_toolcall, t9_agent_repo, t10_docqa, t14_ifeval

CALIBRATION = [
    (t8_toolcall, True),
    (t14_ifeval, True),
    (t2_extract, False),
    (t4_bugfix, False),
    (t10_docqa, True),
    (t9_agent_repo, True),
]

REPS = 2


def _default_reasoning(thinking: str) -> tuple[str, str | None]:
    if thinking == "effort":
        return "on", "medium"
    if thinking == "always":
        return "on", None
    if thinking == "none":
        return "off", None
    return "auto", None


def _flip_reasoning(reasoning: str) -> str:
    return {"auto": "off", "off": "auto", "on": "off"}.get(reasoning, "off")


def build_variants(preset: dict[str, Any]) -> list[dict[str, Any]]:
    thinking = preset.get("thinking", "none")
    sampling = copy.deepcopy(preset.get("sampling") or {})
    reasoning, effort = _default_reasoning(thinking)
    variants: list[dict[str, Any]] = [
        {
            "name": "vendor",
            "sampling": sampling,
            "reasoning": reasoning,
            "reasoning_effort": effort,
        },
        {
            "name": "low_temp",
            "sampling": {**sampling, "temperature": 0.2},
            "reasoning": reasoning,
            "reasoning_effort": effort,
        },
    ]
    if thinking == "toggle":
        flipped = _flip_reasoning(reasoning)
        variants.append(
            {
                "name": f"reasoning_{flipped}",
                "sampling": copy.deepcopy(sampling),
                "reasoning": flipped,
                "reasoning_effort": None,
            }
        )
    if thinking == "effort":
        variants.extend(
            [
                {
                    "name": "effort_low",
                    "sampling": copy.deepcopy(sampling),
                    "reasoning": "on",
                    "reasoning_effort": "low",
                },
                {
                    "name": "effort_high",
                    "sampling": copy.deepcopy(sampling),
                    "reasoning": "on",
                    "reasoning_effort": "high",
                },
            ]
        )
    return variants


CALIBRATION_TASK_TIMEOUT_S = 600


def _apply_config(base_url: str, model: str, sampling: dict[str, Any]) -> None:
    core.CONFIG["base_url"] = base_url
    core.CONFIG["model"] = model
    core.CONFIG["sampling"] = sampling


def _run_calibration(model: str) -> tuple[float, float]:
    scores: list[float] = []
    gen_rates: list[float] = []
    for task, cal in CALIBRATION:
        core.clear_task_chats()
        core.DEADLINE = time.monotonic() + CALIBRATION_TASK_TIMEOUT_S
        try:
            r = task.run(model, calibration=cal)
        except core.TaskTimeout:
            r = core.Result(False, 0.0, "calibration task timeout", "timeout")
        except Exception as e:  # noqa: BLE001 - calibration must not abort tuning
            r = core.Result(False, 0.0, f"calibration error: {e}", str(e))
        finally:
            core.DEADLINE = None
        scores.append(r.score)
        if r.eval_seconds > 0:
            gen_rates.append(r.tok_s)
    mean_score = statistics.mean(scores) if scores else 0.0
    gen_tok_s = statistics.mean(gen_rates) if gen_rates else 0.0
    return mean_score, gen_tok_s


def run_tune(
    slug: str,
    base_cfg: ServerConfig,
    out_dir: Path,
    preset: dict[str, Any] | None = None,
) -> dict[str, Any]:
    tune_path = out_dir / "tune.json"
    tuned_path = out_dir / "tuned.json"
    existing = load_json_if_complete(tune_path, ("variants",))
    if existing and load_json_if_complete(tuned_path, ("server",)):
        return existing

    preset = preset or preset_for(slug)
    variants = build_variants(preset)
    results: list[dict[str, Any]] = []

    for var in variants:
        cfg = ServerConfig(
            slug=slug,
            gguf_path=base_cfg.gguf_path,
            ctx=base_cfg.ctx,
            cache_type=base_cfg.cache_type,
            reasoning=var["reasoning"],
            reasoning_effort=var.get("reasoning_effort"),
            extra_args=list(base_cfg.extra_args),
        )
        rep_scores: list[float] = []
        rep_speeds: list[float] = []
        for rep in range(REPS):
            tag = f"tune-{var['name']}-r{rep + 1}"
            with LlamaServer(cfg, out_dir, tag=tag) as srv:
                _apply_config(srv.base_url, cfg.alias, var["sampling"])
                score, gen_tok_s = _run_calibration(cfg.alias)
                rep_scores.append(score)
                rep_speeds.append(gen_tok_s)
        results.append(
            {
                "name": var["name"],
                "sampling": var["sampling"],
                "reasoning": var["reasoning"],
                "reasoning_effort": var.get("reasoning_effort"),
                "scores": rep_scores,
                "mean_score": statistics.mean(rep_scores),
                "gen_tok_s": statistics.mean(rep_speeds),
            }
        )

    results.sort(key=lambda r: (-r["mean_score"], -r["gen_tok_s"]))
    winner = results[0]
    # tie-break within 0.02 by gen tok/s
    top = winner["mean_score"]
    tied = [r for r in results if abs(r["mean_score"] - top) <= 0.02]
    if len(tied) > 1:
        winner = max(tied, key=lambda r: r["gen_tok_s"])

    win_var = next(v for v in variants if v["name"] == winner["name"])
    tuned = {
        "slug": slug,
        "variant": winner["name"],
        "mean_score": winner["mean_score"],
        "server": {
            **config_to_dict(
                ServerConfig(
                    slug=slug,
                    gguf_path=base_cfg.gguf_path,
                    ctx=base_cfg.ctx,
                    cache_type=base_cfg.cache_type,
                    reasoning=win_var["reasoning"],
                    reasoning_effort=win_var.get("reasoning_effort"),
                )
            ),
            "gguf_path": str(base_cfg.gguf_path),
        },
        "sampling": win_var["sampling"],
    }
    payload = {"slug": slug, "variants": results, "winner": winner["name"]}
    atomic_write_json(tune_path, payload)
    atomic_write_json(tuned_path, tuned)
    return payload
