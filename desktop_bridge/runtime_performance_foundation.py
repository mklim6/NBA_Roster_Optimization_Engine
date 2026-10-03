from __future__ import annotations

from collections import OrderedDict, defaultdict, deque
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from time import monotonic, perf_counter
from typing import Any, Iterable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


RUNTIME_PERFORMANCE_VERSION = "v3-runtime-performance-foundation-batch-18b-v1.1.0-2026-10-03"

# Conservative read-only cache. These endpoints are derived from the current
# checkpoint / desktop preference files and are invalidated whenever any write
# request completes or any watched file signature changes.
DEFAULT_CACHEABLE_PATHS = frozenset(
    {
        "/v3/franchise-summary",
        "/v3/roster",
        "/v3/game-day",
        "/v3/working-save/status",
        "/v3/transaction-foundation",
        "/v3/franchise-intelligence",
        "/v3/league-intelligence",
        "/v3/front-office",
        "/v3/market-intelligence",
        "/v3/free-agency/market",
        "/v3/trade/team-assets",
        "/v3/scouting-draft",
        "/v3/lifecycle",
        "/v3/saves",
        "/v3/preferences",
    }
)


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = int(round((len(ordered) - 1) * fraction))
    return float(ordered[max(0, min(index, len(ordered) - 1))])


def _file_signature(path: Path) -> tuple[Any, ...]:
    try:
        stat = path.stat()
        return (
            str(path),
            True,
            int(stat.st_mtime_ns),
            int(stat.st_ctime_ns),
            int(stat.st_size),
        )
    except FileNotFoundError:
        return (str(path), False, 0, 0, 0)


def watched_state_signature(paths: Iterable[Path | str]) -> tuple[tuple[Any, ...], ...]:
    return tuple(_file_signature(Path(path)) for path in paths)


@dataclass(frozen=True)
class _CacheEntry:
    body: bytes
    status_code: int
    headers: tuple[tuple[str, str], ...]
    media_type: str | None
    created_monotonic: float


class RuntimePerformanceRegistry:
    """Process-local request metrics plus a small LRU response cache."""

    def __init__(self, *, max_entries: int = 96, history_size: int = 256) -> None:
        self.max_entries = int(max_entries)
        self.history_size = int(history_size)
        self.started_monotonic = monotonic()
        self._lock = RLock()
        self._cache: OrderedDict[tuple[Any, ...], _CacheEntry] = OrderedDict()
        self._durations: dict[str, deque[float]] = defaultdict(
            lambda: deque(maxlen=self.history_size)
        )
        self._requests: dict[str, int] = defaultdict(int)
        self._status_counts: dict[str, dict[str, int]] = defaultdict(
            lambda: defaultdict(int)
        )
        self._cache_hits: dict[str, int] = defaultdict(int)
        self._cache_misses: dict[str, int] = defaultdict(int)
        self._cache_bypasses: dict[str, int] = defaultdict(int)
        self._recent: deque[dict[str, Any]] = deque(maxlen=30)
        self._cache_invalidations = 0

    def cache_get(self, key: tuple[Any, ...], *, max_age_seconds: float) -> _CacheEntry | None:
        with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                return None
            if monotonic() - entry.created_monotonic > float(max_age_seconds):
                self._cache.pop(key, None)
                return None
            self._cache.move_to_end(key)
            return entry

    def cache_put(self, key: tuple[Any, ...], entry: _CacheEntry) -> None:
        with self._lock:
            self._cache[key] = entry
            self._cache.move_to_end(key)
            while len(self._cache) > self.max_entries:
                self._cache.popitem(last=False)

    def clear_cache(self) -> None:
        with self._lock:
            if self._cache:
                self._cache.clear()
            self._cache_invalidations += 1

    def record(
        self,
        *,
        method: str,
        path: str,
        status_code: int,
        duration_ms: float,
        cache_status: str,
    ) -> None:
        label = f"{method.upper()} {path}"
        normalized_cache = str(cache_status or "BYPASS").upper()
        with self._lock:
            self._requests[label] += 1
            self._status_counts[label][str(int(status_code))] += 1
            self._durations[label].append(float(duration_ms))
            if normalized_cache == "HIT":
                self._cache_hits[label] += 1
            elif normalized_cache == "MISS":
                self._cache_misses[label] += 1
            else:
                self._cache_bypasses[label] += 1
            self._recent.append(
                {
                    "method": method.upper(),
                    "path": path,
                    "status_code": int(status_code),
                    "duration_ms": round(float(duration_ms), 3),
                    "cache": normalized_cache,
                }
            )

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            endpoints: dict[str, Any] = {}
            total_requests = 0
            total_hits = 0
            total_misses = 0
            total_bypasses = 0
            for label in sorted(self._requests):
                samples = list(self._durations[label])
                count = int(self._requests[label])
                hits = int(self._cache_hits[label])
                misses = int(self._cache_misses[label])
                bypasses = int(self._cache_bypasses[label])
                total_requests += count
                total_hits += hits
                total_misses += misses
                total_bypasses += bypasses
                endpoints[label] = {
                    "requests": count,
                    "samples_retained": len(samples),
                    "average_ms": round(sum(samples) / len(samples), 3) if samples else 0.0,
                    "p50_ms": round(_percentile(samples, 0.50), 3),
                    "p95_ms": round(_percentile(samples, 0.95), 3),
                    "max_ms": round(max(samples), 3) if samples else 0.0,
                    "cache_hits": hits,
                    "cache_misses": misses,
                    "cache_bypasses": bypasses,
                    "status_codes": dict(self._status_counts[label]),
                }

            cache_lookups = total_hits + total_misses
            return {
                "runtime_version": RUNTIME_PERFORMANCE_VERSION,
                "uptime_seconds": round(monotonic() - self.started_monotonic, 3),
                "requests": total_requests,
                "cache": {
                    "entries": len(self._cache),
                    "max_entries": self.max_entries,
                    "hits": total_hits,
                    "misses": total_misses,
                    "bypasses": total_bypasses,
                    "hit_rate": round(total_hits / cache_lookups, 4) if cache_lookups else 0.0,
                    "invalidations": int(self._cache_invalidations),
                },
                "endpoints": endpoints,
                "recent_requests": list(self._recent),
            }


RUNTIME_PERFORMANCE = RuntimePerformanceRegistry()


class V3RuntimePerformanceMiddleware(BaseHTTPMiddleware):
    """Measure every bridge request and cache safe GET responses.

    Cache keys include the URL/query plus metadata signatures for all watched
    state files. Any non-GET request invalidates the complete cache after the
    request finishes, providing a second safety boundary beyond signatures.
    """

    def __init__(
        self,
        app: Any,
        *,
        watched_paths: Iterable[Path | str],
        registry: RuntimePerformanceRegistry = RUNTIME_PERFORMANCE,
        cacheable_paths: Iterable[str] = DEFAULT_CACHEABLE_PATHS,
        max_age_seconds: float = 300.0,
        max_body_bytes: int = 8 * 1024 * 1024,
    ) -> None:
        super().__init__(app)
        self.watched_paths = tuple(Path(path) for path in watched_paths)
        self.registry = registry
        self.cacheable_paths = frozenset(str(path) for path in cacheable_paths)
        self.max_age_seconds = float(max_age_seconds)
        self.max_body_bytes = int(max_body_bytes)

    @staticmethod
    def _cache_bypass_requested(request: Request) -> bool:
        cache_control = request.headers.get("cache-control", "").lower()
        explicit = request.headers.get("x-v3-cache-bypass", "").strip().lower()
        return "no-cache" in cache_control or explicit in {"1", "true", "yes"}

    def _cache_key(self, request: Request) -> tuple[Any, ...]:
        return (
            request.method.upper(),
            request.url.path,
            request.url.query,
            watched_state_signature(self.watched_paths),
        )

    @staticmethod
    async def _materialize_response(response: Response) -> tuple[Response, bytes]:
        iterator = getattr(response, "body_iterator", None)
        if iterator is None:
            body = bytes(getattr(response, "body", b"") or b"")
        else:
            chunks: list[bytes] = []
            async for chunk in iterator:
                if isinstance(chunk, str):
                    chunk = chunk.encode("utf-8")
                chunks.append(bytes(chunk))
            body = b"".join(chunks)

        headers = dict(response.headers)
        headers.pop("content-length", None)
        headers.pop("transfer-encoding", None)
        rebuilt = Response(
            content=body,
            status_code=response.status_code,
            headers=headers,
            media_type=response.media_type,
            background=response.background,
        )
        return rebuilt, body

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        started = perf_counter()
        method = request.method.upper()
        path = request.url.path
        cache_status = "BYPASS"
        response: Response

        use_cache = (
            method == "GET"
            and path in self.cacheable_paths
            and not self._cache_bypass_requested(request)
        )

        if use_cache:
            key = self._cache_key(request)
            entry = self.registry.cache_get(
                key,
                max_age_seconds=self.max_age_seconds,
            )
            if entry is not None:
                response = Response(
                    content=entry.body,
                    status_code=entry.status_code,
                    headers=dict(entry.headers),
                    media_type=entry.media_type,
                )
                cache_status = "HIT"
            else:
                response = await call_next(request)
                response, body = await self._materialize_response(response)
                cache_status = "MISS"
                if response.status_code == 200 and len(body) <= self.max_body_bytes:
                    headers = dict(response.headers)
                    headers.pop("x-v3-cache", None)
                    headers.pop("x-v3-request-ms", None)
                    headers.pop("server-timing", None)
                    self.registry.cache_put(
                        key,
                        _CacheEntry(
                            body=body,
                            status_code=int(response.status_code),
                            headers=tuple(headers.items()),
                            media_type=response.media_type,
                            created_monotonic=monotonic(),
                        ),
                    )
        else:
            response = await call_next(request)

        # Every write-like request clears read cache after the endpoint returns,
        # even when file metadata would already invalidate the old key.
        if method not in {"GET", "HEAD", "OPTIONS"}:
            self.registry.clear_cache()

        duration_ms = (perf_counter() - started) * 1000.0
        response.headers["X-V3-Cache"] = cache_status
        response.headers["X-V3-Request-Ms"] = f"{duration_ms:.3f}"
        response.headers["Server-Timing"] = f"v3;dur={duration_ms:.3f}"
        self.registry.record(
            method=method,
            path=path,
            status_code=int(response.status_code),
            duration_ms=duration_ms,
            cache_status=cache_status,
        )
        return response
