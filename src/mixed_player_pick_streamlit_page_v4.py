"""Polished Streamlit page for mixed player-and-pick trade concepts.

Place this file in:
    pages/2_Mixed_Trade_Recommendations.py

Required app files:
    app_data/mixed_player_pick_release_2026_27_v1.json
    app_data/mixed_player_pick_methodology_2026_27_v1.json
    app_data/mixed_trade_visual_assets_2026_27_v1.json
    app_data/mixed_trade_player_profiles_2026_27_v1.json
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import unicodedata
from pathlib import Path
from typing import Any

try:
    import streamlit as st
except ModuleNotFoundError:
    st = None


BUNDLE_FILENAME = "mixed_player_pick_release_2026_27_v1.json"
METHODOLOGY_FILENAME = "mixed_player_pick_methodology_2026_27_v1.json"
VISUAL_ASSETS_FILENAME = "mixed_trade_visual_assets_2026_27_v1.json"
PLAYER_PROFILES_FILENAME = "mixed_trade_player_profiles_2026_27_v1.json"

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

TEAM_COLORS = {
    "ATL": ("#E03A3E", "#C1D32F"),
    "BKN": ("#FFFFFF", "#A7A7A7"),
    "BOS": ("#007A33", "#BA9653"),
    "CHA": ("#1D1160", "#00788C"),
    "CHI": ("#CE1141", "#000000"),
    "CLE": ("#860038", "#FDBB30"),
    "DAL": ("#00538C", "#B8C4CA"),
    "DEN": ("#0E2240", "#FEC524"),
    "DET": ("#C8102E", "#1D42BA"),
    "GSW": ("#1D428A", "#FFC72C"),
    "HOU": ("#CE1141", "#C4CED4"),
    "IND": ("#002D62", "#FDBB30"),
    "LAC": ("#C8102E", "#1D428A"),
    "LAL": ("#552583", "#FDB927"),
    "MEM": ("#5D76A9", "#12173F"),
    "MIA": ("#98002E", "#F9A01B"),
    "MIL": ("#00471B", "#EEE1C6"),
    "MIN": ("#0C2340", "#78BE20"),
    "NOP": ("#0C2340", "#C8102E"),
    "NYK": ("#006BB6", "#F58426"),
    "OKC": ("#007AC1", "#EF3B24"),
    "ORL": ("#0077C0", "#C4CED4"),
    "PHI": ("#006BB6", "#ED174C"),
    "PHX": ("#1D1160", "#E56020"),
    "POR": ("#E03A3E", "#000000"),
    "SAC": ("#5A2D81", "#63727A"),
    "SAS": ("#C4CED4", "#000000"),
    "TOR": ("#CE1141", "#000000"),
    "UTA": ("#002B5C", "#F9A01B"),
    "WAS": ("#002B5C", "#E31837"),
}

DISPLAY_TIER_RENAMES = {
    "Model-backed recommendation": "Model-backed trade concept",
}

TIER_CLASS = {
    "Model-backed trade concept": "tier-production",
    "Exploratory strategy shortlist": "tier-shortlist",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--bundle-path", type=Path, default=None)
    parser.add_argument("--asset-path", type=Path, default=None)
    parser.add_argument("--profile-path", type=Path, default=None)
    return parser.parse_args()


def normalized_name(value: Any) -> str:
    text = "" if value is None else str(value)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(
        character
        for character in text
        if not unicodedata.combining(character)
    )
    text = text.lower().replace(".", "")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def player_key(name: Any, team: Any) -> str:
    return f"{normalized_name(name)}|{str(team).strip().upper()}"


def split_players(value: Any) -> list[str]:
    return [
        part.strip()
        for part in str(value).split("|")
        if part.strip()
    ]


def escaped(value: Any) -> str:
    return html.escape("" if value is None else str(value))


def normalized_tier(value: Any) -> str:
    text = "" if value is None else str(value).strip()
    return DISPLAY_TIER_RENAMES.get(text, text)


def candidate_project_roots() -> list[Path]:
    current_file = Path(__file__).resolve()
    roots: list[Path] = []

    configured = os.environ.get("NBA_ROSTER_OPTIMIZER_ROOT")
    if configured:
        roots.append(Path(configured).expanduser().resolve())

    if current_file.parent.name.lower() == "pages":
        roots.append(current_file.parent.parent)
    if current_file.parent.name.lower() == "src":
        roots.append(current_file.parent.parent)

    roots.extend([current_file.parent, Path.cwd().resolve()])

    unique: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        key = str(root)
        if key not in seen:
            seen.add(key)
            unique.append(root)
    return unique


def locate_app_file(filename: str) -> Path:
    checked: list[Path] = []
    for root in candidate_project_roots():
        for path in [root / "app_data" / filename, root / filename]:
            checked.append(path)
            if path.exists():
                return path
    raise FileNotFoundError(
        f"Could not locate {filename}. Checked:\n"
        + "\n".join(str(path) for path in checked)
    )


def _read_json_file(
    path_text: str,
    modified_time_ns: int,
) -> dict[str, Any]:
    """Read one JSON object.

    ``modified_time_ns`` is part of the cache key so an updated file
    invalidates the cached value automatically.
    """
    del modified_time_ns
    path = Path(path_text)
    with path.open("r", encoding="utf-8") as file:
        value = json.load(file)
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object in {path}.")
    return value


if st is not None:
    load_json = st.cache_data(show_spinner=False)(_read_json_file)
else:
    load_json = _read_json_file


def load_app_json(filename: str) -> dict[str, Any]:
    path = locate_app_file(filename)
    return load_json(str(path), path.stat().st_mtime_ns)


def team_logo_url(
    visual_assets: dict[str, Any],
    team: str,
) -> str:
    team_row = visual_assets.get("teams", {}).get(team, {})
    return str(team_row.get("logo_url", "")).strip()


def player_headshot_url(
    visual_assets: dict[str, Any],
    player_name: str,
    team: str,
) -> str:
    key = player_key(player_name, team)
    row = visual_assets.get("players", {}).get(key, {})
    return str(row.get("headshot_url", "")).strip()


def player_profile(
    player_profiles: dict[str, Any],
    player_name: str,
    team: str,
) -> dict[str, Any]:
    key = player_key(player_name, team)
    row = player_profiles.get("players", {}).get(key, {})
    return row if isinstance(row, dict) else {}


def display_number(
    value: Any,
    suffix: str = "",
) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "N/A"
    return f"{number:.1f}{suffix}"


def profile_quick_line(profile: dict[str, Any]) -> str:
    if not profile:
        return ""
    return (
        f"{display_number(profile.get('points_per_game'))} PPG · "
        f"{display_number(profile.get('rebounds_per_game'))} RPG · "
        f"{display_number(profile.get('assists_per_game'))} APG"
    )


def comparison_bar_html(
    *,
    left_profile: dict[str, Any],
    right_profile: dict[str, Any],
    label: str,
    value_field: str,
    percentile_field: str,
    suffix: str,
    left_color: str,
    right_color: str,
) -> str:
    left_value = display_number(
        left_profile.get(value_field),
        suffix,
    )
    right_value = display_number(
        right_profile.get(value_field),
        suffix,
    )
    left_percentile = score_value(
        left_profile.get(percentile_field)
    )
    right_percentile = score_value(
        right_profile.get(percentile_field)
    )

    return f"""
<div class="comparison-stat-row">
  <div class="comparison-stat-side comparison-left">
    <div class="comparison-stat-value">{escaped(left_value)}</div>
    <div class="comparison-stat-track">
      <div class="comparison-stat-fill comparison-fill-left"
           style="width:{left_percentile:.1f}%;background:{left_color};"></div>
    </div>
  </div>
  <div class="comparison-stat-label">{escaped(label)}</div>
  <div class="comparison-stat-side comparison-right">
    <div class="comparison-stat-value">{escaped(right_value)}</div>
    <div class="comparison-stat-track">
      <div class="comparison-stat-fill"
           style="width:{right_percentile:.1f}%;background:{right_color};"></div>
    </div>
  </div>
</div>
"""


def render_player_stat_comparison(
    st: Any,
    *,
    outgoing_players: list[str],
    incoming_players: list[str],
    outgoing_team: str,
    incoming_team: str,
    player_profiles: dict[str, Any],
    outgoing_color: str,
    incoming_color: str,
) -> None:
    """Render a familiar 2025-26 production comparison for one-player sides."""
    if len(outgoing_players) != 1 or len(incoming_players) != 1:
        st.caption(
            "Detailed multi-player production comparison will be added with "
            "the freeform Trade Machine."
        )
        return

    outgoing_name = outgoing_players[0]
    incoming_name = incoming_players[0]
    outgoing_profile = player_profile(
        player_profiles,
        outgoing_name,
        outgoing_team,
    )
    incoming_profile = player_profile(
        player_profiles,
        incoming_name,
        incoming_team,
    )

    if not outgoing_profile or not incoming_profile:
        st.info(
            "Player production profiles are not available for both sides "
            "of this concept."
        )
        return

    comparison_rows = [
        (
            "Scoring",
            "points_per_game",
            "points_per_game_percentile",
            " PPG",
        ),
        (
            "Rebounding",
            "rebounds_per_game",
            "rebounds_per_game_percentile",
            " RPG",
        ),
        (
            "Playmaking",
            "assists_per_game",
            "assists_per_game_percentile",
            " APG",
        ),
        (
            "Shooting efficiency",
            "true_shooting_pct",
            "true_shooting_percentile",
            "% TS",
        ),
        (
            "Three-point shooting",
            "three_point_pct",
            "three_point_percentile",
            "% 3P",
        ),
        (
            "Role / minutes",
            "minutes_per_game",
            "minutes_per_game_percentile",
            " MPG",
        ),
        (
            "Availability",
            "games_played",
            "games_played_percentile",
            " GP",
        ),
    ]

    rows_html = "".join(
        comparison_bar_html(
            left_profile=outgoing_profile,
            right_profile=incoming_profile,
            label=label,
            value_field=value_field,
            percentile_field=percentile_field,
            suffix=suffix,
            left_color=outgoing_color,
            right_color=incoming_color,
        )
        for (
            label,
            value_field,
            percentile_field,
            suffix,
        ) in comparison_rows
    )

    outgoing_overall = display_number(
        outgoing_profile.get("overall_rating")
    )
    incoming_overall = display_number(
        incoming_profile.get("overall_rating")
    )

    outgoing_context = " · ".join(
        part
        for part in [
            (
                f"{display_number(outgoing_profile.get('field_goal_pct'), '%')} FG"
            ),
            (
                f"{display_number(outgoing_profile.get('usage_pct'), '%')} USG"
                if outgoing_profile.get("usage_pct") is not None
                else ""
            ),
            outgoing_profile.get("primary_skill", ""),
        ]
        if part
    )
    incoming_context = " · ".join(
        part
        for part in [
            (
                f"{display_number(incoming_profile.get('field_goal_pct'), '%')} FG"
            ),
            (
                f"{display_number(incoming_profile.get('usage_pct'), '%')} USG"
                if incoming_profile.get("usage_pct") is not None
                else ""
            ),
            incoming_profile.get("primary_skill", ""),
        ]
        if part
    )

    st.markdown(
        f"""
<div class="player-comparison-shell">
  <div class="player-comparison-heading">
    <div>
      <span class="eyebrow">2025-26 production</span>
      <h3>Player comparison</h3>
      <p>
        Actual per-game statistics are shown beside each player. Bar length
        represents league percentile among rotation-level players.
      </p>
    </div>
  </div>
  <div class="comparison-player-header">
    <div class="comparison-player comparison-player-left">
      <span class="comparison-player-name">{escaped(outgoing_name)}</span>
      <span class="overall-rating-pill">{escaped(outgoing_overall)} OVR</span>
      <small>{escaped(outgoing_context)}</small>
    </div>
    <div class="comparison-versus">VS</div>
    <div class="comparison-player comparison-player-right">
      <span class="comparison-player-name">{escaped(incoming_name)}</span>
      <span class="overall-rating-pill">{escaped(incoming_overall)} OVR</span>
      <small>{escaped(incoming_context)}</small>
    </div>
  </div>
  <div class="comparison-stat-grid">
    {rows_html}
  </div>
</div>
""",
        unsafe_allow_html=True,
    )


def recommendations_for_team(
    bundle: dict[str, Any],
    team: str,
) -> list[dict[str, Any]]:
    """Return one selected-team perspective per canonical app concept.

    The JSON bundle contains reciprocal perspectives across the league. This
    function defensively filters by ``recommendation_team`` and removes any
    repeated candidate ID before the page renders.
    """
    rows = bundle.get("recommendations_by_team", {}).get(team, [])
    normalized_rows: list[dict[str, Any]] = []
    seen_candidate_ids: set[str] = set()

    for row in rows:
        if not isinstance(row, dict):
            continue

        item = dict(row)
        if str(item.get("recommendation_team", "")).strip() != team:
            continue

        candidate_id = str(
            item.get("optimizer_candidate_id", "")
        ).strip()
        if not candidate_id or candidate_id in seen_candidate_ids:
            continue

        seen_candidate_ids.add(candidate_id)
        item["display_tier"] = normalized_tier(
            item.get("display_tier")
        )
        normalized_rows.append(item)

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
    status = bundle.get("team_status_by_team", {}).get(team)
    if not isinstance(status, dict):
        raise KeyError(f"Missing team status for {team}.")
    return status


def score_value(value: Any) -> float:
    try:
        return max(0.0, min(100.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def score_text(value: Any) -> str:
    try:
        return f"{float(value):.1f}"
    except (TypeError, ValueError):
        return "N/A"


def render_score_bar(
    label: str,
    value: Any,
    color: str,
) -> str:
    score = score_value(value)
    return f"""
<div class="score-block">
  <div class="score-label-row">
    <span>{escaped(label)}</span>
    <strong>{score_text(value)}</strong>
  </div>
  <div class="score-track">
    <div class="score-fill" style="width:{score:.1f}%;background:{color};"></div>
  </div>
</div>
"""


def render_player_card(
    st: Any,
    *,
    title: str,
    players: list[str],
    team: str,
    visual_assets: dict[str, Any],
    player_profiles: dict[str, Any],
    accent: str,
) -> None:
    logo = team_logo_url(visual_assets, team)
    full_team_name = TEAM_NAMES.get(team, team)

    logo_html = (
        f'<img class="mini-team-logo" src="{escaped(logo)}" '
        f'alt="{escaped(full_team_name)} logo">'
        if logo
        else ""
    )

    st.markdown(
        f"""
<div class="asset-side-header" style="border-color:{accent};">
  {logo_html}
  <div>
    <span class="asset-side-kicker">{escaped(title)}</span>
    <strong>{escaped(full_team_name)}</strong>
  </div>
</div>
""",
        unsafe_allow_html=True,
    )

    for player in players:
        headshot = player_headshot_url(
            visual_assets,
            player,
            team,
        )
        profile = player_profile(
            player_profiles,
            player,
            team,
        )
        headshot_html = (
            f'<img class="player-headshot" src="{escaped(headshot)}" '
            f'alt="{escaped(player)} headshot">'
            if headshot
            else '<div class="player-headshot player-placeholder">NBA</div>'
        )
        overall_html = (
            f'<span class="player-overall-badge">'
            f'{escaped(display_number(profile.get("overall_rating")))} OVR'
            f'</span>'
            if profile.get("overall_rating") is not None
            else ""
        )
        quick_line = profile_quick_line(profile)
        quick_line_html = (
            f'<span class="player-quick-stats">{escaped(quick_line)}</span>'
            if quick_line
            else ""
        )
        st.markdown(
            f"""
<div class="player-identity-card">
  {headshot_html}
  <div class="player-identity-copy">
    <div class="player-name-row">
      <span class="player-name">{escaped(player)}</span>
      {overall_html}
    </div>
    <span class="player-team">{escaped(team)}</span>
    {quick_line_html}
  </div>
</div>
""",
            unsafe_allow_html=True,
        )


def render_team_header(
    st: Any,
    team: str,
    status: dict[str, Any],
    visual_assets: dict[str, Any],
) -> None:
    primary, secondary = TEAM_COLORS.get(
        team,
        ("#3B82F6", "#94A3B8"),
    )
    logo = team_logo_url(visual_assets, team)
    logo_html = (
        f'<img class="team-hero-logo" src="{escaped(logo)}" '
        f'alt="{escaped(TEAM_NAMES.get(team, team))} logo">'
        if logo
        else '<div class="team-hero-logo team-logo-placeholder">NBA</div>'
    )

    needs = [
        status.get("top_need_1"),
        status.get("top_need_2"),
        status.get("top_need_3"),
    ]
    need_chips = "".join(
        f'<span class="need-chip">{escaped(need)}</span>'
        for need in needs
        if need
    )

    st.markdown(
        f"""
<div class="team-hero" style="
    --team-primary:{primary};
    --team-secondary:{secondary};
">
  <div class="team-hero-glow"></div>
  <div class="team-hero-main">
    {logo_html}
    <div>
      <span class="eyebrow">Selected front office</span>
      <h2>{escaped(TEAM_NAMES.get(team, team))}</h2>
      <p>{escaped(team)} · {escaped(status.get("team_strategy_archetype_label", ""))}</p>
    </div>
  </div>
  <div class="team-hero-priority">
    <span class="eyebrow">Modeled priority</span>
    <p>{escaped(status.get("model_team_strategy_priority", ""))}</p>
    <div class="need-chip-row">{need_chips}</div>
  </div>
</div>
""",
        unsafe_allow_html=True,
    )


def render_empty_state(
    st: Any,
    team: str,
    status: dict[str, Any],
) -> None:
    primary, _ = TEAM_COLORS.get(team, ("#3B82F6", "#94A3B8"))
    st.markdown(
        f"""
<div class="empty-state" style="border-color:{primary};">
  <span class="eyebrow">{escaped(status.get("app_status_label", ""))}</span>
  <h3>No display-ready trade concept</h3>
  <p>{escaped(status.get("empty_state_message", ""))}</p>
</div>
""",
        unsafe_allow_html=True,
    )

    columns = st.columns(3)
    columns[0].metric(
        "Legal perspective rows",
        f"{int(status.get('deterministic_legal_perspective_rows', 0) or 0):,}",
    )
    columns[1].metric(
        "Strategy-ready variants",
        f"{int(status.get('routine_package_variants', 0) or 0):,}",
    )
    columns[2].metric(
        "Canonical concepts",
        f"{int(status.get('unique_canonical_concepts', 0) or 0):,}",
    )


def build_impact_chips(row: dict[str, Any]) -> list[tuple[str, str]]:
    summary = str(row.get("team_fit_summary", "")).lower()
    chips: list[tuple[str, str]] = []

    checks = [
        ("improves projected contribution", "Contribution upgrade", "positive"),
        ("improves downside protection", "Better downside protection", "positive"),
        ("gets meaningfully younger", "Younger timeline", "positive"),
        ("grades as a strong roster fit", "Strong roster fit", "positive"),
        ("receives a first round asset", "Adds a first-round asset", "positive"),
        ("receives a second round asset", "Adds a second-round asset", "positive"),
        ("adds roster depth", "Adds roster depth", "positive"),
        ("consolidates roster slots", "Consolidates roster", "neutral"),
        ("keeps player count neutral", "Player count neutral", "neutral"),
        ("attaches a first round asset", "Costs a first-round asset", "caution"),
        ("attaches a second round asset", "Costs a second-round asset", "caution"),
        ("reduces projected contribution", "Contribution risk", "caution"),
        ("weakens downside protection", "Downside risk", "caution"),
        ("gets meaningfully older", "Older timeline", "caution"),
        ("marginal roster-fit score", "Marginal roster fit", "caution"),
    ]

    for phrase, label, category in checks:
        if phrase in summary:
            chips.append((label, category))

    if not chips:
        chips.append(("Balanced model-screened concept", "neutral"))

    return chips[:6]


def render_impact_chips(row: dict[str, Any]) -> str:
    chips = build_impact_chips(row)
    return "".join(
        f'<span class="impact-chip impact-{category}">{escaped(label)}</span>'
        for label, category in chips
    )


def render_recommendation(
    st: Any,
    row: dict[str, Any],
    visual_assets: dict[str, Any],
    player_profiles: dict[str, Any],
) -> None:
    team = str(row["recommendation_team"])
    counterpart = str(row["counterpart_team"])
    primary, secondary = TEAM_COLORS.get(
        team,
        ("#3B82F6", "#94A3B8"),
    )
    counterpart_primary, _ = TEAM_COLORS.get(
        counterpart,
        ("#64748B", "#CBD5E1"),
    )

    tier = normalized_tier(row.get("display_tier"))
    tier_class = TIER_CLASS.get(tier, "tier-shortlist")

    st.markdown(
        f"""
<div class="recommendation-shell" style="
    --team-primary:{primary};
    --team-secondary:{secondary};
">
  <div class="recommendation-heading-row">
    <span class="tier-badge {tier_class}">{escaped(tier)}</span>
    <span class="rank-pill">Rank {escaped(row.get("app_display_rank_for_team", ""))}</span>
  </div>
  <h3>{escaped(row.get("team_headline", ""))}</h3>
  <p class="recommendation-subtitle">{escaped(row.get("team_subheadline", ""))}</p>
  <div class="impact-chip-row">{render_impact_chips(row)}</div>
</div>
""",
        unsafe_allow_html=True,
    )

    trade_columns = st.columns([1, 0.12, 1])
    with trade_columns[0]:
        render_player_card(
            st,
            title=f"{team} sends",
            players=split_players(row["outgoing_players"]),
            team=team,
            visual_assets=visual_assets,
            player_profiles=player_profiles,
            accent=primary,
        )
        if bool(row.get("team_attaches_pick")):
            st.markdown(
                f"""
<div class="pick-chip">
  + {escaped(row.get("right_display_name", "Draft asset"))}
</div>
""",
                unsafe_allow_html=True,
            )

    with trade_columns[1]:
        st.markdown(
            '<div class="trade-arrow">⇄</div>',
            unsafe_allow_html=True,
        )

    with trade_columns[2]:
        render_player_card(
            st,
            title=f"{team} receives",
            players=split_players(row["incoming_players"]),
            team=counterpart,
            visual_assets=visual_assets,
            player_profiles=player_profiles,
            accent=counterpart_primary,
        )
        if bool(row.get("team_receives_pick")):
            st.markdown(
                f"""
<div class="pick-chip">
  + {escaped(row.get("right_display_name", "Draft asset"))}
</div>
""",
                unsafe_allow_html=True,
            )

    render_player_stat_comparison(
        st,
        outgoing_players=split_players(row["outgoing_players"]),
        incoming_players=split_players(row["incoming_players"]),
        outgoing_team=team,
        incoming_team=counterpart,
        player_profiles=player_profiles,
        outgoing_color=primary,
        incoming_color=counterpart_primary,
    )

    st.markdown(
        """
<div class="model-score-heading">
  <span class="eyebrow">Front-office model</span>
  <h3>Trade impact scores</h3>
  <p>
    These scores describe roster strategy and transaction value rather than
    traditional player statistics.
  </p>
</div>
""",
        unsafe_allow_html=True,
    )

    score_columns = st.columns(2)
    with score_columns[0]:
        st.markdown(
            render_score_bar(
                "Team strategy",
                row.get("team_strategy_score_display"),
                primary,
            )
            + render_score_bar(
                "Roster fit",
                row.get("team_trade_fit_score_display"),
                primary,
            )
            + render_score_bar(
                "Contribution utility",
                row.get("expected_utility_score_display"),
                primary,
            ),
            unsafe_allow_html=True,
        )
    with score_columns[1]:
        st.markdown(
            render_score_bar(
                "Bilateral floor",
                row.get("bilateral_floor_score_display"),
                secondary,
            )
            + render_score_bar(
                "Asset utility",
                row.get("asset_utility_score_display"),
                secondary,
            )
            + render_score_bar(
                "Downside utility",
                row.get("downside_utility_score_display"),
                secondary,
            ),
            unsafe_allow_html=True,
        )

    detail_columns = st.columns([1.5, 1])
    with detail_columns[0]:
        with st.container(border=True):
            st.markdown("#### Why it may fit")
            st.write(row.get("team_fit_summary", ""))
    with detail_columns[1]:
        with st.container(border=True):
            st.markdown("#### Confidence")
            st.write(row.get("confidence_note", ""))

    with st.expander("Trade, pick, and legality details"):
        st.write(row.get("optimizer_trade_display", ""))
        st.write(
            f"**Draft right:** {row.get('right_display_name', '')}"
        )
        st.write(
            f"**Legality:** {row.get('legality_label', '')}"
        )
        st.write(
            f"**Quality gate:** {row.get('quality_gate_class', '')}"
        )

    st.caption(row.get("availability_disclaimer", ""))
    st.markdown('<div class="section-spacer"></div>', unsafe_allow_html=True)



def available_confidence_tiers(
    rows: list[dict[str, Any]],
) -> list[str]:
    """Return only confidence tiers that exist for the selected team."""
    preferred_order = [
        "Model-backed trade concept",
        "Exploratory strategy shortlist",
    ]
    present = {
        str(row.get("display_tier", "")).strip()
        for row in rows
    }
    return [
        tier
        for tier in preferred_order
        if tier in present
    ]


def render_static_tier_label(tier: str) -> None:
    """Show the only available tier without creating another rerun widget."""
    css_class = TIER_CLASS.get(tier, "tier-shortlist")
    st.markdown(
        f"""
<div class="single-tier-row">
  <span class="single-tier-label">Available confidence tier</span>
  <span class="tier-badge {css_class}">{escaped(tier)}</span>
</div>
""",
        unsafe_allow_html=True,
    )


def render_page() -> None:
    if st is None:
        raise ModuleNotFoundError(
            "Streamlit is required to render this page. "
            "Install it or launch from the nba-roster-optimizer environment."
        )

    st.set_page_config(
        page_title="NBA Front Office Trade Lab",
        page_icon="🏀",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    st.markdown(
        """
<style>
.block-container {
    max-width: 1340px;
    padding-top: 1.6rem;
    padding-bottom: 4rem;
}
.stApp {
    background:
        radial-gradient(circle at 78% 4%, rgba(37,99,235,.10), transparent 28rem),
        radial-gradient(circle at 18% 70%, rgba(14,165,233,.06), transparent 32rem),
        #080D16;
}
[data-testid="stHeader"] {
    background: rgba(8,13,22,.78);
    backdrop-filter: blur(12px);
}
.kpi-grid {
    display:grid;
    grid-template-columns:repeat(4, minmax(0,1fr));
    gap:.85rem;
    margin:1.35rem 0 1.25rem;
}
.kpi-card {
    display:flex;
    flex-direction:column;
    gap:.18rem;
    min-height:112px;
    padding:1rem 1.05rem;
    border:1px solid rgba(148,163,184,.17);
    border-radius:16px;
    background:
        linear-gradient(145deg, rgba(30,41,59,.76), rgba(15,23,42,.60));
    box-shadow:0 14px 34px rgba(0,0,0,.14);
}
.kpi-card strong {
    font-size:1.65rem;
    line-height:1.1;
    letter-spacing:-.035em;
}
.kpi-label {
    color:#F8FAFC;
    font-weight:750;
    font-size:.78rem;
}
.kpi-note {
    margin-top:auto;
    color:rgba(203,213,225,.56);
    font-size:.70rem;
}
[data-testid="stSidebar"] {
    border-right: 1px solid rgba(148,163,184,.18);
}
.hero-title {
    font-size: clamp(2rem, 4vw, 3.35rem);
    line-height: 1.04;
    margin: 0;
    letter-spacing: -0.045em;
}
.hero-subtitle {
    max-width: 760px;
    color: rgba(226,232,240,.74);
    font-size: 1.02rem;
    margin-top: .65rem;
}
.team-hero {
    position: relative;
    overflow: hidden;
    display: grid;
    grid-template-columns: 1.15fr 1fr;
    gap: 1.5rem;
    border: 1px solid rgba(148,163,184,.24);
    border-radius: 22px;
    padding: 1.4rem;
    margin: 1.15rem 0 1.6rem;
    background:
        linear-gradient(135deg, color-mix(in srgb, var(--team-primary) 18%, transparent), transparent 42%),
        rgba(15,23,42,.72);
}
.team-hero-glow {
    position: absolute;
    inset: auto -12% -85% auto;
    width: 420px;
    height: 420px;
    border-radius: 999px;
    background: var(--team-primary);
    filter: blur(95px);
    opacity: .12;
}
.team-hero-main {
    display: flex;
    gap: 1rem;
    align-items: center;
    position: relative;
}
.team-hero-main h2 {
    margin: .12rem 0;
    font-size: 1.65rem;
}
.team-hero-main p,
.team-hero-priority p {
    margin: 0;
    color: rgba(226,232,240,.78);
}
.team-hero-priority {
    position: relative;
    align-self: center;
}
.team-hero-logo,
.team-logo-placeholder {
    width: 88px;
    height: 88px;
    object-fit: contain;
    filter: drop-shadow(0 12px 24px rgba(0,0,0,.30));
}
.team-logo-placeholder {
    display:flex;
    align-items:center;
    justify-content:center;
    border-radius:999px;
    background:rgba(255,255,255,.08);
}
.eyebrow {
    text-transform: uppercase;
    letter-spacing: .11em;
    font-size: .68rem;
    font-weight: 800;
    color: rgba(226,232,240,.58);
}
.need-chip-row {
    display: flex;
    flex-wrap: wrap;
    gap: .45rem;
    margin-top: .75rem;
}
.need-chip {
    padding: .28rem .58rem;
    border-radius: 999px;
    background: rgba(255,255,255,.07);
    border: 1px solid rgba(255,255,255,.10);
    font-size: .76rem;
}
.recommendation-shell {
    border: 1px solid color-mix(in srgb, var(--team-primary) 42%, rgba(148,163,184,.25));
    border-radius: 20px;
    padding: 1.25rem 1.35rem;
    background:
        linear-gradient(135deg, color-mix(in srgb, var(--team-primary) 14%, transparent), transparent 48%),
        rgba(15,23,42,.78);
    box-shadow: 0 18px 45px rgba(0,0,0,.17);
}
.recommendation-shell h3 {
    font-size: 1.35rem;
    margin: .8rem 0 .25rem;
}
.recommendation-subtitle {
    color: rgba(226,232,240,.76);
    margin: 0;
}
.impact-chip-row {
    display:flex;
    flex-wrap:wrap;
    gap:.42rem;
    margin-top:.8rem;
}
.impact-chip {
    display:inline-flex;
    align-items:center;
    border-radius:999px;
    padding:.27rem .58rem;
    font-size:.70rem;
    font-weight:750;
}
.impact-positive {
    color:#BBF7D0;
    background:rgba(34,197,94,.12);
    border:1px solid rgba(34,197,94,.28);
}
.impact-neutral {
    color:#DBEAFE;
    background:rgba(59,130,246,.12);
    border:1px solid rgba(59,130,246,.26);
}
.impact-caution {
    color:#FDE68A;
    background:rgba(245,158,11,.11);
    border:1px solid rgba(245,158,11,.28);
}
.recommendation-heading-row {
    display:flex;
    align-items:center;
    justify-content:space-between;
    gap:1rem;
}
.tier-badge,
.rank-pill {
    border-radius:999px;
    padding:.3rem .68rem;
    font-size:.76rem;
    font-weight:800;
}
.tier-production {
    background:rgba(34,197,94,.18);
    border:1px solid rgba(34,197,94,.55);
}
.tier-shortlist {
    background:rgba(59,130,246,.18);
    border:1px solid rgba(59,130,246,.55);
}
.rank-pill {
    color:rgba(226,232,240,.65);
    border:1px solid rgba(148,163,184,.18);
}
.asset-side-header {
    display:flex;
    gap:.65rem;
    align-items:center;
    padding:.7rem .8rem;
    margin-top:.75rem;
    border-left:3px solid;
    border-radius:12px;
    background:rgba(255,255,255,.035);
}
.asset-side-header div {
    display:flex;
    flex-direction:column;
}
.asset-side-kicker {
    color:rgba(226,232,240,.58);
    font-size:.72rem;
    text-transform:uppercase;
    letter-spacing:.08em;
}
.mini-team-logo {
    width:42px;
    height:42px;
    object-fit:contain;
}
.player-identity-card {
    display:flex;
    align-items:center;
    min-height:116px;
    margin-top:.55rem;
    padding:.25rem .7rem .25rem .2rem;
    border:1px solid rgba(148,163,184,.16);
    border-radius:16px;
    background:rgba(15,23,42,.52);
    overflow:hidden;
}
.player-headshot {
    width:118px;
    height:92px;
    object-fit:contain;
    object-position:center bottom;
    align-self:flex-end;
}
.player-placeholder {
    display:flex;
    align-items:center;
    justify-content:center;
    color:rgba(226,232,240,.42);
    background:rgba(255,255,255,.04);
}
.player-identity-copy {
    display:flex;
    flex-direction:column;
    gap:.15rem;
    width:100%;
}
.player-name-row {
    display:flex;
    align-items:center;
    justify-content:space-between;
    gap:.65rem;
}
.player-overall-badge {
    flex:0 0 auto;
    padding:.22rem .48rem;
    border-radius:999px;
    color:#F8FAFC;
    background:rgba(59,130,246,.15);
    border:1px solid rgba(96,165,250,.26);
    font-size:.68rem;
    font-weight:850;
}
.player-quick-stats {
    margin-top:.22rem;
    color:rgba(203,213,225,.68);
    font-size:.72rem;
}
.player-name {
    font-size:1.08rem;
    font-weight:800;
}
.player-team {
    color:rgba(226,232,240,.58);
    font-size:.78rem;
}
.trade-arrow {
    display:flex;
    align-items:center;
    justify-content:center;
    min-height:190px;
    font-size:1.7rem;
    color:rgba(226,232,240,.45);
}
.pick-chip {
    margin:.5rem 0 .25rem;
    border-radius:10px;
    padding:.55rem .7rem;
    background:rgba(234,179,8,.10);
    border:1px solid rgba(234,179,8,.28);
    color:rgba(254,240,138,.92);
    font-size:.79rem;
}
.player-comparison-shell {
    margin:1.25rem 0 1.1rem;
    padding:1.25rem 1.3rem;
    border:1px solid rgba(148,163,184,.17);
    border-radius:20px;
    background:
        linear-gradient(145deg, rgba(30,41,59,.66), rgba(15,23,42,.56));
}
.player-comparison-heading h3,
.model-score-heading h3 {
    margin:.22rem 0 .28rem;
    font-size:1.22rem;
}
.player-comparison-heading p,
.model-score-heading p {
    margin:0;
    color:rgba(203,213,225,.62);
    font-size:.79rem;
}
.comparison-player-header {
    display:grid;
    grid-template-columns:1fr 54px 1fr;
    align-items:center;
    gap:.75rem;
    margin:1rem 0 .7rem;
}
.comparison-player {
    display:grid;
    grid-template-columns:auto auto;
    align-items:center;
    gap:.35rem .55rem;
}
.comparison-player-right {
    text-align:right;
    justify-content:end;
}
.comparison-player-name {
    font-size:.96rem;
    font-weight:800;
}
.comparison-player small {
    grid-column:1 / -1;
    color:rgba(203,213,225,.55);
    font-size:.68rem;
}
.overall-rating-pill {
    display:inline-flex;
    justify-self:start;
    padding:.24rem .5rem;
    border-radius:999px;
    color:#F8FAFC;
    background:rgba(59,130,246,.14);
    border:1px solid rgba(96,165,250,.25);
    font-size:.68rem;
    font-weight:850;
}
.comparison-player-right .overall-rating-pill {
    justify-self:end;
}
.comparison-versus {
    text-align:center;
    color:rgba(148,163,184,.52);
    font-size:.72rem;
    font-weight:850;
}
.comparison-stat-grid {
    display:grid;
    gap:.64rem;
}
.comparison-stat-row {
    display:grid;
    grid-template-columns:minmax(0,1fr) 150px minmax(0,1fr);
    align-items:end;
    gap:.8rem;
}
.comparison-stat-side {
    min-width:0;
}
.comparison-stat-value {
    margin-bottom:.25rem;
    color:#F8FAFC;
    font-size:.78rem;
    font-weight:800;
}
.comparison-right .comparison-stat-value {
    text-align:right;
}
.comparison-stat-label {
    align-self:center;
    color:rgba(226,232,240,.70);
    text-align:center;
    font-size:.74rem;
    font-weight:700;
}
.comparison-stat-track {
    height:7px;
    overflow:hidden;
    border-radius:999px;
    background:rgba(148,163,184,.13);
}
.comparison-stat-fill {
    height:100%;
    border-radius:999px;
}
.comparison-fill-left {
    margin-left:auto;
}
.model-score-heading {
    margin:1.2rem 0 .25rem;
}
.score-block {
    margin:.85rem 0;
}
.score-label-row {
    display:flex;
    justify-content:space-between;
    gap:1rem;
    font-size:.80rem;
    color:rgba(226,232,240,.76);
}
.score-label-row strong {
    color:#F8FAFC;
}
.score-track {
    width:100%;
    height:7px;
    margin-top:.35rem;
    border-radius:999px;
    overflow:hidden;
    background:rgba(148,163,184,.15);
}
.score-fill {
    height:100%;
    border-radius:999px;
}
.single-tier-row {
    display:flex;
    align-items:center;
    flex-wrap:wrap;
    gap:.65rem;
    margin:.45rem 0 .85rem;
}
.single-tier-label {
    color:rgba(203,213,225,.62);
    font-size:.76rem;
    font-weight:700;
}
.empty-state {
    border:1px solid;
    border-radius:18px;
    padding:1.4rem;
    margin:1rem 0;
    background:rgba(15,23,42,.64);
}
.empty-state h3 {
    margin:.35rem 0;
}
.empty-state p {
    color:rgba(226,232,240,.72);
}
.section-spacer {
    height:1.1rem;
}
@media (max-width: 900px) {
    .kpi-grid {
        grid-template-columns:repeat(2, minmax(0,1fr));
    }
    .team-hero {
        grid-template-columns: 1fr;
    }
    .trade-arrow {
        min-height:60px;
    }
}
@media (max-width: 700px) {
    .comparison-stat-row {
        grid-template-columns:1fr;
        gap:.28rem;
    }
    .comparison-stat-label {
        order:-1;
        text-align:left;
    }
    .comparison-right .comparison-stat-value {
        text-align:left;
    }
    .comparison-fill-left {
        margin-left:0;
    }
}
@media (max-width: 560px) {
    .kpi-grid {
        grid-template-columns:1fr;
    }
    .team-hero-logo,
    .team-logo-placeholder {
        width:68px;
        height:68px;
    }
}
</style>
""",
        unsafe_allow_html=True,
    )

    try:
        bundle = load_app_json(BUNDLE_FILENAME)
        methodology = load_app_json(METHODOLOGY_FILENAME)
        visual_assets = load_app_json(VISUAL_ASSETS_FILENAME)
        player_profiles = load_app_json(PLAYER_PROFILES_FILENAME)
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as error:
        st.error("The app release or visual assets could not be loaded.")
        st.code(str(error))
        st.stop()

    statuses = bundle.get("team_status_by_team", {})
    teams = sorted(
        statuses,
        key=lambda team: TEAM_NAMES.get(team, team),
    )
    teams_with_concepts = set(
        bundle.get("recommendations_by_team", {})
    )

    st.markdown(
        '<h1 class="hero-title">NBA Front Office Trade Lab</h1>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<p class="hero-subtitle">'
        "Explore deterministic-legal mixed player-and-pick concepts, "
        "compare both sides of the deal, and see how each idea aligns "
        "with a team's modeled direction."
        "</p>",
        unsafe_allow_html=True,
    )

    st.markdown(
        f"""
<div class="kpi-grid">
  <div class="kpi-card">
    <span class="kpi-label">Display-ready concepts</span>
    <strong>{int(bundle.get("concept_count", 0))}</strong>
    <span class="kpi-note">Calibrated for public display</span>
  </div>
  <div class="kpi-card">
    <span class="kpi-label">Team perspectives</span>
    <strong>{int(bundle.get("recommendation_count", 0))}</strong>
    <span class="kpi-note">Both sides scored separately</span>
  </div>
  <div class="kpi-card">
    <span class="kpi-label">Teams represented</span>
    <strong>{int(bundle.get("teams_with_recommendations", 0))}</strong>
    <span class="kpi-note">With display-ready concepts</span>
  </div>
  <div class="kpi-card">
    <span class="kpi-label">League coverage</span>
    <strong>{int(bundle.get("team_count", 0))}</strong>
    <span class="kpi-note">Explicit status for every team</span>
  </div>
</div>
""",
        unsafe_allow_html=True,
    )

    st.sidebar.markdown("## Front office controls")
    only_available = st.sidebar.checkbox(
        "Only teams with concepts",
        value=False,
    )
    visible_teams = (
        [team for team in teams if team in teams_with_concepts]
        if only_available
        else teams
    )
    default_team = "BKN" if "BKN" in visible_teams else visible_teams[0]
    selected_team = st.sidebar.selectbox(
        "Select a team",
        visible_teams,
        index=visible_teams.index(default_team),
        format_func=lambda team: (
            f"{TEAM_NAMES.get(team, team)} ({team})"
        ),
        key="selected_trade_team",
    )

    status = status_for_team(bundle, selected_team)
    rows = recommendations_for_team(bundle, selected_team)

    render_team_header(
        st,
        selected_team,
        status,
        visual_assets,
    )

    if not rows:
        render_empty_state(st, selected_team, status)
    else:
        st.markdown("## Front office trade board")
        available_tiers = available_confidence_tiers(rows)

        if len(available_tiers) == 1:
            tier_filter = available_tiers[0]
            render_static_tier_label(tier_filter)
        else:
            tier_filter = st.segmented_control(
                "Confidence tier",
                options=["All", *available_tiers],
                default="All",
                key=f"confidence_tier_{selected_team}",
                help=(
                    "Only confidence tiers available for the selected team "
                    "are shown."
                ),
            )

        filtered = (
            rows
            if tier_filter == "All"
            else [
                row
                for row in rows
                if row["display_tier"] == tier_filter
            ]
        )

        for row in filtered:
            render_recommendation(
                st,
                row,
                visual_assets,
                player_profiles,
            )

    st.markdown('<div class="section-spacer"></div>', unsafe_allow_html=True)
    with st.expander("Methodology and safeguards"):
        st.write(
            "The public board only includes model-backed trade concepts and "
            "exploratory shortlist concepts. Manual-context ideas, held "
            "concepts, and protected-player blockbusters remain outside the "
            "public recommendation cards."
        )
        for disclaimer in methodology.get("disclaimers", []):
            st.write(f"- {disclaimer}")

    st.sidebar.divider()
    st.sidebar.caption(
        f"Data contract: {bundle.get('data_contract_version', 'unknown')}"
    )
    st.sidebar.caption(
        f"Visual assets: {visual_assets.get('release_name', 'unknown')}"
    )


def run_self_test(
    bundle_path: Path | None,
    asset_path: Path | None,
    profile_path: Path | None,
) -> int:
    bundle_file = bundle_path or (
        Path("/mnt/data") / BUNDLE_FILENAME
    )
    bundle = load_json(str(bundle_file), bundle_file.stat().st_mtime_ns)

    teams = sorted(bundle.get("team_status_by_team", {}))
    rows = [
        row
        for team in teams
        for row in recommendations_for_team(bundle, team)
    ]

    tests = {
        "team_count_is_30": len(teams) == 30,
        "recommendation_rows_are_12": len(rows) == 12,
        "production_label_is_trade_concept": any(
            row["display_tier"] == "Model-backed trade concept"
            for row in rows
        ),
        "player_name_normalization": (
            normalized_name("Nikola Jović") == "nikola jovic"
        ),
        "team_colors_cover_30": len(TEAM_COLORS) == 30,
        "empty_state_supported": (
            recommendations_for_team(bundle, "CHA") == []
        ),
        "selected_team_rows_do_not_leak_counterpart_perspectives": all(
            row.get("recommendation_team") == team
            for team in teams
            for row in recommendations_for_team(bundle, team)
        ),
        "candidate_ids_unique_within_each_team": all(
            len(
                {
                    row.get("optimizer_candidate_id")
                    for row in recommendations_for_team(bundle, team)
                }
            )
            == len(recommendations_for_team(bundle, team))
            for team in teams
        ),
        "okc_only_exposes_exploratory_filter": (
            available_confidence_tiers(
                recommendations_for_team(bundle, "OKC")
            )
            == ["Exploratory strategy shortlist"]
        ),
        "bkn_only_exposes_model_backed_filter": (
            available_confidence_tiers(
                recommendations_for_team(bundle, "BKN")
            )
            == ["Model-backed trade concept"]
        ),
        "impossible_team_tier_selection_removed": all(
            len(available_confidence_tiers(
                recommendations_for_team(bundle, team)
            )) >= 1
            for team in teams
            if recommendations_for_team(bundle, team)
        ),
        "recommendation_renderer_receives_player_profiles": (
            "render_recommendation(\n"
            "                st,\n"
            "                row,\n"
            "                visual_assets,\n"
            "                player_profiles,\n"
            "            )"
            in Path(__file__).read_text(encoding="utf-8")
        ),
    }

    if asset_path is not None:
        assets = load_json(str(asset_path), asset_path.stat().st_mtime_ns)
        tests["asset_team_count_is_30"] = (
            len(assets.get("teams", {})) == 30
        )
        tests["all_app_players_resolved"] = (
            assets.get("counts", {}).get("unresolved_players") == 0
        )

    if profile_path is not None:
        profiles = load_json(
            str(profile_path),
            profile_path.stat().st_mtime_ns,
        )
        tests["player_profiles_resolved"] = (
            profiles.get("counts", {}).get("unresolved_players") == 0
        )
        tests["player_profiles_have_familiar_stats"] = all(
            row.get("points_per_game") is not None
            and row.get("rebounds_per_game") is not None
            and row.get("assists_per_game") is not None
            and row.get("true_shooting_pct") is not None
            for row in profiles.get("players", {}).values()
        )
        tests["player_ratings_use_one_decimal"] = all(
            round(float(row.get("overall_rating")), 1)
            == float(row.get("overall_rating"))
            for row in profiles.get("players", {}).values()
        )

    print(json.dumps(tests, indent=2))
    return 0 if all(tests.values()) else 1


def main() -> int:
    args = parse_args()
    if args.self_test:
        return run_self_test(
            args.bundle_path,
            args.asset_path,
            args.profile_path,
        )
    render_page()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())