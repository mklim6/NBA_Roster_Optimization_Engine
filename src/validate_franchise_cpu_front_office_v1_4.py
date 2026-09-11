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
EXPECTED_ENGINE_HASH = '96f67691ab2b32acae12f2ee4a2ba566b67623c141a66cfa35cd905b08f4aae8'
EXPECTED_UI_HASH = '902aca71bc431152f5e8301718c540fcd7d25ce166bc8a4cd3242810a6627cfb'

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from franchise_cpu_front_office_v1 import (  # noqa: E402
    CPU_FRONT_OFFICE_MODEL_VERSION,
    CPU_FRONT_OFFICE_VERSION,
    TIMELINE_CHAMPIONSHIP_PUSH,
    TIMELINE_CONTENDER,
    TIMELINE_DEVELOP,
    TIMELINE_REBUILD,
    TIMELINE_RETOOL,
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
    engine_text = ENGINE.read_text(encoding="utf-8")
    ui_text = UI.read_text(encoding="utf-8")

    checks = {
        "engine_version_is_v1_4": (
            CPU_FRONT_OFFICE_VERSION
            == "franchise-cpu-front-office-v1.4-2026-08-13"
        ),
        "model_version_is_v1_4": (
            CPU_FRONT_OFFICE_MODEL_VERSION
            == "package-level-trade-intent-v1.4-2026-08-13"
        ),
        "ui_version_is_v1_4": (
            CPU_FRONT_OFFICE_UI_VERSION
            == "franchise-cpu-front-office-ui-v1.4-2026-08-13"
        ),
        "exact_engine_hash": sha256(ENGINE) == EXPECTED_ENGINE_HASH,
        "exact_ui_hash": sha256(UI) == EXPECTED_UI_HASH,
        "repaired_franchise_page_preserved": sha256(PAGE) == EXPECTED_PAGE_HASH,
        "page_compiles": True,
        "engine_compiles": True,
        "ui_compiles": True,
        "package_intent_dataclass_installed": (
            "FrontOfficeTradePackageIntent" in engine_text
        ),
        "draft_spend_budget_installed": (
            "_draft_spend_budget" in engine_text
        ),
        "package_intent_ui_installed": (
            "Trade package intent board" in ui_text
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

    all_intents = [
        (team, plan, intent)
        for team, plan in league.teams.items()
        for intent in plan.trade_package_intents
    ]

    intent_player_conflicts = []
    duplicate_packages = []
    invalid_package_sizes = []
    invalid_execution_ready = []
    invalid_rebuild_spend = []
    invalid_develop_spend = []
    invalid_contender_targets = []
    roster_ownership_failures = []

    players = getattr(state, "players", {})

    for team, plan in league.teams.items():
        seen = set()
        roster_ids = {
            str(getattr(player, "player_id", ""))
            for player in [
                players[player_id]
                for player_id in tuple(
                    getattr(
                        getattr(state, "teams", {}).get(team),
                        "roster_player_ids",
                        (),
                    )
                    or ()
                )
                if player_id in players
            ]
        }
        decisions = {
            row.player_id: row
            for row in plan.player_decisions
        }

        for intent in plan.trade_package_intents:
            key = tuple(sorted(intent.outgoing_player_ids))
            if key in seen:
                duplicate_packages.append((team, key))
            seen.add(key)

            if not (1 <= len(intent.outgoing_player_ids) <= 2):
                invalid_package_sizes.append((team, intent.intent_id))

            if intent.execution_ready:
                invalid_execution_ready.append((team, intent.intent_id))

            for player_id in intent.outgoing_player_ids:
                row = decisions.get(player_id)
                if row is None or player_id not in roster_ids:
                    roster_ownership_failures.append(
                        (team, intent.intent_id, player_id)
                    )
                    continue
                if (
                    row.asset_policy in {"Protect", "Develop"}
                    or row.roster_fit == "Need protection"
                    or row.role == "Cornerstone"
                ):
                    intent_player_conflicts.append(
                        (team, intent.intent_id, row.player_name)
                    )

            if plan.timeline == TIMELINE_REBUILD:
                if (
                    intent.draft_first_budget > 0
                    or intent.draft_second_budget > 0
                    or intent.allow_pick_swap
                ):
                    invalid_rebuild_spend.append(
                        (team, intent.intent_id)
                    )

            if plan.timeline == TIMELINE_DEVELOP:
                if intent.draft_first_budget > 0:
                    invalid_develop_spend.append(
                        (team, intent.intent_id)
                    )

            if plan.timeline in {
                TIMELINE_CHAMPIONSHIP_PUSH,
                TIMELINE_CONTENDER,
            }:
                if intent.target_family != plan.biggest_need:
                    invalid_contender_targets.append(
                        (team, intent.intent_id)
                    )

    cpu_plans = [
        plan
        for plan in league.teams.values()
        if plan.cpu_managed
    ]
    cpu_with_intents = [
        plan
        for plan in cpu_plans
        if plan.trade_package_intents
    ]

    rebuild_plans = [
        plan
        for plan in league.teams.values()
        if plan.timeline == TIMELINE_REBUILD
    ]
    push_plans = [
        plan
        for plan in league.teams.values()
        if plan.timeline == TIMELINE_CHAMPIONSHIP_PUSH
    ]
    contender_plans = [
        plan
        for plan in league.teams.values()
        if plan.timeline == TIMELINE_CONTENDER
    ]

    checks.update({
        "planning_is_read_only": before == after == league.state_fingerprint,
        "planning_is_deterministic": (
            league_plan_to_dict(league)
            == league_plan_to_dict(second)
        ),
        "league_aggregate_matches_team_intents": (
            league.trade_intent_count
            == len(all_intents)
            and set(league.teams_with_trade_intents)
            == {
                team
                for team, plan in league.teams.items()
                if plan.trade_package_intents
            }
        ),
        "package_intents_are_planning_only": not invalid_execution_ready,
        "package_sizes_are_bounded": not invalid_package_sizes,
        "package_players_are_live_team_assets": not roster_ownership_failures,
        "protected_develop_need_players_never_in_packages": not intent_player_conflicts,
        "packages_are_deduplicated_within_team": not duplicate_packages,
        "rebuilds_never_spend_draft_capital": not invalid_rebuild_spend,
        "develop_teams_never_spend_firsts": not invalid_develop_spend,
        "contender_packages_target_primary_need": not invalid_contender_targets,
        "championship_first_budget_is_at_least_contender_level": (
            bool(push_plans)
            and bool(contender_plans)
            and max(plan.draft_first_budget for plan in push_plans)
            >= max(plan.draft_first_budget for plan in contender_plans)
        ),
        "package_intent_coverage_is_meaningful": (
            len(cpu_with_intents) >= 12
        ),
        "rebuilds_have_future_value_return_profiles": all(
            (
                not plan.trade_package_intents
                or all(
                    (
                        "future" in intent.return_profile.lower()
                        or "young" in intent.return_profile.lower()
                        or "flexibility" in intent.return_profile.lower()
                    )
                    for intent in plan.trade_package_intents
                )
            )
            for plan in rebuild_plans
        ),
        "checkpoint_hash_still_unchanged": (
            not checkpoint_before
            or sha256(CHECKPOINT) == checkpoint_before
        ),
    })

    print("=" * 108)
    print("CPU FRONT OFFICE PACKAGE-LEVEL TRADE INTENT V1.4 VALIDATION")
    print("=" * 108)
    for name, passed in checks.items():
        print(f"  {name}: {'PASS' if passed else 'FAIL'}")

    print()
    print("LIVE PACKAGE-INTENT AUDIT")
    print(f"  Season: {league.season_label}")
    print(f"  Total package intents: {league.trade_intent_count}")
    print(
        f"  CPU teams with package intents: "
        f"{len(cpu_with_intents)} / {len(cpu_plans)}"
    )
    print(
        f"  Protected/develop/need conflicts: "
        f"{len(intent_player_conflicts)}"
    )
    print(
        f"  Duplicate packages: {len(duplicate_packages)}"
    )

    print()
    print(
        "  RANK TEAM DIR               INTENTS  1ST  2ND  SWAP  RETURN PROFILE"
    )
    print("  " + "-" * 96)
    for plan in sorted(
        league.teams.values(),
        key=lambda item: item.league_rank,
    ):
        print(
            f"  {plan.league_rank:>4} {plan.team:<4} "
            f"{plan.timeline_label:<17} "
            f"{len(plan.trade_package_intents):>7} "
            f"{plan.draft_first_budget:>4} "
            f"{plan.draft_second_budget:>4} "
            f"{('Y' if plan.allow_pick_swap else 'N'):>5}  "
            f"{plan.desired_return_profile}"
        )

    print()
    print("PACKAGE SAMPLES")
    for plan in sorted(
        league.teams.values(),
        key=lambda item: item.league_rank,
    ):
        for intent in plan.trade_package_intents[:2]:
            names = " + ".join(intent.outgoing_player_names)
            print(
                f"  {plan.team} · {intent.intent_type} · "
                f"{names} · priority={intent.priority:.1f} · "
                f"target={intent.target_family} · "
                f"draft={intent.draft_first_budget}F/"
                f"{intent.draft_second_budget}S"
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
    print("CPU FRONT OFFICE PACKAGE-LEVEL TRADE INTENT V1.4 VALIDATION PASSED")
    print(
        "READ-ONLY VALIDATION: package intents are planning objects only. "
        "No trade, roster move, draft-right transfer, contract, free-agent or "
        "checkpoint mutation was performed."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
