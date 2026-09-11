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
from franchise_financial_cba_bridge_v1 import (
    BASE_LEAGUE_YEAR,
    FINANCIAL_BRIDGE_VERSION,
    build_franchise_financial_snapshot,
)
from franchise_live_asset_ledger_v1 import build_live_asset_ledger
from simulation_franchise_checkpoint_v1 import load_franchise_checkpoint


VALIDATOR_VERSION = "franchise-financial-cba-bridge-v1-validator-2026-08-11"
REPORT_PATH = OUTPUTS / "franchise_financial_cba_bridge_v1_validation.json"


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

    snapshot = build_franchise_financial_snapshot(runtime, state)
    ledger = build_live_asset_ledger(runtime, state, trade_state)

    team_rows = {row.team: row for row in snapshot.team_financials}
    player_rows = {row.player_id: row for row in snapshot.player_financials}
    season = str(state.settings.season_label)
    anchor_cap = float(runtime.rules["thresholds"]["salary_cap"])

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
            if row.get("generated_player") and row.get("roster_status") == "rostered"
        ),
        None,
    )
    generated_preview = None
    if generated_row is not None:
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

    state_after = digest_object(state)
    trade_after = digest_object(trade_state)

    source_counts = Counter(row.salary_source for row in snapshot.player_financials)
    rostered_financials = [
        row for row in snapshot.player_financials if row.roster_status == "rostered"
    ]
    generated_rostered = [row for row in rostered_financials if row.generated_player]
    team_payrolls = [row.modeled_team_salary for row in snapshot.team_financials]
    preview_codes = {check.code for check in preview.checks}

    compile_paths = [
        SRC / "franchise_financial_cba_bridge_v1.py",
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
        "validator_version_is_current": VALIDATOR_VERSION.endswith("2026-08-11"),
        "financial_bridge_version_is_current": snapshot.version == FINANCIAL_BRIDGE_VERSION,
        "embedded_trade_center_version_is_financial_bridge_build": "financial-bridge-v1" in EMBEDDED_TRADE_CENTER_VERSION,
        "durable_checkpoint_exists": bool(checkpoint_hash_before),
        "snapshot_does_not_mutate_simulation_state": state_before == state_after,
        "snapshot_does_not_mutate_trade_state": trade_before == trade_after,
        "future_thresholds_anchor_to_2026_27": BASE_LEAGUE_YEAR == str(runtime.rules.get("league_year")),
        "current_season_thresholds_are_modeled_forward": (
            season == BASE_LEAGUE_YEAR
            or (
                snapshot.thresholds.years_after_anchor > 0
                and snapshot.thresholds.salary_cap > anchor_cap
                and snapshot.thresholds.first_apron > snapshot.thresholds.salary_cap
                and snapshot.thresholds.second_apron > snapshot.thresholds.first_apron
            )
        ),
        "all_30_team_financial_rows_exist": len(snapshot.team_financials) == 30,
        "all_live_players_have_financial_rows": len(snapshot.player_financials) == len(state.players),
        "all_rostered_standard_players_have_positive_trade_salary": all(
            row.two_way or row.modeled_trade_salary > 0
            for row in rostered_financials
        ),
        "generated_rostered_players_receive_future_salary_treatment": (
            not generated_rostered
            or all(
                row.salary_source in {
                    "live_generated_contract_salary",
                    "modeled_rookie_scale_proxy",
                    "modeled_generated_market_salary_proxy",
                }
                and row.modeled_trade_salary >= 0
                for row in generated_rostered
            )
        ),
        "team_payrolls_are_nonnegative": all(value >= 0 for value in team_payrolls),
        "team_roster_counts_match_live_state": all(
            team_rows[normalize_team(team)].total_roster_count
            == len(getattr(team_state, "roster_player_ids", ()))
            for team, team_state in state.teams.items()
            if normalize_team(team) in team_rows
        ),
        "trade_preview_invokes_financial_bridge": preview.financial_bridge_invoked,
        "trade_preview_exposes_financial_status": preview.financial_bridge_status in {"pass", "manual_review", "blocked"},
        "trade_preview_contains_financial_checks": "franchise_future_financial_bridge_result" in preview_codes,
        "future_package_still_cannot_commit": not preview.can_commit,
        "generated_player_package_still_cannot_commit": (
            generated_preview is None or not generated_preview.can_commit
        ),
        "embedded_trade_center_imports_financial_bridge": "from franchise_financial_cba_bridge_v1 import" in embedded_text,
        "embedded_ui_exposes_financial_bridge": "Future-season financial bridge" in ui_text and '"Financial Bridge"' in ui_text,
        "all_modified_files_compile": not any(compile_results.values()),
        "checkpoint_hash_still_unchanged": sha256(checkpoint_path) == checkpoint_hash_before,
    }
    failed = [name for name, passed in checks.items() if not passed]

    report = {
        "script": VALIDATOR_VERSION,
        "financial_bridge_version": FINANCIAL_BRIDGE_VERSION,
        "embedded_trade_center_version": EMBEDDED_TRADE_CENTER_VERSION,
        "checks": checks,
        "failed_checks": failed,
        "summary": {
            "season": season,
            "anchor_league_year": BASE_LEAGUE_YEAR,
            "annual_cap_growth_assumption": snapshot.thresholds.annual_cap_growth,
            "salary_cap": snapshot.thresholds.salary_cap,
            "tax_level": snapshot.thresholds.tax_level,
            "first_apron": snapshot.thresholds.first_apron,
            "second_apron": snapshot.thresholds.second_apron,
            "players": len(snapshot.player_financials),
            "rostered_players": len(rostered_financials),
            "generated_rostered_players": len(generated_rostered),
            "teams": len(snapshot.team_financials),
            "team_payroll_min": min(team_payrolls) if team_payrolls else 0,
            "team_payroll_max": max(team_payrolls) if team_payrolls else 0,
            "salary_sources": dict(source_counts),
            "sample_teams": [team_a, team_b],
            "sample_preview_status": preview.status,
            "sample_financial_bridge_status": preview.financial_bridge_status,
            "sample_canonical_engine_invoked": preview.canonical_engine_invoked,
            "generated_sample_financial_status": (
                generated_preview.financial_bridge_status
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
    print("FRANCHISE FINANCIAL / CBA BRIDGE V1 VALIDATION")
    print("=" * 92)
    for name, passed in checks.items():
        print(f"  {name}: {'PASS' if passed else 'FAIL'}")

    summary = report["summary"]
    print()
    print("SIMULATED LEAGUE FINANCIAL ENVIRONMENT")
    print(f"  Season: {summary['season']}")
    print(f"  Anchor league year: {summary['anchor_league_year']}")
    print(f"  Annual cap growth assumption: {summary['annual_cap_growth_assumption']:.1%}")
    print(f"  Salary cap: ${summary['salary_cap']:,.0f}")
    print(f"  Tax level: ${summary['tax_level']:,.0f}")
    print(f"  First apron: ${summary['first_apron']:,.0f}")
    print(f"  Second apron: ${summary['second_apron']:,.0f}")
    print()
    print("LIVE PAYROLL COVERAGE")
    print(f"  Players: {summary['players']}")
    print(f"  Rostered players: {summary['rostered_players']}")
    print(f"  Generated rostered players: {summary['generated_rostered_players']}")
    print(f"  Teams: {summary['teams']}")
    print(f"  Team payroll range: ${summary['team_payroll_min']:,.0f} -> ${summary['team_payroll_max']:,.0f}")
    print("  Salary sources:")
    for key, value in sorted(summary["salary_sources"].items()):
        print(f"    {key}: {value}")
    print()
    print("SAMPLE EMBEDDED TRADE")
    print(f"  Teams: {summary['sample_teams'][0]} <-> {summary['sample_teams'][1]}")
    print(f"  Overall preview: {summary['sample_preview_status']}")
    print(f"  Financial bridge: {summary['sample_financial_bridge_status']}")
    print(f"  Canonical 2026-27 engine invoked: {summary['sample_canonical_engine_invoked']}")
    print(f"  Generated-player financial sample: {summary['generated_sample_financial_status']}")

    if failed:
        raise AssertionError(
            "Franchise Financial / CBA Bridge V1 validation failed: "
            + ", ".join(failed)
        )

    print()
    print("FRANCHISE FINANCIAL / CBA BRIDGE V1 VALIDATION PASSED")
    print("READ-ONLY VALIDATION: no franchise financial state, roster, contract, trade, or draft right was mutated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
