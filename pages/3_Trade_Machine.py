from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from freeform_trade_machine_engine_v2_2 import (  # noqa: E402
    CheckResult,
    RuntimeData,
    Status,
    TradeRequest,
    TradeSideRequest,
    evaluate_trade,
    load_runtime_data,
)


st.set_page_config(
    page_title="Freeform Trade Machine",
    page_icon="🔄",
    layout="wide",
)


STATUS_LABELS = {
    Status.PASS: "PASS",
    Status.MANUAL_REVIEW: "MANUAL REVIEW",
    Status.BLOCKED: "BLOCKED",
}

STATUS_ICONS = {
    Status.PASS: "✅",
    Status.MANUAL_REVIEW: "⚠️",
    Status.BLOCKED: "⛔",
}

STATUS_COLORS = {
    Status.PASS: "#1f9d55",
    Status.MANUAL_REVIEW: "#d97706",
    Status.BLOCKED: "#dc2626",
}

TEAM_NAMES = {
    "ATL": "Atlanta Hawks",
    "BOS": "Boston Celtics",
    "BKN": "Brooklyn Nets",
    "CHA": "Charlotte Hornets",
    "CHI": "Chicago Bulls",
    "CLE": "Cleveland Cavaliers",
    "DAL": "Dallas Mavericks",
    "DEN": "Denver Nuggets",
    "DET": "Detroit Pistons",
    "GSW": "Golden State Warriors",
    "HOU": "Houston Rockets",
    "IND": "Indiana Pacers",
    "LAC": "LA Clippers",
    "LAL": "Los Angeles Lakers",
    "MEM": "Memphis Grizzlies",
    "MIA": "Miami Heat",
    "MIL": "Milwaukee Bucks",
    "MIN": "Minnesota Timberwolves",
    "NOP": "New Orleans Pelicans",
    "NYK": "New York Knicks",
    "OKC": "Oklahoma City Thunder",
    "ORL": "Orlando Magic",
    "PHI": "Philadelphia 76ers",
    "PHX": "Phoenix Suns",
    "POR": "Portland Trail Blazers",
    "SAC": "Sacramento Kings",
    "SAS": "San Antonio Spurs",
    "TOR": "Toronto Raptors",
    "UTA": "Utah Jazz",
    "WAS": "Washington Wizards",
}


@st.cache_resource(show_spinner="Loading trade engine...")
def get_runtime() -> RuntimeData:
    return load_runtime_data()


def safe_float(value: Any) -> float | None:
    if value is None or pd.isna(value):
        return None

    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def money(value: Any) -> str:
    amount = safe_float(value)

    if amount is None:
        return "Salary unavailable"

    return f"${amount / 1_000_000:.2f}M"


def rating_text(value: Any) -> str:
    rating = safe_float(value)

    if rating is None:
        return "NR"

    return f"{rating:.1f}"


def team_label(team: str) -> str:
    return f"{TEAM_NAMES.get(team, team)} ({team})"


def player_label(
    runtime: RuntimeData,
    player_id: str,
) -> str:
    trade = runtime.trade_by_id.get(player_id, {})

    name = str(
        trade.get("player_name", player_id)
    ).strip()

    salary = money(
        trade.get("trade_salary_2026_27")
    )

    return f"{name} | {salary}"


def pick_label(runtime: RuntimeData, pick_right_id: str) -> str:
    record = runtime.pick_by_id.get(pick_right_id, {})
    display_name = str(
        record.get("right_display_name", pick_right_id)
    ).strip()
    value = safe_float(record.get("candidate_right_value_score"))

    value_text = f" | Value {value:.1f}" if value is not None else ""
    return f"{display_name}{value_text}"


def team_players(runtime: RuntimeData, team: str) -> list[str]:
    frame = runtime.trade_pool.loc[
        runtime.trade_pool["current_team_2026_27"].eq(team)
    ].copy()

    if frame.empty:
        return []

    frame["__market_value"] = frame["player_id"].map(
        lambda player_id: safe_float(
            runtime.market_by_id.get(str(player_id), {}).get(
                "market_value_score_v2"
            )
        )
        or -1.0
    )
    frame["__salary"] = pd.to_numeric(
        frame["trade_salary_2026_27"],
        errors="coerce",
    ).fillna(-1.0)

    frame = frame.sort_values(
        ["__market_value", "__salary", "player_name"],
        ascending=[False, False, True],
    )

    return frame["player_id"].astype(str).tolist()


def team_picks(runtime: RuntimeData, team: str) -> list[str]:
    frame = runtime.picks.loc[
        runtime.picks["candidate_team"].eq(team)
    ].copy()

    if frame.empty:
        return []

    if "standalone_trade_asset_flag" in frame.columns:
        standalone = (
            frame["standalone_trade_asset_flag"]
            .astype(str)
            .str.strip()
            .str.lower()
            .isin({"true", "1", "yes"})
        )
        frame = frame.loc[standalone]

    if frame.empty:
        return []

    frame["__year"] = pd.to_numeric(
        frame.get("draft_year_min"),
        errors="coerce",
    ).fillna(9999)
    frame["__value"] = pd.to_numeric(
        frame.get("candidate_right_value_score"),
        errors="coerce",
    ).fillna(-1.0)

    frame = frame.sort_values(
        ["__year", "__value", "right_display_name"],
        ascending=[True, False, True],
    )

    return frame["future_pick_right_id"].astype(str).tolist()


def render_status_banner(status: Status, title: str) -> None:
    color = STATUS_COLORS[status]
    icon = STATUS_ICONS[status]
    label = STATUS_LABELS[status]

    st.markdown(
        f"""
        <div style="
            border: 1px solid {color};
            border-left: 8px solid {color};
            border-radius: 12px;
            padding: 16px 18px;
            margin: 4px 0 18px 0;
            background: color-mix(in srgb, {color} 10%, transparent);
        ">
            <div style="font-size: 0.85rem; font-weight: 700; letter-spacing: 0.08em;">
                {icon} {label}
            </div>
            <div style="font-size: 1.35rem; font-weight: 750; margin-top: 3px;">
                {title}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_check(check: CheckResult) -> None:
    prefix = STATUS_ICONS[check.status]
    code = check.code.replace("_", " ").title()
    body = f"**{prefix} {code}:** {check.message}"

    if check.status == Status.BLOCKED:
        st.error(body)
    elif check.status == Status.MANUAL_REVIEW:
        st.warning(body)
    else:
        st.success(body)


def selected_player_rows(
    runtime: RuntimeData,
    player_ids: list[str],
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []

    for player_id in player_ids:
        trade = runtime.trade_by_id.get(player_id, {})
        rating = runtime.ratings_by_id.get(player_id, {})
        market = runtime.market_by_id.get(player_id, {})
        decision = runtime.player_cba_by_id.get(player_id, {})

        rows.append(
            {
                "Player": trade.get("player_name", player_id),
                "Salary": money(trade.get("trade_salary_2026_27")),
                "OVR": rating_text(rating.get("overall_rating")),
                "POT": rating_text(rating.get("potential_rating")),
                "Asset class": market.get(
                    "recommendation_asset_class_v3",
                    "Unclassified",
                ),
                "CBA evidence": decision.get(
                    "player_cba_evidence_determination",
                    "not covered",
                ),
            }
        )

    return pd.DataFrame(rows)


def selected_pick_rows(
    runtime: RuntimeData,
    pick_right_ids: list[str],
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []

    for pick_right_id in pick_right_ids:
        record = runtime.pick_by_id.get(pick_right_id, {})
        rows.append(
            {
                "Draft right": record.get(
                    "right_display_name",
                    pick_right_id,
                ),
                "Years": (
                    f"{record.get('draft_year_min', '')}"
                    if record.get("draft_year_min")
                    == record.get("draft_year_max")
                    else (
                        f"{record.get('draft_year_min', '')}-"
                        f"{record.get('draft_year_max', '')}"
                    )
                ),
                "Round": record.get("round_numbers", ""),
                "Value": record.get(
                    "candidate_right_value_score",
                    "",
                ),
                "Structure": record.get("right_structure", ""),
            }
        )

    return pd.DataFrame(rows)


def render_side_summary(
    runtime: RuntimeData,
    side_name: str,
    team: str,
    player_ids: list[str],
    pick_right_ids: list[str],
    outgoing_salary: float,
    status: Status,
) -> None:
    st.subheader(f"{side_name}: {team_label(team)}")

    metric_columns = st.columns(
        [1.0, 1.0, 1.35]
    )

    metric_columns[0].metric(
        "Players sent",
        len(player_ids),
    )

    metric_columns[1].metric(
        "Draft rights sent",
        len(pick_right_ids),
    )

    metric_columns[2].metric(
        "Outgoing salary",
        money(outgoing_salary),
    )

    color = STATUS_COLORS[status]
    icon = STATUS_ICONS[status]
    label = STATUS_LABELS[status]

    st.markdown(
        f"""
        <div style="
            display: flex;
            align-items: center;
            justify-content: space-between;
            border: 1px solid {color};
            border-left: 6px solid {color};
            border-radius: 10px;
            padding: 10px 14px;
            margin: 8px 0 14px 0;
        ">
            <span style="
                color: #9ca3af;
                font-size: 0.82rem;
                font-weight: 650;
            ">
                Side result
            </span>
            <span style="
                color: {color};
                font-weight: 800;
                letter-spacing: 0.04em;
            ">
                {icon} {label}
            </span>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if player_ids:
        st.markdown("**Outgoing players**")
        st.dataframe(
            selected_player_rows(
                runtime,
                player_ids,
            ),
            hide_index=True,
            width="stretch",
        )

    if pick_right_ids:
        st.markdown("**Outgoing draft rights**")
        st.dataframe(
            selected_pick_rows(
                runtime,
                pick_right_ids,
            ),
            hide_index=True,
            width="stretch",
        )


runtime = get_runtime()
teams = sorted(runtime.team_salary_by_team)

st.title("Freeform Two-Team Trade Machine")
st.caption(
    "Construct a custom player-and-pick trade using the validated 2026-27 "
    "runtime data. V2.2 evaluates roster identity, player restrictions, verified "
    "team salary, salary-matching routes, aggregation, roster limits, and "
    "hard-cap rules. Complete draft-right validation remains conservative."
)

with st.expander("What each result means", expanded=False):
    st.markdown(
        """
        **PASS** means the currently connected evidence stage found no issue.
        **BLOCKED** means a deterministic rule failed, such as roster ownership,
        trade eligibility, or an active aggregation restriction.
        **MANUAL REVIEW** means the trade may still be workable, but it contains
        unresolved player consent, contract mechanics, team evidence, or draft-right rules.
        """
    )

team_columns = st.columns(2)

with team_columns[0]:
    team_a = st.selectbox(
        "Team A",
        teams,
        index=teams.index("CHI") if "CHI" in teams else 0,
        format_func=team_label,
        key="trade_machine_team_a",
    )

with team_columns[1]:
    default_b = "DET" if "DET" in teams else teams[1]
    team_b = st.selectbox(
        "Team B",
        teams,
        index=teams.index(default_b),
        format_func=team_label,
        key="trade_machine_team_b",
    )

if team_a == team_b:
    st.error("Choose two different teams before evaluating the trade.")

side_columns = st.columns(2, gap="large")

with side_columns[0]:
    st.markdown(f"### {team_label(team_a)} sends")
    team_a_player_options = team_players(runtime, team_a)
    team_a_pick_options = team_picks(runtime, team_a)

    team_a_players = st.multiselect(
        "Players from Team A",
        team_a_player_options,
        format_func=lambda player_id: player_label(
            runtime,
            player_id,
        ),
        key=f"trade_machine_players_{team_a}",
    )

    team_a_picks = st.multiselect(
        "Draft rights from Team A",
        team_a_pick_options,
        format_func=lambda pick_id: pick_label(runtime, pick_id),
        key=f"trade_machine_picks_{team_a}",
    )

with side_columns[1]:
    st.markdown(f"### {team_label(team_b)} sends")
    team_b_player_options = team_players(runtime, team_b)
    team_b_pick_options = team_picks(runtime, team_b)

    team_b_players = st.multiselect(
        "Players from Team B",
        team_b_player_options,
        format_func=lambda player_id: player_label(
            runtime,
            player_id,
        ),
        key=f"trade_machine_players_{team_b}",
    )

    team_b_picks = st.multiselect(
        "Draft rights from Team B",
        team_b_pick_options,
        format_func=lambda pick_id: pick_label(runtime, pick_id),
        key=f"trade_machine_picks_{team_b}",
    )

st.divider()

evaluate_clicked = st.button(
    "Evaluate trade",
    type="primary",
    width="stretch",
)

if evaluate_clicked:
    side_a_has_assets = bool(team_a_players or team_a_picks)
    side_b_has_assets = bool(team_b_players or team_b_picks)

    if team_a == team_b:
        st.error("The two sides must use different teams.")
    elif not side_a_has_assets or not side_b_has_assets:
        st.error(
            "Each team must send at least one player or draft right."
        )
    else:
        request = TradeRequest(
            side_a=TradeSideRequest(
                team_abbreviation=team_a,
                player_ids=tuple(team_a_players),
                pick_right_ids=tuple(team_a_picks),
            ),
            side_b=TradeSideRequest(
                team_abbreviation=team_b,
                player_ids=tuple(team_b_players),
                pick_right_ids=tuple(team_b_picks),
            ),
        )

        result = evaluate_trade(runtime, request)

        st.session_state["trade_machine_last_result"] = result
        st.session_state["trade_machine_last_selection"] = {
            "team_a": team_a,
            "team_b": team_b,
            "team_a_players": team_a_players,
            "team_b_players": team_b_players,
            "team_a_picks": team_a_picks,
            "team_b_picks": team_b_picks,
        }

result = st.session_state.get("trade_machine_last_result")
selection = st.session_state.get("trade_machine_last_selection")

if result is not None and selection is not None:
    st.divider()
    render_status_banner(
        result.status,
        "Overall transaction result",
    )

    summary_columns = st.columns(2, gap="large")

    with summary_columns[0]:
        render_side_summary(
            runtime=runtime,
            side_name="Team A",
            team=selection["team_a"],
            player_ids=selection["team_a_players"],
            pick_right_ids=selection["team_a_picks"],
            outgoing_salary=result.side_a.outgoing_salary,
            status=result.side_a.status,
        )

    with summary_columns[1]:
        render_side_summary(
            runtime=runtime,
            side_name="Team B",
            team=selection["team_b"],
            player_ids=selection["team_b_players"],
            pick_right_ids=selection["team_b_picks"],
            outgoing_salary=result.side_b.outgoing_salary,
            status=result.side_b.status,
        )

    st.subheader("Legality checks")

    if result.checks:
        st.markdown("**Transaction-wide checks**")
        for check in result.checks:
            render_check(check)

    check_columns = st.columns(2, gap="large")

    with check_columns[0]:
        st.markdown(f"**{selection['team_a']} checks**")
        for check in result.side_a.checks:
            render_check(check)

    with check_columns[1]:
        st.markdown(f"**{selection['team_b']} checks**")
        for check in result.side_b.checks:
            render_check(check)

    with st.expander("Remaining limitations", expanded=True):
        st.markdown(
            """
            - Salary matching, aggregation, roster limits, and hard-cap results now
              use the verified team-CBA evidence and validated V9 formulas.
            - Draft rights are checked for canonical existence, assigned team,
              and standalone-asset status. Trade-date ownership, encumbrance,
              and the complete package-level Stepien result remain pending.
            - A manual-review result is intentionally conservative and should
              not be interpreted as an illegal trade.
            """
        )
