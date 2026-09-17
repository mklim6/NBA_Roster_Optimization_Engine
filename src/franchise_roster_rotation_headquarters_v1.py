from __future__ import annotations

import html
import itertools
import math
from typing import Any, Callable

from franchise_command_center_v1 import (
    apply_rotation_plan,
    rotation_plan_from_rows,
)
from franchise_morale_chemistry_v1 import (
    MEETING_ACTIONS,
    ROLE_PRESETS,
    TRADE_RESPONSE_OPTIONS,
    clear_player_role_expectation_v1,
    hold_player_meeting_v1,
    morale_action_queue_v1,
    morale_snapshot_v1,
    refresh_team_morale_v1,
    role_expectation_v1,
    rotation_emphasis_v1,
    set_player_role_expectation_v1,
    set_player_trade_response_v1,
    set_rotation_emphasis_v1,
    trade_response_v1,
)

FRANCHISE_ROSTER_ROTATION_HQ_VERSION = (
    "franchise-roster-rotation-headquarters-v1.4-consequences-2026-09-16"
)


def _clean(value: Any) -> str:
    return str(value or "").strip()


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


def _position_tokens(value: Any) -> set[str]:
    raw = _clean(value).upper().replace("/", "-").replace(" ", "")
    aliases = {
        "POINTGUARD": "PG", "SHOOTINGGUARD": "SG", "SMALLFORWARD": "SF",
        "POWERFORWARD": "PF", "CENTER": "C", "GUARD": "G", "FORWARD": "F",
    }
    raw = aliases.get(raw, raw)
    tokens = {token for token in raw.replace("_", "-").split("-") if token}
    expanded = set(tokens)
    if "G" in tokens:
        expanded.update({"PG", "SG"})
    if "F" in tokens:
        expanded.update({"SF", "PF"})
    if "GF" in tokens or "FG" in tokens:
        expanded.update({"PG", "SG", "SF", "PF"})
    if "FC" in tokens or "CF" in tokens:
        expanded.update({"SF", "PF", "C"})
    return expanded


def _position_cost(position: Any, slot: str) -> float:
    tokens = _position_tokens(position)
    if slot in tokens:
        return 0.0
    adjacency = {
        "PG": ("SG", "SF"), "SG": ("PG", "SF"), "SF": ("SG", "PF"),
        "PF": ("SF", "C"), "C": ("PF", "SF"),
    }
    if any(other in tokens for other in adjacency[slot]):
        return 1.4
    return 4.0


def _available(row: dict[str, Any]) -> bool:
    status = _clean(row.get("availability")).lower()
    return status not in {"out", "doubtful", "inactive", "suspended"}


def _player_score(state: Any, row: dict[str, Any], philosophy: str) -> float:
    player = (getattr(state, "players", {}) or {}).get(str(row.get("player_id", "")))
    overall = _num(row.get("overall"), getattr(player, "overall_rating", 0.0) if player else 0.0)
    potential = _num(getattr(player, "potential_rating", overall) if player else overall, overall)
    age = _num(row.get("age"), getattr(player, "age", 27.0) if player else 27.0)
    fatigue = _num(row.get("fatigue"), 0.0)
    availability_penalty = 0.0 if _available(row) else 100.0

    score = overall * 1.0 + potential * 0.08 - fatigue * 0.045 - availability_penalty
    philosophy = _clean(philosophy).lower()
    if philosophy == "development":
        youth = max(0.0, 27.0 - age)
        upside = max(0.0, potential - overall)
        score += youth * 1.45 + upside * 0.95
        draft_pick = _int(getattr(player, "draft_pick", 0) if player else 0, 0)
        rookie_season = _clean(getattr(player, "rookie_season", "") if player else "")
        current_season = _clean(getattr(getattr(state, "settings", None), "season_label", ""))
        if rookie_season == current_season and 1 <= draft_pick <= 14:
            score += 9.0 if draft_pick <= 5 else 6.0
    elif philosophy == "win now":
        score += max(0.0, overall - 80.0) * 0.55
        score -= max(0.0, 22.0 - age) * 0.35
    else:
        score += max(0.0, potential - overall) * 0.30
    return score


def build_rotation_recommendation_v1(
    state: Any,
    team: str,
    rotation_rows: list[dict[str, Any]],
    *,
    philosophy: str = "Balanced",
) -> list[dict[str, Any]]:
    rows = [dict(row) for row in rotation_rows]
    if len(rows) < 8:
        raise ValueError("A legal rotation recommendation requires at least eight rostered players.")

    healthy = [row for row in rows if _available(row)]
    pool = healthy if len(healthy) >= 8 else rows
    scored = sorted(
        pool,
        key=lambda row: (
            -_player_score(state, row, philosophy),
            -_num(row.get("overall")),
            _clean(row.get("player")),
        ),
    )
    rotation_size = min(10, len(scored))
    rotation = scored[:rotation_size]

    # Choose five starters from the top eight rotation candidates while
    # minimizing positional mismatch and preserving player quality.
    slots = ("PG", "SG", "SF", "PF", "C")
    starter_pool = rotation[: min(8, len(rotation))]
    best: tuple[dict[str, Any], ...] | None = None
    best_cost = float("inf")
    for combo in itertools.combinations(starter_pool, 5):
        for perm in itertools.permutations(combo, 5):
            positional = sum(_position_cost(row.get("position"), slot) for slot, row in zip(slots, perm))
            quality = sum(_player_score(state, row, philosophy) for row in perm)
            cost = positional * 10.0 - quality * 0.05
            if cost < best_cost:
                best_cost = cost
                best = perm
    starter_ids = {str(row.get("player_id")) for row in (best or tuple(rotation[:5]))}
    # Minute templates assume the first five rows are the starters. Reorder the
    # selected rotation after positional optimization so a lower-ranked center
    # chosen for lineup balance does not accidentally receive bench minutes.
    rotation = sorted(
        rotation,
        key=lambda row: (
            str(row.get("player_id")) not in starter_ids,
            -_player_score(state, row, philosophy),
            -_num(row.get("overall")),
        ),
    )

    templates = {
        "balanced": (34.0, 32.0, 31.0, 30.0, 29.0, 24.0, 22.0, 16.0, 12.0, 10.0),
        "win now": (36.0, 34.0, 33.0, 31.0, 30.0, 23.0, 20.0, 14.0, 10.0, 9.0),
        "development": (32.0, 31.0, 30.0, 29.0, 28.0, 25.0, 24.0, 18.0, 13.0, 10.0),
    }
    key = _clean(philosophy).lower()
    minute_template = templates.get(key, templates["balanced"])
    minute_template = minute_template[:rotation_size]
    # If fewer than ten players are available, absorb missing bench minutes
    # proportionally into the selected rotation while keeping exact 240.
    if len(minute_template) < 10:
        missing = 240.0 - sum(minute_template)
        weights = [max(1.0, value) for value in minute_template]
        total_weight = sum(weights)
        minute_template = tuple(value + missing * weight / total_weight for value, weight in zip(minute_template, weights))

    rotation_ids = [str(row.get("player_id")) for row in rotation]
    minutes_by_id = {
        player_id: round(float(minutes), 1)
        for player_id, minutes in zip(rotation_ids, minute_template)
    }
    # Floating-round correction.
    correction = round(240.0 - sum(minutes_by_id.values()), 1)
    if rotation_ids:
        minutes_by_id[rotation_ids[0]] = round(minutes_by_id[rotation_ids[0]] + correction, 1)

    output = []
    rotation_order = {pid: index + 1 for index, pid in enumerate(rotation_ids)}
    for row in rows:
        pid = str(row.get("player_id", ""))
        updated = dict(row)
        updated["in_rotation"] = pid in rotation_order
        updated["starter"] = pid in starter_ids
        updated["rotation_order"] = rotation_order.get(pid, 99)
        updated["minutes"] = minutes_by_id.get(pid, 0.0)
        output.append(updated)

    if sum(bool(row["starter"]) for row in output) != 5:
        raise ValueError("Recommended rotation did not produce exactly five starters.")
    if sum(bool(row["in_rotation"]) for row in output) < 8:
        raise ValueError("Recommended rotation did not produce at least eight rotation players.")
    total_minutes = sum(_num(row["minutes"]) for row in output if row["in_rotation"])
    if abs(total_minutes - 240.0) > 0.11:
        raise ValueError(f"Recommended rotation totals {total_minutes:.1f}, not 240.0 minutes.")
    return output


def roster_hq_snapshot_v1(state: Any, team: str, rotation_rows: list[dict[str, Any]]) -> dict[str, Any]:
    players = getattr(state, "players", {}) or {}
    rows = list(rotation_rows)
    roster_count = len(rows)
    rotation_count = sum(bool(row.get("in_rotation")) for row in rows)
    assigned = sum(_num(row.get("minutes")) for row in rows if bool(row.get("in_rotation")))
    starters = sum(bool(row.get("starter")) for row in rows)
    youth = 0
    veterans = 0
    expiring = 0
    rookies = 0
    current_season = _clean(getattr(getattr(state, "settings", None), "season_label", ""))
    for row in rows:
        player = players.get(str(row.get("player_id", "")))
        age = _num(row.get("age"), getattr(player, "age", 27.0) if player else 27.0)
        youth += age <= 24
        veterans += age >= 31
        contract = getattr(player, "contract", None) if player else None
        years = getattr(contract, "years_remaining", None) if contract is not None else None
        expiring += years is not None and _int(years, 99) <= 1
        rookies += bool(player is not None and _clean(getattr(player, "rookie_season", "")) == current_season)

    groups = {"Guard": [], "Wing": [], "Big": []}
    for row in rows:
        tokens = _position_tokens(row.get("position"))
        if tokens.intersection({"PG", "SG"}): groups["Guard"].append(row)
        if tokens.intersection({"SF", "PF"}): groups["Wing"].append(row)
        if tokens.intersection({"PF", "C"}): groups["Big"].append(row)
    needs = []
    for group, group_rows in groups.items():
        ordered = sorted(group_rows, key=lambda row: -_num(row.get("overall")))
        top = _num(ordered[0].get("overall")) if ordered else 0.0
        second = _num(ordered[1].get("overall")) if len(ordered) > 1 else 0.0
        if not ordered:
            status, priority = "Critical", 100
        elif len(ordered) < 2 or second < 70:
            status, priority = "Thin", 82
        elif top < 78 or second < 73:
            status, priority = "Watch", 62
        else:
            status, priority = "Stable", 30
        needs.append({"group": group, "status": status, "priority": priority, "top": top, "second": second})
    needs.sort(key=lambda row: (-row["priority"], row["group"]))

    morale = morale_snapshot_v1(state, team)
    conflicts = [row for row in morale["players"] if row["score"] < 55 or row["trade_request_risk"] >= 35]
    conflicts.sort(key=lambda row: (-row["trade_request_risk"], row["score"], row["player_name"]))
    return {
        "roster_count": roster_count,
        "rotation_count": rotation_count,
        "starters": starters,
        "assigned_minutes": round(assigned, 1),
        "youth": youth,
        "veterans": veterans,
        "expiring": expiring,
        "rookies": rookies,
        "needs": needs,
        "morale": morale,
        "conflicts": conflicts,
    }


def _esc(value: Any) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def render_roster_rotation_headquarters_v1(
    *,
    state: Any,
    team: str,
    rotation_rows: list[dict[str, Any]],
    team_name_resolver: Callable[[str], str],
    team_logo_resolver: Callable[[str], str],
    team_colors_resolver: Callable[[str], tuple[str, str]],
    player_headshot_resolver: Callable[..., str],
    commit_state: Callable[..., None],
    disabled: bool = False,
) -> None:
    import pandas as pd
    import streamlit as st

    resolved = _clean(team).upper()
    name = team_name_resolver(resolved)
    primary, secondary = team_colors_resolver(resolved)
    snapshot = roster_hq_snapshot_v1(state, resolved, rotation_rows)
    morale = snapshot["morale"]

    st.markdown(
        f"""
<style>
.rrh-hero{{padding:18px 20px;border-radius:20px;border:1px solid rgba(255,255,255,.09);background:radial-gradient(circle at 90% 0%,{_esc(primary)}33,transparent 34%),linear-gradient(135deg,#08131f,#0b1018);margin-bottom:12px}}
.rrh-kicker{{color:#7dd3fc;font-size:.62rem;font-weight:950;letter-spacing:.15em;text-transform:uppercase}} .rrh-title{{color:#fff;font-size:1.6rem;font-weight:950;margin-top:3px}} .rrh-copy{{color:#8fa2b8;font-size:.72rem;margin-top:5px;max-width:850px;line-height:1.5}}
.rrh-needs{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;margin:8px 0 14px}} .rrh-need{{padding:11px;border-radius:13px;border:1px solid rgba(255,255,255,.07);background:#09131f}} .rrh-need small{{color:#71849a;font-size:.48rem;font-weight:950;letter-spacing:.1em}} .rrh-need strong{{display:block;color:#fff;font-size:.78rem;margin-top:4px}} .rrh-need span{{display:block;color:#8497ad;font-size:.53rem;margin-top:3px}}
@media(max-width:800px){{.rrh-needs{{grid-template-columns:1fr}}}}
</style>
<div class="rrh-hero"><div class="rrh-kicker">ROSTER / ROTATION HEADQUARTERS · {_esc(FRANCHISE_ROSTER_ROTATION_HQ_VERSION)}</div><div class="rrh-title">{_esc(name)} Personnel Command</div><div class="rrh-copy">Depth, minutes, role hierarchy, player satisfaction, chemistry and roster weaknesses in one workspace. Recommended rotations use live ratings, health, potential, age and rookie opportunity without altering player ratings.</div></div>
""",
        unsafe_allow_html=True,
    )

    metrics = st.columns(6)
    metrics[0].metric("Roster", snapshot["roster_count"])
    metrics[1].metric("Rotation", snapshot["rotation_count"])
    metrics[2].metric("Minutes", f'{snapshot["assigned_minutes"]:.1f}', f'{snapshot["assigned_minutes"] - 240:+.1f}')
    metrics[3].metric("Chemistry", f'{morale["chemistry"]:.0f}/100')
    metrics[4].metric("Rookies", snapshot["rookies"])
    metrics[5].metric("Expiring", snapshot["expiring"])

    need_html = []
    for row in snapshot["needs"]:
        need_html.append(
            '<div class="rrh-need">'
            f'<small>{_esc(row["group"].upper())} DEPTH</small>'
            f'<strong>{_esc(row["status"])}</strong>'
            f'<span>Top {row["top"]:.0f} · No. 2 {row["second"]:.0f}</span>'
            '</div>'
        )
    st.markdown('<div class="rrh-needs">' + ''.join(need_html) + '</div>', unsafe_allow_html=True)

    left, right = st.columns([1.15, 0.85])
    with left:
        st.markdown("### Rotation recommendation")
        philosophy_key = (
            f"rrh_philosophy_{resolved}_{_clean(getattr(state.settings, 'season_label', ''))}"
        )
        if philosophy_key not in st.session_state:
            st.session_state[philosophy_key] = rotation_emphasis_v1(state, resolved)
        philosophy = st.selectbox(
            "Front-office emphasis",
            options=["Balanced", "Win Now", "Development"],
            key=philosophy_key,
            help="Balanced blends current quality and upside. Win Now leans harder on the best veterans. Development creates more runway for young high-upside players and lottery rookies. The last applied emphasis persists with the franchise.",
        )
        recommendation = build_rotation_recommendation_v1(
            state,
            resolved,
            rotation_rows,
            philosophy=philosophy,
        )
        preview = [
            {
                "Order": row["rotation_order"],
                "Player": row.get("player"),
                "Pos": row.get("position"),
                "OVR": row.get("overall"),
                "Starter": row["starter"],
                "Minutes": row["minutes"],
            }
            for row in sorted(recommendation, key=lambda row: row["rotation_order"])
            if row["in_rotation"]
        ]
        st.dataframe(pd.DataFrame(preview), hide_index=True, width="stretch", height=350)
        if st.button(
            f"Apply {philosophy} recommendation",
            type="primary",
            width="stretch",
            disabled=disabled,
            key=f"rrh_apply_{resolved}_{philosophy}",
        ):
            plan = rotation_plan_from_rows(state, resolved, recommendation)
            updated = apply_rotation_plan(state, plan)
            set_rotation_emphasis_v1(updated, resolved, philosophy)
            refresh_team_morale_v1(
                updated,
                resolved,
                blend=0.45,
                reason="rotation-change",
            )
            commit_state(updated, checkpoint_reason="roster-hq-recommended-rotation-v1")
            st.session_state["franchise_notice"] = (
                f"Applied the {philosophy} rotation plan for {name}."
            )
            st.rerun()

    with right:
        st.markdown("### Locker room")
        st.caption(
            "Morale reacts to playing time, role expectations, team results and recent usage. "
            "Trade-request pressure now requires sustained frustration rather than one bad game."
        )
        pulse = st.columns(4)
        pulse[0].metric("Chemistry", f'{morale["chemistry"]:.0f}', f'{morale.get("chemistry_delta", 0.0):+.1f}')
        pulse[1].metric("Role fit", f'{morale.get("role_alignment", 0.0):.0f}')
        pulse[2].metric("Frustrated", int(morale.get("frustrated_players", 0)))
        pulse[3].metric("Trade asks", int(morale.get("active_requests", 0)))
        locker_rows = [
            {
                "Player": row["player_name"],
                "Status": row["status"],
                "Morale": row["score"],
                "Trend": f'{row.get("score_delta", 0.0):+.1f}',
                "Expected": row["expected_role"],
                "Expected MIN": row["expected_minutes"],
                "Actual MIN": row["actual_minutes"],
                "Trade status": row.get("trade_request_status", "None"),
                "FO response": row.get("trade_availability", "Keep internal"),
                "Risk %": row["trade_request_risk"],
            }
            for row in morale["players"]
        ]
        st.dataframe(
            pd.DataFrame(locker_rows),
            hide_index=True,
            width="stretch",
            height=350,
        )
        actions = morale_action_queue_v1(state, resolved)
        if actions:
            top = actions[0]
            st.warning(
                f'Priority: {top["player_name"]} — {top["action"]}. '
                f'{top["reason"]}.'
            )
        else:
            st.success("No major role-satisfaction conflicts are currently flagged.")

    with st.expander("Player role conversation", expanded=False):
        st.caption(
            "Set an explicit role expectation for a player. Promises become part of morale calculations, "
            "so repeatedly missing promised minutes can create sustained frustration and trade pressure."
        )
        roster_options = {
            row["player_name"]: row["player_id"]
            for row in sorted(morale["players"], key=lambda item: item["player_name"])
        }
        if roster_options:
            selected_name = st.selectbox(
                "Player",
                options=list(roster_options),
                key=f"rrh_role_player_{resolved}",
            )
            selected_id = roster_options[selected_name]
            current_expectation = role_expectation_v1(state, resolved, selected_id)
            role_names = list(ROLE_PRESETS)
            current_role = current_expectation["role"] if current_expectation.get("promise_active") else "Auto"
            if current_role not in role_names:
                current_role = "Auto"
            role_choice = st.selectbox(
                "Role expectation",
                options=role_names,
                index=role_names.index(current_role),
                key=f"rrh_role_choice_{resolved}_{selected_id}",
            )
            if current_expectation.get("promise_active"):
                default_minutes = current_expectation["minutes"]
            elif role_choice == "Auto":
                default_minutes = current_expectation["minutes"]
            else:
                default_minutes = ROLE_PRESETS.get(role_choice, ("Auto", 0.0))[1]
            promised_minutes = st.number_input(
                "Expected minutes per game",
                min_value=0.0,
                max_value=40.0,
                value=float(default_minutes),
                step=1.0,
                key=f"rrh_role_minutes_{resolved}_{selected_id}_{role_choice}",
                disabled=role_choice == "Auto",
            )
            current_review = int(current_expectation.get("review_after_games", 5) or 5)
            review_games = st.slider(
                "Review promise after games",
                min_value=3,
                max_value=10,
                value=max(3, min(10, current_review)),
                step=1,
                key=f"rrh_role_review_{resolved}_{selected_id}_{role_choice}",
                disabled=role_choice == "Auto",
                help="After this many games, the simulator grades whether the role/minutes promise was kept. Repeated misses create a durable broken-promise penalty.",
            )
            automatic = current_expectation.get("automatic_role", "Reserve")
            automatic_minutes = current_expectation.get(
                "automatic_minutes",
                current_expectation["minutes"],
            )
            promise_status = current_expectation.get("promise_status", "none")
            progress_text = ""
            if current_expectation.get("promise_active"):
                progress_text = (
                    f' Promise review: {promise_status} · '
                    f'{int(current_expectation.get("games_since_set", 0))}/{int(current_expectation.get("review_after_games", 5))} games · '
                    f'{int(current_expectation.get("met_games", 0))} met / {int(current_expectation.get("missed_games", 0))} missed.'
                )
            st.caption(
                f'Automatic expectation without a promise: {automatic} · {float(automatic_minutes):.1f} MPG. '
                "Changing a promise does not change ratings or minutes by itself." + progress_text
            )
            buttons = st.columns(2)
            if buttons[0].button(
                "Save role expectation",
                type="primary",
                width="stretch",
                disabled=disabled,
                key=f"rrh_save_role_{resolved}_{selected_id}",
            ):
                if role_choice == "Auto":
                    clear_player_role_expectation_v1(state, resolved, selected_id)
                else:
                    set_player_role_expectation_v1(
                        state,
                        resolved,
                        selected_id,
                        role=role_choice,
                        minutes=float(promised_minutes),
                        review_games=int(review_games),
                    )
                commit_state(state, checkpoint_reason="roster-hq-role-expectation-v1")
                st.session_state["franchise_notice"] = f"Updated {selected_name}'s role expectation."
                st.rerun()
            if buttons[1].button(
                "Return to automatic role",
                width="stretch",
                disabled=disabled or not current_expectation.get("promise_active"),
                key=f"rrh_clear_role_{resolved}_{selected_id}",
            ):
                clear_player_role_expectation_v1(state, resolved, selected_id)
                commit_state(state, checkpoint_reason="roster-hq-role-expectation-clear-v1")
                st.session_state["franchise_notice"] = f"Returned {selected_name} to an automatic role expectation."
                st.rerun()

    with st.expander("Player meeting & front-office response", expanded=False):
        st.caption(
            "Use meetings sparingly. They can ease immediate tension, but they do not erase bad minutes, broken promises, or a real trade request. "
            "Trade-response status is persistent and gives the franchise a visible way to acknowledge an unhappy player without forcing a transaction."
        )
        meeting_order = sorted(
            morale["players"],
            key=lambda row: (
                not bool(row.get("trade_request_active")),
                -float(row.get("trade_request_risk", 0.0)),
                float(row.get("score", 70.0)),
                row.get("player_name", ""),
            ),
        )
        meeting_options = {row["player_name"]: row for row in meeting_order}
        if meeting_options:
            meeting_name = st.selectbox(
                "Player to meet",
                options=list(meeting_options),
                key=f"rrh_meeting_player_{resolved}",
            )
            meeting_row = meeting_options[meeting_name]
            meeting_id = meeting_row["player_id"]
            info = st.columns(4)
            info[0].metric("Morale", f'{float(meeting_row.get("score", 0.0)):.1f}')
            info[1].metric("Trade risk", f'{float(meeting_row.get("trade_request_risk", 0.0)):.0f}%')
            with info[2]:
                st.caption("Request")
                st.markdown(f'**{_esc(meeting_row.get("trade_request_status", "None"))}**')
            info[3].metric("Meeting cooldown", f'{int(meeting_row.get("meeting_cooldown_games", 0))} gm')

            meeting_action = st.selectbox(
                "Meeting approach",
                options=list(MEETING_ACTIONS),
                key=f"rrh_meeting_action_{resolved}_{meeting_id}",
                help=(
                    "Reassure and listen gives a small short-term morale lift. Ask for patience temporarily lowers trade pressure. "
                    "Reset expectations honestly clears an active role promise but carries a small immediate morale cost."
                ),
            )
            current_trade_response = trade_response_v1(state, resolved, meeting_id)
            response_choice = st.selectbox(
                "Front-office trade response",
                options=list(TRADE_RESPONSE_OPTIONS),
                index=list(TRADE_RESPONSE_OPTIONS).index(current_trade_response),
                key=f"rrh_trade_response_{resolved}_{meeting_id}",
            )
            meet_col, response_col = st.columns(2)
            if meet_col.button(
                "Hold player meeting",
                type="primary",
                width="stretch",
                disabled=disabled or int(meeting_row.get("meeting_cooldown_games", 0)) > 0,
                key=f"rrh_hold_meeting_{resolved}_{meeting_id}",
            ):
                try:
                    hold_player_meeting_v1(
                        state,
                        resolved,
                        meeting_id,
                        action=meeting_action,
                    )
                    commit_state(state, checkpoint_reason="roster-hq-player-meeting-v1")
                    st.session_state["franchise_notice"] = f"Met with {meeting_name}: {meeting_action}."
                    st.rerun()
                except ValueError as exc:
                    st.warning(str(exc))
            if response_col.button(
                "Save trade response",
                width="stretch",
                disabled=disabled,
                key=f"rrh_save_trade_response_{resolved}_{meeting_id}",
            ):
                set_player_trade_response_v1(
                    state,
                    resolved,
                    meeting_id,
                    response=response_choice,
                )
                commit_state(state, checkpoint_reason="roster-hq-trade-response-v1")
                st.session_state["franchise_notice"] = f"Updated the front-office response for {meeting_name}."
                st.rerun()

    with st.expander("Full morale & role-satisfaction board", expanded=False):
        morale_rows = [
            {
                "Player": row["player_name"],
                "Morale": row["score"],
                "Trend": row.get("score_delta", 0.0),
                "Status": row["status"],
                "Role satisfaction": row["role_satisfaction"],
                "Expected role": row["expected_role"],
                "Promise": row.get("promise_status", "active") if row.get("promise_active") else "No",
                "Expected MIN": row["expected_minutes"],
                "Actual MIN": row["actual_minutes"],
                "Recent MIN": _num(row.get("recent_minutes"), float("nan")),
                "Trade": row.get("trade_request_status", "None"),
                "FO plan": row.get("trade_availability", "Keep internal"),
                "Risk %": row["trade_request_risk"],
            }
            for row in morale["players"]
        ]
        st.dataframe(pd.DataFrame(morale_rows), hide_index=True, width="stretch")

        st.markdown("#### Why morale is moving")
        st.markdown(
            """
<style>
.morale-reason-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;margin-top:6px}
.morale-reason-card{border:1px solid rgba(255,255,255,.08);border-radius:12px;background:#0a111b;padding:10px 12px;min-width:0}
.morale-reason-head{display:flex;justify-content:space-between;gap:10px;align-items:baseline;margin-bottom:5px}
.morale-reason-name{color:#fff;font-weight:850;font-size:.78rem}.morale-reason-score{color:#91a4b8;font-size:.62rem;white-space:nowrap}
.morale-reason-line{color:#aebdcb;font-size:.64rem;line-height:1.45;margin-top:2px;overflow-wrap:anywhere}
@media(max-width:850px){.morale-reason-grid{grid-template-columns:1fr}}
</style>
""",
            unsafe_allow_html=True,
        )
        reason_cards = []
        for row in morale["players"]:
            reasons = list(row.get("reasons", []) or ["Role and team context are stable"])
            reason_html = "".join(
                f'<div class="morale-reason-line">• {_esc(reason)}</div>'
                for reason in reasons[:4]
            )
            reason_cards.append(
                '<div class="morale-reason-card">'
                '<div class="morale-reason-head">'
                f'<span class="morale-reason-name">{_esc(row["player_name"])}</span>'
                f'<span class="morale-reason-score">{_esc(row["status"])} · {row["score"]:.1f} · {row.get("score_delta", 0.0):+.1f}</span>'
                '</div>'
                f'{reason_html}'
                '</div>'
            )
        st.markdown(
            '<div class="morale-reason-grid">' + ''.join(reason_cards) + '</div>',
            unsafe_allow_html=True,
        )


__all__ = [
    "FRANCHISE_ROSTER_ROTATION_HQ_VERSION",
    "build_rotation_recommendation_v1",
    "roster_hq_snapshot_v1",
    "render_roster_rotation_headquarters_v1",
]
