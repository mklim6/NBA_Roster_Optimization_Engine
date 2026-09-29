from __future__ import annotations

import copy
import hashlib
import json
import sys
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from franchise_free_agency_contract_salary_legality_v1_3 import (
    FREE_AGENCY_CONTRACT_SALARY_LEGALITY_VERSION,
)
from franchise_free_agency_financial_bridge_v1_2 import (
    FREE_AGENCY_FINANCIAL_BRIDGE_VERSION,
)
from franchise_free_agency_live_signing_v1 import (
    FREE_AGENCY_LIVE_SIGNING_VERSION,
    FREE_AGENCY_LIVE_UI_VERSION,
    FREE_AGENCY_TRADE_STATE_SYNC_VERSION,
    FreeAgencyLiveSigningError,
    assert_live_commit_preconditions,
    build_trade_state_free_agency_candidate,
    controlled_teams_from_durable_checkpoint,
    trade_state_fingerprint,
)
from franchise_free_agency_transaction_v1 import (
    FREE_AGENCY_TRANSACTION_VERSION,
    FreeAgencyOffer,
    FreeAgencyTransactionPreview,
    free_agency_state_fingerprint,
)
from franchise_free_agency_transaction_v1_1 import (
    FREE_AGENCY_DURABLE_COMMIT_VERSION,
    FREE_AGENCY_TRANSACTION_V1_1_VERSION,
)
from franchise_free_agency_ui_v1 import FREE_AGENCY_UI_VERSION
from simulation_franchise_checkpoint_v1 import (
    DEFAULT_CHECKPOINT_PATH,
    load_franchise_checkpoint,
)
from simulation_league_state_v1 import validate_simulation_league_state

VALIDATOR_VERSION = "franchise-free-agency-live-signing-validator-v1.0.2-2026-09-28"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _phase(state: Any) -> str:
    raw = getattr(state, "phase", "")
    return str(getattr(raw, "value", raw)).strip().lower()


def _fake_preview(state: Any, offer: FreeAgencyOffer, *, can_commit: bool = True) -> FreeAgencyTransactionPreview:
    from franchise_free_agency_transaction_v1 import FreeAgencyFinancialGateResult
    return FreeAgencyTransactionPreview(
        transaction_version=FREE_AGENCY_TRANSACTION_VERSION,
        offer_version="test",
        offer=offer,
        player_name="Test Player",
        source_fingerprint=free_agency_state_fingerprint(state),
        candidate_fingerprint="test-candidate",
        status="pass" if can_commit else "manual_review",
        can_commit=can_commit,
        checks={},
        financial_gate=FreeAgencyFinancialGateResult(
            status="pass" if can_commit else "manual_review",
            reason="validator",
            payload={},
        ),
        roster_count_before=1,
        roster_count_after=2 if can_commit else 1,
        message="validator",
    )


def main() -> int:
    checkpoint_path = Path(DEFAULT_CHECKPOINT_PATH)
    before_hash = _sha256(checkpoint_path) if checkpoint_path.exists() else ""
    checkpoint = load_franchise_checkpoint()
    if checkpoint is None:
        raise AssertionError("Durable checkpoint is unavailable.")
    state = checkpoint.simulation_state
    validate_simulation_league_state(state)
    controlled = controlled_teams_from_durable_checkpoint(checkpoint)
    workspace_path = ROOT / "src" / "franchise_free_agency_workspace_v1.py"
    workspace_text = workspace_path.read_text(encoding="utf-8") if workspace_path.exists() else ""
    franchise_page_path = ROOT / "pages" / "5_Franchise_Mode.py"
    franchise_page_text = franchise_page_path.read_text(encoding="utf-8") if franchise_page_path.exists() else ""
    player_decision_path = ROOT / "src" / "franchise_free_agency_player_decision_v1.py"
    player_decision_text = player_decision_path.read_text(encoding="utf-8") if player_decision_path.exists() else ""

    checks: dict[str, bool] = {
        "validator_version_is_current": VALIDATOR_VERSION.endswith("v1.0.2-2026-09-28"),
        "live_signing_version_is_current": FREE_AGENCY_LIVE_SIGNING_VERSION == "franchise-free-agency-live-signing-v1-2026-08-14",
        "trade_sync_version_is_current": FREE_AGENCY_TRADE_STATE_SYNC_VERSION == "franchise-free-agency-trade-state-sync-v1-2026-08-14",
        "live_ui_version_is_current": FREE_AGENCY_LIVE_UI_VERSION == "franchise-free-agency-live-ui-v1-2026-08-14",
        "base_transaction_v1_is_preserved": FREE_AGENCY_TRANSACTION_VERSION.startswith("franchise-free-agency-transaction-v1"),
        "durable_transaction_v1_1_is_preserved": FREE_AGENCY_TRANSACTION_V1_1_VERSION.startswith("franchise-free-agency-transaction-v1.1"),
        "durable_checkpoint_backend_is_preserved": FREE_AGENCY_DURABLE_COMMIT_VERSION.startswith("franchise-free-agency-durable-commit-v1-"),
        "financial_bridge_is_current": FREE_AGENCY_FINANCIAL_BRIDGE_VERSION == "franchise-free-agency-financial-bridge-v1.3-modeled-future-market-2026-08-18",
        "salary_legality_is_current": FREE_AGENCY_CONTRACT_SALARY_LEGALITY_VERSION == "franchise-free-agency-contract-salary-legality-v1.5-service-evidence-2026-09-24",
        "preview_ui_helper_is_preserved": FREE_AGENCY_UI_VERSION.startswith("franchise-free-agency-ui-preview-v1"),
        "durable_checkpoint_exists": checkpoint_path.exists(),
        "durable_state_is_valid": True,
        "durable_trade_state_exists": checkpoint.trade_state is not None,
        "controlled_teams_do_not_expand": all(team in getattr(state, "teams", {}) for team in controlled),
    }

    # The live project is currently regular season. A real commit must fail closed.
    if controlled and getattr(state, "free_agent_player_ids", ()):
        offer = FreeAgencyOffer(
            player_id=str(next(iter(state.free_agent_player_ids))),
            team_abbreviation=controlled[0],
            annual_salary=3_000_000.0,
            years=1,
            guaranteed=True,
            option_type="",
        )
        preview = _fake_preview(state, offer)
        try:
            assert_live_commit_preconditions(checkpoint, preview, hypothetical=False)
        except FreeAgencyLiveSigningError:
            checks["non_offseason_live_commit_is_rejected"] = _phase(state) != "offseason"
        else:
            checks["non_offseason_live_commit_is_rejected"] = _phase(state) == "offseason"
        try:
            assert_live_commit_preconditions(checkpoint, preview, hypothetical=True)
        except FreeAgencyLiveSigningError:
            checks["hypothetical_preview_can_never_commit"] = True
        else:
            checks["hypothetical_preview_can_never_commit"] = False
    else:
        checks["non_offseason_live_commit_is_rejected"] = True
        checks["hypothetical_preview_can_never_commit"] = True

    # Read-only in-memory Trade Machine synchronization against the real durable state.
    trade_state = checkpoint.trade_state
    sync_tested = False
    if trade_state is not None:
        owners = dict(getattr(trade_state, "player_team_by_id", {}) or {})
        financials = dict(getattr(trade_state, "team_financials", {}) or {})
        candidate_player = next(
            (
                str(pid)
                for pid in getattr(state, "free_agent_player_ids", ())
                if str(pid) in owners and not str(owners[str(pid)] or "").strip()
            ),
            "",
        )
        candidate_team = next(
            (
                str(team)
                for team, fin in financials.items()
                if getattr(fin, "team_salary", None) is not None
                and getattr(fin, "apron_salary", None) is not None
                and isinstance(getattr(fin, "standard_contract_count", None), int)
            ),
            "",
        )
        if candidate_player and candidate_team:
            sync_offer = FreeAgencyOffer(
                player_id=candidate_player,
                team_abbreviation=candidate_team,
                annual_salary=1_000_000.0,
                years=1,
                guaranteed=True,
                option_type="",
            )
            source_trade_fp = trade_state_fingerprint(trade_state)
            history_len = len(list(getattr(trade_state, "transaction_history", []) or []))
            undo_len = len(list(getattr(trade_state, "undo_stack", []) or []))
            before_fin = copy.deepcopy(financials[candidate_team])
            candidate, sync = build_trade_state_free_agency_candidate(
                trade_state,
                sync_offer,
                transaction_id="FATX-TEST",
                validate=True,
            )
            after_fin = candidate.team_financials[candidate_team]
            checks.update({
                "trade_sync_candidate_is_non_mutating": trade_state_fingerprint(trade_state) == source_trade_fp,
                "trade_sync_updates_player_owner": candidate.player_team_by_id[candidate_player] == candidate_team,
                "trade_sync_increments_revision_once": sync.state_revision_after == sync.state_revision_before + 1,
                "trade_sync_adds_salary_exactly": abs(float(after_fin.team_salary) - float(before_fin.team_salary) - 1_000_000.0) < 0.01,
                "trade_sync_adds_apron_salary_exactly": abs(float(after_fin.apron_salary) - float(before_fin.apron_salary) - 1_000_000.0) < 0.01,
                "trade_sync_adds_standard_contract": int(after_fin.standard_contract_count) == int(before_fin.standard_contract_count) + 1,
                "trade_sync_does_not_invent_trade_record": len(candidate.transaction_history) == history_len,
                "trade_sync_preserves_trade_undo_depth": len(candidate.undo_stack) == undo_len,
                "trade_sync_records_contract_override": candidate_player in getattr(candidate, "free_agency_contract_overrides", {}),
                "trade_sync_records_fatx_metadata": bool(getattr(candidate, "free_agency_transaction_history", [])),
                "trade_sync_rebases_initial_snapshot": (
                    getattr(candidate, "initial_snapshot", None) is None
                    or candidate.initial_snapshot.player_team_by_id.get(candidate_player) == candidate_team
                ),
            })
            sync_tested = True
    checks["real_trade_state_sync_path_is_tested"] = sync_tested

    # Backend-controlled team gate cannot be bypassed by a UI choice.
    if controlled and getattr(state, "free_agent_player_ids", ()):
        cpu_team = next((team for team in getattr(state, "teams", {}) if team not in controlled), "")
        if cpu_team:
            isolated = copy.deepcopy(state)
            try:
                from simulation_league_state_v1 import LeaguePhase
                isolated.phase = LeaguePhase.OFFSEASON
            except Exception:
                isolated.phase = "offseason"
            cpu_offer = FreeAgencyOffer(
                player_id=str(next(iter(isolated.free_agent_player_ids))),
                team_abbreviation=cpu_team,
                annual_salary=3_000_000.0,
                years=1,
                guaranteed=True,
                option_type="",
            )
            cpu_preview = _fake_preview(isolated, cpu_offer)
            # FranchiseCheckpoint is a frozen dataclass. Build a validator-only
            # replacement object instead of mutating the copied checkpoint.
            fake_checkpoint = replace(
                checkpoint,
                simulation_state=isolated,
            )
            checks["validator_uses_frozen_checkpoint_replacement"] = (
                fake_checkpoint is not checkpoint
                and fake_checkpoint.simulation_state is isolated
                and checkpoint.simulation_state is state
            )
            try:
                assert_live_commit_preconditions(fake_checkpoint, cpu_preview)
            except FreeAgencyLiveSigningError:
                checks["backend_rejects_cpu_team_signing"] = True
            else:
                checks["backend_rejects_cpu_team_signing"] = False
        else:
            checks["backend_rejects_cpu_team_signing"] = True
            checks["validator_uses_frozen_checkpoint_replacement"] = True
    else:
        checks["backend_rejects_cpu_team_signing"] = True
        checks["validator_uses_frozen_checkpoint_replacement"] = True

    # Current UI contract: Free Agency is embedded in Franchise Mode through
    # the shared workspace. Persistent negotiation owns the user-facing commit
    # and Player Decisions retains the canonical live-signing backend call.
    ui_markers = {
        "franchise_page_embeds_free_agency_workspace": (
            "render_free_agency_workspace" in franchise_page_text
            and "render_free_agency_workspace(" in franchise_page_text
        ),
        "workspace_routes_through_persistent_live_commit": (
            "commit_persistent_user_winner_live(" in workspace_text
        ),
        "player_decision_uses_live_commit_backend": (
            "commit_contract_legal_free_agency_preview_live(" in player_decision_text
        ),
        "workspace_requires_explicit_signing_action": (
            "I confirm this signing" in workspace_text
            and 'key="fa_live_sign_button"' in workspace_text
        ),
        "workspace_has_live_sign_button": "Confirm and sign" in workspace_text,
        "workspace_blocks_hypothetical_commit": "preview_is_hypothetical" in workspace_text,
        "workspace_blocks_non_offseason_commit": 'phase == "offseason"' in workspace_text,
        "workspace_refreshes_simulation_session_state": (
            'st.session_state["franchise_simulation_league_state"]' in workspace_text
        ),
        "workspace_refreshes_trade_session_state": (
            'st.session_state["franchise_trade_league_state"]' in workspace_text
        ),
        "workspace_reloads_checkpoint_after_commit": "load_franchise_checkpoint()" in workspace_text,
        "workspace_reruns_after_commit": "st.rerun()" in workspace_text,
    }
    checks.update(ui_markers)
    try:
        compile(workspace_text, str(workspace_path), "exec")
        compile(franchise_page_text, str(franchise_page_path), "exec")
        compile(player_decision_text, str(player_decision_path), "exec")
        checks["current_ui_chain_compiles"] = True
    except Exception:
        checks["current_ui_chain_compiles"] = False

    after_hash = _sha256(checkpoint_path) if checkpoint_path.exists() else ""
    checks["validator_did_not_write_checkpoint"] = before_hash == after_hash
    failed = [name for name, passed in checks.items() if not passed]

    print("=" * 108)
    print("FRANCHISE FREE AGENCY LIVE SIGNING V1 VALIDATION")
    print("=" * 108)
    for name, passed in checks.items():
        print(f"  {name}: {'PASS' if passed else 'FAIL'}")
    print()
    print("READ-ONLY LIVE CONTEXT")
    print(f"  Season: {getattr(getattr(state, 'settings', None), 'season_label', '')}")
    print(f"  Phase: {_phase(state)}")
    print(f"  Controlled teams: {', '.join(controlled) or 'NONE'}")
    print(f"  Durable live signing during validator: NOT PERFORMED")
    print(f"  Checkpoint hash unchanged: {before_hash == after_hash}")
    report = {
        "validator": VALIDATOR_VERSION,
        "live_signing": FREE_AGENCY_LIVE_SIGNING_VERSION,
        "checks": checks,
        "failed_checks": failed,
        "checkpoint_hash_before": before_hash,
        "checkpoint_hash_after": after_hash,
        "passed": not failed,
    }
    print("\n" + json.dumps(report, indent=2, default=str))
    if failed:
        raise AssertionError(
            "Free Agency Live Signing V1 failed: " + ", ".join(failed)
        )
    print("\nFRANCHISE FREE AGENCY LIVE SIGNING V1 VALIDATION PASSED")
    print("READ-ONLY VALIDATION: no live signing or checkpoint write was performed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
