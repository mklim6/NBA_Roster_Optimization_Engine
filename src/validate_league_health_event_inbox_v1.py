from __future__ import annotations

import argparse
import json
import py_compile
import sys
import tempfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
PAGES = ROOT / "pages"
OUTPUTS = ROOT / "outputs"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from franchise_league_events_v1 import (  # noqa: E402
    EVENTS_ATTRIBUTE,
    FRANCHISE_EVENT_VERSION,
    blocking_events,
    event_inbox_rows,
    franchise_events,
    resolve_event,
    run_self_test as run_event_self_test,
    synchronize_franchise_events,
)
from freeform_trade_machine_engine_v3 import load_runtime_data  # noqa: E402
from league_health_audit_v1 import (  # noqa: E402
    LEAGUE_HEALTH_AUDIT_VERSION,
    active_injury_rows,
    league_health_audit,
    run_self_test as run_audit_self_test,
)
from mutable_league_state_v1 import create_league_state  # noqa: E402
from simulation_franchise_checkpoint_v1 import (  # noqa: E402
    load_franchise_checkpoint,
    save_franchise_checkpoint,
)
from simulation_injury_fatigue_v1 import (  # noqa: E402
    HEALTH_STATE_ATTRIBUTE,
    ensure_injury_fatigue_state,
    health_events,
)
from simulation_league_state_v1 import (  # noqa: E402
    AvailabilityStatus,
    create_simulation_league_state,
)
from state_runtime_adapter_v1 import build_state_runtime  # noqa: E402


VALIDATOR_VERSION = (
    "league-health-event-inbox-validator-v1-2026-08-09"
)
REPORT_PATH = OUTPUTS / "league_health_event_inbox_validation_v1.json"


def page_markers() -> dict[str, str]:
    return {
        "workspace": '"Inbox & League Health"',
        "decision_inbox": 'st.subheader("Decision Inbox")',
        "blocking_metric": '"Simulation blockers"',
        "advance_guard": "or bool(blocking_events(state))",
        "league_health_audit": 'League health audit',
        "active_injuries": '"Active injuries"',
        "team_health": '"Team health"',
        "interruption_settings": '"Interruption settings"',
        "resolve_action": 'resolve_event(state, event["event_id"])',
        "checkpoint_sync": 'reason="franchise-event-inbox-sync"',
        "future_system_copy": (
            "future AI trade offers, scouting updates, contract deadlines"
        ),
    }


def run_validation() -> dict[str, Any]:
    page = PAGES / "5_Franchise_Mode.py"
    event_module = SRC / "franchise_league_events_v1.py"
    audit_module = SRC / "league_health_audit_v1.py"
    text = page.read_text(encoding="utf-8")

    markers = page_markers()
    missing_markers = [
        name for name, marker in markers.items() if marker not in text
    ]

    compile_results: dict[str, str] = {}
    for path in (page, event_module, audit_module, Path(__file__)):
        try:
            py_compile.compile(str(path), doraise=True)
            compile_results[str(path)] = ""
        except py_compile.PyCompileError as exc:
            compile_results[str(path)] = str(exc)

    audit_self_test = run_audit_self_test()
    event_self_test = run_event_self_test()

    runtime_base = load_runtime_data()
    trade_state = create_league_state(runtime_base)
    runtime = build_state_runtime(runtime_base, trade_state)
    state = create_simulation_league_state(runtime, trade_state)
    profiles = ensure_injury_fatigue_state(state)

    for standing in state.standings.values():
        standing.games_played = 20
        standing.wins = 10
        standing.losses = 10

    for team in state.teams.values():
        for player_id in team.rotation.rotation_player_ids:
            state.player_season_totals[player_id].games_played = 20
            profiles[player_id].recent_minutes = (28.0, 31.0, 30.0, 32.0)
            profiles[player_id].fatigue = 0.4

    audit_before = league_health_audit(state)
    chi_player_id = next(iter(state.teams["CHI"].rotation.rotation_player_ids))
    chi_player = state.players[chi_player_id]
    state.injuries[chi_player_id].status = AvailabilityStatus.OUT
    state.injuries[chi_player_id].injury_type = "ankle sprain"
    state.injuries[chi_player_id].games_remaining = 3
    profiles[chi_player_id].expected_return_day = 24
    health_events(state).append(
        {
            "season_label": state.settings.season_label,
            "game_id": "VALIDATION-INJURY",
            "day_index": 20,
            "player_id": chi_player_id,
            "player_name": chi_player.player_name,
            "team": "CHI",
            "injury_type": "ankle sprain",
            "severity": "minor",
            "status": "out",
            "estimated_games_missed": 3,
            "back_to_back": True,
        }
    )
    sync = synchronize_franchise_events(state, controlled_teams=("CHI",))
    audit_after = league_health_audit(state)
    blocker = blocking_events(state)[0]

    with tempfile.TemporaryDirectory() as temp_dir:
        checkpoint_path = Path(temp_dir) / "franchise.pkl.gz"
        save_franchise_checkpoint(
            state,
            trade_state,
            path=checkpoint_path,
            reason="league-health-event-validation",
        )
        restored = load_franchise_checkpoint(path=checkpoint_path)
        if restored is None:
            raise AssertionError("Checkpoint did not restore.")
        restored_state = restored.simulation_state
        restored_events = franchise_events(restored_state)
        restored_blockers = blocking_events(restored_state)

    resolve_event(state, blocker["event_id"])

    checks = {
        "validator_version_is_current": VALIDATOR_VERSION.endswith("2026-08-09"),
        "event_engine_version_is_current": FRANCHISE_EVENT_VERSION.endswith("2026-08-09"),
        "health_audit_version_is_current": LEAGUE_HEALTH_AUDIT_VERSION.endswith("2026-08-09"),
        "all_page_markers_present": not missing_markers,
        "all_files_compile": not any(compile_results.values()),
        "audit_self_test_passes": bool(audit_self_test.get("passed")),
        "event_self_test_passes": bool(event_self_test.get("passed")),
        "twenty_game_quiet_health_is_flagged": audit_before.overall_status == "needs_more_health_pressure",
        "controlled_injury_creates_blocker": sync["blocking"] >= 1,
        "active_injury_table_contains_player": any(row["player_id"] == chi_player_id for row in active_injury_rows(state)),
        "inbox_rows_are_explainable": any(row["title"] and row["detail"] and row["destination"] for row in event_inbox_rows(state)),
        "event_contract_uses_plain_dicts": all(isinstance(event, dict) for event in getattr(state, EVENTS_ATTRIBUTE)),
        "checkpoint_preserves_events": len(restored_events) == len(franchise_events(state)),
        "checkpoint_preserves_blockers": len(restored_blockers) == 1,
        "resolved_event_releases_pause": not blocking_events(state),
        "audit_updates_after_injury": audit_after.active_injuries == 1 and audit_after.injury_events == 1,
        "health_profiles_remain_present": isinstance(getattr(state, HEALTH_STATE_ATTRIBUTE), dict),
    }
    failed = [name for name, passed in checks.items() if not passed]
    report = {
        "script": VALIDATOR_VERSION,
        "checks": checks,
        "failed_checks": failed,
        "missing_page_markers": missing_markers,
        "compile_results": compile_results,
        "audit_before": audit_before.__dict__,
        "audit_after": audit_after.__dict__,
        "event_sync": sync,
        "restored_event_count": len(restored_events),
        "passed": not failed,
    }
    OUTPUTS.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    if failed:
        raise AssertionError(
            "League health and event inbox validation failed: "
            + ", ".join(failed)
        )
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=20260809)
    parser.parse_args()
    report = run_validation()
    print(json.dumps(report, indent=2))
    print("\nLEAGUE HEALTH AND EVENT INBOX V1 VALIDATION PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
