from __future__ import annotations

import ast
import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
PAGE = ROOT / "pages" / "5_Franchise_Mode.py"
CHECKPOINT = ROOT / "outputs" / "runtime" / "franchise_mode_checkpoint_v1.pkl.gz"
ENGINE = SRC / "franchise_cpu_front_office_v1.py"
UI = SRC / "franchise_cpu_front_office_ui_v1.py"

EXPECTED_PAGE_HASH = 'a1ed427214063bb6c33f2fd86723cfa0fefbcb46786ebf4f223694c7fb3744d6'
EXPECTED_ENGINE_HASH = '81b7aa93f6111895a794727e64c759a55fc03c9bc967efc11e1e93e0ab292cba'
EXPECTED_UI_HASH = '8f31a25cd4434095955566adc7db99f006149b7a56df48bca4579b1ad89d1b5a'

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from franchise_cpu_front_office_v1 import (  # noqa: E402
    CPU_FRONT_OFFICE_MODEL_VERSION,
    CPU_FRONT_OFFICE_VERSION,
    TIMELINE_CHAMPIONSHIP_PUSH,
    TIMELINE_CONTENDER,
    TIMELINE_DEVELOP,
    TIMELINE_LABELS,
    TIMELINE_REBUILD,
    TIMELINE_RETOOL,
    _league_relative_classifications,
    build_league_front_office_plan,
    front_office_state_fingerprint,
    league_plan_to_dict,
)
from franchise_cpu_front_office_ui_v1 import CPU_FRONT_OFFICE_UI_VERSION  # noqa: E402
from simulation_franchise_checkpoint_v1 import load_franchise_checkpoint  # noqa: E402


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def synthetic_classification_test() -> dict[str, bool]:
    # 30-team monotonic synthetic league with a mix of young and older weak
    # teams. This catches accidental threshold regressions before touching the
    # user's live franchise.
    metrics = {}
    for index in range(30):
        strength = 29 - index
        metrics[f"T{index:02d}"] = {
            "best_overall": 94.0 - index * 0.42,
            "top_three": 89.5 - index * 0.36,
            "top_five": 86.0 - index * 0.34,
            "rotation": 81.5 - index * 0.28,
            "average_age": 28.8 if index < 20 else (25.2 if index % 2 == 0 else 28.0),
            "young_core_score": 18.0 if index < 20 else (72.0 if index % 2 == 0 else 20.0),
            "win_pct": 0.68 - index * 0.012,
            "games_played": 0,
            "point_diff_per_game": 0.0,
            "strength_score": float(strength),
            "known_payroll": 150_000_000.0,
            "salary_coverage": 1.0,
        }
    result = _league_relative_classifications(metrics)
    counts = {key: 0 for key in TIMELINE_LABELS}
    for row in result.values():
        counts[row["timeline"]] += 1
    ranked = sorted(result.items(), key=lambda item: item[1]["league_rank"])
    return {
        "synthetic_all_30_classified": len(result) == 30,
        "synthetic_unique_ranks": sorted(row["league_rank"] for row in result.values()) == list(range(1, 31)),
        "synthetic_title_push_is_selective": 2 <= counts[TIMELINE_CHAMPIONSHIP_PUSH] <= 6,
        "synthetic_upper_tier_is_bounded": 8 <= (
            counts[TIMELINE_CHAMPIONSHIP_PUSH] + counts[TIMELINE_CONTENDER]
        ) <= 14,
        "synthetic_bottom_has_long_term_teams": (
            counts[TIMELINE_DEVELOP] + counts[TIMELINE_REBUILD]
        ) >= 6,
        "synthetic_has_rebuilders": counts[TIMELINE_REBUILD] >= 2,
        "synthetic_best_team_not_rebuild": ranked[0][1]["timeline"] not in {
            TIMELINE_DEVELOP,
            TIMELINE_REBUILD,
        },
        "synthetic_bottom_two_are_long_term_builds": all(
            row["timeline"] in {TIMELINE_DEVELOP, TIMELINE_REBUILD}
            for _, row in ranked[-2:]
        ),
        "synthetic_strong_young_bottom_team_can_develop": any(
            row["timeline"] == TIMELINE_DEVELOP
            for _, row in ranked[-2:]
        ),
    }


def main() -> int:
    checkpoint_before = sha256(CHECKPOINT) if CHECKPOINT.is_file() else ""
    page_text = PAGE.read_text(encoding="utf-8")
    engine_text = ENGINE.read_text(encoding="utf-8")
    ui_text = UI.read_text(encoding="utf-8")

    checks: dict[str, bool] = {
        "engine_version_is_v1_1_1": (
            CPU_FRONT_OFFICE_VERSION
            == "franchise-cpu-front-office-v1.1.1-2026-08-13"
        ),
        "model_version_is_v1_1_1": (
            CPU_FRONT_OFFICE_MODEL_VERSION
            == "league-relative-direction-roster-contract-market-v1.1.1-2026-08-13"
        ),
        "ui_version_is_v1_1_1": (
            CPU_FRONT_OFFICE_UI_VERSION
            == "franchise-cpu-front-office-ui-v1.1.1-2026-08-13"
        ),
        "exact_engine_hash": sha256(ENGINE) == EXPECTED_ENGINE_HASH,
        "exact_ui_hash": sha256(UI) == EXPECTED_UI_HASH,
        "repaired_franchise_page_preserved": sha256(PAGE) == EXPECTED_PAGE_HASH,
        "page_compiles": True,
        "engine_compiles": True,
        "ui_compiles": True,
        "league_relative_model_installed": "_league_relative_classifications" in engine_text,
        "competitive_rank_exposed_in_ui": "League rank" in ui_text,
        "direction_rationale_exposed_in_ui": "Why this direction?" in ui_text,
        "durable_checkpoint_exists": CHECKPOINT.is_file(),
    }

    for key, text, path in (
        ("page_compiles", page_text, PAGE),
        ("engine_compiles", engine_text, ENGINE),
        ("ui_compiles", ui_text, UI),
    ):
        try:
            ast.parse(text)
            compile(text, str(path), "exec")
        except Exception:
            checks[key] = False

    checks.update(synthetic_classification_test())

    checkpoint = load_franchise_checkpoint()
    checks["checkpoint_loads"] = checkpoint is not None
    if checkpoint is None:
        for name, passed in checks.items():
            print(f"  {name}: {'PASS' if passed else 'FAIL'}")
        return 1

    state = checkpoint.simulation_state
    controlled_raw = (
        checkpoint.preferences.get("franchise_pref_controlled_teams", ())
        if isinstance(checkpoint.preferences, dict)
        else ()
    )
    if isinstance(controlled_raw, str):
        controlled = (controlled_raw,)
    else:
        try:
            controlled = tuple(controlled_raw)
        except TypeError:
            controlled = ()

    before = front_office_state_fingerprint(state)
    league = build_league_front_office_plan(
        state,
        controlled_teams=controlled,
    )
    after = front_office_state_fingerprint(state)
    second = build_league_front_office_plan(
        state,
        controlled_teams=controlled,
    )

    team_count = len(getattr(state, "teams", {}))
    ranks = sorted(plan.league_rank for plan in league.teams.values())
    directions = league.timeline_counts
    push = directions.get(TIMELINE_CHAMPIONSHIP_PUSH, 0)
    contend = directions.get(TIMELINE_CONTENDER, 0)
    retool = directions.get(TIMELINE_RETOOL, 0)
    develop = directions.get(TIMELINE_DEVELOP, 0)
    rebuild = directions.get(TIMELINE_REBUILD, 0)

    sorted_plans = sorted(
        league.teams.values(),
        key=lambda plan: plan.league_rank,
    )

    checks.update({
        "all_30_teams_receive_plan": len(league.teams) == team_count and team_count >= 30,
        "league_ranks_are_unique_and_complete": ranks == list(range(1, team_count + 1)),
        "planning_is_read_only": before == after == league.state_fingerprint,
        "planning_is_deterministic": league_plan_to_dict(league) == league_plan_to_dict(second),
        "championship_push_count_is_selective": 2 <= push <= 6,
        "push_plus_contend_is_realistic_band": 8 <= (push + contend) <= 14,
        "middle_class_exists": retool >= 6,
        "develop_or_rebuild_population_exists": (develop + rebuild) >= 6,
        "at_least_two_rebuilders_exist": rebuild >= 2,
        "title_pushes_are_top_six_only": all(
            plan.league_rank <= 6
            for plan in league.teams.values()
            if plan.timeline == TIMELINE_CHAMPIONSHIP_PUSH
        ),
        "bottom_two_are_long_term_builds": all(
            plan.timeline in {TIMELINE_DEVELOP, TIMELINE_REBUILD}
            for plan in sorted_plans[-2:]
        ),
        "elite_young_cores_are_not_forced_rebuilds": all(
            not (
                plan.timeline == TIMELINE_REBUILD
                and plan.young_core_score >= 80.0
                and plan.average_age <= 26.5
            )
            for plan in league.teams.values()
        ),
        "top_three_are_not_long_term_teardowns": all(
            plan.timeline not in {TIMELINE_DEVELOP, TIMELINE_REBUILD}
            for plan in sorted_plans[:3]
        ),
        "direction_rationale_present": all(
            len(plan.direction_rationale) >= 3
            for plan in league.teams.values()
        ),
        "controlled_teams_are_not_cpu_managed": all(
            plan.cpu_managed
            == (
                team
                not in {
                    str(value).strip().upper()
                    for value in controlled
                }
            )
            for team, plan in league.teams.items()
        ),
        "all_rostered_players_receive_decision": all(
            len(plan.player_decisions) == plan.roster_count
            for plan in league.teams.values()
        ),
        "protected_players_are_never_cut_candidates": all(
            not set(plan.protected_player_ids).intersection(
                plan.cut_candidate_ids
            )
            for plan in league.teams.values()
        ),
        "checkpoint_hash_still_unchanged": (
            not checkpoint_before
            or sha256(CHECKPOINT) == checkpoint_before
        ),
    })

    print("=" * 96)
    print("CPU FRONT OFFICE CLASSIFICATION V1.1.2 VALIDATION")
    print("=" * 96)
    for name, passed in checks.items():
        print(f"  {name}: {'PASS' if passed else 'FAIL'}")

    print()
    print("LIVE LEAGUE CLASSIFICATION")
    print(f"  Season: {league.season_label}")
    print(f"  Teams: {len(league.teams)}")
    print("  Directions:")
    for key, label in TIMELINE_LABELS.items():
        print(f"    {label}: {league.timeline_counts.get(key, 0)}")

    print()
    print("  RANK  TEAM  DIRECTION           SCORE   TOP5   ROT    AGE   YOUNG")
    print("  " + "-" * 73)
    for plan in sorted_plans:
        print(
            f"  {plan.league_rank:>4}  "
            f"{plan.team:<4}  "
            f"{plan.timeline_label:<18} "
            f"{plan.competitive_score:>6.1f}  "
            f"{plan.top_five_overall:>5.1f}  "
            f"{plan.rotation_quality:>5.1f}  "
            f"{plan.average_age:>5.1f}  "
            f"{plan.young_core_score:>6.1f}"
        )

    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        print()
        print("FAILED: " + ", ".join(failed))
        return 1

    print()
    print("CPU FRONT OFFICE CLASSIFICATION V1.1.2 VALIDATION PASSED")
    print(
        "READ-ONLY VALIDATION: no roster, contract, trade, free-agent, "
        "draft or checkpoint mutation was performed."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
