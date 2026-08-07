from __future__ import annotations

import copy
import html
import importlib.util
import secrets
import sys
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

# Always prioritize this project's src directory. This avoids importing an
# older copy of a simulator module from another path already on sys.path.
while str(SRC) in sys.path:
    sys.path.remove(str(SRC))
sys.path.insert(0, str(SRC))

from freeform_trade_machine_engine_v3 import (  # noqa: E402
    RuntimeData,
    load_runtime_data,
)
from mutable_league_state_v1 import (  # noqa: E402
    STATE_VERSION,
    LeagueState,
    StateMutationError,
    create_league_state,
)
def load_local_roster_validator():
    """Load the validator from this project's exact src file.

    Streamlit can retain an older module object in sys.modules across page
    reruns. Loading under a private name prevents that stale object from
    shadowing the newly installed validator.
    """
    module_path = SRC / "simulation_roster_validator_v1.py"
    module_name = "_game_simulator_local_roster_validator_v1"
    spec = importlib.util.spec_from_file_location(
        module_name,
        module_path,
    )

    if spec is None or spec.loader is None:
        raise ImportError(
            "Could not create an import specification for "
            f"{module_path}."
        )

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)

    required = (
        "VALIDATOR_VERSION",
        "POSITION_DATA_PATH",
        "load_position_records",
        "player_position",
    )
    missing = [
        name
        for name in required
        if not hasattr(module, name)
    ]
    if missing:
        raise ImportError(
            "The local simulation roster validator is missing: "
            + ", ".join(missing)
            + f". Loaded from {module_path}."
        )

    return module


roster_validator = load_local_roster_validator()
from simulation_league_state_v1 import (  # noqa: E402
    SIMULATION_STATE_VERSION,
    GameStatus,
    ScheduledGame,
    SimulationLeagueState,
    SimulationLeagueStateError,
    add_scheduled_games,
    create_simulation_league_state,
    validate_simulation_league_state,
)
from single_game_simulator_v1 import (  # noqa: E402
    GameSimulationMetadata,
    SimulatedGame,
    SingleGameSimulationError,
    simulate_scheduled_game,
)
from state_runtime_adapter_v1 import (  # noqa: E402
    StateRuntimeAdapterError,
    build_state_runtime,
)


st.set_page_config(
    page_title="NBA Game Simulator",
    page_icon="🏀",
    layout="wide",
)


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


@st.cache_resource(show_spinner="Loading simulation engine...")
def get_base_runtime() -> RuntimeData:
    return load_runtime_data()


def get_trade_league_state(
    base_runtime: RuntimeData,
) -> LeagueState:
    key = "trade_machine_league_state"
    state = st.session_state.get(key)

    if (
        not isinstance(state, LeagueState)
        or state.state_version != STATE_VERSION
    ):
        state = create_league_state(base_runtime)
        st.session_state[key] = state

    return state


def clear_game_preview() -> None:
    for key in {
        "game_simulator_preview",
        "game_simulator_preview_request",
    }:
        st.session_state.pop(key, None)


def away_team_changed() -> None:
    clear_game_preview()
    st.session_state.pop(
        "game_simulator_away_sit",
        None,
    )


def home_team_changed() -> None:
    clear_game_preview()
    st.session_state.pop(
        "game_simulator_home_sit",
        None,
    )


def current_position_signature() -> tuple[str, str, int, int]:
    path = roster_validator.POSITION_DATA_PATH
    modified_ns = (
        path.stat().st_mtime_ns
        if path.exists()
        else -1
    )
    records = roster_validator.load_position_records()
    return (
        roster_validator.VALIDATOR_VERSION,
        str(path.resolve()),
        modified_ns,
        len(records),
    )


def apply_latest_player_positions(
    state: SimulationLeagueState,
    runtime: RuntimeData,
) -> None:
    # The position loader is cached. Clear it whenever a fresh simulation
    # state is built so a newly installed data file cannot remain hidden
    # behind an older empty or stale cache entry.
    roster_validator.load_position_records.cache_clear()
    records = roster_validator.load_position_records()

    if not records:
        raise SimulationLeagueStateError(
            "The player-position layer loaded zero records from "
            f"{roster_validator.POSITION_DATA_PATH}."
        )

    unresolved: list[str] = []

    for player_id, player in state.players.items():
        if player.synthetic:
            continue

        resolved = roster_validator.player_position(
            runtime,
            player_id,
        )
        if resolved == "UNK":
            unresolved.append(
                f"{player.player_name} ({player_id})"
            )
            continue

        # SimulationPlayerState is mutable, so update the permanent state
        # rather than merely changing the displayed dataframe.
        player.position = resolved

    if unresolved:
        sample = ", ".join(unresolved[:8])
        suffix = (
            f" and {len(unresolved) - 8} more"
            if len(unresolved) > 8
            else ""
        )
        raise SimulationLeagueStateError(
            "Player-position enrichment still returned UNK for "
            f"{len(unresolved)} real player(s): {sample}{suffix}. "
            "The app is now refusing to silently display an "
            "unenriched simulation state."
        )


def create_fresh_simulation_state(
    runtime: RuntimeData,
    trade_state: LeagueState,
) -> SimulationLeagueState:
    state = create_simulation_league_state(
        runtime,
        trade_state,
    )
    apply_latest_player_positions(
        state,
        runtime,
    )
    st.session_state[
        "game_simulator_league_state"
    ] = state
    st.session_state[
        "game_simulator_source_trade_object_id"
    ] = id(trade_state)
    st.session_state[
        "game_simulator_position_signature"
    ] = current_position_signature()
    clear_game_preview()
    return state


def get_simulation_state(
    runtime: RuntimeData,
    trade_state: LeagueState,
) -> tuple[SimulationLeagueState, bool]:
    key = "game_simulator_league_state"
    state = st.session_state.get(key)
    rebuilt = False

    positions_current = bool(
        isinstance(state, SimulationLeagueState)
        and all(
            player.synthetic
            or player.position != "UNK"
            for player in state.players.values()
        )
    )
    valid = (
        isinstance(state, SimulationLeagueState)
        and state.state_version
        == SIMULATION_STATE_VERSION
        and state.source_league_state_revision
        == trade_state.state_revision
        and state.source_transaction_count
        == len(trade_state.transaction_history)
        and st.session_state.get(
            "game_simulator_source_trade_object_id"
        )
        == id(trade_state)
        and st.session_state.get(
            "game_simulator_position_signature"
        )
        == current_position_signature()
        and positions_current
    )

    if not valid:
        state = create_fresh_simulation_state(
            runtime,
            trade_state,
        )
        rebuilt = True

    return state, rebuilt


def escaped(value: Any) -> str:
    return html.escape(str(value))


def team_label(team: str) -> str:
    return f"{TEAM_NAMES.get(team, team)} ({team})"


def percent(value: float) -> str:
    return f"{value:.1%}"


def player_label(
    state: SimulationLeagueState,
    player_id: str,
) -> str:
    player = state.players[player_id]
    position = (
        player.position
        if player.position != "UNK"
        else "Position unavailable"
    )
    return (
        f"{player.player_name} · {position} · "
        f"{player.overall_rating:.1f} OVR"
    )


def inject_styles() -> None:
    st.markdown(
        """
<style>
:root {
  --gs-ink: #101828;
  --gs-muted: #667085;
  --gs-line: #e4e7ec;
  --gs-soft: #f8fafc;
  --gs-blue: #175cd3;
  --gs-navy: #0b1f3a;
  --gs-green: #067647;
  --gs-red: #b42318;
  --gs-gold: #b54708;
}
.block-container {
  max-width: 1480px;
  padding-top: 1.35rem;
  padding-bottom: 4rem;
}
.gs-hero {
  position: relative;
  overflow: hidden;
  border-radius: 24px;
  padding: 30px 34px;
  margin-bottom: 20px;
  color: white;
  background:
    radial-gradient(circle at 88% 20%, rgba(255,255,255,.18), transparent 24%),
    linear-gradient(130deg, #07182d 0%, #153c70 55%, #2563a9 100%);
  box-shadow: 0 20px 45px rgba(16,24,40,.16);
}
.gs-hero-kicker {
  font-size: .72rem;
  letter-spacing: .17em;
  text-transform: uppercase;
  font-weight: 800;
  opacity: .78;
}
.gs-hero-title {
  margin-top: 7px;
  font-size: clamp(2rem, 4vw, 3.35rem);
  font-weight: 850;
  line-height: 1.02;
  letter-spacing: -.045em;
}
.gs-hero-copy {
  max-width: 780px;
  margin-top: 12px;
  font-size: 1rem;
  line-height: 1.65;
  opacity: .86;
}
.gs-section {
  margin-top: 22px;
  margin-bottom: 8px;
  color: #344054;
  font-size: .73rem;
  font-weight: 850;
  letter-spacing: .13em;
  text-transform: uppercase;
}
.gs-scoreboard {
  border: 1px solid var(--gs-line);
  border-radius: 24px;
  overflow: hidden;
  background: white;
  box-shadow: 0 14px 35px rgba(16,24,40,.09);
}
.gs-score-top {
  padding: 12px 18px;
  color: white;
  text-align: center;
  background: var(--gs-navy);
  font-size: .72rem;
  font-weight: 800;
  letter-spacing: .14em;
  text-transform: uppercase;
}
.gs-score-body {
  display: grid;
  grid-template-columns: 1fr auto 1fr;
  align-items: center;
  gap: 22px;
  padding: 28px 28px 24px;
}
.gs-team {
  min-width: 0;
}
.gs-team.away {
  text-align: right;
}
.gs-abbr {
  color: var(--gs-muted);
  font-size: .72rem;
  font-weight: 850;
  letter-spacing: .12em;
}
.gs-team-name {
  margin-top: 2px;
  color: var(--gs-ink);
  font-size: clamp(1.1rem, 2vw, 1.55rem);
  font-weight: 800;
}
.gs-score {
  margin-top: 7px;
  color: var(--gs-ink);
  font-size: clamp(3rem, 6vw, 5.1rem);
  font-weight: 900;
  letter-spacing: -.06em;
  line-height: .95;
}
.gs-center {
  color: #98a2b3;
  font-size: .77rem;
  font-weight: 800;
  text-align: center;
  letter-spacing: .12em;
}
.gs-winner {
  display: inline-block;
  margin-top: 7px;
  border-radius: 999px;
  padding: 4px 9px;
  color: #027a48;
  background: #ecfdf3;
  font-size: .67rem;
  font-weight: 850;
  letter-spacing: .08em;
}
.gs-card-title {
  color: inherit;
  font-size: 1rem;
  font-weight: 800;
}
.gs-card-copy {
  margin-top: 4px;
  color: #98a2b3;
  font-size: .84rem;
  line-height: 1.5;
}
.gs-source {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  margin-bottom: 14px;
  border: 1px solid #b2ddff;
  border-radius: 999px;
  padding: 7px 11px;
  color: #175cd3;
  background: #eff8ff;
  font-size: .76rem;
  font-weight: 750;
}
.gs-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #2e90fa;
}
.gs-warning {
  border: 1px solid #fedf89;
  border-radius: 14px;
  padding: 12px 14px;
  color: #93370d;
  background: #fffaeb;
  font-size: .84rem;
  line-height: 1.5;
}
@media (max-width: 760px) {
  .gs-score-body {
    grid-template-columns: 1fr;
  }
  .gs-team,
  .gs-team.away {
    text-align: center;
  }
  .gs-center {
    display: none;
  }
}
</style>
        """,
        unsafe_allow_html=True,
    )


def render_hero(
    trade_state: LeagueState,
    simulation_state: SimulationLeagueState,
) -> None:
    st.markdown(
        f"""
<div class="gs-hero">
  <div class="gs-hero-kicker">Front Office Simulation Lab</div>
  <div class="gs-hero-title">NBA Game Simulator</div>
  <div class="gs-hero-copy">
    Choose a matchup, adjust who plays, preview a seeded result,
    inspect the full box score, and commit the game to the shared
    season standings.
  </div>
</div>
<div class="gs-source">
  <span class="gs-dot"></span>
  Trade universe revision {trade_state.state_revision}
  · {len(trade_state.transaction_history)} applied trade(s)
  · {len(simulation_state.completed_games)} completed game(s)
</div>
        """,
        unsafe_allow_html=True,
    )


def team_roster_dataframe(
    state: SimulationLeagueState,
    team: str,
) -> pd.DataFrame:
    team_state = state.teams[team]
    starter_ids = set(
        team_state.rotation.starter_ids
    )
    rotation_ids = set(
        team_state.rotation.rotation_player_ids
    )
    rows = []

    for player_id in team_state.roster_player_ids:
        player = state.players[player_id]
        injury = state.injuries[player_id]
        role = (
            "Starter"
            if player_id in starter_ids
            else "Rotation"
            if player_id in rotation_ids
            else "Reserve"
        )
        rows.append(
            {
                "Player": player.player_name,
                "Pos": player.position,
                "OVR": round(
                    player.overall_rating,
                    1,
                ),
                "Role": role,
                "Availability": (
                    injury.status.value
                    .replace("_", " ")
                    .title()
                ),
                "Target Min": (
                    team_state.rotation
                    .minutes_targets.get(
                        player_id,
                        0.0,
                    )
                ),
            }
        )

    return pd.DataFrame(rows)


def box_score_dataframe(
    state: SimulationLeagueState,
    preview: SimulatedGame,
) -> pd.DataFrame:
    game = preview.game
    team_order = {
        game.away_team: 0,
        game.home_team: 1,
    }
    rows = []

    for line in game.player_box_scores:
        player = state.players[line.player_id]
        rows.append(
            {
                "_team_order": team_order[
                    line.team_abbreviation
                ],
                "_starter_order": (
                    0 if line.started else 1
                ),
                "_minutes_order": -line.minutes,
                "Team": line.team_abbreviation,
                "Player": player.player_name,
                "Pos": player.position,
                "Starter": (
                    "Yes" if line.started else ""
                ),
                "MIN": line.minutes,
                "PTS": line.points,
                "REB": line.rebounds,
                "AST": line.assists,
                "STL": line.steals,
                "BLK": line.blocks,
                "TO": line.turnovers,
                "PF": line.fouls,
                "FG": (
                    f"{line.field_goals_made}-"
                    f"{line.field_goals_attempted}"
                ),
                "3PT": (
                    f"{line.three_pointers_made}-"
                    f"{line.three_pointers_attempted}"
                ),
                "FT": (
                    f"{line.free_throws_made}-"
                    f"{line.free_throws_attempted}"
                ),
            }
        )

    frame = pd.DataFrame(rows)
    frame = frame.sort_values(
        [
            "_team_order",
            "_starter_order",
            "_minutes_order",
        ]
    )
    return frame.drop(
        columns=[
            "_team_order",
            "_starter_order",
            "_minutes_order",
        ]
    )


def standings_dataframe(
    state: SimulationLeagueState,
) -> pd.DataFrame:
    rows = []

    for team, standing in state.standings.items():
        differential = (
            standing.points_for
            - standing.points_against
        )
        rows.append(
            {
                "Team": team,
                "GP": standing.games_played,
                "W": standing.wins,
                "L": standing.losses,
                "Win%": (
                    standing.wins
                    / standing.games_played
                    if standing.games_played
                    else 0.0
                ),
                "PF": standing.points_for,
                "PA": standing.points_against,
                "Diff": differential,
                "Streak": (
                    f"{standing.streak_type}"
                    f"{standing.streak_length}"
                    if standing.streak_length
                    else ""
                ),
            }
        )

    return (
        pd.DataFrame(rows)
        .sort_values(
            ["Win%", "Diff", "PF", "Team"],
            ascending=[False, False, False, True],
        )
        .reset_index(drop=True)
    )


def leaders_dataframe(
    state: SimulationLeagueState,
    preview: SimulatedGame,
) -> pd.DataFrame:
    lines = sorted(
        preview.game.player_box_scores,
        key=lambda line: (
            -line.points,
            -line.assists,
            -line.rebounds,
            line.player_id,
        ),
    )[:6]
    return pd.DataFrame(
        [
            {
                "Player": (
                    state.players[
                        line.player_id
                    ].player_name
                ),
                "Team": line.team_abbreviation,
                "PTS": line.points,
                "REB": line.rebounds,
                "AST": line.assists,
                "STL": line.steals,
                "BLK": line.blocks,
                "TO": line.turnovers,
                "PF": line.fouls,
                "MIN": line.minutes,
            }
            for line in lines
        ]
    )


def render_scoreboard(
    preview: SimulatedGame,
) -> None:
    game = preview.game
    home_won = (
        game.home_score > game.away_score
    )
    overtime = (
        f"{game.overtime_periods} OT"
        if game.overtime_periods
        else "FINAL"
    )
    away_winner = (
        '<div class="gs-winner">WINNER</div>'
        if not home_won
        else ""
    )
    home_winner = (
        '<div class="gs-winner">WINNER</div>'
        if home_won
        else ""
    )
    away_name = escaped(
        TEAM_NAMES.get(
            game.away_team,
            game.away_team,
        )
    )
    home_name = escaped(
        TEAM_NAMES.get(
            game.home_team,
            game.home_team,
        )
    )
    scoreboard_html = (
        '<div class="gs-scoreboard">'
        f'<div class="gs-score-top">{escaped(overtime)}</div>'
        '<div class="gs-score-body">'
        '<div class="gs-team away">'
        f'<div class="gs-abbr">AWAY · {escaped(game.away_team)}</div>'
        f'<div class="gs-team-name">{away_name}</div>'
        f'<div class="gs-score">{game.away_score}</div>'
        f'{away_winner}'
        '</div>'
        '<div class="gs-center">VS</div>'
        '<div class="gs-team">'
        f'<div class="gs-abbr">HOME · {escaped(game.home_team)}</div>'
        f'<div class="gs-team-name">{home_name}</div>'
        f'<div class="gs-score">{game.home_score}</div>'
        f'{home_winner}'
        '</div>'
        '</div>'
        '</div>'
    )
    st.markdown(
        scoreboard_html,
        unsafe_allow_html=True,
    )


def preview_request_matches(
    request: dict[str, Any],
    *,
    home_team: str,
    away_team: str,
    locked_seed: int | None,
    lock_seed: bool,
    sit_ids: tuple[str, ...],
    source_revision: int,
) -> bool:
    seed_matches = (
        request.get("seed") == locked_seed
        if lock_seed
        else not request.get("lock_seed", False)
    )
    return bool(
        request.get("home_team") == home_team
        and request.get("away_team") == away_team
        and request.get("lock_seed") == lock_seed
        and seed_matches
        and tuple(request.get("sit_ids", ()))
        == sit_ids
        and request.get("source_revision")
        == source_revision
    )


base_runtime = get_base_runtime()
trade_state = get_trade_league_state(
    base_runtime
)

try:
    runtime = build_state_runtime(
        base_runtime,
        trade_state,
    )
except (
    StateRuntimeAdapterError,
    StateMutationError,
    ValueError,
    KeyError,
) as exc:
    st.error(
        "The current trade universe could not be converted "
        f"into a simulation runtime. Detail: {exc}"
    )
    st.stop()

try:
    simulation_state, rebuilt = get_simulation_state(
        runtime,
        trade_state,
    )
    validate_simulation_league_state(
        simulation_state
    )
except (
    SimulationLeagueStateError,
    ValueError,
    KeyError,
) as exc:
    st.error(
        "The simulation season could not be initialized. "
        f"Detail: {exc}"
    )
    st.stop()

inject_styles()
render_hero(
    trade_state,
    simulation_state,
)

if rebuilt:
    if (
        trade_state.state_revision > 0
        or len(trade_state.transaction_history) > 0
    ):
        st.info(
            "The simulation season was rebuilt from the latest "
            "Trade Machine universe so every applied roster move "
            "is reflected here."
        )
    else:
        st.info(
            "The simulation season was refreshed from the latest "
            "roster and player-position data."
        )

notice = st.session_state.pop(
    "game_simulator_notice",
    None,
)
if notice:
    st.success(notice)

st.markdown(
    '<div class="gs-section">01 · Build the matchup</div>',
    unsafe_allow_html=True,
)

teams = sorted(simulation_state.teams)
selector_columns = st.columns(2)

with selector_columns[0]:
    away_team = st.selectbox(
        "Away team",
        options=teams,
        index=teams.index("BKN")
        if "BKN" in teams
        else 0,
        format_func=team_label,
        key="game_simulator_away_team",
        on_change=away_team_changed,
    )

with selector_columns[1]:
    default_home = (
        "ATL"
        if "ATL" in teams
        and "ATL" != away_team
        else next(
            team
            for team in teams
            if team != away_team
        )
    )
    home_team = st.selectbox(
        "Home team",
        options=teams,
        index=teams.index(default_home),
        format_func=team_label,
        key="game_simulator_home_team",
        on_change=home_team_changed,
    )

same_team = away_team == home_team

if same_team:
    st.error(
        "Choose two different teams before simulating."
    )

control_columns = st.columns([1.5, 1.5, 1])

away_options = list(
    simulation_state.teams[
        away_team
    ].roster_player_ids
)
home_options = list(
    simulation_state.teams[
        home_team
    ].roster_player_ids
)

with control_columns[0]:
    away_sit = st.multiselect(
        f"{away_team} players to sit",
        options=away_options,
        format_func=lambda player_id: player_label(
            simulation_state,
            player_id,
        ),
        key="game_simulator_away_sit",
        on_change=clear_game_preview,
        help=(
            "Use this for injuries, rest, or a coaching "
            "decision. The engine automatically promotes "
            "available reserves."
        ),
    )

with control_columns[1]:
    home_sit = st.multiselect(
        f"{home_team} players to sit",
        options=home_options,
        format_func=lambda player_id: player_label(
            simulation_state,
            player_id,
        ),
        key="game_simulator_home_sit",
        on_change=clear_game_preview,
        help=(
            "Sitting a starter causes the next available "
            "rotation player or reserve to replace them."
        ),
    )

with control_columns[2]:
    lock_seed = st.toggle(
        "Lock seed",
        value=False,
        key="game_simulator_lock_seed",
        on_change=clear_game_preview,
        help=(
            "Turn this on when you want the same matchup "
            "and player availability to reproduce the exact "
            "same result."
        ),
    )

    if lock_seed:
        locked_seed: int | None = int(
            st.number_input(
                "Simulation seed",
                min_value=1,
                max_value=2_147_483_647,
                value=20_260_808,
                step=1,
                key="game_simulator_seed",
                on_change=clear_game_preview,
            )
        )
    else:
        locked_seed = None
        st.caption(
            "Fresh result each time you click Simulate game."
        )

sit_ids = tuple(
    sorted(
        {
            *away_sit,
            *home_sit,
        }
    )
)

roster_tabs = st.tabs(
    [
        f"{away_team} rotation",
        f"{home_team} rotation",
    ]
)

with roster_tabs[0]:
    st.dataframe(
        team_roster_dataframe(
            simulation_state,
            away_team,
        ),
        hide_index=True,
        width="stretch",
    )

with roster_tabs[1]:
    st.dataframe(
        team_roster_dataframe(
            simulation_state,
            home_team,
        ),
        hide_index=True,
        width="stretch",
    )

action_columns = st.columns([1.5, 1.5, 5])

with action_columns[0]:
    preview_clicked = st.button(
        "Simulate game",
        type="primary",
        width="stretch",
        disabled=same_team,
        key="game_simulator_preview_button",
    )

with action_columns[1]:
    reset_clicked = st.button(
        "Reset season",
        width="stretch",
        key="game_simulator_reset_button",
        help=(
            "Clears simulated games and rebuilds the season "
            "from the current Trade Machine universe."
        ),
    )

if reset_clicked:
    simulation_state = create_fresh_simulation_state(
        runtime,
        trade_state,
    )
    st.session_state[
        "game_simulator_notice"
    ] = (
        "The simulation season was reset from the current "
        "trade universe."
    )
    st.rerun()

if preview_clicked:
    resolved_seed = (
        locked_seed
        if lock_seed
        else secrets.randbelow(
            2_147_483_647
        )
        + 1
    )
    game_number = (
        len(simulation_state.schedule) + 1
    )
    game_id = (
        f"UI-GAME-{game_number:04d}"
    )
    day_index = (
        simulation_state.current_day_index + 1
    )
    trial_state = copy.deepcopy(
        simulation_state
    )

    try:
        add_scheduled_games(
            trial_state,
            [
                ScheduledGame(
                    game_id=game_id,
                    day_index=day_index,
                    home_team=home_team,
                    away_team=away_team,
                )
            ],
        )
        preview = simulate_scheduled_game(
            trial_state,
            game_id,
            seed=resolved_seed,
            commit=False,
            sit_player_ids=sit_ids,
        )
    except (
        SingleGameSimulationError,
        SimulationLeagueStateError,
        ValueError,
        KeyError,
    ) as exc:
        st.error(
            "The matchup could not be simulated. "
            f"Detail: {exc}"
        )
    else:
        st.session_state[
            "game_simulator_preview"
        ] = preview
        st.session_state[
            "game_simulator_preview_request"
        ] = {
            "game_id": game_id,
            "day_index": day_index,
            "home_team": home_team,
            "away_team": away_team,
            "seed": resolved_seed,
            "lock_seed": lock_seed,
            "sit_ids": sit_ids,
            "source_revision": (
                trade_state.state_revision
            ),
        }

preview = st.session_state.get(
    "game_simulator_preview"
)
preview_request = st.session_state.get(
    "game_simulator_preview_request"
)

if (
    isinstance(preview, SimulatedGame)
    and isinstance(preview_request, dict)
):
    st.markdown(
        '<div class="gs-section">02 · Game result</div>',
        unsafe_allow_html=True,
    )
    render_scoreboard(preview)

    metadata: GameSimulationMetadata = (
        preview.metadata
    )
    metric_columns = st.columns(6)
    metric_columns[0].metric(
        "Pace",
        f"{metadata.pace:.1f}",
    )
    metric_columns[1].metric(
        f"Pregame {home_team} win chance",
        percent(
            metadata.home_win_probability
        ),
    )
    metric_columns[2].metric(
        f"{away_team} rating",
        f"{metadata.away_team_rating:.1f}",
    )
    metric_columns[3].metric(
        f"{home_team} rating",
        f"{metadata.home_team_rating:.1f}",
    )
    metric_columns[4].metric(
        f"Expected {away_team}",
        f"{metadata.expected_away_score:.1f}",
    )
    metric_columns[5].metric(
        f"Expected {home_team}",
        f"{metadata.expected_home_score:.1f}",
    )

    result_tabs = st.tabs(
        [
            "Box Score",
            "Top Performers",
            "Simulation Detail",
        ]
    )

    with result_tabs[0]:
        st.dataframe(
            box_score_dataframe(
                simulation_state,
                preview,
            ),
            hide_index=True,
            width="stretch",
        )

    with result_tabs[1]:
        st.dataframe(
            leaders_dataframe(
                simulation_state,
                preview,
            ),
            hide_index=True,
            width="stretch",
        )

    with result_tabs[2]:
        detail_rows = [
            {
                "Metric": "Engine",
                "Value": metadata.engine_version,
            },
            {
                "Metric": "Game ID",
                "Value": metadata.game_id,
            },
            {
                "Metric": "Seed",
                "Value": metadata.seed,
            },
            {
                "Metric": "Overtimes",
                "Value": metadata.overtime_periods,
            },
            {
                "Metric": "Players sat",
                "Value": (
                    len(preview_request["sit_ids"])
                ),
            },
            {
                "Metric": "Trade universe revision",
                "Value": (
                    preview_request[
                        "source_revision"
                    ]
                ),
            },
        ]
        st.dataframe(
            pd.DataFrame(detail_rows),
            hide_index=True,
            width="stretch",
        )
        st.caption(
            "A preview does not alter standings or season "
            "statistics. Commit Result repeats the exact seeded "
            "simulation against the live season state."
        )

    st.markdown(
        '<div class="gs-section">03 · Commit the result</div>',
        unsafe_allow_html=True,
    )

    request_current = preview_request_matches(
        preview_request,
        home_team=home_team,
        away_team=away_team,
        locked_seed=locked_seed,
        lock_seed=lock_seed,
        sit_ids=sit_ids,
        source_revision=(
            trade_state.state_revision
        ),
    )

    with st.container(border=True):
        commit_columns = st.columns([4, 1.4])

        with commit_columns[0]:
            st.markdown(
                '<div class="gs-card-title">'
                'Add this game to the season'
                '</div>',
                unsafe_allow_html=True,
            )
            st.markdown(
                '<div class="gs-card-copy">'
                'The exact previewed result will update the '
                'schedule, standings, team scoring totals, and '
                'every participating player’s season statistics.'
                '</div>',
                unsafe_allow_html=True,
            )

            if not request_current:
                st.markdown(
                    '<div class="gs-warning">'
                    'The matchup controls changed after this '
                    'preview. Simulate again before committing.'
                    '</div>',
                    unsafe_allow_html=True,
                )

        with commit_columns[1]:
            commit_clicked = st.button(
                "Commit result",
                type="primary",
                width="stretch",
                disabled=not request_current,
                key=(
                    "game_simulator_commit_"
                    f"{preview_request['game_id']}"
                ),
            )

        if commit_clicked:
            game_id = preview_request["game_id"]

            try:
                add_scheduled_games(
                    simulation_state,
                    [
                        ScheduledGame(
                            game_id=game_id,
                            day_index=(
                                preview_request[
                                    "day_index"
                                ]
                            ),
                            home_team=(
                                preview_request[
                                    "home_team"
                                ]
                            ),
                            away_team=(
                                preview_request[
                                    "away_team"
                                ]
                            ),
                        )
                    ],
                )
                committed = simulate_scheduled_game(
                    simulation_state,
                    game_id,
                    seed=preview_request["seed"],
                    commit=True,
                    sit_player_ids=(
                        preview_request[
                            "sit_ids"
                        ]
                    ),
                )

                if (
                    committed.game
                    != preview.game
                ):
                    raise (
                        SingleGameSimulationError(
                            "The committed game did not match "
                            "the previewed seeded result."
                        )
                    )

                validate_simulation_league_state(
                    simulation_state
                )
            except (
                SingleGameSimulationError,
                SimulationLeagueStateError,
                ValueError,
                KeyError,
            ) as exc:
                st.error(
                    "The result could not be committed. "
                    f"Detail: {exc}"
                )
            else:
                st.session_state[
                    "game_simulator_league_state"
                ] = simulation_state
                clear_game_preview()
                st.session_state[
                    "game_simulator_notice"
                ] = (
                    f"Committed {game_id}: "
                    f"{committed.game.away_team} "
                    f"{committed.game.away_score}, "
                    f"{committed.game.home_team} "
                    f"{committed.game.home_score}."
                )
                st.rerun()

st.markdown(
    '<div class="gs-section">Season snapshot</div>',
    unsafe_allow_html=True,
)

season_metrics = st.columns(5)
season_metrics[0].metric(
    "Completed games",
    len(simulation_state.completed_games),
)
season_metrics[1].metric(
    "Total schedule entries",
    len(simulation_state.schedule),
)
season_metrics[2].metric(
    "Current day",
    simulation_state.current_day_index,
)
season_metrics[3].metric(
    "Rostered players",
    sum(
        len(team.roster_player_ids)
        for team in simulation_state.teams.values()
    ),
)
season_metrics[4].metric(
    "Free agents",
    len(
        simulation_state.free_agent_player_ids
    ),
)

st.dataframe(
    standings_dataframe(simulation_state),
    hide_index=True,
    width="stretch",
    column_config={
        "Win%": st.column_config.NumberColumn(
            format="%.3f",
        ),
    },
)

if simulation_state.completed_games:
    with st.expander(
        "Completed game history",
        expanded=False,
    ):
        game_rows = []

        for game_id, game in sorted(
            simulation_state.completed_games.items()
        ):
            winner = (
                game.home_team
                if game.home_score > game.away_score
                else game.away_team
            )
            game_rows.append(
                {
                    "Game ID": game_id,
                    "Away": game.away_team,
                    "Away Score": game.away_score,
                    "Home": game.home_team,
                    "Home Score": game.home_score,
                    "Winner": winner,
                    "OT": game.overtime_periods,
                    "Status": GameStatus.COMPLETED.value,
                }
            )

        st.dataframe(
            pd.DataFrame(game_rows),
            hide_index=True,
            width="stretch",
        )
