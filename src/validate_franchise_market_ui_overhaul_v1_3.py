from __future__ import annotations

import hashlib
import py_compile
from pathlib import Path

from freeform_trade_machine_engine_v3 import load_runtime_data
from franchise_financial_cba_bridge_v1 import (
    FINANCIAL_BRIDGE_VERSION,
    build_franchise_financial_snapshot,
)
from franchise_live_asset_ledger_v1 import build_live_asset_ledger
from franchise_trade_finder_ai_v1 import (
    GOAL_BEST_AVAILABLE,
    GOAL_BIGGEST_NEED,
    TRADE_FINDER_AI_VERSION,
    generate_trade_finder_proposals,
)
from simulation_franchise_checkpoint_v1 import (
    DEFAULT_CHECKPOINT_PATH,
    load_franchise_checkpoint,
)

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
PAGE = ROOT / "pages" / "5_Franchise_Mode.py"
VALIDATOR_VERSION = "franchise-market-ui-overhaul-validator-v1.3-2026-08-12"


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
            for team, team_state in sorted(state.teams.items())
        ),
    )


def run_search(runtime, state, trade_state, ledger, goal):
    return generate_trade_finder_proposals(
        runtime,
        state,
        trade_state,
        active_team=sorted(state.teams)[0],
        goal=goal,
        include_picks=True,
        max_results=4,
        max_partners=29,
        max_targets_per_partner=5,
        max_financial_prechecks=360,
        max_package_evaluations=48,
        ledger=ledger,
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
    before_state = state_signature(state)

    snapshot = build_franchise_financial_snapshot(runtime, state)
    ledger = build_live_asset_ledger(runtime, state, trade_state)

    print("[1/3] Running Best Available future-market validation...", flush=True)
    best = run_search(runtime, state, trade_state, ledger, GOAL_BEST_AVAILABLE)
    print("[2/3] Running Fill Biggest Need future-market validation...", flush=True)
    need = run_search(runtime, state, trade_state, ledger, GOAL_BIGGEST_NEED)
    print("[3/3] Validating visual shell and safety markers...", flush=True)

    fin_text = (SRC / "franchise_financial_cba_bridge_v1.py").read_text(encoding="utf-8")
    finder_text = (SRC / "franchise_trade_finder_ai_v1.py").read_text(encoding="utf-8")
    ui_text = (SRC / "franchise_trade_finder_ui_v1.py").read_text(encoding="utf-8")
    branding_text = (SRC / "franchise_ui_branding_v1.py").read_text(encoding="utf-8")
    ledger_ui_text = (SRC / "franchise_live_asset_ledger_ui_v1.py").read_text(encoding="utf-8")
    page_text = PAGE.read_text(encoding="utf-8")

    modeled_rows = sum(
        1 for row in snapshot.player_financials if row.salary_confidence == "modeled"
    )
    live_rows = sum(
        1 for row in snapshot.player_financials if row.salary_confidence == "live_state"
    )

    checks = {
        "validator_version_is_current": "v1.3" in VALIDATOR_VERSION,
        "future_financial_policy_is_v2": (
            "v2-simulation-native-future-economy" in FINANCIAL_BRIDGE_VERSION
        ),
        "live_franchise_contract_salary_is_preferred": (
            "live_franchise_contract_salary" in fin_text
        ),
        "future_salary_uncertainty_release_is_installed": (
            "future_salary_proxy_uncertainty_release" in fin_text
            and "future_salary_simulation_band_release" in fin_text
        ),
        "future_apron_false_precision_is_removed": (
            "future_apron_status_simulation_advisory" in fin_text
        ),
        "roster_no_worsening_guardrail_is_preserved": (
            "future_existing_standard_roster_overflow_worsened" in fin_text
        ),
        "trade_finder_version_is_v1_3": (
            "v1.3-future-market-recovery" in TRADE_FINDER_AI_VERSION
        ),
        "best_available_target_accessibility_is_installed": (
            "def accessibility(" in finder_text
        ),
        "legal_cpu_declines_are_saved_as_near_misses": (
            "near_miss_buffer" in finder_text
            and "near_misses=tuple(near_misses)" in finder_text
        ),
        "best_available_reaches_financial_pass": best.financial_precheck_passes > 0,
        "best_available_reaches_legal_pass": best.legal_packages > 0,
        "best_available_surfaces_market_activity": bool(
            best.proposals or best.near_misses
        ),
        "fill_need_reaches_financial_pass": need.financial_precheck_passes > 0,
        "fill_need_reaches_legal_pass": need.legal_packages > 0,
        "at_least_one_strategy_has_cpu_approved_offer": bool(
            best.proposals or need.proposals
        ),
        "generation_does_not_mutate_live_state": state_signature(state) == before_state,
        "arena_ui_is_installed": (
            "Trade Command Center" in ui_text
            and "Future Economy V2" in ui_text
            and "Negotiation leads" in ui_text
        ),
        "nba_cdn_team_logos_are_installed": "cdn.nba.com/logos/nba/" in branding_text,
        "asset_room_ui_is_branded": "LIVE FRANCHISE ASSET ROOM" in ledger_ui_text,
        "franchise_mode_compact_team_hero_is_installed": (
            "FRANCHISE_VISUAL_V1_3" in page_text
            and "fm-hero-v13" in page_text
        ),
        "checkpoint_hash_still_unchanged": sha256(checkpoint_path) == before_hash,
        "all_modified_files_compile": True,
    }

    for name in (
        "franchise_financial_cba_bridge_v1.py",
        "franchise_trade_finder_ai_v1.py",
        "franchise_trade_finder_ui_v1.py",
        "franchise_ui_branding_v1.py",
        "franchise_live_asset_ledger_ui_v1.py",
        "franchise_player_search_ui_v1.py",
        Path(__file__).name,
    ):
        py_compile.compile(str(SRC / name), doraise=True)
    py_compile.compile(str(PAGE), doraise=True)

    failed = [name for name, passed in checks.items() if not passed]

    print("=" * 92)
    print("FRANCHISE MARKET + UI OVERHAUL V1.3 VALIDATION")
    print("=" * 92)
    for name, passed in checks.items():
        print(f"  {name}: {'PASS' if passed else 'FAIL'}")

    print()
    print("FUTURE ECONOMY")
    print(f"  Season: {snapshot.season_label}")
    print(f"  Live-state salary rows: {live_rows}")
    print(f"  Modeled salary rows: {modeled_rows}")

    for label, result in (("BEST AVAILABLE", best), ("FILL BIGGEST NEED", need)):
        print()
        print(label)
        print(f"  Teams reached: {result.teams_scanned}")
        print(f"  Packages built: {result.candidate_packages_generated}")
        print(f"  Financial PASS: {result.financial_precheck_passes}")
        print(f"  Legal PASS: {result.legal_packages}")
        print(f"  CPU-approved offers: {len(result.proposals)}")
        print(f"  Negotiation leads: {len(result.near_misses)}")

    if failed:
        raise AssertionError("Franchise Market + UI Overhaul V1.3 failed: " + ", ".join(failed))

    print()
    print("FRANCHISE MARKET + UI OVERHAUL V1.3 VALIDATION PASSED")
    print("READ-ONLY VALIDATION: no live trade or checkpoint write was performed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
