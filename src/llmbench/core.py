"""OpenAI-compatible client, result type, sandbox and parsing helpers shared by all tasks."""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

# Set by the orchestrator before tasks run (base_url, model alias, sampling, limits).
CONFIG: dict[str, Any] = {
    "base_url": "http://127.0.0.1:8080",
    "model": "bench",
    "sampling": {},
    "max_tokens": 16384,  # thinking models need room; the task deadline caps runaways
    "timeout": 600.0,
}

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SANDBOX_WORK = "/tmp/work"  # where the workdir appears inside the sandbox (on its tmpfs)
# Extra attempts a task may make after checker feedback (test output, errors, lint). Set by the
# CLI. Feedback never reveals the expected answer, only what a real orchestrator could see.
RETRIES = 0


@dataclass
class Result:
    passed: bool
    score: float  # 0..1
    notes: str
    output: str  # final model text, for eyeballing
    seconds: float = 0.0
    eval_tokens: int = 0
    eval_seconds: float = 0.0
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def tok_s(self) -> float:
        return self.eval_tokens / self.eval_seconds if self.eval_seconds else 0.0


@dataclass
class Grade:
    passed: bool
    score: float
    notes: str
    output: str
    # What a checker could tell the model (errors, failing visible tests, lint). None means a
    # real orchestrator would have nothing actionable to say, so no retry happens.
    feedback: str | None = None


def call_args(tool_call: dict[str, Any]) -> dict[str, Any]:
    fn = tool_call.get("function") or tool_call
    raw = fn.get("arguments", {})
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        return json.loads(raw or "{}")
    return {}


# Wall-clock deadline (time.monotonic()) for the running task; set by the runner.
DEADLINE: float | None = None


class TaskTimeout(Exception):
    """Raised by Chat.send once the task's deadline has passed."""


# Populated by each Chat during a task; cleared by the runner before every task run.
TASK_CHATS: list[Chat] = []


def clear_task_chats() -> None:
    TASK_CHATS.clear()


def _trunc_text(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "...[truncated]"


def _format_message(msg: dict[str, Any]) -> str:
    role = msg.get("role", "?")
    lines = [f"=== {role} ==="]
    content = msg.get("content")
    if content:
        cap = 2000 if role == "tool" else None
        text = str(content)
        lines.append(_trunc_text(text, cap) if cap else text)
    reasoning = msg.get("reasoning_content")
    if reasoning:
        lines.append(_trunc_text(str(reasoning), 4000))
    tool_calls = msg.get("tool_calls")
    if tool_calls:
        lines.append(json.dumps(tool_calls, indent=2))
    name = msg.get("name")
    if name and role == "tool":
        lines.insert(1, f"tool: {name}")
    return "\n".join(lines)


def format_task_transcript(result: Result) -> str:
    """Full conversation(s) for a task run plus graded result notes/output."""
    parts: list[str] = []
    for i, chat in enumerate(TASK_CHATS, 1):
        parts.append(f"--- chat {i} ---")
        for idx, msg in enumerate(chat.messages):
            # History omits reasoning (it must not be sent back), so re-attach it for the log.
            reasoning, finish = chat.turn_meta.get(idx, (None, None))
            text = _format_message(msg | {"reasoning_content": reasoning} if reasoning else msg)
            if finish == "length":
                text += "\n[finish_reason=length: hit max_tokens before finishing]"
            parts.append(text)
    parts.append(f"=== result ===\nnotes: {result.notes}\noutput:\n{result.output}")
    return "\n\n".join(parts)


class Chat:
    """One conversation against llama-server's /v1/chat/completions."""

    def __init__(self, model: str | None = None) -> None:
        self.model = model or str(CONFIG["model"])
        self.messages: list[dict[str, Any]] = []
        # message index -> (reasoning_content, finish_reason) for assistant turns
        self.turn_meta: dict[int, tuple[str | None, str | None]] = {}
        self.length_stops = 0
        TASK_CHATS.append(self)
        self.eval_tokens = 0
        self.eval_seconds = 0.0
        self.last_prompt_ms = 0.0
        self.last_gen_tok_s = 0.0
        self.last_prompt_tok_s = 0.0
        self.started = time.monotonic()
        timeout = float(CONFIG.get("timeout", 600))
        self._http = httpx.Client(base_url=str(CONFIG["base_url"]), timeout=timeout)

    def _sampling_body(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for k, v in (CONFIG.get("sampling") or {}).items():
            if v is not None:
                out[k] = v
        return out

    def send(
        self,
        tools: list[dict] | None = None,
        tool_choice: str | dict | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": self.messages,
            "stream": False,
            "max_tokens": CONFIG.get("max_tokens", 16384),
            **self._sampling_body(),
        }
        if tools:
            body["tools"] = tools
        if tool_choice is not None:
            body["tool_choice"] = tool_choice
        if DEADLINE is not None:
            left = DEADLINE - time.monotonic()
            if left <= 0:
                raise TaskTimeout
            r = self._http.post("/v1/chat/completions", json=body, timeout=min(left, 600.0))
        else:
            r = self._http.post("/v1/chat/completions", json=body)
        r.raise_for_status()
        data = r.json()
        usage = data.get("usage") or {}
        self.eval_tokens += int(usage.get("completion_tokens") or 0)
        timings = data.get("timings") or {}
        pred_ms = float(timings.get("predicted_ms") or 0)
        if pred_ms:
            self.eval_seconds += pred_ms / 1000.0
        self.last_prompt_ms = float(timings.get("prompt_ms") or 0)
        self.last_prompt_tok_s = float(timings.get("prompt_per_second") or 0)
        self.last_gen_tok_s = float(timings.get("predicted_per_second") or 0)

        choice = data["choices"][0]
        msg = choice["message"]
        history_msg = {k: v for k, v in msg.items() if k != "reasoning_content" and v is not None}
        finish = choice.get("finish_reason")
        self.length_stops += finish == "length"
        self.turn_meta[len(self.messages)] = (msg.get("reasoning_content"), finish)
        self.messages.append(history_msg)
        return msg

    def tool_result(self, call_id: str, name: str, content: str) -> None:
        self.messages.append(
            {"role": "tool", "tool_call_id": call_id, "name": name, "content": content}
        )

    def ask(self, prompt: str, system: str | None = None) -> str:
        if system:
            self.messages.append({"role": "system", "content": system})
        self.messages.append({"role": "user", "content": prompt})
        return self.send().get("content") or ""

    def result(self, passed: bool, score: float, notes: str, output: str, **extra: Any) -> Result:
        return Result(
            passed=passed,
            score=round(score, 3),
            notes=notes,
            output=output,
            seconds=round(time.monotonic() - self.started, 1),
            eval_tokens=self.eval_tokens,
            eval_seconds=self.eval_seconds,
            extra=extra,
        )

    def close(self) -> None:
        self._http.close()


def merged_result(
    chats: list[Chat], passed: bool, score: float, notes: str, output: str, **extra: Any
) -> Result:
    """One Result for a task that used a fresh Chat per case: wall time from the first chat,
    tokens and generation time summed over all of them."""
    r = chats[0].result(passed, score, notes, output, **extra)
    r.eval_tokens = sum(c.eval_tokens for c in chats)
    r.eval_seconds = sum(c.eval_seconds for c in chats)
    return r


def graded_run(
    chat: Chat,
    prompt: str,
    grade: Callable[[str], Grade],
    respond: Callable[[str], str] | None = None,
) -> Result:
    """Ask, grade, and on a fail with feedback retry up to RETRIES times in the same chat."""
    respond = respond or chat.ask
    g = first = grade(respond(prompt))
    outputs = [g.output]
    attempts = 1
    while not g.passed and g.feedback and attempts <= RETRIES:
        fb = g.feedback
        g = grade(respond(fb))
        attempts += 1
        outputs.append(f"=== feedback sent ===\n{fb}\n\n=== attempt {attempts} ===\n{g.output}")
    notes = g.notes
    if attempts > 1:
        notes += f" [after {attempts} attempts; first: {first.notes}]"
    return chat.result(
        g.passed,
        g.score,
        notes,
        "\n\n".join(outputs),
        first_passed=first.passed,
        first_score=round(first.score, 3),
        attempts=attempts,
    )


def extract_json(text: str) -> Any:
    """Parse the first JSON object/array in text, tolerating code fences and chatter."""
    text = re.sub(r"```(?:json)?", "", text)
    dec = json.JSONDecoder()
    for i, ch in enumerate(text):
        if ch in "{[":
            try:
                return dec.raw_decode(text[i:])[0]
            except json.JSONDecodeError:
                continue
    raise ValueError("no JSON found")


def extract_code(text: str, lang: str) -> str | None:
    """Return the body of the first ```lang fenced block (or any fenced block)."""
    m = re.search(rf"```{lang}\s*\n(.*?)```", text, re.DOTALL) or re.search(
        r"```[\w-]*\s*\n(.*?)```", text, re.DOTALL
    )
    return m.group(1) if m else None


def sandbox_run(
    cmd: list[str],
    workdir: Path,
    timeout: int = 60,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess:
    """Run model-written code with no network, a read-only root, and $HOME hidden.

    workdir is mounted read-write at SANDBOX_WORK; the project is re-exposed read-only so its
    venv (and uv's managed Python behind it) still resolves.
    """
    home = Path.home()
    uv_python = home / ".local/share/uv/python"
    args = [
        "bwrap",
        "--ro-bind",
        "/",
        "/",
        "--dev",
        "/dev",
        "--proc",
        "/proc",
        "--tmpfs",
        "/tmp",
        "--tmpfs",
        str(home),
        "--ro-bind",
        str(PROJECT_ROOT),
        str(PROJECT_ROOT),
    ]
    if uv_python.exists():
        args += ["--ro-bind", str(uv_python), str(uv_python)]
    args += [
        "--bind",
        str(workdir),
        SANDBOX_WORK,
        "--chdir",
        SANDBOX_WORK,
        "--unshare-all",
        "--die-with-parent",
        "--",
        *cmd,
    ]
    run_env = os.environ.copy()
    if env:
        run_env.update(env)
    try:
        return subprocess.run(
            args, capture_output=True, text=True, timeout=timeout, check=False, env=run_env
        )
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(args, 124, "", f"timed out after {timeout}s")
