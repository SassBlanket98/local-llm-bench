"""Start and probe llama-server for one model config at a time."""

from __future__ import annotations

import json
import os
import re
import signal
import socket
import subprocess
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Self

import httpx

DEFAULT_GGUF_DIR = Path(os.environ.get("BENCH_GGUF_DIR", "~/models/gguf")).expanduser()
MIN_VRAM_FREE_MIB = 512
HEALTH_TIMEOUT_S = 300
PROBE_CTX = (32768, 65536, 131072)
PROBE_CACHE = ("f16", "q8_0")


REASONING_BUDGET = 12288


@dataclass
class ServerConfig:
    slug: str
    gguf_path: Path
    ctx: int
    cache_type: str  # "f16" | "q8_0"
    reasoning: str  # "on" | "off" | "auto"
    reasoning_effort: str | None = None
    extra_args: list[str] = field(default_factory=list)

    @property
    def alias(self) -> str:
        return self.slug


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _vram_mib() -> tuple[int, int]:
    out = subprocess.run(
        [
            "nvidia-smi",
            "--query-gpu=memory.used,memory.total",
            "--format=csv,noheader,nounits",
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    used_s, total_s = out.split(",")
    return int(used_s.strip()), int(total_s.strip())


def parse_compute_apps_csv(csv_text: str, pid: int) -> int | None:
    """Return used GPU memory in MiB for pid from nvidia-smi compute-apps CSV."""
    for line in csv_text.strip().splitlines():
        if not line.strip():
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 2:
            continue
        try:
            row_pid = int(parts[0])
            used = int(float(parts[1]))
        except ValueError:
            continue
        if row_pid == pid:
            return used
    return None


def _vram_mib_for_pid(pid: int) -> int | None:
    out = subprocess.run(
        [
            "nvidia-smi",
            "--query-compute-apps=pid,used_memory",
            "--format=csv,noheader,nounits",
        ],
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    return parse_compute_apps_csv(out, pid)


def gguf_size_mib(gguf_path: Path) -> float:
    return gguf_path.stat().st_size / (1024 * 1024)


def gpu_offload_ok(log_text: str, server_vram_mib: int | None, gguf_mib: float) -> bool:
    """Full offload per llama.cpp's own layer count (logged at -lv 4). The VRAM-vs-file-size
    ratio is only a fallback: some models (e.g. Gemma E4B's per-layer embeddings) keep large
    embedding tables in host RAM by design, so the ratio misreads them as partly offloaded."""
    layers = parse_offload_log(log_text)
    if layers is not None:
        return layers[0] == layers[1]
    if server_vram_mib is None:
        return False
    return server_vram_mib >= 0.9 * gguf_mib


def parse_offload_log(log_text: str) -> tuple[int, int] | None:
    """Return (offloaded, total) from offload lines in server log."""
    patterns = (
        r"offloaded\s+(\d+)/(\d+)\s+layers to GPU",
        r"offloading\s+(\d+)\s+of\s+(\d+)\s+layers to GPU",
        r"load_tensors:\s+.*offloaded\s+(\d+)/(\d+)",
    )
    for pat in patterns:
        m = re.search(pat, log_text, re.IGNORECASE)
        if m:
            return int(m.group(1)), int(m.group(2))
    return None


def choose_run_config(probe_rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Deterministic run config from probe rows; may mark model unfit."""
    by_cache: dict[str, list[dict[str, Any]]] = {c: [] for c in PROBE_CACHE}
    for row in probe_rows:
        if row.get("cache") in by_cache:
            by_cache[row["cache"]].append(row)

    max_ok: dict[str, int | None] = {}
    for cache in PROBE_CACHE:
        ok_ctx = [r["ctx"] for r in by_cache[cache] if r.get("ok")]
        max_ok[cache] = max(ok_ctx) if ok_ctx else None

    def first_ok(cache: str, ctx: int) -> dict[str, Any] | None:
        for r in by_cache[cache]:
            if r.get("ctx") == ctx and r.get("ok"):
                return r
        return None

    if first_ok("f16", 32768):
        chosen = {"ctx": 32768, "cache_type": "f16", "unfit": False}
    elif first_ok("q8_0", 32768):
        chosen = {"ctx": 32768, "cache_type": "q8_0", "unfit": False}
    else:
        chosen = {"ctx": None, "cache_type": None, "unfit": True}

    return {**chosen, "max_ok_ctx": max_ok}


class LlamaServer:
    """Context manager: one llama-server process, killed with its process group on exit."""

    def __init__(self, config: ServerConfig, out_dir: Path, tag: str = "run") -> None:
        self.config = config
        self.out_dir = out_dir
        self.tag = tag
        self.port = _free_port()
        self.base_url = f"http://127.0.0.1:{self.port}"
        self.log_path = out_dir / f"server-{tag}.log"
        self._proc: subprocess.Popen[str] | None = None
        self.vram_used_mib = 0
        self.vram_free_mib = 0
        self.server_vram_mib = 0
        self.all_on_gpu = False

    def _build_cmd(self) -> list[str]:
        c = self.config
        cache = c.cache_type
        cmd = [
            "llama-server",
            "-m",
            str(c.gguf_path),
            "--alias",
            c.alias,
            "-c",
            str(c.ctx),
            "-ngl",
            "99",
            "--fit",
            "off",
            "-fa",
            "on",
            "-ctk",
            cache,
            "-ctv",
            cache,
            "--jinja",
            "--reasoning",
            c.reasoning,
            "--port",
            str(self.port),
            "--host",
            "127.0.0.1",
            "--no-webui",
            "-lv",
            "4",  # needed for load_tensors' "offloaded X/Y layers" line
            "-np",
            "1",
            # Cap thinking so over-deliberating models still answer within max_tokens (16384).
            "--reasoning-budget",
            str(REASONING_BUDGET),
            "--reasoning-budget-message",
            "Time is up. Give your final answer now.",
            *c.extra_args,
        ]
        if c.reasoning_effort:
            cmd += ["--reasoning-effort", c.reasoning_effort]
        return cmd

    def __enter__(self) -> Self:
        self.out_dir.mkdir(parents=True, exist_ok=True)
        log_f = self.log_path.open("w")
        self._proc = subprocess.Popen(
            self._build_cmd(),
            stdout=log_f,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            text=True,
        )
        log_f.close()
        deadline = time.monotonic() + HEALTH_TIMEOUT_S
        with httpx.Client(base_url=self.base_url, timeout=5.0) as client:
            while time.monotonic() < deadline:
                if self._proc.poll() is not None:
                    log = self.log_path.read_text(errors="replace")
                    raise RuntimeError(f"llama-server exited early:\n{log[-4000:]}")
                try:
                    r = client.get("/health")
                    if r.status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(0.5)
            else:
                self._kill()
                raise TimeoutError(f"health check failed after {HEALTH_TIMEOUT_S}s")

        try:
            log_text = self.log_path.read_text(errors="replace")
            pid = self._proc.pid if self._proc else 0
            server_vram = _vram_mib_for_pid(pid) if pid else None
            self.server_vram_mib = server_vram or 0
            gguf_mib = gguf_size_mib(self.config.gguf_path)
            self.all_on_gpu = gpu_offload_ok(log_text, server_vram, gguf_mib)
            used, total = _vram_mib()
            self.vram_used_mib = used
            self.vram_free_mib = total - used
        except BaseException:
            # __exit__ never runs when __enter__ raises, so don't leave the server holding VRAM.
            self._kill()
            raise
        return self

    def _kill(self) -> None:
        if self._proc is None or self._proc.poll() is not None:
            return
        try:
            os.killpg(self._proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        try:
            self._proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(self._proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            self._proc.wait(timeout=5)

    def __exit__(self, *exc: object) -> None:
        self._kill()
        self._proc = None


def _probe_completion(base_url: str, alias: str) -> dict[str, Any] | None:
    """One short completion; return timings dict or None on failure."""
    body = {
        "model": alias,
        "messages": [{"role": "user", "content": "Count from one to ten briefly."}],
        "max_tokens": 64,
        "stream": False,
    }
    try:
        with httpx.Client(base_url=base_url, timeout=120.0) as client:
            r = client.post("/v1/chat/completions", json=body)
            r.raise_for_status()
            return r.json()
    except httpx.HTTPError:
        return None


def probe_fit(slug: str, gguf: Path, out_dir: Path) -> dict[str, Any]:
    """Try ctx x cache combos; write fit.json and return summary."""
    out_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    failed_cache: set[str] = set()

    for cache in PROBE_CACHE:
        if cache in failed_cache:
            continue
        for ctx in PROBE_CTX:
            if cache in failed_cache:
                break
            cfg = ServerConfig(
                slug=slug, gguf_path=gguf, ctx=ctx, cache_type=cache, reasoning="off"
            )
            row: dict[str, Any] = {
                "ctx": ctx,
                "cache": cache,
                "ok": False,
                "all_on_gpu": False,
                "server_vram_mib": 0,
                "vram_free_mib": 0,
                "error": None,
            }
            tag = f"fit-{cache}-{ctx}"
            try:
                with LlamaServer(cfg, out_dir, tag=tag) as srv:
                    row["all_on_gpu"] = srv.all_on_gpu
                    row["server_vram_mib"] = srv.server_vram_mib
                    row["vram_free_mib"] = srv.vram_free_mib
                    resp = _probe_completion(srv.base_url, cfg.alias)
                    if resp is None:
                        row["error"] = "completion failed"
                    elif not srv.all_on_gpu:
                        row["error"] = "not all layers on GPU"
                    elif srv.vram_free_mib < MIN_VRAM_FREE_MIB:
                        row["error"] = f"vram_free {srv.vram_free_mib} < {MIN_VRAM_FREE_MIB}"
                    else:
                        row["ok"] = True
            except (OSError, RuntimeError, TimeoutError) as e:
                row["error"] = str(e)
            rows.append(row)
            if not row["ok"]:
                failed_cache.add(cache)

    run = choose_run_config(rows)
    result = {"slug": slug, "gguf": str(gguf), "probes": rows, "run_config": run}
    path = out_dir / "fit.json"
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(result, indent=2))
    tmp.rename(path)
    return result


def server_config_from_dict(d: dict[str, Any], gguf: Path | None = None) -> ServerConfig:
    return ServerConfig(
        slug=d["slug"],
        gguf_path=Path(gguf or d["gguf_path"]),
        ctx=int(d["ctx"]),
        cache_type=d["cache_type"],
        reasoning=d.get("reasoning", "off"),
        reasoning_effort=d.get("reasoning_effort"),
        extra_args=list(d.get("extra_args", [])),
    )


def config_to_dict(cfg: ServerConfig) -> dict[str, Any]:
    d = asdict(cfg)
    d["gguf_path"] = str(d["gguf_path"])
    return d
