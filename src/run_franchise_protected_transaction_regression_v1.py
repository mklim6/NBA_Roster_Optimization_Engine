from __future__ import annotations

import argparse
import copy
import json
import shutil
import sys
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
OUTPUT = ROOT / "outputs" / "franchise_protected_transaction_regression_v1.json"
RUNS = ROOT / "outputs" / "protected_transaction_regression_v1"
VERSION = "franchise-protected-transaction-regression-v1.0-2026-09-09"
CONTROLLED_TEAMS_KEY = "franchise_pref_controlled_teams"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from run_franchise_protected_launch_smoke_v1 import (
    _checkpoint_family_hashes,
    _durability_fingerprint,
    _isolated_checkpoint_contract,
    _save_and_assert_roundtrip,
    _validate_release_freeze,
)


class ProtectedTransactionRegressionError(RuntimeError):
    pass


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def _phase(state: Any) -> str:
    raw = getattr(state, "phase", "")
    return str(getattr(raw, "value", raw)).strip().lower()


def _find_free_agency_pass(state: Any, trade_state: Any):
    from franchise_free_agency_contract_salary_legality_v1_3 import (
        build_contract_legal_free_agency_preview,
        minimum_salary_floor_for_state,
        resolve_years_of_service,
    )
    from franchise_free_agency_transaction_v1 import FreeAgencyOffer
    from simulation_league_state_v1 import validate_simulation_league_state

    owner_map = dict(getattr(trade_state, "player_team_by_id", {}) or {})
    teams = sorted(str(team).strip().upper() for team in getattr(state, "teams", {}))
    free_agents = sorted(str(pid) for pid in getattr(state, "free_agent_player_ids", ()) or ())
    attempts: list[dict[str, Any]] = []

    # Prefer teams with the most roster room so the smoke cannot create an
    # opening-night roster-size blocker merely because it chose a full team.
    teams.sort(key=lambda t: (len(getattr(state.teams[t], "roster_player_ids", ()) or ()), t))

    for team in teams:
        roster_count = len(getattr(state.teams[team], "roster_player_ids", ()) or ())
        if roster_count >= 18:
            continue
        for player_id in free_agents:
            if str(owner_map.get(player_id, "") or "").strip():
                continue
            player = getattr(state, "players", {}).get(player_id)
            service, _ = resolve_years_of_service(player)
            minimum = minimum_salary_floor_for_state(
                state,
                years_of_service=service,
                contract_years=1,
            )
            if minimum is None:
                continue
            offer = FreeAgencyOffer(
                player_id=player_id,
                team_abbreviation=team,
                annual_salary=float(minimum),
                years=1,
                guaranteed=True,
                option_type="",
            )
            try:
                preview = build_contract_legal_free_agency_preview(
                    state,
                    offer,
                    state_validator=validate_simulation_league_state,
                    max_roster_size=18,
                )
            except Exception as exc:
                if len(attempts) < 12:
                    attempts.append({"team": team, "player_id": player_id, "error": str(exc)})
                continue
            if preview.status == "pass" and preview.can_commit:
                return team, player_id, offer, preview, attempts
            if len(attempts) < 12:
                attempts.append({
                    "team": team,
                    "player_id": player_id,
                    "status": preview.status,
                    "can_commit": bool(preview.can_commit),
                    "message": str(preview.message),
                })
    raise ProtectedTransactionRegressionError(
        "No contract-legal, cap-space PASS free-agent signing was found in the frozen opening offseason."
    )


def _find_pick_only_trade_pass(runtime: Any, state: Any, trade_state: Any):
    from franchise_draft_right_stepien_bridge_v1 import build_franchise_draft_right_profiles
    from franchise_embedded_trade_center_v2 import build_franchise_trade_preview
    from franchise_live_asset_ledger_v1 import build_live_asset_ledger

    ledger = build_live_asset_ledger(runtime, state, trade_state)
    profiles = build_franchise_draft_right_profiles(ledger)
    seconds_by_team: dict[str, list[Any]] = {}
    for profile in profiles:
        if int(getattr(profile, "round_number", 0) or 0) == 2 and bool(getattr(profile, "bridge_ready", False)):
            seconds_by_team.setdefault(str(profile.current_owner), []).append(profile)
    teams = sorted(team for team, rows in seconds_by_team.items() if rows)
    for index, team_a in enumerate(teams):
        for team_b in teams[index + 1:]:
            pick_a = sorted(seconds_by_team[team_a], key=lambda p: (p.draft_year, p.asset_id))[0]
            pick_b = sorted(seconds_by_team[team_b], key=lambda p: (p.draft_year, p.asset_id))[0]
            preview = build_franchise_trade_preview(
                runtime,
                state,
                trade_state,
                team_a=team_a,
                team_b=team_b,
                side_a_pick_asset_ids=(pick_a.asset_id,),
                side_b_pick_asset_ids=(pick_b.asset_id,),
                ledger=ledger,
            )
            if preview.status == "pass" and preview.can_commit:
                return team_a, team_b, str(pick_a.asset_id), str(pick_b.asset_id), preview
    raise ProtectedTransactionRegressionError(
        "No deterministic PASS second-round pick trade was found."
    )


def run_regression(*, keep_artifacts: bool = False) -> dict[str, Any]:
    import simulation_franchise_checkpoint_v1 as checkpoint_api
    import franchise_live_start_v1 as live_api
    import franchise_opening_regular_season_transition_v1 as opening_api
    from freeform_trade_machine_engine_v3 import load_runtime_data
    from franchise_full_reset_v1 import build_starting_franchise
    from franchise_free_agency_live_signing_v1 import (
        commit_contract_legal_free_agency_preview_live,
        trade_state_fingerprint,
    )
    from franchise_free_agency_transaction_v1_1 import free_agency_durable_state_fingerprint
    from franchise_live_asset_ledger_v1 import build_live_asset_ledger
    from franchise_trade_transaction_v1 import commit_live_franchise_trade
    from mutable_league_state_v1 import validate_state
    from simulation_league_state_v1 import validate_simulation_league_state

    freeze = _validate_release_freeze()
    active_primary = Path(checkpoint_api.DEFAULT_CHECKPOINT_PATH).resolve()
    active_before = _checkpoint_family_hashes(active_primary)

    run_root = RUNS / f"run_{_stamp()}"
    temp_primary = run_root / "outputs" / "runtime" / "franchise_mode_checkpoint_v1.pkl.gz"
    run_root.mkdir(parents=True, exist_ok=False)

    checks: dict[str, bool] = {}
    details: dict[str, Any] = {
        "version": VERSION,
        "started_at_utc": _utc_now(),
        "active_checkpoint_path": str(active_primary),
        "active_checkpoint_family_before": active_before,
        "isolated_run_root": str(run_root),
        "isolated_checkpoint": str(temp_primary),
        "release_freeze": freeze,
    }
    failure = ""

    try:
        with _isolated_checkpoint_contract(temp_primary):
            runtime = load_runtime_data()
            source = build_starting_franchise(runtime)
            validate_simulation_league_state(source.simulation_state)
            validate_state(source.trade_state, runtime)
            base_preferences = {
                "protected_transaction_regression_v1": True,
                "release_id": "live_2026_09_07_release_candidate_v1",
            }
            checkpoint_api.save_franchise_checkpoint(
                source.simulation_state,
                source.trade_state,
                preferences=base_preferences,
                reason="protected-transaction-source-fixture",
                path=temp_primary,
                copy_payload=True,
                force_replace=True,
            )
            checks["isolated_source_checkpoint_created"] = temp_primary.is_file()

            launch = live_api.commit_live_franchise_start(
                runtime,
                source.simulation_state,
                source.trade_state,
                preferences=base_preferences,
            )
            launched = checkpoint_api.load_franchise_checkpoint(path=temp_primary, allow_backup=False)
            if launched is None:
                raise ProtectedTransactionRegressionError("Frozen live start did not reload.")
            validate_simulation_league_state(launched.simulation_state)
            validate_state(launched.trade_state, runtime)
            checks["frozen_live_start_reloaded"] = True
            checks["live_start_is_opening_offseason"] = _phase(launched.simulation_state) == "offseason"

            # Keep a semantic and byte recovery point for the clean frozen live start.
            clean_live_fp = _durability_fingerprint(launched.simulation_state, launched.trade_state)
            clean_live_copy = run_root / "clean_frozen_live_start.pkl.gz"
            shutil.copy2(temp_primary, clean_live_copy)
            details["clean_live_start_fingerprint"] = clean_live_fp

            team, player_id, offer, preview, attempts = _find_free_agency_pass(
                launched.simulation_state,
                launched.trade_state,
            )
            preferences = copy.deepcopy(dict(launched.preferences or {}))
            preferences[CONTROLLED_TEAMS_KEY] = [team]
            launched, pref_expected, pref_observed = _save_and_assert_roundtrip(
                checkpoint_api,
                temp_primary,
                launched.simulation_state,
                launched.trade_state,
                preferences=preferences,
                reason="protected-transaction-set-controlled-team",
            )
            checks["controlled_team_preference_survives_reload"] = (
                pref_expected == pref_observed
                and list((launched.preferences or {}).get(CONTROLLED_TEAMS_KEY, [])) == [team]
            )

            # Rebuild against the exact durable state after the preference save so
            # the source fingerprint is unquestionably current.
            team2, player_id2, offer2, preview2, _ = _find_free_agency_pass(
                launched.simulation_state,
                launched.trade_state,
            )
            if (team2, player_id2) != (team, player_id):
                team, player_id, offer, preview = team2, player_id2, offer2, preview2
                preferences = copy.deepcopy(dict(launched.preferences or {}))
                preferences[CONTROLLED_TEAMS_KEY] = [team]
                launched, _, _ = _save_and_assert_roundtrip(
                    checkpoint_api,
                    temp_primary,
                    launched.simulation_state,
                    launched.trade_state,
                    preferences=preferences,
                    reason="protected-transaction-reset-controlled-team",
                )
                _, _, offer, preview, _ = _find_free_agency_pass(
                    launched.simulation_state,
                    launched.trade_state,
                )

            fa_source_sim_fp = free_agency_durable_state_fingerprint(launched.simulation_state)
            fa_source_trade_fp = trade_state_fingerprint(launched.trade_state)
            fa_result = commit_contract_legal_free_agency_preview_live(
                preview,
                hypothetical=False,
                max_roster_size=18,
                recovery_directory=run_root / "fa_recovery",
            )
            after_fa = checkpoint_api.load_franchise_checkpoint(path=temp_primary, allow_backup=False)
            if after_fa is None:
                raise ProtectedTransactionRegressionError("Free-agent signing did not reload.")
            validate_simulation_league_state(after_fa.simulation_state)
            validate_state(after_fa.trade_state, runtime)
            checks["free_agency_live_commit_completed"] = bool(fa_result.transaction_id)
            checks["free_agent_removed_from_market"] = player_id not in set(after_fa.simulation_state.free_agent_player_ids)
            checks["signed_player_rostered_to_team"] = (
                str(after_fa.simulation_state.players[player_id].team_abbreviation).strip().upper() == team
                and player_id in set(after_fa.simulation_state.teams[team].roster_player_ids)
            )
            checks["free_agency_trade_state_sync_survives_reload"] = (
                str(after_fa.trade_state.player_team_by_id.get(player_id, "") or "").strip().upper() == team
            )
            checks["free_agency_state_changed_from_source"] = (
                free_agency_durable_state_fingerprint(after_fa.simulation_state) != fa_source_sim_fp
                and trade_state_fingerprint(after_fa.trade_state) != fa_source_trade_fp
            )
            fa_history = list(getattr(after_fa.simulation_state, "free_agency_transaction_history", []) or [])
            checks["free_agency_history_survives_reload"] = bool(
                fa_history and fa_history[-1].get("transaction_id") == fa_result.transaction_id
            )
            fa_roundtrip, expected, observed = _save_and_assert_roundtrip(
                checkpoint_api,
                temp_primary,
                after_fa.simulation_state,
                after_fa.trade_state,
                preferences=after_fa.preferences,
                reason="protected-transaction-after-fa-signing",
            )
            checks["post_signing_save_reload_exact"] = expected == observed
            details["free_agency"] = {
                "team": team,
                "player_id": player_id,
                "player_name": str(getattr(after_fa.simulation_state.players[player_id], "name", "") or ""),
                "annual_salary": float(offer.annual_salary),
                "years": int(offer.years),
                "preview_status": preview.status,
                "transaction_id": fa_result.transaction_id,
                "recovery_path": fa_result.recovery_path,
                "candidate_search_samples": attempts,
            }

            opening_preview = opening_api.preview_opening_regular_season(
                fa_roundtrip.simulation_state,
                fa_roundtrip.trade_state,
            )
            checks["post_signing_opening_preview_is_commit_ready"] = opening_preview.can_commit
            if not opening_preview.can_commit:
                raise ProtectedTransactionRegressionError(
                    "Opening regular season is blocked after protected signing: "
                    + ", ".join(opening_preview.blockers)
                )
            opening_result = opening_api.commit_opening_regular_season_live(
                confirmation_token=opening_preview.confirmation_token,
                expected_fingerprint=opening_preview.source_fingerprint,
                recovery_directory=run_root / "opening_recovery",
            )
            opened = checkpoint_api.load_franchise_checkpoint(path=temp_primary, allow_backup=False)
            if opened is None:
                raise ProtectedTransactionRegressionError("Opening-night transition did not reload.")
            validate_simulation_league_state(opened.simulation_state)
            checks["regular_season_opens_after_signing"] = _phase(opened.simulation_state) == "regular_season"
            details["opening_transition"] = asdict(opening_result)

            team_a, team_b, pick_a, pick_b, trade_preview = _find_pick_only_trade_pass(
                runtime,
                opened.simulation_state,
                opened.trade_state,
            )
            before_trade_ledger = build_live_asset_ledger(runtime, opened.simulation_state, opened.trade_state)
            before_pick_map = {row["asset_id"]: row for row in before_trade_ledger.draft_rows}
            original_owner_a = str(before_pick_map[pick_a]["current_owner"])
            original_owner_b = str(before_pick_map[pick_b]["current_owner"])
            trade_result = commit_live_franchise_trade(
                runtime,
                opened.simulation_state,
                opened.trade_state,
                team_a=team_a,
                team_b=team_b,
                side_a_pick_asset_ids=(pick_a,),
                side_b_pick_asset_ids=(pick_b,),
                expected_fingerprint=trade_preview.package_fingerprint,
                recovery_directory=run_root / "trade_recovery",
            )
            after_trade = checkpoint_api.load_franchise_checkpoint(path=temp_primary, allow_backup=False)
            if after_trade is None:
                raise ProtectedTransactionRegressionError("Trade transaction did not reload.")
            validate_simulation_league_state(after_trade.simulation_state)
            after_trade_ledger = build_live_asset_ledger(runtime, after_trade.simulation_state, after_trade.trade_state)
            after_pick_map = {row["asset_id"]: row for row in after_trade_ledger.draft_rows}
            checks["trade_live_commit_completed"] = bool(trade_result.transaction_id)
            checks["pick_a_owner_swapped_after_reload"] = str(after_pick_map[pick_a]["current_owner"]) == team_b
            checks["pick_b_owner_swapped_after_reload"] = str(after_pick_map[pick_b]["current_owner"]) == team_a
            trade_history = list(getattr(after_trade.simulation_state, "franchise_transaction_history_v1", []) or [])
            checks["trade_history_survives_reload"] = bool(
                trade_history and trade_history[-1].get("transaction_id") == trade_result.transaction_id
            )
            checks["trade_revision_incremented"] = int(
                getattr(after_trade.simulation_state, "franchise_trade_revision_v1", 0) or 0
            ) >= 1
            after_trade_roundtrip, expected, observed = _save_and_assert_roundtrip(
                checkpoint_api,
                temp_primary,
                after_trade.simulation_state,
                after_trade.trade_state,
                preferences=after_trade.preferences,
                reason="protected-transaction-after-live-trade",
            )
            checks["post_trade_save_reload_exact"] = expected == observed
            details["trade"] = {
                "team_a": team_a,
                "team_b": team_b,
                "pick_a": pick_a,
                "pick_b": pick_b,
                "original_owner_a": original_owner_a,
                "original_owner_b": original_owner_b,
                "preview_status": trade_preview.status,
                "transaction_id": trade_result.transaction_id,
                "recovery_checkpoint_path": trade_result.recovery_checkpoint_path,
            }

            # Restore the clean frozen live-start fixture and prove both tested
            # transactions disappear exactly, without involving the real save.
            shutil.copy2(clean_live_copy, temp_primary)
            restored = checkpoint_api.load_franchise_checkpoint(path=temp_primary, allow_backup=False)
            if restored is None:
                raise ProtectedTransactionRegressionError("Clean live-start restore did not reload.")
            restored_fp = _durability_fingerprint(restored.simulation_state, restored.trade_state)
            checks["clean_frozen_live_start_restores_exactly"] = restored_fp == clean_live_fp
            checks["restored_state_has_no_test_fa_signing"] = player_id in set(restored.simulation_state.free_agent_player_ids)
            restored_ledger = build_live_asset_ledger(runtime, restored.simulation_state, restored.trade_state)
            restored_pick_map = {row["asset_id"]: row for row in restored_ledger.draft_rows}
            checks["restored_state_has_original_pick_owners"] = (
                str(restored_pick_map[pick_a]["current_owner"]) == original_owner_a
                and str(restored_pick_map[pick_b]["current_owner"]) == original_owner_b
            )
            details["restored_fingerprint"] = restored_fp

    except Exception as exc:
        failure = f"{type(exc).__name__}: {exc}"
    finally:
        active_after = _checkpoint_family_hashes(active_primary)
        checks["active_checkpoint_family_unchanged"] = active_before == active_after
        details["active_checkpoint_family_after"] = active_after

    failed = [name for name, passed in checks.items() if not passed]
    if failure:
        failed.append("protected_transaction_regression_raised")

    report = {
        "version": VERSION,
        "generated_at_utc": _utc_now(),
        "passed": not failed,
        "checks": checks,
        "failed_checks": failed,
        "error": failure,
        "details": details,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

    if report["passed"] and not keep_artifacts:
        shutil.rmtree(run_root, ignore_errors=True)
        report["details"]["isolated_artifacts_removed_after_pass"] = True
    else:
        report["details"]["isolated_artifacts_preserved"] = str(run_root)
    OUTPUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run a frozen Sep. 7 franchise in an isolated checkpoint tree, commit one "
            "contract-legal free-agent signing, open the regular season, commit one "
            "deterministic PASS draft-pick trade, reload after each transaction, restore "
            "the clean frozen live-start fixture, and prove the active checkpoint is unchanged."
        )
    )
    parser.add_argument("--keep-artifacts", action="store_true")
    args = parser.parse_args()

    print("FRANCHISE PROTECTED TRANSACTION + SAVE/LOAD REGRESSION V1")
    print(f"Project root: {ROOT}")
    print(f"Started: {_utc_now()}")
    print("Active franchise mutation: FORBIDDEN")
    print()
    started = time.perf_counter()
    report = run_regression(keep_artifacts=args.keep_artifacts)
    elapsed = round(time.perf_counter() - started, 3)
    report["duration_seconds"] = elapsed
    OUTPUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

    for name, passed in report["checks"].items():
        print(f"{'PASS' if passed else 'FAIL'}  {name}")
    print()
    print(f"Report: {OUTPUT}")
    print(f"Elapsed: {elapsed:.3f}s")
    if report["passed"]:
        print("FRANCHISE PROTECTED TRANSACTION + SAVE/LOAD REGRESSION V1 PASSED")
        return 0
    print("FRANCHISE PROTECTED TRANSACTION + SAVE/LOAD REGRESSION V1 FAILED")
    if report.get("error"):
        print(f"Error: {report['error']}")
    for name in report["failed_checks"]:
        print(f"  - {name}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
