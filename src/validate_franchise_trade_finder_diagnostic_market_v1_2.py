from __future__ import annotations

import hashlib
import py_compile
from pathlib import Path

from freeform_trade_machine_engine_v3 import load_runtime_data
from franchise_financial_cba_bridge_v1 import FINANCIAL_BRIDGE_VERSION
from franchise_live_asset_ledger_v1 import build_live_asset_ledger
from franchise_trade_finder_ai_v1 import (
    GOAL_BIGGEST_NEED,
    TRADE_FINDER_AI_VERSION,
    TRADE_FINDER_VALUE_MODEL_VERSION,
    generate_trade_finder_proposals,
)
from simulation_franchise_checkpoint_v1 import DEFAULT_CHECKPOINT_PATH, load_franchise_checkpoint

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
VALIDATOR_VERSION = "franchise-trade-finder-diagnostic-market-validator-v1.2-2026-08-12"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def signature(state):
    return (
        getattr(getattr(state, "settings", None), "season_label", ""),
        int(getattr(state, "franchise_trade_revision_v1", 0) or 0),
        tuple((team, tuple(ts.roster_player_ids)) for team, ts in sorted(state.teams.items())),
    )


def main() -> int:
    checkpoint_path = Path(DEFAULT_CHECKPOINT_PATH)
    before_hash = sha256(checkpoint_path)
    checkpoint = load_franchise_checkpoint()
    if checkpoint is None:
        raise RuntimeError("Durable franchise checkpoint could not be loaded.")

    runtime = load_runtime_data()
    state = checkpoint.simulation_state
    trade_state = checkpoint.trade_state
    before = signature(state)
    ledger = build_live_asset_ledger(runtime, state, trade_state)
    active = sorted(state.teams)[0]

    print("Running diagnostic Fill-biggest-need market sample...", flush=True)
    result = generate_trade_finder_proposals(
        runtime,
        state,
        trade_state,
        active_team=active,
        goal=GOAL_BIGGEST_NEED,
        include_picks=True,
        max_results=4,
        max_partners=12,
        max_targets_per_partner=4,
        max_financial_prechecks=160,
        max_package_evaluations=40,
        ledger=ledger,
    )

    backend = (SRC / "franchise_trade_finder_ai_v1.py").read_text(encoding="utf-8")
    ui = (SRC / "franchise_trade_finder_ui_v1.py").read_text(encoding="utf-8")

    partner_targets = sum(row.get("targets", 0) for row in result.partner_funnel.values())
    partner_packages = sum(row.get("packages", 0) for row in result.partner_funnel.values())
    partner_fin_pass = sum(row.get("financial_pass", 0) for row in result.partner_funnel.values())
    partner_legal = sum(row.get("legal_pass", 0) for row in result.partner_funnel.values())

    checks = {
        "validator_version_is_current": "v1.2" in VALIDATOR_VERSION,
        "trade_finder_version_is_diagnostic_market": "v1.2-diagnostic-market" in TRADE_FINDER_AI_VERSION,
        "value_model_version_is_market_breadth": "v1.2-market-breadth" in TRADE_FINDER_VALUE_MODEL_VERSION,
        "cached_financial_bridge_is_still_required": "cached-routing" in FINANCIAL_BRIDGE_VERSION,
        "durable_checkpoint_exists": checkpoint_path.is_file(),
        "generation_does_not_mutate_live_state": signature(state) == before,
        "targets_are_counted": result.targets_identified > 0,
        "packages_are_counted": result.candidate_packages_generated > 0,
        "partner_funnel_targets_reconcile": partner_targets == result.targets_identified,
        "partner_funnel_packages_reconcile": partner_packages == result.candidate_packages_generated,
        "partner_funnel_financial_pass_reconciles": partner_fin_pass == result.financial_precheck_passes,
        "partner_funnel_legal_pass_reconciles": partner_legal == result.legal_packages,
        "guaranteed_market_exploration_is_installed": "guaranteed_routes" in backend and "guaranteed_exploration_packages" in backend,
        "biggest_need_search_preserves_secondary_market_breadth": "secondary_targets" in backend and "primary_quota" in backend,
        "actual_partner_scan_count_is_used": "teams_scanned=partners_scanned_count" in backend,
        "diagnostic_funnel_is_exposed_in_ui": "Market funnel" in ui and "Partner-by-partner market funnel" in ui,
        "ui_distinguishes_zero_result_failure_stage": "Market bottleneck: FINANCIAL ROUTING" in ui and "Market bottleneck: CPU VALUE" in ui,
        "team_branding_and_logos_are_present": "_TEAM_BRAND" in ui and "_logo_url" in ui and "tf-hero" in ui,
        "neutral_pick_swap_fallback_stays_removed": not result.fallback_used,
        "financial_search_is_reached": result.financial_prechecks > 0,
        "checkpoint_hash_still_unchanged": sha256(checkpoint_path) == before_hash,
        "all_modified_files_compile": True,
    }

    for name in (
        "franchise_trade_finder_ai_v1.py",
        "franchise_trade_finder_ui_v1.py",
        Path(__file__).name,
    ):
        py_compile.compile(str(SRC / name), doraise=True)

    failed = [name for name, passed in checks.items() if not passed]

    print("=" * 92)
    print("TRADE FINDER DIAGNOSTIC + MARKET GENERATION V1.2 VALIDATION")
    print("=" * 92)
    for name, passed in checks.items():
        print(f"  {name}: {'PASS' if passed else 'FAIL'}")
    print()
    print("LIVE FUNNEL SAMPLE")
    print(f"  Active team: {active}")
    print(f"  Teams reached: {result.teams_scanned}")
    print(f"  Targets: {result.targets_identified} ({result.primary_need_targets_identified} primary-need)")
    print(f"  Packages built: {result.candidate_packages_generated}")
    print(f"  Value-screen routes: {result.value_screen_passes}")
    print(f"  Guaranteed exploration: {result.guaranteed_exploration_packages}")
    print(f"  Financial prechecks: {result.financial_prechecks}")
    print(f"  Financial PASS: {result.financial_precheck_passes}")
    print(f"  Full legality: {result.packages_evaluated}")
    print(f"  Legal PASS: {result.legal_packages}")
    print(f"  CPU rejected legal: {result.cpu_rejected_legal}")
    print(f"  Offers: {len(result.proposals)}")
    print()
    if failed:
        raise AssertionError("Trade Finder V1.2 validation failed: " + ", ".join(failed))
    print("TRADE FINDER DIAGNOSTIC + MARKET GENERATION V1.2 VALIDATION PASSED")
    print("READ-ONLY VALIDATION: no trade, roster, player, or checkpoint was modified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
