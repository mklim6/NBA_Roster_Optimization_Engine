from __future__ import annotations

import hashlib
import json
import py_compile
import sys
from pathlib import Path
from typing import Any

try:
    import cloudpickle as _serializer
except ImportError:  # pragma: no cover
    import pickle as _serializer

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
OUTPUTS = ROOT / "outputs"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from freeform_trade_machine_engine_v3 import load_runtime_data, normalize_player_id, normalize_team
from franchise_live_asset_ledger_v1 import (
    ASSET_LEDGER_VERSION,
    DRAFT_HORIZON_YEARS,
    build_live_asset_ledger,
)
from franchise_draft_forfeitures_v1 import DRAFT_PICK_FORFEITURES
from simulation_franchise_checkpoint_v1 import load_franchise_checkpoint


VALIDATOR_VERSION = (
    "franchise-live-asset-ledger-validator-v1.2-pick-forfeitures-2026-09-07"
)
REPORT_PATH = OUTPUTS / "franchise_live_asset_ledger_v1_validation.json"


def digest_object(value: Any) -> str:
    return hashlib.sha256(_serializer.dumps(value)).hexdigest()


def sha256(path: Path) -> str:
    if not path.is_file():
        return ""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    checkpoint_path = ROOT / "outputs" / "runtime" / "franchise_mode_checkpoint_v1.pkl.gz"
    checkpoint_hash_before = sha256(checkpoint_path)
    checkpoint = load_franchise_checkpoint()
    if checkpoint is None:
        raise AssertionError("No durable franchise checkpoint exists.")

    state = checkpoint.simulation_state
    trade_state = checkpoint.trade_state
    runtime = load_runtime_data()
    state_before = digest_object(state)
    trade_before = digest_object(trade_state)

    ledger = build_live_asset_ledger(runtime, state, trade_state)

    state_after = digest_object(state)
    trade_after = digest_object(trade_state)
    live_ids = {normalize_player_id(player_id) for player_id in state.players}
    ledger_ids = {row["player_id"] for row in ledger.player_rows}
    free_agents = {normalize_player_id(x) for x in state.free_agent_player_ids}
    ledger_free_agents = {row["player_id"] for row in ledger.player_rows if row["roster_status"] == "free_agent"}
    generated = [row for row in ledger.player_rows if row["generated_player"]]
    canonical = [row for row in ledger.draft_rows if row["asset_type"] == "canonical_trade_right"]
    verified = [row for row in ledger.draft_rows if row["asset_type"] == "verified_stepien_physical_first"]
    procedural = [row for row in ledger.draft_rows if row["asset_type"] == "procedural_future_own_pick"]
    forfeited = [row for row in ledger.draft_rows if row["asset_type"] == "forfeited_draft_pick"]
    complex_rows = [row for row in verified if "Complex right" in row["tradability_status"]]
    clean_bridge = [row for row in verified if row["tradability_status"] == "Verified · Bridge Needed"]
    years = sorted({int(row["draft_year"]) for row in ledger.draft_rows})

    stepien_owner_lookup = {}
    if hasattr(runtime, "stepien") and not runtime.stepien.empty:
        for record in runtime.stepien.to_dict(orient="records"):
            source = str(record.get("own_first_round_source_asset_id") or "").strip()
            if source:
                stepien_owner_lookup[source] = normalize_team(record.get("own_first_round_current_owner_team"))
    ownership_overrides = getattr(
        state, "franchise_draft_right_ownership_v1", {}
    ) or {}
    verified_owner_matches = all(
        normalize_team(ownership_overrides.get(
            row["asset_id"],
            stepien_owner_lookup.get(row["asset_id"], row["current_owner"]),
        )) == row["current_owner"]
        for row in verified
    )

    page = ROOT / "pages" / "5_Franchise_Mode.py"
    backend = ROOT / "src" / "franchise_live_asset_ledger_v1.py"
    ui = ROOT / "src" / "franchise_live_asset_ledger_ui_v1.py"
    trade_war_room = ROOT / "src" / "franchise_trade_war_room_v1.py"
    page_text = page.read_text(encoding="utf-8") if page.is_file() else ""
    trade_war_room_text = (
        trade_war_room.read_text(encoding="utf-8")
        if trade_war_room.is_file()
        else ""
    )
    compile_results = {}
    forfeiture_backend = ROOT / "src" / "franchise_draft_forfeitures_v1.py"
    for path in (
        page,
        backend,
        ui,
        trade_war_room,
        forfeiture_backend,
        Path(__file__),
    ):
        try:
            py_compile.compile(str(path), doraise=True)
            compile_results[str(path.relative_to(ROOT))] = ""
        except Exception as exc:
            compile_results[str(path.relative_to(ROOT))] = str(exc)

    checks = {
        "validator_version_is_current": VALIDATOR_VERSION.endswith("2026-09-07"),
        "ledger_version_is_current": ledger.version == ASSET_LEDGER_VERSION,
        "durable_checkpoint_exists": bool(checkpoint_hash_before),
        "ledger_build_does_not_mutate_simulation_state": state_before == state_after,
        "ledger_build_does_not_mutate_trade_state": trade_before == trade_after,
        "player_ledger_exactly_covers_live_players": ledger_ids == live_ids and len(ledger.player_rows) == len(live_ids),
        "free_agent_status_matches_live_state": ledger_free_agents == free_agents,
        "rostered_team_ownership_matches_live_simulation_state": all(
            row["team"] == normalize_team(state.players[row["player_id"]].team_abbreviation)
            for row in ledger.player_rows
            if row["roster_status"] == "rostered"
        ),
        "generated_players_are_not_dropped": all(row["player_id"] in live_ids for row in generated),
        "contract_fields_exposed_for_every_player": all("contract_status" in row and "salary" in row and "years_remaining" in row for row in ledger.player_rows),
        "career_status_exposed_for_every_player": all(bool(row.get("career_status")) for row in ledger.player_rows),
        "draft_horizon_is_seven_years": years == list(range(ledger.next_draft_year, ledger.horizon_end_year + 1)) and len(years) == DRAFT_HORIZON_YEARS,
        "no_canonical_right_is_entirely_in_the_past": all(int(row["draft_year"]) >= ledger.next_draft_year for row in canonical),
        "verified_stepien_first_owners_match_calendar": verified_owner_matches,
        "clean_stepien_firsts_are_not_falsely_engine_ready": all((not row["engine_ready"]) and row["manual_review_required"] for row in clean_bridge),
        "complex_stepien_rights_require_manual_review": all(row["manual_review_required"] and not row["engine_ready"] for row in complex_rows),
        "procedural_future_assets_are_manual_and_not_engine_ready": all(row["manual_review_required"] and not row["engine_ready"] for row in procedural),
        "all_five_clippers_forfeitures_are_auditable": (
            {row["forfeited_source_asset_id"] for row in forfeited}
            == {item.source_asset_id for item in DRAFT_PICK_FORFEITURES}
        ),
        "forfeited_picks_have_no_owner_or_trade_path": all(
            not row["current_owner"]
            and not row["engine_ready"]
            and row["tradability_status"] == "Forfeited · NBA Sanction"
            for row in forfeited
        ),
        "separate_2029_lac_phi_swap_right_is_preserved": any(
            row.get("forfeiture_status") == "active"
            and "2029_R1_LAC" in str(row.get("source_assets") or "")
            and "2029_R1_PHI" in str(row.get("source_assets") or "")
            for row in ledger.draft_rows
        ),
        "page_wires_live_asset_ledger_ui": (
            "render_live_asset_ledger(" in page_text
            or (
                "render_franchise_trade_war_room_v1(" in page_text
                and "render_live_asset_ledger(" in trade_war_room_text
            )
        ),
        "all_modified_files_compile": not any(compile_results.values()),
        "checkpoint_hash_still_unchanged": sha256(checkpoint_path) == checkpoint_hash_before,
    }
    failed = [name for name, passed in checks.items() if not passed]
    report = {
        "script": VALIDATOR_VERSION,
        "ledger_version": ledger.version,
        "checks": checks,
        "failed_checks": failed,
        "summary": {
            "season": ledger.season_label,
            "live_players": len(ledger.player_rows),
            "generated_or_drafted_players": len(generated),
            "free_agents": len(ledger_free_agents),
            "next_draft_year": ledger.next_draft_year,
            "horizon_end_year": ledger.horizon_end_year,
            "draft_rows": len(ledger.draft_rows),
            "canonical_right_rows": len(canonical),
            "verified_stepien_first_rows": len(verified),
            "clean_bridge_first_rows": len(clean_bridge),
            "complex_stepien_rows": len(complex_rows),
            "procedural_future_rows": len(procedural),
            "forfeited_pick_rows": len(forfeited),
            "engine_ready_pick_rows": ledger.engine_ready_pick_count,
            "manual_review_pick_rows": ledger.draft_manual_review_count,
        },
        "compile_results": compile_results,
        "checkpoint_sha256": checkpoint_hash_before,
        "passed": not failed,
    }
    OUTPUTS.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print("=" * 92)
    print("FRANCHISE LIVE ASSET LEDGER V1 VALIDATION")
    print("=" * 92)
    for name, passed in checks.items():
        print(f"  {name}: {'PASS' if passed else 'FAIL'}")
    summary = report["summary"]
    print()
    print("LIVE PLAYER LEDGER")
    print(f"  Season: {summary['season']}")
    print(f"  Players: {summary['live_players']}")
    print(f"  Generated / drafted: {summary['generated_or_drafted_players']}")
    print(f"  Free agents: {summary['free_agents']}")
    print()
    print("ROLLING DRAFT CAPITAL")
    print(f"  Horizon: {summary['next_draft_year']} -> {summary['horizon_end_year']}")
    print(f"  Rows: {summary['draft_rows']}")
    print(f"  Canonical engine rights: {summary['canonical_right_rows']}")
    print(f"  Verified Stepien physical firsts: {summary['verified_stepien_first_rows']}")
    print(f"  Procedural future placeholders: {summary['procedural_future_rows']}")
    print(f"  Forfeited picks (audit only): {summary['forfeited_pick_rows']}")
    print(f"  Engine-ready rows: {summary['engine_ready_pick_rows']}")
    print(f"  Manual / bridge rows: {summary['manual_review_pick_rows']}")
    if failed:
        raise AssertionError("Live asset ledger validation failed: " + ", ".join(failed))
    print()
    print("FRANCHISE LIVE ASSET LEDGER V1 VALIDATION PASSED")
    print("READ-ONLY VALIDATION: durable franchise checkpoint was not modified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
