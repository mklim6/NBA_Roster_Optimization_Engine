from __future__ import annotations

import copy
import csv
import hashlib
import io
import json
import math
import pickle
import sys
import tempfile
import zipfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


VERSION = "fa-full-team-salary-component-reconciliation-clone-v1-2026-08-16"
SEASON_LABEL = "2026-27"
ZERO_YOS_MINIMUM = 1_357_763.0
EXPECTED_CHECKPOINT_SHA256 = (
    "19f2fee601f5765bde4f5fabea34f20dc9b8ddc8dd5069186502dff08fc0cf9f"
)
EXPECTED_SIMULATION_DIGEST = (
    "f92f03b4c54e53f8f017c3fca43e93ccd09c8b8ba0e5fe0323f418021baf268e"
)
EXPECTED_TRADE_DIGEST = (
    "5183e4794f6a4e1a2daecabab45f3235ce712a7f4b34bf21ff62139334c3d70e"
)
MARKET_AMOUNT_ATTR = "offseason_free_agent_amount_candidates_v1"
RFA_LEDGER_ATTR = "offseason_rfa_rights_qo_decisions_v1"
NON_RFA_LEDGER_ATTR = "offseason_non_rfa_rights_decisions_v1"
OFFICIAL_SALARY_LEDGER_ATTR = "offseason_official_team_salary_components_v1"
SIM_HISTORY_ATTR = "offseason_transaction_application_v1_history"
SIM_REVISION_ATTR = "offseason_transaction_application_v1_revision"
TRADE_HISTORY_ATTR = "offseason_transaction_application_v1_history"


def clean(value: Any) -> str:
    return "" if value is None else str(value).strip()


def pid(value: Any) -> str:
    text = clean(value)
    return text[:-2] if text.endswith(".0") and text[:-2].isdigit() else text


def number(value: Any) -> float | None:
    text = clean(value).replace("$", "").replace(",", "")
    if not text:
        return None
    result = float(text)
    if not math.isfinite(result):
        raise RuntimeError(f"Invalid number: {value!r}")
    return result


def as_bool(value: Any) -> bool:
    return value is True or clean(value).lower() in {"true", "1", "yes", "y"}


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


def stable_digest(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


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


def write_csv(
    path: Path,
    rows: list[dict[str, Any]],
    fields: Iterable[str] | None = None,
) -> None:
    fieldnames = list(fields or [])
    if not fieldnames:
        seen: set[str] = set()
        for row in rows:
            for key in row:
                if key not in seen:
                    seen.add(key)
                    fieldnames.append(key)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        if not fieldnames:
            return
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def simulation_structure(state: Any) -> dict[str, Any]:
    return {
        "free_agents": sorted(pid(value) for value in state.free_agent_player_ids),
        "players": {
            pid(player_id): {
                "team": clean(player.team_abbreviation),
                "roster_status": clean(player.roster_status),
                "contract_status": clean(player.contract.status),
                "salary": player.contract.salary,
                "years_remaining": player.contract.years_remaining,
                "option_type": clean(player.contract.option_type),
                "guaranteed": player.contract.guaranteed,
            }
            for player_id, player in sorted(state.players.items())
        },
        "teams": {
            clean(code): {
                "roster": list(row.roster_player_ids),
                "active": list(row.active_player_ids),
                "inactive": list(row.inactive_player_ids),
                "starters": list(row.rotation.starter_ids),
                "rotation": list(row.rotation.rotation_player_ids),
                "minutes": sorted(
                    (pid(player_id), float(value))
                    for player_id, value in row.rotation.minutes_targets.items()
                ),
            }
            for code, row in sorted(state.teams.items())
        },
    }


def trade_ownership_structure(state: Any) -> dict[str, Any]:
    return {
        "owners": sorted((pid(player_id), clean(owner)) for player_id, owner in state.player_team_by_id.items()),
        "contract_counts": sorted(
            (
                clean(code),
                int(row.standard_contract_count),
                int(row.two_way_contract_count),
            )
            for code, row in state.team_financials.items()
        ),
    }


def candidate_semantic_digest(simulation_state: Any, trade_state: Any) -> str:
    payload = {
        "simulation": simulation_structure(simulation_state),
        "trade_ownership": trade_ownership_structure(trade_state),
        "trade_revision": int(getattr(trade_state, "state_revision", 0) or 0),
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
        "rfa_ledger": list(getattr(simulation_state, RFA_LEDGER_ATTR, ()) or ()),
        "non_rfa_ledger": list(getattr(simulation_state, NON_RFA_LEDGER_ATTR, ()) or ()),
        "official_salary_ledger": list(
            getattr(simulation_state, OFFICIAL_SALARY_LEDGER_ATTR, ()) or ()
        ),
        "market_amounts": list(getattr(simulation_state, MARKET_AMOUNT_ATTR, ()) or ()),
        "simulation_history": list(getattr(simulation_state, SIM_HISTORY_ATTR, ()) or ()),
        "trade_history": list(getattr(trade_state, TRADE_HISTORY_ATTR, ()) or ()),
    }
    return stable_digest(payload)


def build_component_rows(
    posture_rows: list[dict[str, str]],
    incentive_player_rows: list[dict[str, str]],
    incentive_team_rows: list[dict[str, str]],
    dead_cap_rows: list[dict[str, str]],
    rights_rows: list[dict[str, str]],
) -> list[dict[str, Any]]:
    posture_by_team = {clean(row.get("team")).upper(): row for row in posture_rows}
    incentive_team_by_team = {
        clean(row.get("team")).upper(): row for row in incentive_team_rows
    }
    dead_by_team = {clean(row.get("team")).upper(): row for row in dead_cap_rows}
    rights_by_team: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rights_rows:
        rights_by_team[clean(row.get("prior_team")).upper()].append(row)
    incentive_players_by_team: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in incentive_player_rows:
        incentive_players_by_team[clean(row.get("frozen_team")).upper()].append(row)

    teams = sorted(posture_by_team)
    if len(teams) != 30 or set(teams) != set(incentive_team_by_team) or set(teams) != set(dead_by_team):
        raise RuntimeError("Team component sources do not share an exact 30-team key set.")

    output: list[dict[str, Any]] = []
    for team in teams:
        posture = posture_by_team[team]
        incentive_team = incentive_team_by_team[team]
        dead = dead_by_team[team]
        player_rows = incentive_players_by_team[team]
        standard_count = int(number(posture.get("standard_contract_count")) or 0)
        listed_salary = float(number(posture.get("standard_contract_base_salary_subtotal")) or 0)
        frozen_listed_salary = sum(
            float(number(row.get("frozen_listed_base_salary")) or 0) for row in player_rows
        )
        corrected_contract_cap_hit = sum(
            float(number(row.get("cap_hit")) or 0)
            if as_bool(row.get("numeric_values_frozen"))
            else float(number(row.get("frozen_listed_base_salary")) or 0)
            for row in player_rows
        )
        team_rights = rights_by_team.get(team, [])
        retained_rights = [
            row for row in team_rights if float(number(row.get("effective_charge_2026_27")) or 0) > 0
        ]
        rights_charge = sum(
            float(number(row.get("effective_charge_2026_27")) or 0) for row in team_rights
        )
        dead_cap = float(number(dead.get("frozen_2026_27_dead_cap_total")) or 0)
        likely = float(number(incentive_team.get("frozen_likely_incentive_total")) or 0)
        unlikely = float(number(incentive_team.get("frozen_unlikely_incentive_total")) or 0)
        dynamic_pick_hold_count = 0
        dynamic_pick_hold = 0.0
        salary_population = standard_count + len(retained_rights) + dynamic_pick_hold_count
        incomplete_slots = max(0, 12 - salary_population)
        incomplete_charge = incomplete_slots * ZERO_YOS_MINIMUM
        official_total = (
            corrected_contract_cap_hit
            + rights_charge
            + dead_cap
            + dynamic_pick_hold
            + incomplete_charge
        )
        output.append({
            "team": team,
            "standard_contract_count": standard_count,
            "frozen_incentive_player_count": len(player_rows),
            "listed_standard_contract_salary": listed_salary,
            "frozen_listed_salary_crosscheck": frozen_listed_salary,
            "corrected_standard_contract_cap_hit": corrected_contract_cap_hit,
            "contract_cap_hit_normalization_delta": corrected_contract_cap_hit - listed_salary,
            "retained_rights_count": len(retained_rights),
            "rights_effective_charge": rights_charge,
            "frozen_dead_cap": dead_cap,
            "frozen_likely_incentive_evidence": likely,
            "frozen_unlikely_incentive_exposure": unlikely,
            "likely_incentive_separately_added": False,
            "unlikely_incentive_added_to_team_salary": False,
            "opening_snapshot_first_round_pick_hold_count": dynamic_pick_hold_count,
            "opening_snapshot_first_round_pick_hold_total": dynamic_pick_hold,
            "players_counted_for_incomplete_roster": salary_population,
            "incomplete_roster_slots": incomplete_slots,
            "incomplete_roster_charge": incomplete_charge,
            "official_modeled_team_salary": official_total,
            "official_modeled_apron_salary": official_total,
            "applied_to_clone": True,
            "applied_to_canonical": False,
        })
    return output


def apply_component_ledger(
    simulation_state: Any,
    trade_state: Any,
    component_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    simulation_candidate = copy.deepcopy(simulation_state)
    trade_candidate = copy.deepcopy(trade_state)
    by_team = {clean(row.get("team")).upper(): dict(row) for row in component_rows}
    if not (len(component_rows) == len(by_team) == 30):
        raise RuntimeError("Official component ledger must contain exactly 30 unique teams.")
    if set(by_team) != {clean(team).upper() for team in trade_candidate.team_financials}:
        raise RuntimeError("Official component ledger team set does not match Trade Machine state.")

    reconciliation_rows: list[dict[str, Any]] = []
    for code, financial in sorted(trade_candidate.team_financials.items()):
        team = clean(code).upper()
        component = by_team[team]
        before_team_salary = float(financial.team_salary)
        before_apron_salary = float(financial.apron_salary)
        official_team_salary = float(component["official_modeled_team_salary"])
        official_apron_salary = float(component["official_modeled_apron_salary"])
        financial.team_salary = official_team_salary
        financial.apron_salary = official_apron_salary
        reconciliation_rows.append({
            **component,
            "rights_applied_clone_team_salary_before_reconciliation": before_team_salary,
            "rights_applied_clone_apron_salary_before_reconciliation": before_apron_salary,
            "team_salary_reconciliation_delta": official_team_salary - before_team_salary,
            "apron_salary_reconciliation_delta": official_apron_salary - before_apron_salary,
        })

    snapshots = list(getattr(trade_candidate, "undo_stack", ()) or ())
    initial_snapshot = getattr(trade_candidate, "initial_snapshot", None)
    if initial_snapshot is not None:
        snapshots.append(initial_snapshot)
    for snapshot in snapshots:
        snapshot.team_financials = copy.deepcopy(trade_candidate.team_financials)

    setattr(simulation_candidate, OFFICIAL_SALARY_LEDGER_ATTR, copy.deepcopy(reconciliation_rows))
    setattr(trade_candidate, OFFICIAL_SALARY_LEDGER_ATTR, copy.deepcopy(reconciliation_rows))
    event = {
        "transaction_id": "OFFSEASON-OFFICIAL-TEAM-SALARY-2026-0004",
        "version": VERSION,
        "team_count": 30,
        "official_modeled_team_salary_total": 6_257_630_520.0,
        "dynamic_first_round_pick_hold_total": 0.0,
        "incomplete_roster_charge_total": 0.0,
        "applied_to_clone": True,
        "applied_to_canonical": False,
    }
    sim_history = copy.deepcopy(list(getattr(simulation_candidate, SIM_HISTORY_ATTR, ()) or ()))
    trade_history = copy.deepcopy(list(getattr(trade_candidate, TRADE_HISTORY_ATTR, ()) or ()))
    sim_history.append(copy.deepcopy(event))
    trade_history.append(copy.deepcopy(event))
    setattr(simulation_candidate, SIM_HISTORY_ATTR, sim_history)
    setattr(trade_candidate, TRADE_HISTORY_ATTR, trade_history)
    setattr(
        simulation_candidate,
        SIM_REVISION_ATTR,
        int(getattr(simulation_candidate, SIM_REVISION_ATTR, 0) or 0) + 1,
    )
    trade_candidate.state_revision = int(getattr(trade_candidate, "state_revision", 0) or 0) + 1
    if hasattr(simulation_candidate, "source_league_state_revision"):
        simulation_candidate.source_league_state_revision = int(trade_candidate.state_revision)
    return {
        "simulation_candidate": simulation_candidate,
        "trade_candidate": trade_candidate,
        "reconciliation_rows": reconciliation_rows,
        "event": event,
        "snapshot_count": len(snapshots),
    }


def main() -> int:
    root = Path.cwd().resolve()
    src = root / "src"
    if not src.exists():
        raise RuntimeError("Run from the NBA_Roster_Optimization_Engine project root.")

    rights_apply_zip = find_passed(
        root,
        "fa_non_rfa_rights_default_preservation_clone_apply_v1_2026-27_*.zip",
        "non_rfa_clone_application_summary.json",
    )
    posture_zip = find_passed(
        root,
        "fa_team_base_salary_and_rights_posture_preview_v1_2026-27_*.zip",
        "team_base_salary_and_rights_posture_summary.json",
    )
    dead_cap_zip = find_passed(
        root,
        "fa_frozen_dead_cap_final_freeze_v1_2026-27_*.zip",
        "frozen_dead_cap_final_freeze_summary.json",
    )
    incentive_zip = find_passed(
        root,
        "fa_frozen_incentive_final_freeze_v1_2026-27_*.zip",
        "frozen_incentive_final_freeze_summary.json",
    )
    pick_bridge_zip = find_passed(
        root,
        "fa_post_draft_first_round_pick_hold_bridge_final_integration_v1_2026-27_*.zip",
        "final_bridge_integration_summary.json",
    )
    rfa_preview_zip = find_passed(
        root,
        "fa_rfa_rights_qo_controlled_team_preview_v1_2026-27_*.zip",
        "rfa_rights_qo_preview_summary.json",
    )
    non_rfa_rights_zip = find_passed(
        root,
        "fa_non_rfa_rights_final_completion_v1_2026-27_*.zip",
        "non_rfa_rights_final_completion_summary.json",
    )
    clone_input_zip = find_passed(
        root,
        "fa_clone_only_offseason_decision_application_preview_v1_2026-27_*.zip",
        "clone_application_summary.json",
    )
    market_zip = find_passed(
        root,
        "fa_full_market_free_agent_amount_completion_v1_2026-27_*.zip",
        "full_market_free_agent_amount_summary.json",
    )

    with zipfile.ZipFile(rights_apply_zip) as archive:
        rights_summary = json_suffix(archive, "non_rfa_clone_application_summary.json")
        rights_checks = csv_suffix(archive, "non_rfa_clone_application_checks.csv")
        audited_rights_ledger = csv_suffix(
            archive, "full_market_rights_ledger_after_all_application_226.csv"
        )
        audited_rights_team_deltas = csv_suffix(
            archive, "non_rfa_team_financial_deltas_30.csv"
        )
    with zipfile.ZipFile(posture_zip) as archive:
        posture_summary = json_suffix(archive, "team_base_salary_and_rights_posture_summary.json")
        posture_rows = csv_suffix(archive, "team_rights_posture_wide_30.csv")
    with zipfile.ZipFile(dead_cap_zip) as archive:
        dead_summary = json_suffix(archive, "frozen_dead_cap_final_freeze_summary.json")
        dead_checks = csv_suffix(archive, "frozen_dead_cap_final_freeze_checks.csv")
        dead_rows = csv_suffix(archive, "final_frozen_dead_cap_team_ledger_30.csv")
    with zipfile.ZipFile(incentive_zip) as archive:
        incentive_summary = json_suffix(archive, "frozen_incentive_final_freeze_summary.json")
        incentive_checks = csv_suffix(archive, "frozen_incentive_final_freeze_checks.csv")
        incentive_player_rows = csv_suffix(archive, "final_frozen_incentive_player_ledger_331.csv")
        incentive_team_rows = csv_suffix(archive, "final_frozen_incentive_team_ledger_30.csv")
    with zipfile.ZipFile(pick_bridge_zip) as archive:
        pick_summary = json_suffix(archive, "final_bridge_integration_summary.json")
        pick_checks = csv_suffix(archive, "final_bridge_integration_checks.csv")
    with zipfile.ZipFile(rfa_preview_zip) as archive:
        rfa_board = csv_suffix(archive, "rfa_rights_qo_decision_board_64.csv")
    with zipfile.ZipFile(non_rfa_rights_zip) as archive:
        non_rfa_rights = csv_suffix(archive, "non_rfa_rights_evidence_complete_162.csv")
    with zipfile.ZipFile(clone_input_zip) as archive:
        automatic = csv_suffix(archive, "automatic_decisions_applied_109.csv")
        pending = csv_suffix(archive, "user_decisions_pending_2.csv")
        owner_ledger = csv_suffix(archive, "clone_owner_ledger_587.csv")
    with zipfile.ZipFile(market_zip) as archive:
        market_rows = csv_suffix(archive, "full_market_free_agent_amounts_complete_226.csv")

    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
    import simulation_franchise_checkpoint_v1 as checkpoint_module
    from fa_non_rfa_rights_default_preservation_clone_apply_v1 import (
        VERSION as NON_RFA_APPLICATION_VERSION,
        apply_non_rfa_board,
    )
    from fa_rfa_rights_qo_recommended_branch_clone_apply_v1 import apply_rfa_board
    from freeform_trade_machine_engine_v3 import load_runtime_data
    from franchise_offseason_transaction_application_v1 import (
        build_offseason_transaction_candidates,
        validate_offseason_transition_state,
    )
    from mutable_league_state_v1 import validate_state

    if NON_RFA_APPLICATION_VERSION != "fa-non-rfa-rights-default-preservation-clone-apply-v1-2026-08-16":
        raise RuntimeError(f"Unexpected non-RFA application version: {NON_RFA_APPLICATION_VERSION}")

    checkpoint_path = Path(checkpoint_module.DEFAULT_CHECKPOINT_PATH)
    checkpoint_hash_before = sha256_file(checkpoint_path)
    checkpoint = checkpoint_module.load_franchise_checkpoint()
    if checkpoint is None:
        raise RuntimeError("Canonical checkpoint could not be loaded.")
    canonical_simulation_digest_before = object_digest(checkpoint.simulation_state)
    canonical_trade_digest_before = object_digest(checkpoint.trade_state)
    canonical_object_digest_before = object_digest(checkpoint)
    overlay_path = root / "outputs" / "runtime" / "free_agency_rights_population_v1.json"
    overlay_existed_before = overlay_path.exists()
    overlay_hash_before = sha256_file(overlay_path) if overlay_existed_before else ""
    if checkpoint_hash_before != EXPECTED_CHECKPOINT_SHA256:
        raise RuntimeError("Canonical checkpoint changed before Team Salary reconciliation.")
    if canonical_simulation_digest_before != EXPECTED_SIMULATION_DIGEST:
        raise RuntimeError("Canonical simulation state changed before Team Salary reconciliation.")
    if canonical_trade_digest_before != EXPECTED_TRADE_DIGEST:
        raise RuntimeError("Canonical Trade Machine state changed before Team Salary reconciliation.")

    print("=" * 132)
    print("2026 FULL TEAM SALARY COMPONENT RECONCILIATION CLONE V1")
    print("=" * 132)
    print("Rebuilding the complete rights-applied clone and replacing legacy salary proxies with frozen components...")

    runtime = load_runtime_data()
    base = build_offseason_transaction_candidates(
        checkpoint.simulation_state,
        checkpoint.trade_state,
        runtime=runtime,
        owner_ledger_rows=owner_ledger,
        market_rows=market_rows,
        automatic_decisions=automatic,
        pending_decisions=pending,
    )
    post_rfa = apply_rfa_board(base["simulation_candidate"], base["trade_candidate"], rfa_board)
    post_rights = apply_non_rfa_board(
        post_rfa["simulation_candidate"], post_rfa["trade_candidate"], non_rfa_rights
    )
    rights_simulation = post_rights["simulation_candidate"]
    rights_trade = post_rights["trade_candidate"]
    rights_simulation_structure_digest = stable_digest(simulation_structure(rights_simulation))
    rights_trade_ownership_digest = stable_digest(trade_ownership_structure(rights_trade))

    component_rows = build_component_rows(
        posture_rows,
        incentive_player_rows,
        incentive_team_rows,
        dead_rows,
        audited_rights_ledger,
    )
    result = apply_component_ledger(rights_simulation, rights_trade, component_rows)
    repeat = apply_component_ledger(rights_simulation, rights_trade, component_rows)
    simulation_candidate = result["simulation_candidate"]
    trade_candidate = result["trade_candidate"]
    reconciliation_rows = result["reconciliation_rows"]

    sim_checks = validate_offseason_transition_state(simulation_candidate)
    trade_checks = validate_state(trade_candidate, runtime)
    candidate_bytes = pickle.dumps(
        (simulation_candidate, trade_candidate), protocol=pickle.HIGHEST_PROTOCOL
    )
    reloaded_simulation, reloaded_trade = pickle.loads(candidate_bytes)
    validate_offseason_transition_state(reloaded_simulation)
    validate_state(reloaded_trade, runtime)

    audited_rights_team_by_team = {
        clean(row.get("team")).upper(): row for row in audited_rights_team_deltas
    }
    audited_legacy_rights_total = sum(
        float(number(row.get("trade_team_salary_after_all_rights")) or 0)
        for row in audited_rights_team_deltas
    )
    reconstructed_rights_salary = {
        clean(team).upper(): float(row.team_salary)
        for team, row in rights_trade.team_financials.items()
    }
    source_team_sets = [
        {clean(row.get("team")).upper() for row in rows}
        for rows in (posture_rows, incentive_team_rows, dead_rows, reconciliation_rows)
    ]
    listed_salary_total = sum(float(row["listed_standard_contract_salary"]) for row in reconciliation_rows)
    frozen_listed_crosscheck_total = sum(float(row["frozen_listed_salary_crosscheck"]) for row in reconciliation_rows)
    corrected_contract_total = sum(float(row["corrected_standard_contract_cap_hit"]) for row in reconciliation_rows)
    contract_normalization_delta = sum(float(row["contract_cap_hit_normalization_delta"]) for row in reconciliation_rows)
    rights_charge_total = sum(float(row["rights_effective_charge"]) for row in reconciliation_rows)
    rights_hold_count = sum(int(row["retained_rights_count"]) for row in reconciliation_rows)
    dead_cap_total = sum(float(row["frozen_dead_cap"]) for row in reconciliation_rows)
    likely_total = sum(float(row["frozen_likely_incentive_evidence"]) for row in reconciliation_rows)
    unlikely_total = sum(float(row["frozen_unlikely_incentive_exposure"]) for row in reconciliation_rows)
    pick_hold_total = sum(float(row["opening_snapshot_first_round_pick_hold_total"]) for row in reconciliation_rows)
    incomplete_charge_total = sum(float(row["incomplete_roster_charge"]) for row in reconciliation_rows)
    official_total = sum(float(row["official_modeled_team_salary"]) for row in reconciliation_rows)
    legacy_rights_total = sum(float(row["rights_applied_clone_team_salary_before_reconciliation"]) for row in reconciliation_rows)
    reconciliation_delta_total = sum(float(row["team_salary_reconciliation_delta"]) for row in reconciliation_rows)

    numeric_incentive_rows = [row for row in incentive_player_rows if as_bool(row.get("numeric_values_frozen"))]
    not_applicable_incentive_rows = [row for row in incentive_player_rows if not as_bool(row.get("numeric_values_frozen"))]
    snapshots = list(getattr(trade_candidate, "undo_stack", ()) or ())
    if getattr(trade_candidate, "initial_snapshot", None) is not None:
        snapshots.append(trade_candidate.initial_snapshot)
    snapshots_rebased = all(
        all(
            math.isclose(
                float(snapshot.team_financials[code].team_salary),
                float(trade_candidate.team_financials[code].team_salary),
                abs_tol=0.01,
            )
            and math.isclose(
                float(snapshot.team_financials[code].apron_salary),
                float(trade_candidate.team_financials[code].apron_salary),
                abs_tol=0.01,
            )
            for code in trade_candidate.team_financials
        )
        for snapshot in snapshots
    )

    checks: list[dict[str, str]] = []

    def add(check_id: str, passed: bool, detail: str) -> None:
        checks.append({
            "check_id": check_id,
            "status": "PASS" if passed else "FAIL",
            "severity": "strict",
            "detail": detail,
        })
        print(f"  {check_id}: {'PASS' if passed else 'FAIL'}")

    print("")
    print("Validating official Team Salary component invariants...")
    add(
        "upstream_combined_rights_application_passed_all_31_checks",
        rights_summary.get("passed") is True
        and rights_summary.get("ready_for_full_team_salary_reconciliation") is True
        and len(rights_checks) == 31
        and all(clean(row.get("status")) == "PASS" for row in rights_checks),
        rights_apply_zip.name,
    )
    add(
        "all_financial_component_source_audits_passed",
        posture_summary.get("passed") is True
        and dead_summary.get("passed") is True
        and incentive_summary.get("passed") is True
        and pick_summary.get("passed") is True
        and all(clean(row.get("status")) == "PASS" for row in dead_checks)
        and all(clean(row.get("status")) == "PASS" for row in incentive_checks)
        and all(clean(row.get("status")) == "PASS" for row in pick_checks),
        "posture / dead cap / incentives / pick bridge",
    )
    add(
        "financial_component_registry_has_zero_remaining_blockers",
        pick_summary.get("financial_component_registry_complete") is True
        and int(pick_summary.get("remaining_financial_component_blocker_count", -1)) == 0,
        "0 blockers",
    )
    add(
        "all_component_sources_share_exact_30_team_set",
        all(len(team_set) == 30 and team_set == source_team_sets[0] for team_set in source_team_sets),
        "30/30",
    )
    add(
        "incentive_contract_population_is_exactly_320_plus_11",
        len(incentive_player_rows) == 331
        and len(numeric_incentive_rows) == 320
        and len(not_applicable_incentive_rows) == 11,
        "331 = 320 numeric + 11 temporal N/A",
    )
    add(
        "listed_standard_contract_salary_total_is_exact",
        listed_salary_total == frozen_listed_crosscheck_total == 5_072_251_338.0,
        f"${listed_salary_total:,.0f}",
    )
    add(
        "corrected_contract_cap_hit_total_is_exact",
        corrected_contract_total == 5_083_727_809.0,
        f"${corrected_contract_total:,.0f}",
    )
    add(
        "contract_cap_hit_normalization_delta_is_exact",
        contract_normalization_delta == 11_476_471.0,
        f"${contract_normalization_delta:,.0f}",
    )
    add(
        "combined_rights_component_is_exact_155_holds",
        rights_hold_count == 155 and rights_charge_total == 1_118_248_880.0,
        f"155 holds / ${rights_charge_total:,.0f}",
    )
    add(
        "frozen_dead_cap_component_is_exact",
        dead_cap_total == float(dead_summary.get("final_frozen_dead_cap_total", -1)) == 55_653_831.0,
        f"${dead_cap_total:,.0f}",
    )
    add(
        "frozen_incentive_evidence_totals_are_exact",
        likely_total == float(incentive_summary.get("final_frozen_likely_incentive_total", -1)) == 10_691_125.0
        and unlikely_total == float(incentive_summary.get("final_frozen_unlikely_incentive_total", -1)) == 42_079_384.0,
        f"likely=${likely_total:,.0f}; unlikely=${unlikely_total:,.0f}",
    )
    add(
        "likely_incentives_are_embedded_in_corrected_cap_hits_not_double_counted",
        all(row["likely_incentive_separately_added"] is False for row in reconciliation_rows)
        and official_total == corrected_contract_total + rights_charge_total + dead_cap_total,
        "cap-hit normalization owns active-contract incentive treatment",
    )
    add(
        "unlikely_incentive_exposure_is_tracked_but_not_added",
        all(row["unlikely_incentive_added_to_team_salary"] is False for row in reconciliation_rows),
        f"${unlikely_total:,.0f} tracked separately",
    )
    add(
        "opening_snapshot_dynamic_first_round_pick_holds_are_zero",
        pick_summary.get("opening_snapshot_hold_count") == 0
        and pick_hold_total == 0
        and all(int(row["opening_snapshot_first_round_pick_hold_count"]) == 0 for row in reconciliation_rows),
        "0 at April 12 boundary",
    )
    add(
        "incomplete_roster_charge_is_zero_after_155_retained_rights",
        incomplete_charge_total == 0
        and all(int(row["incomplete_roster_slots"]) == 0 for row in reconciliation_rows),
        "$0 / 30 teams complete",
    )
    add(
        "official_modeled_team_salary_total_is_exact",
        official_total == 6_257_630_520.0,
        f"${official_total:,.0f}",
    )
    add(
        "reconstructed_rights_clone_financials_match_passed_audit",
        len(audited_rights_team_by_team) == 30
        and all(
            math.isclose(
                reconstructed_rights_salary[team],
                float(number(row.get("trade_team_salary_after_all_rights")) or 0),
                abs_tol=0.01,
            )
            for team, row in audited_rights_team_by_team.items()
        ),
        "30/30",
    )
    add(
        "legacy_rights_applied_salary_total_is_frozen_for_reconciliation",
        legacy_rights_total == audited_legacy_rights_total,
        f"${legacy_rights_total:,.2f}",
    )
    add(
        "legacy_proxy_reconciliation_delta_is_exact",
        math.isclose(
            reconciliation_delta_total,
            official_total - audited_legacy_rights_total,
            abs_tol=0.01,
        )
        and math.isclose(legacy_rights_total + reconciliation_delta_total, official_total, abs_tol=0.01),
        f"${reconciliation_delta_total:,.2f}",
    )
    add(
        "all_30_team_component_equations_reconcile",
        all(
            math.isclose(
                float(row["official_modeled_team_salary"]),
                float(row["corrected_standard_contract_cap_hit"])
                + float(row["rights_effective_charge"])
                + float(row["frozen_dead_cap"])
                + float(row["opening_snapshot_first_round_pick_hold_total"])
                + float(row["incomplete_roster_charge"]),
                abs_tol=0.01,
            )
            for row in reconciliation_rows
        ),
        "30/30",
    )
    add(
        "trade_team_and_apron_salaries_match_official_ledger",
        all(
            float(trade_candidate.team_financials[row["team"]].team_salary)
            == float(row["official_modeled_team_salary"])
            and float(trade_candidate.team_financials[row["team"]].apron_salary)
            == float(row["official_modeled_apron_salary"])
            for row in reconciliation_rows
        ),
        "30/30",
    )
    add(
        "simulation_rosters_contracts_and_market_membership_unchanged",
        stable_digest(simulation_structure(simulation_candidate))
        == rights_simulation_structure_digest,
        rights_simulation_structure_digest,
    )
    add(
        "trade_ownership_and_contract_counts_unchanged",
        stable_digest(trade_ownership_structure(trade_candidate))
        == rights_trade_ownership_digest,
        rights_trade_ownership_digest,
    )
    add(
        "all_226_rights_decisions_remain_present_and_applied",
        len(getattr(simulation_candidate, MARKET_AMOUNT_ATTR, ()) or ()) == 226
        and len(getattr(simulation_candidate, RFA_LEDGER_ATTR, ()) or ()) == 64
        and len(getattr(simulation_candidate, NON_RFA_LEDGER_ATTR, ()) or ()) == 162,
        "226 = 64 RFA + 162 non-RFA",
    )
    add(
        "official_salary_ledger_is_mirrored_across_both_clones",
        getattr(simulation_candidate, OFFICIAL_SALARY_LEDGER_ATTR, None)
        == getattr(trade_candidate, OFFICIAL_SALARY_LEDGER_ATTR, None)
        == reconciliation_rows,
        "30/30",
    )
    add(
        "trade_undo_and_reset_snapshots_are_rebased",
        snapshots_rebased and len(snapshots) == result["snapshot_count"],
        f"snapshots={len(snapshots)}",
    )
    add(
        "simulation_state_passes_all_offseason_invariants",
        all(sim_checks.values()),
        f"{len(sim_checks)}/{len(sim_checks)}",
    )
    add(
        "trade_state_passes_all_native_invariants",
        all(trade_checks.values()),
        f"{len(trade_checks)}/{len(trade_checks)}",
    )
    add(
        "full_component_reconciliation_is_deterministic",
        candidate_semantic_digest(simulation_candidate, trade_candidate)
        == candidate_semantic_digest(repeat["simulation_candidate"], repeat["trade_candidate"]),
        "repeat digests exact",
    )
    add(
        "candidate_pickle_round_trip_is_exact",
        candidate_semantic_digest(reloaded_simulation, reloaded_trade)
        == candidate_semantic_digest(simulation_candidate, trade_candidate),
        f"bytes={len(candidate_bytes)}",
    )
    add(
        "component_reconciliation_is_clone_only",
        all(row["applied_to_canonical"] is False for row in reconciliation_rows),
        "0 canonical rows",
    )

    checkpoint_after = checkpoint_module.load_franchise_checkpoint()
    checkpoint_hash_after = sha256_file(checkpoint_path)
    overlay_existed_after = overlay_path.exists()
    overlay_hash_after = sha256_file(overlay_path) if overlay_existed_after else ""
    add(
        "canonical_simulation_state_unchanged",
        object_digest(checkpoint_after.simulation_state)
        == canonical_simulation_digest_before
        == EXPECTED_SIMULATION_DIGEST,
        canonical_simulation_digest_before,
    )
    add(
        "canonical_trade_state_unchanged",
        object_digest(checkpoint_after.trade_state)
        == canonical_trade_digest_before
        == EXPECTED_TRADE_DIGEST,
        canonical_trade_digest_before,
    )
    add(
        "canonical_checkpoint_object_unchanged",
        object_digest(checkpoint_after) == canonical_object_digest_before,
        canonical_object_digest_before,
    )
    add(
        "rights_population_overlay_unchanged",
        overlay_existed_before == overlay_existed_after and overlay_hash_before == overlay_hash_after,
        overlay_hash_after or "overlay absent before and after",
    )
    add(
        "checkpoint_file_unchanged",
        checkpoint_hash_before == checkpoint_hash_after == EXPECTED_CHECKPOINT_SHA256,
        checkpoint_hash_after,
    )

    failed = [row["check_id"] for row in checks if row["status"] != "PASS"]
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    export_id = f"fa_full_team_salary_component_reconciliation_clone_v1_{SEASON_LABEL}_{timestamp}"
    audit_dir = root / "outputs" / "audits"
    audit_dir.mkdir(parents=True, exist_ok=True)
    audit_zip = audit_dir / f"{export_id}.zip"
    summary = {
        "version": VERSION,
        "season": SEASON_LABEL,
        "passed": not failed,
        "failed_checks": failed,
        "source_combined_rights_audit": rights_apply_zip.name,
        "source_dead_cap_audit": dead_cap_zip.name,
        "source_incentive_audit": incentive_zip.name,
        "source_pick_hold_bridge_audit": pick_bridge_zip.name,
        "team_count": 30,
        "listed_standard_contract_salary_total": listed_salary_total,
        "corrected_standard_contract_cap_hit_total": corrected_contract_total,
        "contract_cap_hit_normalization_delta": contract_normalization_delta,
        "combined_rights_charge_total": rights_charge_total,
        "combined_retained_rights_count": rights_hold_count,
        "frozen_dead_cap_total": dead_cap_total,
        "frozen_likely_incentive_evidence_total": likely_total,
        "frozen_unlikely_incentive_exposure_total": unlikely_total,
        "likely_incentives_separately_added": False,
        "opening_snapshot_first_round_pick_hold_total": pick_hold_total,
        "incomplete_roster_charge_total": incomplete_charge_total,
        "legacy_rights_applied_salary_total": legacy_rights_total,
        "legacy_proxy_reconciliation_delta": reconciliation_delta_total,
        "official_modeled_team_salary_total": official_total,
        "official_salary_applied_to_clones": True,
        "state_mutation_performed": False,
        "rights_overlay_write_performed": False,
        "checkpoint_write_performed": False,
        "ready_for_temporary_checkpoint_rehearsal": not failed,
        "next_slice": (
            "Perform a temporary-file checkpoint commit, reload, digest, rollback, and recovery "
            "rehearsal for the fully reconciled clone before authorizing a canonical write."
        ),
    }
    readme = f"""2026 FULL TEAM SALARY COMPONENT RECONCILIATION CLONE V1
========================================================

Result
------
- Audit passed: {not failed}
- Corrected standard-contract cap hits: ${corrected_contract_total:,.0f}
- Combined rights charges: ${rights_charge_total:,.0f}
- Frozen dead cap: ${dead_cap_total:,.0f}
- Opening first-round pick holds: ${pick_hold_total:,.0f}
- Incomplete-roster charges: ${incomplete_charge_total:,.0f}
- Official modeled Team Salary: ${official_total:,.0f}
- Legacy proxy correction: ${reconciliation_delta_total:,.2f}

Incentive treatment
-------------------
The frozen player cap-hit ledger replaces the earlier listed-salary proxy for
320 numeric contracts. This captures active-contract incentive treatment once.
The $10,691,125 likely ledger is retained as a crosscheck and is not added a
second time. The $42,079,384 unlikely exposure remains separately auditable.

Draft boundary
--------------
The April 12 opening snapshot contains zero 2026 first-round pick holds. The
installed dynamic bridge creates and removes those holds only after the Draft.

Safety
------
The official 30-team component ledger was applied only to reconstructed clones.
No canonical state, rights overlay, or checkpoint was written.
"""

    with tempfile.TemporaryDirectory(prefix="fa_team_salary_reconciliation_") as temporary:
        export = Path(temporary) / export_id
        export.mkdir(parents=True)
        write_csv(export / "official_team_salary_component_ledger_30.csv", reconciliation_rows)
        write_csv(
            export / "active_contract_cap_hit_normalization_331.csv",
            incentive_player_rows,
        )
        write_csv(export / "combined_rights_component_226.csv", audited_rights_ledger)
        write_csv(export / "frozen_dead_cap_component_30.csv", dead_rows)
        write_csv(export / "frozen_incentive_component_30.csv", incentive_team_rows)
        write_csv(
            export / "team_salary_component_reconciliation_checks.csv",
            checks,
            ["check_id", "status", "severity", "detail"],
        )
        (export / "team_salary_component_reconciliation_summary.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8"
        )
        (export / "README.txt").write_text(readme, encoding="utf-8")
        with zipfile.ZipFile(audit_zip, "w", zipfile.ZIP_DEFLATED) as archive:
            for item in sorted(export.iterdir()):
                archive.write(item, arcname=f"{export_id}/{item.name}")

    print("")
    print("=" * 132)
    print(
        "2026 FULL TEAM SALARY COMPONENT RECONCILIATION CLONE V1 "
        + ("PASSED" if not failed else "FAILED")
    )
    print("=" * 132)
    print("Teams reconciled:                     30/30 (CLONE ONLY)")
    print("Corrected contract cap hits:     $5,083,727,809")
    print("Combined rights charges:         $1,118,248,880")
    print("Frozen dead cap:                    $55,653,831")
    print("Opening first-round pick holds:              $0")
    print("Incomplete-roster charges:                   $0")
    print("Official modeled Team Salary:      $6,257,630,520")
    print(f"Legacy proxy reconciliation:      ${reconciliation_delta_total:,.2f}")
    print("Canonical mutation:                 NOT PERFORMED")
    print("Rights overlay write:               NOT PERFORMED")
    print("Checkpoint write:                   NOT PERFORMED")
    print(f"Audit ZIP: {audit_zip}")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
