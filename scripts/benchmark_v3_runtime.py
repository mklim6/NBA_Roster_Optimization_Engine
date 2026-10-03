from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from desktop_bridge import server


BENCHMARK_VERSION = "v3-batch18b-runtime-benchmark-v1.1.0-2026-10-03"
DEFAULT_ENDPOINTS = (
    "/v3/franchise-summary",
    "/v3/roster",
    "/v3/game-day",
    "/v3/working-save/status",
    "/v3/transaction-foundation?trade_finder=0",
    "/v3/preferences",
    "/v3/saves",
    "/v3/franchise-intelligence",
    "/v3/market-intelligence",
)


def _sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _get(url: str, *, timeout: float = 90.0) -> dict[str, object]:
    request = Request(url, method="GET", headers={"Accept": "application/json"})
    started = time.perf_counter()
    try:
        with urlopen(request, timeout=timeout) as response:
            body = response.read()
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            return {
                "status": int(response.status),
                "elapsed_ms": round(elapsed_ms, 3),
                "cache": response.headers.get("X-V3-Cache", ""),
                "server_ms": response.headers.get("X-V3-Request-Ms", ""),
                "bytes": len(body),
            }
    except HTTPError as exc:
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        return {
            "status": int(exc.code),
            "elapsed_ms": round(elapsed_ms, 3),
            "cache": exc.headers.get("X-V3-Cache", "") if exc.headers else "",
            "server_ms": exc.headers.get("X-V3-Request-Ms", "") if exc.headers else "",
            "error": str(exc),
        }
    except URLError as exc:
        return {"status": 0, "elapsed_ms": 0.0, "cache": "", "server_ms": "", "error": str(exc)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark V3 bridge read endpoints without mutating franchise state.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8765")
    parser.add_argument("--rounds", type=int, default=4)
    parser.add_argument("--endpoint", action="append", dest="endpoints")
    args = parser.parse_args()

    rounds = max(2, int(args.rounds))
    endpoints = tuple(args.endpoints or DEFAULT_ENDPOINTS)
    base_url = str(args.base_url).rstrip("/")

    v3_path = Path(server.V3_WORKING_CHECKPOINT_PATH)
    v2_path = Path(server.DEFAULT_CHECKPOINT_PATH)
    v3_before = _sha256(v3_path)
    v2_before = _sha256(v2_path)

    health = _get(f"{base_url}/health", timeout=5.0)
    if int(health.get("status", 0)) != 200:
        print("V3 bridge is not reachable. Launch .\\Launch_V3_Desktop.cmd first.")
        return 2

    print("=" * 100)
    print("V3 BATCH 18B DESKTOP RUNTIME + NAVIGATION BENCHMARK")
    print("=" * 100)
    print(f"Bridge: {base_url} • rounds: {rounds}")
    print()

    endpoint_results: dict[str, object] = {}
    for endpoint in endpoints:
        samples = []
        for _ in range(rounds):
            result = _get(f"{base_url}{endpoint}")
            samples.append(result)
            if int(result.get("status", 0)) != 200:
                break

        elapsed = [float(row.get("elapsed_ms", 0.0)) for row in samples if int(row.get("status", 0)) == 200]
        cache_values = [str(row.get("cache", "")) for row in samples]
        cold = elapsed[0] if elapsed else 0.0
        warm = elapsed[1:] if len(elapsed) > 1 else []
        warm_avg = statistics.fmean(warm) if warm else 0.0
        endpoint_results[endpoint] = {
            "samples": samples,
            "cold_ms": round(cold, 3),
            "warm_average_ms": round(warm_avg, 3),
            "warm_min_ms": round(min(warm), 3) if warm else 0.0,
            "cache_hits": sum(1 for value in cache_values if value.upper() == "HIT"),
            "cache_misses": sum(1 for value in cache_values if value.upper() == "MISS"),
        }
        print(
            f"{endpoint:<34} cold {cold:>9.2f} ms   warm avg {warm_avg:>9.2f} ms   "
            f"cache {'/'.join(cache_values)}"
        )

    runtime_url = f"{base_url}/v3/runtime/performance"
    runtime_request = Request(runtime_url, method="GET", headers={"Accept": "application/json"})
    runtime_payload: dict[str, object] = {}
    try:
        with urlopen(runtime_request, timeout=10.0) as response:
            runtime_payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        runtime_payload = {"error": str(exc)}

    v3_after = _sha256(v3_path)
    v2_after = _sha256(v2_path)
    safe = v3_before == v3_after and v2_before == v2_after

    report = {
        "benchmark_version": BENCHMARK_VERSION,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "base_url": base_url,
        "rounds": rounds,
        "endpoints": endpoint_results,
        "runtime_performance": runtime_payload,
        "safety": {
            "active_v3_before": v3_before,
            "active_v3_after": v3_after,
            "active_v3_unchanged": v3_before == v3_after,
            "active_v2_before": v2_before,
            "active_v2_after": v2_after,
            "active_v2_unchanged": v2_before == v2_after,
        },
    }
    out_dir = ROOT / "outputs" / "v3_batch18b_request_coordination"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report_path = out_dir / f"benchmark_{stamp}.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print()
    print(f"Franchise checkpoint safety: {'PASS' if safe else 'FAIL'}")
    print(f"Report: {report_path}")
    return 0 if safe else 1


if __name__ == "__main__":
    raise SystemExit(main())
