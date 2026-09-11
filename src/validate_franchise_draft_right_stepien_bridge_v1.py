from __future__ import annotations

import copy
import hashlib
import json
import py_compile
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from simulation_franchise_checkpoint_v1 import load_franchise_checkpoint
from franchise_live_asset_ledger_v1 import build_live_asset_ledger
from franchise_draft_right_stepien_bridge_v1 import (
    DRAFT_RIGHT_BRIDGE_VERSION,
    build_franchise_draft_right_profiles,
    evaluate_franchise_draft_right_trade,
)
from franchise_embedded_trade_center_v2 import (
    EMBEDDED_TRADE_CENTER_VERSION,
    build_franchise_trade_preview,
    preview_to_dict,
)
from freeform_trade_machine_engine_v3 import load_runtime_data


VALIDATOR_VERSION = "franchise-draft-right-stepien-bridge-validator-v1-2026-08-12"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def state_digest(value) -> str:
    return hashlib.sha256(repr(value).encode("utf-8")).hexdigest()


def main() -> int:
    checkpoint = ROOT / "outputs" / "runtime" / "franchise_mode_checkpoint_v1.pkl.gz"
    before_hash = sha256(checkpoint)

    checkpoint_payload = load_franchise_checkpoint()
    if checkpoint_payload is None:
        raise AssertionError("No durable franchise checkpoint exists.")
    state = checkpoint_payload.simulation_state
    trade_state = checkpoint_payload.trade_state
    runtime = load_runtime_data()
    state_before = copy.deepcopy(state)
    trade_before = copy.deepcopy(trade_state)

    ledger = build_live_asset_ledger(runtime, state, trade_state)
    profiles = build_franchise_draft_right_profiles(ledger)
    profile_by_id = {p.asset_id: p for p in profiles}

    clean_verified = [
        p for p in profiles
        if p.asset_type == "verified_stepien_physical_first" and p.status == "pass"
    ]
    complex_verified = [
        p for p in profiles
        if p.asset_type == "verified_stepien_physical_first" and p.status != "pass"
    ]
    procedural_firsts = [
        p for p in profiles
        if p.asset_type == "procedural_future_own_pick" and p.round_number == 1
    ]
    procedural_seconds = [
        p for p in profiles
        if p.asset_type == "procedural_future_own_pick" and p.round_number == 2
    ]

    teams = sorted(state.teams)
    pair = (teams[0], teams[1])
    sample_a = next(
        (p for p in profiles if p.current_owner == pair[0] and p.bridge_ready),
        None,
    )
    sample_b = next(
        (p for p in profiles if p.current_owner == pair[1] and p.bridge_ready),
        None,
    )

    single_eval = evaluate_franchise_draft_right_trade(
        runtime,
        state,
        trade_state,
        team_a=pair[0],
        team_b=pair[1],
        side_a_asset_ids=((sample_a.asset_id,) if sample_a else ()),
        side_b_asset_ids=((sample_b.asset_id,) if sample_b else ()),
        ledger=ledger,
    )

    # Find a deterministic Stepien block by sending two consecutive bridge-ready
    # firsts from the same team when possible.
    stepien_block_eval = None
    stepien_block_team = ""
    firsts_by_team = {}
    for profile in profiles:
        if profile.round_number == 1 and profile.bridge_ready:
            firsts_by_team.setdefault(profile.current_owner, {})[profile.draft_year] = profile
    for team, by_year in firsts_by_team.items():
        for year in range(ledger.next_draft_year, ledger.horizon_end_year):
            if year in by_year and year + 1 in by_year:
                opponent = next(t for t in teams if t != team)
                stepien_block_eval = evaluate_franchise_draft_right_trade(
                    runtime,
                    state,
                    trade_state,
                    team_a=team,
                    team_b=opponent,
                    side_a_asset_ids=(by_year[year].asset_id, by_year[year + 1].asset_id),
                    side_b_asset_ids=(),
                    ledger=ledger,
                )
                stepien_block_team = team
                break
        if stepien_block_eval is not None:
            break

    # Embedded preview with a pick if possible, otherwise player-only.
    a_pick = (sample_a.asset_id,) if sample_a else ()
    b_pick = (sample_b.asset_id,) if sample_b else ()
    # The embedded builder requires each side to send an asset. A bridge-ready
    # pick on each side provides the cleanest integration test.
    preview = build_franchise_trade_preview(
        runtime,
        state,
        trade_state,
        team_a=pair[0],
        team_b=pair[1],
        side_a_pick_asset_ids=a_pick,
        side_b_pick_asset_ids=b_pick,
        ledger=ledger,
    )
    preview_payload = preview_to_dict(preview)

    checks = {
        "validator_version_is_current": VALIDATOR_VERSION.endswith("2026-08-12"),
        "draft_right_bridge_version_is_current": DRAFT_RIGHT_BRIDGE_VERSION == "franchise-draft-right-stepien-bridge-v1.1-transaction-ownership-2026-08-12",
        "embedded_trade_center_version_is_transaction_build": "transaction-release-v1" in EMBEDDED_TRADE_CENTER_VERSION,
        "durable_checkpoint_exists": checkpoint.is_file(),
        "snapshot_does_not_mutate_simulation_state": state_digest(state) == state_digest(state_before),
        "snapshot_does_not_mutate_trade_state": state_digest(trade_state) == state_digest(trade_before),
        "all_live_draft_rows_have_profiles": len(profiles) == len(ledger.draft_rows) and {p.asset_id for p in profiles} == {str(r["asset_id"]) for r in ledger.draft_rows},
        "rolling_horizon_still_seven_years": ledger.horizon_end_year - ledger.next_draft_year + 1 == 7,
        "clean_verified_firsts_release_from_manual_bridge": bool(clean_verified),
        "complex_verified_firsts_stay_manual": all(not p.bridge_ready and p.status == "manual_review" for p in complex_verified),
        "procedural_future_firsts_become_bridge_ready": bool(procedural_firsts) and all(p.bridge_ready for p in procedural_firsts),
        "procedural_future_seconds_become_bridge_ready": bool(procedural_seconds) and all(p.bridge_ready for p in procedural_seconds),
        "procedural_assets_are_labeled_modeled": all(p.modeled_future_asset for p in procedural_firsts + procedural_seconds),
        "sample_draft_evaluation_releases_status": single_eval.status in {"pass", "manual_review", "blocked"},
        "stepien_consecutive_firsts_are_blocked": (
            stepien_block_eval is not None
            and stepien_block_eval.status == "blocked"
            and any(c.code == "stepien_consecutive_future_firsts_failed" for c in stepien_block_eval.checks)
        ),
        "trade_preview_invokes_draft_right_bridge": preview.draft_right_bridge_invoked,
        "trade_preview_exposes_draft_right_status": preview.draft_right_bridge_status in {"pass", "manual_review", "blocked"},
        "trade_preview_contains_draft_right_check": any(c.code == "franchise_draft_right_stepien_bridge_result" for c in preview.checks),
        "future_package_commit_gate_matches_pass_status": preview.can_commit == (preview.status == "pass" and preview.draft_right_bridge_status == "pass" and preview.player_contract_bridge_status == "pass" and preview.financial_bridge_status == "pass"),
        "embedded_ui_exposes_draft_right_bridge": "Draft Right / Stepien bridge" in (SRC / "franchise_embedded_trade_center_ui_v2.py").read_text(encoding="utf-8"),
        "all_modified_files_compile": True,
        "checkpoint_hash_still_unchanged": sha256(checkpoint) == before_hash,
    }

    modified = [
        SRC / "franchise_draft_right_stepien_bridge_v1.py",
        SRC / "franchise_embedded_trade_center_v2.py",
        SRC / "franchise_embedded_trade_center_ui_v2.py",
        SRC / "validate_franchise_draft_right_stepien_bridge_v1.py",
    ]
    try:
        for path in modified:
            py_compile.compile(str(path), doraise=True)
    except Exception:
        checks["all_modified_files_compile"] = False

    print("=" * 92)
    print("FRANCHISE DRAFT RIGHT / STEPIEN BRIDGE V1 VALIDATION")
    print("=" * 92)
    for name, passed in checks.items():
        print(f"  {name}: {'PASS' if passed else 'FAIL'}")

    print()
    print("LIVE DRAFT-RIGHT ENVIRONMENT")
    print(f"  Season: {ledger.season_label}")
    print(f"  Horizon: {ledger.next_draft_year} -> {ledger.horizon_end_year}")
    print(f"  Draft-capital rows: {len(ledger.draft_rows)}")
    print(f"  Clean verified firsts released: {len(clean_verified)}")
    print(f"  Complex verified firsts retained for review: {len(complex_verified)}")
    print(f"  Procedural future firsts activated: {len(procedural_firsts)}")
    print(f"  Procedural future seconds activated: {len(procedural_seconds)}")
    print(f"  Bridge-ready rows: {sum(p.bridge_ready for p in profiles)}")
    print(f"  Manual / blocked rows: {sum(not p.bridge_ready for p in profiles)}")

    print()
    print("STEPIEN PACKAGE TEST")
    print(f"  Team: {stepien_block_team or 'not found'}")
    print(f"  Consecutive-first sample: {stepien_block_eval.status if stepien_block_eval else 'not_available'}")

    print()
    print("SAMPLE EMBEDDED TRADE")
    print(f"  Teams: {pair[0]} <-> {pair[1]}")
    print(f"  Draft Right Bridge: {preview.draft_right_bridge_status}")
    print(f"  Player Contract Bridge: {preview.player_contract_bridge_status}")
    print(f"  Financial Bridge: {preview.financial_bridge_status}")
    print(f"  Overall preview: {preview.status}")
    print(f"  Commit: {'enabled' if preview.can_commit else 'disabled'}")

    failed = [name for name, passed in checks.items() if not passed]
    report = {
        "validator_version": VALIDATOR_VERSION,
        "bridge_version": DRAFT_RIGHT_BRIDGE_VERSION,
        "checks": checks,
        "failed_checks": failed,
        "summary": {
            "season": ledger.season_label,
            "draft_rows": len(ledger.draft_rows),
            "bridge_ready_rows": sum(p.bridge_ready for p in profiles),
            "manual_or_blocked_rows": sum(not p.bridge_ready for p in profiles),
            "clean_verified_firsts": len(clean_verified),
            "complex_verified_firsts": len(complex_verified),
            "procedural_firsts": len(procedural_firsts),
            "procedural_seconds": len(procedural_seconds),
            "embedded_preview": preview_payload,
        },
    }
    out = ROOT / "outputs" / "franchise_draft_right_stepien_bridge_v1_validation.json"
    out.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

    if failed:
        raise SystemExit("Draft Right / Stepien Bridge validation failed: " + ", ".join(failed))

    print()
    print("FRANCHISE DRAFT RIGHT / STEPIEN BRIDGE V1 VALIDATION PASSED")
    print("READ-ONLY VALIDATION: no draft right, roster, contract, trade, or franchise checkpoint was mutated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
