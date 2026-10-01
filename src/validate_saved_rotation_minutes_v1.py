from __future__ import annotations

import ast
import json
import math
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
OUTPUTS = ROOT / "outputs"
TARGET = SRC / "single_game_simulator_v1.py"

VALIDATOR_VERSION = (
    "saved-rotation-minutes-validator-v1-2026-08-08"
)
REPORT_PATH = (
    OUTPUTS
    / "saved_rotation_minutes_validation_v1.json"
)


def load_installed_allocation_function() -> Callable[..., dict[str, float]]:
    if not TARGET.exists():
        raise FileNotFoundError(
            f"Simulator source does not exist: {TARGET}"
        )

    source = TARGET.read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)
    required_names = {
        "allocate_integer_units",
        "allocate_bounded_integer_units",
        "allocate_minutes",
    }
    selected = [
        node
        for node in tree.body
        if isinstance(
            node,
            (ast.FunctionDef, ast.AsyncFunctionDef),
        )
        and node.name in required_names
    ]
    found = {
        node.name
        for node in selected
    }

    if found != required_names:
        missing = sorted(
            required_names - found
        )
        raise RuntimeError(
            "Could not extract installed allocation functions: "
            + ", ".join(missing)
        )

    isolated = ast.Module(
        body=[
            ast.ImportFrom(
                module="__future__",
                names=[
                    ast.alias(
                        name="annotations"
                    )
                ],
                level=0,
            ),
            *selected,
        ],
        type_ignores=[],
    )
    ast.fix_missing_locations(isolated)
    namespace: dict[str, Any] = {
        "math": math,
        "SingleGameSimulationError": RuntimeError,
        # This validator isolates allocate_minutes() from the installed
        # simulator. Medical/load-management caps are tested elsewhere, so
        # use the function's own default maximum here and keep this validator
        # focused on saved rotation target preservation.
        "player_minutes_cap": (
            lambda state, player_id, *, day_index, default_maximum:
                float(default_maximum)
        ),
        # Coaching Workload Redistribution V1 is identity behavior when the
        # saved starting five is healthy. This validator intentionally models
        # that healthy path, so inject exact neutral multipliers rather than
        # importing the complete coaching dependency graph.
        "coaching_minute_weight_multipliers_v1": (
            lambda state, team, *, rotation_ids, starter_ids:
                {player_id: 1.0 for player_id in rotation_ids}
        ),
    }
    exec(
        compile(
            isolated,
            str(TARGET),
            "exec",
        ),
        namespace,
    )
    return namespace[
        "allocate_minutes"
    ]


def build_state(
    targets: dict[str, float],
) -> Any:
    return SimpleNamespace(
        current_day_index=0,
        settings=SimpleNamespace(
            regulation_minutes=48,
            overtime_minutes=5,
        ),
        teams={
            "TST": SimpleNamespace(
                rotation=SimpleNamespace(
                    minutes_targets=dict(
                        targets
                    )
                )
            )
        },
    )


def run_validation() -> dict[str, Any]:
    allocate_minutes = (
        load_installed_allocation_function()
    )
    rotation_ids = tuple(
        f"P{index}"
        for index in range(1, 11)
    )
    starter_ids = rotation_ids[:5]
    expected_values = (
        34.0,
        32.5,
        31.0,
        29.5,
        28.0,
        24.0,
        21.0,
        18.0,
        14.0,
        8.0,
    )
    expected = {
        player_id: expected_values[index]
        for index, player_id
        in enumerate(rotation_ids)
    }

    actual = allocate_minutes(
        build_state(expected),
        "TST",
        rotation_ids,
        starter_ids,
        overtime_periods=0,
    )
    maximum_difference = max(
        abs(
            actual[player_id]
            - expected[player_id]
        )
        for player_id in rotation_ids
    )

    missing_target = dict(expected)
    missing_target["P10"] = 0.0
    fallback_result = allocate_minutes(
        build_state(missing_target),
        "TST",
        rotation_ids,
        starter_ids,
        overtime_periods=0,
    )

    source_text = TARGET.read_text(
        encoding="utf-8"
    )
    checks = {
        "validator_version_is_current": (
            VALIDATOR_VERSION.endswith(
                "2026-08-08"
            )
        ),
        "saved_target_branch_is_installed": (
            "if saved > 0.0"
            in source_text
            and "else max(\n                fallback,"
            in source_text
        ),
        "saved_targets_reconcile_to_240": (
            math.isclose(
                sum(expected.values()),
                240.0,
                abs_tol=0.01,
            )
        ),
        "game_plan_preserves_saved_targets": (
            maximum_difference <= 0.1
        ),
        "star_workloads_remain_above_32": (
            actual["P1"] > 32.0
            and actual["P2"] > 32.0
        ),
        "low_minute_bench_roles_are_not_forced_to_18": (
            actual["P9"] == 14.0
            and actual["P10"] == 8.0
        ),
        "normal_rotation_stays_below_38": (
            max(actual.values()) <= 38.0
        ),
        "missing_target_fallback_still_reconciles": (
            math.isclose(
                sum(fallback_result.values()),
                240.0,
                abs_tol=0.05,
            )
            and fallback_result["P10"] > 0.0
        ),
        "all_outputs_are_finite": all(
            math.isfinite(value)
            for value
            in (
                *actual.values(),
                *fallback_result.values(),
            )
        ),
    }
    failed = [
        name
        for name, passed
        in checks.items()
        if not passed
    ]
    report = {
        "script": VALIDATOR_VERSION,
        "checks": checks,
        "failed_checks": failed,
        "expected_targets": expected,
        "actual_minutes": actual,
        "maximum_target_difference": round(
            maximum_difference,
            4,
        ),
        "missing_target_fallback_minutes": (
            fallback_result
        ),
        "passed": not failed,
    }

    OUTPUTS.mkdir(
        parents=True,
        exist_ok=True,
    )
    REPORT_PATH.write_text(
        json.dumps(
            report,
            indent=2,
        ),
        encoding="utf-8",
    )

    if failed:
        raise AssertionError(
            "Saved rotation minute validation failed: "
            + ", ".join(failed)
        )

    return report


def main() -> int:
    report = run_validation()
    print(
        json.dumps(
            report,
            indent=2,
        )
    )
    print(
        "\nSAVED ROTATION MINUTES VALIDATION PASSED"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
