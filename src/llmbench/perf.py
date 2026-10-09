"""Performance probe: prompt/gen tok/s and TTFT at 2k and 30k prompt tokens."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx

from llmbench.core import CONFIG


def _tokenize(client: httpx.Client, text: str) -> list[int]:
    r = client.post("/tokenize", json={"content": text})
    r.raise_for_status()
    data = r.json()
    if "tokens" in data:
        return data["tokens"]
    return list(range(int(data.get("n_tokens") or data.get("count") or 0)))


def _prompt_of_size(client: httpx.Client, target: int) -> str:
    chunk = "The quick brown fox jumps over the lazy dog. "
    text = chunk
    while len(_tokenize(client, text)) < target:
        text += chunk
    return text


def _bench_prompt(client: httpx.Client, model: str, prompt: str) -> dict[str, Any]:
    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 256,
        "stream": False,
        "temperature": 0.7,
    }
    r = client.post("/v1/chat/completions", json=body)
    r.raise_for_status()
    data = r.json()
    timings = data.get("timings") or {}
    usage = data.get("usage") or {}
    return {
        "prompt_tokens": usage.get("prompt_tokens"),
        "completion_tokens": usage.get("completion_tokens"),
        "prompt_ms": timings.get("prompt_ms"),
        "prompt_tok_s": timings.get("prompt_per_second"),
        "gen_tok_s": timings.get("predicted_per_second"),
        "ttft_ms": timings.get("prompt_ms"),
    }


def run_perf(
    out_path: Path,
    vram_used_mib: int,
    vram_free_mib: int,
    all_on_gpu: bool,
) -> dict[str, Any]:
    base = str(CONFIG["base_url"])
    model = str(CONFIG["model"])
    result: dict[str, Any] = {
        "vram_used_mib": vram_used_mib,
        "vram_free_mib": vram_free_mib,
        "all_on_gpu": all_on_gpu,
        "prompts": {},
    }
    with httpx.Client(base_url=base, timeout=600.0) as client:
        for label, size in (("2k", 2000), ("30k", 30000)):
            prompt = _prompt_of_size(client, size)
            result["prompts"][label] = _bench_prompt(client, model, prompt)
    tmp = out_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(result, indent=2))
    tmp.rename(out_path)
    return result
