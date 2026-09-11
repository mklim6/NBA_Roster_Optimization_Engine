from __future__ import annotations

import argparse
import copy
import hashlib
import json
import shutil
import subprocess
import sys
import time
from contextlib import contextmanager
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
OUTPUT = ROOT / "outputs" / "franchise_protected_launch_smoke_v1.json"
RUNS = ROOT / "outputs" / "protected_launch_smoke_v1"
FREEZE_MANIFEST = ROOT / "app_data" / "nba_sep7_release_freeze_v1.json"
VERSION = "franchise-protected-launch-smoke-v1.0-2026-09-09"
EXPECTED_RELEASE_ID = "live_2026_09_07_release_candidate_v1"
EXPECTED_CUTOFF = "2026-09-07"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


class ProtectedLaunchSmokeError(RuntimeError):
    pass


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def _sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _checkpoint_family_hashes(primary: Path) -> dict[str, str]:
    if not primary.parent.exists():
        return {}
    prefix = primary.name.split(".pkl", 1)[0]
    out: dict[str, str] = {}
    for candidate in sorted(primary.parent.iterdir(), key=lambda p: p.name):
        if not candidate.is_file() or not candidate.name.startswith(prefix):
            continue
        digest = _sha256(candidate)
        if digest is not None:
            out[candidate.name] = digest
    return out


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if is_dataclass(value):
        return _json_safe(asdict(value))
    enum_value = getattr(value, "value", None)
    if isinstance(enum_value, (str, int, float, bool)):
        return enum_value
    if isinstance(value, Mapping):
        return {
            str(key): _json_safe(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_safe(item) for item in value]
    return str(value)


def _durability_payload(state: Any, trade_state: Any) -> dict[str, Any]:
    """Gameplay-focused semantic payload used before and after checkpoint reloads."""
    players: dict[str, Any] = {}
    for player_id, player in sorted(getattr(state, "players", {}).items()):
        contract = getattr(player, "contract", None)
        players[str(player_id)] = {
            "team": str(getattr(player, "team_abbreviation", "") or ""),
            "status": str(getattr(player, "roster_status", "") or ""),
            "overall": getattr(player, "overall_rating", None),
            "potential": getattr(player, "potential_rating", None),
            "two_way": bool(getattr(player, "two_way", False)),
            "salary": getattr(contract, "salary", None),
            "years_remaining": getattr(contract, "years_remaining", None),
            "option_type": str(getattr(contract, "option_type", "") or ""),
        }

    standings = {
        str(team): {
            "gp": int(getattr(row, "games_played", 0) or 0),
            "w": int(getattr(row, "wins", 0) or 0),
            "l": int(getattr(row, "losses", 0) or 0),
            "pf": int(getattr(row, "points_for", 0) or 0),
            "pa": int(getattr(row, "points_against", 0) or 0),
        }
        for team, row in sorted(getattr(state, "standings", {}).items())
    }

    season_totals = {
        str(player_id): _json_safe(row)
        for player_id, row in sorted(getattr(state, "player_season_totals", {}).items())
        if int(getattr(row, "games_played", 0) or 0) > 0
    }

    completed = {
        str(game_id): {
            "home": str(getattr(game, "home_team", "") or ""),
            "away": str(getattr(game, "away_team", "") or ""),
            "home_score": int(getattr(game, "home_score", 0) or 0),
            "away_score": int(getattr(game, "away_score", 0) or 0),
            "ot": int(getattr(game, "overtime_periods", 0) or 0),
            "box_count": len(getattr(game, "player_box_scores", ()) or ()),
        }
        for game_id, game in sorted(getattr(state, "completed_games", {}).items())
    }

    schedule_status = {
        str(game_id): str(
            getattr(getattr(game, "status", ""), "value", getattr(game, "status", ""))
        )
        for game_id, game in sorted(getattr(state, "schedule", {}).items())
    }

    teams = {
        str(team): list(getattr(team_state, "roster_player_ids", ()) or ())
        for team, team_state in sorted(getattr(state, "teams", {}).items())
    }

    payload = {
        "season": str(getattr(getattr(state, "settings", None), "season_label", "") or ""),
        "phase": str(getattr(getattr(state, "phase", ""), "value", getattr(state, "phase", ""))),
        "current_day_index": int(getattr(state, "current_day_index", 0) or 0),
        "transition_count": int(getattr(state, "transition_count", 0) or 0),
        "season_history_count": len(getattr(state, "season_history", ()) or ()),
        "universe": _json_safe(getattr(state, "franchise_start_universe_v1", {})),
        "staff": _json_safe(getattr(state, "franchise_staff_state_v1", {})),
        "players": players,
        "teams": teams,
        "free_agents": sorted(str(x) for x in getattr(state, "free_agent_player_ids", ()) or ()),
        "standings": standings,
        "season_totals": season_totals,
        "schedule_status": schedule_status,
        "completed": completed,
        "trade_state_revision": int(getattr(trade_state, "state_revision", 0) or 0),
        "trade_transaction_count": len(getattr(trade_state, "transaction_history", ()) or ()),
        "pick_team_by_id": {
            str(key): str(value or "")
            for key, value in sorted(getattr(trade_state, "pick_team_by_id", {}).items())
        },
    }
    return payload


def _durability_fingerprint(state: Any, trade_state: Any) -> str:
    encoded = json.dumps(
        _durability_payload(state, trade_state),
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _validate_release_freeze() -> dict[str, Any]:
    if not FREEZE_MANIFEST.is_file():
        raise ProtectedLaunchSmokeError(
            "The Sep. 7 release freeze is not installed. Run Step 1 before this smoke test."
        )
    manifest = json.loads(FREEZE_MANIFEST.read_text(encoding="utf-8"))
    checks = {
        "freeze_is_immutable": manifest.get("immutable") is True,
        "release_id_matches": manifest.get("release_id") == EXPECTED_RELEASE_ID,
        "cutoff_is_sep7": manifest.get("cutoff_date") == EXPECTED_CUTOFF,
        "frozen_files_present": bool(manifest.get("frozen_files")),
    }
    file_rows: list[dict[str, Any]] = []
    for row in manifest.get("frozen_files", []):
        path = ROOT / str(row.get("path") or "")
        expected = str(row.get("sha256") or "")
        actual = _sha256(path)
        matched = bool(expected and actual == expected)
        file_rows.append(
            {
                "path": str(row.get("path") or ""),
                "expected_sha256": expected,
                "actual_sha256": actual,
                "matched": matched,
            }
        )
    checks["all_frozen_hashes_match"] = bool(file_rows) and all(
        row["matched"] for row in file_rows
    )
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise ProtectedLaunchSmokeError(
            "Sep. 7 release freeze failed preflight: " + ", ".join(failed)
        )
    return {
        "checks": checks,
        "files": file_rows,
        "expected_live_start": dict(manifest.get("expected_live_start", {})),
    }


def _set_kw_default(function: Any, name: str, value: Any) -> dict[str, Any]:
    original = dict(getattr(function, "__kwdefaults__", {}) or {})
    if name in original:
        updated = dict(original)
        updated[name] = value
        function.__kwdefaults__ = updated
    return original


@contextmanager
def _isolated_checkpoint_contract(temp_primary: Path) -> Iterator[None]:
    """Redirect checkpoint constants AND bound keyword defaults to a temp tree.

    Several older durable APIs call load_franchise_checkpoint() with no path.
    Patching only DEFAULT_CHECKPOINT_PATH is not enough because Python binds
    keyword defaults when the function is defined. This context redirects both
    forms and restores them in a finally block.
    """
    import simulation_franchise_checkpoint_v1 as checkpoint_api

    temp_primary = temp_primary.resolve()
    temp_backup = temp_primary.with_name(temp_primary.name + ".backup")
    temp_primary.parent.mkdir(parents=True, exist_ok=True)

    original_primary = checkpoint_api.DEFAULT_CHECKPOINT_PATH
    original_backup = checkpoint_api.DEFAULT_BACKUP_PATH
    original_kw: dict[Any, dict[str, Any]] = {}
    for function_name in (
        "save_franchise_checkpoint",
        "load_franchise_checkpoint",
        "clear_franchise_checkpoint",
    ):
        function = getattr(checkpoint_api, function_name, None)
        if function is not None:
            original_kw[function] = _set_kw_default(function, "path", temp_primary)

    checkpoint_api.DEFAULT_CHECKPOINT_PATH = temp_primary
    checkpoint_api.DEFAULT_BACKUP_PATH = temp_backup

    patched_module_values: list[tuple[Any, str, Any]] = []
    for module_name in (
        "franchise_trade_transaction_v1",
    ):
        try:
            module = __import__(module_name)
        except Exception:
            continue
        if hasattr(module, "DEFAULT_CHECKPOINT_PATH"):
            old = getattr(module, "DEFAULT_CHECKPOINT_PATH")
            patched_module_values.append((module, "DEFAULT_CHECKPOINT_PATH", old))
            setattr(module, "DEFAULT_CHECKPOINT_PATH", temp_primary)

    try:
        yield
    finally:
        for module, name, old in reversed(patched_module_values):
            setattr(module, name, old)
        checkpoint_api.DEFAULT_CHECKPOINT_PATH = original_primary
        checkpoint_api.DEFAULT_BACKUP_PATH = original_backup
        for function, kwdefaults in original_kw.items():
            function.__kwdefaults__ = kwdefaults


def _save_and_assert_roundtrip(
    checkpoint_api: Any,
    path: Path,
    state: Any,
    trade_state: Any,
    *,
    preferences: Mapping[str, Any],
    reason: str,
) -> tuple[Any, str, str]:
    expected = _durability_fingerprint(state, trade_state)
    checkpoint_api.save_franchise_checkpoint(
        state,
        trade_state,
        preferences=dict(preferences),
        reason=reason,
        path=path,
        copy_payload=True,
    )
    reloaded = checkpoint_api.load_franchise_checkpoint(
        path=path,
        allow_backup=False,
    )
    if reloaded is None:
        raise ProtectedLaunchSmokeError(f"Checkpoint disappeared after {reason}.")
    observed = _durability_fingerprint(reloaded.simulation_state, reloaded.trade_state)
    if observed != expected:
        raise ProtectedLaunchSmokeError(
            f"Semantic checkpoint round-trip changed after {reason}."
        )
    return reloaded, expected, observed


def _sorted_scheduled_game_ids(state: Any) -> list[str]:
    rows = []
    for game_id, game in getattr(state, "schedule", {}).items():
        status = str(getattr(getattr(game, "status", ""), "value", getattr(game, "status", "")))
        if status != "scheduled":
            continue
        rows.append((int(getattr(game, "day_index", 0) or 0), str(game_id)))
    rows.sort()
    return [game_id for _, game_id in rows]


def run_smoke(*, keep_artifacts: bool = False, game_count: int = 2) -> dict[str, Any]:
    import simulation_franchise_checkpoint_v1 as checkpoint_api
    import franchise_live_start_v1 as live_api
    import franchise_opening_regular_season_transition_v1 as opening_api
    from freeform_trade_machine_engine_v3 import load_runtime_data
    from franchise_full_reset_v1 import build_starting_franchise
    from simulation_league_state_v1 import validate_simulation_league_state
    from mutable_league_state_v1 import validate_state
    from single_game_simulator_v1 import simulate_scheduled_game

    if game_count < 1 or game_count > 5:
        raise ProtectedLaunchSmokeError("game_count must be between 1 and 5.")

    freeze = _validate_release_freeze()
    expected_live_fp = str(
        freeze.get("expected_live_start", {}).get("live_start_fingerprint") or ""
    )
    if not expected_live_fp:
        raise ProtectedLaunchSmokeError("Frozen manifest has no expected live-start fingerprint.")

    active_primary = Path(checkpoint_api.DEFAULT_CHECKPOINT_PATH).resolve()
    active_before = _checkpoint_family_hashes(active_primary)

    run_root = RUNS / f"run_{_stamp()}"
    temp_primary = run_root / "outputs" / "runtime" / "franchise_mode_checkpoint_v1.pkl.gz"
    run_root.mkdir(parents=True, exist_ok=False)

    checks: dict[str, bool] = {}
    details: dict[str, Any] = {
        "version": VERSION,
        "started_at_utc": _utc_now(),
        "release_freeze": freeze,
        "active_checkpoint_path": str(active_primary),
        "active_checkpoint_family_before": active_before,
        "isolated_run_root": str(run_root),
        "isolated_checkpoint": str(temp_primary),
        "requested_game_count": int(game_count),
    }

    failure: str = ""
    try:
        with _isolated_checkpoint_contract(temp_primary):
            runtime = load_runtime_data()
            source = build_starting_franchise(runtime)
            validate_simulation_league_state(source.simulation_state)
            validate_state(source.trade_state, runtime)
            source_fp = _durability_fingerprint(source.simulation_state, source.trade_state)
            details["source_fingerprint"] = source_fp

            preferences = {
                "protected_launch_smoke_v1": True,
                "release_id": EXPECTED_RELEASE_ID,
            }
            checkpoint_api.save_franchise_checkpoint(
                source.simulation_state,
                source.trade_state,
                preferences=preferences,
                reason="protected-launch-source-fixture",
                path=temp_primary,
                copy_payload=True,
                force_replace=True,
            )
            checks["isolated_source_checkpoint_created"] = temp_primary.is_file()

            launch = live_api.commit_live_franchise_start(
                runtime,
                source.simulation_state,
                source.trade_state,
                preferences=preferences,
            )
            launched = checkpoint_api.load_franchise_checkpoint(
                path=temp_primary,
                allow_backup=False,
            )
            if launched is None:
                raise ProtectedLaunchSmokeError("Live-start checkpoint could not be reloaded.")
            validate_simulation_league_state(launched.simulation_state)
            validate_state(launched.trade_state, runtime)

            launched_live_fp = live_api.live_start_fingerprint(
                launched.simulation_state,
                launched.trade_state,
            )
            checks["frozen_live_start_fingerprint_matches"] = launched_live_fp == expected_live_fp
            checks["live_start_has_1230_games"] = len(launched.simulation_state.schedule) == 1230
            checks["live_start_player_population_matches_freeze"] = (
                len(launched.simulation_state.players)
                == int(freeze["expected_live_start"].get("total_player_count", 0))
            )
            checks["live_start_is_opening_offseason"] = (
                str(
                    getattr(
                        getattr(launched.simulation_state, "phase", ""),
                        "value",
                        getattr(launched.simulation_state, "phase", ""),
                    )
                )
                == "offseason"
            )
            checks["launch_created_recovery_manifest"] = (
                Path(launch.backup_directory).is_dir()
                and (Path(launch.backup_directory) / "live_start_manifest.json").is_file()
                and (Path(launch.backup_directory) / "checkpoint").is_dir()
            )
            details["live_start"] = {
                "result": asdict(launch),
                "observed_fingerprint": launched_live_fp,
                "durability_fingerprint": _durability_fingerprint(
                    launched.simulation_state, launched.trade_state
                ),
            }

            # Exercise a no-mutation save/reload immediately after launch.
            launched_roundtrip, expected, observed = _save_and_assert_roundtrip(
                checkpoint_api,
                temp_primary,
                launched.simulation_state,
                launched.trade_state,
                preferences=launched.preferences,
                reason="protected-smoke-post-live-launch-roundtrip",
            )
            checks["post_launch_save_reload_exact"] = expected == observed

            opening_preview = opening_api.preview_opening_regular_season(
                launched_roundtrip.simulation_state,
                launched_roundtrip.trade_state,
            )
            checks["opening_regular_season_preview_is_commit_ready"] = opening_preview.can_commit
            if not opening_preview.can_commit:
                raise ProtectedLaunchSmokeError(
                    "Opening regular season is blocked: " + ", ".join(opening_preview.blockers)
                )

            opening_result = opening_api.commit_opening_regular_season_live(
                confirmation_token=opening_preview.confirmation_token,
                expected_fingerprint=opening_preview.source_fingerprint,
                recovery_directory=run_root / "opening_recovery",
            )
            opened = checkpoint_api.load_franchise_checkpoint(
                path=temp_primary,
                allow_backup=False,
            )
            if opened is None:
                raise ProtectedLaunchSmokeError("Opening-night checkpoint could not be reloaded.")
            validate_simulation_league_state(opened.simulation_state)
            checks["opening_transition_reloaded"] = True
            checks["regular_season_phase_active"] = (
                str(
                    getattr(
                        getattr(opened.simulation_state, "phase", ""),
                        "value",
                        getattr(opened.simulation_state, "phase", ""),
                    )
                )
                == "regular_season"
            )
            details["opening_transition"] = asdict(opening_result)

            game_ids = _sorted_scheduled_game_ids(opened.simulation_state)
            if len(game_ids) < game_count:
                raise ProtectedLaunchSmokeError(
                    f"Only {len(game_ids)} scheduled games are available after opening."
                )

            game_rows: list[dict[str, Any]] = []
            current = opened
            for index, game_id in enumerate(game_ids[:game_count], start=1):
                seed = 2026090900 + index
                preview = simulate_scheduled_game(
                    current.simulation_state,
                    game_id,
                    seed=seed,
                    commit=False,
                )
                committed = simulate_scheduled_game(
                    current.simulation_state,
                    game_id,
                    seed=seed,
                    commit=True,
                )
                if committed.game != preview.game:
                    raise ProtectedLaunchSmokeError(
                        f"Committed game {game_id} diverged from deterministic preview."
                    )

                completed_before_save = len(current.simulation_state.completed_games)
                standing_gp_before_save = sum(
                    int(getattr(row, "games_played", 0) or 0)
                    for row in current.simulation_state.standings.values()
                )
                current, expected, observed = _save_and_assert_roundtrip(
                    checkpoint_api,
                    temp_primary,
                    current.simulation_state,
                    current.trade_state,
                    preferences=current.preferences,
                    reason=f"protected-smoke-after-game-{index}",
                )
                validate_simulation_league_state(current.simulation_state)
                completed_after_reload = len(current.simulation_state.completed_games)
                standing_gp_after_reload = sum(
                    int(getattr(row, "games_played", 0) or 0)
                    for row in current.simulation_state.standings.values()
                )
                if game_id not in current.simulation_state.completed_games:
                    raise ProtectedLaunchSmokeError(
                        f"Completed game {game_id} disappeared after reload."
                    )
                if completed_after_reload != completed_before_save:
                    raise ProtectedLaunchSmokeError(
                        f"Completed-game count changed after reload for {game_id}."
                    )
                if standing_gp_after_reload != standing_gp_before_save:
                    raise ProtectedLaunchSmokeError(
                        f"Standing games-played changed after reload for {game_id}."
                    )
                game = current.simulation_state.completed_games[game_id]
                game_rows.append(
                    {
                        "index": index,
                        "game_id": game_id,
                        "home_team": str(game.home_team),
                        "away_team": str(game.away_team),
                        "home_score": int(game.home_score),
                        "away_score": int(game.away_score),
                        "box_score_rows": len(game.player_box_scores),
                        "completed_games_after_reload": completed_after_reload,
                        "standing_games_played_sum": standing_gp_after_reload,
                        "semantic_fingerprint_expected": expected,
                        "semantic_fingerprint_observed": observed,
                    }
                )

            checks["all_requested_games_survive_save_reload"] = len(game_rows) == game_count
            checks["standings_reconcile_after_games"] = sum(
                int(getattr(row, "games_played", 0) or 0)
                for row in current.simulation_state.standings.values()
            ) == 2 * game_count
            checks["completed_game_count_matches"] = (
                len(current.simulation_state.completed_games) == game_count
            )
            checks["player_totals_exist_after_games"] = any(
                int(getattr(row, "games_played", 0) or 0) > 0
                for row in current.simulation_state.player_season_totals.values()
            )
            details["games"] = game_rows

            # Prove the original pre-launch franchise can still be restored after the
            # isolated franchise has advanced through opening night and gameplay.
            live_api._restore_checkpoint_family(Path(launch.backup_directory), temp_primary)
            restored = checkpoint_api.load_franchise_checkpoint(
                path=temp_primary,
                allow_backup=False,
            )
            if restored is None:
                raise ProtectedLaunchSmokeError("Recovery restore produced no checkpoint.")
            restored_fp = _durability_fingerprint(
                restored.simulation_state,
                restored.trade_state,
            )
            checks["recovery_restores_exact_source_semantics"] = restored_fp == source_fp
            details["restored_source_fingerprint"] = restored_fp

    except Exception as exc:
        failure = f"{type(exc).__name__}: {exc}"
    finally:
        active_after = _checkpoint_family_hashes(active_primary)
        checks["active_checkpoint_family_unchanged"] = active_before == active_after
        details["active_checkpoint_family_after"] = active_after

    failed_checks = [name for name, passed in checks.items() if not passed]
    if failure:
        failed_checks.append("protected_launch_smoke_raised")

    report = {
        "version": VERSION,
        "generated_at_utc": _utc_now(),
        "passed": not failed_checks,
        "checks": checks,
        "failed_checks": failed_checks,
        "error": failure,
        "details": details,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

    if report["passed"] and not keep_artifacts:
        shutil.rmtree(run_root, ignore_errors=True)
        report["details"]["isolated_artifacts_removed_after_pass"] = True
        OUTPUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    else:
        report["details"]["isolated_artifacts_preserved"] = str(run_root)
        OUTPUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

    return report


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Launch the frozen Sep. 7 franchise only inside an isolated checkpoint tree, "
            "open the regular season, simulate games, repeatedly save/reload, restore the "
            "pre-launch source, and prove the user's active checkpoint family is unchanged."
        )
    )
    parser.add_argument(
        "--keep-artifacts",
        action="store_true",
        help="Keep the isolated checkpoint tree even when every check passes.",
    )
    parser.add_argument(
        "--games",
        type=int,
        default=2,
        help="Number of opening regular-season games to simulate (1-5, default 2).",
    )
    args = parser.parse_args()

    print("FRANCHISE PROTECTED LAUNCH + SAVE/LOAD SMOKE V1")
    print(f"Project root: {ROOT}")
    print(f"Started: {_utc_now()}")
    print("Active franchise mutation: FORBIDDEN")
    print()

    started = time.perf_counter()
    report = run_smoke(keep_artifacts=args.keep_artifacts, game_count=args.games)
    elapsed = round(time.perf_counter() - started, 3)
    report["duration_seconds"] = elapsed
    OUTPUT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

    for name, passed in report["checks"].items():
        print(f"{'PASS' if passed else 'FAIL'}  {name}")
    print()
    print(f"Report: {OUTPUT}")
    print(f"Elapsed: {elapsed:.3f}s")
    if report["passed"]:
        print("FRANCHISE PROTECTED LAUNCH + SAVE/LOAD SMOKE V1 PASSED")
        return 0

    print("FRANCHISE PROTECTED LAUNCH + SAVE/LOAD SMOKE V1 FAILED")
    if report.get("error"):
        print(f"Error: {report['error']}")
    for name in report["failed_checks"]:
        print(f"  - {name}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
