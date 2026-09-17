"""Home page for the NBA Front Office Decision Suite.

Recommended location:
    Home.py

Recommended project layout:
    Home.py
    pages/
        1_Trade_Lab.py
    app_data/
        mixed_player_pick_release_2026_27_v1.json
        mixed_player_pick_methodology_2026_27_v1.json
        mixed_trade_visual_assets_2026_27_v1.json

Launch:
    streamlit run Home.py
"""

from __future__ import annotations

import html
import json
import os
import re
import unicodedata
from pathlib import Path
from typing import Any


BUNDLE_FILENAME = "mixed_player_pick_release_2026_27_v1.json"
VISUAL_ASSETS_FILENAME = "mixed_trade_visual_assets_2026_27_v1.json"

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


def escaped(value: Any) -> str:
    return html.escape("" if value is None else str(value))


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


def candidate_project_roots() -> list[Path]:
    current_file = Path(__file__).resolve()
    roots: list[Path] = []

    configured = os.environ.get("NBA_ROSTER_OPTIMIZER_ROOT")
    if configured:
        roots.append(Path(configured).expanduser().resolve())

    roots.extend(
        [
            current_file.parent,
            current_file.parent.parent,
            Path.cwd().resolve(),
        ]
    )

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
        for path in [
            root / "app_data" / filename,
            root / filename,
        ]:
            checked.append(path)
            if path.exists():
                return path

    raise FileNotFoundError(
        f"Could not locate {filename}. Checked:\n"
        + "\n".join(str(path) for path in checked)
    )


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file:
        payload = json.load(file)
    if not isinstance(payload, dict):
        raise ValueError(f"Expected an object in {path}.")
    return payload


def team_logo_url(
    visual_assets: dict[str, Any],
    team: str,
) -> str:
    return str(
        visual_assets
        .get("teams", {})
        .get(team, {})
        .get("logo_url", "")
    ).strip()


def render_logo_strip(
    visual_assets: dict[str, Any],
) -> str:
    logo_cards = []

    for team in sorted(
        TEAM_NAMES,
        key=lambda abbreviation: TEAM_NAMES[abbreviation],
    ):
        logo = team_logo_url(visual_assets, team)
        if not logo:
            continue
        logo_cards.append(
            f"""
<div class="league-logo-cell" title="{escaped(TEAM_NAMES[team])}">
  <img src="{escaped(logo)}" alt="{escaped(TEAM_NAMES[team])} logo">
</div>
"""
        )

    return '<div class="league-logo-strip">' + "".join(logo_cards) + "</div>"


def featured_concept(
    bundle: dict[str, Any],
) -> dict[str, Any] | None:
    recommendations = bundle.get("recommendations_by_team", {})
    if not isinstance(recommendations, dict):
        return None

    preferred_rows = recommendations.get("BKN", [])
    for row in preferred_rows:
        if row.get("display_tier") in {
            "Model-backed trade concept",
            "Model-backed recommendation",
        }:
            return row

    for rows in recommendations.values():
        for row in rows:
            if row.get("display_tier") in {
                "Model-backed trade concept",
                "Model-backed recommendation",
            }:
                return row

    for rows in recommendations.values():
        if rows:
            return rows[0]

    return None


def render_page() -> None:
    import streamlit as st

    st.set_page_config(
        page_title="NBA Franchise Simulator",
        page_icon="🏀",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    # FRANCHISE_PRIMARY_NAV_V1
    from src.franchise_primary_navigation_v1 import render_franchise_primary_navigation_v1
    render_franchise_primary_navigation_v1()

    # FRANCHISE_VISUAL_OVERHAUL_V3
    from src.franchise_visual_overhaul_v3 import (
        inject_home_visual_overhaul_v3,
        render_home_flagship_v3,
    )
    inject_home_visual_overhaul_v3()


    st.markdown(
        """
<style>
.block-container {
    max-width: 1380px;
    padding-top: 2rem;
    padding-bottom: 4rem;
}
.stApp {
    background:
        radial-gradient(circle at 18% 4%, rgba(37,99,235,.14), transparent 32rem),
        radial-gradient(circle at 85% 18%, rgba(14,165,233,.08), transparent 28rem),
        radial-gradient(circle at 50% 90%, rgba(99,102,241,.08), transparent 34rem),
        #070C14;
}
[data-testid="stHeader"] {
    background: rgba(7,12,20,.78);
    backdrop-filter: blur(12px);
}
[data-testid="stSidebar"] {
    min-width: 245px;
    max-width: 245px;
    border-right: 1px solid rgba(148,163,184,.16);
    background:
        linear-gradient(180deg, rgba(15,23,42,.96), rgba(9,14,24,.98));
}
[data-testid="stSidebar"] > div:first-child {
    padding-top: 1rem;
}
[data-testid="stSidebarNav"] {
    padding-top: .25rem;
}
[data-testid="stSidebarNav"] ul {
    gap: .45rem;
}
[data-testid="stSidebarNav"] li {
    margin: 0;
}
[data-testid="stSidebarNav"] a {
    min-height: 46px;
    padding: .72rem .85rem;
    border-radius: 12px;
    border: 1px solid rgba(148,163,184,.10);
    background: rgba(255,255,255,.025);
    transition:
        background .16s ease,
        border-color .16s ease,
        transform .16s ease;
}
[data-testid="stSidebarNav"] a:hover {
    transform: translateX(2px);
    background: rgba(59,130,246,.09);
    border-color: rgba(59,130,246,.24);
}
[data-testid="stSidebarNav"] a[aria-current="page"] {
    background:
        linear-gradient(135deg, rgba(37,99,235,.18), rgba(15,23,42,.44));
    border-color: rgba(96,165,250,.34);
}
[data-testid="stSidebarNav"] span {
    font-size: .90rem;
    font-weight: 700;
}
.hero-shell {
    position:relative;
    overflow:hidden;
    padding:2.4rem 2.4rem 2.2rem;
    border:1px solid rgba(148,163,184,.20);
    border-radius:28px;
    background:
        linear-gradient(135deg, rgba(37,99,235,.18), transparent 42%),
        linear-gradient(145deg, rgba(30,41,59,.85), rgba(15,23,42,.72));
    box-shadow:0 28px 70px rgba(0,0,0,.26);
}
.hero-shell:after {
    content:"";
    position:absolute;
    width:420px;
    height:420px;
    right:-150px;
    top:-180px;
    border-radius:999px;
    background:#2563EB;
    filter:blur(100px);
    opacity:.16;
}
.hero-kicker {
    display:inline-flex;
    align-items:center;
    gap:.45rem;
    margin-bottom:.8rem;
    color:#BFDBFE;
    font-size:.72rem;
    font-weight:800;
    text-transform:uppercase;
    letter-spacing:.13em;
}
.hero-title {
    position:relative;
    z-index:1;
    max-width:900px;
    margin:0;
    font-size:clamp(2.4rem, 5vw, 4.6rem);
    line-height:.98;
    letter-spacing:-.055em;
}
.hero-copy {
    position:relative;
    z-index:1;
    max-width:800px;
    margin:1rem 0 0;
    color:rgba(226,232,240,.76);
    font-size:1.05rem;
    line-height:1.65;
}
.metric-grid {
    display:grid;
    grid-template-columns:repeat(4, minmax(0,1fr));
    gap:.85rem;
    margin:1.25rem 0 1.8rem;
}
.metric-card {
    min-height:112px;
    padding:1rem 1.05rem;
    border:1px solid rgba(148,163,184,.16);
    border-radius:16px;
    background:rgba(15,23,42,.64);
}
.metric-card span {
    display:block;
    color:rgba(203,213,225,.62);
    font-size:.72rem;
}
.metric-card strong {
    display:block;
    margin:.18rem 0 .12rem;
    color:#F8FAFC;
    font-size:1.75rem;
    letter-spacing:-.04em;
}
.metric-card small {
    color:rgba(148,163,184,.62);
}
.section-title {
    margin:2.25rem 0 .85rem;
    font-size:1.7rem;
    letter-spacing:-.03em;
}
.product-grid {
    display:grid;
    grid-template-columns:1.15fr 1fr;
    gap:1rem;
}
.product-card {
    min-height:250px;
    padding:1.4rem;
    border:1px solid rgba(148,163,184,.17);
    border-radius:22px;
    background:
        linear-gradient(145deg, rgba(30,41,59,.72), rgba(15,23,42,.58));
}
.product-card.active {
    background:
        linear-gradient(135deg, rgba(37,99,235,.17), transparent 48%),
        linear-gradient(145deg, rgba(30,41,59,.78), rgba(15,23,42,.62));
}
.product-card.future {
    border-style:dashed;
}
.product-icon {
    display:flex;
    align-items:center;
    justify-content:center;
    width:46px;
    height:46px;
    margin-bottom:.9rem;
    border-radius:14px;
    background:rgba(59,130,246,.14);
    border:1px solid rgba(59,130,246,.25);
    font-size:1.25rem;
}
.product-card h3 {
    margin:.25rem 0 .45rem;
    font-size:1.35rem;
}
.product-card p {
    color:rgba(203,213,225,.70);
    line-height:1.55;
}
.feature-list {
    display:grid;
    gap:.42rem;
    margin-top:1rem;
}
.feature-item {
    color:rgba(226,232,240,.80);
    font-size:.82rem;
}
.featured-shell {
    display:grid;
    grid-template-columns:1.25fr .75fr;
    gap:1rem;
    padding:1.35rem;
    border:1px solid rgba(148,163,184,.16);
    border-radius:22px;
    background:rgba(15,23,42,.62);
}
.featured-shell h3 {
    margin:.3rem 0 .45rem;
    font-size:1.4rem;
}
.featured-shell p {
    color:rgba(203,213,225,.70);
}
.featured-badge {
    display:inline-flex;
    border-radius:999px;
    padding:.28rem .62rem;
    color:#BBF7D0;
    background:rgba(34,197,94,.12);
    border:1px solid rgba(34,197,94,.28);
    font-size:.70rem;
    font-weight:800;
}
.featured-score-grid {
    display:grid;
    grid-template-columns:repeat(2, minmax(0,1fr));
    gap:.65rem;
}
.featured-score {
    padding:.8rem;
    border-radius:14px;
    background:rgba(255,255,255,.035);
    border:1px solid rgba(148,163,184,.12);
}
.featured-score span {
    display:block;
    color:rgba(203,213,225,.58);
    font-size:.68rem;
}
.featured-score strong {
    display:block;
    margin-top:.15rem;
    font-size:1.35rem;
}
.pipeline-grid {
    display:grid;
    grid-template-columns:repeat(5, minmax(0,1fr));
    gap:.7rem;
}
.pipeline-step {
    padding:1rem;
    border-radius:15px;
    border:1px solid rgba(148,163,184,.14);
    background:rgba(15,23,42,.48);
}
.pipeline-step span {
    display:block;
    margin-bottom:.4rem;
    color:#93C5FD;
    font-size:.66rem;
    font-weight:800;
    letter-spacing:.10em;
}
.pipeline-step strong {
    font-size:.85rem;
}
.league-logo-strip {
    display:grid;
    grid-template-columns:repeat(15, minmax(0,1fr));
    gap:.5rem;
    padding:1rem;
    border:1px solid rgba(148,163,184,.12);
    border-radius:20px;
    background:rgba(15,23,42,.42);
}
.league-logo-cell {
    display:flex;
    align-items:center;
    justify-content:center;
    min-height:54px;
    padding:.25rem;
    border-radius:10px;
    transition:transform .18s ease, background .18s ease;
}
.league-logo-cell:hover {
    transform:translateY(-3px);
    background:rgba(255,255,255,.045);
}
.league-logo-cell img {
    width:42px;
    height:42px;
    object-fit:contain;
}
.footer-note {
    margin-top:1.5rem;
    color:rgba(148,163,184,.58);
    font-size:.75rem;
    text-align:center;
}
@media (max-width: 950px) {
    .metric-grid {
        grid-template-columns:repeat(2, minmax(0,1fr));
    }
    .product-grid,
    .featured-shell {
        grid-template-columns:1fr;
    }
    .pipeline-grid {
        grid-template-columns:repeat(2, minmax(0,1fr));
    }
    .league-logo-strip {
        grid-template-columns:repeat(8, minmax(0,1fr));
    }
}
@media (max-width: 560px) {
    .hero-shell {
        padding:1.45rem;
    }
    .metric-grid,
    .pipeline-grid {
        grid-template-columns:1fr;
    }
    .league-logo-strip {
        grid-template-columns:repeat(5, minmax(0,1fr));
    }
}
</style>
""",
        unsafe_allow_html=True,
    )

    try:
        bundle = load_json(locate_app_file(BUNDLE_FILENAME))
        visual_assets = load_json(
            locate_app_file(VISUAL_ASSETS_FILENAME)
        )
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as error:
        st.error("The app release could not be loaded.")
        st.code(str(error))
        st.stop()

    featured = featured_concept(bundle)

    # FRANCHISE_VISUAL_OVERHAUL_V3_HOME_HERO
    render_home_flagship_v3()

    st.markdown(
        """
<div class="hero-shell">
  <span class="hero-kicker">🏆 Flagship franchise management simulator</span>
  <h1 class="hero-title">NBA Franchise Simulator</h1>
  <p class="hero-copy">
    Take control of a persistent NBA universe. Build rosters, manage the cap,
    navigate trades and free agency, draft and develop players, and carry every
    decision across seasons.
  </p>
</div>
""",
        unsafe_allow_html=True,
    )

    st.markdown(
        f"""
<div class="metric-grid">
  <div class="metric-card">
    <span>Deterministic legal packages</span>
    <strong>17,461</strong>
    <small>Across one-for-one and two-for-one structures</small>
  </div>
  <div class="metric-card">
    <span>Canonical app concepts</span>
    <strong>{int(bundle.get("concept_count", 0))}</strong>
    <small>Calibrated for public display</small>
  </div>
  <div class="metric-card">
    <span>Team perspectives</span>
    <strong>{int(bundle.get("recommendation_count", 0))}</strong>
    <small>Each side scored independently</small>
  </div>
  <div class="metric-card">
    <span>League teams covered</span>
    <strong>{int(bundle.get("team_count", 0))}</strong>
    <small>Every team receives an explicit model status</small>
  </div>
</div>
""",
        unsafe_allow_html=True,
    )

    st.markdown(
        '<h2 class="section-title">Flagship experience and supporting tools</h2>',
        unsafe_allow_html=True,
    )

    st.markdown(
        """
<div class="product-grid">
  <div class="product-card active">
    <div class="product-icon">⇄</div>
    <span class="hero-kicker">Supporting analytics tool</span>
    <h3>Trade Lab</h3>
    <p>
      Explore legal mixed player-and-pick concepts, compare each side of the
      transaction, and see how the move fits a team's modeled direction.
    </p>
    <div class="feature-list">
      <span class="feature-item">✓ Deterministic CBA legality</span>
      <span class="feature-item">✓ Team-specific strategy scoring</span>
      <span class="feature-item">✓ Player headshots and team branding</span>
      <span class="feature-item">✓ Explicit confidence and risk labels</span>
    </div>
  </div>
  <div class="product-card active">
    <div class="product-icon">🏆</div>
    <span class="hero-kicker">Flagship experience</span>
    <h3>FRANCHISE MODE</h3>
    <p>
      Run a persistent NBA universe through the regular season, playoffs,
      awards, the 3-2-1 Draft Lottery, scouting, NBA Draft Night, player
      development, health, and multi-season progression.
    </p>
    <div class="feature-list">
      <span class="feature-item">✓ Persistent multi-season league state</span>
      <span class="feature-item">✓ NBA Draft Lottery + live On-the-Clock Draft Night</span>
      <span class="feature-item">✓ Awards, postseason honors, health and development</span>
      <span class="feature-item">✓ Player photography and dynamic team branding</span>
    </div>
  </div>
</div>
""",
        unsafe_allow_html=True,
    )

    trade_page_candidates = [
        Path("pages/1_Trade_Lab.py"),
        Path("pages/1_Trade_Lab_v3.py"),
        Path("pages/2_Mixed_Trade_Recommendations.py"),
    ]
    trade_page = next(
        (
            str(path)
            for path in trade_page_candidates
            if path.exists()
        ),
        None,
    )

    # FRANCHISE_FLAGSHIP_OFFSEASON_EXPERIENCE_V1
    # Franchise Mode is the primary product. Specialist workspaces
    # remain directly accessible without visually outranking it.
    action_columns = st.columns([1.35, 1.0, 1.65])
    with action_columns[0]:
        franchise_page = Path("pages/5_Franchise_Mode.py")
        if franchise_page.exists():
            st.page_link(
                str(franchise_page),
                label="Open Franchise Mode",
                icon="🏆",
                width="stretch",
            )
        else:
            st.button(
                "Franchise Mode",
                disabled=True,
                width="stretch",
            )

    with action_columns[1]:
        if trade_page:
            st.page_link(
                trade_page,
                label="Open Trade Lab",
                icon="🏀",
                width="stretch",
            )
        else:
            st.info(
                "Move the V3 page into `pages/1_Trade_Lab.py` "
                "to activate this navigation button."
            )
    with action_columns[2]:
        st.caption(
            "Franchise Mode is the main front-office experience. "
            "Trade Lab, Trade Machine, Game Simulator, and Free Agency "
            "are specialist workspaces that support the same franchise."
        )

    if featured:
        st.markdown(
            '<h2 class="section-title">Featured model concept</h2>',
            unsafe_allow_html=True,
        )
        st.markdown(
            f"""
<div class="featured-shell">
  <div>
    <span class="featured-badge">Model-backed trade concept</span>
    <h3>{escaped(featured.get("team_headline", ""))}</h3>
    <p>{escaped(featured.get("team_subheadline", ""))}</p>
    <p>{escaped(featured.get("team_fit_summary", ""))}</p>
  </div>
  <div class="featured-score-grid">
    <div class="featured-score">
      <span>Team strategy</span>
      <strong>{escaped(featured.get("team_strategy_score_display", ""))}</strong>
    </div>
    <div class="featured-score">
      <span>Bilateral floor</span>
      <strong>{escaped(featured.get("bilateral_floor_score_display", ""))}</strong>
    </div>
    <div class="featured-score">
      <span>Roster fit</span>
      <strong>{escaped(featured.get("team_trade_fit_score_display", ""))}</strong>
    </div>
    <div class="featured-score">
      <span>Asset utility</span>
      <strong>{escaped(featured.get("asset_utility_score_display", ""))}</strong>
    </div>
  </div>
</div>
""",
            unsafe_allow_html=True,
        )

    st.markdown(
        '<h2 class="section-title">How a concept reaches the app</h2>',
        unsafe_allow_html=True,
    )
    st.markdown(
        """
<div class="pipeline-grid">
  <div class="pipeline-step">
    <span>01</span>
    <strong>Salary and CBA legality</strong>
  </div>
  <div class="pipeline-step">
    <span>02</span>
    <strong>Player and pick valuation</strong>
  </div>
  <div class="pipeline-step">
    <span>03</span>
    <strong>Protection and quality gates</strong>
  </div>
  <div class="pipeline-step">
    <span>04</span>
    <strong>Team strategy scoring</strong>
  </div>
  <div class="pipeline-step">
    <span>05</span>
    <strong>Bilateral display calibration</strong>
  </div>
</div>
""",
        unsafe_allow_html=True,
    )

    st.markdown(
        '<h2 class="section-title">League-wide coverage</h2>',
        unsafe_allow_html=True,
    )
    st.markdown(
        render_logo_strip(visual_assets),
        unsafe_allow_html=True,
    )

    st.markdown(
        """
<p class="footer-note">
  Model-generated concepts do not imply that a player or team is available.
  Deterministic legality reflects the modeled evidence cutoff and package checks.
</p>
""",
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    render_page()