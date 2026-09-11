from __future__ import annotations

import math
from dataclasses import dataclass, replace
from functools import lru_cache
from pathlib import Path
from typing import Any

from simulation_player_stat_fingerprints_v2 import (
    PlayerStatFingerprint,
    build_player_stat_fingerprint as build_v2_fingerprint,
    clamp,
)


FINGERPRINT_VERSION = "player-statistical-fingerprint-v3-empirical-2026-08-10"
ROOT = Path(__file__).resolve().parents[1]
EMPIRICAL_SOURCE = (
    ROOT / "data" / "processed" / "unified_player_seasons_2014_15_2025_26.parquet"
)
RECENCY_WEIGHTS = {0: 1.0, 1: 0.55, 2: 0.30}


@dataclass(frozen=True)
class EmpiricalPlayerPrior:
    player_id: str
    seasons: tuple[str, ...]
    latest_season: str
    weighted_minutes: float
    reliability: float
    rebounds_per_36: float
    assists_per_36: float
    steals_per_36: float
    blocks_per_36: float
    turnovers_per_36: float
    fouls_per_36: float
    three_attempts_per_36: float
    free_throw_attempts_per_36: float
    three_point_percentage: float | None
    two_point_percentage: float | None
    free_throw_percentage: float | None
    weighted_three_attempts: float
    weighted_free_throw_attempts: float
    weighted_two_point_attempts: float


def _player_key(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if text.endswith(".0") and text[:-2].isdigit():
        return text[:-2]
    return text


def _finite(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return float(default)
    return parsed if math.isfinite(parsed) else float(default)


def _safe_pct(made: float, attempted: float) -> float | None:
    if attempted <= 0.0:
        return None
    return clamp(made / attempted, 0.0, 1.0)


def _safe_per36(value: float, minutes: float) -> float:
    return 36.0 * value / minutes if minutes > 0.0 else 0.0


def _empirical_reliability(weighted_minutes: float, season_count: int) -> float:
    minutes_component = clamp(weighted_minutes / 2800.0, 0.0, 1.0)
    season_component = clamp(season_count / 3.0, 0.0, 1.0)
    return clamp(0.20 + 0.62 * minutes_component + 0.18 * season_component, 0.20, 1.0)


@lru_cache(maxsize=1)
def load_empirical_player_priors() -> dict[str, EmpiricalPlayerPrior]:
    if not EMPIRICAL_SOURCE.exists():
        return {}

    import pandas as pd

    required = [
        "season",
        "season_start",
        "player_id",
        "base_min",
        "base_fgm",
        "base_fga",
        "base_fg3m",
        "base_fg3a",
        "base_ftm",
        "base_fta",
        "base_reb",
        "base_ast",
        "base_tov",
        "base_stl",
        "base_blk",
        "base_pf",
    ]
    frame = pd.read_parquet(EMPIRICAL_SOURCE, columns=required)
    if frame.empty:
        return {}

    frame = frame.copy()
    frame["player_id"] = frame["player_id"].map(_player_key)
    frame["season_start"] = pd.to_numeric(frame["season_start"], errors="coerce")
    frame = frame.loc[frame["player_id"].ne("") & frame["season_start"].notna()].copy()
    if frame.empty:
        return {}

    numeric_columns = [column for column in required if column.startswith("base_")]
    for column in numeric_columns:
        frame[column] = pd.to_numeric(frame[column], errors="coerce").fillna(0.0)

    priors: dict[str, EmpiricalPlayerPrior] = {}
    for player_id, group in frame.groupby("player_id", sort=False):
        group = group.sort_values("season_start")
        latest_start = int(group["season_start"].max())
        recent = group.loc[
            group["season_start"].between(latest_start - 2, latest_start)
        ].copy()
        if recent.empty:
            continue
        recent["recency_weight"] = recent["season_start"].map(
            lambda value: RECENCY_WEIGHTS.get(latest_start - int(value), 0.0)
        )
        recent = recent.loc[recent["recency_weight"].gt(0.0)].copy()
        if recent.empty:
            continue

        def weighted_total(column: str) -> float:
            return float((recent[column] * recent["recency_weight"]).sum())

        minutes = weighted_total("base_min")
        if minutes < 60.0:
            continue
        fgm = weighted_total("base_fgm")
        fga = weighted_total("base_fga")
        threes_made = weighted_total("base_fg3m")
        threes_attempted = weighted_total("base_fg3a")
        ftm = weighted_total("base_ftm")
        fta = weighted_total("base_fta")
        twos_made = max(0.0, fgm - threes_made)
        twos_attempted = max(0.0, fga - threes_attempted)
        seasons = tuple(str(value) for value in recent["season"].tolist())
        reliability = _empirical_reliability(minutes, len(seasons))

        priors[player_id] = EmpiricalPlayerPrior(
            player_id=player_id,
            seasons=seasons,
            latest_season=str(recent.iloc[-1]["season"]),
            weighted_minutes=round(minutes, 2),
            reliability=round(reliability, 4),
            rebounds_per_36=round(_safe_per36(weighted_total("base_reb"), minutes), 4),
            assists_per_36=round(_safe_per36(weighted_total("base_ast"), minutes), 4),
            steals_per_36=round(_safe_per36(weighted_total("base_stl"), minutes), 4),
            blocks_per_36=round(_safe_per36(weighted_total("base_blk"), minutes), 4),
            turnovers_per_36=round(_safe_per36(weighted_total("base_tov"), minutes), 4),
            fouls_per_36=round(_safe_per36(weighted_total("base_pf"), minutes), 4),
            three_attempts_per_36=round(_safe_per36(threes_attempted, minutes), 4),
            free_throw_attempts_per_36=round(_safe_per36(fta, minutes), 4),
            three_point_percentage=_safe_pct(threes_made, threes_attempted),
            two_point_percentage=_safe_pct(twos_made, twos_attempted),
            free_throw_percentage=_safe_pct(ftm, fta),
            weighted_three_attempts=round(threes_attempted, 2),
            weighted_free_throw_attempts=round(fta, 2),
            weighted_two_point_attempts=round(twos_attempted, 2),
        )

    return priors


def empirical_player_prior(player_id: str) -> EmpiricalPlayerPrior | None:
    return load_empirical_player_priors().get(_player_key(player_id))


def _development_anchor_multiplier(player: Any) -> float:
    history = getattr(player, "development_history", [])
    seasons_advanced = len(history) if isinstance(history, list) else 0
    return 0.86 ** max(0, seasons_advanced)


def _blend(base: float, empirical: float, weight: float) -> float:
    return (1.0 - weight) * float(base) + weight * float(empirical)


def _volume_weight(prior: EmpiricalPlayerPrior, player: Any) -> float:
    return clamp(
        (0.58 + 0.38 * prior.reliability) * _development_anchor_multiplier(player),
        0.0,
        0.96,
    )


def _accuracy_weight(
    prior: EmpiricalPlayerPrior,
    player: Any,
    attempts: float,
    full_sample: float,
) -> float:
    sample_strength = clamp(attempts / full_sample, 0.18, 1.0)
    return clamp(
        (0.42 + 0.48 * prior.reliability)
        * sample_strength
        * _development_anchor_multiplier(player),
        0.0,
        0.92,
    )


def _build_player_stat_fingerprint_uncached_v3(player: Any) -> PlayerStatFingerprint:
    base = build_v2_fingerprint(player)
    prior = empirical_player_prior(str(getattr(player, "player_id", "")))
    if prior is None:
        return base

    volume_weight = _volume_weight(prior, player)
    secondary_weight = clamp(volume_weight * 0.82, 0.0, 0.88)

    three_pct = base.three_point_percentage
    if prior.three_point_percentage is not None:
        w = _accuracy_weight(prior, player, prior.weighted_three_attempts, 350.0)
        three_pct = _blend(three_pct, prior.three_point_percentage, w)

    two_pct = base.two_point_percentage
    if prior.two_point_percentage is not None:
        w = _accuracy_weight(prior, player, prior.weighted_two_point_attempts, 650.0)
        two_pct = _blend(two_pct, prior.two_point_percentage, w)

    free_throw_pct = base.free_throw_percentage
    if prior.free_throw_percentage is not None:
        w = _accuracy_weight(prior, player, prior.weighted_free_throw_attempts, 260.0)
        free_throw_pct = _blend(free_throw_pct, prior.free_throw_percentage, w)

    return replace(
        base,
        rebounds_per_36=round(_blend(base.rebounds_per_36, prior.rebounds_per_36, secondary_weight), 4),
        assists_per_36=round(_blend(base.assists_per_36, prior.assists_per_36, secondary_weight), 4),
        steals_per_36=round(_blend(base.steals_per_36, prior.steals_per_36, secondary_weight), 4),
        blocks_per_36=round(_blend(base.blocks_per_36, prior.blocks_per_36, secondary_weight), 4),
        turnovers_per_36=round(_blend(base.turnovers_per_36, prior.turnovers_per_36, secondary_weight), 4),
        fouls_per_36=round(_blend(base.fouls_per_36, prior.fouls_per_36, secondary_weight), 4),
        three_attempts_per_36=round(_blend(base.three_attempts_per_36, prior.three_attempts_per_36, volume_weight), 4),
        free_throw_attempts_per_36=round(_blend(base.free_throw_attempts_per_36, prior.free_throw_attempts_per_36, volume_weight), 4),
        three_point_percentage=round(clamp(three_pct, 0.20, 0.48), 5),
        two_point_percentage=round(clamp(two_pct, 0.38, 0.74), 5),
        free_throw_percentage=round(clamp(free_throw_pct, 0.45, 0.96), 5),
    )


_PLAYER_FINGERPRINT_RUNTIME_CACHE_V1 = True
PLAYER_FINGERPRINT_RUNTIME_CACHE_VERSION = "player-fingerprint-runtime-cache-v1-2026-08-13"
PLAYER_FINGERPRINT_RUNTIME_CACHE_MAXSIZE_V1 = 8192

import atexit as _fingerprint_atexit_v1
import dataclasses as _fingerprint_dataclasses_v1
import enum as _fingerprint_enum_v1
import functools as _fingerprint_functools_v1
import json as _fingerprint_json_v1
import math as _fingerprint_math_v1
import os as _fingerprint_os_v1
from collections import OrderedDict as _FingerprintOrderedDictV1
from pathlib import Path as _FingerprintPathV1

_PLAYER_FINGERPRINT_CACHE_V1 = _FingerprintOrderedDictV1()
_PLAYER_FINGERPRINT_CACHE_HITS_V1 = 0
_PLAYER_FINGERPRINT_CACHE_MISSES_V1 = 0
_PLAYER_FINGERPRINT_CACHE_UNCACHEABLE_V1 = 0
_PLAYER_FINGERPRINT_CACHE_EVICTIONS_V1 = 0
_PLAYER_FINGERPRINT_CACHE_ATEXIT_REGISTERED_V1 = False
_PLAYER_FINGERPRINT_CACHE_UNCACHEABLE_SENTINEL_V1 = object()


def _fingerprint_cache_freeze_v1(value, *, _depth=0, _budget=None):
    # The key is value-based, not object-identity based. If an argument cannot
    # be frozen conservatively within the bounded budget, the caller bypasses
    # caching instead of risking stale statistical identities.
    if _budget is None:
        _budget = [768]
    _budget[0] -= 1
    if _budget[0] < 0 or _depth > 7:
        return _PLAYER_FINGERPRINT_CACHE_UNCACHEABLE_SENTINEL_V1

    if value is None or isinstance(value, (bool, int, str, bytes)):
        return value
    if isinstance(value, float):
        if _fingerprint_math_v1.isnan(value):
            return ("__float_nan__",)
        if value == 0.0:
            return 0.0
        return value
    if isinstance(value, _FingerprintPathV1):
        return ("__path__", str(value))
    if isinstance(value, _fingerprint_enum_v1.Enum):
        frozen = _fingerprint_cache_freeze_v1(
            value.value, _depth=_depth + 1, _budget=_budget
        )
        if frozen is _PLAYER_FINGERPRINT_CACHE_UNCACHEABLE_SENTINEL_V1:
            return frozen
        return (
            "__enum__",
            value.__class__.__module__,
            value.__class__.__qualname__,
            frozen,
        )
    if isinstance(value, tuple):
        output = []
        for item in value:
            frozen = _fingerprint_cache_freeze_v1(
                item, _depth=_depth + 1, _budget=_budget
            )
            if frozen is _PLAYER_FINGERPRINT_CACHE_UNCACHEABLE_SENTINEL_V1:
                return frozen
            output.append(frozen)
        return ("__tuple__", tuple(output))
    if isinstance(value, list):
        output = []
        for item in value:
            frozen = _fingerprint_cache_freeze_v1(
                item, _depth=_depth + 1, _budget=_budget
            )
            if frozen is _PLAYER_FINGERPRINT_CACHE_UNCACHEABLE_SENTINEL_V1:
                return frozen
            output.append(frozen)
        return ("__list__", tuple(output))
    if isinstance(value, (set, frozenset)):
        output = []
        for item in value:
            frozen = _fingerprint_cache_freeze_v1(
                item, _depth=_depth + 1, _budget=_budget
            )
            if frozen is _PLAYER_FINGERPRINT_CACHE_UNCACHEABLE_SENTINEL_V1:
                return frozen
            output.append(frozen)
        output.sort(key=repr)
        return ("__set__", tuple(output))
    if isinstance(value, dict):
        if len(value) > 128:
            return _PLAYER_FINGERPRINT_CACHE_UNCACHEABLE_SENTINEL_V1
        output = []
        for key, item in value.items():
            frozen_key = _fingerprint_cache_freeze_v1(
                key, _depth=_depth + 1, _budget=_budget
            )
            frozen_item = _fingerprint_cache_freeze_v1(
                item, _depth=_depth + 1, _budget=_budget
            )
            if (
                frozen_key is _PLAYER_FINGERPRINT_CACHE_UNCACHEABLE_SENTINEL_V1
                or frozen_item is _PLAYER_FINGERPRINT_CACHE_UNCACHEABLE_SENTINEL_V1
            ):
                return _PLAYER_FINGERPRINT_CACHE_UNCACHEABLE_SENTINEL_V1
            output.append((frozen_key, frozen_item))
        output.sort(key=lambda pair: repr(pair[0]))
        return ("__dict__", tuple(output))
    if _fingerprint_dataclasses_v1.is_dataclass(value) and not isinstance(value, type):
        output = []
        for field in _fingerprint_dataclasses_v1.fields(value):
            frozen = _fingerprint_cache_freeze_v1(
                getattr(value, field.name),
                _depth=_depth + 1,
                _budget=_budget,
            )
            if frozen is _PLAYER_FINGERPRINT_CACHE_UNCACHEABLE_SENTINEL_V1:
                return frozen
            output.append((field.name, frozen))
        return (
            "__dataclass__",
            value.__class__.__module__,
            value.__class__.__qualname__,
            tuple(output),
        )

    # Named tuples are semantically tuples even though they expose attributes.
    if isinstance(value, tuple) and hasattr(value, "_fields"):
        output = []
        for field_name in value._fields:
            frozen = _fingerprint_cache_freeze_v1(
                getattr(value, field_name),
                _depth=_depth + 1,
                _budget=_budget,
            )
            if frozen is _PLAYER_FINGERPRINT_CACHE_UNCACHEABLE_SENTINEL_V1:
                return frozen
            output.append((field_name, frozen))
        return (
            "__namedtuple__",
            value.__class__.__module__,
            value.__class__.__qualname__,
            tuple(output),
        )

    return _PLAYER_FINGERPRINT_CACHE_UNCACHEABLE_SENTINEL_V1


def _fingerprint_cache_key_v1(args, kwargs):
    frozen_args = _fingerprint_cache_freeze_v1(args)
    if frozen_args is _PLAYER_FINGERPRINT_CACHE_UNCACHEABLE_SENTINEL_V1:
        return frozen_args
    # Preserve keyword insertion order. Equivalent calls expressed with a
    # different kwargs order may miss the cache, but can never collide.
    frozen_kwargs = _fingerprint_cache_freeze_v1(tuple(kwargs.items()))
    if frozen_kwargs is _PLAYER_FINGERPRINT_CACHE_UNCACHEABLE_SENTINEL_V1:
        return frozen_kwargs
    return (frozen_args, frozen_kwargs)


def _fingerprint_cache_result_is_safe_v1(result) -> bool:
    if result is None or isinstance(result, (bool, int, float, str, bytes)):
        return True
    if isinstance(result, tuple):
        return all(_fingerprint_cache_result_is_safe_v1(item) for item in result)
    if isinstance(result, frozenset):
        return all(_fingerprint_cache_result_is_safe_v1(item) for item in result)
    if _fingerprint_dataclasses_v1.is_dataclass(result) and not isinstance(result, type):
        params = getattr(result.__class__, "__dataclass_params__", None)
        if not bool(params is not None and getattr(params, "frozen", False)):
            return False
        return all(
            _fingerprint_cache_result_is_safe_v1(getattr(result, field.name))
            for field in _fingerprint_dataclasses_v1.fields(result)
        )
    return False


def player_fingerprint_runtime_cache_clear_v1() -> None:
    global _PLAYER_FINGERPRINT_CACHE_HITS_V1
    global _PLAYER_FINGERPRINT_CACHE_MISSES_V1
    global _PLAYER_FINGERPRINT_CACHE_UNCACHEABLE_V1
    global _PLAYER_FINGERPRINT_CACHE_EVICTIONS_V1
    _PLAYER_FINGERPRINT_CACHE_V1.clear()
    _PLAYER_FINGERPRINT_CACHE_HITS_V1 = 0
    _PLAYER_FINGERPRINT_CACHE_MISSES_V1 = 0
    _PLAYER_FINGERPRINT_CACHE_UNCACHEABLE_V1 = 0
    _PLAYER_FINGERPRINT_CACHE_EVICTIONS_V1 = 0


def player_fingerprint_runtime_cache_info_v1() -> dict[str, int | float]:
    total = _PLAYER_FINGERPRINT_CACHE_HITS_V1 + _PLAYER_FINGERPRINT_CACHE_MISSES_V1
    return {
        "version": PLAYER_FINGERPRINT_RUNTIME_CACHE_VERSION,
        "maxsize": PLAYER_FINGERPRINT_RUNTIME_CACHE_MAXSIZE_V1,
        "currsize": len(_PLAYER_FINGERPRINT_CACHE_V1),
        "hits": _PLAYER_FINGERPRINT_CACHE_HITS_V1,
        "misses": _PLAYER_FINGERPRINT_CACHE_MISSES_V1,
        "uncacheable": _PLAYER_FINGERPRINT_CACHE_UNCACHEABLE_V1,
        "evictions": _PLAYER_FINGERPRINT_CACHE_EVICTIONS_V1,
        "hit_rate": (
            float(_PLAYER_FINGERPRINT_CACHE_HITS_V1) / float(total)
            if total > 0 else 0.0
        ),
    }


def _player_fingerprint_runtime_cache_write_stats_v1() -> None:
    path = _fingerprint_os_v1.environ.get("NBA_FINGERPRINT_CACHE_STATS_PATH", "").strip()
    if not path:
        return
    try:
        _FingerprintPathV1(path).write_text(
            _fingerprint_json_v1.dumps(player_fingerprint_runtime_cache_info_v1(), indent=2),
            encoding="utf-8",
        )
    except Exception:
        # Stats are diagnostic only and must never affect simulation behavior.
        pass


def _player_fingerprint_runtime_cache_register_stats_v1() -> None:
    global _PLAYER_FINGERPRINT_CACHE_ATEXIT_REGISTERED_V1
    if _PLAYER_FINGERPRINT_CACHE_ATEXIT_REGISTERED_V1:
        return
    if _fingerprint_os_v1.environ.get("NBA_FINGERPRINT_CACHE_STATS_PATH", "").strip():
        _fingerprint_atexit_v1.register(_player_fingerprint_runtime_cache_write_stats_v1)
        _PLAYER_FINGERPRINT_CACHE_ATEXIT_REGISTERED_V1 = True


_PLAYER_FINGERPRINT_RUNTIME_CACHE_V1_0_1 = True
PLAYER_FINGERPRINT_RUNTIME_CACHE_VERSION = "player-fingerprint-runtime-cache-v1.0.1-2026-08-14"

import pickle as _fingerprint_pickle_v1_0_1


def _fingerprint_cache_fast_candidate_key_v1_0_1(args, kwargs):
    # Fast value snapshot. The V1 recursive freezer remains the safety oracle on misses.
    try:
        return _fingerprint_pickle_v1_0_1.dumps(
            (args, tuple(kwargs.items())),
            protocol=5,
        )
    except Exception:
        return _PLAYER_FINGERPRINT_CACHE_UNCACHEABLE_SENTINEL_V1


@_fingerprint_functools_v1.wraps(_build_player_stat_fingerprint_uncached_v3)
def build_player_stat_fingerprint(*args, **kwargs):
    global _PLAYER_FINGERPRINT_CACHE_HITS_V1
    global _PLAYER_FINGERPRINT_CACHE_MISSES_V1
    global _PLAYER_FINGERPRINT_CACHE_UNCACHEABLE_V1
    global _PLAYER_FINGERPRINT_CACHE_EVICTIONS_V1

    _player_fingerprint_runtime_cache_register_stats_v1()

    # Fast path: create the current value snapshot in C. A cache hit never
    # enters the expensive recursive V1 freezer.
    key = _fingerprint_cache_fast_candidate_key_v1_0_1(args, kwargs)
    if key is _PLAYER_FINGERPRINT_CACHE_UNCACHEABLE_SENTINEL_V1:
        _PLAYER_FINGERPRINT_CACHE_UNCACHEABLE_V1 += 1
        return _build_player_stat_fingerprint_uncached_v3(*args, **kwargs)

    try:
        result = _PLAYER_FINGERPRINT_CACHE_V1.pop(key)
    except KeyError:
        # Preserve V1's conservative cacheability contract. The old recursive
        # freezer is now paid only on a miss (331 times in the locked batch),
        # rather than on every one of ~183k calls.
        authoritative_key = _fingerprint_cache_key_v1(args, kwargs)
        if authoritative_key is _PLAYER_FINGERPRINT_CACHE_UNCACHEABLE_SENTINEL_V1:
            _PLAYER_FINGERPRINT_CACHE_UNCACHEABLE_V1 += 1
            return _build_player_stat_fingerprint_uncached_v3(*args, **kwargs)

        _PLAYER_FINGERPRINT_CACHE_MISSES_V1 += 1
        result = _build_player_stat_fingerprint_uncached_v3(*args, **kwargs)
        if not _fingerprint_cache_result_is_safe_v1(result):
            _PLAYER_FINGERPRINT_CACHE_UNCACHEABLE_V1 += 1
            return result
        _PLAYER_FINGERPRINT_CACHE_V1[key] = result
        if len(_PLAYER_FINGERPRINT_CACHE_V1) > PLAYER_FINGERPRINT_RUNTIME_CACHE_MAXSIZE_V1:
            _PLAYER_FINGERPRINT_CACHE_V1.popitem(last=False)
            _PLAYER_FINGERPRINT_CACHE_EVICTIONS_V1 += 1
        return result
    else:
        _PLAYER_FINGERPRINT_CACHE_HITS_V1 += 1
        _PLAYER_FINGERPRINT_CACHE_V1[key] = result
        return result






def expected_secondary_count(
    fingerprint: PlayerStatFingerprint,
    stat_name: str,
    minutes: float,
) -> float:
    rate = fingerprint.secondary_rate(stat_name)
    return max(0.0, rate * max(0.0, float(minutes)) / 36.0)


def fingerprint_summary(player: Any) -> dict[str, Any]:
    fp = build_player_stat_fingerprint(player)
    prior = empirical_player_prior(str(getattr(player, "player_id", "")))
    return {
        "version": FINGERPRINT_VERSION,
        "player_id": fp.player_id,
        "position": fp.position,
        "reliability": fp.reliability,
        "empirical_source_available": prior is not None,
        "empirical_source_seasons": list(prior.seasons) if prior else [],
        "empirical_reliability": prior.reliability if prior else 0.0,
        "3PA_per_36": fp.three_attempts_per_36,
        "FTA_per_36": fp.free_throw_attempts_per_36,
        "REB_per_36": fp.rebounds_per_36,
        "AST_per_36": fp.assists_per_36,
        "STL_per_36": fp.steals_per_36,
        "BLK_per_36": fp.blocks_per_36,
        "TO_per_36": fp.turnovers_per_36,
        "PF_per_36": fp.fouls_per_36,
        "3P_target": round(100.0 * fp.three_point_percentage, 1),
        "2P_target": round(100.0 * fp.two_point_percentage, 1),
        "FT_target": round(100.0 * fp.free_throw_percentage, 1),
        "empirical_3PA_per_36": prior.three_attempts_per_36 if prior else None,
        "empirical_FTA_per_36": prior.free_throw_attempts_per_36 if prior else None,
        "empirical_3P%": round(100.0 * prior.three_point_percentage, 1) if prior and prior.three_point_percentage is not None else None,
        "empirical_2P%": round(100.0 * prior.two_point_percentage, 1) if prior and prior.two_point_percentage is not None else None,
        "empirical_FT%": round(100.0 * prior.free_throw_percentage, 1) if prior and prior.free_throw_percentage is not None else None,
    }
