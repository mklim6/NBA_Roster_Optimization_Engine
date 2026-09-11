from __future__ import annotations

import hashlib
import json
import py_compile
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import cloudpickle

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
OUTPUTS = ROOT / "outputs"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from freeform_trade_machine_engine_v3 import load_runtime_data, normalize_team
from franchise_embedded_trade_center_v2 import (
    EMBEDDED_TRADE_CENTER_VERSION,
    build_franchise_trade_preview,
)
from franchise_live_asset_ledger_v1 import build_live_asset_ledger
from franchise_player_contract_bridge_v1 import (
    BASE_LEAGUE_YEAR,
    PLAYER_CONTRACT_BRIDGE_VERSION,
    build_franchise_player_contract_snapshot,
    evaluate_franchise_player_contract_trade,
)
from simulation_franchise_checkpoint_v1 import load_franchise_checkpoint


VALIDATOR_VERSION = (
    "franchise-player-contract-bridge-v1-validator-v1.0.1-2026-09-11"
)
REPORT_PATH = OUTPUTS / "franchise_player_contract_bridge_v1_validation.json"


def sha256(path: Path) -> str:
    if not path.is_file():
        return ""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def digest_object(value: Any) -> str:
    return hashlib.sha256(cloudpickle.dumps(value)).hexdigest()


def rostered_rows(ledger: Any, team: str) -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in ledger.player_rows
        if row.get("roster_status") == "rostered"
        and normalize_team(row.get("team")) == team
    ]


def main() -> int:
    checkpoint_path = ROOT / "outputs" / "runtime" / "franchise_mode_checkpoint_v1.pkl.gz"
    checkpoint_hash_before = sha256(checkpoint_path)
    checkpoint = load_franchise_checkpoint()
    if checkpoint is None:
        raise AssertionError("No durable franchise checkpoint exists.")

    state = checkpoint.simulation_state
    trade_state = checkpoint.trade_state
    runtime = load_runtime_data()
    state_before = digest_object(state)
    trade_before = digest_object(trade_state)

    snapshot = build_franchise_player_contract_snapshot(runtime, state)
    ledger = build_live_asset_ledger(runtime, state, trade_state)
    pmap = {profile.player_id: profile for profile in snapshot.profiles}
    season = str(state.settings.season_label)

    teams = [
        normalize_team(team)
        for team in state.teams
        if rostered_rows(ledger, normalize_team(team))
    ]
    if len(teams) < 2:
        raise AssertionError("Need at least two teams with rostered players.")

    team_a, team_b = teams[0], teams[1]
    player_a = rostered_rows(ledger, team_a)[0]
    player_b = rostered_rows(ledger, team_b)[0]
    contract_eval = evaluate_franchise_player_contract_trade(
        runtime,
        state,
        team_a=team_a,
        team_b=team_b,
        side_a_player_ids=(player_a["player_id"],),
        side_b_player_ids=(player_b["player_id"],),
    )
    preview = build_franchise_trade_preview(
        runtime,
        state,
        trade_state,
        team_a=team_a,
        team_b=team_b,
        side_a_player_ids=(player_a["player_id"],),
        side_b_player_ids=(player_b["player_id"],),
        ledger=ledger,
    )

    generated_row = next(
        (
            dict(row)
            for row in ledger.player_rows
            if row.get("generated_player")
            and row.get("roster_status") == "rostered"
            and not bool(row.get("two_way"))
            and not bool(getattr(state.players.get(str(row.get("player_id"))), "synthetic", False))
        ),
        None,
    )
    generated_preview = None
    generated_profile = None
    if generated_row is not None:
        generated_profile = pmap.get(str(generated_row["player_id"]))
        generated_team = normalize_team(generated_row["team"])
        opponent = next(team for team in teams if team != generated_team)
        opponent_player = rostered_rows(ledger, opponent)[0]
        generated_preview = build_franchise_trade_preview(
            runtime,
            state,
            trade_state,
            team_a=generated_team,
            team_b=opponent,
            side_a_player_ids=(generated_row["player_id"],),
            side_b_player_ids=(opponent_player["player_id"],),
            ledger=ledger,
        )

    profiles = list(snapshot.profiles)
    rostered_profiles = [p for p in profiles if p.roster_status == "rostered"]
    generated_rostered = [p for p in rostered_profiles if p.generated_player]
    generated_standard = [p for p in generated_rostered if not p.two_way and not p.synthetic]
    baseline_rostered = [p for p in rostered_profiles if not p.generated_player]
    two_way_profiles = [p for p in rostered_profiles if p.two_way]
    status_counts = Counter(p.status for p in profiles)
    source_counts = Counter(p.source for p in profiles)

    preview_codes = {check.code for check in preview.checks}
    generated_codes = (
        {check.code for check in generated_preview.checks}
        if generated_preview is not None
        else set()
    )

    state_after = digest_object(state)
    trade_after = digest_object(trade_state)

    compile_paths = [
        SRC / "franchise_player_contract_bridge_v1.py",
        SRC / "franchise_embedded_trade_center_v2.py",
        SRC / "franchise_embedded_trade_center_ui_v2.py",
        Path(__file__),
    ]
    compile_results: dict[str, str] = {}
    for path in compile_paths:
        try:
            py_compile.compile(str(path), doraise=True)
            compile_results[str(path.relative_to(ROOT))] = ""
        except Exception as exc:
            compile_results[str(path.relative_to(ROOT))] = str(exc)

    embedded_text = (SRC / "franchise_embedded_trade_center_v2.py").read_text(encoding="utf-8")
    ui_text = (SRC / "franchise_embedded_trade_center_ui_v2.py").read_text(encoding="utf-8")

    checks = {
        "validator_version_is_current": VALIDATOR_VERSION.endswith("2026-09-11"),
        "player_contract_bridge_version_is_current": snapshot.version == PLAYER_CONTRACT_BRIDGE_VERSION,
        # The Trade Center now has its own release identity. Verify the actual
        # protocol it exposes instead of requiring an obsolete version-name
        # substring from an earlier integration build.
        "embedded_trade_center_reports_current_contract_bridge": (
            preview.player_contract_bridge_version
            == PLAYER_CONTRACT_BRIDGE_VERSION
        ),
        "durable_checkpoint_exists": bool(checkpoint_hash_before),
        "snapshot_does_not_mutate_simulation_state": state_before == state_after,
        "snapshot_does_not_mutate_trade_state": trade_before == trade_after,
        "all_live_players_have_contract_profiles": len(snapshot.profiles) == len(state.players),
        "all_rostered_players_have_team_ownership": all(bool(profile.team) for profile in rostered_profiles),
        "future_season_does_not_reuse_anchor_restrictions_as_current": (
            season == BASE_LEAGUE_YEAR
            or all(
                profile.source != "verified_2026_27_player_cba_release"
                for profile in baseline_rostered
            )
        ),
        "generated_rostered_players_are_not_blanket_manual": (
            not generated_standard
            or any(profile.status == "pass" for profile in generated_standard)
        ),
        "generated_standard_sample_has_contract_profile": (
            generated_profile is None
            or generated_profile.player_id == str(generated_row["player_id"])
        ),
        "two_way_contracts_preserve_manual_guardrail": (
            not two_way_profiles
            or all(profile.status in {"manual_review", "blocked"} for profile in two_way_profiles)
        ),
        "sample_contract_evaluation_releases_status": contract_eval.status in {"pass", "manual_review", "blocked"},
        "trade_preview_invokes_player_contract_bridge": preview.player_contract_bridge_invoked,
        "trade_preview_exposes_player_contract_status": preview.player_contract_bridge_status in {"pass", "manual_review", "blocked"},
        "trade_preview_contains_player_contract_check": "franchise_player_contract_bridge_result" in preview_codes,
        "generated_player_uses_contract_bridge_not_blanket_future_manual": (
            generated_preview is None
            or (
                generated_preview.player_contract_bridge_invoked
                and "future_player_cba_bridge_required" not in generated_codes
            )
        ),
        "future_package_still_cannot_commit": not preview.can_commit,
        "generated_player_package_still_cannot_commit": (
            generated_preview is None or not generated_preview.can_commit
        ),
        "embedded_trade_center_imports_player_contract_bridge": "from franchise_player_contract_bridge_v1 import" in embedded_text,
        "embedded_ui_exposes_player_contract_bridge": (
            "Player contract eligibility bridge" in ui_text
            and '"Player Contract"' in ui_text
        ),
        "all_modified_files_compile": not any(compile_results.values()),
        "checkpoint_hash_still_unchanged": sha256(checkpoint_path) == checkpoint_hash_before,
    }
    failed = [name for name, passed in checks.items() if not passed]

    report = {
        "script": VALIDATOR_VERSION,
        "player_contract_bridge_version": PLAYER_CONTRACT_BRIDGE_VERSION,
        "embedded_trade_center_version": EMBEDDED_TRADE_CENTER_VERSION,
        "checks": checks,
        "failed_checks": failed,
        "summary": {
            "season": season,
            "phase": snapshot.phase,
            "current_day_index": snapshot.current_day_index,
            "players": len(profiles),
            "rostered_players": len(rostered_profiles),
            "generated_rostered_players": len(generated_rostered),
            "generated_standard_players": len(generated_standard),
            "baseline_rostered_players": len(baseline_rostered),
            "two_way_rostered_players": len(two_way_profiles),
            "profile_status_counts": dict(status_counts),
            "profile_source_counts": dict(source_counts),
            "sample_teams": [team_a, team_b],
            "sample_contract_bridge_status": contract_eval.status,
            "sample_overall_preview_status": preview.status,
            "sample_financial_bridge_status": preview.financial_bridge_status,
            "generated_sample_contract_status": (
                generated_preview.player_contract_bridge_status
                if generated_preview is not None
                else "not_available"
            ),
            "generated_sample_overall_status": (
                generated_preview.status
                if generated_preview is not None
                else "not_available"
            ),
        },
        "compile_results": compile_results,
        "checkpoint_sha256": checkpoint_hash_before,
        "passed": not failed,
    }

    OUTPUTS.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print("=" * 92)
    print("FRANCHISE PLAYER CONTRACT ELIGIBILITY BRIDGE V1 VALIDATION")
    print("=" * 92)
    for name, passed in checks.items():
        print(f"  {name}: {'PASS' if passed else 'FAIL'}")

    summary = report["summary"]
    print()
    print("LIVE PLAYER CONTRACT ENVIRONMENT")
    print(f"  Season: {summary['season']}")
    print(f"  Phase: {summary['phase']}")
    print(f"  Current day index: {summary['current_day_index']}")
    print(f"  Players: {summary['players']}")
    print(f"  Rostered players: {summary['rostered_players']}")
    print(f"  Generated rostered players: {summary['generated_rostered_players']}")
    print(f"  Generated standard players: {summary['generated_standard_players']}")
    print(f"  Baseline rostered players: {summary['baseline_rostered_players']}")
    print(f"  Two-way rostered players: {summary['two_way_rostered_players']}")
    print("  Profile statuses:")
    for key, value in sorted(summary["profile_status_counts"].items()):
        print(f"    {key}: {value}")
    print()
    print("SAMPLE EMBEDDED TRADE")
    print(f"  Teams: {summary['sample_teams'][0]} <-> {summary['sample_teams'][1]}")
    print(f"  Player Contract Bridge: {summary['sample_contract_bridge_status']}")
    print(f"  Financial Bridge: {summary['sample_financial_bridge_status']}")
    print(f"  Overall preview: {summary['sample_overall_preview_status']}")
    print(f"  Generated-player Contract Bridge: {summary['generated_sample_contract_status']}")
    print(f"  Generated-player overall preview: {summary['generated_sample_overall_status']}")

    if failed:
        raise AssertionError(
            "Franchise Player Contract Eligibility Bridge V1 validation failed: "
            + ", ".join(failed)
        )

    print()
    print("FRANCHISE PLAYER CONTRACT ELIGIBILITY BRIDGE V1 VALIDATION PASSED")
    print("READ-ONLY VALIDATION: no franchise player, contract, roster, trade, or draft right was mutated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
