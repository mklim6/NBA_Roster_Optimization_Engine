from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
OUTPUTS = ROOT / "outputs"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import freeform_trade_machine_engine_v3 as engine  # noqa: E402

from freeform_trade_machine_engine_v3 import (  # noqa: E402
    TRADE_DATE,
    VALIDATION_REVISION,
    Status,
    TradeRequest,
    TradeSideRequest,
    clean_text,
    evaluate_trade,
    load_runtime_data,
    normalize_player_id,
    normalize_team,
    run_self_test,
    split_player_ids,
    to_bool,
    validate_against_v9,
    validate_pick_pipeline_against_v9,
)


SCRIPT_VERSION = "trade-machine-v3-integration-validation-v1-1-2026-08-07"

# Stepien calculations use the same authoritative calendar and trade date
# repeatedly. Cache that immutable baseline during this validation run so
# hundreds of mixed-package checks do not rebuild the same Arrow-backed
# DataFrame thousands of times.
_ORIGINAL_BUILD_STEPIEN_BASELINE = engine.build_stepien_baseline
_STEPIEN_BASELINE_CACHE: dict[tuple[int, str], Any] = {}


def cached_build_stepien_baseline(
    runtime: Any,
    trade_date: Any,
) -> Any:
    key = (id(runtime), str(trade_date))

    if key not in _STEPIEN_BASELINE_CACHE:
        _STEPIEN_BASELINE_CACHE[key] = (
            _ORIGINAL_BUILD_STEPIEN_BASELINE(
                runtime,
                trade_date,
            )
        )

    return _STEPIEN_BASELINE_CACHE[key]


engine.build_stepien_baseline = cached_build_stepien_baseline
REPORT_JSON = OUTPUTS / "trade_machine_v3_integration_validation_v1.json"
CASES_CSV = OUTPUTS / "trade_machine_v3_integration_cases_v1.csv"


@dataclass
class CaseResult:
    case_name: str
    passed: bool
    expected_status: str
    actual_status: str
    expected_code: str
    observed_codes: str
    details: str
    hard_gate: bool = True


def result_codes(result: Any) -> list[str]:
    checks = [
        *result.checks,
        *result.side_a.checks,
        *result.side_b.checks,
    ]
    return [str(check.code) for check in checks]


def evaluate_case(
    *,
    runtime: Any,
    case_name: str,
    request: TradeRequest,
    expected_status: Status,
    expected_code: str,
    details: str = "",
    hard_gate: bool = True,
) -> CaseResult:
    result = evaluate_trade(runtime, request)
    codes = result_codes(result)
    passed = (
        result.status == expected_status
        and expected_code in codes
    )

    return CaseResult(
        case_name=case_name,
        passed=passed,
        expected_status=expected_status.value,
        actual_status=result.status.value,
        expected_code=expected_code,
        observed_codes="|".join(codes),
        details=details,
        hard_gate=hard_gate,
    )


def runtime_teams(runtime: Any) -> list[str]:
    return sorted(
        team
        for team in runtime.team_salary_by_team
        if team
    )


def distinct_team(runtime: Any, excluded: str) -> str:
    return next(
        team
        for team in runtime_teams(runtime)
        if team != normalize_team(excluded)
    )


def first_runtime_player(runtime: Any) -> tuple[str, str]:
    for player_id, record in runtime.trade_by_id.items():
        team = normalize_team(
            record.get("current_team_2026_27")
        )
        if team in runtime.team_salary_by_team:
            return normalize_player_id(player_id), team

    raise AssertionError("No runtime player with a valid team was found.")


def first_standalone_pick(runtime: Any) -> tuple[str, str]:
    for row in runtime.picks.to_dict(orient="records"):
        if to_bool(row.get("standalone_trade_asset_flag")) is not True:
            continue

        pick_id = clean_text(row.get("future_pick_right_id"))
        team = normalize_team(row.get("candidate_team"))

        if pick_id and team in runtime.team_salary_by_team:
            return pick_id, team

    raise AssertionError("No standalone draft right was found.")


def find_pick_only_example(
    runtime: Any,
    target_status: Status,
) -> tuple[str, str, Any]:
    standalone = runtime.picks.loc[
        runtime.picks["standalone_trade_asset_flag"]
        .map(to_bool)
        .eq(True)
    ].copy()

    for row in standalone.to_dict(orient="records"):
        pick_id = clean_text(row.get("future_pick_right_id"))
        team = normalize_team(row.get("candidate_team"))

        if (
            not pick_id
            or team not in runtime.team_salary_by_team
        ):
            continue

        other = distinct_team(runtime, team)
        result = evaluate_trade(
            runtime,
            TradeRequest(
                side_a=TradeSideRequest(
                    team_abbreviation=team,
                    pick_right_ids=(pick_id,),
                ),
                side_b=TradeSideRequest(
                    team_abbreviation=other,
                ),
            ),
        )

        if result.status == target_status:
            return pick_id, team, result

    raise AssertionError(
        f"No pick-only {target_status.value} example was found."
    )


def mixed_package_coverage(
    runtime: Any,
    sample_size: int,
) -> dict[str, Any]:
    files = {
        "one_for_one": (
            OUTPUTS
            / "one_for_one_mixed_player_pick_candidates_2026_27_v9_final_full_cba_evaluated.parquet"
        ),
        "two_for_one": (
            OUTPUTS
            / "two_for_one_mixed_player_pick_candidates_2026_27_v9_final_full_cba_evaluated.parquet"
        ),
    }

    columns = [
        "optimizer_candidate_id",
        "team_a",
        "team_b",
        "side_a_player_ids",
        "side_b_player_ids",
        "attached_pick_team",
        "attached_pick_right_id",
    ]

    missing = [
        str(path)
        for path in files.values()
        if not path.exists()
    ]
    if missing:
        raise FileNotFoundError(
            "Mixed-package V9 files are missing:\n"
            + "\n".join(missing)
        )

    branch_reports: dict[str, Any] = {}
    overall_statuses: Counter[str] = Counter()
    total_evaluated = 0
    exceptions: list[dict[str, Any]] = []

    for branch, path in files.items():
        frame = pd.read_parquet(path, columns=columns)
        selected = frame.sample(
            n=min(sample_size, len(frame)),
            random_state=20260807,
        )

        branch_statuses: Counter[str] = Counter()
        branch_evaluated = 0

        for row in selected.to_dict(orient="records"):
            team_a = normalize_team(row.get("team_a"))
            team_b = normalize_team(row.get("team_b"))
            pick_team = normalize_team(
                row.get("attached_pick_team")
            )
            pick_id = clean_text(
                row.get("attached_pick_right_id")
            )

            if (
                not team_a
                or not team_b
                or not pick_id
                or pick_team not in {team_a, team_b}
            ):
                continue

            side_a_picks = (
                (pick_id,) if pick_team == team_a else ()
            )
            side_b_picks = (
                (pick_id,) if pick_team == team_b else ()
            )

            request = TradeRequest(
                side_a=TradeSideRequest(
                    team_abbreviation=team_a,
                    player_ids=tuple(
                        split_player_ids(
                            row.get("side_a_player_ids")
                        )
                    ),
                    pick_right_ids=side_a_picks,
                ),
                side_b=TradeSideRequest(
                    team_abbreviation=team_b,
                    player_ids=tuple(
                        split_player_ids(
                            row.get("side_b_player_ids")
                        )
                    ),
                    pick_right_ids=side_b_picks,
                ),
            )

            try:
                result = evaluate_trade(runtime, request)
            except Exception as exc:  # pragma: no cover
                if len(exceptions) < 20:
                    exceptions.append(
                        {
                            "branch": branch,
                            "candidate_id": row.get(
                                "optimizer_candidate_id"
                            ),
                            "error": repr(exc),
                        }
                    )
                continue

            status = result.status.value
            branch_statuses[status] += 1
            overall_statuses[status] += 1
            branch_evaluated += 1
            total_evaluated += 1

        branch_reports[branch] = {
            "sampled_rows": len(selected),
            "evaluated_mixed_packages": branch_evaluated,
            "status_counts": dict(branch_statuses),
        }

    return {
        "branches": branch_reports,
        "total_evaluated_mixed_packages": total_evaluated,
        "status_counts": dict(overall_statuses),
        "exceptions": exceptions,
        "passed": (
            total_evaluated > 0
            and not exceptions
            and sum(overall_statuses.values())
            == total_evaluated
        ),
    }


def build_request_cases(runtime: Any) -> list[CaseResult]:
    player_id, player_team = first_runtime_player(runtime)
    other_team = distinct_team(runtime, player_team)
    pick_id, pick_team = first_standalone_pick(runtime)
    other_pick_team = distinct_team(runtime, pick_team)

    cases = [
        evaluate_case(
            runtime=runtime,
            case_name="same_team_blocked",
            request=TradeRequest(
                side_a=TradeSideRequest(
                    team_abbreviation=player_team,
                ),
                side_b=TradeSideRequest(
                    team_abbreviation=player_team,
                ),
            ),
            expected_status=Status.BLOCKED,
            expected_code="same_team_on_both_sides",
        ),
        evaluate_case(
            runtime=runtime,
            case_name="unknown_team_blocked",
            request=TradeRequest(
                side_a=TradeSideRequest(
                    team_abbreviation="ZZZ",
                ),
                side_b=TradeSideRequest(
                    team_abbreviation=player_team,
                ),
            ),
            expected_status=Status.BLOCKED,
            expected_code="team_not_found",
        ),
        evaluate_case(
            runtime=runtime,
            case_name="duplicate_player_blocked",
            request=TradeRequest(
                side_a=TradeSideRequest(
                    team_abbreviation=player_team,
                    player_ids=(player_id, player_id),
                ),
                side_b=TradeSideRequest(
                    team_abbreviation=other_team,
                ),
            ),
            expected_status=Status.BLOCKED,
            expected_code="duplicate_player_on_side",
            details=f"player_id={player_id}",
        ),
        evaluate_case(
            runtime=runtime,
            case_name="player_roster_mismatch_blocked",
            request=TradeRequest(
                side_a=TradeSideRequest(
                    team_abbreviation=other_team,
                    player_ids=(player_id,),
                ),
                side_b=TradeSideRequest(
                    team_abbreviation=player_team,
                ),
            ),
            expected_status=Status.BLOCKED,
            expected_code="player_roster_mismatch",
            details=(
                f"player_id={player_id}; "
                f"actual_team={player_team}; "
                f"submitted_team={other_team}"
            ),
        ),
        evaluate_case(
            runtime=runtime,
            case_name="unknown_player_blocked",
            request=TradeRequest(
                side_a=TradeSideRequest(
                    team_abbreviation=player_team,
                    player_ids=("NOT_A_REAL_PLAYER_ID",),
                ),
                side_b=TradeSideRequest(
                    team_abbreviation=other_team,
                ),
            ),
            expected_status=Status.BLOCKED,
            expected_code="player_not_in_trade_pool",
        ),
        evaluate_case(
            runtime=runtime,
            case_name="duplicate_pick_blocked",
            request=TradeRequest(
                side_a=TradeSideRequest(
                    team_abbreviation=pick_team,
                    pick_right_ids=(pick_id, pick_id),
                ),
                side_b=TradeSideRequest(
                    team_abbreviation=other_pick_team,
                ),
            ),
            expected_status=Status.BLOCKED,
            expected_code="duplicate_pick_on_side",
            details=f"pick_right_id={pick_id}",
        ),
        evaluate_case(
            runtime=runtime,
            case_name="unknown_pick_blocked",
            request=TradeRequest(
                side_a=TradeSideRequest(
                    team_abbreviation=pick_team,
                    pick_right_ids=("NOT_A_REAL_PICK_RIGHT",),
                ),
                side_b=TradeSideRequest(
                    team_abbreviation=other_pick_team,
                ),
            ),
            expected_status=Status.BLOCKED,
            expected_code="pick_right_not_found",
        ),
        evaluate_case(
            runtime=runtime,
            case_name="pick_ownership_mismatch_blocked",
            request=TradeRequest(
                side_a=TradeSideRequest(
                    team_abbreviation=other_pick_team,
                    pick_right_ids=(pick_id,),
                ),
                side_b=TradeSideRequest(
                    team_abbreviation=pick_team,
                ),
            ),
            expected_status=Status.BLOCKED,
            expected_code="pick_ownership_mismatch",
            details=(
                f"pick_right_id={pick_id}; "
                f"actual_team={pick_team}; "
                f"submitted_team={other_pick_team}"
            ),
        ),
        evaluate_case(
            runtime=runtime,
            case_name="empty_trade_rejected",
            request=TradeRequest(
                side_a=TradeSideRequest(
                    team_abbreviation=player_team,
                ),
                side_b=TradeSideRequest(
                    team_abbreviation=other_team,
                ),
            ),
            expected_status=Status.BLOCKED,
            expected_code="empty_trade",
            details=(
                "A request with no players or draft rights "
                "should not be released as a valid trade."
            ),
        ),
    ]

    for target in [
        Status.PASS,
        Status.MANUAL_REVIEW,
        Status.BLOCKED,
    ]:
        pick_example_id, team, result = find_pick_only_example(
            runtime,
            target,
        )
        codes = result_codes(result)
        cases.append(
            CaseResult(
                case_name=(
                    f"pick_only_{target.value}_example"
                ),
                passed=result.status == target,
                expected_status=target.value,
                actual_status=result.status.value,
                expected_code="",
                observed_codes="|".join(codes),
                details=(
                    f"pick_right_id={pick_example_id}; "
                    f"team={team}"
                ),
                hard_gate=True,
            )
        )

    return cases


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--sample-size",
        type=int,
        default=500,
        help=(
            "Rows sampled per V9 branch for salary, pick, "
            "and mixed-package integration validation."
        ),
    )
    parser.add_argument(
        "--skip-v9",
        action="store_true",
        help="Run request guardrails without V9 comparisons.",
    )
    args = parser.parse_args()
    sample_size = max(1, args.sample_size)

    OUTPUTS.mkdir(parents=True, exist_ok=True)

    print("Loading V3 runtime...")
    runtime = load_runtime_data()

    print("Running V3 engine self-test...")
    engine_self_test = run_self_test()

    print("Running request guardrail cases...")
    cases = build_request_cases(runtime)
    case_frame = pd.DataFrame(
        [asdict(case) for case in cases]
    )
    case_frame.to_csv(CASES_CSV, index=False)

    salary_validation: dict[str, Any] | None = None
    pick_validation: dict[str, Any] | None = None
    mixed_validation: dict[str, Any] | None = None

    if not args.skip_v9:
        print(
            f"Validating salary routes against V9 "
            f"({sample_size} rows per branch)..."
        )
        salary_validation = validate_against_v9(
            runtime,
            sample_size,
        )

        print(
            f"Validating pick and Stepien results against V9 "
            f"({sample_size} rows per branch)..."
        )
        pick_validation = validate_pick_pipeline_against_v9(
            runtime,
            sample_size,
        )

        print(
            f"Evaluating mixed player-and-pick packages "
            f"({sample_size} rows per branch)..."
        )
        mixed_validation = mixed_package_coverage(
            runtime,
            sample_size,
        )

    failed_hard_cases = case_frame.loc[
        case_frame["hard_gate"].eq(True)
        & case_frame["passed"].eq(False)
    ]["case_name"].tolist()

    checks = {
        "engine_self_test_passed": all(
            engine_self_test["checks"].values()
        ),
        "request_guardrails_passed": (
            len(failed_hard_cases) == 0
        ),
        "salary_v9_validation_passed": (
            True
            if salary_validation is None
            else bool(salary_validation["passed"])
        ),
        "pick_v9_validation_passed": (
            True
            if pick_validation is None
            else bool(pick_validation["passed"])
        ),
        "mixed_package_evaluation_passed": (
            True
            if mixed_validation is None
            else bool(mixed_validation["passed"])
        ),
    }

    report = {
        "script": SCRIPT_VERSION,
        "trade_date": TRADE_DATE,
        "engine_validation_revision": VALIDATION_REVISION,
        "sample_size_per_v9_branch": (
            None if args.skip_v9 else sample_size
        ),
        "checks": checks,
        "failed_request_cases": failed_hard_cases,
        "request_case_counts": {
            "total": int(len(case_frame)),
            "passed": int(case_frame["passed"].sum()),
            "failed": int((~case_frame["passed"]).sum()),
        },
        "salary_validation": salary_validation,
        "pick_validation": pick_validation,
        "mixed_package_validation": mixed_validation,
        "outputs": {
            "report_json": str(REPORT_JSON),
            "cases_csv": str(CASES_CSV),
        },
    }

    REPORT_JSON.write_text(
        json.dumps(report, indent=2, default=str),
        encoding="utf-8",
    )

    print("=" * 100)
    print("TRADE MACHINE V3 INTEGRATION VALIDATION")
    print("=" * 100)
    print(case_frame.to_string(index=False))
    print()
    print("CHECKS")
    print(json.dumps(checks, indent=2))
    print()
    print("FAILED REQUEST CASES")
    print(
        json.dumps(failed_hard_cases, indent=2)
    )
    print()
    print("OUTPUTS")
    print(f"  {REPORT_JSON}")
    print(f"  {CASES_CSV}")

    if not all(checks.values()):
        raise AssertionError(
            "Trade Machine V3 integration validation failed: "
            + ", ".join(
                name
                for name, passed in checks.items()
                if not passed
            )
        )

    print()
    print("TRADE MACHINE V3 INTEGRATION VALIDATION PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())