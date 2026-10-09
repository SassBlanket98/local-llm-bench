"""Render a results JSON from `bench` into a self-contained HTML scorecard."""

from __future__ import annotations

import argparse
import html
import json
import statistics
from pathlib import Path

CSS = """
:root{
  --bg:#f5f6f3;--panel:#ffffff;--ink:#1b2026;--muted:#5d6670;--rule:#dde1dc;
  --accent:#2c5d8a;--pass:#1f7a4d;--pass-bg:#e3f2ea;--fail:#b3372d;--fail-bg:#f8e4e1;
  --part:#9a6a00;--part-bg:#f7eed6;--code:#eef0ec;
}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){
  --bg:#12161a;--panel:#1a2026;--ink:#e3e7ea;--muted:#98a2ab;--rule:#2b333a;
  --accent:#7fb0dc;--pass:#6fcf9b;--pass-bg:#173326;--fail:#f08a7e;--fail-bg:#3a1d1a;
  --part:#e3b54e;--part-bg:#342a12;--code:#20272d;color-scheme:dark}}
:root[data-theme="dark"]{
  --bg:#12161a;--panel:#1a2026;--ink:#e3e7ea;--muted:#98a2ab;--rule:#2b333a;
  --accent:#7fb0dc;--pass:#6fcf9b;--pass-bg:#173326;--fail:#f08a7e;--fail-bg:#3a1d1a;
  --part:#e3b54e;--part-bg:#342a12;--code:#20272d;color-scheme:dark}
body{background:var(--bg);color:var(--ink);font:15px/1.55 "IBM Plex Sans",system-ui,sans-serif}
.wrap{max-width:1080px;margin:0 auto;padding-inline:20px;padding-block:32px 64px;
  display:flex;flex-direction:column;gap:36px}
h1,h2,h3{font-family:"Bricolage Grotesque","IBM Plex Sans",sans-serif;text-wrap:balance;margin:0}
h1{font-size:2rem;line-height:1.15;font-weight:700}
h2{font-size:1.3rem;font-weight:650}
h3{font-size:1.05rem;font-weight:650}
.eyebrow{font:600 .72rem/1 "IBM Plex Mono",monospace;letter-spacing:.08em;text-transform:uppercase;
  color:var(--muted)}
.lede{max-width:68ch;color:var(--ink);margin:10px 0 0}
.meta{display:flex;flex-wrap:wrap;gap:6px 18px;color:var(--muted);font:.8rem "IBM Plex Mono",monospace;
  margin-top:14px}
.models{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:14px}
.model{background:var(--panel);border:1px solid var(--rule);border-radius:10px;padding:18px;
  display:flex;flex-direction:column;gap:10px}
.model .name{font:600 1rem "IBM Plex Mono",monospace}
.big{font:700 2.1rem/1 "Bricolage Grotesque",sans-serif;font-variant-numeric:tabular-nums}
.big small{font:500 .85rem "IBM Plex Sans",sans-serif;color:var(--muted);margin-left:6px}
.stats{display:grid;grid-template-columns:auto 1fr;gap:4px 14px;font-size:.85rem;margin:0}
.stats dt{color:var(--muted)} .stats dd{margin:0;font-variant-numeric:tabular-nums}
.scroll{overflow-x:auto;background:var(--panel);border:1px solid var(--rule);border-radius:10px}
table{border-collapse:collapse;width:100%;min-width:560px;font-variant-numeric:tabular-nums}
th,td{padding:11px 14px;text-align:left;border-bottom:1px solid var(--rule);vertical-align:top}
tr:last-child td{border-bottom:0}
th{font:600 .72rem "IBM Plex Mono",monospace;letter-spacing:.06em;text-transform:uppercase;
  color:var(--muted)}
td .what{color:var(--muted);font-size:.82rem;margin-top:2px}
.cell{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.dots{display:flex;gap:4px}
.dot{width:14px;height:14px;border-radius:3px;display:inline-block}
.dot.p{background:var(--pass)} .dot.r{background:transparent;box-shadow:inset 0 0 0 2.5px var(--pass)} .dot.f{background:var(--fail)} .dot.h{background:var(--part)}
.pill{font:600 .75rem "IBM Plex Mono",monospace;padding:2px 8px;border-radius:999px}
.pill.p{background:var(--pass-bg);color:var(--pass)} .pill.f{background:var(--fail-bg);color:var(--fail)}
.pill.h{background:var(--part-bg);color:var(--part)}
.pill.r{background:var(--pass-bg);color:var(--pass);box-shadow:inset 0 0 0 1px var(--pass)}
.score{font:.8rem "IBM Plex Mono",monospace;color:var(--muted)}
.task{display:flex;flex-direction:column;gap:12px}
.task > p{margin:0;color:var(--muted);max-width:75ch}
.runs{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:12px}
.col{display:flex;flex-direction:column;gap:8px;min-width:0}
.col .name{font:600 .85rem "IBM Plex Mono",monospace}
details{background:var(--panel);border:1px solid var(--rule);border-radius:8px}
summary{cursor:pointer;padding:9px 12px;display:flex;gap:10px;align-items:baseline;flex-wrap:wrap;
  list-style:none;font-size:.85rem}
summary::-webkit-details-marker{display:none}
summary:focus-visible{outline:2px solid var(--accent);outline-offset:2px;border-radius:8px}
summary .n{font:600 .75rem "IBM Plex Mono",monospace;color:var(--muted)}
summary .note{flex:1 1 200px;min-width:0;overflow-wrap:anywhere}
summary .t{font:.75rem "IBM Plex Mono",monospace;color:var(--muted)}
pre{margin:0;padding:12px;background:var(--code);border-top:1px solid var(--rule);
  font:.75rem/1.5 "IBM Plex Mono",monospace;white-space:pre-wrap;overflow-wrap:anywhere;
  max-height:420px;overflow:auto;border-radius:0 0 8px 8px}
.legend{display:flex;gap:16px;flex-wrap:wrap;font-size:.8rem;color:var(--muted);align-items:center}
.legend span{display:inline-flex;gap:6px;align-items:center}
@media (max-width:480px){h1{font-size:1.6rem}.runs{grid-template-columns:1fr}}
"""

FONTS = (
    '<link rel="preconnect" href="https://fonts.googleapis.com">'
    '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:'
    "opsz,wght@12..96,600;12..96,700&family=IBM+Plex+Mono:wght@400;600&family=IBM+Plex+Sans:"
    'wght@400;500;600&display=swap">'
)


def _first(run: dict) -> bool:
    return run.get("extra", {}).get("first_passed", run["passed"])


def _kind(run: dict) -> str:
    if run["passed"]:
        return "p" if _first(run) else "r"
    return "h" if run["score"] >= 0.5 else "f"


def _esc(s: object) -> str:
    return html.escape(str(s))


def _fmt_tok_s(v: object) -> str:
    if v is None or v == "?":
        return "?"
    try:
        return f"{round(float(v)):.0f}"
    except (TypeError, ValueError):
        return str(v)


def _fmt_ms(v: object) -> str:
    if v is None or v == "?":
        return "?"
    try:
        return f"{float(v):.1f}"
    except (TypeError, ValueError):
        return str(v)


def render(data: dict, verdict: str = "") -> str:
    models = list(data["models"])
    tasks = data["tasks"]
    e = _esc

    cards = []
    for m in models:
        md = data["models"][m]
        runs = [r for t in tasks for r in md["tasks"][t["id"]]]
        passes = sum(r["passed"] for r in runs)
        firsts = sum(_first(r) for r in runs)
        toks = [r["tok_s"] for r in runs if r["tok_s"]]
        secs = [r["seconds"] for r in runs]
        place = md.get("placement", {})
        cards.append(
            f'<div class="model"><div class="name">{e(m)}</div>'
            f'<div class="big">{passes}/{len(runs)}<small>passed with feedback</small></div>'
            f'<dl class="stats"><dt>First try</dt><dd>{firsts}/{len(runs)} passed</dd><dt>Mean score</dt><dd>{statistics.mean(r["score"] for r in runs):.2f}</dd>'
            f"<dt>Generation</dt><dd>{statistics.median(toks) if toks else 0:.0f} tok/s median</dd>"
            f"<dt>Wall time</dt><dd>{sum(secs):.0f}s total, {statistics.median(secs):.1f}s median/run</dd>"
            f"<dt>Memory</dt><dd>{place.get('size_gb', '?')} GB, {place.get('gpu_pct', '?')}% on GPU</dd>"
            "</dl></div>"
        )

    rows = []
    for t in tasks:
        cells = []
        for m in models:
            runs = data["models"][m]["tasks"][t["id"]]
            p = sum(r["passed"] for r in runs)
            p1 = sum(_first(r) for r in runs)
            kind = "p" if p == len(runs) else "f" if p == 0 else "h"
            dots = "".join(f'<span class="dot {_kind(r)}"></span>' for r in runs)
            cells.append(
                f'<td><div class="cell"><span class="dots">{dots}</span>'
                f'<span class="pill {kind}">{p}/{len(runs)}</span>'
                f'<span class="score">first try {p1}/{len(runs)} · avg {statistics.mean(r["score"] for r in runs):.2f}</span></div></td>'
            )
        rows.append(
            f'<tr><td><a href="#{e(t["id"])}">{e(t["title"])}</a><div class="what">{e(t["tests"])}</div></td>'
            + "".join(cells)
            + "</tr>"
        )

    sections = []
    for t in tasks:
        cols = []
        for m in models:
            items = []
            for i, r in enumerate(data["models"][m]["tasks"][t["id"]], 1):
                k = _kind(r)
                label = {"p": "PASS", "r": "PASS ON RETRY", "h": "PARTIAL", "f": "FAIL"}[k]
                items.append(
                    f'<details><summary><span class="n">run {i}</span><span class="pill {k}">{label}</span>'
                    f'<span class="note">{e(r["notes"])}</span>'
                    f'<span class="t">{r["seconds"]:.1f}s · {r["tok_s"]:.0f} tok/s</span></summary>'
                    f"<pre>{e(r['output'])}</pre></details>"
                )
            cols.append(f'<div class="col"><div class="name">{e(m)}</div>{"".join(items)}</div>')
        sections.append(
            f'<section class="task" id="{e(t["id"])}"><h3>{e(t["title"])}</h3><p>{e(t["tests"])}</p>'
            f'<div class="runs">{"".join(cols)}</div></section>'
        )

    head = "".join(f"<th>{e(m)}</th>" for m in models)
    verdict_html = f'<p class="lede">{e(verdict)}</p>' if verdict else ""
    return f"""<title>Local Model Bake-off</title>
{FONTS}
<style>{CSS}</style>
<div class="wrap">
<header>
  <div class="eyebrow">Grunt-work candidates · RTX 5070 Ti 16 GB</div>
  <h1>Local model bake-off</h1>
  {verdict_html}
  <div class="meta"><span>run {e(data["started"])}</span><span>num_ctx {data["num_ctx"]}</span>
  <span>{data["runs"]} runs per task</span><span>{data.get("retries", 0)} retry after checker feedback</span><span>graded automatically, no LLM judge</span></div>
</header>
<section class="models">{"".join(cards)}</section>
<section class="task">
  <h2>Scorecard</h2>
  <div class="legend"><span><i class="dot p"></i>pass first try</span><span><i class="dot r"></i>pass after feedback</span><span><i class="dot h"></i>partial (score ≥ 0.5)</span>
  <span><i class="dot f"></i>fail</span><span>one square per run</span></div>
  <div class="scroll"><table><thead><tr><th>Task</th>{head}</tr></thead><tbody>{"".join(rows)}</tbody></table></div>
</section>
<section class="task"><h2>Run by run</h2><p>Open any run to see what the model actually said.
Tool-use runs list every tool call; the bash runs show what the script printed.
Feedback is only what a real checker could say (test output, crashes, lint, invalid JSON),
never the expected answer.</p></section>
{"".join(sections)}
</div>
"""


def suite_length_stops(suite: dict) -> int:
    """Sum of per-run length_stops across a model's suite.json."""
    return sum(
        int(r.get("length_stops") or 0)
        for runs in (suite.get("tasks") or {}).values()
        for r in runs
    )


def category_scores(suite: dict, tasks) -> dict[str, dict[str, float]]:
    """Mean and min-max per category for one model suite."""
    from llmbench.tasks import TASKS

    tasks = tasks or TASKS
    by_cat: dict[str, list[float]] = {}
    for task in tasks:
        runs = suite.get("tasks", {}).get(task.ID) or []
        if not runs:
            continue
        # Skipped runs (e.g. live web with the network down) say nothing about the model.
        scores = [r["score"] for r in runs if not (r.get("extra") or {}).get("skipped")]
        if scores:
            by_cat.setdefault(task.CATEGORY, []).extend(scores)
    out: dict[str, dict[str, float]] = {}
    for cat, scores in by_cat.items():
        out[cat] = {
            "mean": statistics.mean(scores),
            "min": min(scores),
            "max": max(scores),
        }
    return out


def weighted_overall(cat_means: dict[str, dict[str, float]], weights: dict[str, int]) -> float:
    total = 0.0
    wsum = 0.0
    for cat, w in weights.items():
        if cat in cat_means:
            total += w * cat_means[cat]["mean"]
            wsum += w
    return total / wsum if wsum else 0.0


def render_run_report(run_dir: Path, top: int = 7) -> tuple[str, str]:
    from llmbench.run_util import load_json_if_complete
    from llmbench.tasks import CATEGORY_WEIGHTS, TASKS

    models: list[str] = []
    suites: dict[str, dict] = {}
    perf: dict[str, dict] = {}
    for d in sorted(run_dir.iterdir()):
        if not d.is_dir() or d.name.startswith("."):
            continue
        s = load_json_if_complete(d / "suite.json", ("tasks",))
        if s:
            models.append(d.name)
            suites[d.name] = s
        p = load_json_if_complete(d / "perf.json", ("prompts",))
        if p:
            perf[d.name] = p

    ranked = sorted(
        models,
        key=lambda m: weighted_overall(category_scores(suites[m], TASKS), CATEGORY_WEIGHTS),
        reverse=True,
    )

    md_lines = [f"# Run report `{run_dir.name}`\n", "## Overall ranking\n"]
    md_lines.append("| Rank | Model | Weighted | hit max_tokens |")
    md_lines.append("| ---: | --- | ---: | ---: |")
    for i, m in enumerate(ranked[:top], 1):
        cats = category_scores(suites[m], TASKS)
        overall = weighted_overall(cats, CATEGORY_WEIGHTS)
        md_lines.append(f"| {i} | {m} | {overall:.3f} | {suite_length_stops(suites[m])} |")

    md_lines.append("\n## Category means (min–max over reps)\n")
    for m in ranked[:top]:
        md_lines.append(f"\n### {m}\n")
        for cat, stats in sorted(category_scores(suites[m], TASKS).items()):
            md_lines.append(f"- {cat}: {stats['mean']:.3f} ({stats['min']:.2f}–{stats['max']:.2f})")

    md_lines.append("\n## Performance\n")
    for m in ranked[:top]:
        p = perf.get(m, {})
        p2 = (p.get("prompts") or {}).get("2k") or {}
        p30 = (p.get("prompts") or {}).get("30k") or {}
        md_lines.append(
            f"- {m}: 2k prompt {_fmt_tok_s(p2.get('prompt_tok_s', '?'))} tok/s, "
            f"gen {_fmt_tok_s(p2.get('gen_tok_s', '?'))} tok/s, "
            f"TTFT {_fmt_ms(p2.get('ttft_ms', '?'))} ms; "
            f"30k prompt {_fmt_tok_s(p30.get('prompt_tok_s', '?'))} tok/s"
        )

    md = "\n".join(md_lines) + "\n"

    rows = []
    for m in ranked:
        cats = category_scores(suites[m], TASKS)
        overall = weighted_overall(cats, CATEGORY_WEIGHTS)
        rows.append(
            f"<tr><td>{_esc(m)}</td><td>{overall:.3f}</td>"
            + "".join(
                f"<td>{cats[c]['mean']:.2f}</td>" if c in cats else "<td>—</td>"
                for c in sorted(CATEGORY_WEIGHTS)
            )
            + f"<td>{suite_length_stops(suites[m])}</td></tr>"
        )

    headers = "".join(f"<th>{_esc(c)}</th>" for c in sorted(CATEGORY_WEIGHTS))
    headers += "<th>hit max_tokens</th>"
    html = f"""<title>llmbench {_esc(run_dir.name)}</title>
<style>{CSS}</style>
<div class="wrap">
<h1>Run {_esc(run_dir.name)}</h1>
<p class="lede">Weighted category scores; perf at 2k/30k prompt.</p>
<div class="scroll"><table>
<thead><tr><th>Model</th><th>Weighted</th>{headers}</tr></thead>
<tbody>{"".join(rows)}</tbody>
</table></div>
<pre>{_esc(md)}</pre>
</div>"""
    return html, md


def write_report_md(md: str, path: Path) -> None:
    path.write_text(md)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("results", type=Path)
    ap.add_argument("-o", "--out", type=Path, default=Path("report.html"))
    ap.add_argument("--verdict", default="", help="one-paragraph summary shown under the title")
    args = ap.parse_args()
    args.out.write_text(render(json.loads(args.results.read_text()), args.verdict))
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
