from __future__ import annotations

import math
from typing import Any


FRANCHISE_MORALE_CHEMISTRY_VERSION = (
    "franchise-morale-chemistry-v1.3-2026-09-16"
)
MORALE_STATE_ATTR = "franchise_morale_chemistry_v1"
MAX_RECENT_GAMES = 10
PROMISE_REVIEW_DEFAULT_GAMES = 5
MEETING_ACTIONS = (
    "Reassure and listen",
    "Ask for patience",
    "Reset expectations honestly",
)
TRADE_RESPONSE_OPTIONS = (
    "Keep internal",
    "Listening to offers",
    "On trade block",
)

ROLE_PRESETS: dict[str, tuple[str, float]] = {
    "Auto": ("Auto", 0.0),
    "Featured starter": ("Featured starter", 32.0),
    "Starter": ("Starter", 28.0),
    "Sixth man": ("Sixth man", 24.0),
    "Rotation": ("Rotation", 19.0),
    "Bench rotation": ("Bench rotation", 13.0),
    "Prospect development": ("Prospect development", 16.0),
    "Reserve": ("Reserve", 5.0),
}


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _team(value: Any) -> str:
    return _clean(value).upper()


def _num(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return float(default)
    return result if math.isfinite(result) else float(default)


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, float(value)))


def _season(state: Any) -> str:
    return _clean(getattr(getattr(state, "settings", None), "season_label", ""))


def _day(state: Any) -> int:
    return _int(getattr(state, "current_day_index", 0), 0)


def ensure_morale_state_v1(state: Any) -> dict[str, Any]:
    """Return the durable morale payload and migrate older V1 payloads in place."""
    payload = getattr(state, MORALE_STATE_ATTR, None)
    if not isinstance(payload, dict):
        payload = {}
        setattr(state, MORALE_STATE_ATTR, payload)

    payload["version"] = FRANCHISE_MORALE_CHEMISTRY_VERSION
    payload.setdefault("season", _season(state))
    payload.setdefault("players", {})
    payload.setdefault("teams", {})
    payload.setdefault("processed_game_ids", [])
    payload.setdefault("role_promises", {})
    payload.setdefault("trade_request_history", [])
    payload.setdefault("event_history", [])
    payload.setdefault("rotation_emphasis", {})
    payload.setdefault("meetings", {})
    payload.setdefault("trade_responses", {})

    if payload.get("season") != _season(state):
        # Morale carries over with a soft offseason reset. Game ledgers and
        # short-term streak counters do not, which prevents reused game ids or
        # last season's frustration from instantly triggering a new request.
        payload["season"] = _season(state)
        payload["processed_game_ids"] = []
        for record in list((payload.get("players") or {}).values()):
            if not isinstance(record, dict):
                continue
            score = _num(record.get("score"), 70.0)
            record["score"] = round(score + (70.0 - score) * 0.28, 2)
            record["recent_games"] = []
            previous_request_active = bool(record.get("trade_request_active"))
            previous_request_status = _clean(record.get("trade_request_status"))
            had_broken_promise = _int(record.get("broken_promise_games"), 0) > 0
            record["offseason_grievance_games"] = (
                8 if previous_request_active or previous_request_status == "Requested trade"
                else 5 if score < 49 or had_broken_promise
                else 0
            )
            record["low_morale_games"] = 0
            record["high_risk_games"] = 0
            record["recovery_games"] = 0
            record["meeting_cooldown_games"] = 0
            record["meeting_support_games"] = 0
            record["patience_games"] = 0
            record["broken_promise_games"] = max(0, _int(record.get("broken_promise_games"), 0) - 2)
            record["kept_promise_games"] = 0
            if record.get("trade_request_status") != "Requested trade":
                record["trade_request_status"] = "None"
                record["trade_request_active"] = False
    return payload


def _rotation_context(state: Any, team: str) -> dict[str, dict[str, Any]]:
    team_state = (getattr(state, "teams", {}) or {}).get(team)
    if team_state is None:
        return {}
    rotation = getattr(team_state, "rotation", None)
    starters = set(tuple(getattr(rotation, "starter_ids", ()) or ()))
    rotation_ids = list(tuple(getattr(rotation, "rotation_player_ids", ()) or ()))
    minutes = dict(getattr(rotation, "minutes_targets", {}) or {})
    order = {str(pid): index + 1 for index, pid in enumerate(rotation_ids)}
    result: dict[str, dict[str, Any]] = {}
    for player_id in tuple(getattr(team_state, "roster_player_ids", ()) or ()):
        pid = str(player_id)
        result[pid] = {
            "starter": pid in starters,
            "in_rotation": pid in order,
            "rotation_order": order.get(pid, 99),
            "planned_minutes": _num(minutes.get(pid), 0.0),
        }
    return result


def _automatic_expected_role(state: Any, team: str, player_id: str) -> dict[str, Any]:
    team_state = (getattr(state, "teams", {}) or {}).get(team)
    players = getattr(state, "players", {}) or {}
    player = players.get(player_id)
    if team_state is None or player is None:
        return {"expected_minutes": 0.0, "expected_role": "Reserve", "rank": 99}

    roster = [
        players.get(str(pid))
        for pid in tuple(getattr(team_state, "roster_player_ids", ()) or ())
        if players.get(str(pid)) is not None
    ]
    ordered = sorted(
        roster,
        key=lambda row: (
            -_num(getattr(row, "overall_rating", 0.0)),
            -_num(getattr(row, "potential_rating", 0.0)),
            _clean(getattr(row, "player_name", "")),
        ),
    )
    rank = 99
    for index, row in enumerate(ordered, start=1):
        if _clean(getattr(row, "player_id", "")) == player_id:
            rank = index
            break

    expected = 5.0
    role = "Reserve"
    if rank <= 2:
        expected, role = 32.0, "Featured starter"
    elif rank <= 5:
        expected, role = 28.0, "Starter"
    elif rank == 6:
        expected, role = 24.0, "Sixth man"
    elif rank <= 8:
        expected, role = 19.0, "Rotation"
    elif rank <= 10:
        expected, role = 13.0, "Bench rotation"

    age = _num(getattr(player, "age", 27.0), 27.0)
    draft_pick = _int(getattr(player, "draft_pick", 0), 0)
    rookie_season = _clean(getattr(player, "rookie_season", ""))
    if rookie_season == _season(state) and draft_pick:
        if draft_pick <= 5:
            expected = max(expected, 24.0)
            role = "Lottery development priority"
        elif draft_pick <= 14:
            expected = max(expected, 19.0)
            role = "Lottery rotation opportunity"
        elif draft_pick <= 30:
            expected = max(expected, 12.0)
            role = "First-round development role"
    if age <= 22 and _num(getattr(player, "potential_rating", 0.0)) >= 84:
        expected = max(expected, 16.0)
        if rank > 8:
            role = "Prospect development"

    return {
        "expected_minutes": round(expected, 1),
        "expected_role": role,
        "rank": rank,
    }


def _role_promise(state: Any, team: str, player_id: str) -> dict[str, Any] | None:
    payload = ensure_morale_state_v1(state)
    raw = (payload.get("role_promises") or {}).get(player_id)
    if not isinstance(raw, dict) or _team(raw.get("team")) != team:
        return None
    # Role promises are season-specific. Old-season promises remain in the
    # audit payload but never silently carry into a new season.
    promise_season = _clean(raw.get("season"))
    if promise_season and promise_season != _season(state):
        return None
    return raw


def _trade_response(state: Any, team: str, player_id: str) -> str:
    payload = ensure_morale_state_v1(state)
    raw = (payload.get("trade_responses") or {}).get(player_id)
    if isinstance(raw, dict) and _team(raw.get("team")) == team:
        value = _clean(raw.get("response"))
    else:
        value = _clean(raw)
    return value if value in TRADE_RESPONSE_OPTIONS else "Keep internal"


def _counter(existing: dict[str, Any] | None, name: str) -> int:
    return _int((existing or {}).get(name), 0) if isinstance(existing, dict) else 0


def _expected_role(state: Any, team: str, player_id: str) -> dict[str, Any]:
    automatic = _automatic_expected_role(state, team, player_id)
    promise = _role_promise(state, team, player_id)
    if not promise:
        return {**automatic, "promise_active": False, "automatic_role": automatic["expected_role"], "automatic_minutes": automatic["expected_minutes"]}
    promised_role = _clean(promise.get("role")) or automatic["expected_role"]
    promised_minutes = _clamp(
        _num(promise.get("minutes"), automatic["expected_minutes"]),
        0.0,
        40.0,
    )
    return {
        **automatic,
        "expected_minutes": round(promised_minutes, 1),
        "expected_role": promised_role,
        "promise_active": True,
        "automatic_role": automatic["expected_role"],
        "automatic_minutes": automatic["expected_minutes"],
        "promise_set_day": _int(promise.get("set_day"), 0),
    }


def _season_minutes(state: Any, player_id: str, planned: float) -> tuple[float, int]:
    totals = (getattr(state, "player_season_totals", {}) or {}).get(player_id)
    games = _int(getattr(totals, "games_played", 0), 0) if totals is not None else 0
    if games <= 0:
        return round(planned, 1), 0
    season_mpg = _num(getattr(totals, "minutes", 0.0)) / max(1, games)
    actual_weight = _clamp(games / 15.0, 0.20, 1.0)
    return round((1.0 - actual_weight) * planned + actual_weight * season_mpg, 1), games


def _recent_minutes(existing: dict[str, Any] | None) -> tuple[float | None, float | None, int]:
    if not isinstance(existing, dict):
        return None, None, 0
    recent = [row for row in list(existing.get("recent_games", []) or []) if isinstance(row, dict)]
    if not recent:
        return None, None, 0
    sample = recent[-5:]
    mpg = sum(_num(row.get("minutes"), 0.0) for row in sample) / len(sample)
    start_rate = sum(bool(row.get("started")) for row in sample) / len(sample)
    return round(mpg, 1), round(start_rate, 3), len(sample)


def _status(score: float) -> str:
    if score >= 88:
        return "Thriving"
    if score >= 76:
        return "Happy"
    if score >= 62:
        return "Content"
    if score >= 49:
        return "Uneasy"
    if score >= 36:
        return "Frustrated"
    return "Disgruntled"


def _trade_request_stage(
    score: float,
    risk: float,
    low_morale_games: int,
    high_risk_games: int,
    previous_status: str,
    recovery_games: int,
) -> tuple[str, bool]:
    # A request requires sustained unhappiness. A single bad game or rotation
    # edit can create pressure, but cannot instantly force a trade request.
    if previous_status == "Requested trade":
        if score >= 64 and recovery_games >= 5:
            return "Withdrawn request", False
        return "Requested trade", True
    if risk >= 76 and low_morale_games >= 4 and high_risk_games >= 3:
        return "Requested trade", True
    if risk >= 62 and low_morale_games >= 3:
        return "Considering request", False
    if risk >= 45 or low_morale_games >= 2:
        return "Pressure building", False
    if previous_status == "Withdrawn request" and recovery_games < 3:
        return "Withdrawn request", False
    return "None", False


def _morale_target(state: Any, team: str, player_id: str) -> dict[str, Any]:
    payload = ensure_morale_state_v1(state)
    players = getattr(state, "players", {}) or {}
    player = players.get(player_id)
    existing = (payload.get("players") or {}).get(player_id)
    if player is None:
        return {
            "target": 70.0,
            "role_satisfaction": 70.0,
            "expected_minutes": 0.0,
            "actual_minutes": 0.0,
            "expected_role": "Reserve",
            "reasons": ["No live player context"],
        }

    rotation = _rotation_context(state, team).get(player_id, {})
    expected = _expected_role(state, team, player_id)
    planned = _num(rotation.get("planned_minutes"), 0.0)
    season_actual, games = _season_minutes(state, player_id, planned)
    recent_mpg, recent_start_rate, recent_sample = _recent_minutes(existing if isinstance(existing, dict) else None)
    if recent_mpg is None:
        actual = season_actual
    else:
        recent_weight = _clamp(recent_sample / 5.0, 0.25, 0.60)
        actual = round(season_actual * (1.0 - recent_weight) + recent_mpg * recent_weight, 1)

    minute_gap = actual - _num(expected["expected_minutes"])
    role_satisfaction = 70.0 + minute_gap * 2.25
    rank = _int(expected.get("rank"), 99)
    starter = bool(rotation.get("starter"))
    if rank <= 5 and not starter:
        role_satisfaction -= 9.0
    if bool(expected.get("promise_active")):
        promised_role = _clean(expected.get("expected_role")).lower()
        if "starter" in promised_role and not starter:
            role_satisfaction -= 12.0
        elif "sixth" in promised_role and _int(rotation.get("rotation_order"), 99) > 7:
            role_satisfaction -= 6.0
        elif promised_role in {"rotation", "prospect development"} and not bool(rotation.get("in_rotation")):
            role_satisfaction -= 8.0
    if rank >= 9 and starter:
        role_satisfaction += 5.0
    role_satisfaction = _clamp(role_satisfaction, 8.0, 98.0)

    standing = (getattr(state, "standings", {}) or {}).get(team)
    wins = _int(getattr(standing, "wins", 0), 0) if standing is not None else 0
    losses = _int(getattr(standing, "losses", 0), 0) if standing is not None else 0
    standing_games = wins + losses
    win_pct = wins / standing_games if standing_games else 0.5
    team_success = 50.0 + (win_pct - 0.5) * 48.0
    streak_type = _clean(getattr(standing, "streak_type", "")).upper() if standing is not None else ""
    streak_length = _int(getattr(standing, "streak_length", 0), 0) if standing is not None else 0
    streak_effect = 0.0
    if streak_length >= 3:
        streak_effect = min(5.0, streak_length * 0.75) * (1.0 if streak_type.startswith("W") else -1.0)

    age = _num(getattr(player, "age", 27.0), 27.0)
    development_bonus = 0.0
    if age <= 24:
        development_bonus = _clamp((actual - 12.0) * 0.45, -5.0, 7.0)

    contract = getattr(player, "contract", None)
    years_remaining = _int(getattr(contract, "years_remaining", 99), 99) if contract is not None else 99
    contract_pressure = 0.0
    if years_remaining == 1 and _num(getattr(player, "overall_rating", 0.0)) >= 76:
        contract_pressure = _clamp(minute_gap * 0.20, -4.0, 2.0)

    broken_promise_games = _counter(existing, "broken_promise_games")
    kept_promise_games = _counter(existing, "kept_promise_games")
    meeting_support_games = _counter(existing, "meeting_support_games")
    patience_games = _counter(existing, "patience_games")
    offseason_grievance_games = _counter(existing, "offseason_grievance_games")
    promise_memory = (
        -7.0 if broken_promise_games > 0 else
        2.5 if kept_promise_games > 0 else 0.0
    )
    meeting_effect = 1.5 if meeting_support_games > 0 else (0.5 if patience_games > 0 else 0.0)
    offseason_memory = -4.0 if offseason_grievance_games > 0 else 0.0

    target = (
        role_satisfaction * 0.68
        + team_success * 0.20
        + 70.0 * 0.12
        + development_bonus
        + streak_effect
        + contract_pressure
        + promise_memory
        + meeting_effect
        + offseason_memory
    )
    target = _clamp(target, 6.0, 97.0)

    reasons: list[tuple[float, str]] = []
    if minute_gap >= 4:
        reasons.append((abs(minute_gap) + 2.0, "Playing time is exceeding expectations"))
    elif minute_gap <= -4:
        reasons.append((abs(minute_gap) + 2.0, "Playing time is below role expectations"))
    if rank <= 5 and not starter:
        reasons.append((9.0, "Expects a starting role"))
    if bool(expected.get("promise_active")):
        if "starter" in _clean(expected.get("expected_role")).lower() and not starter:
            reasons.append((12.0, "A promised starting role is not being met"))
        elif minute_gap <= -3:
            reasons.append((10.0, "Promised minutes are not being met"))
        else:
            reasons.append((4.0, "Front-office role promise is being honored"))
    if win_pct >= 0.62 and standing_games >= 8:
        reasons.append((6.0, "Winning is lifting locker-room confidence"))
    elif win_pct <= 0.38 and standing_games >= 8:
        reasons.append((6.0, "Team results are creating frustration"))
    if streak_effect >= 3:
        reasons.append((4.5, "A winning streak is building confidence"))
    elif streak_effect <= -3:
        reasons.append((4.5, "A losing streak is adding pressure"))
    if age <= 24 and actual >= 18:
        reasons.append((4.0, "Development opportunity is meaningful"))
    if years_remaining == 1 and minute_gap <= -4:
        reasons.append((3.5, "Contract-year role pressure is increasing"))
    if recent_mpg is not None and recent_mpg + 4 < expected["expected_minutes"]:
        reasons.append((5.5, "Recent-game usage has fallen below expectations"))
    if broken_promise_games > 0:
        reasons.append((12.5, "A recent front-office promise was broken"))
    elif kept_promise_games > 0:
        reasons.append((4.5, "A recent front-office promise was kept"))
    if meeting_support_games > 0:
        reasons.append((3.5, "A recent player meeting eased immediate tension"))
    elif patience_games > 0:
        reasons.append((2.5, "The player agreed to give the front office time to respond"))
    if offseason_grievance_games > 0:
        reasons.append((7.0, "Frustration from last season has carried into this year"))
    if not reasons:
        reasons.append((1.0, "Role and team context are stable"))
    reasons.sort(key=lambda item: (-item[0], item[1]))

    return {
        "target": round(target, 2),
        "role_satisfaction": round(role_satisfaction, 2),
        "team_success": round(team_success, 2),
        "expected_minutes": round(_num(expected["expected_minutes"]), 1),
        "actual_minutes": round(actual, 1),
        "recent_minutes": recent_mpg,
        "expected_role": expected["expected_role"],
        "automatic_role": expected.get("automatic_role", expected["expected_role"]),
        "promise_active": bool(expected.get("promise_active")),
        "rotation_order": _int(rotation.get("rotation_order"), 99),
        "starter": starter,
        "in_rotation": bool(rotation.get("in_rotation")),
        "games": games,
        "minute_gap": round(minute_gap, 1),
        "broken_promise_games": broken_promise_games,
        "kept_promise_games": kept_promise_games,
        "meeting_support_games": meeting_support_games,
        "patience_games": patience_games,
        "offseason_grievance_games": offseason_grievance_games,
        "reasons": [text for _, text in reasons[:4]],
    }


def _chemistry_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {
            "chemistry": 0.0,
            "morale_average": 0.0,
            "role_alignment": 0.0,
            "happy_players": 0,
            "frustrated_players": 0,
            "trade_pressure_players": 0,
            "active_requests": 0,
            "broken_promises": 0,
            "kept_promises": 0,
        }
    scores = [_num(row.get("score"), 70.0) for row in rows]
    alignments = [_num(row.get("role_satisfaction"), 70.0) for row in rows]
    morale_average = sum(scores) / len(scores)
    role_alignment = sum(alignments) / len(alignments)
    frustrated = sum(score < 49 for score in scores)
    happy = sum(score >= 76 for score in scores)
    pressured = sum(_clean(row.get("trade_request_status")) not in {"", "None", "Withdrawn request"} for row in rows)
    requests = sum(bool(row.get("trade_request_active")) for row in rows)
    broken_promises = sum(_int(row.get("broken_promise_games"), 0) > 0 for row in rows)
    kept_promises = sum(_int(row.get("kept_promise_games"), 0) > 0 for row in rows)
    chemistry = morale_average * 0.66 + role_alignment * 0.24 + 70.0 * 0.10
    chemistry -= frustrated * 1.1
    chemistry -= pressured * 0.55
    chemistry -= requests * 2.25
    chemistry -= broken_promises * 0.80
    chemistry += min(3.0, happy * 0.25)
    chemistry += min(1.5, kept_promises * 0.25)
    return {
        "chemistry": round(_clamp(chemistry, 8.0, 97.0), 1),
        "morale_average": round(morale_average, 1),
        "role_alignment": round(role_alignment, 1),
        "happy_players": happy,
        "frustrated_players": frustrated,
        "trade_pressure_players": pressured,
        "active_requests": requests,
        "broken_promises": broken_promises,
        "kept_promises": kept_promises,
    }


def _record_event(payload: dict[str, Any], event: dict[str, Any]) -> None:
    history = list(payload.get("event_history", []) or [])
    history.append(event)
    payload["event_history"] = history[-500:]


def _game_personal_adjustment(context: dict[str, Any]) -> float:
    """Small player-specific game adjustment layered on the shared team signal.

    The target model already contains team success and role context. This
    adjustment prevents a team-wide win/loss swing from making every player's
    displayed trend identical when their usage and role fulfillment were very
    different in the same game.
    """
    expected = _num(context.get("expected_minutes"), 0.0)
    recent = context.get("recent_minutes")
    actual = _num(recent, context.get("actual_minutes", 0.0)) if recent is not None else _num(context.get("actual_minutes"), 0.0)
    minute_gap = actual - expected
    adjustment = _clamp(minute_gap * 0.055, -0.65, 0.45)

    if bool(context.get("promise_active")) and minute_gap <= -4.0:
        adjustment -= 0.18
    if _int(context.get("rotation_order"), 99) <= 5 and not bool(context.get("starter")):
        adjustment -= 0.12
    if minute_gap >= 4.0 and bool(context.get("starter")):
        adjustment += 0.08

    return round(_clamp(adjustment, -0.85, 0.60), 3)


def rotation_emphasis_v1(state: Any, team: str) -> str:
    payload = ensure_morale_state_v1(state)
    stored = _clean((payload.get("rotation_emphasis") or {}).get(_team(team)))
    return stored if stored in {"Balanced", "Win Now", "Development"} else "Balanced"


def set_rotation_emphasis_v1(state: Any, team: str, philosophy: str) -> str:
    resolved = _clean(philosophy)
    if resolved not in {"Balanced", "Win Now", "Development"}:
        raise ValueError(f"Unsupported rotation emphasis: {resolved}")
    payload = ensure_morale_state_v1(state)
    payload.setdefault("rotation_emphasis", {})[_team(team)] = resolved
    return resolved



def _decrement_game_counters(existing: dict[str, Any]) -> None:
    for name in (
        "meeting_cooldown_games",
        "meeting_support_games",
        "patience_games",
        "broken_promise_games",
        "kept_promise_games",
        "offseason_grievance_games",
    ):
        existing[name] = max(0, _int(existing.get(name), 0) - 1)


def _evaluate_role_promise_after_game(
    state: Any,
    team: str,
    player_id: str,
    game_id: str,
    existing: dict[str, Any],
) -> None:
    promise = _role_promise(state, team, player_id)
    if not promise or _clean(promise.get("status")) in {"kept", "broken", "expired"}:
        return
    if game_id and _clean(promise.get("last_evaluated_game_id")) == game_id:
        return
    recent = [row for row in list(existing.get("recent_games", []) or []) if isinstance(row, dict)]
    latest = next((row for row in reversed(recent) if not game_id or _clean(row.get("game_id")) == game_id), None)
    if latest is None:
        return

    promised_minutes = _num(promise.get("minutes"), 0.0)
    role = _clean(promise.get("role")).lower()
    actual_minutes = _num(latest.get("minutes"), 0.0)
    started = bool(latest.get("started"))
    met = actual_minutes >= max(0.0, promised_minutes - 3.0)
    if "starter" in role:
        met = met and started

    promise["games_since_set"] = _int(promise.get("games_since_set"), 0) + 1
    promise["met_games"] = _int(promise.get("met_games"), 0) + (1 if met else 0)
    promise["missed_games"] = _int(promise.get("missed_games"), 0) + (0 if met else 1)
    promise["last_evaluated_game_id"] = game_id
    review_after = max(3, min(10, _int(promise.get("review_after_games"), PROMISE_REVIEW_DEFAULT_GAMES)))
    promise["review_after_games"] = review_after

    if promise["games_since_set"] < review_after:
        return
    threshold = max(2, math.ceil(review_after * 0.60))
    kept = _int(promise.get("met_games"), 0) >= threshold
    promise["status"] = "kept" if kept else "broken"
    if kept:
        existing["kept_promise_games"] = max(_int(existing.get("kept_promise_games"), 0), 4)
    else:
        existing["broken_promise_games"] = max(_int(existing.get("broken_promise_games"), 0), 6)
    payload = ensure_morale_state_v1(state)
    _record_event(
        payload,
        {
            "type": "role-promise-review",
            "team": team,
            "player_id": player_id,
            "season": _season(state),
            "day": _day(state),
            "game_id": game_id,
            "verdict": promise["status"],
            "review_after_games": review_after,
            "met_games": _int(promise.get("met_games"), 0),
            "missed_games": _int(promise.get("missed_games"), 0),
        },
    )


def _trade_availability(state: Any, team: str, player_id: str, request_active: bool) -> str:
    response = _trade_response(state, team, player_id)
    if request_active:
        if response == "On trade block":
            return "Requested · trade block"
        if response == "Listening to offers":
            return "Requested · listening"
        return "Trade requested"
    return response

def refresh_team_morale_v1(
    state: Any,
    team: str,
    *,
    blend: float = 0.18,
    reason: str = "refresh",
) -> dict[str, Any]:
    resolved = _team(team)
    payload = ensure_morale_state_v1(state)
    player_state = payload["players"]
    team_state = (getattr(state, "teams", {}) or {}).get(resolved)
    if team_state is None:
        return {"team": resolved, "chemistry": 0.0, "players": []}

    rows: list[dict[str, Any]] = []
    for raw_player_id in tuple(getattr(team_state, "roster_player_ids", ()) or ()):
        player_id = str(raw_player_id)
        player = (getattr(state, "players", {}) or {}).get(player_id)
        if player is None:
            continue
        existing = player_state.get(player_id)
        existing = existing if isinstance(existing, dict) else {}
        player_state[player_id] = existing
        resolved_blend = _clamp(blend, 0.0, 1.0)
        is_game_update = reason.startswith("game:") or reason == "game"
        game_id = reason.split(":", 1)[1] if reason.startswith("game:") else ""
        if is_game_update:
            _decrement_game_counters(existing)
            _evaluate_role_promise_after_game(state, resolved, player_id, game_id, existing)
        context = _morale_target(state, resolved, player_id)
        previous = _num(existing.get("score"), context["target"])
        personal_adjustment = _game_personal_adjustment(context) if is_game_update else 0.0
        score = (
            previous
            + (context["target"] - previous) * resolved_blend
            + personal_adjustment
        )
        score = round(_clamp(score, 5.0, 98.0), 2)
        score_delta = round(score - previous, 2)

        base_risk = (52.0 - score) * 1.85
        minutes_risk = max(0.0, context["expected_minutes"] - context["actual_minutes"]) * 1.55
        promise_risk = 8.0 if context["promise_active"] and context["minute_gap"] <= -4 else 0.0
        broken_risk = 12.0 if context.get("broken_promise_games", 0) > 0 else 0.0
        carryover_risk = 6.0 if context.get("offseason_grievance_games", 0) > 0 else 0.0
        patience_relief = 7.0 if context.get("patience_games", 0) > 0 else 0.0
        trade_risk = _clamp(
            base_risk + minutes_risk + promise_risk + broken_risk + carryover_risk - patience_relief,
            0.0,
            97.0,
        )

        low_morale_games = _int(existing.get("low_morale_games"), 0)
        high_risk_games = _int(existing.get("high_risk_games"), 0)
        recovery_games = _int(existing.get("recovery_games"), 0)
        if is_game_update:
            low_morale_games = low_morale_games + 1 if score < 49 else max(0, low_morale_games - 1)
            high_risk_games = high_risk_games + 1 if trade_risk >= 60 else max(0, high_risk_games - 1)
            recovery_games = recovery_games + 1 if score >= 64 and score_delta >= -0.25 else 0

        previous_request = _clean(existing.get("trade_request_status")) or "None"
        request_status, request_active = _trade_request_stage(
            score,
            trade_risk,
            low_morale_games,
            high_risk_games,
            previous_request,
            recovery_games,
        )
        if request_status != previous_request:
            payload["trade_request_history"].append(
                {
                    "player_id": player_id,
                    "player_name": _clean(getattr(player, "player_name", "")),
                    "team": resolved,
                    "season": _season(state),
                    "day": _day(state),
                    "from": previous_request,
                    "to": request_status,
                    "risk": round(trade_risk, 1),
                    "morale": score,
                }
            )
            payload["trade_request_history"] = payload["trade_request_history"][-250:]

        record = {
            **existing,
            "player_id": player_id,
            "player_name": _clean(getattr(player, "player_name", "")),
            "team": resolved,
            "season": _season(state),
            "score": score,
            "previous_score": round(previous, 2),
            "score_delta": score_delta,
            "personal_game_adjustment": round(personal_adjustment, 3),
            "status": _status(score),
            "target_score": context["target"],
            "role_satisfaction": context["role_satisfaction"],
            "expected_role": context["expected_role"],
            "automatic_role": context["automatic_role"],
            "promise_active": context["promise_active"],
            "expected_minutes": context["expected_minutes"],
            "actual_minutes": context["actual_minutes"],
            "recent_minutes": context["recent_minutes"],
            "starter": context["starter"],
            "rotation_order": context["rotation_order"],
            "trade_request_risk": round(trade_risk, 1),
            "trade_request_status": request_status,
            "trade_request_active": request_active,
            "trade_availability": _trade_availability(state, resolved, player_id, request_active),
            "trade_response": _trade_response(state, resolved, player_id),
            "broken_promise_games": _int(existing.get("broken_promise_games"), 0),
            "kept_promise_games": _int(existing.get("kept_promise_games"), 0),
            "meeting_cooldown_games": _int(existing.get("meeting_cooldown_games"), 0),
            "meeting_support_games": _int(existing.get("meeting_support_games"), 0),
            "patience_games": _int(existing.get("patience_games"), 0),
            "offseason_grievance_games": _int(existing.get("offseason_grievance_games"), 0),
            "low_morale_games": low_morale_games,
            "high_risk_games": high_risk_games,
            "recovery_games": recovery_games,
            "reasons": list(context["reasons"]),
            "last_reason": reason,
            "last_day": _day(state),
        }
        player_state[player_id] = record
        rows.append(record)

    summary = _chemistry_summary(rows)
    previous_team = payload["teams"].get(resolved)
    previous_chemistry = _num(previous_team.get("chemistry"), summary["chemistry"]) if isinstance(previous_team, dict) else summary["chemistry"]
    team_record = {
        "team": resolved,
        "season": _season(state),
        **summary,
        "chemistry_delta": round(summary["chemistry"] - previous_chemistry, 1),
        "player_count": len(rows),
        "last_day": _day(state),
        "last_reason": reason,
    }
    payload["teams"][resolved] = team_record
    return {**team_record, "players": rows}


def _append_game_context(state: Any, game: Any, team: str) -> None:
    payload = ensure_morale_state_v1(state)
    player_state = payload["players"]
    home = _team(getattr(game, "home_team", ""))
    away = _team(getattr(game, "away_team", ""))
    home_score = _int(getattr(game, "home_score", 0), 0)
    away_score = _int(getattr(game, "away_score", 0), 0)
    won = (team == home and home_score > away_score) or (team == away and away_score > home_score)
    game_id = _clean(getattr(game, "game_id", ""))

    # Completed-game box scores may omit players who logged a true DNP.
    # Morale still needs that zero-minute game in recent usage history;
    # otherwise a player frozen out of the rotation looks as though no game
    # occurred at all. Build a team box-score lookup, then walk the live roster
    # so missing rows become explicit 0.0-minute DNP observations.
    boxes_by_player: dict[str, Any] = {}
    for box in tuple(getattr(game, "player_box_scores", ()) or ()):
        if _team(getattr(box, "team_abbreviation", "")) != team:
            continue
        pid = _clean(getattr(box, "player_id", ""))
        if pid:
            boxes_by_player[pid] = box

    team_state = (getattr(state, "teams", {}) or {}).get(team)
    roster_ids = [
        _clean(value)
        for value in tuple(getattr(team_state, "roster_player_ids", ()) or ())
        if _clean(value)
    ] if team_state is not None else list(boxes_by_player)

    # Preserve any box-score-only player as a defensive fallback while making
    # the authoritative live roster the normal source of DNP observations.
    ordered_ids = list(dict.fromkeys(roster_ids + list(boxes_by_player)))
    for pid in ordered_ids:
        box = boxes_by_player.get(pid)
        existing = player_state.get(pid)
        if not isinstance(existing, dict):
            existing = {}
            player_state[pid] = existing
        recent = [row for row in list(existing.get("recent_games", []) or []) if isinstance(row, dict)]
        if game_id and any(_clean(row.get("game_id")) == game_id for row in recent):
            continue
        recent.append(
            {
                "game_id": game_id,
                "day": _day(state),
                "minutes": round(_num(getattr(box, "minutes", 0.0), 0.0), 1) if box is not None else 0.0,
                "started": bool(getattr(box, "started", False)) if box is not None else False,
                "won": bool(won),
                "dnp": box is None,
            }
        )
        existing["recent_games"] = recent[-MAX_RECENT_GAMES:]

def update_morale_after_game_v1(state: Any, game: Any) -> None:
    payload = ensure_morale_state_v1(state)
    game_id = _clean(getattr(game, "game_id", ""))
    processed = list(payload.get("processed_game_ids", []) or [])
    if game_id and game_id in processed:
        return

    teams = (
        _team(getattr(game, "home_team", "")),
        _team(getattr(game, "away_team", "")),
    )
    for team in teams:
        if not team:
            continue
        _append_game_context(state, game, team)
        refresh_team_morale_v1(
            state,
            team,
            blend=0.20,
            reason=f"game:{game_id}" if game_id else "game",
        )

    if game_id:
        processed.append(game_id)
        payload["processed_game_ids"] = processed[-400:]


def set_player_role_expectation_v1(
    state: Any,
    team: str,
    player_id: str,
    *,
    role: str,
    minutes: float,
    review_games: int = PROMISE_REVIEW_DEFAULT_GAMES,
) -> dict[str, Any]:
    resolved = _team(team)
    pid = _clean(player_id)
    if not pid:
        raise ValueError("A player id is required for a role expectation.")
    team_state = (getattr(state, "teams", {}) or {}).get(resolved)
    if team_state is None or pid not in {str(value) for value in tuple(getattr(team_state, "roster_player_ids", ()) or ())}:
        raise ValueError("Role expectations can only be set for a rostered player.")
    role_name = _clean(role)
    if role_name == "Auto":
        return clear_player_role_expectation_v1(state, resolved, pid)
    if role_name not in ROLE_PRESETS:
        raise ValueError(f"Unsupported role expectation: {role_name}")
    promised_minutes = round(_clamp(minutes, 0.0, 40.0), 1)
    payload = ensure_morale_state_v1(state)
    record = {
        "team": resolved,
        "player_id": pid,
        "role": role_name,
        "minutes": promised_minutes,
        "season": _season(state),
        "set_day": _day(state),
        "review_after_games": max(3, min(10, _int(review_games, PROMISE_REVIEW_DEFAULT_GAMES))),
        "games_since_set": 0,
        "met_games": 0,
        "missed_games": 0,
        "status": "active",
        "last_evaluated_game_id": "",
    }
    payload["role_promises"][pid] = record
    _record_event(payload, {"type": "role-promise", **record})
    refresh_team_morale_v1(state, resolved, blend=0.50, reason="role-promise-change")
    return record


def clear_player_role_expectation_v1(state: Any, team: str, player_id: str) -> dict[str, Any]:
    resolved = _team(team)
    pid = _clean(player_id)
    payload = ensure_morale_state_v1(state)
    previous = (payload.get("role_promises") or {}).pop(pid, None)
    _record_event(
        payload,
        {
            "type": "role-promise-cleared",
            "team": resolved,
            "player_id": pid,
            "season": _season(state),
            "day": _day(state),
        },
    )
    refresh_team_morale_v1(state, resolved, blend=0.40, reason="role-promise-cleared")
    return previous if isinstance(previous, dict) else {}


def role_expectation_v1(state: Any, team: str, player_id: str) -> dict[str, Any]:
    resolved = _team(team)
    pid = _clean(player_id)
    expected = _expected_role(state, resolved, pid)
    return {
        "player_id": pid,
        "team": resolved,
        "role": expected["expected_role"],
        "minutes": expected["expected_minutes"],
        "promise_active": bool(expected.get("promise_active")),
        "automatic_role": expected.get("automatic_role", expected["expected_role"]),
        "automatic_minutes": expected.get("automatic_minutes", expected["expected_minutes"]),
        "promise_status": _clean((_role_promise(state, resolved, pid) or {}).get("status")) or "none",
        "review_after_games": _int((_role_promise(state, resolved, pid) or {}).get("review_after_games"), PROMISE_REVIEW_DEFAULT_GAMES),
        "games_since_set": _int((_role_promise(state, resolved, pid) or {}).get("games_since_set"), 0),
        "met_games": _int((_role_promise(state, resolved, pid) or {}).get("met_games"), 0),
        "missed_games": _int((_role_promise(state, resolved, pid) or {}).get("missed_games"), 0),
    }


def hold_player_meeting_v1(
    state: Any,
    team: str,
    player_id: str,
    *,
    action: str,
) -> dict[str, Any]:
    resolved = _team(team)
    pid = _clean(player_id)
    if action not in MEETING_ACTIONS:
        raise ValueError(f"Unsupported player meeting action: {action}")
    payload = ensure_morale_state_v1(state)
    team_state = (getattr(state, "teams", {}) or {}).get(resolved)
    if team_state is None or pid not in {str(value) for value in tuple(getattr(team_state, "roster_player_ids", ()) or ())}:
        raise ValueError("Player meetings can only be held with a rostered player.")
    existing = payload["players"].get(pid)
    existing = existing if isinstance(existing, dict) else {}
    payload["players"][pid] = existing
    cooldown = _int(existing.get("meeting_cooldown_games"), 0)
    if cooldown > 0:
        raise ValueError(f"Another meeting can be held after {cooldown} more game(s).")

    before = _num(existing.get("score"), 70.0)
    if action == "Reassure and listen":
        existing["score"] = round(_clamp(before + 1.5, 5.0, 98.0), 2)
        existing["meeting_support_games"] = 3
        existing["meeting_cooldown_games"] = 3
    elif action == "Ask for patience":
        existing["score"] = round(_clamp(before + 0.5, 5.0, 98.0), 2)
        existing["patience_games"] = 3
        existing["meeting_cooldown_games"] = 3
    else:
        clear_player_role_expectation_v1(state, resolved, pid)
        existing = payload["players"].get(pid) if isinstance(payload["players"].get(pid), dict) else existing
        existing["score"] = round(_clamp(_num(existing.get("score"), before) - 0.75, 5.0, 98.0), 2)
        existing["meeting_cooldown_games"] = 2

    meeting = {
        "team": resolved,
        "player_id": pid,
        "action": action,
        "season": _season(state),
        "day": _day(state),
        "score_before": round(before, 2),
        "score_after": round(_num(existing.get("score"), before), 2),
    }
    payload.setdefault("meetings", {}).setdefault(pid, []).append(meeting)
    payload["meetings"][pid] = payload["meetings"][pid][-30:]
    _record_event(payload, {"type": "player-meeting", **meeting})
    refresh_team_morale_v1(state, resolved, blend=0.0, reason="player-meeting")
    return meeting


def set_player_trade_response_v1(
    state: Any,
    team: str,
    player_id: str,
    *,
    response: str,
) -> dict[str, Any]:
    resolved = _team(team)
    pid = _clean(player_id)
    value = _clean(response)
    if value not in TRADE_RESPONSE_OPTIONS:
        raise ValueError(f"Unsupported trade response: {value}")
    team_state = (getattr(state, "teams", {}) or {}).get(resolved)
    if team_state is None or pid not in {str(v) for v in tuple(getattr(team_state, "roster_player_ids", ()) or ())}:
        raise ValueError("Trade responses can only be set for a rostered player.")
    payload = ensure_morale_state_v1(state)
    record = {
        "team": resolved,
        "player_id": pid,
        "response": value,
        "season": _season(state),
        "day": _day(state),
    }
    payload.setdefault("trade_responses", {})[pid] = record
    _record_event(payload, {"type": "trade-response", **record})
    return record


def trade_response_v1(state: Any, team: str, player_id: str) -> str:
    return _trade_response(state, _team(team), _clean(player_id))


def morale_snapshot_v1(state: Any, team: str) -> dict[str, Any]:
    # Viewing a page must never mutate morale. Context is recalculated so the
    # UI reflects current rotations and stats, while persistent score changes
    # only occur after games or explicit front-office role actions.
    resolved = _team(team)
    payload = ensure_morale_state_v1(state)
    team_state = (getattr(state, "teams", {}) or {}).get(resolved)
    if team_state is None:
        return {"team": resolved, "chemistry": 0.0, "players": []}

    rows: list[dict[str, Any]] = []
    for raw_player_id in tuple(getattr(team_state, "roster_player_ids", ()) or ()):
        player_id = str(raw_player_id)
        player = (getattr(state, "players", {}) or {}).get(player_id)
        if player is None:
            continue
        context = _morale_target(state, resolved, player_id)
        existing = payload["players"].get(player_id)
        existing = existing if isinstance(existing, dict) else {}
        score = _num(existing.get("score"), context["target"])
        previous_score = _num(existing.get("previous_score"), score)
        base_risk = (52.0 - score) * 1.85
        minutes_risk = max(0.0, context["expected_minutes"] - context["actual_minutes"]) * 1.55
        promise_risk = 8.0 if context["promise_active"] and context["minute_gap"] <= -4 else 0.0
        broken_risk = 12.0 if context.get("broken_promise_games", 0) > 0 else 0.0
        carryover_risk = 6.0 if context.get("offseason_grievance_games", 0) > 0 else 0.0
        patience_relief = 7.0 if context.get("patience_games", 0) > 0 else 0.0
        risk = _clamp(base_risk + minutes_risk + promise_risk + broken_risk + carryover_risk - patience_relief, 0.0, 97.0)
        request_status = _clean(existing.get("trade_request_status")) or "None"
        request_active = bool(existing.get("trade_request_active"))
        row = {
            "player_id": player_id,
            "player_name": _clean(getattr(player, "player_name", "")),
            "team": resolved,
            "score": round(score, 1),
            "score_delta": round(score - previous_score, 1),
            "status": _status(score),
            "role_satisfaction": context["role_satisfaction"],
            "expected_role": context["expected_role"],
            "automatic_role": context["automatic_role"],
            "promise_active": context["promise_active"],
            "expected_minutes": context["expected_minutes"],
            "actual_minutes": context["actual_minutes"],
            "recent_minutes": context["recent_minutes"],
            "minute_gap": context["minute_gap"],
            "starter": context["starter"],
            "trade_request_risk": round(risk, 1),
            "trade_request_status": request_status,
            "trade_request_active": request_active,
            "trade_response": _trade_response(state, resolved, player_id),
            "trade_availability": _trade_availability(state, resolved, player_id, request_active),
            "broken_promise_games": _int(existing.get("broken_promise_games"), 0),
            "kept_promise_games": _int(existing.get("kept_promise_games"), 0),
            "meeting_cooldown_games": _int(existing.get("meeting_cooldown_games"), 0),
            "offseason_grievance_games": _int(existing.get("offseason_grievance_games"), 0),
            "promise_status": _clean((_role_promise(state, resolved, player_id) or {}).get("status")) or "none",
            "low_morale_games": _int(existing.get("low_morale_games"), 0),
            "reasons": list(context["reasons"]),
        }
        rows.append(row)

    summary = _chemistry_summary(rows)
    stored_team = payload["teams"].get(resolved)
    chemistry_delta = _num(stored_team.get("chemistry_delta"), 0.0) if isinstance(stored_team, dict) else 0.0
    rows.sort(
        key=lambda row: (
            not row["trade_request_active"],
            row["score"],
            -row["trade_request_risk"],
            row["player_name"],
        )
    )
    return {
        "team": resolved,
        "season": _season(state),
        **summary,
        "chemistry_delta": round(chemistry_delta, 1),
        "players": rows,
        "version": FRANCHISE_MORALE_CHEMISTRY_VERSION,
    }


def morale_action_queue_v1(state: Any, team: str) -> list[dict[str, Any]]:
    snapshot = morale_snapshot_v1(state, team)
    actions: list[dict[str, Any]] = []
    for row in snapshot.get("players", []):
        if row.get("trade_request_active"):
            priority = 100
            action = (
                "Evaluate trade offers"
                if row.get("trade_response") in {"Listening to offers", "On trade block"}
                else "Respond to active trade request"
            )
        elif row.get("broken_promise_games", 0) > 0:
            priority = 90
            action = "Repair a broken front-office promise"
        elif row.get("trade_request_status") == "Considering request":
            priority = 82
            action = "Hold a player meeting"
        elif row.get("score", 70) < 49:
            priority = 70
            action = "Review minutes and role"
        elif row.get("promise_active") and row.get("minute_gap", 0) <= -4:
            priority = 65
            action = "Honor or reset role promise"
        else:
            continue
        actions.append(
            {
                "player_id": row["player_id"],
                "player_name": row["player_name"],
                "priority": priority,
                "action": action,
                "status": row["status"],
                "trade_request_status": row["trade_request_status"],
                "reason": row["reasons"][0] if row["reasons"] else "Role pressure",
            }
        )
    return sorted(actions, key=lambda row: (-row["priority"], row["player_name"]))


__all__ = [
    "FRANCHISE_MORALE_CHEMISTRY_VERSION",
    "MORALE_STATE_ATTR",
    "ROLE_PRESETS",
    "PROMISE_REVIEW_DEFAULT_GAMES",
    "MEETING_ACTIONS",
    "TRADE_RESPONSE_OPTIONS",
    "ensure_morale_state_v1",
    "refresh_team_morale_v1",
    "rotation_emphasis_v1",
    "set_rotation_emphasis_v1",
    "update_morale_after_game_v1",
    "morale_snapshot_v1",
    "morale_action_queue_v1",
    "set_player_role_expectation_v1",
    "clear_player_role_expectation_v1",
    "role_expectation_v1",
    "hold_player_meeting_v1",
    "set_player_trade_response_v1",
    "trade_response_v1",
]
