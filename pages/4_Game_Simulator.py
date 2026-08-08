from __future__ import annotations

import copy
import html
import importlib.util
import secrets
import sys
from datetime import date
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
from simulation_module_bootstrap_v1 import (  # noqa: E402
    BOOTSTRAP_VERSION,
    SimulationModuleBootstrapError,
    ensure_current_simulation_modules,
)


# Streamlit may preload an older simulator module object before this page
# begins. Repair that chain before importing any state-dependent controller.
ensure_current_simulation_modules()
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
from simulation_season_transition_controller_v1 import (  # noqa: E402
    CONTROLLER_VERSION as SEASON_CONTROLLER_VERSION,
    SimulationSeasonTransitionControllerError,
    build_season_transition_preview,
    commit_season_transition_preview,
    incomplete_scheduled_game_ids,
    next_target_season,
    preview_matches_state,
)
from regular_season_schedule_v1 import (  # noqa: E402
    LEAGUE_GAME_COUNT,
    RegularSeasonScheduleError,
    generate_regular_season_schedule,
    install_regular_season_schedule,
)
from regular_season_simulation_controller_v1 import (  # noqa: E402
    RegularSeasonSimulationControllerError,
    SimulationScope,
    regular_season_progress,
    simulate_regular_season_scope,
)
from franchise_calendar_v1 import (  # noqa: E402
    CALENDAR_VERSION,
    FranchiseCalendarError,
    available_calendar_months,
    build_team_month_calendar,
    calendar_html,
    controlled_team_pause,
    date_for_day_index,
    default_calendar_month,
    normalize_controlled_teams,
    team_schedule_games,
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


def clear_season_transition_preview() -> None:
    for key in {
        "game_simulator_season_transition_preview",
        "game_simulator_season_transition_confirmation",
        "game_simulator_season_transition_acknowledged",
    }:
        st.session_state.pop(key, None)


def away_team_changed() -> None:
    clear_game_preview()
    st.session_state.pop(
        "game_simulator_selected_schedule_game_id",
        None,
    )
    st.session_state.pop(
        "game_simulator_away_sit",
        None,
    )


def home_team_changed() -> None:
    clear_game_preview()
    st.session_state.pop(
        "game_simulator_selected_schedule_game_id",
        None,
    )
    st.session_state.pop(
        "game_simulator_home_sit",
        None,
    )


def clear_franchise_game_selection() -> None:
    st.session_state.pop(
        "game_simulator_selected_schedule_game_id",
        None,
    )
    clear_game_preview()


def prepare_scheduled_game(
    state: SimulationLeagueState,
    game_id: str,
) -> None:
    game = state.schedule.get(game_id)

    if (
        game is None
        or game.status != GameStatus.SCHEDULED
    ):
        raise FranchiseCalendarError(
            "Only an upcoming scheduled game can be prepared."
        )

    st.session_state[
        "game_simulator_selected_schedule_game_id"
    ] = game_id
    st.session_state[
        "game_simulator_away_team"
    ] = game.away_team
    st.session_state[
        "game_simulator_home_team"
    ] = game.home_team
    st.session_state.pop(
        "game_simulator_away_sit",
        None,
    )
    st.session_state.pop(
        "game_simulator_home_sit",
        None,
    )
    clear_game_preview()


def schedule_game_label(
    state: SimulationLeagueState,
    game_id: str,
) -> str:
    game = state.schedule[game_id]
    game_date = date_for_day_index(
        state.settings.season_label,
        game.day_index,
    )
    return (
        f"{game_date.strftime('%b %d')} · "
        f"{game.away_team} at {game.home_team}"
    )


def execute_calendar_scope(
    state: SimulationLeagueState,
    *,
    controlled_teams: tuple[str, ...],
    scope: SimulationScope,
) -> tuple[
    SimulationLeagueState,
    str,
    str | None,
]:
    pause = controlled_team_pause(
        state,
        controlled_teams=controlled_teams,
        scope=scope,
    )

    if pause.requires_user_action:
        selected_game_id = (
            pause.pause_game_ids[0]
            if pause.pause_game_ids
            else None
        )

        if pause.can_auto_advance:
            next_state, result = (
                simulate_regular_season_scope(
                    state,
                    scope=SimulationScope.THROUGH_DAY,
                    target_day=pause.auto_target_day,
                )
            )
            message = (
                f"Simulated {result.games_simulated} game(s) "
                f"through day {result.final_current_day}. "
                "Paused before the next controlled-team game."
            )
            return (
                next_state,
                message,
                selected_game_id,
            )

        return (
            state,
            (
                "No games were auto-simulated because the next "
                "unplayed day contains a controlled-team game."
            ),
            selected_game_id,
        )

    next_state, result = (
        simulate_regular_season_scope(
            state,
            scope=scope,
        )
    )
    return (
        next_state,
        (
            f"Simulated {result.games_simulated} game(s) "
            f"through day {result.final_current_day}."
        ),
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
    clear_season_transition_preview()
    clear_franchise_game_selection()
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
.fc-calendar {
  display: grid;
  grid-template-columns: repeat(7, minmax(0, 1fr));
  gap: 7px;
  margin-top: 10px;
}
.fc-weekday {
  padding: 8px 4px;
  color: #667085;
  font-size: .68rem;
  font-weight: 850;
  letter-spacing: .12em;
  text-align: center;
}
.fc-day {
  min-height: 112px;
  border: 1px solid #e4e7ec;
  border-radius: 14px;
  padding: 9px;
  background: #ffffff;
  box-shadow: 0 3px 9px rgba(16,24,40,.04);
}
.fc-day.outside {
  opacity: .32;
  background: #f8fafc;
}
.fc-day.current {
  border: 2px solid #f79009;
  box-shadow: 0 0 0 3px rgba(247,144,9,.14);
}
.fc-day.home {
  background:
    linear-gradient(145deg, rgba(239,248,255,.98), #ffffff);
  border-color: #84caff;
}
.fc-day.away {
  background:
    linear-gradient(145deg, rgba(255,244,237,.98), #ffffff);
  border-color: #f7b27a;
}
.fc-date {
  color: #344054;
  font-size: .72rem;
  font-weight: 850;
}
.fc-rest {
  display: flex;
  min-height: 70px;
  align-items: center;
  justify-content: center;
  color: #98a2b3;
  font-size: .64rem;
  font-weight: 750;
  letter-spacing: .08em;
}
.fc-game {
  display: flex;
  min-height: 70px;
  flex-direction: column;
  justify-content: center;
}
.fc-opponent {
  color: #101828;
  font-size: .98rem;
  font-weight: 900;
}
.fc-result {
  margin-top: 8px;
  color: #027a48;
  font-size: .76rem;
  font-weight: 850;
}
.fc-upcoming {
  margin-top: 8px;
  color: #175cd3;
  font-size: .65rem;
  font-weight: 850;
  letter-spacing: .08em;
}
.fc-legend {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  margin: 8px 0 2px;
  color: #667085;
  font-size: .74rem;
  font-weight: 700;
}
.fc-legend span {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.fc-swatch {
  width: 11px;
  height: 11px;
  border-radius: 3px;
}
.fc-swatch.home {
  background: #b2ddff;
}
.fc-swatch.away {
  background: #f7b27a;
}
.fc-swatch.current {
  border: 2px solid #f79009;
  background: #fffaeb;
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
    Control one or more teams, manage a full season calendar,
    prepare lineups for upcoming games, simulate the league safely,
    and carry permanent results into future seasons.
  </div>
</div>
<div class="gs-source">
  <span class="gs-dot"></span>
  Season {escaped(simulation_state.settings.season_label)}
  · {escaped(simulation_state.phase.value.replace("_", " ").title())}
  · Trade universe revision {trade_state.state_revision}
  · Bootstrap {escaped(BOOTSTRAP_VERSION)}
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


def development_change_dataframe(
    rows: list[dict[str, Any]]
    | tuple[dict[str, Any], ...],
) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Player": row["player_name"],
                "Age": (
                    f"{float(row['source_age']):.0f}"
                    f" → {float(row['target_age']):.0f}"
                ),
                "Previous OVR": round(
                    float(
                        row[
                            "current_overall_rating"
                        ]
                    ),
                    2,
                ),
                "New OVR": round(
                    float(
                        row[
                            "projected_overall_rating"
                        ]
                    ),
                    2,
                ),
                "Change": round(
                    float(row["overall_delta"]),
                    2,
                ),
                "Performance Signal": round(
                    float(
                        row.get(
                            "performance_signal",
                            0.0,
                        )
                    ),
                    3,
                ),
            }
            for row in rows
        ]
    )


def archived_standings_dataframe(
    archive: Any,
) -> pd.DataFrame:
    rows = []

    for team, standing in archive.standings.items():
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


def archived_player_leaders_dataframe(
    state: SimulationLeagueState,
    archive: Any,
) -> pd.DataFrame:
    rows = []

    for player_id, totals in (
        archive.player_season_totals.items()
    ):
        if totals.games_played <= 0:
            continue

        player = state.players.get(player_id)
        rows.append(
            {
                "Player": (
                    player.player_name
                    if player is not None
                    else player_id
                ),
                "GP": totals.games_played,
                "MIN": round(totals.minutes, 1),
                "PTS": totals.points,
                "REB": totals.rebounds,
                "AST": totals.assists,
                "STL": totals.steals,
                "BLK": totals.blocks,
            }
        )

    if not rows:
        return pd.DataFrame(
            columns=[
                "Player",
                "GP",
                "MIN",
                "PTS",
                "REB",
                "AST",
                "STL",
                "BLK",
            ]
        )

    return (
        pd.DataFrame(rows)
        .sort_values(
            ["PTS", "AST", "REB", "Player"],
            ascending=[False, False, False, True],
        )
        .head(25)
        .reset_index(drop=True)
    )


def archived_season_summary_dataframe(
    state: SimulationLeagueState,
) -> pd.DataFrame:
    rows = []

    for archive in reversed(
        state.season_history
    ):
        standings = archived_standings_dataframe(
            archive
        )
        leader = (
            standings.iloc[0]
            if (
                not standings.empty
                and len(archive.completed_games) > 0
            )
            else None
        )
        development = (
            archive.development_summary
            if isinstance(
                archive.development_summary,
                dict,
            )
            else {}
        )
        rows.append(
            {
                "Season": archive.season_label,
                "Completed Games": len(
                    archive.completed_games
                ),
                "Top Team": (
                    str(leader["Team"])
                    if leader is not None
                    else ""
                ),
                "Top Record": (
                    f"{int(leader['W'])}-"
                    f"{int(leader['L'])}"
                    if leader is not None
                    else ""
                ),
                "Players Developed": (
                    development.get(
                        "players_projected",
                        0,
                    )
                ),
                "Average OVR Change": (
                    development.get(
                        "average_overall_delta",
                        0.0,
                    )
                ),
                "Transitioned To": (
                    development.get(
                        "target_season",
                        "",
                    )
                ),
            }
        )

    return pd.DataFrame(rows)


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
    '<div class="gs-section">00 · Franchise calendar</div>',
    unsafe_allow_html=True,
)

teams = sorted(simulation_state.teams)
controlled_key = (
    "game_simulator_controlled_teams"
)
if controlled_key not in st.session_state:
    st.session_state[controlled_key] = (
        ["CHI"]
        if "CHI" in teams
        else [teams[0]]
    )

franchise_control_columns = st.columns(
    [2.4, 1.5, 1.1]
)

with franchise_control_columns[0]:
    controlled_team_values = st.multiselect(
        "User-controlled teams",
        options=teams,
        format_func=team_label,
        key=controlled_key,
        help=(
            "Batch simulation pauses before games involving "
            "any controlled team so you can manage rotations "
            "and availability."
        ),
    )

try:
    controlled_teams = (
        normalize_controlled_teams(
            controlled_team_values,
            available_teams=teams,
        )
    )
except FranchiseCalendarError as exc:
    st.error(str(exc))
    controlled_teams = ()

viewed_key = (
    "game_simulator_viewed_team"
)
preferred_viewed_team = (
    controlled_teams[0]
    if controlled_teams
    else teams[0]
)
if (
    viewed_key not in st.session_state
    or st.session_state[viewed_key]
    not in teams
):
    st.session_state[
        viewed_key
    ] = preferred_viewed_team

with franchise_control_columns[1]:
    viewed_team = st.selectbox(
        "Calendar team",
        options=teams,
        format_func=team_label,
        key=viewed_key,
    )

with franchise_control_columns[2]:
    st.metric(
        "Controlled",
        len(controlled_teams),
    )

full_schedule_active = (
    len(simulation_state.schedule)
    == LEAGUE_GAME_COUNT
)
partial_schedule_active = bool(
    simulation_state.schedule
) and not full_schedule_active

if not simulation_state.schedule:
    with st.container(border=True):
        schedule_columns = st.columns(
            [3.7, 1.3]
        )

        with schedule_columns[0]:
            st.markdown(
                '<div class="gs-card-title">'
                'Create the generated 2026–27 season'
                '</div>',
                unsafe_allow_html=True,
            )
            st.markdown(
                '<div class="gs-card-copy">'
                'This installs the validated realistic filler '
                'schedule: 1,230 games, 82 per team, 41 home '
                'and 41 away. It is not the official NBA '
                'schedule and can later be replaced by an '
                'official-schedule import layer.'
                '</div>',
                unsafe_allow_html=True,
            )

        with schedule_columns[1]:
            install_schedule_clicked = (
                st.button(
                    "Generate schedule",
                    type="primary",
                    width="stretch",
                    key=(
                        "game_simulator_install_"
                        "regular_schedule"
                    ),
                )
            )

    if install_schedule_clicked:
        try:
            scheduled_state = copy.deepcopy(
                simulation_state
            )
            generated_schedule = (
                generate_regular_season_schedule(
                    scheduled_state,
                    seed=(
                        scheduled_state.settings
                        .random_seed
                    ),
                )
            )
            install_regular_season_schedule(
                scheduled_state,
                generated_schedule,
            )
            validate_simulation_league_state(
                scheduled_state
            )
        except (
            RegularSeasonScheduleError,
            SimulationLeagueStateError,
            ValueError,
            KeyError,
        ) as exc:
            st.error(
                "The 82-game schedule could not be "
                f"installed. Detail: {exc}"
            )
        else:
            st.session_state[
                "game_simulator_league_state"
            ] = scheduled_state
            clear_game_preview()
            clear_season_transition_preview()
            clear_franchise_game_selection()
            st.session_state[
                "game_simulator_notice"
            ] = (
                "Generated and installed the realistic "
                "1,230-game simulation schedule."
            )
            st.rerun()

elif partial_schedule_active:
    st.markdown(
        '<div class="gs-warning">'
        'The current season contains a partial custom schedule. '
        'Reset the season before installing the complete '
        '82-game franchise calendar.'
        '</div>',
        unsafe_allow_html=True,
    )

else:
    progress = regular_season_progress(
        simulation_state
    )
    calendar_month_options = (
        available_calendar_months(
            simulation_state
        )
    )
    default_month_value = (
        default_calendar_month(
            simulation_state,
            viewed_team,
        )
    )
    calendar_month_key = (
        "game_simulator_calendar_month"
    )

    if (
        calendar_month_key
        not in st.session_state
        or st.session_state[
            calendar_month_key
        ] not in calendar_month_options
    ):
        st.session_state[
            calendar_month_key
        ] = default_month_value

    calendar_header_columns = st.columns(
        [1.7, 1, 1, 1, 1]
    )

    with calendar_header_columns[0]:
        selected_month = st.selectbox(
            "Calendar month",
            options=calendar_month_options,
            format_func=lambda value: date(
                value[0],
                value[1],
                1,
            ).strftime("%B %Y"),
            key=calendar_month_key,
        )

    calendar_model = (
        build_team_month_calendar(
            simulation_state,
            viewed_team,
            year=selected_month[0],
            month=selected_month[1],
            controlled_teams=(
                controlled_teams
            ),
        )
    )

    calendar_header_columns[1].metric(
        "Season progress",
        (
            f"{progress['completion_percentage']:.1f}%"
        ),
    )
    calendar_header_columns[2].metric(
        "Month games",
        calendar_model.scheduled_games,
    )
    calendar_header_columns[3].metric(
        "Home",
        calendar_model.home_games,
    )
    calendar_header_columns[4].metric(
        "Away",
        calendar_model.away_games,
    )

    st.markdown(
        '<div class="fc-legend">'
        '<span><i class="fc-swatch home"></i>Home</span>'
        '<span><i class="fc-swatch away"></i>Away</span>'
        '<span><i class="fc-swatch current"></i>Current day</span>'
        '</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        calendar_html(
            calendar_model
        ),
        unsafe_allow_html=True,
    )
    st.caption(
        "Generated simulation schedule. Day 1 is displayed "
        "as October 20 of the season start year. The calendar "
        "is a realistic filler until an official schedule "
        "import is available."
    )

    viewed_upcoming_games = [
        game
        for game in team_schedule_games(
            simulation_state,
            viewed_team,
        )
        if (
            game.status
            == GameStatus.SCHEDULED
            and date_for_day_index(
                simulation_state.settings
                .season_label,
                game.day_index,
            ).year
            == selected_month[0]
            and date_for_day_index(
                simulation_state.settings
                .season_label,
                game.day_index,
            ).month
            == selected_month[1]
        )
    ]

    if not viewed_upcoming_games:
        viewed_upcoming_games = [
            game
            for game in team_schedule_games(
                simulation_state,
                viewed_team,
            )
            if game.status
            == GameStatus.SCHEDULED
        ][:8]

    upcoming_columns = st.columns(
        [2.6, 1.1]
    )
    selected_calendar_game_id = None

    with upcoming_columns[0]:
        if viewed_upcoming_games:
            selected_calendar_game_id = (
                st.selectbox(
                    "Upcoming matchup to manage",
                    options=[
                        game.game_id
                        for game
                        in viewed_upcoming_games
                    ],
                    format_func=lambda game_id: (
                        schedule_game_label(
                            simulation_state,
                            game_id,
                        )
                    ),
                    key=(
                        "game_simulator_calendar_"
                        "upcoming_game"
                    ),
                )
            )
        else:
            st.info(
                "This team has no remaining regular-season "
                "games."
            )

    with upcoming_columns[1]:
        prepare_game_clicked = st.button(
            "Prepare matchup",
            width="stretch",
            disabled=(
                selected_calendar_game_id
                is None
            ),
            key=(
                "game_simulator_prepare_"
                "calendar_game"
            ),
        )

    if (
        prepare_game_clicked
        and selected_calendar_game_id
        is not None
    ):
        try:
            prepare_scheduled_game(
                simulation_state,
                selected_calendar_game_id,
            )
        except FranchiseCalendarError as exc:
            st.error(str(exc))
        else:
            st.session_state[
                "game_simulator_notice"
            ] = (
                "Loaded the scheduled matchup into "
                "the lineup-management controls."
            )
            st.rerun()

    st.markdown(
        '<div class="gs-section">'
        'Calendar simulation controls'
        '</div>',
        unsafe_allow_html=True,
    )
    simulation_columns = st.columns(
        [1, 1, 1.25, 2.6]
    )
    next_day_clicked = simulation_columns[
        0
    ].button(
        "Sim next day",
        width="stretch",
        disabled=progress[
            "regular_season_complete"
        ],
        key="game_simulator_sim_next_day",
    )
    next_week_clicked = simulation_columns[
        1
    ].button(
        "Sim next week",
        width="stretch",
        disabled=progress[
            "regular_season_complete"
        ],
        key="game_simulator_sim_next_week",
    )
    remainder_clicked = simulation_columns[
        2
    ].button(
        "Sim to season end",
        width="stretch",
        disabled=progress[
            "regular_season_complete"
        ],
        key=(
            "game_simulator_sim_"
            "season_remainder"
        ),
    )
    simulation_columns[3].caption(
        "Computer-only games simulate automatically. "
        "Any requested range stops before the first day "
        "containing a controlled-team game."
    )

    requested_scope = (
        SimulationScope.NEXT_DAY
        if next_day_clicked
        else SimulationScope.NEXT_WEEK
        if next_week_clicked
        else SimulationScope.REMAINDER
        if remainder_clicked
        else None
    )

    if requested_scope is not None:
        try:
            with st.spinner(
                "Simulating eligible games..."
            ):
                (
                    advanced_state,
                    advance_message,
                    pause_game_id,
                ) = execute_calendar_scope(
                    simulation_state,
                    controlled_teams=(
                        controlled_teams
                    ),
                    scope=requested_scope,
                )
                validate_simulation_league_state(
                    advanced_state
                )
        except (
            RegularSeasonSimulationControllerError,
            FranchiseCalendarError,
            SimulationLeagueStateError,
            ValueError,
            KeyError,
        ) as exc:
            st.error(
                "The calendar simulation could not "
                f"advance. Detail: {exc}"
            )
        else:
            st.session_state[
                "game_simulator_league_state"
            ] = advanced_state

            if pause_game_id is not None:
                prepare_scheduled_game(
                    advanced_state,
                    pause_game_id,
                )

            clear_season_transition_preview()
            st.session_state[
                "game_simulator_notice"
            ] = advance_message
            st.rerun()

st.markdown(
    '<div class="gs-section">01 · Build the matchup</div>',
    unsafe_allow_html=True,
)

selected_schedule_game_id = (
    st.session_state.get(
        "game_simulator_selected_schedule_game_id"
    )
)
selected_schedule_game = (
    simulation_state.schedule.get(
        selected_schedule_game_id
    )
    if isinstance(
        selected_schedule_game_id,
        str,
    )
    else None
)
selected_schedule_game_ready = bool(
    selected_schedule_game is not None
    and selected_schedule_game.status
    == GameStatus.SCHEDULED
)
full_schedule_active = (
    len(simulation_state.schedule)
    == LEAGUE_GAME_COUNT
)

if (
    selected_schedule_game_ready
    and (
        st.session_state.get(
            "game_simulator_away_team"
        )
        != selected_schedule_game.away_team
        or st.session_state.get(
            "game_simulator_home_team"
        )
        != selected_schedule_game.home_team
    )
):
    clear_franchise_game_selection()
    selected_schedule_game = None
    selected_schedule_game_ready = False

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

if full_schedule_active:
    if selected_schedule_game_ready:
        selected_date = date_for_day_index(
            simulation_state.settings.season_label,
            selected_schedule_game.day_index,
        )
        st.info(
            "Managing scheduled game "
            f"{selected_schedule_game.game_id} on "
            f"{selected_date.strftime('%B %d, %Y')}: "
            f"{selected_schedule_game.away_team} at "
            f"{selected_schedule_game.home_team}."
        )
    else:
        st.markdown(
            '<div class="gs-warning">'
            'The full franchise schedule is active. Select an '
            'upcoming game from the calendar before simulating '
            'or committing a season result.'
            '</div>',
            unsafe_allow_html=True,
        )

action_columns = st.columns([1.5, 1.5, 5])

with action_columns[0]:
    preview_clicked = st.button(
        (
            "Simulate scheduled game"
            if selected_schedule_game_ready
            else "Simulate game"
        ),
        type="primary",
        width="stretch",
        disabled=(
            same_team
            or (
                full_schedule_active
                and not selected_schedule_game_ready
            )
        ),
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
    existing_schedule_game = bool(
        selected_schedule_game_ready
    )
    game_number = (
        len(simulation_state.schedule) + 1
    )
    game_id = (
        selected_schedule_game.game_id
        if selected_schedule_game_ready
        else f"UI-GAME-{game_number:04d}"
    )
    day_index = (
        int(
            selected_schedule_game.day_index
        )
        if selected_schedule_game_ready
        else (
            simulation_state.current_day_index
            + 1
        )
    )
    trial_state = copy.deepcopy(
        simulation_state
    )

    try:
        if not existing_schedule_game:
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
            "existing_schedule_game": (
                existing_schedule_game
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

    request_current = (
        preview_request_matches(
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
        and (
            not preview_request.get(
                "existing_schedule_game",
                False,
            )
            or preview_request.get(
                "game_id"
            )
            == selected_schedule_game_id
        )
    )

    with st.container(border=True):
        commit_columns = st.columns([4, 1.4])

        with commit_columns[0]:
            commit_title = (
                "Commit the scheduled game"
                if preview_request.get(
                    "existing_schedule_game",
                    False,
                )
                else "Add this game to the season"
            )
            st.markdown(
                (
                    '<div class="gs-card-title">'
                    f"{escaped(commit_title)}"
                    "</div>"
                ),
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
                if not preview_request.get(
                    "existing_schedule_game",
                    False,
                ):
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
                clear_season_transition_preview()
                clear_franchise_game_selection()
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

season_metrics = st.columns(7)
season_metrics[0].metric(
    "Season",
    simulation_state.settings.season_label,
)
season_metrics[1].metric(
    "Phase",
    simulation_state.phase.value
    .replace("_", " ")
    .title(),
)
season_metrics[2].metric(
    "Completed games",
    len(simulation_state.completed_games),
)
season_metrics[3].metric(
    "Total schedule entries",
    len(simulation_state.schedule),
)
season_metrics[4].metric(
    "Current day",
    simulation_state.current_day_index,
)
season_metrics[5].metric(
    "Archived seasons",
    len(simulation_state.season_history),
)
season_metrics[6].metric(
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

st.markdown(
    '<div class="gs-section">04 · Season management</div>',
    unsafe_allow_html=True,
)

incomplete_games = incomplete_scheduled_game_ids(
    simulation_state
)
target_season = next_target_season(
    simulation_state
)

with st.container(border=True):
    management_columns = st.columns([3.8, 1.3])

    with management_columns[0]:
        st.markdown(
            '<div class="gs-card-title">'
            f'Advance to {escaped(target_season)}'
            '</div>',
            unsafe_allow_html=True,
        )
        st.markdown(
            '<div class="gs-card-copy">'
            'Preview deterministic player progression and '
            'regression before changing the permanent league. '
            'The completed season will be archived, every '
            'player will age one year, rotations will be '
            're-ranked, and the new season will begin in '
            'preseason.'
            '</div>',
            unsafe_allow_html=True,
        )

        if incomplete_games:
            st.markdown(
                '<div class="gs-warning">'
                'Every scheduled game must be completed first. '
                f'{len(incomplete_games)} incomplete game(s): '
                f'{escaped(", ".join(incomplete_games[:6]))}'
                '</div>',
                unsafe_allow_html=True,
            )
        elif not simulation_state.completed_games:
            st.markdown(
                '<div class="gs-warning">'
                'This season has no committed games. Advancing '
                'is still allowed, but development will rely on '
                'age, potential, reliability, and deterministic '
                'variance rather than simulated performance.'
                '</div>',
                unsafe_allow_html=True,
            )

    with management_columns[1]:
        build_transition_clicked = st.button(
            "Preview transition",
            width="stretch",
            disabled=bool(incomplete_games),
            key=(
                "game_simulator_build_transition_"
                f"{simulation_state.settings.season_label}_"
                f"{simulation_state.transition_count}"
            ),
        )

if build_transition_clicked:
    try:
        transition_preview = (
            build_season_transition_preview(
                simulation_state
            )
        )
    except (
        SimulationSeasonTransitionControllerError,
        SimulationLeagueStateError,
        ValueError,
        KeyError,
    ) as exc:
        st.error(
            "The season transition could not be previewed. "
            f"Detail: {exc}"
        )
    else:
        st.session_state[
            "game_simulator_season_transition_preview"
        ] = transition_preview
        st.rerun()

transition_preview = st.session_state.get(
    "game_simulator_season_transition_preview"
)

if isinstance(transition_preview, dict):
    transition_is_current = (
        preview_matches_state(
            simulation_state,
            transition_preview,
        )
    )
    transition_result = transition_preview.get(
        "result",
        {},
    )

    st.markdown(
        '<div class="gs-section">'
        'Transition preview'
        '</div>',
        unsafe_allow_html=True,
    )

    preview_metrics = st.columns(6)
    preview_metrics[0].metric(
        "Players projected",
        transition_result.get(
            "players_projected",
            0,
        ),
    )
    preview_metrics[1].metric(
        "Average OVR change",
        f"{float(transition_result.get('average_overall_delta', 0.0)):+.3f}",
    )
    preview_metrics[2].metric(
        "Improved",
        transition_result.get(
            "improved_players",
            0,
        ),
    )
    preview_metrics[3].metric(
        "Stable",
        transition_result.get(
            "stable_players",
            0,
        ),
    )
    preview_metrics[4].metric(
        "Declined",
        transition_result.get(
            "declined_players",
            0,
        ),
    )
    preview_metrics[5].metric(
        "Performance signals",
        transition_result.get(
            "performance_signals_used",
            0,
        ),
    )

    transition_tabs = st.tabs(
        [
            "Biggest Risers",
            "Biggest Fallers",
            "Transition Detail",
        ]
    )

    with transition_tabs[0]:
        st.dataframe(
            development_change_dataframe(
                transition_result.get(
                    "biggest_risers",
                    [],
                )
            ),
            hide_index=True,
            width="stretch",
            column_config={
                "Change": st.column_config.NumberColumn(
                    format="%+.2f",
                ),
                "Performance Signal": (
                    st.column_config.NumberColumn(
                        format="%+.3f",
                    )
                ),
            },
        )

    with transition_tabs[1]:
        st.dataframe(
            development_change_dataframe(
                transition_result.get(
                    "biggest_fallers",
                    [],
                )
            ),
            hide_index=True,
            width="stretch",
            column_config={
                "Change": st.column_config.NumberColumn(
                    format="%+.2f",
                ),
                "Performance Signal": (
                    st.column_config.NumberColumn(
                        format="%+.3f",
                    )
                ),
            },
        )

    with transition_tabs[2]:
        detail_rows = [
            {
                "Metric": "Controller",
                "Value": SEASON_CONTROLLER_VERSION,
            },
            {
                "Metric": "Transition engine",
                "Value": transition_result.get(
                    "transition_version",
                    "",
                ),
            },
            {
                "Metric": "Development engine",
                "Value": transition_result.get(
                    "development_engine_version",
                    "",
                ),
            },
            {
                "Metric": "Source season",
                "Value": transition_preview.get(
                    "source_season",
                    "",
                ),
            },
            {
                "Metric": "Target season",
                "Value": transition_preview.get(
                    "target_season",
                    "",
                ),
            },
            {
                "Metric": "Synthetic players skipped",
                "Value": transition_result.get(
                    "synthetic_players_skipped",
                    0,
                ),
            },
        ]
        st.dataframe(
            pd.DataFrame(detail_rows),
            hide_index=True,
            width="stretch",
        )

    if not transition_is_current:
        st.markdown(
            '<div class="gs-warning">'
            'The live season changed after this preview. '
            'Build a new transition preview before advancing.'
            '</div>',
            unsafe_allow_html=True,
        )

    confirmation_key = (
        "game_simulator_season_transition_confirmation"
    )
    acknowledgement_key = (
        "game_simulator_season_transition_acknowledged"
    )
    confirmation_columns = st.columns([2.2, 2.2, 1.4])

    with confirmation_columns[0]:
        transition_acknowledged = st.checkbox(
            (
                "I understand this archives the current "
                "season and permanently updates player ratings."
            ),
            key=acknowledgement_key,
        )

    with confirmation_columns[1]:
        transition_confirmation = st.text_input(
            (
                "Type "
                f"{transition_preview.get('target_season', '')} "
                "to confirm"
            ),
            key=confirmation_key,
        )

    confirmation_matches = (
        transition_confirmation.strip()
        == str(
            transition_preview.get(
                "target_season",
                "",
            )
        )
    )

    with confirmation_columns[2]:
        advance_transition_clicked = st.button(
            (
                "Advance to "
                f"{transition_preview.get('target_season', '')}"
            ),
            type="primary",
            width="stretch",
            disabled=not (
                transition_is_current
                and transition_acknowledged
                and confirmation_matches
            ),
            key=(
                "game_simulator_commit_transition_"
                f"{transition_preview.get('source_season', '')}_"
                f"{transition_preview.get('target_season', '')}_"
                f"{simulation_state.transition_count}"
            ),
        )

    if advance_transition_clicked:
        try:
            (
                transitioned_state,
                committed_transition,
            ) = commit_season_transition_preview(
                simulation_state,
                transition_preview,
            )
            validate_simulation_league_state(
                transitioned_state
            )
        except (
            SimulationSeasonTransitionControllerError,
            SimulationLeagueStateError,
            ValueError,
            KeyError,
        ) as exc:
            st.error(
                "The season transition could not be committed. "
                f"Detail: {exc}"
            )
        else:
            st.session_state[
                "game_simulator_league_state"
            ] = transitioned_state
            clear_game_preview()
            clear_season_transition_preview()
            st.session_state[
                "game_simulator_notice"
            ] = (
                f"Advanced from "
                f"{committed_transition.source_season} "
                f"to {committed_transition.target_season}. "
                f"Projected "
                f"{committed_transition.players_projected} "
                "players and archived the completed season."
            )
            st.rerun()

if simulation_state.season_history:
    st.markdown(
        '<div class="gs-section">'
        'Archived season history'
        '</div>',
        unsafe_allow_html=True,
    )
    st.dataframe(
        archived_season_summary_dataframe(
            simulation_state
        ),
        hide_index=True,
        width="stretch",
        column_config={
            "Average OVR Change": (
                st.column_config.NumberColumn(
                    format="%+.3f",
                )
            ),
        },
    )

    for archive in reversed(
        simulation_state.season_history
    ):
        with st.expander(
            f"{archive.season_label} archive",
            expanded=False,
        ):
            archive_tabs = st.tabs(
                [
                    "Standings",
                    "Player Leaders",
                    "Development",
                ]
            )

            with archive_tabs[0]:
                st.dataframe(
                    archived_standings_dataframe(
                        archive
                    ),
                    hide_index=True,
                    width="stretch",
                    column_config={
                        "Win%": (
                            st.column_config.NumberColumn(
                                format="%.3f",
                            )
                        ),
                    },
                )

            with archive_tabs[1]:
                st.dataframe(
                    archived_player_leaders_dataframe(
                        simulation_state,
                        archive,
                    ),
                    hide_index=True,
                    width="stretch",
                )

            with archive_tabs[2]:
                development = (
                    archive.development_summary
                    if isinstance(
                        archive.development_summary,
                        dict,
                    )
                    else {}
                )
                archive_metrics = st.columns(4)
                archive_metrics[0].metric(
                    "Transitioned to",
                    development.get(
                        "target_season",
                        "",
                    ),
                )
                archive_metrics[1].metric(
                    "Improved",
                    development.get(
                        "improved_players",
                        0,
                    ),
                )
                archive_metrics[2].metric(
                    "Stable",
                    development.get(
                        "stable_players",
                        0,
                    ),
                )
                archive_metrics[3].metric(
                    "Declined",
                    development.get(
                        "declined_players",
                        0,
                    ),
                )

                development_tabs = st.tabs(
                    [
                        "Risers",
                        "Fallers",
                    ]
                )
                with development_tabs[0]:
                    st.dataframe(
                        development_change_dataframe(
                            development.get(
                                "biggest_risers",
                                [],
                            )
                        ),
                        hide_index=True,
                        width="stretch",
                    )
                with development_tabs[1]:
                    st.dataframe(
                        development_change_dataframe(
                            development.get(
                                "biggest_fallers",
                                [],
                            )
                        ),
                        hide_index=True,
                        width="stretch",
                    )