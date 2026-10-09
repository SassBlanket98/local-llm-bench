from pathlib import Path

from llmbench.tasks.t9_agent_repo import _pytest_cmd, _pytest_env, _snapshot_tests, _tests_touched


def _repo(tmp_path: Path) -> Path:
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_foo.py").write_text("def test_ok(): pass\n")
    return tmp_path


def test_pyc_in_tests_not_tampering(tmp_path: Path):
    root = _repo(tmp_path)
    before = _snapshot_tests(root)
    cache = root / "tests" / "__pycache__"
    cache.mkdir()
    (cache / "test_foo.cpython-312.pyc").write_bytes(b"\xcb\x00\x00")
    (root / "tests" / "stray.pyc").write_bytes(b"\xcb\x01")
    assert not _tests_touched(root, before)


def test_snapshot_skips_cache_and_reads_binary(tmp_path: Path):
    root = _repo(tmp_path)
    (root / "tests" / "data.bin").write_bytes(b"\xcb\xff\x00")
    cache = root / "tests" / "__pycache__"
    cache.mkdir()
    (cache / "x.pyc").write_bytes(b"\xcb")
    snap = _snapshot_tests(root)
    assert not any("__pycache__" in k or k.endswith(".pyc") for k in snap)
    assert any(k.endswith("data.bin") for k in snap)


def test_modified_test_file_is_tampering(tmp_path: Path):
    root = _repo(tmp_path)
    before = _snapshot_tests(root)
    (root / "tests" / "test_foo.py").write_text("def test_ok(): assert False\n")
    assert _tests_touched(root, before)


def test_new_or_deleted_test_file_is_tampering(tmp_path: Path):
    root = _repo(tmp_path)
    before = _snapshot_tests(root)
    (root / "tests" / "test_new.py").write_text("def test_x(): pass\n")
    assert _tests_touched(root, before)
    (root / "tests" / "test_new.py").unlink()
    (root / "tests" / "test_foo.py").unlink()
    assert _tests_touched(root, before)


def test_pytest_runs_without_cache_or_bytecode():
    cmd = _pytest_cmd()
    assert "pytest" in cmd
    i = cmd.index("-p")
    assert cmd[i + 1] == "no:cacheprovider"
    assert _pytest_env().get("PYTHONDONTWRITEBYTECODE") == "1"
