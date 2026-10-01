from __future__ import annotations

import copy
import hashlib
from pathlib import Path

from franchise_coaching_matchup_tactics_v1 import (
    coach_tendency_profile_v1,
    choose_defensive_tactical_counter_v1,
)
from franchise_staff_system_v1 import (
    ROLE_ASSISTANT_COACH,
    ROLE_HEAD_COACH,
    ensure_franchise_staff_state,
    team_staff,
)
from simulation_franchise_checkpoint_v1 import (
    DEFAULT_CHECKPOINT_PATH,
    load_franchise_checkpoint,
)
from single_game_simulator_v1 import GameSimulationConfig, build_team_game_plan


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def main() -> int:
    active = Path(DEFAULT_CHECKPOINT_PATH)
    before_hash = sha(active) if active.is_file() else ""
    checkpoint = load_franchise_checkpoint(allow_backup=False)
    if checkpoint is None:
        raise RuntimeError("Active franchise checkpoint unavailable.")

    source = checkpoint.simulation_state
    config = GameSimulationConfig()
    chosen = None

    for game_id, game in sorted(source.schedule.items()):
        status = str(
            getattr(
                getattr(game, "status", ""),
                "value",
                getattr(game, "status", ""),
            )
        ).lower()
        if status == "completed":
            continue
        try:
            home = build_team_game_plan(
                source, game.home_team, sit_player_ids=set(),
                overtime_periods=0, config=config,
            )
            away = build_team_game_plan(
                source, game.away_team, sit_player_ids=set(),
                overtime_periods=0, config=config,
            )
        except Exception:
            continue
        decision = choose_defensive_tactical_counter_v1(source, home, away)
        if decision.scheme != "balanced":
            chosen = (game_id, game, home, away)
            break

    if chosen is None:
        raise RuntimeError("No remaining matchup with a real tactical counter.")

    game_id, game, home, away = chosen
    protected = copy.deepcopy(source)
    ensure_franchise_staff_state(protected)
    staff = team_staff(protected, game.home_team, ensure=True)
    head = staff.members[ROLE_HEAD_COACH]
    assistant = staff.members[ROLE_ASSISTANT_COACH]

    ratings_before = (
        head.offense_rating,
        head.defense_rating,
        head.rotation_management_rating,
        head.adaptability_rating,
        assistant.offense_rating,
        assistant.defense_rating,
        assistant.rotation_management_rating,
        assistant.adaptability_rating,
    )

    original_profile = coach_tendency_profile_v1(protected, game.home_team)
    original_decision = choose_defensive_tactical_counter_v1(
        protected, home, away
    )

    head.traits = ("Half-court detail", "Discipline")
    assistant.traits = ("Opponent prep", "Analytics")

    altered_profile = coach_tendency_profile_v1(protected, game.home_team)
    altered_decision = choose_defensive_tactical_counter_v1(
        protected, home, away
    )

    ratings_after = (
        head.offense_rating,
        head.defense_rating,
        head.rotation_management_rating,
        head.adaptability_rating,
        assistant.offense_rating,
        assistant.defense_rating,
        assistant.rotation_management_rating,
        assistant.adaptability_rating,
    )

    checks = {
        "coach_identity_present": bool(original_profile.head_coach_name),
        "original_traits_present": bool(original_profile.head_traits),
        "protected_trait_edit_changes_preferences":
            original_profile.scheme_biases != altered_profile.scheme_biases,
        "biases_remain_bounded":
            all(abs(value) <= 0.085 for _, value in altered_profile.scheme_biases),
        "decision_stays_valid":
            bool(altered_decision.scheme)
            and 0.0 <= altered_decision.suppression_points <= 0.65,
        "staff_ratings_are_unchanged": ratings_before == ratings_after,
        "source_staff_is_unchanged":
            coach_tendency_profile_v1(source, game.home_team) == original_profile,
    }

    active_after = sha(active) if active.is_file() else ""
    checks["active_checkpoint_unchanged"] = before_hash == active_after

    print("FRANCHISE V2 COACHING IDENTITY / GAME DAY V1 RUNTIME VALIDATION")
    print(f"Game: {game_id} | {game.away_team} at {game.home_team}")
    print(f"Coach: {original_profile.head_coach_name}")
    print(f"Original traits: {', '.join(original_profile.head_traits)}")
    print(f"Original decision: {original_decision.scheme_label}")
    print(
        "Protected alternate traits: "
        f"{', '.join(altered_profile.head_traits)} / "
        f"{', '.join(altered_profile.assistant_traits)}"
    )
    print(f"Altered decision: {altered_decision.scheme_label}")
    print(
        "Largest altered biases: "
        + ", ".join(
            f"{scheme}={bias:+.03f}"
            for scheme, bias in altered_profile.scheme_biases[:3]
        )
    )

    for name, passed in checks.items():
        print(f"  {name}: {'PASS' if passed else 'FAIL'}")

    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        print("RUNTIME VALIDATION FAILED")
        for name in failed:
            print("  - " + name)
        return 1

    print("RUNTIME VALIDATION PASSED")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
