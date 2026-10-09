4. **GPU offload check is hollow**: commit 18e66b9 sets `all_on_gpu = True` when the log has no
   offload line, and build 11146 never prints it at default verbosity, so the check always passes.
   Replace with a measurement: after /health, read the server PID's usage from
   `nvidia-smi --query-compute-apps=pid,used_memory --format=csv,noheader,nounits`;
   `all_on_gpu = used_mib >= 0.9 * gguf_file_size_mib`. Keep the log-line parse as an extra signal
   (if present and X<Y, not on GPU). Record `server_vram_mib` in fit.json. Unit tests with canned
   nvidia-smi output.


## Interface (acceptance tests call exactly these)
- `llmbench.server.parse_compute_apps_csv(csv_text: str, pid: int) -> int | None`: used MiB for that PID from the nvidia-smi CSV, None if absent.
- `llmbench.server.gpu_offload_ok(log_text: str, server_vram_mib: int | None, gguf_mib: float) -> bool`: the rule above (VRAM threshold, overridden by a log line showing partial offload).
- Keep `parse_offload_log` and `choose_run_config` as they are.
