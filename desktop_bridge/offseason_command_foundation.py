from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any, Mapping
from collections import Counter
import math

OFFSEASON_COMMAND_FOUNDATION_VERSION = (
    "v3-complete-offseason-expansion-40-v1.0.0-2026-10-04"
)

STANDARD_ROSTER_TARGET = 15
MIN_SUSTAINABLE_STANDARD_ROSTER = 14
TWO_WAY_TARGET = 3
YOUNG_CORE_MAX_AGE = 24.0


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _team(value: Any) -> str:
    return _clean(value).upper()


def _enum(value: Any) -> str:
    return _clean(getattr(value, "value", value)).lower()


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_float(value: Any, default: float | None = 0.0) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _json_safe(value: Any, *, depth: int = 0) -> Any:
    if depth > 6:
        return _clean(value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if is_dataclass(value):
        return _json_safe(asdict(value), depth=depth + 1)
    if isinstance(value, Mapping):
        return {
            str(key): _json_safe(item, depth=depth + 1)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_safe(item, depth=depth + 1) for item in value]
    enum_value = getattr(value, "value", None)
    if isinstance(enum_value, (str, int, float, bool)):
        return enum_value
    if hasattr(value, "__dict__"):
        return {
            str(key): _json_safe(item, depth=depth + 1)
            for key, item in vars(value).items()
            if not str(key).startswith("_")
        }
    return _clean(value)


def _active_team(checkpoint: Any) -> str:
    preferences = dict(getattr(checkpoint, "preferences", {}) or {})
    return _team(preferences.get("franchise_pref_active_team", ""))


def _team_name(team_names: Mapping[str, str], abbreviation: str) -> str:
    key = _team(abbreviation)
    return str(team_names.get(key, key))


def _position_bucket(value: Any) -> str:
    text = _clean(value).upper()
    if "/" in text:
        text = text.split("/")[0]
    aliases = {
        "G": "PG",
        "GUARD": "PG",
        "F": "SF",
        "FORWARD": "SF",
        "BIG": "C",
        "CENTER": "C",
    }
    text = aliases.get(text, text)
    return text if text in {"PG", "SG", "SF", "PF", "C"} else "OTHER"


def _contract_payload(player: Any) -> dict[str, Any]:
    contract = getattr(player, "contract", None)
    if contract is None:
        return {
            "exists": False,
            "salary": None,
            "years_remaining": 0,
            "guaranteed": None,
            "option_type": "",
            "contract_type": "",
            "two_way": False,
        }

    contract_type = _clean(
        getattr(
            contract,
            "contract_type",
            getattr(contract, "roster_type", getattr(contract, "type", "")),
        )
    ).lower()
    explicit_two_way = bool(
        getattr(contract, "two_way", False)
        or getattr(contract, "is_two_way", False)
        or getattr(player, "two_way", False)
        or getattr(player, "is_two_way", False)
    )
    two_way = explicit_two_way or "two" in contract_type and "way" in contract_type
    salary = _safe_float(getattr(contract, "salary", None), None)

    return {
        "exists": True,
        "salary": salary,
        "years_remaining": _safe_int(getattr(contract, "years_remaining", 0)),
        "guaranteed": (
            bool(getattr(contract, "guaranteed", False))
            if hasattr(contract, "guaranteed")
            else None
        ),
        "option_type": _clean(getattr(contract, "option_type", "")),
        "contract_type": contract_type,
        "two_way": bool(two_way),
    }


def _player_payload(state: Any, player_id: str) -> dict[str, Any]:
    player = getattr(state, "players", {}).get(player_id)
    if player is None:
        return {
            "player_id": str(player_id),
            "name": str(player_id),
            "position": "",
            "position_bucket": "OTHER",
            "age": None,
            "overall": None,
            "potential": None,
            "future_outlook": None,
            "development_direction": "",
            "contract": _contract_payload(None),
        }

    age = _safe_float(getattr(player, "age", None), None)
    overall = _safe_float(getattr(player, "overall_rating", None), None)
    potential = _safe_float(getattr(player, "potential_rating", None), None)
    future = _safe_float(getattr(player, "future_outlook_rating", None), None)
    position = _clean(getattr(player, "position", ""))

    return {
        "player_id": str(player_id),
        "name": _clean(getattr(player, "player_name", player_id)),
        "position": position,
        "position_bucket": _position_bucket(position),
        "age": round(age, 1) if age is not None else None,
        "overall": round(overall, 1) if overall is not None else None,
        "potential": round(potential, 1) if potential is not None else None,
        "future_outlook": round(future, 1) if future is not None else None,
        "development_direction": _clean(
            getattr(player, "development_direction", "Stable")
        )
        or "Stable",
        "contract": _contract_payload(player),
    }


def _roster_payload(state: Any, active_team: str) -> dict[str, Any]:
    team = getattr(state, "teams", {}).get(active_team)
    if team is None:
        return {
            "roster_count": 0,
            "standard_count": 0,
            "two_way_count": 0,
            "players": [],
            "position_counts": {},
            "rotation_count": 0,
            "starter_count": 0,
            "listed_payroll": 0.0,
        }

    ids = list(getattr(team, "roster_player_ids", ()) or ())
    rows = [_player_payload(state, str(player_id)) for player_id in ids]

    standard = [row for row in rows if not bool(row["contract"].get("two_way"))]
    two_way = [row for row in rows if bool(row["contract"].get("two_way"))]
    position_counts = Counter(row["position_bucket"] for row in standard)

    rotation = getattr(team, "rotation", None)
    rotation_ids = list(getattr(rotation, "rotation_player_ids", ()) or ())
    starter_ids = list(getattr(rotation, "starter_ids", ()) or ())

    listed_payroll = sum(
        float(row["contract"]["salary"] or 0.0)
        for row in rows
        if row["contract"]["salary"] is not None
    )

    rows.sort(
        key=lambda row: (
            -float(row.get("overall") or 0.0),
            float(row.get("age") if row.get("age") is not None else 99.0),
            row.get("name", ""),
        )
    )

    return {
        "roster_count": len(rows),
        "standard_count": len(standard),
        "two_way_count": len(two_way),
        "standard_target": STANDARD_ROSTER_TARGET,
        "sustainable_standard_minimum": MIN_SUSTAINABLE_STANDARD_ROSTER,
        "two_way_target": TWO_WAY_TARGET,
        "open_standard_slots": max(0, STANDARD_ROSTER_TARGET - len(standard)),
        "open_two_way_slots": max(0, TWO_WAY_TARGET - len(two_way)),
        "players": rows,
        "position_counts": dict(position_counts),
        "rotation_count": len(rotation_ids),
        "starter_count": len(starter_ids),
        "listed_payroll": round(listed_payroll, 2),
    }


def _young_core(roster: Mapping[str, Any], *, limit: int = 10) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for raw in roster.get("players", []) or []:
        if not isinstance(raw, Mapping):
            continue
        row = dict(raw)
        age = row.get("age")
        if age is None or float(age) > YOUNG_CORE_MAX_AGE:
            continue
        overall = float(row.get("overall") or 0.0)
        potential = float(row.get("potential") or row.get("future_outlook") or overall)
        future = float(row.get("future_outlook") or potential)
        age_bonus = max(0.0, YOUNG_CORE_MAX_AGE - float(age)) * 1.8
        growth_gap = max(0.0, max(potential, future) - overall)
        score = overall * 0.52 + max(potential, future) * 0.36 + growth_gap * 0.8 + age_bonus
        row["development_priority_score"] = round(score, 2)
        row["growth_gap"] = round(growth_gap, 1)
        rows.append(row)

    rows.sort(
        key=lambda row: (
            -float(row["development_priority_score"]),
            -float(row.get("potential") or 0.0),
            row.get("name", ""),
        )
    )
    return rows[:limit]


def _roster_battles(roster: Mapping[str, Any], *, limit: int = 10) -> list[dict[str, Any]]:
    rows = [dict(row) for row in roster.get("players", []) if isinstance(row, Mapping)]
    if not rows:
        return []

    standard = [row for row in rows if not bool(row.get("contract", {}).get("two_way"))]
    standard.sort(
        key=lambda row: (
            float(row.get("overall") or 0.0),
            -float(row.get("age") or 0.0),
            row.get("name", ""),
        )
    )

    result: list[dict[str, Any]] = []
    for row in standard[:limit]:
        contract = dict(row.get("contract", {}) or {})
        security = "CORE"
        overall = float(row.get("overall") or 0.0)
        years = int(contract.get("years_remaining") or 0)
        guaranteed = contract.get("guaranteed")

        if overall < 72 or years <= 1:
            security = "BUBBLE"
        if overall < 68 and years <= 1:
            security = "CUT WATCH"
        if guaranteed is False:
            security = "NON-GUARANTEED"

        result.append(
            {
                **row,
                "competition_tier": security,
                "reason": (
                    "Non-guaranteed contract"
                    if guaranteed is False
                    else (
                        f"{years} year(s) remaining • OVR {overall:.0f}"
                        if years > 0
                        else f"Contract term unresolved • OVR {overall:.0f}"
                    )
                ),
            }
        )
    return result


def _raw_free_agents(state: Any, *, limit: int = 12) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for player_id in list(getattr(state, "free_agent_player_ids", ()) or ()):
        row = _player_payload(state, str(player_id))
        rows.append(
            {
                "player_id": row["player_id"],
                "name": row["name"],
                "position": row["position"],
                "age": row["age"],
                "overall": row["overall"],
                "potential": row["potential"],
                "salary": row["contract"].get("salary"),
            }
        )
    rows.sort(
        key=lambda row: (
            -float(row.get("overall") or 0.0),
            -float(row.get("potential") or 0.0),
            row.get("name", ""),
        )
    )
    return rows[:limit]


def _market_payload(checkpoint: Any, active_team: str) -> tuple[dict[str, Any], list[str]]:
    diagnostics: list[str] = []
    try:
        from desktop_bridge.transaction_foundation import build_free_agency_market_payload

        payload = build_free_agency_market_payload(checkpoint, active_team)
        if isinstance(payload, Mapping):
            return dict(payload), diagnostics
    except Exception as exc:
        diagnostics.append(
            f"free_agency_market:{type(exc).__name__}:{exc}"
        )
    return {}, diagnostics


def _draft_payload(checkpoint: Any, active_team: str) -> tuple[dict[str, Any], list[str]]:
    diagnostics: list[str] = []
    try:
        from desktop_bridge.transaction_foundation import build_scouting_draft_payload

        payload = build_scouting_draft_payload(checkpoint, active_team)
        if isinstance(payload, Mapping):
            return dict(payload), diagnostics
    except Exception as exc:
        diagnostics.append(f"scouting_draft:{type(exc).__name__}:{exc}")
    return {}, diagnostics


def _lifecycle_payload(checkpoint: Any) -> tuple[dict[str, Any], list[str]]:
    diagnostics: list[str] = []
    try:
        from desktop_bridge.season_lifecycle_foundation import build_lifecycle_summary

        payload = build_lifecycle_summary(checkpoint)
        if isinstance(payload, Mapping):
            return dict(payload), diagnostics
    except Exception as exc:
        diagnostics.append(f"lifecycle:{type(exc).__name__}:{exc}")
    return {}, diagnostics


def _latest_archive(state: Any, active_team: str, team_names: Mapping[str, str]) -> dict[str, Any]:
    history = list(getattr(state, "season_history", []) or [])
    if not history:
        return {
            "available": False,
            "season": "",
            "record": "",
            "result": "",
            "champion": "",
            "champion_name": "",
        }

    archive = history[-1]
    season = _clean(getattr(archive, "season_label", ""))
    standings = dict(getattr(archive, "standings", {}) or {})
    standing = standings.get(active_team)
    wins = _safe_int(getattr(standing, "wins", 0)) if standing is not None else 0
    losses = _safe_int(getattr(standing, "losses", 0)) if standing is not None else 0

    champion = _team(getattr(archive, "champion", ""))
    runner_up = _team(getattr(archive, "runner_up", ""))
    conference_champions = {
        _team(value)
        for value in dict(getattr(archive, "conference_champions", {}) or {}).values()
    }

    result = "REGULAR SEASON"
    if champion == active_team:
        result = "NBA CHAMPION"
    elif runner_up == active_team:
        result = "NBA FINALS"
    elif active_team in conference_champions:
        result = "CONFERENCE CHAMPION"
    else:
        postseason = getattr(archive, "postseason_state", None)
        seed_by_team = dict(getattr(postseason, "seed_by_team", {}) or {}) if postseason else {}
        if active_team in {_team(key) for key in seed_by_team}:
            result = "PLAYOFFS"

    return {
        "available": True,
        "season": season,
        "record": f"{wins}-{losses}",
        "wins": wins,
        "losses": losses,
        "result": result,
        "champion": champion,
        "champion_name": _team_name(team_names, champion) if champion else "",
        "runner_up": runner_up,
        "runner_up_name": _team_name(team_names, runner_up) if runner_up else "",
    }


def _stage_statuses(
    *,
    state: Any,
    lifecycle: Mapping[str, Any],
    draft: Mapping[str, Any],
    roster: Mapping[str, Any],
) -> list[dict[str, Any]]:
    phase = _enum(getattr(state, "phase", ""))
    lifecycle_stage = _clean(lifecycle.get("stage", "")).lower()
    lifecycle_timeline = {
        _clean(row.get("key", "")).lower(): _clean(row.get("status", "")).lower()
        for row in lifecycle.get("timeline", []) or []
        if isinstance(row, Mapping)
    }

    draft_info = dict(draft.get("draft", {}) or {})
    draft_phase = _clean(draft_info.get("phase", "")).lower()
    draft_initialized = bool(draft.get("draft_initialized", False))
    draft_complete = draft_phase == "draft_complete" or bool(
        draft_info.get("complete", False)
    )
    post_draft = dict(draft.get("post_draft_roster", {}) or {})
    cuts_remaining = _safe_int(post_draft.get("cuts_remaining", 0))

    def timeline_status(key: str, fallback: str = "locked") -> str:
        return lifecycle_timeline.get(key, fallback)

    stages = [
        {
            "key": "season_recap",
            "label": "SEASON RECAP",
            "kicker": "YEAR IN REVIEW",
            "status": (
                "complete"
                if phase == "offseason"
                else ("current" if phase == "regular_season" else "available")
            ),
            "detail": (
                "Review the completed season and franchise legacy before roster construction."
                if phase == "offseason"
                else "The offseason recap unlocks when the season reaches its boundary."
            ),
            "destination": "LEGACY",
        },
        {
            "key": "contract_closeout",
            "label": "CONTRACT CLOSEOUT",
            "kicker": "EXPIRING DEALS",
            "status": timeline_status("closeout"),
            "detail": "Expire completed contracts and open the real offseason market.",
            "destination": "SEASON",
        },
        {
            "key": "cpu_market",
            "label": "LEAGUE ROSTER MARKET",
            "kicker": "CPU FREE AGENCY",
            "status": timeline_status("cpu_free_agency"),
            "detail": "CPU front offices fill sustainable roster deficits through production free agency.",
            "destination": "SEASON",
        },
        {
            "key": "draft_lottery",
            "label": "DRAFT LOTTERY",
            "kicker": "ORDER REVEAL",
            "status": timeline_status("draft_lottery"),
            "detail": "Set the lottery order and reveal the incoming prospect class.",
            "destination": "SEASON",
        },
        {
            "key": "scouting",
            "label": "PRE-DRAFT SCOUTING",
            "kicker": "WAR ROOM",
            "status": (
                "current"
                if draft_phase == "scouting"
                else (
                    "complete"
                    if draft_phase in {"draft_in_progress", "draft_complete"}
                    else ("available" if draft_initialized else "locked")
                )
            ),
            "detail": "Use scouting confidence, focus prospects, and team needs before Draft Night.",
            "destination": "SCOUTING",
        },
        {
            "key": "draft_night",
            "label": "DRAFT NIGHT",
            "kicker": "ON THE CLOCK",
            "status": timeline_status("draft_night"),
            "detail": "Make selections through the certified Draft engine and preserve pick history.",
            "destination": "SCOUTING",
        },
        {
            "key": "post_draft",
            "label": "POST-DRAFT ROSTER",
            "kicker": "ROOKIE INTEGRATION",
            "status": (
                "current"
                if draft_complete and cuts_remaining > 0
                else (
                    "complete"
                    if draft_complete and cuts_remaining == 0
                    else "locked"
                )
            ),
            "detail": (
                f"{cuts_remaining} roster cut decision(s) remain."
                if cuts_remaining > 0
                else "Resolve rookie integration, standard roster limits, and two-way structure."
            ),
            "destination": "SCOUTING" if cuts_remaining > 0 else "ROSTER",
        },
        {
            "key": "user_free_agency",
            "label": "FREE AGENCY",
            "kicker": "PLAYER MARKET",
            "status": "current" if phase == "offseason" else "locked",
            "detail": "Negotiate with the live market through preview-first CBA and contract safety.",
            "destination": "FREE AGENCY",
        },
        {
            "key": "summer_development",
            "label": "SUMMER DEVELOPMENT",
            "kicker": "YOUNG CORE",
            "status": (
                "available"
                if phase == "offseason" or draft_complete
                else "planning"
            ),
            "detail": "Prioritize young-player development and identify the next rotation leap.",
            "destination": "ROSTER",
        },
        {
            "key": "camp",
            "label": "TRAINING CAMP",
            "kicker": "ROSTER BATTLES",
            "status": (
                "ready"
                if int(roster.get("standard_count", 0)) in {14, 15}
                and int(roster.get("rotation_count", 0)) >= 8
                else "planning"
            ),
            "detail": "Audit the 14–15 player standard roster, two-way slots, position coverage, and rotation depth.",
            "destination": "ROSTER",
        },
        {
            "key": "opening_night",
            "label": "OPENING NIGHT",
            "kicker": "NEXT SEASON",
            "status": timeline_status("next_season"),
            "detail": "Commit the certified season boundary only after Draft and roster gates are complete.",
            "destination": "SEASON",
        },
    ]

    current_index = next(
        (index for index, row in enumerate(stages) if row["status"] == "current"),
        -1,
    )
    if current_index < 0:
        current_index = next(
            (
                index
                for index, row in enumerate(stages)
                if row["status"] in {"ready", "available", "planning"}
            ),
            0,
        )

    for index, row in enumerate(stages):
        row["index"] = index
        row["current_focus"] = index == current_index

    return stages


def _market_watch(
    state: Any,
    market: Mapping[str, Any],
    *,
    limit: int = 10,
) -> dict[str, Any]:
    players = [
        dict(row)
        for row in market.get("players", []) or []
        if isinstance(row, Mapping)
    ]
    if not players:
        players = _raw_free_agents(state, limit=max(limit, 12))

    players.sort(
        key=lambda row: (
            -float(row.get("overall") or 0.0),
            -float(row.get("potential") or 0.0),
            float(row.get("age") if row.get("age") is not None else 99.0),
            str(row.get("name", "")),
        )
    )

    top = []
    for row in players[:limit]:
        top.append(
            {
                "player_id": _clean(row.get("player_id")),
                "name": _clean(row.get("name") or row.get("player_name")),
                "position": _clean(row.get("position")),
                "age": row.get("age"),
                "overall": row.get("overall"),
                "potential": row.get("potential"),
                "salary": row.get("salary"),
            }
        )

    return {
        "total_available": len(players),
        "top_available": top,
        "market_source": (
            "production_free_agency_market"
            if market.get("players") is not None
            else "simulation_free_agent_pool"
        ),
    }


def _draft_watch(draft: Mapping[str, Any], *, limit: int = 10) -> dict[str, Any]:
    draft_info = dict(draft.get("draft", {}) or {})
    summary = dict(draft.get("summary", {}) or {})
    board = [
        dict(row)
        for row in draft.get("board", []) or []
        if isinstance(row, Mapping)
    ]

    def score(row: Mapping[str, Any]) -> float:
        for key in (
            "Scouted POT",
            "scouted_potential",
            "projected_potential",
            "potential",
            "Scouted OVR",
            "scouted_overall",
            "projected_overall",
            "overall",
            "team_fit_score",
        ):
            value = row.get(key)
            if isinstance(value, (int, float)):
                return float(value)
        return 0.0

    board.sort(
        key=lambda row: (
            -score(row),
            _clean(row.get("player_name") or row.get("name")),
        )
    )

    prospects: list[dict[str, Any]] = []
    for row in board[:limit]:
        prospects.append(
            {
                "prospect_id": _clean(row.get("prospect_id")),
                "name": _clean(
                    row.get("Prospect")
                    or row.get("player_name")
                    or row.get("name")
                    or row.get("prospect_id")
                ),
                "position": _clean(
                    row.get("Pos")
                    or row.get("position")
                ),
                "archetype": _clean(
                    row.get("Archetype")
                    or row.get("archetype")
                ),
                "confidence": row.get(
                    "Confidence",
                    row.get("confidence"),
                ),
                "scouted_overall": row.get(
                    "Scouted OVR",
                    row.get(
                        "scouted_overall",
                        row.get("projected_overall", row.get("overall")),
                    ),
                ),
                "scouted_potential": row.get(
                    "Scouted POT",
                    row.get(
                        "scouted_potential",
                        row.get("projected_potential", row.get("potential")),
                    ),
                ),
            }
        )

    return {
        "initialized": bool(draft.get("draft_initialized", False)),
        "draft_year": draft_info.get("draft_year"),
        "phase": _clean(draft_info.get("phase")),
        "current_pick": _json_safe(draft_info.get("current_pick", {})),
        "available_prospect_count": _safe_int(
            draft_info.get("available_prospect_count", len(board))
        ),
        "weeks_completed": _safe_int(summary.get("weeks_completed", 0)),
        "average_confidence": summary.get(
            "average_confidence",
            summary.get("avg_confidence"),
        ),
        "lead_scout": _json_safe(draft.get("lead_scout", {})),
        "top_prospects": prospects,
        "post_draft_roster": _json_safe(draft.get("post_draft_roster", {})),
    }


def _camp_readiness(roster: Mapping[str, Any]) -> dict[str, Any]:
    position_counts = dict(roster.get("position_counts", {}) or {})
    covered_positions = sum(
        1
        for position in ("PG", "SG", "SF", "PF", "C")
        if _safe_int(position_counts.get(position, 0)) >= 2
    )
    standard = _safe_int(roster.get("standard_count", 0))
    two_way = _safe_int(roster.get("two_way_count", 0))
    rotation = _safe_int(roster.get("rotation_count", 0))
    starters = _safe_int(roster.get("starter_count", 0))

    score = 0
    score += 30 if 14 <= standard <= 15 else max(0, 30 - abs(15 - standard) * 8)
    score += min(20, covered_positions * 4)
    score += min(20, rotation * 2)
    score += 15 if starters == 5 else min(15, starters * 3)
    score += min(15, two_way * 5)
    score = max(0, min(100, score))

    if score >= 90:
        grade = "A"
        label = "OPENING-NIGHT READY"
    elif score >= 80:
        grade = "B"
        label = "ONE OR TWO DECISIONS AWAY"
    elif score >= 68:
        grade = "C"
        label = "CAMP COMPETITION NEEDED"
    elif score >= 55:
        grade = "D"
        label = "ROSTER WORK REMAINS"
    else:
        grade = "F"
        label = "MAJOR ROSTER WORK"

    return {
        "score": score,
        "grade": grade,
        "label": label,
        "standard_roster": standard,
        "two_way_roster": two_way,
        "rotation_players": rotation,
        "starters": starters,
        "covered_positions": covered_positions,
        "position_counts": position_counts,
        "model_note": (
            "Readiness is a simulator planning grade based on roster size, "
            "position redundancy, rotation depth, starters, and two-way usage. "
            "It is not a prediction of team quality."
        ),
    }


def _decision_checklist(
    *,
    lifecycle: Mapping[str, Any],
    roster: Mapping[str, Any],
    draft_watch: Mapping[str, Any],
    market_watch: Mapping[str, Any],
    camp: Mapping[str, Any],
) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []

    stage = _clean(lifecycle.get("stage", ""))
    next_action = _clean(lifecycle.get("next_action", ""))
    next_label = _clean(lifecycle.get("next_action_label", ""))
    blockers = [str(value) for value in lifecycle.get("blockers", []) or []]

    if next_action:
        tasks.append(
            {
                "priority": "CRITICAL",
                "title": next_label or next_action.replace("_", " ").upper(),
                "detail": "The certified Season Command lifecycle identifies this as the next durable league boundary.",
                "destination": "SEASON",
                "status": "ACTIONABLE",
            }
        )
    elif blockers:
        tasks.append(
            {
                "priority": "HIGH",
                "title": "CLEAR LIFECYCLE BLOCKERS",
                "detail": blockers[0],
                "destination": "SEASON",
                "status": "BLOCKED",
            }
        )

    open_standard = _safe_int(roster.get("open_standard_slots", 0))
    if open_standard > 0:
        tasks.append(
            {
                "priority": "HIGH" if open_standard >= 2 else "MEDIUM",
                "title": f"FILL {open_standard} STANDARD ROSTER SLOT(S)",
                "detail": (
                    f"The roster is below the {STANDARD_ROSTER_TARGET}-player standard target."
                ),
                "destination": "FREE AGENCY",
                "status": "OPEN",
            }
        )

    if _safe_int(camp.get("covered_positions", 0)) < 5:
        tasks.append(
            {
                "priority": "MEDIUM",
                "title": "IMPROVE POSITION REDUNDANCY",
                "detail": "At least one position group has fewer than two standard-roster players.",
                "destination": "ROSTER",
                "status": "REVIEW",
            }
        )

    if bool(draft_watch.get("initialized")) and _clean(draft_watch.get("phase")) in {
        "season_scouting",
        "scouting",
    }:
        tasks.append(
            {
                "priority": "HIGH",
                "title": "LOCK THE DRAFT BOARD",
                "detail": (
                    f"{draft_watch.get('available_prospect_count', 0)} prospects remain available. "
                    "Use scouting confidence and focus assignments before Draft Night."
                ),
                "destination": "SCOUTING",
                "status": "OPEN",
            }
        )

    if _safe_int(market_watch.get("total_available", 0)) > 0:
        tasks.append(
            {
                "priority": "MEDIUM",
                "title": "AUDIT THE FREE-AGENT MARKET",
                "detail": (
                    f"{market_watch.get('total_available', 0)} player(s) are visible in the current market snapshot."
                ),
                "destination": "FREE AGENCY",
                "status": "OPEN",
            }
        )

    if _safe_int(roster.get("open_two_way_slots", 0)) > 0:
        tasks.append(
            {
                "priority": "LOW",
                "title": "USE TWO-WAY CAPACITY",
                "detail": (
                    f"{roster.get('open_two_way_slots', 0)} two-way slot(s) remain in the planning model."
                ),
                "destination": "ROSTER",
                "status": "OPTIONAL",
            }
        )

    if not tasks:
        tasks.append(
            {
                "priority": "LOW",
                "title": "OFFSEASON BOARD IS CLEAR",
                "detail": f"No immediate planning flag was generated from lifecycle stage '{stage or 'unknown'}'.",
                "destination": "SEASON",
                "status": "CLEAR",
            }
        )

    priority_rank = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
    tasks.sort(
        key=lambda row: (
            priority_rank.get(str(row["priority"]), 9),
            str(row["title"]),
        )
    )
    return tasks[:8]


def build_offseason_command_payload(
    checkpoint: Any,
    *,
    team_names: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    state = getattr(checkpoint, "simulation_state", None)
    trade_state = getattr(checkpoint, "trade_state", None)
    if state is None:
        raise RuntimeError("V3 working checkpoint has no simulation state.")
    if trade_state is None:
        raise RuntimeError("V3 working checkpoint has no durable trade state.")

    names = dict(team_names or {})
    active_team = _active_team(checkpoint)
    if not active_team:
        raise RuntimeError("V3 working checkpoint has no active franchise team.")

    diagnostics: list[str] = []
    lifecycle, lifecycle_errors = _lifecycle_payload(checkpoint)
    diagnostics.extend(lifecycle_errors)
    market, market_errors = _market_payload(checkpoint, active_team)
    diagnostics.extend(market_errors)
    draft, draft_errors = _draft_payload(checkpoint, active_team)
    diagnostics.extend(draft_errors)

    roster = _roster_payload(state, active_team)
    market_watch = _market_watch(state, market, limit=10)
    draft_watch = _draft_watch(draft, limit=10)
    young_core = _young_core(roster, limit=10)
    roster_battles = _roster_battles(roster, limit=10)
    camp = _camp_readiness(roster)
    stages = _stage_statuses(
        state=state,
        lifecycle=lifecycle,
        draft=draft,
        roster=roster,
    )
    latest = _latest_archive(state, active_team, names)
    checklist = _decision_checklist(
        lifecycle=lifecycle,
        roster=roster,
        draft_watch=draft_watch,
        market_watch=market_watch,
        camp=camp,
    )

    phase = _enum(getattr(state, "phase", ""))
    season_label = _clean(
        getattr(getattr(state, "settings", None), "season_label", "")
    )
    current_stage = next(
        (
            row
            for row in stages
            if bool(row.get("current_focus"))
        ),
        stages[0] if stages else {},
    )

    top_roster = [
        {
            "player_id": row.get("player_id"),
            "name": row.get("name"),
            "position": row.get("position"),
            "age": row.get("age"),
            "overall": row.get("overall"),
            "potential": row.get("potential"),
            "future_outlook": row.get("future_outlook"),
            "two_way": bool(row.get("contract", {}).get("two_way")),
            "salary": row.get("contract", {}).get("salary"),
            "years_remaining": row.get("contract", {}).get("years_remaining"),
        }
        for row in roster.get("players", [])[:8]
    ]

    return {
        "foundation_version": OFFSEASON_COMMAND_FOUNDATION_VERSION,
        "read_only": True,
        "working_save_only": True,
        "working_save_write_performed": False,
        "active_v2_read_only": True,
        "team": active_team,
        "team_name": _team_name(names, active_team),
        "season": {
            "label": season_label,
            "phase": phase,
            "day_index": _safe_int(getattr(state, "current_day_index", 0)),
            "offseason_active": phase == "offseason",
        },
        "command": {
            "headline": (
                "OFFSEASON COMMAND CENTER"
                if phase == "offseason"
                else "OFFSEASON WAR ROOM • PREP MODE"
            ),
            "current_stage": _json_safe(current_stage),
            "next_certified_action": _clean(lifecycle.get("next_action", "")),
            "next_certified_action_label": _clean(
                lifecycle.get("next_action_label", "NO ACTION AVAILABLE")
            ),
            "lifecycle_stage": _clean(lifecycle.get("stage", "")),
            "blockers": _json_safe(lifecycle.get("blockers", [])),
        },
        "roadmap": stages,
        "lifecycle": _json_safe(lifecycle),
        "roster": {
            **{key: value for key, value in roster.items() if key != "players"},
            "top_roster": top_roster,
        },
        "camp_readiness": camp,
        "young_core": young_core,
        "roster_battles": roster_battles,
        "market_watch": market_watch,
        "draft_watch": draft_watch,
        "last_season": latest,
        "decision_checklist": checklist,
        "shortcuts": [
            {
                "label": "SEASON COMMAND",
                "detail": "Preview and commit certified lifecycle boundaries.",
                "destination": "SEASON",
            },
            {
                "label": "SCOUTING & DRAFT",
                "detail": "Scout the class, run Draft Night, and resolve post-Draft cuts.",
                "destination": "SCOUTING",
            },
            {
                "label": "FREE AGENCY",
                "detail": "Negotiate production contracts with preview-first safety.",
                "destination": "FREE AGENCY",
            },
            {
                "label": "ROSTER",
                "detail": "Audit depth, development, roles, and rotation structure.",
                "destination": "ROSTER",
            },
            {
                "label": "LEGACY",
                "detail": "Review the season archive and franchise history.",
                "destination": "LEGACY",
            },
        ],
        "system_scope": {
            "summer_league_simulation_available": False,
            "training_camp_simulation_available": True,
            "planning_surfaces_available": True,
            "note": (
                "Expansion 40 uses real lifecycle, Draft, market, roster, and contract state. "
                "Summer Development remains a planning surface. Expansion 41 adds one focused skill camp "
                "per offseason with previewed, saved outcomes and CPU participation. Summer League games are not simulated."
            ),
        },
        "diagnostics": diagnostics,
    }
