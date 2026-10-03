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
    DEFAULT_CACHEABLE_PATHS,
    RUNTIME_PERFORMANCE_VERSION,
    RuntimePerformanceRegistry,
    V3RuntimePerformanceMiddleware,
)

VALIDATOR_VERSION = "v3-batch18b-request-coordination-validator-v1.0.0-2026-10-03"
REQUEST_COORDINATOR_VERSION = "v3-request-coordinator-batch-18b-v1.0.0-2026-10-03"
REPORT_DIR = ROOT / "outputs" / "v3_batch18b_request_coordination"
REPORT_PATH = REPORT_DIR / "validation.json"


def _sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


async def _asgi_get(app: Any, path: str, query: str = "") -> dict[str, Any]:
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
        "query_string": query.encode("ascii"),
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
        "json": json.loads(body.decode("utf-8")) if body else None,
    }


def _expanded_cache_probe() -> tuple[dict[str, bool], dict[str, Any]]:
    checks: dict[str, bool] = {}
    with tempfile.TemporaryDirectory(prefix="v3_batch18b_cache_") as tmp:
        watched = Path(tmp) / "working.bin"
        watched.write_bytes(b"state-one")
        calls = {"status": 0, "foundation": 0}

        async def status_endpoint(_request: Any) -> JSONResponse:
            calls["status"] += 1
            return JSONResponse({"kind": "status", "call": calls["status"]})

        async def foundation_endpoint(_request: Any) -> JSONResponse:
            calls["foundation"] += 1
            return JSONResponse({"kind": "foundation", "call": calls["foundation"]})

        registry = RuntimePerformanceRegistry(max_entries=8, history_size=32)
        app = Starlette(
            routes=[
                Route("/v3/working-save/status", status_endpoint, methods=["GET"]),
                Route("/v3/transaction-foundation", foundation_endpoint, methods=["GET"]),
            ]
        )
        app.add_middleware(
            V3RuntimePerformanceMiddleware,
            watched_paths=(watched,),
            registry=registry,
            cacheable_paths=(
                "/v3/working-save/status",
                "/v3/transaction-foundation",
            ),
            max_age_seconds=60.0,
        )

        status_first = asyncio.run(_asgi_get(app, "/v3/working-save/status"))
        status_second = asyncio.run(_asgi_get(app, "/v3/working-save/status"))
        foundation_first = asyncio.run(
            _asgi_get(app, "/v3/transaction-foundation", "trade_finder=0")
        )
        foundation_second = asyncio.run(
            _asgi_get(app, "/v3/transaction-foundation", "trade_finder=0")
        )

        checks["isolated_working_status_first_miss_second_hit"] = (
            status_first["status"] == 200
            and status_second["status"] == 200
            and status_first["headers"].get("x-v3-cache") == "MISS"
            and status_second["headers"].get("x-v3-cache") == "HIT"
            and calls["status"] == 1
        )
        checks["isolated_transaction_foundation_first_miss_second_hit"] = (
            foundation_first["status"] == 200
            and foundation_second["status"] == 200
            and foundation_first["headers"].get("x-v3-cache") == "MISS"
            and foundation_second["headers"].get("x-v3-cache") == "HIT"
            and calls["foundation"] == 1
        )

        dynamic = {
            "status": "pass" if all(checks.values()) else "failed",
            "status_endpoint_executions": calls["status"],
            "transaction_foundation_executions": calls["foundation"],
            "runtime_snapshot": registry.snapshot(),
        }
        return checks, dynamic


def _function_body(text: str, name: str) -> str:
    marker = f"func {name}"
    start = text.find(marker)
    if start < 0:
        return ""
    next_func = text.find("\nfunc ", start + len(marker))
    return text[start:] if next_func < 0 else text[start:next_func]


def main() -> int:
    active_v3 = Path(server.V3_WORKING_CHECKPOINT_PATH)
    active_v2 = Path(server.DEFAULT_CHECKPOINT_PATH)
    v3_before = _sha256(active_v3)
    v2_before = _sha256(active_v2)

    bridge = ROOT / "desktop_bridge" / "server.py"
    runtime = ROOT / "desktop_bridge" / "runtime_performance_foundation.py"
    main_gd = ROOT / "godot_client" / "scripts" / "main.gd"
    coordinator_gd = ROOT / "godot_client" / "scripts" / "request_coordinator_v3.gd"
    game_day_gd = ROOT / "godot_client" / "scripts" / "game_day_center_v3.gd"
    season_gd = ROOT / "godot_client" / "scripts" / "season_lifecycle_center_v3.gd"
    league_gd = ROOT / "godot_client" / "scripts" / "league_intelligence_center_v3.gd"
    front_gd = ROOT / "godot_client" / "scripts" / "front_office_center_v3.gd"
    benchmark = ROOT / "scripts" / "benchmark_v3_runtime.py"
    batch18a = ROOT / "src" / "validate_v3_batch18a_runtime_performance.py"
    batch17a = ROOT / "src" / "validate_v3_batch17a_save_manager.py"
    batch17b = ROOT / "src" / "validate_v3_batch17b_new_franchise.py"
    batch17c = ROOT / "src" / "validate_v3_batch17c_settings_tutorial.py"

    bridge_text = bridge.read_text(encoding="utf-8")
    runtime_text = runtime.read_text(encoding="utf-8")
    main_text = main_gd.read_text(encoding="utf-8")
    coordinator_text = coordinator_gd.read_text(encoding="utf-8")
    game_day_text = game_day_gd.read_text(encoding="utf-8")
    season_text = season_gd.read_text(encoding="utf-8")
    league_text = league_gd.read_text(encoding="utf-8")
    front_text = front_gd.read_text(encoding="utf-8")
    benchmark_text = benchmark.read_text(encoding="utf-8")

    health_body = _function_body(main_text, "_on_health_completed")
    show_page_body = _function_body(main_text, "_show_page")
    game_ready = _function_body(game_day_text, "_ready")
    season_ready = _function_body(season_text, "_ready")
    league_ready = _function_body(league_text, "_ready")
    front_ready = _function_body(front_text, "_ready")

    checks: dict[str, bool] = {
        "request_coordinator_version_present": REQUEST_COORDINATOR_VERSION in coordinator_text,
        "request_coordinator_blocks_inflight_and_recent_duplicates": (
            "_suppressed_in_flight" in coordinator_text
            and "_suppressed_recent" in coordinator_text
            and "reuse_window_ms" in coordinator_text
            and "begin_request" in coordinator_text
            and "finish_request" in coordinator_text
        ),
        "bridge_api_version_bumped": 'API_VERSION = "0.18.1"' in bridge_text,
        "runtime_version_advanced": "batch-18b" in RUNTIME_PERFORMANCE_VERSION,
        "working_status_is_cacheable": "/v3/working-save/status" in DEFAULT_CACHEABLE_PATHS,
        "transaction_foundation_is_cacheable": "/v3/transaction-foundation" in DEFAULT_CACHEABLE_PATHS,
        "main_preloads_and_instantiates_request_coordinator": (
            'preload("res://scripts/request_coordinator_v3.gd")' in main_text
            and "request_coordinator = RequestCoordinatorV3.new()" in main_text
        ),
        "main_summary_and_roster_are_coordinated": (
            'begin_request("franchise_summary"' in main_text
            and 'finish_request("franchise_summary"' in main_text
            and 'begin_request("roster"' in main_text
            and 'finish_request("roster"' in main_text
        ),
        "startup_no_longer_eager_loads_hidden_roster": "_request_roster()" not in health_body,
        "same_page_navigation_guard_present": (
            "page_navigation_initialized" in show_page_body
            and "page_name == current_page" in show_page_body
            and "not force_refresh" in show_page_body
        ),
        "league_and_front_office_refresh_on_navigation": (
            'page_name == "LEAGUE"' in show_page_body
            and 'league_page.call("refresh")' in show_page_body
            and 'page_name == "FRONT OFFICE"' in show_page_body
            and 'front_office_page.call("refresh")' in show_page_body
        ),
        "game_day_hidden_autoload_removed": "refresh()" not in game_ready,
        "season_hidden_autoload_removed": "refresh()" not in season_ready,
        "league_hidden_autoload_removed": "call_deferred(\"refresh\")" not in league_ready,
        "front_office_hidden_autoload_removed": "_refresh()" not in front_ready,
        "front_office_public_refresh_available": "func refresh() -> void:" in front_text,
        "benchmark_covers_new_hotspots": (
            "/v3/working-save/status" in benchmark_text
            and "/v3/transaction-foundation?trade_finder=0" in benchmark_text
        ),
        "batch18a_validator_preserved": batch18a.is_file(),
        "batch17a_validator_preserved": batch17a.is_file(),
        "batch17b_validator_preserved": batch17b.is_file(),
        "batch17c_validator_preserved": batch17c.is_file(),
    }

    try:
        for path in (bridge, runtime, benchmark, batch18a, Path(__file__)):
            py_compile.compile(str(path), doraise=True)
        checks["modified_python_files_compile"] = True
    except Exception:
        checks["modified_python_files_compile"] = False

    try:
        dynamic_checks, dynamic = _expanded_cache_probe()
        checks.update(dynamic_checks)
    except Exception as exc:
        dynamic = {
            "status": "failed",
            "exception_type": type(exc).__name__,
            "reason": str(exc),
        }
        checks["isolated_working_status_first_miss_second_hit"] = False
        checks["isolated_transaction_foundation_first_miss_second_hit"] = False

    godot_candidates = [
        shutil.which("godot4"),
        shutil.which("godot"),
        str(Path.home() / "Downloads" / "Godot_v4.0-stable_win64.exe"),
    ]
    godot_binary = next(
        (value for value in godot_candidates if value and Path(value).is_file()),
        None,
    )
    godot_output = ""
    if godot_binary:
        result = subprocess.run(
            [str(godot_binary), "--headless", "--path", str(ROOT / "godot_client"), "--editor", "--quit"],
            capture_output=True,
            text=True,
            timeout=90,
        )
        godot_output = (result.stdout + "\n" + result.stderr).strip()[-6000:]
        lowered = godot_output.lower()
        fatal_markers = (
            "parse error",
            "script error",
            "failed to load script",
            "error loading script",
            "cannot load source code",
            "parser error",
        )
        checks["godot_headless_parse"] = not any(marker in lowered for marker in fatal_markers)
    else:
        checks["godot_headless_parse"] = False
        godot_output = "Godot executable not found."

    v3_after = _sha256(active_v3)
    v2_after = _sha256(active_v2)
    checks["validator_never_changes_active_v3_save"] = v3_before == v3_after
    checks["validator_never_changes_active_v2_save"] = v2_before == v2_after

    passed = all(checks.values())
    report = {
        "validator_version": VALIDATOR_VERSION,
        "status": "pass" if passed else "failed",
        "checks": checks,
        "dynamic": dynamic,
        "runtime_version": RUNTIME_PERFORMANCE_VERSION,
        "godot_output_tail": godot_output,
        "active_v3_sha256_before": v3_before,
        "active_v3_sha256_after": v3_after,
        "active_v2_sha256_before": v2_before,
        "active_v2_sha256_after": v2_after,
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print("=" * 100)
    print("V3 BATCH 18B REQUEST COORDINATION + PAGE TRANSITIONS VALIDATION")
    print("=" * 100)
    for name, value in checks.items():
        print(f"  {name}: {'PASS' if value else 'FAIL'}")
    print()
    print(f"Dynamic expanded-cache validation: {str(dynamic.get('status', 'unknown')).upper()}")
    print(f"Godot parser: {'PASS' if checks.get('godot_headless_parse') else 'FAIL'}")
    print(f"Report: {REPORT_PATH}")
    print()
    if passed:
        print("V3 BATCH 18B VALIDATION PASSED")
        print("Request coordination/cache probes were read-only; active V3 and protected V2 remained unchanged.")
        return 0

    print("V3 BATCH 18B VALIDATION FAILED")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
