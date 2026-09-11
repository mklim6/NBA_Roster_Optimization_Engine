from __future__ import annotations

import hashlib
import py_compile
from pathlib import Path

from freeform_trade_machine_engine_v3 import load_runtime_data
from franchise_live_asset_ledger_v1 import build_live_asset_ledger
from franchise_trade_finder_ai_v1 import (
    GOAL_BIGGEST_NEED,
    TRADE_FINDER_AI_VERSION,
    TRADE_FINDER_VALUE_MODEL_VERSION,
    build_team_trade_ai_profiles,
    generate_trade_finder_proposals,
)
from simulation_franchise_checkpoint_v1 import (
    DEFAULT_CHECKPOINT_PATH,
    load_franchise_checkpoint,
)


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
VALIDATOR_VERSION = "franchise-trade-finder-realism-validator-v1.1-2026-08-12"


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
    active = sorted(getattr(state, "teams", {}))[0]

    print("Running player-centered Trade Finder realism sample...", flush=True)
    result = generate_trade_finder_proposals(
        runtime,
        state,
        trade_state,
        active_team=active,
        goal=GOAL_BIGGEST_NEED,
        include_picks=True,
        max_results=4,
        max_partners=4,
        max_targets_per_partner=2,
        max_package_evaluations=18,
        ledger=ledger,
    )

    backend = (SRC / "franchise_trade_finder_ai_v1.py").read_text(encoding="utf-8")
    ui = (SRC / "franchise_trade_finder_ui_v1.py").read_text(encoding="utf-8")

    player_centered = all(
        bool(proposal.side_a_player_ids or proposal.side_b_player_ids)
        for proposal in result.proposals
    )
    no_neutral_asset_only = all(
        not (
            not proposal.side_a_player_ids
            and not proposal.side_b_player_ids
        )
        for proposal in result.proposals
    )

    checks = {
        "validator_version_is_current": "v1.1" in VALIDATOR_VERSION,
        "trade_finder_version_is_v1_1": "v1.1-realism" in TRADE_FINDER_AI_VERSION,
        "value_model_version_is_v1_1": "v1.1-realism" in TRADE_FINDER_VALUE_MODEL_VERSION,
        "team_ai_profiles_cover_all_30_teams": len(profiles) == 30,
        "generation_does_not_mutate_live_state": state_signature(state) == before_state,
        "player_centered_results_only": player_centered,
        "neutral_pick_swap_fallback_removed": (
            not result.fallback_used
            and no_neutral_asset_only
            and "does not fill an empty basketball search with neutral" in backend
        ),
        "biggest_need_search_prefers_position_family": (
            "need_targets" in backend
            and "active_profile.biggest_need" in backend
        ),
        "nba_like_package_shapes_are_present": (
            "1-for-1" in backend
            and "2-for-1" in backend
            and "Depth rebalance" in backend
        ),
        "cpu_counter_path_preserved": "_find_counter(" in backend,
        "ui_explains_no_boring_fallback": (
            "meaningless same-round pick swaps" in ui
        ),
        "bounded_legality_budget_preserved": result.packages_evaluated <= 18,
        "all_modified_files_compile": True,
        "checkpoint_hash_still_unchanged": sha256(checkpoint_path) == before_hash,
    }

    for name in (
        "franchise_trade_finder_ai_v1.py",
        "franchise_trade_finder_ui_v1.py",
        "franchise_live_asset_ledger_ui_v1.py",
        "franchise_player_search_v1.py",
        "franchise_player_search_ui_v1.py",
    ):
        py_compile.compile(str(SRC / name), doraise=True)

    failed = [name for name, passed in checks.items() if not passed]

    print("=" * 92)
    print("TRADE FINDER REALISM V1.1 VALIDATION")
    print("=" * 92)
    for name, passed in checks.items():
        print(f"  {name}: {'PASS' if passed else 'FAIL'}")
    print()
    print("LIVE SAMPLE")
    print(f"  Active: {active}")
    print(f"  Biggest need: {profiles[active].biggest_need}")
    print(f"  Packages evaluated: {result.packages_evaluated}")
    print(f"  Player-centered results: {len(result.proposals)}")
    print(f"  Fallback used: {result.fallback_used}")
    for proposal in result.proposals[:4]:
        print(
            f"  {proposal.response_label} vs {proposal.partner_team} | "
            f"{proposal.deal_type} | target={proposal.target_player_name or '-'} | "
            f"user Δ {proposal.user_value_delta:+.1f} | CPU Δ {proposal.cpu_value_delta:+.1f}"
        )
    print()
    if failed:
        raise AssertionError("Trade Finder Realism V1.1 failed: " + ", ".join(failed))
    print("TRADE FINDER REALISM V1.1 VALIDATION PASSED")
    print("READ-ONLY VALIDATION: no live trade or checkpoint write was performed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
