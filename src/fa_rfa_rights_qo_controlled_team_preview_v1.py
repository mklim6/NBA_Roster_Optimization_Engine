from __future__ import annotations

import csv
import hashlib
import io
import json
import pickle
import tempfile
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


VERSION = "fa-rfa-rights-qo-controlled-team-preview-v1-2026-08-16"
SEASON_LABEL = "2026-27"
CONTROLLED_TEAM = "CHI"
EXPECTED_CHECKPOINT_SHA256 = (
    "19f2fee601f5765bde4f5fabea34f20dc9b8ddc8dd5069186502dff08fc0cf9f"
)
EXPECTED_SIMULATION_DIGEST = (
    "f92f03b4c54e53f8f017c3fca43e93ccd09c8b8ba0e5fe0323f418021baf268e"
)
EXPECTED_CONTROLLED_IDS = {"1631338", "1642530", "1642950"}
NBA_TEAMS = (
    "ATL", "BOS", "BKN", "CHA", "CHI", "CLE", "DAL", "DEN", "DET", "GSW",
    "HOU", "IND", "LAC", "LAL", "MEM", "MIA", "MIL", "MIN", "NOP", "NYK",
    "OKC", "ORL", "PHI", "PHX", "POR", "SAC", "SAS", "TOR", "UTA", "WAS",
)


def clean(value: Any) -> str:
    return str(value or "").strip()


def pid(value: Any) -> str:
    text = clean(value)
    return text[:-2] if text.endswith(".0") and text[:-2].isdigit() else text


def as_bool(value: Any) -> bool:
    return value is True or clean(value).lower() in {"true", "1", "yes", "y"}


def amount(value: Any) -> float | None:
    text = clean(value).replace("$", "").replace(",", "")
    if not text:
        return None
    result = float(text)
    if result < 0:
        raise RuntimeError(f"Negative amount is invalid: {value!r}")
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


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row:
            if key not in seen:
                seen.add(key)
                fields.append(key)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        if not fields:
            return
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    root = Path.cwd().resolve()
    clone_zip = find_passed(
        root,
        "fa_offseason_transaction_clone_candidate_hotfix_v1_0_1_2026-27_*.zip",
        "clone_candidate_summary.json",
    )
    posture_zip = find_passed(
        root,
        "fa_team_base_salary_and_rights_posture_preview_v1_2026-27_*.zip",
        "team_base_salary_and_rights_posture_summary.json",
    )
    amount_zip = find_passed(
        root,
        "fa_full_market_free_agent_amount_completion_v1_2026-27_*.zip",
        "full_market_free_agent_amount_summary.json",
    )

    with zipfile.ZipFile(clone_zip) as archive:
        clone_summary = json_suffix(archive, "clone_candidate_summary.json")
        clone_checks = csv_suffix(archive, "clone_candidate_checks.csv")
    with zipfile.ZipFile(posture_zip) as archive:
        posture_summary = json_suffix(archive, "team_base_salary_and_rights_posture_summary.json")
        scenario_rows = csv_suffix(archive, "full_market_rights_scenario_inputs_170.csv")
    with zipfile.ZipFile(amount_zip) as archive:
        amount_summary = json_suffix(archive, "full_market_free_agent_amount_summary.json")
        exact_amount_rows = csv_suffix(archive, "full_market_exact_rfa_amounts_64.csv")

    rfa_rows = [row for row in scenario_rows if clean(row.get("market_category")) == "rfa_exact"]
    exact_by_id = {pid(row.get("player_id")): row for row in exact_amount_rows}
    rfa_ids = [pid(row.get("player_id")) for row in rfa_rows]
    duplicate_ids = len(rfa_ids) != len(set(rfa_ids))

    board: list[dict[str, Any]] = []
    normalizations: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    for source in sorted(rfa_rows, key=lambda row: int(pid(row.get("player_id")))):
        player_id = pid(source.get("player_id"))
        exact = exact_by_id.get(player_id)
        if exact is None:
            conflicts.append({
                "player_id": player_id,
                "player_name": clean(source.get("player_name")),
                "conflict_type": "missing_exact_rfa_amount_row",
                "detail": "",
            })
            continue
        raw_rights = clean(source.get("rfa_model_recommendation"))
        raw_qo = clean(source.get("qo_model_recommendation"))
        executable_qo = (
            "not_applicable_after_rights_renouncement"
            if raw_rights == "renounce_rights"
            else raw_qo
        )
        prior_team = clean(source.get("prior_team")).upper()
        controlled = prior_team == CONTROLLED_TEAM
        free_agent_amount = amount(source.get("free_agent_amount_2026_27"))
        qo_amount = amount(source.get("qo_amount_2026_27"))
        effective_charge = amount(source.get("effective_charge_under_model_qo"))
        frozen_charge = None
        if not controlled:
            frozen_charge = effective_charge if raw_rights == "retain_rights" else 0.0

        row = {
            "player_id": player_id,
            "player_name": clean(source.get("player_name")),
            "prior_team": prior_team,
            "rights_classification": clean(source.get("rights_classification")),
            "free_agent_amount_2026_27": free_agent_amount,
            "qo_amount_2026_27": qo_amount,
            "raw_rights_model_recommendation": raw_rights,
            "raw_qo_model_recommendation": raw_qo,
            "executable_rights_decision": raw_rights,
            "executable_qo_decision": executable_qo,
            "effective_charge_if_recommended_branch": (
                effective_charge if raw_rights == "retain_rights" else 0.0
            ),
            "controlled_team_decision": controlled,
            "decision_status": (
                "pending_controlled_team_confirmation"
                if controlled
                else "automatic_recommendation_frozen_for_clone_apply"
            ),
            "frozen_charge_for_next_clone_apply": frozen_charge,
            "rights_decision_applied_to_simulation": False,
            "qo_decision_applied_to_simulation": False,
            "cap_hold_applied_to_simulation": False,
            "state_mutation_applied": False,
            "amount_evidence_mode": clean(exact.get("amount_evidence_mode")),
            "amount_evidence_url": clean(exact.get("amount_evidence_url")),
        }
        board.append(row)
        if raw_rights == "renounce_rights" and raw_qo == "issue_qo":
            normalizations.append({
                "player_id": player_id,
                "player_name": row["player_name"],
                "prior_team": prior_team,
                "raw_rights_recommendation": raw_rights,
                "raw_qo_recommendation": raw_qo,
                "executable_qo_decision": executable_qo,
                "reason": "Renouncing all free-agent rights makes an issued qualifying offer non-executable.",
            })

    automatic = [row for row in board if not row["controlled_team_decision"]]
    pending = [row for row in board if row["controlled_team_decision"]]
    rights_counts = Counter(row["raw_rights_model_recommendation"] for row in board)
    raw_qo_counts = Counter(row["raw_qo_model_recommendation"] for row in board)
    pair_counts = Counter(
        (row["executable_rights_decision"], row["executable_qo_decision"])
        for row in board
    )
    automatic_rights_counts = Counter(row["executable_rights_decision"] for row in automatic)
    automatic_qo_counts = Counter(row["executable_qo_decision"] for row in automatic)

    team_rows: list[dict[str, Any]] = []
    for team in NBA_TEAMS:
        rows = [row for row in board if row["prior_team"] == team]
        auto = [row for row in rows if not row["controlled_team_decision"]]
        team_rows.append({
            "team": team,
            "rfa_decision_count": len(rows),
            "automatic_frozen_count": len(auto),
            "controlled_pending_count": len(rows) - len(auto),
            "automatic_retain_count": sum(row["executable_rights_decision"] == "retain_rights" for row in auto),
            "automatic_renounce_count": sum(row["executable_rights_decision"] == "renounce_rights" for row in auto),
            "automatic_issue_qo_count": sum(row["executable_qo_decision"] == "issue_qo" for row in auto),
            "automatic_retained_charge_for_next_clone_apply": sum(
                float(row["frozen_charge_for_next_clone_apply"] or 0) for row in auto
            ),
            "charges_applied_to_simulation": 0,
        })

    import simulation_franchise_checkpoint_v1 as checkpoint_module

    checkpoint_path = Path(checkpoint_module.DEFAULT_CHECKPOINT_PATH)
    checkpoint_hash_before = sha256_file(checkpoint_path)
    checkpoint = checkpoint_module.load_franchise_checkpoint()
    if checkpoint is None:
        raise RuntimeError("Canonical checkpoint could not be loaded.")
    simulation_digest_before = object_digest(checkpoint.simulation_state)
    trade_digest_before = object_digest(checkpoint.trade_state)
    overlay_path = root / "outputs" / "runtime" / "free_agency_rights_population_v1.json"
    overlay_existed_before = overlay_path.exists()
    overlay_hash_before = sha256_file(overlay_path) if overlay_existed_before else ""
    if checkpoint_hash_before != EXPECTED_CHECKPOINT_SHA256:
        raise RuntimeError("Canonical checkpoint changed before RFA rights/QO preview.")

    checks: list[dict[str, str]] = []

    def add(check_id: str, passed: bool, detail: str) -> None:
        checks.append({
            "check_id": check_id,
            "status": "PASS" if passed else "FAIL",
            "severity": "strict",
            "detail": detail,
        })
        print(f"  {check_id}: {'PASS' if passed else 'FAIL'}")

    print("=" * 132)
    print("2026 RFA RIGHTS/QO CONTROLLED-TEAM PREVIEW V1")
    print("=" * 132)
    print("Freezing 61 automatic recommendations and isolating the three Chicago choices...")
    print("")
    print("Validating RFA decision-board invariants...")

    add(
        "successful_34_of_34_clone_candidate_is_upstream_gate",
        clone_summary.get("passed") is True
        and clone_summary.get("ready_for_rights_qo_resolution") is True
        and len(clone_checks) == 34
        and all(clean(row.get("status")) == "PASS" for row in clone_checks),
        clone_zip.name,
    )
    add(
        "team_posture_and_exact_amount_audits_passed",
        posture_summary.get("passed") is True and amount_summary.get("passed") is True,
        f"{posture_zip.name} | {amount_zip.name}",
    )
    add(
        "exact_64_unique_rfa_decision_rows",
        len(board) == 64 and not duplicate_ids and len({row["player_id"] for row in board}) == 64,
        f"{len(board)}/64",
    )
    add(
        "exact_rfa_amount_registry_matches_decision_board",
        set(exact_by_id) == {row["player_id"] for row in board} and len(exact_by_id) == 64,
        f"{len(exact_by_id)}/64",
    )
    add(
        "rfa_free_agent_amount_total_is_exact",
        sum(float(row["free_agent_amount_2026_27"] or 0) for row in board) == 232_178_464.0,
        "$232,178,464",
    )
    add(
        "raw_rights_distribution_is_49_retain_15_renounce",
        rights_counts == Counter({"retain_rights": 49, "renounce_rights": 15}),
        repr(dict(rights_counts)),
    )
    add(
        "raw_qo_distribution_is_44_issue_20_no_qo",
        raw_qo_counts == Counter({"issue_qo": 44, "do_not_issue_qo": 20}),
        repr(dict(raw_qo_counts)),
    )
    add(
        "three_renounce_plus_issue_pairs_are_semantically_normalized",
        len(normalizations) == 3
        and all(row["executable_qo_decision"] == "not_applicable_after_rights_renouncement" for row in normalizations),
        f"{len(normalizations)}/3",
    )
    add(
        "all_64_executable_decision_pairs_are_coherent",
        all(
            not (
                row["executable_rights_decision"] == "renounce_rights"
                and row["executable_qo_decision"] == "issue_qo"
            )
            for row in board
        ),
        repr({f"{a}|{b}": n for (a, b), n in sorted(pair_counts.items())}),
    )
    add(
        "exact_61_automatic_and_3_controlled_partition",
        len(automatic) == 61 and len(pending) == 3,
        f"automatic={len(automatic)}, controlled={len(pending)}",
    )
    add(
        "controlled_queue_is_exactly_three_chicago_players",
        {row["player_id"] for row in pending} == EXPECTED_CONTROLLED_IDS
        and all(row["prior_team"] == CONTROLLED_TEAM for row in pending),
        repr(sorted(row["player_name"] for row in pending)),
    )
    add(
        "controlled_recommendations_are_one_renounce_two_retain",
        Counter(row["executable_rights_decision"] for row in pending)
        == Counter({"retain_rights": 2, "renounce_rights": 1}),
        "Gueye renounce; Kawamura and Olbrich retain",
    )
    add(
        "controlled_qo_recommendations_are_one_no_two_issue",
        Counter(row["executable_qo_decision"] for row in pending)
        == Counter({"issue_qo": 2, "not_applicable_after_rights_renouncement": 1}),
        "Gueye no QO; Kawamura and Olbrich issue",
    )
    add(
        "automatic_rights_distribution_is_47_retain_14_renounce",
        automatic_rights_counts == Counter({"retain_rights": 47, "renounce_rights": 14}),
        repr(dict(automatic_rights_counts)),
    )
    add(
        "automatic_executable_qo_distribution_is_39_issue_22_no_or_not_applicable",
        automatic_qo_counts.get("issue_qo") == 39
        and sum(value for key, value in automatic_qo_counts.items() if key != "issue_qo") == 22,
        repr(dict(automatic_qo_counts)),
    )
    add(
        "automatic_retained_charge_total_is_exact",
        sum(float(row["frozen_charge_for_next_clone_apply"] or 0) for row in automatic)
        == 115_044_586.0,
        "$115,044,586",
    )
    add(
        "all_recommended_retained_charge_total_is_exact",
        sum(float(row["effective_charge_if_recommended_branch"] or 0) for row in board)
        == 118_851_771.0,
        "$118,851,771",
    )
    add(
        "team_preview_covers_exactly_30_teams",
        len(team_rows) == 30 and {row["team"] for row in team_rows} == set(NBA_TEAMS),
        "30/30",
    )
    add("semantic_conflicts_are_zero", not conflicts, f"conflicts={len(conflicts)}")
    add(
        "no_rights_qo_or_cap_hold_was_applied",
        all(
            not row["rights_decision_applied_to_simulation"]
            and not row["qo_decision_applied_to_simulation"]
            and not row["cap_hold_applied_to_simulation"]
            and not row["state_mutation_applied"]
            for row in board
        ),
        "preview only",
    )

    checkpoint_after = checkpoint_module.load_franchise_checkpoint()
    checkpoint_hash_after = sha256_file(checkpoint_path)
    overlay_existed_after = overlay_path.exists()
    overlay_hash_after = sha256_file(overlay_path) if overlay_existed_after else ""
    add(
        "loaded_simulation_state_unchanged",
        simulation_digest_before
        == object_digest(checkpoint_after.simulation_state)
        == EXPECTED_SIMULATION_DIGEST,
        simulation_digest_before,
    )
    add(
        "loaded_trade_state_unchanged",
        trade_digest_before == object_digest(checkpoint_after.trade_state),
        trade_digest_before,
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
    export_id = f"fa_rfa_rights_qo_controlled_team_preview_v1_{SEASON_LABEL}_{timestamp}"
    audit_dir = root / "outputs" / "audits"
    audit_dir.mkdir(parents=True, exist_ok=True)
    audit_zip = audit_dir / f"{export_id}.zip"
    summary = {
        "version": VERSION,
        "season": SEASON_LABEL,
        "passed": not failed,
        "failed_checks": failed,
        "rfa_decision_count": len(board),
        "automatic_recommendation_count": len(automatic),
        "controlled_team_pending_count": len(pending),
        "controlled_team": CONTROLLED_TEAM,
        "controlled_team_pending_ids": sorted(row["player_id"] for row in pending),
        "raw_rights_recommendation_counts": dict(rights_counts),
        "raw_qo_recommendation_counts": dict(raw_qo_counts),
        "semantic_normalization_count": len(normalizations),
        "automatic_retained_charge_for_next_clone_apply": 115_044_586,
        "all_recommended_retained_charge": 118_851_771,
        "rights_decisions_applied": 0,
        "qo_decisions_applied": 0,
        "cap_holds_applied": 0,
        "state_mutation_performed": False,
        "checkpoint_write_performed": False,
        "source_clone_candidate_audit": clone_zip.name,
        "source_team_posture_audit": posture_zip.name,
        "source_exact_amount_audit": amount_zip.name,
        "ready_for_controlled_team_confirmation": not failed,
        "next_slice": (
            "Confirm or override the three CHI recommendations: renounce/no-QO Mouhamadou Gueye; "
            "retain/issue-QO Yuki Kawamura; retain/issue-QO Lachlan Olbrich. Then clone-apply "
            "all 64 coherent RFA decisions and only the retained effective charges."
        ),
    }

    readme = """2026 RFA RIGHTS/QO CONTROLLED-TEAM PREVIEW V1
================================================

This preview freezes the 61 non-CHI model recommendations and isolates the
three controlled Chicago choices. It also converts three raw
renounce-rights/issue-QO pairs into the only executable interpretation: once
rights are renounced, the QO is not applicable.

Recommended Chicago branch
--------------------------
- Mouhamadou Gueye: renounce rights, no qualifying offer
- Yuki Kawamura: retain rights, issue qualifying offer
- Lachlan Olbrich: retain rights, issue qualifying offer

No rights decision, qualifying offer, cap hold, simulation state, rights
overlay, Trade Machine state, or checkpoint is mutated by this preview.
"""

    with tempfile.TemporaryDirectory(prefix="fa_rfa_rights_qo_preview_") as temporary:
        export = Path(temporary) / export_id
        export.mkdir(parents=True)
        write_csv(export / "rfa_rights_qo_decision_board_64.csv", board)
        write_csv(export / "rfa_automatic_recommendations_frozen_61.csv", automatic)
        write_csv(export / "rfa_controlled_chicago_decisions_pending_3.csv", pending)
        write_csv(export / "rfa_qo_semantic_normalizations_3.csv", normalizations)
        write_csv(export / "rfa_team_charge_preview_30.csv", team_rows)
        write_csv(export / "rfa_rights_qo_preview_conflicts.csv", conflicts)
        write_csv(export / "rfa_rights_qo_preview_checks.csv", checks)
        (export / "rfa_rights_qo_preview_summary.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8"
        )
        (export / "README.txt").write_text(readme, encoding="utf-8")
        with zipfile.ZipFile(audit_zip, "w", zipfile.ZIP_DEFLATED) as archive:
            for item in sorted(export.iterdir()):
                archive.write(item, arcname=f"{export_id}/{item.name}")

    print("")
    print("=" * 132)
    print(f"2026 RFA RIGHTS/QO CONTROLLED-TEAM PREVIEW V1 {'PASSED' if not failed else 'FAILED'}")
    print("=" * 132)
    print("RFA decision board:              64/64")
    print("Automatic recommendations:       61/61 FROZEN")
    print("Controlled CHI decisions:          3 PENDING")
    print("Raw retain / renounce:             49 / 15")
    print("Raw issue-QO / no-QO:              44 / 20")
    print("Semantic QO normalizations:         3/3")
    print("Automatic retained charge:  $115,044,586")
    print("All-recommended charge:      $118,851,771")
    print("Rights/QO/cap holds applied:          0")
    print("Canonical mutation:           NOT PERFORMED")
    print("Checkpoint write:             NOT PERFORMED")
    print(f"Audit ZIP: {audit_zip}")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
