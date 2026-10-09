from llmbench.server import (
    choose_run_config,
    gpu_offload_ok,
    parse_compute_apps_csv,
    parse_offload_log,
)


def test_parse_offload_log():
    text = "llama_kv_cache: offloaded 32/32 layers to GPU"
    assert parse_offload_log(text) == (32, 32)


def test_parse_compute_apps_csv():
    csv = "12345, 2048\n99999, 512\n"
    assert parse_compute_apps_csv(csv, 12345) == 2048
    assert parse_compute_apps_csv(csv, 1) is None


def test_gpu_offload_ok_uses_vram_threshold():
    log = "no offload line here"
    assert gpu_offload_ok(log, 900, 1000.0)
    assert not gpu_offload_ok(log, 800, 1000.0)


def test_gpu_offload_ok_log_partial_offload():
    log = "offloaded 10/32 layers to GPU"
    assert not gpu_offload_ok(log, 9000, 1000.0)


def test_choose_run_config_prefers_f16_32k():
    rows = [
        {"cache": "f16", "ctx": 32768, "ok": True},
        {"cache": "f16", "ctx": 65536, "ok": True},
        {"cache": "q8_0", "ctx": 32768, "ok": True},
    ]
    cfg = choose_run_config(rows)
    assert cfg["cache_type"] == "f16" and cfg["ctx"] == 32768 and not cfg["unfit"]


def test_choose_run_config_unfit():
    rows = [
        {"cache": "f16", "ctx": 32768, "ok": False},
        {"cache": "q8_0", "ctx": 32768, "ok": False},
    ]
    cfg = choose_run_config(rows)
    assert cfg["unfit"]
