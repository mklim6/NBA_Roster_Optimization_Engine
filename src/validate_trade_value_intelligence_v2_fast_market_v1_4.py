from __future__ import annotations

import hashlib
import time
from pathlib import Path

from freeform_trade_machine_engine_v3 import load_runtime_data, normalize_player_id, normalize_team
from franchise_live_asset_ledger_v1 import build_live_asset_ledger
from franchise_trade_finder_ai_v1 import (
    GOAL_BEST_AVAILABLE,
    TRADE_FINDER_AI_VERSION,
    TRADE_FINDER_VALUE_MODEL_VERSION,
    _bundle_value,
    _values_for_spec,
    build_team_trade_ai_profiles,
    generate_trade_finder_proposals,
    player_value_for_team,
)
from simulation_franchise_checkpoint_v1 import DEFAULT_CHECKPOINT_PATH, load_franchise_checkpoint

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
VALIDATOR_VERSION = "trade-value-intelligence-v2-fast-market-validator-v1.4a-2026-08-12"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def state_signature(state):
    return (
        getattr(getattr(state, "settings", None), "season_label", ""),
        int(getattr(state, "franchise_trade_revision_v1", 0) or 0),
        tuple(
            (team, tuple(team_state.roster_player_ids))
            for team, team_state in sorted(getattr(state, "teams", {}).items())
        ),
    )


def player_by_name(ledger, name: str):
    for row in ledger.player_rows:
        if str(row.get("player_name") or "").strip().lower() == name.lower():
            return dict(row)
    return None


def pid(row):
    return normalize_player_id(row.get("player_id")) if row else ""


def main() -> int:
    checkpoint_path = Path(DEFAULT_CHECKPOINT_PATH)
    before_hash = sha256(checkpoint_path)
    checkpoint = load_franchise_checkpoint()
    if checkpoint is None:
        raise RuntimeError("Durable franchise checkpoint could not be loaded.")

    runtime = load_runtime_data()
    state = checkpoint.simulation_state
    trade_state = checkpoint.trade_state
    before_state = state_signature(state)
    ledger = build_live_asset_ledger(runtime, state, trade_state)
    profiles = build_team_trade_ai_profiles(state, ledger)
    active = "PHI" if "PHI" in profiles else sorted(profiles)[0]
    neutral_profile = profiles[active]

    print("[1/4] Validating nonlinear player-value separation...", flush=True)
    names = {
        name: player_by_name(ledger, name)
        for name in (
            "Cooper Flagg",
            "VJ Edgecombe",
            "Luka Dončić",
            "Tyrese Maxey",
            "Anfernee Simons",
            "Marcus Sasser",
            "Dean Wade",
            "Bronny James",
        )
    }
    named_values = {
        name: player_value_for_team(row, neutral_profile)
        for name, row in names.items()
        if row is not None
    }

    print("[2/4] Validating old audit-regression trade shapes when those players are live...", flush=True)
    regression_flagg = None
    regression_luka = None
    if all(names.get(name) is not None for name in ("VJ Edgecombe", "Anfernee Simons", "Cooper Flagg", "Marcus Sasser")):
        player_map = {
            normalize_player_id(row.get("player_id")): dict(row)
            for row in ledger.player_rows
        }
        pick_map = {str(row.get("asset_id")): dict(row) for row in ledger.draft_rows}
        dal_profile = profiles.get("DAL", neutral_profile)
        spec = (
            (pid(names["VJ Edgecombe"]), pid(names["Anfernee Simons"])),
            (pid(names["Cooper Flagg"]), pid(names["Marcus Sasser"])),
            (),
            (),
        )
        regression_flagg = _values_for_spec(
            spec=spec,
            active_profile=neutral_profile,
            partner_profile=dal_profile,
            player_map=player_map,
            pick_map=pick_map,
            ledger=ledger,
            active_goal=GOAL_BEST_AVAILABLE,
        )[-1]
    if all(names.get(name) is not None for name in ("Tyrese Maxey", "Dean Wade", "Luka Dončić", "Bronny James")):
        player_map = {
            normalize_player_id(row.get("player_id")): dict(row)
            for row in ledger.player_rows
        }
        pick_map = {str(row.get("asset_id")): dict(row) for row in ledger.draft_rows}
        lal_profile = profiles.get("LAL", neutral_profile)
        spec = (
            (pid(names["Tyrese Maxey"]), pid(names["Dean Wade"])),
            (pid(names["Luka Dončić"]), pid(names["Bronny James"])),
            (),
            (),
        )
        regression_luka = _values_for_spec(
            spec=spec,
            active_profile=neutral_profile,
            partner_profile=lal_profile,
            player_map=player_map,
            pick_map=pick_map,
            ledger=ledger,
            active_goal=GOAL_BEST_AVAILABLE,
        )[-1]

    print("[3/4] Running bounded live market benchmark...", flush=True)
    started = time.perf_counter()
    result = generate_trade_finder_proposals(
        runtime,
        state,
        trade_state,
        active_team=active,
        goal=GOAL_BEST_AVAILABLE,
        include_picks=True,
        max_results=6,
        max_partners=8,
        max_targets_per_partner=4,
        max_package_evaluations=10,
        max_financial_prechecks=240,
        ledger=ledger,
    )
    elapsed = time.perf_counter() - started

    print("[4/4] Finalizing safety/performance checks...", flush=True)
    ai_text = (SRC / "franchise_trade_finder_ai_v1.py").read_text(encoding="utf-8")
    ui_text = (SRC / "franchise_trade_finder_ui_v1.py").read_text(encoding="utf-8")
    contract_text = (SRC / "franchise_player_contract_bridge_v1.py").read_text(encoding="utf-8")
    center_text = (SRC / "franchise_embedded_trade_center_v2.py").read_text(encoding="utf-8")

    named_sep_ok = True
    if "Cooper Flagg" in named_values and "VJ Edgecombe" in named_values:
        named_sep_ok = named_sep_ok and named_values["Cooper Flagg"] >= named_values["VJ Edgecombe"] + 20.0
    if "Luka Dončić" in named_values and "Tyrese Maxey" in named_values:
        named_sep_ok = named_sep_ok and named_values["Luka Dončić"] >= named_values["Tyrese Maxey"] + 10.0
    if "Bronny James" in named_values:
        named_sep_ok = named_sep_ok and named_values["Bronny James"] <= 25.0
    if "Dean Wade" in named_values:
        named_sep_ok = named_sep_ok and named_values["Dean Wade"] <= 20.0

    family_keys = [
        (p.partner_team, p.target_player_id or tuple(p.side_b_player_ids[:1]))
        for p in result.proposals
    ]
    surfaced_all_pass = all(
        str(p.preview_payload.get("status", "")).lower() == "pass"
        and bool(p.preview_payload.get("can_commit", False))
        for p in result.proposals
    )

    checks = {
        "validator_version_is_current": "v1.4a" in VALIDATOR_VERSION,
        "trade_finder_version_is_v1_4": "v1.4-trade-value-intelligence-v2-fast-market" in TRADE_FINDER_AI_VERSION,
        "value_model_is_nonlinear_v2": "trade-value-intelligence-v2-nonlinear" in TRADE_FINDER_VALUE_MODEL_VERSION,
        "replacement_level_curve_is_installed": "above_replacement ** 1.35" in ai_text,
        "diminishing_bundle_value_is_installed": "four quarters for a dollar" in ai_text,
        "expected_pick_slot_model_is_installed": "expected_slot" in ai_text and "_origin_win_pct" in ai_text,
        "star_scarcity_acceptance_floor_is_installed": "floor = max(floor, 12.0)" in ai_text,
        "named_live_value_separation_is_sane": named_sep_ok,
        "old_flagg_shape_is_rejected_by_value_if_available": regression_flagg is None or regression_flagg <= -12.0,
        "old_luka_shape_is_rejected_by_value_if_available": regression_luka is None or regression_luka <= -10.0,
        "cached_contract_snapshot_is_installed": "snapshot: FranchisePlayerContractSnapshot | None = None" in contract_text,
        "embedded_preview_accepts_market_caches": "market_read_only_fast_path" in center_text and "player_contract_snapshot" in center_text,
        "trade_finder_builds_contract_snapshot_once": "contract_snapshot = build_franchise_player_contract_snapshot" in ai_text,
        "missing_salary_fillers_are_prepruned": "side_*_live_salary_missing" in ai_text,
        "cached_contract_precheck_precedes_deep_preview": "contract_precheck_rejected" in ai_text,
        "deep_preview_budget_is_tight": result.packages_evaluated <= 10,
        "bounded_market_benchmark_under_three_minutes": elapsed < 180.0,
        "market_still_surfaces_actionable_offers": len(result.proposals) >= 1,
        "all_surfaced_offers_are_full_live_pass": surfaced_all_pass,
        "surfaced_offer_families_are_deduplicated": len(family_keys) == len(set(family_keys)),
        "user_overpay_and_cpu_decline_are_distinguished": "USER VALUE GUARD" in ai_text and "CPU DECLINES" in ai_text,
        "ui_reports_search_time_and_deep_checks": "Search time {result.search_elapsed_seconds:.1f}s" in ui_text,
        "generation_does_not_mutate_live_state": state_signature(state) == before_state,
        "checkpoint_hash_still_unchanged": sha256(checkpoint_path) == before_hash,
        "all_modified_files_compile": True,
    }

    for name in (
        "franchise_trade_finder_ai_v1.py",
        "franchise_trade_finder_ui_v1.py",
        "franchise_player_contract_bridge_v1.py",
        "franchise_embedded_trade_center_v2.py",
        Path(__file__).name,
    ):
        source_path = SRC / name
        source_text = source_path.read_text(encoding="utf-8")
        compile(source_text, str(source_path), "exec")

    failed = [name for name, passed in checks.items() if not passed]

    print("=" * 92)
    print("TRADE VALUE INTELLIGENCE V2 + FAST MARKET V1.4A VALIDATION")
    print("=" * 92)
    for name, passed in checks.items():
        print(f"  {name}: {'PASS' if passed else 'FAIL'}")

    print()
    print("VALUE REGRESSION")
    for name in ("Cooper Flagg", "VJ Edgecombe", "Luka Dončić", "Tyrese Maxey", "Anfernee Simons", "Marcus Sasser", "Dean Wade", "Bronny James"):
        if name in named_values:
            print(f"  {name}: {named_values[name]:.1f}")
    if regression_flagg is not None:
        print(f"  DAL CPU delta, Edgecombe+Simons for Flagg+Sasser: {regression_flagg:+.1f}")
    if regression_luka is not None:
        print(f"  LAL CPU delta, Maxey+Wade for Luka+Bronny: {regression_luka:+.1f}")

    print()
    print("FAST MARKET BENCHMARK")
    print(f"  Active team: {active}")
    print(f"  Search elapsed: {elapsed:.2f}s")
    print(f"  Teams reached: {result.teams_scanned}")
    print(f"  Packages generated: {result.candidate_packages_generated}")
    print(f"  Financial prechecks: {result.financial_prechecks}")
    print(f"  Financial PASS: {result.financial_precheck_passes}")
    print(f"  Expensive full previews: {result.packages_evaluated}")
    print(f"  Legal PASS: {result.legal_packages}")
    print(f"  CPU offers: {len(result.proposals)}")

    if failed:
        raise AssertionError("Trade Value Intelligence V2 + Fast Market V1.4 failed: " + ", ".join(failed))

    print()
    print("TRADE VALUE INTELLIGENCE V2 + FAST MARKET V1.4A VALIDATION PASSED")
    print("READ-ONLY VALIDATION: no live trade, roster move, or checkpoint write was performed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
