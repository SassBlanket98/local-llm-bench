from pathlib import Path

from llmbench.tasks.t9_agent_repo import _snapshot_tests, _tests_touched


def test_pyc_in_tests_not_tampering(tmp_path: Path):
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_foo.py").write_text("def test_ok(): pass\n")
    before = _snapshot_tests(tmp_path)
    cache = tests / "__pycache__"
    cache.mkdir()
    (cache / "test_foo.cpython-312.pyc").write_bytes(b"\xcb\x00\x00")
    assert not _tests_touched(tmp_path, before)


def test_modified_test_file_is_tampering(tmp_path: Path):
    tests = tmp_path / "tests"
    tests.mkdir()
    p = tests / "test_foo.py"
    p.write_text("def test_ok(): pass\n")
    before = _snapshot_tests(tmp_path)
    p.write_text("def test_ok(): assert False\n")
    assert _tests_touched(tmp_path, before)
