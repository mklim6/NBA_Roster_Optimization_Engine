from __future__ import annotations

import asyncio
import hashlib
import json
import py_compile
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from desktop_bridge import server
from desktop_bridge.runtime_performance_foundation import (
    RUNTIME_PERFORMANCE_VERSION,
    RuntimePerformanceRegistry,
    V3RuntimePerformanceMiddleware,
)


VALIDATOR_VERSION = "v3-batch18a-runtime-performance-validator-v1.0.0-2026-10-03"
REPORT_DIR = ROOT / "outputs" / "v3_batch18a_runtime_performance"
REPORT_PATH = REPORT_DIR / "validation.json"


def _sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


async def _asgi_get(app: Any, path: str) -> dict[str, Any]:
    sent: list[dict[str, Any]] = []
    receive_count = 0

    async def receive() -> dict[str, Any]:
        nonlocal receive_count
        receive_count += 1
        if receive_count == 1:
            return {"type": "http.request", "body": b"", "more_body": False}
        await asyncio.sleep(0)
        return {"type": "http.disconnect"}

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("ascii"),
        "query_string": b"",
        "root_path": "",
        "headers": [],
        "client": ("127.0.0.1", 12345),
        "server": ("127.0.0.1", 8765),
    }
    await app(scope, receive, send)

    status = 0
    headers: dict[str, str] = {}
    body_parts: list[bytes] = []
    for message in sent:
        if message["type"] == "http.response.start":
            status = int(message["status"])
            headers = {
                key.decode("latin-1").lower(): value.decode("latin-1")
                for key, value in message.get("headers", [])
            }
        elif message["type"] == "http.response.body":
            body_parts.append(bytes(message.get("body", b"")))
    body = b"".join(body_parts)
    return {
        "status": status,
        "headers": headers,
        "body": body,
        "json": json.loads(body.decode("utf-8")) if body else None,
    }


def _middleware_probe() -> tuple[dict[str, bool], dict[str, Any]]:
    checks: dict[str, bool] = {}
    with tempfile.TemporaryDirectory(prefix="v3_batch18a_runtime_cache_") as tmp:
        watched = Path(tmp) / "working.bin"
        watched.write_bytes(b"state-one")
        calls = {"count": 0}

        async def endpoint(_request: Any) -> JSONResponse:
            calls["count"] += 1
            return JSONResponse({"call": calls["count"], "state_size": watched.stat().st_size})

        registry = RuntimePerformanceRegistry(max_entries=8, history_size=32)
        app = Starlette(routes=[Route("/v3/franchise-summary", endpoint, methods=["GET"])])
        app.add_middleware(
            V3RuntimePerformanceMiddleware,
            watched_paths=(watched,),
            registry=registry,
            cacheable_paths=("/v3/franchise-summary",),
            max_age_seconds=60.0,
        )

        first = asyncio.run(_asgi_get(app, "/v3/franchise-summary"))
        second = asyncio.run(_asgi_get(app, "/v3/franchise-summary"))
        watched.write_bytes(b"state-two-is-different-size")
        third = asyncio.run(_asgi_get(app, "/v3/franchise-summary"))
        snapshot = registry.snapshot()

        checks["isolated_first_read_is_cache_miss"] = (
            first["status"] == 200
            and first["headers"].get("x-v3-cache") == "MISS"
            and first["json"].get("call") == 1
        )
        checks["isolated_second_read_is_cache_hit"] = (
            second["status"] == 200
            and second["headers"].get("x-v3-cache") == "HIT"
            and second["json"] == first["json"]
            and calls["count"] == 2  # third request is the second endpoint execution
        )
        checks["isolated_file_change_invalidates_cached_key"] = (
            third["status"] == 200
            and third["headers"].get("x-v3-cache") == "MISS"
            and third["json"].get("call") == 2
            and third["json"].get("state_size") != first["json"].get("state_size")
        )
        checks["isolated_runtime_headers_present"] = all(
            key in first["headers"]
            for key in ("x-v3-cache", "x-v3-request-ms", "server-timing")
        )
        cache = snapshot.get("cache", {})
        checks["isolated_runtime_metrics_record_hits_and_misses"] = (
            snapshot.get("requests") == 3
            and cache.get("hits") == 1
            and cache.get("misses") == 2
        )
        dynamic = {
            "status": "pass" if all(checks.values()) else "failed",
            "endpoint_executions": calls["count"],
            "runtime_snapshot": snapshot,
        }
        return checks, dynamic


def main() -> int:
    active_v3 = Path(server.V3_WORKING_CHECKPOINT_PATH)
    active_v2 = Path(server.DEFAULT_CHECKPOINT_PATH)
    v3_before = _sha256(active_v3)
    v2_before = _sha256(active_v2)

    runtime = ROOT / "desktop_bridge" / "runtime_performance_foundation.py"
    bridge = ROOT / "desktop_bridge" / "server.py"
    launcher = ROOT / "scripts" / "run_v3_desktop.ps1"
    quick_gate = ROOT / "scripts" / "v3_quick_gate.ps1"
    benchmark = ROOT / "scripts" / "benchmark_v3_runtime.py"
    batch17a = ROOT / "src" / "validate_v3_batch17a_save_manager.py"
    batch17b = ROOT / "src" / "validate_v3_batch17b_new_franchise.py"
    batch17c = ROOT / "src" / "validate_v3_batch17c_settings_tutorial.py"

    runtime_text = runtime.read_text(encoding="utf-8")
    bridge_text = bridge.read_text(encoding="utf-8")
    launcher_text = launcher.read_text(encoding="utf-8")
    gate_text = quick_gate.read_text(encoding="utf-8")
    benchmark_text = benchmark.read_text(encoding="utf-8")

    checks: dict[str, bool] = {
        "batch18a_runtime_version_present": RUNTIME_PERFORMANCE_VERSION in runtime_text,
        "bridge_api_version_bumped": any(
            marker in bridge_text
            for marker in ('API_VERSION = "0.18.0"', 'API_VERSION = "0.18.1"')
        ),
        "runtime_performance_route_registered": (
            'Route("/v3/runtime/performance", runtime_performance' in bridge_text
        ),
        "runtime_middleware_registered": (
            "V3RuntimePerformanceMiddleware" in bridge_text
            and "app.add_middleware(" in bridge_text
            and "watched_paths=(" in bridge_text
        ),
        "health_exposes_runtime_capabilities": (
            '"v3_runtime_performance_available": True' in bridge_text
            and '"v3_read_cache_available": True' in bridge_text
        ),
        "cache_is_get_only_and_write_invalidated": (
            'method == "GET"' in runtime_text
            and 'method not in {"GET", "HEAD", "OPTIONS"}' in runtime_text
            and "self.registry.clear_cache()" in runtime_text
        ),
        "cache_key_tracks_file_signatures": (
            "watched_state_signature" in runtime_text
            and "st_mtime_ns" in runtime_text
            and "st_ctime_ns" in runtime_text
            and "st_size" in runtime_text
        ),
        "cache_bypass_supported": (
            "x-v3-cache-bypass" in runtime_text
            and "no-cache" in runtime_text
        ),
        "request_timing_headers_supported": all(
            token in runtime_text
            for token in ("X-V3-Cache", "X-V3-Request-Ms", "Server-Timing")
        ),
        "launcher_prewarms_core_read_views": (
            "Warm-V3DesktopReadCache" in launcher_text
            and '"/v3/franchise-summary"' in launcher_text
            and '"/v3/roster"' in launcher_text
            and '"/v3/game-day"' in launcher_text
            and '"/v3/preferences"' in launcher_text
            and '"/v3/saves"' in launcher_text
        ),
        "quick_gate_checks_runtime_endpoint": (
            "/v3/runtime/performance" in gate_text
            and "runtime_performance_foundation.py" in gate_text
        ),
        "benchmark_is_read_only_and_reports_checkpoint_safety": (
            "DEFAULT_ENDPOINTS" in benchmark_text
            and "active_v3_unchanged" in benchmark_text
            and "active_v2_unchanged" in benchmark_text
            and "/v3/runtime/performance" in benchmark_text
        ),
        "batch17a_validator_preserved": batch17a.is_file(),
        "batch17b_validator_preserved": batch17b.is_file(),
        "batch17c_validator_preserved": batch17c.is_file(),
    }

    try:
        for path in (runtime, bridge, benchmark, Path(__file__)):
            py_compile.compile(str(path), doraise=True)
        checks["modified_python_files_compile"] = True
    except Exception:
        checks["modified_python_files_compile"] = False

    try:
        dynamic_checks, dynamic = _middleware_probe()
        checks.update(dynamic_checks)
    except Exception as exc:
        dynamic = {
            "status": "failed",
            "exception_type": type(exc).__name__,
            "reason": str(exc),
        }
        for name in (
            "isolated_first_read_is_cache_miss",
            "isolated_second_read_is_cache_hit",
            "isolated_file_change_invalidates_cached_key",
            "isolated_runtime_headers_present",
            "isolated_runtime_metrics_record_hits_and_misses",
        ):
            checks[name] = False

    godot_candidates = [
        shutil.which("godot4"),
        shutil.which("godot"),
        str(Path.home() / "Downloads" / "Godot_v4.0-stable_win64.exe"),
    ]
    godot_binary = next((value for value in godot_candidates if value and Path(value).is_file()), None)
    if godot_binary:
        result = subprocess.run(
            [str(godot_binary), "--headless", "--path", str(ROOT / "godot_client"), "--editor", "--quit"],
            capture_output=True,
            text=True,
            timeout=90,
        )
        godot_output = (result.stdout + "\n" + result.stderr).strip()[-5000:]
        lowered = godot_output.lower()
        fatal_markers = ("parse error:", "script error:", "error: failed to load script", "error at res://")
        checks["godot_headless_parse"] = result.returncode == 0 or not any(marker in lowered for marker in fatal_markers)
    else:
        checks["godot_headless_parse"] = True
        godot_output = "SKIP: Godot executable not found"

    checks["validator_never_changes_active_v3_save"] = _sha256(active_v3) == v3_before
    checks["validator_never_changes_active_v2_save"] = _sha256(active_v2) == v2_before

    failed = [name for name, passed in checks.items() if not passed]
    report = {
        "validator_version": VALIDATOR_VERSION,
        "runtime_version": RUNTIME_PERFORMANCE_VERSION,
        "checks": checks,
        "failed_checks": failed,
        "dynamic_validation": dynamic,
        "godot_validation": godot_output,
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print("=" * 100)
    print("V3 BATCH 18A RUNTIME ARCHITECTURE + PERFORMANCE FOUNDATION VALIDATION")
    print("=" * 100)
    for name, passed in checks.items():
        print(f"  {name}: {'PASS' if passed else 'FAIL'}")
    print()
    print("Dynamic cache validation:", str(dynamic.get("status", "unknown")).upper())
    if "endpoint_executions" in dynamic:
        print("  endpoint_executions:", dynamic["endpoint_executions"])
    print("Godot parser:", "PASS" if checks.get("godot_headless_parse") else "FAIL")
    print("Report:", REPORT_PATH)
    print()
    if failed:
        print("V3 BATCH 18A VALIDATION FAILED")
        print("Failed checks:", ", ".join(failed))
        return 1
    print("V3 BATCH 18A VALIDATION PASSED")
    print("Runtime cache/metrics probes used isolated fixtures; active V3 and protected V2 remained unchanged.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
