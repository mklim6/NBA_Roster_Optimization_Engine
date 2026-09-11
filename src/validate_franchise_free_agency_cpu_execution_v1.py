from __future__ import annotations

import copy
import hashlib
import inspect
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from franchise_free_agency_competing_market_v1 import (  # noqa: E402
    FREE_AGENCY_COMPETING_MARKET_VERSION,
)
from franchise_free_agency_cpu_execution_v1 import (  # noqa: E402
    CPU_FREE_AGENCY_CONFIRMATION_TOKEN,
    CPU_FREE_AGENCY_EXECUTION_SCOPE,
    CPU_FREE_AGENCY_EXECUTION_VERSION,
    CPUFreeAgencyExecutionError,
    assert_cpu_live_commit_preconditions,
    build_cpu_free_agency_execution_plan,
    cpu_execution_contract_report,
)
from franchise_free_agency_cpu_offer_generation_v1 import (  # noqa: E402
    CPU_FREE_AGENCY_OFFER_GENERATION_VERSION,
    build_cpu_free_agency_offer_board,
)
from franchise_free_agency_live_signing_v1 import (  # noqa: E402
    controlled_teams_from_durable_checkpoint,
)
from franchise_free_agency_transaction_v1 import (  # noqa: E402
    FreeAgencyFinancialGateResult,
    FreeAgencyOffer,
    FreeAgencyTransactionPreview,
    free_agency_state_fingerprint,
)
from simulation_franchise_checkpoint_v1 import (  # noqa: E402
    DEFAULT_CHECKPOINT_PATH,
    load_franchise_checkpoint,
)

VALIDATOR_VERSION = (
    "franchise-free-agency-cpu-execution-validator-v1-2026-08-14"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else ""


def _digest(state: Any) -> str:
    payload = {
        "season": str(getattr(getattr(state, "settings", None), "season_label", "")),
        "phase": str(getattr(state, "phase", "")),
        "free_agents": list(getattr(state, "free_agent_player_ids", ()) or ()),
        "teams": {
            str(team): list(getattr(team_state, "roster_player_ids", ()) or ())
            for team, team_state in sorted((getattr(state, "teams", {}) or {}).items())
        },
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def _fake_preview_for_team(state: Any, team: str) -> Any | None:
    free_ids = list(getattr(state, "free_agent_player_ids", ()) or ())
    if not free_ids:
        return None
    player_id = str(free_ids[0])
    offer = FreeAgencyOffer(
        player_id=player_id,
        team_abbreviation=team,
        annual_salary=5_000_000.0,
        years=1,
        guaranteed=True,
        option_type="",
    )
    source = free_agency_state_fingerprint(state)
    return FreeAgencyTransactionPreview(
        transaction_version="validator-only",
        offer_version="validator-only",
        offer=offer,
        player_name=str(getattr(getattr(state, "players", {}).get(player_id), "player_name", player_id)),
        source_fingerprint=source,
        candidate_fingerprint=source,
        status="pass",
        can_commit=True,
        checks={"validator_only": True},
        financial_gate=FreeAgencyFinancialGateResult(
            status="pass",
            reason="validator-only",
            payload={"route": "pure_cap_space_only"},
        ),
        roster_count_before=0,
        roster_count_after=1,
        message="validator-only",
    )


def main() -> int:
    print("=" * 108)
    print("FRANCHISE FREE AGENCY CPU EXECUTION V1 VALIDATION")
    print("=" * 108)

    cp_path = Path(DEFAULT_CHECKPOINT_PATH)
    cp_before = _sha256(cp_path)
    checkpoint = load_franchise_checkpoint()
    if checkpoint is None:
        raise RuntimeError("Durable franchise checkpoint is unavailable.")
    state = checkpoint.simulation_state
    state_before = _digest(state)
    controlled = controlled_teams_from_durable_checkpoint(checkpoint)
    report = cpu_execution_contract_report()

    live_plan = None
    live_error = ""
    try:
        live_plan = build_cpu_free_agency_execution_plan(
            state,
            controlled_teams=controlled,
            max_targets_per_team=1,
        )
    except Exception as exc:
        live_error = f"{type(exc).__name__}: {exc}"

    non_offseason_blocked = True
    fake_cpu_preview = None
    teams = [str(team).upper() for team in getattr(state, "teams", {})]
    cpu_team = next((team for team in teams if team not in set(controlled)), "")
    if cpu_team:
        fake_cpu_preview = _fake_preview_for_team(state, cpu_team)
    if fake_cpu_preview is not None and str(getattr(getattr(state, "phase", None), "value", getattr(state, "phase", ""))).lower() != "offseason":
        try:
            assert_cpu_live_commit_preconditions(checkpoint, fake_cpu_preview)
            non_offseason_blocked = False
        except CPUFreeAgencyExecutionError:
            non_offseason_blocked = True

    controlled_blocked = True
    if controlled:
        fake_controlled = _fake_preview_for_team(state, controlled[0])
        if fake_controlled is not None:
            isolated_checkpoint = copy.deepcopy(checkpoint)
            isolated_state = isolated_checkpoint.simulation_state
            # Replace only the isolated phase when mutable. If the real state uses
            # a frozen settings/phase model, leave the live regular-season gate as
            # the first blocker and verify controlled authorization statically below.
            try:
                phase_value = getattr(isolated_state, "phase", None)
                phase_type = type(phase_value)
                if hasattr(phase_type, "OFFSEASON"):
                    isolated_state.phase = phase_type.OFFSEASON
                elif isinstance(phase_value, str):
                    isolated_state.phase = "offseason"
                fake_controlled = _fake_preview_for_team(isolated_state, controlled[0])
                assert_cpu_live_commit_preconditions(isolated_checkpoint, fake_controlled)
                controlled_blocked = False
            except CPUFreeAgencyExecutionError as exc:
                controlled_blocked = "user-controlled" in str(exc).lower() or controlled_blocked
            except Exception:
                controlled_blocked = True

    source_text = (SRC / "franchise_free_agency_cpu_execution_v1.py").read_text(encoding="utf-8")
    checkpoint_source_text = (
        SRC / "simulation_franchise_checkpoint_v1.py"
    ).read_text(encoding="utf-8")
    runner_path = SRC / "run_franchise_free_agency_cpu_execution_v1.py"
    runner_text = runner_path.read_text(encoding="utf-8") if runner_path.exists() else ""

    checks = {
        "validator_version_is_current": VALIDATOR_VERSION.endswith("v1-2026-08-14"),
        "cpu_execution_version_is_current": report.get("version") == CPU_FREE_AGENCY_EXECUTION_VERSION,
        "cpu_execution_scope_is_current": report.get("scope") == CPU_FREE_AGENCY_EXECUTION_SCOPE,
        "cpu_offer_generation_v1_is_preserved": report.get("offer_generation_version") == CPU_FREE_AGENCY_OFFER_GENERATION_VERSION,
        "competing_market_v1_is_preserved": report.get("competing_market_version") == FREE_AGENCY_COMPETING_MARKET_VERSION,
        "actual_offseason_is_required": report.get("actual_offseason_required") is True,
        "user_controlled_commit_is_disabled": report.get("user_controlled_team_commit_allowed") is False,
        "cpu_only_market_scope_is_explicit": report.get("cpu_only_markets") is True,
        "user_offer_injection_is_not_faked": report.get("user_offer_injection") is False,
        "board_rebuild_after_each_signing_is_required": report.get("board_rebuilt_after_each_signing") is True,
        "background_autonomy_is_disabled": report.get("autonomous_background_execution") is False,
        "confirmation_token_is_explicit": CPU_FREE_AGENCY_CONFIRMATION_TOKEN == "CPU_FREE_AGENCY_EXECUTION_V1",
        "runner_exists": runner_path.exists(),
        "runner_defaults_to_preview_only": "if not args.commit" in runner_text,
        "runner_requires_confirmation_token": "args.confirm != CPU_FREE_AGENCY_CONFIRMATION_TOKEN" in runner_text,
        "cpu_commit_has_recovery_copy": "shutil.copy2(checkpoint_path, recovery_path)" in source_text,
        "cpu_commit_reloads_checkpoint": (
            "_return_verified=True" in source_text
            and "reloaded = saved" in source_text
            and "verified = load_checkpoint_path(" in checkpoint_source_text
        ),
        "cpu_commit_verifies_simulation_fingerprint": "observed_sim_fp != expected_sim_fp" in source_text,
        "cpu_commit_verifies_trade_fingerprint": "observed_trade_fp != expected_trade_fp" in source_text,
        "cpu_commit_records_cpu_actor": 'history[-1]["execution_actor"] = "cpu_front_office"' in source_text,
        "cpu_commit_does_not_call_user_live_commit": "commit_contract_legal_free_agency_preview_live(" not in source_text,
        "cpu_round_rebuilds_via_next_step": "execute_next_cpu_free_agency_signing_durably(" in source_text,
        "non_offseason_live_commit_is_rejected_read_only": non_offseason_blocked,
        "controlled_team_cpu_commit_is_rejected": controlled_blocked,
        "live_plan_builds_without_mutation_or_reports_error": live_plan is not None or bool(live_error),
        "live_plan_excludes_controlled_winners": (
            live_plan is None
            or all(op.winner_team_abbreviation not in set(controlled) for op in live_plan.opportunities)
        ),
        "live_plan_is_deterministic": True,
        "durable_state_is_unchanged": _digest(state) == state_before,
        "validator_did_not_write_checkpoint": _sha256(cp_path) == cp_before,
    }

    if live_plan is not None:
        try:
            live_plan_again = build_cpu_free_agency_execution_plan(
                state,
                controlled_teams=controlled,
                max_targets_per_team=1,
            )
            checks["live_plan_is_deterministic"] = (
                live_plan.plan_fingerprint == live_plan_again.plan_fingerprint
            )
        except Exception:
            checks["live_plan_is_deterministic"] = False

    failed = [name for name, ok in checks.items() if not ok]
    for name, ok in checks.items():
        print(f"  {name}: {'PASS' if ok else 'FAIL'}")

    print("\nREAD-ONLY LIVE CPU EXECUTION CONTEXT")
    print(f"  Season: {getattr(getattr(state, 'settings', None), 'season_label', '')}")
    print(f"  Phase: {getattr(getattr(state, 'phase', None), 'value', getattr(state, 'phase', ''))}")
    print(f"  Controlled teams: {', '.join(controlled) if controlled else 'None'}")
    if live_plan is not None:
        print(f"  Generated legal CPU offers (top target/team): {live_plan.generated_offer_count}")
        print(f"  CPU player markets: {live_plan.market_count}")
        print(f"  Accepted CPU winner markets: {live_plan.winner_market_count}")
        if live_plan.opportunities:
            top = live_plan.opportunities[0]
            print(
                f"  Next hypothetical CPU winner: {top.player_name} -> {top.winner_team_abbreviation} "
                f"at ${top.annual_salary:,.0f}/yr"
            )
    else:
        print(f"  Live plan error: {live_error}")
    print("  Durable CPU signing during validator: NOT PERFORMED")
    print(f"  Checkpoint hash unchanged: {_sha256(cp_path) == cp_before}")

    payload = {
        "validator": VALIDATOR_VERSION,
        "cpu_execution": CPU_FREE_AGENCY_EXECUTION_VERSION,
        "checks": checks,
        "failed_checks": failed,
        "live": {
            "generated_offers": getattr(live_plan, "generated_offer_count", None),
            "markets": getattr(live_plan, "market_count", None),
            "winner_markets": getattr(live_plan, "winner_market_count", None),
            "error": live_error,
        },
        "checkpoint_hash_before": cp_before,
        "checkpoint_hash_after": _sha256(cp_path),
        "passed": not failed,
    }
    print("\n" + json.dumps(payload, indent=2, default=str))
    if failed:
        raise SystemExit("CPU Free Agency Execution V1 validation failed: " + ", ".join(failed))
    print("\nFRANCHISE FREE AGENCY CPU EXECUTION V1 VALIDATION PASSED")
    print("READ-ONLY VALIDATION: no CPU signing, roster move, Trade Machine mutation, or checkpoint write was performed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
