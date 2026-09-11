from __future__ import annotations

import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

import single_game_simulator_v1 as game  # noqa: E402

EXPECTED_PERFORMANCE_VERSION = "shooting-identity-performance-optimization-v1-2026-08-13"
EXPECTED_IDENTITY_VERSION = "player-shooting-identity-preservation-v1.0.3-2026-08-13"


def main() -> int:
    checks: dict[str, bool] = {}
    details: dict[str, str] = {}

    checks["performance_version_is_current"] = (
        getattr(game, "SHOOTING_IDENTITY_PERFORMANCE_VERSION", "")
        == EXPECTED_PERFORMANCE_VERSION
    )
    checks["player_identity_v1_0_3_is_preserved"] = (
        getattr(game, "PLAYER_SHOOTING_IDENTITY_VERSION", "")
        == EXPECTED_IDENTITY_VERSION
    )
    checks["v1_0_3_regular_three_center_is_unchanged"] = (
        abs(float(game.REGULAR_THREE_IDENTITY_ODDS_SCALE_V1_0_3) - 0.975) < 1e-12
    )
    checks["v1_0_3_regular_ft_center_is_unchanged"] = (
        abs(float(game.REGULAR_FT_IDENTITY_ODDS_SCALE_V1_0_3) - 1.08) < 1e-12
    )
    checks["v1_0_3_fta_penalties_are_unchanged"] = (
        abs(float(game.FT_ATTEMPT_ERROR_WEIGHT_V1_0_3) - 1.80) < 1e-12
        and abs(float(game.FT_ATTEMPT_UPWARD_PENALTY_V1_0_3) - 0.40) < 1e-12
    )

    config = game.GameSimulationConfig()
    cases = [
        (30, (10, 22, 5, 12, 5, 6)),
        (27, (10, 18, 0, 1, 7, 10)),
        (25, (8, 17, 4, 9, 5, 5)),
        (18, (7, 14, 2, 5, 2, 2)),
        (14, (6, 12, 0, 0, 2, 4)),
        (12, (5, 11, 1, 4, 1, 2)),
        (9, (4, 8, 1, 3, 0, 0)),
        (6, (3, 7, 0, 2, 0, 0)),
        (3, (1, 4, 1, 3, 0, 0)),
        (2, (1, 3, 0, 0, 0, 0)),
    ]

    game._identity_scoring_cache_clear_v1()
    all_equal = True
    rng_equal = True
    valid_lines = True

    for seed in range(64):
        for points, original in cases:
            ref_rng = random.Random(202608130000 + seed)
            opt_rng = random.Random(202608130000 + seed)
            reference = game._identity_preserved_scoring_line_reference_v1_0_3(
                points=points,
                original=original,
                config=config,
                rng=ref_rng,
            )
            optimized = game._identity_preserved_scoring_line(
                points=points,
                original=original,
                config=config,
                rng=opt_rng,
            )
            if reference != optimized:
                all_equal = False
            if ref_rng.random() != opt_rng.random():
                rng_equal = False
            fgm, fga, tpm, tpa, ftm, fta = optimized
            if not (
                0 <= tpm <= tpa <= fga
                and 0 <= ftm <= fta
                and 0 <= fgm <= fga
                and fgm >= tpm
                and 2 * (fgm - tpm) + 3 * tpm + ftm == points
            ):
                valid_lines = False

    checks["optimized_lines_are_exactly_reference_equal"] = all_equal
    checks["optimized_path_consumes_identical_rng_stream"] = rng_equal
    checks["optimized_lines_preserve_all_scoring_invariants"] = valid_lines

    workload = []
    for _repeat in range(32):
        for index, (points, original) in enumerate(cases):
            workload.append((points, original, 1000 + index))

    started = time.perf_counter()
    reference_outputs = [
        game._identity_preserved_scoring_line_reference_v1_0_3(
            points=points,
            original=original,
            config=config,
            rng=random.Random(seed),
        )
        for points, original, seed in workload
    ]
    reference_seconds = time.perf_counter() - started

    game._identity_scoring_cache_clear_v1()
    started = time.perf_counter()
    optimized_outputs = [
        game._identity_preserved_scoring_line(
            points=points,
            original=original,
            config=config,
            rng=random.Random(seed),
        )
        for points, original, seed in workload
    ]
    optimized_seconds = time.perf_counter() - started

    info = game._identity_scoring_cache_info_v1()
    speedup = reference_seconds / max(optimized_seconds, 1e-9)
    checks["benchmark_outputs_are_exactly_equal"] = (
        reference_outputs == optimized_outputs
    )
    checks["memoization_records_real_cache_hits"] = (
        int(info.hits) > int(info.misses) * 5
    )
    details["memoization_records_real_cache_hits"] = (
        f"hits={info.hits} misses={info.misses}"
    )
    checks["hot_path_is_materially_faster"] = speedup >= 2.0
    details["hot_path_is_materially_faster"] = (
        f"reference={reference_seconds:.4f}s optimized={optimized_seconds:.4f}s "
        f"speedup={speedup:.2f}x"
    )

    print("=" * 104)
    print("SHOOTING IDENTITY PERFORMANCE OPTIMIZATION V1 VALIDATION")
    print("=" * 104)
    for name, passed in checks.items():
        suffix = f" | {details[name]}" if name in details else ""
        print(f"  {name}: {'PASS' if passed else 'FAIL'}{suffix}")

    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise AssertionError(
            "Shooting identity performance optimization failed: "
            + ", ".join(failed)
        )

    print()
    print("SHOOTING IDENTITY PERFORMANCE OPTIMIZATION V1 VALIDATION PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
