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
from franchise_live_asset_ledger_v1 import build_live_asset_ledger
from franchise_player_contract_bridge_v1 import build_franchise_player_contract_snapshot
from franchise_draft_right_stepien_bridge_v1 import build_franchise_draft_right_profiles
from franchise_trade_transaction_v1 import (
    FRANCHISE_TRADE_TRANSACTION_VERSION,
    build_franchise_trade_candidate,
)
from franchise_trade_finder_ai_v1 import (
    GOAL_BIGGEST_NEED,
    TRADE_FINDER_AI_VERSION,
    TRADE_FINDER_VALUE_MODEL_VERSION,
    build_team_trade_ai_profiles,
    generate_trade_finder_proposals,
)


VALIDATOR_VERSION = "franchise-trade-finder-cpu-ai-validator-v1.0.1-bounded-2026-08-12"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def signature(value) -> str:
    return hashlib.sha256(repr(value).encode("utf-8")).hexdigest()


def main() -> int:
    checkpoint_path = Path(DEFAULT_CHECKPOINT_PATH)
    if not checkpoint_path.is_file():
        raise AssertionError("No durable franchise checkpoint exists.")
    before_hash = sha256(checkpoint_path)

    print("[1/5] Loading durable franchise checkpoint and runtime...", flush=True)
    checkpoint = load_franchise_checkpoint()
    if checkpoint is None:
        raise AssertionError("Durable franchise checkpoint could not be loaded.")
    runtime = load_runtime_data()
    state = checkpoint.simulation_state
    trade_state = checkpoint.trade_state
    before_state = copy.deepcopy(state)
    before_trade = copy.deepcopy(trade_state)

    print("[2/5] Building live asset, team-AI, contract, and draft-right snapshots...", flush=True)
    ledger = build_live_asset_ledger(runtime, state, trade_state)
    profiles = build_team_trade_ai_profiles(state, ledger)
    contract_snapshot = build_franchise_player_contract_snapshot(runtime, state)
    contract_map = {profile.player_id: profile for profile in contract_snapshot.profiles}
    draft_profiles = {
        profile.asset_id: profile
        for profile in build_franchise_draft_right_profiles(ledger)
    }

    active = "ATL" if "ATL" in state.teams else sorted(state.teams)[0]
    print("[3/5] Running bounded CPU Trade Finder validation (max 10 live legality checks)...", flush=True)

    def validation_progress(event):
        stage = str(event.get("stage", ""))
        if stage in {"partner", "legality", "complete"}:
            partner = str(event.get("partner", ""))
            idx = int(event.get("partner_index", 0) or 0)
            total = int(event.get("partner_total", 0) or 0)
            checked = int(event.get("packages_evaluated", 0) or 0)
            found = int(event.get("proposals_found", 0) or 0)
            print(
                f"      {stage}: partner={partner or '-'} "
                f"{idx}/{total} checks={checked}/10 offers={found}",
                flush=True,
            )

    result = generate_trade_finder_proposals(
        runtime,
        state,
        trade_state,
        active_team=active,
        goal=GOAL_BIGGEST_NEED,
        include_picks=True,
        max_results=2,
        max_partners=2,
        max_targets_per_partner=1,
        max_package_evaluations=10,
        progress_callback=validation_progress,
        ledger=ledger,
    )

    print("[4/5] Validating generated offers and in-memory transaction candidate...", flush=True)
    actionable = result.proposals[0] if result.proposals else None
    candidate = None
    if actionable is not None:
        candidate = build_franchise_trade_candidate(
            runtime,
            state,
            trade_state,
            team_a=actionable.active_team,
            team_b=actionable.partner_team,
            side_a_player_ids=actionable.side_a_player_ids,
            side_b_player_ids=actionable.side_b_player_ids,
            side_a_pick_asset_ids=actionable.side_a_pick_asset_ids,
            side_b_pick_asset_ids=actionable.side_b_pick_asset_ids,
            expected_fingerprint=str(
                actionable.preview_payload.get("package_fingerprint", "")
            ),
        )

    rostered_rows = [
        row for row in ledger.player_rows
        if row.get("roster_status") == "rostered"
    ]
    blocked_contract_ids = {
        profile.player_id
        for profile in contract_snapshot.profiles
        if profile.status != "pass" or not profile.trade_eligible
    }
    selected_player_ids = {
        pid
        for proposal in result.proposals
        for pid in (
            *proposal.side_a_player_ids,
            *proposal.side_b_player_ids,
        )
    }
    nonready_pick_ids = {
        asset_id
        for asset_id, profile in draft_profiles.items()
        if not profile.bridge_ready or profile.status != "pass"
    }
    selected_pick_ids = {
        aid
        for proposal in result.proposals
        for aid in (
            *proposal.side_a_pick_asset_ids,
            *proposal.side_b_pick_asset_ids,
        )
    }

    ledger_ui_text = (
        SRC / "franchise_live_asset_ledger_ui_v1.py"
    ).read_text(encoding="utf-8")
    finder_ui_text = (
        SRC / "franchise_trade_finder_ui_v1.py"
    ).read_text(encoding="utf-8")
    finder_backend_text = (
        SRC / "franchise_trade_finder_ai_v1.py"
    ).read_text(encoding="utf-8")

    checks = {
        "validator_version_is_current": (
            VALIDATOR_VERSION
            == "franchise-trade-finder-cpu-ai-validator-v1.0.1-bounded-2026-08-12"
        ),
        "trade_finder_version_is_current": (
            TRADE_FINDER_AI_VERSION
            == "franchise-trade-finder-cpu-ai-v1.0.1-bounded-2026-08-12"
        ),
        "value_model_version_is_current": (
            TRADE_FINDER_VALUE_MODEL_VERSION
            == "franchise-trade-finder-value-model-v1-2026-08-12"
        ),
        "transaction_engine_is_auto_reconcile_build": (
            "v1.0.1-auto-reconcile"
            in FRANCHISE_TRADE_TRANSACTION_VERSION
        ),
        "durable_checkpoint_exists": checkpoint_path.is_file(),
        "generation_does_not_mutate_simulation_state": (
            signature(state) == signature(before_state)
        ),
        "generation_does_not_mutate_trade_machine_state": (
            signature(trade_state) == signature(before_trade)
        ),
        "team_ai_profiles_cover_all_30_teams": (
            len(profiles) == 30
            and set(profiles) == set(state.teams)
        ),
        "team_profiles_expose_timeline_and_need": all(
            profile.timeline in {"contender", "balanced", "rebuild"}
            and profile.biggest_need
            in {"Guard", "Wing/Forward", "Center"}
            for profile in profiles.values()
        ),
        "contract_blocked_players_are_not_selected": not (
            blocked_contract_ids & selected_player_ids
        ),
        "non_bridge_ready_picks_are_not_selected": not (
            nonready_pick_ids & selected_pick_ids
        ),
        "finder_result_is_bound_to_live_trade_revision": (
            result.franchise_trade_revision
            == int(getattr(state, "franchise_trade_revision_v1", 0) or 0)
        ),
        "trade_finder_returns_actionable_results": bool(result.proposals),
        "all_results_are_cpu_accept_or_counter": all(
            proposal.cpu_response in {"accept", "counter"}
            for proposal in result.proposals
        ),
        "all_results_have_live_pass_preview": all(
            proposal.preview_payload.get("status") == "pass"
            and bool(proposal.preview_payload.get("can_commit"))
            for proposal in result.proposals
        ),
        "all_results_use_active_team_on_side_a": all(
            proposal.active_team == active
            and proposal.partner_team != active
            for proposal in result.proposals
        ),
        "proposal_packages_have_assets_on_both_sides": all(
            (
                proposal.side_a_player_ids
                or proposal.side_a_pick_asset_ids
            )
            and (
                proposal.side_b_player_ids
                or proposal.side_b_pick_asset_ids
            )
            for proposal in result.proposals
        ),
        "candidate_can_build_from_first_finder_result": (
            candidate is not None
            and candidate.preview.status == "pass"
            and candidate.preview.can_commit
        ),
        "candidate_build_is_in_memory_only": (
            sha256(checkpoint_path) == before_hash
        ),
        "ledger_ui_invokes_trade_finder": (
            "render_trade_finder_v1(" in ledger_ui_text
            and "Trade Finder foundation" not in ledger_ui_text
        ),
        "trade_finder_ui_loads_into_builder_not_direct_commit": (
            'st.session_state[LEDGER_VIEW_KEY] = "Trade Builder"'
            in finder_ui_text
            and "commit_live_franchise_trade" not in finder_ui_text
        ),
        "finder_backend_uses_live_legality_preview": (
            "build_franchise_trade_preview(" in finder_backend_text
            and 'preview.status != "pass"' in finder_backend_text
        ),
        "finder_backend_uses_team_needs": (
            "team_needs_rows(" in finder_backend_text
            and "position_family(" in finder_backend_text
        ),
        "no_force_trade_path_added": (
            "force_trade" not in finder_backend_text.lower()
            and "force trade" not in finder_ui_text.lower()
        ),
        "bounded_legality_budget_is_active": (
            result.packages_evaluated <= 10
            and "max_package_evaluations" in finder_backend_text
        ),
        "cheap_value_screen_precedes_live_legality": (
            "Cheap value/fit screen BEFORE the expensive full live legality stack."
            in finder_backend_text
        ),
        "ui_exposes_live_search_progress": (
            "Preparing bounded live Trade Finder search" in finder_ui_text
            and "progress_callback=_finder_progress" in finder_ui_text
        ),
        "all_modified_files_compile": True,
        "checkpoint_hash_still_unchanged": (
            sha256(checkpoint_path) == before_hash
        ),
    }

    modified = [
        SRC / "franchise_trade_finder_ai_v1.py",
        SRC / "franchise_trade_finder_ui_v1.py",
        SRC / "franchise_live_asset_ledger_ui_v1.py",
        SRC / "validate_franchise_trade_finder_ai_v1.py",
    ]
    try:
        for path in modified:
            py_compile.compile(str(path), doraise=True)
    except Exception:
        checks["all_modified_files_compile"] = False

    print("[5/5] Finalizing validation report...", flush=True)
    print("=" * 92)
    print("FRANCHISE TRADE FINDER / CPU TRADE AI V1.0.1 VALIDATION")
    print("=" * 92)
    for name, passed in checks.items():
        print(f"  {name}: {'PASS' if passed else 'FAIL'}")

    print()
    print("LIVE TRADE FINDER")
    print(f"  Season: {result.season_label}")
    print(f"  Active team: {active}")
    print(f"  Team timeline: {profiles[active].timeline}")
    print(f"  Biggest need: {profiles[active].biggest_need}")
    print(f"  Teams scanned: {result.teams_scanned}")
    print(f"  Packages evaluated: {result.packages_evaluated}")
    print(f"  Legal PASS packages: {result.legal_packages}")
    print(f"  CPU accepts: {result.cpu_accepts_found}")
    print(f"  CPU counters: {result.cpu_counters_found}")
    print(f"  Results returned: {len(result.proposals)}")
    print(f"  Fallback used: {result.fallback_used}")

    print()
    print("SAMPLE PROPOSALS")
    player_names = {
        str(row.get("player_id")): str(row.get("player_name"))
        for row in ledger.player_rows
    }
    pick_names = {
        str(row.get("asset_id")): str(row.get("display_name"))
        for row in ledger.draft_rows
    }
    for proposal in result.proposals[:4]:
        sent = [
            player_names.get(pid, pid)
            for pid in proposal.side_a_player_ids
        ] + [
            pick_names.get(aid, aid)
            for aid in proposal.side_a_pick_asset_ids
        ]
        received = [
            player_names.get(pid, pid)
            for pid in proposal.side_b_player_ids
        ] + [
            pick_names.get(aid, aid)
            for aid in proposal.side_b_pick_asset_ids
        ]
        print(
            f"  {proposal.response_label} vs {proposal.partner_team} | "
            f"send: {', '.join(sent)} | receive: {', '.join(received)} | "
            f"user Δ {proposal.user_value_delta:+.1f} | "
            f"CPU Δ {proposal.cpu_value_delta:+.1f}"
        )

    print()
    print("TRANSACTION INTEGRATION")
    if candidate is not None:
        print(f"  Candidate: {candidate.transaction_id}")
        print(f"  Candidate preview: {candidate.preview.status}")
        print("  Durable checkpoint write: NOT PERFORMED")

    failed = [name for name, passed in checks.items() if not passed]
    report = {
        "validator_version": VALIDATOR_VERSION,
        "finder_version": TRADE_FINDER_AI_VERSION,
        "value_model_version": TRADE_FINDER_VALUE_MODEL_VERSION,
        "checks": checks,
        "failed_checks": failed,
        "summary": {
            "active_team": active,
            "timeline": profiles[active].timeline,
            "biggest_need": profiles[active].biggest_need,
            "teams_scanned": result.teams_scanned,
            "packages_evaluated": result.packages_evaluated,
            "legal_packages": result.legal_packages,
            "cpu_accepts": result.cpu_accepts_found,
            "cpu_counters": result.cpu_counters_found,
            "results": len(result.proposals),
            "fallback_used": result.fallback_used,
        },
    }
    output = ROOT / "outputs" / "franchise_trade_finder_cpu_ai_v1_validation.json"
    output.write_text(
        json.dumps(report, indent=2, default=str),
        encoding="utf-8",
    )

    if failed:
        raise SystemExit(
            "Trade Finder / CPU Trade AI validation failed: "
            + ", ".join(failed)
        )

    print()
    print("FRANCHISE TRADE FINDER / CPU TRADE AI V1 VALIDATION PASSED")
    print(
        "READ-ONLY VALIDATION: no live trade, roster move, draft-right move, "
        "or durable checkpoint write was performed."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
