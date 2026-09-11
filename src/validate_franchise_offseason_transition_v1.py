from __future__ import annotations

import copy
import json
import py_compile
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
OUTPUTS = ROOT / "outputs"
PAGE = ROOT / "pages" / "5_Franchise_Mode.py"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from freeform_trade_machine_engine_v3 import (  # noqa: E402
    load_runtime_data,
)
from mutable_league_state_v1 import (  # noqa: E402
    create_league_state,
)
from simulation_franchise_checkpoint_v1 import (  # noqa: E402
    checkpoint_progress_key,
    load_franchise_checkpoint,
    save_franchise_checkpoint,
)
from simulation_league_state_v1 import (  # noqa: E402
    LeaguePhase,
    create_simulation_league_state,
    validate_simulation_league_state,
)
from simulation_season_transition_controller_v1 import (  # noqa: E402
    build_season_transition_preview,
    commit_season_transition_preview,
    preview_matches_state,
    transition_source_fingerprint,
)
from state_runtime_adapter_v1 import (  # noqa: E402
    build_state_runtime,
)
from franchise_offseason_market_season_v1 import (  # noqa: E402
    COMPLETED_SEASON_CLOSEOUT_ATTR,
    next_season_label,
)


SCRIPT_VERSION = (
    "franchise-offseason-transition-validator-v1-2026-08-09"
)
REPORT_PATH = (
    OUTPUTS
    / "franchise_offseason_transition_validation_v1.json"
)


PAGE_MARKERS = {
    "controller_import": (
        "from simulation_season_transition_controller_v1 import"
    ),
    "transition_preview": (
        "build_season_transition_preview"
    ),
    "transactional_commit": (
        "commit_season_transition_preview"
    ),
    "freshness_guard": "preview_matches_state",
    "confirmation_acknowledgement": (
        "_season_boundary_durable.confirmation_token("
    ),
    "checkpoint_reason": (
        "commit_atomic_season_boundary_live("
    ),
    "archived_history": "Archived Season History",
    "champion_preservation": "archive_champion(",
    "automatic_target_season": (
        "expected_target_season=str("
    ),
    "dynamic_season_schedule": (
        'f"Generate {state.settings.season_label} schedule"'
    ),
    "preseason_next_action": (
        'f"Generate the {state.settings.season_label} schedule"'
    ),
    "preseason_rank_display": (
        "conference_metric_value"
    ),
}


def build_test_state() -> Any:
    base_runtime = load_runtime_data()
    trade_state = create_league_state(
        base_runtime
    )
    runtime = build_state_runtime(
        base_runtime,
        trade_state,
    )
    state = create_simulation_league_state(
        runtime,
        trade_state,
    )
    state.phase = LeaguePhase.OFFSEASON
    state.postseason_state = SimpleNamespace(
        stage="complete",
        champion="CHI",
        runner_up="HOU",
        conference_champions={
            "East": "CHI",
            "West": "HOU",
        },
        completed_games={
            "NBA-FINALS-G1": SimpleNamespace(
                winner="CHI",
                loser="HOU",
            ),
            "NBA-FINALS-G2": SimpleNamespace(
                winner="CHI",
                loser="HOU",
            ),
        },
        postseason_player_totals={
            "sample-player": SimpleNamespace(
                games_played=2,
                points=61,
            )
        },
        series={
            "NBA-FINALS": SimpleNamespace(
                winner="CHI",
                loser="HOU",
            )
        },
    )
    setattr(
        state,
        COMPLETED_SEASON_CLOSEOUT_ATTR,
        {
            "status": "applied",
            "source_season": state.settings.season_label,
            "target_market_season": next_season_label(state.settings.season_label),
            "fixture_scope": "franchise_offseason_transition_validator",
        },
    )
    validate_simulation_league_state(
        state
    )
    return state


def run_validation() -> dict[str, Any]:
    page_text = PAGE.read_text(
        encoding="utf-8"
    )
    missing_markers = [
        name
        for name, marker
        in PAGE_MARKERS.items()
        if marker not in page_text
    ]
    legacy_confirmation_removed = all(
        marker not in page_text
        for marker in (
            "Type the target season to confirm",
            "FRANCHISE_TRANSITION_CONFIRM_KEY",
            "confirmation_matches",
        )
    )
    preview_tab_is_preserved = (
        (
            "FRANCHISE_TRANSITION_PREVIEW_KEY\n"
            "            ] = preview\n"
            "            st.rerun()"
        )
        not in page_text
    )

    source = build_test_state()
    source_fingerprint = (
        transition_source_fingerprint(source)
    )
    preview = build_season_transition_preview(
        source
    )
    source_after_preview = (
        transition_source_fingerprint(source)
    )
    source_postseason = copy.deepcopy(
        source.postseason_state
    )
    committed_state, result = (
        commit_season_transition_preview(
            source,
            preview,
        )
    )
    validate_simulation_league_state(
        committed_state
    )
    archive = committed_state.season_history[-1]

    old_progress = checkpoint_progress_key(
        source
    )
    new_progress = checkpoint_progress_key(
        committed_state
    )

    with tempfile.TemporaryDirectory() as directory:
        checkpoint_path = (
            Path(directory)
            / "offseason-transition.pkl.gz"
        )
        save_franchise_checkpoint(
            source,
            {"revision": 1},
            reason="completed-season",
            path=checkpoint_path,
            copy_payload=False,
        )
        save_result = save_franchise_checkpoint(
            committed_state,
            {"revision": 1},
            reason="franchise-season-transition",
            path=checkpoint_path,
            copy_payload=False,
        )
        loaded = load_franchise_checkpoint(
            path=checkpoint_path
        )

    checks = {
        "validator_version_is_current": (
            SCRIPT_VERSION.endswith(
                "2026-08-09"
            )
        ),
        "franchise_page_exists": PAGE.exists(),
        "franchise_page_compiles": True,
        "all_franchise_ui_markers_present": (
            not missing_markers
        ),
        "legacy_typed_confirmation_is_removed": (
            legacy_confirmation_removed
        ),
        "preview_remains_on_offseason_tab": (
            preview_tab_is_preserved
        ),
        "preview_does_not_mutate_live_state": (
            source_fingerprint
            == source_after_preview
        ),
        "preview_matches_completed_state": (
            preview_matches_state(
                source,
                preview,
            )
        ),
        "source_state_remains_completed": (
            source.phase == LeaguePhase.OFFSEASON
            and hasattr(
                source,
                "postseason_state",
            )
            and source.postseason_state.champion
            == "CHI"
        ),
        "transition_opens_next_preseason": (
            committed_state.phase
            == LeaguePhase.PRESEASON
            and committed_state.settings.season_label
            == "2027-28"
            and committed_state.transition_count
            == 1
        ),
        "completed_season_is_archived": (
            len(committed_state.season_history)
            == 1
            and archive.season_label
            == "2026-27"
        ),
        "champion_and_runner_up_are_archived": (
            archive.champion == "CHI"
            and archive.runner_up == "HOU"
            and result.archived_champion == "CHI"
            and result.archived_runner_up == "HOU"
        ),
        "conference_champions_are_archived": (
            archive.conference_champions
            == {
                "East": "CHI",
                "West": "HOU",
            }
        ),
        "full_postseason_object_is_archived": (
            archive.postseason_state
            is not None
            and archive.postseason_state
            is not source.postseason_state
            and archive.postseason_state.champion
            == source_postseason.champion
            and len(
                archive.postseason_state
                .completed_games
            )
            == 2
            and archive.postseason_games_completed
            == 2
            and result.archived_postseason_games
            == 2
        ),
        "new_season_has_no_stale_live_postseason": (
            not hasattr(
                committed_state,
                "postseason_state",
            )
        ),
        "new_season_results_are_clean": (
            not committed_state.schedule
            and not committed_state.completed_games
            and all(
                standing.games_played == 0
                for standing
                in committed_state.standings.values()
            )
        ),
        "checkpoint_progress_advances_across_transition": (
            new_progress > old_progress
            and new_progress[0] == 1
        ),
        "transition_checkpoint_replaces_completed_season": (
            save_result.reason
            == "franchise-season-transition"
            and loaded is not None
            and loaded.reason
            == "franchise-season-transition"
            and loaded.simulation_state
            .settings.season_label
            == "2027-28"
            and loaded.simulation_state
            .transition_count
            == 1
            and loaded.simulation_state
            .season_history[-1]
            .champion
            == "CHI"
        ),
    }

    try:
        py_compile.compile(
            str(PAGE),
            doraise=True,
        )
    except py_compile.PyCompileError:
        checks["franchise_page_compiles"] = False

    failed = [
        name
        for name, passed
        in checks.items()
        if not passed
    ]
    report = {
        "script": SCRIPT_VERSION,
        "checks": checks,
        "failed_checks": failed,
        "details": {
            "missing_page_markers": (
                missing_markers
            ),
            "source_progress": old_progress,
            "target_progress": new_progress,
            "archived_champion": (
                archive.champion
            ),
            "archived_runner_up": (
                archive.runner_up
            ),
            "archived_postseason_games": (
                archive
                .postseason_games_completed
            ),
            "target_season": (
                committed_state
                .settings.season_label
            ),
        },
        "passed": not failed,
    }

    OUTPUTS.mkdir(
        parents=True,
        exist_ok=True,
    )
    REPORT_PATH.write_text(
        json.dumps(
            report,
            indent=2,
        ),
        encoding="utf-8",
    )

    if failed:
        raise AssertionError(
            "Franchise offseason transition validation failed: "
            + ", ".join(failed)
        )

    return report


def main() -> int:
    report = run_validation()
    print(
        json.dumps(
            report,
            indent=2,
        )
    )
    print(
        "\nFRANCHISE OFFSEASON TRANSITION VALIDATION PASSED"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
