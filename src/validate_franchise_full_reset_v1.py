from __future__ import annotations

import hashlib
import json
import py_compile
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from freeform_trade_machine_engine_v3 import load_runtime_data
import simulation_franchise_checkpoint_v1 as checkpoint_api
from franchise_full_reset_v1 import (
    FULL_RESET_VERSION,
    RESET_STARTING_SEASON,
    build_full_reset_preview,
    build_starting_franchise,
)
from regular_season_schedule_v1 import LEAGUE_GAME_COUNT
from simulation_league_state_v1 import LeaguePhase, validate_simulation_league_state


VALIDATOR_VERSION = "franchise-full-reset-validator-v1-2026-08-11"
REPORT = ROOT / "outputs" / "franchise_full_reset_v1_validation.json"


def sha256(path: Path) -> str:
    if not path.is_file():
        return ""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def empty_attr(state, names):
    for name in names:
        value = getattr(state, name, None)
        if value:
            return False
    return True


def main() -> int:
    checkpoint_path = Path(checkpoint_api.DEFAULT_CHECKPOINT_PATH)
    before_hash = sha256(checkpoint_path)
    checkpoint = checkpoint_api.load_franchise_checkpoint()
    if checkpoint is None:
        raise RuntimeError("A durable franchise checkpoint is required for reset validation.")

    source_preview = build_full_reset_preview(checkpoint.simulation_state, checkpoint.trade_state)
    runtime = load_runtime_data()
    fresh = build_starting_franchise(runtime)
    state = fresh.simulation_state
    trade_state = fresh.trade_state

    compile_targets = [
        ROOT / "src" / "franchise_full_reset_v1.py",
        ROOT / "src" / "franchise_full_reset_ui_v1.py",
        ROOT / "pages" / "5_Franchise_Mode.py",
    ]
    compile_errors = {}
    for path in compile_targets:
        try:
            py_compile.compile(str(path), doraise=True)
            compile_errors[str(path.relative_to(ROOT))] = ""
        except Exception as exc:
            compile_errors[str(path.relative_to(ROOT))] = str(exc)

    checks = {
        "validator_version_is_current": VALIDATOR_VERSION.endswith("2026-08-11"),
        "reset_engine_version_is_current": FULL_RESET_VERSION.endswith("2026-08-11"),
        "durable_checkpoint_exists": bool(before_hash),
        "in_memory_build_does_not_modify_checkpoint": sha256(checkpoint_path) == before_hash,
        "starting_season_is_2026_27": str(state.settings.season_label) == RESET_STARTING_SEASON,
        "starting_schedule_has_1230_games": len(state.schedule) == LEAGUE_GAME_COUNT,
        "starting_schedule_activates_regular_season": state.phase == LeaguePhase.REGULAR_SEASON,
        "starting_day_is_zero": int(state.current_day_index) == 0,
        "no_completed_games": not state.completed_games,
        "no_archived_seasons": not state.season_history,
        "transition_count_is_zero": int(state.transition_count) == 0,
        "no_postseason_state": getattr(state, "postseason_state", None) is None,
        "no_retirement_history": not getattr(state, "retirement_history", []),
        "no_development_history": all(not getattr(player, "development_history", []) for player in state.players.values()),
        "no_draft_or_award_history": empty_attr(
            state,
            (
                "draft_history",
                "completed_draft_history",
                "completed_drafts",
                "franchise_draft_history",
                "award_history",
                "awards_history",
                "franchise_award_history",
            ),
        ),
        "trade_machine_transactions_reset": not getattr(trade_state, "transaction_history", []),
        "career_lifecycle_initialized_for_opening_season": bool(
            getattr(state, "career_intent_by_player_id", {})
        ),
        "fresh_state_is_valid": bool(validate_simulation_league_state(state)),
        "all_modified_files_compile": all(not value for value in compile_errors.values()),
        "checkpoint_hash_still_unchanged": sha256(checkpoint_path) == before_hash,
    }
    failed = [name for name, passed in checks.items() if not passed]

    report = {
        "script": VALIDATOR_VERSION,
        "reset_engine": FULL_RESET_VERSION,
        "checks": checks,
        "failed_checks": failed,
        "source_franchise": source_preview,
        "fresh_franchise": {
            "season": state.settings.season_label,
            "phase": state.phase.value,
            "players": len(state.players),
            "rostered_players": fresh.rostered_players,
            "free_agents": fresh.free_agents,
            "schedule_games": fresh.schedule_games,
            "schedule_signature": fresh.schedule_signature,
            "career_considering": fresh.career_considering,
            "farewell_announcements": fresh.farewell_announcements,
            "trade_transactions": len(getattr(trade_state, "transaction_history", [])),
        },
        "checkpoint_sha256_before": before_hash,
        "checkpoint_sha256_after": sha256(checkpoint_path),
        "compile_errors": compile_errors,
        "passed": not failed,
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

    print("=" * 92)
    print("FULL FRANCHISE RESET V1 VALIDATION")
    print("=" * 92)
    for name, passed in checks.items():
        print(f"  {name}: {'PASS' if passed else 'FAIL'}")
    print()
    print("CURRENT LIVE FRANCHISE")
    print(f"  Season: {source_preview['season']}")
    print(f"  Players: {source_preview['players']}")
    print(f"  Archived seasons: {source_preview['archived_seasons']}")
    print(f"  Completed games: {source_preview['completed_games']}")
    print()
    print("FRESH RESET BUILD (IN MEMORY ONLY)")
    print(f"  Season: {state.settings.season_label}")
    print(f"  Players: {len(state.players)}")
    print(f"  Schedule games: {len(state.schedule)}")
    print(f"  Phase: {state.phase.value}")
    print(f"  Career considering: {fresh.career_considering}")
    print(f"  Farewell announcements: {fresh.farewell_announcements}")
    print()
    if failed:
        raise AssertionError("Full franchise reset validation failed: " + ", ".join(failed))
    print("FULL FRANCHISE RESET V1 VALIDATION PASSED")
    print("READ-ONLY VALIDATION: current durable franchise checkpoint was not modified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
