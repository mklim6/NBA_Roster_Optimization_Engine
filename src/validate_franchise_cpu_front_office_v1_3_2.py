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
EXPECTED_ENGINE_HASH = '3434d35a575fee7016777f5195d4265a18cceda5ead84f479296785cd3feaf5c'
EXPECTED_UI_HASH = '27172e6dbe02ab23b87817ca5c7b2c79059b991837761ea75f52da3d7b555a21'

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
    _free_agent_targets,
    _market_stance,
    build_league_front_office_plan,
    front_office_state_fingerprint,
    league_plan_to_dict,
    team_roster_construction,
)
from franchise_cpu_front_office_ui_v1 import CPU_FRONT_OFFICE_UI_VERSION  # noqa: E402
from simulation_franchise_checkpoint_v1 import load_franchise_checkpoint  # noqa: E402


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def mock_player(
    pid: str,
    position: str,
    overall: float,
    potential: float,
    age: float,
    *,
    salary: float = 8_000_000.0,
):
    return SimpleNamespace(
        player_id=pid,
        player_name=pid,
        position=position,
        overall_rating=overall,
        potential_rating=potential,
        future_outlook_rating=potential,
        age=age,
        career_status="active",
        contract=SimpleNamespace(
            salary=salary,
            years_remaining=2,
            status="under_contract",
        ),
    )


def synthetic_roster_state():
    # Deliberately guard-heavy team with weak center depth.
    roster = [
        mock_player("G1", "PG", 86, 87, 27),
        mock_player("G2", "SG", 82, 83, 26),
        mock_player("G3", "PG", 79, 80, 25),
        mock_player("G4", "SG", 77, 79, 24),
        mock_player("G5", "PG", 75, 77, 29),
        mock_player("W1", "SF", 84, 85, 27),
        mock_player("W2", "PF", 80, 82, 25),
        mock_player("W3", "SF", 77, 80, 23),
        mock_player("W4", "PF", 75, 77, 29),
        mock_player("C1", "C", 74, 76, 28),
    ]
    players = {p.player_id: p for p in roster}
    team_state = SimpleNamespace(
        roster_player_ids=tuple(players),
    )
    return SimpleNamespace(
        players=players,
        teams={"AAA": team_state},
    ), roster


def synthetic_fa_state():
    roster_state, roster = synthetic_roster_state()
    free_agents = [
        mock_player("FA_G", "PG", 82, 84, 26),
        mock_player("FA_W", "SF", 82, 84, 26),
        mock_player("FA_C", "C", 82, 84, 26),
        mock_player("FA_CY", "C", 76, 88, 22),
        mock_player("FA_GY", "PG", 76, 88, 22),
    ]
    players = dict(roster_state.players)
    players.update({p.player_id: p for p in free_agents})
    return SimpleNamespace(
        players=players,
        teams=roster_state.teams,
        free_agent_player_ids=tuple(
            p.player_id
            for p in free_agents
        ),
    )


def synthetic_checks() -> dict[str, bool]:
    state, roster = synthetic_roster_state()
    construction = team_roster_construction(
        state,
        "AAA",
    )
    needs = construction["need_scores"]
    surplus = construction["surplus_scores"]

    contender_guard = _market_stance(
        roster[2],
        role="Starter",
        retention_score=62.0,
        timeline=TIMELINE_CONTENDER,
        roster_count=len(roster),
        family_need=needs["Guard"],
        family_surplus=surplus["Guard"],
        depth_rank=3,
        is_biggest_need=False,
        need_protection=False,
    )
    center_hold = _market_stance(
        roster[-1],
        role="Rotation",
        retention_score=50.0,
        timeline=TIMELINE_CONTENDER,
        roster_count=len(roster),
        family_need=needs["Center"],
        family_surplus=surplus["Center"],
        depth_rank=1,
        is_biggest_need=True,
        need_protection=True,
    )

    fa_state = synthetic_fa_state()
    targets = _free_agent_targets(
        fa_state,
        timeline=TIMELINE_CONTENDER,
        biggest_need="Center",
        secondary_need="Wing/Forward",
        need_scores={
            "Guard": 2.0,
            "Wing/Forward": 10.0,
            "Center": 22.0,
        },
        surplus_scores={
            "Guard": 10.0,
            "Wing/Forward": 1.0,
            "Center": 0.0,
        },
        financial_posture="Balanced flexibility",
        limit=5,
    )

    return {
        "synthetic_center_is_primary_need": (
            construction["biggest_need"] == "Center"
        ),
        "synthetic_guard_is_surplus": (
            construction["surplus_family"] == "Guard"
        ),
        "synthetic_need_and_surplus_are_distinct": (
            construction["biggest_need"]
            != construction["surplus_family"]
        ),
        "synthetic_contender_surplus_guard_is_consolidation_candidate": (
            contender_guard
            in {
                "Available in targeted upgrade",
                "Hold for playoff role",
            }
        ),
        "synthetic_needed_center_is_not_shopped": (
            center_hold
            not in {
                "Shop / salary relief",
                "Available in targeted upgrade",
            }
        ),
        "synthetic_fa_board_leads_with_primary_need": (
            bool(targets)
            and targets[0].position_family == "Center"
            and targets[0].target_lane == "Primary need"
        ),
        "synthetic_fa_board_contains_secondary_need_lane": any(
            row.position_family == "Wing/Forward"
            and row.target_lane == "Secondary need"
            for row in targets
        ),
        "synthetic_fa_board_is_family_diversified": (
            len({row.position_family for row in targets}) >= 2
        ),
    }


def main() -> int:
    checkpoint_before = sha256(CHECKPOINT) if CHECKPOINT.is_file() else ""
    page_text = PAGE.read_text(encoding="utf-8")
    engine_text = ENGINE.read_text(encoding="utf-8")
    ui_text = UI.read_text(encoding="utf-8")

    checks = {
        "engine_version_is_v1_3_1": (
            CPU_FRONT_OFFICE_VERSION
            == "franchise-cpu-front-office-v1.3.1-2026-08-13"
        ),
        "model_version_is_v1_3_1": (
            CPU_FRONT_OFFICE_MODEL_VERSION
            == "roster-construction-target-diversification-v1.3.1-2026-08-13"
        ),
        "ui_version_is_v1_3_1": (
            CPU_FRONT_OFFICE_UI_VERSION
            == "franchise-cpu-front-office-ui-v1.3.1-2026-08-13"
        ),
        "exact_engine_hash": sha256(ENGINE) == EXPECTED_ENGINE_HASH,
        "exact_ui_hash": sha256(UI) == EXPECTED_UI_HASH,
        "repaired_franchise_page_preserved": sha256(PAGE) == EXPECTED_PAGE_HASH,
        "page_compiles": True,
        "engine_compiles": True,
        "ui_compiles": True,
        "roster_construction_model_installed": (
            "team_roster_construction" in engine_text
        ),
        "player_depth_and_fit_exposed": (
            "family_depth_rank" in engine_text
            and "roster_fit" in engine_text
        ),
        "fa_target_lanes_installed": (
            "target_lane" in engine_text
            and "Primary need" in engine_text
            and "Secondary need" in engine_text
        ),
        "roster_construction_ui_installed": (
            "Roster construction" in ui_text
            and "Roster balance" in ui_text
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

    checks.update(synthetic_checks())

    checkpoint = load_franchise_checkpoint()
    checks["checkpoint_loads"] = checkpoint is not None
    if checkpoint is None:
        for name, passed in checks.items():
            print(f"  {name}: {'PASS' if passed else 'FAIL'}")
        return 1

    state = checkpoint.simulation_state
    preferences = (
        checkpoint.preferences
        if isinstance(checkpoint.preferences, dict)
        else {}
    )
    controlled_raw = preferences.get(
        "franchise_pref_controlled_teams",
        (),
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

    top_targets = [
        plan.free_agent_targets[0].player_name
        for plan in league.teams.values()
        if plan.free_agent_targets
    ]
    unique_top_targets = set(top_targets)
    max_target_share = (
        max(
            top_targets.count(name)
            for name in unique_top_targets
        )
        / len(top_targets)
        if top_targets
        else 0.0
    )

    primary_lane_matches = [
        bool(plan.free_agent_targets)
        and (
            plan.free_agent_targets[0].position_family
            == plan.biggest_need
        )
        and (
            plan.free_agent_targets[0].target_lane
            == "Primary need"
        )
        for plan in league.teams.values()
        if plan.free_agent_targets
    ]

    contender_plans = [
        plan
        for plan in league.teams.values()
        if plan.timeline
        in {
            TIMELINE_CHAMPIONSHIP_PUSH,
            TIMELINE_CONTENDER,
        }
    ]
    contender_rows = [
        row
        for plan in contender_plans
        for row in plan.player_decisions
    ]
    contender_market_share = (
        sum(
            row.asset_policy == "Market"
            for row in contender_rows
        )
        / len(contender_rows)
        if contender_rows
        else 0.0
    )

    retool_plans = [
        plan
        for plan in league.teams.values()
        if plan.timeline == TIMELINE_RETOOL
    ]
    retool_rows = [
        row
        for plan in retool_plans
        for row in plan.player_decisions
    ]
    retool_market_share = (
        sum(
            row.asset_policy == "Market"
            for row in retool_rows
        )
        / len(retool_rows)
        if retool_rows
        else 0.0
    )

    needed_players_marketed = [
        (plan.team, row.player_name)
        for plan in league.teams.values()
        for row in plan.player_decisions
        if row.roster_fit == "Need protection"
        and row.asset_policy in {"Market", "Exit"}
    ]

    checks.update({
        "planning_is_read_only": before == after == league.state_fingerprint,
        "planning_is_deterministic": (
            league_plan_to_dict(league)
            == league_plan_to_dict(second)
        ),
        "all_teams_have_primary_secondary_and_surplus": all(
            plan.biggest_need in {"Guard", "Wing/Forward", "Center"}
            and plan.secondary_need in {"Guard", "Wing/Forward", "Center"}
            and plan.surplus_family in {"Guard", "Wing/Forward", "Center"}
            and plan.biggest_need != plan.secondary_need
            for plan in league.teams.values()
        ),
        "all_roster_balance_scores_bounded": all(
            0.0 <= plan.roster_balance_score <= 100.0
            for plan in league.teams.values()
        ),
        "need_protected_players_are_not_marketed": not needed_players_marketed,
        "live_fa_top_targets_are_diversified": (
            len(unique_top_targets) >= 3
        ),
        "no_single_fa_target_dominates_league": (
            max_target_share <= 0.60
        ),
        "live_top_fa_lane_matches_primary_need": (
            bool(primary_lane_matches)
            and sum(primary_lane_matches) / len(primary_lane_matches) >= 0.90
        ),
        "contender_market_share_is_bounded": (
            contender_market_share <= 0.35
        ),
        "retool_market_share_is_not_entire_roster": (
            retool_market_share <= 0.65
        ),
        "checkpoint_hash_still_unchanged": (
            not checkpoint_before
            or sha256(CHECKPOINT) == checkpoint_before
        ),
    })

    print("=" * 104)
    print("CPU FRONT OFFICE ROSTER CONSTRUCTION + TARGET DIVERSIFICATION V1.3.2 VALIDATION")
    print("=" * 104)
    for name, passed in checks.items():
        print(f"  {name}: {'PASS' if passed else 'FAIL'}")

    print()
    print("LIVE ROSTER-CONSTRUCTION AUDIT")
    print(f"  Season: {league.season_label}")
    print(
        f"  Unique #1 FA targets: {len(unique_top_targets)} "
        f"across {len(top_targets)} team boards"
    )
    print(
        f"  Largest #1 FA target share: {max_target_share:.1%}"
    )
    print(
        f"  Contender Market share: {contender_market_share:.1%}"
    )
    print(
        f"  Retool Market share: {retool_market_share:.1%}"
    )
    print(
        "  Need-protected players incorrectly marketed: "
        f"{len(needed_players_marketed)}"
    )

    if needed_players_marketed:
        print("  Need-protection conflicts:")
        for team, player_name in needed_players_marketed:
            print(f"    {team}: {player_name}")

    print()
    print(
        "  RANK TEAM DIR               PRIMARY       SECONDARY     SURPLUS         BAL  TOP FA                 LANE"
    )
    print("  " + "-" * 98)
    for plan in sorted(
        league.teams.values(),
        key=lambda item: item.league_rank,
    ):
        top = (
            plan.free_agent_targets[0]
            if plan.free_agent_targets
            else None
        )
        top_name = top.player_name if top else "none"
        lane = top.target_lane if top else "none"
        print(
            f"  {plan.league_rank:>4} {plan.team:<4} "
            f"{plan.timeline_label:<17} "
            f"{plan.biggest_need:<13} "
            f"{plan.secondary_need:<13} "
            f"{plan.surplus_family:<13} "
            f"{plan.roster_balance_score:>4.0f}  "
            f"{top_name:<22} {lane}"
        )

    print()
    print("TOP TARGET FREQUENCY")
    for name in sorted(
        unique_top_targets,
        key=lambda n: (
            -top_targets.count(n),
            n,
        ),
    ):
        print(
            f"  {name}: {top_targets.count(name)}"
        )

    failed = [
        name
        for name, passed in checks.items()
        if not passed
    ]
    if failed:
        print()
        print("FAILED: " + ", ".join(failed))
        return 1

    print()
    print("CPU FRONT OFFICE ROSTER CONSTRUCTION + TARGET DIVERSIFICATION V1.3.2 VALIDATION PASSED")
    print(
        "READ-ONLY VALIDATION: no roster, contract, trade, free-agent, "
        "draft or checkpoint mutation was performed."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
