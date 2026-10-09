1. **t9_agent_repo crash** (`'utf-8' codec can't decode byte 0xcb`): the tests/ snapshot uses
   `read_text()` and hits pytest's `__pycache__/*.pyc`. Snapshot with `read_bytes()`, skip
   `__pycache__` dirs and `*.pyc`; run pytest with `-p no:cacheprovider` and
   `PYTHONDONTWRITEBYTECODE=1`. Unit test: a pyc file in tests/ does not count as tampering.


## Interface (acceptance tests call exactly these)
- `llmbench.tasks.t9_agent_repo._snapshot_tests(root: Path) -> dict[str, bytes]`: relative path -> bytes for every file under `root/tests`, skipping `__pycache__` dirs and `*.pyc`.
- `llmbench.tasks.t9_agent_repo._tests_touched(root: Path, before: dict[str, bytes]) -> bool`: True if any snapshotted file changed, disappeared, or a new non-cache file appeared.
- `llmbench.tasks.t9_agent_repo._pytest_cmd() -> list[str]` and `_pytest_env() -> dict[str, str]`: the pytest command and extra env used by both `run_tests` and final grading.
