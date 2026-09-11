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


VERSION = "fa-full-market-registry-completion-v1-2026-08-15"
SEASON_LABEL = "2026-27"
EXPECTED_CHECKPOINT_SHA256 = (
    "19f2fee601f5765bde4f5fabea34f20dc9b8ddc8dd5069186502dff08fc0cf9f"
)
EXPECTED_NON_RFA_RIGHTS_COUNTS = Counter(
    {"bird": 44, "early_bird": 14, "non_bird": 48, "not_applicable": 56}
)
SALARY_DEPENDENT_RIGHTS = {"bird", "early_bird", "non_bird"}
EXPECTED_DEPENDENT_SALARY_TOTAL = 692_859_473


def clean(value: Any) -> str:
    return str(value or "").strip()


def pid(value: Any) -> str:
    text = clean(value)
    return text[:-2] if text.endswith(".0") and text[:-2].isdigit() else text


def as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return clean(value).lower() in {"true", "1", "yes", "y"}


def integer_salary(value: Any) -> int | None:
    text = clean(value).replace("$", "").replace(",", "")
    if not text:
        return None
    number = float(text)
    if not number.is_integer() or number <= 0:
        raise RuntimeError(f"Invalid prior salary value: {value!r}")
    return int(number)


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


def latest(root: Path, pattern: str) -> Path:
    paths = [path for path in root.rglob(pattern) if path.is_file()]
    if not paths:
        raise RuntimeError(f"Missing required audit: {pattern}")
    return max(paths, key=lambda path: path.stat().st_mtime)


def csv_suffix(archive: zipfile.ZipFile, suffix: str) -> list[dict[str, str]]:
    member = next((name for name in archive.namelist() if name.endswith(suffix)), "")
    if not member:
        raise RuntimeError(f"ZIP missing member: {suffix}")
    text = archive.read(member).decode("utf-8-sig", errors="replace")
    return list(csv.DictReader(io.StringIO(text))) if text.strip() else []


def json_suffix(archive: zipfile.ZipFile, suffix: str) -> dict[str, Any]:
    member = next((name for name in archive.namelist() if name.endswith(suffix)), "")
    if not member:
        raise RuntimeError(f"ZIP missing member: {suffix}")
    return json.loads(archive.read(member).decode("utf-8-sig"))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row:
            if key not in seen:
                seen.add(key)
                fields.append(key)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    root = Path.cwd().resolve()
    owner_zip = latest(
        root, "fa_full_market_owner_rights_reconciliation_v1_0_2_2026-27_*.zip"
    )
    rights_zip = latest(
        root, "fa_non_rfa_rights_final_completion_v1_2026-27_*.zip"
    )
    salary_zip = latest(
        root, "fa_non_rfa_prior_salary_completion_v1_2026-27_*.zip"
    )

    with zipfile.ZipFile(owner_zip) as archive:
        owner_summary = json_suffix(archive, "owner_rights_reconciliation_summary.json")
        owner_rows = csv_suffix(archive, "full_market_owner_rights_reconciliation_226.csv")
    with zipfile.ZipFile(rights_zip) as archive:
        rights_summary = json_suffix(archive, "non_rfa_rights_final_completion_summary.json")
        rights_rows = csv_suffix(archive, "non_rfa_rights_evidence_complete_162.csv")
    with zipfile.ZipFile(salary_zip) as archive:
        salary_summary = json_suffix(archive, "non_rfa_prior_salary_completion_summary.json")
        salary_rows = csv_suffix(archive, "non_rfa_prior_salary_resolution_40.csv")

    if not owner_summary.get("passed"):
        raise RuntimeError("Upstream 226-player owner reconciliation did not pass.")
    if not rights_summary.get("passed"):
        raise RuntimeError("Upstream 162-player rights completion did not pass.")
    if not salary_summary.get("passed"):
        raise RuntimeError("Upstream 40-player salary completion did not pass.")

    owner_by_id = {pid(row.get("player_id")): row for row in owner_rows}
    rights_by_id = {pid(row.get("player_id")): row for row in rights_rows}
    salary_by_id = {pid(row.get("player_id")): row for row in salary_rows}
    duplicate_owner_ids = len(owner_by_id) != len(owner_rows)
    duplicate_rights_ids = len(rights_by_id) != len(rights_rows)
    duplicate_salary_ids = len(salary_by_id) != len(salary_rows)

    exact_rfa_ids = {
        player_id
        for player_id, row in owner_by_id.items()
        if as_bool(row.get("exact_rfa_free_agent_amount_available"))
    }
    non_rfa_ids = set(owner_by_id) - exact_rfa_ids
    conflicts: list[dict[str, Any]] = []
    final_rows: list[dict[str, Any]] = []
    non_rfa_rows: list[dict[str, Any]] = []
    rfa_rows: list[dict[str, Any]] = []

    for player_id in sorted(owner_by_id, key=lambda value: int(value)):
        owner = owner_by_id[player_id]
        player_name = clean(owner.get("player_name"))
        prior_team = clean(owner.get("resolved_prior_team"))
        exact_rfa = player_id in exact_rfa_ids

        base = {
            "player_id": player_id,
            "player_name": player_name,
            "resolved_prior_team": prior_team,
            "market_category": "rfa_exact" if exact_rfa else "non_rfa",
            "exact_rfa_free_agent_amount_available": exact_rfa,
            "owner_evidence_complete": bool(prior_team),
        }

        if exact_rfa:
            row = {
                **base,
                "final_rights_classification": clean(
                    owner.get("reconciled_rights_classification")
                ),
                "final_prior_regular_salary": "",
                "prior_salary_requirement_status": "handled_by_exact_rfa_amount",
                "formula_input_status": "exact_rfa_amount_already_available",
                "rights_evidence_mode": "existing_exact_rfa_pipeline",
                "salary_evidence_mode": "not_required_for_exact_rfa_amount",
                "upstream_prior_salary_audit_only": clean(
                    owner.get("reconciled_prior_salary_evidence")
                ),
                "ready_for_full_market_amount_preview": True,
                "registry_applied_to_simulation": False,
            }
            final_rows.append(row)
            rfa_rows.append(row)
            continue

        rights = rights_by_id.get(player_id, {})
        if not rights:
            conflicts.append({
                "player_id": player_id,
                "player_name": player_name,
                "conflict_type": "non_rfa_missing_final_rights_row",
                "detail": "",
            })
            continue

        rights_name = clean(rights.get("player_name"))
        rights_team = clean(rights.get("prior_team"))
        if rights_name != player_name or rights_team != prior_team:
            conflicts.append({
                "player_id": player_id,
                "player_name": player_name,
                "conflict_type": "non_rfa_identity_or_owner_mismatch",
                "detail": f"owner={player_name}|{prior_team}; rights={rights_name}|{rights_team}",
            })

        classification = clean(rights.get("final_rights_classification"))
        completion = salary_by_id.get(player_id)
        upstream_salary = integer_salary(owner.get("reconciled_prior_salary_evidence"))

        if classification in SALARY_DEPENDENT_RIGHTS:
            completion_salary = (
                integer_salary(completion.get("prior_regular_salary"))
                if completion
                else None
            )
            final_salary = completion_salary or upstream_salary
            if final_salary is None:
                conflicts.append({
                    "player_id": player_id,
                    "player_name": player_name,
                    "conflict_type": "salary_dependent_non_rfa_missing_salary",
                    "detail": classification,
                })
            salary_status = "numeric_resolved"
            salary_mode = (
                clean(completion.get("evidence_mode"))
                if completion_salary is not None
                else "reconciled_existing_top_priority_evidence"
            )
            formula_status = "ready_for_non_rfa_formula"
        elif classification == "not_applicable":
            final_salary = None
            salary_status = "not_required"
            salary_mode = "final_rights_classification_not_applicable"
            formula_status = "no_veteran_free_agent_amount_required"
            if completion and clean(completion.get("resolution_status")) != "not_required":
                conflicts.append({
                    "player_id": player_id,
                    "player_name": player_name,
                    "conflict_type": "not_applicable_completion_status_mismatch",
                    "detail": clean(completion.get("resolution_status")),
                })
        else:
            final_salary = None
            salary_status = "unresolved"
            salary_mode = ""
            formula_status = "rights_classification_invalid"
            conflicts.append({
                "player_id": player_id,
                "player_name": player_name,
                "conflict_type": "invalid_final_rights_classification",
                "detail": classification,
            })

        row = {
            **base,
            "final_rights_classification": classification,
            "final_prior_regular_salary": final_salary if final_salary is not None else "",
            "prior_salary_requirement_status": salary_status,
            "formula_input_status": formula_status,
            "rights_evidence_mode": clean(rights.get("evidence_mode")),
            "salary_evidence_mode": salary_mode,
            "upstream_prior_salary_audit_only": upstream_salary if upstream_salary is not None else "",
            "salary_completion_override_used": bool(
                completion and clean(completion.get("resolution_status")) == "numeric_resolved"
            ),
            "ready_for_full_market_amount_preview": (
                classification == "not_applicable" or final_salary is not None
            ),
            "registry_applied_to_simulation": False,
        }
        final_rows.append(row)
        non_rfa_rows.append(row)

    rights_counts = Counter(
        clean(row.get("final_rights_classification")) for row in non_rfa_rows
    )
    dependent_rows = [
        row
        for row in non_rfa_rows
        if row["final_rights_classification"] in SALARY_DEPENDENT_RIGHTS
    ]
    not_applicable_rows = [
        row
        for row in non_rfa_rows
        if row["final_rights_classification"] == "not_applicable"
    ]
    completion_numeric_count = sum(
        bool(row.get("salary_completion_override_used")) for row in non_rfa_rows
    )
    dependent_salary_total = sum(
        int(row["final_prior_regular_salary"]) for row in dependent_rows
    )

    import simulation_franchise_checkpoint_v1 as checkpoint_module

    checkpoint_path = Path(checkpoint_module.DEFAULT_CHECKPOINT_PATH)
    checkpoint_hash_before = sha256_file(checkpoint_path)
    checkpoint = checkpoint_module.load_franchise_checkpoint()
    simulation_digest_before = object_digest(checkpoint.simulation_state)
    if checkpoint_hash_before != EXPECTED_CHECKPOINT_SHA256:
        raise RuntimeError(
            "Canonical checkpoint changed before full-market registry completion."
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

    print("=" * 132)
    print("2026 FULL-MARKET REGISTRY COMPLETION V1")
    print("=" * 132)
    print("Merging final owner, rights, and prior-salary evidence...")

    add(
        "all_three_upstream_audits_passed",
        all(summary.get("passed") for summary in [owner_summary, rights_summary, salary_summary]),
        "Owner, rights, and salary completion audits passed.",
    )
    add(
        "upstream_tables_have_exact_unique_cardinality",
        len(owner_rows) == 226
        and len(rights_rows) == 162
        and len(salary_rows) == 40
        and not duplicate_owner_ids
        and not duplicate_rights_ids
        and not duplicate_salary_ids,
        f"owner={len(owner_rows)}, rights={len(rights_rows)}, salary={len(salary_rows)}",
    )
    add(
        "exact_64_rfa_and_162_non_rfa_partition",
        len(exact_rfa_ids) == 64 and len(non_rfa_ids) == 162 and not (exact_rfa_ids & non_rfa_ids),
        f"rfa={len(exact_rfa_ids)}, non_rfa={len(non_rfa_ids)}",
    )
    add(
        "final_rights_ids_exactly_match_non_rfa_market",
        set(rights_by_id) == non_rfa_ids,
        f"matched={len(set(rights_by_id) & non_rfa_ids)}/162",
    )
    add(
        "all_226_prior_team_owners_preserved",
        len(final_rows) == 226 and all(clean(row["resolved_prior_team"]) for row in final_rows),
        f"complete={len(final_rows)}/226",
    )
    add(
        "non_rfa_rights_distribution_matches_expected",
        rights_counts == EXPECTED_NON_RFA_RIGHTS_COUNTS,
        repr(dict(rights_counts)),
    )
    add(
        "all_106_salary_dependent_non_rfas_have_numeric_salary",
        len(dependent_rows) == 106
        and all(isinstance(row["final_prior_regular_salary"], int) and row["final_prior_regular_salary"] > 0 for row in dependent_rows),
        f"resolved={len(dependent_rows)}/106",
    )
    add(
        "dependent_salary_total_matches_expected",
        dependent_salary_total == EXPECTED_DEPENDENT_SALARY_TOTAL,
        f"total={dependent_salary_total}",
    )
    add(
        "exact_21_new_numeric_salary_resolutions_merged",
        completion_numeric_count == 21,
        f"merged={completion_numeric_count}/21",
    )
    add(
        "all_56_not_applicable_rows_have_no_fake_salary_requirement",
        len(not_applicable_rows) == 56
        and all(row["final_prior_regular_salary"] == "" and row["prior_salary_requirement_status"] == "not_required" for row in not_applicable_rows),
        f"not_required={len(not_applicable_rows)}/56",
    )
    add(
        "all_64_rfas_preserve_exact_amount_readiness",
        len(rfa_rows) == 64
        and all(row["formula_input_status"] == "exact_rfa_amount_already_available" for row in rfa_rows),
        f"exact_rfa={len(rfa_rows)}/64",
    )
    add(
        "all_226_rows_ready_for_amount_preview",
        len(final_rows) == 226
        and all(bool(row["ready_for_full_market_amount_preview"]) for row in final_rows),
        f"ready={sum(bool(row['ready_for_full_market_amount_preview']) for row in final_rows)}/226",
    )
    add(
        "merge_conflicts_are_zero",
        not conflicts,
        f"conflicts={len(conflicts)}",
    )
    add(
        "registry_not_applied_to_simulation",
        all(not row["registry_applied_to_simulation"] for row in final_rows),
        "Evidence registry only.",
    )

    simulation_digest_after = object_digest(checkpoint.simulation_state)
    checkpoint_hash_after = sha256_file(checkpoint_path)
    add(
        "loaded_simulation_state_unchanged",
        simulation_digest_after == simulation_digest_before,
        simulation_digest_after,
    )
    add(
        "checkpoint_file_unchanged",
        checkpoint_hash_after == checkpoint_hash_before == EXPECTED_CHECKPOINT_SHA256,
        checkpoint_hash_after,
    )

    failed = [row["check_id"] for row in checks if row["status"] == "FAIL"]
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    export_id = f"fa_full_market_registry_completion_v1_{SEASON_LABEL}_{timestamp}"
    output_dir = root / "outputs" / "audits"
    output_dir.mkdir(parents=True, exist_ok=True)
    audit_zip = output_dir / f"{export_id}.zip"

    summary = {
        "version": VERSION,
        "market_count": len(final_rows),
        "rfa_exact_count": len(rfa_rows),
        "non_rfa_count": len(non_rfa_rows),
        "non_rfa_rights_counts": dict(sorted(rights_counts.items())),
        "salary_dependent_non_rfa_count": len(dependent_rows),
        "salary_dependent_numeric_resolved_count": sum(bool(row["final_prior_regular_salary"]) for row in dependent_rows),
        "salary_dependent_numeric_total": dependent_salary_total,
        "not_applicable_non_rfa_count": len(not_applicable_rows),
        "new_numeric_salary_resolutions_merged": completion_numeric_count,
        "formula_input_ready_count": sum(bool(row["ready_for_full_market_amount_preview"]) for row in final_rows),
        "merge_conflict_count": len(conflicts),
        "registry_rows_applied": 0,
        "cap_holds_computed": 0,
        "state_mutation_performed": False,
        "checkpoint_write_performed": False,
        "source_owner_reconciliation_audit": owner_zip.name,
        "source_final_rights_audit": rights_zip.name,
        "source_prior_salary_completion_audit": salary_zip.name,
        "passed": not failed,
        "failed_checks": failed,
        "next_slice": (
            "Compute a read-only full-market Free Agent Amount and cap-hold preview. "
            "The 64 exact RFA rows can be preserved directly; the 106 salary-dependent "
            "non-RFA rows now have complete formula inputs; 56 not-applicable rows need "
            "no veteran Free Agent Amount."
        ),
    }

    with tempfile.TemporaryDirectory(prefix="fa_full_market_registry_completion_") as temporary_directory:
        export = Path(temporary_directory) / export_id
        export.mkdir(parents=True)
        write_csv(export / "full_market_registry_complete_226.csv", final_rows)
        write_csv(export / "full_market_registry_rfa_exact_64.csv", rfa_rows)
        write_csv(export / "full_market_registry_non_rfa_162.csv", non_rfa_rows)
        write_csv(export / "full_market_registry_salary_dependent_106.csv", dependent_rows)
        write_csv(export / "full_market_registry_not_applicable_56.csv", not_applicable_rows)
        write_csv(export / "full_market_registry_completion_conflicts.csv", conflicts)
        write_csv(export / "full_market_registry_completion_checks.csv", checks)
        (export / "full_market_registry_completion_summary.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8"
        )
        (export / "README.txt").write_text(
            """2026 FULL-MARKET REGISTRY COMPLETION V1
==========================================

Purpose
-------
Merge the authoritative 226-player prior-team map, the completed 162-player
non-RFA rights table, and the completed 40-player prior-salary blocker into one
formula-input-complete free-agent market registry.

Expected result
---------------
- 226/226 prior-team owners preserved
- 64 exact-RFA rows preserved
- 162/162 non-RFA rights classifications merged
- 106/106 salary-dependent non-RFAs have numeric prior salary
- 56/56 not-applicable non-RFAs require no prior salary
- zero merge conflicts

This is a read-only evidence and formula-input registry.
No Free Agent Amount or cap hold is computed in this slice.
No simulation, roster, QO, rights, Team Salary, or checkpoint mutation occurs.
""",
            encoding="utf-8",
        )
        with zipfile.ZipFile(audit_zip, "w", zipfile.ZIP_DEFLATED) as archive:
            for item in sorted(export.iterdir()):
                archive.write(item, arcname=f"{export_id}/{item.name}")

    if failed:
        print("")
        print(f"Diagnostic audit ZIP: {audit_zip}")
        raise RuntimeError(
            "Full-Market Registry Completion V1 failed: " + ", ".join(failed)
        )

    print("")
    print("=" * 132)
    print("2026 FULL-MARKET REGISTRY COMPLETION V1 PASSED")
    print("=" * 132)
    print("Market owners:              226/226")
    print("Exact RFA rows:               64/64")
    print("Non-RFA rights:             162/162")
    print("Salary-dependent inputs:    106/106")
    print("Not-required salary rows:     56/56")
    print("Formula-input ready:        226/226")
    print("Registry rows applied:        0")
    print("Cap holds computed:           0")
    print(f"Audit ZIP: {audit_zip}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
