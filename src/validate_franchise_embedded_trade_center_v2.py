from __future__ import annotations

import hashlib
import json
import py_compile
import sys
from pathlib import Path
from typing import Any

try:
    import cloudpickle as _serializer
except ImportError:  # pragma: no cover
    import pickle as _serializer

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
from simulation_franchise_checkpoint_v1 import load_franchise_checkpoint


VALIDATOR_VERSION = "franchise-embedded-trade-center-v2-validator-v1-2026-08-11"
REPORT_PATH = OUTPUTS / "franchise_embedded_trade_center_v2_validation.json"


def digest_object(value: Any) -> str:
    return hashlib.sha256(_serializer.dumps(value)).hexdigest()


def sha256(path: Path) -> str:
    if not path.is_file():
        return ""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _rostered_players(ledger: Any, team: str) -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in ledger.player_rows
        if normalize_team(row.get("team")) == team and row.get("roster_status") == "rostered"
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
    ledger = build_live_asset_ledger(runtime, state, trade_state)
    state_before = digest_object(state)
    trade_before = digest_object(trade_state)

    teams = [
        normalize_team(team)
        for team in state.teams
        if _rostered_players(ledger, normalize_team(team))
    ]
    if len(teams) < 2:
        raise AssertionError("Need at least two teams with rostered players for trade-center validation.")
    team_a, team_b = teams[0], teams[1]
    a_player = _rostered_players(ledger, team_a)[0]
    b_player = _rostered_players(ledger, team_b)[0]

    preview = build_franchise_trade_preview(
        runtime,
        state,
        trade_state,
        team_a=team_a,
        team_b=team_b,
        side_a_player_ids=(a_player["player_id"],),
        side_b_player_ids=(b_player["player_id"],),
        ledger=ledger,
    )

    generated_preview = None
    generated_row = next(
        (
            dict(row)
            for row in ledger.player_rows
            if row.get("generated_player") and row.get("roster_status") == "rostered"
        ),
        None,
    )
    if generated_row is not None:
        generated_team = normalize_team(generated_row["team"])
        opponent = next(
            team for team in teams
            if team != generated_team and _rostered_players(ledger, team)
        )
        opponent_player = _rostered_players(ledger, opponent)[0]
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

    manual_pick_preview = None
    manual_pick = next(
        (dict(row) for row in ledger.draft_rows if row.get("manual_review_required")),
        None,
    )
    if manual_pick is not None:
        pick_team = normalize_team(manual_pick["current_owner"])
        opponent = next(team for team in teams if team != pick_team and _rostered_players(ledger, team))
        opponent_player = _rostered_players(ledger, opponent)[0]
        manual_pick_preview = build_franchise_trade_preview(
            runtime,
            state,
            trade_state,
            team_a=pick_team,
            team_b=opponent,
            side_a_pick_asset_ids=(manual_pick["asset_id"],),
            side_b_player_ids=(opponent_player["player_id"],),
            ledger=ledger,
        )

    state_after = digest_object(state)
    trade_after = digest_object(trade_state)
    season = str(state.settings.season_label)
    runtime_year = str(runtime.rules.get("league_year") or "")
    future_guard_expected = season != runtime_year

    backend = SRC / "franchise_embedded_trade_center_v2.py"
    ui = SRC / "franchise_embedded_trade_center_ui_v2.py"
    ledger_ui = SRC / "franchise_live_asset_ledger_ui_v1.py"
    validator_path = Path(__file__)
    compile_results = {}
    for path in (backend, ui, ledger_ui, validator_path):
        try:
            py_compile.compile(str(path), doraise=True)
            compile_results[str(path.relative_to(ROOT))] = ""
        except Exception as exc:
            compile_results[str(path.relative_to(ROOT))] = str(exc)

    ui_text = ledger_ui.read_text(encoding="utf-8") if ledger_ui.is_file() else ""
    embedded_ui_text = ui.read_text(encoding="utf-8") if ui.is_file() else ""
    preview_codes = {check.code for check in preview.checks}
    generated_codes = (
        {check.code for check in generated_preview.checks}
        if generated_preview is not None
        else set()
    )
    manual_pick_codes = (
        {check.code for check in manual_pick_preview.checks}
        if manual_pick_preview is not None
        else set()
    )

    checks = {
        "validator_version_is_current": VALIDATOR_VERSION.endswith("2026-08-11"),
        "trade_center_version_is_current": preview.version == EMBEDDED_TRADE_CENTER_VERSION,
        "durable_checkpoint_exists": bool(checkpoint_hash_before),
        "preview_does_not_mutate_simulation_state": state_before == state_after,
        "preview_does_not_mutate_trade_state": trade_before == trade_after,
        "live_player_ownership_is_checked": "player_live_ownership_verified" in preview_codes,
        "live_salary_is_exposed_in_preview": preview.side_a.outgoing_salary >= 0 and preview.side_b.outgoing_salary >= 0,
        "roster_floor_math_is_exposed": "live_roster_floor_preserved" in preview_codes,
        "future_season_runtime_guard_applies": (
            (not future_guard_expected)
            or (
                not preview.canonical_engine_invoked
                and "canonical_engine_not_released_for_live_package" in preview_codes
                and preview.status == "manual_review"
            )
        ),
        "generated_player_is_live_selectable_but_manual": (
            generated_preview is None
            or (
                generated_preview.status == "manual_review"
                and "future_player_cba_bridge_required" in generated_codes
            )
        ),
        "manual_draft_asset_remains_manual": (
            manual_pick_preview is None
            or (
                manual_pick_preview.status == "manual_review"
                and "pick_trade_engine_bridge_required" in manual_pick_codes
            )
        ),
        "commit_is_disabled_for_all_previews": (
            not preview.can_commit
            and (generated_preview is None or not generated_preview.can_commit)
            and (manual_pick_preview is None or not manual_pick_preview.can_commit)
        ),
        "ledger_ui_calls_embedded_trade_center": "render_embedded_trade_center_v2(" in ui_text,
        "embedded_ui_has_preview_marker": "FRANCHISE_EMBEDDED_TRADE_CENTER_V2_PREVIEW" in embedded_ui_text,
        "embedded_ui_has_no_commit_trade_button": '"Commit trade"' not in embedded_ui_text and "commit_trade" not in embedded_ui_text,
        "all_modified_files_compile": not any(compile_results.values()),
        "checkpoint_hash_still_unchanged": sha256(checkpoint_path) == checkpoint_hash_before,
    }
    failed = [name for name, passed in checks.items() if not passed]
    report = {
        "script": VALIDATOR_VERSION,
        "trade_center_version": EMBEDDED_TRADE_CENTER_VERSION,
        "checks": checks,
        "failed_checks": failed,
        "summary": {
            "season": season,
            "runtime_league_year": runtime_year,
            "live_players": len(ledger.player_rows),
            "generated_players": ledger.generated_player_count,
            "draft_rows": len(ledger.draft_rows),
            "engine_ready_pick_rows": ledger.engine_ready_pick_count,
            "manual_pick_rows": ledger.draft_manual_review_count,
            "sample_team_a": team_a,
            "sample_team_b": team_b,
            "sample_status": preview.status,
            "canonical_engine_invoked": preview.canonical_engine_invoked,
            "generated_sample_status": generated_preview.status if generated_preview else "not_available",
            "manual_pick_sample_status": manual_pick_preview.status if manual_pick_preview else "not_available",
        },
        "compile_results": compile_results,
        "checkpoint_sha256": checkpoint_hash_before,
        "passed": not failed,
    }
    OUTPUTS.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print("=" * 92)
    print("EMBEDDED FRANCHISE TRADE CENTER V2 PREVIEW VALIDATION")
    print("=" * 92)
    for name, passed in checks.items():
        print(f"  {name}: {'PASS' if passed else 'FAIL'}")
    summary = report["summary"]
    print()
    print("LIVE TRADE BRIDGE")
    print(f"  Franchise season: {summary['season']}")
    print(f"  Verified engine league year: {summary['runtime_league_year']}")
    print(f"  Live players: {summary['live_players']}")
    print(f"  Generated / drafted players: {summary['generated_players']}")
    print(f"  Draft-capital rows: {summary['draft_rows']}")
    print(f"  Engine-ready pick rows: {summary['engine_ready_pick_rows']}")
    print(f"  Manual / bridge pick rows: {summary['manual_pick_rows']}")
    print()
    print("SAMPLE LIVE PACKAGE")
    print(f"  Teams: {summary['sample_team_a']} <-> {summary['sample_team_b']}")
    print(f"  Preview status: {summary['sample_status']}")
    print(f"  Canonical engine invoked: {summary['canonical_engine_invoked']}")
    print(f"  Generated-player sample: {summary['generated_sample_status']}")
    print(f"  Manual-pick sample: {summary['manual_pick_sample_status']}")
    if failed:
        raise AssertionError("Embedded Trade Center V2 validation failed: " + ", ".join(failed))
    print()
    print("EMBEDDED FRANCHISE TRADE CENTER V2 PREVIEW VALIDATION PASSED")
    print("READ-ONLY VALIDATION: no trade, roster, contract, or draft-right mutation was committed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
