from __future__ import annotations

import csv
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any


ROOT = Path.cwd().resolve()
SRC = ROOT / "src"
OUTPUTS = ROOT / "outputs"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from career_lifecycle_transition_adapter_v1 import (  # noqa: E402
    CONTROLLER_VERSION,
    build_season_transition_preview,
    commit_season_transition_preview,
    lifecycle_source_fingerprint,
    preview_matches_state,
)
from franchise_career_lifecycle_v1 import (  # noqa: E402
    CAREER_LIFECYCLE_VERSION,
    STATUS_CONSIDERING,
    STATUS_FAREWELL,
    return_offer_modifier,
)
from simulation_franchise_checkpoint_v1 import load_franchise_checkpoint  # noqa: E402
from simulation_league_state_v1 import validate_simulation_league_state  # noqa: E402


REPORT = OUTPUTS / "franchise_career_lifecycle_v1_validation.json"
VALIDATOR_VERSION = "validate-franchise-career-lifecycle-v1.0.2-2026-08-11"


def approved_snapshot(source: str, target: str) -> dict[str, Any] | None:
    """Load the older read-only preview only as a historical snapshot.

    It is authoritative only when its source season, target season, and player
    population still match the durable checkpoint being validated.
    """
    summary_path = OUTPUTS / "retirement_population_preview_v1.json"
    retiree_path = OUTPUTS / "projected_retirees_v1.csv"
    if not summary_path.is_file() or not retiree_path.is_file():
        return None
    try:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if str(summary.get("season")) != source or str(summary.get("target_season")) != target:
        return None
    with retiree_path.open("r", encoding="utf-8-sig", newline="") as handle:
        ids = [
            str(row.get("player_id", "")).strip()
            for row in csv.DictReader(handle)
            if str(row.get("player_id", "")).strip()
        ]
    return {"summary": summary, "retirement_player_ids": ids}


def current_legacy_preview(state: Any) -> dict[str, Any]:
    """Run the already-approved V1 preview algorithm on the *current* state.

    This is the migration-parity guardrail. It deliberately imports the prior
    preview implementation instead of reusing Career Lifecycle internals.
    """
    try:
        import preview_retirement_population_v1 as legacy  # noqa: E402
    except Exception as exc:  # pragma: no cover - surfaced in report
        return {
            "available": False,
            "error": f"{type(exc).__name__}: {exc}",
            "retirement_player_ids": [],
            "retirement_count": None,
            "players_before": len(getattr(state, "players", {})),
        }

    try:
        rows = legacy.build_rows(state)
        legacy.apply_roster_floor(state, rows)
        retirees = [row for row in rows if bool(row.get("projected_retire"))]
        retirees.sort(
            key=lambda row: (
                -float(row.get("age", 0.0) or 0.0),
                -float(row.get("retirement_probability", 0.0) or 0.0),
                str(row.get("player_name", "")),
            )
        )
    except Exception as exc:  # pragma: no cover - surfaced in report
        return {
            "available": False,
            "error": f"{type(exc).__name__}: {exc}",
            "retirement_player_ids": [],
            "retirement_count": None,
            "players_before": len(getattr(state, "players", {})),
        }

    return {
        "available": True,
        "error": "",
        "preview_version": str(getattr(legacy, "PREVIEW_VERSION", "")),
        "players_before": len(getattr(state, "players", {})),
        "retirement_count": len(retirees),
        "rostered_retirements": sum(not bool(row.get("free_agent")) for row in retirees),
        "free_agent_retirements": sum(bool(row.get("free_agent")) for row in retirees),
        "retirement_player_ids": [str(row.get("player_id", "")) for row in retirees],
    }


def offer_logic_checks() -> dict[str, bool]:
    player = SimpleNamespace(contract=SimpleNamespace(salary=8_000_000.0))
    strong_offer = {
        "salary": 16_000_000.0,
        "market_salary": 8_000_000.0,
        "years": 2,
        "guaranteed": True,
        "role": "starter",
        "contender_score": 0.85,
        "same_team": True,
    }
    modifier = return_offer_modifier(
        player=player,
        age=39.0,
        base_probability=0.72,
        status_before=STATUS_CONSIDERING,
        offer=strong_offer,
    )
    farewell_modifier = return_offer_modifier(
        player=player,
        age=39.0,
        base_probability=0.72,
        status_before=STATUS_FAREWELL,
        offer=strong_offer,
    )
    very_old_modifier = return_offer_modifier(
        player=player,
        age=46.0,
        base_probability=1.0,
        status_before=STATUS_CONSIDERING,
        offer=strong_offer,
    )
    return {
        "strong_offer_lowers_considering_probability": modifier < 0.0,
        "farewell_season_ignores_offer": farewell_modifier == 0.0,
        "absolute_max_age_cannot_be_bought_back": very_old_modifier == 0.0,
    }


def main() -> int:
    checkpoint = load_franchise_checkpoint()
    if checkpoint is None:
        raise RuntimeError("No durable Franchise Mode checkpoint could be loaded.")
    state = checkpoint.simulation_state
    source_signature = lifecycle_source_fingerprint(state)
    source_season = str(state.settings.season_label)
    players_before = len(getattr(state, "players", {}))

    # Capture whether this checkpoint predates Career Lifecycle. Migration
    # parity is mandatory in that case. Once users have real farewell states
    # or return offers, divergence from the legacy algorithm is intentional.
    source_intents = dict(getattr(state, "career_intent_by_player_id", {}) or {})
    source_offers = dict(getattr(state, "retirement_return_offers", {}) or {})
    legacy_parity_applicable = not source_intents and not source_offers

    preview = build_season_transition_preview(state)
    lifecycle = preview["career_lifecycle"]
    retirement = lifecycle["retirement_plan"]
    target = str(preview["target_season"])
    retired_ids = list(retirement.get("retirement_player_ids", []))

    legacy_current = current_legacy_preview(state)
    snapshot = approved_snapshot(source_season, target)
    snapshot_players = None
    snapshot_ids: list[str] = []
    if snapshot is not None:
        snapshot_players = int(snapshot["summary"].get("players_before", -1) or -1)
        snapshot_ids = list(snapshot["retirement_player_ids"])
    historical_snapshot_applicable = bool(
        snapshot is not None and snapshot_players == players_before
    )

    transitioned, result = commit_season_transition_preview(state, preview)
    validate_simulation_league_state(transitioned)

    target_intents = lifecycle.get("target_season_intents", {})
    checks = {
        "adapter_version_is_current": CONTROLLER_VERSION == "career-lifecycle-transition-adapter-v1.0.1-2026-08-11",
        "lifecycle_version_is_current": lifecycle.get("career_lifecycle_version") == CAREER_LIFECYCLE_VERSION,
        "preview_matches_unchanged_state": preview_matches_state(state, preview),
        "preview_does_not_mutate_source": lifecycle_source_fingerprint(state) == source_signature,
        "commit_returns_replacement_state": transitioned is not state,
        "commit_does_not_mutate_source": lifecycle_source_fingerprint(state) == source_signature,
        "committed_state_valid": bool(validate_simulation_league_state(transitioned)),
        "retirees_removed_from_committed_state": all(player_id not in transitioned.players for player_id in retired_ids),
        "retirement_history_persists": len(getattr(transitioned, "retirement_history", []) or []) >= len(retired_ids),
        "target_career_intents_persist": isinstance(getattr(transitioned, "career_intent_by_player_id", None), dict),
        "target_intent_summary_matches_preview": int(target_intents.get("tracked_veterans", 0) or 0) == len(getattr(transitioned, "career_intent_by_player_id", {}) or {}),
        "player_population_matches_preview": len(transitioned.players) == int(lifecycle.get("players_after_transition", -1)),
        "base_transition_result_preserved": str(result.target_season) == target,
        "medical_v2_health_profiles_match_live_players": (
            not hasattr(transitioned, "injury_fatigue_profiles")
            or set(getattr(transitioned, "injury_fatigue_profiles", {}))
            == set(getattr(transitioned, "players", {}))
        ),
        "retirees_removed_from_current_health_profiles": (
            not hasattr(transitioned, "injury_fatigue_profiles")
            or all(
                player_id not in getattr(transitioned, "injury_fatigue_profiles", {})
                for player_id in retired_ids
            )
        ),
        "legacy_preview_module_available": bool(legacy_current.get("available")),
        "current_checkpoint_preserves_approved_v1_retirement_logic": (
            (not legacy_parity_applicable)
            or (
                bool(legacy_current.get("available"))
                and retired_ids == list(legacy_current.get("retirement_player_ids", []))
            )
        ),
        # The historical CSV is only an exact guardrail while it describes the
        # same checkpoint population. A later Draft/population change makes it
        # archival evidence rather than a valid expected result.
        "historical_snapshot_preserved_when_applicable": (
            (not historical_snapshot_applicable)
            or retired_ids == snapshot_ids
        ),
    }
    checks.update(offer_logic_checks())

    failed = [name for name, passed in checks.items() if not passed]
    report = {
        "script": VALIDATOR_VERSION,
        "source_season": source_season,
        "target_season": target,
        "checks": checks,
        "failed_checks": failed,
        "parity": {
            "legacy_parity_applicable": legacy_parity_applicable,
            "legacy_preview_available": legacy_current.get("available"),
            "legacy_preview_error": legacy_current.get("error", ""),
            "legacy_current_players_before": legacy_current.get("players_before"),
            "legacy_current_retirements": legacy_current.get("retirement_count"),
            "legacy_current_rostered_retirements": legacy_current.get("rostered_retirements"),
            "legacy_current_free_agent_retirements": legacy_current.get("free_agent_retirements"),
            "historical_snapshot_found": snapshot is not None,
            "historical_snapshot_players_before": snapshot_players,
            "historical_snapshot_retirements": len(snapshot_ids) if snapshot is not None else None,
            "historical_snapshot_applicable": historical_snapshot_applicable,
            "historical_snapshot_skipped_because_population_changed": bool(
                snapshot is not None and not historical_snapshot_applicable
            ),
        },
        "summary": {
            "players_before": retirement.get("players_before"),
            "retirements": retirement.get("retirement_count"),
            "players_after_transition": lifecycle.get("players_after_transition"),
            "rostered_retirements": retirement.get("rostered_retirements"),
            "free_agent_retirements": retirement.get("free_agent_retirements"),
            "age_40_plus_before": retirement.get("age_40_plus_before"),
            "age_40_plus_after": retirement.get("age_40_plus_after"),
            "offer_saved_returns": retirement.get("offer_saved_returns"),
            "target_considering_retirement": target_intents.get("considering_retirement"),
            "target_farewell_seasons": target_intents.get("farewell_seasons"),
        },
        "passed": not failed,
    }
    OUTPUTS.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print("=" * 92)
    print("FRANCHISE CAREER LIFECYCLE V1.0.2 VALIDATION")
    print("=" * 92)
    for name, passed in checks.items():
        print(f"  {name}: {'PASS' if passed else 'FAIL'}")
    print()
    print("Season:", source_season, "->", target)
    print("Players:", retirement.get("players_before"), "->", lifecycle.get("players_after_transition"))
    print("Retirements:", retirement.get("retirement_count"))
    print("Rostered retirements:", retirement.get("rostered_retirements"))
    print("Free-agent retirements:", retirement.get("free_agent_retirements"))
    print("Age 40+:", retirement.get("age_40_plus_before"), "->", retirement.get("age_40_plus_after"))
    print("Return offers that changed a decision:", retirement.get("offer_saved_returns"))
    print("Next-season considering retirement:", target_intents.get("considering_retirement"))
    print("Next-season farewell announcements:", target_intents.get("farewell_seasons"))
    print()
    print("CURRENT-CHECKPOINT LEGACY PARITY")
    print("  Applicable:", legacy_parity_applicable)
    print("  Legacy preview available:", legacy_current.get("available"))
    print("  Legacy current players:", legacy_current.get("players_before"))
    print("  Legacy current retirements:", legacy_current.get("retirement_count"))
    print("  Lifecycle current retirements:", len(retired_ids))
    print()
    print("HISTORICAL 765-PLAYER SNAPSHOT")
    print("  Found:", snapshot is not None)
    print("  Snapshot players:", snapshot_players)
    print("  Current players:", players_before)
    print("  Exact snapshot applicable:", historical_snapshot_applicable)
    if snapshot is not None and not historical_snapshot_applicable:
        print("  Status: SKIPPED AS STALE because the live player population changed.")
    print()
    if failed:
        raise AssertionError("Career lifecycle validation failed: " + ", ".join(failed))
    print("FRANCHISE CAREER LIFECYCLE V1.0.2 VALIDATION PASSED")
    print("READ-ONLY VALIDATION: durable franchise checkpoint was not modified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
