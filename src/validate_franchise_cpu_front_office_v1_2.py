from __future__ import annotations

import ast
import hashlib
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
PAGE = ROOT / "pages" / "5_Franchise_Mode.py"
CHECKPOINT = ROOT / "outputs" / "runtime" / "franchise_mode_checkpoint_v1.pkl.gz"
ENGINE = SRC / "franchise_cpu_front_office_v1.py"
UI = SRC / "franchise_cpu_front_office_ui_v1.py"

EXPECTED_PAGE_HASH = 'a1ed427214063bb6c33f2fd86723cfa0fefbcb46786ebf4f223694c7fb3744d6'
EXPECTED_ENGINE_HASH = '3f686630b49f0973ae90db418d7f247a99c46c62ca59be0895baefb1ef380182'
EXPECTED_UI_HASH = '5752f22f5ddd1a5d180221acded0e91129b00647b244771b2957491ad4c83522'

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from franchise_cpu_front_office_v1 import (  # noqa: E402
    BEHAVIOR_PROFILES,
    CPU_FRONT_OFFICE_MODEL_VERSION,
    CPU_FRONT_OFFICE_VERSION,
    TIMELINE_CHAMPIONSHIP_PUSH,
    TIMELINE_CONTENDER,
    TIMELINE_DEVELOP,
    TIMELINE_LABELS,
    TIMELINE_REBUILD,
    TIMELINE_RETOOL,
    _contract_plan,
    _free_agent_target_score,
    _market_stance,
    _player_role,
    _retention_score,
    behavior_profile,
    build_league_front_office_plan,
    front_office_state_fingerprint,
    league_plan_to_dict,
)
from franchise_cpu_front_office_ui_v1 import CPU_FRONT_OFFICE_UI_VERSION  # noqa: E402
from simulation_franchise_checkpoint_v1 import load_franchise_checkpoint  # noqa: E402


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def mock_player(
    *,
    age: float,
    overall: float,
    potential: float,
    salary: float = 10_000_000.0,
    years: int | None = 1,
    status: str = "under_contract",
    position: str = "SF",
):
    return SimpleNamespace(
        player_id="mock",
        player_name="Mock Player",
        age=age,
        overall_rating=overall,
        potential_rating=potential,
        future_outlook_rating=potential,
        position=position,
        career_status="active",
        contract=SimpleNamespace(
            salary=salary,
            years_remaining=years,
            status=status,
        ),
    )


def synthetic_behavior_test() -> dict[str, bool]:
    need_scores = {
        "Guard": 8.0,
        "Wing/Forward": 10.0,
        "Center": 7.0,
    }
    veteran = mock_player(
        age=32.0,
        overall=82.0,
        potential=82.0,
        salary=21_000_000.0,
        years=1,
    )
    young = mock_player(
        age=22.0,
        overall=76.0,
        potential=88.0,
        salary=6_000_000.0,
        years=2,
    )
    veteran_fa = mock_player(
        age=33.0,
        overall=81.0,
        potential=81.0,
        salary=9_000_000.0,
        years=0,
        status="ufa",
    )
    young_fa = mock_player(
        age=23.0,
        overall=76.0,
        potential=87.0,
        salary=7_000_000.0,
        years=0,
        status="rfa",
    )

    veteran_role = _player_role(veteran)
    young_role = _player_role(young)

    def retention(player, role, timeline):
        return _retention_score(
            player,
            role=role,
            timeline=timeline,
            biggest_need="Wing/Forward",
            need_scores=need_scores,
            financial_posture="Balanced flexibility",
        )

    veteran_push = retention(
        veteran,
        veteran_role,
        TIMELINE_CHAMPIONSHIP_PUSH,
    )
    veteran_rebuild = retention(
        veteran,
        veteran_role,
        TIMELINE_REBUILD,
    )
    young_push = retention(
        young,
        young_role,
        TIMELINE_CHAMPIONSHIP_PUSH,
    )
    young_develop = retention(
        young,
        young_role,
        TIMELINE_DEVELOP,
    )

    veteran_push_stance = _market_stance(
        veteran,
        role=veteran_role,
        retention_score=veteran_push,
        timeline=TIMELINE_CHAMPIONSHIP_PUSH,
        roster_count=15,
    )
    veteran_rebuild_stance = _market_stance(
        veteran,
        role=veteran_role,
        retention_score=veteran_rebuild,
        timeline=TIMELINE_REBUILD,
        roster_count=15,
    )
    young_develop_stance = _market_stance(
        young,
        role=young_role,
        retention_score=young_develop,
        timeline=TIMELINE_DEVELOP,
        roster_count=15,
    )

    veteran_fa_push, _ = _free_agent_target_score(
        veteran_fa,
        timeline=TIMELINE_CHAMPIONSHIP_PUSH,
        biggest_need="Wing/Forward",
        need_scores=need_scores,
        financial_posture="Balanced flexibility",
    )
    veteran_fa_rebuild, _ = _free_agent_target_score(
        veteran_fa,
        timeline=TIMELINE_REBUILD,
        biggest_need="Wing/Forward",
        need_scores=need_scores,
        financial_posture="Balanced flexibility",
    )
    young_fa_push, _ = _free_agent_target_score(
        young_fa,
        timeline=TIMELINE_CHAMPIONSHIP_PUSH,
        biggest_need="Wing/Forward",
        need_scores=need_scores,
        financial_posture="Balanced flexibility",
    )
    young_fa_rebuild, _ = _free_agent_target_score(
        young_fa,
        timeline=TIMELINE_REBUILD,
        biggest_need="Wing/Forward",
        need_scores=need_scores,
        financial_posture="Balanced flexibility",
    )

    behavior_vectors = {
        (
            profile.win_now_bias,
            profile.youth_bias,
            profile.future_asset_bias,
            profile.consolidation_bias,
            profile.salary_discipline,
            profile.veteran_liquidity,
        )
        for profile in BEHAVIOR_PROFILES.values()
    }

    return {
        "five_distinct_behavior_profiles": len(behavior_vectors) == 5,
        "push_values_veteran_more_than_rebuild": veteran_push > veteran_rebuild,
        "develop_values_young_player_more_than_push": young_develop > young_push,
        "push_keeps_useful_veteran_in_competitive_bucket": veteran_push_stance in {
            "Hold for playoff role",
            "Premium offers only",
            "Available in championship upgrade",
        },
        "rebuild_markets_useful_veteran_for_future": veteran_rebuild_stance in {
            "Shop for future assets",
            "Premium future assets only",
            "Shop / salary relief",
        },
        "develop_protects_young_upside": young_develop_stance == "Protect development asset",
        "push_prefers_veteran_fa_more_than_rebuild": veteran_fa_push > veteran_fa_rebuild,
        "rebuild_prefers_young_fa_more_than_veteran_fa": young_fa_rebuild > veteran_fa_rebuild,
        "rebuild_young_fa_fit_not_worse_than_push": young_fa_rebuild >= young_fa_push,
        "rebuild_veteran_contract_plan_is_not_extension_first": (
            _contract_plan(
                veteran,
                veteran_rebuild,
                veteran_role,
                TIMELINE_REBUILD,
            )
            in {
                "Explore trade before extension",
                "Explore premium market before extension",
                "Extension watch",
                "Evaluate before contract decision",
            }
        ),
    }


def main() -> int:
    checkpoint_before = sha256(CHECKPOINT) if CHECKPOINT.is_file() else ""
    page_text = PAGE.read_text(encoding="utf-8")
    engine_text = ENGINE.read_text(encoding="utf-8")
    ui_text = UI.read_text(encoding="utf-8")

    checks: dict[str, bool] = {
        "engine_version_is_v1_2": (
            CPU_FRONT_OFFICE_VERSION
            == "franchise-cpu-front-office-v1.2-2026-08-13"
        ),
        "model_version_is_v1_2": (
            CPU_FRONT_OFFICE_MODEL_VERSION
            == "direction-driven-behavior-roster-contract-market-v1.2-2026-08-13"
        ),
        "ui_version_is_v1_2": (
            CPU_FRONT_OFFICE_UI_VERSION
            == "franchise-cpu-front-office-ui-v1.2-2026-08-13"
        ),
        "exact_engine_hash": sha256(ENGINE) == EXPECTED_ENGINE_HASH,
        "exact_ui_hash": sha256(UI) == EXPECTED_UI_HASH,
        "repaired_franchise_page_preserved": sha256(PAGE) == EXPECTED_PAGE_HASH,
        "page_compiles": True,
        "engine_compiles": True,
        "ui_compiles": True,
        "behavior_matrix_installed": "BEHAVIOR_PROFILES" in engine_text,
        "asset_policy_installed": "asset_policy" in engine_text,
        "decision_priority_installed": "decision_priority" in engine_text,
        "behavior_biases_exposed_in_ui": (
            "Future assets" in ui_text
            and "Consolidation" in ui_text
            and "Salary discipline" in ui_text
        ),
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

    checks.update(synthetic_behavior_test())

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

    directions = league.timeline_counts
    push = directions.get(TIMELINE_CHAMPIONSHIP_PUSH, 0)
    contend = directions.get(TIMELINE_CONTENDER, 0)
    retool = directions.get(TIMELINE_RETOOL, 0)
    develop = directions.get(TIMELINE_DEVELOP, 0)
    rebuild = directions.get(TIMELINE_REBUILD, 0)

    valid_policies = {
        "Protect",
        "Retain",
        "Develop",
        "Consolidate",
        "Market",
        "Exit",
    }
    controlled_set = {
        str(value).strip().upper()
        for value in controlled
    }

    live_rebuild_veterans = [
        row
        for plan in league.teams.values()
        if plan.timeline == TIMELINE_REBUILD
        for row in plan.player_decisions
        if row.age >= 30.0
        and row.overall >= 76.0
        and row.role != "Cornerstone"
    ]
    live_develop_youth = [
        row
        for plan in league.teams.values()
        if plan.timeline == TIMELINE_DEVELOP
        for row in plan.player_decisions
        if row.age <= 24.5
        and row.potential >= max(80.0, row.overall + 4.0)
    ]
    live_push_core = [
        row
        for plan in league.teams.values()
        if plan.timeline == TIMELINE_CHAMPIONSHIP_PUSH
        for row in plan.player_decisions
        if row.role in {"Cornerstone", "Core"}
    ]

    checks.update({
        "classification_distribution_preserved": (
            2 <= push <= 6
            and 8 <= push + contend <= 14
            and retool >= 6
            and develop + rebuild >= 6
            and rebuild >= 2
        ),
        "planning_is_read_only": before == after == league.state_fingerprint,
        "planning_is_deterministic": (
            league_plan_to_dict(league)
            == league_plan_to_dict(second)
        ),
        "all_teams_have_matching_behavior_profile": all(
            plan.behavior_label
            == behavior_profile(plan.timeline).label
            for plan in league.teams.values()
        ),
        "all_player_asset_policies_valid": all(
            row.asset_policy in valid_policies
            for plan in league.teams.values()
            for row in plan.player_decisions
        ),
        "all_decision_priorities_bounded": all(
            0.0 <= row.decision_priority <= 100.0
            for plan in league.teams.values()
            for row in plan.player_decisions
        ),
        "protected_and_market_lists_do_not_overlap": all(
            not set(plan.protected_player_ids).intersection(
                plan.shop_player_ids
            )
            for plan in league.teams.values()
        ),
        "push_core_is_protected": all(
            row.asset_policy == "Protect"
            for row in live_push_core
        ),
        "develop_youth_is_not_marketed_or_cut": all(
            row.asset_policy in {"Protect", "Develop", "Retain"}
            for row in live_develop_youth
        ),
        "rebuild_noncore_veterans_are_liquid": all(
            row.asset_policy in {"Market", "Exit"}
            for row in live_rebuild_veterans
        ),
        "controlled_teams_are_not_cpu_managed": all(
            plan.cpu_managed == (team not in controlled_set)
            for team, plan in league.teams.items()
        ),
        "checkpoint_hash_still_unchanged": (
            not checkpoint_before
            or sha256(CHECKPOINT) == checkpoint_before
        ),
    })

    print("=" * 100)
    print("CPU FRONT OFFICE DIRECTION-DRIVEN BEHAVIOR V1.2 VALIDATION")
    print("=" * 100)
    for name, passed in checks.items():
        print(f"  {name}: {'PASS' if passed else 'FAIL'}")

    print()
    print("LIVE DIRECTION BEHAVIOR AUDIT")
    print(f"  Season: {league.season_label}")
    print("  Directions:")
    for key, label in TIMELINE_LABELS.items():
        print(f"    {label}: {league.timeline_counts.get(key, 0)}")

    print()
    print(
        "  DIR                 TEAMS  PROTECT  DEVELOP  CONSOLIDATE  MARKET  EXIT  AVG PRIORITY"
    )
    print("  " + "-" * 84)
    for timeline, label in TIMELINE_LABELS.items():
        plans = [
            plan
            for plan in league.teams.values()
            if plan.timeline == timeline
        ]
        rows = [
            row
            for plan in plans
            for row in plan.player_decisions
        ]
        def count(policy):
            return sum(row.asset_policy == policy for row in rows)
        avg_priority = (
            sum(row.decision_priority for row in rows) / len(rows)
            if rows
            else 0.0
        )
        print(
            f"  {label:<19} "
            f"{len(plans):>5}  "
            f"{count('Protect'):>7}  "
            f"{count('Develop'):>7}  "
            f"{count('Consolidate'):>11}  "
            f"{count('Market'):>6}  "
            f"{count('Exit'):>4}  "
            f"{avg_priority:>12.1f}"
        )

    print()
    print("  SAMPLE TEAM BEHAVIOR")
    for plan in sorted(
        league.teams.values(),
        key=lambda item: item.league_rank,
    ):
        protect = sum(
            row.asset_policy == "Protect"
            for row in plan.player_decisions
        )
        develop_count = sum(
            row.asset_policy == "Develop"
            for row in plan.player_decisions
        )
        consolidate = sum(
            row.asset_policy == "Consolidate"
            for row in plan.player_decisions
        )
        market = sum(
            row.asset_policy == "Market"
            for row in plan.player_decisions
        )
        print(
            f"  #{plan.league_rank:>2} {plan.team} · "
            f"{plan.timeline_label:<17} · {plan.behavior_label:<20} · "
            f"P={protect} D={develop_count} C={consolidate} M={market} · "
            f"FA={plan.free_agent_targets[0].player_name if plan.free_agent_targets else 'none'}"
        )

    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        print()
        print("FAILED: " + ", ".join(failed))
        return 1

    print()
    print("CPU FRONT OFFICE DIRECTION-DRIVEN BEHAVIOR V1.2 VALIDATION PASSED")
    print(
        "READ-ONLY VALIDATION: no roster, contract, trade, free-agent, "
        "draft or checkpoint mutation was performed."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
