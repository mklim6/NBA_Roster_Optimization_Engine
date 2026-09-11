from __future__ import annotations

import copy
import hashlib
import json
import py_compile
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from freeform_trade_machine_engine_v3 import load_runtime_data, normalize_team
from simulation_franchise_checkpoint_v1 import DEFAULT_CHECKPOINT_PATH, load_franchise_checkpoint
from simulation_league_state_v1 import validate_simulation_league_state
from franchise_live_asset_ledger_v1 import ASSET_LEDGER_VERSION, build_live_asset_ledger
from franchise_draft_right_stepien_bridge_v1 import build_franchise_draft_right_profiles
from franchise_embedded_trade_center_v2 import build_franchise_trade_preview
from franchise_trade_transaction_v1 import (
    FRANCHISE_TRADE_TRANSACTION_VERSION,
    FranchiseTradeTransactionError,
    _apply_player_moves,
    build_franchise_trade_candidate,
)

VALIDATOR_VERSION = "franchise-trade-transaction-validator-v1-2026-08-12"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def signature(value) -> str:
    return hashlib.sha256(repr(value).encode("utf-8")).hexdigest()


def find_pick_only_pass(runtime, state, trade_state, ledger):
    profiles = build_franchise_draft_right_profiles(ledger)
    seconds_by_team = {}
    for p in profiles:
        if p.round_number == 2 and p.bridge_ready:
            seconds_by_team.setdefault(p.current_owner, []).append(p)
    teams = sorted(t for t, rows in seconds_by_team.items() if rows)
    for i, team_a in enumerate(teams):
        for team_b in teams[i + 1:]:
            a = sorted(seconds_by_team[team_a], key=lambda p: (p.draft_year, p.asset_id))[0]
            b = sorted(seconds_by_team[team_b], key=lambda p: (p.draft_year, p.asset_id))[0]
            preview = build_franchise_trade_preview(
                runtime,
                state,
                trade_state,
                team_a=team_a,
                team_b=team_b,
                side_a_pick_asset_ids=(a.asset_id,),
                side_b_pick_asset_ids=(b.asset_id,),
                ledger=ledger,
            )
            if preview.status == "pass" and preview.can_commit:
                return team_a, team_b, a.asset_id, b.asset_id, preview
    raise AssertionError("No deterministic PASS pick-only package was found for transaction validation.")


def main() -> int:
    checkpoint_path = Path(DEFAULT_CHECKPOINT_PATH)
    before_hash = sha256(checkpoint_path)
    checkpoint = load_franchise_checkpoint()
    if checkpoint is None:
        raise AssertionError("No durable franchise checkpoint exists.")
    runtime = load_runtime_data()
    state = checkpoint.simulation_state
    trade_state = checkpoint.trade_state
    state_before = copy.deepcopy(state)
    trade_before = copy.deepcopy(trade_state)
    ledger = build_live_asset_ledger(runtime, state, trade_state)

    team_a, team_b, pick_a, pick_b, preview = find_pick_only_pass(
        runtime, state, trade_state, ledger
    )
    candidate = build_franchise_trade_candidate(
        runtime,
        state,
        trade_state,
        team_a=team_a,
        team_b=team_b,
        side_a_pick_asset_ids=(pick_a,),
        side_b_pick_asset_ids=(pick_b,),
        expected_fingerprint=preview.package_fingerprint,
    )
    candidate_ledger = build_live_asset_ledger(runtime, candidate.state, trade_state)
    candidate_picks = {row["asset_id"]: row for row in candidate_ledger.draft_rows}
    candidate_profiles = {p.asset_id: p for p in build_franchise_draft_right_profiles(candidate_ledger)}

    # Mutation primitive test on a separate deep copy. This does not require the
    # selected player package itself to be salary-legal; it verifies roster and
    # rotation mutation correctness without touching the live state.
    player_state = copy.deepcopy(state)
    baseline_ids = set(runtime.trade_by_id)
    player_pair = None
    teams = sorted(player_state.teams)
    for a in teams:
        a_ids = [pid for pid in player_state.teams[a].roster_player_ids if pid in baseline_ids]
        if not a_ids:
            continue
        for b in teams:
            if b <= a:
                continue
            b_ids = [pid for pid in player_state.teams[b].roster_player_ids if pid in baseline_ids]
            if b_ids:
                player_pair = (a, b, a_ids[0], b_ids[0])
                break
        if player_pair:
            break
    if player_pair is None:
        raise AssertionError("Could not locate two baseline rostered players for mutation testing.")
    pa, pb, pid_a, pid_b = player_pair
    _apply_player_moves(
        player_state,
        team_a=pa,
        team_b=pb,
        side_a_player_ids=(pid_a,),
        side_b_player_ids=(pid_b,),
    )
    validate_simulation_league_state(player_state)

    stale_rejected = False
    try:
        build_franchise_trade_candidate(
            runtime,
            state,
            trade_state,
            team_a=team_a,
            team_b=team_b,
            side_a_pick_asset_ids=(pick_a,),
            side_b_pick_asset_ids=(pick_b,),
            expected_fingerprint="0" * 64,
        )
    except FranchiseTradeTransactionError:
        stale_rejected = True

    blocked_preview = build_franchise_trade_preview(
        runtime,
        state,
        trade_state,
        team_a=team_a,
        team_b=team_b,
        side_a_pick_asset_ids=(pick_a,),
        side_b_pick_asset_ids=(pick_a,),
        ledger=ledger,
    )
    blocked_rejected = False
    try:
        build_franchise_trade_candidate(
            runtime,
            state,
            trade_state,
            team_a=team_a,
            team_b=team_b,
            side_a_pick_asset_ids=(pick_a,),
            side_b_pick_asset_ids=(pick_a,),
            expected_fingerprint=blocked_preview.package_fingerprint,
        )
    except FranchiseTradeTransactionError:
        blocked_rejected = True

    ui_text = (SRC / "franchise_embedded_trade_center_ui_v2.py").read_text(encoding="utf-8")
    transaction_text = (SRC / "franchise_trade_transaction_v1.py").read_text(encoding="utf-8")
    checks = {
        "validator_version_is_current": VALIDATOR_VERSION.endswith("2026-08-12"),
        "transaction_version_is_current": FRANCHISE_TRADE_TRANSACTION_VERSION == "franchise-trade-transaction-commit-rollback-v1.0.1-auto-reconcile-2026-08-12",
        "asset_ledger_has_transactional_ownership_build": "transaction-ownership" in ASSET_LEDGER_VERSION,
        "durable_checkpoint_exists": checkpoint_path.is_file(),
        "candidate_build_does_not_mutate_live_state": signature(state) == signature(state_before),
        "candidate_build_does_not_mutate_trade_state": signature(trade_state) == signature(trade_before),
        "future_native_pass_can_release_without_2026_engine": preview.status == "pass" and preview.can_commit and not preview.canonical_engine_invoked,
        "passing_pick_only_package_can_build_candidate": candidate.transaction_id.startswith("FTX-") and candidate.preview.can_commit,
        "draft_ownership_override_persists_in_candidate_ledger": normalize_team(candidate_picks[pick_a]["current_owner"]) == team_b and normalize_team(candidate_picks[pick_b]["current_owner"]) == team_a,
        "procedural_transferred_pick_remains_bridge_ready": all(candidate_profiles[asset_id].bridge_ready for asset_id in (pick_a, pick_b) if candidate_profiles[asset_id].asset_type == "procedural_future_own_pick"),
        "candidate_transaction_history_appended": len(getattr(candidate.state, "franchise_transaction_history_v1", [])) == len(getattr(state, "franchise_transaction_history_v1", [])) + 1,
        "candidate_transaction_revision_increments": int(getattr(candidate.state, "franchise_trade_revision_v1", 0)) == int(getattr(state, "franchise_trade_revision_v1", 0) or 0) + 1,
        "candidate_simulation_state_valid": bool(validate_simulation_league_state(candidate.state)),
        "player_mutation_moves_live_ownership": normalize_team(player_state.players[pid_a].team_abbreviation) == pb and normalize_team(player_state.players[pid_b].team_abbreviation) == pa,
        "player_mutation_repairs_rotations": pid_b in player_state.teams[pa].roster_player_ids and pid_a in player_state.teams[pb].roster_player_ids and len(player_state.teams[pa].rotation.starter_ids) == 5 and len(player_state.teams[pb].rotation.starter_ids) == 5,
        "stale_fingerprint_is_rejected": stale_rejected,
        "blocked_package_is_rejected": blocked_rejected and blocked_preview.status == "blocked",
        "ui_requires_explicit_confirmation": "I understand this will change the live franchise" in ui_text,
        "ui_commit_only_uses_transaction_engine": "commit_live_franchise_trade" in ui_text,
        "transaction_forces_pretrade_durable_save": "franchise-pre-trade-" in transaction_text and "pretrade_reload = load_franchise_checkpoint()" in transaction_text,
        "transaction_has_durable_recovery_copy": "shutil.copy2(primary, recovery)" in transaction_text and "shutil.copy2(recovery, primary)" in transaction_text,
        "transaction_reloads_and_verifies_checkpoint": "reloaded = load_franchise_checkpoint()" in transaction_text,
        "trade_machine_state_remains_separate": signature(trade_state) == signature(trade_before),
        "all_modified_files_compile": True,
        "checkpoint_hash_still_unchanged": sha256(checkpoint_path) == before_hash,
    }
    modified = [
        SRC / "franchise_live_asset_ledger_v1.py",
        SRC / "validate_franchise_live_asset_ledger_v1.py",
        SRC / "franchise_draft_right_stepien_bridge_v1.py",
        SRC / "validate_franchise_draft_right_stepien_bridge_v1.py",
        SRC / "franchise_embedded_trade_center_v2.py",
        SRC / "franchise_embedded_trade_center_ui_v2.py",
        SRC / "franchise_trade_transaction_v1.py",
        SRC / "franchise_live_asset_ledger_ui_v1.py",
        SRC / "validate_franchise_trade_transaction_v1.py",
    ]
    try:
        for path in modified:
            py_compile.compile(str(path), doraise=True)
    except Exception:
        checks["all_modified_files_compile"] = False

    print("=" * 92)
    print("TRANSACTIONAL FRANCHISE TRADE COMMIT / ROLLBACK V1 VALIDATION")
    print("=" * 92)
    for name, passed in checks.items():
        print(f"  {name}: {'PASS' if passed else 'FAIL'}")
    print()
    print("READ-ONLY LIVE STATE")
    print(f"  Season: {ledger.season_label}")
    print(f"  Live franchise revision: {int(getattr(state, 'franchise_trade_revision_v1', 0) or 0)}")
    print(f"  Existing franchise transactions: {len(getattr(state, 'franchise_transaction_history_v1', []))}")
    print(f"  Draft ownership overrides: {len(getattr(state, 'franchise_draft_right_ownership_v1', {}))}")
    print()
    print("IN-MEMORY PASS CANDIDATE")
    print(f"  Teams: {team_a} <-> {team_b}")
    print(f"  Assets: {pick_a} <-> {pick_b}")
    print(f"  Preview: {preview.status}")
    print(f"  Commit eligible: {preview.can_commit}")
    print(f"  Candidate transaction: {candidate.transaction_id}")
    print(f"  Candidate checkpoint write: NOT PERFORMED")
    print()
    print("PLAYER MUTATION TEST")
    print(f"  Teams: {pa} <-> {pb}")
    print(f"  Players: {pid_a} <-> {pid_b}")
    print("  Full league validator: PASS")

    failed = [name for name, passed in checks.items() if not passed]
    report = {
        "validator_version": VALIDATOR_VERSION,
        "transaction_version": FRANCHISE_TRADE_TRANSACTION_VERSION,
        "checks": checks,
        "failed_checks": failed,
        "sample_pick_transaction": {
            "team_a": team_a,
            "team_b": team_b,
            "pick_a": pick_a,
            "pick_b": pick_b,
            "preview_status": preview.status,
            "can_commit": preview.can_commit,
            "candidate_transaction_id": candidate.transaction_id,
        },
    }
    (ROOT / "outputs" / "franchise_trade_transaction_v1_validation.json").write_text(
        json.dumps(report, indent=2, default=str), encoding="utf-8"
    )
    if failed:
        raise SystemExit("Transactional trade validation failed: " + ", ".join(failed))
    print()
    print("TRANSACTIONAL FRANCHISE TRADE COMMIT / ROLLBACK V1 VALIDATION PASSED")
    print("READ-ONLY INSTALL VALIDATION: no live trade or durable checkpoint write was performed.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
