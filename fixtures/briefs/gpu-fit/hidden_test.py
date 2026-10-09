from llmbench.server import (
    choose_run_config,
    gpu_offload_ok,
    parse_compute_apps_csv,
    parse_offload_log,
)


def test_parse_compute_apps_csv():
    csv = "12345, 2048\n99999, 512\n"
    assert parse_compute_apps_csv(csv, 12345) == 2048
    assert parse_compute_apps_csv(csv, 99999) == 512
    assert parse_compute_apps_csv(csv, 1) is None
    assert parse_compute_apps_csv("", 1) is None


def test_vram_threshold_decides_without_log_line():
    log = "no offload line here"
    assert gpu_offload_ok(log, 900, 1000.0)
    assert gpu_offload_ok(log, 1500, 1000.0)
    assert not gpu_offload_ok(log, 899, 1000.0)
    assert not gpu_offload_ok(log, None, 1000.0)


def test_partial_offload_log_overrides_vram():
    assert not gpu_offload_ok("load_tensors: offloaded 10/32 layers to GPU", 9000, 1000.0)
    assert gpu_offload_ok("load_tensors: offloaded 33/33 layers to GPU", 950, 1000.0)


def test_existing_helpers_unchanged():
    assert parse_offload_log("llama_kv_cache: offloaded 32/32 layers to GPU") == (32, 32)
    rows = [
        {"cache": "f16", "ctx": 32768, "ok": True},
        {"cache": "q8_0", "ctx": 32768, "ok": True},
    ]
    assert not choose_run_config(rows)["unfit"]
