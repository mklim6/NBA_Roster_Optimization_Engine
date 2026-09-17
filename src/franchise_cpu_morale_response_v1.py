from __future__ import annotations

import math
from typing import Any

from franchise_morale_chemistry_v1 import (
    ensure_morale_state_v1,
    hold_player_meeting_v1,
    morale_snapshot_v1,
    refresh_team_morale_v1,
    set_player_trade_response_v1,
    trade_response_v1,
)

CPU_MORALE_RESPONSE_VERSION = "franchise-cpu-morale-response-v1-2026-09-16"
MAX_AUDIT_ROWS = 500


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


def _season(state: Any) -> str:
    return _clean(getattr(getattr(state, "settings", None), "season_label", ""))


def _day(state: Any) -> int:
    return _int(getattr(state, "current_day_index", 0), 0)


def _latest_team_game_marker(state: Any, team: str) -> str:
    payload = ensure_morale_state_v1(state)
    team_state = (getattr(state, "teams", {}) or {}).get(team)
    if team_state is None:
        return ""
    best: tuple[int, int, str] | None = None
    for raw_pid in tuple(getattr(team_state, "roster_player_ids", ()) or ()):
        record = (payload.get("players") or {}).get(str(raw_pid))
        if not isinstance(record, dict):
            continue
        for index, game in enumerate(list(record.get("recent_games", []) or [])):
            if not isinstance(game, dict):
                continue
            marker = _clean(game.get("game_id")) or f'day-{_int(game.get("day"), 0)}'
            candidate = (_int(game.get("day"), 0), index, marker)
            if best is None or candidate > best:
                best = candidate
    return best[2] if best is not None else ""


def _player_fields(state: Any, player_id: str) -> dict[str, Any]:
    player = (getattr(state, "players", {}) or {}).get(player_id)
    contract = getattr(player, "contract", None) if player is not None else None
    return {
        "overall": _num(getattr(player, "overall_rating", 0.0) if player is not None else 0.0),
        "potential": _num(getattr(player, "potential_rating", 0.0) if player is not None else 0.0),
        "age": _num(getattr(player, "age", 27.0) if player is not None else 27.0, 27.0),
        "years": _int(getattr(contract, "years_remaining", 99) if contract is not None else 99, 99),
    }


def _team_context(state: Any, team: str) -> dict[str, Any]:
    standing = (getattr(state, "standings", {}) or {}).get(team)
    wins = _int(getattr(standing, "wins", 0), 0) if standing is not None else 0
    losses = _int(getattr(standing, "losses", 0), 0) if standing is not None else 0
    games = wins + losses
    win_pct = wins / games if games else 0.5
    return {
        "wins": wins,
        "losses": losses,
        "games": games,
        "win_pct": win_pct,
        "contender": games >= 10 and win_pct >= 0.55,
        "struggling": games >= 10 and win_pct < 0.43,
    }


def _is_core_player(state: Any, player_id: str) -> bool:
    fields = _player_fields(state, player_id)
    return bool(
        fields["overall"] >= 86.0
        or (fields["age"] <= 24.0 and fields["potential"] >= 89.0)
    )


def _rotation_total(rotation: Any) -> float:
    return round(sum(_num(v) for v in dict(getattr(rotation, "minutes_targets", {}) or {}).values()), 1)


def _repair_rotation_minutes(
    state: Any,
    team: str,
    target: dict[str, Any],
    rows_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    team_state = (getattr(state, "teams", {}) or {}).get(team)
    rotation = getattr(team_state, "rotation", None) if team_state is not None else None
    if rotation is None:
        return {"changed": False, "type": "none", "detail": "No rotation state"}

    pid = _clean(target.get("player_id"))
    if not pid:
        return {"changed": False, "type": "none", "detail": "No player id"}
    active_ids = set(str(v) for v in tuple(getattr(team_state, "active_player_ids", ()) or ()))
    if not active_ids:
        active_ids = set(str(v) for v in tuple(getattr(team_state, "roster_player_ids", ()) or ()))
    if pid not in active_ids:
        return {"changed": False, "type": "none", "detail": "Player unavailable"}

    rotation_ids = [str(v) for v in tuple(getattr(rotation, "rotation_player_ids", ()) or ())]
    starter_ids = tuple(str(v) for v in tuple(getattr(rotation, "starter_ids", ()) or ()))
    minutes = {str(k): _num(v) for k, v in dict(getattr(rotation, "minutes_targets", {}) or {}).items()}
    before_total = round(sum(minutes.values()), 1)

    if pid in rotation_ids:
        current = _num(minutes.get(pid), 0.0)
        desired_gap = max(0.0, _num(target.get("expected_minutes")) - current)
        if desired_gap < 1.0:
            return {"changed": False, "type": "none", "detail": "Current plan already near expectation"}
        transfer_goal = min(4.0, max(1.5, desired_gap * 0.45))
        donors = []
        for donor_id in rotation_ids:
            if donor_id == pid:
                continue
            row = rows_by_id.get(donor_id, {})
            donor_minutes = _num(minutes.get(donor_id), 0.0)
            expected = _num(row.get("expected_minutes"), 8.0)
            floor = max(8.0, expected - 2.0)
            surplus = max(0.0, donor_minutes - floor)
            if surplus <= 0.0:
                continue
            fields = _player_fields(state, donor_id)
            donors.append((donor_id in starter_ids, -surplus, fields["overall"], donor_id, surplus))
        donors.sort()
        remaining = transfer_goal
        moved = 0.0
        for _starter, _neg_surplus, _ovr, donor_id, surplus in donors:
            take = min(remaining, surplus)
            if take <= 0:
                continue
            minutes[donor_id] = round(minutes[donor_id] - take, 1)
            minutes[pid] = round(_num(minutes.get(pid), current) + take, 1)
            moved += take
            remaining -= take
            if remaining <= 0.05:
                break
        if moved < 0.9:
            return {"changed": False, "type": "none", "detail": "No safe donor minutes"}
        # Correct any one-decimal drift on the target so the team remains at 240.
        drift = round(before_total - sum(minutes.values()), 1)
        minutes[pid] = round(minutes[pid] + drift, 1)
        rotation.minutes_targets = minutes
        return {
            "changed": True,
            "type": "minutes_repair",
            "detail": f"Raised planned minutes from {current:.1f} to {minutes[pid]:.1f}",
        }

    expected = _num(target.get("expected_minutes"), 0.0)
    fields = _player_fields(state, pid)
    if expected < 12.0 or fields["overall"] < 67.0:
        return {"changed": False, "type": "none", "detail": "No safe rotation promotion"}

    candidates = []
    for donor_id in rotation_ids:
        if donor_id in starter_ids or donor_id not in active_ids:
            continue
        donor_fields = _player_fields(state, donor_id)
        donor_row = rows_by_id.get(donor_id, {})
        donor_minutes = _num(minutes.get(donor_id), 0.0)
        protection = donor_fields["overall"] + max(0.0, donor_fields["potential"] - donor_fields["overall"]) * 0.15
        candidates.append((protection, _num(donor_row.get("score"), 70.0), donor_minutes, donor_id))
    if not candidates:
        return {"changed": False, "type": "none", "detail": "No bench rotation candidate"}
    candidates.sort()
    _protection, _morale, donor_minutes, donor_id = candidates[0]
    donor_fields = _player_fields(state, donor_id)
    target_value = fields["overall"] + max(0.0, fields["potential"] - fields["overall"]) * 0.15
    donor_value = donor_fields["overall"] + max(0.0, donor_fields["potential"] - donor_fields["overall"]) * 0.15
    youth_exception = fields["age"] <= 23.0 and fields["potential"] >= 84.0
    if target_value < donor_value - 3.0 and not youth_exception:
        return {"changed": False, "type": "none", "detail": "Promotion would be too costly competitively"}

    index = rotation_ids.index(donor_id)
    rotation_ids[index] = pid
    minutes.pop(donor_id, None)
    minutes[pid] = round(donor_minutes, 1)
    rotation.rotation_player_ids = tuple(rotation_ids)
    rotation.minutes_targets = minutes
    return {
        "changed": True,
        "type": "rotation_repair",
        "detail": f"Promoted into rotation for {donor_minutes:.1f} MPG slot",
        "replaced_player_id": donor_id,
    }


def _desired_trade_response(state: Any, team: str, row: dict[str, Any]) -> str:
    fields = _player_fields(state, row["player_id"])
    context = _team_context(state, team)
    core = _is_core_player(state, row["player_id"])
    active = bool(row.get("trade_request_active"))
    stage = _clean(row.get("trade_request_status"))
    risk = _num(row.get("trade_request_risk"), 0.0)
    low_games = _int(row.get("low_morale_games"), 0)
    expiring = fields["years"] <= 1

    if active:
        if core:
            return "Listening to offers"
        if risk >= 82 and low_games >= 5:
            return "On trade block"
        return "Listening to offers"
    if stage == "Considering request":
        if not core and (context["struggling"] or expiring) and risk >= 64:
            return "Listening to offers"
        return "Keep internal"
    if stage == "Pressure building" and not core and context["struggling"] and expiring and risk >= 58:
        return "Listening to offers"
    return "Keep internal"


def cpu_trade_willingness_modifier_v1(state: Any, team: str, player_id: str) -> float:
    """Planning-only multiplier for downstream CPU trade valuation/search.

    This function does not execute, legalize, or approve any transaction.
    """
    snapshot = morale_snapshot_v1(state, team)
    row = next((r for r in snapshot.get("players", []) if r.get("player_id") == str(player_id)), None)
    if row is None:
        return 1.0
    response = trade_response_v1(state, team, str(player_id))
    modifier = {"Keep internal": 0.92, "Listening to offers": 1.10, "On trade block": 1.22}.get(response, 1.0)
    if row.get("trade_request_active"):
        modifier += 0.08
    if _is_core_player(state, str(player_id)):
        modifier -= 0.08
    return round(max(0.78, min(1.35, modifier)), 3)


def run_cpu_morale_reactions_v1(
    state: Any,
    *,
    controlled_teams: tuple[str, ...] | list[str] | set[str] = (),
) -> dict[str, Any]:
    payload = ensure_morale_state_v1(state)
    controlled = {_team(team) for team in controlled_teams}
    processed = payload.setdefault("cpu_morale_processed_games", {})
    audit = payload.setdefault("cpu_morale_reactions", [])
    if not isinstance(processed, dict):
        processed = {}
        payload["cpu_morale_processed_games"] = processed
    if not isinstance(audit, list):
        audit = []
        payload["cpu_morale_reactions"] = audit

    actions: list[dict[str, Any]] = []
    changed = False
    teams_processed = 0
    for raw_team in sorted((getattr(state, "teams", {}) or {})):
        team = _team(raw_team)
        if not team or team in controlled:
            continue
        marker = _latest_team_game_marker(state, team)
        if not marker or _clean(processed.get(team)) == marker:
            continue

        snapshot = morale_snapshot_v1(state, team)
        rows = list(snapshot.get("players", []) or [])
        rows_by_id = {str(row.get("player_id")): row for row in rows}
        concerns = [
            row for row in rows
            if row.get("trade_request_active")
            or _clean(row.get("trade_request_status")) in {"Considering request", "Pressure building"}
            or _num(row.get("score"), 70.0) < 55.0
            or _num(row.get("minute_gap"), 0.0) <= -5.0
            or _int(row.get("broken_promise_games"), 0) > 0
        ]
        concerns.sort(
            key=lambda row: (
                not bool(row.get("trade_request_active")),
                -_num(row.get("trade_request_risk"), 0.0),
                _num(row.get("score"), 70.0),
                _clean(row.get("player_name")),
            )
        )

        for row in concerns[:2]:
            pid = str(row.get("player_id"))
            rotation_result = {"changed": False, "type": "none", "detail": "No rotation change"}
            if _num(row.get("minute_gap"), 0.0) <= -4.0 and _num(row.get("score"), 70.0) < 57.0:
                rotation_result = _repair_rotation_minutes(state, team, row, rows_by_id)
                if rotation_result.get("changed"):
                    changed = True
                    refresh_team_morale_v1(state, team, blend=0.0, reason="cpu-role-repair")
                    # Re-read visible context after changing the rotation.
                    refreshed = morale_snapshot_v1(state, team)
                    row = next((r for r in refreshed.get("players", []) if r.get("player_id") == pid), row)

            meeting_action = ""
            if (
                not row.get("trade_request_active")
                and _num(row.get("score"), 70.0) < 54.0
                and _int(row.get("meeting_cooldown_games"), 0) <= 0
            ):
                meeting_action = (
                    "Ask for patience"
                    if _num(row.get("trade_request_risk"), 0.0) >= 58.0
                    else "Reassure and listen"
                )
                try:
                    hold_player_meeting_v1(state, team, pid, action=meeting_action)
                    changed = True
                except ValueError:
                    meeting_action = ""

            desired = _desired_trade_response(state, team, row)
            previous = trade_response_v1(state, team, pid)
            if desired != previous:
                set_player_trade_response_v1(state, team, pid, response=desired)
                changed = True

            fields = _player_fields(state, pid)
            record = {
                "version": CPU_MORALE_RESPONSE_VERSION,
                "season": _season(state),
                "day": _day(state),
                "game_marker": marker,
                "team": team,
                "player_id": pid,
                "player_name": _clean(row.get("player_name")),
                "morale": round(_num(row.get("score"), 70.0), 1),
                "risk": round(_num(row.get("trade_request_risk"), 0.0), 1),
                "request": _clean(row.get("trade_request_status")) or "None",
                "core_player": _is_core_player(state, pid),
                "overall": round(fields["overall"], 1),
                "rotation_action": _clean(rotation_result.get("type")) or "none",
                "rotation_detail": _clean(rotation_result.get("detail")),
                "meeting": meeting_action or "None",
                "trade_response": desired,
                "trade_willingness_modifier": cpu_trade_willingness_modifier_v1(state, team, pid),
                "reason": (row.get("reasons") or ["Role pressure"])[0],
            }
            actions.append(record)
            audit.append(record)

        processed[team] = marker
        teams_processed += 1
        changed = True  # Persist the idempotency marker even if no concern existed.

    payload["cpu_morale_reactions"] = audit[-MAX_AUDIT_ROWS:]
    return {
        "version": CPU_MORALE_RESPONSE_VERSION,
        "changed": changed,
        "teams_processed": teams_processed,
        "actions": actions,
        "controlled_teams_skipped": sorted(controlled),
    }


def cpu_morale_audit_rows_v1(state: Any, *, limit: int = 40) -> list[dict[str, Any]]:
    payload = ensure_morale_state_v1(state)
    rows = [row for row in list(payload.get("cpu_morale_reactions", []) or []) if isinstance(row, dict)]
    rows = rows[-max(1, int(limit)):]
    rows.reverse()
    return rows


def render_cpu_morale_response_audit_v1(state: Any, *, controlled_teams: tuple[str, ...] = ()) -> None:
    import pandas as pd
    import streamlit as st

    rows = cpu_morale_audit_rows_v1(state, limit=40)
    st.markdown("### League morale responses")
    st.caption(
        "CPU teams first try role/minute repair and internal meetings. Sustained trade pressure can move a player to listening or the trade block, but this system never executes or legalizes a trade by itself."
    )
    if not rows:
        st.info("No CPU morale intervention has been required yet in this save.")
        return
    metrics = st.columns(4)
    metrics[0].metric("Recent actions", len(rows))
    metrics[1].metric("Role repairs", sum(row.get("rotation_action") in {"minutes_repair", "rotation_repair"} for row in rows))
    metrics[2].metric("Listening", sum(row.get("trade_response") == "Listening to offers" for row in rows))
    metrics[3].metric("Trade block", sum(row.get("trade_response") == "On trade block" for row in rows))
    display = pd.DataFrame(
        [
            {
                "Team": row.get("team"),
                "Player": row.get("player_name"),
                "Morale": row.get("morale"),
                "Risk %": row.get("risk"),
                "Request": row.get("request"),
                "Role response": row.get("rotation_action"),
                "Meeting": row.get("meeting"),
                "Trade plan": row.get("trade_response"),
                "Why": row.get("reason"),
            }
            for row in rows
        ]
    )
    st.dataframe(display, hide_index=True, width="stretch", height=min(560, 68 + 35 * len(display)))


__all__ = [
    "CPU_MORALE_RESPONSE_VERSION",
    "run_cpu_morale_reactions_v1",
    "cpu_trade_willingness_modifier_v1",
    "cpu_morale_audit_rows_v1",
    "render_cpu_morale_response_audit_v1",
]
