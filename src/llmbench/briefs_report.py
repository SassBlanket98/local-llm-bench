"""Aggregate stage-3 brief run results into report.md."""

from __future__ import annotations

import json
import statistics
from pathlib import Path

from llmbench.briefs import WEIGHTS, load_cases

SUB_KEYS = tuple(WEIGHTS.keys())


def _load_grades(run_dir: Path) -> dict[str, list[dict]]:
    """agent_label -> list of grade records."""
    by_agent: dict[str, list[dict]] = {}
    if not run_dir.is_dir():
        return by_agent
    for agent_dir in sorted(run_dir.iterdir()):
        if not agent_dir.is_dir() or agent_dir.name == "run.log":
            continue
        records: list[dict] = []
        for grade_path in sorted(agent_dir.glob("*/grade.json")):
            try:
                records.append(json.loads(grade_path.read_text()))
            except (json.JSONDecodeError, OSError):
                continue
        if records:
            by_agent[agent_dir.name] = records
    return by_agent


def _mean_total(records: list[dict], case: str) -> float | None:
    totals = [r["total"] * 100 for r in records if r.get("case") == case]
    if not totals:
        return None
    return statistics.mean(totals)


def _hidden_pass_rate(records: list[dict]) -> float:
    if not records:
        return 0.0
    hits = sum(1 for r in records if (r.get("sub") or {}).get("hidden", 0) >= 1.0)
    return hits / len(records)


def _mean_wall_min(records: list[dict]) -> float:
    walls = [float(r.get("wall_s") or 0) for r in records]
    if not walls:
        return 0.0
    return statistics.mean(walls) / 60.0


def _timeout_count(records: list[dict]) -> int:
    return sum(1 for r in records if r.get("timed_out"))


def render_report(run_dir: Path) -> str:
    cases = sorted(load_cases().keys())
    by_agent = _load_grades(run_dir)

    lines = [f"# Briefs run `{run_dir.name}`", ""]

    header = ["agent", *cases, "overall", "hidden_pass", "wall_min", "timeouts"]
    lines.append("| " + " | ".join(header) + " |")
    lines.append("| " + " | ".join(["---"] * len(header)) + " |")

    for agent, records in sorted(by_agent.items()):
        case_means = []
        row_cells = [agent]
        for case in cases:
            m = _mean_total(records, case)
            if m is None:
                row_cells.append("—")
            else:
                case_means.append(m)
                row_cells.append(f"{m:.1f}")
        # Only a run over every case gets a comparable overall score.
        if len(case_means) == len(cases):
            row_cells.append(f"{statistics.mean(case_means):.1f}")
        else:
            row_cells.append(f"incomplete ({len(case_means)}/{len(cases)})")
        row_cells.append(f"{_hidden_pass_rate(records):.0%}")
        row_cells.append(f"{_mean_wall_min(records):.1f}")
        row_cells.append(str(_timeout_count(records)))
        lines.append("| " + " | ".join(row_cells) + " |")

    lines.append("")
    lines.append("## Sub-scores (mean per agent)")
    lines.append("")

    sub_header = ["agent", *SUB_KEYS]
    lines.append("| " + " | ".join(sub_header) + " |")
    lines.append("| " + " | ".join(["---"] * len(sub_header)) + " |")

    for agent, records in sorted(by_agent.items()):
        subs = [r.get("sub") or {} for r in records]
        cells = [agent]
        for key in SUB_KEYS:
            vals = [float(s.get(key, 0)) for s in subs]
            cells.append(f"{statistics.mean(vals):.3f}" if vals else "—")
        lines.append("| " + " | ".join(cells) + " |")

    lines.append("")
    return "\n".join(lines)


def write_report(run_id: str, results_root: Path | None = None) -> Path:
    root = results_root or Path(__file__).resolve().parents[2] / "results"
    run_dir = root / run_id
    md = render_report(run_dir)
    out = run_dir / "report.md"
    out.write_text(md)
    return out
