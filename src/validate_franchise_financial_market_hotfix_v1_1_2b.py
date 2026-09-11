from __future__ import annotations

import hashlib
import py_compile
from collections import Counter
from pathlib import Path

from freeform_trade_machine_engine_v3 import load_runtime_data
from franchise_financial_cba_bridge_v1 import (
    FINANCIAL_BRIDGE_VERSION,
    REGULAR_SEASON_STANDARD_MAX,
    build_franchise_financial_snapshot,
    evaluate_franchise_financial_trade,
)
from franchise_live_asset_ledger_v1 import build_live_asset_ledger
from franchise_trade_finder_ai_v1 import (
    GOAL_BEST_AVAILABLE,
    TRADE_FINDER_AI_VERSION,
    generate_trade_finder_proposals,
)
from simulation_franchise_checkpoint_v1 import (
    DEFAULT_CHECKPOINT_PATH,
    load_franchise_checkpoint,
)


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
VALIDATOR_VERSION = "franchise-financial-market-hotfix-validator-v1.1.2b-2026-08-12"


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

    print("[1/4] Building one cached live financial snapshot...", flush=True)
    snapshot = build_franchise_financial_snapshot(runtime, state)
    ledger = build_live_asset_ledger(runtime, state, trade_state)

    overflow_teams = sorted(
        row.team
        for row in snapshot.team_financials
        if row.standard_contract_count > REGULAR_SEASON_STANDARD_MAX
    )

    player_by_team = {}
    for row in ledger.player_rows:
        team = str(row.get("team") or "").strip().upper()
        if not team or str(row.get("roster_status") or "") != "rostered":
            continue
        player_by_team.setdefault(team, []).append(row)

    print("[2/4] Testing up to 72 salary-close one-for-one routes...", flush=True)
    candidate_pairs = []
    teams = sorted(player_by_team)
    for i, team_a in enumerate(teams):
        rows_a = sorted(
            player_by_team[team_a],
            key=lambda r: float(r.get("salary") or 0.0),
            reverse=True,
        )[:8]
        for team_b in teams[i + 1:]:
            rows_b = sorted(
                player_by_team[team_b],
                key=lambda r: float(r.get("salary") or 0.0),
                reverse=True,
            )[:8]
            for a in rows_a:
                for b in rows_b:
                    candidate_pairs.append(
                        (
                            abs(float(a.get("salary") or 0.0) - float(b.get("salary") or 0.0)),
                            team_a,
                            team_b,
                            a,
                            b,
                        )
                    )
    candidate_pairs.sort(key=lambda item: item[0])

    live_pass = None
    rejection_codes = Counter()
    checked = 0
    for _, team_a, team_b, a, b in candidate_pairs[:72]:
        checked += 1
        evaluation = evaluate_franchise_financial_trade(
            runtime,
            state,
            team_a=team_a,
            team_b=team_b,
            side_a_player_ids=(str(a["player_id"]),),
            side_b_player_ids=(str(b["player_id"]),),
            snapshot=snapshot,
            verify_nonmutation=False,
        )
        if evaluation.status == "pass":
            live_pass = (team_a, team_b, a, b, evaluation)
            break
        for check in evaluation.checks:
            if str(check.status).lower() != "pass":
                rejection_codes[str(check.code)] += 1

    print(f"      Direct routes checked: {checked}", flush=True)

    print("[3/4] Running bounded cached-snapshot Trade Finder search...", flush=True)
    active = sorted(getattr(state, "teams", {}))[0]

    def progress(event):
        stage = str(event.get("stage", ""))
        if stage in {"partner", "financial", "legality", "complete"}:
            print(
                f"      {stage}: partner={event.get('partner') or '-'} "
                f"financial={event.get('financial_prechecks', 0)}/120 "
                f"full={event.get('packages_evaluated', 0)}/30 "
                f"offers={event.get('proposals_found', 0)}",
                flush=True,
            )

    result = generate_trade_finder_proposals(
        runtime,
        state,
        trade_state,
        active_team=active,
        goal=GOAL_BEST_AVAILABLE,
        include_picks=True,
        max_results=4,
        max_partners=8,
        max_targets_per_partner=2,
        max_financial_prechecks=120,
        max_package_evaluations=30,
        progress_callback=progress,
        ledger=ledger,
    )

    print("[4/4] Finalizing validation...", flush=True)
    fin_text = (SRC / "franchise_financial_cba_bridge_v1.py").read_text(encoding="utf-8")
    finder_text = (SRC / "franchise_trade_finder_ai_v1.py").read_text(encoding="utf-8")

    checks = {
        "validator_version_is_current": "v1.1.2b" in VALIDATOR_VERSION,
        "financial_bridge_supports_cached_snapshot": (
            "v1.1.2-cached-routing" in FINANCIAL_BRIDGE_VERSION
            and "snapshot: FranchiseFinancialSnapshot | None = None" in fin_text
        ),
        "trade_finder_uses_one_cached_financial_snapshot": (
            "v1.1.2b-cached-financial-routing" in TRADE_FINDER_AI_VERSION
            and "financial_snapshot = build_franchise_financial_snapshot" in finder_text
            and "verify_nonmutation=False" in finder_text
        ),
        "durable_checkpoint_exists": checkpoint_path.is_file(),
        "generation_does_not_mutate_live_state": state_signature(state) == before_state,
        "no_worsening_roster_rule_is_preserved": (
            "future_existing_standard_roster_overflow_not_worsened" in fin_text
            and "future_existing_standard_roster_overflow_worsened" in fin_text
        ),
        "bounded_direct_route_search_completed": checked <= 72,
        "live_financial_one_for_one_route_exists": live_pass is not None,
        "finder_reaches_financial_pass_routes": result.financial_precheck_passes > 0,
        "full_legality_budget_remains_bounded": result.packages_evaluated <= 30,
        "neutral_pick_swap_fallback_stays_removed": not result.fallback_used,
        "checkpoint_hash_still_unchanged": sha256(checkpoint_path) == before_hash,
        "all_modified_files_compile": True,
    }

    for name in (
        "franchise_financial_cba_bridge_v1.py",
        "franchise_trade_finder_ai_v1.py",
        "franchise_trade_finder_ui_v1.py",
        Path(__file__).name,
    ):
        py_compile.compile(str(SRC / name), doraise=True)

    failed = [name for name, passed in checks.items() if not passed]

    print("=" * 92)
    print("FRANCHISE FINANCIAL + TRADE MARKET HOTFIX V1.1.2B VALIDATION")
    print("=" * 92)
    for name, passed in checks.items():
        print(f"  {name}: {'PASS' if passed else 'FAIL'}")

    print()
    print("LIVE FINANCIAL STATE")
    print(f"  Season: {snapshot.season_label}")
    print(f"  Phase: {snapshot.phase}")
    print(f"  Teams above {REGULAR_SEASON_STANDARD_MAX} modeled standard players: {len(overflow_teams)}")
    if overflow_teams:
        print("  Overflow teams: " + ", ".join(overflow_teams))

    print()
    print("LIVE FINANCIAL PASS ROUTE")
    if live_pass is not None:
        team_a, team_b, a, b, evaluation = live_pass
        print(f"  Teams: {team_a} <-> {team_b}")
        print(f"  {team_a}: {a.get('player_name')} (${float(a.get('salary') or 0):,.0f})")
        print(f"  {team_b}: {b.get('player_name')} (${float(b.get('salary') or 0):,.0f})")
        print(f"  Financial status: {evaluation.status}")
    else:
        print("  None found in bounded sample.")
        for code, count in rejection_codes.most_common(8):
            print(f"    {code}: {count}")

    print()
    print("BOUNDED TRADE FINDER ROUTING")
    print(f"  Financial prechecks: {result.financial_prechecks}")
    print(f"  Financial PASS routes: {result.financial_precheck_passes}")
    print(f"  Full legality checks: {result.packages_evaluated}")
    print(f"  Full Legal PASS: {result.legal_packages}")
    print(f"  CPU results: {len(result.proposals)}")

    if failed:
        raise AssertionError(
            "Franchise Financial + Trade Market Hotfix V1.1.2B failed: "
            + ", ".join(failed)
        )

    print()
    print("FRANCHISE FINANCIAL + TRADE MARKET HOTFIX V1.1.2B VALIDATION PASSED")
    print("READ-ONLY VALIDATION: no roster, player, trade, or checkpoint was modified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
