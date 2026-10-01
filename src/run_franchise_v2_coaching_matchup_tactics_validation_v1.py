from __future__ import annotations

import hashlib
from pathlib import Path

from franchise_coaching_matchup_tactics_v1 import (
    MAX_DEFENSIVE_SUPPRESSION_POINTS,
    apply_matchup_tactical_counters_v1,
    opponent_threat_profile_v1,
)
from simulation_franchise_checkpoint_v1 import (
    DEFAULT_CHECKPOINT_PATH,
    load_franchise_checkpoint,
)
from single_game_simulator_v1 import (
    GameSimulationConfig,
    build_team_game_plan,
    regulation_score_expectations,
)


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def main() -> int:
    active = Path(DEFAULT_CHECKPOINT_PATH)
    before_hash = sha(active) if active.is_file() else ""

    checkpoint = load_franchise_checkpoint(allow_backup=False)
    if checkpoint is None:
        raise RuntimeError("Active franchise checkpoint is unavailable.")

    state = checkpoint.simulation_state
    config = GameSimulationConfig()

    candidate_rows = []

    # Use current scheduled matchups only. This validates the actual franchise
    # universe without committing or advancing a single game.
    for game_id, scheduled in sorted(state.schedule.items()):
        status = str(getattr(getattr(scheduled, "status", ""), "value", getattr(scheduled, "status", ""))).lower()
        if status == "completed":
            continue

        try:
            home = build_team_game_plan(
                state,
                scheduled.home_team,
                sit_player_ids=set(),
                overtime_periods=0,
                config=config,
            )
            away = build_team_game_plan(
                state,
                scheduled.away_team,
                sit_player_ids=set(),
                overtime_periods=0,
                config=config,
            )
        except Exception:
            continue

        adjusted_home, adjusted_away, report = apply_matchup_tactical_counters_v1(
            state,
            home,
            away,
            offense_rating_weight=config.offense_rating_weight,
            opponent_rating_weight=config.opponent_rating_weight,
        )
        total_suppression = (
            report.home_defense.suppression_points
            + report.away_defense.suppression_points
        )
        candidate_rows.append(
            (
                -total_suppression,
                game_id,
                home,
                away,
                adjusted_home,
                adjusted_away,
                report,
            )
        )

    if not candidate_rows:
        raise RuntimeError("No scheduled matchup was available for protected tactical validation.")

    candidate_rows.sort(key=lambda row: (row[0], row[1]))
    _, game_id, home, away, adjusted_home, adjusted_away, report = candidate_rows[0]

    pace = config.base_pace
    base_home, base_away = regulation_score_expectations(
        home,
        away,
        pace=pace,
        config=config,
    )
    tactical_home, tactical_away = regulation_score_expectations(
        adjusted_home,
        adjusted_away,
        pace=pace,
        config=config,
    )

    home_expected_suppression = report.away_defense.suppression_points
    away_expected_suppression = report.home_defense.suppression_points

    home_profile = opponent_threat_profile_v1(state, home)
    away_profile = opponent_threat_profile_v1(state, away)

    checks = {
        "home_defensive_suppression_is_bounded":
            0.0 <= report.home_defense.suppression_points <= MAX_DEFENSIVE_SUPPRESSION_POINTS,
        "away_defensive_suppression_is_bounded":
            0.0 <= report.away_defense.suppression_points <= MAX_DEFENSIVE_SUPPRESSION_POINTS,
        "home_expected_score_shift_matches_away_counter":
            abs((base_home - tactical_home) - home_expected_suppression) <= 0.02,
        "away_expected_score_shift_matches_home_counter":
            abs((base_away - tactical_away) - away_expected_suppression) <= 0.02,
        "at_least_one_team_has_a_real_counter":
            report.home_defense.scheme != "balanced"
            or report.away_defense.scheme != "balanced",
        "home_threat_profile_is_finite":
            all(
                0.0 <= value <= 100.0
                for value in (
                    home_profile.creation,
                    home_profile.multi_handler_creation,
                    home_profile.spacing,
                    home_profile.rim_pressure,
                    home_profile.glass_size,
                    home_profile.interior_hub,
                )
            ),
        "away_threat_profile_is_finite":
            all(
                0.0 <= value <= 100.0
                for value in (
                    away_profile.creation,
                    away_profile.multi_handler_creation,
                    away_profile.spacing,
                    away_profile.rim_pressure,
                    away_profile.glass_size,
                    away_profile.interior_hub,
                )
            ),
        "tactical_explanations_are_present":
            bool(report.home_defense.explanation)
            and bool(report.away_defense.explanation),
        "source_plans_are_not_mutated":
            home is not adjusted_home
            and away is not adjusted_away,
    }

    active_after = sha(active) if active.is_file() else ""
    checks["active_checkpoint_unchanged"] = before_hash == active_after

    print("FRANCHISE V2 COACHING MATCHUP TACTICS V1 RUNTIME VALIDATION")
    print(f"Game: {game_id} | {away.team_abbreviation} at {home.team_abbreviation}")
    print(
        f"{home.team_abbreviation} threat: creation={home_profile.creation:.1f}, "
        f"spacing={home_profile.spacing:.1f}, rim={home_profile.rim_pressure:.1f}, "
        f"glass={home_profile.glass_size:.1f}, hub={home_profile.interior_hub:.1f}"
    )
    print(
        f"{away.team_abbreviation} threat: creation={away_profile.creation:.1f}, "
        f"spacing={away_profile.spacing:.1f}, rim={away_profile.rim_pressure:.1f}, "
        f"glass={away_profile.glass_size:.1f}, hub={away_profile.interior_hub:.1f}"
    )
    print(
        f"{home.team_abbreviation} defensive counter: "
        f"{report.home_defense.scheme_label} | "
        f"suppression={report.home_defense.suppression_points:.2f}"
    )
    print(f"  {report.home_defense.explanation}")
    print(
        f"{away.team_abbreviation} defensive counter: "
        f"{report.away_defense.scheme_label} | "
        f"suppression={report.away_defense.suppression_points:.2f}"
    )
    print(f"  {report.away_defense.explanation}")
    print(
        f"Expected score shift: "
        f"{home.team_abbreviation} {base_home:.2f}->{tactical_home:.2f}, "
        f"{away.team_abbreviation} {base_away:.2f}->{tactical_away:.2f}"
    )

    for name, passed in checks.items():
        print(f"  {name}: {'PASS' if passed else 'FAIL'}")

    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        print("RUNTIME VALIDATION FAILED")
        for name in failed:
            print(f"  - {name}")
        return 1

    print("RUNTIME VALIDATION PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
