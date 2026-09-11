from __future__ import annotations

import ast
import hashlib
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
PAGE = ROOT / "pages" / "5_Franchise_Mode.py"
CHECKPOINT = ROOT / "outputs" / "runtime" / "franchise_mode_checkpoint_v1.pkl.gz"
ENGINE = SRC / "franchise_cpu_front_office_v1.py"
UI = SRC / "franchise_cpu_front_office_ui_v1.py"

EXPECTED_PAGE_HASH = 'a1ed427214063bb6c33f2fd86723cfa0fefbcb46786ebf4f223694c7fb3744d6'
EXPECTED_ENGINE_HASH = "974a28e321d9a1fabd97bc6124d69b59670e88e1148593251c3ec00ac7937153"
EXPECTED_UI_HASH = "8e0511c5aac522d5ea5c2a5adab37d0f4a26a051c9b8d90dca899bb7aa0caced"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from franchise_cpu_front_office_v1 import (  # noqa: E402
    ASSET_TIER_ORDER,
    CPU_FRONT_OFFICE_MODEL_VERSION,
    CPU_FRONT_OFFICE_VERSION,
    TIMELINE_DEVELOP,
    TIMELINE_REBUILD,
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
        "engine_version_is_v1_5_1": (
            CPU_FRONT_OFFICE_VERSION
            == "franchise-cpu-front-office-v1.5.1-2026-08-13"
        ),
        "model_version_is_v1_5_1": (
            CPU_FRONT_OFFICE_MODEL_VERSION
            == "star-asset-package-quality-v1.5.1-2026-08-13"
        ),
        "ui_version_is_v1_5_1": (
            CPU_FRONT_OFFICE_UI_VERSION
            == "franchise-cpu-front-office-ui-v1.5.1-2026-08-13"
        ),
        "exact_engine_hash": sha256(ENGINE) == EXPECTED_ENGINE_HASH,
        "exact_ui_hash": sha256(UI) == EXPECTED_UI_HASH,
        "repaired_franchise_page_preserved": sha256(PAGE) == EXPECTED_PAGE_HASH,
        "page_compiles": True,
        "engine_compiles": True,
        "ui_compiles": True,
        "asset_tier_model_installed": "_asset_tier" in engine_text,
        "strategic_value_is_bound_before_asset_tier": (
            "value = intrinsic_player_value(player)" in engine_text
            and "strategic_value=value" in engine_text
            and "strategic_value=value," in engine_text
        ),
        "premium_return_floor_installed": "_minimum_return_for_asset_tier" in engine_text,
        "starter_need_depth_surplus_split_installed": (
            "starter_need_score" in engine_text
            and "depth_surplus_family" in engine_text
        ),
        "star_asset_ui_installed": (
            "Asset tier" in ui_text
            and "Required 1st-eq" in ui_text
            and "Depth surplus" in ui_text
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
    preferences = checkpoint.preferences if isinstance(checkpoint.preferences, dict) else {}
    controlled_raw = preferences.get("franchise_pref_controlled_teams", ())
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

    all_rows = [
        (team, plan, row)
        for team, plan in league.teams.items()
        for row in plan.player_decisions
    ]
    all_intents = [
        (team, plan, intent)
        for team, plan in league.teams.items()
        for intent in plan.trade_package_intents
    ]

    invalid_tiers = [
        (team, row.player_name, row.asset_tier)
        for team, _, row in all_rows
        if row.asset_tier not in ASSET_TIER_ORDER
    ]

    young_premium_in_develop_packages = []
    star_generic_intents = []
    premium_return_floor_failures = []
    premium_multi_player_failures = []
    franchise_not_protected = []

    decision_map = {
        (team, row.player_id): row
        for team, _, row in all_rows
    }

    for team, plan, intent in all_intents:
        outgoing_rows = [
            decision_map[(team, player_id)]
            for player_id in intent.outgoing_player_ids
            if (team, player_id) in decision_map
        ]
        peak = intent.outgoing_peak_asset_tier

        if peak in {"Franchise", "Star"}:
            if len(intent.outgoing_player_ids) != 1:
                premium_multi_player_failures.append((team, intent.intent_id))
            if intent.intent_type not in {
                "Premium star market",
                "Premium asset reshape",
            }:
                star_generic_intents.append((team, intent.intent_id, intent.intent_type))
            if (
                intent.required_first_equivalent_return < 1
                or not intent.minimum_return_label
            ):
                premium_return_floor_failures.append((team, intent.intent_id))

        if plan.timeline in {TIMELINE_DEVELOP, TIMELINE_REBUILD}:
            for row in outgoing_rows:
                if (
                    row.asset_tier in {"Franchise", "Star"}
                    and row.age <= 28.5
                ):
                    young_premium_in_develop_packages.append(
                        (team, intent.intent_id, row.player_name)
                    )

    for team, _, row in all_rows:
        if row.asset_tier == "Franchise" and row.age <= 30.0:
            if row.asset_policy not in {"Protect", "Develop"}:
                franchise_not_protected.append((team, row.player_name, row.asset_policy))

    coexistence_teams = [
        plan.team
        for plan in league.teams.values()
        if (
            plan.primary_upgrade_need == plan.depth_surplus_family
            and float(
                plan.position_profiles[
                    plan.primary_upgrade_need
                ]["starter_need_score"]
            ) > 0.0
            and plan.surplus_scores[
                plan.depth_surplus_family
            ] > 0.0
        )
    ]

    tier_counts = Counter(row.asset_tier for _, _, row in all_rows)
    package_tier_counts = Counter(
        intent.outgoing_peak_asset_tier
        for _, _, intent in all_intents
    )

    checks.update({
        "planning_is_read_only": before == after == league.state_fingerprint,
        "planning_is_deterministic": (
            league_plan_to_dict(league)
            == league_plan_to_dict(second)
        ),
        "all_player_asset_tiers_valid": not invalid_tiers,
        "franchise_assets_are_protected_in_prime": not franchise_not_protected,
        "young_stars_on_develop_rebuild_never_packaged": not young_premium_in_develop_packages,
        "star_packages_use_premium_intent_type": not star_generic_intents,
        "star_packages_are_single_asset": not premium_multi_player_failures,
        "star_packages_have_real_return_floor": not premium_return_floor_failures,
        "all_teams_have_upgrade_need_and_depth_surplus_labels": all(
            plan.primary_upgrade_need in {"Guard", "Wing/Forward", "Center"}
            and plan.secondary_upgrade_need in {"Guard", "Wing/Forward", "Center"}
            and plan.depth_surplus_family in {"Guard", "Wing/Forward", "Center"}
            for plan in league.teams.values()
        ),
        "starter_need_and_depth_surplus_can_coexist": bool(coexistence_teams),
        "package_intents_remain_planning_only": all(
            not intent.execution_ready
            for _, _, intent in all_intents
        ),
        "checkpoint_hash_still_unchanged": (
            not checkpoint_before
            or sha256(CHECKPOINT) == checkpoint_before
        ),
    })

    print("=" * 108)
    print("CPU FRONT OFFICE STAR ASSET INTELLIGENCE + PACKAGE QUALITY V1.5.1 VALIDATION")
    print("=" * 108)
    for name, passed in checks.items():
        print(f"  {name}: {'PASS' if passed else 'FAIL'}")

    print()
    print("LIVE STAR-ASSET AUDIT")
    print(f"  Season: {league.season_label}")
    print("  Player asset tiers:")
    for tier in sorted(
        ASSET_TIER_ORDER,
        key=lambda value: -ASSET_TIER_ORDER[value],
    ):
        print(f"    {tier}: {tier_counts.get(tier, 0)}")

    print()
    print("  Package peak tiers:")
    for tier in sorted(
        ASSET_TIER_ORDER,
        key=lambda value: -ASSET_TIER_ORDER[value],
    ):
        print(f"    {tier}: {package_tier_counts.get(tier, 0)}")

    print()
    print(
        f"  Young premium assets wrongly packaged by Develop/Rebuild: "
        f"{len(young_premium_in_develop_packages)}"
    )
    print(
        f"  Premium assets using generic intent type: "
        f"{len(star_generic_intents)}"
    )
    print(
        f"  Premium packages missing return floor: "
        f"{len(premium_return_floor_failures)}"
    )
    print(
        f"  Teams with starter-upgrade need + depth surplus at same position: "
        f"{len(coexistence_teams)}"
    )

    print()
    print(
        "  RANK TEAM DIR               PRIMARY UPGRADE  DEPTH SURPLUS  INTENTS"
    )
    print("  " + "-" * 80)
    for plan in sorted(
        league.teams.values(),
        key=lambda item: item.league_rank,
    ):
        print(
            f"  {plan.league_rank:>4} {plan.team:<4} "
            f"{plan.timeline_label:<17} "
            f"{plan.primary_upgrade_need:<16} "
            f"{plan.depth_surplus_family:<14} "
            f"{len(plan.trade_package_intents):>7}"
        )

    print()
    print("PREMIUM PACKAGE SAMPLES")
    premium_samples = [
        (team, plan, intent)
        for team, plan, intent in all_intents
        if intent.outgoing_peak_asset_tier in {"Franchise", "Star", "High-End Starter"}
    ]
    for team, plan, intent in premium_samples[:30]:
        names = " + ".join(intent.outgoing_player_names)
        print(
            f"  {team} · {intent.outgoing_peak_asset_tier} · "
            f"{intent.intent_type} · {names} · "
            f"required={intent.required_first_equivalent_return} first-eq · "
            f"blue-chip={intent.requires_blue_chip_return} · "
            f"return={intent.minimum_return_label}"
        )

    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        print()
        print("FAILED: " + ", ".join(failed))
        return 1

    print()
    print("CPU FRONT OFFICE STAR ASSET INTELLIGENCE + PACKAGE QUALITY V1.5.1 VALIDATION PASSED")
    print(
        "READ-ONLY VALIDATION: no trade, roster move, draft-right transfer, "
        "contract, free-agent or checkpoint mutation was performed."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
