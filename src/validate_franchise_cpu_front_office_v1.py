from __future__ import annotations

import ast
import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
PAGE = ROOT / "pages" / "5_Franchise_Mode.py"
CHECKPOINT = ROOT / "outputs" / "runtime" / "franchise_mode_checkpoint_v1.pkl.gz"
EXPECTED_PAGE_HASH = 'a1ed427214063bb6c33f2fd86723cfa0fefbcb46786ebf4f223694c7fb3744d6'

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from franchise_cpu_front_office_v1 import (  # noqa: E402
    CPU_FRONT_OFFICE_MODEL_VERSION,
    CPU_FRONT_OFFICE_VERSION,
    TIMELINE_LABELS,
    build_league_front_office_plan,
    front_office_state_fingerprint,
    league_plan_to_dict,
)
from franchise_cpu_front_office_ui_v1 import CPU_FRONT_OFFICE_UI_VERSION  # noqa: E402
from simulation_franchise_checkpoint_v1 import load_franchise_checkpoint  # noqa: E402


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    checkpoint_before = sha256(CHECKPOINT) if CHECKPOINT.is_file() else ""
    page_text = PAGE.read_text(encoding="utf-8")
    checks: dict[str, bool] = {
        "engine_version_is_current": CPU_FRONT_OFFICE_VERSION == "franchise-cpu-front-office-v1-2026-08-13",
        "model_version_is_current": CPU_FRONT_OFFICE_MODEL_VERSION == "team-direction-roster-contract-market-v1-2026-08-13",
        "ui_version_is_current": CPU_FRONT_OFFICE_UI_VERSION == "franchise-cpu-front-office-ui-v1-2026-08-13",
        "exact_page_hash": sha256(PAGE) == EXPECTED_PAGE_HASH,
        "page_compiles": True,
        "page_imports_cpu_front_office": "from franchise_cpu_front_office_ui_v1 import" in page_text,
        "league_offseason_renders_cpu_front_office": "render_cpu_front_office_v1(" in page_text,
        "v1_7_performance_foundation_preserved": (
            "V1.7 deep startup profile" in page_text
            and "_franchise_module_source_signature_v1_6" in page_text
            and "FRANCHISE_UI_PREFERENCES_PATH_V1_6" in page_text
        ),
        "durable_checkpoint_exists": CHECKPOINT.is_file(),
    }
    try:
        ast.parse(page_text)
        compile(page_text, str(PAGE), "exec")
    except Exception:
        checks["page_compiles"] = False

    checkpoint = load_franchise_checkpoint()
    checks["checkpoint_loads"] = checkpoint is not None
    if checkpoint is None:
        for name, passed in checks.items():
            print(f"  {name}: {'PASS' if passed else 'FAIL'}")
        return 1

    state = checkpoint.simulation_state
    controlled_raw = checkpoint.preferences.get("franchise_pref_controlled_teams", ()) if isinstance(checkpoint.preferences, dict) else ()
    if isinstance(controlled_raw, str):
        controlled = (controlled_raw,)
    else:
        try:
            controlled = tuple(controlled_raw)
        except TypeError:
            controlled = ()

    before = front_office_state_fingerprint(state)
    league = build_league_front_office_plan(state, controlled_teams=controlled)
    after = front_office_state_fingerprint(state)
    second = build_league_front_office_plan(state, controlled_teams=controlled)

    team_count = len(getattr(state, "teams", {}))
    free_agents = {str(value) for value in tuple(getattr(state, "free_agent_player_ids", ()) or ())}
    all_decisions_match = all(
        len(plan.player_decisions) == plan.roster_count
        for plan in league.teams.values()
    )
    no_protected_cut_overlap = all(
        not set(plan.protected_player_ids).intersection(plan.cut_candidate_ids)
        for plan in league.teams.values()
    )
    cut_only_under_pressure = all(
        (not plan.cut_candidate_ids) or plan.roster_count > 15
        for plan in league.teams.values()
    )
    no_cornerstone_cut = all(
        row.market_stance != "Waive/cut candidate"
        for plan in league.teams.values()
        for row in plan.player_decisions
        if row.role == "Cornerstone"
    )
    fa_targets_valid = all(
        target.player_id in free_agents
        for plan in league.teams.values()
        for target in plan.free_agent_targets
    )
    fa_targets_unique = all(
        len({target.player_id for target in plan.free_agent_targets}) == len(plan.free_agent_targets)
        for plan in league.teams.values()
    )
    needs_valid = all(
        set(plan.need_scores) == {"Guard", "Wing/Forward", "Center"}
        and plan.biggest_need in plan.need_scores
        for plan in league.teams.values()
    )
    objectives_present = all(len(plan.objectives) >= 4 for plan in league.teams.values())
    controlled_flags_correct = all(
        plan.cpu_managed == (team not in {str(value).strip().upper() for value in controlled})
        for team, plan in league.teams.items()
    )

    checks.update({
        "all_league_teams_receive_plan": len(league.teams) == team_count and team_count >= 30,
        "planning_is_read_only": before == after == league.state_fingerprint,
        "planning_is_deterministic": league_plan_to_dict(league) == league_plan_to_dict(second),
        "all_rostered_players_receive_decision": all_decisions_match,
        "need_model_covers_three_position_families": needs_valid,
        "every_team_has_organizational_objectives": objectives_present,
        "controlled_teams_are_not_cpu_managed": controlled_flags_correct,
        "protected_players_are_never_cut_candidates": no_protected_cut_overlap,
        "cuts_only_exist_for_roster_pressure": cut_only_under_pressure,
        "cornerstones_are_never_cut_candidates": no_cornerstone_cut,
        "free_agent_targets_come_from_live_fa_pool": fa_targets_valid,
        "free_agent_target_boards_are_deduplicated": fa_targets_unique,
        "timeline_values_are_valid": all(plan.timeline in TIMELINE_LABELS for plan in league.teams.values()),
        "checkpoint_hash_still_unchanged": (not checkpoint_before) or sha256(CHECKPOINT) == checkpoint_before,
    })

    print("=" * 92)
    print("CPU FRONT OFFICE / OFFSEASON AI V1 VALIDATION")
    print("=" * 92)
    for name, passed in checks.items():
        print(f"  {name}: {'PASS' if passed else 'FAIL'}")

    print()
    print("LIVE LEAGUE FRONT OFFICE SAMPLE")
    print(f"  Season: {league.season_label}")
    print(f"  Teams planned: {len(league.teams)}")
    print(f"  CPU teams: {league.cpu_team_count}")
    print(f"  User-controlled teams: {league.user_team_count}")
    print("  Directions:")
    for key, label in TIMELINE_LABELS.items():
        print(f"    {label}: {league.timeline_counts.get(key, 0)}")
    print(f"  Roster-pressure teams: {len(league.roster_pressure_teams)}")
    print(f"  Contract/retention decisions: {league.contract_decision_count}")
    print(f"  Shop/listen candidates: {league.shop_candidate_count}")

    samples = list(sorted(league.teams))[:3]
    for team in samples:
        plan = league.teams[team]
        print()
        print(f"  {team} · {plan.timeline_label} · need={plan.biggest_need} · {plan.financial_posture}")
        print(f"    Top objective: {plan.objectives[0]}")
        if plan.player_decisions:
            leader = plan.player_decisions[0]
            print(f"    Core decision: {leader.player_name} · {leader.contract_plan} · {leader.market_stance}")
        if plan.free_agent_targets:
            target = plan.free_agent_targets[0]
            print(f"    FA board: {target.player_name} · fit {target.fit_score:.1f}")

    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        print()
        print("FAILED: " + ", ".join(failed))
        return 1

    print()
    print("CPU FRONT OFFICE / OFFSEASON AI V1 VALIDATION PASSED")
    print("READ-ONLY VALIDATION: no roster, contract, trade, free-agent, draft or checkpoint mutation was performed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
