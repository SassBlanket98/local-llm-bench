import json
from pathlib import Path

from llmbench.run_util import atomic_write_json, load_json_if_complete, suite_complete


def test_atomic_write_and_load(tmp_path: Path):
    p = tmp_path / "out.json"
    atomic_write_json(p, {"a": 1})
    assert load_json_if_complete(p, ("a",)) == {"a": 1}


def test_suite_complete(tmp_path: Path):
    p = tmp_path / "suite.json"
    data = {"tasks": {"t1": [{"score": 1.0}, {"score": 0.5}]}}
    p.write_text(json.dumps(data))
    assert suite_complete(p, ["t1"], 2)
    assert not suite_complete(p, ["t1", "t2"], 2)
