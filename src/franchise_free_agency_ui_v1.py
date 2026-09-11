from __future__ import annotations

import copy
import math
from typing import Any, Iterable, Mapping

FREE_AGENCY_UI_VERSION = "franchise-free-agency-ui-preview-v1-2026-08-14"
FREE_AGENCY_UI_EXECUTION_BOUNDARY = "preview_only_no_durable_commit"
CONTROLLED_TEAMS_PREFERENCE_KEY = "franchise_pref_controlled_teams"
ACTIVE_TEAM_PREFERENCE_KEY = "franchise_pref_active_team"


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _team(value: Any) -> str:
    return _clean(value).upper()


def _float(value: Any) -> float | None:
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _preference_dict(checkpoint: Any) -> dict[str, Any]:
    raw = getattr(checkpoint, "preferences", None)
    return dict(raw) if isinstance(raw, Mapping) else {}


def controlled_teams_from_checkpoint(checkpoint: Any, state: Any) -> tuple[str, ...]:
    """Resolve only explicitly user-controlled teams from durable preferences.

    No all-team fallback is used. If the checkpoint does not identify a controlled
    team, the UI remains read-only rather than silently granting control.
    """
    preferences = _preference_dict(checkpoint)
    raw = preferences.get(CONTROLLED_TEAMS_PREFERENCE_KEY, ())
    if isinstance(raw, str):
        candidates = [raw]
    elif isinstance(raw, Iterable):
        candidates = list(raw)
    else:
        candidates = []

    valid = {_team(key) for key in getattr(state, "teams", {})}
    resolved = []
    for value in candidates:
        code = _team(value)
        if code and code in valid and code not in resolved:
            resolved.append(code)
    return tuple(resolved)


def active_controlled_team(checkpoint: Any, controlled_teams: tuple[str, ...]) -> str:
    preferences = _preference_dict(checkpoint)
    active = _team(preferences.get(ACTIVE_TEAM_PREFERENCE_KEY, ""))
    return active if active in controlled_teams else (controlled_teams[0] if controlled_teams else "")


def free_agent_rows(state: Any) -> list[dict[str, Any]]:
    players = getattr(state, "players", {})
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw_id in getattr(state, "free_agent_player_ids", ()):
        player_id = _clean(raw_id)
        if not player_id or player_id in seen:
            continue
        seen.add(player_id)
        player = players.get(player_id)
        if player is None:
            continue
        contract = getattr(player, "contract", None)
        salary = _float(getattr(contract, "salary", None)) if contract is not None else None
        rows.append({
            "player_id": player_id,
            "player_name": _clean(getattr(player, "player_name", "")) or player_id,
            "position": _clean(getattr(player, "position", "")) or "UNK",
            "age": _float(getattr(player, "age", None)),
            "overall": _float(getattr(player, "overall_rating", None)),
            "potential": _float(getattr(player, "potential_rating", None)),
            "last_salary": salary,
            "synthetic": bool(getattr(player, "synthetic", False)),
            "roster_status": _clean(getattr(player, "roster_status", "")),
        })
    rows.sort(key=lambda row: (-(row["overall"] if row["overall"] is not None else -1.0), row["player_name"].casefold(), row["player_id"]))
    return rows


def free_agency_history_rows(state: Any) -> list[dict[str, Any]]:
    raw = getattr(state, "free_agency_transaction_history", None)
    if not isinstance(raw, list):
        return []
    rows = []
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        rows.append({
            "transaction_id": _clean(item.get("transaction_id")),
            "player": _clean(item.get("player_name")) or _clean(item.get("player_id")),
            "team": _team(item.get("team_abbreviation")),
            "annual_salary": _float(item.get("annual_salary")),
            "years": item.get("years"),
            "route": _clean((item.get("financial_gate_payload") or {}).get("route")) if isinstance(item.get("financial_gate_payload"), Mapping) else "",
            "financial_status": _clean(item.get("financial_gate_status")),
        })
    return rows


def isolated_offseason_preview_state(state: Any) -> Any:
    """Return a copy with only its phase changed for hypothetical UI preview."""
    candidate = copy.deepcopy(state)
    try:
        from simulation_league_state_v1 import LeaguePhase
        candidate.phase = LeaguePhase.OFFSEASON
    except Exception:
        candidate.phase = "offseason"
    return candidate


def offer_signature(player_id: Any, team: Any, annual_salary: Any, years: Any, guaranteed: Any, option_type: Any) -> tuple[Any, ...]:
    return (
        _clean(player_id),
        _team(team),
        round(float(annual_salary), 2),
        int(years),
        bool(guaranteed),
        _clean(option_type).lower(),
    )


def preview_matches_signature(preview: Any, signature: tuple[Any, ...]) -> bool:
    offer = getattr(preview, "offer", None)
    if offer is None:
        return False
    return offer_signature(
        getattr(offer, "player_id", ""),
        getattr(offer, "team_abbreviation", ""),
        getattr(offer, "annual_salary", 0.0),
        getattr(offer, "years", 0),
        getattr(offer, "guaranteed", False),
        getattr(offer, "option_type", ""),
    ) == signature
