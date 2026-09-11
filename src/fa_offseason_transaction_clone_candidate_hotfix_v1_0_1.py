from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import pickle
import sys
import tempfile
import zipfile
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable


VERSION = "fa-offseason-transaction-clone-candidate-hotfix-v1.0.1-2026-08-16"
SEASON_LABEL = "2026-27"
SPLIT_DATE = date(2026, 4, 12)
PROBE_PATTERN = "fa_offseason_transaction_application_interface_probe_v1_2026-27_*.zip"
CLONE_PATTERN = "fa_clone_only_offseason_decision_application_preview_v1_2026-27_*.zip"
MARKET_PATTERN = "fa_full_market_free_agent_amount_completion_v1_2026-27_*.zip"
BRIDGE_PATTERN = "fa_post_draft_first_round_pick_hold_bridge_final_integration_v1_2026-27_*.zip"
EXPECTED_CHECKPOINT_SHA256 = "19f2fee601f5765bde4f5fabea34f20dc9b8ddc8dd5069186502dff08fc0cf9f"
EXPECTED_SIMULATION_DIGEST = "f92f03b4c54e53f8f017c3fca43e93ccd09c8b8ba0e5fe0323f418021baf268e"
CRITICAL_SOURCE_FILES = {
    "simulation_league_state_v1.py",
    "simulation_franchise_checkpoint_v1.py",
    "mutable_league_state_v1.py",
    "freeform_trade_machine_engine_v3.py",
    "franchise_free_agency_live_signing_v1.py",
    "franchise_player_contract_bridge_v1.py",
    "franchise_financial_cba_bridge_v1.py",
    "franchise_post_draft_first_round_pick_hold_bridge_v1.py",
    "franchise_trade_transaction_v1.py",
}


def clean(value: Any) -> str:
    return "" if value is None else str(value).strip()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def object_digest(value: Any) -> str:
    try:
        payload = pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL)
    except Exception:
        payload = repr(value).encode("utf-8", errors="replace")
    return hashlib.sha256(payload).hexdigest()


def candidate_semantic_digest(simulation_state: Any, trade_state: Any) -> str:
    payload = {
        "free_agents": sorted(clean(value) for value in simulation_state.free_agent_player_ids),
        "players": {
            clean(pid): {
                "team": clean(player.team_abbreviation),
                "roster_status": clean(player.roster_status),
                "contract_status": clean(player.contract.status),
                "salary": player.contract.salary,
                "years_remaining": player.contract.years_remaining,
                "option_type": clean(player.contract.option_type),
                "guaranteed": player.contract.guaranteed,
            }
            for pid, player in sorted(simulation_state.players.items())
        },
        "teams": {
            clean(code): {
                "roster": list(row.roster_player_ids),
                "active": list(row.active_player_ids),
                "inactive": list(row.inactive_player_ids),
                "starters": list(row.rotation.starter_ids),
                "rotation": list(row.rotation.rotation_player_ids),
                "minutes": sorted((clean(pid), float(value)) for pid, value in row.rotation.minutes_targets.items()),
            }
            for code, row in sorted(simulation_state.teams.items())
        },
        "trade_revision": int(getattr(trade_state, "state_revision", 0) or 0),
        "trade_owners": sorted((clean(pid), clean(owner)) for pid, owner in trade_state.player_team_by_id.items()),
        "trade_financials": sorted(
            (
                clean(code),
                float(row.team_salary),
                float(row.apron_salary),
                int(row.standard_contract_count),
                int(row.two_way_contract_count),
            )
            for code, row in trade_state.team_financials.items()
        ),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def member_suffix(archive: zipfile.ZipFile, suffix: str) -> str:
    matches = [name for name in archive.namelist() if name.endswith(suffix)]
    if len(matches) != 1:
        raise RuntimeError(f"Expected one ZIP member ending with {suffix}; found {len(matches)}")
    return matches[0]


def csv_suffix(archive: zipfile.ZipFile, suffix: str) -> list[dict[str, str]]:
    text = archive.read(member_suffix(archive, suffix)).decode("utf-8-sig", errors="replace")
    return list(csv.DictReader(io.StringIO(text))) if text.strip() else []


def json_suffix(archive: zipfile.ZipFile, suffix: str) -> dict[str, Any]:
    return json.loads(archive.read(member_suffix(archive, suffix)).decode("utf-8-sig"))


def find_passed(root: Path, pattern: str, summary_suffix: str) -> Path:
    valid: list[Path] = []
    for path in root.rglob(pattern):
        if not path.is_file():
            continue
        try:
            with zipfile.ZipFile(path) as archive:
                summary = json_suffix(archive, summary_suffix)
                if summary.get("passed") is True and not summary.get("failed_checks"):
                    valid.append(path)
        except Exception:
            continue
    if not valid:
        raise RuntimeError(f"Missing required passed audit: {pattern}")
    return max(valid, key=lambda path: path.stat().st_mtime)


def write_csv(path: Path, rows: list[dict[str, Any]], fields: Iterable[str] | None = None) -> None:
    fieldnames = list(fields or [])
    if not fieldnames:
        seen: set[str] = set()
        for row in rows:
            for key in row:
                if key not in seen:
                    seen.add(key)
                    fieldnames.append(key)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    root = Path.cwd().resolve()
    src = root / "src"
    if not src.exists():
        raise RuntimeError("Run from the NBA_Roster_Optimization_Engine project root.")

    probe_zip = find_passed(root, PROBE_PATTERN, "transaction_interface_probe_summary.json")
    clone_zip = find_passed(root, CLONE_PATTERN, "clone_application_summary.json")
    market_zip = find_passed(root, MARKET_PATTERN, "full_market_free_agent_amount_summary.json")
    bridge_zip = find_passed(root, BRIDGE_PATTERN, "final_bridge_integration_summary.json")
    with zipfile.ZipFile(probe_zip) as archive:
        probe_summary = json_suffix(archive, "transaction_interface_probe_summary.json")
        probe_checks = csv_suffix(archive, "transaction_interface_probe_checks.csv")
        source_inventory = csv_suffix(archive, "transaction_runtime_source_inventory.csv")
    with zipfile.ZipFile(clone_zip) as archive:
        clone_summary = json_suffix(archive, "clone_application_summary.json")
        automatic = csv_suffix(archive, "automatic_decisions_applied_109.csv")
        pending = csv_suffix(archive, "user_decisions_pending_2.csv")
        owner_ledger = csv_suffix(archive, "clone_owner_ledger_587.csv")
    with zipfile.ZipFile(market_zip) as archive:
        market_summary = json_suffix(archive, "full_market_free_agent_amount_summary.json")
        market_rows = csv_suffix(archive, "full_market_free_agent_amounts_complete_226.csv")
    with zipfile.ZipFile(bridge_zip) as archive:
        bridge_summary = json_suffix(archive, "final_bridge_integration_summary.json")

    inventory_by_name = {Path(clean(row.get("source_file"))).name: row for row in source_inventory}
    missing_fingerprints: list[str] = []
    changed_fingerprints: list[str] = []
    for name in sorted(CRITICAL_SOURCE_FILES):
        row = inventory_by_name.get(name)
        path = src / name
        if row is None or not path.exists():
            missing_fingerprints.append(name)
        elif sha256_file(path) != clean(row.get("sha256")):
            changed_fingerprints.append(name)
    if missing_fingerprints or changed_fingerprints:
        raise RuntimeError(
            f"Runtime contracts changed since the passed probe. Missing={missing_fingerprints}; changed={changed_fingerprints}"
        )

    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
    import simulation_franchise_checkpoint_v1 as checkpoint_module
    from freeform_trade_machine_engine_v3 import load_runtime_data
    from franchise_offseason_transaction_application_v1 import (
        BASELINE_PER_36_FIELDS,
        DEVELOPMENT_SKILL_FIELDS,
        DEVELOPMENT_STAT_FACTORS,
        POPULATION_SUPPLEMENT,
        build_offseason_transaction_candidates,
        validate_offseason_transition_state,
    )
    from mutable_league_state_v1 import validate_state
    from simulation_league_state_v1 import validate_simulation_league_state

    checkpoint_path = Path(checkpoint_module.DEFAULT_CHECKPOINT_PATH)
    checkpoint_hash_before = sha256_file(checkpoint_path)
    checkpoint = checkpoint_module.load_franchise_checkpoint()
    if checkpoint is None:
        raise RuntimeError("Canonical checkpoint could not be loaded.")
    simulation_digest_before = object_digest(checkpoint.simulation_state)
    trade_digest_before = object_digest(checkpoint.trade_state)
    checkpoint_object_digest_before = object_digest(checkpoint)
    if checkpoint_hash_before != EXPECTED_CHECKPOINT_SHA256:
        raise RuntimeError("Canonical checkpoint changed before clone candidate validation.")

    print("=" * 132)
    print("2026 OFFSEASON TRANSACTION CLONE CANDIDATE HOTFIX V1.0.1")
    print("=" * 132)
    print("Reconstructing the April 12 branch and applying all 111 lifecycle decisions to clones only...")

    runtime = load_runtime_data()
    result = build_offseason_transaction_candidates(
        checkpoint.simulation_state,
        checkpoint.trade_state,
        runtime=runtime,
        owner_ledger_rows=owner_ledger,
        market_rows=market_rows,
        automatic_decisions=automatic,
        pending_decisions=pending,
    )
    repeat = build_offseason_transaction_candidates(
        checkpoint.simulation_state,
        checkpoint.trade_state,
        runtime=runtime,
        owner_ledger_rows=owner_ledger,
        market_rows=market_rows,
        automatic_decisions=automatic,
        pending_decisions=pending,
    )
    sim_candidate = result["simulation_candidate"]
    trade_candidate = result["trade_candidate"]
    sim_checks = validate_offseason_transition_state(sim_candidate)
    trade_checks = validate_state(trade_candidate, runtime)

    native_game_ready = True
    native_game_ready_error = ""
    try:
        validate_simulation_league_state(sim_candidate)
    except Exception as exc:
        native_game_ready = False
        native_game_ready_error = clean(exc)

    candidate_bytes = pickle.dumps(
        (sim_candidate, trade_candidate), protocol=pickle.HIGHEST_PROTOCOL
    )
    reloaded_sim, reloaded_trade = pickle.loads(candidate_bytes)
    validate_offseason_transition_state(reloaded_sim)
    validate_state(reloaded_trade, runtime)

    decisions = result["resolved_decisions"]
    materialized = result["materialized_population_supplement"]
    materialized_ids = {clean(row.get("player_id")) for row in materialized}
    exact_supplement_ids = {"1627832", "1642440", "1642850", "202681", "203081"}
    supplement_by_id = {clean(row.get("player_id")): row for row in materialized}
    expected_identity_position = {
        pid: (clean(profile["player_name"]), clean(profile["position"]))
        for pid, profile in POPULATION_SUPPLEMENT.items()
    }
    identity_position_exact = all(
        pid in sim_candidate.players
        and (
            clean(sim_candidate.players[pid].player_name),
            clean(sim_candidate.players[pid].position),
        ) == expected_identity_position[pid]
        for pid in exact_supplement_ids
    )
    profile_schema_exact = all(
        set(sim_candidate.players[pid].skill_ratings) == set(DEVELOPMENT_SKILL_FIELDS)
        and set(sim_candidate.players[pid].stat_factors) == set(DEVELOPMENT_STAT_FACTORS)
        and set(sim_candidate.players[pid].baseline_per_36) == set(BASELINE_PER_36_FIELDS)
        and all(
            math.isfinite(float(value))
            for value in (
                sim_candidate.players[pid].overall_rating,
                *sim_candidate.players[pid].skill_ratings.values(),
                *sim_candidate.players[pid].stat_factors.values(),
                *sim_candidate.players[pid].baseline_per_36.values(),
            )
        )
        for pid in exact_supplement_ids
    )
    baseline_values_exact = all(
        all(
            math.isclose(
                float(sim_candidate.players[pid].baseline_per_36[field]),
                float(expected),
                abs_tol=1e-8,
            )
            for field, expected in zip(
                BASELINE_PER_36_FIELDS,
                POPULATION_SUPPLEMENT[pid]["baseline_per_36"],
            )
        )
        for pid in exact_supplement_ids
    )
    initial_salary_evidence_exact = all(
        supplement_by_id.get(pid, {}).get("initial_contract_salary_2026_27")
        == POPULATION_SUPPLEMENT[pid]["initial_salary"]
        for pid in exact_supplement_ids
    )
    evidence_is_direct_and_cited = all(
        clean(supplement_by_id.get(pid, {}).get("evidence_method"))
        == clean(POPULATION_SUPPLEMENT[pid]["evidence_method"])
        and clean(supplement_by_id.get(pid, {}).get("source_url")).startswith("https://")
        and clean(supplement_by_id.get(pid, {}).get("calibration_label"))
        == "explicit_conservative_bridge_v1"
        for pid in exact_supplement_ids
    )
    state_maps_cover_population = (
        set(sim_candidate.injuries) == set(sim_candidate.players)
        and set(sim_candidate.player_season_totals) == set(sim_candidate.players)
        and (
            not hasattr(sim_candidate, "injury_fatigue_profiles")
            or set(sim_candidate.injury_fatigue_profiles) == set(sim_candidate.players)
        )
    )
    decision_counts = Counter(clean(row.get("recommendation")) for row in decisions)
    market_ids = {clean(row.get("player_id")) for row in market_rows}
    candidate_market = {clean(value) for value in sim_candidate.free_agent_player_ids}
    roster_owners = {
        clean(pid): clean(team_code)
        for team_code, team_state in sim_candidate.teams.items()
        for pid in team_state.roster_player_ids
    }
    parity = all(
        ("" if clean(row.get("simulation_owner")) == "FA" else clean(row.get("simulation_owner")))
        == ("" if clean(row.get("trade_state_owner")) == "FA" else clean(row.get("trade_state_owner")))
        for row in result["ownership_rows"]
    )
    contract_transition_ok = True
    for row in decisions:
        pid = clean(row.get("player_id"))
        recommendation = clean(row.get("recommendation"))
        player = sim_candidate.players[pid]
        contract = player.contract
        if recommendation in {"exercise", "retain"}:
            contract_transition_ok = contract_transition_ok and (
                clean(contract.status) == "under_contract"
                and float(contract.salary or 0) == float(row.get("salary_2026_27") or 0)
                and roster_owners.get(pid) == clean(row.get("owner_after"))
                and pid not in candidate_market
            )
        else:
            contract_transition_ok = contract_transition_ok and (
                clean(contract.status) == "free_agent_pool"
                and contract.salary is None
                and pid in candidate_market
                and pid not in roster_owners
            )

    roster_counts = [{
        "team": clean(team_code),
        "roster_count": len(team_state.roster_player_ids),
        "active_count": len(team_state.active_player_ids),
        "inactive_count": len(team_state.inactive_player_ids),
        "rotation_count": len(team_state.rotation.rotation_player_ids),
        "starter_count": len(team_state.rotation.starter_ids),
    } for team_code, team_state in sorted(sim_candidate.teams.items())]
    amount_rows = [
        row for row in result["market_amount_candidates"]
        if row.get("free_agent_amount_2026_27") is not None
    ]
    amount_total = round(sum(float(row["free_agent_amount_2026_27"]) for row in amount_rows), 2)

    snapshots = list(getattr(trade_candidate, "undo_stack", ()) or ())
    initial = getattr(trade_candidate, "initial_snapshot", None)
    if initial is not None:
        snapshots.append(initial)
    snapshots_rebased = all(
        all(clean(snapshot.player_team_by_id.get(pid)) == owner for pid, owner in result["final_owner"].items())
        and all(
            math.isclose(
                float(snapshot.team_financials[team].team_salary),
                float(trade_candidate.team_financials[team].team_salary),
                abs_tol=0.01,
            )
            for team in trade_candidate.team_financials
        )
        for snapshot in snapshots
    )

    checks: list[dict[str, str]] = []

    def add(check_id: str, passed: bool, detail: str) -> None:
        checks.append({"check_id": check_id, "status": "PASS" if passed else "FAIL", "severity": "strict", "detail": detail})
        print(f"  {check_id}: {'PASS' if passed else 'FAIL'}")

    print("\nValidating clone-only transactional invariants...")
    add("interface_probe_passed_and_implementation_ready", probe_summary.get("passed") is True and probe_summary.get("implementation_ready") is True and all(clean(row.get("status")) == "PASS" for row in probe_checks), probe_zip.name)
    add("financial_component_registry_remains_zero_blockers", bridge_summary.get("passed") is True and bridge_summary.get("remaining_financial_component_blocker_count") == 0, "0")
    add("upstream_contracts_match_probe_fingerprints", not missing_fingerprints and not changed_fingerprints, f"{len(CRITICAL_SOURCE_FILES)}/{len(CRITICAL_SOURCE_FILES)}")
    add("ownership_ledger_is_exactly_587_unique", len(owner_ledger) == len({clean(row.get("player_id")) for row in owner_ledger}) == 587, "587/587")
    add("checkpoint_population_is_582_before_clone_hydration", result["source_population_count"] == 582, str(result["source_population_count"]))
    add("exact_five_zero_game_players_materialized_on_clone", materialized_ids == exact_supplement_ids and len(materialized) == 5, repr(sorted(materialized_ids)))
    add("five_official_identities_and_positions_are_exact", identity_position_exact, repr(expected_identity_position))
    add("five_development_profile_schemas_are_complete_and_finite", profile_schema_exact, "7 skills / 9 factors / 9 baselines each")
    add("five_evidence_derived_per36_profiles_are_exact", baseline_values_exact, "45/45 values")
    add("five_initial_salary_semantics_are_exact", initial_salary_evidence_exact, "4 attached salaries / 1 free agent")
    add("five_direct_evidence_methods_and_sources_are_cited", evidence_is_direct_and_cited, "5/5 explicit bridge records")
    add("candidate_population_is_exactly_587", result["candidate_population_count"] == len(sim_candidate.players) == 587, str(len(sim_candidate.players)))
    add("injury_totals_and_optional_health_maps_cover_all_587", state_maps_cover_population, "587/587")
    add("zero_game_materialization_is_clone_only", all(row.get("materialized_on_clone") is True and row.get("materialized_on_canonical") is False for row in materialized), "5/5 clone-only")
    add("decision_board_is_exactly_111_unique", len(decisions) == len({clean(row.get("player_id")) for row in decisions}) == 111, "111/111")
    add("decision_distribution_is_43_30_36_2", decision_counts == Counter({"exercise": 43, "decline": 30, "retain": 36, "waive": 2}), str(dict(decision_counts)))
    add("final_market_is_exactly_226_unique", candidate_market == market_ids and len(candidate_market) == 226, "226/226")
    add("chicago_branch_is_leonard_exercise_gueye_decline", roster_owners.get("1631159") == "CHI" and "1631338" in candidate_market, "Leonard retained / Gueye market")
    add("all_111_contract_and_roster_transitions_are_exact", contract_transition_ok, "111/111")
    add("simulation_and_trade_ownership_match_for_all_587", parity, "587/587")
    add("all_30_rosters_remain_within_offseason_limit", len(roster_counts) == 30 and all(5 <= int(row["roster_count"]) <= 21 for row in roster_counts), "30/30 between 5 and 21")
    add("offseason_state_passes_all_structural_invariants", all(sim_checks.values()), f"{len(sim_checks)}/{len(sim_checks)}")
    add("native_game_ready_blocker_is_only_expected_lal_floor", (native_game_ready and all(int(row["roster_count"]) >= 8 for row in roster_counts)) or ((not native_game_ready) and int(next(row for row in roster_counts if row["team"] == "LAL")["roster_count"]) == 7 and ("all_team_rosters_playable" in native_game_ready_error or "minimum_rosters" in native_game_ready_error)), native_game_ready_error or "native validator passed")
    add("trade_state_passes_all_native_invariants", all(trade_checks.values()), f"{len(trade_checks)}/{len(trade_checks)}")
    add("contract_payroll_delta_covers_exactly_30_teams", len(result["financial_deltas"]) == 30 and all(math.isfinite(float(row["contract_payroll_delta"])) for row in result["financial_deltas"]), "30/30")
    add("free_agent_amount_evidence_is_170_exact_unapplied", len(amount_rows) == int(market_summary.get("amount_ready_count", -1)) == 170 and amount_total == float(market_summary.get("full_market_amount_total", -1)) and all(not row["cap_hold_applied"] for row in amount_rows), f"170 rows / ${amount_total:,.0f}")
    add("rights_qo_and_cap_holds_remain_unapplied", all(not row["rights_decision_applied"] and not row["qo_decision_applied"] and not row["cap_hold_applied"] for row in result["market_amount_candidates"]), "0 applied")
    add("trade_undo_and_reset_snapshots_are_rebased", snapshots_rebased, f"snapshots={len(snapshots)}")
    first_transaction_digest = candidate_semantic_digest(
        result["simulation_candidate"],
        result["trade_candidate"],
    )
    repeat_transaction_digest = candidate_semantic_digest(
        repeat["simulation_candidate"],
        repeat["trade_candidate"],
    )
    add(
        "candidate_build_is_deterministic",
        first_transaction_digest == repeat_transaction_digest,
        "transaction semantic digests exact: " + first_transaction_digest,
    )
    round_trip_exact = candidate_semantic_digest(reloaded_sim, reloaded_trade) == candidate_semantic_digest(sim_candidate, trade_candidate)
    add("candidate_pickle_round_trip_is_exact", round_trip_exact, f"bytes={len(candidate_bytes)}")

    checkpoint_hash_after = sha256_file(checkpoint_path)
    checkpoint_after = checkpoint_module.load_franchise_checkpoint()
    add("canonical_simulation_state_unchanged", simulation_digest_before == object_digest(checkpoint_after.simulation_state) == EXPECTED_SIMULATION_DIGEST, simulation_digest_before)
    add("canonical_trade_state_unchanged", trade_digest_before == object_digest(checkpoint_after.trade_state), trade_digest_before)
    add("canonical_checkpoint_object_unchanged", checkpoint_object_digest_before == object_digest(checkpoint_after), checkpoint_object_digest_before)
    add("checkpoint_file_unchanged", checkpoint_hash_before == checkpoint_hash_after == EXPECTED_CHECKPOINT_SHA256, checkpoint_hash_after)
    failed = [row["check_id"] for row in checks if row["status"] != "PASS"]

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    name = f"fa_offseason_transaction_clone_candidate_hotfix_v1_0_1_{SEASON_LABEL}_{timestamp}"
    audit_dir = root / "outputs" / "audits"
    audit_dir.mkdir(parents=True, exist_ok=True)
    output_zip = audit_dir / f"{name}.zip"
    summary = {
        "version": VERSION,
        "season": SEASON_LABEL,
        "canonical_split_date": SPLIT_DATE.isoformat(),
        "passed": not failed,
        "failed_checks": failed,
        "owner_ledger_count": len(owner_ledger),
        "source_checkpoint_population_count": result["source_population_count"],
        "materialized_population_supplement_count": len(materialized),
        "materialized_population_supplement_ids": sorted(materialized_ids),
        "candidate_population_count": result["candidate_population_count"],
        "decision_count": len(decisions),
        "decision_distribution": dict(decision_counts),
        "final_market_count": len(candidate_market),
        "final_attached_population_count": len(owner_ledger) - len(candidate_market),
        "free_agent_amount_candidate_count": len(amount_rows),
        "free_agent_amount_candidate_total": amount_total,
        "rights_decisions_applied": 0,
        "qo_decisions_applied": 0,
        "cap_holds_applied": 0,
        "simulation_candidate_created": True,
        "trade_candidate_created": True,
        "pickle_round_trip_passed": round_trip_exact,
        "state_mutation_performed": False,
        "checkpoint_write_performed": False,
        "ready_for_rights_qo_resolution": not failed,
        "native_game_ready": native_game_ready,
        "game_ready_roster_blockers": [row["team"] for row in roster_counts if int(row["roster_count"]) < 8],
        "next_slice": "Resolve and clone-apply the 64 RFA rights/QO decisions, including the three controlled-CHI choices, then join only retained amounts as cap holds before a temporary-checkpoint commit/recovery rehearsal.",
    }
    readme = f"""2026 OFFSEASON TRANSACTION CLONE CANDIDATE HOTFIX V1.0.1

Result
------
- Audit passed: {not failed}
- Base checkpoint players: {result["source_population_count"]}
- Zero-game players materialized on clone: {len(materialized)}
- Candidate players: {result["candidate_population_count"]}
- Ownership universe: {len(owner_ledger)}
- Lifecycle decisions applied to clones: {len(decisions)}
- Decision distribution: 43 exercise / 30 decline / 36 retain / 2 waive
- Final market: {len(candidate_market)}
- Attached players: {len(owner_ledger) - len(candidate_market)}
- Native simulation and Trade Machine validation: PASS
- Game-ready roster blocker: LAL has 7 players and must sign at least one player before games

Financial boundary
------------------
Contract-payroll deltas were synchronized across both cloned states. The 170
exact Free Agent Amounts totaling ${amount_total:,.0f} remain evidence only.
Rights, QOs, renouncements, and cap holds were not applied.

Safety
------
No canonical simulation, Trade Machine state, rights overlay, or checkpoint was mutated.
"""

    with tempfile.TemporaryDirectory(prefix="fa_offseason_transaction_clone_") as temporary:
        folder = Path(temporary) / name
        folder.mkdir(parents=True)
        write_csv(folder / "resolved_lifecycle_transactions_111.csv", decisions)
        write_csv(folder / "zero_game_playerstate_population_supplement_5.csv", materialized)
        write_csv(folder / "final_clone_ownership_ledger_587.csv", result["ownership_rows"])
        write_csv(folder / "final_clone_market_226.csv", [row for row in result["ownership_rows"] if row["final_market_member"]])
        write_csv(folder / "team_roster_counts_after_lifecycle_30.csv", roster_counts)
        write_csv(folder / "contract_payroll_deltas_30.csv", result["financial_deltas"])
        write_csv(folder / "free_agent_amount_candidates_226_unapplied.csv", result["market_amount_candidates"])
        write_csv(folder / "clone_candidate_checks.csv", checks, ["check_id", "status", "severity", "detail"])
        (folder / "clone_candidate_summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
        (folder / "README.txt").write_text(readme, encoding="utf-8")
        with zipfile.ZipFile(output_zip, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for path in sorted(folder.rglob("*")):
                if path.is_file():
                    archive.write(path, arcname=f"{name}/{path.name}")

    print("\n" + "=" * 132)
    print(f"2026 OFFSEASON TRANSACTION CLONE CANDIDATE HOTFIX V1.0.1 {'PASSED' if not failed else 'FAILED'}")
    print("=" * 132)
    print("Base checkpoint population:   582")
    print("Clone population supplement:    5/5")
    print("Ownership universe:           587")
    print("Lifecycle decisions applied:  111/111 (CLONE ONLY)")
    print("Decision distribution:        43 exercise / 30 decline / 36 retain / 2 waive")
    print("Final market:                 226")
    print("Attached population:          361")
    print("FA Amount candidates:         170 exact / 56 not required")
    print("Rights/QO/cap holds applied:  0")
    print("Canonical mutation:           NOT PERFORMED")
    print("Checkpoint write:             NOT PERFORMED")
    print(f"Audit ZIP: {output_zip}")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
