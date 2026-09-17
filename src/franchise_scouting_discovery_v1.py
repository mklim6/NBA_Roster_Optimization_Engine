from __future__ import annotations

import hashlib
import math
import random
from typing import Any, Iterable

from franchise_staff_system_v1 import (
    scouting_error_band,
    team_staff_effects,
    lead_scout_member,
)


FRANCHISE_SCOUTING_DISCOVERY_VERSION = (
    "franchise-scouting-discovery-v1.1-2026-09-16"
)
SCOUTING_KEY = "scouting_discovery_v1"
MAX_SCOUTING_WEEKS = 5
MAX_FOCUS_PROSPECTS = 6


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


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, float(value)))


def _seed(*parts: Any) -> int:
    text = "|".join(_clean(part) for part in parts)
    return int(hashlib.sha256(text.encode("utf-8")).hexdigest()[:14], 16)


def _draft_state(state: Any) -> dict[str, Any] | None:
    current = getattr(state, "franchise_draft_state_v1", None)
    return current if isinstance(current, dict) else None


def ensure_scouting_team_state_v1(state: Any, team: str) -> dict[str, Any]:
    current = _draft_state(state)
    if current is None:
        raise ValueError("Draft state is not initialized.")
    root = current.setdefault(SCOUTING_KEY, {})
    root.setdefault("version", FRANCHISE_SCOUTING_DISCOVERY_VERSION)
    root.setdefault("draft_year", current.get("draft_year"))
    teams = root.setdefault("teams", {})
    resolved = _team(team)
    payload = teams.setdefault(
        resolved,
        {
            "team": resolved,
            "weeks_completed": 0,
            "focus_ids": [],
            "reports": {},
        },
    )
    payload.setdefault("weeks_completed", 0)
    payload.setdefault("focus_ids", [])
    payload.setdefault("reports", {})
    return payload


def _confidence_baseline(state: Any, team: str, *, potential: bool = False) -> float:
    effects = team_staff_effects(state, team, ensure=True)
    rating = effects.scouting_potential_accuracy if potential else effects.scouting_current_accuracy
    return _clamp(28.0 + (rating - 50.0) * 0.58, 25.0, 58.0)


def _estimate(
    state: Any,
    team: str,
    prospect: dict[str, Any],
    *,
    confidence: float,
    potential: bool,
    week: int,
) -> float:
    truth_key = "hidden_potential" if potential else "hidden_overall"
    truth = _num(prospect.get(truth_key), 70.0)
    band = scouting_error_band(state, team, potential=potential)
    residual = max(0.55, band * (1.0 - confidence / 108.0))
    rng = random.Random(
        _seed(
            FRANCHISE_SCOUTING_DISCOVERY_VERSION,
            _team(team),
            prospect.get("prospect_id"),
            "potential" if potential else "overall",
            week,
        )
    )
    return round(_clamp(truth + rng.gauss(0.0, residual), 45.0, 99.0), 1)


def _report_for(
    state: Any,
    team: str,
    prospect: dict[str, Any],
    payload: dict[str, Any],
) -> dict[str, Any]:
    pid = _clean(prospect.get("prospect_id"))
    reports = payload["reports"]
    report = reports.get(pid)
    if not isinstance(report, dict):
        current_conf = _confidence_baseline(state, team, potential=False)
        potential_conf = _confidence_baseline(state, team, potential=True)
        report = {
            "prospect_id": pid,
            "current_confidence": round(current_conf, 1),
            "potential_confidence": round(potential_conf, 1),
            "weeks_seen": 0,
        }
        reports[pid] = report
    week = int(payload.get("weeks_completed", 0) or 0)
    report["scouted_overall"] = _estimate(
        state,
        team,
        prospect,
        confidence=_num(report.get("current_confidence")),
        potential=False,
        week=week,
    )
    report["scouted_potential"] = _estimate(
        state,
        team,
        prospect,
        confidence=_num(report.get("potential_confidence")),
        potential=True,
        week=week,
    )
    report["confidence"] = round(
        (_num(report.get("current_confidence")) + _num(report.get("potential_confidence"))) / 2.0,
        1,
    )
    return report


def set_scouting_focus_v1(state: Any, team: str, prospect_ids: Iterable[str]) -> tuple[str, ...]:
    payload = ensure_scouting_team_state_v1(state, team)
    current = _draft_state(state) or {}
    valid = {_clean(row.get("prospect_id")) for row in current.get("prospects", [])}
    selected = []
    for raw in prospect_ids:
        pid = _clean(raw)
        if pid and pid in valid and pid not in selected:
            selected.append(pid)
        if len(selected) >= MAX_FOCUS_PROSPECTS:
            break
    payload["focus_ids"] = selected
    return tuple(selected)


def advance_scouting_week_v1(state: Any, team: str) -> dict[str, Any]:
    payload = ensure_scouting_team_state_v1(state, team)
    week = int(payload.get("weeks_completed", 0) or 0)
    if week >= MAX_SCOUTING_WEEKS:
        raise ValueError(f"The scouting cycle is already complete after {MAX_SCOUTING_WEEKS} weeks.")
    current = _draft_state(state) or {}
    focus = set(payload.get("focus_ids", []) or [])
    for prospect in current.get("prospects", []):
        report = _report_for(state, team, prospect, payload)
        pid = _clean(prospect.get("prospect_id"))
        focused = pid in focus
        current_gain = 17.0 if focused else 4.0
        potential_gain = 15.0 if focused else 3.0
        report["current_confidence"] = round(_clamp(_num(report.get("current_confidence")) + current_gain, 0.0, 94.0), 1)
        report["potential_confidence"] = round(_clamp(_num(report.get("potential_confidence")) + potential_gain, 0.0, 92.0), 1)
        report["confidence"] = round(
            (_num(report.get("current_confidence")) + _num(report.get("potential_confidence"))) / 2.0,
            1,
        )
        report["scouted_overall"] = _estimate(
            state, team, prospect, confidence=_num(report.get("current_confidence")), potential=False, week=week + 1
        )
        report["scouted_potential"] = _estimate(
            state, team, prospect, confidence=_num(report.get("potential_confidence")), potential=True, week=week + 1
        )
        if focused:
            report["weeks_seen"] = int(report.get("weeks_seen", 0) or 0) + 1
    payload["weeks_completed"] = week + 1
    return scouting_summary_v1(state, team)


def scouting_summary_v1(state: Any, team: str) -> dict[str, Any]:
    payload = ensure_scouting_team_state_v1(state, team)
    effects = team_staff_effects(state, team, ensure=True)
    reports = list(payload.get("reports", {}).values())
    avg_conf = sum(_num(row.get("confidence")) for row in reports) / len(reports) if reports else _confidence_baseline(state, team)
    return {
        "team": _team(team),
        "weeks_completed": int(payload.get("weeks_completed", 0) or 0),
        "weeks_remaining": max(0, MAX_SCOUTING_WEEKS - int(payload.get("weeks_completed", 0) or 0)),
        "focus_ids": tuple(payload.get("focus_ids", []) or []),
        "average_confidence": round(avg_conf, 1),
        "scout_current": round(effects.scouting_current_accuracy, 1),
        "scout_potential": round(effects.scouting_potential_accuracy, 1),
        "current_error_band": scouting_error_band(state, team, potential=False),
        "potential_error_band": scouting_error_band(state, team, potential=True),
        "version": FRANCHISE_SCOUTING_DISCOVERY_VERSION,
    }


def scouting_board_rows_v1(state: Any, team: str, *, available_only: bool = False) -> list[dict[str, Any]]:
    current = _draft_state(state)
    if current is None:
        return []
    payload = ensure_scouting_team_state_v1(state, team)
    rows = []
    for prospect in current.get("prospects", []):
        if available_only and prospect.get("drafted"):
            continue
        report = _report_for(state, team, prospect, payload)
        confidence = _num(report.get("confidence"))
        if confidence >= 80:
            tier = "Deep"
        elif confidence >= 65:
            tier = "Strong"
        elif confidence >= 48:
            tier = "Evaluated"
        else:
            tier = "Preliminary"
        rows.append(
            {
                "prospect_id": prospect.get("prospect_id"),
                "Rank": prospect.get("big_board_rank"),
                "Prospect": prospect.get("player_name"),
                "Pos": prospect.get("position"),
                "Age": prospect.get("age"),
                "School / Club": prospect.get("school"),
                "Archetype": prospect.get("archetype"),
                "Scouted OVR": report.get("scouted_overall"),
                "Scouted POT": report.get("scouted_potential"),
                "Confidence": confidence,
                "Report": tier,
                "Focus": _clean(prospect.get("prospect_id")) in set(payload.get("focus_ids", []) or []),
                "Projected": prospect.get("projected_range"),
                "Drafted": bool(prospect.get("drafted")),
            }
        )
    rows.sort(key=lambda row: (_num(row.get("Rank"), 999), row.get("Prospect", "")))
    return rows


def ai_scouted_estimate_v1(state: Any, team: str, prospect: dict[str, Any]) -> dict[str, float]:
    """Deterministic imperfect scouting for CPU draft boards.

    CPU teams no longer draft from exact hidden OVR/POT. Their lead scout's
    ratings control the error band, while a team/prospect hash makes misses
    stable and reproducible within a draft.
    """
    effects = team_staff_effects(state, team, ensure=True)
    current_conf = _clamp(48.0 + (effects.scouting_current_accuracy - 50.0) * 0.42, 45.0, 78.0)
    potential_conf = _clamp(46.0 + (effects.scouting_potential_accuracy - 50.0) * 0.42, 43.0, 76.0)
    current = _estimate(state, team, prospect, confidence=current_conf, potential=False, week=99)
    potential = _estimate(state, team, prospect, confidence=potential_conf, potential=True, week=99)
    return {
        "overall": current,
        "potential": potential,
        "confidence": round((current_conf + potential_conf) / 2.0, 1),
    }


def render_scouting_discovery_v1(
    *,
    state: Any,
    team: str,
    commit_state: Any,
) -> None:
    import pandas as pd
    import streamlit as st

    current = _draft_state(state)
    if current is None or current.get("phase") not in {"season_scouting", "scouting"}:
        return
    resolved = _team(team)
    summary = scouting_summary_v1(state, resolved)
    board_rows = scouting_board_rows_v1(state, resolved)
    active_scout = lead_scout_member(state, resolved, ensure=True)

    st.markdown("### Scouting Command Center")
    phase = _clean(current.get("phase"))
    if phase == "season_scouting":
        st.caption(
            "The next draft class is available throughout the season. Your lead scout controls "
            "uncertainty, focus assignments accelerate confidence, and reports persist into the "
            "lottery and Draft Night. Hidden OVR/POT never become perfectly known."
        )
    else:
        st.caption(
            "Your lead scout controls uncertainty. Focus assignments accelerate confidence, "
            "but hidden OVR/POT never become perfectly known before the draft. CPU teams now "
            "use their own imperfect staff-driven scouting instead of exact hidden ratings."
        )
    metrics = st.columns(5)
    metrics[0].metric("Scouting week", f'{summary["weeks_completed"]}/{MAX_SCOUTING_WEEKS}')
    metrics[1].metric("Board confidence", f'{summary["average_confidence"]:.0f}%')
    metrics[2].metric("Current talent scout", f'{summary["scout_current"]:.0f}')
    metrics[3].metric("Potential scout", f'{summary["scout_potential"]:.0f}')
    metrics[4].metric("Focus slots", f'{len(summary["focus_ids"])}/{MAX_FOCUS_PROSPECTS}')
    if active_scout is not None:
        st.caption(
            f"Lead scout: **{active_scout.name}** · Current expected band ±{summary['current_error_band']:.1f} · "
            f"Potential expected band ±{summary['potential_error_band']:.1f}. Manage or replace the scout from **Staff**."
        )

    options = [row for row in board_rows if not row["Drafted"]][:40]
    label_by_id = {
        _clean(row["prospect_id"]): f'#{int(row["Rank"])} {row["Prospect"]} · {row["Pos"]} · {row["Projected"]}'
        for row in options
    }
    selected = st.multiselect(
        "Priority scouting assignments",
        options=list(label_by_id),
        default=[pid for pid in summary["focus_ids"] if pid in label_by_id],
        max_selections=MAX_FOCUS_PROSPECTS,
        format_func=lambda pid: label_by_id.get(pid, pid),
        key=f"scouting_focus_{current.get('draft_year')}_{resolved}",
    )
    if tuple(selected) != tuple(summary["focus_ids"]):
        set_scouting_focus_v1(state, resolved, selected)

    if st.button(
        "Advance one scouting week",
        type="primary",
        width="stretch",
        disabled=summary["weeks_remaining"] <= 0,
        key=f"scouting_advance_{current.get('draft_year')}_{resolved}",
    ):
        set_scouting_focus_v1(state, resolved, selected)
        advance_scouting_week_v1(state, resolved)
        commit_state(state, checkpoint_reason="draft-scouting-week-v1")
        st.rerun()

    display = pd.DataFrame(board_rows).drop(columns=["prospect_id"], errors="ignore")
    st.dataframe(display, hide_index=True, width="stretch", height=620)


__all__ = [
    "FRANCHISE_SCOUTING_DISCOVERY_VERSION",
    "ensure_scouting_team_state_v1",
    "set_scouting_focus_v1",
    "advance_scouting_week_v1",
    "scouting_summary_v1",
    "scouting_board_rows_v1",
    "ai_scouted_estimate_v1",
    "render_scouting_discovery_v1",
]
