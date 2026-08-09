from __future__ import annotations

import copy
import html
import importlib
import statistics
import sys
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

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
    create_league_state,
)
from simulation_module_bootstrap_v1 import (  # noqa: E402
    BOOTSTRAP_VERSION,
    ensure_current_simulation_modules,
)


# Repair the state-dependent chain first, then explicitly reload the local
# cross-page helper. Streamlit can otherwise retain its previous module
# object after an in-place source update.
ensure_current_simulation_modules()
import simulation_cross_page_state_v1 as _cross_page_state  # noqa: E402

_cross_page_state = importlib.reload(
    _cross_page_state
)

from simulation_cross_page_state_v1 import (  # noqa: E402
    CROSS_PAGE_STATE_VERSION,
    initialize_persistent_widget,
    persist_widget_value,
    simulation_matches_trade_state,
    simulation_source_status,
    simulation_state_is_compatible,
    trade_state_is_compatible,
)
# Streamlit preserves imported dependency modules across page reruns. Reload
# the checkpoint module explicitly so an in-place writer upgrade is visible
# without restarting the process or discarding the live franchise session.
import simulation_franchise_checkpoint_v1 as _franchise_checkpoint  # noqa: E402

_franchise_checkpoint = importlib.reload(
    _franchise_checkpoint
)
CHECKPOINT_IMPLEMENTATION_VERSION = (
    _franchise_checkpoint.CHECKPOINT_IMPLEMENTATION_VERSION
)
CHECKPOINT_VERSION = (
    _franchise_checkpoint.CHECKPOINT_VERSION
)
DEFAULT_CHECKPOINT_PATH = (
    _franchise_checkpoint.DEFAULT_CHECKPOINT_PATH
)
FranchiseCheckpointError = (
    _franchise_checkpoint.FranchiseCheckpointError
)
load_franchise_checkpoint = (
    _franchise_checkpoint.load_franchise_checkpoint
)
save_franchise_checkpoint = (
    _franchise_checkpoint.save_franchise_checkpoint
)


import simulation_roster_validator_v1 as roster_validator  # noqa: E402
from simulation_league_alignment_v1 import (  # noqa: E402
    ALIGNMENT_VERSION,
    apply_nba_team_alignment,
    conference_for_team,
)
from simulation_trade_sync_v1 import (  # noqa: E402
    TRADE_SYNC_VERSION,
    SimulationTradeSyncError,
    build_trade_sync_preview,
    synchronize_simulation_with_trade_state,
)
from simulation_postseason_v1 import (  # noqa: E402
    POSTSEASON_VERSION,
    PostseasonSimulationScope,
    PostseasonStage,
    SimulationPostseasonError,
    advance_postseason,
    commit_postseason_game,
    completed_postseason_games,
    controlled_postseason_games,
    get_postseason_state,
    initialize_postseason,
    next_postseason_game,
    postseason_team_status,
    postseason_player_rows,
    postseason_seed_rows,
    postseason_series_rows,
    regular_season_is_complete,
    simulate_postseason_game,
)
from franchise_calendar_v1 import (  # noqa: E402
    available_calendar_months,
    build_team_month_calendar,
    date_for_day_index,
    default_calendar_month,
    normalize_controlled_teams,
    team_schedule_games,
)
from franchise_command_center_v1 import (  # noqa: E402
    COMMAND_CENTER_VERSION,
    POLICY_LABELS,
    FranchiseAdvanceResult,
    FranchiseCommandCenterError,
    FranchiseSimulationPolicy,
    advance_franchise_scope,
    apply_rotation_plan,
    build_team_snapshot,
    calendar_with_logos_html,
    player_leader_rows,
    rotation_management_rows,
    rotation_plan_from_rows,
    standings_rows,
    team_colors,
    team_logo_url,
    team_name,
    team_needs_rows,
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
    regular_season_state_fingerprint,
)
from simulation_league_state_v1 import (  # noqa: E402
    MINUTES_MODEL_VERSION,
    SIMULATION_STATE_VERSION,
    GameStatus,
    SimulationLeagueState,
    SimulationLeagueStateError,
    create_simulation_league_state,
    validate_simulation_league_state,
)
from single_game_simulator_v1 import (  # noqa: E402
    ENGINE_VERSION,
    SingleGameSimulationError,
    simulate_scheduled_game,
)
from state_runtime_adapter_v1 import (  # noqa: E402
    build_state_runtime,
)


EXPECTED_REALISM_ENGINE_VERSION = (
    "single-game-simulator-v1.6-2026-08-08"
)

if ENGINE_VERSION != EXPECTED_REALISM_ENGINE_VERSION:
    raise ImportError(
        "Franchise Mode loaded an outdated game engine: "
        f"{ENGINE_VERSION}. Expected "
        f"{EXPECTED_REALISM_ENGINE_VERSION}."
    )


def season_stat_contamination(
    state: SimulationLeagueState,
) -> dict[str, float | bool]:
    qualified: list[tuple[float, float]] = []

    for totals in state.player_season_totals.values():
        games = int(totals.games_played)

        if games < 10:
            continue

        qualified.append(
            (
                float(totals.points) / games,
                float(totals.minutes) / games,
            )
        )

    maximum_ppg = max(
        (row[0] for row in qualified),
        default=0.0,
    )
    minute_values = [
        row[1]
        for row in qualified
    ]
    maximum_mpg = max(
        minute_values,
        default=0.0,
    )
    minute_standard_deviation = (
        statistics.pstdev(
            minute_values
        )
        if len(minute_values) >= 2
        else 0.0
    )
    high_minute_values = [
        value
        for value in minute_values
        if value >= 24.0
    ]
    high_minute_standard_deviation = (
        statistics.pstdev(
            high_minute_values
        )
        if len(
            high_minute_values
        )
        >= 2
        else 0.0
    )
    flat_minutes = bool(
        len(high_minute_values) >= 100
        and maximum_mpg < 33.0
        and high_minute_standard_deviation
        < 1.5
    )
    return {
        "contaminated": (
            maximum_ppg > 39.0
            or maximum_mpg > 39.0
            or flat_minutes
        ),
        "maximum_ppg": maximum_ppg,
        "maximum_mpg": maximum_mpg,
        "minute_standard_deviation": (
            minute_standard_deviation
        ),
        "high_minute_standard_deviation": (
            high_minute_standard_deviation
        ),
        "flat_minutes": flat_minutes,
    }


def postseason_matchup_html(
    home_team: str,
    away_team: str,
    *,
    round_label: str,
    game_number: int,
) -> str:
    home_name = html.escape(
        team_name(home_team)
    )
    away_name = html.escape(
        team_name(away_team)
    )
    home_logo = html.escape(
        team_logo_url(home_team)
    )
    away_logo = html.escape(
        team_logo_url(away_team)
    )
    label = html.escape(
        round_label
    )

    return f"""
    <div style="
        border:1px solid #334155;
        border-radius:18px;
        padding:22px;
        margin:8px 0 16px 0;
        background:#111827;
    ">
      <div style="
          text-align:center;
          color:#94a3b8;
          font-size:12px;
          font-weight:800;
          letter-spacing:.12em;
          text-transform:uppercase;
          margin-bottom:16px;
      ">
        {label} · Game {game_number}
      </div>
      <div style="
          display:grid;
          grid-template-columns:1fr 70px 1fr;
          align-items:center;
          gap:18px;
      ">
        <div style="text-align:center;">
          <img src="{away_logo}" style="
              width:82px;
              height:82px;
              object-fit:contain;
          ">
          <div style="
              color:white;
              font-size:20px;
              font-weight:800;
              margin-top:8px;
          ">{away_name}</div>
          <div style="color:#94a3b8;">Away</div>
        </div>
        <div style="
            color:#94a3b8;
            font-weight:900;
            text-align:center;
        ">AT</div>
        <div style="text-align:center;">
          <img src="{home_logo}" style="
              width:82px;
              height:82px;
              object-fit:contain;
          ">
          <div style="
              color:white;
              font-size:20px;
              font-weight:800;
              margin-top:8px;
          ">{home_name}</div>
          <div style="color:#94a3b8;">Home</div>
        </div>
      </div>
    </div>
    """


st.set_page_config(
    page_title="NBA Franchise Mode",
    page_icon="🏆",
    layout="wide",
)


@st.cache_resource(
    show_spinner="Loading franchise engine..."
)
def get_base_runtime() -> RuntimeData:
    return load_runtime_data()


def escaped(value: Any) -> str:
    return html.escape(str(value))


def current_position_signature() -> tuple[
    str,
    str,
    int,
    int,
]:
    path = Path(
        roster_validator.POSITION_DATA_PATH
    )
    stat = path.stat()
    return (
        roster_validator.VALIDATOR_VERSION,
        str(path.resolve()),
        int(stat.st_mtime_ns),
        int(stat.st_size),
    )


FRANCHISE_CHECKPOINT_PREFERENCE_KEYS = (
    "franchise_pref_controlled_teams",
    "franchise_pref_active_team",
    "franchise_pref_simulation_policy",
    "franchise_pref_calendar_month",
    "franchise_pref_draft_class_strength",
)


def franchise_checkpoint_preferences() -> dict[
    str,
    Any,
]:
    return {
        key: copy.deepcopy(
            st.session_state[key]
        )
        for key
        in FRANCHISE_CHECKPOINT_PREFERENCE_KEYS
        if key in st.session_state
    }


def save_current_franchise_checkpoint(
    state: SimulationLeagueState,
    *,
    reason: str,
    trade_state: LeagueState | None = None,
    copy_payload: bool = True,
) -> bool:
    resolved_trade_state = (
        trade_state
        if trade_state is not None
        else st.session_state.get(
            "trade_machine_league_state"
        )
    )

    if resolved_trade_state is None:
        st.session_state[
            "franchise_checkpoint_warning"
        ] = (
            "The durable franchise checkpoint could not "
            "be written because the Trade Machine state "
            "is unavailable."
        )
        return False

    try:
        checkpoint = (
            save_franchise_checkpoint(
                state,
                resolved_trade_state,
                preferences=(
                    franchise_checkpoint_preferences()
                ),
                reason=reason,
                copy_payload=(
                    copy_payload
                ),
            )
        )
    except FranchiseCheckpointError as exc:
        error_text = str(exc)
        st.session_state[
            "franchise_checkpoint_warning"
        ] = error_text
        st.session_state[
            "franchise_checkpoint_last_error"
        ] = {
            "reason": reason,
            "stage": getattr(
                exc,
                "stage",
                "",
            ),
            "cause_type": getattr(
                exc,
                "cause_type",
                "",
            ),
            "cause_message": getattr(
                exc,
                "cause_message",
                "",
            ),
            "message": error_text,
        }
        return False

    st.session_state[
        "franchise_checkpoint_saved_at"
    ] = checkpoint.saved_at_utc
    st.session_state[
        "franchise_checkpoint_last_reason"
    ] = checkpoint.reason
    st.session_state.pop(
        "franchise_checkpoint_warning",
        None,
    )
    st.session_state.pop(
        "franchise_checkpoint_last_error",
        None,
    )
    return True


def restore_franchise_checkpoint() -> bool:
    if (
        "game_simulator_league_state"
        in st.session_state
    ):
        return False

    try:
        checkpoint = (
            load_franchise_checkpoint()
        )
    except FranchiseCheckpointError as exc:
        st.session_state[
            "franchise_checkpoint_warning"
        ] = (
            "The durable franchise checkpoint "
            f"could not be restored: {exc}"
        )
        return False

    if checkpoint is None:
        return False

    simulation_state = (
        checkpoint.simulation_state
    )
    trade_state = checkpoint.trade_state

    if not simulation_state_is_compatible(
        simulation_state,
        expected_state_version=(
            SIMULATION_STATE_VERSION
        ),
    ):
        st.session_state[
            "franchise_checkpoint_warning"
        ] = (
            "A franchise checkpoint was found, "
            "but its simulation-state contract "
            "is no longer compatible."
        )
        return False

    if not trade_state_is_compatible(
        trade_state,
        expected_state_version=(
            STATE_VERSION
        ),
    ):
        st.session_state[
            "franchise_checkpoint_warning"
        ] = (
            "A franchise checkpoint was found, "
            "but its Trade Machine state is no "
            "longer compatible."
        )
        return False

    if any(
        not player.synthetic
        and player.position == "UNK"
        for player
        in simulation_state.players.values()
    ):
        st.session_state[
            "franchise_checkpoint_warning"
        ] = (
            "The durable checkpoint contains "
            "unresolved player positions and "
            "was not restored."
        )
        return False

    apply_nba_team_alignment(
        simulation_state
    )
    st.session_state[
        "game_simulator_league_state"
    ] = simulation_state
    st.session_state[
        "trade_machine_league_state"
    ] = trade_state
    st.session_state[
        "game_simulator_position_signature"
    ] = current_position_signature()

    for key, value in (
        checkpoint.preferences.items()
    ):
        if (
            key
            in FRANCHISE_CHECKPOINT_PREFERENCE_KEYS
            and key
            not in st.session_state
        ):
            st.session_state[key] = (
                copy.deepcopy(value)
            )

    st.session_state[
        "franchise_notice"
    ] = (
        "Restored the durable Franchise Mode "
        f"checkpoint saved at "
        f"{checkpoint.saved_at_utc}."
    )
    st.session_state[
        "franchise_checkpoint_saved_at"
    ] = checkpoint.saved_at_utc
    return True


def advance_postseason_with_progress(
    state: SimulationLeagueState,
    *,
    scope: PostseasonSimulationScope,
    controlled_teams: tuple[str, ...],
    policy: FranchiseSimulationPolicy,
    label: str,
) -> tuple[
    SimulationLeagueState,
    Any,
]:
    max_games = {
        PostseasonSimulationScope
        .NEXT_CONTROLLED_GAME: 12,
        PostseasonSimulationScope
        .CURRENT_STAGE: 20,
        PostseasonSimulationScope
        .TO_CHAMPION: 140,
        PostseasonSimulationScope
        .NEXT_GAME: 1,
    }[scope]

    with st.status(
        label,
        expanded=True,
    ) as progress_status:
        def checkpoint_progress(
            progress_state: SimulationLeagueState,
            count: int,
            game: Any,
        ) -> None:
            st.session_state[
                "game_simulator_league_state"
            ] = progress_state
            progress_status.update(
                label=(
                    f"Simulated {count} CPU "
                    "postseason game(s). "
                    f"Latest: {game.round_label} "
                    f"Game {game.game_number}."
                ),
                state="running",
                expanded=True,
            )

            if count % 3 == 0:
                save_current_franchise_checkpoint(
                    progress_state,
                    reason=(
                        "postseason-progress-"
                        f"{count}"
                    ),
                    copy_payload=False,
                )

        try:
            updated_state, result = (
                advance_postseason(
                    state,
                    scope=scope,
                    controlled_teams=(
                        controlled_teams
                    ),
                    policy=policy,
                    max_games=max_games,
                    progress_callback=(
                        checkpoint_progress
                    ),
                )
            )
        except Exception:
            progress_status.update(
                label=(
                    "Postseason advancement stopped "
                    "because of an error. The most "
                    "recent checkpoint remains available."
                ),
                state="error",
                expanded=True,
            )
            raise

        st.session_state[
            "game_simulator_league_state"
        ] = updated_state
        save_current_franchise_checkpoint(
            updated_state,
            reason=(
                "postseason-advance-complete"
            ),
            copy_payload=False,
        )
        progress_status.update(
            label=(
                f"Postseason advancement finished "
                f"after {result.games_simulated} "
                "game(s)."
            ),
            state="complete",
            expanded=False,
        )

    return updated_state, result


def get_trade_state(
    runtime: RuntimeData,
) -> LeagueState:
    key = "trade_machine_league_state"
    state = st.session_state.get(key)

    if not trade_state_is_compatible(
        state,
        expected_state_version=STATE_VERSION,
    ):
        state = create_league_state(
            runtime
        )
        st.session_state[key] = state

    return state


def apply_latest_positions(
    state: SimulationLeagueState,
    runtime: RuntimeData,
) -> None:
    unresolved: list[str] = []

    for player_id, player in (
        state.players.items()
    ):
        if player.synthetic:
            continue

        position = (
            roster_validator
            .player_position(
                runtime,
                player_id,
            )
        )

        if position == "UNK":
            unresolved.append(
                player.player_name
            )
        else:
            player.position = position

    if unresolved:
        raise SimulationLeagueStateError(
            "Franchise Mode could not resolve "
            f"{len(unresolved)} player positions."
        )


def create_fresh_state(
    runtime: RuntimeData,
    trade_state: LeagueState,
) -> SimulationLeagueState:
    state = create_simulation_league_state(
        runtime,
        trade_state,
    )
    apply_latest_positions(
        state,
        runtime,
    )
    apply_nba_team_alignment(
        state
    )
    st.session_state[
        "game_simulator_league_state"
    ] = state
    st.session_state[
        "game_simulator_position_signature"
    ] = current_position_signature()
    clear_game_day_preview()
    save_current_franchise_checkpoint(
        state,
        trade_state=trade_state,
        reason="fresh-franchise-state",
        copy_payload=False,
    )
    return state


def get_franchise_state(
    runtime: RuntimeData,
    trade_state: LeagueState,
) -> tuple[
    SimulationLeagueState,
    bool,
]:
    key = "game_simulator_league_state"
    state = st.session_state.get(key)
    structurally_current = (
        simulation_state_is_compatible(
            state,
            expected_state_version=(
                SIMULATION_STATE_VERSION
            ),
        )
        and st.session_state.get(
            "game_simulator_position_signature"
        )
        == current_position_signature()
        and all(
            player.synthetic
            or player.position != "UNK"
            for player
            in state.players.values()
        )
    )

    if not structurally_current:
        st.session_state[
            "game_simulator_trade_sync_required"
        ] = False
        return (
            create_fresh_state(
                runtime,
                trade_state,
            ),
            True,
        )

    apply_nba_team_alignment(
        state
    )
    source_matches = (
        simulation_matches_trade_state(
            state,
            trade_state,
        )
    )
    st.session_state[
        "game_simulator_trade_sync_required"
    ] = not source_matches
    st.session_state[
        "game_simulator_trade_source_status"
    ] = simulation_source_status(
        state,
        trade_state,
    )

    # A changed Trade Machine revision must never silently erase an
    # in-progress season. Keep the permanent simulation state and block
    # additional games until a roster-sync transaction is applied.
    return state, False


def persist_franchise_widget(
    widget_key: str,
    persistent_key: str,
) -> None:
    persist_widget_value(
        st.session_state,
        persistent_key=persistent_key,
        widget_key=widget_key,
    )
    current_state = st.session_state.get(
        "game_simulator_league_state"
    )

    if simulation_state_is_compatible(
        current_state,
        expected_state_version=(
            SIMULATION_STATE_VERSION
        ),
    ):
        save_current_franchise_checkpoint(
            current_state,
            reason=(
                f"preference-update-{persistent_key}"
            ),
            copy_payload=False,
        )


def clear_game_day_preview() -> None:
    for key in {
        "franchise_game_preview",
        "franchise_game_preview_request",
    }:
        st.session_state.pop(
            key,
            None,
        )


def set_franchise_state(
    state: SimulationLeagueState,
) -> None:
    validate_simulation_league_state(
        state
    )
    st.session_state[
        "game_simulator_league_state"
    ] = state
    save_current_franchise_checkpoint(
        state,
        reason="franchise-state-commit",
        copy_payload=False,
    )


def set_selected_game(
    game_id: str,
) -> None:
    st.session_state[
        "franchise_selected_game_id"
    ] = game_id
    clear_game_day_preview()


def selected_game(
    state: SimulationLeagueState,
) -> Any | None:
    game_id = st.session_state.get(
        "franchise_selected_game_id"
    )
    game = (
        state.schedule.get(game_id)
        if isinstance(game_id, str)
        else None
    )

    if (
        game is not None
        and game.status
        == GameStatus.SCHEDULED
    ):
        return game

    return None


def upcoming_controlled_games(
    state: SimulationLeagueState,
    controlled_teams: tuple[str, ...],
) -> list[Any]:
    controlled = set(
        controlled_teams
    )

    if not controlled:
        return []

    return sorted(
        [
            game
            for game
            in state.schedule.values()
            if (
                game.status
                == GameStatus.SCHEDULED
                and controlled.intersection(
                    {
                        game.home_team,
                        game.away_team,
                    }
                )
            )
        ],
        key=lambda game: (
            int(game.day_index),
            game.game_id,
        ),
    )


def game_label(
    state: SimulationLeagueState,
    game: Any,
) -> str:
    game_date = date_for_day_index(
        state.settings.season_label,
        game.day_index,
    )
    return (
        f"{game_date.strftime('%b %d')} · "
        f"{game.away_team} at "
        f"{game.home_team}"
    )


def box_score_dataframe(
    state: SimulationLeagueState,
    completed: Any,
) -> pd.DataFrame:
    rows = []

    for line in (
        completed.player_box_scores
    ):
        player = state.players[
            line.player_id
        ]
        rows.append(
            {
                "Team": (
                    line.team_abbreviation
                ),
                "Player": (
                    player.player_name
                ),
                "Pos": player.position,
                "Starter": (
                    "Yes"
                    if line.started
                    else ""
                ),
                "MIN": round(
                    line.minutes,
                    1,
                ),
                "PTS": line.points,
                "REB": line.rebounds,
                "AST": line.assists,
                "STL": line.steals,
                "BLK": line.blocks,
                "TO": line.turnovers,
                "PF": line.fouls,
            }
        )

    return pd.DataFrame(rows)


def commit_game_transactionally(
    state: SimulationLeagueState,
    game_id: str,
    *,
    seed: int | None = None,
    sit_player_ids: tuple[str, ...] = (),
) -> tuple[
    SimulationLeagueState,
    Any,
]:
    source = (
        regular_season_state_fingerprint(
            state
        )
    )
    updated = copy.deepcopy(
        state
    )
    simulated = simulate_scheduled_game(
        updated,
        game_id,
        seed=seed,
        commit=True,
        sit_player_ids=(
            sit_player_ids
        ),
    )
    validate_simulation_league_state(
        updated
    )

    if (
        regular_season_state_fingerprint(
            state
        )
        != source
    ):
        raise FranchiseCommandCenterError(
            "Game commit mutated the "
            "source franchise state."
        )

    return updated, simulated


def postseason_game_label(
    game: Any,
) -> str:
    return (
        f"{game.round_label} · "
        f"Game {game.game_number} · "
        f"{game.away_team} at "
        f"{game.home_team}"
    )


def postseason_completed_game_label(
    game: Any,
    completed: Any,
) -> str:
    return (
        f"{game.round_label} · "
        f"Game {game.game_number} · "
        f"{completed.away_team} "
        f"{completed.away_score} at "
        f"{completed.home_team} "
        f"{completed.home_score}"
    )


def postseason_top_performers_dataframe(
    state: SimulationLeagueState,
    completed: Any,
) -> pd.DataFrame:
    rows = []

    for line in completed.player_box_scores:
        player = state.players[
            line.player_id
        ]
        impact = (
            line.points
            + 1.2 * line.rebounds
            + 1.5 * line.assists
            + 2.0 * line.steals
            + 2.0 * line.blocks
            - 1.2 * line.turnovers
        )
        rows.append(
            {
                "Team": (
                    line.team_abbreviation
                ),
                "Player": (
                    player.player_name
                ),
                "MIN": round(
                    line.minutes,
                    1,
                ),
                "PTS": line.points,
                "REB": line.rebounds,
                "AST": line.assists,
                "STL": line.steals,
                "BLK": line.blocks,
                "Impact": round(
                    impact,
                    1,
                ),
            }
        )

    rows.sort(
        key=lambda row: (
            -row["Impact"],
            -row["PTS"],
            row["Player"],
        )
    )
    return pd.DataFrame(
        rows[:10]
    )


def render_completed_postseason_game(
    state: SimulationLeagueState,
    game: Any,
    completed: Any,
) -> None:
    st.markdown(
        postseason_matchup_html(
            completed.home_team,
            completed.away_team,
            round_label=(
                game.round_label
            ),
            game_number=(
                game.game_number
            ),
        ),
        unsafe_allow_html=True,
    )
    score_columns = st.columns(
        [2, 1, 2]
    )
    score_columns[0].metric(
        completed.away_team,
        completed.away_score,
    )
    score_columns[1].metric(
        "Overtime",
        (
            completed.overtime_periods
            if completed.overtime_periods
            else "No"
        ),
    )
    score_columns[2].metric(
        completed.home_team,
        completed.home_score,
    )
    result_tabs = st.tabs(
        [
            "Box Score",
            "Top Performers",
            "Game Details",
        ]
    )

    with result_tabs[0]:
        st.dataframe(
            box_score_dataframe(
                state,
                completed,
            ),
            hide_index=True,
            width="stretch",
        )

    with result_tabs[1]:
        st.dataframe(
            postseason_top_performers_dataframe(
                state,
                completed,
            ),
            hide_index=True,
            width="stretch",
        )

    with result_tabs[2]:
        winner = (
            completed.home_team
            if completed.home_score
            > completed.away_score
            else completed.away_team
        )
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Round": (
                            game.round_label
                        ),
                        "Game": (
                            game.game_number
                        ),
                        "Winner": winner,
                        "Away": (
                            completed.away_team
                        ),
                        "Away Score": (
                            completed.away_score
                        ),
                        "Home": (
                            completed.home_team
                        ),
                        "Home Score": (
                            completed.home_score
                        ),
                        "Overtime": (
                            completed.overtime_periods
                        ),
                    }
                ]
            ),
            hide_index=True,
            width="stretch",
        )


def render_postseason_game_history(
    state: SimulationLeagueState,
    *,
    key_prefix: str,
    controlled_teams: tuple[str, ...] = (),
    default_to_controlled: bool = True,
) -> None:
    postseason = get_postseason_state(
        state,
        required=False,
    )

    if postseason is None:
        st.info(
            "Postseason game history will appear "
            "after the bracket is created."
        )
        return

    show_all = st.checkbox(
        "Show every postseason game",
        value=not default_to_controlled,
        key=(
            f"{key_prefix}_show_all_"
            "postseason_games"
        ),
    )
    filtered = (
        ()
        if show_all
        else controlled_teams
    )
    games = completed_postseason_games(
        state,
        teams=filtered,
    )

    if (
        not games
        and filtered
    ):
        games = completed_postseason_games(
            state
        )

    if not games:
        st.info(
            "No completed postseason games "
            "are available yet."
        )
        return

    game_map = {
        game.game_id: (
            game,
            completed,
        )
        for game, completed in games
    }
    selected_id = st.selectbox(
        "Completed postseason game",
        options=list(game_map),
        format_func=lambda game_id: (
            postseason_completed_game_label(
                game_map[game_id][0],
                game_map[game_id][1],
            )
        ),
        key=(
            f"{key_prefix}_completed_"
            "postseason_game"
        ),
    )
    selected_game, completed = (
        game_map[selected_id]
    )
    render_completed_postseason_game(
        state,
        selected_game,
        completed,
    )


def render_postseason_next_game_controls(
    state: SimulationLeagueState,
    *,
    active_team: str,
    controlled_teams: tuple[str, ...],
    policy: str,
    key_prefix: str,
    show_bulk_controls: bool = True,
) -> None:
    postseason = get_postseason_state(
        state
    )
    status = postseason_team_status(
        state,
        active_team,
    )
    controlled_games = (
        controlled_postseason_games(
            state,
            controlled_teams,
        )
    )

    if (
        postseason.stage
        == PostseasonStage.COMPLETE
    ):
        if status.champion:
            st.success(
                f"{team_name(active_team)} won "
                "the NBA championship."
            )
        elif status.runner_up:
            st.info(
                f"{team_name(active_team)} reached "
                "the NBA Finals."
            )
        else:
            st.info(
                f"{team_name(active_team)}'s "
                "postseason is complete."
            )
        return

    if not controlled_games:
        if status.eliminated:
            st.warning(
                f"{team_name(active_team)} has been "
                "eliminated. You can simulate the "
                "remaining postseason to the champion."
            )
        else:
            st.info(
                "No controlled-team playoff game is "
                "currently scheduled. Advance the CPU "
                "games until your next matchup is ready."
            )

        action_columns = st.columns(
            [1.3, 1.3, 2.4]
        )
        advance_clicked = (
            action_columns[0].button(
                "Advance to my next game",
                type=(
                    "primary"
                    if not status.eliminated
                    else "secondary"
                ),
                width="stretch",
                key=(
                    f"{key_prefix}_advance_"
                    "to_controlled_game"
                ),
                disabled=status.eliminated,
            )
        )
        finish_clicked = (
            action_columns[1].button(
                "Sim to champion",
                width="stretch",
                key=(
                    f"{key_prefix}_sim_"
                    "remaining_postseason"
                ),
            )
        )
        action_columns[2].caption(
            "CPU games simulate automatically. "
            "Your next controlled matchup remains "
            "unplayed and opens here."
        )

        if advance_clicked or finish_clicked:
            scope = (
                PostseasonSimulationScope
                .NEXT_CONTROLLED_GAME
                if advance_clicked
                else (
                    PostseasonSimulationScope
                    .TO_CHAMPION
                )
            )

            try:
                updated_state, result = (
                    advance_postseason_with_progress(
                        state,
                        scope=scope,
                        controlled_teams=(
                            controlled_teams
                        ),
                        policy=(
                            FranchiseSimulationPolicy
                            .FREE_SIMULATION
                        ),
                        label=(
                            "Advancing CPU postseason "
                            "games to your next matchup..."
                            if scope
                            == (
                                PostseasonSimulationScope
                                .NEXT_CONTROLLED_GAME
                            )
                            else (
                                "Simulating the remaining "
                                "postseason..."
                            )
                        ),
                    )
                )
                set_franchise_state(
                    updated_state
                )
            except (
                SimulationPostseasonError,
                SingleGameSimulationError,
                SimulationLeagueStateError,
            ) as exc:
                st.error(str(exc))
            else:
                if result.champion:
                    message = (
                        f"Postseason complete. "
                        f"{team_name(result.champion)} "
                        "won the NBA championship."
                    )
                elif (
                    result.paused_before_game_id
                ):
                    message = (
                        f"Simulated "
                        f"{result.games_simulated} CPU "
                        "postseason game(s) and stopped "
                        "before your next matchup."
                    )
                elif (
                    result.stopped_at_game_limit
                ):
                    message = (
                        f"Checkpointed "
                        f"{result.games_simulated} CPU "
                        "postseason game(s). Your next "
                        "matchup is not ready yet; use "
                        "Advance to my next game again."
                    )
                else:
                    message = (
                        f"Simulated "
                        f"{result.games_simulated} "
                        "postseason game(s)."
                    )

                st.session_state[
                    "franchise_notice"
                ] = message
                st.rerun()

        return

    game = controlled_games[0]
    st.markdown(
        postseason_matchup_html(
            game.home_team,
            game.away_team,
            round_label=(
                game.round_label
            ),
            game_number=(
                game.game_number
            ),
        ),
        unsafe_allow_html=True,
    )

    series_caption = (
        f"Series: {status.series_wins}-"
        f"{status.series_losses}"
        if status.current_series_id
        else "Single-elimination Play-In game"
    )
    st.caption(
        f"{series_caption} · "
        f"Seed {status.seed or '—'} · "
        f"{postseason_game_label(game)}"
    )

    roster_ids = [
        *state.teams[
            game.away_team
        ].rotation.rotation_player_ids,
        *state.teams[
            game.home_team
        ].rotation.rotation_player_ids,
    ]
    sit_ids = st.multiselect(
        "Players to rest or sit",
        options=roster_ids,
        format_func=lambda player_id: (
            f"{state.players[player_id].player_name} "
            f"({state.players[player_id].team_abbreviation})"
        ),
        key=(
            f"{key_prefix}_postseason_"
            f"sit_{game.game_id}"
        ),
    )
    preview_key = (
        f"{key_prefix}_postseason_preview"
    )
    preview_request_key = (
        f"{key_prefix}_postseason_"
        "preview_request"
    )
    preview = st.session_state.get(
        preview_key
    )
    preview_request = (
        st.session_state.get(
            preview_request_key
        )
    )

    if (
        preview is not None
        and (
            not isinstance(
                preview_request,
                dict,
            )
            or preview_request.get(
                "game_id"
            )
            != game.game_id
        )
    ):
        st.session_state.pop(
            preview_key,
            None,
        )
        st.session_state.pop(
            preview_request_key,
            None,
        )
        preview = None
        preview_request = None

    action_count = (
        4
        if show_bulk_controls
        else 2
    )
    actions = st.columns(
        [1] * action_count
    )
    preview_clicked = actions[0].button(
        "Preview game",
        width="stretch",
        key=(
            f"{key_prefix}_preview_"
            "postseason_game"
        ),
    )
    quick_clicked = actions[1].button(
        "Quick sim & commit",
        type="primary",
        width="stretch",
        key=(
            f"{key_prefix}_commit_"
            "postseason_game"
        ),
    )
    stage_clicked = False
    finish_clicked = False

    if show_bulk_controls:
        stage_clicked = (
            actions[2].button(
                "Sim current stage",
                width="stretch",
                key=(
                    f"{key_prefix}_sim_"
                    "postseason_stage"
                ),
            )
        )
        finish_clicked = (
            actions[3].button(
                "Sim to champion",
                width="stretch",
                key=(
                    f"{key_prefix}_sim_"
                    "postseason_champion"
                ),
            )
        )

    if preview_clicked:
        try:
            preview = simulate_postseason_game(
                state,
                game.game_id,
                sit_player_ids=(
                    tuple(sit_ids)
                ),
            )
        except (
            SimulationPostseasonError,
            SingleGameSimulationError,
            SimulationLeagueStateError,
        ) as exc:
            st.error(str(exc))
        else:
            st.session_state[
                preview_key
            ] = preview
            st.session_state[
                preview_request_key
            ] = {
                "game_id": game.game_id,
                "sit_ids": tuple(
                    sit_ids
                ),
            }
            st.rerun()

    if quick_clicked:
        try:
            updated_state, simulated = (
                commit_postseason_game(
                    state,
                    game.game_id,
                    sit_player_ids=(
                        tuple(sit_ids)
                    ),
                )
            )
            set_franchise_state(
                updated_state
            )
        except (
            SimulationPostseasonError,
            SingleGameSimulationError,
            SimulationLeagueStateError,
        ) as exc:
            st.error(str(exc))
        else:
            st.session_state.pop(
                preview_key,
                None,
            )
            st.session_state.pop(
                preview_request_key,
                None,
            )
            st.session_state[
                "franchise_notice"
            ] = (
                f"Committed {game.round_label} "
                f"Game {game.game_number}: "
                f"{simulated.game.away_team} "
                f"{simulated.game.away_score}, "
                f"{simulated.game.home_team} "
                f"{simulated.game.home_score}."
            )
            st.rerun()

    if stage_clicked or finish_clicked:
        scope = (
            PostseasonSimulationScope
            .CURRENT_STAGE
            if stage_clicked
            else (
                PostseasonSimulationScope
                .TO_CHAMPION
            )
        )
        try:
            updated_state, result = (
                advance_postseason_with_progress(
                    state,
                    scope=scope,
                    controlled_teams=(
                        controlled_teams
                    ),
                    policy=(
                        FranchiseSimulationPolicy(
                            policy
                        )
                    ),
                    label=(
                        "Simulating the current "
                        "postseason stage..."
                        if scope
                        == (
                            PostseasonSimulationScope
                            .CURRENT_STAGE
                        )
                        else (
                            "Simulating to the NBA "
                            "champion..."
                        )
                    ),
                )
            )
            set_franchise_state(
                updated_state
            )
        except (
            SimulationPostseasonError,
            SingleGameSimulationError,
            SimulationLeagueStateError,
        ) as exc:
            st.error(str(exc))
        else:
            st.session_state.pop(
                preview_key,
                None,
            )
            st.session_state.pop(
                preview_request_key,
                None,
            )
            st.session_state[
                "franchise_notice"
            ] = (
                f"Simulated "
                f"{result.games_simulated} "
                "postseason game(s)."
            )
            st.rerun()

    preview = st.session_state.get(
        preview_key
    )
    preview_request = (
        st.session_state.get(
            preview_request_key
        )
    )

    if (
        preview is not None
        and isinstance(
            preview_request,
            dict,
        )
        and preview_request.get(
            "game_id"
        )
        == game.game_id
    ):
        st.markdown("### Preview Result")
        render_completed_postseason_game(
            state,
            game,
            preview.game,
        )

        if st.button(
            "Commit previewed postseason result",
            type="primary",
            key=(
                f"{key_prefix}_commit_"
                "previewed_postseason_game"
            ),
        ):
            try:
                updated_state, _ = (
                    commit_postseason_game(
                        state,
                        game.game_id,
                        seed=(
                            preview.metadata.seed
                        ),
                        sit_player_ids=(
                            tuple(
                                preview_request[
                                    "sit_ids"
                                ]
                            )
                        ),
                    )
                )
                set_franchise_state(
                    updated_state
                )
            except (
                SimulationPostseasonError,
                SingleGameSimulationError,
                SimulationLeagueStateError,
            ) as exc:
                st.error(str(exc))
            else:
                st.session_state.pop(
                    preview_key,
                    None,
                )
                st.session_state.pop(
                    preview_request_key,
                    None,
                )
                st.session_state[
                    "franchise_notice"
                ] = (
                    "Committed the exact previewed "
                    "postseason result."
                )
                st.rerun()


def render_postseason_command_center(
    state: SimulationLeagueState,
    *,
    active_team: str,
    controlled_teams: tuple[str, ...],
    policy: str,
) -> None:
    postseason = get_postseason_state(
        state,
        required=False,
    )
    st.markdown(
        '<div class="fm-section">Postseason</div>',
        unsafe_allow_html=True,
    )

    if postseason is None:
        standing = state.standings[
            active_team
        ]
        conference = (
            conference_for_team(
                active_team
            )
        )
        seed_order = standings_rows(
            state,
            conference=conference,
        )
        seed = next(
            (
                row["Rank"]
                for row in seed_order
                if row["Team"]
                == active_team
            ),
            "—",
        )
        st.success(
            "The regular season is complete. "
            f"{team_name(active_team)} finished "
            f"{standing.wins}-{standing.losses} "
            f"as the {conference} No. {seed} seed."
        )

        if st.button(
            "Begin NBA postseason",
            type="primary",
            width="stretch",
            key=(
                "command_center_begin_"
                "postseason"
            ),
        ):
            try:
                updated_state = copy.deepcopy(
                    state
                )
                initialize_postseason(
                    updated_state
                )
                set_franchise_state(
                    updated_state
                )
            except (
                SimulationPostseasonError,
                SimulationLeagueStateError,
            ) as exc:
                st.error(str(exc))
            else:
                st.session_state[
                    "franchise_notice"
                ] = (
                    "Created the NBA Play-In "
                    "Tournament and playoff bracket."
                )
                st.rerun()

        return

    status = postseason_team_status(
        state,
        active_team,
    )
    metrics = st.columns(5)
    metrics[0].metric(
        "Stage",
        postseason.stage.value.replace(
            "_",
            " ",
        ).title(),
    )
    metrics[1].metric(
        "Seed",
        (
            f"#{status.seed}"
            if status.seed
            else "—"
        ),
    )
    metrics[2].metric(
        "Series",
        (
            f"{status.series_wins}-"
            f"{status.series_losses}"
            if status.current_series_id
            else "Play-In"
            if status.current_round
            else "—"
        ),
    )
    metrics[3].metric(
        "Postseason Games",
        len(
            postseason.completed_games
        ),
    )
    metrics[4].metric(
        "Status",
        (
            "Champion"
            if status.champion
            else "Runner-up"
            if status.runner_up
            else "Eliminated"
            if status.eliminated
            else "Alive"
        ),
    )

    render_postseason_next_game_controls(
        state,
        active_team=active_team,
        controlled_teams=(
            controlled_teams
        ),
        policy=policy,
        key_prefix="command_center",
        show_bulk_controls=True,
    )

    with st.expander(
        "View postseason bracket",
        expanded=False,
    ):
        rows = postseason_series_rows(
            state
        )

        if rows:
            st.dataframe(
                pd.DataFrame(rows),
                hide_index=True,
                width="stretch",
            )
        else:
            opening_rows = [
                {
                    "Round": game.round_label,
                    "Conference": (
                        game.conference
                    ),
                    "Away": game.away_team,
                    "Home": game.home_team,
                    "Status": (
                        game.status.value
                    ),
                    "Winner": game.winner,
                }
                for game
                in postseason.games.values()
            ]
            st.dataframe(
                pd.DataFrame(
                    opening_rows
                ),
                hide_index=True,
                width="stretch",
            )


def render_postseason_game_day(
    state: SimulationLeagueState,
    *,
    active_team: str,
    controlled_teams: tuple[str, ...],
    policy: str,
) -> None:
    postseason = get_postseason_state(
        state,
        required=False,
    )

    if postseason is None:
        st.info(
            "The regular season is complete. "
            "Begin the NBA postseason from the "
            "Command Center."
        )
        return

    st.markdown("## Postseason Game Center")
    render_postseason_next_game_controls(
        state,
        active_team=active_team,
        controlled_teams=(
            controlled_teams
        ),
        policy=policy,
        key_prefix="game_day",
        show_bulk_controls=False,
    )
    st.divider()
    st.markdown("## Completed Postseason Games")
    render_postseason_game_history(
        state,
        key_prefix="game_day",
        controlled_teams=(
            controlled_teams
        ),
        default_to_controlled=True,
    )


def inject_styles() -> None:
    st.markdown(
        """
<style>
:root {
  --fm-ink: #f8fafc;
  --fm-muted: #98a2b3;
  --fm-line: #344054;
  --fm-card: #151922;
  --fm-soft: #1d2430;
  --fm-blue: #2e90fa;
  --fm-red: #ff4b55;
}
.block-container {
  max-width: 1540px;
  padding-top: 1.15rem;
}
.fm-hero {
  padding: 24px 28px;
  border: 1px solid #344054;
  border-radius: 22px;
  background:
    linear-gradient(115deg, #071c35 0%, #123f73 58%, #367fbd 100%);
  box-shadow: 0 18px 45px rgba(0,0,0,.18);
}
.fm-eyebrow {
  color: #d1e9ff;
  font-size: .72rem;
  font-weight: 850;
  letter-spacing: .18em;
}
.fm-title {
  margin-top: 6px;
  color: #fff;
  font-size: clamp(2rem, 4vw, 3.35rem);
  font-weight: 950;
  line-height: 1;
}
.fm-subtitle {
  max-width: 920px;
  margin-top: 12px;
  color: #e6f1fb;
  font-size: 1rem;
  line-height: 1.65;
}
.fm-team-header {
  display: flex;
  min-height: 142px;
  align-items: center;
  gap: 22px;
  padding: 20px 24px;
  border: 1px solid #344054;
  border-radius: 20px;
  background: linear-gradient(145deg, #151922, #0b1018);
}
.fm-team-logo {
  width: 106px;
  height: 106px;
  object-fit: contain;
  filter: drop-shadow(0 8px 14px rgba(0,0,0,.25));
}
.fm-team-name {
  color: #fff;
  font-size: 2rem;
  font-weight: 950;
}
.fm-team-meta {
  margin-top: 6px;
  color: #98a2b3;
  font-size: .85rem;
  font-weight: 700;
}
.fm-next {
  margin-top: 10px;
  color: #d1e9ff;
  font-size: .94rem;
  font-weight: 750;
}
.fm-section {
  margin: 24px 0 10px;
  color: #98a2b3;
  font-size: .72rem;
  font-weight: 850;
  letter-spacing: .16em;
  text-transform: uppercase;
}
.fm-alert {
  margin: 8px 0;
  padding: 12px 14px;
  border: 1px solid #475467;
  border-radius: 12px;
  background: #1d2430;
}
.fm-alert.warning,
.fm-alert.critical {
  border-color: #f79009;
  background: #2b2112;
}
.fm-alert-title {
  color: #fff;
  font-weight: 850;
}
.fm-alert-detail {
  margin-top: 4px;
  color: #cbd5e1;
  font-size: .82rem;
}
.fm-calendar {
  display: grid;
  grid-template-columns: repeat(7, minmax(0, 1fr));
  gap: 7px;
  margin-top: 10px;
}
.fm-weekday {
  padding: 7px 3px;
  color: #98a2b3;
  font-size: .65rem;
  font-weight: 850;
  letter-spacing: .11em;
  text-align: center;
}
.fm-day {
  min-height: 128px;
  padding: 9px;
  border: 1px solid #344054;
  border-radius: 14px;
  background: #151922;
}
.fm-day.outside {
  opacity: .28;
}
.fm-day.current {
  border: 2px solid #f79009;
  box-shadow: 0 0 0 3px rgba(247,144,9,.14);
}
.fm-day.home {
  background: linear-gradient(145deg, #102a43, #151922);
  border-color: #53b1fd;
}
.fm-day.away {
  background: linear-gradient(145deg, #3b211b, #151922);
  border-color: #f79009;
}
.fm-date {
  color: #d0d5dd;
  font-size: .72rem;
  font-weight: 850;
}
.fm-rest {
  display: flex;
  min-height: 95px;
  align-items: center;
  justify-content: center;
  color: #667085;
  font-size: .62rem;
  font-weight: 800;
  letter-spacing: .08em;
}
.fm-game {
  display: flex;
  min-height: 95px;
  flex-direction: column;
  align-items: center;
  justify-content: center;
}
.fm-game-logo {
  width: 46px;
  height: 46px;
  object-fit: contain;
}
.fm-matchup {
  margin-top: 5px;
  color: #fff;
  font-size: .78rem;
  font-weight: 900;
}
.fm-result {
  margin-top: 4px;
  color: #6ce9a6;
  font-size: .72rem;
  font-weight: 850;
}
.fm-upcoming {
  margin-top: 4px;
  color: #84caff;
  font-size: .6rem;
  font-weight: 850;
  letter-spacing: .08em;
}
.fm-matchup-card {
  display: flex;
  min-height: 190px;
  align-items: center;
  justify-content: center;
  gap: 32px;
  padding: 20px;
  border: 1px solid #344054;
  border-radius: 18px;
  background: #151922;
}
.fm-matchup-team {
  min-width: 220px;
  text-align: center;
}
.fm-matchup-team img {
  width: 92px;
  height: 92px;
  object-fit: contain;
}
.fm-matchup-name {
  margin-top: 8px;
  color: #fff;
  font-size: 1.1rem;
  font-weight: 900;
}
.fm-versus {
  color: #98a2b3;
  font-size: 1rem;
  font-weight: 850;
}
div[data-testid="stMetric"] {
  border: 1px solid #344054;
  border-radius: 14px;
  padding: 10px 12px;
  background: #151922;
}
</style>
        """,
        unsafe_allow_html=True,
    )


inject_styles()
runtime = get_base_runtime()
checkpoint_restored = (
    restore_franchise_checkpoint()
)
trade_state = get_trade_state(
    runtime
)
state, rebuilt = get_franchise_state(
    runtime,
    trade_state,
)

# One-time migration for a live pre-checkpoint Streamlit session. Installing
# this slice while the page is open writes the current season before any
# process restart is allowed.
if (
    not checkpoint_restored
    and not rebuilt
    and not DEFAULT_CHECKPOINT_PATH.exists()
):
    save_current_franchise_checkpoint(
        state,
        trade_state=trade_state,
        reason="live-session-checkpoint-migration",
        copy_payload=False,
    )

# Installing a newer checkpoint writer while Franchise Mode is open must
# immediately migrate the live in-memory season. This also recovers a save
# failure whose warning was already rendered and removed from session state.
checkpoint_writer_key = (
    "franchise_checkpoint_writer_implementation"
)
if (
    not rebuilt
    and st.session_state.get(
        checkpoint_writer_key
    )
    != CHECKPOINT_IMPLEMENTATION_VERSION
):
    writer_upgrade_saved = (
        save_current_franchise_checkpoint(
            state,
            trade_state=trade_state,
            reason=(
                "checkpoint-writer-upgrade-recovery"
            ),
            copy_payload=False,
        )
    )

    if writer_upgrade_saved:
        st.session_state[
            checkpoint_writer_key
        ] = CHECKPOINT_IMPLEMENTATION_VERSION
        st.session_state[
            "franchise_notice"
        ] = (
            "Recovered the live franchise state with "
            "the upgraded durable checkpoint writer."
        )

if rebuilt and not checkpoint_restored:
    st.session_state[
        "franchise_notice"
    ] = (
        "Franchise state refreshed from "
        "the latest roster universe."
    )

teams = sorted(state.teams)

controlled_pref_key = (
    "franchise_pref_controlled_teams"
)
controlled_widget_key = (
    "_franchise_controlled_teams_widget"
)
active_pref_key = (
    "franchise_pref_active_team"
)
active_widget_key = (
    "_franchise_active_team_widget"
)
policy_pref_key = (
    "franchise_pref_simulation_policy"
)
policy_widget_key = (
    "_franchise_simulation_policy_widget"
)

default_controlled = (
    ["CHI"]
    if "CHI" in teams
    else [teams[0]]
)
initialize_persistent_widget(
    st.session_state,
    persistent_key=controlled_pref_key,
    widget_key=controlled_widget_key,
    default=default_controlled,
)
persisted_controlled = [
    team
    for team in st.session_state[
        controlled_pref_key
    ]
    if team in teams
]

if not persisted_controlled:
    persisted_controlled = list(
        default_controlled
    )
    st.session_state[
        controlled_pref_key
    ] = list(
        persisted_controlled
    )
    st.session_state[
        controlled_widget_key
    ] = list(
        persisted_controlled
    )

default_active = (
    persisted_controlled[0]
    if persisted_controlled
    else teams[0]
)
initialize_persistent_widget(
    st.session_state,
    persistent_key=active_pref_key,
    widget_key=active_widget_key,
    default=default_active,
)

if st.session_state[
    active_pref_key
] not in teams:
    st.session_state[
        active_pref_key
    ] = default_active
    st.session_state[
        active_widget_key
    ] = default_active

initialize_persistent_widget(
    st.session_state,
    persistent_key=policy_pref_key,
    widget_key=policy_widget_key,
    default=(
        FranchiseSimulationPolicy
        .STOP_FOR_DECISIONS.value
    ),
)

st.markdown(
    """
<div class="fm-hero">
  <div class="fm-eyebrow">MULTI-YEAR FRONT OFFICE MODE</div>
  <div class="fm-title">NBA Franchise Mode</div>
  <div class="fm-subtitle">
    Control teams, save rotations, manage game-day decisions,
    simulate complete seasons, follow statistics and standings,
    explore trade needs, and build toward the postseason,
    offseason, and draft.
  </div>
</div>
    """,
    unsafe_allow_html=True,
)

notice = st.session_state.pop(
    "franchise_notice",
    None,
)
if notice:
    st.success(notice)

checkpoint_warning = st.session_state.pop(
    "franchise_checkpoint_warning",
    None,
)
if checkpoint_warning:
    retry_signature = (
        f"{checkpoint_warning}|"
        f"{len(state.completed_games)}|"
        f"{getattr(getattr(state, 'postseason_state', None), 'stage', '')}"
    )
    already_retried = (
        st.session_state.get(
            "franchise_checkpoint_auto_retry_signature"
        )
        == retry_signature
    )
    retry_succeeded = False

    if not already_retried:
        st.session_state[
            "franchise_checkpoint_auto_retry_signature"
        ] = retry_signature
        retry_succeeded = (
            save_current_franchise_checkpoint(
                state,
                trade_state=trade_state,
                reason=(
                    "automatic-checkpoint-write-recovery"
                ),
                copy_payload=False,
            )
        )

    if retry_succeeded:
        st.success(
            "Recovered the durable franchise checkpoint "
            "and saved the current live season state."
        )
    else:
        current_warning = st.session_state.get(
            "franchise_checkpoint_warning",
            checkpoint_warning,
        )
        st.warning(
            current_warning
        )
        error_details = st.session_state.get(
            "franchise_checkpoint_last_error"
        )

        if error_details:
            with st.expander(
                "Checkpoint error details",
                expanded=False,
            ):
                st.json(
                    error_details
                )

        if st.button(
            "Retry durable checkpoint now",
            type="primary",
            key="retry_durable_franchise_checkpoint",
        ):
            saved = save_current_franchise_checkpoint(
                state,
                trade_state=trade_state,
                reason=(
                    "manual-checkpoint-write-recovery"
                ),
                copy_payload=False,
            )

            if saved:
                st.session_state[
                    "franchise_notice"
                ] = (
                    "Saved the current franchise state "
                    "to the durable checkpoint."
                )
                st.rerun()

checkpoint_saved_at = (
    st.session_state.get(
        "franchise_checkpoint_saved_at"
    )
)
if checkpoint_saved_at:
    st.caption(
        "Durable franchise checkpoint: "
        f"{checkpoint_saved_at}"
    )

trade_sync_required = bool(
    st.session_state.get(
        "game_simulator_trade_sync_required",
        False,
    )
)

if trade_sync_required:
    source_status = st.session_state.get(
        "game_simulator_trade_source_status"
    )
    detail = ""
    if source_status is not None:
        detail = (
            " Franchise source revision "
            f"{source_status.simulation_revision}; "
            "Trade Machine revision "
            f"{source_status.trade_descriptor.state_revision}."
        )

    try:
        sync_preview = (
            build_trade_sync_preview(
                state,
                trade_state,
            )
        )
    except SimulationTradeSyncError as exc:
        st.error(
            "The trade could not be prepared "
            f"for the active season. Detail: {exc}"
        )
        sync_preview = None

    st.warning(
        "The Trade Machine league changed after this franchise "
        "season began. The current schedule, scores, standings, "
        "statistics, injuries, and history remain intact."
        + detail
    )

    if sync_preview is not None:
        moved_names = [
            (
                f"{move.player_name}: "
                f"{move.old_team or 'FA'} → "
                f"{move.new_team or 'FA'}"
            )
            for move in sync_preview.moves
        ]
        st.caption(
            (
                "Pending roster moves: "
                + "; ".join(moved_names)
            )
            if moved_names
            else (
                "The new transaction changes picks or "
                "metadata but not player ownership."
            )
        )

        if st.button(
            "Apply trade to active season",
            type="primary",
            key="franchise_apply_trade_sync",
        ):
            try:
                with st.spinner(
                    "Synchronizing rosters without "
                    "resetting the season..."
                ):
                    (
                        synchronized_state,
                        sync_result,
                    ) = (
                        synchronize_simulation_with_trade_state(
                            state,
                            trade_state,
                        )
                    )
                    set_franchise_state(
                        synchronized_state
                    )
            except (
                SimulationTradeSyncError,
                SimulationLeagueStateError,
            ) as exc:
                st.error(
                    "The in-season trade sync "
                    f"failed. Detail: {exc}"
                )
            else:
                clear_game_day_preview()
                st.session_state[
                    "game_simulator_trade_sync_required"
                ] = False
                st.session_state[
                    "franchise_notice"
                ] = (
                    f"Applied {len(sync_result.moved_players)} "
                    "player move(s) while preserving "
                    f"{sync_result.preserved_completed_games} "
                    "completed game(s), the full schedule, "
                    "standings, and player statistics."
                )
                st.rerun()


control_columns = st.columns(
    [2.5, 1.6, 2.4]
)

with control_columns[0]:
    controlled_values = st.multiselect(
        "User-controlled teams",
        options=teams,
        format_func=lambda team: (
            f"{team_name(team)} ({team})"
        ),
        key=controlled_widget_key,
        on_change=persist_franchise_widget,
        args=(
            controlled_widget_key,
            controlled_pref_key,
        ),
    )

controlled_teams = (
    normalize_controlled_teams(
        controlled_values,
        available_teams=teams,
    )
)

if (
    st.session_state[
        active_widget_key
    ] not in teams
):
    st.session_state[
        active_widget_key
    ] = (
        controlled_teams[0]
        if controlled_teams
        else teams[0]
    )

with control_columns[1]:
    active_team = st.selectbox(
        "Active team",
        options=teams,
        format_func=lambda team: (
            f"{team_name(team)} ({team})"
        ),
        key=active_widget_key,
        on_change=persist_franchise_widget,
        args=(
            active_widget_key,
            active_pref_key,
        ),
    )

with control_columns[2]:
    policy = st.selectbox(
        "Simulation policy",
        options=[
            value.value
            for value
            in FranchiseSimulationPolicy
        ],
        format_func=lambda value: (
            POLICY_LABELS[
                FranchiseSimulationPolicy(
                    value
                )
            ]
        ),
        key=policy_widget_key,
        on_change=persist_franchise_widget,
        args=(
            policy_widget_key,
            policy_pref_key,
        ),
    )

full_schedule_active = (
    len(state.schedule)
    == LEAGUE_GAME_COUNT
)

if not state.schedule:
    with st.container(border=True):
        schedule_columns = st.columns(
            [3.4, 1.2]
        )

        with schedule_columns[0]:
            st.subheader(
                "Create the generated 2026–27 season"
            )
            st.caption(
                "Installs the validated realistic "
                "1,230-game filler schedule. It is "
                "not the official NBA schedule."
            )

        with schedule_columns[1]:
            generate_clicked = st.button(
                "Generate season",
                type="primary",
                width="stretch",
            )

    if generate_clicked:
        try:
            updated = copy.deepcopy(
                state
            )
            generated = (
                generate_regular_season_schedule(
                    updated,
                    seed=(
                        updated.settings
                        .random_seed
                    ),
                )
            )
            install_regular_season_schedule(
                updated,
                generated,
            )
            set_franchise_state(
                updated
            )
        except (
            RegularSeasonScheduleError,
            SimulationLeagueStateError,
        ) as exc:
            st.error(str(exc))
        else:
            st.session_state[
                "franchise_notice"
            ] = (
                "Generated the full "
                "82-game schedule."
            )
            st.rerun()

if (
    state.schedule
    and not full_schedule_active
):
    st.warning(
        "The current state contains a partial custom "
        "schedule. Reset the simulation before using "
        "the complete Franchise Mode calendar."
    )

snapshot = build_team_snapshot(
    state,
    active_team,
)
primary, secondary = team_colors(
    active_team
)
next_copy = (
    (
        f"{snapshot.next_location} vs "
        f"{snapshot.next_opponent} · "
        f"{snapshot.next_game_date}"
    )
    if snapshot.next_game_id
    else "Regular season complete"
)

st.markdown(
    (
        '<div class="fm-team-header" '
        f'style="border-top:5px solid {primary};">'
        f'<img class="fm-team-logo" '
        f'src="{escaped(snapshot.logo_url)}">'
        "<div>"
        f'<div class="fm-team-name">'
        f"{escaped(snapshot.team_name)}"
        "</div>"
        f'<div class="fm-team-meta">'
        f"{escaped(snapshot.conference)} · "
        f"{escaped(snapshot.division)} · "
        f"{snapshot.wins}-{snapshot.losses} · "
        f"Conference rank #{snapshot.conference_rank}"
        "</div>"
        f'<div class="fm-next">'
        f"Next: {escaped(next_copy)}"
        "</div>"
        "</div>"
        "</div>"
    ),
    unsafe_allow_html=True,
)

stat_health = season_stat_contamination(
    state
)

if bool(stat_health["contaminated"]):
    st.error(
        "This active season contains statistics produced by the "
        "previous scoring and minutes allocator. Its existing box "
        "scores cannot be made realistic without replaying the season. "
        f"Current maxima: {stat_health['maximum_ppg']:.1f} PPG and "
        f"{stat_health['maximum_mpg']:.1f} MPG. "
        "High-workload minute standard deviation: "
        f"{stat_health['high_minute_standard_deviation']:.2f}."
    )
    confirm_clean_reset = st.checkbox(
        "I understand this will erase this test season's schedule, "
        "results, standings, and statistics while preserving the "
        "current Trade Machine roster universe.",
        key="_franchise_confirm_calibrated_reset",
    )

    if st.button(
        "Start clean season with historical-minute engine",
        type="primary",
        disabled=not confirm_clean_reset,
        key="franchise_calibrated_season_reset",
    ):
        try:
            calibrated_state = create_fresh_state(
                runtime,
                trade_state,
            )
            calibrated_schedule = (
                generate_regular_season_schedule(
                    calibrated_state,
                    seed=(
                        calibrated_state
                        .settings.random_seed
                    ),
                )
            )
            install_regular_season_schedule(
                calibrated_state,
                calibrated_schedule,
            )
            set_franchise_state(
                calibrated_state
            )
        except (
            RegularSeasonScheduleError,
            SimulationLeagueStateError,
        ) as exc:
            st.error(str(exc))
        else:
            st.session_state[
                "franchise_notice"
            ] = (
                "Started a clean 2026-27 season using "
                f"{ENGINE_VERSION} and "
                f"{MINUTES_MODEL_VERSION}."
            )
            st.rerun()

tabs = st.tabs(
    [
        "Command Center",
        "Calendar",
        "Team Management",
        "Game Day",
        "Stats & Standings",
        "Trade Center",
        "League & Offseason",
    ]
)

with tabs[0]:
    metrics = st.columns(6)
    metrics[0].metric(
        "Record",
        f"{snapshot.wins}-{snapshot.losses}",
    )
    metrics[1].metric(
        "Conference",
        f"#{snapshot.conference_rank}",
    )
    metrics[2].metric(
        "League",
        f"#{snapshot.league_rank}",
    )
    metrics[3].metric(
        "Point diff",
        f"{snapshot.point_differential:+d}",
    )
    metrics[4].metric(
        "Recent form",
        snapshot.recent_form,
    )
    metrics[5].metric(
        "Season",
        (
            f"{snapshot.season_completion_percentage:.1f}%"
        ),
    )

    if regular_season_is_complete(
        state
    ):
        render_postseason_command_center(
            state,
            active_team=active_team,
            controlled_teams=(
                controlled_teams
            ),
            policy=policy,
        )
    else:
        st.markdown(
            '<div class="fm-section">Coaching inbox</div>',
            unsafe_allow_html=True,
        )

        if snapshot.alerts:
            for alert in snapshot.alerts:
                st.markdown(
                    (
                        '<div class="fm-alert '
                        f'{escaped(alert.severity)}">'
                        '<div class="fm-alert-title">'
                        f"{escaped(alert.title)}"
                        "</div>"
                        '<div class="fm-alert-detail">'
                        f"{escaped(alert.detail)}"
                        "</div>"
                        "</div>"
                    ),
                    unsafe_allow_html=True,
                )
        else:
            st.info(
                "No urgent coaching or medical "
                "decisions are required."
            )

        st.markdown(
            '<div class="fm-section">Advance the league</div>',
            unsafe_allow_html=True,
        )
        advance_columns = st.columns(
            [1, 1, 1.2, 2.4]
        )
        next_day_clicked = advance_columns[
            0
        ].button(
            "Next day",
            width="stretch",
            disabled=(
                not full_schedule_active
                or trade_sync_required
            ),
            key="franchise_next_day",
        )
        next_week_clicked = advance_columns[
            1
        ].button(
            "Next week",
            width="stretch",
            disabled=(
                not full_schedule_active
                or trade_sync_required
            ),
            key="franchise_next_week",
        )
        season_end_clicked = advance_columns[
            2
        ].button(
            "Season end",
            type="primary",
            width="stretch",
            disabled=(
                not full_schedule_active
                or trade_sync_required
            ),
            key="franchise_season_end",
        )
        advance_columns[3].caption(
            POLICY_LABELS[
                FranchiseSimulationPolicy(
                    policy
                )
            ]
        )

        requested_scope = (
            SimulationScope.NEXT_DAY
            if next_day_clicked
            else SimulationScope.NEXT_WEEK
            if next_week_clicked
            else SimulationScope.REMAINDER
            if season_end_clicked
            else None
        )

        if requested_scope is not None:
            try:
                with st.spinner(
                    "Advancing the franchise..."
                ):
                    updated, advance_result = (
                        advance_franchise_scope(
                            state,
                            controlled_teams=(
                                controlled_teams
                            ),
                            policy=policy,
                            scope=requested_scope,
                        )
                    )
                    set_franchise_state(
                        updated
                    )
            except (
                FranchiseCommandCenterError,
                RegularSeasonSimulationControllerError,
                SimulationLeagueStateError,
            ) as exc:
                st.error(str(exc))
            else:
                if (
                    advance_result
                    .selected_game_id
                ):
                    set_selected_game(
                        advance_result
                        .selected_game_id
                    )

                st.session_state[
                    "franchise_notice"
                ] = (
                    advance_result.message
                )
                st.rerun()

        if snapshot.next_game_id:
            action_columns = st.columns(
                [1.2, 1.2, 3]
            )

            if action_columns[0].button(
                "Open next game",
                width="stretch",
            ):
                set_selected_game(
                    snapshot.next_game_id
                )
                st.session_state[
                    "franchise_notice"
                ] = (
                    "Loaded the next matchup "
                    "into Game Day."
                )
                st.rerun()

            action_columns[1].page_link(
                "pages/4_Game_Simulator.py",
                label="Open quick simulator",
                icon="🏀",
            )

with tabs[1]:
    if not full_schedule_active:
        st.info(
            "Generate the complete schedule "
            "to unlock the calendar."
        )
    else:
        month_options = (
            available_calendar_months(
                state
            )
        )
        default_month = (
            default_calendar_month(
                state,
                active_team,
            )
        )
        month_pref_key = (
            "franchise_pref_calendar_month"
        )
        month_widget_key = (
            "_franchise_calendar_month_widget"
        )
        initialize_persistent_widget(
            st.session_state,
            persistent_key=month_pref_key,
            widget_key=month_widget_key,
            default=default_month,
        )

        if st.session_state[
            month_widget_key
        ] not in month_options:
            st.session_state[
                month_widget_key
            ] = default_month
            st.session_state[
                month_pref_key
            ] = default_month

        selected_month = st.selectbox(
            "Month",
            options=month_options,
            format_func=lambda value: (
                pd.Timestamp(
                    year=value[0],
                    month=value[1],
                    day=1,
                ).strftime("%B %Y")
            ),
            key=month_widget_key,
            on_change=persist_franchise_widget,
            args=(
                month_widget_key,
                month_pref_key,
            ),
        )
        month_model = (
            build_team_month_calendar(
                state,
                active_team,
                year=selected_month[0],
                month=selected_month[1],
                controlled_teams=(
                    controlled_teams
                ),
            )
        )
        st.markdown(
            calendar_with_logos_html(
                month_model
            ),
            unsafe_allow_html=True,
        )
        st.caption(
            "Generated simulation schedule. "
            "Opponent logos use NBA-hosted "
            "public logo assets."
        )

        month_games = [
            game
            for game
            in team_schedule_games(
                state,
                active_team,
            )
            if (
                game.status
                == GameStatus.SCHEDULED
                and date_for_day_index(
                    state.settings
                    .season_label,
                    game.day_index,
                ).year
                == selected_month[0]
                and date_for_day_index(
                    state.settings
                    .season_label,
                    game.day_index,
                ).month
                == selected_month[1]
            )
        ]

        if month_games:
            calendar_action = st.selectbox(
                "Upcoming game",
                options=[
                    game.game_id
                    for game in month_games
                ],
                format_func=lambda game_id: (
                    game_label(
                        state,
                        state.schedule[
                            game_id
                        ],
                    )
                ),
            )

            if st.button(
                "Manage selected game",
                type="primary",
            ):
                set_selected_game(
                    calendar_action
                )
                st.session_state[
                    "franchise_notice"
                ] = (
                    "Selected calendar game "
                    "loaded into Game Day."
                )
                st.rerun()

with tabs[2]:
    st.subheader(
        f"{team_name(active_team)} rotation"
    )
    st.caption(
        "Choose exactly five starters, keep "
        "at least eight players in the rotation, "
        "and assign exactly 240 total minutes."
    )
    rotation_rows = (
        rotation_management_rows(
            state,
            active_team,
        )
    )
    rotation_frame = pd.DataFrame(
        rotation_rows
    )
    edited_rotation = st.data_editor(
        rotation_frame,
        hide_index=True,
        width="stretch",
        disabled=[
            "player_id",
            "player",
            "position",
            "age",
            "overall",
            "availability",
        ],
        column_order=[
            "rotation_order",
            "player",
            "position",
            "age",
            "overall",
            "starter",
            "in_rotation",
            "minutes",
            "availability",
        ],
        column_config={
            "rotation_order": (
                st.column_config.NumberColumn(
                    "Order",
                    min_value=1,
                    max_value=30,
                    step=1,
                )
            ),
            "player": "Player",
            "position": "Pos",
            "overall": (
                st.column_config.NumberColumn(
                    "OVR",
                    format="%.1f",
                )
            ),
            "starter": (
                st.column_config.CheckboxColumn(
                    "Starter"
                )
            ),
            "in_rotation": (
                st.column_config.CheckboxColumn(
                    "Rotation"
                )
            ),
            "minutes": (
                st.column_config.NumberColumn(
                    "Minutes",
                    min_value=0.0,
                    max_value=48.0,
                    step=0.5,
                    format="%.1f",
                )
            ),
        },
        key=(
            f"franchise_rotation_editor_"
            f"{active_team}_"
            f"{state.settings.season_label}"
        ),
    )
    assigned_minutes = float(
        edited_rotation.loc[
            edited_rotation[
                "in_rotation"
            ],
            "minutes",
        ].sum()
    )
    starter_count = int(
        edited_rotation[
            "starter"
        ].sum()
    )
    rotation_count = int(
        edited_rotation[
            "in_rotation"
        ].sum()
    )
    rotation_metrics = st.columns(4)
    rotation_metrics[0].metric(
        "Assigned minutes",
        f"{assigned_minutes:.1f}",
        delta=(
            f"{assigned_minutes - 240:+.1f}"
        ),
    )
    rotation_metrics[1].metric(
        "Starters",
        starter_count,
    )
    rotation_metrics[2].metric(
        "Rotation players",
        rotation_count,
    )
    rotation_metrics[3].metric(
        "Target",
        "240.0",
    )

    if st.button(
        "Save rotation and minutes",
        type="primary",
        disabled=trade_sync_required,
    ):
        try:
            ordered = (
                edited_rotation
                .sort_values(
                    [
                        "rotation_order",
                        "overall",
                    ],
                    ascending=[
                        True,
                        False,
                    ],
                )
                .to_dict(
                    orient="records"
                )
            )
            plan = (
                rotation_plan_from_rows(
                    state,
                    active_team,
                    ordered,
                )
            )
            updated = apply_rotation_plan(
                state,
                plan,
            )
            set_franchise_state(
                updated
            )
        except (
            FranchiseCommandCenterError,
            SimulationLeagueStateError,
            ValueError,
        ) as exc:
            st.error(str(exc))
        else:
            st.session_state[
                "franchise_notice"
            ] = (
                f"Saved {active_team}'s "
                "rotation and 240-minute plan."
            )
            st.rerun()

with tabs[3]:
    if regular_season_is_complete(
        state
    ):
        render_postseason_game_day(
            state,
            active_team=active_team,
            controlled_teams=(
                controlled_teams
            ),
            policy=policy,
        )
    else:
        controlled_games = (
            upcoming_controlled_games(
                state,
                controlled_teams,
            )
        )
        current_game = selected_game(
            state
        )

        if (
            current_game is None
            and controlled_games
        ):
            current_game = (
                controlled_games[0]
            )
            st.session_state[
                "franchise_selected_game_id"
            ] = current_game.game_id

        if current_game is None:
            st.info(
                "No upcoming controlled-team "
                "game is available."
            )
        else:
            game_choices = {
                game.game_id: game
                for game in controlled_games
            }

            if (
                current_game.game_id
                not in game_choices
            ):
                game_choices[
                    current_game.game_id
                ] = current_game

            chosen_game_id = st.selectbox(
                "Controlled-team matchup",
                options=list(
                    game_choices
                ),
                index=list(
                    game_choices
                ).index(
                    current_game.game_id
                ),
                format_func=lambda game_id: (
                    game_label(
                        state,
                        game_choices[
                            game_id
                        ],
                    )
                ),
            )

            if (
                chosen_game_id
                != current_game.game_id
            ):
                set_selected_game(
                    chosen_game_id
                )
                st.rerun()

            current_game = game_choices[
                chosen_game_id
            ]
            st.markdown(
                (
                    '<div class="fm-matchup-card">'
                    '<div class="fm-matchup-team">'
                    f'<img src="{escaped(team_logo_url(current_game.away_team))}">'
                    '<div class="fm-matchup-name">'
                    f"{escaped(team_name(current_game.away_team))}"
                    "</div>"
                    "</div>"
                    '<div class="fm-versus">AT</div>'
                    '<div class="fm-matchup-team">'
                    f'<img src="{escaped(team_logo_url(current_game.home_team))}">'
                    '<div class="fm-matchup-name">'
                    f"{escaped(team_name(current_game.home_team))}"
                    "</div>"
                    "</div>"
                    "</div>"
                ),
                unsafe_allow_html=True,
            )

            game_roster_ids = [
                *state.teams[
                    current_game.away_team
                ].rotation.rotation_player_ids,
                *state.teams[
                    current_game.home_team
                ].rotation.rotation_player_ids,
            ]
            sit_ids = st.multiselect(
                "Players to rest or sit",
                options=game_roster_ids,
                format_func=lambda player_id: (
                    f"{state.players[player_id].player_name} "
                    f"({state.players[player_id].team_abbreviation})"
                ),
                key=(
                    f"franchise_sit_"
                    f"{current_game.game_id}"
                ),
            )
            game_actions = st.columns(
                [1, 1, 1.6]
            )
            preview_clicked = game_actions[
                0
            ].button(
                "Preview game",
                width="stretch",
                disabled=trade_sync_required,
            )
            quick_commit_clicked = (
                game_actions[1].button(
                    "Quick sim & commit",
                    type="primary",
                    width="stretch",
                    disabled=trade_sync_required,
                )
            )
            game_actions[2].caption(
                "Quick sim commits immediately. "
                "Preview lets you inspect the box "
                "score first."
            )

            if preview_clicked:
                try:
                    preview = (
                        simulate_scheduled_game(
                            state,
                            current_game.game_id,
                            commit=False,
                            sit_player_ids=(
                                tuple(sit_ids)
                            ),
                        )
                    )
                except (
                    SingleGameSimulationError,
                    SimulationLeagueStateError,
                ) as exc:
                    st.error(str(exc))
                else:
                    st.session_state[
                        "franchise_game_preview"
                    ] = preview
                    st.session_state[
                        "franchise_game_preview_request"
                    ] = {
                        "game_id": (
                            current_game.game_id
                        ),
                        "sit_ids": tuple(
                            sit_ids
                        ),
                        "fingerprint": (
                            regular_season_state_fingerprint(
                                state
                            )
                        ),
                    }
                    st.rerun()

            if quick_commit_clicked:
                try:
                    updated, committed = (
                        commit_game_transactionally(
                            state,
                            current_game.game_id,
                            sit_player_ids=(
                                tuple(sit_ids)
                            ),
                        )
                    )
                    set_franchise_state(
                        updated
                    )
                except (
                    FranchiseCommandCenterError,
                    SingleGameSimulationError,
                    SimulationLeagueStateError,
                ) as exc:
                    st.error(str(exc))
                else:
                    clear_game_day_preview()
                    next_games = (
                        upcoming_controlled_games(
                            updated,
                            controlled_teams,
                        )
                    )
                    if next_games:
                        set_selected_game(
                            next_games[0]
                            .game_id
                        )
                    st.session_state[
                        "franchise_notice"
                    ] = (
                        f"Committed "
                        f"{committed.game.away_team} "
                        f"{committed.game.away_score}, "
                        f"{committed.game.home_team} "
                        f"{committed.game.home_score}. "
                        "Loaded the next controlled game."
                    )
                    st.rerun()

            preview = st.session_state.get(
                "franchise_game_preview"
            )
            preview_request = (
                st.session_state.get(
                    "franchise_game_preview_request"
                )
            )

            if (
                preview is not None
                and isinstance(
                    preview_request,
                    dict,
                )
                and preview_request.get(
                    "game_id"
                )
                == current_game.game_id
                and preview_request.get(
                    "fingerprint"
                )
                == regular_season_state_fingerprint(
                    state
                )
            ):
                completed = preview.game
                score_columns = st.columns(
                    [1, 1, 1]
                )
                score_columns[0].metric(
                    completed.away_team,
                    completed.away_score,
                )
                score_columns[1].metric(
                    "OT",
                    completed.overtime_periods,
                )
                score_columns[2].metric(
                    completed.home_team,
                    completed.home_score,
                )
                st.dataframe(
                    box_score_dataframe(
                        state,
                        completed,
                    ),
                    hide_index=True,
                    width="stretch",
                )

                if st.button(
                    "Commit previewed result",
                    type="primary",
                    disabled=trade_sync_required,
                ):
                    try:
                        updated, committed = (
                            commit_game_transactionally(
                                state,
                                current_game.game_id,
                                seed=(
                                    preview.metadata
                                    .seed
                                ),
                                sit_player_ids=(
                                    tuple(
                                        preview_request[
                                            "sit_ids"
                                        ]
                                    )
                                ),
                            )
                        )
                        set_franchise_state(
                            updated
                        )
                    except (
                        FranchiseCommandCenterError,
                        SingleGameSimulationError,
                        SimulationLeagueStateError,
                    ) as exc:
                        st.error(str(exc))
                    else:
                        clear_game_day_preview()
                        next_games = (
                            upcoming_controlled_games(
                                updated,
                                controlled_teams,
                            )
                        )
                        if next_games:
                            set_selected_game(
                                next_games[0]
                                .game_id
                            )
                        st.session_state[
                            "franchise_notice"
                        ] = (
                            "Committed the previewed "
                            "result and loaded the next "
                            "controlled game."
                        )
                        st.rerun()

with tabs[4]:
    standings_tabs = st.tabs(
        [
            "Eastern Conference",
            "Western Conference",
            "League",
            "Player Leaders",
        ]
    )

    with standings_tabs[0]:
        st.dataframe(
            pd.DataFrame(
                standings_rows(
                    state,
                    conference="East",
                )
            ),
            hide_index=True,
            width="stretch",
        )

    with standings_tabs[1]:
        st.dataframe(
            pd.DataFrame(
                standings_rows(
                    state,
                    conference="West",
                )
            ),
            hide_index=True,
            width="stretch",
        )

    with standings_tabs[2]:
        st.dataframe(
            pd.DataFrame(
                standings_rows(
                    state
                )
            ),
            hide_index=True,
            width="stretch",
        )

    with standings_tabs[3]:
        st.dataframe(
            pd.DataFrame(
                player_leader_rows(
                    state,
                    minimum_games=max(
                        1,
                        int(
                            max(
                                standing.games_played
                                for standing
                                in state.standings.values()
                            )
                            * 0.50
                        ),
                    ),
                    limit=50,
                )
            ),
            hide_index=True,
            width="stretch",
        )

with tabs[5]:
    st.subheader(
        f"{team_name(active_team)} trade profile"
    )
    st.caption(
        "This first version identifies roster "
        "weaknesses. Recommended trade packages "
        "will connect this profile to the existing "
        "Trade Machine in the next trade-AI slice."
    )
    st.dataframe(
        pd.DataFrame(
            team_needs_rows(
                state,
                active_team,
            )
        ),
        hide_index=True,
        width="stretch",
    )
    roster_assets = pd.DataFrame(
        [
            {
                "Player": (
                    state.players[
                        player_id
                    ].player_name
                ),
                "Pos": (
                    state.players[
                        player_id
                    ].position
                ),
                "Age": (
                    state.players[
                        player_id
                    ].age
                ),
                "OVR": round(
                    state.players[
                        player_id
                    ].overall_rating,
                    1,
                ),
                "Potential": (
                    state.players[
                        player_id
                    ].potential_rating
                ),
                "Outlook": (
                    state.players[
                        player_id
                    ].development_direction
                ),
            }
            for player_id
            in state.teams[
                active_team
            ].roster_player_ids
        ]
    ).sort_values(
        "OVR",
        ascending=False,
    )
    st.dataframe(
        roster_assets,
        hide_index=True,
        width="stretch",
    )
    st.page_link(
        "pages/3_Trade_Machine.py",
        label="Open Trade Machine",
        icon="🔁",
    )

with tabs[6]:
    league_metrics = st.columns(5)
    progress = regular_season_progress(
        state
    )
    postseason = get_postseason_state(
        state,
        required=False,
    )
    postseason_completed = (
        len(
            postseason.completed_games
        )
        if postseason is not None
        else 0
    )
    postseason_stage = (
        postseason.stage.value.replace(
            "_",
            " ",
        ).title()
        if postseason is not None
        else "Not Started"
    )

    league_metrics[0].metric(
        "Season",
        state.settings.season_label,
    )
    league_metrics[1].metric(
        "Phase",
        state.phase.value.replace(
            "_",
            " ",
        ).title(),
    )
    league_metrics[2].metric(
        "Regular Season",
        (
            f"{progress['completed_games']}/"
            f"{LEAGUE_GAME_COUNT}"
        ),
    )
    league_metrics[3].metric(
        "Postseason Games",
        postseason_completed,
    )
    league_metrics[4].metric(
        "Archived",
        len(
            state.season_history
        ),
    )

    st.markdown("## NBA Postseason")

    if not regular_season_is_complete(
        state
    ):
        st.info(
            "Complete all 1,230 regular-season games "
            "before generating the play-in tournament "
            "and playoff bracket."
        )
    elif postseason is None:
        st.success(
            "The regular season is complete. The final "
            "conference standings are ready to seed the "
            "NBA Play-In Tournament and playoffs."
        )

        if st.button(
            "Create play-in and playoff bracket",
            type="primary",
            key="franchise_create_postseason",
        ):
            try:
                updated_state = copy.deepcopy(
                    state
                )
                initialize_postseason(
                    updated_state
                )
                validate_simulation_league_state(
                    updated_state
                )
                set_franchise_state(
                    updated_state
                )
            except (
                SimulationPostseasonError,
                SimulationLeagueStateError,
            ) as exc:
                st.error(str(exc))
            else:
                st.session_state[
                    "franchise_notice"
                ] = (
                    "Created the NBA Play-In Tournament "
                    "and playoff bracket from the final "
                    "regular-season standings."
                )
                st.rerun()
    else:
        postseason_metrics = st.columns(4)
        postseason_metrics[0].metric(
            "Postseason Stage",
            postseason_stage,
        )
        postseason_metrics[1].metric(
            "Games Completed",
            len(
                postseason.completed_games
            ),
        )
        postseason_metrics[2].metric(
            "Series Created",
            len(
                postseason.series
            ),
        )
        postseason_metrics[3].metric(
            "Champion",
            (
                team_name(
                    postseason.champion
                )
                if postseason.champion
                else "TBD"
            ),
        )

        seed_tabs = st.tabs(
            [
                "Eastern Seeds",
                "Western Seeds",
                "Bracket",
                "Postseason Leaders",
                "Game Log",
            ]
        )

        with seed_tabs[0]:
            st.dataframe(
                pd.DataFrame(
                    postseason_seed_rows(
                        state,
                        "East",
                    )
                ),
                hide_index=True,
                width="stretch",
            )

        with seed_tabs[1]:
            st.dataframe(
                pd.DataFrame(
                    postseason_seed_rows(
                        state,
                        "West",
                    )
                ),
                hide_index=True,
                width="stretch",
            )

        with seed_tabs[2]:
            bracket_rows = (
                postseason_series_rows(
                    state
                )
            )

            if bracket_rows:
                st.dataframe(
                    pd.DataFrame(
                        bracket_rows
                    ),
                    hide_index=True,
                    width="stretch",
                )
            else:
                opening_rows = [
                    {
                        "Stage": (
                            game.round_label
                        ),
                        "Conference": (
                            game.conference
                        ),
                        "Away": (
                            game.away_team
                        ),
                        "Home": (
                            game.home_team
                        ),
                        "Status": (
                            game.status.value
                        ),
                        "Winner": (
                            game.winner
                        ),
                    }
                    for game
                    in postseason.games.values()
                ]
                st.dataframe(
                    pd.DataFrame(
                        opening_rows
                    ),
                    hide_index=True,
                    width="stretch",
                )

        with seed_tabs[3]:
            leader_rows = (
                postseason_player_rows(
                    state,
                    minimum_games=1,
                    limit=50,
                )
            )

            if leader_rows:
                st.dataframe(
                    pd.DataFrame(
                        leader_rows
                    ),
                    hide_index=True,
                    width="stretch",
                )
            else:
                st.info(
                    "Postseason player statistics "
                    "will appear after the first game."
                )

        with seed_tabs[4]:
            render_postseason_game_history(
                state,
                key_prefix="league_offseason",
                controlled_teams=(
                    controlled_teams
                ),
                default_to_controlled=False,
            )

        if (
            postseason.stage
            == PostseasonStage.COMPLETE
        ):
            champion_columns = st.columns(
                [1, 3, 1]
            )

            with champion_columns[1]:
                st.image(
                    team_logo_url(
                        postseason.champion
                    ),
                    width=130,
                )
                st.markdown(
                    "<h2 style='text-align:center;'>"
                    f"{html.escape(team_name(postseason.champion))}"
                    " are NBA Champions</h2>",
                    unsafe_allow_html=True,
                )
                st.markdown(
                    "<p style='text-align:center;color:#94a3b8;'>"
                    f"Defeated {html.escape(team_name(postseason.runner_up))} "
                    "in the NBA Finals."
                    "</p>",
                    unsafe_allow_html=True,
                )

            st.success(
                "The postseason is complete. The league "
                "is ready for the offseason, draft lottery, "
                "procedural draft class, and player movement "
                "systems in the next franchise slice."
            )
        else:
            next_game = next_postseason_game(
                state
            )

            if next_game is not None:
                st.markdown(
                    postseason_matchup_html(
                        next_game.home_team,
                        next_game.away_team,
                        round_label=(
                            next_game.round_label
                        ),
                        game_number=(
                            next_game.game_number
                        ),
                    ),
                    unsafe_allow_html=True,
                )
                next_game_key = (
                    "franchise_postseason_preview"
                )
                preview = st.session_state.get(
                    next_game_key
                )

                if (
                    preview is not None
                    and getattr(
                        preview.metadata,
                        "game_id",
                        "",
                    )
                    != next_game.game_id
                ):
                    st.session_state.pop(
                        next_game_key,
                        None,
                    )
                    preview = None

                game_actions = st.columns(
                    [1, 1, 1, 1]
                )
                preview_clicked = (
                    game_actions[0].button(
                        "Preview next game",
                        width="stretch",
                        key=(
                            "franchise_preview_"
                            "postseason_game"
                        ),
                    )
                )
                commit_clicked = (
                    game_actions[1].button(
                        "Quick sim & commit",
                        type="primary",
                        width="stretch",
                        key=(
                            "franchise_commit_"
                            "postseason_game"
                        ),
                    )
                )
                stage_clicked = (
                    game_actions[2].button(
                        "Sim current stage",
                        width="stretch",
                        key=(
                            "franchise_sim_"
                            "postseason_stage"
                        ),
                    )
                )
                champion_clicked = (
                    game_actions[3].button(
                        "Sim to champion",
                        width="stretch",
                        key=(
                            "franchise_sim_"
                            "postseason_finish"
                        ),
                    )
                )

                if preview_clicked:
                    try:
                        preview = (
                            simulate_postseason_game(
                                state,
                                next_game.game_id,
                            )
                        )
                    except (
                        SimulationPostseasonError,
                        SingleGameSimulationError,
                    ) as exc:
                        st.error(str(exc))
                    else:
                        st.session_state[
                            next_game_key
                        ] = preview

                if commit_clicked:
                    try:
                        (
                            updated_state,
                            simulated,
                        ) = (
                            commit_postseason_game(
                                state,
                                next_game.game_id,
                            )
                        )
                        set_franchise_state(
                            updated_state
                        )
                    except (
                        SimulationPostseasonError,
                        SingleGameSimulationError,
                        SimulationLeagueStateError,
                    ) as exc:
                        st.error(str(exc))
                    else:
                        st.session_state.pop(
                            next_game_key,
                            None,
                        )
                        st.session_state[
                            "franchise_notice"
                        ] = (
                            f"Committed {next_game.round_label} "
                            f"Game {next_game.game_number}: "
                            f"{simulated.game.away_team} "
                            f"{simulated.game.away_score}, "
                            f"{simulated.game.home_team} "
                            f"{simulated.game.home_score}."
                        )
                        st.rerun()

                if stage_clicked or champion_clicked:
                    scope = (
                        PostseasonSimulationScope
                        .CURRENT_STAGE
                        if stage_clicked
                        else (
                            PostseasonSimulationScope
                            .TO_CHAMPION
                        )
                    )

                    try:
                        (
                            updated_state,
                            advance_result,
                        ) = (
                            advance_postseason_with_progress(
                                state,
                                scope=scope,
                                controlled_teams=(
                                    controlled_teams
                                ),
                                policy=(
                                    FranchiseSimulationPolicy(
                                        policy
                                    )
                                ),
                                label=(
                                    "Simulating postseason "
                                    "games..."
                                ),
                            )
                        )
                        set_franchise_state(
                            updated_state
                        )
                    except (
                        SimulationPostseasonError,
                        SingleGameSimulationError,
                        SimulationLeagueStateError,
                    ) as exc:
                        st.error(str(exc))
                    else:
                        st.session_state.pop(
                            next_game_key,
                            None,
                        )
                        if (
                            advance_result
                            .paused_before_game_id
                        ):
                            message = (
                                f"Simulated "
                                f"{advance_result.games_simulated} "
                                "postseason game(s), then paused "
                                "before the next controlled-team "
                                "decision."
                            )
                        elif (
                            advance_result.champion
                        ):
                            message = (
                                f"Postseason complete. "
                                f"{team_name(advance_result.champion)} "
                                "won the NBA championship."
                            )
                        else:
                            message = (
                                f"Simulated "
                                f"{advance_result.games_simulated} "
                                "postseason game(s)."
                            )

                        st.session_state[
                            "franchise_notice"
                        ] = message
                        st.rerun()

                preview = st.session_state.get(
                    next_game_key
                )

                if preview is not None:
                    completed = preview.game
                    st.markdown("### Preview Result")
                    score_columns = st.columns(
                        [2, 1, 2]
                    )
                    score_columns[0].metric(
                        completed.away_team,
                        completed.away_score,
                    )
                    score_columns[1].markdown(
                        "<h3 style='text-align:center;'>FINAL</h3>",
                        unsafe_allow_html=True,
                    )
                    score_columns[2].metric(
                        completed.home_team,
                        completed.home_score,
                    )
                    st.dataframe(
                        box_score_dataframe(
                            state,
                            completed,
                        ),
                        hide_index=True,
                        width="stretch",
                    )

                    if st.button(
                        "Commit previewed postseason result",
                        type="primary",
                        key=(
                            "franchise_commit_previewed_"
                            "postseason_game"
                        ),
                    ):
                        try:
                            (
                                updated_state,
                                _,
                            ) = (
                                commit_postseason_game(
                                    state,
                                    next_game.game_id,
                                    seed=(
                                        preview.metadata.seed
                                    ),
                                )
                            )
                            set_franchise_state(
                                updated_state
                            )
                        except (
                            SimulationPostseasonError,
                            SingleGameSimulationError,
                            SimulationLeagueStateError,
                        ) as exc:
                            st.error(str(exc))
                        else:
                            st.session_state.pop(
                                next_game_key,
                                None,
                            )
                            st.session_state[
                                "franchise_notice"
                            ] = (
                                "Committed the exact "
                                "previewed postseason result."
                            )
                            st.rerun()

    st.divider()
    st.markdown("## Offseason Setup")

    draft_pref_key = (
        "franchise_pref_draft_class_strength"
    )
    draft_widget_key = (
        "_franchise_draft_class_strength_widget"
    )
    initialize_persistent_widget(
        st.session_state,
        persistent_key=draft_pref_key,
        widget_key=draft_widget_key,
        default=5,
    )
    draft_strength = st.slider(
        "Generated draft-class strength",
        min_value=1,
        max_value=10,
        help=(
            "This will control elite talent, "
            "depth, sleepers, bust risk, and "
            "generational prospect probability."
        ),
        key=draft_widget_key,
        on_change=persist_franchise_widget,
        args=(
            draft_widget_key,
            draft_pref_key,
        ),
    )
    st.info(
        f"Draft class strength {draft_strength}/10 "
        "is saved for the upcoming procedural "
        "draft-class engine."
    )
    roadmap = pd.DataFrame(
        [
            {
                "System": "Play-in and playoffs",
                "Status": (
                    "Active"
                    if postseason is not None
                    else (
                        "Ready after regular season"
                    )
                ),
            },
            {
                "System": "Draft lottery",
                "Status": (
                    "Next offseason slice"
                ),
            },
            {
                "System": "Procedural draft class",
                "Status": (
                    f"Strength setting saved: "
                    f"{draft_strength}/10"
                ),
            },
            {
                "System": "Contracts and free agency",
                "Status": (
                    "Permanent contract state "
                    "already available"
                ),
            },
            {
                "System": "Fatigue and injuries",
                "Status": (
                    "Planned after postseason "
                    "stabilization"
                ),
            },
        ]
    )
    st.dataframe(
        roadmap,
        hide_index=True,
        width="stretch",
    )

st.caption(
    f"{COMMAND_CENTER_VERSION} · "
    f"{BOOTSTRAP_VERSION} · "
    f"{CROSS_PAGE_STATE_VERSION} · "
    f"{ALIGNMENT_VERSION} · "
    f"{TRADE_SYNC_VERSION} · "
    f"{ENGINE_VERSION} · "
    f"{MINUTES_MODEL_VERSION} · "
    f"{POSTSEASON_VERSION} · "
    f"{CHECKPOINT_VERSION} · "
    f"{CHECKPOINT_IMPLEMENTATION_VERSION}"
)
