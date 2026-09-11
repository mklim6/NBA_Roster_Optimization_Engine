from __future__ import annotations







import copy



import html



import importlib



import json



import statistics



import sys



import time



from pathlib import Path



from typing import Any







import pandas as pd



import streamlit as st



_franchise_page_started_at_v1_6 = time.perf_counter()
_franchise_perf_v1_6: dict[str, float] = {}







# FRANCHISE EARLY LOADING EXPERIENCE V2.1



st.set_page_config(



    page_title="NBA Franchise Mode",



    page_icon="🏆",



    layout="wide",



)



_franchise_loading_message = st.empty()



_franchise_loading_message.info(



    "🏀 Loading Franchise Mode... restoring your league, rosters, Draft state, and front-office systems."



)



_franchise_loading_progress = st.progress(



    10,



    text="Starting franchise engine...",



)















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



import simulation_module_bootstrap_v1 as _simulation_bootstrap  # noqa: E402


# FRANCHISE PERFORMANCE V1.6
# Ordinary Streamlit reruns should not purge/reload the full simulation
# dependency chain. Repair it only after one of the relevant source files
# actually changes.
def _franchise_module_source_signature_v1_6() -> tuple[tuple[str, int, int], ...]:
    names = (
        "simulation_module_bootstrap_v1.py",
        "simulation_league_state_v1.py",
        "simulation_cross_page_state_v1.py",
        "simulation_franchise_checkpoint_v1.py",
        "franchise_command_center_v1.py",
        "franchise_calendar_v1.py",
        "franchise_staff_system_v1.py",
        "franchise_staff_ui_v1.py",
        "simulation_trade_sync_v1.py",
        "simulation_postseason_v1.py",
        "simulation_league_alignment_v1.py",
        "simulation_player_minutes_v1.py",
        "simulation_injury_fatigue_v1.py",
        "regular_season_simulation_controller_v1.py",
        "regular_season_schedule_v1.py",
        "simulation_season_transition_controller_v1.py",
        "simulation_season_transition_v1.py",
        "single_game_simulator_v1.py",
        "simulation_roster_validator_v1.py",
    )
    result: list[tuple[str, int, int]] = []
    for name in names:
        path = SRC / name
        if not path.is_file():
            continue
        stat = path.stat()
        result.append((name, int(stat.st_mtime_ns), int(stat.st_size)))
    return tuple(result)


_module_signature_v1_6 = _franchise_module_source_signature_v1_6()
_previous_module_signature_v1_6 = st.session_state.get(
    "_franchise_module_source_signature_v1_6"
)
_module_sources_changed_v1_6 = (
    _previous_module_signature_v1_6 is not None
    and _previous_module_signature_v1_6 != _module_signature_v1_6
)

if _module_sources_changed_v1_6:
    importlib.invalidate_caches()
    _simulation_bootstrap = importlib.reload(_simulation_bootstrap)
    _simulation_bootstrap.ensure_current_simulation_modules()

st.session_state["_franchise_module_source_signature_v1_6"] = (
    _module_signature_v1_6
)

BOOTSTRAP_VERSION = _simulation_bootstrap.BOOTSTRAP_VERSION
ensure_current_simulation_modules = (
    _simulation_bootstrap.ensure_current_simulation_modules
)

import simulation_cross_page_state_v1 as _cross_page_state  # noqa: E402

if _module_sources_changed_v1_6:
    _cross_page_state = importlib.reload(_cross_page_state)


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

if _module_sources_changed_v1_6:
    _franchise_checkpoint = importlib.reload(_franchise_checkpoint)


_franchise_perf_v1_6["module_bootstrap"] = time.perf_counter() - _franchise_page_started_at_v1_6



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



    POSTSEASON_EXECUTION_VERSION,



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



    postseason_team_rows,



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



from simulation_injury_fatigue_v1 import (  # noqa: E402



    HEALTH_PERSISTENCE_REPAIR_VERSION,



    HEALTH_WORKLOAD_REBUILD_MARKER_ATTRIBUTE,



    INJURY_FATIGUE_VERSION,



    ensure_injury_fatigue_state,



    health_events,



    league_injury_summary,



    player_health_report_rows,



    recommended_rest_player_ids,



    team_health_summary,



)



from simulation_medical_injury_v2 import (  # noqa: E402



    MEDICAL_INJURY_V2_VERSION,



)



from league_health_audit_v1 import (  # noqa: E402



    LEAGUE_HEALTH_AUDIT_VERSION,



    active_injury_rows,



    league_health_audit,



    team_health_rows,



)



from franchise_health_realism_export_v1 import (  # noqa: E402



    HEALTH_REALISM_EXPORT_VERSION,



    injury_event_history_rows,



    player_availability_audit_rows,



    rows_to_csv_bytes,



)



from franchise_league_events_v1 import (  # noqa: E402



    EVENT_SYNC_MARKER_ATTRIBUTE,



    FRANCHISE_EVENT_VERSION,



    blocking_events,



    event_inbox_rows,



    event_settings,



    franchise_events,



    mark_event_read,



    resolve_all_nonblocking,



    resolve_event,



    synchronize_franchise_events,



    unread_events,



    update_event_settings,



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



from franchise_player_stats_v1 import (  # noqa: E402



    FRANCHISE_PLAYER_STATS_VERSION,



    regular_season_player_rows,



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



from career_lifecycle_transition_adapter_v1 import (  # noqa: E402



    CONTROLLER_VERSION as SEASON_TRANSITION_CONTROLLER_VERSION,



    SimulationSeasonTransitionControllerError,



    build_season_transition_preview,



    commit_season_transition_preview,



    incomplete_scheduled_game_ids,



    preview_matches_state,



)



from franchise_career_lifecycle_ui_v1 import (  # noqa: E402


    render_career_lifecycle_preview,


    render_career_lifecycle_season_open,


)


from franchise_full_reset_ui_v1 import (  # noqa: E402

    render_full_franchise_reset,

)

from franchise_live_start_ui_v1 import (  # noqa: E402

    render_live_franchise_start,

)

from franchise_live_asset_ledger_ui_v1 import (  # noqa: E402
    render_live_asset_ledger,
)
from franchise_cpu_front_office_ui_v1 import (  # noqa: E402
    CPU_FRONT_OFFICE_UI_VERSION,
    render_cpu_front_office_v1,
)
from franchise_staff_system_v1 import (  # noqa: E402
    ensure_franchise_staff_state,
)
from franchise_staff_ui_v1 import (  # noqa: E402
    render_franchise_staff_center_v1,
)
from simulation_league_state_v1 import (  # noqa: E402



    MINUTES_MODEL_VERSION,



    SIMULATION_STATE_VERSION,



    GameStatus,



    LeaguePhase,



    SeasonArchive,



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



# AWARDS V3.2 EXACT-SRC RUNTIME WIRING



import importlib as _awards_v31_importlib



import sys as _awards_v31_sys



from pathlib import Path as _AwardsV31Path







_awards_v31_src = str((



    _AwardsV31Path(__file__).resolve().parents[1]



    / "src"



).resolve())



if _awards_v31_src in _awards_v31_sys.path:



    _awards_v31_sys.path.remove(_awards_v31_src)



_awards_v31_sys.path.insert(0, _awards_v31_src)







for _awards_v31_name in (



    "simulation_career_awards_v2",



    "franchise_generated_player_portraits_v1",



):



    _awards_v31_sys.modules.pop(



        _awards_v31_name,



        None,



    )







_awards_v31_runtime = (



    _awards_v31_importlib.import_module(



        "simulation_career_awards_v2"



    )



)



if getattr(



    _awards_v31_runtime,



    "CAREER_AWARDS_VERSION",



    "",



) != "simulation-career-awards-v3.2-2026-08-11":



    raise ImportError(



        "Franchise Mode loaded the wrong Awards engine. "



        "Loaded version: "



        + str(



            getattr(



                _awards_v31_runtime,



                "CAREER_AWARDS_VERSION",



                "unknown",



            )



        )



    )







CAREER_AWARDS_VERSION = getattr(



    _awards_v31_runtime,



    "CAREER_AWARDS_VERSION",



)



career_metadata_summary = getattr(



    _awards_v31_runtime,



    "career_metadata_summary",



)



ensure_career_metadata = getattr(



    _awards_v31_runtime,



    "ensure_career_metadata",



)



inject_career_awards_styles = getattr(



    _awards_v31_runtime,



    "inject_career_awards_styles",



)



render_awards_showcase_v2 = getattr(



    _awards_v31_runtime,



    "render_awards_showcase_v2",



)



render_championship_ceremony_v2 = getattr(



    _awards_v31_runtime,



    "render_championship_ceremony_v2",



)



render_playoff_honors_v2 = getattr(



    _awards_v31_runtime,



    "render_playoff_honors_v2",



)



# END AWARDS V3.2 EXACT-SRC RUNTIME WIRING



from franchise_draft_engine_v1 import (  # noqa: E402



    DRAFT_ENGINE_VERSION,



    activate_drafted_rookies_after_transition,



    draft_is_complete,



    draft_state,



    expected_draft_pick_count,



    initialize_draft_state,



)



from franchise_draft_ui_v1 import (  # noqa: E402



    DRAFT_UI_VERSION,



    render_draft_room_v1,



)











EXPECTED_REALISM_ENGINE_VERSION = (



    "single-game-simulator-v1.6-2026-08-08"



)



FRANCHISE_OFFSEASON_INTEGRATION_VERSION = (



    "franchise-offseason-transition-v1-2026-08-09"



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
    home_name = html.escape(team_name(home_team))
    away_name = html.escape(team_name(away_team))
    home_logo = html.escape(team_logo_url(home_team))
    away_logo = html.escape(team_logo_url(away_team))
    label = html.escape(round_label)

    # Keep the markup contiguous. Blank lines inside a raw HTML block can
    # cause Markdown to terminate the block and display CSS as code.
    return (
        '<div class="fm-postseason-matchup">'
        f'<div class="fm-matchup-label">{label} · Game {game_number}</div>'
        '<div class="fm-matchup-grid">'
        '<div class="fm-matchup-team">'
        f'<img src="{away_logo}" alt="{away_name}">'
        f'<div class="fm-matchup-name">{away_name}</div>'
        '<div class="fm-matchup-side">Away</div>'
        '</div>'
        '<div class="fm-matchup-at">AT</div>'
        '<div class="fm-matchup-team">'
        f'<img src="{home_logo}" alt="{home_name}">'
        f'<div class="fm-matchup-name">{home_name}</div>'
        '<div class="fm-matchup-side">Home</div>'
        '</div>'
        '</div>'
        '</div>'
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



    "franchise_active_section",



)












FRANCHISE_UI_PREFERENCES_VERSION_V1_6 = (
    "franchise-ui-preferences-v1.6-2026-08-12"
)
FRANCHISE_UI_PREFERENCES_PATH_V1_6 = (
    ROOT / "outputs" / "runtime" / "franchise_ui_preferences_v1.json"
)


def _load_franchise_ui_preferences_v1_6() -> None:
    if st.session_state.get("_franchise_ui_preferences_loaded_v1_6"):
        return
    st.session_state["_franchise_ui_preferences_loaded_v1_6"] = True
    path = FRANCHISE_UI_PREFERENCES_PATH_V1_6
    if not path.is_file():
        return
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return
    values = payload.get("preferences", payload) if isinstance(payload, dict) else {}
    if not isinstance(values, dict):
        return
    for key in FRANCHISE_CHECKPOINT_PREFERENCE_KEYS:
        if key in values:
            st.session_state[key] = copy.deepcopy(values[key])


def _save_franchise_ui_preferences_v1_6() -> None:
    path = FRANCHISE_UI_PREFERENCES_PATH_V1_6
    payload = {
        "version": FRANCHISE_UI_PREFERENCES_VERSION_V1_6,
        "preferences": {
            key: copy.deepcopy(st.session_state[key])
            for key in FRANCHISE_CHECKPOINT_PREFERENCE_KEYS
            if key in st.session_state
        },
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(payload, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        temporary.replace(path)
    except OSError as exc:
        st.session_state["franchise_ui_preference_warning_v1_6"] = str(exc)


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



            "franchise_trade_league_state"



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











# FRANCHISE_SIMULATION_SESSION_ISOLATION_V1
# Franchise Mode owns this live simulation session state. Standalone Game Simulator has a separate sandbox session.
def restore_franchise_checkpoint() -> bool:



    if (



        "franchise_simulation_league_state"



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



        "franchise_simulation_league_state"



    ] = simulation_state



    st.session_state[



        "franchise_trade_league_state"



    ] = trade_state



    st.session_state[



        "franchise_position_signature"



    ] = current_position_signature()


    # This checkpoint was successfully decoded by the current writer. Do not
    # rewrite the full compressed franchise merely to seed a new session key.
    st.session_state[
        "franchise_checkpoint_writer_implementation"
    ] = CHECKPOINT_IMPLEMENTATION_VERSION

    # A health reconstruction marker already stored in the restored checkpoint
    # is already durable. Seed its session marker before the health ensure pass.
    restored_health_marker_v1_6 = getattr(
        simulation_state,
        HEALTH_WORKLOAD_REBUILD_MARKER_ATTRIBUTE,
        None,
    )
    if restored_health_marker_v1_6 is not None:
        st.session_state[
            "franchise_health_rebuild_saved_marker"
        ] = restored_health_marker_v1_6

    restored_event_sync_marker_v1_7 = getattr(
        simulation_state,
        EVENT_SYNC_MARKER_ATTRIBUTE,
        None,
    )
    if restored_event_sync_marker_v1_7 is not None:
        st.session_state[
            "franchise_event_sync_saved_marker"
        ] = restored_event_sync_marker_v1_7







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



) -> tuple[SimulationLeagueState, Any]:



    max_games = {



        PostseasonSimulationScope.NEXT_CONTROLLED_GAME: 12,



        PostseasonSimulationScope.CURRENT_STAGE: 20,



        PostseasonSimulationScope.TO_CHAMPION: 140,



        PostseasonSimulationScope.NEXT_GAME: 1,



    }[scope]



    started_at = time.perf_counter()



    initial_completed = len(



        get_postseason_state(state).completed_games



    )



    estimated_total = {



        PostseasonSimulationScope.NEXT_CONTROLLED_GAME: 12,



        PostseasonSimulationScope.CURRENT_STAGE: 20,



        PostseasonSimulationScope.TO_CHAMPION: max(



            1,



            min(110 - initial_completed, 100),



        ),



        PostseasonSimulationScope.NEXT_GAME: 1,



    }[scope]



    last_checkpoint_stage = {



        "value": get_postseason_state(state).stage



    }







    with st.status(label, expanded=True) as progress_status:



        def checkpoint_progress(



            progress_state: SimulationLeagueState,



            count: int,



            game: Any,



        ) -> None:



            st.session_state[



                "franchise_simulation_league_state"



            ] = progress_state



            elapsed = max(



                time.perf_counter() - started_at,



                0.001,



            )



            rate = count / elapsed



            estimated_remaining = max(



                0,



                estimated_total - count,



            )



            eta = estimated_remaining / max(rate, 0.001)



            current_stage = get_postseason_state(



                progress_state



            ).stage



            progress_status.update(



                label=(



                    f"Simulated {count} CPU postseason game(s). "



                    f"Latest: {game.round_label} Game {game.game_number}. "



                    f"Elapsed {elapsed:.1f}s · {rate:.1f} games/s · "



                    f"ETA ~{eta:.0f}s."



                ),



                state="running",



                expanded=True,



            )







            # Durable writes occur at round boundaries instead of every three



            # games. This preserves recovery points without serializing the



            # complete franchise state dozens of times per postseason.



            if current_stage != last_checkpoint_stage["value"]:



                save_current_franchise_checkpoint(



                    progress_state,



                    reason=(



                        "postseason-round-boundary-"



                        f"{current_stage.value}"



                    ),



                    copy_payload=False,



                )



                last_checkpoint_stage["value"] = current_stage







        try:



            updated_state, result = advance_postseason(



                state,



                scope=scope,



                controlled_teams=controlled_teams,



                policy=policy,



                max_games=max_games,



                progress_callback=checkpoint_progress,



            )



        except Exception:



            progress_status.update(



                label=(



                    "Postseason advancement stopped because of an error. "



                    "The most recent round-boundary checkpoint remains available."



                ),



                state="error",



                expanded=True,



            )



            raise







        elapsed = time.perf_counter() - started_at



        st.session_state[



            "franchise_simulation_league_state"



        ] = updated_state



        save_current_franchise_checkpoint(



            updated_state,



            reason="postseason-advance-complete",



            copy_payload=False,



        )



        progress_status.update(



            label=(



                f"Postseason advancement finished after "



                f"{result.games_simulated} game(s) in {elapsed:.1f}s "



                f"using {POSTSEASON_EXECUTION_VERSION}."



            ),



            state="complete",



            expanded=False,



        )







    return updated_state, result











def get_trade_state(
    runtime: RuntimeData,
) -> LeagueState:
    key = "franchise_trade_league_state"
    state = st.session_state.get(key)

    if trade_state_is_compatible(
        state,
        expected_state_version=STATE_VERSION,
    ):
        return state

    checkpoint = None
    try:
        checkpoint = load_franchise_checkpoint(
            allow_backup=False,
        )
    except TypeError:
        try:
            checkpoint = load_franchise_checkpoint()
        except Exception:
            checkpoint = None
    except Exception:
        checkpoint = None

    durable_trade_state = (
        getattr(checkpoint, "trade_state", None)
        if checkpoint is not None
        else None
    )
    if trade_state_is_compatible(
        durable_trade_state,
        expected_state_version=STATE_VERSION,
    ):
        state = copy.deepcopy(durable_trade_state)
    else:
        state = create_league_state(runtime)

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



        "franchise_simulation_league_state"



    ] = state



    st.session_state[



        "franchise_position_signature"



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



    key = "franchise_simulation_league_state"



    state = st.session_state.get(key)



    structurally_current = (



        simulation_state_is_compatible(



            state,



            expected_state_version=(



                SIMULATION_STATE_VERSION



            ),



        )



        and st.session_state.get(



            "franchise_position_signature"



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



    # FRANCHISE_TRADE_AUTHORITY_V1:
    # The live franchise trade state is checkpoint-owned and separate from the
    # standalone 2026-27 Trade Machine sandbox. No cross-page roster sync is
    # required or permitted.
    st.session_state["game_simulator_trade_sync_required"] = False
    st.session_state.pop("game_simulator_trade_source_status", None)
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

    # UI-only preference changes no longer serialize and gzip the full
    # franchise state. Real state mutations still use the authoritative
    # durable checkpoint path.
    _save_franchise_ui_preferences_v1_6()




def clear_game_day_preview() -> None:



    for key in {



        "franchise_game_preview",



        "franchise_game_preview_request",



    }:



        st.session_state.pop(



            key,



            None,



        )











FRANCHISE_SECTION_KEY = "franchise_active_section"



FRANCHISE_SECTIONS = (



    "Command Center",



    "Inbox & League Health",



    "Calendar",



    "Team Management",



    "Staff",



    "Free Agency",



    "Game Day",



    "Stats & Standings",



    "Trade Center",



    "Draft Room",



    "League & Offseason",



)



FRANCHISE_SECTION_GUIDE = {



    "Command Center": (



        "Command deck",



        "Your record, next matchup, health pulse, recent form, and the fastest path to the next meaningful franchise action.",



        "#2e90fa",



    ),



    "Inbox & League Health": (



        "Medical & workload center",



        "Review injuries, fatigue, availability, league-health diagnostics, and the realism exports used to audit the medical engine.",



        "#f63d68",



    ),



    "Calendar": (



        "Road through the season",



        "Browse the calendar, home and road stretches, rest patterns, results, and the next matchup you want to manage.",



        "#12b76a",



    ),



    "Team Management": (



        "Rotation & availability",



        "Build the rotation, assign minutes, monitor availability, and see the players who define your franchise identity.",



        "#f79009",



    ),



    "Staff": (



        "Coaching & organization",



        "Review the persistent coaching, development, scouting, and medical staff shaping your franchise behind the scenes.",



        "#6172f3",



    ),



    "Free Agency": (



        "Offseason marketplace",



        "Negotiate with the live franchise free-agent market, manage rights and qualifying offers, advance the offseason calendar, and finalize signings without leaving Franchise Mode.",



        "#17b26a",



    ),



    "Game Day": (



        "Matchup center",



        "Preview the next game, make optional lineup choices, commit the result, and review the complete box score in one flow.",



        "#f04438",



    ),



    "Stats & Standings": (



        "League results",



        "Compare standings, regular-season leaders, and playoff-only player and team results.",



        "#7f56d9",



    ),



    "Trade Center": (



        "Front office",



        "Build and commit live franchise trades against the evolving roster, contracts, draft capital, and transaction history. The standalone Trade Machine is sandbox-only.",



        "#ee46bc",



    ),



    "Draft Room": (



        "Draft command center",



        "Run the 3-2-1 lottery, scout a generated class, manage a persistent two-minute AI clock, make user selections, and simulate to the next meaningful draft decision.",



        "#f5b301",



    ),



    "League & Offseason": (



        "NBA universe",



        "Inspect postseason structure, league archives, trophy races, awards night, development, and deeper long-term tools. Normal progression no longer requires this section.",



        "#06aed4",



    ),



}











def set_franchise_section(section: str) -> None:



    if section in FRANCHISE_SECTIONS:



        # Apply before the navigation widget is created on the next rerun.



        # Streamlit blocks direct mutation of an instantiated widget key.



        st.session_state[



            "franchise_pending_section"



        ] = section











def render_franchise_section_guide(section: str) -> None:



    title, detail, color = FRANCHISE_SECTION_GUIDE[section]



    st.markdown(



        (



            '<div class="fm-route-guide" '



            f'style="border-left-color:{color}">'



            '<div class="fm-route-title">'



            f'{escaped(title)}'



            '</div>'



            '<div class="fm-route-copy">'



            f'{escaped(detail)}'



            '</div>'



            '</div>'



        ),



        unsafe_allow_html=True,



    )











def remember_committed_game_result(game_id: str) -> None:



    st.session_state[



        "franchise_last_committed_game_id"



    ] = str(game_id)



    set_franchise_section("Game Day")











def render_latest_committed_game(



    state: SimulationLeagueState,



) -> None:



    game_id = str(



        st.session_state.get(



            "franchise_last_committed_game_id",



            "",



        )



        or ""



    )



    completed = state.completed_games.get(game_id)



    if completed is None:



        return







    st.markdown("### Latest committed result")



    st.success(



        "This result is already part of the permanent season. "



        "The controls below are for the next matchup."



    )



    score_columns = st.columns([1, 1, 1])



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



    with st.expander(



        "Review final box score",



        expanded=True,



    ):



        st.dataframe(



            box_score_dataframe(



                state,



                completed,



            ),



            hide_index=True,



            width="stretch",



        )



        medical_rows = [



            event



            for event in health_events(state)



            if str(event.get("game_id", "")) == game_id



        ]



        if medical_rows:



            st.warning("Medical events from this game")



            st.dataframe(



                pd.DataFrame(medical_rows),



                hide_index=True,



                width="stretch",



            )











def set_franchise_state(



    state: SimulationLeagueState,



    *,



    checkpoint_reason: str = "franchise-state-commit",



) -> None:



    validate_simulation_league_state(



        state



    )



    st.session_state[



        "franchise_simulation_league_state"



    ] = state



    save_current_franchise_checkpoint(



        state,



        reason=checkpoint_reason,



        copy_payload=False,



    )











FRANCHISE_TRANSITION_PREVIEW_KEY = (



    "franchise_season_transition_preview"



)



FRANCHISE_TRANSITION_ACK_KEY = (



    "franchise_season_transition_acknowledged"



)











def clear_franchise_transition_preview() -> None:



    for key in {



        FRANCHISE_TRANSITION_PREVIEW_KEY,



        FRANCHISE_TRANSITION_ACK_KEY,



    }:



        st.session_state.pop(



            key,



            None,



        )











def archive_champion(



    archive: SeasonArchive,



) -> str:



    direct = str(



        getattr(



            archive,



            "champion",



            "",



        )



        or ""



    )



    if direct:



        return direct







    postseason = getattr(



        archive,



        "postseason_state",



        None,



    )



    return str(



        getattr(



            postseason,



            "champion",



            "",



        )



        or ""



    )











def archive_runner_up(



    archive: SeasonArchive,



) -> str:



    direct = str(



        getattr(



            archive,



            "runner_up",



            "",



        )



        or ""



    )



    if direct:



        return direct







    postseason = getattr(



        archive,



        "postseason_state",



        None,



    )



    return str(



        getattr(



            postseason,



            "runner_up",



            "",



        )



        or ""



    )











def archive_postseason_games(



    archive: SeasonArchive,



) -> int:



    direct = int(



        getattr(



            archive,



            "postseason_games_completed",



            0,



        )



        or 0



    )



    if direct:



        return direct







    postseason = getattr(



        archive,



        "postseason_state",



        None,



    )



    return len(



        getattr(



            postseason,



            "completed_games",



            {},



        )



        or {}



    )











def archived_season_rows(



    state: SimulationLeagueState,



) -> list[dict[str, Any]]:



    rows: list[dict[str, Any]] = []







    for archive in reversed(



        state.season_history



    ):



        development = (



            archive.development_summary



            if isinstance(



                archive.development_summary,



                dict,



            )



            else {}



        )



        champion = archive_champion(



            archive



        )



        runner_up = archive_runner_up(



            archive



        )



        rows.append(



            {



                "Season": archive.season_label,



                "Champion": (



                    team_name(champion)



                    if champion



                    else "Not recorded"



                ),



                "Runner-Up": (



                    team_name(runner_up)



                    if runner_up



                    else "Not recorded"



                ),



                "Regular Games": len(



                    archive.completed_games



                ),



                "Postseason Games": (



                    archive_postseason_games(



                        archive



                    )



                ),



                "Players Developed": int(



                    development.get(



                        "players_projected",



                        0,



                    )



                    or 0



                ),



                "Average OVR Change": float(



                    development.get(



                        "average_overall_delta",



                        0.0,



                    )



                    or 0.0



                ),



                "Advanced To": str(



                    development.get(



                        "target_season",



                        "",



                    )



                    or ""



                ),



            }



        )







    return rows











def archived_standings_rows(



    archive: SeasonArchive,



) -> list[dict[str, Any]]:



    ordered = sorted(



        archive.standings.values(),



        key=lambda standing: (



            -standing.wins,



            -(



                standing.points_for



                - standing.points_against



            ),



            -standing.points_for,



            standing.team_abbreviation,



        ),



    )



    rows: list[dict[str, Any]] = []







    for rank, standing in enumerate(



        ordered,



        start=1,



    ):



        games = max(



            1,



            int(standing.games_played),



        )



        rows.append(



            {



                "Rank": rank,



                "Team": team_name(



                    standing.team_abbreviation



                ),



                "W": standing.wins,



                "L": standing.losses,



                "Win%": round(



                    standing.wins / games,



                    3,



                ),



                "Point Diff": (



                    standing.points_for



                    - standing.points_against



                ),



            }



        )







    return rows











def render_archived_season_history(



    state: SimulationLeagueState,



) -> None:



    if not state.season_history:



        return







    st.markdown("## Archived Season History")



    st.dataframe(



        pd.DataFrame(



            archived_season_rows(state)



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



        state.season_history



    ):



        champion = archive_champion(



            archive



        )



        runner_up = archive_runner_up(



            archive



        )



        label = archive.season_label



        if champion:



            label += (



                " · Champion: "



                + team_name(champion)



            )







        with st.expander(label):



            detail_metrics = st.columns(4)



            detail_metrics[0].metric(



                "Champion",



                (



                    team_name(champion)



                    if champion



                    else "Not recorded"



                ),



            )



            detail_metrics[1].metric(



                "Runner-Up",



                (



                    team_name(runner_up)



                    if runner_up



                    else "Not recorded"



                ),



            )



            detail_metrics[2].metric(



                "Regular Games",



                len(archive.completed_games),



            )



            detail_metrics[3].metric(



                "Postseason Games",



                archive_postseason_games(



                    archive



                ),



            )



            st.dataframe(



                pd.DataFrame(



                    archived_standings_rows(



                        archive



                    )



                ),



                hide_index=True,



                width="stretch",



            )











FRANCHISE_OPENING_REGULAR_SEASON_UI_V1 = (
    "franchise-opening-regular-season-ui-v1-2026-08-17"
)


def render_opening_regular_season_control_v1(
    state: SimulationLeagueState,
) -> None:
    # Render the opening-2026-27 finalization gate without mutating on view.
    phase_name = str(
        getattr(
            getattr(state, "phase", None),
            "value",
            getattr(state, "phase", ""),
        )
        or ""
    ).strip().lower()

    if phase_name != "offseason":
        return
    if int(getattr(state, "transition_count", 0) or 0) != 0:
        return
    if len(getattr(state, "season_history", ()) or ()) != 0:
        return

    from franchise_opening_regular_season_transition_v1 import (
        OpeningRegularSeasonTransitionError,
        commit_opening_regular_season_live,
        preview_opening_regular_season,
    )
    from franchise_free_agency_persistent_calendar_v1 import (
        free_agency_calendar_snapshot,
    )
    from franchise_free_agency_rfa_offer_sheet_v1 import (
        pending_offer_sheets,
    )
    from simulation_franchise_checkpoint_v1 import (
        load_franchise_checkpoint,
    )

    checkpoint = load_franchise_checkpoint(allow_backup=False)
    if checkpoint is None:
        st.error(
            "The durable Franchise checkpoint could not be loaded, so the "
            "regular season cannot be opened."
        )
        return

    durable_state = checkpoint.simulation_state
    durable_trade = checkpoint.trade_state

    try:
        preview = preview_opening_regular_season(
            durable_state,
            durable_trade,
        )
    except Exception as exc:
        st.error(
            "The opening regular-season readiness preview could not be built. "
            f"Detail: {exc}"
        )
        return

    schedule = dict(getattr(durable_state, "schedule", {}) or {})
    minimum_players = int(
        getattr(
            getattr(durable_state, "settings", None),
            "minimum_game_players",
            8,
        )
        or 8
    )
    roster_blockers: list[tuple[str, int]] = []
    teams = dict(getattr(durable_state, "teams", {}) or {})
    for team_code, team_state in sorted(teams.items()):
        count = len(
            tuple(
                getattr(
                    team_state,
                    "roster_player_ids",
                    (),
                )
                or ()
            )
        )
        if count < minimum_players:
            roster_blockers.append((str(team_code), count))

    calendar = free_agency_calendar_snapshot(durable_state)
    try:
        pending_sheets = list(pending_offer_sheets(durable_state))
    except Exception:
        pending_sheets = []

    st.markdown("### Open 2026-27 Regular Season")
    st.caption(
        "Finalize the opening offseason and activate the already-installed "
        "2026-27 schedule. This does not advance to 2027-28 or decrement "
        "contract years."
    )

    metric_cols = st.columns(4)
    metric_cols[0].metric(
        "Schedule",
        f"{preview.scheduled_game_count:,} / {preview.schedule_count:,}",
    )
    metric_cols[1].metric(
        "Active FA markets",
        str(int(calendar.active_market_count)),
    )
    metric_cols[2].metric(
        "Pending RFA sheets",
        str(len(pending_sheets)),
    )
    metric_cols[3].metric(
        "Game-ready teams",
        f"{len(teams) - len(roster_blockers)} / {len(teams)}",
    )

    backend_blockers = list(preview.blockers)
    ready = (
        bool(preview.can_commit)
        and not backend_blockers
        and not roster_blockers
        and len(schedule) == 1230
    )

    if roster_blockers:
        blocker_copy = ", ".join(
            f"{team_code} {count}/{minimum_players}"
            for team_code, count in roster_blockers
        )
        st.warning(
            "League roster readiness is blocking the season opener: "
            f"{blocker_copy}. CPU-controlled teams must complete legal "
            "roster moves before the regular season can begin."
        )

    if backend_blockers:
        st.warning(
            "Offseason lifecycle blockers remain: "
            + ", ".join(str(item) for item in backend_blockers)
        )

    preview_key = (
        "franchise_opening_regular_season_preview_v1::"
        f"{preview.season_label}"
    )
    ack_key = (
        "franchise_opening_regular_season_ack_v1::"
        f"{preview.season_label}"
    )

    if not ready:
        st.button(
            "Open 2026-27 Regular Season",
            type="primary",
            width="stretch",
            disabled=True,
            key=(
                "franchise_opening_regular_season_blocked_v1::"
                f"{preview.season_label}"
            ),
        )
        st.caption(
            "The final action remains disabled until every production "
            "readiness gate passes."
        )
        st.session_state.pop(preview_key, None)
        st.session_state.pop(ack_key, None)
        return

    prepared = st.session_state.get(preview_key)
    if (
        not isinstance(prepared, dict)
        or prepared.get("source_fingerprint")
        != preview.source_fingerprint
    ):
        prepared = None
        st.session_state.pop(preview_key, None)
        st.session_state.pop(ack_key, None)

    if prepared is None:
        if st.button(
            "Review season-opening confirmation",
            width="stretch",
            key=(
                "franchise_prepare_opening_regular_season_v1::"
                f"{preview.season_label}"
            ),
        ):
            st.session_state[preview_key] = {
                "season_label": preview.season_label,
                "source_fingerprint": preview.source_fingerprint,
                "confirmation_token": preview.confirmation_token,
                "schedule_count": preview.schedule_count,
                "trade_revision": preview.trade_revision,
            }
            st.rerun()
        return

    st.info(
        "Ready to open the 2026-27 regular season. The season label remains "
        "2026-27, all 1,230 scheduled games remain intact, current contracts "
        "and ownership are preserved, and this action is durable."
    )

    acknowledged = st.checkbox(
        "I’m ready to begin the 2026-27 regular season.",
        key=ack_key,
    )
    if st.button(
        "Open 2026-27 Regular Season",
        type="primary",
        width="stretch",
        disabled=not acknowledged,
        key=(
            "franchise_commit_opening_regular_season_v1::"
            f"{preview.season_label}"
        ),
    ):
        live_checkpoint = load_franchise_checkpoint(
            allow_backup=False,
        )
        if live_checkpoint is None:
            st.error(
                "The durable Franchise checkpoint could not be reloaded."
            )
            return

        live_preview = preview_opening_regular_season(
            live_checkpoint.simulation_state,
            live_checkpoint.trade_state,
        )
        if (
            live_preview.source_fingerprint
            != prepared.get("source_fingerprint")
        ):
            st.session_state.pop(preview_key, None)
            st.session_state.pop(ack_key, None)
            st.error(
                "The Franchise state changed after confirmation was prepared. "
                "Review the season-opening confirmation again."
            )
            return

        try:
            with st.spinner(
                "Opening the 2026-27 regular season..."
            ):
                commit_opening_regular_season_live(
                    confirmation_token=live_preview.confirmation_token,
                    expected_fingerprint=prepared["source_fingerprint"],
                )
        except OpeningRegularSeasonTransitionError as exc:
            st.error(
                "The 2026-27 regular season was not opened. "
                f"Detail: {exc}"
            )
            return
        except Exception as exc:
            st.error(
                "The 2026-27 regular season could not be opened. "
                f"Detail: {exc}"
            )
            return

        st.session_state.pop(preview_key, None)
        st.session_state.pop(ack_key, None)
        st.success("The 2026-27 regular season is now open.")
        st.rerun()


def render_franchise_season_transition(
    state: SimulationLeagueState,
) -> None:
    """Render only the authoritative Franchise season-boundary controls.

    Opening 2026-27 remains a distinct activation step. After a completed
    postseason, Franchise Mode must stay in the offseason until the completed-
    season closeout and the full Draft are finished. The actual next-season
    commit is owned by the certified Season Boundary Open next season path.
    """
    render_opening_regular_season_control_v1(state)

    # Keep the career-history surface, but retire the predecessor Franchise
    # transition commit UI. The generic transition controller remains available
    # to the standalone Game Simulator and to the Draft-complete wrapper below.
    render_career_lifecycle_season_open(state)

    phase_name = str(
        getattr(
            getattr(state, "phase", None),
            "value",
            getattr(state, "phase", ""),
        )
        or ""
    ).strip().lower()
    if phase_name != "offseason":
        return

    # The opening 2026-27 offseason has no completed prior season. Its only
    # authoritative transition is handled above by the regular-season opener.
    if (
        int(getattr(state, "transition_count", 0) or 0) == 0
        and not list(getattr(state, "season_history", ()) or ())
    ):
        return

    postseason = get_postseason_state(state, required=False)
    postseason_complete = bool(
        postseason is not None
        and postseason.stage == PostseasonStage.COMPLETE
    )
    if not postseason_complete:
        return

    from franchise_offseason_market_season_v1 import (
        completed_season_closeout_applied,
    )

    source_season = str(
        getattr(getattr(state, "settings", None), "season_label", "")
        or ""
    ).strip()
    closeout_applied = completed_season_closeout_applied(
        state,
        source_season,
    )
    draft_status = _draft_transition_status_v1_1_6(state)

    st.divider()
    st.markdown("## Season Boundary")
    st.caption(
        "Franchise Mode now uses one offseason authority: completed-season "
        "contract closeout → Free Agency → Draft → post-Draft CPU roster trim "
        "→ atomic Open next season."
    )

    if not closeout_applied:
        st.warning(
            "The completed-season contract closeout has not been proven for "
            f"{source_season}. The next season cannot open."
        )
        return

    if not bool(draft_status.get("ready")):
        st.info(
            "The completed season is closed. Continue the offseason through "
            "Free Agency and the Draft Room. The next season remains locked "
            "until the full Draft is complete."
        )
        return

    st.success(
        "The Draft is complete. Use the certified Open next season control "
        "to run the certified post-Draft trim and atomic season-boundary commit."
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



        render_playoff_honors_v2(



            state



        )



        st.markdown(



            '<div class="fm-section">Next chapter</div>',



            unsafe_allow_html=True,



        )







        _draft_gate_ready_v1_1_5, _draft_gate_detail_v1_1_5 = _draft_completion_gate_v1_1_6(state)



        if not draft_is_complete(state):  # draft-lifecycle-v1.1.8



            current_draft = draft_state(state)



            if current_draft is None:



                draft_label = "Enter NBA Draft Lottery"



                draft_detail = (



                    "The championship is complete. The next required event is "



                    "the NBA Draft Lottery, followed by scouting and Draft Night."



                )



            else:



                draft_label = "Continue NBA Draft"



                draft_detail = (



                    f"The {current_draft['draft_year']} draft is currently at "



                    f"{str(current_draft.get('phase', '')).replace('_', ' ').title()}. "



                    "Finish the draft before opening the next season."



                )



            st.info(draft_detail)



            enter_draft_clicked = st.button(



                draft_label,



                type="primary",



                width="stretch",



                key=(



                    "franchise_enter_draft_"



                    f"{state.settings.season_label}_"



                    f"{state.transition_count}"



                ),



            )



            if enter_draft_clicked:



                if current_draft is None:



                    initialize_draft_state(



                        state,



                        runtime,



                        controlled_teams=controlled_teams,



                        class_strength=int(



                            st.session_state.get(



                                "franchise_pref_draft_class_strength",



                                5,



                            )



                        ),



                    )



                    set_franchise_state(



                        state,



                        checkpoint_reason="draft-lottery-entry",



                    )



                set_franchise_section("Draft Room")



                st.rerun()



            st.caption(



                "The next-season schedule stays locked until all 60 draft "



                "selections are complete."



            )



        else:



            st.success(



                "Draft complete. The next-season transition is unlocked."



            )



            next_season_clicked = st.button(



                "Open next season",



                type="primary",



                width="stretch",



                key=(



                    "franchise_open_next_season_"



                    f"{state.settings.season_label}_"



                    f"{state.transition_count}"



                ),



            )



            st.caption(



                "Archives this completed season, activates the drafted rookie "



                "class, applies player development, and immediately generates "



                "the next 82-game schedule."



            )



            if next_season_clicked:



                try:



                    with st.spinner(



                        "Archiving the season and building the next schedule..."



                    ):



                        # FRANCHISE_SEASON_BOUNDARY_ATOMIC_UI_WIRING_V1
                        import simulation_franchise_checkpoint_v1 as _season_boundary_checkpoint
                        import franchise_season_boundary_durable_transition_v1 as _season_boundary_durable
                        from simulation_season_transition_controller_v1 import (
                            transition_source_fingerprint as _season_boundary_state_fingerprint,
                        )

                        _season_boundary_source = (
                            _season_boundary_checkpoint.load_franchise_checkpoint(
                                allow_backup=False,
                            )
                        )
                        if _season_boundary_source is None:
                            raise SimulationSeasonTransitionControllerError(
                                "The durable Franchise checkpoint could not be loaded "
                                "before opening the next season."
                            )

                        if (
                            _season_boundary_state_fingerprint(state)
                            != _season_boundary_state_fingerprint(
                                _season_boundary_source.simulation_state
                            )
                        ):
                            raise SimulationSeasonTransitionControllerError(
                                "The live Franchise UI state differs from the durable "
                                "checkpoint. Reload Franchise Mode before opening the "
                                "next season."
                            )

                        # FRANCHISE_CPU_POST_DRAFT_ROSTER_TRIM_LIVE_UI_WIRING_V1
                        import franchise_cpu_post_draft_roster_trim_live_v1 as _cpu_post_draft_trim_live

                        _cpu_post_draft_trim_source_fingerprint = (
                            _season_boundary_durable.checkpoint_boundary_fingerprint(
                                _season_boundary_source
                            )
                        )
                        try:
                            _cpu_post_draft_trim_result = (
                                _cpu_post_draft_trim_live.commit_atomic_cpu_post_draft_trim_live(
                                    expected_source_fingerprint=(
                                        _cpu_post_draft_trim_source_fingerprint
                                    ),
                                    confirmation=(
                                        _cpu_post_draft_trim_live.confirmation_token(
                                            _season_boundary_source.simulation_state
                                        )
                                    ),
                                )
                            )
                        except _cpu_post_draft_trim_live.CPUPostDraftRosterTrimLiveError as _cpu_post_draft_trim_exc:
                            raise SimulationSeasonTransitionControllerError(
                                "The CPU post-Draft roster trim must be resolved before "
                                "opening the next season. "
                                f"Detail: {_cpu_post_draft_trim_exc}"
                            ) from _cpu_post_draft_trim_exc

                        _season_boundary_source = (
                            _season_boundary_checkpoint.load_franchise_checkpoint(
                                allow_backup=False,
                            )
                        )
                        if _season_boundary_source is None:
                            raise SimulationSeasonTransitionControllerError(
                                "The durable Franchise checkpoint could not be reloaded "
                                "after the CPU post-Draft roster trim."
                            )
                        if (
                            _season_boundary_durable.checkpoint_boundary_fingerprint(
                                _season_boundary_source
                            )
                            != _cpu_post_draft_trim_result.target_fingerprint
                        ):
                            raise SimulationSeasonTransitionControllerError(
                                "The reloaded post-Draft roster-trim checkpoint does not "
                                "match the verified atomic trim result."
                            )

                        # Continue the existing season-boundary transaction from the
                        # exact durable post-trim state. If no trim was required, this
                        # is the unchanged original checkpoint.
                        state = _season_boundary_source.simulation_state
                        st.session_state[
                            "franchise_simulation_league_state"
                        ] = _season_boundary_source.simulation_state
                        st.session_state[
                            "franchise_trade_league_state"
                        ] = _season_boundary_source.trade_state

                        _season_boundary_source_fingerprint = (
                            _season_boundary_durable.checkpoint_boundary_fingerprint(
                                _season_boundary_source
                            )
                        )

                        transitioned_state, committed = (
                            advance_to_next_season_with_schedule(state)
                        )

                        try:
                            _season_boundary_result = (
                                _season_boundary_durable.commit_atomic_season_boundary_live(
                                    transitioned_state,
                                    expected_source_fingerprint=(
                                        _season_boundary_source_fingerprint
                                    ),
                                    expected_target_season=str(
                                        committed.target_season
                                    ),
                                    confirmation=(
                                        _season_boundary_durable.confirmation_token(
                                            str(committed.source_season),
                                            str(committed.target_season),
                                        )
                                    ),
                                )
                            )
                        except RuntimeError as _season_boundary_exc:
                            raise SimulationSeasonTransitionControllerError(
                                "The durable next-season checkpoint commit failed. "
                                f"Detail: {_season_boundary_exc}"
                            ) from _season_boundary_exc

                        _season_boundary_reloaded = (
                            _season_boundary_checkpoint.load_franchise_checkpoint(
                                allow_backup=False,
                            )
                        )
                        if _season_boundary_reloaded is None:
                            raise SimulationSeasonTransitionControllerError(
                                "The next season was committed, but the durable "
                                "checkpoint could not be reloaded."
                            )

                        if (
                            _season_boundary_durable.checkpoint_boundary_fingerprint(
                                _season_boundary_reloaded
                            )
                            != _season_boundary_result.target_fingerprint
                        ):
                            raise SimulationSeasonTransitionControllerError(
                                "The reloaded next-season checkpoint does not match "
                                "the atomic durable commit."
                            )

                        # Refresh BOTH live Franchise states from the exact durable checkpoint.
                        # Do not use the legacy state-save helper here: it performs another
                        # checkpoint write and could reintroduce stale TradeState ownership.
                        st.session_state[
                            "franchise_simulation_league_state"
                        ] = _season_boundary_reloaded.simulation_state
                        st.session_state[
                            "franchise_trade_league_state"
                        ] = _season_boundary_reloaded.trade_state



                except (



                    SimulationSeasonTransitionControllerError,



                    SimulationLeagueStateError,



                    RegularSeasonScheduleError,



                    ValueError,



                    KeyError,



                ) as exc:



                    st.error(



                        "The next season could not be opened. "



                        f"Detail: {exc}"



                    )



                else:



                    clear_franchise_transition_preview()



                    clear_game_day_preview()



                    st.session_state["franchise_notice"] = (



                        f"Archived {committed.source_season}, preserved the "



                        "championship history, activated the new rookie class, "



                        f"and opened {committed.target_season} with a new "



                        "82-game schedule."



                    )



                    st.rerun()







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



                disabled=(



                    status.eliminated



                    or bool(blocking_events(state))



                ),



            )



        )



        finish_clicked = (



            action_columns[1].button(



                "Sim to champion",



                width="stretch",



                disabled=bool(blocking_events(state)),



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







    current_postseason_preview_request = {



        "game_id": game.game_id,



        "sit_ids": tuple(sorted(sit_ids)),



    }



    if (



        preview is not None



        and preview_request



        != current_postseason_preview_request



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



        "What-if preview",



        width="stretch",



        key=(



            f"{key_prefix}_preview_"



            "postseason_game"



        ),



    )



    quick_clicked = actions[1].button(



        "Simulate & commit",



        type="primary",



        width="stretch",



        disabled=bool(blocking_events(state)),



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



                disabled=bool(blocking_events(state)),



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



                disabled=bool(blocking_events(state)),



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



            ] = current_postseason_preview_request



            preview_request = (



                current_postseason_preview_request



            )







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



        and preview_request



        == current_postseason_preview_request



    ):



        st.markdown("### What-If Result")



        st.info(



            "Sandbox result only. It has not been added to the "



            "postseason bracket, player totals, fatigue, or injuries."



        )



        render_completed_postseason_game(



            state,



            game,



            preview.game,



        )











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











FRANCHISE_EXPERIENCE_VERSION = (



    "franchise-draft-engine-v1.1.2-2026-08-11"



)







FRANCHISE_SECTION_DISPLAY = {



    "Command Center": "Home",



    "Inbox & League Health": "Health",



    "Calendar": "Schedule",



    "Team Management": "Roster",



    "Staff": "Staff",



    "Free Agency": "Free Agency",



    "Game Day": "Game Day",



    "Stats & Standings": "Stats",



    "Trade Center": "Transactions",



    "Draft Room": "Draft",



    "League & Offseason": "League Hub",



}











FRANCHISE_EXPERIENCE_AWARDS_VERSION = (



    "franchise-experience-v2.1-awards-v1-2026-08-10"



)







AWARDS_DISPLAY_META = {



    "mvp": {



        "label": "Most Valuable Player",



        "short": "MVP",



        "accent": "#f5b301",



        "icon": "🏆",



        "trophy": "Michael Jordan Trophy",



    },



    "dpoy": {



        "label": "Defensive Player of the Year",



        "short": "DPOY",



        "accent": "#38bdf8",



        "icon": "🛡️",



        "trophy": "Hakeem Olajuwon Trophy",



    },



    "roy": {



        "label": "Rookie of the Year",



        "short": "ROY",



        "accent": "#22c55e",



        "icon": "🌟",



        "trophy": "Wilt Chamberlain Trophy",



    },



    "smoy": {



        "label": "Sixth Man of the Year",



        "short": "6MOY",



        "accent": "#c084fc",



        "icon": "🔥",



        "trophy": "John Havlicek Trophy",



    },



    "mip": {



        "label": "Most Improved Player",



        "short": "MIP",



        "accent": "#fb7185",



        "icon": "📈",



        "trophy": "George Mikan Trophy",



    },



    "clutch": {



        "label": "Clutch Player of the Year",



        "short": "CLUTCH",



        "accent": "#f97316",



        "icon": "⏱️",



        "trophy": "Jerry West Trophy",



    },



    "coach": {



        "label": "Coach of the Year",



        "short": "COY",



        "accent": "#14b8a6",



        "icon": "🎯",



        "trophy": "Red Auerbach Trophy",



    },



    "executive": {



        "label": "Executive of the Year",



        "short": "EOTY",



        "accent": "#60a5fa",



        "icon": "🧠",



        "trophy": "Basketball Executive of the Year",



    },



}











def inject_awards_styles() -> None:



    st.markdown(



        """



        <style>



        .fm-awards-wrap {



            margin-top: 1rem;



        }



        .fm-awards-grid {



            display: grid;



            grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));



            gap: 1rem;



            margin: 0.75rem 0 1rem 0;



        }



        .fm-award-card {



            position: relative;



            overflow: hidden;



            min-height: 260px;



            border-radius: 26px;



            border: 1px solid rgba(255,255,255,0.12);



            background:



                radial-gradient(circle at 82% 20%, rgba(255,255,255,0.16), transparent 28%),



                linear-gradient(135deg, rgba(7,18,38,0.96), rgba(6,15,31,0.94));



            box-shadow: 0 18px 40px rgba(0,0,0,0.32);



            padding: 1.1rem 1.1rem 1rem 1.1rem;



        }



        .fm-award-card::before {



            content: "";



            position: absolute;



            inset: 0;



            background: linear-gradient(135deg, color-mix(in srgb, var(--award-accent) 38%, transparent), transparent 56%);



            opacity: 0.92;



            pointer-events: none;



        }



        .fm-award-card > * {



            position: relative;



            z-index: 1;



        }



        .fm-award-topline {



            display:flex;



            align-items:center;



            justify-content:space-between;



            gap: 0.75rem;



            margin-bottom: 0.7rem;



        }



        .fm-award-badge {



            display:inline-flex;



            align-items:center;



            gap:0.45rem;



            padding:0.35rem 0.65rem;



            border-radius:999px;



            font-size:0.72rem;



            font-weight:800;



            letter-spacing:0.12em;



            text-transform:uppercase;



            color:white;



            background: color-mix(in srgb, var(--award-accent) 28%, rgba(255,255,255,0.06));



            border:1px solid color-mix(in srgb, var(--award-accent) 60%, rgba(255,255,255,0.18));



        }



        .fm-award-trophy {



            font-size: 2rem;



            line-height: 1;



            filter: drop-shadow(0 6px 14px rgba(0,0,0,0.32));



        }



        .fm-award-winner-row {



            display:grid;



            grid-template-columns: 88px 1fr;



            gap: 0.9rem;



            align-items:center;



        }



        .fm-award-headshot {



            width: 88px;



            height: 88px;



            object-fit: cover;



            border-radius: 22px;



            border: 2px solid rgba(255,255,255,0.16);



            background: rgba(15,23,42,0.94);



        }



        .fm-award-logo {



            width: 88px;



            height: 88px;



            object-fit: contain;



            border-radius: 22px;



            padding: 0.9rem;



            border: 2px solid rgba(255,255,255,0.12);



            background: rgba(15,23,42,0.92);



        }



        .fm-award-label {



            color: rgba(255,255,255,0.78);



            font-size: 0.74rem;



            letter-spacing: 0.12em;



            text-transform: uppercase;



            font-weight: 800;



            margin-bottom: 0.18rem;



        }



        .fm-award-name {



            color: white;



            font-size: 1.35rem;



            font-weight: 900;



            line-height: 1.1;



            margin-bottom: 0.2rem;



        }



        .fm-award-meta {



            color: rgba(255,255,255,0.78);



            font-size: 0.95rem;



        }



        .fm-award-trophy-name {



            color: rgba(255,255,255,0.88);



            margin-top: 0.9rem;



            font-size: 0.86rem;



            font-weight: 700;



        }



        .fm-award-footnote {



            color: rgba(255,255,255,0.72);



            margin-top: 0.4rem;



            font-size: 0.83rem;



            line-height: 1.45;



        }



        .fm-award-summary-bar {



            display:flex;



            flex-wrap: wrap;



            gap: 0.55rem;



            margin-top: 0.85rem;



        }



        .fm-award-pill {



            padding:0.32rem 0.58rem;



            border-radius:999px;



            border:1px solid rgba(255,255,255,0.14);



            background: rgba(255,255,255,0.06);



            color:white;



            font-size:0.78rem;



            font-weight:700;



        }



        .fm-honors-shell {



            border-radius: 26px;



            border: 1px solid rgba(255,255,255,0.10);



            background: linear-gradient(145deg, rgba(7,18,38,0.95), rgba(6,15,31,0.92));



            padding: 1rem 1.1rem 1.15rem 1.1rem;



            box-shadow: 0 16px 32px rgba(0,0,0,0.28);



            margin-top: 0.8rem;



        }



        .fm-awards-stage {



            border-radius: 30px;



            overflow: hidden;



            position: relative;



            padding: 1.2rem;



            background:



                radial-gradient(circle at 20% 0%, rgba(250,204,21,0.18), transparent 22%),



                radial-gradient(circle at 82% 10%, rgba(255,255,255,0.12), transparent 26%),



                linear-gradient(135deg, rgba(12,20,40,0.98), rgba(20,10,34,0.98));



            border: 1px solid rgba(255,255,255,0.12);



            box-shadow: 0 22px 48px rgba(0,0,0,0.36);



            margin-top: 1rem;



        }



        .fm-awards-stage-kicker {



            font-size: 0.74rem;



            font-weight: 800;



            letter-spacing: 0.16em;



            text-transform: uppercase;



            color: #fde68a;



            margin-bottom: 0.45rem;



        }



        .fm-awards-stage-title {



            color: white;



            font-size: 2rem;



            font-weight: 900;



            line-height: 1.05;



            margin-bottom: 0.35rem;



        }



        .fm-awards-stage-copy {



            color: rgba(255,255,255,0.78);



            font-size: 0.97rem;



            max-width: 760px;



            line-height: 1.55;



        }



        @media (max-width: 980px) {



            .fm-award-winner-row {



                grid-template-columns: 1fr;



            }



        }



        </style>



        """,



        unsafe_allow_html=True,



    )











def _row_value(



    row: dict[str, Any],



    key: str,



    default: float = 0.0,



) -> float:



    try:



        value = row.get(key, default)



        if value in {None, "", "—"}:



            return float(default)



        return float(value)



    except (TypeError, ValueError):



        return float(default)











def _player_lookup_for_awards(



    state: SimulationLeagueState,



) -> dict[tuple[str, str], SimulationPlayerState]:



    lookup: dict[tuple[str, str], SimulationPlayerState] = {}



    for player in state.players.values():



        lookup[



            (



                str(player.player_name),



                str(player.team_abbreviation),



            )



        ] = player



    return lookup











def _regular_season_award_pool(



    state: SimulationLeagueState,



) -> list[dict[str, Any]]:



    max_games = max(



        (



            standing.games_played



            for standing in state.standings.values()



        ),



        default=0,



    )



    minimum_games = max(1, int(max_games * 0.55))



    team_rows = {



        str(row["Team"]): row



        for row in standings_rows(state)



    }



    player_lookup = _player_lookup_for_awards(state)



    rows = regular_season_player_rows(



        state,



        minimum_games=minimum_games,



        limit=max(120, len(state.players)),



    )



    pool: list[dict[str, Any]] = []



    for row in rows:



        team = str(row.get("Team", ""))



        standing = team_rows.get(team, {})



        player = player_lookup.get(



            (str(row.get("Player", "")), team)



        )



        pool.append(



            {



                **row,



                "_player_id": getattr(player, "player_id", ""),



                "_age": float(getattr(player, "age", 0.0) or 0.0),



                "_overall": float(



                    getattr(player, "overall_rating", 0.0) or 0.0



                ),



                "_wins": int(standing.get("W", 0) or 0),



                "_diff": float(standing.get("Diff", 0) or 0),



                "_rank": int(standing.get("Rank", 30) or 30),



            }



        )



    return pool











def _vote_table(



    candidates: list[dict[str, Any]],



    *,



    label: str,



) -> list[dict[str, Any]]:



    if not candidates:



        return []



    best = max(item["award_score"] for item in candidates)



    weights = [



        pow(2.0, (item["award_score"] - best) / 6.0)



        for item in candidates



    ]



    total = sum(weights) or 1.0



    first_place = [



        max(0, int(round(100.0 * weight / total)))



        for weight in weights



    ]



    diff = 100 - sum(first_place)



    first_place[0] += diff



    scoring = [100, 70, 55, 40, 25]



    rows = []



    for index, item in enumerate(candidates, start=1):



        rows.append(



            {



                "Rank": index,



                label: item["subject_name"],



                "Team": item["subject_team"],



                "Award Score": round(item["award_score"], 1),



                "Model Vote Share": (



                    f"{100.0 * weights[index - 1] / total:.1f}%"



                ),



                "First-Place Votes": first_place[index - 1],



                "Voting Pts": int(



                    round(



                        first_place[index - 1]



                        * scoring[index - 1]



                        / 10.0



                    )



                ),



            }



        )



    return rows











def _score_regular_season_awards(



    state: SimulationLeagueState,



) -> dict[str, Any]:



    pool = _regular_season_award_pool(state)



    if not pool:



        return {



            "ready": False,



            "reason": (



                "Awards will appear once the season has a "



                "qualified regular-season sample."



            ),



        }







    max_wins = max((row["_wins"] for row in pool), default=1) or 1







    def wins_bonus(row: dict[str, Any], scale: float) -> float:



        return scale * row["_wins"] / max_wins







    def efficiency_bonus(row: dict[str, Any]) -> float:



        return max(0.0, _row_value(row, "TS%") - 54.0)







    def build_ranking(name: str, rows: list[dict[str, Any]], scorer) -> list[dict[str, Any]]:



        ranked = []



        for row in rows:



            ranked.append(



                {



                    "award_key": name,



                    "subject_name": str(row.get("Player", "")),



                    "subject_team": str(row.get("Team", "")),



                    "subject_pos": str(row.get("Pos", "")),



                    "image_url": player_headshot_url(



                        str(row.get("_player_id", ""))



                    ),



                    "award_score": float(scorer(row)),



                    "summary": row,



                }



            )



        ranked.sort(



            key=lambda item: (



                -item["award_score"],



                item["subject_name"],



            )



        )



        return ranked







    awards: dict[str, list[dict[str, Any]]] = {}



    awards["mvp"] = build_ranking(



        "mvp",



        pool,



        lambda row: (



            _row_value(row, "PTS") * 1.65



            + _row_value(row, "AST") * 1.15



            + _row_value(row, "REB") * 0.78



            + _row_value(row, "STL") * 2.0



            + _row_value(row, "BLK") * 1.7



            + efficiency_bonus(row) * 0.85



            + wins_bonus(row, 18.0)



            + _row_value(row, "MIN") * 0.14



        ),



    )



    awards["dpoy"] = build_ranking(



        "dpoy",



        pool,



        lambda row: (



            _row_value(row, "BLK") * 6.0



            + _row_value(row, "STL") * 6.0



            + _row_value(row, "REB") * 1.1



            + wins_bonus(row, 14.0)



            + max(0.0, 55.0 - _row_value(row, "FG%")) * 0.25



            + _row_value(row, "MIN") * 0.12



        ),



    )



    rookie_pool = [



        row



        for row in pool



        if row.get("_age", 99.0) <= 23.5



    ]



    awards["roy"] = build_ranking(



        "roy",



        rookie_pool or pool,



        lambda row: (



            _row_value(row, "PTS") * 1.45



            + _row_value(row, "AST") * 1.0



            + _row_value(row, "REB") * 0.85



            + _row_value(row, "STL") * 1.7



            + _row_value(row, "BLK") * 1.4



            + efficiency_bonus(row) * 0.45



            + wins_bonus(row, 10.0)



            + max(0.0, 24.0 - row.get("_age", 24.0)) * 1.8



        ),



    )



    bench_pool = [



        row



        for row in pool



        if _row_value(row, "GS")



        <= max(4.0, _row_value(row, "GP") * 0.45)



    ]



    awards["smoy"] = build_ranking(



        "smoy",



        bench_pool or pool,



        lambda row: (



            _row_value(row, "PTS") * 1.55



            + _row_value(row, "AST") * 0.9



            + _row_value(row, "REB") * 0.55



            + efficiency_bonus(row) * 0.5



            + wins_bonus(row, 10.0)



            + _row_value(row, "MIN") * 0.24



        ),



    )



    breakout_pool = [



        row



        for row in pool



        if row.get("_overall", 100.0) <= 89.5



    ]



    awards["mip"] = build_ranking(



        "mip",



        breakout_pool or pool,



        lambda row: (



            _row_value(row, "PTS") * 1.15



            + _row_value(row, "AST") * 0.85



            + _row_value(row, "REB") * 0.65



            + efficiency_bonus(row) * 0.45



            + wins_bonus(row, 8.0)



            + max(0.0, 90.0 - row.get("_overall", 90.0)) * 0.9



            + max(0.0, 27.5 - row.get("_age", 27.5)) * 0.35



        ),



    )



    awards["clutch"] = build_ranking(



        "clutch",



        pool,



        lambda row: (



            _row_value(row, "PTS") * 1.25



            + _row_value(row, "FT%") * 0.09



            + _row_value(row, "3P%") * 0.08



            + wins_bonus(row, 13.0)



            + _row_value(row, "MIN") * 0.3



            + _row_value(row, "AST") * 0.4



        ),



    )







    coach_candidates = []



    executive_candidates = []



    for row in standings_rows(state):



        team = str(row.get("Team", ""))



        wins = float(row.get("W", 0) or 0)



        diff = float(row.get("Diff", 0) or 0)



        win_pct = float(row.get("Win%", 0) or 0.0)



        health = team_health_summary(



            state,



            team,



            day_index=state.current_day_index,



        )



        adversity_bonus = max(



            0.0,



            float(health.get("out", 0)) * 0.45



            + float(health.get("limited", 0)) * 0.18,



        )



        coach_candidates.append(



            {



                "award_key": "coach",



                "subject_name": f"{team_name(team)} coaching staff",



                "subject_team": team,



                "image_url": team_logo_url(team),



                "award_score": wins * 1.5 + diff * 0.18 + win_pct * 28.0 + adversity_bonus,



                "summary": row,



            }



        )



        executive_candidates.append(



            {



                "award_key": "executive",



                "subject_name": f"{team_name(team)} front office",



                "subject_team": team,



                "image_url": team_logo_url(team),



                "award_score": wins * 1.45 + diff * 0.2 + win_pct * 22.0 + max(0.0, 32.0 - float(row.get("Rank", 30))) * 0.4,



                "summary": row,



            }



        )



    coach_candidates.sort(key=lambda item: (-item["award_score"], item["subject_name"]))



    executive_candidates.sort(key=lambda item: (-item["award_score"], item["subject_name"]))



    awards["coach"] = coach_candidates



    awards["executive"] = executive_candidates







    return {



        "ready": True,



        "awards": awards,



        "voting": {



            key: _vote_table(



                value[:5],



                label=("Candidate" if key in {"coach", "executive"} else "Player"),



            )



            for key, value in awards.items()



        },



        "all_nba": {



            "All-NBA First Team": awards["mvp"][:5],



            "All-NBA Second Team": awards["mvp"][5:10],



            "All-NBA Third Team": awards["mvp"][10:15],



        },



        "all_defense": {



            "All-Defensive First Team": awards["dpoy"][:5],



            "All-Defensive Second Team": awards["dpoy"][5:10],



        },



        "all_rookie": {



            "All-Rookie First Team": awards["roy"][:5],



            "All-Rookie Second Team": awards["roy"][5:10],



        },



    }











def _award_stat_pills(summary: dict[str, Any]) -> str:



    labels = [



        "PTS",



        "REB",



        "AST",



        "STL",



        "BLK",



        "TS%",



    ]



    pills = []



    for label in labels:



        if label in summary:



            pills.append(



                '<span class="fm-award-pill">'



                f'{escaped(label)} {escaped(str(summary[label]))}'



                '</span>'



            )



        if len(pills) >= 4:



            break



    return "".join(pills)











def _finals_mvp_card(



    state: SimulationLeagueState,



) -> str:



    postseason = get_postseason_state(



        state,



        required=False,



    )



    if postseason is None or postseason.champion is None:



        return ""



    leaders = postseason_player_rows(



        state,



        minimum_games=1,



        limit=120,



    )



    if not leaders:



        return ""



    champion_rows = [



        row



        for row in leaders



        if str(row.get("Team", "")) == postseason.champion



    ]



    champion_rows.sort(



        key=lambda row: (



            -(



                _row_value(row, "PTS") * 1.45



                + _row_value(row, "REB") * 0.85



                + _row_value(row, "AST") * 1.05



                + _row_value(row, "STL") * 2.2



                + _row_value(row, "BLK") * 2.2



            ),



            str(row.get("Player", "")),



        )



    )



    winner = champion_rows[0] if champion_rows else leaders[0]



    player_lookup = _player_lookup_for_awards(state)



    player = player_lookup.get(



        (



            str(winner.get("Player", "")),



            str(winner.get("Team", "")),



        )



    )



    return (



        '<div class="fm-award-card" style="--award-accent:#facc15;">'



        '<div class="fm-award-topline">'



        '<span class="fm-award-badge">👑 FINALS MVP</span>'



        '<div class="fm-award-trophy">👑</div>'



        '</div>'



        '<div class="fm-award-winner-row">'



        f'<img class="fm-award-headshot" src="{escaped(player_headshot_url(getattr(player, "player_id", "")))}" alt="Finals MVP">'



        '<div>'



        '<div class="fm-award-label">Bill Russell Trophy</div>'



        f'<div class="fm-award-name">{escaped(str(winner.get("Player", "")))}</div>'



        f'<div class="fm-award-meta">{escaped(str(winner.get("Team", "")))} · NBA Finals winner</div>'



        '</div>'



        '</div>'



        '<div class="fm-award-summary-bar">'



        f'{_award_stat_pills(winner)}'



        '</div>'



        '<div class="fm-award-footnote">'



        f'{escaped(team_name(postseason.champion))} captured the Larry O\'Brien Trophy. Finals MVP is estimated from the champion\'s postseason production.'



        '</div>'



        '</div>'



    )











def render_awards_showcase(



    state: SimulationLeagueState,



) -> None:



    payload = _score_regular_season_awards(state)



    if not payload.get("ready"):



        st.info(payload.get("reason", "Awards will appear later in the season."))



        return







    st.markdown(



        (



            '<div class="fm-awards-stage">'



            '<div class="fm-awards-stage-kicker">Awards Night</div>'



            '<div class="fm-awards-stage-title">League Honors & Trophy Room</div>'



            '<div class="fm-awards-stage-copy">'



            'Model-based voting turns the completed season into a presentation layer with trophy winners, ballots, and honors teams. Use this room to showcase the franchise universe after the season takes shape.'



            '</div>'



            '</div>'



        ),



        unsafe_allow_html=True,



    )







    cards = []



    for key in [



        "mvp",



        "dpoy",



        "roy",



        "smoy",



        "mip",



        "clutch",



        "coach",



        "executive",



    ]:



        meta = AWARDS_DISPLAY_META[key]



        winner = payload["awards"][key][0]



        image_class = (



            "fm-award-logo"



            if key in {"coach", "executive"}



            else "fm-award-headshot"



        )



        subtitle = (



            team_name(winner["subject_team"])



            if key in {"coach", "executive"}



            else (



                f'{winner.get("subject_pos", "")} '



                f'· {winner["subject_team"]}'



            )



        )



        cards.append(



            '<div class="fm-award-card" '



            f'style="--award-accent:{escaped(meta["accent"])};">'



            '<div class="fm-award-topline">'



            '<span class="fm-award-badge">'



            f'{escaped(meta["icon"])} {escaped(meta["short"])}'



            '</span>'



            '<div class="fm-award-trophy">'



            f'{escaped(meta["icon"])}'



            '</div>'



            '</div>'



            '<div class="fm-award-winner-row">'



            f'<img class="{image_class}" src="{escaped(winner["image_url"])}" alt="Award winner">'



            '<div>'



            '<div class="fm-award-label">Winner</div>'



            f'<div class="fm-award-name">{escaped(winner["subject_name"])}</div>'



            f'<div class="fm-award-meta">{escaped(subtitle)}</div>'



            '</div>'



            '</div>'



            f'<div class="fm-award-trophy-name">{escaped(meta["trophy"])}</div>'



            '<div class="fm-award-summary-bar">'



            f'{_award_stat_pills(winner.get("summary", {}))}'



            '</div>'



            '<div class="fm-award-footnote">'



            f'Model score {winner["award_score"]:.1f}. Production, efficiency, and team success drive this ballot.'



            '</div>'



            '</div>'



        )







    finals_card = _finals_mvp_card(state)



    if finals_card:



        cards.append(finals_card)







    cards_markup = "".join(cards)



    st.markdown(



        '<div class="fm-awards-wrap"><div class="fm-awards-grid">'



        f'{cards_markup}'



        '</div></div>',



        unsafe_allow_html=True,



    )







    tabs = st.tabs(



        [



            "MVP Voting",



            "Defensive Voting",



            "Rookie Voting",



            "Sixth Man",



            "Most Improved",



            "Clutch",



            "Coach & Executive",



            "All-NBA",



            "Defense & Rookie Teams",



        ]



    )



    with tabs[0]:



        st.caption(



            "Modeled ballot using scoring production, efficiency, two-way impact, workload, and team success."



        )



        st.dataframe(



            pd.DataFrame(payload["voting"]["mvp"]),



            hide_index=True,



            width="stretch",



        )



    with tabs[1]:



        st.dataframe(



            pd.DataFrame(payload["voting"]["dpoy"]),



            hide_index=True,



            width="stretch",



        )



    with tabs[2]:



        st.dataframe(



            pd.DataFrame(payload["voting"]["roy"]),



            hide_index=True,



            width="stretch",



        )



    with tabs[3]:



        st.dataframe(



            pd.DataFrame(payload["voting"]["smoy"]),



            hide_index=True,



            width="stretch",



        )



    with tabs[4]:



        st.dataframe(



            pd.DataFrame(payload["voting"]["mip"]),



            hide_index=True,



            width="stretch",



        )



    with tabs[5]:



        st.dataframe(



            pd.DataFrame(payload["voting"]["clutch"]),



            hide_index=True,



            width="stretch",



        )



    with tabs[6]:



        coach_col, exec_col = st.columns(2)



        with coach_col:



            st.markdown("#### Coach of the Year")



            st.dataframe(



                pd.DataFrame(payload["voting"]["coach"]),



                hide_index=True,



                width="stretch",



            )



        with exec_col:



            st.markdown("#### Executive of the Year")



            st.dataframe(



                pd.DataFrame(payload["voting"]["executive"]),



                hide_index=True,



                width="stretch",



            )



    with tabs[7]:



        st.markdown(



            '<div class="fm-honors-shell">',



            unsafe_allow_html=True,



        )



        for label, entries in payload["all_nba"].items():



            st.markdown(f"#### {label}")



            st.dataframe(



                pd.DataFrame(



                    [



                        {



                            "Player": row["subject_name"],



                            "Team": row["subject_team"],



                            "Pos": row.get("subject_pos", ""),



                            "Award Score": round(row["award_score"], 1),



                        }



                        for row in entries



                    ]



                ),



                hide_index=True,



                width="stretch",



            )



        st.markdown(



            '</div>',



            unsafe_allow_html=True,



        )



    with tabs[8]:



        left, right = st.columns(2)



        with left:



            st.markdown(



                '<div class="fm-honors-shell">',



                unsafe_allow_html=True,



            )



            for label, entries in payload["all_defense"].items():



                st.markdown(f"#### {label}")



                st.dataframe(



                    pd.DataFrame(



                        [



                            {



                                "Player": row["subject_name"],



                                "Team": row["subject_team"],



                                "Pos": row.get("subject_pos", ""),



                                "Award Score": round(row["award_score"], 1),



                            }



                            for row in entries



                        ]



                    ),



                    hide_index=True,



                    width="stretch",



                )



            st.markdown(



                '</div>',



                unsafe_allow_html=True,



            )



        with right:



            st.markdown(



                '<div class="fm-honors-shell">',



                unsafe_allow_html=True,



            )



            for label, entries in payload["all_rookie"].items():



                st.markdown(f"#### {label}")



                st.dataframe(



                    pd.DataFrame(



                        [



                            {



                                "Player": row["subject_name"],



                                "Team": row["subject_team"],



                                "Pos": row.get("subject_pos", ""),



                                "Award Score": round(row["award_score"], 1),



                            }



                            for row in entries



                        ]



                    ),



                    hide_index=True,



                    width="stretch",



                )



            st.markdown(



                '</div>',



                unsafe_allow_html=True,



            )







def player_headshot_url(



    player_id: str,



    team: str = "",



    player_name: str = "",



) -> str:



    from franchise_generated_player_portraits_v1 import player_image_url







    return player_image_url(



        player_id,



        team=team,



        player_name=player_name,



    )











def featured_team_rows(



    state: SimulationLeagueState,



    team: str,



    *,



    limit: int = 4,



) -> list[dict[str, Any]]:



    rows = rotation_management_rows(state, team)



    return sorted(



        rows,



        key=lambda row: (



            -float(row.get("overall", 0.0) or 0.0),



            -float(row.get("minutes", 0.0) or 0.0),



            str(row.get("player", "")),



        ),



    )[:limit]











def render_team_hero(



    state: SimulationLeagueState,



    snapshot: Any,



    active_team: str,



    *,



    primary: str,



    secondary: str,



    next_copy: str,



) -> None:



    featured = featured_team_rows(state, active_team, limit=3)



    art: list[str] = []







    for index, row in enumerate(featured):



        player_id = str(row.get("player_id", "")).strip()



        image = player_headshot_url(player_id, active_team)



        if not image:



            continue



        name = escaped(row.get("player", ""))



        overall = float(row.get("overall", 0.0) or 0.0)



        art.append(



            (



                '<div class="fxv2-hero-player '



                f'fxv2-hero-player-{index + 1}">'



                f'<img src="{escaped(image)}" alt="{name}">'



                '<div class="fxv2-player-chip">'



                f'<span>{name}</span><b>{overall:.0f}</b>'



                '</div></div>'



            )



        )







    phase_name = str(
        getattr(getattr(state, "phase", None), "value", getattr(state, "phase", ""))
    ).strip().lower()
    if phase_name == "offseason":
        record_copy = "OFFSEASON · BUILD THE NEXT ROSTER"
        next_label = "OFFSEASON FOCUS"
        hero_next_copy = "Free Agency · Transactions · Draft"
        hero_description = (
            "Build the next version of the franchise. Manage the roster, "
            "negotiate in Free Agency, make live franchise trades, and prepare "
            "for the draft from one persistent front-office universe."
        )
    else:
        record_copy = (
            f"{snapshot.wins}-{snapshot.losses} · "
            f"#{snapshot.conference_rank} CONF · "
            f"#{snapshot.league_rank} NBA"
        )
        next_label = "NEXT UP"
        hero_next_copy = next_copy
        hero_description = (
            "Run the franchise from one command deck. Manage the rotation, "
            "follow health and league trends, simulate through the calendar, "
            "and move into the next season without hunting through setup screens."
        )



    st.markdown(



        (



            '<div class="fxv2-team-hero" '



            f'style="--team-primary:{escaped(primary)};'



            f'--team-secondary:{escaped(secondary)};">'



            '<div class="fxv2-court"></div>'



            '<div class="fxv2-hero-copy">'



            '<div class="fxv2-kicker">'



            f'{escaped(snapshot.conference).upper()} · '



            f'{escaped(snapshot.division).upper()}'



            '</div>'



            '<div class="fxv2-lockup">'



            f'<img src="{escaped(snapshot.logo_url)}" '



            'class="fxv2-logo">'



            '<div>'



            f'<div class="fxv2-team-name">{escaped(snapshot.team_name)}</div>'



            '<div class="fxv2-record-line">'



            f'{escaped(record_copy)}'



            '</div></div></div>'



            '<div class="fxv2-next">'



            f'<small>{escaped(next_label)}</small>'



            f'<strong>{escaped(hero_next_copy)}</strong>'



            '</div>'



            '<p class="fxv2-hero-desc">'



            f'{escaped(hero_description)}'



            '</p>'



            '</div>'



            '<div class="fxv2-player-stage">'



            + ''.join(art)



            + '</div></div>'



        ),



        unsafe_allow_html=True,



    )











def render_franchise_core(



    state: SimulationLeagueState,



    active_team: str,



    *,



    title: str,



) -> None:



    rows = featured_team_rows(state, active_team, limit=4)



    if not rows:



        return







    cards: list[str] = []



    for row in rows:



        player_id = str(row.get("player_id", "")).strip()



        image = player_headshot_url(player_id, active_team) or team_logo_url(active_team)



        name = escaped(row.get("player", ""))



        position = escaped(row.get("position", "—"))



        overall = float(row.get("overall", 0.0) or 0.0)



        minutes = float(row.get("minutes", 0.0) or 0.0)



        availability = escaped(row.get("availability", "available"))



        cards.append(



            (



                '<div class="fxv2-player-card">'



                '<div class="fxv2-player-photo">'



                f'<img src="{escaped(image)}" alt="{name}">'



                f'<div class="fxv2-ovr">{overall:.0f}</div>'



                '</div>'



                '<div class="fxv2-player-info">'



                f'<b>{name}</b>'



                f'<span>{position} · {minutes:.1f} MIN</span>'



                f'<em>{availability}</em>'



                '</div></div>'



            )



        )







    st.markdown(



        f'<div class="fxv2-subheading">{escaped(title)}</div>'



        '<div class="fxv2-player-grid">'



        + ''.join(cards)



        + '</div>',



        unsafe_allow_html=True,



    )











def auto_process_routine_franchise_events(



    state: SimulationLeagueState,



    policy: str,



) -> int:



    if policy != FranchiseSimulationPolicy.AUTO_SAVED_ROTATIONS.value:



        return 0







    resolved = resolve_all_nonblocking(state)



    routine_categories = {



        "medical",



        "performance",



        "league health",



    }



    for event in list(blocking_events(state)):



        category = str(event.get("category", "")).strip().lower()



        if category in routine_categories:



            if resolve_event(state, str(event.get("event_id", ""))):



                resolved += 1



    return resolved











def _draft_transition_status_v1_1_6(



    state: SimulationLeagueState,



) -> dict[str, Any]:



    current = getattr(



        state,



        "franchise_draft_state_v1",



        None,



    )



    if not isinstance(current, dict):



        return {



            "ready": False,



            "mode": "missing_draft_state",



            "detail": (



                "no franchise_draft_state_v1 dictionary is "



                "attached to the league state"



            ),



        }







    phase = str(



        current.get("phase", "")



    ).strip()



    source_season = str(



        current.get("source_season", "")



    ).strip()



    target_season = str(



        current.get("target_season", "")



    ).strip()



    live_season = str(



        getattr(



            getattr(state, "settings", None),



            "season_label",



            "",



        )



    ).strip()







    draft_order = current.get(



        "draft_order",



        [],



    )



    if not isinstance(



        draft_order,



        list,



    ):



        draft_order = []







    total_picks = len(draft_order)



    expected_picks = expected_draft_pick_count(



        current.get("draft_year"),



        team_count=(



            len(getattr(state, "standings", {}) or {})



            or 30



        ),



    )



    completed_picks = sum(



        1



        for pick in draft_order



        if (



            isinstance(pick, dict)



            and str(



                pick.get(



                    "prospect_id",



                    "",



                )



            ).strip()



        )



    )







    archived_labels = {



        str(



            getattr(



                archive,



                "season_label",



                "",



            )



        ).strip()



        for archive in getattr(



            state,



            "season_history",



            [],



        )



    }



    source_archived = (



        bool(source_season)



        and source_season



        in archived_labels



    )







    scheduled_games = len(



        getattr(



            state,



            "schedule",



            {},



        )



    )



    completed_games = len(



        getattr(



            state,



            "completed_games",



            {},



        )



    )



    max_team_games = max(



        (



            int(



                getattr(



                    standing,



                    "games_played",



                    0,



                )



                or 0



            )



            for standing



            in getattr(



                state,



                "standings",



                {},



            ).values()



        ),



        default=0,



    )







    reasons: list[str] = []







    if phase != "draft_complete":



        reasons.append(



            f"phase={phase!r}"



        )







    if total_picks != expected_picks:



        reasons.append(



            "draft_order contains "



            f"{total_picks} picks instead of {expected_picks}"



        )







    if completed_picks != total_picks:



        reasons.append(



            f"{completed_picks}/{total_picks} "



            "picks have selected prospects"



        )







    if reasons:



        return {



            "ready": False,



            "mode": "draft_incomplete",



            "detail": "; ".join(reasons),



        }







    if (



        source_season



        and live_season



        and live_season



        == source_season



    ):



        return {



            "ready": True,



            "mode": "normal_transition",



            "source_season": source_season,



            "target_season": target_season,



            "live_season": live_season,



            "source_archived": source_archived,



            "scheduled_games": scheduled_games,



            "completed_games": completed_games,



            "max_team_games": max_team_games,



            "detail": (



                "draft complete; live state is still on "



                f"source season {source_season}"



            ),



        }







    if (



        target_season



        and live_season



        and live_season



        == target_season



    ):



        mode = (



            "target_already_transitioned"



            if source_archived



            else "repair_season_label_then_transition"



        )



        return {



            "ready": True,



            "mode": mode,



            "source_season": source_season,



            "target_season": target_season,



            "live_season": live_season,



            "source_archived": source_archived,



            "scheduled_games": scheduled_games,



            "completed_games": completed_games,



            "max_team_games": max_team_games,



            "detail": (



                "draft complete; live season already equals "



                f"draft target {target_season}; "



                f"source_archived={source_archived}; "



                f"schedule={scheduled_games}; "



                f"completed_games={completed_games}; "



                f"max_team_games={max_team_games}"



            ),



        }







    return {



        "ready": False,



        "mode": "season_mismatch",



        "detail": (



            "draft is complete, but season labels cannot be "



            "reconciled safely: "



            f"source={source_season!r}; "



            f"target={target_season!r}; "



            f"live={live_season!r}"



        ),



    }











def _draft_completion_gate_v1_1_6(



    state: SimulationLeagueState,



) -> tuple[bool, str]:



    status = (



        _draft_transition_status_v1_1_6(



            state



        )



    )



    return (



        bool(status["ready"]),



        str(status["detail"]),



    )











def advance_to_next_season_with_schedule(



    state: SimulationLeagueState,



) -> tuple[SimulationLeagueState, Any]:



    from dataclasses import replace as _replace_settings



    from types import SimpleNamespace as _SimpleNamespace







    status = (



        _draft_transition_status_v1_1_6(



            state



        )



    )



    if not bool(status["ready"]):



        raise SimulationSeasonTransitionControllerError(



            "The NBA Draft must be completed before the next "



            "season can open. Draft-state diagnostic: "



            + str(status["detail"])



        )







    mode = str(status["mode"])

    # FRANCHISE_LIFECYCLE_AUTHORITY_CONSOLIDATION_V1
    # A future Franchise season may only open from a completed-season offseason
    # whose contract closeout already ran. Never let the generic transition
    # fallback silently become a second Franchise closeout path.
    if mode in {"normal_transition", "repair_season_label_then_transition"}:
        from franchise_offseason_market_season_v1 import (
            completed_season_closeout_applied as _completed_closeout_applied_v1,
        )

        _authority_source_season = str(
            status.get("source_season", "") or ""
        ).strip()
        if not _completed_closeout_applied_v1(
            state,
            _authority_source_season,
        ):
            raise SimulationSeasonTransitionControllerError(
                "Completed-season contract closeout must be committed before "
                "Franchise Mode can open the next season."
            )

    source_season = str(



        status.get(



            "source_season",



            "",



        )



    )



    target_season = str(



        status.get(



            "target_season",



            "",



        )



    )







    if mode == "normal_transition":



        preview = (



            build_season_transition_preview(



                state



            )



        )



        transitioned, committed = (



            commit_season_transition_preview(



                state,



                preview,



            )



        )







    elif mode == "repair_season_label_then_transition":



        # The draft is complete and its target season already



        # appears in settings, but the source season was never



        # archived. This indicates a season-label drift rather



        # than a completed season transition. Repair the label



        # only on a deep copy, then perform the normal



        # transactional transition exactly once.



        repaired = copy.deepcopy(state)



        repaired.settings = _replace_settings(



            repaired.settings,



            season_label=source_season,



        )







        preview = (



            build_season_transition_preview(



                repaired



            )



        )



        transitioned, committed = (



            commit_season_transition_preview(



                repaired,



                preview,



            )



        )







    elif mode == "target_already_transitioned":



        # The source season is already archived and the live



        # state is already on the draft's target season. Never



        # advance again. Reconcile rookies and schedule only.



        transitioned = copy.deepcopy(state)







        if (



            status.get(



                "scheduled_games",



                0,



            )



            not in {0, LEAGUE_GAME_COUNT}



        ):



            raise SimulationSeasonTransitionControllerError(



                "The draft target season is already open, but "



                "its schedule is neither empty nor a complete "



                f"{LEAGUE_GAME_COUNT}-game schedule. "



                "Draft-state diagnostic: "



                + str(status["detail"])



            )







        committed = _SimpleNamespace(



            source_season=source_season,



            target_season=target_season,



            transition_count=getattr(



                transitioned,



                "transition_count",



                0,



            ),



            recovered_existing_target=True,



        )







    else:



        raise SimulationSeasonTransitionControllerError(



            "Unsupported Draft transition reconciliation mode: "



            + mode



        )







    activate_drafted_rookies_after_transition(



        transitioned,



        target_season,



    )







    if not transitioned.schedule:



        generated = (



            generate_regular_season_schedule(



                transitioned,



                seed=(



                    transitioned



                    .settings



                    .random_seed



                ),



            )



        )



        install_regular_season_schedule(



            transitioned,



            generated,



        )







    validate_simulation_league_state(



        transitioned



    )



    return transitioned, committed











def inject_franchise_experience_v2_styles() -> None:



    st.markdown(



        """



<style>



:root {



  --fx-bg:#070a11;



  --fx-panel:rgba(15,20,31,.84);



  --fx-border:rgba(255,255,255,.10);



  --team-primary:#1d428a;



  --team-secondary:#c8102e;



}



.stApp {



  background:



    radial-gradient(circle at 82% 8%, rgba(45,103,230,.16), transparent 28%),



    radial-gradient(circle at 12% 34%, rgba(255,65,108,.11), transparent 30%),



    linear-gradient(180deg,#070a11 0%,#0a0f18 46%,#070a10 100%);



}



.block-container { max-width:1580px; padding-top:.8rem; padding-bottom:4rem; }



[data-testid="stSidebar"] {



  background:linear-gradient(180deg,#10151f 0%,#0d1119 100%);



  border-right:1px solid rgba(255,255,255,.07);



}



.fxv2-team-hero {



  position:relative; min-height:390px; overflow:hidden; margin:14px 0 18px;



  border:1px solid rgba(255,255,255,.14); border-radius:30px;



  background:



    radial-gradient(circle at 78% 38%, color-mix(in srgb,var(--team-secondary) 55%,transparent),transparent 30%),



    linear-gradient(112deg,color-mix(in srgb,var(--team-primary) 82%,#05070d),color-mix(in srgb,var(--team-primary) 52%,#090c14) 52%,#080b12 82%);



  box-shadow:0 30px 90px rgba(0,0,0,.36),inset 0 1px 0 rgba(255,255,255,.14);



}



.fxv2-team-hero:after {



  content:""; position:absolute; inset:0; pointer-events:none;



  background:linear-gradient(90deg,transparent 35%,rgba(0,0,0,.18)),linear-gradient(0deg,rgba(0,0,0,.34),transparent 38%);



}



.fxv2-court {



  position:absolute; width:520px; height:520px; right:-150px; top:-105px;



  border:2px solid rgba(255,255,255,.13); border-radius:50%; opacity:.8;



}



.fxv2-court:before {



  content:""; position:absolute; width:210px; height:340px; left:-165px; top:88px;



  border:2px solid rgba(255,255,255,.11); border-radius:110px 0 0 110px;



}



.fxv2-hero-copy { position:relative; z-index:4; width:57%; padding:44px 0 38px 44px; }



.fxv2-kicker { color:rgba(255,255,255,.66); font-size:.68rem; font-weight:900; letter-spacing:.18em; margin-bottom:15px; }



.fxv2-lockup { display:flex; align-items:center; gap:18px; }



.fxv2-logo { width:92px; height:92px; object-fit:contain; filter:drop-shadow(0 12px 24px rgba(0,0,0,.34)); }



.fxv2-team-name { color:#fff; font-size:clamp(2.25rem,4vw,4.45rem); font-weight:1000; letter-spacing:-.055em; line-height:.94; }



.fxv2-record-line { margin-top:10px; color:rgba(255,255,255,.78); font-size:.78rem; font-weight:850; letter-spacing:.055em; }



.fxv2-next { display:inline-flex; flex-direction:column; margin-top:26px; padding:11px 15px; border:1px solid rgba(255,255,255,.16); border-radius:15px; background:rgba(5,8,14,.38); backdrop-filter:blur(10px); }



.fxv2-next small { color:rgba(255,255,255,.50); font-size:.56rem; font-weight:950; letter-spacing:.17em; }



.fxv2-next strong { margin-top:2px; color:#fff; font-size:.92rem; }



.fxv2-hero-desc { max-width:640px; margin:17px 0 0; color:rgba(255,255,255,.66); font-size:.84rem; line-height:1.6; }



.fxv2-player-stage { position:absolute; z-index:3; right:0; bottom:0; width:48%; height:100%; }



.fxv2-hero-player { position:absolute; bottom:-2px; width:285px; height:350px; }



.fxv2-hero-player img { width:100%; height:100%; object-fit:contain; object-position:bottom center; filter:drop-shadow(0 26px 30px rgba(0,0,0,.42)); }



.fxv2-hero-player-1 { right:150px; z-index:4; }



.fxv2-hero-player-2 { right:-4px; z-index:3; transform:scale(.88); opacity:.92; }



.fxv2-hero-player-3 { right:305px; z-index:2; transform:scale(.78); opacity:.82; }



.fxv2-player-chip { position:absolute; left:50%; bottom:15px; transform:translateX(-50%); display:flex; align-items:center; gap:8px; padding:6px 8px 6px 10px; border:1px solid rgba(255,255,255,.15); border-radius:999px; background:rgba(5,8,14,.68); color:#fff; font-size:.62rem; font-weight:850; white-space:nowrap; }



.fxv2-player-chip b { display:grid; place-items:center; width:27px; height:27px; border-radius:50%; background:#fff; color:#080b12; }



.fxv2-player-grid { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:12px; margin:12px 0 18px; }



.fxv2-subheading { color:#fff; font-size:.92rem; font-weight:950; margin:18px 0 8px; }



.fxv2-player-card { overflow:hidden; border:1px solid var(--fx-border); border-radius:18px; background:var(--fx-panel); box-shadow:0 14px 36px rgba(0,0,0,.18); }



.fxv2-player-photo { position:relative; height:178px; overflow:hidden; background:radial-gradient(circle at 50% 92%,color-mix(in srgb,var(--team-secondary) 28%,transparent),transparent 60%); }



.fxv2-player-photo img { width:100%; height:100%; object-fit:contain; object-position:bottom center; filter:drop-shadow(0 14px 18px rgba(0,0,0,.30)); }



.fxv2-ovr { position:absolute; top:10px; right:10px; display:grid; place-items:center; width:42px; height:42px; border-radius:50%; background:#fff; color:#070a11; font-size:.82rem; font-weight:1000; }



.fxv2-player-info { display:flex; flex-direction:column; padding:12px 14px 14px; }



.fxv2-player-info b { color:#fff; font-size:.9rem; }



.fxv2-player-info span { color:#9aa7b8; font-size:.7rem; margin-top:2px; }



.fxv2-player-info em { width:max-content; margin-top:8px; padding:4px 8px; border-radius:999px; background:rgba(46,144,250,.12); color:#b9ddff; font-style:normal; font-size:.61rem; font-weight:850; }



.fm-route-guide { margin:12px 0 16px !important; padding:16px 18px !important; border:1px solid rgba(255,255,255,.09) !important; border-left-width:5px !important; border-radius:17px !important; background:linear-gradient(110deg,rgba(255,255,255,.035),rgba(255,255,255,.012)) !important; }



.fm-route-title { color:#fff !important; font-weight:950 !important; font-size:1.02rem !important; }



.fm-route-detail { color:#9eabbd !important; font-size:.78rem !important; line-height:1.5 !important; }



[role="radiogroup"] { gap:7px !important; padding:7px !important; border:1px solid rgba(255,255,255,.08); border-radius:16px; background:rgba(8,12,19,.72); }



[role="radiogroup"] label { padding:7px 10px !important; border-radius:11px !important; }



[role="radiogroup"] label:has(input:checked) { background:linear-gradient(110deg,color-mix(in srgb,var(--team-primary) 66%,#101622),color-mix(in srgb,var(--team-secondary) 38%,#101622)); box-shadow:0 8px 18px rgba(0,0,0,.20); }



div[data-testid="stMetric"] { min-height:110px; padding:14px 15px; border:1px solid rgba(255,255,255,.09); border-radius:17px; background:linear-gradient(145deg,rgba(255,255,255,.035),rgba(255,255,255,.012)); box-shadow:0 12px 28px rgba(0,0,0,.12); }



div[data-testid="stMetricValue"] { color:#fff !important; font-weight:950 !important; }



button[kind="primary"] { border:0 !important; border-radius:12px !important; background:linear-gradient(110deg,var(--team-primary),color-mix(in srgb,var(--team-secondary) 78%,var(--team-primary))) !important; box-shadow:0 10px 28px color-mix(in srgb,var(--team-primary) 24%,transparent); font-weight:850 !important; }



[data-testid="stDataFrame"],[data-testid="stDataEditor"] { overflow:hidden; border:1px solid rgba(255,255,255,.09); border-radius:16px; }



@media (max-width:1050px) {



  .fxv2-hero-copy { width:64%; padding-left:28px; }



  .fxv2-player-stage { width:42%; opacity:.80; }



  .fxv2-hero-player-3 { display:none; }



  .fxv2-player-grid { grid-template-columns:repeat(2,minmax(0,1fr)); }



}



@media (max-width:760px) {



  .fxv2-team-hero { min-height:520px; }



  .fxv2-hero-copy { width:auto; padding:28px 22px; }



  .fxv2-player-stage { width:100%; height:220px; opacity:.48; }



  .fxv2-team-name { font-size:2.3rem; }



  .fxv2-player-grid { grid-template-columns:1fr 1fr; }



}



</style>



        """,



        unsafe_allow_html=True,



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
  display:flex;
  align-items:center;
  justify-content:space-between;
  gap:24px;
  padding:14px 18px;
  margin:0 0 12px 0;
  border:1px solid rgba(255,255,255,.10);
  border-radius:16px;
  background:linear-gradient(115deg,rgba(7,28,53,.94),rgba(18,63,115,.86));
  box-shadow:0 10px 28px rgba(0,0,0,.16);
}

.fm-hero-copy { min-width:260px; }

.fm-eyebrow {
  color:#9fd3ff;
  font-size:.64rem;
  font-weight:850;
  letter-spacing:.16em;
}

.fm-title {
  margin-top:3px;
  color:#fff;
  font-size:1.45rem;
  font-weight:950;
  line-height:1.08;
}

.fm-subtitle {
  max-width:720px;
  margin:0;
  color:#dbeafe;
  font-size:.86rem;
  line-height:1.45;
  text-align:right;
}

.fm-postseason-matchup {
  margin:8px 0 16px 0;
  padding:20px;
  border:1px solid #334155;
  border-radius:18px;
  background:linear-gradient(145deg,#111827,#0b1220);
}

.fm-matchup-label {
  margin-bottom:14px;
  color:#94a3b8;
  font-size:.72rem;
  font-weight:850;
  letter-spacing:.12em;
  text-align:center;
  text-transform:uppercase;
}

.fm-matchup-grid {
  display:grid;
  grid-template-columns:minmax(0,1fr) 56px minmax(0,1fr);
  align-items:center;
  gap:16px;
}

.fm-matchup-team { text-align:center; }
.fm-matchup-team img { width:76px; height:76px; object-fit:contain; }
.fm-matchup-name { margin-top:6px; color:#fff; font-size:1.08rem; font-weight:850; }
.fm-matchup-side { color:#94a3b8; font-size:.78rem; }
.fm-matchup-at { color:#64748b; font-size:.78rem; font-weight:900; text-align:center; }

@media (max-width:760px) {
  .fm-hero { align-items:flex-start; flex-direction:column; gap:8px; }
  .fm-subtitle { text-align:left; }
  .fm-matchup-grid { grid-template-columns:1fr 34px 1fr; gap:8px; }
  .fm-matchup-team img { width:62px; height:62px; }
  .fm-matchup-name { font-size:.92rem; }
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



.fm-route-guide {



  margin: 10px 0 18px 0;



  padding: 11px 14px;



  border: 1px solid #344054;



  border-left: 6px solid #2e90fa;



  border-radius: 12px;



  background: linear-gradient(90deg, #171d28, #11151d);



}



.fm-route-title {



  color: #ffffff;



  font-weight: 900;



  letter-spacing: .02em;



}



.fm-route-copy {



  margin-top: 3px;



  color: #b8c2d1;



  font-size: .82rem;



}



div[data-testid="stRadio"] > div {



  gap: .35rem;



}



div[data-testid="stRadio"] label {



  padding: .34rem .62rem;



  border: 1px solid #344054;



  border-radius: 999px;



  background: #151922;



}



div[data-testid="stRadio"] label:nth-child(1) { border-color: #2e90fa; }



div[data-testid="stRadio"] label:nth-child(2) { border-color: #f63d68; }



div[data-testid="stRadio"] label:nth-child(3) { border-color: #12b76a; }



div[data-testid="stRadio"] label:nth-child(4) { border-color: #f79009; }



div[data-testid="stRadio"] label:nth-child(5) { border-color: #f04438; }



div[data-testid="stRadio"] label:nth-child(6) { border-color: #7f56d9; }



div[data-testid="stRadio"] label:nth-child(7) { border-color: #ee46bc; }



div[data-testid="stRadio"] label:nth-child(8) { border-color: #06aed4; }







.fm-inbox-card {



  border: 1px solid #344054;



  border-left: 5px solid #667085;



  border-radius: 12px;



  padding: 12px 14px;



  margin: 8px 0;



  background: linear-gradient(90deg, #171d28, #11151d);



}



.fm-inbox-card.blocking { border-left-color: #f04438; }



.fm-inbox-card.warning { border-left-color: #f79009; }



.fm-inbox-card.info { border-left-color: #2e90fa; }



.fm-inbox-title { color: #fff; font-weight: 900; }



.fm-inbox-meta { color: #98a2b3; font-size: .78rem; margin-top: 2px; }



.fm-inbox-detail { color: #d0d5dd; font-size: .87rem; margin-top: 7px; }



.fm-health-warning {



  border: 1px solid #f79009;



  background: rgba(247,144,9,.10);



  border-radius: 12px;



  padding: 12px 14px;



  margin: 10px 0;



}



.fm-health-ok {



  border: 1px solid #12b76a;



  background: rgba(18,183,106,.08);



  border-radius: 12px;



  padding: 12px 14px;



  margin: 10px 0;



}







div[data-testid="stMetric"] {



  border: 1px solid #344054;



  border-radius: 14px;



  padding: 10px 12px;



  background: #151922;



}




/* FRANCHISE_VISUAL_V1_3 */
.fm-hero-v13 {
  display:grid;
  grid-template-columns:auto 1fr;
  gap:22px;
  align-items:center;
  padding:19px 22px;
  border-radius:24px;
  border:1px solid var(--hero-line);
  background:radial-gradient(circle at 90% 0,var(--hero-secondary-soft),transparent 30%),linear-gradient(115deg,var(--hero-primary-soft),#101827 55%,#080c13);
  box-shadow:0 22px 60px rgba(0,0,0,.25);
  margin-bottom:12px;
  overflow:hidden;
}
.fm-hero-v13-logo {width:92px;height:92px;object-fit:contain;filter:drop-shadow(0 10px 15px rgba(0,0,0,.38));}
.fm-hero-v13-kicker {font-size:.7rem;letter-spacing:.17em;color:#a7b2c3;font-weight:900;}
.fm-hero-v13-title {font-size:clamp(1.8rem,3vw,2.75rem);line-height:1.02;color:#fff;font-weight:950;margin-top:3px;}
.fm-hero-v13-sub {color:#cbd5e1;font-size:.9rem;margin-top:7px;line-height:1.45;max-width:850px;}
.fm-hero-v13-pills {display:flex;flex-wrap:wrap;gap:7px;margin-top:11px;}
.fm-hero-v13-pill {font-size:.68rem;font-weight:850;color:#fff;padding:5px 8px;border-radius:999px;border:1px solid rgba(255,255,255,.13);background:rgba(0,0,0,.23);}
@media(max-width:760px){.fm-hero-v13{grid-template-columns:1fr;text-align:center}.fm-hero-v13-logo{margin:auto}.fm-hero-v13-pills{justify-content:center}}

</style>



        """,



        unsafe_allow_html=True,



    )











_franchise_perf_v1_6["imports_and_page_setup"] = (
    time.perf_counter() - _franchise_page_started_at_v1_6
)

inject_styles()



inject_awards_styles()



inject_career_awards_styles()



inject_franchise_experience_v2_styles()



_perf_stage_v1_6 = time.perf_counter()
runtime = get_base_runtime()
_franchise_perf_v1_6["runtime"] = time.perf_counter() - _perf_stage_v1_6



_franchise_loading_progress.progress(58, text="Loading league data...")







_perf_stage_v1_6 = time.perf_counter()
checkpoint_restored = (



    restore_franchise_checkpoint()



)
_franchise_perf_v1_6["checkpoint_restore"] = (
    time.perf_counter() - _perf_stage_v1_6
)
_load_franchise_ui_preferences_v1_6()



_franchise_loading_progress.progress(72, text="Restoring franchise checkpoint...")







_perf_stage_v1_6 = time.perf_counter()
trade_state = get_trade_state(



    runtime



)
_franchise_perf_v1_6["trade_state"] = (
    time.perf_counter() - _perf_stage_v1_6
)



_franchise_loading_progress.progress(84, text="Preparing front-office state...")







_perf_stage_v1_6 = time.perf_counter()
state, rebuilt = get_franchise_state(



    runtime,



    trade_state,



)
# FRANCHISE_TRADE_SYNC_COMPATIBILITY_HOTFIX_V1
# The legacy standalone Trade Machine -> Franchise sync path has been
# permanently retired. Some downstream UI disable guards still reference
# this scalar, so keep it explicitly false at module scope.
trade_sync_required = False


_franchise_perf_v1_6["franchise_state"] = (
    time.perf_counter() - _perf_stage_v1_6
)



_franchise_loading_progress.progress(



    100,



    text="Franchise Mode ready.",



)



_franchise_loading_progress.empty()



_franchise_loading_message.empty()







_perf_stage_v1_7 = time.perf_counter()
career_metadata_counts = ensure_career_metadata(



    state



)
_franchise_perf_v1_6["career_metadata"] = (
    time.perf_counter() - _perf_stage_v1_7
)



_perf_stage_v1_7 = time.perf_counter()
ensure_injury_fatigue_state(



    state



)
_franchise_perf_v1_6["injury_fatigue_ensure"] = (
    time.perf_counter() - _perf_stage_v1_7
)

# FRANCHISE_STAFF_FOUNDATION_V1
ensure_franchise_staff_state(state)

# COMPLETED_SEASON_CONTRACT_CLOSEOUT_V1
# Close expiring contracts exactly once as soon as a completed postseason
# enters the offseason, before Free Agency or the Draft can operate.
from franchise_completed_season_contract_closeout_v1 import (
    completed_season_contract_closeout_required as _completed_season_closeout_required_v1,
    commit_completed_season_contract_closeout_durably as _commit_completed_season_closeout_v1,
)

if _completed_season_closeout_required_v1(state):
    try:
        _closeout_result_v1 = _commit_completed_season_closeout_v1(
            state,
            trade_state,
            preferences=franchise_checkpoint_preferences(),
        )
    except Exception as _closeout_exc_v1:
        st.error(
            "The completed-season contract closeout could not be committed safely. "
            f"No Draft or Free Agency action was opened: {_closeout_exc_v1}"
        )
        st.stop()

    state = _closeout_result_v1.simulation_state
    trade_state = _closeout_result_v1.trade_state
    st.session_state["franchise_simulation_league_state"] = state
    st.session_state["franchise_trade_league_state"] = trade_state
    st.session_state["franchise_completed_season_closeout_notice_v1"] = (
        f"{_closeout_result_v1.contracts_expired} expiring contract(s) moved to "
        f"the {_closeout_result_v1.target_market_season} offseason market."
    )
    st.rerun()




health_rebuild_marker = getattr(



    state,



    HEALTH_WORKLOAD_REBUILD_MARKER_ATTRIBUTE,



    None,



)



health_rebuild_session_key = (



    "franchise_health_rebuild_saved_marker"



)



if (



    health_rebuild_marker is not None



    and st.session_state.get(



        health_rebuild_session_key



    )



    != health_rebuild_marker



):



    if not checkpoint_restored and save_current_franchise_checkpoint(



        state,



        trade_state=trade_state,



        reason="health-workload-reconstruction",



        copy_payload=False,



    ):



        st.session_state[



            health_rebuild_session_key



        ] = health_rebuild_marker



        st.session_state[



            "franchise_notice"



        ] = (



            "Recovered fatigue and recent workload from "



            "committed box scores after the health-state upgrade."



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
    # FA_OFFSEASON_APPLICATION_BOUNDARY_REPAIR_V1:
    # a clean durable restore is already using the current writer contract.
    not checkpoint_restored
    and not rebuilt
    and st.session_state.get(checkpoint_writer_key)
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



        .AUTO_SAVED_ROTATIONS.value



    ),



)







if not st.session_state.get(



    "franchise_auto_manage_policy_migrated_v1",



    False,



):



    if st.session_state.get(



        policy_pref_key



    ) == (



        FranchiseSimulationPolicy



        .STOP_FOR_DECISIONS.value



    ):



        st.session_state[



            policy_pref_key



        ] = (



            FranchiseSimulationPolicy



            .AUTO_SAVED_ROTATIONS.value



        )



        st.session_state[



            policy_widget_key



        ] = (



            FranchiseSimulationPolicy



            .AUTO_SAVED_ROTATIONS.value



        )



    st.session_state[



        "franchise_auto_manage_policy_migrated_v1"



    ] = True







st.markdown(
    (
        '<div class="fm-hero">'
        '<div class="fm-hero-copy">'
        '<div class="fm-eyebrow">MULTI-YEAR FRONT OFFICE MODE</div>'
        '<div class="fm-title">NBA Franchise Mode</div>'
        '</div>'
        '<div class="fm-subtitle">'
        'Run the season, roster, transactions, draft and long-term league from one workspace.'
        '</div>'
        '</div>'
    ),
    unsafe_allow_html=True,
)




notice = st.session_state.pop(



    "franchise_notice",



    None,



)



if notice:
    if str(notice).startswith("Restored the durable Franchise Mode"):
        st.caption(f"✓ {notice}")
    else:
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



    st.caption(f"Autosave checkpoint · {checkpoint_saved_at}")







# FRANCHISE_TRADE_AUTHORITY_V1
# Standalone Trade Machine transactions are sandbox-only and are never offered
# for application to the live franchise.
st.session_state["game_simulator_trade_sync_required"] = False
st.session_state.pop("game_simulator_trade_source_status", None)


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







_perf_stage_v1_7 = time.perf_counter()
event_sync = synchronize_franchise_events(



    state,



    controlled_teams=controlled_teams,



)
_franchise_perf_v1_6["event_sync"] = (
    time.perf_counter() - _perf_stage_v1_7
)



event_sync_marker = getattr(



    state,



    EVENT_SYNC_MARKER_ATTRIBUTE,



    None,



)



event_sync_session_key = (



    "franchise_event_sync_saved_marker"



)



if (
    # FA_OFFSEASON_APPLICATION_BOUNDARY_REPAIR_V1:
    # first render of a restored checkpoint is read-only.
    not checkpoint_restored
    and event_sync_marker is not None
    and st.session_state.get(event_sync_session_key)
    != event_sync_marker
):



    _perf_stage_v1_7 = time.perf_counter()
    event_sync_saved_v1_7 = save_current_franchise_checkpoint(



        state,



        trade_state=trade_state,



        reason="franchise-event-inbox-sync",



        copy_payload=False,



    )
    _franchise_perf_v1_6["event_sync_checkpoint_write"] = (
        time.perf_counter() - _perf_stage_v1_7
    )

    if event_sync_saved_v1_7:
        st.session_state[event_sync_session_key] = event_sync_marker







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











_perf_stage_v1_7 = time.perf_counter()
auto_processed_events = auto_process_routine_franchise_events(



    state,



    policy,



)
_franchise_perf_v1_6["auto_event_processing"] = (
    time.perf_counter() - _perf_stage_v1_7
)



if auto_processed_events and not checkpoint_restored:
    # FA_OFFSEASON_APPLICATION_BOUNDARY_REPAIR_V1:
    # no durable write from automatic housekeeping on clean restore.



    _perf_stage_v1_7 = time.perf_counter()
    save_current_franchise_checkpoint(



        state,



        trade_state=trade_state,



        reason="franchise-auto-managed-routine-events",



        copy_payload=False,



    )
    _franchise_perf_v1_6["auto_event_checkpoint_write"] = (
        time.perf_counter() - _perf_stage_v1_7
    )



    st.session_state["franchise_notice"] = (



        f"Auto-managed {auto_processed_events} routine coaching/medical "



        "notification(s). Significant future decisions will still require you."



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



                f"Create the {state.settings.season_label} schedule"



            )



            st.caption(



                "Installs the validated, realistic "



                "1,230-game generated schedule. It is "



                "not the official NBA schedule."



            )







        with schedule_columns[1]:



            generate_clicked = st.button(



                f"Generate {state.settings.season_label} schedule",



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



                f"{state.settings.season_label} "



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








# FRANCHISE PERFORMANCE V1.6: cache global read-only views that were being
# recomputed before every workspace render.
def _franchise_view_signature_v1_6(
    state: SimulationLeagueState,
    team: str,
) -> tuple[Any, ...]:
    resolved = str(team).strip().upper()
    standing = state.standings[resolved]
    team_state = state.teams[resolved]
    return (
        id(state),
        state.settings.season_label,
        str(getattr(state.phase, "value", state.phase)),
        resolved,
        int(standing.wins),
        int(standing.losses),
        int(standing.points_for),
        int(standing.points_against),
        len(state.completed_games),
        int(getattr(state, "franchise_trade_revision_v1", 0) or 0),
        tuple(team_state.roster_player_ids),
        tuple(team_state.rotation.rotation_player_ids),
    )


def _cached_team_snapshot_v1_6(
    state: SimulationLeagueState,
    team: str,
) -> Any:
    signature = _franchise_view_signature_v1_6(state, team)
    cache = st.session_state.get("_franchise_team_snapshot_cache_v1_6")
    if isinstance(cache, dict) and cache.get("signature") == signature:
        return cache["value"]
    value = build_team_snapshot(state, team)
    st.session_state["_franchise_team_snapshot_cache_v1_6"] = {
        "signature": signature,
        "value": value,
    }
    return value


def _cached_stat_health_v1_6(
    state: SimulationLeagueState,
) -> dict[str, float | bool]:
    signature = (
        id(state),
        state.settings.season_label,
        len(state.completed_games),
        int(getattr(state, "franchise_trade_revision_v1", 0) or 0),
    )
    cache = st.session_state.get("_franchise_stat_health_cache_v1_6")
    if isinstance(cache, dict) and cache.get("signature") == signature:
        return dict(cache["value"])
    value = season_stat_contamination(state)
    st.session_state["_franchise_stat_health_cache_v1_6"] = {
        "signature": signature,
        "value": dict(value),
    }
    return value


_perf_stage_v1_6 = time.perf_counter()
snapshot = _cached_team_snapshot_v1_6(



    state,



    active_team,



)
_franchise_perf_v1_6["team_snapshot"] = (
    time.perf_counter() - _perf_stage_v1_6
)



primary, secondary = team_colors(



    active_team



)



games_played = (



    int(snapshot.wins)



    + int(snapshot.losses)



)



has_played_games = games_played > 0



conference_rank_copy = (



    f"Conference rank #{snapshot.conference_rank}"



    if has_played_games



    else "Conference rank —"



)



conference_metric_value = (



    f"#{snapshot.conference_rank}"



    if has_played_games



    else "—"



)



league_metric_value = (



    f"#{snapshot.league_rank}"



    if has_played_games



    else "—"



)



next_copy = (



    (



        f"{snapshot.next_location} vs "



        f"{snapshot.next_opponent} · "



        f"{snapshot.next_game_date}"



    )



    if snapshot.next_game_id



    else (



        f"Generate the {state.settings.season_label} schedule"



        if not state.schedule



        else "Regular season complete"



    )



)







st.markdown(



    (



        "<style>:root{"



        f"--team-primary:{escaped(primary)};"



        f"--team-secondary:{escaped(secondary)};"



        "}</style>"



    ),



    unsafe_allow_html=True,



)



_perf_stage_v1_7 = time.perf_counter()
render_team_hero(



    state,



    snapshot,



    active_team,



    primary=primary,



    secondary=secondary,



    next_copy=next_copy,



)
_franchise_perf_v1_6["team_hero"] = (
    time.perf_counter() - _perf_stage_v1_7
)







_perf_stage_v1_6 = time.perf_counter()
stat_health = _cached_stat_health_v1_6(



    state



)
_franchise_perf_v1_6["stat_health"] = (
    time.perf_counter() - _perf_stage_v1_6
)







if bool(stat_health["contaminated"]):



    st.warning(
        "Legacy test-season statistics detected. Reset this season before judging "
        "the current scoring/minutes engine."
    )
    with st.expander("Why this season is flagged", expanded=False):
        st.write(
            "The active season contains box scores produced by the previous scoring "
            "and minutes allocator, so those historical results cannot be repaired in place. "
            f"Current maxima: {stat_health['maximum_ppg']:.1f} PPG, "
            f"{stat_health['maximum_mpg']:.1f} MPG, high-workload minute standard "
            f"deviation {stat_health['high_minute_standard_deviation']:.2f}."
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



                f"Started a clean {state.settings.season_label} "



                "season using "



                f"{ENGINE_VERSION} and "



                f"{MINUTES_MODEL_VERSION}."



            )



            st.rerun()







pending_section = st.session_state.pop(



    "franchise_pending_section",



    None,



)



_franchise_phase_name = str(
    getattr(getattr(state, "phase", None), "value", getattr(state, "phase", ""))
).strip().lower()

if _franchise_phase_name == "offseason":
    _franchise_visible_sections = (
        "Command Center",
        "Team Management",
        "Staff",
        "Free Agency",
        "Trade Center",
        "Draft Room",
        "League & Offseason",
        "Stats & Standings",
        "Inbox & League Health",
        "Calendar",
    )
else:
    _franchise_visible_sections = tuple(
        section
        for section in FRANCHISE_SECTIONS
        if section != "Free Agency"
    )

if pending_section in _franchise_visible_sections:



    st.session_state[FRANCHISE_SECTION_KEY] = (



        pending_section



    )







if (



    st.session_state.get(FRANCHISE_SECTION_KEY)



    not in _franchise_visible_sections



):



    st.session_state[FRANCHISE_SECTION_KEY] = (



        "Command Center"



    )







active_section = st.radio(



    "Franchise workspace",



    options=_franchise_visible_sections,



    horizontal=True,



    label_visibility="collapsed",



    format_func=lambda section: (



        FRANCHISE_SECTION_DISPLAY.get(



            section,



            section,



        )



    ),



    key=FRANCHISE_SECTION_KEY,



)



render_franchise_section_guide(active_section)

_franchise_perf_v1_6["page_to_workspace"] = (
    time.perf_counter() - _franchise_page_started_at_v1_6
)
with st.expander("Performance diagnostics", expanded=False):
    st.caption(
        "V1.7 deep startup profile. A first cold Franchise open is the most useful sample."
    )

    row1 = st.columns(4)
    row1[0].metric("Startup to workspace", f"{_franchise_perf_v1_6.get('page_to_workspace', 0.0):.2f}s")
    row1[1].metric("Imports + page setup", f"{_franchise_perf_v1_6.get('imports_and_page_setup', 0.0):.2f}s")
    row1[2].metric("Runtime data", f"{_franchise_perf_v1_6.get('runtime', 0.0):.2f}s")
    row1[3].metric("Checkpoint restore", f"{_franchise_perf_v1_6.get('checkpoint_restore', 0.0):.2f}s")

    row2 = st.columns(4)
    row2[0].metric("Trade state", f"{_franchise_perf_v1_6.get('trade_state', 0.0):.3f}s")
    row2[1].metric("Franchise state checks", f"{_franchise_perf_v1_6.get('franchise_state', 0.0):.3f}s")
    row2[2].metric("Career metadata", f"{_franchise_perf_v1_6.get('career_metadata', 0.0):.3f}s")
    row2[3].metric("Health ensure", f"{_franchise_perf_v1_6.get('injury_fatigue_ensure', 0.0):.3f}s")

    row3 = st.columns(4)
    row3[0].metric("Event sync", f"{_franchise_perf_v1_6.get('event_sync', 0.0):.3f}s")
    row3[1].metric("Event checkpoint write", f"{_franchise_perf_v1_6.get('event_sync_checkpoint_write', 0.0):.2f}s")
    row3[2].metric("Team snapshot", f"{_franchise_perf_v1_6.get('team_snapshot', 0.0):.3f}s")
    row3[3].metric("Team hero", f"{_franchise_perf_v1_6.get('team_hero', 0.0):.3f}s")

    tracked_v1_7 = sum(
        float(_franchise_perf_v1_6.get(key, 0.0) or 0.0)
        for key in (
            "imports_and_page_setup",
            "runtime",
            "checkpoint_restore",
            "trade_state",
            "franchise_state",
            "career_metadata",
            "injury_fatigue_ensure",
            "event_sync",
            "event_sync_checkpoint_write",
            "auto_event_processing",
            "auto_event_checkpoint_write",
            "team_snapshot",
            "stat_health",
            "team_hero",
        )
    )
    unattributed_v1_7 = max(
        0.0,
        float(_franchise_perf_v1_6.get("page_to_workspace", 0.0)) - tracked_v1_7,
    )
    st.caption(
        "Auto-event processing: "
        f"{_franchise_perf_v1_6.get('auto_event_processing', 0.0):.3f}s · "
        "Auto-event checkpoint write: "
        f"{_franchise_perf_v1_6.get('auto_event_checkpoint_write', 0.0):.2f}s · "
        "Stat-health scan: "
        f"{_franchise_perf_v1_6.get('stat_health', 0.0):.3f}s · "
        "Remaining unattributed page work: "
        f"{unattributed_v1_7:.2f}s"
    )
    st.caption(
        "V1.7 seeds the event-inbox persistence marker from the restored checkpoint. "
        "A new Streamlit session will not rewrite the full checkpoint unless event state actually changed."
    )


if active_section == "Command Center":



    metrics = st.columns(6)



    metrics[0].metric(



        "Record",



        f"{snapshot.wins}-{snapshot.losses}",



    )



    metrics[1].metric(



        "Conference",



        conference_metric_value,



    )



    metrics[2].metric(



        "League",



        league_metric_value,



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







    health_summary = team_health_summary(



        state,



        active_team,



        day_index=(



            snapshot.next_game_day



            if snapshot.next_game_day is not None



            else state.current_day_index



        ),



    )



    health_metrics = st.columns(5)



    health_metrics[0].metric(



        "Available",



        health_summary["available"],



        help=(



            "Players currently eligible for automatic "



            "game rotations."



        ),



    )



    health_metrics[1].metric(



        "Unavailable",



        health_summary["out"],



        help=(



            "Players listed Out or Doubtful by the "



            "simulation medical model."



        ),



    )



    health_metrics[2].metric(



        "Limited",



        health_summary["limited"],



        help=(



            "Players who can appear but may have a "



            "performance or minutes restriction."



        ),



    )



    health_metrics[3].metric(



        "High workload risk",



        health_summary["high_risk"],



        help=(



            "Elevated modeled risk from fatigue, schedule "



            "density, recent minutes, age, and durability."



        ),



    )



    health_metrics[4].metric(



        "Current team fatigue",



        f"{health_summary['average_fatigue']:.1f}/100",



        delta=(



            "Next game "



            f"{health_summary['projected_average_fatigue']:.1f}/100"



        ),



        delta_color="off",



        help=(



            "Current stored workload is shown first. The delta is the "



            "projected level after scheduled recovery before the next game."



        ),



    )







    unread_count = len(unread_events(state))



    blocking_count = len(blocking_events(state))



    inbox_columns = st.columns([1, 1, 3])



    inbox_columns[0].metric(



        "Unread decisions",



        unread_count,



    )



    inbox_columns[1].metric(



        "Simulation blockers",



        blocking_count,



    )



    if inbox_columns[2].button(



        "Open decision inbox",



        type=("primary" if blocking_count else "secondary"),



        width="stretch",



        key="franchise_open_inbox",



    ):



        set_franchise_section("Inbox & League Health")



        st.rerun()







    if blocking_count:



        st.error(



            f"{blocking_count} unresolved decision(s) are pausing "



            "league advancement. Open the inbox and acknowledge "



            "the required action before simulating more games."



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



                or bool(blocking_events(state))



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



                or bool(blocking_events(state))



            ),



            key="franchise_next_week",



        )



        season_end_clicked = advance_columns[



            2



        ].button(



            "Sim regular season",



            type="primary",



            width="stretch",



            disabled=(



                not full_schedule_active



                or trade_sync_required



                or bool(blocking_events(state))



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



                    auto_postseason_created = False



                    if (



                        regular_season_is_complete(updated)



                        and get_postseason_state(



                            updated,



                            required=False,



                        ) is None



                    ):



                        initialize_postseason(updated)



                        auto_postseason_created = True







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







            action_columns[1].caption(



                "Use Game Day for franchise games. "



                "Standalone Game Simulator is a sandbox."



            )







if active_section == "Inbox & League Health":



    audit = league_health_audit(state)



    inbox = franchise_events(state)



    blockers = blocking_events(state)



    unread = unread_events(state)







    st.subheader("Decision Inbox")



    st.caption(



        "This is the shared interruption layer for medical decisions, "



        "future AI trade offers, scouting updates, contract deadlines, "



        "staff decisions, and draft-night events. Blocking items pause "



        "league advancement until they are resolved."



    )







    inbox_metrics = st.columns(5)



    inbox_metrics[0].metric("Unread", len(unread))



    inbox_metrics[1].metric("Blocking", len(blockers))



    inbox_metrics[2].metric("Active injuries", audit.active_injuries)



    inbox_metrics[3].metric("Injury events", audit.injury_events)



    inbox_metrics[4].metric(



        "Max fatigue",



        f"{audit.maximum_fatigue:.1f}/100",



    )







    if blockers:



        st.error(



            "Simulation is paused by unresolved decisions. Resolve the "



            "blocking items below before advancing the calendar."



        )







    inbox_filter = st.segmented_control(



        "Inbox filter",



        options=["Open", "Unread", "Blocking", "All"],



        default="Open",



        key="franchise_inbox_filter",



    )



    if inbox_filter == "Unread":



        visible_events = unread



    elif inbox_filter == "Blocking":



        visible_events = blockers



    elif inbox_filter == "All":



        visible_events = inbox



    else:



        visible_events = franchise_events(



            state,



            statuses={"unread", "read"},



        )







    if not visible_events:



        st.success("No events match this inbox filter.")



    else:



        for event in visible_events[:60]:



            card_class = (



                "blocking"



                if event.get("blocking")



                else "warning"



                if event.get("severity") in {"warning", "critical"}



                else "info"



            )



            st.markdown(



                (



                    f'<div class="fm-inbox-card {card_class}">'



                    f'<div class="fm-inbox-title">{escaped(event["title"])}</div>'



                    f'<div class="fm-inbox-meta">Day {event["created_day"]} · '



                    f'{escaped(event["category"])} · {escaped(event["status"].title())} · '



                    f'{"BLOCKING" if event["blocking"] else "Informational"}</div>'



                    f'<div class="fm-inbox-detail">{escaped(event["detail"])}</div>'



                    '</div>'



                ),



                unsafe_allow_html=True,



            )



            action_columns = st.columns([1, 1, 1, 3])



            if action_columns[0].button(



                "Mark read",



                key=f"event_read_{event['event_id']}",



                disabled=event["status"] != "unread",



                width="stretch",



            ):



                mark_event_read(state, event["event_id"])



                save_current_franchise_checkpoint(



                    state,



                    reason="event-mark-read",



                    copy_payload=False,



                )



                st.rerun()



            if action_columns[1].button(



                "Resolve",



                type=("primary" if event["blocking"] else "secondary"),



                key=f"event_resolve_{event['event_id']}",



                disabled=event["status"] in {"resolved", "expired"},



                width="stretch",



            ):



                resolve_event(state, event["event_id"])



                save_current_franchise_checkpoint(



                    state,



                    reason="event-resolved",



                    copy_payload=False,



                )



                st.rerun()



            if action_columns[2].button(



                "Open area",



                key=f"event_open_{event['event_id']}",



                width="stretch",



            ):



                mark_event_read(state, event["event_id"])



                set_franchise_section(event["action_section"])



                save_current_franchise_checkpoint(



                    state,



                    reason="event-open-destination",



                    copy_payload=False,



                )



                st.rerun()



            action_columns[3].caption(



                f"Destination: {event['action_section']}"



            )







    if st.button(



        "Resolve all informational items",



        key="franchise_resolve_nonblocking",



        disabled=not any(not event["blocking"] for event in visible_events),



    ):



        resolved_count = resolve_all_nonblocking(state)



        save_current_franchise_checkpoint(



            state,



            reason="event-bulk-resolve",



            copy_payload=False,



        )



        st.session_state["franchise_notice"] = (



            f"Resolved {resolved_count} informational inbox item(s)."



        )



        st.rerun()







    st.markdown(



        '<div class="fm-section">League health audit</div>',



        unsafe_allow_html=True,



    )



    status_class = (



        "fm-health-warning"



        if audit.overall_status != "plausible"



        else "fm-health-ok"



    )



    st.markdown(



        (



            f'<div class="{status_class}"><strong>'



            f'{escaped(audit.overall_status.replace("_", " ").title())}</strong><br>'



            f'{escaped(audit.explanation)}</div>'



        ),



        unsafe_allow_html=True,



    )



    audit_metrics = st.columns(6)



    audit_metrics[0].metric("Avg team GP", f"{audit.average_team_games:.1f}")



    audit_metrics[1].metric("Player-games", audit.player_games)



    audit_metrics[2].metric("Observed events", audit.injury_events)



    audit_metrics[3].metric("Base expected", f"{audit.expected_base_events:.1f}")



    audit_metrics[4].metric("Unavailable", audit.unavailable_players)



    audit_metrics[5].metric("Games missed", audit.games_missed_recorded)







    health_export_columns = st.columns(2)



    availability_audit_rows = player_availability_audit_rows(state)



    injury_history_export_rows = injury_event_history_rows(state)



    health_export_columns[0].download_button(



        "Download availability & injury realism CSV",



        data=rows_to_csv_bytes(availability_audit_rows),



        file_name=f"franchise_health_realism_{state.settings.season_label}.csv",



        mime="text/csv",



        key="download_franchise_health_realism_csv",



        width="stretch",



    )



    health_export_columns[1].download_button(



        "Download injury event history CSV",



        data=rows_to_csv_bytes(injury_history_export_rows),



        file_name=f"franchise_injury_events_{state.settings.season_label}.csv",



        mime="text/csv",



        key="download_franchise_injury_events_csv",



        width="stretch",



        disabled=not injury_history_export_rows,



    )



    st.caption(



        "The availability export is designed for realism review. At a completed "



        "regular season, games_not_played_reference uses the exact 82-game "



        "reference-team game count. During an in-progress season, use the "



        "engine-tracked medical_games_missed_recorded column for the cleanest "



        "medical-only diagnostic."



    )







    health_tabs = st.tabs([



        "Active injuries",



        "Team health",



        "Audit details",



        "Interruption settings",



    ])



    with health_tabs[0]:



        injury_frame = pd.DataFrame(active_injury_rows(state))



        if injury_frame.empty:



            st.info(



                "No player in the current league state is listed with an active injury. "



                "The audit above distinguishes a genuinely healthy moment from an injury "



                "engine that has been too quiet over a larger sample."



            )



        else:



            st.dataframe(injury_frame, hide_index=True, width="stretch")



    with health_tabs[1]:



        team_health_frame = pd.DataFrame(team_health_rows(state)).rename(



            columns={



                "team": "Team",



                "games": "GP",



                "active_injuries": "Active injuries",



                "unavailable": "Unavailable",



                "elevated_high_risk": "Elevated/high risk",



                "average_fatigue": "Current avg fatigue",



                "maximum_fatigue": "Current max fatigue",



                "projected_average_fatigue": "Pregame avg fatigue",



                "projected_maximum_fatigue": "Pregame max fatigue",



                "projection_day": "Next game day",



            }



        )



        st.caption(



            "Current fatigue is stored workload now. Pregame fatigue applies "



            "scheduled recovery through each team's next game day."



        )



        st.dataframe(



            team_health_frame,



            hide_index=True,



            width="stretch",



        )



    with health_tabs[2]:



        st.json({



            "audit_version": LEAGUE_HEALTH_AUDIT_VERSION,



            "event_engine_version": FRANCHISE_EVENT_VERSION,



            "injury_frequency": audit.injury_frequency_status,



            "fatigue_calibration": audit.fatigue_calibration_status,



            "event_frequency_ratio": audit.event_frequency_ratio,



            "heavy_workload_players": audit.heavy_workload_players,



            "heavy_workload_low_fatigue_players": audit.heavy_workload_low_fatigue_players,



            "heavy_workload_low_fatigue_share": audit.heavy_workload_low_fatigue_share,



            "back_to_back_events": audit.back_to_back_events,



            "major_events": audit.major_events,



        })



    with health_tabs[3]:



        current_settings = event_settings(state)



        setting_labels = {



            "pause_on_controlled_injury": "Pause for injuries on user-controlled teams",



            "pause_on_high_workload": "Pause for elevated/high workload warnings",



            "pause_on_health_calibration": "Pause at league-health calibration checkpoints",



            "show_ai_injuries": "Show injuries from AI-controlled teams",



            "show_high_workload_alerts": "Create high-workload inbox alerts",



            "show_health_milestones": "Create 10/20/40/82-game health audits",



        }



        changed_settings = {}



        for setting_key, label in setting_labels.items():



            changed_settings[setting_key] = st.toggle(



                label,



                value=current_settings[setting_key],



                key=f"event_setting_{setting_key}",



            )



        if changed_settings != current_settings:



            update_event_settings(state, **changed_settings)



            synchronize_franchise_events(



                state,



                controlled_teams=controlled_teams,



            )



            save_current_franchise_checkpoint(



                state,



                reason="event-settings-update",



                copy_payload=False,



            )



            st.rerun()







if active_section == "Calendar":



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



                set_franchise_section("Game Day")



                st.rerun()







if active_section == "Team Management":



    render_franchise_core(



        state,



        active_team,



        title="Franchise core",



    )



    st.subheader(



        f"{team_name(active_team)} Health & Load Center"



    )



    st.caption(



        "The medical model combines recent minutes, fatigue, "



        "back-to-backs, schedule density, age, durability, and "



        "existing injuries. These are simulation probabilities, "



        "not real-world medical predictions."



    )



    health_rows = player_health_report_rows(



        state,



        active_team,



    )



    health_frame = pd.DataFrame(



        health_rows



    )



    health_cards = team_health_summary(



        state,



        active_team,



    )



    medical_metrics = st.columns(6)



    medical_metrics[0].metric(



        "Available",



        health_cards["available"],



    )



    medical_metrics[1].metric(



        "Unavailable",



        health_cards["out"],



    )



    medical_metrics[2].metric(



        "Medical limits",



        health_cards["limited"],



        help="Players carrying a playable injury status or medical restriction.",



    )



    medical_metrics[3].metric(



        "Rehab / return",



        health_cards.get("rehab_or_return", 0),



        help="Players in acute rehab, return-to-play testing, or a minutes ramp.",



    )



    medical_metrics[4].metric(



        "Elevated / high",



        health_cards["high_risk"],



    )



    medical_metrics[5].metric(



        "Current max fatigue",



        f"{health_cards['maximum_fatigue']:.1f}/100",



        delta=(



            f"Pregame {health_cards['projected_maximum_fatigue']:.1f}"



        ),



        help=(



            "Current stored workload is shown first. The delta is projected "



            "fatigue after recovery through the next scheduled team game."



        ),



    )



    st.caption(



        f"Medical engine: {MEDICAL_INJURY_V2_VERSION}. "



        "Recovery timelines use calendar days and the installed NBA schedule, "



        "then return players through a staged minutes ramp rather than clearing "



        "them instantly on one date."



    )



    with st.expander(



        "How fatigue, rehab, and injury risk work",



        expanded=False,



    ):



        st.markdown(



            """



**Fatigue** rises with playing time, overtime, and games on



consecutive days. Current fatigue reflects recovery through today, while



pregame fatigue includes any additional rest before the next scheduled game.







**Medical cases** now move through acute care, rehab, return-to-play,



and a short return ramp. Moderate and major injuries must reach the return



window before a player can become Questionable or Probable. Cleared players



can still carry a small history-based recurrence modifier later in the season.







**Setbacks and recurrence** are modeled separately from ordinary new injuries.



A player who is already limited or returning has more aggravation risk, and a



same-region event is tracked as a recurrence/setback rather than being treated



as unrelated.







**Availability** still drives the simulator. Out and Doubtful players are



removed automatically. Questionable and Probable players can play with a



performance effect or a medical minutes cap.







These are franchise-simulation probabilities, not real-world medical



predictions. Every risk row still exposes the workload explanation used by the



model.



            """



        )



    medical_columns = [



        "player",



        "position",



        "age",



        "status",



        "injury",



        "body_region",



        "injury_grade",



        "medical_phase",



        "recovery_progress",



        "expected_return_day",



        "minutes_limit",



        "reinjury_risk",



        "current_fatigue",



        "projected_fatigue",



        "risk",



        "risk_probability",



        "planned_minutes",



        "recent_minutes",



        "games_missed",



        "recurrence_count",



        "setback_count",



        "explanation",



    ]



    st.dataframe(



        health_frame.reindex(columns=medical_columns),



        hide_index=True,



        width="stretch",



        column_config={



            "player": "Player",



            "position": "Pos",



            "age": st.column_config.NumberColumn(



                "Age",



                format="%.0f",



                help=(



                    "Live franchise age for the active season. "



                    "It advances during each committed season transition."



                ),



            ),



            "status": "Status",



            "injury": "Injury",



            "body_region": "Region",



            "injury_grade": "Grade",



            "medical_phase": "Medical phase",



            "recovery_progress": st.column_config.ProgressColumn(



                "Recovery %",



                min_value=0.0,



                max_value=100.0,



                format="%.0f%%",



                help="Calendar-based progress through the current medical timeline.",



            ),



            "expected_return_day": st.column_config.NumberColumn(



                "Return day",



                format="%d",



                help="Current modeled return-to-play target day, not a guarantee of full clearance.",



            ),



            "minutes_limit": st.column_config.NumberColumn(



                "Medical cap",



                format="%.1f",



                help="Maximum minutes allowed by the active medical case when restricted.",



            ),



            "reinjury_risk": st.column_config.NumberColumn(



                "Reinjury %",



                format="%.1f%%",



                help="Medical aggravation/recurrence estimate while an injury case remains active.",



            ),



            "current_fatigue": st.column_config.ProgressColumn(



                "Current fatigue",



                min_value=0.0,



                max_value=100.0,



                format="%.1f",



                help=(



                    "Stored workload immediately after the latest processed "



                    "game day. This does not disappear merely because the next "



                    "game is several days away."



                ),



            ),



            "projected_fatigue": st.column_config.ProgressColumn(



                "Pregame fatigue",



                min_value=0.0,



                max_value=100.0,



                format="%.1f",



                help=(



                    "Projected workload after scheduled recovery before the "



                    "next team game. Injury risk uses this value."



                ),



            ),



            "risk": "Risk tier",



            "risk_probability": st.column_config.NumberColumn(



                "Game injury risk %",



                format="%.2f%%",



                help="Modeled probability for the player's next scheduled game.",



            ),



            "planned_minutes": st.column_config.NumberColumn(



                "Planned MIN",



                format="%.1f",



            ),



            "recent_minutes": st.column_config.NumberColumn(



                "Last 4 MIN",



                format="%.1f",



            ),



            "games_missed": "Games missed",



            "recurrence_count": "Same-region recurrences",



            "setback_count": "Setbacks",



            "explanation": st.column_config.TextColumn(



                "Why",



                width="large",



            ),



        },



    )











    current_team_events = [



        event



        for event in reversed(



            health_events(state)



        )



        if (



            event.get("season_label")



            == state.settings.season_label



            and event.get("team")



            == active_team



        )



    ]



    with st.expander(



        "Recent medical events",



        expanded=False,



    ):



        if current_team_events:



            recent_medical_columns = [



                "day_index",



                "player_name",



                "event_kind",



                "injury_type",



                "body_region",



                "injury_grade",



                "severity",



                "status",



                "estimated_games_missed",



                "recurrence_count",



                "setback_count",



                "fatigue_before_game",



                "minutes_played",



                "back_to_back",



                "explanation",



            ]



            st.dataframe(



                pd.DataFrame(



                    current_team_events[:20]



                ).reindex(columns=recent_medical_columns),



                hide_index=True,



                width="stretch",



                column_config={



                    "day_index": "Day",



                    "player_name": "Player",



                    "event_kind": "Event",



                    "injury_type": "Injury",



                    "body_region": "Region",



                    "injury_grade": "Grade",



                    "severity": "Severity",



                    "status": "Status",



                    "recurrence_count": "Recurrences",



                    "setback_count": "Setbacks",



                    "estimated_games_missed": (



                        "Est. games missed"



                    ),



                    "fatigue_before_game": (



                        "Pregame fatigue"



                    ),



                    "minutes_played": "Minutes",



                    "back_to_back": "Back-to-back",



                    "explanation": (



                        st.column_config.TextColumn(



                            "Why",



                            width="large",



                        )



                    ),



                },



            )



        else:



            st.info(



                "No injury events have been recorded "



                "for this team this season."



            )







    st.divider()



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



            "fatigue",



            "injury_risk",



            "recent_minutes",



            "medical_note",



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



            "fatigue",



            "injury_risk",



            "recent_minutes",



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



            "availability": "Medical status",



            "fatigue": (



                st.column_config.ProgressColumn(



                    "Fatigue",



                    min_value=0.0,



                    max_value=100.0,



                    format="%.1f",



                )



            ),



            "injury_risk": "Risk",



            "recent_minutes": (



                st.column_config.NumberColumn(



                    "Last 4 MIN",



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







if active_section == "Staff":
    render_franchise_staff_center_v1(
        state,
        active_team=active_team,
        controlled_teams=controlled_teams,
    )



if active_section == "Game Day":



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







            st.markdown("### Pregame Health Brief")



            st.caption(



                "Risk is recalculated for this exact game day, "



                "so a back-to-back can change the recommendation."



            )



            matchup_health = []



            for matchup_team in (



                current_game.away_team,



                current_game.home_team,



            ):



                matchup_health.extend(



                    player_health_report_rows(



                        state,



                        matchup_team,



                        day_index=(



                            current_game.day_index



                        ),



                    )



                )



            elevated_health = [



                row



                for row in matchup_health



                if (



                    row["status"] != "Healthy"



                    or row["risk"]



                    in {



                        "High",



                        "Elevated",



                    }



                    or float(



                        row["fatigue"]



                    )



                    >= 60.0



                )



            ]



            if elevated_health:



                st.dataframe(



                    pd.DataFrame(



                        elevated_health



                    )[



                        [



                            "player",



                            "status",



                            "fatigue",



                            "risk",



                            "planned_minutes",



                            "explanation",



                        ]



                    ],



                    hide_index=True,



                    width="stretch",



                )



            else:



                st.success(



                    "No elevated medical or workload flags "



                    "for this matchup."



                )







            recommended_sit = tuple(



                dict.fromkeys(



                    (



                        *recommended_rest_player_ids(



                            state,



                            current_game.away_team,



                            day_index=(



                                current_game.day_index



                            ),



                        ),



                        *recommended_rest_player_ids(



                            state,



                            current_game.home_team,



                            day_index=(



                                current_game.day_index



                            ),



                        ),



                    )



                )



            )



            if recommended_sit:



                st.warning(



                    "Load-management suggestion: "



                    + ", ".join(



                        state.players[



                            player_id



                        ].player_name



                        for player_id



                        in recommended_sit



                    )



                    + ". This is optional and based on "



                    "modeled workload risk."



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



                help=(



                    "Resting a player prevents game fatigue and "



                    "injury exposure, but may reduce your chance "



                    "of winning this matchup."



                ),



                format_func=lambda player_id: (



                    f"{state.players[player_id].player_name} "



                    f"({state.players[player_id].team_abbreviation})"



                ),



                key=(



                    f"franchise_sit_"



                    f"{current_game.game_id}"



                ),



            )



            render_latest_committed_game(state)







            st.markdown("### Lock game plan")



            st.caption(



                "The main simulation is one-way, like a franchise game. "



                "Once started, the result is committed to the season before "



                "the final score is revealed."



            )



            play_columns = st.columns([1.1, 2.2])



            simulate_commit_clicked = play_columns[0].button(



                "Simulate game",



                type="primary",



                width="stretch",



                disabled=(



                    trade_sync_required



                    or bool(blocking_events(state))



                ),



                key=(



                    "franchise_simulate_commit_"



                    f"{current_game.game_id}"



                ),



            )



            play_columns[1].caption(



                "Uses the selected rest decisions, commits the game, "



                "then reveals the result and loads the next matchup."



            )







            if simulate_commit_clicked:



                try:



                    updated, committed = (



                        commit_game_transactionally(



                            state,



                            current_game.game_id,



                            sit_player_ids=tuple(sit_ids),



                        )



                    )



                    set_franchise_state(updated)



                except (



                    FranchiseCommandCenterError,



                    SingleGameSimulationError,



                    SimulationLeagueStateError,



                ) as exc:



                    st.error(str(exc))



                else:



                    clear_game_day_preview()



                    remember_committed_game_result(



                        current_game.game_id



                    )



                    next_games = upcoming_controlled_games(



                        updated,



                        controlled_teams,



                    )



                    if next_games:



                        set_selected_game(



                            next_games[0].game_id



                        )



                    st.session_state[



                        "franchise_notice"



                    ] = (



                        "Game committed. The final result is "



                        "ready in Game Day, and the next controlled "



                        "matchup has been loaded."



                    )



                    st.rerun()







            current_preview_request = {



                "game_id": current_game.game_id,



                "sit_ids": tuple(sorted(sit_ids)),



                "fingerprint": (



                    regular_season_state_fingerprint(state)



                ),



            }



            stored_preview = st.session_state.get(



                "franchise_game_preview"



            )



            stored_request = st.session_state.get(



                "franchise_game_preview_request"



            )



            if (



                stored_preview is not None



                and stored_request



                != current_preview_request



            ):



                clear_game_day_preview()



                stored_preview = None



                stored_request = None







            with st.expander(



                "Advanced What-If Lab",



                expanded=False,



            ):



                st.caption(



                    "This optional sandbox does not affect the season. "



                    "Use it to compare a lineup or rest decision. Changing "



                    "the selected players immediately invalidates the old result."



                )



                what_if_clicked = st.button(



                    "Run what-if simulation",



                    width="stretch",



                    disabled=trade_sync_required,



                    key=(



                        "franchise_what_if_"



                        f"{current_game.game_id}"



                    ),



                )



                if what_if_clicked:



                    try:



                        stored_preview = simulate_scheduled_game(



                            state,



                            current_game.game_id,



                            commit=False,



                            sit_player_ids=tuple(sit_ids),



                        )



                    except (



                        SingleGameSimulationError,



                        SimulationLeagueStateError,



                    ) as exc:



                        st.error(str(exc))



                    else:



                        st.session_state[



                            "franchise_game_preview"



                        ] = stored_preview



                        st.session_state[



                            "franchise_game_preview_request"



                        ] = current_preview_request



                        stored_request = current_preview_request







                if (



                    stored_preview is not None



                    and stored_request



                    == current_preview_request



                ):



                    completed = stored_preview.game



                    st.info(



                        "What-if result only. It has not been added "



                        "to standings, stats, fatigue, or injuries."



                    )



                    score_columns = st.columns([1, 1, 1])



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



                        box_score_dataframe(state, completed),



                        hide_index=True,



                        width="stretch",



                    )



                    if (



                        stored_preview.health_update is not None



                        and stored_preview.health_update.injury_events



                    ):



                        st.warning(



                            "Sandbox medical outcome. This event is not saved."



                        )



                        st.dataframe(



                            pd.DataFrame(



                                [



                                    {



                                        "Player": event.player_name,



                                        "Team": event.team,



                                        "Injury": event.injury_type,



                                        "Severity": event.severity.title(),



                                        "Status": event.status



                                        .replace("_", " ")



                                        .title(),



                                        "Estimated Games": (



                                            event.estimated_games_missed



                                        ),



                                        "Why": event.explanation,



                                    }



                                    for event in stored_preview



                                    .health_update.injury_events



                                ]



                            ),



                            hide_index=True,



                            width="stretch",



                        )







if active_section == "Stats & Standings":



    render_franchise_core(



        state,



        active_team,



        title="Team spotlight",



    )



    standings_tabs = st.tabs(



        [



            "Eastern Conference",



            "Western Conference",



            "League",



            "Regular Season Leaders",



            "Playoff Leaders",



            "Playoff Teams",



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



        st.caption(



            "Regular-season statistics only. Shooting-volume columns are per-game averages; FG%, 3P%, FT%, eFG%, and TS% are calculated from season totals. Playoff games are tracked separately."



        )



        st.dataframe(



            pd.DataFrame(



                regular_season_player_rows(



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







    with standings_tabs[4]:



        postseason = get_postseason_state(



            state,



            required=False,



        )



        if postseason is None:



            st.info(



                "Playoff player statistics will appear after the postseason bracket is created and First Round games are completed."



            )



        else:



            playoff_leaders = postseason_player_rows(



                state,



                minimum_games=1,



                limit=50,



                include_play_in=False,



            )



            if playoff_leaders:



                st.caption(



                    "Playoff statistics only: First Round through NBA Finals. Play-In games are excluded."



                )



                st.dataframe(



                    pd.DataFrame(



                        playoff_leaders



                    ),



                    hide_index=True,



                    width="stretch",



                )



            else:



                st.info(



                    "Playoff player statistics will appear after the first completed First Round game. Play-In games are excluded."



                )







    with standings_tabs[5]:



        postseason = get_postseason_state(



            state,



            required=False,



        )



        if postseason is None:



            st.info(



                "Playoff team results will appear after the postseason bracket is created and First Round games are completed."



            )



        else:



            playoff_teams = postseason_team_rows(



                state,



                include_play_in=False,



                limit=30,



            )



            if playoff_teams:



                st.caption(



                    "Playoff team results only: First Round through NBA Finals. Play-In games are excluded."



                )



                st.dataframe(



                    pd.DataFrame(



                        playoff_teams



                    ),



                    hide_index=True,



                    width="stretch",



                )



            else:



                st.info(



                    "Playoff team results will appear after the first completed First Round game. Play-In games are excluded."



                )







if active_section == "Free Agency":
    # FRANCHISE_EMBEDDED_FREE_AGENCY_V1
    from franchise_free_agency_workspace_v1 import (
        render_free_agency_workspace,
    )

    try:
        _fa_checkpoint = load_franchise_checkpoint(
            allow_backup=False,
        )
    except TypeError:
        _fa_checkpoint = load_franchise_checkpoint()
    except Exception as exc:
        st.error(
            "The live Free Agency workspace could not load the durable "
            f"franchise checkpoint. Detail: {exc}"
        )
        _fa_checkpoint = None

    if _fa_checkpoint is None:
        st.warning(
            "The live franchise checkpoint is unavailable. "
            "Free Agency cannot open safely."
        )
    else:
        render_free_agency_workspace(
            checkpoint_override=_fa_checkpoint,
            active_team_override=active_team,
            controlled_teams_override=controlled_teams,
            embedded=True,
        )



if active_section == "Trade Center":
    # FRANCHISE_TRADE_AUTHORITY_V1
    st.caption(
        "This is the only workspace that commits trades to Franchise Mode. "
        "It uses the live evolving franchise roster, contracts, draft capital, "
        "financial state, and transaction history."
    )
    render_live_asset_ledger(
        runtime,
        state,
        trade_state,
        active_team,
    )



if active_section == "Draft Room":



    # Draft V1.1.2: load the active Draft UI directly from the



    # project's src path at render time. This avoids a stale bound



    # render_draft_room_v1 function object surviving module refreshes.



    import importlib.util as _draft_importlib_util



    import inspect as _draft_inspect



    import sys as _draft_sys



    from pathlib import Path as _DraftPath







    _draft_ui_runtime_path = (



        _DraftPath(__file__).resolve().parents[1]



        / "src"



        / "franchise_draft_ui_v1.py"



    )



    # Draft V1.1.3: make sibling src imports resolvable before



    # loading the UI directly from disk, and discard any stale engine module.



    _draft_src_text = str(_draft_ui_runtime_path.parent)



    if _draft_src_text not in _draft_sys.path:



        _draft_sys.path.insert(0, _draft_src_text)



    _draft_sys.modules.pop("franchise_draft_engine_v1", None)







    _draft_module_name = "_franchise_draft_ui_v1_live"



    _draft_spec = _draft_importlib_util.spec_from_file_location(



        _draft_module_name,



        _draft_ui_runtime_path,



    )



    if _draft_spec is None or _draft_spec.loader is None:



        raise RuntimeError(



            "Could not load the active Draft UI module from "



            f"{_draft_ui_runtime_path}."



        )







    _draft_ui_live = _draft_importlib_util.module_from_spec(



        _draft_spec



    )



    _draft_sys.modules[_draft_module_name] = _draft_ui_live



    _draft_spec.loader.exec_module(_draft_ui_live)







    _draft_renderer = _draft_ui_live.render_draft_room_v1



    _draft_signature = _draft_inspect.signature(



        _draft_renderer



    )



    _draft_parameters = _draft_signature.parameters







    if "set_section" not in _draft_parameters:



        raise RuntimeError(



            "The on-disk Draft UI is not V1.1-compatible. "



            f"Active path: {_draft_ui_runtime_path} | "



            f"Signature: {_draft_signature}"



        )







    _draft_renderer(



        state,



        runtime,



        controlled_teams=controlled_teams,



        active_team=active_team,



        default_class_strength=int(



            st.session_state.get(



                "franchise_pref_draft_class_strength",



                5,



            )



        ),



        commit_state=set_franchise_state,



        set_section=set_franchise_section,



    )







if active_section == "League & Offseason":
    # FRANCHISE_FLAGSHIP_OFFSEASON_EXPERIENCE_V1
    # Franchise Mode owns the offseason lifecycle. The dedicated specialist
    # pages are launched from this command center rather than feeling like
    # unrelated products.
    _flagship_phase = str(
        getattr(state.phase, "value", state.phase)
    ).strip().lower()

    if _flagship_phase == "offseason":
        def _flagship_rows(value):
            output = []
            for row in list(value or ()):
                if isinstance(row, dict):
                    output.append(row)
                elif hasattr(row, "__dict__"):
                    output.append(vars(row))
            return output

        _flagship_market = _flagship_rows(
            getattr(
                state,
                "offseason_free_agent_amount_candidates_v1",
                (),
            )
        )
        _flagship_rfa = _flagship_rows(
            getattr(
                state,
                "offseason_rfa_rights_qo_decisions_v1",
                (),
            )
        )
        _flagship_non_rfa = _flagship_rows(
            getattr(
                state,
                "offseason_non_rfa_rights_decisions_v1",
                (),
            )
        )
        _flagship_salary = _flagship_rows(
            getattr(
                state,
                "offseason_official_team_salary_components_v1",
                (),
            )
        )
        _flagship_rights = _flagship_rfa + _flagship_non_rfa
        _flagship_retained = sum(
            1
            for row in _flagship_rights
            if float(row.get("effective_charge_2026_27") or 0.0) > 0.0
        )
        _flagship_qos = sum(
            1
            for row in _flagship_rfa
            if str(row.get("qo_decision") or "").strip() == "issue_qo"
        )
        _flagship_active_salary = next(
            (
                float(row.get("official_modeled_team_salary") or 0.0)
                for row in _flagship_salary
                if str(row.get("team") or "").strip().upper()
                == str(active_team).strip().upper()
            ),
            0.0,
        )

        st.markdown("## Offseason Command Center")
        st.caption(
            "Manage free agency, rights, qualifying offers, roster building, "
            "trades, and the draft from the franchise lifecycle. Dedicated "
            "workspaces open into this same durable franchise state."
        )

        _flagship_metrics = st.columns(4)
        _flagship_metrics[0].metric("Free agents", len(_flagship_market))
        _flagship_metrics[1].metric("Retained rights", _flagship_retained)
        _flagship_metrics[2].metric("Qualifying offers", _flagship_qos)
        _flagship_metrics[3].metric(
            f"{active_team} Team Salary",
            f"${_flagship_active_salary:,.0f}",
        )

        _flagship_actions = st.columns([1.2, 1.2, 2.1])
        with _flagship_actions[0]:
            if st.button(
                "📝 Open Free Agency",
                width="stretch",
                key="franchise_open_embedded_free_agency",
            ):
                set_franchise_section("Free Agency")
                st.rerun()
        with _flagship_actions[1]:
            if st.button(
                "🔁 Open Trade Center",
                width="stretch",
                key="franchise_open_live_trade_center",
            ):
                set_franchise_section("Trade Center")
                st.rerun()
        with _flagship_actions[2]:
            st.info(
                "Free Agency and the Trade Center are live Franchise Mode "
                "workspaces. The standalone Trade Machine is a separate "
                "2026-27 sandbox and never changes this franchise."
            )

        st.divider()




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







    render_awards_showcase_v2(state)



    render_cpu_front_office_v1(
        state,
        active_team=active_team,
        controlled_teams=controlled_teams,
    )







    with st.expander(



        "Career & rookie eligibility audit",



        expanded=False,



    ):



        st.caption(



            "Rookie status is based on durable career metadata, not age. "



            "Use this audit to verify draft year, rookie season, years of "



            "service, and the active Rookie of the Year eligibility pool."



        )



        career_audit = career_metadata_summary(



            state



        )



        rookie_first = career_audit.sort_values(



            ["Rookie Eligible", "Rookie Season", "Player"],



            ascending=[False, False, True],



        )



        st.dataframe(



            rookie_first,



            hide_index=True,



            width="stretch",



        )







    # FRANCHISE_FULL_RESET_UI_V1

    # FRANCHISE_LIVE_START_UI_V1

    render_live_franchise_start(runtime, state, trade_state)


    render_full_franchise_reset(runtime, state, trade_state)



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



            render_championship_ceremony_v2(



                state



            )



            st.success(



                "The postseason is complete. Awards are finalized and the "



                "league is ready to move into the draft-lottery and Draft "



                "Engine overhaul."



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



                        "What-if next game",



                        width="stretch",



                        key=(



                            "franchise_preview_"



                            "postseason_game"



                        ),



                    )



                )



                commit_clicked = (



                    game_actions[1].button(



                        "Simulate & commit",



                        type="primary",



                        width="stretch",



                        disabled=bool(blocking_events(state)),



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



                        disabled=bool(blocking_events(state)),



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



                        disabled=bool(blocking_events(state)),



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



                    st.markdown("### What-If Result")



                    st.info(



                        "Sandbox result only. It is not part of the "



                        "postseason until you use Simulate & commit."



                    )



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















    render_franchise_season_transition(



        state



    )







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



                "System": "Season archival",



                "Status": (



                    "Active with durable history"



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



                    "Active with explainable workload risk"



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



    f"{INJURY_FATIGUE_VERSION} · "



    f"{HEALTH_PERSISTENCE_REPAIR_VERSION} · "



    f"{POSTSEASON_VERSION} · "



    f"{SEASON_TRANSITION_CONTROLLER_VERSION} · "



    f"{FRANCHISE_OFFSEASON_INTEGRATION_VERSION} · "



    f"{CHECKPOINT_VERSION} · "



    f"{CHECKPOINT_IMPLEMENTATION_VERSION}"



)
