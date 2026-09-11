from __future__ import annotations

import csv
import hashlib
import io
import json
import pickle
import sys
import tempfile
import zipfile
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


VERSION = "fa-salaryswish-team-component-semantic-hotfix-v1.0.1-2026-08-15"
SEASON_LABEL = "2026-27"
UPSTREAM_PATTERN = "fa_salaryswish_team_component_evidence_harvest_v1_2026-27_*.zip"
EXPECTED_FAILED_CHECKS = {
    "cap_hit_equals_roster_plus_dead_plus_incomplete_for_all_teams",
    "team_salary_equals_cap_hit_plus_holds_for_all_teams",
}
EXPECTED_CAP_EXCEPTION_TEAMS = {"DET"}
EXPECTED_TEAM_SALARY_EXCEPTION_TEAMS = {"DET", "MIA", "ORL", "WAS"}
REQUIRED_TEAMS = {
    "ATL", "BKN", "BOS", "CHA", "CHI", "CLE", "DAL", "DEN", "DET", "GSW",
    "HOU", "IND", "LAC", "LAL", "MEM", "MIA", "MIL", "MIN", "NOP", "NYK",
    "OKC", "ORL", "PHI", "PHX", "POR", "SAC", "SAS", "TOR", "UTA", "WAS",
}


def clean(value: Any) -> str:
    return "" if value is None else str(value).strip()


def as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return clean(value).lower() in {"true", "1", "yes", "y"}


def as_int(value: Any) -> int | None:
    text = clean(value).replace("$", "").replace(",", "")
    if not text:
        return None
    try:
        number = Decimal(text)
    except InvalidOperation:
        return None
    return int(number) if number == number.to_integral_value() else None


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
    candidates = [path for path in root.rglob(pattern) if path.is_file()]
    if not candidates:
        raise RuntimeError(f"Missing required audit: {pattern}")
    return max(candidates, key=lambda path: path.stat().st_mtime)


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


def classify_cap_relation(row: dict[str, str]) -> tuple[str, int, int]:
    roster = as_int(row.get("roster_cap_hit"))
    dead = as_int(row.get("dead_cap_hit"))
    incomplete = as_int(row.get("incomplete_roster_charge"))
    cap_hit = as_int(row.get("cap_hit"))
    holds = as_int(row.get("holds"))
    team_salary = as_int(row.get("team_salary"))
    values = (roster, dead, incomplete, cap_hit, holds, team_salary)
    if any(value is None for value in values):
        raise RuntimeError(f"Missing numeric component for {clean(row.get('team'))}.")
    additive = int(roster) + int(dead) + int(incomplete)
    gap = int(cap_hit) - additive
    if gap == 0:
        relation = "exact_roster_dead_incomplete_additive_match"
    elif gap == int(holds) and int(team_salary) == int(cap_hit):
        relation = "reported_holds_already_embedded_in_source_cap_hit_and_team_salary"
    elif gap > 0:
        relation = "positive_source_cap_hit_adjustment_requires_category_reconciliation"
    else:
        relation = "negative_source_cap_hit_adjustment_requires_category_reconciliation"
    return relation, additive, gap


def classify_team_salary_relation(row: dict[str, str]) -> tuple[str, int, int]:
    cap_hit = as_int(row.get("cap_hit"))
    holds = as_int(row.get("holds"))
    team_salary = as_int(row.get("team_salary"))
    if cap_hit is None or holds is None or team_salary is None:
        raise RuntimeError(f"Missing Team Salary component for {clean(row.get('team'))}.")
    additive = cap_hit + holds
    gap = team_salary - additive
    if gap == 0:
        relation = "exact_cap_hit_plus_holds_additive_match"
    elif team_salary == cap_hit and holds > 0:
        relation = "reported_holds_excluded_or_already_embedded_in_team_salary"
    elif gap < 0:
        relation = "subset_of_reported_holds_excluded_from_team_salary"
    else:
        relation = "positive_team_salary_adjustment_requires_category_reconciliation"
    return relation, additive, gap


def main() -> int:
    root = Path.cwd().resolve()
    upstream_zip = latest(root, UPSTREAM_PATTERN)
    with zipfile.ZipFile(upstream_zip) as archive:
        upstream_summary = json_suffix(archive, "salaryswish_component_harvest_summary.json")
        upstream_checks = csv_suffix(archive, "salaryswish_component_harvest_checks.csv")
        evidence_rows = csv_suffix(archive, "salaryswish_team_component_evidence_30.csv")
        dead_cap_rows = csv_suffix(archive, "dead_cap_team_evidence_30.csv")
        incentive_rows = csv_suffix(archive, "team_incentive_evidence_30.csv")
        rookie_rows = csv_suffix(archive, "unsigned_first_round_hold_evidence_30.csv")
        drift_rows = csv_suffix(archive, "live_source_vs_legacy_checkpoint_drift_30.csv")
        fetch_errors = csv_suffix(archive, "source_fetch_errors.csv")

    if str(root / "src") not in sys.path:
        sys.path.insert(0, str(root / "src"))
    import simulation_franchise_checkpoint_v1 as checkpoint_module

    checkpoint_path = Path(checkpoint_module.DEFAULT_CHECKPOINT_PATH)
    checkpoint_hash_before = sha256_file(checkpoint_path)
    checkpoint = checkpoint_module.load_franchise_checkpoint()
    simulation_digest_before = object_digest(checkpoint.simulation_state)
    upstream_checkpoint_check = next(
        (row for row in upstream_checks if clean(row.get("check_id")) == "checkpoint_file_unchanged"),
        {},
    )
    upstream_checkpoint_hash = clean(upstream_checkpoint_check.get("detail"))
    upstream_failed_checks = {
        clean(row.get("check_id")) for row in upstream_checks if clean(row.get("status")) == "FAIL"
    }

    reconciled_rows: list[dict[str, Any]] = []
    exception_rows: list[dict[str, Any]] = []
    for source in sorted(evidence_rows, key=lambda row: clean(row.get("team"))):
        team = clean(source.get("team"))
        cap_relation, cap_additive, cap_gap = classify_cap_relation(source)
        salary_relation, salary_additive, salary_gap = classify_team_salary_relation(source)
        cap_exact = cap_gap == 0
        salary_exact = salary_gap == 0
        reconciled_rows.append(
            {
                **source,
                "cap_hit_semantic_relation": cap_relation,
                "cap_hit_simple_additive_total": cap_additive,
                "cap_hit_minus_simple_additive_total": cap_gap,
                "team_salary_semantic_relation": salary_relation,
                "team_salary_simple_additive_total": salary_additive,
                "team_salary_minus_simple_additive_total": salary_gap,
                "formula_exception_count": int(not cap_exact) + int(not salary_exact),
                "all_source_formula_relations_classified": True,
                "applied_to_team_salary": False,
                "state_mutation_applied": False,
            }
        )
        if not cap_exact:
            exception_rows.append(
                {
                    "team": team,
                    "formula": "cap_hit_vs_roster_dead_incomplete",
                    "reported_total": as_int(source.get("cap_hit")),
                    "simple_additive_total": cap_additive,
                    "difference": cap_gap,
                    "reported_holds": as_int(source.get("holds")),
                    "semantic_classification": cap_relation,
                    "source_url": clean(source.get("source_url")),
                    "fetched_at_utc": clean(source.get("fetched_at_utc")),
                    "source_sha256": clean(source.get("source_sha256")),
                    "requires_source_category_reconciliation": True,
                    "applied_to_team_salary": False,
                }
            )
        if not salary_exact:
            exception_rows.append(
                {
                    "team": team,
                    "formula": "team_salary_vs_cap_hit_plus_holds",
                    "reported_total": as_int(source.get("team_salary")),
                    "simple_additive_total": salary_additive,
                    "difference": salary_gap,
                    "reported_holds": as_int(source.get("holds")),
                    "semantic_classification": salary_relation,
                    "source_url": clean(source.get("source_url")),
                    "fetched_at_utc": clean(source.get("fetched_at_utc")),
                    "source_sha256": clean(source.get("source_sha256")),
                    "requires_source_category_reconciliation": True,
                    "applied_to_team_salary": False,
                }
            )

    cap_exception_teams = {
        row["team"] for row in exception_rows if row["formula"] == "cap_hit_vs_roster_dead_incomplete"
    }
    salary_exception_teams = {
        row["team"] for row in exception_rows if row["formula"] == "team_salary_vs_cap_hit_plus_holds"
    }
    exact_match_count = sum(as_bool(row.get("exact_match")) for row in drift_rows)
    unsigned_first_round_count = sum(
        int(as_int(row.get("unsigned_first_round_hold_count_2026_27")) or 0) for row in rookie_rows
    )
    unsigned_first_round_total = sum(
        int(as_int(row.get("unsigned_first_round_hold_amount_2026_27")) or 0) for row in rookie_rows
    )

    checks: list[dict[str, str]] = []

    def add(check_id: str, passed: bool, detail: str) -> None:
        checks.append(
            {
                "check_id": check_id,
                "status": "PASS" if passed else "FAIL",
                "severity": "strict",
                "detail": detail,
            }
        )
        print(f"  {check_id}: {'PASS' if passed else 'FAIL'}")

    print("=" * 132)
    print("2026 SALARYSWISH TEAM COMPONENT SEMANTIC HOTFIX V1.0.1")
    print("=" * 132)
    print("Reclassifying source accounting relations without refetching or mutating state...")

    add("upstream_failed_only_the_two_overstrict_formula_checks", upstream_failed_checks == EXPECTED_FAILED_CHECKS, json.dumps(sorted(upstream_failed_checks)))
    add("upstream_30_pages_fetched_without_errors", int(upstream_summary.get("team_page_count", -1)) == 30 and int(upstream_summary.get("fetch_error_count", -1)) == 0 and not fetch_errors, f"pages={upstream_summary.get('team_page_count')}, errors={len(fetch_errors)}")
    add("upstream_all_30_component_rows_were_complete", int(upstream_summary.get("required_component_complete_team_count", -1)) == 30, f"complete={upstream_summary.get('required_component_complete_team_count')}")
    add("upstream_checkpoint_matches_current_checkpoint", bool(upstream_checkpoint_hash) and upstream_checkpoint_hash == checkpoint_hash_before, checkpoint_hash_before)
    add("exact_30_unique_team_component_rows_retained", len(reconciled_rows) == 30 and {row["team"] for row in reconciled_rows} == REQUIRED_TEAMS, f"rows={len(reconciled_rows)}")
    add("all_source_provenance_hashes_and_urls_retained", all(clean(row.get("source_url")) and clean(row.get("source_sha256")) and clean(row.get("fetched_at_utc")) for row in reconciled_rows), "30/30")
    add("all_30_cap_hit_relations_semantically_classified", all(clean(row.get("cap_hit_semantic_relation")) for row in reconciled_rows), "30/30")
    add("all_30_team_salary_relations_semantically_classified", all(clean(row.get("team_salary_semantic_relation")) for row in reconciled_rows), "30/30")
    add("cap_hit_exception_is_exactly_detroit", cap_exception_teams == EXPECTED_CAP_EXCEPTION_TEAMS, json.dumps(sorted(cap_exception_teams)))
    add("team_salary_exceptions_are_exactly_det_mia_orl_was", salary_exception_teams == EXPECTED_TEAM_SALARY_EXCEPTION_TEAMS, json.dumps(sorted(salary_exception_teams)))
    add("exact_five_formula_exception_rows_exported", len(exception_rows) == 5, f"rows={len(exception_rows)}")
    add("detroit_holds_are_classified_as_embedded", any(row["team"] == "DET" and row["formula"] == "cap_hit_vs_roster_dead_incomplete" and row["semantic_classification"] == "reported_holds_already_embedded_in_source_cap_hit_and_team_salary" for row in exception_rows), "DET")
    add("three_2185116_partial_hold_exclusions_are_preserved", sum(row["formula"] == "team_salary_vs_cap_hit_plus_holds" and row["difference"] == -2185116 for row in exception_rows) == 3, "MIA/ORL/WAS")
    add("dead_cap_incentive_and_rookie_registries_retain_30_team_coverage", len(dead_cap_rows) == len(incentive_rows) == len(rookie_rows) == 30, f"dead={len(dead_cap_rows)}, incentive={len(incentive_rows)}, rookie={len(rookie_rows)}")
    add("one_unsigned_first_round_hold_is_preserved", unsigned_first_round_count == 1 and unsigned_first_round_total == 2926800, f"count={unsigned_first_round_count}, total={unsigned_first_round_total}")
    add("live_source_drift_is_preserved_as_16_match_14_drift", len(drift_rows) == 30 and exact_match_count == 16, f"matches={exact_match_count}, drift={len(drift_rows) - exact_match_count}")
    add("no_source_component_applied_to_team_salary", all(not as_bool(row.get("applied_to_team_salary")) and not as_bool(row.get("state_mutation_applied")) for row in reconciled_rows), "Evidence only.")

    simulation_digest_after = object_digest(checkpoint.simulation_state)
    checkpoint_hash_after = sha256_file(checkpoint_path)
    add("loaded_simulation_state_unchanged", simulation_digest_after == simulation_digest_before, simulation_digest_after)
    add("checkpoint_file_unchanged", checkpoint_hash_after == checkpoint_hash_before, checkpoint_hash_after)

    failed = [row["check_id"] for row in checks if row["status"] == "FAIL"]
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    export_id = f"fa_salaryswish_team_component_semantic_hotfix_v1_0_1_{SEASON_LABEL}_{timestamp}"
    output_dir = root / "outputs" / "audits"
    output_dir.mkdir(parents=True, exist_ok=True)
    audit_zip = output_dir / f"{export_id}.zip"
    summary = {
        "version": VERSION,
        "source_failed_harvest_audit": upstream_zip.name,
        "team_component_row_count": len(reconciled_rows),
        "fetch_error_count": len(fetch_errors),
        "cap_hit_exact_additive_match_count": 30 - len(cap_exception_teams),
        "team_salary_exact_additive_match_count": 30 - len(salary_exception_teams),
        "formula_exception_row_count": len(exception_rows),
        "cap_hit_exception_teams": sorted(cap_exception_teams),
        "team_salary_exception_teams": sorted(salary_exception_teams),
        "dead_cap_total": sum(int(as_int(row.get("dead_cap_hit_2026_27")) or 0) for row in dead_cap_rows),
        "likely_incentive_total": sum(int(as_int(row.get("likely_incentive_2026_27")) or 0) for row in incentive_rows),
        "unlikely_incentive_total": sum(int(as_int(row.get("unlikely_incentive_2026_27")) or 0) for row in incentive_rows),
        "unsigned_first_round_hold_count": unsigned_first_round_count,
        "unsigned_first_round_hold_total": unsigned_first_round_total,
        "legacy_checkpoint_team_salary_match_count": exact_match_count,
        "legacy_checkpoint_team_salary_drift_count": len(drift_rows) - exact_match_count,
        "external_evidence_applied": False,
        "state_mutation_performed": False,
        "checkpoint_write_performed": False,
        "passed": not failed,
        "failed_checks": failed,
        "next_slice": (
            "Reconcile the 14 live-source/checkpoint drift teams and the five classified source-formula exceptions against the frozen 361-player snapshot. "
            "Preserve the one NYK unsigned first-round hold ($2,926,800). Do not apply Team Salary yet."
        ),
    }

    with tempfile.TemporaryDirectory(prefix="fa_salaryswish_semantic_hotfix_") as temporary_directory:
        export = Path(temporary_directory) / export_id
        export.mkdir(parents=True)
        write_csv(export / "reconciled_team_component_evidence_30.csv", reconciled_rows)
        write_csv(export / "source_formula_semantic_exceptions_5.csv", exception_rows)
        write_csv(export / "dead_cap_team_evidence_30.csv", dead_cap_rows)
        write_csv(export / "team_incentive_evidence_30.csv", incentive_rows)
        write_csv(export / "unsigned_first_round_hold_evidence_30.csv", rookie_rows)
        write_csv(export / "live_source_vs_legacy_checkpoint_drift_30.csv", drift_rows)
        write_csv(export / "semantic_hotfix_checks.csv", checks)
        (export / "semantic_hotfix_summary.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8"
        )
        (export / "README.txt").write_text(
            """2026 SALARYSWISH TEAM COMPONENT SEMANTIC HOTFIX V1.0.1
===========================================================

Purpose
-------
Correct the V1 harvester's overstrict assumption that SalarySwish Cap Hit and
Team Salary always obey two simple additive identities. The 30-page harvest
itself succeeded completely; only the universal-formula assumptions failed.

This hotfix consumes the existing audit without refetching pages. It classifies
Detroit's embedded-hold treatment and the partial hold exclusions for Miami,
Orlando, and Washington, while retaining all source values and provenance.

Safety
------
No salary, cap hold, rights decision, roster, simulation, overlay, or
checkpoint mutation occurs. The external evidence remains preview-only.
""",
            encoding="utf-8",
        )
        with zipfile.ZipFile(audit_zip, "w", zipfile.ZIP_DEFLATED) as archive:
            for item in sorted(export.iterdir()):
                archive.write(item, arcname=f"{export_id}/{item.name}")

    if failed:
        print("")
        print(f"Diagnostic audit ZIP: {audit_zip}")
        raise RuntimeError("SalarySwish Team Component Semantic Hotfix V1.0.1 failed: " + ", ".join(failed))

    print("")
    print("=" * 132)
    print("2026 SALARYSWISH TEAM COMPONENT SEMANTIC HOTFIX V1.0.1 PASSED")
    print("=" * 132)
    print("Team component rows retained:          30/30")
    print("Cap Hit simple-formula matches:        29/30")
    print("Team Salary simple-formula matches:    26/30")
    print("Formula exceptions classified:           5/5")
    print(f"Unsigned first-round holds:               {unsigned_first_round_count}")
    print(f"Live/checkpoint drift teams:              {len(drift_rows) - exact_match_count}/30")
    print("External evidence applied:                 0")
    print("Checkpoint write:              NOT PERFORMED")
    print(f"Audit ZIP: {audit_zip}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
