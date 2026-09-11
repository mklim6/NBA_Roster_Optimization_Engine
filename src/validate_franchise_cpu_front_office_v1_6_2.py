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

SHARED = SRC / "franchise_asset_market_value_v1.py"
ENGINE = SRC / "franchise_cpu_front_office_v1.py"
UI = SRC / "franchise_cpu_front_office_ui_v1.py"

EXPECTED_PAGE_HASH = 'a1ed427214063bb6c33f2fd86723cfa0fefbcb46786ebf4f223694c7fb3744d6'
EXPECTED_SHARED_HASH = "6ab1c377757ade6c6208cc66a20f6306827577f917bbe3fa39944e2946975899"
EXPECTED_ENGINE_HASH = "2978362f8edf626431fd29bc4f349525041d48460c4e7dc22dee230deceffc9f"
EXPECTED_UI_HASH = "cf3bd0a12f17c272b9323c85b00cfe3c26014a5a4fec34c42fd2ef5d9ab63806"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from franchise_asset_market_value_v1 import (  # noqa: E402
    ASSET_MARKET_CONTEXT_VERSION,
    ASSET_MARKET_MODEL_VERSION,
    ASSET_TIER_ORDER,
    build_league_asset_market_contexts,
)
from franchise_cpu_front_office_v1 import (  # noqa: E402
    CPU_FRONT_OFFICE_MODEL_VERSION,
    CPU_FRONT_OFFICE_VERSION,
    build_league_front_office_plan,
    front_office_state_fingerprint,
    league_plan_to_dict,
)
from franchise_cpu_front_office_ui_v1 import CPU_FRONT_OFFICE_UI_VERSION  # noqa: E402
from simulation_franchise_checkpoint_v1 import load_franchise_checkpoint  # noqa: E402


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _named_contexts(league):
    wanted = {
        "Cooper Flagg",
        "Derrick White",
        "Stephen Curry",
        "Jalen Suggs",
        "Kawhi Leonard",
        "Anthony Davis",
        "Domantas Sabonis",
        "Trae Young",
        "Pascal Siakam",
        "Lauri Markkanen",
        "Luka Doncic",
        "Luka Dončić",
        "Tyrese Maxey",
    }
    output = {}
    for plan in league.teams.values():
        for row in plan.player_decisions:
            if row.player_name in wanted:
                output[row.player_name] = row
    return output


def main() -> int:
    checkpoint_before = sha256(CHECKPOINT) if CHECKPOINT.is_file() else ""

    page_text = PAGE.read_text(encoding="utf-8")
    shared_text = SHARED.read_text(encoding="utf-8")
    engine_text = ENGINE.read_text(encoding="utf-8")
    ui_text = UI.read_text(encoding="utf-8")

    checks = {
        "engine_version_is_v1_6_2": (
            CPU_FRONT_OFFICE_VERSION
            == "franchise-cpu-front-office-v1.6.2-2026-08-13"
        ),
        "model_version_is_v1_6_2": (
            CPU_FRONT_OFFICE_MODEL_VERSION
            == "shared-market-context-asset-tier-calibration-v1.6.2-2026-08-13"
        ),
        "ui_version_is_v1_6_2": (
            CPU_FRONT_OFFICE_UI_VERSION
            == "franchise-cpu-front-office-ui-v1.6.2-2026-08-13"
        ),
        "shared_context_version_is_current": (
            ASSET_MARKET_CONTEXT_VERSION
            == "franchise-asset-market-context-v1.0.2-2026-08-13"
        ),
        "shared_market_model_version_is_current": (
            ASSET_MARKET_MODEL_VERSION
            == "age-upside-control-salary-availability-v1.0.2-2026-08-13"
        ),
        "exact_shared_hash": sha256(SHARED) == EXPECTED_SHARED_HASH,
        "exact_engine_hash": sha256(ENGINE) == EXPECTED_ENGINE_HASH,
        "exact_ui_hash": sha256(UI) == EXPECTED_UI_HASH,
        "repaired_franchise_page_preserved": sha256(PAGE) == EXPECTED_PAGE_HASH,
        "shared_module_compiles": True,
        "page_compiles": True,
        "engine_compiles": True,
        "ui_compiles": True,
        "nonlinear_trade_value_context_installed": (
            "0.014 * score * score" in shared_text
        ),
        "league_relative_tier_caps_installed": (
            "franchise_cap" in shared_text
            and "star_total_cap" in shared_text
        ),
        "trade_finder_adapter_is_exposed": (
            "trade_market_value_from_row" in shared_text
            and "build_trade_row_market_context" in shared_text
        ),
        "market_context_ui_installed": (
            "Market score" in ui_text
            and "Trade value" in ui_text
            and "Availability" in ui_text
        ),
        "durable_checkpoint_exists": CHECKPOINT.is_file(),
    }

    for key, text, path in (
        ("shared_module_compiles", shared_text, SHARED),
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

    rows = [
        row
        for plan in league.teams.values()
        for row in plan.player_decisions
    ]
    tiers = Counter(row.asset_tier for row in rows)
    n = len(rows)
    franchise_count = tiers.get("Franchise", 0)
    star_count = tiers.get("Star", 0)
    premium_count = franchise_count + star_count

    invalid_scores = [
        row.player_name
        for row in rows
        if not (
            0.0 <= row.market_value_score <= 100.0
            and 0.0 <= row.organizational_value_score <= 100.0
            and 0.0 <= row.trade_value_score <= 185.0
            and 0.0 <= row.age_curve_score <= 100.0
            and 0.0 <= row.contract_control_score <= 100.0
            and 0.0 <= row.salary_efficiency_score <= 100.0
            and 0.0 <= row.availability_score <= 100.0
            and 0.0 <= row.market_context_confidence <= 100.0
        )
    ]

    named = _named_contexts(league)

    flagg_ok = True
    flagg = named.get("Cooper Flagg")
    if flagg is not None:
        flagg_ok = (
            flagg.asset_tier in {"Franchise", "Star"}
            and flagg.trade_value_score >= 120.0
        )

    kawhi_ok = True
    kawhi = named.get("Kawhi Leonard")
    if kawhi is not None and kawhi.age >= 33.0:
        kawhi_ok = kawhi.asset_tier != "Franchise"

    white_ok = True
    white = named.get("Derrick White")
    if white is not None and white.age >= 30.0:
        white_ok = white.asset_tier != "Franchise"

    curry_ok = True
    curry = named.get("Stephen Curry")
    if curry is not None:
        curry_ok = (
            curry.asset_tier == "Star"
            and curry.trade_value_score >= 60.0
            and curry.minimum_return_label
            != "Clear high-end rotation upgrade or strong young value"
        )

    ad_ok = True
    ad = named.get("Anthony Davis")
    if ad is not None and ad.age >= 32.0:
        ad_ok = ad.asset_tier != "Franchise"

    sabonis_ok = True
    sabonis = named.get("Domantas Sabonis")
    if sabonis is not None and sabonis.overall >= 84.0:
        sabonis_ok = (
            ASSET_TIER_ORDER.get(sabonis.asset_tier, -1)
            >= ASSET_TIER_ORDER["High-End Starter"]
        )

    suggs_ok = True
    suggs = named.get("Jalen Suggs")
    if (
        suggs is not None
        and suggs.age <= 25.0
        and suggs.overall >= 82.0
        and suggs.potential >= 90.0
    ):
        suggs_ok = suggs.asset_tier in {"Star", "Franchise"}

    young_prime_premium = [
        row
        for row in rows
        if row.age <= 25.0
        and row.potential >= 90.0
        and row.overall >= 82.0
    ]
    young_prime_low = [
        row.player_name
        for row in young_prime_premium
        if ASSET_TIER_ORDER.get(row.asset_tier, -1)
        < ASSET_TIER_ORDER["Star"]
    ]

    older_franchise = [
        row.player_name
        for row in rows
        if row.asset_tier == "Franchise"
        and row.age >= 33.0
    ]

    legacy_superstars_underclassified = [
        row.player_name
        for row in rows
        if row.overall >= 91.5
        and row.market_value_score >= 55.0
        and row.asset_tier not in {"Franchise", "Star"}
    ]

    checks.update({
        "planning_is_read_only": before == after == league.state_fingerprint,
        "planning_is_deterministic": (
            league_plan_to_dict(league)
            == league_plan_to_dict(second)
        ),
        "all_market_context_scores_bounded": not invalid_scores,
        "franchise_tier_is_genuinely_scarce": (
            4 <= franchise_count <= 15
            and (
                n == 0
                or franchise_count / n <= 0.045
            )
        ),
        "premium_tier_population_is_reasonable": (
            20 <= premium_count <= 55
        ),
        "no_age_33_plus_franchise_assets": not older_franchise,
        "elite_young_assets_are_not_underclassified": not young_prime_low,
        "flagg_is_premium_young_asset_if_live": flagg_ok,
        "kawhi_is_not_franchise_at_33_plus_if_live": kawhi_ok,
        "derrick_white_is_not_franchise_if_live": white_ok,
        "stephen_curry_remains_star_if_live": curry_ok,
        "legacy_91_5_plus_superstars_are_not_underclassified": (
            not legacy_superstars_underclassified
        ),
        "anthony_davis_is_not_franchise_at_32_plus_if_live": ad_ok,
        "sabonis_is_at_least_high_end_starter_if_live": sabonis_ok,
        "jalen_suggs_elite_young_floor_if_live": suggs_ok,
        "package_intents_still_planning_only": all(
            not intent.execution_ready
            for plan in league.teams.values()
            for intent in plan.trade_package_intents
        ),
        "checkpoint_hash_still_unchanged": (
            not checkpoint_before
            or sha256(CHECKPOINT) == checkpoint_before
        ),
    })

    print("=" * 112)
    print("CPU FRONT OFFICE SHARED MARKET CONTEXT + ASSET TIER CALIBRATION V1.6.2 VALIDATION")
    print("=" * 112)
    for name, passed in checks.items():
        print(f"  {name}: {'PASS' if passed else 'FAIL'}")

    print()
    print("LIVE ASSET-TIER DISTRIBUTION")
    print(f"  Season: {league.season_label}")
    print(f"  Rostered players evaluated: {n}")
    for tier in sorted(
        ASSET_TIER_ORDER,
        key=lambda value: -ASSET_TIER_ORDER[value],
    ):
        print(f"    {tier}: {tiers.get(tier, 0)}")

    print()
    print(
        "  Elite young assets below Star: "
        f"{len(young_prime_low)}"
    )
    if young_prime_low:
        for player_name in young_prime_low:
            print(f"    {player_name}")

    print(
        "  Legacy 92+ OVR superstars below Star: "
        f"{len(legacy_superstars_underclassified)}"
    )
    if legacy_superstars_underclassified:
        for player_name in legacy_superstars_underclassified:
            print(f"    {player_name}")

    print()
    print("NAMED MARKET CONTEXT")
    for name in (
        "Cooper Flagg",
        "Derrick White",
        "Stephen Curry",
        "Jalen Suggs",
        "Kawhi Leonard",
        "Anthony Davis",
        "Domantas Sabonis",
        "Trae Young",
        "Pascal Siakam",
        "Lauri Markkanen",
        "Luka Doncic",
        "Luka Dončić",
        "Tyrese Maxey",
    ):
        row = named.get(name)
        if row is None:
            continue
        years = (
            "?"
            if getattr(row, "contract_years_remaining", None) is None
            else str(getattr(row, "contract_years_remaining"))
        )
        print(
            f"  {row.player_name:<20} "
            f"age={row.age:>4.1f} "
            f"ovr={row.overall:>5.1f} "
            f"pot={row.potential:>5.1f} "
            f"tier={row.asset_tier:<16} "
            f"market={row.market_value_score:>5.1f} "
            f"org={row.organizational_value_score:>5.1f} "
            f"trade={row.trade_value_score:>6.1f} "
            f"ctrl={row.contract_control_score:>5.1f} "
            f"avail={row.availability_score:>5.1f}"
        )

    print()
    print("PREMIUM PACKAGE RETURN FLOORS")
    for plan in sorted(
        league.teams.values(),
        key=lambda item: item.league_rank,
    ):
        for intent in plan.trade_package_intents:
            if intent.outgoing_peak_asset_tier not in {
                "Franchise",
                "Star",
                "High-End Starter",
            }:
                continue
            names = " + ".join(intent.outgoing_player_names)
            print(
                f"  {plan.team} · "
                f"{intent.outgoing_peak_asset_tier} · "
                f"{names} · "
                f"required={intent.required_first_equivalent_return} first-eq · "
                f"blue-chip={intent.requires_blue_chip_return} · "
                f"{intent.minimum_return_label}"
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
    print("CPU FRONT OFFICE SHARED MARKET CONTEXT + ASSET TIER CALIBRATION V1.6.2 VALIDATION PASSED")
    print(
        "READ-ONLY VALIDATION: no roster, trade, draft-right, contract, "
        "free-agent or checkpoint mutation was performed."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
