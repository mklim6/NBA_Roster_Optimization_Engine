"""Streamlit page for the finalized mixed player-and-pick recommendation release.

Place this file in the project's ``pages`` directory, for example:

    pages/2_Mixed_Trade_Recommendations.py

The page reads:

    app_data/mixed_player_pick_release_2026_27_v1.json
    app_data/mixed_player_pick_methodology_2026_27_v1.json

It does not recalculate trades. It only renders the validated app data contract.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import sys
from pathlib import Path
from typing import Any


BUNDLE_FILENAME = "mixed_player_pick_release_2026_27_v1.json"
METHODOLOGY_FILENAME = "mixed_player_pick_methodology_2026_27_v1.json"

TEAM_NAMES = {
    "ATL": "Atlanta Hawks",
    "BKN": "Brooklyn Nets",
    "BOS": "Boston Celtics",
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

DISPLAY_TIER_RENAMES = {
    "Model-backed recommendation": "Model-backed trade concept",
}

TIER_BADGE_CLASS = {
    "Model-backed trade concept": "tier-production",
    "Exploratory strategy shortlist": "tier-shortlist",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Validate the page helpers and data contract without Streamlit.",
    )
    parser.add_argument(
        "--bundle-path",
        type=Path,
        default=None,
        help="Optional JSON bundle used by --self-test.",
    )
    return parser.parse_args()


def candidate_project_roots() -> list[Path]:
    current_file = Path(__file__).resolve()
    candidates: list[Path] = []

    configured_root = os.environ.get("NBA_ROSTER_OPTIMIZER_ROOT")
    if configured_root:
        candidates.append(Path(configured_root).expanduser().resolve())

    # When this file is inside PROJECT_ROOT/pages.
    if current_file.parent.name.lower() == "pages":
        candidates.append(current_file.parent.parent)

    # When this file is placed directly at the project root.
    candidates.append(current_file.parent)

    # When Streamlit is launched from the project root.
    candidates.append(Path.cwd().resolve())

    # Keep order while removing duplicates.
    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate)
        if key not in seen:
            seen.add(key)
            unique.append(candidate)
    return unique


def locate_app_file(filename: str) -> Path:
    checked: list[Path] = []

    for root in candidate_project_roots():
        for path in [
            root / "app_data" / filename,
            root / filename,
        ]:
            checked.append(path)
            if path.exists():
                return path

    checked_text = "\n".join(str(path) for path in checked)
    raise FileNotFoundError(
        f"Could not locate {filename}. Checked:\n{checked_text}"
    )


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file:
        value = json.load(file)

    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object in {path}.")
    return value


def normalized_display_tier(value: Any) -> str:
    text = "" if value is None else str(value).strip()
    return DISPLAY_TIER_RENAMES.get(text, text)


def team_sort_key(team: str) -> tuple[str, str]:
    return TEAM_NAMES.get(team, team), team


def build_team_options(bundle: dict[str, Any]) -> list[str]:
    status_by_team = bundle.get("team_status_by_team", {})
    if not isinstance(status_by_team, dict):
        raise ValueError("team_status_by_team must be a JSON object.")

    teams = sorted(status_by_team, key=team_sort_key)
    if len(teams) != 30:
        raise ValueError(
            f"Expected 30 teams in team_status_by_team, found {len(teams)}."
        )
    return teams


def recommendations_for_team(
    bundle: dict[str, Any],
    team: str,
) -> list[dict[str, Any]]:
    by_team = bundle.get("recommendations_by_team", {})
    rows = by_team.get(team, []) if isinstance(by_team, dict) else []

    if not isinstance(rows, list):
        raise ValueError(
            f"Recommendations for {team} must be a list."
        )

    normalized_rows: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError(
                f"Recommendation row for {team} is not an object."
            )
        normalized = dict(row)
        normalized["display_tier"] = normalized_display_tier(
            normalized.get("display_tier")
        )
        normalized_rows.append(normalized)

    return sorted(
        normalized_rows,
        key=lambda row: (
            int(row.get("display_sort_tier", 999)),
            int(row.get("app_display_rank_for_team", 999)),
            str(row.get("optimizer_candidate_id", "")),
        ),
    )


def status_for_team(
    bundle: dict[str, Any],
    team: str,
) -> dict[str, Any]:
    status_by_team = bundle.get("team_status_by_team", {})
    if not isinstance(status_by_team, dict):
        raise ValueError("team_status_by_team must be a JSON object.")

    status = status_by_team.get(team)
    if not isinstance(status, dict):
        raise KeyError(f"Missing team status for {team}.")
    return status


def safe_score(value: Any) -> str:
    try:
        return f"{float(value):.1f}"
    except (TypeError, ValueError):
        return "N/A"


def escaped(value: Any) -> str:
    return html.escape("" if value is None else str(value))


def render_score_help(st: Any) -> None:
    with st.expander("How to read the scores"):
        st.markdown(
            """
- **Team strategy score:** How well the concept fits the selected team's modeled direction.
- **Bilateral floor:** The lower of the two team strategy scores. Higher values indicate a more balanced concept.
- **Roster fit:** Basketball fit relative to the modeled team needs.
- **Asset utility:** Value retained or gained by the selected team.
- **Contribution utility:** Expected on-court contribution retained or gained.
- **Downside utility:** Protection against a poor outcome.

These scores rank model-generated concepts. They do not indicate that a player or team is actually available.
"""
        )


def render_status_panel(
    st: Any,
    team: str,
    status: dict[str, Any],
) -> None:
    full_name = TEAM_NAMES.get(team, team)
    archetype = status.get(
        "team_strategy_archetype_label",
        "Team profile unavailable",
    )
    priority = status.get(
        "model_team_strategy_priority",
        "",
    )
    needs = [
        status.get("top_need_1"),
        status.get("top_need_2"),
        status.get("top_need_3"),
    ]
    needs = [str(value) for value in needs if value]

    with st.container(border=True):
        left, middle, right = st.columns([1.4, 1.2, 1.0])
        with left:
            st.markdown(f"### {full_name}")
            st.caption(f"{team} | {archetype}")
        with middle:
            st.markdown("**Modeled priority**")
            st.write(priority or "Priority description unavailable.")
        with right:
            st.markdown("**Top roster needs**")
            st.write(", ".join(needs) if needs else "Not available")

        st.caption(
            status.get(
                "availability_disclaimer",
                "Model-generated concepts do not imply real-world availability.",
            )
        )


def render_empty_state(
    st: Any,
    status: dict[str, Any],
) -> None:
    status_label = status.get(
        "app_status_label",
        "No display-ready concept",
    )
    message = status.get(
        "empty_state_message",
        "No recommendation is available for this team.",
    )

    st.info(f"**{status_label}**\n\n{message}")

    with st.expander("Why no recommendation is shown"):
        legal_rows = int(
            status.get("deterministic_legal_perspective_rows", 0) or 0
        )
        routine_variants = int(
            status.get("routine_package_variants", 0) or 0
        )
        concepts = int(
            status.get("unique_canonical_concepts", 0) or 0
        )

        metric_columns = st.columns(3)
        metric_columns[0].metric(
            "Legal perspective rows",
            f"{legal_rows:,}",
        )
        metric_columns[1].metric(
            "Strategy-ready variants",
            f"{routine_variants:,}",
        )
        metric_columns[2].metric(
            "Canonical concepts",
            f"{concepts:,}",
        )

        st.write(
            "The pipeline does not force a recommendation for every team. "
            "A concept must pass legality, player protection, quality, "
            "strategy-readiness, bilateral balance, and display calibration."
        )


def render_recommendation_card(
    st: Any,
    row: dict[str, Any],
) -> None:
    tier = normalized_display_tier(row.get("display_tier"))
    badge_class = TIER_BADGE_CLASS.get(tier, "tier-shortlist")
    headline = escaped(row.get("team_headline"))
    subheadline = escaped(row.get("team_subheadline"))
    description = escaped(row.get("display_tier_description"))

    st.markdown(
        f"""
<div class="trade-card">
  <div class="trade-card-topline">
    <span class="tier-badge {badge_class}">{escaped(tier)}</span>
    <span class="concept-id">Rank {escaped(row.get("app_display_rank_for_team", ""))}</span>
  </div>
  <h3>{headline}</h3>
  <p class="trade-subheadline">{subheadline}</p>
  <p class="tier-description">{description}</p>
</div>
""",
        unsafe_allow_html=True,
    )

    score_columns = st.columns(4)
    score_columns[0].metric(
        "Team strategy",
        safe_score(row.get("team_strategy_score_display")),
    )
    score_columns[1].metric(
        "Bilateral floor",
        safe_score(row.get("bilateral_floor_score_display")),
    )
    score_columns[2].metric(
        "Roster fit",
        safe_score(row.get("team_trade_fit_score_display")),
    )
    score_columns[3].metric(
        "Asset utility",
        safe_score(row.get("asset_utility_score_display")),
    )

    with st.container(border=True):
        st.markdown("**Why it may fit**")
        st.write(
            row.get(
                "team_fit_summary",
                "No fit summary is available.",
            )
        )

        secondary = st.columns(3)
        secondary[0].metric(
            "Contribution utility",
            safe_score(row.get("expected_utility_score_display")),
        )
        secondary[1].metric(
            "Downside utility",
            safe_score(row.get("downside_utility_score_display")),
        )
        secondary[2].metric(
            "Counterpart score",
            safe_score(
                row.get("counterpart_strategy_score_display")
            ),
        )

        st.markdown("**Confidence note**")
        st.write(
            row.get(
                "confidence_note",
                "No confidence note is available.",
            )
        )

        with st.expander("Trade and legality details"):
            st.write(row.get("optimizer_trade_display", ""))
            st.write(
                f"**Draft right:** "
                f"{row.get('right_display_name', 'Not available')}"
            )
            st.write(
                f"**Legality:** "
                f"{row.get('legality_label', 'Not available')}"
            )
            st.write(
                f"**Quality gate:** "
                f"{row.get('quality_gate_class', 'Not available')}"
            )

    st.caption(
        row.get(
            "availability_disclaimer",
            "This is a model-generated concept, not evidence that either "
            "team or player is available.",
        )
    )
    st.divider()


def render_page() -> None:
    import streamlit as st

    st.set_page_config(
        page_title="Mixed Trade Recommendations",
        page_icon="🏀",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    st.markdown(
        """
<style>
.block-container {
    max-width: 1320px;
    padding-top: 1.6rem;
    padding-bottom: 3rem;
}
.trade-card {
    border: 1px solid rgba(148, 163, 184, 0.30);
    border-radius: 16px;
    padding: 1.15rem 1.25rem;
    margin-top: 0.6rem;
    margin-bottom: 0.8rem;
    background: linear-gradient(
        145deg,
        rgba(30, 41, 59, 0.72),
        rgba(15, 23, 42, 0.88)
    );
}
.trade-card h3 {
    margin: 0.75rem 0 0.35rem 0;
    font-size: 1.35rem;
}
.trade-card-topline {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 0.75rem;
}
.tier-badge {
    display: inline-block;
    border-radius: 999px;
    padding: 0.28rem 0.70rem;
    font-size: 0.78rem;
    font-weight: 700;
    letter-spacing: 0.01em;
}
.tier-production {
    background: rgba(34, 197, 94, 0.18);
    border: 1px solid rgba(34, 197, 94, 0.55);
}
.tier-shortlist {
    background: rgba(59, 130, 246, 0.18);
    border: 1px solid rgba(59, 130, 246, 0.55);
}
.concept-id {
    color: rgba(226, 232, 240, 0.75);
    font-size: 0.80rem;
}
.trade-subheadline {
    margin: 0;
    color: rgba(226, 232, 240, 0.92);
}
.tier-description {
    margin: 0.65rem 0 0 0;
    color: rgba(203, 213, 225, 0.86);
    font-size: 0.90rem;
}
</style>
""",
        unsafe_allow_html=True,
    )

    try:
        bundle_path = locate_app_file(BUNDLE_FILENAME)
        bundle = load_json(bundle_path)
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as error:
        st.error("The mixed trade release could not be loaded.")
        st.code(str(error))
        st.stop()

    try:
        methodology_path = locate_app_file(METHODOLOGY_FILENAME)
        methodology = load_json(methodology_path)
    except (FileNotFoundError, ValueError, json.JSONDecodeError):
        methodology = {}

    teams = build_team_options(bundle)
    recommendation_teams = set(
        bundle.get("recommendations_by_team", {})
    )

    st.title("Mixed Player-and-Pick Trade Concepts")
    st.caption(
        "Explore deterministic-legal, strategy-screened concepts from the "
        "2026-27 NBA roster optimization model."
    )

    summary_columns = st.columns(4)
    summary_columns[0].metric(
        "Display-ready concepts",
        int(bundle.get("concept_count", 0)),
    )
    summary_columns[1].metric(
        "Team perspectives",
        int(bundle.get("recommendation_count", 0)),
    )
    summary_columns[2].metric(
        "Teams represented",
        int(bundle.get("teams_with_recommendations", 0)),
    )
    summary_columns[3].metric(
        "League teams covered",
        int(bundle.get("team_count", 0)),
    )

    st.sidebar.header("Team selection")
    show_only_available = st.sidebar.checkbox(
        "Show only teams with concepts",
        value=False,
        help=(
            "Leave this unchecked to inspect the model's explicit empty state "
            "for every NBA team."
        ),
    )

    visible_teams = (
        [team for team in teams if team in recommendation_teams]
        if show_only_available
        else teams
    )

    default_team = (
        "BKN"
        if "BKN" in visible_teams
        else visible_teams[0]
    )
    default_index = visible_teams.index(default_team)

    selected_team = st.sidebar.selectbox(
        "NBA team",
        options=visible_teams,
        index=default_index,
        format_func=lambda team: f"{TEAM_NAMES.get(team, team)} ({team})",
    )

    st.sidebar.divider()
    st.sidebar.caption(
        f"Data contract: {bundle.get('data_contract_version', 'unknown')}"
    )
    st.sidebar.caption(
        f"League year: {bundle.get('league_year', 'unknown')}"
    )

    status = status_for_team(bundle, selected_team)
    team_rows = recommendations_for_team(bundle, selected_team)

    render_status_panel(
        st=st,
        team=selected_team,
        status=status,
    )

    if team_rows:
        st.markdown("## Display-ready trade concepts")

        tier_filter = st.multiselect(
            "Display tier",
            options=[
                "Model-backed trade concept",
                "Exploratory strategy shortlist",
            ],
            default=[
                "Model-backed trade concept",
                "Exploratory strategy shortlist",
            ],
        )

        filtered_rows = [
            row
            for row in team_rows
            if row.get("display_tier") in tier_filter
        ]

        if not filtered_rows:
            st.warning(
                "No concepts remain under the selected display-tier filter."
            )
        else:
            for row in filtered_rows:
                render_recommendation_card(st, row)
    else:
        st.markdown("## Recommendation status")
        render_empty_state(st, status)

    render_score_help(st)

    with st.expander("Methodology and release safeguards"):
        display_tiers = methodology.get("display_tiers", {})
        if display_tiers:
            st.markdown("**Display tiers**")
            for label, description in display_tiers.items():
                normalized_label = normalized_display_tier(label)
                st.write(f"**{normalized_label}:** {description}")

        display_rules = methodology.get("display_rules", {})
        if display_rules:
            st.markdown("**Excluded from public recommendation cards**")
            for rule, description in display_rules.items():
                readable_rule = rule.replace("_", " ").title()
                st.write(f"**{readable_rule}:** {description}")

        disclaimers = methodology.get("disclaimers", [])
        if disclaimers:
            st.markdown("**Important limitations**")
            for disclaimer in disclaimers:
                st.write(f"- {disclaimer}")


def run_self_test(bundle_path: Path | None) -> int:
    path = (
        bundle_path
        if bundle_path is not None
        else Path("/mnt/data") / BUNDLE_FILENAME
    )

    bundle = load_json(path)
    teams = build_team_options(bundle)
    all_rows = [
        row
        for team in teams
        for row in recommendations_for_team(bundle, team)
    ]
    unique_concepts = {
        row["optimizer_candidate_id"]
        for row in all_rows
    }
    pair_counts: dict[str, int] = {}
    for row in all_rows:
        candidate_id = row["optimizer_candidate_id"]
        pair_counts[candidate_id] = pair_counts.get(candidate_id, 0) + 1

    statuses_complete = all(
        bool(status_for_team(bundle, team).get("empty_state_message"))
        for team in teams
    )
    labels_normalized = all(
        row.get("display_tier")
        in {
            "Model-backed trade concept",
            "Exploratory strategy shortlist",
        }
        for row in all_rows
    )

    tests = {
        "team_count_is_30": len(teams) == 30,
        "recommendation_rows_are_12": len(all_rows) == 12,
        "concept_count_is_6": len(unique_concepts) == 6,
        "two_rows_per_concept": all(
            count == 2 for count in pair_counts.values()
        ),
        "every_team_has_status_message": statuses_complete,
        "display_labels_normalized": labels_normalized,
        "bkn_has_model_backed_concept": any(
            row.get("display_tier") == "Model-backed trade concept"
            for row in recommendations_for_team(bundle, "BKN")
        ),
        "empty_state_team_is_supported": (
            recommendations_for_team(bundle, "CHA") == []
            and bool(status_for_team(bundle, "CHA"))
        ),
    }

    print(json.dumps(tests, indent=2))
    return 0 if all(tests.values()) else 1


def main() -> int:
    args = parse_args()
    if args.self_test:
        return run_self_test(args.bundle_path)

    render_page()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())