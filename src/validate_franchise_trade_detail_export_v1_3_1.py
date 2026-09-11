from __future__ import annotations

import hashlib
import py_compile
from pathlib import Path

from freeform_trade_machine_engine_v3 import load_runtime_data
from franchise_live_asset_ledger_v1 import build_live_asset_ledger
from franchise_trade_finder_ai_v1 import (
    GOAL_BEST_AVAILABLE,
    TRADE_FINDER_AI_VERSION,
    TRADE_FINDER_VALUE_MODEL_VERSION,
    generate_trade_finder_proposals,
)
from simulation_franchise_checkpoint_v1 import (
    DEFAULT_CHECKPOINT_PATH,
    load_franchise_checkpoint,
)


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
VALIDATOR_VERSION = "franchise-trade-detail-export-validator-v1.3.1-2026-08-12"


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
    before_state = signature(state)
    ledger = build_live_asset_ledger(runtime, state, trade_state)
    active = sorted(getattr(state, "teams", {}))[0]

    print("Running bounded Trade Detail / CSV audit sample...", flush=True)
    result = generate_trade_finder_proposals(
        runtime,
        state,
        trade_state,
        active_team=active,
        goal=GOAL_BEST_AVAILABLE,
        include_picks=True,
        max_results=3,
        max_partners=2,
        max_targets_per_partner=2,
        max_financial_prechecks=120,
        max_package_evaluations=30,
        ledger=ledger,
    )

    rows = list(result.package_audit_rows)
    ui_text = (SRC / "franchise_trade_finder_ui_v1.py").read_text(encoding="utf-8")
    ai_text = (SRC / "franchise_trade_finder_ai_v1.py").read_text(encoding="utf-8")

    required_columns = {
        "route_stage",
        "side_a_player_names",
        "side_b_player_names",
        "user_value_delta",
        "cpu_value_delta",
        "financial_status",
        "full_legality_status",
        "side_a_player_1_age",
        "side_a_player_1_overall",
        "side_a_player_1_potential",
        "side_a_player_1_salary",
        "side_a_player_1_value_to_active",
        "side_a_player_1_value_to_partner",
        "side_b_player_1_age",
        "side_b_player_1_overall",
        "side_b_player_1_potential",
        "side_b_player_1_salary",
        "side_b_player_1_value_to_active",
        "side_b_player_1_value_to_partner",
    }

    checks = {
        "validator_version_is_current": "v1.3.1" in VALIDATOR_VERSION,
        "trade_finder_version_is_package_audit": "v1.3.1-package-audit" in TRADE_FINDER_AI_VERSION,
        "value_model_version_is_audit_context": "v1.3.1-audit-context" in TRADE_FINDER_VALUE_MODEL_VERSION,
        "durable_checkpoint_exists": checkpoint_path.is_file(),
        "generation_does_not_mutate_live_state": signature(state) == before_state,
        "audit_rows_are_generated": len(rows) > 0,
        "audit_rows_cover_constructed_packages": len(rows) >= result.candidate_packages_generated,
        "audit_rows_have_value_and_player_context": (
            bool(rows) and required_columns.issubset(rows[0].keys())
        ),
        "audit_records_multiple_pipeline_stages": len({str(row.get("route_stage")) for row in rows}) >= 2,
        "ui_shows_age_overall_potential_salary": (
            "OVR {overall:.1f} · POT {potential:.1f}" in ui_text
            and "_age(row.get(\"age\"))" in ui_text
            and "_money(row.get(\"salary\"))" in ui_text
        ),
        "ui_downloads_full_package_audit_csv": (
            "Download full package audit CSV" in ui_text
            and "_audit_csv_bytes" in ui_text
            and "text/csv" in ui_text
        ),
        "backend_exposes_individual_player_values": (
            "value_to_active" in ai_text and "value_to_partner" in ai_text
        ),
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
    print("TRADE DETAIL + FULL PACKAGE CSV EXPORT V1.3.1 VALIDATION")
    print("=" * 92)
    for name, passed in checks.items():
        print(f"  {name}: {'PASS' if passed else 'FAIL'}")

    print()
    print("AUDIT SAMPLE")
    print(f"  Active: {active}")
    print(f"  Constructed packages: {result.candidate_packages_generated}")
    print(f"  Audit rows: {len(rows)}")
    print(f"  Financial PASS: {result.financial_precheck_passes}")
    print(f"  Legal PASS: {result.legal_packages}")
    print(f"  CPU offers: {len(result.proposals)}")
    print(f"  Stages captured: {', '.join(sorted({str(row.get('route_stage')) for row in rows}))}")

    if failed:
        raise AssertionError(
            "Trade Detail + CSV Export V1.3.1 failed: " + ", ".join(failed)
        )

    print()
    print("TRADE DETAIL + FULL PACKAGE CSV EXPORT V1.3.1 VALIDATION PASSED")
    print("READ-ONLY VALIDATION: no live trade or checkpoint write was performed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
