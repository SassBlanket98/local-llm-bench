import json

from llmbench.report import category_scores, render_run_report, weighted_overall
from llmbench.tasks import CATEGORY_WEIGHTS, TASKS


def test_weighted_overall():
    suite = {
        "tasks": {
            TASKS[0].ID: [{"score": 1.0}],
            TASKS[7].ID: [{"score": 0.5}],
        }
    }
    cats = category_scores(suite, TASKS)
    overall = weighted_overall(cats, CATEGORY_WEIGHTS)
    assert 0 < overall <= 1.0


def test_report_hit_max_tokens_column(tmp_path):
    model_dir = tmp_path / "model-a"
    model_dir.mkdir()
    tid_a, tid_b = TASKS[0].ID, TASKS[7].ID
    (model_dir / "suite.json").write_text(
        json.dumps(
            {
                "tasks": {
                    tid_a: [{"score": 1.0, "length_stops": 2}],
                    tid_b: [{"score": 0.5, "length_stops": 1}],
                }
            }
        )
    )
    html, md = render_run_report(tmp_path)
    assert "hit max_tokens" in html
    assert "hit max_tokens" in md
    assert "<td>3</td>" in html
    assert md.split("hit max_tokens")[1].count("3") >= 1
