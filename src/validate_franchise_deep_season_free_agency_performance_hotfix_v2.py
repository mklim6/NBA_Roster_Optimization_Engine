from __future__ import annotations

import inspect
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import franchise_free_agency_cpu_execution_v1 as execution
import franchise_free_agency_cpu_offer_generation_v1 as generation
import franchise_free_agency_transaction_v1 as transaction
import simulation_franchise_checkpoint_v1 as checkpoint

VALIDATOR_VERSION = "franchise-deep-season-free-agency-performance-hotfix-v2-validator-2026-09-11"
EXPECTED_PERFORMANCE_VERSION = "franchise-free-agency-deep-season-performance-v3-floor-first-2026-09-17"
EXPECTED_DEFER_VERSION = "franchise-free-agency-deferred-preview-fingerprint-v1-2026-09-11"


def _deferred_preview_checks() -> dict[str, bool]:
    @dataclass
    class Contract:
        status: str
        salary: float | None
        years_remaining: int | None = None
        option_type: str = ""
        guaranteed: bool | None = None

    @dataclass
    class Player:
        player_id: str
        player_name: str
        team_abbreviation: str
        roster_status: str
        two_way: bool
        contract: Contract

    @dataclass
    class Rotation:
        starter_ids: tuple[str, ...]
        rotation_player_ids: tuple[str, ...]
        minutes_targets: dict[str, float]

    @dataclass
    class Team:
        roster_player_ids: tuple[str, ...]
        active_player_ids: tuple[str, ...]
        inactive_player_ids: tuple[str, ...]
        rotation: Rotation

    @dataclass
    class Settings:
        season_label: str = "2034-35"

    @dataclass
    class State:
        state_version: str = "v2-validator"
        source_league_state_revision: int = 1
        source_transaction_count: int = 0
        transition_count: int = 8
        franchise_transaction_revision: int = 0
        phase: str = "offseason"
        settings: Settings = field(default_factory=Settings)
        players: dict[str, Player] = field(default_factory=dict)
        teams: dict[str, Team] = field(default_factory=dict)
        free_agent_player_ids: tuple[str, ...] = ("FA1",)

    roster = tuple(f"P{i}" for i in range(1, 9))
    rotation = Rotation(
        starter_ids=roster[:5],
        rotation_player_ids=roster,
        minutes_targets={player_id: 24.0 for player_id in roster},
    )
    state = State(
        players={
            "FA1": Player(
                player_id="FA1",
                player_name="Validator Free Agent",
                team_abbreviation="",
                roster_status="free_agent",
                two_way=False,
                contract=Contract(status="free_agent_pool", salary=None),
            )
        },
        teams={
            "CHI": Team(
                roster_player_ids=roster,
                active_player_ids=roster,
                inactive_player_ids=(),
                rotation=rotation,
            )
        },
    )

    def validator(candidate: State) -> None:
        assert "FA1" not in candidate.free_agent_player_ids
        assert "FA1" in candidate.teams["CHI"].roster_player_ids

    def pass_gate(_state: Any, _offer: transaction.FreeAgencyOffer) -> dict[str, Any]:
        return {"status": "pass", "reason": "v2-validator"}

    offer = transaction.FreeAgencyOffer(
        player_id="FA1",
        team_abbreviation="CHI",
        annual_salary=3_000_000,
        years=1,
    )
    full = transaction.build_free_agency_preview(
        state,
        offer,
        financial_gate=pass_gate,
        state_validator=validator,
    )
    deferred = transaction.build_free_agency_preview(
        state,
        offer,
        financial_gate=pass_gate,
        state_validator=validator,
        _source_fingerprint=full.source_fingerprint,
        _defer_candidate_fingerprint=True,
    )
    return {
        "full_preview_passes": full.can_commit and full.status == "pass",
        "full_preview_has_candidate_fingerprint": bool(full.candidate_fingerprint),
        "deferred_preview_passes_same_legality": deferred.can_commit and deferred.status == full.status,
        "deferred_preview_preserves_source_fingerprint": deferred.source_fingerprint == full.source_fingerprint,
        "deferred_preview_intentionally_omits_candidate_fingerprint": deferred.candidate_fingerprint == "",
        "deferred_preview_preserves_normalized_offer": deferred.offer == full.offer,
    }


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    execution_source = (root / "src" / "franchise_free_agency_cpu_execution_v1.py").read_text(encoding="utf-8")
    checkpoint_source = (root / "src" / "simulation_franchise_checkpoint_v1.py").read_text(encoding="utf-8")

    checkpoint_report = checkpoint.run_self_test()
    transaction_self_test_passed = transaction.run_self_test() == 0
    deferred = _deferred_preview_checks()
    generation_report = generation.generation_contract_report()
    execution_report = execution.cpu_execution_contract_report()
    save_signature = inspect.signature(checkpoint.save_franchise_checkpoint)

    checks = {
        "performance_version_is_v2": execution.CPU_FREE_AGENCY_DEEP_SEASON_PERFORMANCE_VERSION == EXPECTED_PERFORMANCE_VERSION,
        "deferred_preview_version_is_current": transaction.FREE_AGENCY_DEFERRED_PREVIEW_FINGERPRINT_VERSION == EXPECTED_DEFER_VERSION,
        "offer_generation_reports_deferred_speculative_fingerprints": generation_report.get("speculative_candidate_fingerprint_deferred") is True,
        "execution_reports_carried_byte_verified_checkpoint": execution_report.get("round_carries_byte_verified_checkpoint") is True,
        "execution_reports_final_semantic_reload": execution_report.get("round_final_semantic_reload_required") is True,
        "execution_reports_roster_floor_early_stop": execution_report.get("round_stops_when_roster_floor_complete") is True,
        "checkpoint_save_has_private_byte_verification_gate": "_verify_encoded_bytes_only" in save_signature.parameters,
        "checkpoint_has_current_graph_scan": callable(getattr(checkpoint, "runtime_graph_is_current", None)),
        "checkpoint_hot_reload_self_test_passes": bool(checkpoint_report.get("passed")),
        "checkpoint_stale_hot_reload_rebind_still_passes": bool(checkpoint_report.get("checks", {}).get("stale_hot_reload_class_is_rebound")),
        "transaction_self_test_passes": transaction_self_test_passed,
        "round_source_uses_byte_verified_carry_forward": "_verify_bytes_only=True" in execution_source,
        "roster_floor_rescue_precedes_full_market_plan": (
            execution_source.index("rescue = build_cpu_roster_floor_rescue_opportunity(", execution_source.index("def execute_next_cpu_free_agency_signing_durably("))
            < execution_source.index("plan = build_cpu_free_agency_execution_plan(", execution_source.index("def execute_next_cpu_free_agency_signing_durably("))
        ),
        "round_source_releases_mature_graph_before_final_reload": "checkpoint = None" in execution_source and "gc.collect()" in execution_source,
        "checkpoint_source_skips_rebind_only_after_identity_scan": "if not runtime_graph_is_current(payload_object):" in checkpoint_source,
        **deferred,
    }
    failed = [name for name, passed in checks.items() if not passed]
    report = {
        "version": VALIDATOR_VERSION,
        "checks": checks,
        "failed_checks": failed,
        "passed": not failed,
    }
    print(json.dumps(report, indent=2))
    if failed:
        print("\nFRANCHISE DEEP-SEASON FREE AGENCY PERFORMANCE HOTFIX V2 FAILED")
        return 1
    print("\nFRANCHISE DEEP-SEASON FREE AGENCY PERFORMANCE HOTFIX V2 PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
