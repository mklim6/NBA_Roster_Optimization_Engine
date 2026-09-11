"""Streamlit Player Ratings page for the NBA Front Office Decision Suite.

Install as:
    pages/2_Player_Ratings.py

Run the full multipage app with:
    streamlit run Home.py

Self-test:
    python pages/2_Player_Ratings.py --self-test
"""

from __future__ import annotations

import argparse
import html
import json
import math
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from nba_current_reference_overlay_v1 import (  # noqa: E402
    CurrentReferenceOverlayError,
    load_current_reference_overlay,
)

SCRIPT_VERSION = "player-ratings-streamlit-v1-4-2026-09-08"
RATINGS_FILENAME = "player_ratings_2026_27_v2.json"

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

TEAM_IDS = {
    "ATL": 1610612737,
    "BOS": 1610612738,
    "CLE": 1610612739,
    "NOP": 1610612740,
    "CHI": 1610612741,
    "DAL": 1610612742,
    "DEN": 1610612743,
    "GSW": 1610612744,
    "HOU": 1610612745,
    "LAC": 1610612746,
    "LAL": 1610612747,
    "MIA": 1610612748,
    "MIL": 1610612749,
    "MIN": 1610612750,
    "BKN": 1610612751,
    "NYK": 1610612752,
    "ORL": 1610612753,
    "IND": 1610612754,
    "PHI": 1610612755,
    "PHX": 1610612756,
    "POR": 1610612757,
    "SAC": 1610612758,
    "SAS": 1610612759,
    "OKC": 1610612760,
    "TOR": 1610612761,
    "UTA": 1610612762,
    "MEM": 1610612763,
    "WAS": 1610612764,
    "DET": 1610612765,
    "CHA": 1610612766,
}

TEAM_COLORS = {
    "ATL": ("#E03A3E", "#C1D32F"),
    "BOS": ("#007A33", "#BA9653"),
    "BKN": ("#FFFFFF", "#A7A9AC"),
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
    "TOR": ("#CE1141", "#A1A1A4"),
    "UTA": ("#002B5C", "#F9A01B"),
    "WAS": ("#002B5C", "#E31837"),
}

RATING_FIELDS = [
    ("Scoring", "scoring_rating", "scoring_grade", "SCO"),
    ("Shooting", "shooting_rating", "shooting_grade", "SHO"),
    ("Playmaking", "playmaking_rating", "playmaking_grade", "PLY"),
    ("Rebounding", "rebounding_rating", "rebounding_grade", "REB"),
    ("Defense", "defense_rating", "defense_grade", "DEF"),
    ("Efficiency", "efficiency_rating", "efficiency_grade", "EFF"),
    ("Availability", "availability_rating", "availability_grade", "AVL"),
]

VALUE_FIELDS = [
    ("Overall", "overall_rating", "overall_grade", "OVR"),
    ("Potential", "potential_rating", "potential_grade", "POT"),
    (
        "Future outlook",
        "future_outlook_rating",
        "future_outlook_grade",
        "FUT",
    ),
    (
        "Contract value",
        "contract_value_rating",
        "contract_value_grade",
        "CV",
    ),
    (
        "Trade value",
        "trade_value_rating",
        "trade_value_grade",
        "TV",
    ),
]

LEADERBOARD_RATINGS = {
    "Overall": "overall_rating",
    "Potential": "potential_rating",
    "Future outlook": "future_outlook_rating",
    "Scoring": "scoring_rating",
    "Shooting": "shooting_rating",
    "Playmaking": "playmaking_rating",
    "Rebounding": "rebounding_rating",
    "Defense": "defense_rating",
    "Efficiency": "efficiency_rating",
    "Availability": "availability_rating",
    "Contract value": "contract_value_rating",
    "Trade value": "trade_value_rating",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Validate helpers and the local ratings release.",
    )
    parser.add_argument(
        "--rating-path",
        type=Path,
        default=None,
        help="Optional explicit path to the ratings JSON.",
    )
    return parser.parse_args()


def escaped(value: Any) -> str:
    if value is None:
        return ""
    return html.escape(str(value), quote=True)


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def percentage_text(value: Any) -> str:
    number = safe_float(value, math.nan)
    if not math.isfinite(number):
        return "—"
    if abs(number) <= 1.0:
        number *= 100.0
    return f"{number:.1f}%"


def number_text(value: Any, decimals: int = 1) -> str:
    number = safe_float(value, math.nan)
    if not math.isfinite(number):
        return "—"
    return f"{number:.{decimals}f}"


def money_text(value: Any) -> str:
    number = safe_float(value, math.nan)
    if not math.isfinite(number):
        return "—"
    if abs(number) >= 1_000_000:
        return f"${number / 1_000_000:.1f}M"
    if abs(number) >= 1_000:
        return f"${number / 1_000:.0f}K"
    return f"${number:,.0f}"


def normalize_player_id(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if text.endswith(".0") and text[:-2].isdigit():
        return text[:-2]
    return text


def player_headshot_url(player_id: Any) -> str:
    normalized = normalize_player_id(player_id)
    return (
        "https://cdn.nba.com/headshots/nba/latest/"
        f"260x190/{normalized}.png"
    )


def team_logo_url(team: str) -> str:
    team_id = TEAM_IDS.get(team)
    if not team_id:
        return ""
    return (
        f"https://cdn.nba.com/logos/nba/{team_id}/"
        "global/L/logo.svg"
    )


def branding_team(record: dict[str, Any]) -> str:
    display = str(record.get("display_team_abbreviation", "")).strip().upper()
    if display and display not in {"FA", "FREE AGENT", "NONE", "NAN"}:
        return display
    return str(record.get("team_abbreviation", "")).strip().upper()


def roster_status_text(record: dict[str, Any]) -> str:
    status = str(record.get("roster_status", "")).strip()
    return status or (
        "Free agent"
        if str(record.get("team_abbreviation", "")).strip().upper() == "FA"
        else "Under contract"
    )


def team_display_line(record: dict[str, Any]) -> str:
    team = branding_team(record)
    team_name = str(record.get("display_team_name", "")).strip() or TEAM_NAMES.get(team, team)
    status = roster_status_text(record)
    if status.lower() == "free agent":
        return f"{team_name} · Free Agent"
    return team_name


def rating_bar_width(value: Any) -> float:
    rating = safe_float(value, 60.0)
    return float(
        max(0.0, min(100.0, 100.0 * (rating - 60.0) / 39.5))
    )


def rating_band(value: Any) -> str:
    rating = safe_float(value, 60.0)
    if rating >= 97.0:
        return "generational"
    if rating >= 93.0:
        return "elite"
    if rating >= 90.0:
        return "allstar"
    if rating >= 87.0:
        return "highstarter"
    if rating >= 83.0:
        return "starter"
    if rating >= 79.0:
        return "rotation"
    return "depth"


def locate_ratings_file(explicit: Path | None = None) -> Path:
    if explicit is not None:
        candidate = explicit.expanduser().resolve()
        if candidate.exists():
            return candidate
        raise FileNotFoundError(f"Ratings file not found: {candidate}")

    script_path = Path(__file__).resolve()
    candidates = [
        script_path.parents[1] / "app_data" / RATINGS_FILENAME,
        Path.cwd() / "app_data" / RATINGS_FILENAME,
        script_path.parent / RATINGS_FILENAME,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate

    raise FileNotFoundError(
        "Could not locate the approved player ratings release. Checked:\n"
        + "\n".join(str(path) for path in candidates)
    )


def load_release(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    players = payload.get("players_by_id")
    if not isinstance(players, dict) or not players:
        raise ValueError(
            "Ratings JSON is missing a nonempty players_by_id mapping."
        )
    return payload


def player_records(payload: dict[str, Any]) -> list[dict[str, Any]]:
    records = []
    for player_id, raw in payload["players_by_id"].items():
        record = dict(raw)
        record["player_id"] = normalize_player_id(
            record.get("player_id", player_id)
        )
        records.append(record)
    return sorted(
        records,
        key=lambda row: (
            safe_int(row.get("league_overall_rank"), 9999),
            str(row.get("player_name", "")),
        ),
    )


def player_label(record: dict[str, Any]) -> str:
    team = str(record.get("team_abbreviation", "")).strip()
    rank = safe_int(record.get("league_overall_rank"), 0)
    rank_text = f"#{rank} · " if rank else ""
    return (
        f"{rank_text}{record.get('player_name', 'Unknown')} "
        f"({team or 'FA'})"
    )


def records_by_id(
    records: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    return {
        normalize_player_id(record.get("player_id")): record
        for record in records
    }


def team_filter_label(team: str) -> str:
    if team == "All teams":
        return team
    if team == "FA":
        return "Free agents (FA)"
    return f"{TEAM_NAMES.get(team, team)} ({team})"


def sorted_teams(records: list[dict[str, Any]]) -> list[str]:
    represented = {
        str(record.get("team_abbreviation", "")).strip().upper()
        for record in records
        if str(record.get("team_abbreviation", "")).strip()
    }
    return sorted(
        represented,
        key=lambda team: TEAM_NAMES.get(team, team),
    )


def render_current_reference(st: Any, records: list[dict[str, Any]]) -> None:
    import pandas as pd

    st.markdown("## Current NBA reference changes")
    st.caption(
        "Confirmed roster-affiliation changes through September 7, 2026. "
        "This is a read-only real-world reference layer; it does not alter the "
        "April 12 Franchise Mode scenario or its saved checkpoint."
    )
    try:
        overlay = load_current_reference_overlay()
    except CurrentReferenceOverlayError as exc:
        st.error(f"The current-reference snapshot failed validation: {exc}")
        return

    names = {
        normalize_player_id(record.get("player_id")): str(record.get("player_name", "")).strip()
        for record in records
    }
    rows = []
    for player_id, current in overlay.items():
        slug_name = str(current.get("player_slug", "")).replace("-", " ").title()
        rows.append({
            "Date": current.get("latest_event_date", ""),
            "Player": names.get(player_id) or slug_name or player_id,
            "NBA ID": player_id,
            "Current team": current.get("current_reference_team") or "FA",
            "Status": str(current.get("current_reference_status", "")).replace("_", " ").title(),
            "Latest action": str(current.get("contract_reference_action", "")).replace("_", " ").title(),
            "Description": current.get("latest_description", ""),
            "Source": current.get("source_name", ""),
        })

    status_options = sorted({row["Status"] for row in rows})
    team_options = sorted({row["Current team"] for row in rows})
    f1, f2 = st.columns(2)
    selected_status = f1.multiselect(
        "Reference status",
        status_options,
        default=status_options,
        key="ratings_current_reference_status",
    )
    selected_teams = f2.multiselect(
        "Current team",
        team_options,
        default=team_options,
        key="ratings_current_reference_team",
    )
    visible = [
        row for row in rows
        if row["Status"] in selected_status and row["Current team"] in selected_teams
    ]
    visible.sort(key=lambda row: (row["Date"], row["Player"]), reverse=True)

    c1, c2, c3 = st.columns(3)
    c1.metric("Players in snapshot", len(rows))
    c2.metric("Visible", len(visible))
    c3.metric("Reference cutoff", "Sep. 7, 2026")
    st.dataframe(
        pd.DataFrame(visible),
        use_container_width=True,
        hide_index=True,
        column_config={
            "Description": st.column_config.TextColumn(width="large"),
            "Source": st.column_config.TextColumn(width="medium"),
        },
    )


def top_player_for_team(
    records: list[dict[str, Any]],
    team: str,
) -> dict[str, Any] | None:
    candidates = [
        record
        for record in records
        if str(record.get("team_abbreviation", "")).upper() == team
    ]
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda row: safe_int(
            row.get("league_overall_rank"),
            9999,
        ),
    )


def split_pipe(value: Any) -> list[str]:
    if value is None:
        return []
    return [
        item.strip()
        for item in str(value).split("|")
        if item.strip()
    ]


def development_class(direction: Any) -> str:
    normalized = str(direction or "").strip().lower()
    if normalized == "rising":
        return "rising"
    if normalized == "declining":
        return "declining"
    return "stable"


def team_colors(team: str) -> tuple[str, str]:
    return TEAM_COLORS.get(team, ("#38BDF8", "#F8FAFC"))


def render_global_css(st: Any) -> None:
    st.markdown(
        """
<style>
:root {
    --page-bg:#050A13;
    --panel:#0B1220;
    --panel-soft:#111A2B;
    --border:rgba(148,163,184,.18);
    --text:#F8FAFC;
    --muted:#94A3B8;
    --blue:#38BDF8;
    --gold:#FBBF24;
    --green:#34D399;
    --red:#FB7185;
}
.stApp {
    background:
        radial-gradient(circle at 13% 3%, rgba(30,64,175,.18), transparent 24rem),
        radial-gradient(circle at 85% 11%, rgba(14,165,233,.12), transparent 29rem),
        linear-gradient(180deg, #07101E 0%, #050A13 48%, #04070D 100%);
    color:var(--text);
}
.block-container {
    max-width:1420px;
    padding-top:2.2rem;
    padding-bottom:4rem;
}
[data-testid="stSidebar"] {
    background:
        linear-gradient(180deg, rgba(9,16,30,.98), rgba(5,10,19,.98));
    border-right:1px solid rgba(148,163,184,.13);
}
.hero-kicker {
    color:#7DD3FC;
    display:inline-block;
    font-size:.76rem;
    font-weight:800;
    letter-spacing:.14em;
    text-transform:uppercase;
    margin-bottom:.55rem;
}
.hero-title {
    color:#F8FAFC;
    font-size:clamp(2.25rem,4vw,4.1rem);
    font-weight:900;
    line-height:1.02;
    letter-spacing:-.045em;
    margin:0;
}
.hero-subtitle {
    color:#A8B5C8;
    max-width:850px;
    font-size:1.06rem;
    line-height:1.7;
    margin:.85rem 0 1.65rem;
}
.kpi-grid {
    display:grid;
    grid-template-columns:repeat(4,minmax(0,1fr));
    gap:.8rem;
    margin:1rem 0 1.65rem;
}
.kpi-card {
    border:1px solid var(--border);
    border-radius:18px;
    padding:1rem 1.1rem;
    background:linear-gradient(145deg,rgba(15,23,42,.92),rgba(9,15,27,.9));
    box-shadow:0 12px 32px rgba(0,0,0,.16);
}
.kpi-label {
    color:#93A4BA;
    display:block;
    font-size:.76rem;
    font-weight:750;
    letter-spacing:.07em;
    text-transform:uppercase;
}
.kpi-card strong {
    display:block;
    color:#F8FAFC;
    font-size:1.7rem;
    margin-top:.22rem;
}
.kpi-note {
    color:#64748B;
    display:block;
    font-size:.76rem;
    margin-top:.18rem;
}
.profile-shell {
    --team-primary:#38BDF8;
    --team-secondary:#F8FAFC;
    position:relative;
    overflow:hidden;
    display:grid;
    grid-template-columns:240px minmax(0,1fr) 150px;
    gap:1.4rem;
    align-items:center;
    min-height:280px;
    border:1px solid color-mix(in srgb,var(--team-primary) 45%,transparent);
    border-radius:28px;
    padding:1.35rem 1.5rem;
    background:
        radial-gradient(circle at 8% 40%,color-mix(in srgb,var(--team-primary) 27%,transparent),transparent 19rem),
        radial-gradient(circle at 93% 15%,color-mix(in srgb,var(--team-secondary) 13%,transparent),transparent 18rem),
        linear-gradient(135deg,rgba(13,22,39,.98),rgba(6,11,20,.98));
    box-shadow:0 24px 70px rgba(0,0,0,.28);
}
.profile-shell::after {
    content:"";
    position:absolute;
    inset:auto -90px -145px auto;
    width:360px;
    height:360px;
    border-radius:50%;
    border:55px solid color-mix(in srgb,var(--team-primary) 8%,transparent);
}
.headshot-wrap {
    position:relative;
    align-self:end;
    min-height:238px;
}
.headshot-wrap img.player-headshot {
    position:absolute;
    inset:auto 0 -1.35rem 0;
    width:238px;
    height:auto;
    object-fit:contain;
    filter:drop-shadow(0 16px 20px rgba(0,0,0,.42));
    z-index:2;
}
.headshot-backdrop {
    position:absolute;
    width:205px;
    height:205px;
    left:15px;
    bottom:8px;
    border-radius:50%;
    background:
        radial-gradient(circle,color-mix(in srgb,var(--team-primary) 38%,transparent),transparent 70%);
    border:1px solid color-mix(in srgb,var(--team-primary) 30%,transparent);
}
.player-copy {
    position:relative;
    z-index:2;
}
.team-line {
    display:flex;
    align-items:center;
    gap:.65rem;
    color:#BAC7D8;
    font-weight:700;
    font-size:.9rem;
}
.team-line img {
    width:42px;
    height:42px;
    object-fit:contain;
}
.player-name {
    margin:.35rem 0 .28rem;
    color:#FFFFFF;
    font-size:clamp(2rem,4vw,3.5rem);
    font-weight:900;
    letter-spacing:-.045em;
    line-height:1;
}
.player-role {
    color:#C9D5E5;
    font-size:1.02rem;
    font-weight:650;
}
.player-archetype {
    color:var(--team-secondary);
    font-size:.92rem;
    font-weight:800;
    margin-top:.28rem;
}
.chip-row {
    display:flex;
    flex-wrap:wrap;
    gap:.45rem;
    margin-top:1rem;
}
.info-chip {
    border:1px solid rgba(148,163,184,.18);
    background:rgba(15,23,42,.72);
    border-radius:999px;
    color:#CBD5E1;
    padding:.34rem .62rem;
    font-size:.76rem;
    font-weight:700;
}
.info-chip.development-rising {
    color:#6EE7B7;
    border-color:rgba(52,211,153,.32);
}
.info-chip.development-declining {
    color:#FDA4AF;
    border-color:rgba(251,113,133,.32);
}
.info-chip.development-stable {
    color:#BAE6FD;
    border-color:rgba(56,189,248,.28);
}
.overall-panel {
    position:relative;
    z-index:3;
    text-align:center;
    border:1px solid color-mix(in srgb,var(--team-primary) 38%,transparent);
    border-radius:24px;
    padding:1rem .7rem;
    background:rgba(3,7,18,.7);
    backdrop-filter:blur(10px);
}
.overall-label {
    color:#94A3B8;
    font-size:.76rem;
    font-weight:850;
    letter-spacing:.15em;
}
.overall-number {
    color:#FFFFFF;
    font-size:3.35rem;
    line-height:1;
    font-weight:950;
    margin:.28rem 0;
}
.overall-grade {
    display:inline-block;
    padding:.23rem .55rem;
    border-radius:999px;
    color:#07101E;
    background:var(--team-secondary);
    font-size:.8rem;
    font-weight:900;
}
.overall-rank {
    color:#A8B5C8;
    font-size:.75rem;
    margin-top:.7rem;
}
.stat-strip {
    display:grid;
    grid-template-columns:repeat(7,minmax(0,1fr));
    gap:.65rem;
    margin:1rem 0 1.3rem;
}
.stat-tile {
    border:1px solid var(--border);
    border-radius:15px;
    background:rgba(10,18,32,.84);
    padding:.75rem .7rem;
    text-align:center;
}
.stat-tile strong {
    color:#F8FAFC;
    display:block;
    font-size:1.04rem;
}
.stat-tile span {
    color:#718096;
    display:block;
    font-size:.68rem;
    font-weight:800;
    letter-spacing:.08em;
    margin-top:.18rem;
}
.value-grid {
    display:grid;
    grid-template-columns:repeat(5,minmax(0,1fr));
    gap:.8rem;
    margin:.25rem 0 1.3rem;
}
.value-card {
    border:1px solid var(--border);
    border-radius:18px;
    background:linear-gradient(145deg,rgba(15,23,42,.9),rgba(9,15,27,.88));
    padding:.9rem 1rem;
}
.value-card .value-top {
    display:flex;
    justify-content:space-between;
    align-items:center;
}
.value-card .value-label {
    color:#A8B5C8;
    font-size:.78rem;
    font-weight:760;
}
.value-card .value-abbrev {
    color:#64748B;
    font-size:.68rem;
    font-weight:850;
}
.value-card .value-score {
    color:#F8FAFC;
    font-size:1.82rem;
    font-weight:900;
    line-height:1.1;
    margin-top:.4rem;
}
.value-card .value-grade {
    color:#7DD3FC;
    font-size:.78rem;
    font-weight:800;
}
.section-title {
    color:#F8FAFC;
    font-size:1.45rem;
    font-weight:850;
    letter-spacing:-.02em;
    margin:1.4rem 0 .8rem;
}
.rating-grid {
    display:grid;
    grid-template-columns:repeat(2,minmax(0,1fr));
    gap:.72rem 1rem;
}
.rating-row {
    border:1px solid var(--border);
    border-radius:15px;
    background:rgba(10,18,32,.78);
    padding:.72rem .8rem;
}
.rating-heading {
    display:flex;
    justify-content:space-between;
    align-items:baseline;
    gap:.6rem;
}
.rating-heading span {
    color:#CBD5E1;
    font-size:.82rem;
    font-weight:760;
}
.rating-heading strong {
    color:#F8FAFC;
    font-size:1rem;
}
.rating-heading em {
    color:#7DD3FC;
    font-size:.72rem;
    font-style:normal;
    font-weight:850;
    margin-left:.24rem;
}
.rating-track {
    height:7px;
    background:rgba(71,85,105,.28);
    border-radius:999px;
    overflow:hidden;
    margin-top:.5rem;
}
.rating-fill {
    height:100%;
    border-radius:999px;
    background:linear-gradient(90deg,var(--team-primary),var(--team-secondary));
    box-shadow:0 0 15px color-mix(in srgb,var(--team-primary) 35%,transparent);
}
.insight-grid {
    display:grid;
    grid-template-columns:1fr 1fr;
    gap:.9rem;
    margin:1rem 0;
}
.insight-card {
    border:1px solid var(--border);
    border-radius:18px;
    padding:1rem 1.05rem;
    background:rgba(10,18,32,.8);
}
.insight-card h4 {
    color:#F8FAFC;
    margin:0 0 .55rem;
    font-size:.93rem;
}
.insight-card p {
    color:#A8B5C8;
    margin:.25rem 0;
    line-height:1.55;
    font-size:.84rem;
}
.insight-card.strengths {
    border-color:rgba(52,211,153,.24);
}
.insight-card.concerns {
    border-color:rgba(251,113,133,.22);
}
.compare-header {
    border:1px solid var(--border);
    border-radius:19px;
    padding:1rem;
    text-align:center;
    background:rgba(10,18,32,.82);
}
.compare-header img {
    width:150px;
    height:110px;
    object-fit:contain;
}
.compare-header h3 {
    color:#F8FAFC;
    margin:.25rem 0 .1rem;
    font-size:1.25rem;
}
.compare-header p {
    color:#94A3B8;
    margin:0;
    font-size:.78rem;
}
.compare-rating-row {
    display:grid;
    grid-template-columns:70px minmax(0,1fr) 135px minmax(0,1fr) 70px;
    gap:.7rem;
    align-items:center;
    margin:.7rem 0;
}
.compare-rating-row .left-score {
    text-align:right;
}
.compare-rating-row .right-score {
    text-align:left;
}
.compare-rating-row .metric-label {
    text-align:center;
    color:#CBD5E1;
    font-size:.76rem;
    font-weight:800;
}
.compare-rating-row strong {
    color:#F8FAFC;
    font-size:.96rem;
}
.compare-track {
    height:8px;
    background:rgba(71,85,105,.28);
    border-radius:999px;
    overflow:hidden;
}
.compare-fill-left {
    height:100%;
    margin-left:auto;
    background:linear-gradient(90deg,#0EA5E9,#7DD3FC);
    border-radius:999px;
}
.compare-fill-right {
    height:100%;
    background:linear-gradient(90deg,#FBBF24,#FB7185);
    border-radius:999px;
}
.compare-leader {
    color:#34D399;
    font-size:.7rem;
    font-weight:850;
}
.method-note {
    border-left:3px solid #38BDF8;
    padding:.8rem 1rem;
    background:rgba(14,165,233,.07);
    color:#A8B5C8;
    font-size:.82rem;
    line-height:1.55;
    margin-top:1rem;
}
@media (max-width:1000px) {
    .profile-shell {
        grid-template-columns:190px minmax(0,1fr);
    }
    .value-grid {
        grid-template-columns:repeat(3,minmax(0,1fr));
    }
    .overall-panel {
        grid-column:1/-1;
    }
    .stat-strip {
        grid-template-columns:repeat(4,minmax(0,1fr));
    }
}
@media (max-width:760px) {
    .kpi-grid,.value-grid,.rating-grid,.insight-grid {
        grid-template-columns:1fr;
    }
    .profile-shell {
        grid-template-columns:1fr;
        text-align:center;
    }
    .headshot-wrap {
        min-height:180px;
    }
    .headshot-wrap img.player-headshot {
        left:50%;
        transform:translateX(-50%);
    }
    .headshot-backdrop {
        left:50%;
        transform:translateX(-50%);
    }
    .team-line,.chip-row {
        justify-content:center;
    }
    .stat-strip {
        grid-template-columns:repeat(2,minmax(0,1fr));
    }
    .compare-rating-row {
        grid-template-columns:48px minmax(0,1fr) 70px minmax(0,1fr) 48px;
        gap:.35rem;
    }
}
</style>
""",
        unsafe_allow_html=True,
    )


def render_kpis(st: Any, payload: dict[str, Any], records: list[dict[str, Any]]) -> None:
    elite = sum(
        safe_float(record.get("overall_rating")) >= 93.0
        for record in records
    )
    all_star = sum(
        safe_float(record.get("overall_rating")) >= 90.0
        for record in records
    )
    median = sorted(
        safe_float(record.get("overall_rating"))
        for record in records
    )[len(records) // 2]
    teams = len(sorted_teams(records))

    st.markdown(
        f"""
<div class="kpi-grid">
  <div class="kpi-card">
    <span class="kpi-label">Players rated</span>
    <strong>{len(records):,}</strong>
    <span class="kpi-note">League-wide refined release</span>
  </div>
  <div class="kpi-card">
    <span class="kpi-label">Elite players</span>
    <strong>{elite}</strong>
    <span class="kpi-note">93.0 OVR or higher</span>
  </div>
  <div class="kpi-card">
    <span class="kpi-label">All-Star range</span>
    <strong>{all_star}</strong>
    <span class="kpi-note">90.0 OVR or higher</span>
  </div>
  <div class="kpi-card">
    <span class="kpi-label">League median</span>
    <strong>{median:.1f}</strong>
    <span class="kpi-note">{teams} teams represented</span>
  </div>
</div>
""",
        unsafe_allow_html=True,
    )


def render_player_profile(st: Any, player: dict[str, Any]) -> None:
    team = branding_team(player)
    roster_status = roster_status_text(player)
    primary, secondary = team_colors(team)
    logo = team_logo_url(team)
    headshot = player_headshot_url(player.get("player_id"))
    direction = str(player.get("development_direction", "Stable"))
    direction_css = development_class(direction)

    rank = safe_int(player.get("league_overall_rank"))
    team_rank = safe_int(player.get("team_overall_rank"))
    age = number_text(player.get("age"), 0)
    confidence = str(player.get("rating_confidence", ""))
    role = str(player.get("role_label", ""))
    archetype = str(player.get("archetype", ""))
    development_arrow = str(player.get("development_arrow", "→"))

    st.markdown(
        f"""
<div class="profile-shell"
     style="--team-primary:{primary};--team-secondary:{secondary};">
  <div class="headshot-wrap">
    <div class="headshot-backdrop"></div>
    <img class="player-headshot" src="{escaped(headshot)}"
         alt="{escaped(player.get('player_name'))}">
  </div>
  <div class="player-copy">
    <div class="team-line">
      <img src="{escaped(logo)}" alt="{escaped(team)} logo">
      <span>{escaped(team_display_line(player))}</span>
    </div>
    <h2 class="player-name">{escaped(player.get("player_name"))}</h2>
    <div class="player-role">{escaped(role)}</div>
    <div class="player-archetype">{escaped(archetype)}</div>
    <div class="chip-row">
      <span class="info-chip">League rank #{rank}</span>
      {('<span class="info-chip">Free agent</span>' if roster_status.lower() == 'free agent' else f'<span class="info-chip">Team rank #{team_rank}</span>')}
      <span class="info-chip">Age {escaped(age)}</span>
      <span class="info-chip">Confidence {escaped(confidence)}</span>
      <span class="info-chip development-{direction_css}">
        {escaped(development_arrow)} {escaped(direction)}
      </span>
    </div>
  </div>
  <div class="overall-panel">
    <div class="overall-label">OVERALL</div>
    <div class="overall-number">{safe_float(player.get("overall_rating")):.1f}</div>
    <div class="overall-grade">{escaped(player.get("overall_grade"))}</div>
    <div class="overall-rank">#{rank} in the league</div>
  </div>
</div>
""",
        unsafe_allow_html=True,
    )

    stat_values = [
        ("PPG", number_text(player.get("points_per_game"))),
        ("RPG", number_text(player.get("rebounds_per_game"))),
        ("APG", number_text(player.get("assists_per_game"))),
        ("TS%", percentage_text(player.get("true_shooting_pct"))),
        ("3P%", percentage_text(player.get("three_point_pct"))),
        ("MPG", number_text(player.get("minutes_per_game"))),
        ("GP", number_text(player.get("games_played"), 0)),
    ]
    stat_html = "".join(
        (
            '<div class="stat-tile">'
            f"<strong>{escaped(value)}</strong>"
            f"<span>{escaped(label)}</span>"
            "</div>"
        )
        for label, value in stat_values
    )
    st.markdown(
        f'<div class="stat-strip">{stat_html}</div>',
        unsafe_allow_html=True,
    )

    value_cards = []
    for label, field, grade_field, abbreviation in VALUE_FIELDS:
        value_cards.append(
            f"""
<div class="value-card">
  <div class="value-top">
    <span class="value-label">{escaped(label)}</span>
    <span class="value-abbrev">{escaped(abbreviation)}</span>
  </div>
  <div class="value-score">{safe_float(player.get(field)):.1f}</div>
  <div class="value-grade">{escaped(player.get(grade_field))}</div>
</div>
"""
        )
    st.markdown(
        '<div class="value-grid">'
        + "".join(value_cards)
        + "</div>",
        unsafe_allow_html=True,
    )

    st.markdown(
        '<h3 class="section-title">Basketball ratings</h3>',
        unsafe_allow_html=True,
    )
    rows = []
    for label, field, grade_field, abbreviation in RATING_FIELDS:
        rating = safe_float(player.get(field), 60.0)
        width = rating_bar_width(rating)
        rows.append(
            f"""
<div class="rating-row">
  <div class="rating-heading">
    <span>{escaped(label)} <em>{escaped(abbreviation)}</em></span>
    <strong>{rating:.1f} · {escaped(player.get(grade_field))}</strong>
  </div>
  <div class="rating-track">
    <div class="rating-fill" style="width:{width:.2f}%"></div>
  </div>
</div>
"""
        )
    st.markdown(
        f"""
<div class="rating-grid"
     style="--team-primary:{primary};--team-secondary:{secondary};">
  {''.join(rows)}
</div>
""",
        unsafe_allow_html=True,
    )

    strengths = split_pipe(player.get("strengths"))
    concerns = split_pipe(player.get("concerns"))
    strength_text = "".join(
        f"<p>✓ {escaped(item)}</p>" for item in strengths
    ) or "<p>No standout strength label available.</p>"
    concern_text = "".join(
        f"<p>• {escaped(item)}</p>" for item in concerns
    ) or "<p>No major concern label available.</p>"

    st.markdown(
        f"""
<div class="insight-grid">
  <div class="insight-card strengths">
    <h4>Strengths</h4>
    {strength_text}
  </div>
  <div class="insight-card concerns">
    <h4>Concerns and context</h4>
    {concern_text}
  </div>
</div>
""",
        unsafe_allow_html=True,
    )

    peak_season = player.get("future_peak_season")
    st.markdown(
        f"""
<div class="method-note">
  <strong>Development outlook:</strong>
  {escaped(direction)} with a modeled peak season of
  {escaped(peak_season if peak_season is not None else "not available")}.
  OVR measures current on-court value. POT is career ceiling and cannot be
  below OVR. Future Outlook is the model's projected future standing, so it
  may be lower for aging or declining players. Contract value and trade value
  remain separate from basketball ability.
</div>
""",
        unsafe_allow_html=True,
    )


def filtered_leaderboard(
    records: list[dict[str, Any]],
    team: str,
    rating_field: str,
    minimum_rating: float,
    limit: int,
) -> list[dict[str, Any]]:
    filtered = [
        record
        for record in records
        if (
            team == "All teams"
            or str(record.get("team_abbreviation", "")).upper() == team
        )
        and safe_float(record.get(rating_field)) >= minimum_rating
    ]
    return sorted(
        filtered,
        key=lambda row: (
            -safe_float(row.get(rating_field)),
            safe_int(row.get("league_overall_rank"), 9999),
            str(row.get("player_name", "")),
        ),
    )[:limit]


def leaderboard_frame(rows: list[dict[str, Any]], rating_field: str) -> Any:
    import pandas as pd

    output = pd.DataFrame(
        [
            {
                "Rank": safe_int(row.get("league_overall_rank")),
                "Player": row.get("player_name", ""),
                "Team": row.get("team_abbreviation", ""),
                "Age": safe_float(row.get("age"), math.nan),
                "OVR": safe_float(row.get("overall_rating"), math.nan),
                "POT": safe_float(row.get("potential_rating"), math.nan),
                "CV": safe_float(
                    row.get("contract_value_rating"),
                    math.nan,
                ),
                "TV": safe_float(
                    row.get("trade_value_rating"),
                    math.nan,
                ),
                "Selected rating": safe_float(
                    row.get(rating_field),
                    math.nan,
                ),
                "Role": row.get("role_label", ""),
                "Archetype": row.get("archetype", ""),
                "Development": (
                    f"{row.get('development_arrow', '')} "
                    f"{row.get('development_direction', '')}"
                ).strip(),
            }
            for row in rows
        ]
    )
    return output


def render_leaderboard(st: Any, records: list[dict[str, Any]]) -> None:
    st.markdown(
        '<h3 class="section-title">League leaderboard</h3>',
        unsafe_allow_html=True,
    )

    teams = ["All teams", *sorted_teams(records)]
    controls = st.columns([1.3, 1.3, 1, 1])
    with controls[0]:
        selected_team = st.selectbox(
            "Team",
            teams,
            format_func=team_filter_label,
            key="ratings_leaderboard_team",
        )
    with controls[1]:
        selected_category = st.selectbox(
            "Rank by",
            list(LEADERBOARD_RATINGS),
            key="ratings_leaderboard_category",
        )
    with controls[2]:
        minimum = st.slider(
            "Minimum rating",
            min_value=60.0,
            max_value=99.0,
            value=70.0,
            step=1.0,
            key="ratings_leaderboard_minimum",
        )
    with controls[3]:
        limit = st.selectbox(
            "Rows",
            [10, 25, 50, 100, 250, 582],
            index=2,
            key="ratings_leaderboard_limit",
        )

    rating_field = LEADERBOARD_RATINGS[selected_category]
    rows = filtered_leaderboard(
        records,
        selected_team,
        rating_field,
        minimum,
        limit,
    )
    frame = leaderboard_frame(rows, rating_field)

    st.caption(
        f"{len(frame):,} players shown · ranked by {selected_category.lower()}"
    )
    st.dataframe(
        frame,
        hide_index=True,
        width="stretch",
        height=min(900, 92 + 35 * max(len(frame), 1)),
        column_config={
            "Rank": st.column_config.NumberColumn(format="#%d"),
            "Age": st.column_config.NumberColumn(format="%.0f"),
            "OVR": st.column_config.NumberColumn(format="%.1f"),
            "POT": st.column_config.NumberColumn(format="%.1f"),
            "CV": st.column_config.NumberColumn(format="%.1f"),
            "TV": st.column_config.NumberColumn(format="%.1f"),
            "Selected rating": st.column_config.NumberColumn(
                label=selected_category,
                format="%.1f",
            ),
        },
    )

    csv_bytes = frame.to_csv(index=False).encode("utf-8")
    st.download_button(
        "Download filtered rankings",
        data=csv_bytes,
        file_name=(
            f"nba_player_ratings_{selected_category.lower().replace(' ', '_')}.csv"
        ),
        mime="text/csv",
        key="ratings_download_rankings",
    )


def render_compare_header(player: dict[str, Any]) -> str:
    team = branding_team(player)
    return f"""
<div class="compare-header">
  <img src="{escaped(player_headshot_url(player.get('player_id')))}"
       alt="{escaped(player.get('player_name'))}">
  <h3>{escaped(player.get("player_name"))}</h3>
  <p>{escaped(team_display_line(player))} ·
     {safe_float(player.get("overall_rating")):.1f} OVR ·
     #{safe_int(player.get("league_overall_rank"))}</p>
</div>
"""


def comparison_metric_row(
    left: dict[str, Any],
    right: dict[str, Any],
    label: str,
    field: str,
) -> str:
    left_value = safe_float(left.get(field), 60.0)
    right_value = safe_float(right.get(field), 60.0)
    left_width = rating_bar_width(left_value)
    right_width = rating_bar_width(right_value)

    if left_value > right_value:
        left_leader = '<span class="compare-leader">LEADS</span>'
        right_leader = ""
    elif right_value > left_value:
        left_leader = ""
        right_leader = '<span class="compare-leader">LEADS</span>'
    else:
        left_leader = right_leader = (
            '<span class="compare-leader">TIED</span>'
        )

    return f"""
<div class="compare-rating-row">
  <div class="left-score">
    <strong>{left_value:.1f}</strong><br>{left_leader}
  </div>
  <div class="compare-track">
    <div class="compare-fill-left" style="width:{left_width:.2f}%"></div>
  </div>
  <div class="metric-label">{escaped(label)}</div>
  <div class="compare-track">
    <div class="compare-fill-right" style="width:{right_width:.2f}%"></div>
  </div>
  <div class="right-score">
    <strong>{right_value:.1f}</strong><br>{right_leader}
  </div>
</div>
"""


def render_comparison(
    st: Any,
    records: list[dict[str, Any]],
    by_id: dict[str, dict[str, Any]],
) -> None:
    st.markdown(
        '<h3 class="section-title">Compare two players</h3>',
        unsafe_allow_html=True,
    )

    ids = [
        normalize_player_id(record.get("player_id"))
        for record in records
    ]
    label_lookup = {
        normalize_player_id(record.get("player_id")): player_label(record)
        for record in records
    }

    default_left = ids[0]
    default_right = ids[1] if len(ids) > 1 else ids[0]

    selectors = st.columns(2)
    with selectors[0]:
        left_id = st.selectbox(
            "Player one",
            ids,
            index=ids.index(default_left),
            format_func=lambda player_id: label_lookup[player_id],
            key="ratings_compare_left",
        )
    with selectors[1]:
        right_id = st.selectbox(
            "Player two",
            ids,
            index=ids.index(default_right),
            format_func=lambda player_id: label_lookup[player_id],
            key="ratings_compare_right",
        )

    left = by_id[left_id]
    right = by_id[right_id]

    headers = st.columns(2)
    with headers[0]:
        st.markdown(
            render_compare_header(left),
            unsafe_allow_html=True,
        )
    with headers[1]:
        st.markdown(
            render_compare_header(right),
            unsafe_allow_html=True,
        )

    compare_fields = [
        ("Overall", "overall_rating"),
        ("Potential", "potential_rating"),
        ("Future outlook", "future_outlook_rating"),
        ("Scoring", "scoring_rating"),
        ("Shooting", "shooting_rating"),
        ("Playmaking", "playmaking_rating"),
        ("Rebounding", "rebounding_rating"),
        ("Defense", "defense_rating"),
        ("Efficiency", "efficiency_rating"),
        ("Availability", "availability_rating"),
        ("Contract value", "contract_value_rating"),
        ("Trade value", "trade_value_rating"),
    ]
    rows = [
        comparison_metric_row(
            left,
            right,
            label,
            field,
        )
        for label, field in compare_fields
    ]
    st.markdown(
        "".join(rows),
        unsafe_allow_html=True,
    )

    stat_frame = comparison_stats_frame(left, right)
    st.markdown(
        '<h4 class="section-title">Production comparison</h4>',
        unsafe_allow_html=True,
    )
    st.dataframe(
        stat_frame,
        hide_index=True,
        width="stretch",
        column_config={
            str(left.get("player_name")): st.column_config.NumberColumn(
                format="%.1f"
            ),
            str(right.get("player_name")): st.column_config.NumberColumn(
                format="%.1f"
            ),
        },
    )


def comparison_stats_frame(
    left: dict[str, Any],
    right: dict[str, Any],
) -> Any:
    import pandas as pd

    metrics = [
        ("Points per game", "points_per_game", False),
        ("Rebounds per game", "rebounds_per_game", False),
        ("Assists per game", "assists_per_game", False),
        ("True shooting %", "true_shooting_pct", True),
        ("Three-point %", "three_point_pct", True),
        ("Minutes per game", "minutes_per_game", False),
        ("Games played", "games_played", False),
    ]

    rows = []
    for label, field, percentage in metrics:
        left_value = safe_float(left.get(field), math.nan)
        right_value = safe_float(right.get(field), math.nan)
        if percentage:
            if math.isfinite(left_value) and abs(left_value) <= 1.0:
                left_value *= 100.0
            if math.isfinite(right_value) and abs(right_value) <= 1.0:
                right_value *= 100.0
        rows.append(
            {
                "Metric": label,
                str(left.get("player_name")): left_value,
                str(right.get("player_name")): right_value,
            }
        )
    return pd.DataFrame(rows)


def render_methodology(st: Any, payload: dict[str, Any]) -> None:
    with st.expander("Rating methodology and safeguards"):
        st.write(
            "Ratings use a calibrated 60.0–99.9 presentation scale. "
            "The source projections, optimizer values, salary calculations, "
            "and legality checks retain their original full precision."
        )
        st.write(
            "OVR represents current on-court value. POT represents career "
            "ceiling and is never lower than OVR. Future Outlook is the model's "
            "projected future standing and may be lower for aging players. "
            "Contract value and trade value remain separate concepts."
        )
        st.write(
            "Finishing is not published as a standalone rating because the "
            "current audited data does not include direct rim frequency and "
            "rim efficiency."
        )
        release_name = payload.get("release_name", "unknown")
        script_version = payload.get("script_version", "unknown")
        st.caption(
            f"Release: {release_name} · Page: {SCRIPT_VERSION} · "
            f"Rating builder: {script_version}"
        )


def render_page() -> None:
    import streamlit as st

    st.set_page_config(
        page_title="NBA Player Ratings",
        page_icon="🏀",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    render_global_css(st)

    try:
        ratings_path = locate_ratings_file()
        payload = load_release(ratings_path)
        records = player_records(payload)
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as error:
        st.error("The approved player-rating release could not be loaded.")
        st.code(str(error))
        st.stop()

    by_id = records_by_id(records)
    teams = sorted_teams(records)

    st.markdown(
        '<span class="hero-kicker">FRONT OFFICE PLAYER MODEL</span>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<h1 class="hero-title">NBA Player Ratings</h1>',
        unsafe_allow_html=True,
    )
    st.markdown(
        """
<p class="hero-subtitle">
Explore refined player ratings, familiar production statistics, development
outlooks, and the distinction between current performance, potential, contract
value, and trade value.
</p>
""",
        unsafe_allow_html=True,
    )
    render_kpis(st, payload, records)

    st.sidebar.markdown("## Player controls")
    selected_team = st.sidebar.selectbox(
        "Filter player list by team",
        ["All teams", *teams],
        format_func=team_filter_label,
        key="ratings_profile_team",
    )

    available_records = (
        records
        if selected_team == "All teams"
        else [
            record
            for record in records
            if str(record.get("team_abbreviation", "")).upper()
            == selected_team
        ]
    )
    available_ids = [
        normalize_player_id(record.get("player_id"))
        for record in available_records
    ]
    labels = {
        normalize_player_id(record.get("player_id")): player_label(record)
        for record in available_records
    }

    selected_player_id = st.sidebar.selectbox(
        "Select a player",
        available_ids,
        format_func=lambda player_id: labels[player_id],
        key=f"ratings_profile_player_{selected_team}",
    )

    st.sidebar.divider()
    st.sidebar.caption(
        "OVR = current on-court value\n\n"
        "POT = career ceiling\n\n"
        "FUT = projected future standing\n\n"
        "CV = contract value\n\n"
        "TV = trade-market value"
    )

    tabs = st.tabs(
        [
            "Player profile",
            "League rankings",
            "Compare players",
            "Current-reference changes",
        ]
    )

    with tabs[0]:
        render_player_profile(
            st,
            by_id[selected_player_id],
        )

    with tabs[1]:
        render_leaderboard(st, records)

    with tabs[2]:
        render_comparison(st, records, by_id)

    with tabs[3]:
        render_current_reference(st, records)

    render_methodology(st, payload)


def run_self_test(rating_path: Path | None = None) -> int:
    tests: dict[str, bool] = {
        "team_count_is_30": len(TEAM_IDS) == 30,
        "team_names_cover_30": len(TEAM_NAMES) == 30,
        "team_colors_cover_30": len(TEAM_COLORS) == 30,
        "headshot_url": (
            player_headshot_url("203999")
            == "https://cdn.nba.com/headshots/nba/latest/260x190/203999.png"
        ),
        "logo_url": (
            team_logo_url("DEN")
            == "https://cdn.nba.com/logos/nba/1610612743/global/L/logo.svg"
        ),
        "rating_bar_floor": rating_bar_width(60.0) == 0.0,
        "rating_bar_potential_ceiling": math.isclose(
            rating_bar_width(99.5),
            100.0,
        ),
        "rating_bar_current_ceiling_below_full": (
            rating_bar_width(98.2) < 100.0
        ),
        "percentage_decimal_conversion": (
            percentage_text(0.625) == "62.5%"
        ),
        "percentage_whole_preserved": (
            percentage_text(62.5) == "62.5%"
        ),
        "rating_band_elite": rating_band(94.0) == "elite",
    }

    try:
        located = locate_ratings_file(rating_path)
        payload = load_release(located)
        records = player_records(payload)
        by_id = records_by_id(records)
        teams = sorted_teams(records)

        required_fields = {
            "player_id",
            "player_name",
            "team_abbreviation",
            "display_team_abbreviation",
            "roster_status",
            "league_overall_rank",
            "overall_rating",
            "potential_rating",
            "future_outlook_rating",
            "contract_value_rating",
            "trade_value_rating",
            "archetype",
        }

        tests.update(
            {
                "release_is_validated_v4_5_1": (
                    payload.get("release_name")
                    == "player_ratings_2026_27_v4_5_1_role_aware"
                ),
                "player_count_is_582": len(records) == 582,
                "player_ids_unique": len(by_id) == len(records),
                "all_required_fields_present": all(
                    required_fields.issubset(record)
                    for record in records
                ),
                "all_core_ratings_in_range": all(
                    60.0
                    <= safe_float(record.get(field), 0.0)
                    <= {
                        "overall_rating": 98.5,
                        "potential_rating": 99.5,
                        "contract_value_rating": 99.9,
                        "trade_value_rating": 99.9,
                    }[field]
                    for record in records
                    for field in [
                        "overall_rating",
                        "potential_rating",
                        "contract_value_rating",
                        "trade_value_rating",
                    ]
                ),
                "league_rank_complete": {
                    safe_int(record.get("league_overall_rank"))
                    for record in records
                }
                == set(range(1, 583)),
                "thirty_teams_represented": len(teams) == 30,
                "top_player_is_near_97_9": math.isclose(
                    safe_float(records[0].get("overall_rating")),
                    97.9,
                    abs_tol=0.05,
                ),
                "potential_never_below_overall": all(
                    safe_float(record.get("potential_rating"))
                    >= safe_float(record.get("overall_rating"))
                    for record in records
                ),
                "future_outlook_is_present": all(
                    "future_outlook_rating" in record
                    for record in records
                ),
                "elite_population_is_selective": 15 <= sum(
                    safe_float(record.get("overall_rating")) >= 93.0
                    for record in records
                ) <= 35,
                "duren_detroit_branding_when_present": (
                    "1631105" not in by_id
                    or branding_team(by_id["1631105"]) == "DET"
                ),
                "duren_free_agent_status_when_present": (
                    "1631105" not in by_id
                    or roster_status_text(by_id["1631105"]) == "Free agent"
                ),
                "comparison_frame_has_seven_rows": (
                    len(comparison_stats_frame(records[0], records[1]))
                    == 7
                ),
                "wembanyama_potential_near_99_5": (
                    safe_float(
                        next(
                            record.get("potential_rating")
                            for record in records
                            if record.get("player_name")
                            == "Victor Wembanyama"
                        )
                    )
                    >= 99.4
                ),
                "wembanyama_potential_above_kon": (
                    safe_float(
                        next(
                            record.get("potential_rating")
                            for record in records
                            if record.get("player_name")
                            == "Victor Wembanyama"
                        )
                    )
                    >
                    safe_float(
                        next(
                            record.get("potential_rating")
                            for record in records
                            if record.get("player_name")
                            == "Kon Knueppel"
                        )
                    )
                ),
            }
        )
    except Exception:
        tests["ratings_release_loads"] = False

    serializable = {
        key: bool(value)
        for key, value in tests.items()
    }
    print(json.dumps(serializable, indent=2))
    return 0 if all(serializable.values()) else 1


def main() -> int:
    args = parse_args()
    if args.self_test:
        return run_self_test(args.rating_path)

    render_page()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
