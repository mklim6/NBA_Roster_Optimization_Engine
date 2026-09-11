from __future__ import annotations

import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

import single_game_simulator_v1 as game  # noqa: E402

EXPECTED_V2 = "franchise-simulation-performance-optimization-v2-2026-08-13"
EXPECTED_V1 = "shooting-identity-performance-optimization-v1-2026-08-13"
EXPECTED_IDENTITY = "player-shooting-identity-preservation-v1.0.3-2026-08-13"


def _problem_cases(count: int = 2400):
    rng = random.Random(20260813)
    cases = []
    hand = [
        (30, (10, 22, 5, 12, 5, 6), 5, 0.5, 0.401, 0.923, 11, 5, 22),
        (27, (10, 18, 0, 1, 7, 10), 10, 10 / 17, 0.235, 0.743, 1, 8, 18),
        (25, (8, 17, 4, 9, 5, 5), 4, 0.5, 0.383, 0.831, 8, 4, 17),
        (18, (7, 14, 2, 5, 2, 2), 5, 5 / 9, 0.360, 0.770, 5, 2, 14),
        (14, (6, 12, 0, 0, 2, 4), 6, 0.5, 0.340, 0.720, 0, 3, 12),
        (9, (4, 8, 1, 3, 0, 0), 3, 0.6, 0.355, 0.760, 3, 0, 8),
        (3, (1, 4, 1, 3, 0, 0), 0, 0.0, 0.401, 0.760, 3, 0, 4),
        (2, (1, 3, 0, 0, 0, 0), 1, 1 / 3, 0.340, 0.760, 0, 0, 3),
    ]
    cases.extend(hand)
    while len(cases) < count:
        original_fga = rng.randint(1, 26)
        original_three_attempted = rng.randint(0, min(original_fga, 15))
        original_three_made = rng.randint(0, original_three_attempted)
        original_fgm = rng.randint(original_three_made, original_fga)
        original_ft_attempted = rng.randint(0, 14)
        original_ft_made = rng.randint(0, original_ft_attempted)
        original = (
            original_fgm,
            original_fga,
            original_three_made,
            original_three_attempted,
            original_ft_made,
            original_ft_attempted,
        )
        original_two_made = max(0, original_fgm - original_three_made)
        original_two_attempted = max(0, original_fga - original_three_attempted)
        original_two_pct = (
            float(original_two_made) / float(original_two_attempted)
            if original_two_attempted > 0 else 0.52
        )
        points = rng.randint(1, 46)
        target_three_pct = rng.uniform(0.10, 0.65)
        target_ft_pct = rng.uniform(0.40, 0.99)
        target_three_attempted = max(0, round(original_three_attempted * rng.uniform(0.78, 1.05)))
        target_ft_attempted = max(0, round(original_ft_attempted * rng.uniform(0.68, 1.05)))
        target_fga = max(0, round(original_fga * rng.uniform(0.88, 1.05)))
        cases.append((
            points,
            original,
            original_two_made,
            original_two_pct,
            target_three_pct,
            target_ft_pct,
            target_three_attempted,
            target_ft_attempted,
            target_fga,
        ))
    return cases


def _call_reference(case):
    return game._identity_solve_scoring_line_reference_exhaustive_v1_0_3(
        points=case[0], original=case[1], original_two_made=case[2],
        original_two_pct=case[3], target_three_pct=case[4], target_ft_pct=case[5],
        target_three_attempted=case[6], target_ft_attempted=case[7], target_fga=case[8],
    )


def _call_optimized(case):
    return game._identity_solve_scoring_line_uncached_v1_0_3(
        points=case[0], original=case[1], original_two_made=case[2],
        original_two_pct=case[3], target_three_pct=case[4], target_ft_pct=case[5],
        target_three_attempted=case[6], target_ft_attempted=case[7], target_fga=case[8],
    )


def main() -> int:
    checks: dict[str, bool] = {}
    details: dict[str, str] = {}
    checks["performance_v2_version_is_current"] = (
        getattr(game, "FRANCHISE_SIMULATION_PERFORMANCE_VERSION_V2", "") == EXPECTED_V2
    )
    checks["performance_v1_cache_layer_is_preserved"] = (
        getattr(game, "SHOOTING_IDENTITY_PERFORMANCE_VERSION", "") == EXPECTED_V1
    )
    checks["player_identity_v1_0_3_is_preserved"] = (
        getattr(game, "PLAYER_SHOOTING_IDENTITY_VERSION", "") == EXPECTED_IDENTITY
    )
    checks["v1_0_3_calibration_constants_unchanged"] = (
        abs(float(game.REGULAR_THREE_IDENTITY_ODDS_SCALE_V1_0_3) - 0.975) < 1e-12
        and abs(float(game.REGULAR_FT_IDENTITY_ODDS_SCALE_V1_0_3) - 1.08) < 1e-12
        and abs(float(game.FT_ATTEMPT_ERROR_WEIGHT_V1_0_3) - 1.80) < 1e-12
        and abs(float(game.FT_ATTEMPT_UPWARD_PENALTY_V1_0_3) - 0.40) < 1e-12
    )

    cases = _problem_cases()
    mismatch = None
    started = time.perf_counter()
    for index, case in enumerate(cases):
        reference = _call_reference(case)
        optimized = _call_optimized(case)
        if reference != optimized:
            mismatch = (index, reference, optimized)
            break
    equivalence_seconds = time.perf_counter() - started
    checks["2400_miss_path_problems_are_exactly_equal"] = mismatch is None
    details["2400_miss_path_problems_are_exactly_equal"] = (
        f"elapsed={equivalence_seconds:.3f}s" if mismatch is None
        else f"first_mismatch_index={mismatch[0]} ref={mismatch[1]} opt={mismatch[2]}"
    )

    config = game.GameSimulationConfig()
    public_equal = True
    rng_equal = True
    valid_lines = True
    public_cases = [
        (30, (10, 22, 5, 12, 5, 6)), (27, (10, 18, 0, 1, 7, 10)),
        (25, (8, 17, 4, 9, 5, 5)), (18, (7, 14, 2, 5, 2, 2)),
        (14, (6, 12, 0, 0, 2, 4)), (12, (5, 11, 1, 4, 1, 2)),
        (9, (4, 8, 1, 3, 0, 0)), (6, (3, 7, 0, 2, 0, 0)),
        (3, (1, 4, 1, 3, 0, 0)), (2, (1, 3, 0, 0, 0, 0)),
    ]
    game._identity_scoring_cache_clear_v1()
    for seed in range(96):
        for points, original in public_cases:
            ref_rng = random.Random(202608130000 + seed)
            opt_rng = random.Random(202608130000 + seed)
            reference = game._identity_preserved_scoring_line_reference_v1_0_3(
                points=points, original=original, config=config, rng=ref_rng,
            )
            optimized = game._identity_preserved_scoring_line(
                points=points, original=original, config=config, rng=opt_rng,
            )
            if reference != optimized:
                public_equal = False
            if ref_rng.random() != opt_rng.random():
                rng_equal = False
            fgm, fga, tpm, tpa, ftm, fta = optimized
            if not (
                0 <= tpm <= tpa <= fga and 0 <= ftm <= fta and 0 <= fgm <= fga
                and fgm >= tpm and 2 * (fgm - tpm) + 3 * tpm + ftm == points
            ):
                valid_lines = False
    checks["public_scoring_path_matches_exhaustive_reference"] = public_equal
    checks["public_path_consumes_identical_rng_stream"] = rng_equal
    checks["optimized_lines_preserve_scoring_invariants"] = valid_lines

    benchmark_cases = cases[:512]
    started = time.perf_counter()
    ref_bench = [_call_reference(case) for case in benchmark_cases]
    reference_seconds = time.perf_counter() - started
    started = time.perf_counter()
    opt_bench = [_call_optimized(case) for case in benchmark_cases]
    optimized_seconds = time.perf_counter() - started
    speedup = reference_seconds / max(optimized_seconds, 1e-9)
    checks["miss_path_benchmark_outputs_are_exactly_equal"] = ref_bench == opt_bench
    checks["uncached_miss_path_is_materially_faster"] = speedup >= 1.25
    details["uncached_miss_path_is_materially_faster"] = (
        f"reference={reference_seconds:.4f}s optimized={optimized_seconds:.4f}s speedup={speedup:.2f}x"
    )

    print("=" * 108)
    print("FRANCHISE SIMULATION PERFORMANCE OPTIMIZATION V2 VALIDATION")
    print("=" * 108)
    for name, passed in checks.items():
        suffix = f" | {details[name]}" if name in details else ""
        print(f"  {name}: {'PASS' if passed else 'FAIL'}{suffix}")
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise AssertionError(
            "Franchise Simulation Performance Optimization V2 failed: " + ", ".join(failed)
        )
    print()
    print("FRANCHISE SIMULATION PERFORMANCE OPTIMIZATION V2 VALIDATION PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
