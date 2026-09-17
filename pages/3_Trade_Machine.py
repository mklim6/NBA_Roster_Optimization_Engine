from __future__ import annotations

import gzip
import cloudpickle
import copy
import html
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
APP_DATA = ROOT / "app_data"
VISUAL_ASSETS_PATH = APP_DATA / "mixed_trade_visual_assets_2026_27_v1.json"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from freeform_trade_machine_engine_v3 import (  # noqa: E402
    CheckResult,
    RuntimeData,
    Status,
    TradeRequest,
    TradeSideRequest,
    evaluate_trade,
    load_runtime_data,
)
from mutable_league_state_v1 import (  # noqa: E402
    STATE_VERSION,
    LeagueState,
    StateMutationError,
    apply_passed_trade,
    create_league_state,
    reset_league_state,
    undo_last_trade,
)
from state_runtime_adapter_v1 import (  # noqa: E402
    StateRuntimeAdapterError,
    build_state_runtime,
)
from league_scenario_store_v1 import (  # noqa: E402
    DEFAULT_SCENARIO_DIR,
    ScenarioStoreError,
    delete_scenario,
    import_scenario_file,
    list_scenarios,
    load_scenario_file,
    save_scenario,
)
from trade_mode_policy_v1 import (  # noqa: E402
    ModeTradeEvaluation,
    SandboxDisposition,
    TradeMode,
    TradeModePolicyError,
    apply_trade_in_mode,
    classify_trade,
)


st.set_page_config(
    page_title="Freeform Trade Machine",
    page_icon="🔄",
    layout="wide",
)
# FRANCHISE_PRIMARY_NAV_V1
from src.franchise_primary_navigation_v1 import render_franchise_primary_navigation_v1
render_franchise_primary_navigation_v1()



TRADE_MACHINE_SANDBOX_VERSION = "trade-machine-sandbox-anchor-v1-2026-08-16"
TRADE_MACHINE_SANDBOX_PATH = (
    ROOT / "outputs" / "runtime"
    / "trade_machine_sandbox_anchor_2026_27_v1.pkl.gz"
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
def get_base_runtime() -> RuntimeData:
    return load_runtime_data()


def load_trade_machine_sandbox_seed() -> LeagueState:
    if not TRADE_MACHINE_SANDBOX_PATH.is_file():
        raise StateMutationError(
            "The immutable 2026-27 Trade Machine sandbox seed is missing."
        )
    with gzip.open(TRADE_MACHINE_SANDBOX_PATH, "rb") as handle:
        state = cloudpickle.load(handle)
    if not isinstance(state, LeagueState) or state.state_version != STATE_VERSION:
        raise StateMutationError(
            "The immutable Trade Machine sandbox seed is incompatible."
        )
    return state


def get_league_state(
    base_runtime: RuntimeData,
) -> LeagueState:
    # TRADE_MACHINE_STANDALONE_SANDBOX_V1:
    # The standalone Trade Machine never reads or writes Franchise Mode state.
    key = "trade_machine_league_state"
    state = st.session_state.get(key)
    if (
        isinstance(state, LeagueState)
        and state.state_version == STATE_VERSION
    ):
        return state

    try:
        state = load_trade_machine_sandbox_seed()
    except Exception:
        # Fail closed to the static base runtime rather than hydrating from a
        # live Franchise Mode checkpoint.
        state = create_league_state(base_runtime)
    st.session_state[key] = state
    return state


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


def compact_asset_label(value: Any) -> str:
    text = str(value or "").strip().lower()

    labels = {
        "franchise_caliber": "Franchise",
        "superstar_caliber": "Superstar",
        "star_caliber": "Star",
        "high_end_starter": "High-End Starter",
        "quality_starter": "Starter",
        "starter_caliber": "Starter",
        "development_core": "Dev Core",
        "development_depth": "Development / Depth",
        "starter_rotation": "Starter / Rotation",
        "rotation_depth": "Rotation / Depth",
        "rotation_player": "Rotation",
        "rotation_caliber": "Rotation",
        "bench_depth": "Bench",
        "salary_filler": "Salary Filler",
    }

    if not text or text in {"nan", "none", "unclassified"}:
        return ""

    return labels.get(
        text,
        text.replace("_", " ").title(),
    )


def player_label(
    runtime: RuntimeData,
    player_id: str,
) -> str:
    trade = runtime.trade_by_id.get(player_id, {})
    rating = runtime.ratings_by_id.get(player_id, {})
    market = runtime.market_by_id.get(player_id, {})

    name = str(
        trade.get("player_name", player_id)
    ).strip()

    overall = rating_text(
        rating.get("overall_rating")
    )

    asset_class = compact_asset_label(
        market.get("recommendation_asset_class_v3")
    )

    salary = money(
        trade.get("trade_salary_2026_27")
    )

    parts = [
        name,
        f"{overall} OVR",
    ]

    if asset_class:
        parts.append(asset_class)

    parts.append(salary)

    return " | ".join(parts)



def compact_pick_years(record: dict[str, Any]) -> str:
    def year_text(value: Any) -> str:
        try:
            return str(int(float(value)))
        except (TypeError, ValueError):
            return ""

    first = year_text(record.get("draft_year_min"))
    last = year_text(record.get("draft_year_max"))

    if first and last and first != last:
        return f"{first}-{last}"

    return first or last or "Future"


def compact_pick_rounds(value: Any) -> str:
    text = str(value or "").strip()

    if text in {"1", "1.0"}:
        return "R1"

    if text in {"2", "2.0"}:
        return "R2"

    if text in {"1|2", "1.0|2.0", "2|1"}:
        return "R1/R2"

    return text.replace("|", "/") or "Pick"


def compact_pick_structure(value: Any) -> str:
    text = str(value or "").strip().lower()

    labels = {
        "direct_owned_pick": "Direct",
        "joint_component_candidate_right": "Component",
        "retained_or_fallback_right": "Retained/Fallback",
        "protected_or_conditional_pick": "Protected",
        "linked_rollover_right": "Rollover",
        "swap_option_value_right": "Swap",
        "integrated_pool_candidate_right": "Pool",
        "composite_candidate_right": "Composite",
    }

    if not text or text in {"nan", "none"}:
        return "Draft Right"

    return labels.get(
        text,
        text.replace("_", " ").title(),
    )


def compact_originating_teams(value: Any) -> str:
    text = str(value or "").strip()

    if not text or text.lower() in {"nan", "none"}:
        return ""

    return text.replace("|", "/")


def pick_label(
    runtime: RuntimeData,
    pick_right_id: str,
) -> str:
    record = runtime.pick_by_id.get(pick_right_id, {})

    years = compact_pick_years(record)
    rounds = compact_pick_rounds(
        record.get("round_numbers")
    )
    structure = compact_pick_structure(
        record.get("right_structure")
    )
    origins = compact_originating_teams(
        record.get("originating_teams")
    )
    value = safe_float(
        record.get("candidate_right_value_score")
    )

    parts = [
        f"{years} {rounds}",
        structure,
    ]

    if origins:
        parts.append(origins)

    if value is not None:
        parts.append(f"V{value:.1f}")

    return " | ".join(parts)



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


def friendly_status_value(value: Any) -> str:
    text = str(value or "").strip().lower()
    labels = {
        "verified_clear": "Verified Clear",
        "verified_with_conditions": "Verified w/ Conditions",
        "manual_review_required": "Manual Review",
        "not_trade_eligible": "Not Trade Eligible",
        "not covered": "Not Covered",
        "not_covered": "Not Covered",
    }
    if not text or text in {"nan", "none"}:
        return "Not Covered"
    return labels.get(text, text.replace("_", " ").title())


def humanize_code(value: Any) -> str:
    text = str(value or "").strip().replace("_", " ").title()
    replacements = {
        "Cba": "CBA",
        "Tpe": "TPE",
        "Byc": "BYC",
        "Nba": "NBA",
    }
    for source, target in replacements.items():
        text = text.replace(source, target)
    return text


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
                "Asset class": compact_asset_label(
                    market.get(
                        "recommendation_asset_class_v3",
                        "Unclassified",
                    )
                ) or "Unclassified",
                "CBA evidence": friendly_status_value(
                    decision.get(
                        "player_cba_evidence_determination",
                        "not covered",
                    )
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
                "Structure": compact_pick_structure(
                    record.get("right_structure", "")
                ),
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



TEAM_COLORS = {
    "ATL": ("#E03A3E", "#C1D32F"),
    "BOS": ("#007A33", "#BA9653"),
    "BKN": ("#FFFFFF", "#6B7280"),
    "CHA": ("#1D1160", "#00788C"),
    "CHI": ("#CE1141", "#0B0F17"),
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
    "SAS": ("#C4CED4", "#111827"),
    "TOR": ("#CE1141", "#000000"),
    "UTA": ("#002B5C", "#F9A01B"),
    "WAS": ("#002B5C", "#E31837"),
}


@st.cache_data(show_spinner=False)
def get_visual_assets() -> dict[str, Any]:
    if not VISUAL_ASSETS_PATH.exists():
        return {"teams": {}, "players": {}}

    try:
        payload = json.loads(
            VISUAL_ASSETS_PATH.read_text(encoding="utf-8-sig")
        )
    except (OSError, json.JSONDecodeError):
        return {"teams": {}, "players": {}}

    return payload if isinstance(payload, dict) else {"teams": {}, "players": {}}


def escaped(value: Any) -> str:
    return html.escape("" if value is None else str(value))


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


def player_headshot_url(player_id: str) -> str:
    cleaned = str(player_id).strip()
    if not cleaned.isdigit():
        return ""

    return (
        "https://cdn.nba.com/headshots/nba/latest/"
        f"260x190/{cleaned}.png"
    )


def team_palette(team: str) -> tuple[str, str]:
    return TEAM_COLORS.get(team, ("#38BDF8", "#A78BFA"))


def standalone_pick_count(runtime: RuntimeData) -> int:
    column = runtime.picks.get("standalone_trade_asset_flag")
    if column is None:
        return 0

    return int(
        column.astype(str)
        .str.strip()
        .str.lower()
        .isin({"true", "1", "yes"})
        .sum()
    )


def selected_outgoing_salary(
    runtime: RuntimeData,
    player_ids: list[str],
) -> float:
    total = 0.0

    for player_id in player_ids:
        record = runtime.trade_by_id.get(player_id, {})
        amount = safe_float(record.get("trade_salary_2026_27"))
        if amount is not None:
            total += amount

    return total


def inject_trade_machine_styles() -> None:
    st.markdown(
        """
<style>
@import url('https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@600;700;800&family=Inter:wght@400;500;600;700&display=swap');

:root {
    --tm-bg: #070b13;
    --tm-panel: rgba(15, 23, 42, 0.76);
    --tm-panel-strong: rgba(17, 25, 40, 0.94);
    --tm-border: rgba(148, 163, 184, 0.18);
    --tm-text: #f8fafc;
    --tm-muted: #94a3b8;
    --tm-cyan: #38bdf8;
    --tm-violet: #8b5cf6;
}

html, body, [class*="css"] {
    font-family: "Inter", sans-serif;
}

.stApp {
    background:
        radial-gradient(circle at 18% 0%, rgba(56, 189, 248, 0.10), transparent 32%),
        radial-gradient(circle at 82% 8%, rgba(139, 92, 246, 0.11), transparent 30%),
        linear-gradient(180deg, #080c15 0%, #070a11 100%);
}

[data-testid="stMainBlockContainer"] {
    max-width: 1480px;
    padding-top: 2rem;
    padding-bottom: 5rem;
}

h1, h2, h3, .tm-display {
    font-family: "Barlow Condensed", sans-serif !important;
    letter-spacing: 0.01em;
}

[data-testid="stVerticalBlockBorderWrapper"] {
    border: 1px solid var(--tm-border) !important;
    border-radius: 22px !important;
    background:
        linear-gradient(145deg, rgba(19, 29, 48, 0.92), rgba(10, 15, 26, 0.92)) !important;
    box-shadow: 0 18px 50px rgba(0, 0, 0, 0.22);
    overflow: hidden;
}

div[data-baseweb="select"] > div {
    background: rgba(10, 15, 26, 0.92) !important;
    border-color: rgba(148, 163, 184, 0.22) !important;
    border-radius: 12px !important;
    min-height: 48px;
}

div[data-baseweb="select"] span {
    font-weight: 600;
}

.stButton > button[kind="primary"] {
    min-height: 54px;
    border: 0;
    border-radius: 14px;
    background: linear-gradient(100deg, #0ea5e9 0%, #6366f1 52%, #8b5cf6 100%);
    color: white;
    font-weight: 800;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    box-shadow: 0 12px 30px rgba(79, 70, 229, 0.28);
}

.stButton > button[kind="primary"]:hover {
    transform: translateY(-1px);
    box-shadow: 0 16px 36px rgba(79, 70, 229, 0.36);
}

.stButton > button[kind="secondary"] {
    min-height: 54px;
    border-radius: 14px;
    border: 1px solid rgba(148, 163, 184, 0.22);
    background: rgba(15, 23, 42, 0.72);
    color: #cbd5e1;
    font-weight: 700;
}

[data-testid="stTabs"] [data-baseweb="tab-list"] {
    gap: 8px;
}

[data-testid="stTabs"] button[role="tab"] {
    border-radius: 999px;
    padding: 0.35rem 1rem;
    font-weight: 700;
}

.tm-hero {
    position: relative;
    overflow: hidden;
    border: 1px solid rgba(125, 211, 252, 0.20);
    border-radius: 28px;
    padding: 30px 32px 26px;
    margin-bottom: 20px;
    background:
        linear-gradient(120deg, rgba(14, 165, 233, 0.14), rgba(99, 102, 241, 0.11) 46%, rgba(139, 92, 246, 0.15)),
        rgba(8, 13, 24, 0.92);
    box-shadow: 0 24px 70px rgba(0, 0, 0, 0.30);
}

.tm-hero::after {
    content: "";
    position: absolute;
    width: 380px;
    height: 380px;
    right: -160px;
    top: -210px;
    border-radius: 50%;
    background: radial-gradient(circle, rgba(56, 189, 248, 0.30), transparent 68%);
}

.tm-eyebrow {
    color: #7dd3fc;
    font-size: 0.76rem;
    font-weight: 800;
    letter-spacing: 0.16em;
    text-transform: uppercase;
}

.tm-title {
    margin: 6px 0 6px;
    color: #f8fafc;
    font-family: "Barlow Condensed", sans-serif;
    font-size: clamp(2.8rem, 5vw, 5.1rem);
    line-height: 0.90;
    font-weight: 800;
    letter-spacing: -0.025em;
    text-transform: uppercase;
}

.tm-subtitle {
    max-width: 900px;
    color: #b9c4d4;
    font-size: 1rem;
    line-height: 1.65;
}

.tm-stat-grid {
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: 12px;
    margin-top: 22px;
}

.tm-stat {
    border: 1px solid rgba(148, 163, 184, 0.15);
    border-radius: 16px;
    padding: 13px 15px;
    background: rgba(5, 10, 18, 0.48);
}

.tm-stat-value {
    color: #ffffff;
    font-family: "Barlow Condensed", sans-serif;
    font-size: 1.75rem;
    font-weight: 800;
    line-height: 1;
}

.tm-stat-label {
    margin-top: 5px;
    color: #8fa0b7;
    font-size: 0.72rem;
    font-weight: 700;
    letter-spacing: 0.07em;
    text-transform: uppercase;
}

.tm-section-kicker {
    margin: 18px 0 8px;
    color: #7dd3fc;
    font-size: 0.72rem;
    font-weight: 800;
    letter-spacing: 0.15em;
    text-transform: uppercase;
}

.tm-team-header {
    position: relative;
    display: flex;
    align-items: center;
    gap: 16px;
    margin: 4px 0 15px;
    padding: 16px;
    border: 1px solid color-mix(in srgb, var(--team-primary) 45%, transparent);
    border-radius: 18px;
    background:
        linear-gradient(110deg, color-mix(in srgb, var(--team-primary) 22%, transparent), transparent 58%),
        rgba(7, 12, 22, 0.70);
    overflow: hidden;
}

.tm-team-header::after {
    content: "";
    position: absolute;
    inset: 0 0 0 auto;
    width: 5px;
    background: linear-gradient(180deg, var(--team-primary), var(--team-secondary));
}

.tm-team-logo {
    width: 70px;
    height: 70px;
    object-fit: contain;
    filter: drop-shadow(0 8px 14px rgba(0,0,0,0.35));
}

.tm-team-side {
    color: #94a3b8;
    font-size: 0.68rem;
    font-weight: 800;
    letter-spacing: 0.14em;
    text-transform: uppercase;
}

.tm-team-name {
    color: #f8fafc;
    font-family: "Barlow Condensed", sans-serif;
    font-size: 1.75rem;
    font-weight: 800;
    line-height: 1;
}

.tm-team-meta {
    margin-top: 5px;
    color: #a8b3c4;
    font-size: 0.78rem;
}

.tm-asset-summary {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 9px;
    margin: 12px 0 4px;
}

.tm-mini-stat {
    padding: 10px 11px;
    border: 1px solid rgba(148, 163, 184, 0.13);
    border-radius: 12px;
    background: rgba(5, 10, 18, 0.48);
}

.tm-mini-stat strong {
    display: block;
    color: #f8fafc;
    font-size: 0.98rem;
}

.tm-mini-stat span {
    color: #7f8da3;
    font-size: 0.66rem;
    font-weight: 700;
    letter-spacing: 0.06em;
    text-transform: uppercase;
}

.tm-asset-stack {
    display: grid;
    gap: 8px;
    margin-top: 12px;
}

.tm-player-card, .tm-pick-card {
    display: flex;
    align-items: center;
    gap: 12px;
    min-height: 68px;
    padding: 9px 11px;
    border: 1px solid rgba(148, 163, 184, 0.14);
    border-radius: 14px;
    background: rgba(8, 13, 23, 0.68);
}

.tm-player-card img {
    width: 58px;
    height: 50px;
    object-fit: cover;
    object-position: top center;
    border-radius: 10px;
    background: rgba(148, 163, 184, 0.10);
}

.tm-player-name, .tm-pick-name {
    color: #f8fafc;
    font-weight: 750;
    font-size: 0.90rem;
}

.tm-player-meta, .tm-pick-meta {
    margin-top: 3px;
    color: #8fa0b7;
    font-size: 0.72rem;
}

.tm-pick-icon {
    display: grid;
    place-items: center;
    width: 46px;
    height: 46px;
    border-radius: 12px;
    color: #dbeafe;
    background: linear-gradient(135deg, rgba(14,165,233,0.24), rgba(139,92,246,0.28));
    font-family: "Barlow Condensed", sans-serif;
    font-size: 0.82rem;
    font-weight: 800;
}

.tm-empty {
    margin-top: 12px;
    padding: 17px;
    border: 1px dashed rgba(148, 163, 184, 0.20);
    border-radius: 14px;
    color: #728197;
    text-align: center;
    font-size: 0.80rem;
}

.tm-trade-rail {
    display: flex;
    align-items: center;
    gap: 13px;
    margin: 18px 0 10px;
    color: #8291a7;
    font-size: 0.68rem;
    font-weight: 800;
    letter-spacing: 0.14em;
    text-transform: uppercase;
}

.tm-trade-rail::before,
.tm-trade-rail::after {
    content: "";
    flex: 1;
    height: 1px;
    background: linear-gradient(90deg, transparent, rgba(125,211,252,0.42), transparent);
}

.tm-swap-orb {
    display: grid;
    place-items: center;
    width: 42px;
    height: 42px;
    border: 1px solid rgba(125,211,252,0.30);
    border-radius: 50%;
    color: #7dd3fc;
    background: rgba(14,165,233,0.10);
    font-size: 1.1rem;
}

.tm-verdict {
    position: relative;
    overflow: hidden;
    display: grid;
    grid-template-columns: auto 1fr;
    gap: 18px;
    align-items: center;
    padding: 22px 24px;
    margin: 12px 0 18px;
    border: 1px solid color-mix(in srgb, var(--status-color) 52%, transparent);
    border-radius: 22px;
    background:
        linear-gradient(110deg, color-mix(in srgb, var(--status-color) 18%, transparent), transparent 62%),
        rgba(8, 13, 23, 0.91);
    box-shadow: 0 18px 48px rgba(0,0,0,0.24);
}

.tm-verdict-icon {
    display: grid;
    place-items: center;
    width: 68px;
    height: 68px;
    border-radius: 18px;
    color: white;
    background: var(--status-color);
    font-family: "Barlow Condensed", sans-serif;
    font-size: 2rem;
    font-weight: 800;
}

.tm-verdict-label {
    color: var(--status-color);
    font-size: 0.72rem;
    font-weight: 900;
    letter-spacing: 0.15em;
    text-transform: uppercase;
}

.tm-verdict-title {
    margin-top: 2px;
    color: #f8fafc;
    font-family: "Barlow Condensed", sans-serif;
    font-size: 2rem;
    font-weight: 800;
    line-height: 1;
}

.tm-verdict-copy {
    margin-top: 7px;
    color: #aeb9c9;
    font-size: 0.84rem;
    line-height: 1.55;
}

.tm-result-header {
    display: flex;
    align-items: center;
    gap: 12px;
    margin-bottom: 12px;
}

.tm-result-header img {
    width: 52px;
    height: 52px;
    object-fit: contain;
}

.tm-result-name {
    color: #f8fafc;
    font-family: "Barlow Condensed", sans-serif;
    font-size: 1.55rem;
    font-weight: 800;
}

.tm-result-status {
    color: var(--status-color);
    font-size: 0.70rem;
    font-weight: 850;
    letter-spacing: 0.12em;
    text-transform: uppercase;
}

.tm-result-metrics {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 9px;
    margin: 10px 0 14px;
}

.tm-result-metric {
    min-width: 0;
    padding: 11px 12px;
    border: 1px solid rgba(148, 163, 184, 0.13);
    border-radius: 13px;
    background: rgba(5, 10, 18, 0.48);
}

.tm-result-metric-value {
    color: #f8fafc;
    font-family: "Barlow Condensed", sans-serif;
    font-size: 1.55rem;
    font-weight: 750;
    line-height: 1;
    white-space: nowrap;
}

.tm-result-metric-label {
    margin-top: 5px;
    color: #8291a7;
    font-size: 0.66rem;
    font-weight: 800;
    letter-spacing: 0.07em;
    text-transform: uppercase;
}

.tm-salary-card {
    margin: 12px 0 15px;
    padding: 14px;
    border: 1px solid rgba(148, 163, 184, 0.14);
    border-radius: 15px;
    background: rgba(5, 10, 18, 0.52);
}

.tm-salary-top {
    display: flex;
    justify-content: space-between;
    gap: 12px;
}

.tm-salary-title {
    color: #dbe5f3;
    font-weight: 750;
    font-size: 0.82rem;
}

.tm-salary-route {
    color: #7dd3fc;
    font-size: 0.68rem;
    font-weight: 800;
    letter-spacing: 0.08em;
    text-transform: uppercase;
}

.tm-salary-bar {
    position: relative;
    height: 10px;
    margin: 12px 0 8px;
    border-radius: 999px;
    background: rgba(148, 163, 184, 0.14);
    overflow: hidden;
}

.tm-salary-fill {
    height: 100%;
    width: var(--bar-width);
    border-radius: inherit;
    background: var(--bar-color);
}

.tm-salary-values {
    display: flex;
    justify-content: space-between;
    gap: 8px;
    color: #7f8da3;
    font-size: 0.70rem;
}

.tm-salary-margin {
    margin-top: 7px;
    color: var(--bar-color);
    font-size: 0.78rem;
    font-weight: 800;
}

.tm-audit-card {
    position: relative;
    display: grid;
    grid-template-columns: 34px 1fr auto;
    gap: 11px;
    align-items: start;
    margin: 8px 0;
    padding: 13px 14px;
    border: 1px solid color-mix(in srgb, var(--audit-color) 36%, transparent);
    border-radius: 14px;
    background: color-mix(in srgb, var(--audit-color) 9%, rgba(8,13,23,0.76));
}

.tm-audit-icon {
    display: grid;
    place-items: center;
    width: 30px;
    height: 30px;
    border-radius: 9px;
    color: white;
    background: var(--audit-color);
    font-weight: 900;
}

.tm-audit-title {
    color: #eef2f7;
    font-weight: 780;
    font-size: 0.84rem;
}

.tm-audit-message {
    margin-top: 4px;
    color: #9daabc;
    font-size: 0.75rem;
    line-height: 1.48;
}

.tm-audit-badge {
    color: var(--audit-color);
    font-size: 0.62rem;
    font-weight: 900;
    letter-spacing: 0.09em;
    text-transform: uppercase;
}

.tm-resolution-card {
    margin: -4px 0 18px;
    padding: 16px 18px;
    border: 1px solid rgba(56, 189, 248, 0.24);
    border-radius: 16px;
    background:
        linear-gradient(110deg, rgba(14, 165, 233, 0.11), rgba(99, 102, 241, 0.08)),
        rgba(8, 13, 23, 0.78);
}

.tm-resolution-label {
    color: #7dd3fc;
    font-size: 0.66rem;
    font-weight: 900;
    letter-spacing: 0.13em;
    text-transform: uppercase;
}

.tm-resolution-title {
    margin-top: 3px;
    color: #f8fafc;
    font-family: "Barlow Condensed", sans-serif;
    font-size: 1.28rem;
    font-weight: 800;
}

.tm-resolution-copy {
    margin-top: 5px;
    color: #aeb9c9;
    font-size: 0.80rem;
    line-height: 1.55;
}

@media (max-width: 900px) {
    .tm-stat-grid {
        grid-template-columns: repeat(2, minmax(0, 1fr));
    }

    .tm-hero {
        padding: 24px 20px;
    }

    .tm-title {
        font-size: 3rem;
    }

    .tm-verdict {
        grid-template-columns: 1fr;
    }
}
</style>
        """,
        unsafe_allow_html=True,
    )


def render_hero(runtime: RuntimeData) -> None:
    stats = [
        (len(runtime.trade_pool), "Trade-pool players"),
        (len(runtime.player_cba), "Player CBA decisions"),
        (standalone_pick_count(runtime), "Standalone draft rights"),
        (len(runtime.stepien), "Stepien team-years"),
    ]

    cards = "".join(
        f"""
<div class="tm-stat">
  <div class="tm-stat-value">{value:,}</div>
  <div class="tm-stat-label">{escaped(label)}</div>
</div>
"""
        for value, label in stats
    )

    st.markdown(
        f"""
<div class="tm-hero">
  <div class="tm-eyebrow">V3 legality engine · standalone 2026-27 sandbox</div>
  <div class="tm-title">NBA Trade Command Center</div>
  <div class="tm-subtitle">
    Build a two-team player-and-pick package against the frozen 2026-27
    sandbox. This workspace never modifies Franchise Mode. Live franchise
    trades belong in Franchise Mode → Transactions → Trade Builder.
  </div>
  <div class="tm-stat-grid">{cards}</div>
</div>
        """,
        unsafe_allow_html=True,
    )


def render_team_header(
    visual_assets: dict[str, Any],
    runtime: RuntimeData,
    team: str,
    side_label: str,
) -> None:
    primary, secondary = team_palette(team)
    logo = team_logo_url(visual_assets, team)
    logo_html = (
        f'<img class="tm-team-logo" src="{escaped(logo)}" '
        f'alt="{escaped(team_label(team))} logo">'
        if logo
        else ""
    )
    available_players = len(team_players(runtime, team))
    available_picks = len(team_picks(runtime, team))

    st.markdown(
        f"""
<div class="tm-team-header"
     style="--team-primary:{primary};--team-secondary:{secondary};">
  {logo_html}
  <div>
    <div class="tm-team-side">{escaped(side_label)}</div>
    <div class="tm-team-name">{escaped(TEAM_NAMES.get(team, team))}</div>
    <div class="tm-team-meta">
      {team} · {available_players} eligible players ·
      {available_picks} standalone rights
    </div>
  </div>
</div>
        """,
        unsafe_allow_html=True,
    )


def render_asset_preview(
    runtime: RuntimeData,
    player_ids: list[str],
    pick_right_ids: list[str],
) -> None:
    salary = selected_outgoing_salary(runtime, player_ids)

    st.markdown(
        f"""
<div class="tm-asset-summary">
  <div class="tm-mini-stat">
    <strong>{len(player_ids)}</strong><span>Players</span>
  </div>
  <div class="tm-mini-stat">
    <strong>{len(pick_right_ids)}</strong><span>Draft rights</span>
  </div>
  <div class="tm-mini-stat">
    <strong>{escaped(money(salary))}</strong><span>Listed salary</span>
  </div>
</div>
        """,
        unsafe_allow_html=True,
    )

    cards: list[str] = []

    for player_id in player_ids:
        trade = runtime.trade_by_id.get(player_id, {})
        rating = runtime.ratings_by_id.get(player_id, {})
        market = runtime.market_by_id.get(player_id, {})
        name = str(trade.get("player_name", player_id)).strip()
        headshot = player_headshot_url(player_id)
        image = (
            f'<img src="{escaped(headshot)}" alt="{escaped(name)}" '
            'onerror="this.style.visibility=\'hidden\'">'
            if headshot
            else ""
        )
        cards.append(
            f"""
<div class="tm-player-card">
  {image}
  <div>
    <div class="tm-player-name">{escaped(name)}</div>
    <div class="tm-player-meta">
      {escaped(rating_text(rating.get("overall_rating")))} OVR ·
      {escaped(money(trade.get("trade_salary_2026_27")))} ·
      {escaped(compact_asset_label(
          market.get("recommendation_asset_class_v3")
      ) or "Unclassified")}
    </div>
  </div>
</div>
"""
        )

    for pick_right_id in pick_right_ids:
        record = runtime.pick_by_id.get(pick_right_id, {})
        display_name = str(
            record.get("right_display_name", pick_right_id)
        ).strip()
        cards.append(
            f"""
<div class="tm-pick-card">
  <div class="tm-pick-icon">PICK</div>
  <div>
    <div class="tm-pick-name">
      {escaped(compact_pick_years(record))}
      {escaped(compact_pick_rounds(record.get("round_numbers")))}
    </div>
    <div class="tm-pick-meta">
      {escaped(compact_pick_structure(record.get("right_structure")))} ·
      {escaped(display_name)}
    </div>
  </div>
</div>
"""
        )

    if cards:
        st.markdown(
            '<div class="tm-asset-stack">'
            + "".join(cards)
            + "</div>",
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            '<div class="tm-empty">'
            "No outgoing assets selected yet."
            "</div>",
            unsafe_allow_html=True,
        )


def render_trade_rail() -> None:
    st.markdown(
        """
<div class="tm-trade-rail">
  <span>Sending assets</span>
  <div class="tm-swap-orb">⇄</div>
  <span>Receiving assets</span>
</div>
        """,
        unsafe_allow_html=True,
    )


def first_relevant_check(result: Any) -> CheckResult | None:
    ordered = [
        *result.checks,
        *result.side_a.checks,
        *result.side_b.checks,
    ]

    for target in [Status.BLOCKED, Status.MANUAL_REVIEW]:
        for check in ordered:
            if check.status == target:
                return check

    return ordered[0] if ordered else None


def blocked_salary_side(result: Any) -> tuple[str, Any] | None:
    for side in [result.side_a, result.side_b]:
        if (
            side.status == Status.BLOCKED
            and str(side.salary_issue) == "salary_matching_failed"
        ):
            return side.team_abbreviation, side
    return None


def manual_review_evidence_check(
    result: Any,
) -> CheckResult | None:
    ordered = [
        *result.checks,
        *result.side_a.checks,
        *result.side_b.checks,
    ]
    preferred_codes = [
        "player_cba_evidence_missing",
        "salary_evidence_missing",
        "team_cba_evidence_missing",
        "transaction_player_mechanics_manual_review",
        "team_cba_manual_review",
    ]

    for code in preferred_codes:
        for check in ordered:
            if (
                check.status == Status.MANUAL_REVIEW
                and check.code == code
            ):
                return check

    return next(
        (
            check
            for check in ordered
            if check.status == Status.MANUAL_REVIEW
        ),
        None,
    )


def verdict_copy(result: Any) -> str:
    if result.status == Status.PASS:
        return (
            "Both teams clear the connected V3 player, salary, roster, "
            "draft-right, frozen-pick, and Stepien checks."
        )

    salary_failure = blocked_salary_side(result)
    if salary_failure is not None:
        team, side = salary_failure
        incoming = safe_float(side.incoming_salary_for_matching)
        maximum = safe_float(side.salary_matching_max_incoming)
        margin = safe_float(side.salary_matching_margin)
        team_name = TEAM_NAMES.get(team, team)

        if incoming is not None and maximum is not None:
            overage = abs(margin) if margin is not None else max(
                incoming - maximum,
                0.0,
            )
            return (
                f"{team_name} cannot receive this package under the "
                f"validated salary-matching rules. It would receive "
                f"{money(incoming)}, but its maximum is {money(maximum)}, "
                f"leaving the trade {money(overage)} over the limit."
            )

    if result.status == Status.MANUAL_REVIEW:
        check = manual_review_evidence_check(result)

        if check is not None:
            if check.code == "player_cba_evidence_missing":
                return (
                    f"{check.message} Because that player evidence is "
                    "incomplete, neither team's exact salary route can be "
                    "deterministically released."
                )

            if check.code in {
                "salary_evidence_missing",
                "team_cba_evidence_missing",
            }:
                return (
                    "The package contains incomplete team or player salary "
                    "evidence, so neither side's exact salary route can be "
                    "released deterministically."
                )

            return check.message

        return "The package requires unresolved evidence or contract review."

    check = first_relevant_check(result)
    if check is not None:
        return check.message

    return "At least one deterministic legality rule blocks the package."


def resolution_guidance(result: Any) -> tuple[str, str] | None:
    salary_failure = blocked_salary_side(result)
    if salary_failure is not None:
        team, side = salary_failure
        incoming = safe_float(side.incoming_salary_for_matching)
        maximum = safe_float(side.salary_matching_max_incoming)
        margin = safe_float(side.salary_matching_margin)
        team_name = TEAM_NAMES.get(team, team)

        if incoming is not None and maximum is not None:
            overage = abs(margin) if margin is not None else max(
                incoming - maximum,
                0.0,
            )
            return (
                "How to restructure this trade",
                (
                    f"Reduce {team_name}'s incoming matching salary by at "
                    f"least {money(overage)}, or change its outgoing package "
                    f"so the permitted incoming maximum rises from "
                    f"{money(maximum)} to at least {money(incoming)}."
                ),
            )

    if result.status == Status.MANUAL_REVIEW:
        check = manual_review_evidence_check(result)

        if (
            check is not None
            and check.code == "player_cba_evidence_missing"
        ):
            return (
                "Resolve the missing player evidence",
                (
                    f"{check.message} Until that player is covered by the "
                    "player-CBA decision layer, both salary routes must remain "
                    "manual review."
                ),
            )

        return (
            "What requires review",
            (
                "Open the Legality Audit tab and resolve the first manual-"
                "review item before treating the package as deterministically "
                "legal."
            ),
        )

    return None


def render_resolution_guidance(result: Any) -> None:
    guidance = resolution_guidance(result)
    if guidance is None:
        return

    title, body = guidance
    st.markdown(
        f"""
<div class="tm-resolution-card">
  <div class="tm-resolution-label">Next action</div>
  <div class="tm-resolution-title">{escaped(title)}</div>
  <div class="tm-resolution-copy">{escaped(body)}</div>
</div>
        """,
        unsafe_allow_html=True,
    )


def render_status_banner(
    status: Status,
    title: str,
    copy: str | None = None,
) -> None:
    color = STATUS_COLORS[status]
    label = STATUS_LABELS[status]
    icon = {
        Status.PASS: "✓",
        Status.MANUAL_REVIEW: "!",
        Status.BLOCKED: "×",
    }[status]

    st.markdown(
        f"""
<div class="tm-verdict" style="--status-color:{color};">
  <div class="tm-verdict-icon">{icon}</div>
  <div>
    <div class="tm-verdict-label">{escaped(label)}</div>
    <div class="tm-verdict-title">{escaped(title)}</div>
    <div class="tm-verdict-copy">{escaped(copy or "")}</div>
  </div>
</div>
        """,
        unsafe_allow_html=True,
    )


def friendly_trade_message(value: Any) -> str:
    text = str(value or "").strip()
    return (
        text.replace(" through nan.", ".")
        .replace(" through NaN.", ".")
        .replace(" through <NA>.", ".")
    )


def render_trade_mode_banner(
    policy: ModeTradeEvaluation,
) -> None:
    if policy.mode == TradeMode.REALISM:
        render_status_banner(
            policy.strict_status,
            "Overall transaction result",
            verdict_copy(policy.strict_evaluation),
        )
        return

    if (
        policy.disposition
        == SandboxDisposition.VERIFIED
    ):
        color = "#1f9d55"
        icon = "✓"
        title = "Verified and ready to apply"
        copy = (
            "The package passed the strict V3 legality audit "
            "and is fully playable in Sandbox Mode."
        )
    elif (
        policy.disposition
        == SandboxDisposition.PLAYABLE_WITH_WARNING
    ):
        color = "#2563eb"
        icon = "▶"
        title = "Playable with realism warnings"
        copy = (
            "Sandbox Mode can apply this package using modeled "
            "salary treatment. The unresolved strict-CBA items "
            "remain visible in the legality audit."
        )
    elif (
        policy.disposition
        == SandboxDisposition.FORCE_REQUIRED
    ):
        color = "#d97706"
        icon = "!"
        title = "Force trade available"
        copy = (
            "The package violates one or more strict realism "
            "rules. It can only be applied after explicit force-"
            "trade confirmation."
        )
    else:
        color = "#dc2626"
        icon = "×"
        title = "Invalid package"
        copy = (
            "The package contains a structural problem that "
            "cannot be bypassed in either mode."
        )

    st.markdown(
        f"""
<div class="tm-verdict" style="--status-color:{color};">
  <div class="tm-verdict-icon">{icon}</div>
  <div>
    <div class="tm-verdict-label">
      {escaped(policy.verification_label)}
    </div>
    <div class="tm-verdict-title">{escaped(title)}</div>
    <div class="tm-verdict-copy">{escaped(copy)}</div>
  </div>
</div>
        """,
        unsafe_allow_html=True,
    )


def render_check(check: CheckResult) -> None:
    conditional_pass = (
        check.status == Status.PASS
        and "with_conditions" in check.code
    )
    color = (
        "#38bdf8"
        if conditional_pass
        else STATUS_COLORS[check.status]
    )
    label = (
        "CONDITIONAL PASS"
        if conditional_pass
        else STATUS_LABELS[check.status]
    )
    icon = (
        "i"
        if conditional_pass
        else {
            Status.PASS: "✓",
            Status.MANUAL_REVIEW: "!",
            Status.BLOCKED: "×",
        }[check.status]
    )
    title = humanize_code(check.code)

    st.markdown(
        f"""
<div class="tm-audit-card" style="--audit-color:{color};">
  <div class="tm-audit-icon">{icon}</div>
  <div>
    <div class="tm-audit-title">{escaped(title)}</div>
    <div class="tm-audit-message">{escaped(friendly_trade_message(check.message))}</div>
  </div>
  <div class="tm-audit-badge">{escaped(label)}</div>
</div>
        """,
        unsafe_allow_html=True,
    )


def render_salary_meter(side: Any, team: str) -> None:
    incoming = safe_float(side.incoming_salary_for_matching)
    maximum = safe_float(side.salary_matching_max_incoming)
    margin = safe_float(side.salary_matching_margin)
    route = str(side.salary_matching_route or "not evaluated")
    passed = side.salary_matching_passed is True

    if incoming is None or maximum is None or maximum <= 0:
        st.markdown(
            '<div class="tm-empty">'
            "Salary route was not deterministically evaluated."
            "</div>",
            unsafe_allow_html=True,
        )
        return

    ratio = max(0.0, incoming / maximum)
    width = min(100.0, ratio * 100.0)
    color = "#22c55e" if passed else "#ef4444"

    if margin is None:
        margin_text = "Margin unavailable"
    elif margin >= 0:
        margin_text = f"{money(margin)} remaining"
    else:
        margin_text = f"{money(abs(margin))} over the limit"

    st.markdown(
        f"""
<div class="tm-salary-card">
  <div class="tm-salary-top">
    <div class="tm-salary-title">{escaped(team)} salary match</div>
    <div class="tm-salary-route">{escaped(route.replace("_", " "))}</div>
  </div>
  <div class="tm-salary-bar">
    <div class="tm-salary-fill"
         style="--bar-width:{width:.1f}%;--bar-color:{color};"></div>
  </div>
  <div class="tm-salary-values">
    <span>Incoming {escaped(money(incoming))}</span>
    <span>Maximum {escaped(money(maximum))}</span>
  </div>
  <div class="tm-salary-margin" style="--bar-color:{color};">
    {escaped(margin_text)}
  </div>
</div>
        """,
        unsafe_allow_html=True,
    )


def render_result_header(
    visual_assets: dict[str, Any],
    team: str,
    status: Status,
) -> None:
    logo = team_logo_url(visual_assets, team)
    logo_html = (
        f'<img src="{escaped(logo)}" alt="{escaped(team)} logo">'
        if logo
        else ""
    )
    color = STATUS_COLORS[status]

    st.markdown(
        f"""
<div class="tm-result-header" style="--status-color:{color};">
  {logo_html}
  <div>
    <div class="tm-result-name">{escaped(team_label(team))}</div>
    <div class="tm-result-status">{escaped(STATUS_LABELS[status])}</div>
  </div>
</div>
        """,
        unsafe_allow_html=True,
    )


def render_side_summary(
    visual_assets: dict[str, Any],
    runtime: RuntimeData,
    team: str,
    player_ids: list[str],
    pick_right_ids: list[str],
    side: Any,
) -> None:
    render_result_header(
        visual_assets,
        team,
        side.status,
    )

    st.markdown(
        f"""
<div class="tm-result-metrics">
  <div class="tm-result-metric">
    <div class="tm-result-metric-value">{len(player_ids)}</div>
    <div class="tm-result-metric-label">Players sent</div>
  </div>
  <div class="tm-result-metric">
    <div class="tm-result-metric-value">{len(pick_right_ids)}</div>
    <div class="tm-result-metric-label">Draft rights</div>
  </div>
  <div class="tm-result-metric">
    <div class="tm-result-metric-value">
      {escaped(money(side.outgoing_salary))}
    </div>
    <div class="tm-result-metric-label">Outgoing salary</div>
  </div>
  <div class="tm-result-metric">
    <div class="tm-result-metric-value">
      {escaped(money(side.incoming_salary_for_matching))}
    </div>
    <div class="tm-result-metric-label">Incoming salary</div>
  </div>
</div>
        """,
        unsafe_allow_html=True,
    )

    render_salary_meter(side, team)

    if player_ids:
        st.markdown("**Outgoing players**")
        st.dataframe(
            selected_player_rows(runtime, player_ids),
            hide_index=True,
            width="stretch",
            column_config={
                "Player": st.column_config.TextColumn(
                    "Player",
                    width="medium",
                ),
                "Salary": st.column_config.TextColumn(
                    "Salary",
                    width="small",
                ),
                "OVR": st.column_config.TextColumn(
                    "OVR",
                    width="small",
                ),
                "POT": st.column_config.TextColumn(
                    "POT",
                    width="small",
                ),
                "Asset class": st.column_config.TextColumn(
                    "Asset class",
                    width="medium",
                ),
                "CBA evidence": st.column_config.TextColumn(
                    "CBA evidence",
                    width="medium",
                ),
            },
        )

    if pick_right_ids:
        st.markdown("**Outgoing draft rights**")
        st.dataframe(
            selected_pick_rows(runtime, pick_right_ids),
            hide_index=True,
            width="stretch",
        )


def clear_trade_audit_state() -> None:
    for key in {
        "trade_machine_last_result",
        "trade_machine_last_policy",
        "trade_machine_last_selection",
    }:
        st.session_state.pop(key, None)


def clear_trade_state() -> None:
    removable = [
        key
        for key in list(st.session_state)
        if (
            key.startswith("trade_machine_players_")
            or key.startswith("trade_machine_picks_")
        )
    ]

    for key in removable:
        del st.session_state[key]

    clear_trade_audit_state()


def selection_request(
    selection: dict[str, Any],
) -> TradeRequest:
    return TradeRequest(
        side_a=TradeSideRequest(
            team_abbreviation=selection["team_a"],
            player_ids=tuple(
                selection["team_a_players"]
            ),
            pick_right_ids=tuple(
                selection["team_a_picks"]
            ),
        ),
        side_b=TradeSideRequest(
            team_abbreviation=selection["team_b"],
            player_ids=tuple(
                selection["team_b_players"]
            ),
            pick_right_ids=tuple(
                selection["team_b_picks"]
            ),
        ),
    )


def player_names(
    runtime: RuntimeData,
    player_ids: tuple[str, ...],
) -> str:
    names = [
        str(
            runtime.trade_by_id.get(
                player_id,
                {},
            ).get("player_name", player_id)
        ).strip()
        for player_id in player_ids
    ]
    return ", ".join(names)


def active_scenario_label(
    state: LeagueState,
) -> str:
    name = st.session_state.get(
        "trade_machine_active_scenario_name"
    )
    saved_revision = st.session_state.get(
        "trade_machine_active_scenario_revision"
    )

    if not name:
        return "Unsaved session"

    if saved_revision == state.state_revision:
        return str(name)

    return f"{name} · unsaved changes"


def activate_scenario(
    name: str,
    state_revision: int,
) -> None:
    st.session_state[
        "trade_machine_active_scenario_name"
    ] = name
    st.session_state[
        "trade_machine_active_scenario_revision"
    ] = state_revision


def clear_active_scenario() -> None:
    st.session_state.pop(
        "trade_machine_active_scenario_name",
        None,
    )
    st.session_state.pop(
        "trade_machine_active_scenario_revision",
        None,
    )


def history_rows(
    state: LeagueState,
    runtime: RuntimeData,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []

    for record in reversed(state.transaction_history):
        team_a_assets = [
            player_names(
                runtime,
                record.team_a_player_ids,
            ),
            (
                f"{len(record.team_a_pick_right_ids)} draft right(s)"
                if record.team_a_pick_right_ids
                else ""
            ),
        ]
        team_b_assets = [
            player_names(
                runtime,
                record.team_b_player_ids,
            ),
            (
                f"{len(record.team_b_pick_right_ids)} draft right(s)"
                if record.team_b_pick_right_ids
                else ""
            ),
        ]

        rows.append(
            {
                "Transaction": record.transaction_id,
                "Revision": record.state_revision,
                "Trade date": record.trade_date,
                "Matchup": (
                    f"{record.team_a} ↔ {record.team_b}"
                ),
                f"{record.team_a} sent": " · ".join(
                    value
                    for value in team_a_assets
                    if value
                ),
                f"{record.team_b} sent": " · ".join(
                    value
                    for value in team_b_assets
                    if value
                ),
            }
        )

    return pd.DataFrame(rows)


base_runtime = get_base_runtime()
league_state = get_league_state(base_runtime)

try:
    runtime = build_state_runtime(
        base_runtime,
        league_state,
    )
except (
    StateRuntimeAdapterError,
    StateMutationError,
    ValueError,
    KeyError,
) as exc:
    # TRADE_MACHINE_CANONICAL_HYDRATION_REPAIR_V1:
    # Never replace a durable franchise state with an unrelated revision-0
    # league merely because a runtime view failed to rebuild.
    st.error(
        "The standalone 2026-27 sandbox runtime could not be rebuilt. "
        "No Franchise Mode state was read or modified. "
        f"Detail: {exc}"
    )
    st.stop()

visual_assets = get_visual_assets()
teams = sorted(runtime.team_salary_by_team)

inject_trade_machine_styles()
render_hero(runtime)

st.info(
    "Sandbox only: trades here stay inside this standalone 2026-27 session. "
    "They never change Franchise Mode. Use Franchise Mode → Transactions → "
    "Trade Builder for live franchise trades."
)

notice = st.session_state.pop(
    "trade_machine_state_notice",
    None,
)
if notice:
    st.success(notice)

st.markdown(
    '<div class="tm-section-kicker">League state</div>',
    unsafe_allow_html=True,
)

with st.container(border=True):
    state_metrics = st.columns(4)
    state_metrics[0].metric(
        "State revision",
        league_state.state_revision,
    )
    state_metrics[1].metric(
        "Applied trades",
        len(league_state.transaction_history),
    )
    state_metrics[2].metric(
        "Tracked players",
        len(league_state.player_team_by_id),
    )
    state_metrics[3].metric(
        "Tracked draft rights",
        len(league_state.pick_team_by_id),
    )

    control_columns = st.columns([1.4, 1.4, 4.2])

    with control_columns[0]:
        undo_clicked = st.button(
            "Undo last trade",
            width="stretch",
            disabled=not league_state.transaction_history,
            key="trade_machine_undo",
        )

    with control_columns[1]:
        reset_clicked = st.button(
            "Reset league",
            width="stretch",
            disabled=not league_state.transaction_history,
            key="trade_machine_reset",
        )

    with control_columns[2]:
        st.caption(
            "Applied moves live only in this standalone sandbox session. "
            "They never write to the durable Franchise Mode checkpoint."
        )

    if undo_clicked:
        removed = undo_last_trade(
            league_state,
            base_runtime,
        )
        clear_trade_state()
        st.session_state[
            "trade_machine_state_notice"
        ] = (
            f"Undid {removed.transaction_id}: "
            f"{removed.team_a} ↔ {removed.team_b}."
        )
        st.rerun()

    if reset_clicked:
        try:
            st.session_state[
                "trade_machine_league_state"
            ] = load_trade_machine_sandbox_seed()
        except Exception:
            st.session_state[
                "trade_machine_league_state"
            ] = create_league_state(base_runtime)
        clear_trade_state()
        st.session_state[
            "trade_machine_state_notice"
        ] = "Restored the standalone 2026-27 sandbox."
        st.rerun()

    st.caption(
        "Active scenario: "
        f"**{active_scenario_label(league_state)}**"
    )

    if league_state.transaction_history:
        with st.expander(
            "Applied transaction history",
            expanded=False,
        ):
            st.dataframe(
                history_rows(
                    league_state,
                    base_runtime,
                ),
                hide_index=True,
                width="stretch",
            )

    with st.expander(
        "Save, load, import, or export scenarios",
        expanded=False,
    ):
        st.caption(
            "Saved scenarios preserve the complete mutable league, "
            "including rosters, draft rights, salaries, transaction "
            "history, and the undo stack."
        )

        with st.form(
            "trade_machine_save_scenario_form",
            clear_on_submit=False,
        ):
            save_name = st.text_input(
                "Scenario name",
                placeholder=(
                    "Example: Bulls rebuild after deadline"
                ),
                max_chars=80,
            )
            save_notes = st.text_area(
                "Notes",
                placeholder=(
                    "Optional explanation of the strategy "
                    "behind this universe"
                ),
                max_chars=4000,
                height=90,
            )
            overwrite_existing = st.checkbox(
                "Replace an existing scenario with the same name",
                value=False,
            )
            save_clicked = st.form_submit_button(
                "Save current league",
                type="primary",
                width="stretch",
            )

        if save_clicked:
            try:
                saved = save_scenario(
                    league_state,
                    base_runtime,
                    save_name,
                    notes=save_notes,
                    directory=DEFAULT_SCENARIO_DIR,
                    overwrite=overwrite_existing,
                )
            except (
                ScenarioStoreError,
                OSError,
                ValueError,
            ) as exc:
                st.error(
                    "The scenario could not be saved. "
                    f"Detail: {exc}"
                )
            else:
                activate_scenario(
                    saved.name,
                    league_state.state_revision,
                )
                st.session_state[
                    "trade_machine_state_notice"
                ] = (
                    f"Saved scenario: {saved.name}."
                )
                st.rerun()

        scenario_summaries = list_scenarios(
            base_runtime,
            directory=DEFAULT_SCENARIO_DIR,
        )
        valid_scenarios = [
            summary
            for summary in scenario_summaries
            if summary.valid
        ]
        invalid_scenarios = [
            summary
            for summary in scenario_summaries
            if not summary.valid
        ]

        st.divider()
        st.markdown("**Saved scenario library**")

        if invalid_scenarios:
            st.warning(
                f"{len(invalid_scenarios)} saved scenario file(s) "
                "failed validation and were excluded from loading."
            )

        if valid_scenarios:
            summary_by_path = {
                summary.path: summary
                for summary in valid_scenarios
            }
            selected_path = st.selectbox(
                "Saved scenario",
                options=list(summary_by_path),
                format_func=lambda path: (
                    f"{summary_by_path[path].name} · "
                    f"{summary_by_path[path].transaction_count} "
                    "trade(s)"
                ),
                key="trade_machine_saved_scenario",
            )
            selected_summary = summary_by_path[
                selected_path
            ]

            detail_columns = st.columns(4)
            detail_columns[0].metric(
                "Revision",
                selected_summary.state_revision,
            )
            detail_columns[1].metric(
                "Transactions",
                selected_summary.transaction_count,
            )
            detail_columns[2].metric(
                "Players",
                selected_summary.player_count,
            )
            detail_columns[3].metric(
                "Draft rights",
                selected_summary.draft_right_count,
            )

            if selected_summary.notes:
                st.caption(selected_summary.notes)

            library_actions = st.columns(
                [1.2, 1.2, 1.5],
                gap="small",
            )

            with library_actions[0]:
                load_clicked = st.button(
                    "Load scenario",
                    type="primary",
                    width="stretch",
                    key="trade_machine_load_scenario",
                )

            with library_actions[1]:
                confirm_delete = st.checkbox(
                    "Confirm delete",
                    key=(
                        "trade_machine_confirm_"
                        "scenario_delete"
                    ),
                )
                delete_clicked = st.button(
                    "Delete",
                    width="stretch",
                    disabled=not confirm_delete,
                    key="trade_machine_delete_scenario",
                )

            with library_actions[2]:
                scenario_bytes = Path(
                    selected_summary.path
                ).read_bytes()
                st.download_button(
                    "Export scenario JSON",
                    data=scenario_bytes,
                    file_name=Path(
                        selected_summary.path
                    ).name,
                    mime="application/json",
                    width="stretch",
                    key="trade_machine_export_scenario",
                )

            if load_clicked:
                try:
                    loaded_state, loaded_summary = (
                        load_scenario_file(
                            Path(selected_summary.path),
                            base_runtime,
                        )
                    )
                except (
                    ScenarioStoreError,
                    OSError,
                    ValueError,
                ) as exc:
                    st.error(
                        "The selected scenario could not be "
                        f"loaded. Detail: {exc}"
                    )
                else:
                    st.session_state[
                        "trade_machine_league_state"
                    ] = loaded_state
                    activate_scenario(
                        loaded_summary.name,
                        loaded_state.state_revision,
                    )
                    clear_trade_state()
                    st.session_state[
                        "trade_machine_state_notice"
                    ] = (
                        f"Loaded scenario: "
                        f"{loaded_summary.name}."
                    )
                    st.rerun()

            if delete_clicked:
                try:
                    delete_scenario(
                        selected_summary.name,
                        directory=DEFAULT_SCENARIO_DIR,
                    )
                except (
                    ScenarioStoreError,
                    OSError,
                    ValueError,
                ) as exc:
                    st.error(
                        "The selected scenario could not be "
                        f"deleted. Detail: {exc}"
                    )
                else:
                    active_name = st.session_state.get(
                        "trade_machine_active_scenario_name"
                    )
                    if active_name == selected_summary.name:
                        clear_active_scenario()
                    st.session_state[
                        "trade_machine_state_notice"
                    ] = (
                        f"Deleted scenario: "
                        f"{selected_summary.name}."
                    )
                    st.rerun()
        else:
            st.info(
                "No valid saved scenarios exist yet. "
                "Save the current league above to create one."
            )

        st.divider()
        st.markdown("**Import scenario JSON**")

        uploaded_scenario = st.file_uploader(
            "Choose an exported scenario file",
            type=["json"],
            key="trade_machine_import_upload",
        )
        import_name = st.text_input(
            "Imported scenario name override",
            placeholder=(
                "Leave blank to retain the exported name"
            ),
            max_chars=80,
            key="trade_machine_import_name",
        )
        import_overwrite = st.checkbox(
            "Replace an existing imported scenario",
            key="trade_machine_import_overwrite",
        )
        import_clicked = st.button(
            "Import and load scenario",
            width="stretch",
            disabled=uploaded_scenario is None,
            key="trade_machine_import_scenario",
        )

        if import_clicked and uploaded_scenario is not None:
            temporary_path: Path | None = None

            try:
                with tempfile.NamedTemporaryFile(
                    mode="wb",
                    suffix=".json",
                    delete=False,
                ) as handle:
                    handle.write(
                        uploaded_scenario.getvalue()
                    )
                    temporary_path = Path(handle.name)

                imported = import_scenario_file(
                    temporary_path,
                    base_runtime,
                    name=(
                        import_name.strip()
                        if import_name.strip()
                        else None
                    ),
                    directory=DEFAULT_SCENARIO_DIR,
                    overwrite=import_overwrite,
                )
                imported_state, imported_summary = (
                    load_scenario_file(
                        Path(imported.path),
                        base_runtime,
                    )
                )
            except (
                ScenarioStoreError,
                OSError,
                ValueError,
            ) as exc:
                st.error(
                    "The uploaded scenario could not be "
                    f"imported. Detail: {exc}"
                )
            else:
                st.session_state[
                    "trade_machine_league_state"
                ] = imported_state
                activate_scenario(
                    imported_summary.name,
                    imported_state.state_revision,
                )
                clear_trade_state()
                st.session_state[
                    "trade_machine_state_notice"
                ] = (
                    f"Imported and loaded scenario: "
                    f"{imported_summary.name}."
                )
                st.rerun()
            finally:
                if (
                    temporary_path is not None
                    and temporary_path.exists()
                ):
                    temporary_path.unlink()

with st.expander("How the V3 verdict works", expanded=False):
    st.markdown(
        """
        **PASS** means the package cleared every connected deterministic stage.
        **BLOCKED** means at least one verified rule failed.
        **MANUAL REVIEW** means the package may be workable, but unresolved
        consent, contract mechanics, team evidence, or right-specific evidence
        prevents a deterministic release.

        V3 includes player-CBA evidence, verified team salary routes, roster and
        apron tests, right-legality evidence, frozen-pick screening, and combined
        package-level Stepien analysis.
        """
    )

st.markdown(
    '<div class="tm-section-kicker">Trade experience</div>',
    unsafe_allow_html=True,
)

with st.container(border=True):
    mode_label = st.radio(
        "Choose how strictly the transaction should be judged",
        options=["Sandbox Mode", "Realism Mode"],
        index=0,
        horizontal=True,
        key="trade_machine_mode_selector",
        on_change=clear_trade_audit_state,
    )

    trade_mode = (
        TradeMode.SANDBOX
        if mode_label == "Sandbox Mode"
        else TradeMode.REALISM
    )

    if trade_mode == TradeMode.SANDBOX:
        st.info(
            "Sandbox Mode is built for team building and future "
            "simulation play. Missing player-CBA evidence becomes "
            "a visible warning, while structural errors still "
            "remain blocked. Strict rule failures may be force-"
            "traded after confirmation."
        )
    else:
        st.caption(
            "Realism Mode preserves the strict V3 CBA, salary, "
            "apron, roster, draft-right, and Stepien verdict. "
            "Only deterministic PASS transactions can be applied."
        )

st.markdown(
    '<div class="tm-section-kicker">01 · Build the package</div>',
    unsafe_allow_html=True,
)

side_columns = st.columns(2, gap="large")

with side_columns[0]:
    with st.container(border=True):
        team_a = st.selectbox(
            "Team A franchise",
            teams,
            index=teams.index("CHI") if "CHI" in teams else 0,
            format_func=team_label,
            key="trade_machine_team_a",
        )
        render_team_header(
            visual_assets,
            runtime,
            team_a,
            "Team A · Sending assets",
        )

        team_a_player_options = team_players(runtime, team_a)
        team_a_pick_options = team_picks(runtime, team_a)

        team_a_players = st.multiselect(
            "Outgoing players",
            team_a_player_options,
            format_func=lambda player_id: player_label(
                runtime,
                player_id,
            ),
            key=(
                f"trade_machine_players_side_a_{team_a}_"
                f"r{league_state.state_revision}"
            ),
            placeholder="Search the roster",
        )

        team_a_picks = st.multiselect(
            "Outgoing draft rights",
            team_a_pick_options,
            format_func=lambda pick_id: pick_label(
                runtime,
                pick_id,
            ),
            key=(
                f"trade_machine_picks_side_a_{team_a}_"
                f"r{league_state.state_revision}"
            ),
            placeholder="Add a future draft right",
        )

        render_asset_preview(
            runtime,
            team_a_players,
            team_a_picks,
        )

with side_columns[1]:
    with st.container(border=True):
        default_b = "DET" if "DET" in teams else teams[1]
        team_b = st.selectbox(
            "Team B franchise",
            teams,
            index=teams.index(default_b),
            format_func=team_label,
            key="trade_machine_team_b",
        )
        render_team_header(
            visual_assets,
            runtime,
            team_b,
            "Team B · Sending assets",
        )

        team_b_player_options = team_players(runtime, team_b)
        team_b_pick_options = team_picks(runtime, team_b)

        team_b_players = st.multiselect(
            "Outgoing players",
            team_b_player_options,
            format_func=lambda player_id: player_label(
                runtime,
                player_id,
            ),
            key=(
                f"trade_machine_players_side_b_{team_b}_"
                f"r{league_state.state_revision}"
            ),
            placeholder="Search the roster",
        )

        team_b_picks = st.multiselect(
            "Outgoing draft rights",
            team_b_pick_options,
            format_func=lambda pick_id: pick_label(
                runtime,
                pick_id,
            ),
            key=(
                f"trade_machine_picks_side_b_{team_b}_"
                f"r{league_state.state_revision}"
            ),
            placeholder="Add a future draft right",
        )

        render_asset_preview(
            runtime,
            team_b_players,
            team_b_picks,
        )

if team_a == team_b:
    st.error("Choose two different franchises before running the audit.")

render_trade_rail()

action_columns = st.columns([4.5, 1.1], gap="small")
with action_columns[0]:
    evaluate_clicked = st.button(
        (
            "Evaluate sandbox trade"
            if trade_mode == TradeMode.SANDBOX
            else "Run V3 realism audit"
        ),
        type="primary",
        width="stretch",
        disabled=(team_a == team_b),
        help=(
            "Choose two different franchises."
            if team_a == team_b
            else None
        ),
    )

with action_columns[1]:
    st.button(
        "Clear",
        type="secondary",
        width="stretch",
        on_click=clear_trade_state,
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

        policy = classify_trade(
            runtime,
            request,
            mode=trade_mode,
        )
        result = policy.strict_evaluation

        st.session_state["trade_machine_last_result"] = result
        st.session_state["trade_machine_last_policy"] = policy
        st.session_state["trade_machine_last_selection"] = {
            "team_a": team_a,
            "team_b": team_b,
            "team_a_players": list(team_a_players),
            "team_b_players": list(team_b_players),
            "team_a_picks": list(team_a_picks),
            "team_b_picks": list(team_b_picks),
            "state_revision": league_state.state_revision,
            "trade_mode": trade_mode.value,
        }

result = st.session_state.get("trade_machine_last_result")
policy = st.session_state.get("trade_machine_last_policy")
selection = st.session_state.get("trade_machine_last_selection")

if (
    result is not None
    and policy is not None
    and selection is not None
):
    st.markdown(
        '<div class="tm-section-kicker">02 · Trade verdict</div>',
        unsafe_allow_html=True,
    )
    render_trade_mode_banner(policy)

    if policy.mode == TradeMode.REALISM:
        render_resolution_guidance(result)
    elif policy.warnings:
        with st.expander(
            "Strict realism warnings preserved",
            expanded=(
                policy.disposition
                != SandboxDisposition.VERIFIED
            ),
        ):
            for warning in policy.warnings:
                st.warning(
                    friendly_trade_message(warning)
                )

    can_offer_apply = (
        policy.can_apply_without_force
        or policy.force_allowed
    )

    if can_offer_apply:
        with st.container(border=True):
            force_trade = (
                policy.disposition
                == SandboxDisposition.FORCE_REQUIRED
            )

            apply_columns = st.columns([3.8, 1.6])

            with apply_columns[0]:
                st.markdown(
                    (
                        "**Force this transaction into the "
                        "simulation universe**"
                        if force_trade
                        else "**Commit this transaction**"
                    )
                )
                st.caption(
                    (
                        "Force Trade bypasses non-structural "
                        "realism rules, but still updates rosters, "
                        "listed salaries, draft-right ownership, "
                        "history, undo, and saved scenarios."
                        if force_trade
                        else (
                            "The package will update both rosters, "
                            "team financials, draft-right ownership, "
                            "and all later Trade Machine evaluations."
                        )
                    )
                )

                force_confirmed = False
                if force_trade:
                    force_confirmed = st.checkbox(
                        "I understand this trade failed strict "
                        "realism rules and want to force it.",
                        key=(
                            "trade_machine_force_confirmation_"
                            f"r{league_state.state_revision}"
                        ),
                    )

            with apply_columns[1]:
                apply_clicked = st.button(
                    (
                        "Force trade"
                        if force_trade
                        else (
                            "Apply sandbox trade"
                            if policy.mode
                            == TradeMode.SANDBOX
                            else "Apply approved trade"
                        )
                    ),
                    type="primary",
                    width="stretch",
                    disabled=(
                        force_trade
                        and not force_confirmed
                    ),
                    key=(
                        "trade_machine_apply_"
                        f"{policy.mode.value}_"
                        f"r{league_state.state_revision}"
                    ),
                )

            if apply_clicked:
                audited_revision = selection.get(
                    "state_revision"
                )
                audited_mode = selection.get(
                    "trade_mode"
                )

                if (
                    audited_revision
                    != league_state.state_revision
                ):
                    st.error(
                        "The league changed after this evaluation. "
                        "Evaluate the package again before applying it."
                    )
                elif audited_mode != trade_mode.value:
                    st.error(
                        "The trade mode changed after this evaluation. "
                        "Evaluate the package again."
                    )
                else:
                    request = selection_request(selection)

                    try:
                        trial_state = copy.deepcopy(
                            league_state
                        )
                        apply_trade_in_mode(
                            trial_state,
                            runtime,
                            request,
                            mode=policy.mode,
                            force=force_trade,
                        )
                        build_state_runtime(
                            base_runtime,
                            trial_state,
                        )

                        applied = apply_trade_in_mode(
                            league_state,
                            runtime,
                            request,
                            mode=policy.mode,
                            force=force_trade,
                        )
                        record = applied.transaction
                    except (
                        TradeModePolicyError,
                        StateMutationError,
                        StateRuntimeAdapterError,
                        ValueError,
                        KeyError,
                    ) as exc:
                        st.error(
                            "The transaction could not be committed "
                            f"to league state. Detail: {exc}"
                        )
                    else:
                        clear_trade_state()
                        st.session_state[
                            "trade_machine_state_notice"
                        ] = (
                            (
                                "Force-applied "
                                if force_trade
                                else "Applied "
                            )
                            + f"{record.transaction_id}: "
                            + f"{record.team_a} ↔ "
                            + f"{record.team_b}."
                        )
                        st.rerun()

    st.caption(
        "The Legality Audit tab below always preserves the "
        "strict V3 result, even when Sandbox Mode allows the "
        "transaction to remain playable."
    )

    overview_tab, audit_tab = st.tabs(
        ["Trade overview", "Legality audit"]
    )

    with overview_tab:
        summary_columns = st.columns(2, gap="large")

        with summary_columns[0]:
            with st.container(border=True):
                render_side_summary(
                    visual_assets=visual_assets,
                    runtime=runtime,
                    team=selection["team_a"],
                    player_ids=selection["team_a_players"],
                    pick_right_ids=selection["team_a_picks"],
                    side=result.side_a,
                )

        with summary_columns[1]:
            with st.container(border=True):
                render_side_summary(
                    visual_assets=visual_assets,
                    runtime=runtime,
                    team=selection["team_b"],
                    player_ids=selection["team_b_players"],
                    pick_right_ids=selection["team_b_picks"],
                    side=result.side_b,
                )

    with audit_tab:
        if result.checks:
            st.markdown("#### Transaction-wide checks")
            for check in result.checks:
                render_check(check)

        check_columns = st.columns(2, gap="large")

        with check_columns[0]:
            st.markdown(
                f"#### {escaped(selection['team_a'])} audit"
            )
            for check in result.side_a.checks:
                render_check(check)

        with check_columns[1]:
            st.markdown(
                f"#### {escaped(selection['team_b'])} audit"
            )
            for check in result.side_b.checks:
                render_check(check)

        with st.expander("Validation scope and interpretation"):
            st.markdown(
                """
                - Salary matching, aggregation, roster limits, and hard-cap
                  outcomes use the verified team-CBA release and V9-validated
                  formulas.
                - Draft rights are screened for canonical inventory, assigned
                  team, standalone-right evidence, frozen-pick status, and
                  combined package-level Stepien effects.
                - Manual review is intentionally conservative and is not the
                  same as a deterministic illegal-trade ruling.
                """
            )