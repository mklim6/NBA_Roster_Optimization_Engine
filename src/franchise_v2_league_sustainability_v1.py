from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import streamlit as st


FRANCHISE_V2_SUSTAINABILITY_VERSION = (
    "franchise-v2-league-sustainability-v1-2026-09-23"
)
TARGET_ROSTER_MIN = 14
TARGET_ROSTER_MAX = 15


@dataclass(frozen=True)
class LeagueSustainabilitySnapshot:
    team_count: int
    rostered_players: int
    free_agent_count: int
    total_player_count: int
    average_roster_size: float
    minimum_roster_size: int
    maximum_roster_size: int
    teams_below_target: int
    teams_in_target: int
    teams_above_target: int
    free_agent_share: float
    status: str
    team_rows: tuple[dict[str, Any], ...]


def build_league_sustainability_snapshot(
    state: Any,
    *,
    target_min: int = TARGET_ROSTER_MIN,
    target_max: int = TARGET_ROSTER_MAX,
) -> LeagueSustainabilitySnapshot:
    if target_min < 1 or target_max < target_min:
        raise ValueError("Roster sustainability targets are invalid.")

    rows: list[dict[str, Any]] = []
    for team, team_state in sorted(
        (getattr(state, "teams", {}) or {}).items(),
        key=lambda item: str(item[0]),
    ):
        count = len(tuple(getattr(team_state, "roster_player_ids", ()) or ()))
        if count < target_min:
            roster_status = "Below target"
        elif count > target_max:
            roster_status = "Above target"
        else:
            roster_status = "On target"
        rows.append(
            {
                "Team": str(team),
                "Roster": count,
                "Target": f"{target_min}-{target_max}",
                "Players needed": max(0, target_min - count),
                "Status": roster_status,
            }
        )

    counts = [int(row["Roster"]) for row in rows]
    rostered = sum(counts)
    free_agents = len(tuple(getattr(state, "free_agent_player_ids", ()) or ()))
    total_players = rostered + free_agents
    below = sum(count < target_min for count in counts)
    in_target = sum(target_min <= count <= target_max for count in counts)
    above = sum(count > target_max for count in counts)
    average = (rostered / len(counts)) if counts else 0.0
    free_agent_share = (free_agents / total_players) if total_players else 0.0

    if counts and below == 0 and above == 0:
        status = "healthy"
    elif counts and average >= target_min - 1 and below <= max(3, len(counts) // 6):
        status = "watch"
    else:
        status = "needs_attention"

    return LeagueSustainabilitySnapshot(
        team_count=len(rows),
        rostered_players=rostered,
        free_agent_count=free_agents,
        total_player_count=total_players,
        average_roster_size=round(average, 2),
        minimum_roster_size=min(counts) if counts else 0,
        maximum_roster_size=max(counts) if counts else 0,
        teams_below_target=below,
        teams_in_target=in_target,
        teams_above_target=above,
        free_agent_share=round(free_agent_share, 4),
        status=status,
        team_rows=tuple(rows),
    )


def render_league_sustainability_v1(state: Any) -> LeagueSustainabilitySnapshot:
    snapshot = build_league_sustainability_snapshot(state)

    with st.container(border=True):
        heading, badge_column = st.columns([4, 1], vertical_alignment="center")
        heading.subheader("League roster sustainability")
        badge = {
            "healthy": ("Healthy", "green", ":material/check_circle:"),
            "watch": ("Watch", "orange", ":material/visibility:"),
            "needs_attention": (
                "V2 priority",
                "red",
                ":material/build_circle:",
            ),
        }[snapshot.status]
        badge_column.badge(badge[0], color=badge[1], icon=badge[2])

        st.caption(
            "V2 monitors the long-term player economy against a 14-15 player "
            "organizational target. This panel is diagnostic and never signs, "
            "waives, or moves a player."
        )

        metrics = st.columns(4)
        metrics[0].metric(
            "Average roster",
            f"{snapshot.average_roster_size:.1f}",
            delta=f"Target {TARGET_ROSTER_MIN}-{TARGET_ROSTER_MAX}",
            delta_color="off",
        )
        metrics[1].metric(
            "Teams below target",
            snapshot.teams_below_target,
            delta=f"{snapshot.teams_in_target} on target",
            delta_color=("normal" if snapshot.teams_below_target == 0 else "inverse"),
        )
        metrics[2].metric(
            "Free-agent pool",
            snapshot.free_agent_count,
            delta=f"{snapshot.free_agent_share:.0%} of players",
            delta_color="off",
        )
        metrics[3].metric(
            "Roster range",
            f"{snapshot.minimum_roster_size}-{snapshot.maximum_roster_size}",
            delta=f"{snapshot.rostered_players} rostered",
            delta_color="off",
        )

        target_progress = min(
            100,
            round(100 * snapshot.average_roster_size / TARGET_ROSTER_MIN),
        )
        st.progress(
            target_progress,
            text=(
                f"League average: {snapshot.average_roster_size:.1f} of "
                f"{TARGET_ROSTER_MIN} players at the lower V2 target"
            ),
        )

        if snapshot.status == "healthy":
            st.success(
                "Every organization is inside the V2 roster target.",
                icon=":material/check_circle:",
            )
        elif snapshot.status == "watch":
            st.warning(
                "The league is close to the V2 target, but a small number of "
                "organizations still need sustainable depth.",
                icon=":material/monitoring:",
            )
        else:
            st.warning(
                f"{snapshot.teams_below_target} organizations are below the "
                f"{TARGET_ROSTER_MIN}-player V2 target. They may still satisfy "
                "the existing game-ready floor; V2 will improve this without "
                "weakening contract, acceptance, or roster validation.",
                icon=":material/build:",
            )

        with st.expander(
            "Team-by-team roster detail",
            icon=":material/groups:",
        ):
            st.dataframe(
                list(snapshot.team_rows),
                hide_index=True,
                width="stretch",
                column_config={
                    "Team": st.column_config.TextColumn(width="small"),
                    "Roster": st.column_config.NumberColumn(format="%d"),
                    "Players needed": st.column_config.NumberColumn(format="%d"),
                },
            )

    return snapshot

