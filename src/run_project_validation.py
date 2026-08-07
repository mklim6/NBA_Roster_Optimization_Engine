from __future__ import annotations

import argparse
import json
import py_compile
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
PAGES = ROOT / "pages"
OUTPUTS = ROOT / "outputs"
HOME = ROOT / "Home.py"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from freeform_trade_machine_engine_v3 import (  # noqa: E402
    Status,
    load_runtime_data,
    normalize_player_id,
    normalize_team,
)
from league_scenario_store_v1 import (  # noqa: E402
    delete_scenario,
    list_scenarios,
    load_scenario,
    operational_signature,
    save_scenario,
)
from mutable_league_state_v1 import (  # noqa: E402
    apply_passed_trade,
    create_league_state,
    find_pass_player_trade,
    reset_league_state,
    undo_last_trade,
    validate_state,
)
from state_runtime_adapter_v1 import (  # noqa: E402
    build_state_runtime,
    validate_state_runtime,
)
from trade_mode_policy_v1 import (  # noqa: E402
    SandboxDisposition,
    TradeMode,
    apply_trade_in_mode,
    classify_trade,
    find_forceable_blocked_trade,
    find_missing_cba_manual_trade,
)
from simulation_roster_validator_v1 import (  # noqa: E402
    build_simulation_roster_snapshot,
    snapshot_report,
)


VALIDATOR_VERSION = (
    "project-validation-runner-v1.2-2026-08-08"
)
QUICK_REPORT = (
    OUTPUTS / "project_validation_quick_v1.json"
)
FULL_REPORT = (
    OUTPUTS / "project_validation_full_v1.json"
)


class ProjectValidationError(RuntimeError):
    """Raised when a project validation check fails."""


def elapsed_seconds(started: float) -> float:
    return round(time.perf_counter() - started, 3)


def runtime_signature(runtime: Any) -> dict[str, Any]:
    return {
        "players": tuple(
            sorted(
                (
                    player_id,
                    normalize_team(
                        record.get(
                            "current_team_2026_27"
                        )
                    ),
                )
                for player_id, record in (
                    runtime.trade_by_id.items()
                )
            )
        ),
        "draft_rights": tuple(
            sorted(
                (
                    pick_right_id,
                    normalize_team(
                        record.get("candidate_team")
                    ),
                )
                for pick_right_id, record in (
                    runtime.pick_by_id.items()
                )
            )
        ),
        "team_salaries": tuple(
            sorted(
                (
                    team,
                    record.get(
                        "verified_team_salary_value"
                    ),
                    record.get(
                        (
                            "verified_apron_"
                            "team_salary_value"
                        )
                    ),
                    record.get("hard_cap_level"),
                )
                for team, record in (
                    runtime.team_cba_by_team.items()
                )
            )
        ),
    }


def record_check(
    checks: list[dict[str, Any]],
    *,
    phase: str,
    name: str,
    passed: bool,
    details: str = "",
    seconds: float = 0.0,
) -> None:
    checks.append(
        {
            "phase": phase,
            "name": name,
            "passed": bool(passed),
            "seconds": round(seconds, 3),
            "details": details,
        }
    )


def require(
    checks: list[dict[str, Any]],
    *,
    phase: str,
    name: str,
    condition: bool,
    details: str = "",
    seconds: float = 0.0,
) -> None:
    record_check(
        checks,
        phase=phase,
        name=name,
        passed=condition,
        details=details,
        seconds=seconds,
    )

    if not condition:
        raise ProjectValidationError(
            f"{phase}/{name} failed"
            + (f": {details}" if details else "")
        )


def python_sources() -> list[Path]:
    sources: list[Path] = []

    if HOME.exists():
        sources.append(HOME)

    if SRC.exists():
        sources.extend(
            sorted(SRC.glob("*.py"))
        )

    if PAGES.exists():
        sources.extend(
            sorted(PAGES.glob("*.py"))
        )

    return sources


def compile_project(
    checks: list[dict[str, Any]],
) -> None:
    started = time.perf_counter()
    sources = python_sources()
    failures: list[str] = []

    for path in sources:
        try:
            py_compile.compile(
                str(path),
                doraise=True,
            )
        except py_compile.PyCompileError as exc:
            failures.append(
                f"{path.relative_to(ROOT)}: {exc}"
            )

    require(
        checks,
        phase="compile",
        name="all_project_python_compiles",
        condition=not failures,
        details=(
            f"{len(sources)} file(s) checked"
            if not failures
            else " | ".join(failures)
        ),
        seconds=elapsed_seconds(started),
    )


def validate_required_files(
    checks: list[dict[str, Any]],
) -> None:
    required = [
        HOME,
        PAGES / "3_Trade_Machine.py",
        SRC / "freeform_trade_machine_engine_v3.py",
        SRC / "mutable_league_state_v1.py",
        SRC / "state_runtime_adapter_v1.py",
        SRC / "league_scenario_store_v1.py",
        SRC / "trade_mode_policy_v1.py",
        SRC / "simulation_roster_validator_v1.py",
        SRC
        / "validate_mutable_league_state_integration_v1.py",
    ]
    missing = [
        str(path.relative_to(ROOT))
        for path in required
        if not path.exists()
    ]

    require(
        checks,
        phase="structure",
        name="required_foundation_files_exist",
        condition=not missing,
        details=(
            f"{len(required)} required file(s)"
            if not missing
            else "Missing: " + ", ".join(missing)
        ),
    )


def validate_ui_contract(
    checks: list[dict[str, Any]],
) -> None:
    page = PAGES / "3_Trade_Machine.py"
    text = page.read_text(encoding="utf-8")

    markers = {
        "mutable_state_panel": (
            "trade_machine_league_state"
        ),
        "stale_audit_guard": "audited_revision",
        "same_team_guard": (
            "disabled=(team_a == team_b)"
        ),
        "revision_widget_keys": (
            "r{league_state.state_revision}"
        ),
        "scenario_save": "Save current league",
        "scenario_load": "Load scenario",
        "scenario_export": "Export scenario JSON",
        "scenario_import": "Import and load scenario",
        "scenario_delete": (
            "trade_machine_delete_scenario"
        ),
        "unsaved_changes_label": "unsaved changes",
        "sandbox_mode_selector": "Sandbox Mode",
        "realism_mode_selector": "Realism Mode",
        "sandbox_apply": "Apply sandbox trade",
        "force_trade": "Force trade",
        "mode_policy_session": (
            "trade_machine_last_policy"
        ),
        "mode_policy_apply": "apply_trade_in_mode",
    }

    missing = [
        name
        for name, marker in markers.items()
        if marker not in text
    ]

    require(
        checks,
        phase="ui_contract",
        name="trade_machine_foundation_markers_present",
        condition=not missing,
        details=(
            f"{len(markers)} marker(s)"
            if not missing
            else "Missing: " + ", ".join(missing)
        ),
    )

    gitignore = ROOT / ".gitignore"
    ignored = (
        gitignore.exists()
        and (
            "app_data/league_scenarios/*.json"
            in gitignore.read_text(
                encoding="utf-8"
            )
        )
    )
    require(
        checks,
        phase="ui_contract",
        name="scenario_json_files_are_gitignored",
        condition=ignored,
        details=(
            "Scenario ignore rule present"
            if ignored
            else (
                "Missing app_data/league_scenarios/"
                "*.json from .gitignore"
            )
        ),
    )


def quick_runtime_validation(
    checks: list[dict[str, Any]],
) -> dict[str, Any]:
    started = time.perf_counter()
    runtime = load_runtime_data()
    load_seconds = elapsed_seconds(started)

    require(
        checks,
        phase="runtime",
        name="base_runtime_loaded",
        condition=(
            len(runtime.trade_by_id) > 0
            and len(runtime.pick_by_id) > 0
            and len(runtime.team_cba_by_team) == 30
        ),
        details=(
            f"players={len(runtime.trade_by_id)}; "
            f"draft_rights={len(runtime.pick_by_id)}; "
            f"teams={len(runtime.team_cba_by_team)}"
        ),
        seconds=load_seconds,
    )

    base_signature_before = runtime_signature(runtime)
    state = create_league_state(runtime)

    state_checks = validate_state(
        state,
        runtime,
    )
    require(
        checks,
        phase="runtime",
        name="initial_mutable_state_valid",
        condition=all(state_checks.values()),
        details=(
            "all checks passed"
            if all(state_checks.values())
            else ", ".join(
                name
                for name, passed
                in state_checks.items()
                if not passed
            )
        ),
    )

    adapted_initial = build_state_runtime(
        runtime,
        state,
    )
    adapter_checks = validate_state_runtime(
        runtime,
        adapted_initial,
        state,
    )
    require(
        checks,
        phase="runtime",
        name="initial_state_runtime_adapter_valid",
        condition=all(adapter_checks.values()),
        details=(
            "all checks passed"
            if all(adapter_checks.values())
            else ", ".join(
                name
                for name, passed
                in adapter_checks.items()
                if not passed
            )
        ),
    )

    roster_started = time.perf_counter()
    roster_snapshot = build_simulation_roster_snapshot(
        adapted_initial,
        state,
    )
    roster_report = snapshot_report(
        roster_snapshot
    )

    require(
        checks,
        phase="simulation_rosters",
        name="all_30_teams_ready_for_game",
        condition=(
            roster_snapshot.ready
            and len(roster_snapshot.teams) == 30
            and roster_report["summary"]["ready_teams"] == 30
        ),
        details=(
            f"ready={roster_report['summary']['ready_teams']}; "
            f"teams={roster_report['summary']['teams']}"
        ),
        seconds=elapsed_seconds(roster_started),
    )
    require(
        checks,
        phase="simulation_rosters",
        name="baseline_needs_no_emergency_replacements",
        condition=(
            roster_report["summary"]["replacement_players"] == 0
        ),
        details=(
            "replacement_players="
            f"{roster_report['summary']['replacement_players']}"
        ),
    )
    require(
        checks,
        phase="simulation_rosters",
        name="baseline_has_no_missing_ratings",
        condition=(
            roster_report["summary"]["fallback_rating_players"] == 0
        ),
        details=(
            "fallback_rating_players="
            f"{roster_report['summary']['fallback_rating_players']}"
        ),
    )

    trade_started = time.perf_counter()
    request, result = find_pass_player_trade(
        adapted_initial
    )
    require(
        checks,
        phase="transaction",
        name="deterministic_pass_trade_found",
        condition=result.status == Status.PASS,
        details=(
            f"{request.side_a.team_abbreviation} ↔ "
            f"{request.side_b.team_abbreviation}; "
            f"status={result.status.value}"
        ),
        seconds=elapsed_seconds(trade_started),
    )

    verified_policy = classify_trade(
        adapted_initial,
        request,
        mode=TradeMode.SANDBOX,
    )
    require(
        checks,
        phase="trade_modes",
        name="strict_pass_remains_sandbox_verified",
        condition=(
            verified_policy.disposition
            == SandboxDisposition.VERIFIED
            and verified_policy.can_apply_without_force
            and not verified_policy.force_allowed
        ),
        details=verified_policy.verification_label,
    )

    manual_request, manual_policy = (
        find_missing_cba_manual_trade(
            adapted_initial
        )
    )
    require(
        checks,
        phase="trade_modes",
        name="missing_cba_trade_is_playable_with_warning",
        condition=(
            manual_policy.disposition
            == SandboxDisposition.PLAYABLE_WITH_WARNING
            and manual_policy.can_apply_without_force
            and "player_cba_evidence_missing"
            in manual_policy.manual_review_codes
        ),
        details=(
            f"{manual_request.side_a.team_abbreviation} ↔ "
            f"{manual_request.side_b.team_abbreviation}"
        ),
    )

    sandbox_state = create_league_state(runtime)
    sandbox_runtime = build_state_runtime(
        runtime,
        sandbox_state,
    )
    sandbox_applied = apply_trade_in_mode(
        sandbox_state,
        sandbox_runtime,
        manual_request,
        mode=TradeMode.SANDBOX,
    )
    sandbox_adapted = build_state_runtime(
        runtime,
        sandbox_state,
    )
    require(
        checks,
        phase="trade_modes",
        name="sandbox_warning_trade_mutates_valid_state",
        condition=(
            sandbox_applied.transaction.transaction_id
            == "TXN-0001"
            and all(
                validate_state(
                    sandbox_state,
                    runtime,
                ).values()
            )
            and all(
                validate_state_runtime(
                    runtime,
                    sandbox_adapted,
                    sandbox_state,
                ).values()
            )
        ),
        details=(
            sandbox_applied.policy.verification_label
        ),
    )

    force_request, force_policy = (
        find_forceable_blocked_trade(
            adapted_initial
        )
    )
    require(
        checks,
        phase="trade_modes",
        name="nonstructural_block_requires_force",
        condition=(
            force_policy.disposition
            == SandboxDisposition.FORCE_REQUIRED
            and force_policy.requires_force
            and force_policy.force_allowed
            and not force_policy.structural_codes
        ),
        details=(
            f"{force_request.side_a.team_abbreviation} ↔ "
            f"{force_request.side_b.team_abbreviation}"
        ),
    )

    record = apply_passed_trade(
        state,
        adapted_initial,
        request,
        result,
    )
    adapted_after_trade = build_state_runtime(
        runtime,
        state,
    )

    team_a = normalize_team(
        request.side_a.team_abbreviation
    )
    team_b = normalize_team(
        request.side_b.team_abbreviation
    )
    moved_players = (
        all(
            state.player_team_by_id[
                normalize_player_id(player_id)
            ]
            == team_b
            for player_id
            in request.side_a.player_ids
        )
        and all(
            state.player_team_by_id[
                normalize_player_id(player_id)
            ]
            == team_a
            for player_id
            in request.side_b.player_ids
        )
    )

    require(
        checks,
        phase="transaction",
        name="passed_trade_mutates_rosters",
        condition=moved_players,
        details=record.transaction_id,
    )

    posttrade_checks = validate_state_runtime(
        runtime,
        adapted_after_trade,
        state,
    )
    require(
        checks,
        phase="transaction",
        name="runtime_valid_after_trade",
        condition=all(posttrade_checks.values()),
        details=(
            f"revision={state.state_revision}; "
            f"transactions={len(state.transaction_history)}"
        ),
    )

    scenario_summary: dict[str, Any] = {}

    OUTPUTS.mkdir(
        parents=True,
        exist_ok=True,
    )
    with tempfile.TemporaryDirectory(
        prefix="project_validation_quick_",
        dir=OUTPUTS,
    ) as temporary:
        directory = Path(temporary)
        saved = save_scenario(
            state,
            runtime,
            "Quick Validation Universe",
            notes=(
                "Temporary project validation scenario."
            ),
            directory=directory,
        )
        loaded, loaded_summary = load_scenario(
            saved.name,
            runtime,
            directory=directory,
        )

        require(
            checks,
            phase="scenario",
            name="scenario_round_trip_exact",
            condition=(
                operational_signature(loaded)
                == operational_signature(state)
            ),
            details=loaded_summary.name,
        )

        listed = list_scenarios(
            runtime,
            directory=directory,
        )
        require(
            checks,
            phase="scenario",
            name="scenario_library_lists_saved_universe",
            condition=(
                len(listed) == 1
                and listed[0].valid
                and listed[0].name
                == "Quick Validation Universe"
            ),
            details=f"listed={len(listed)}",
        )

        removed = undo_last_trade(
            loaded,
            runtime,
        )
        require(
            checks,
            phase="scenario",
            name="loaded_undo_stack_operates",
            condition=(
                removed.transaction_id
                == record.transaction_id
                and not loaded.transaction_history
            ),
            details=removed.transaction_id,
        )

        loaded_again, _ = load_scenario(
            saved.name,
            runtime,
            directory=directory,
        )
        before_reset_revision = (
            loaded_again.state_revision
        )
        reset_league_state(
            loaded_again,
            runtime,
        )
        require(
            checks,
            phase="scenario",
            name="loaded_reset_operates",
            condition=(
                not loaded_again.transaction_history
                and not loaded_again.undo_stack
                and loaded_again.state_revision
                == before_reset_revision + 1
                and all(
                    validate_state(
                        loaded_again,
                        runtime,
                    ).values()
                )
            ),
            details=(
                f"revision={loaded_again.state_revision}"
            ),
        )

        deleted = delete_scenario(
            saved.name,
            directory=directory,
        )
        require(
            checks,
            phase="scenario",
            name="scenario_delete_operates",
            condition=not deleted.exists(),
            details=deleted.name,
        )

        scenario_summary = asdict(loaded_summary)

    require(
        checks,
        phase="immutability",
        name="base_runtime_not_mutated",
        condition=(
            runtime_signature(runtime)
            == base_signature_before
        ),
        details="Static runtime signature unchanged",
    )

    return {
        "trade": {
            "transaction_id": record.transaction_id,
            "team_a": team_a,
            "team_b": team_b,
            "side_a_player_ids": list(
                request.side_a.player_ids
            ),
            "side_b_player_ids": list(
                request.side_b.player_ids
            ),
        },
        "scenario": scenario_summary,
        "trade_modes": {
            "verified_label": (
                verified_policy.verification_label
            ),
            "manual_warning_matchup": (
                f"{manual_request.side_a.team_abbreviation} ↔ "
                f"{manual_request.side_b.team_abbreviation}"
            ),
            "force_matchup": (
                f"{force_request.side_a.team_abbreviation} ↔ "
                f"{force_request.side_b.team_abbreviation}"
            ),
        },
        "simulation_rosters": roster_report["summary"],
    }


def run_subprocess_suite(
    checks: list[dict[str, Any]],
    *,
    name: str,
    command: list[str],
) -> None:
    started = time.perf_counter()
    print(
        "\n"
        + "=" * 88
        + f"\nRUNNING FULL SUITE: {name}\n"
        + "=" * 88
    )
    completed = subprocess.run(
        command,
        cwd=ROOT,
        check=False,
    )
    seconds = elapsed_seconds(started)

    require(
        checks,
        phase="full_suite",
        name=name,
        condition=completed.returncode == 0,
        details=(
            "exit_code="
            f"{completed.returncode}; "
            f"command={' '.join(command)}"
        ),
        seconds=seconds,
    )


def run_quick() -> dict[str, Any]:
    started = time.perf_counter()
    checks: list[dict[str, Any]] = []
    summary: dict[str, Any] = {}

    validate_required_files(checks)
    compile_project(checks)
    validate_ui_contract(checks)
    summary = quick_runtime_validation(checks)

    failed = [
        check
        for check in checks
        if not check["passed"]
    ]
    report = {
        "script": VALIDATOR_VERSION,
        "mode": "quick",
        "elapsed_seconds": elapsed_seconds(started),
        "checks": checks,
        "failed_checks": failed,
        "summary": summary,
        "passed": not failed,
    }

    OUTPUTS.mkdir(
        parents=True,
        exist_ok=True,
    )
    QUICK_REPORT.write_text(
        json.dumps(
            report,
            indent=2,
        ),
        encoding="utf-8",
    )

    if failed:
        raise ProjectValidationError(
            "Quick project validation failed."
        )

    return report


def run_full() -> dict[str, Any]:
    started = time.perf_counter()
    quick_report = run_quick()
    checks = list(quick_report["checks"])

    run_subprocess_suite(
        checks,
        name="trade_machine_v3_integration",
        command=[
            sys.executable,
            str(
                SRC
                / (
                    "validate_trade_machine_"
                    "v3_integration_v1.py"
                )
            ),
            "--sample-size",
            "500",
        ],
    )
    run_subprocess_suite(
        checks,
        name="mutable_league_state_integration",
        command=[
            sys.executable,
            str(
                SRC
                / (
                    "validate_mutable_league_"
                    "state_integration_v1.py"
                )
            ),
        ],
    )
    run_subprocess_suite(
        checks,
        name="scenario_store_self_test",
        command=[
            sys.executable,
            str(
                SRC / "league_scenario_store_v1.py"
            ),
            "--self-test",
        ],
    )
    run_subprocess_suite(
        checks,
        name="trade_mode_policy_self_test",
        command=[
            sys.executable,
            str(
                SRC / "trade_mode_policy_v1.py"
            ),
            "--self-test",
        ],
    )
    run_subprocess_suite(
        checks,
        name="simulation_roster_validator_self_test",
        command=[
            sys.executable,
            str(
                SRC / "simulation_roster_validator_v1.py"
            ),
            "--self-test",
        ],
    )

    failed = [
        check
        for check in checks
        if not check["passed"]
    ]
    report = {
        "script": VALIDATOR_VERSION,
        "mode": "full",
        "elapsed_seconds": elapsed_seconds(started),
        "checks": checks,
        "failed_checks": failed,
        "quick_summary": quick_report["summary"],
        "passed": not failed,
    }

    FULL_REPORT.write_text(
        json.dumps(
            report,
            indent=2,
        ),
        encoding="utf-8",
    )

    if failed:
        raise ProjectValidationError(
            "Full project validation failed."
        )

    return report


def print_report(report: dict[str, Any]) -> None:
    print("\n" + "=" * 88)
    print(
        f"PROJECT VALIDATION: "
        f"{report['mode'].upper()}"
    )
    print("=" * 88)

    for check in report["checks"]:
        status = (
            "PASS"
            if check["passed"]
            else "FAIL"
        )
        print(
            f"{status:<4}  "
            f"{check['phase']:<16}  "
            f"{check['name']:<45}  "
            f"{check['seconds']:>8.3f}s"
        )
        if check["details"]:
            print(
                "      "
                + str(check["details"])
            )

    print("-" * 88)
    print(
        f"Checks: {len(report['checks'])} | "
        f"Failed: {len(report['failed_checks'])} | "
        f"Elapsed: "
        f"{report['elapsed_seconds']:.3f}s"
    )

    if report["passed"]:
        print(
            "\nPROJECT VALIDATION PASSED"
        )
    else:
        print(
            "\nPROJECT VALIDATION FAILED"
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--quick",
        action="store_true",
        help=(
            "Compile the project and run one fast "
            "end-to-end foundation smoke test."
        ),
    )
    mode.add_argument(
        "--full",
        action="store_true",
        help=(
            "Run the quick suite plus the expensive "
            "Trade Machine and mutable-state validators."
        ),
    )
    args = parser.parse_args()

    try:
        report = (
            run_full()
            if args.full
            else run_quick()
        )
    except (
        ProjectValidationError,
        FileNotFoundError,
        OSError,
        ValueError,
        KeyError,
        TypeError,
    ) as exc:
        print(
            f"\nPROJECT VALIDATION FAILED: {exc}",
            file=sys.stderr,
        )
        return 1

    print_report(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())