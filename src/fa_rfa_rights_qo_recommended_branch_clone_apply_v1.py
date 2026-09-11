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
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


VERSION = "fa-rfa-rights-qo-recommended-branch-clone-apply-v1-2026-08-16"
SEASON_LABEL = "2026-27"
CONTROLLED_TEAM = "CHI"
EXPECTED_CONTROLLED_IDS = {"1631338", "1642530", "1642950"}
EXPECTED_CHECKPOINT_SHA256 = (
    "19f2fee601f5765bde4f5fabea34f20dc9b8ddc8dd5069186502dff08fc0cf9f"
)
EXPECTED_SIMULATION_DIGEST = (
    "f92f03b4c54e53f8f017c3fca43e93ccd09c8b8ba0e5fe0323f418021baf268e"
)
EXPECTED_TRADE_DIGEST = (
    "5183e4794f6a4e1a2daecabab45f3235ce712a7f4b34bf21ff62139334c3d70e"
)
RFA_LEDGER_ATTR = "offseason_rfa_rights_qo_decisions_v1"
MARKET_AMOUNT_ATTR = "offseason_free_agent_amount_candidates_v1"
SIM_HISTORY_ATTR = "offseason_transaction_application_v1_history"
SIM_REVISION_ATTR = "offseason_transaction_application_v1_revision"
TRADE_HISTORY_ATTR = "offseason_transaction_application_v1_history"


def clean(value: Any) -> str:
    return "" if value is None else str(value).strip()


def pid(value: Any) -> str:
    text = clean(value)
    return text[:-2] if text.endswith(".0") and text[:-2].isdigit() else text


def amount(value: Any) -> float | None:
    text = clean(value).replace("$", "").replace(",", "")
    if not text:
        return None
    result = float(text)
    if not math.isfinite(result) or result < 0:
        raise RuntimeError(f"Invalid amount: {value!r}")
    return result


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
        "market_amounts": list(getattr(simulation_state, MARKET_AMOUNT_ATTR, ()) or ()),
        "simulation_history": list(getattr(simulation_state, SIM_HISTORY_ATTR, ()) or ()),
        "trade_history": list(getattr(trade_state, TRADE_HISTORY_ATTR, ()) or ()),
    }
    return stable_digest(payload)


def apply_rfa_board(
    simulation_state: Any,
    trade_state: Any,
    board_rows: list[dict[str, str]],
) -> dict[str, Any]:
    simulation_candidate = copy.deepcopy(simulation_state)
    trade_candidate = copy.deepcopy(trade_state)
    board_by_id = {pid(row.get("player_id")): dict(row) for row in board_rows}
    if len(board_rows) != 64 or len(board_by_id) != 64:
        raise RuntimeError("RFA application board must contain exactly 64 unique players.")

    market_rows = copy.deepcopy(list(getattr(simulation_candidate, MARKET_AMOUNT_ATTR, ()) or ()))
    market_by_id = {pid(row.get("player_id")): row for row in market_rows}
    if len(market_rows) != 226 or len(market_by_id) != 226:
        raise RuntimeError("Clone must expose exactly 226 unique market amount rows.")
    if not set(board_by_id).issubset(market_by_id):
        raise RuntimeError("The 64-player RFA board is not an exact subset of the clone market.")

    charges_by_team: dict[str, float] = defaultdict(float)
    applied_rows: list[dict[str, Any]] = []
    for player_id in sorted(board_by_id, key=int):
        source = board_by_id[player_id]
        rights = clean(source.get("executable_rights_decision"))
        qo = clean(source.get("executable_qo_decision"))
        prior_team = clean(source.get("prior_team")).upper()
        charge = amount(source.get("effective_charge_if_recommended_branch")) or 0.0
        if rights == "renounce_rights":
            if qo != "not_applicable_after_rights_renouncement" or charge != 0:
                raise RuntimeError(f"Incoherent renouncement row for {player_id}.")
            cap_hold_applied = False
        elif rights == "retain_rights":
            if qo not in {"issue_qo", "do_not_issue_qo"} or charge <= 0:
                raise RuntimeError(f"Incoherent retained-rights row for {player_id}.")
            cap_hold_applied = True
            charges_by_team[prior_team] += charge
        else:
            raise RuntimeError(f"Unknown rights decision for {player_id}: {rights!r}")

        controlled = player_id in EXPECTED_CONTROLLED_IDS
        applied = {
            "player_id": player_id,
            "player_name": clean(source.get("player_name")),
            "prior_team": prior_team,
            "rights_classification": clean(source.get("rights_classification")),
            "free_agent_amount_2026_27": amount(source.get("free_agent_amount_2026_27")),
            "qo_amount_2026_27": amount(source.get("qo_amount_2026_27")),
            "rights_decision": rights,
            "qo_decision": qo,
            "effective_charge_2026_27": charge,
            "controlled_team_decision": controlled,
            "decision_source": (
                "recommended_chicago_branch_clone_preview"
                if controlled
                else "frozen_automatic_recommendation"
            ),
            "rights_decision_applied_to_clone": True,
            "qo_decision_applied_to_clone": True,
            "cap_hold_applied_to_clone": cap_hold_applied,
            "applied_to_canonical": False,
        }
        applied_rows.append(applied)

        market_row = market_by_id[player_id]
        market_row.update({
            "rights_decision": rights,
            "qo_decision": qo,
            "qo_amount_2026_27": applied["qo_amount_2026_27"],
            "effective_charge_2026_27": charge,
            "rights_decision_applied": True,
            "qo_decision_applied": True,
            "cap_hold_applied": cap_hold_applied,
            "decision_source": applied["decision_source"],
        })

    team_deltas: list[dict[str, Any]] = []
    for code, financial in sorted(trade_candidate.team_financials.items()):
        team = clean(code).upper()
        before_team_salary = float(financial.team_salary)
        before_apron_salary = float(financial.apron_salary)
        charge = round(float(charges_by_team.get(team, 0.0)), 2)
        financial.team_salary = round(before_team_salary + charge, 2)
        financial.apron_salary = round(before_apron_salary + charge, 2)
        team_rows = [row for row in applied_rows if row["prior_team"] == team]
        team_deltas.append({
            "team": team,
            "rfa_decision_count": len(team_rows),
            "rights_retained_count": sum(row["rights_decision"] == "retain_rights" for row in team_rows),
            "rights_renounced_count": sum(row["rights_decision"] == "renounce_rights" for row in team_rows),
            "qualifying_offers_issued": sum(row["qo_decision"] == "issue_qo" for row in team_rows),
            "rfa_effective_charge_applied": charge,
            "trade_team_salary_before": before_team_salary,
            "trade_team_salary_after": float(financial.team_salary),
            "trade_apron_salary_before": before_apron_salary,
            "trade_apron_salary_after": float(financial.apron_salary),
            "applied_to_canonical": False,
        })

    snapshots = list(getattr(trade_candidate, "undo_stack", ()) or ())
    initial_snapshot = getattr(trade_candidate, "initial_snapshot", None)
    if initial_snapshot is not None:
        snapshots.append(initial_snapshot)
    for snapshot in snapshots:
        snapshot.team_financials = copy.deepcopy(trade_candidate.team_financials)

    setattr(simulation_candidate, MARKET_AMOUNT_ATTR, copy.deepcopy(market_rows))
    setattr(trade_candidate, MARKET_AMOUNT_ATTR, copy.deepcopy(market_rows))
    setattr(simulation_candidate, RFA_LEDGER_ATTR, copy.deepcopy(applied_rows))
    setattr(trade_candidate, RFA_LEDGER_ATTR, copy.deepcopy(applied_rows))

    event = {
        "transaction_id": "OFFSEASON-RFA-RIGHTS-QO-2026-0002",
        "version": VERSION,
        "rfa_decision_count": 64,
        "rights_retained_count": 49,
        "rights_renounced_count": 15,
        "qualifying_offers_issued": 41,
        "cap_holds_applied": 49,
        "rfa_effective_charge_applied": 118_851_771.0,
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
        "applied_rows": applied_rows,
        "market_rows": market_rows,
        "team_deltas": team_deltas,
        "event": event,
        "snapshot_count": len(snapshots),
    }


def main() -> int:
    root = Path.cwd().resolve()
    src = root / "src"
    if not src.exists():
        raise RuntimeError("Run from the NBA_Roster_Optimization_Engine project root.")

    preview_zip = find_passed(
        root,
        "fa_rfa_rights_qo_controlled_team_preview_v1_2026-27_*.zip",
        "rfa_rights_qo_preview_summary.json",
    )
    successful_clone_zip = find_passed(
        root,
        "fa_offseason_transaction_clone_candidate_hotfix_v1_0_1_2026-27_*.zip",
        "clone_candidate_summary.json",
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

    with zipfile.ZipFile(preview_zip) as archive:
        preview_summary = json_suffix(archive, "rfa_rights_qo_preview_summary.json")
        preview_checks = csv_suffix(archive, "rfa_rights_qo_preview_checks.csv")
        board = csv_suffix(archive, "rfa_rights_qo_decision_board_64.csv")
    with zipfile.ZipFile(successful_clone_zip) as archive:
        successful_clone_summary = json_suffix(archive, "clone_candidate_summary.json")
        successful_clone_checks = csv_suffix(archive, "clone_candidate_checks.csv")
    with zipfile.ZipFile(clone_input_zip) as archive:
        clone_input_summary = json_suffix(archive, "clone_application_summary.json")
        automatic = csv_suffix(archive, "automatic_decisions_applied_109.csv")
        pending = csv_suffix(archive, "user_decisions_pending_2.csv")
        owner_ledger = csv_suffix(archive, "clone_owner_ledger_587.csv")
    with zipfile.ZipFile(market_zip) as archive:
        market_summary = json_suffix(archive, "full_market_free_agent_amount_summary.json")
        market_rows = csv_suffix(archive, "full_market_free_agent_amounts_complete_226.csv")

    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
    import simulation_franchise_checkpoint_v1 as checkpoint_module
    from freeform_trade_machine_engine_v3 import load_runtime_data
    from franchise_offseason_transaction_application_v1 import (
        VERSION as APPLICATION_VERSION,
        build_offseason_transaction_candidates,
        validate_offseason_transition_state,
    )
    from mutable_league_state_v1 import validate_state

    if APPLICATION_VERSION != "franchise-offseason-transaction-application-v1.0.1-2026-08-16":
        raise RuntimeError(f"Unexpected application interface version: {APPLICATION_VERSION}")

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
        raise RuntimeError("Canonical checkpoint changed before RFA clone application.")
    if canonical_simulation_digest_before != EXPECTED_SIMULATION_DIGEST:
        raise RuntimeError("Canonical simulation state changed before RFA clone application.")
    if canonical_trade_digest_before != EXPECTED_TRADE_DIGEST:
        raise RuntimeError("Canonical Trade Machine state changed before RFA clone application.")

    print("=" * 132)
    print("2026 RFA RIGHTS/QO RECOMMENDED-BRANCH CLONE APPLY V1")
    print("=" * 132)
    print("Rebuilding the passed offseason clone and applying the complete 64-player RFA board...")

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
    base_simulation = base["simulation_candidate"]
    base_trade = base["trade_candidate"]
    base_simulation_structure_digest = stable_digest(simulation_structure(base_simulation))
    base_trade_ownership_digest = stable_digest(trade_ownership_structure(base_trade))

    result = apply_rfa_board(base_simulation, base_trade, board)
    repeat = apply_rfa_board(base_simulation, base_trade, board)
    simulation_candidate = result["simulation_candidate"]
    trade_candidate = result["trade_candidate"]
    applied_rows = result["applied_rows"]
    team_deltas = result["team_deltas"]
    final_market_rows = result["market_rows"]

    sim_checks = validate_offseason_transition_state(simulation_candidate)
    trade_checks = validate_state(trade_candidate, runtime)
    candidate_bytes = pickle.dumps(
        (simulation_candidate, trade_candidate), protocol=pickle.HIGHEST_PROTOCOL
    )
    reloaded_simulation, reloaded_trade = pickle.loads(candidate_bytes)
    validate_offseason_transition_state(reloaded_simulation)
    validate_state(reloaded_trade, runtime)

    rights_counts = Counter(row["rights_decision"] for row in applied_rows)
    qo_counts = Counter(row["qo_decision"] for row in applied_rows)
    controlled_rows = [row for row in applied_rows if row["controlled_team_decision"]]
    retained_rows = [row for row in applied_rows if row["rights_decision"] == "retain_rights"]
    renounced_rows = [row for row in applied_rows if row["rights_decision"] == "renounce_rights"]
    total_charge = round(sum(float(row["effective_charge_2026_27"]) for row in applied_rows), 2)
    team_charge_total = round(sum(float(row["rfa_effective_charge_applied"]) for row in team_deltas), 2)
    market_by_id = {pid(row.get("player_id")): row for row in final_market_rows}
    board_ids = {row["player_id"] for row in applied_rows}
    non_rfa_rows = [row for row in final_market_rows if pid(row.get("player_id")) not in board_ids]

    snapshot_rows = list(getattr(trade_candidate, "undo_stack", ()) or ())
    if getattr(trade_candidate, "initial_snapshot", None) is not None:
        snapshot_rows.append(trade_candidate.initial_snapshot)
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
        for snapshot in snapshot_rows
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
    print("Validating clone-only RFA application invariants...")
    add(
        "upstream_rfa_preview_passed_all_24_checks",
        preview_summary.get("passed") is True
        and preview_summary.get("ready_for_controlled_team_confirmation") is True
        and len(preview_checks) == 24
        and all(clean(row.get("status")) == "PASS" for row in preview_checks),
        preview_zip.name,
    )
    add(
        "upstream_clone_candidate_passed_all_34_checks",
        successful_clone_summary.get("passed") is True
        and successful_clone_summary.get("ready_for_rights_qo_resolution") is True
        and len(successful_clone_checks) == 34
        and all(clean(row.get("status")) == "PASS" for row in successful_clone_checks),
        successful_clone_zip.name,
    )
    add(
        "clone_inputs_and_market_gate_are_exact",
        clone_input_summary.get("passed") is True
        and market_summary.get("passed") is True
        and len(owner_ledger) == 587
        and len(market_rows) == 226,
        "587 ownership / 226 market",
    )
    add(
        "exact_64_unique_rfa_decisions_applied_to_clone",
        len(applied_rows) == len(board_ids) == 64
        and all(row["rights_decision_applied_to_clone"] for row in applied_rows)
        and all(row["qo_decision_applied_to_clone"] for row in applied_rows),
        f"{len(applied_rows)}/64",
    )
    add(
        "recommended_chicago_branch_is_exact",
        {row["player_id"] for row in controlled_rows} == EXPECTED_CONTROLLED_IDS
        and {(row["player_id"], row["rights_decision"], row["qo_decision"]) for row in controlled_rows}
        == {
            ("1631338", "renounce_rights", "not_applicable_after_rights_renouncement"),
            ("1642530", "retain_rights", "issue_qo"),
            ("1642950", "retain_rights", "issue_qo"),
        },
        "Gueye renounce; Kawamura/Olbrich retain + QO",
    )
    add(
        "rights_distribution_is_49_retain_15_renounce",
        rights_counts == Counter({"retain_rights": 49, "renounce_rights": 15}),
        repr(dict(rights_counts)),
    )
    add(
        "executable_qo_distribution_is_41_issue_8_no_15_not_applicable",
        qo_counts == Counter({
            "issue_qo": 41,
            "do_not_issue_qo": 8,
            "not_applicable_after_rights_renouncement": 15,
        }),
        repr(dict(qo_counts)),
    )
    add(
        "exact_49_retained_cap_holds_applied",
        len(retained_rows) == 49
        and all(row["cap_hold_applied_to_clone"] for row in retained_rows)
        and all(not row["cap_hold_applied_to_clone"] for row in renounced_rows),
        "49 retained / 15 released",
    )
    add(
        "rfa_effective_charge_total_is_exact",
        total_charge == team_charge_total == 118_851_771.0,
        f"${total_charge:,.0f}",
    )
    add(
        "team_charge_application_covers_exactly_30_teams",
        len(team_deltas) == 30
        and len({row["team"] for row in team_deltas}) == 30
        and all(
            math.isclose(
                float(row["trade_team_salary_after"]),
                float(row["trade_team_salary_before"]) + float(row["rfa_effective_charge_applied"]),
                abs_tol=0.01,
            )
            for row in team_deltas
        ),
        "30/30",
    )
    add(
        "apron_salary_moves_by_the_same_applied_charge",
        all(
            math.isclose(
                float(row["trade_apron_salary_after"]),
                float(row["trade_apron_salary_before"]) + float(row["rfa_effective_charge_applied"]),
                abs_tol=0.01,
            )
            for row in team_deltas
        ),
        "30/30",
    )
    add(
        "market_remains_exactly_226_unique",
        len(final_market_rows) == len(market_by_id) == 226
        and set(market_by_id) == {pid(value) for value in simulation_candidate.free_agent_player_ids},
        "226/226",
    )
    add(
        "all_64_rfa_market_rows_are_marked_applied",
        all(
            market_by_id[player_id].get("rights_decision_applied") is True
            and market_by_id[player_id].get("qo_decision_applied") is True
            for player_id in board_ids
        ),
        "64/64",
    )
    add(
        "all_162_non_rfa_market_rows_remain_unapplied",
        len(non_rfa_rows) == 162
        and all(
            not row.get("rights_decision_applied")
            and not row.get("qo_decision_applied")
            and not row.get("cap_hold_applied")
            for row in non_rfa_rows
        ),
        "162/162 untouched",
    )
    add(
        "simulation_rosters_contracts_and_market_membership_unchanged_from_base_clone",
        stable_digest(simulation_structure(simulation_candidate))
        == base_simulation_structure_digest,
        base_simulation_structure_digest,
    )
    add(
        "trade_ownership_and_contract_counts_unchanged_from_base_clone",
        stable_digest(trade_ownership_structure(trade_candidate))
        == base_trade_ownership_digest,
        base_trade_ownership_digest,
    )
    add(
        "rfa_ledger_is_exactly_mirrored_across_both_clones",
        getattr(simulation_candidate, RFA_LEDGER_ATTR, None)
        == getattr(trade_candidate, RFA_LEDGER_ATTR, None)
        == applied_rows,
        "64/64",
    )
    add(
        "trade_undo_and_reset_snapshots_are_rebased",
        snapshots_rebased and len(snapshot_rows) == result["snapshot_count"],
        f"snapshots={len(snapshot_rows)}",
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
        "clone_application_is_deterministic",
        candidate_semantic_digest(simulation_candidate, trade_candidate)
        == candidate_semantic_digest(
            repeat["simulation_candidate"], repeat["trade_candidate"]
        ),
        "repeat digests exact",
    )
    add(
        "candidate_pickle_round_trip_is_exact",
        candidate_semantic_digest(reloaded_simulation, reloaded_trade)
        == candidate_semantic_digest(simulation_candidate, trade_candidate),
        f"bytes={len(candidate_bytes)}",
    )
    add(
        "application_is_clone_only",
        all(not row["applied_to_canonical"] for row in applied_rows)
        and all(not row["applied_to_canonical"] for row in team_deltas),
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
    export_id = f"fa_rfa_rights_qo_recommended_branch_clone_apply_v1_{SEASON_LABEL}_{timestamp}"
    audit_dir = root / "outputs" / "audits"
    audit_dir.mkdir(parents=True, exist_ok=True)
    audit_zip = audit_dir / f"{export_id}.zip"
    summary = {
        "version": VERSION,
        "season": SEASON_LABEL,
        "passed": not failed,
        "failed_checks": failed,
        "source_rfa_preview_audit": preview_zip.name,
        "source_clone_candidate_audit": successful_clone_zip.name,
        "rfa_decision_count": len(applied_rows),
        "rights_retained_count": len(retained_rows),
        "rights_renounced_count": len(renounced_rows),
        "qualifying_offers_issued": qo_counts.get("issue_qo", 0),
        "qualifying_offers_not_issued": qo_counts.get("do_not_issue_qo", 0),
        "qualifying_offers_not_applicable_after_renouncement": qo_counts.get(
            "not_applicable_after_rights_renouncement", 0
        ),
        "controlled_team": CONTROLLED_TEAM,
        "controlled_team_branch": {
            "Mouhamadou Gueye": "renounce_rights / no_QO",
            "Yuki Kawamura": "retain_rights / issue_QO",
            "Lachlan Olbrich": "retain_rights / issue_QO",
        },
        "rfa_effective_charge_applied_to_clone": total_charge,
        "teams_updated_on_clone": 30,
        "non_rfa_market_rows_unchanged": len(non_rfa_rows),
        "simulation_candidate_created": True,
        "trade_candidate_created": True,
        "state_mutation_performed": False,
        "rights_overlay_write_performed": False,
        "checkpoint_write_performed": False,
        "ready_for_non_rfa_rights_clone_application": not failed,
        "next_slice": (
            "Clone-apply the frozen 162-player non-RFA rights board and its retained Free Agent "
            "Amounts, then reconcile the combined 226-player rights charge against the completed "
            "30-team salary-component registry before a temporary checkpoint rehearsal."
        ),
    }
    readme = f"""2026 RFA RIGHTS/QO RECOMMENDED-BRANCH CLONE APPLY V1
=======================================================

Result
------
- Audit passed: {not failed}
- RFA decisions applied to clones: {len(applied_rows)}/64
- Rights retained / renounced: {len(retained_rows)} / {len(renounced_rows)}
- Qualifying offers issued: {qo_counts.get('issue_qo', 0)}
- Retained effective charge applied: ${total_charge:,.0f}
- Non-RFA market rows changed: 0/162

Recommended Chicago branch
--------------------------
- Mouhamadou Gueye: renounce rights; no qualifying offer
- Yuki Kawamura: retain rights; issue qualifying offer
- Lachlan Olbrich: retain rights; issue qualifying offer

Safety
------
The complete RFA board and retained charges were applied only to reconstructed
simulation and Trade Machine clones. No canonical state, rights overlay, or
checkpoint was written.
"""

    with tempfile.TemporaryDirectory(prefix="fa_rfa_clone_apply_") as temporary:
        export = Path(temporary) / export_id
        export.mkdir(parents=True)
        write_csv(export / "rfa_rights_qo_decisions_applied_64.csv", applied_rows)
        write_csv(export / "rfa_retained_cap_holds_applied_49.csv", retained_rows)
        write_csv(export / "rfa_renouncements_applied_15.csv", renounced_rows)
        write_csv(export / "rfa_team_financial_deltas_30.csv", team_deltas)
        write_csv(export / "full_market_amount_ledger_after_rfa_application_226.csv", final_market_rows)
        write_csv(
            export / "rfa_clone_application_checks.csv",
            checks,
            ["check_id", "status", "severity", "detail"],
        )
        (export / "rfa_clone_application_summary.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8"
        )
        (export / "README.txt").write_text(readme, encoding="utf-8")
        with zipfile.ZipFile(audit_zip, "w", zipfile.ZIP_DEFLATED) as archive:
            for item in sorted(export.iterdir()):
                archive.write(item, arcname=f"{export_id}/{item.name}")

    print("")
    print("=" * 132)
    print(
        "2026 RFA RIGHTS/QO RECOMMENDED-BRANCH CLONE APPLY V1 "
        + ("PASSED" if not failed else "FAILED")
    )
    print("=" * 132)
    print("RFA decisions applied:          64/64 (CLONE ONLY)")
    print("Rights retained / renounced:    49 / 15")
    print("Qualifying offers issued:       41")
    print("Retained cap holds applied:     49")
    print("RFA effective charge:       $118,851,771")
    print("Non-RFA rows changed:             0/162")
    print("Canonical mutation:          NOT PERFORMED")
    print("Rights overlay write:        NOT PERFORMED")
    print("Checkpoint write:            NOT PERFORMED")
    print(f"Audit ZIP: {audit_zip}")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
