from __future__ import annotations

import importlib
import random
import sys
from pathlib import Path

ROOT = Path.cwd()
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))


def points_from_line(line):
    fgm, _fga, three_made, _three_attempted, ft_made, _fta = line
    two_made = int(fgm) - int(three_made)
    return 2 * two_made + 3 * int(three_made) + int(ft_made)


def rate(made, attempted):
    return (float(made) / float(attempted)) if attempted else None


def main() -> int:
    import single_game_simulator_v1 as game
    game = importlib.reload(game)

    checks = {}
    checks["identity_marker_is_live"] = bool(
        getattr(game, "_PLAYER_SHOOTING_IDENTITY_PRESERVATION_V1_0_3", False)
    )
    checks["identity_version_is_current"] = (
        getattr(game, "PLAYER_SHOOTING_IDENTITY_VERSION", "")
        == "player-shooting-identity-preservation-v1.0.3-2026-08-13"
    )
    checks["regular_three_identity_recenter_is_current"] = (
        abs(float(getattr(game, "REGULAR_THREE_IDENTITY_ODDS_SCALE_V1_0_3", 0.0)) - 0.975) < 1e-12
    )
    checks["regular_ft_identity_recenter_is_current"] = (
        abs(float(getattr(game, "REGULAR_FT_IDENTITY_ODDS_SCALE_V1_0_3", 0.0)) - 1.08) < 1e-12
    )
    checks["ft_attempt_target_penalty_is_current"] = (
        abs(float(getattr(game, "FT_ATTEMPT_ERROR_WEIGHT_V1_0_3", 0.0)) - 1.80) < 1e-12
        and abs(float(getattr(game, "FT_ATTEMPT_UPWARD_PENALTY_V1_0_3", 0.0)) - 0.40) < 1e-12
    )
    checks["v1_0_9_regular_environment_is_frozen"] = (
        abs(float(game.GameSimulationConfig().three_attempt_multiplier) - 0.904) < 1e-12
        and abs(float(game.GameSimulationConfig().free_throw_attempt_multiplier) - 0.843) < 1e-12
        and abs(float(game.GameSimulationConfig().field_goal_attempt_multiplier) - 0.988) < 1e-12
    )
    postseason = game.postseason_game_config()
    checks["v1_0_9_postseason_environment_is_frozen"] = (
        abs(float(postseason.three_attempt_multiplier) - 1.000) < 1e-12
        and abs(float(postseason.free_throw_attempt_multiplier) - 0.862) < 1e-12
        and abs(float(postseason.field_goal_attempt_multiplier) - 1.020) < 1e-12
    )

    original_function = game._scoring_components_pre_realism_v1_0_3
    try:
        profiles = [
            # points, original line: FGM,FGA,3PM,3PA,FTM,FTA
            (24, (8, 16, 3, 8, 5, 6)),
            (27, (10, 20, 2, 7, 5, 8)),
            (18, (7, 13, 0, 0, 4, 6)),
            (31, (10, 21, 4, 10, 7, 8)),
            (12, (5, 9, 1, 3, 1, 2)),
        ]
        produced = []
        for index, (points, original_line) in enumerate(profiles):
            def stub(*args, _line=original_line, **kwargs):
                return _line
            game._scoring_components_pre_realism_v1_0_3 = stub
            output = game.scoring_components(
                random.Random(9100 + index),
                points=points,
                position="PG/SG",
                overall_rating=86.0,
                player_id=f"TEST{index}",
                config=game.GameSimulationConfig(),
            )
            produced.append((points, original_line, output))

        checks["all_test_lines_preserve_exact_points"] = all(
            points_from_line(output) == points
            for points, _original, output in produced
        )
        checks["all_test_lines_have_valid_made_attempt_relationships"] = all(
            output[0] <= output[1]
            and output[2] <= output[3]
            and output[4] <= output[5]
            and output[2] <= output[0]
            for _points, _original, output in produced
        )

        three_diffs = []
        ft_diffs = []
        for _points, original, output in produced:
            original_three = rate(original[2], original[3])
            output_three = rate(output[2], output[3])
            if original_three is not None and output_three is not None:
                three_diffs.append(abs(output_three - original_three))
            original_ft = rate(original[4], original[5])
            output_ft = rate(output[4], output[5])
            if original_ft is not None and output_ft is not None:
                ft_diffs.append(abs(output_ft - original_ft))

        checks["controlled_three_accuracy_stays_identity_close"] = bool(
            three_diffs and sum(three_diffs) / len(three_diffs) <= 0.085
        )
        checks["controlled_ft_accuracy_stays_identity_close"] = bool(
            ft_diffs and sum(ft_diffs) / len(ft_diffs) <= 0.095
        )

        # Explicitly ensure a zero-3PA player is not gratuitously turned into a
        # volume shooter by the environment layer.
        zero_profile_output = produced[2][2]
        checks["zero_three_volume_is_respected"] = zero_profile_output[3] <= 1

    finally:
        game._scoring_components_pre_realism_v1_0_3 = original_function

    failed = [name for name, passed in checks.items() if not passed]
    print("=" * 104)
    print("PLAYER SHOOTING IDENTITY PRESERVATION V1.0.3 VALIDATION")
    print("=" * 104)
    for name, passed in checks.items():
        print(f"  {name}: {'PASS' if passed else 'FAIL'}")
    if failed:
        raise AssertionError(
            "Player shooting identity validation failed: " + ", ".join(failed)
        )
    print()
    print("PLAYER SHOOTING IDENTITY PRESERVATION V1.0.3 VALIDATION PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
