from __future__ import annotations

import ast
import copy
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import simulation_season_transition_v1 as transition
from simulation_league_state_v1 import LeaguePhase, RotationState


def main() -> int:
    career_path = SRC / "simulation_career_awards_v2.py"
    transition_path = SRC / "simulation_season_transition_v1.py"
    career_source = career_path.read_text(encoding="utf-8")
    transition_source = transition_path.read_text(encoding="utf-8")

    checks: dict[str, bool] = {}
    try:
        ast.parse(career_source)
        ast.parse(transition_source)
        checks["patched_modules_compile"] = True
    except Exception:
        checks["patched_modules_compile"] = False

    checks["career_patch_present"] = (
        "CPU_ROOKIE_USAGE_REALISM_V1_CAREER_METADATA" in career_source
        and "_generated_draft_metadata_lookup_v1" in career_source
    )
    checks["career_cache_rejects_erased_generated_pedigree"] = (
        'or getattr(player, "draft_pick", None) is not None' in career_source
    )
    checks["rotation_patch_present"] = (
        "CPU_ROOKIE_USAGE_REALISM_V1_ROTATION_POLICY" in transition_source
        and "lottery_priority" in transition_source
    )
    checks["top_five_has_strong_bonus"] = "pedigree_bonus = 5.50" in transition_source
    checks["late_lottery_has_strong_bonus"] = "pedigree_bonus = 4.00" in transition_source
    checks["late_first_not_blindly_forced"] = "elif pick_number <= 30" in transition_source

    players = {}
    roster = []

    def add(pid: str, name: str, ovr: float, age: float, potential: float, *, pick=None, rookie=False):
        player = SimpleNamespace(
            player_id=pid,
            player_name=name,
            overall_rating=ovr,
            age=age,
            potential_rating=potential,
            development_history=[],
            years_of_service=0 if rookie else 5,
            generated_prospect=bool(rookie),
            rookie_season="2027-28" if rookie else "2022-23",
            draft_year=2027 if rookie else None,
            draft_pick=pick,
        )
        players[pid] = player
        roster.append(pid)

    for idx, ovr in enumerate((84, 83, 82, 81, 80, 79, 78, 77, 76, 75), start=1):
        add(f"V{idx}", f"Veteran {idx}", ovr, 27 + (idx % 4), ovr)

    add("R2", "Lottery Two", 70, 20, 91, pick=2, rookie=True)
    add("R11", "Lottery Eleven", 69, 20, 88, pick=11, rookie=True)
    add("R45", "Second Round", 68, 21, 90, pick=45, rookie=True)

    state = SimpleNamespace(
        settings=SimpleNamespace(
            season_label="2027-28",
            rotation_size=10,
            regulation_minutes=48,
        ),
        phase=LeaguePhase.PRESEASON,
        players=players,
        teams={
            "TST": SimpleNamespace(
                team_abbreviation="TST",
                roster_player_ids=tuple(roster),
                rotation=RotationState(
                    starter_ids=(),
                    rotation_player_ids=(),
                    minutes_targets={},
                ),
                active_player_ids=(),
                inactive_player_ids=(),
            )
        },
        franchise_draft_history_v1=[
            {
                "draft_year": 2027,
                "target_season": "2027-28",
                "draft_order": [
                    {"prospect_id": "R2", "overall_pick": 2, "round": 1, "owner_team": "TST"},
                    {"prospect_id": "R11", "overall_pick": 11, "round": 1, "owner_team": "TST"},
                    {"prospect_id": "R45", "overall_pick": 45, "round": 2, "owner_team": "TST"},
                ],
            }
        ],
    )

    baselines = (34.0, 32.5, 31.0, 29.5, 28.0, 24.0, 21.0, 18.0, 14.0, 8.0)
    original_minutes_targets = transition.minutes_targets
    transition.minutes_targets = lambda rotation_ids, starter_ids, regulation_minutes: {
        pid: baselines[idx] for idx, pid in enumerate(rotation_ids)
    }
    try:
        transition.refresh_team_rotations(state)
    finally:
        transition.minutes_targets = original_minutes_targets

    rotation = state.teams["TST"].rotation
    rotation_ids = tuple(rotation.rotation_player_ids)

    checks["top_five_lottery_in_rotation"] = "R2" in rotation_ids
    checks["late_lottery_in_rotation"] = "R11" in rotation_ids
    checks["second_round_not_blindly_forced"] = "R45" not in rotation_ids
    checks["lottery_gets_meaningful_role_rank"] = (
        rotation_ids.index("R2") <= 7
        and rotation_ids.index("R11") <= 9
    )
    checks["stars_remain_starters"] = set(rotation.starter_ids) == {"V1", "V2", "V3", "V4", "V5"}
    checks["rotation_is_ten_players"] = len(rotation_ids) == 10
    checks["minutes_still_sum_240"] = abs(sum(rotation.minutes_targets.values()) - 240.0) < 0.01

    erased = copy.deepcopy(state)
    erased.players["R2"].draft_pick = None
    erased.players["R11"].draft_pick = None
    erased.teams["TST"].rotation = RotationState(
        starter_ids=(),
        rotation_player_ids=(),
        minutes_targets={},
    )
    transition.minutes_targets = lambda rotation_ids, starter_ids, regulation_minutes: {
        pid: baselines[idx] for idx, pid in enumerate(rotation_ids)
    }
    try:
        transition.refresh_team_rotations(erased)
    finally:
        transition.minutes_targets = original_minutes_targets

    erased_rotation = erased.teams["TST"].rotation.rotation_player_ids
    checks["durable_archive_recovers_lottery_priority"] = (
        "R2" in erased_rotation and "R11" in erased_rotation
    )

    failed = [name for name, passed in checks.items() if not passed]
    print({"checks": checks, "failed_checks": failed, "passed": not failed})
    if failed:
        print("FRANCHISE CPU ROOKIE USAGE REALISM V1 VALIDATOR FAILED")
        return 1
    print("FRANCHISE CPU ROOKIE USAGE REALISM V1 VALIDATOR PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
