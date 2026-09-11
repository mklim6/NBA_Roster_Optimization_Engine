from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

PRIOR_SALARY_VERSION = "franchise-free-agency-prior-salary-v1-2026-08-16"
ANCHOR_SEASON = "2026-27"
ROOT = Path(__file__).resolve().parents[1]
CACHE_PATH = (
    ROOT / "outputs" / "runtime"
    / "free_agency_prior_salary_2025_26_v1.json"
)


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _finite_positive(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number <= 0.0:
        return None
    return number


def load_anchor_prior_salary_cache() -> dict[str, float]:
    if not CACHE_PATH.is_file():
        return {}
    try:
        payload = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if payload.get("version") != PRIOR_SALARY_VERSION:
        return {}
    salaries = payload.get("prior_salary_by_player_id")
    if not isinstance(salaries, dict):
        return {}
    result: dict[str, float] = {}
    for player_id, value in salaries.items():
        salary = _finite_positive(value)
        if salary is not None:
            result[_clean(player_id)] = salary
    return result


def anchor_prior_salary(player_id: Any) -> float | None:
    return load_anchor_prior_salary_cache().get(_clean(player_id))


def resolve_prior_salary(state: Any, player_id: Any) -> float | None:
    season = _clean(
        getattr(getattr(state, "settings", None), "season_label", "")
    )
    if season == ANCHOR_SEASON:
        return anchor_prior_salary(player_id)

    players = getattr(state, "players", {})
    player = players.get(_clean(player_id)) if isinstance(players, dict) else None
    contract = getattr(player, "contract", None) if player is not None else None
    return _finite_positive(getattr(contract, "salary", None))


def apply_prior_salary_to_free_agent_rows(
    rows: list[dict[str, Any]],
    state: Any,
) -> list[dict[str, Any]]:
    season = _clean(
        getattr(getattr(state, "settings", None), "season_label", "")
    )
    cache = load_anchor_prior_salary_cache() if season == ANCHOR_SEASON else {}
    for row in rows:
        existing = _finite_positive(row.get("last_salary"))
        if existing is not None:
            row["last_salary"] = existing
            row["prior_salary_source"] = "live_contract"
            continue
        player_id = _clean(row.get("player_id"))
        resolved = cache.get(player_id)
        if resolved is not None:
            row["last_salary"] = resolved
            row["prior_salary_source"] = "verified_2025_26_evidence"
        else:
            row["last_salary"] = None
            row["prior_salary_source"] = "not_available"
    return rows
