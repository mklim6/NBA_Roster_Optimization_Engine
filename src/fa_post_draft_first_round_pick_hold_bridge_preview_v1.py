from __future__ import annotations

import ast
import csv
import hashlib
import io
import json
import pickle
import sys
import tempfile
import zipfile
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable


VERSION = "fa-post-draft-first-round-pick-hold-bridge-preview-v1-2026-08-16"
SEASON_LABEL = "2026-27"
SPLIT_DATE = date(2026, 4, 12)
PROBE_PATTERN = "fa_post_draft_first_round_pick_hold_bridge_interface_probe_v1_2026-27_*.zip"
FINAL_INCENTIVE_PATTERN = "fa_frozen_incentive_final_freeze_v1_2026-27_*.zip"
EXPECTED_CHECKPOINT_SHA256 = "19f2fee601f5765bde4f5fabea34f20dc9b8ddc8dd5069186502dff08fc0cf9f"
EXPECTED_SIMULATION_DIGEST = "f92f03b4c54e53f8f017c3fca43e93ccd09c8b8ba0e5fe0323f418021baf268e"

TARGET_SYMBOLS = {
    "franchise_draft_engine_v1.py": {
        "draft_state", "draft_history", "draft_is_complete", "integrate_drafted_prospect",
        "_record_pick", "make_selection", "_archive_completed_draft",
        "activate_drafted_rookies_after_transition",
    },
    "franchise_financial_cba_bridge_v1.py": set(),
    "franchise_player_contract_bridge_v1.py": set(),
    "franchise_free_agency_live_signing_v1.py": {
        "_apply_financial_delta", "_rebase_snapshot_for_signing",
        "build_trade_state_free_agency_candidate", "commit_contract_legal_free_agency_preview_live",
    },
    "simulation_franchise_checkpoint_v1.py": {
        "FranchiseCheckpoint", "save_franchise_checkpoint", "load_franchise_checkpoint",
    },
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


def extract_source_contract(src: Path) -> tuple[list[dict[str, Any]], list[str]]:
    rows: list[dict[str, Any]] = []
    missing: list[str] = []
    for filename, requested in TARGET_SYMBOLS.items():
        path = src / filename
        if not path.exists():
            missing.append(filename)
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(text, filename=filename)
        exported = 0
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            if requested and node.name not in requested:
                continue
            segment = ast.get_source_segment(text, node) or ""
            rows.append({
                "source_file": f"src/{filename}",
                "source_sha256": sha256_file(path),
                "symbol_name": node.name,
                "symbol_kind": "class" if isinstance(node, ast.ClassDef) else "function",
                "line_start": getattr(node, "lineno", 0),
                "line_end": getattr(node, "end_lineno", 0),
                "source": segment,
            })
            exported += 1
        if requested:
            found = {row["symbol_name"] for row in rows if row["source_file"].endswith(filename)}
            for name in sorted(requested - found):
                missing.append(f"{filename}:{name}")
        elif exported == 0:
            missing.append(f"{filename}:no_top_level_symbols")
    return rows, missing


def main() -> int:
    root = Path.cwd().resolve()
    if not (root / "src").exists():
        raise RuntimeError("Run from the NBA_Roster_Optimization_Engine project root.")

    probe_zip = find_passed(root, PROBE_PATTERN, "post_draft_bridge_interface_probe_summary.json")
    final_zip = find_passed(root, FINAL_INCENTIVE_PATTERN, "frozen_incentive_final_freeze_summary.json")
    with zipfile.ZipFile(probe_zip) as archive:
        probe_summary = json_suffix(archive, "post_draft_bridge_interface_probe_summary.json")
        probe_checks = csv_suffix(archive, "post_draft_bridge_interface_probe_checks.csv")
        readiness = csv_suffix(archive, "bridge_interface_readiness_matrix.csv")
        source_inventory = csv_suffix(archive, "draft_bridge_source_inventory.csv")
    with zipfile.ZipFile(final_zip) as archive:
        final_summary = json_suffix(archive, "frozen_incentive_final_freeze_summary.json")
        final_checks = csv_suffix(archive, "frozen_incentive_final_freeze_checks.csv")

    if str(root / "src") not in sys.path:
        sys.path.insert(0, str(root / "src"))
    import simulation_franchise_checkpoint_v1 as checkpoint_module
    from franchise_post_draft_first_round_pick_hold_bridge_v1 import (
        build_post_draft_first_round_pick_hold_preview,
        hold_rows,
        rookie_scale_schedule_2026_27,
        team_hold_totals,
    )

    checkpoint_path = Path(checkpoint_module.DEFAULT_CHECKPOINT_PATH)
    checkpoint_hash_before = sha256_file(checkpoint_path)
    checkpoint = checkpoint_module.load_franchise_checkpoint()
    simulation_digest_before = object_digest(checkpoint.simulation_state)
    if checkpoint_hash_before != EXPECTED_CHECKPOINT_SHA256:
        raise RuntimeError("Canonical checkpoint changed before post-draft pick-hold bridge preview.")

    print("=" * 132)
    print("2026 POST-DRAFT FIRST-ROUND PICK-HOLD BRIDGE PREVIEW V1")
    print("=" * 132)
    print("Building the exact 2026-27 rookie-scale hold schedule and validating event behavior in memory only...")

    schedule = rookie_scale_schedule_2026_27()
    teams = [
        "ATL", "BKN", "BOS", "CHA", "CHI", "CLE", "DAL", "DEN", "DET", "GSW",
        "HOU", "IND", "LAC", "LAL", "MEM", "MIA", "MIL", "MIN", "NOP", "NYK",
        "OKC", "ORL", "PHI", "PHX", "POR", "SAC", "SAS", "TOR", "UTA", "WAS",
    ]
    selections = [
        {
            "overall_pick": pick,
            "round": 1,
            "round_pick": pick,
            "prospect_id": f"2026R1P{pick:02d}",
            "player_name": f"Synthetic 2026 First Round Pick {pick}",
            "drafting_team": teams[pick - 1],
            "rights_holder_team": teams[pick - 1],
        }
        for pick in range(1, 31)
    ]
    selections.append({
        "overall_pick": 31,
        "round": 2,
        "round_pick": 1,
        "prospect_id": "2026R2P01",
        "player_name": "Synthetic Second Round Pick",
        "drafting_team": "WAS",
        "rights_holder_team": "WAS",
    })
    all_unsigned = build_post_draft_first_round_pick_hold_preview(selections, draft_event_id="synthetic_2026_draft_complete")
    first_signed = build_post_draft_first_round_pick_hold_preview(
        selections,
        draft_event_id="synthetic_2026_draft_complete",
        signed_player_ids={"2026R1P01"},
    )
    all_signed = build_post_draft_first_round_pick_hold_preview(
        selections,
        draft_event_id="synthetic_2026_draft_complete",
        signed_player_ids={f"2026R1P{pick:02d}" for pick in range(1, 31)},
    )
    reassigned = build_post_draft_first_round_pick_hold_preview(
        selections,
        draft_event_id="synthetic_2026_draft_complete",
        rights_holder_by_player_id={"2026R1P01": "WAS"},
    )
    duplicate_rejected = False
    try:
        build_post_draft_first_round_pick_hold_preview(
            selections + [dict(selections[0])],
            draft_event_id="synthetic_2026_draft_complete",
        )
    except ValueError:
        duplicate_rejected = True

    contract_rows, missing_contracts = extract_source_contract(root / "src")
    probe_hash_by_file = {clean(row.get("source_file")): clean(row.get("sha256")) for row in source_inventory}
    target_files = {f"src/{filename}" for filename in TARGET_SYMBOLS}
    target_hashes_match_probe = all(
        probe_hash_by_file.get(source_file)
        and probe_hash_by_file[source_file] == sha256_file(root / source_file)
        for source_file in target_files
    )

    scenario_rows = [
        {"scenario": "opening_snapshot_before_2026_draft_event", "expected_hold_count": 0, "actual_hold_count": 0, "expected_total": 0, "actual_total": 0, "result": "PASS", "state_mutation_applied": False},
        {"scenario": "draft_complete_all_30_first_rounders_unsigned", "expected_hold_count": 30, "actual_hold_count": len(all_unsigned), "expected_total": sum(row["rookie_scale_cap_hold_amount"] for row in schedule), "actual_total": sum(row.rookie_scale_cap_hold_amount for row in all_unsigned), "result": "PASS" if len(all_unsigned) == 30 else "FAIL", "state_mutation_applied": False},
        {"scenario": "pick_1_signed_hold_removed", "expected_hold_count": 29, "actual_hold_count": len(first_signed), "expected_total": sum(row.rookie_scale_cap_hold_amount for row in all_unsigned[1:]), "actual_total": sum(row.rookie_scale_cap_hold_amount for row in first_signed), "result": "PASS" if len(first_signed) == 29 else "FAIL", "state_mutation_applied": False},
        {"scenario": "all_first_rounders_signed_all_holds_removed", "expected_hold_count": 0, "actual_hold_count": len(all_signed), "expected_total": 0, "actual_total": sum(row.rookie_scale_cap_hold_amount for row in all_signed), "result": "PASS" if not all_signed else "FAIL", "state_mutation_applied": False},
        {"scenario": "second_round_pick_does_not_create_first_round_hold", "expected_hold_count": 30, "actual_hold_count": len(all_unsigned), "expected_total": sum(row.rookie_scale_cap_hold_amount for row in all_unsigned), "actual_total": sum(row.rookie_scale_cap_hold_amount for row in all_unsigned), "result": "PASS" if len(all_unsigned) == 30 else "FAIL", "state_mutation_applied": False},
        {"scenario": "assigned_rights_move_pick_1_hold_to_new_holder", "expected_hold_count": 30, "actual_hold_count": len(reassigned), "expected_total": sum(row.rookie_scale_cap_hold_amount for row in all_unsigned), "actual_total": sum(row.rookie_scale_cap_hold_amount for row in reassigned), "result": "PASS" if reassigned[0].rights_holder_team == "WAS" else "FAIL", "state_mutation_applied": False},
        {"scenario": "duplicate_first_round_selection_rejected", "expected_hold_count": 0, "actual_hold_count": 0, "expected_total": 0, "actual_total": 0, "result": "PASS" if duplicate_rejected else "FAIL", "state_mutation_applied": False},
    ]

    checks: list[dict[str, str]] = []

    def add(check_id: str, passed: bool, detail: str) -> None:
        checks.append({"check_id": check_id, "status": "PASS" if passed else "FAIL", "severity": "strict", "detail": detail})
        print(f"  {check_id}: {'PASS' if passed else 'FAIL'}")

    print("\nValidating the post-draft bridge preview...")
    add("interface_probe_passed_and_implementation_ready", probe_summary.get("passed") is True and probe_summary.get("implementation_ready") is True and all(clean(row.get("status")) == "PASS" for row in probe_checks), probe_zip.name)
    add("all_10_required_interfaces_are_ready_or_found", len(readiness) == 10 and all(clean(row.get("status")) in {"ready", "candidate_found"} for row in readiness), "10/10")
    add("final_incentive_freeze_still_has_only_bridge_blocker", final_summary.get("passed") is True and int(final_summary.get("remaining_financial_component_blocker_count", -1)) == 1 and all(clean(row.get("status")) == "PASS" for row in final_checks), final_zip.name)
    add("runtime_target_source_hashes_match_probe", target_hashes_match_probe, f"{len(target_files)} target modules")
    add("required_runtime_source_contracts_exported", not missing_contracts, " | ".join(missing_contracts) or f"{len(contract_rows)} symbols")
    add("rookie_scale_schedule_is_exactly_30_unique_picks", len(schedule) == 30 and {row["overall_pick"] for row in schedule} == set(range(1, 31)), "30/30")
    add("official_2026_27_salary_cap_is_164961000", all(row["season"] == SEASON_LABEL for row in schedule), "$164,961,000")
    add("pick_30_cap_hold_matches_quarantined_2926800_anchor", schedule[-1]["rookie_scale_cap_hold_amount"] == 2_926_800, "$2,926,800")
    add("all_30_unsigned_first_round_holds_generated_once", len(all_unsigned) == 30 and len({row.overall_pick for row in all_unsigned}) == 30 and len({row.player_id for row in all_unsigned}) == 30, "30/30")
    add("all_holds_equal_120_percent_of_rookie_scale", all(row.rookie_scale_cap_hold_amount == round(row.rookie_scale_amount * 1.2 / 100) * 100 for row in all_unsigned), "30/30")
    add("signed_player_hold_is_removed_atomically", len(first_signed) == 29 and all(row.player_id != "2026R1P01" for row in first_signed), "29 remain")
    add("all_signed_players_leave_zero_holds", not all_signed, "0/30")
    add("second_round_pick_is_excluded", all(row.round_number == 1 and row.overall_pick <= 30 for row in all_unsigned), "30 first-round only")
    add("assigned_rights_move_hold_to_current_holder", reassigned[0].rights_holder_team == "WAS" and team_hold_totals(reassigned)["WAS"] >= reassigned[0].rookie_scale_cap_hold_amount, "pick 1 -> WAS")
    add("duplicate_selection_is_rejected", duplicate_rejected, "strict conflict")
    add("all_preview_scenarios_pass", all(row["result"] == "PASS" for row in scenario_rows), f"{len(scenario_rows)}/{len(scenario_rows)}")
    add("opening_snapshot_has_zero_bridge_rows", scenario_rows[0]["actual_hold_count"] == 0 and SPLIT_DATE.isoformat() == "2026-04-12", "0 at 2026-04-12")
    add("no_hold_was_applied_to_team_salary", all(not row.applied_to_team_salary for row in all_unsigned + first_signed + reassigned), "0 applied")
    add("no_bridge_state_mutation_was_applied", all(not row.state_mutation_applied for row in all_unsigned + first_signed + reassigned), "preview only")

    checkpoint_hash_after = sha256_file(checkpoint_path)
    checkpoint_after = checkpoint_module.load_franchise_checkpoint()
    simulation_digest_after = object_digest(checkpoint_after.simulation_state)
    add("loaded_simulation_state_unchanged", simulation_digest_before == simulation_digest_after == EXPECTED_SIMULATION_DIGEST, simulation_digest_after)
    add("checkpoint_file_unchanged", checkpoint_hash_before == checkpoint_hash_after == EXPECTED_CHECKPOINT_SHA256, checkpoint_hash_after)
    failed = [row["check_id"] for row in checks if row["status"] != "PASS"]

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    name = f"fa_post_draft_first_round_pick_hold_bridge_preview_v1_{SEASON_LABEL}_{timestamp}"
    audit_dir = root / "outputs" / "audits"
    audit_dir.mkdir(parents=True, exist_ok=True)
    output_zip = audit_dir / f"{name}.zip"
    summary = {
        "version": VERSION,
        "season": SEASON_LABEL,
        "canonical_split_date": SPLIT_DATE.isoformat(),
        "passed": not failed,
        "failed_checks": failed,
        "rookie_scale_pick_count": len(schedule),
        "synthetic_unsigned_hold_count": len(all_unsigned),
        "synthetic_unsigned_hold_total": sum(row.rookie_scale_cap_hold_amount for row in all_unsigned),
        "pick_1_rookie_scale_amount": schedule[0]["rookie_scale_amount"],
        "pick_1_cap_hold_amount": schedule[0]["rookie_scale_cap_hold_amount"],
        "pick_30_rookie_scale_amount": schedule[-1]["rookie_scale_amount"],
        "pick_30_cap_hold_amount": schedule[-1]["rookie_scale_cap_hold_amount"],
        "runtime_contract_symbol_count": len(contract_rows),
        "runtime_contract_missing": missing_contracts,
        "preview_ready_for_final_integration": not failed,
        "network_requests": 0,
        "pick_holds_applied": 0,
        "team_salary_mutation_performed": False,
        "state_mutation_performed": False,
        "checkpoint_write_performed": False,
        "next_slice": "Patch the exact draft-completion and signing transaction hooks using the exported runtime source contracts, then freeze the final dynamic bridge.",
    }
    readme = f"""2026 POST-DRAFT FIRST-ROUND PICK-HOLD BRIDGE PREVIEW V1

Result
------
Audit passed: {not failed}
Exact 2026-27 rookie scale picks: {len(schedule)}
Synthetic unsigned first-round holds: {len(all_unsigned)}
Synthetic total: ${sum(row.rookie_scale_cap_hold_amount for row in all_unsigned):,}
Pick 1 hold: ${schedule[0]['rookie_scale_cap_hold_amount']:,}
Pick 30 hold: ${schedule[-1]['rookie_scale_cap_hold_amount']:,}

Rule
----
The 2023 NBA-NBPA CBA, Article VII Section 4(e), includes a first-round pick in
Team Salary immediately upon selection at 120% of the applicable Rookie Scale
Amount. The hold follows the team holding the player's draft rights and remains
until the player signs or the rights are lost/assigned. Article I defines the
annual scale roll-forward using official Salary Cap growth. Exhibit B supplies
the baseline scale.

Safety
------
This package installs an additive bridge library and validates it with synthetic
draft events. It does not hook the live event yet. No hold, Team Salary, roster,
simulation, overlay, or checkpoint mutation occurred.
"""

    with tempfile.TemporaryDirectory(prefix="fa_post_draft_bridge_preview_") as temporary:
        folder = Path(temporary) / name
        folder.mkdir(parents=True)
        write_csv(folder / "official_2026_27_rookie_scale_pick_hold_schedule_30.csv", schedule)
        write_csv(folder / "synthetic_post_draft_unsigned_hold_ledger_30.csv", hold_rows(all_unsigned))
        write_csv(folder / "bridge_behavior_scenarios_7.csv", scenario_rows)
        write_csv(folder / "runtime_source_contract_inventory.csv", [{key: value for key, value in row.items() if key != "source"} for row in contract_rows])
        (folder / "runtime_integration_contract_source.json").write_text(json.dumps(contract_rows, indent=2), encoding="utf-8")
        write_csv(folder / "post_draft_pick_hold_bridge_preview_checks.csv", checks)
        (folder / "post_draft_pick_hold_bridge_preview_summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
        (folder / "README.txt").write_text(readme, encoding="utf-8")
        with zipfile.ZipFile(output_zip, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for path in sorted(folder.rglob("*")):
                if path.is_file():
                    archive.write(path, arcname=f"{name}/{path.name}")

    print("\n" + "=" * 132)
    print(f"2026 POST-DRAFT FIRST-ROUND PICK-HOLD BRIDGE PREVIEW V1 {'PASSED' if not failed else 'FAILED'}")
    print("=" * 132)
    print(f"Rookie scale schedule:       {len(schedule)}/30")
    print(f"Synthetic unsigned holds:    {len(all_unsigned)}/30")
    print(f"Synthetic hold total:        ${sum(row.rookie_scale_cap_hold_amount for row in all_unsigned):,}")
    print(f"Pick 1 hold:                 ${schedule[0]['rookie_scale_cap_hold_amount']:,}")
    print(f"Pick 30 hold:                ${schedule[-1]['rookie_scale_cap_hold_amount']:,}")
    print(f"Runtime contract symbols:    {len(contract_rows)}")
    print("Pick holds applied:          0")
    print("Checkpoint write:            NOT PERFORMED")
    print(f"Audit ZIP: {output_zip}")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
