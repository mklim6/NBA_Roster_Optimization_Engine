from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
OUTPUTS = ROOT / "outputs"

MINUTES_MODEL_VERSION = (
    "simulation-player-minutes-v1-2026-08-08"
)
SELF_TEST_REPORT = (
    OUTPUTS
    / "simulation_player_minutes_v1_self_test.json"
)

# The 10-player template sums to exactly 240 minutes. Historical evidence
# moves players away from these role priors without allowing ten players'
# previous-team workloads to overfill one new team's rotation.
ROLE_BASELINE_10 = (
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

ROLE_MINIMUM_10 = (
    30.0,
    28.0,
    26.0,
    24.0,
    22.0,
    16.0,
    13.0,
    10.0,
    6.0,
    2.0,
)

ROLE_MAXIMUM_10 = (
    38.0,
    37.0,
    36.0,
    35.0,
    34.0,
    30.0,
    27.0,
    24.0,
    20.0,
    16.0,
)


class SimulationPlayerMinutesError(
    RuntimeError
):
    """Raised when historical minute targets cannot be reconciled."""


@dataclass(frozen=True)
class PlayerMinuteEvidence:
    player_id: str
    rotation_rank: int
    starter: bool
    role_baseline: float
    observed_minutes_per_game: float | None
    reliability: float
    raw_target: float
    minimum: float
    maximum: float
    final_target: float


@dataclass(frozen=True)
class TeamMinutesPlan:
    version: str
    regulation_minutes: int
    total_minutes: float
    evidence: tuple[PlayerMinuteEvidence, ...]
    targets: dict[str, float]


def finite_float(
    value: Any,
    *,
    default: float | None = None,
) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default

    if not math.isfinite(number):
        return default

    return number


def clamp(
    value: float,
    minimum: float,
    maximum: float,
) -> float:
    return max(
        minimum,
        min(maximum, value),
    )


def role_templates(
    player_count: int,
    *,
    team_minutes: float,
) -> tuple[
    tuple[float, ...],
    tuple[float, ...],
    tuple[float, ...],
]:
    if player_count < 5:
        raise SimulationPlayerMinutesError(
            "A rotation requires at least five players."
        )

    if player_count == 10:
        scale = team_minutes / 240.0
        return (
            tuple(
                value * scale
                for value in ROLE_BASELINE_10
            ),
            tuple(
                value * scale
                for value in ROLE_MINIMUM_10
            ),
            tuple(
                value * scale
                for value in ROLE_MAXIMUM_10
            ),
        )

    # Generic fallback for nonstandard rotations. The first five slots are
    # starter-weighted and later positions decline smoothly.
    weights = tuple(
        (
            1.50 - 0.08 * rank
            if rank < 5
            else max(
                0.24,
                0.95 - 0.13 * (rank - 5),
            )
        )
        for rank in range(player_count)
    )
    total_weight = sum(weights)
    baselines = tuple(
        team_minutes
        * weight
        / total_weight
        for weight in weights
    )
    minimums = tuple(
        max(
            2.0,
            baseline
            - (
                4.0
                if rank < 5
                else 6.0
            ),
        )
        for rank, baseline
        in enumerate(baselines)
    )
    maximums = tuple(
        min(
            38.0,
            baseline
            + (
                4.0
                if rank < 5
                else 6.0
            ),
        )
        for rank, baseline
        in enumerate(baselines)
    )

    if sum(minimums) > team_minutes:
        scale = team_minutes / sum(minimums)
        minimums = tuple(
            value * scale
            for value in minimums
        )

    if sum(maximums) < team_minutes:
        scale = team_minutes / sum(maximums)
        maximums = tuple(
            min(
                48.0,
                value * scale,
            )
            for value in maximums
        )

    return baselines, minimums, maximums


def profile_minutes(
    profile: Mapping[str, Any] | None,
) -> tuple[float | None, float]:
    if not profile:
        return None, 0.0

    observed = finite_float(
        profile.get(
            "minutes_per_game"
        )
    )
    games = finite_float(
        profile.get(
            "games_played"
        ),
        default=0.0,
    )
    reliability = finite_float(
        profile.get(
            "profile_reliability"
        ),
        default=0.0,
    )

    if (
        observed is None
        or observed <= 0
    ):
        return None, 0.0

    sample_factor = clamp(
        float(games or 0.0) / 65.0,
        0.15,
        1.0,
    )
    resolved_reliability = clamp(
        float(reliability or 0.0)
        * sample_factor,
        0.0,
        1.0,
    )
    return observed, resolved_reliability


def reconcile_targets(
    raw_targets: Sequence[float],
    minimums: Sequence[float],
    maximums: Sequence[float],
    *,
    total_minutes: float,
) -> tuple[float, ...]:
    if not (
        len(raw_targets)
        == len(minimums)
        == len(maximums)
    ):
        raise SimulationPlayerMinutesError(
            "Minute target vectors have inconsistent lengths."
        )

    if sum(minimums) > total_minutes + 1e-9:
        raise SimulationPlayerMinutesError(
            "Minimum minute bounds exceed the team total."
        )

    if sum(maximums) < total_minutes - 1e-9:
        raise SimulationPlayerMinutesError(
            "Maximum minute bounds cannot absorb the team total."
        )

    low = -100.0
    high = 100.0

    for _ in range(100):
        shift = (low + high) / 2.0
        current = sum(
            clamp(
                raw + shift,
                minimum,
                maximum,
            )
            for raw, minimum, maximum
            in zip(
                raw_targets,
                minimums,
                maximums,
            )
        )

        if current < total_minutes:
            low = shift
        else:
            high = shift

    shifted = [
        clamp(
            raw + (low + high) / 2.0,
            minimum,
            maximum,
        )
        for raw, minimum, maximum
        in zip(
            raw_targets,
            minimums,
            maximums,
        )
    ]

    total_tenths = int(
        round(total_minutes * 10)
    )
    minimum_tenths = [
        int(math.ceil(value * 10 - 1e-9))
        for value in minimums
    ]
    maximum_tenths = [
        int(math.floor(value * 10 + 1e-9))
        for value in maximums
    ]
    raw_tenths = [
        value * 10.0
        for value in shifted
    ]
    allocated = [
        max(
            minimum_tenths[index],
            min(
                maximum_tenths[index],
                int(
                    math.floor(
                        raw_tenths[index]
                    )
                ),
            ),
        )
        for index in range(len(shifted))
    ]

    remaining = (
        total_tenths
        - sum(allocated)
    )

    if remaining > 0:
        order = sorted(
            range(len(allocated)),
            key=lambda index: (
                -(
                    raw_tenths[index]
                    - math.floor(
                        raw_tenths[index]
                    )
                ),
                index,
            ),
        )

        while remaining > 0:
            progressed = False

            for index in order:
                if (
                    allocated[index]
                    >= maximum_tenths[index]
                ):
                    continue

                allocated[index] += 1
                remaining -= 1
                progressed = True

                if remaining == 0:
                    break

            if not progressed:
                raise SimulationPlayerMinutesError(
                    "Unable to distribute remaining minute tenths."
                )

    elif remaining < 0:
        order = sorted(
            range(len(allocated)),
            key=lambda index: (
                (
                    raw_tenths[index]
                    - math.floor(
                        raw_tenths[index]
                    )
                ),
                -index,
            ),
        )

        while remaining < 0:
            progressed = False

            for index in order:
                if (
                    allocated[index]
                    <= minimum_tenths[index]
                ):
                    continue

                allocated[index] -= 1
                remaining += 1
                progressed = True

                if remaining == 0:
                    break

            if not progressed:
                raise SimulationPlayerMinutesError(
                    "Unable to remove excess minute tenths."
                )

    result = tuple(
        value / 10.0
        for value in allocated
    )

    if not math.isclose(
        sum(result),
        total_minutes,
        abs_tol=0.05,
    ):
        raise SimulationPlayerMinutesError(
            "Historical minute targets do not reconcile."
        )

    return result


def build_historical_minutes_plan(
    rotation_ids: Sequence[str],
    starter_ids: Sequence[str],
    profiles: Mapping[
        str,
        Mapping[str, Any],
    ],
    *,
    regulation_minutes: int = 48,
) -> TeamMinutesPlan:
    ordered_ids = tuple(
        str(player_id)
        for player_id in rotation_ids
    )

    if len(set(ordered_ids)) != len(
        ordered_ids
    ):
        raise SimulationPlayerMinutesError(
            "Rotation contains duplicate player IDs."
        )

    starter_set = {
        str(player_id)
        for player_id in starter_ids
    }

    if not starter_set.issubset(
        ordered_ids
    ):
        raise SimulationPlayerMinutesError(
            "Starters must belong to the rotation."
        )

    team_minutes = float(
        regulation_minutes * 5
    )
    (
        baselines,
        minimums,
        maximums,
    ) = role_templates(
        len(ordered_ids),
        team_minutes=team_minutes,
    )

    raw_targets: list[float] = []
    observed_values: list[
        float | None
    ] = []
    reliabilities: list[float] = []

    for rank, player_id in enumerate(
        ordered_ids
    ):
        observed, reliability = (
            profile_minutes(
                profiles.get(
                    player_id
                )
            )
        )
        # High-quality recent evidence receives up to 80% of the target.
        # The role prior still matters after trades and depth-chart changes.
        evidence_weight = (
            0.20
            + 0.60 * reliability
            if observed is not None
            else 0.0
        )
        raw = (
            baselines[rank]
            if observed is None
            else (
                baselines[rank]
                * (1.0 - evidence_weight)
                + observed
                * evidence_weight
            )
        )
        raw_targets.append(
            clamp(
                raw,
                minimums[rank],
                maximums[rank],
            )
        )
        observed_values.append(
            observed
        )
        reliabilities.append(
            reliability
        )

    final_targets = reconcile_targets(
        raw_targets,
        minimums,
        maximums,
        total_minutes=team_minutes,
    )
    evidence = tuple(
        PlayerMinuteEvidence(
            player_id=player_id,
            rotation_rank=rank + 1,
            starter=(
                player_id
                in starter_set
            ),
            role_baseline=round(
                baselines[rank],
                3,
            ),
            observed_minutes_per_game=(
                None
                if observed_values[
                    rank
                ] is None
                else round(
                    float(
                        observed_values[
                            rank
                        ]
                    ),
                    3,
                )
            ),
            reliability=round(
                reliabilities[rank],
                4,
            ),
            raw_target=round(
                raw_targets[rank],
                3,
            ),
            minimum=round(
                minimums[rank],
                3,
            ),
            maximum=round(
                maximums[rank],
                3,
            ),
            final_target=(
                final_targets[rank]
            ),
        )
        for rank, player_id
        in enumerate(ordered_ids)
    )

    return TeamMinutesPlan(
        version=MINUTES_MODEL_VERSION,
        regulation_minutes=(
            regulation_minutes
        ),
        total_minutes=round(
            sum(final_targets),
            1,
        ),
        evidence=evidence,
        targets={
            player_id: final_targets[
                rank
            ]
            for rank, player_id
            in enumerate(ordered_ids)
        },
    )


def run_self_test() -> dict[str, Any]:
    rotation_ids = tuple(
        f"P{rank}"
        for rank in range(1, 11)
    )
    starters = rotation_ids[:5]
    observed = (
        33.2,
        35.4,
        31.6,
        29.7,
        27.9,
        25.1,
        21.8,
        18.3,
        13.2,
        8.5,
    )
    profiles = {
        player_id: {
            "minutes_per_game": (
                observed[index]
            ),
            "games_played": (
                72 - index
            ),
            "profile_reliability": 0.9,
        }
        for index, player_id
        in enumerate(rotation_ids)
    }
    plan = build_historical_minutes_plan(
        rotation_ids,
        starters,
        profiles,
    )
    missing_plan = (
        build_historical_minutes_plan(
            rotation_ids,
            starters,
            {},
        )
    )

    checks = {
        "minutes_model_version_is_current": (
            plan.version
            == MINUTES_MODEL_VERSION
        ),
        "rotation_reconciles_to_240": (
            math.isclose(
                sum(
                    plan.targets.values()
                ),
                240.0,
                abs_tol=0.05,
            )
        ),
        "historical_superstars_exceed_30_minutes": (
            plan.targets["P1"] > 32.0
            and plan.targets["P2"] > 33.0
        ),
        "luka_style_workload_exceeds_sga_style_workload": (
            plan.targets["P2"]
            > plan.targets["P1"]
        ),
        "bench_roles_remain_below_starters": (
            max(
                plan.targets[
                    player_id
                ]
                for player_id
                in rotation_ids[5:]
            )
            < min(
                plan.targets[
                    player_id
                ]
                for player_id
                in rotation_ids[:5]
            )
        ),
        "all_targets_respect_bounds": all(
            item.minimum
            <= item.final_target
            <= item.maximum
            for item in plan.evidence
        ),
        "missing_profiles_use_role_template": (
            tuple(
                missing_plan.targets[
                    player_id
                ]
                for player_id
                in rotation_ids
            )
            == ROLE_BASELINE_10
        ),
        "historical_targets_are_not_uniform": (
            len(
                set(
                    plan.targets.values()
                )
            )
            >= 8
        ),
    }
    failed = [
        name
        for name, passed
        in checks.items()
        if not passed
    ]
    report = {
        "script": MINUTES_MODEL_VERSION,
        "checks": checks,
        "failed_checks": failed,
        "targets": plan.targets,
        "evidence": [
            item.__dict__
            for item in plan.evidence
        ],
        "passed": not failed,
    }

    OUTPUTS.mkdir(
        parents=True,
        exist_ok=True,
    )
    SELF_TEST_REPORT.write_text(
        json.dumps(
            report,
            indent=2,
        ),
        encoding="utf-8",
    )

    if failed:
        raise AssertionError(
            "Historical player-minutes self-test failed: "
            + ", ".join(failed)
        )

    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--self-test",
        action="store_true",
    )
    args = parser.parse_args()

    if args.self_test:
        report = run_self_test()
        print(
            json.dumps(
                report,
                indent=2,
            )
        )
        print(
            "\nSIMULATION PLAYER MINUTES "
            "V1 SELF-TEST PASSED"
        )
        return 0

    print(
        json.dumps(
            {
                "script": (
                    MINUTES_MODEL_VERSION
                ),
                "message": (
                    "Use --self-test to validate "
                    "historical minute targeting."
                ),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
