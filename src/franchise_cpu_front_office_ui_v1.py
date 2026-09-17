from __future__ import annotations

from typing import Any, Iterable

import pandas as pd
import streamlit as st

from franchise_cpu_front_office_v1 import (
    CPU_FRONT_OFFICE_MODEL_VERSION,
    CPU_FRONT_OFFICE_VERSION,
    TIMELINE_LABELS,
    build_league_front_office_plan,
    team_plan_rows,
)


CPU_FRONT_OFFICE_UI_VERSION = "franchise-cpu-front-office-ui-v1.6.2-2026-08-13"


def _salary_label(value: float) -> str:
    if value <= 0.0:
        return "Unknown / $0"
    return f"${value / 1_000_000:.1f}M"


def _years_label(value: int | None) -> str:
    return "Unknown" if value is None else str(value)


def _timeline_count(plan: Any, key: str) -> int:
    return int(getattr(plan, "timeline_counts", {}).get(key, 0) or 0)


def _decision_frame(team_plan: Any) -> pd.DataFrame:
    rows = []
    for row in team_plan.player_decisions:
        rows.append(
            {
                "Player": row.player_name,
                "Pos": row.position,
                "Age": row.age,
                "OVR": row.overall,
                "POT": row.potential,
                "Salary": _salary_label(row.salary),
                "Control yrs": _years_label(row.years_remaining),
                "Role": row.role,
                "Retention": row.retention_score,
                "Contract plan": row.contract_plan,
                "Market stance": row.market_stance,
                "Asset policy": row.asset_policy,
                "Roster fit": row.roster_fit,
                "Asset tier": row.asset_tier,
                "Market score": row.market_value_score,
                "Org score": row.organizational_value_score,
                "Trade value": row.trade_value_score,
                "Market pct": row.market_percentile,
                "Control": row.contract_control_score,
                "Availability": row.availability_score,
                "Premium market": "Yes" if row.premium_market else "No",
                "Family depth": row.family_depth_rank,
                "Priority": row.decision_priority,
                "Strategic value": row.strategic_value,
                "Why": " · ".join(row.rationale),
            }
        )
    return pd.DataFrame(rows)



def _trade_package_frame(team_plan: Any) -> pd.DataFrame:
    rows = []
    for intent in team_plan.trade_package_intents:
        players = " + ".join(intent.outgoing_player_names)
        rows.append(
            {
                "Priority": intent.priority,
                "Intent": intent.intent_type,
                "Outgoing": players,
                "Salary out": _salary_label(intent.outgoing_salary),
                "Value out": intent.outgoing_value,
                "Peak asset": intent.outgoing_peak_asset_tier,
                "Target": intent.target_family,
                "Desired return": intent.return_profile,
                "Required 1st-eq": intent.required_first_equivalent_return,
                "Blue-chip req.": "Yes" if intent.requires_blue_chip_return else "No",
                "1st budget": intent.draft_first_budget,
                "2nd budget": intent.draft_second_budget,
                "Swap": "Yes" if intent.allow_pick_swap else "No",
                "Why": " · ".join(intent.rationale),
            }
        )
    return pd.DataFrame(rows)


def _free_agent_frame(team_plan: Any) -> pd.DataFrame:
    rows = []
    for row in team_plan.free_agent_targets:
        rows.append(
            {
                "Player": row.player_name,
                "Pos": row.position,
                "Age": row.age,
                "OVR": row.overall,
                "POT": row.potential,
                "Salary reference": _salary_label(row.salary_reference),
                "Target lane": row.target_lane,
                "Target tier": row.target_tier,
                "Fit score": row.fit_score,
                "Why": " · ".join(row.rationale),
            }
        )
    return pd.DataFrame(rows)


def render_cpu_front_office_v1(
    state: Any,
    *,
    active_team: str,
    controlled_teams: Iterable[str] = (),
) -> None:
    controlled = tuple(sorted({str(value).strip().upper() for value in controlled_teams if str(value).strip()}))

    st.markdown("## CPU Front Office Intelligence · V1.6.2")
    st.caption(
        "V1.6 calibrates asset tiers using one shared market-value context. "
        "Current impact now competes with age curve, upside, contract control, "
        "salary efficiency and availability, while league-relative tiering keeps "
        "Franchise status genuinely scarce. The same context is ready for Trade Finder."
    )

    try:
        league_plan = build_league_front_office_plan(
            state,
            controlled_teams=controlled,
        )
    except Exception as exc:
        st.error(f"CPU Front Office could not build the league plan: {exc}")
        return

    top = st.columns(6)
    top[0].metric("CPU teams", league_plan.cpu_team_count)
    top[1].metric(
        "Title pushes",
        _timeline_count(league_plan, "championship_push"),
    )
    top[2].metric(
        "Contenders",
        _timeline_count(league_plan, "contender"),
    )
    top[3].metric(
        "Retool",
        _timeline_count(league_plan, "retool"),
    )
    top[4].metric(
        "Develop / rebuild",
        _timeline_count(league_plan, "develop")
        + _timeline_count(league_plan, "rebuild"),
    )
    top[5].metric(
        "Roster pressure",
        len(league_plan.roster_pressure_teams),
    )

    st.caption(
        f"{league_plan.contract_decision_count} contract/retention decision(s) "
        f"identified across the league · {league_plan.shop_candidate_count} player(s) "
        f"flagged for a shop/listen posture · {league_plan.trade_intent_count} package "
        "intent(s) generated · controlled teams are never labeled CPU-managed."
    )

    team_options = sorted(league_plan.teams)
    default_team = str(active_team).strip().upper()
    default_index = team_options.index(default_team) if default_team in team_options else 0
    selected_team = st.selectbox(
        "Front office to inspect",
        options=team_options,
        index=default_index,
        key="franchise_cpu_front_office_team_v1",
    )
    team_plan = league_plan.teams[selected_team]

    # Two wider rows prevent long front-office labels/values from being
    # ellipsized by Streamlit's native metric card at desktop widths.
    identity_top = st.columns(4)
    identity_top[0].metric("Direction", team_plan.timeline_label)
    identity_top[1].metric("League rank", f"#{team_plan.league_rank}")
    identity_top[2].metric(
        "Roster balance",
        f"{team_plan.roster_balance_score:.0f}/100",
    )
    identity_top[3].metric("Roster", team_plan.roster_count)

    identity_needs = st.columns(3)
    identity_needs[0].metric(
        "Primary upgrade need",
        team_plan.primary_upgrade_need,
    )
    identity_needs[1].metric(
        "Secondary upgrade",
        team_plan.secondary_upgrade_need,
    )
    identity_needs[2].metric(
        "Depth surplus",
        team_plan.depth_surplus_family,
    )

    st.markdown(
        f"**Control:** {'CPU managed' if team_plan.cpu_managed else 'User controlled'}  \n"
        f"**Financial posture:** {team_plan.financial_posture}  \n"
        f"**Draft posture:** {team_plan.draft_posture}  \n"
        f"**Trade-search policy:** `{team_plan.trade_goal}`"
    )

    st.markdown(
        f"**Behavior:** {team_plan.behavior_label}  \n"
        f"**Free-agent strategy:** {team_plan.free_agent_strategy}"
    )
    st.caption(team_plan.behavior_summary)

    strategy = st.columns(5)
    strategy[0].metric("Win-now", f"{team_plan.win_now_bias:.0f}/100")
    strategy[1].metric("Youth", f"{team_plan.youth_bias:.0f}/100")
    strategy[2].metric(
        "Future assets",
        f"{team_plan.future_asset_bias:.0f}/100",
    )
    strategy[3].metric(
        "Consolidation",
        f"{team_plan.consolidation_bias:.0f}/100",
    )
    strategy[4].metric(
        "Salary discipline",
        f"{team_plan.salary_discipline:.0f}/100",
    )

    st.markdown("### Roster construction")
    construction_rows = []
    for family in ("Guard", "Wing/Forward", "Center"):
        profile = team_plan.position_profiles[family]
        construction_rows.append(
            {
                "Family": family,
                "Players": int(profile["count"]),
                "Target depth": int(profile["target_count"]),
                "Top OVR": float(profile["top_overall"]),
                "Second OVR": float(profile["second_overall"]),
                "Rotation players": int(profile["rotation_count"]),
                "Young upside": int(profile["young_upside_count"]),
                "Starter need": float(profile["starter_need_score"]),
                "Depth need": float(profile["depth_need_score"]),
                "Overall need": float(team_plan.need_scores[family]),
                "Depth surplus": float(team_plan.surplus_scores[family]),
            }
        )
    st.dataframe(
        pd.DataFrame(construction_rows),
        hide_index=True,
        width="stretch",
        column_config={
            "Starter need": st.column_config.ProgressColumn(
                "Starter need",
                min_value=0.0,
                max_value=max(
                    20.0,
                    max(
                        float(team_plan.position_profiles[family]["starter_need_score"])
                        for family in ("Guard", "Wing/Forward", "Center")
                    ) + 2.0,
                ),
                format="%.1f",
            ),
            "Overall need": st.column_config.ProgressColumn(
                "Overall need",
                min_value=0.0,
                max_value=max(
                    20.0,
                    max(team_plan.need_scores.values()) + 2.0,
                ),
                format="%.1f",
            ),
            "Depth surplus": st.column_config.ProgressColumn(
                "Depth surplus",
                min_value=0.0,
                max_value=max(
                    12.0,
                    max(team_plan.surplus_scores.values()) + 2.0,
                ),
                format="%.1f",
            ),
        },
    )
    st.caption(
        "Starter need measures top-end quality. Depth need measures roster/rotation "
        "coverage. Depth surplus measures extra playable bodies. A position can therefore "
        "need a better starter while still having surplus depth."
    )

    if team_plan.risk_flags:
        st.warning(" · ".join(team_plan.risk_flags))

    with st.expander("Why this direction?", expanded=False):
        st.metric(
            "Competitive score",
            f"{team_plan.competitive_score:.1f}",
        )
        for reason in team_plan.direction_rationale:
            st.markdown(f"- {reason}")

    st.markdown("### Organizational priorities")
    for index, objective in enumerate(team_plan.objectives, start=1):
        st.markdown(f"**{index}.** {objective}")

    st.markdown("### Roster decision board")
    decisions = _decision_frame(team_plan)
    if decisions.empty:
        st.info("No rostered players were available for this team plan.")
    else:
        st.dataframe(
            decisions,
            hide_index=True,
            width="stretch",
            column_config={
                "Retention": st.column_config.ProgressColumn(
                    "Retention",
                    min_value=0.0,
                    max_value=100.0,
                    format="%.1f",
                ),
                "Priority": st.column_config.ProgressColumn(
                    "Priority",
                    min_value=0.0,
                    max_value=100.0,
                    format="%.1f",
                ),
                "Market score": st.column_config.ProgressColumn(
                    "Market score",
                    min_value=0.0,
                    max_value=100.0,
                    format="%.1f",
                ),
                "Org score": st.column_config.ProgressColumn(
                    "Org score",
                    min_value=0.0,
                    max_value=100.0,
                    format="%.1f",
                ),
                "Trade value": st.column_config.ProgressColumn(
                    "Trade value",
                    min_value=0.0,
                    max_value=185.0,
                    format="%.1f",
                ),
                "Market pct": st.column_config.NumberColumn(
                    "Market pct",
                    format="%.1f",
                ),
                "Control": st.column_config.ProgressColumn(
                    "Control",
                    min_value=0.0,
                    max_value=100.0,
                    format="%.1f",
                ),
                "Availability": st.column_config.ProgressColumn(
                    "Availability",
                    min_value=0.0,
                    max_value=100.0,
                    format="%.1f",
                ),
                "Strategic value": st.column_config.NumberColumn(
                    "Strategic value",
                    format="%.1f",
                ),
            },
        )

    st.markdown("### Trade package intent board")
    package_meta = st.columns(4)
    package_meta[0].metric(
        "Tradeable pool",
        len(team_plan.tradeable_player_pool_ids),
    )
    package_meta[1].metric(
        "Consolidation candidates",
        len(team_plan.consolidation_candidate_ids),
    )
    package_meta[2].metric(
        "1st-round budget",
        team_plan.draft_first_budget,
    )
    package_meta[3].metric(
        "2nd-round budget",
        team_plan.draft_second_budget,
    )
    st.caption(
        f"Desired return: {team_plan.desired_return_profile}. "
        f"Pick-swap willingness: {'yes' if team_plan.allow_pick_swap else 'no'}. "
        "Draft budgets are willingness ceilings, not claims that specific picks are available."
    )

    packages = _trade_package_frame(team_plan)
    if packages.empty:
        st.info(
            "No current roster combination cleared this front office's package-intent rules."
        )
    else:
        st.dataframe(
            packages,
            hide_index=True,
            width="stretch",
            column_config={
                "Priority": st.column_config.ProgressColumn(
                    "Priority",
                    min_value=0.0,
                    max_value=100.0,
                    format="%.1f",
                ),
                "Value out": st.column_config.NumberColumn(
                    "Value out",
                    format="%.1f",
                ),
            },
        )

    st.caption(
        "Package intents are not executable trades. The later CPU trade layer must "
        "resolve actual counterparties, live salaries, owned draft rights, Stepien "
        "constraints, full CBA legality and acceptance before any commit."
    )

    st.markdown("### Free-agent target board")
    st.caption(
        "Targets are recommendations only. V1 does not create contracts or move players. "
        "The next contract/free-agency layer will execute against this same front-office plan."
    )
    fa = _free_agent_frame(team_plan)
    if fa.empty:
        st.info("No current free agent cleared this front office's minimum fit threshold.")
    else:
        st.dataframe(
            fa,
            hide_index=True,
            width="stretch",
            column_config={
                "Fit score": st.column_config.ProgressColumn(
                    "Fit score",
                    min_value=0.0,
                    max_value=100.0,
                    format="%.1f",
                ),
            },
        )

    with st.expander("League-wide front office board", expanded=False):
        league_rows = pd.DataFrame(team_plan_rows(league_plan))
        st.dataframe(league_rows, hide_index=True, width="stretch")
        st.caption(
            f"Engine {CPU_FRONT_OFFICE_VERSION} · model {CPU_FRONT_OFFICE_MODEL_VERSION} · "
            f"UI {CPU_FRONT_OFFICE_UI_VERSION}"
        )
