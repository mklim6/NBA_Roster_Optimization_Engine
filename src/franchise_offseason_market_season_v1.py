from __future__ import annotations

import re
from typing import Any

OFFSEASON_MARKET_SEASON_VERSION = (
    "franchise-offseason-market-season-v1-2026-08-18"
)
COMPLETED_SEASON_CLOSEOUT_ATTR = (
    "franchise_completed_season_contract_closeout_v1"
)


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _phase(state: Any) -> str:
    raw = getattr(state, "phase", "")
    return _clean(getattr(raw, "value", raw)).lower()


def _live_season(state: Any) -> str:
    return _clean(
        getattr(getattr(state, "settings", None), "season_label", "")
    )


def next_season_label(season_label: str) -> str:
    match = re.fullmatch(r"(\d{4})-(\d{2}|\d{4})", _clean(season_label))
    if not match:
        raise ValueError(f"Unsupported NBA season label: {season_label!r}.")
    start = int(match.group(1))
    suffix = match.group(2)
    end = int(suffix) if len(suffix) == 4 else (start // 100) * 100 + int(suffix)
    if end < start:
        end += 100
    if end != start + 1:
        raise ValueError(f"Season label is not a one-year NBA season: {season_label!r}.")
    return f"{end}-{str(end + 1)[-2:]}"


def completed_season_closeout_payload(state: Any) -> dict[str, Any] | None:
    value = getattr(state, COMPLETED_SEASON_CLOSEOUT_ATTR, None)
    return value if isinstance(value, dict) else None


def completed_season_closeout_applied(
    state: Any,
    source_season: str | None = None,
) -> bool:
    payload = completed_season_closeout_payload(state)
    if payload is None:
        return False
    expected = _clean(source_season) if source_season is not None else _live_season(state)
    return bool(
        payload.get("status") == "applied"
        and _clean(payload.get("source_season")) == expected
        and _clean(payload.get("target_market_season"))
    )


def resolve_offseason_market_season(state: Any) -> str:
    """Return the economic season for the current free-agency market.

    Opening-offseason checkpoints already describe the coming live season and
    therefore use state.settings.season_label directly. After a completed
    postseason closeout, the live season label intentionally remains the season
    that just ended until Draft/Open Next Season archives it. In that specific
    epoch, the economic market belongs to the following season and is carried by
    the durable closeout marker.
    """
    live = _live_season(state)
    if not live or _phase(state) != "offseason":
        return live

    payload = completed_season_closeout_payload(state)
    if not completed_season_closeout_applied(state, live) or payload is None:
        return live

    target = _clean(payload.get("target_market_season"))
    return target or live


def modeled_future_market_enabled(state: Any) -> bool:
    live = _live_season(state)
    market = resolve_offseason_market_season(state)
    return bool(
        live
        and market
        and market != live
        and completed_season_closeout_applied(state, live)
    )
