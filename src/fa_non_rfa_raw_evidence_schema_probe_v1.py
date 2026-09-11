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

VERSION = "fa-non-rfa-raw-evidence-schema-probe-v1-2026-08-15"
SEASON_LABEL = "2026-27"
EXPECTED_CHECKPOINT_SHA256 = (
    "19f2fee601f5765bde4f5fabea34f20dc9b8ddc8dd5069186502dff08fc0cf9f"
)

TARGET_MEMBER_TOKENS = (
    "player_movement_rows_canonical.csv",
    "rights_external_transaction_rows.csv",
    "additional_lifecycle_contract_spans.csv",
    "additional_lifecycle_contract_classification.csv",
    "additional_lifecycle_final_84.csv",
    "rights_continuity",
)

TRANSACTION_SIGNAL_TOKENS = (
    "transaction",
    "action",
    "type",
    "description",
    "movement",
    "acquired",
    "waiv",
    "trade",
    "sign",
    "team",
    "date",
)
CONTRACT_SIGNAL_TOKENS = (
    "salary",
    "base",
    "guarantee",
    "contract",
    "season",
    "year",
    "start",
    "end",
    "date",
    "team",
    "option",
    "term",
)


def clean(v: Any) -> str:
    return str(v or "").strip()


def pid(v: Any) -> str:
    text = clean(v)
    if text.endswith(".0") and text[:-2].isdigit():
        return text[:-2]
    return text


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def object_digest(value: Any) -> str:
    try:
        payload = pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL)
    except Exception:
        payload = repr(value).encode("utf-8", errors="replace")
    return hashlib.sha256(payload).hexdigest()


def find_latest(root: Path, pattern: str) -> Path | None:
    paths = [p for p in root.rglob(pattern) if p.is_file()]
    return max(paths, key=lambda p: p.stat().st_mtime) if paths else None


def read_csv_suffix(z: zipfile.ZipFile, suffix: str, required: bool = True):
    name = next((n for n in z.namelist() if n.endswith(suffix)), "")
    if not name:
        if required:
            raise RuntimeError(f"ZIP missing member: {suffix}")
        return []
    raw = z.read(name)
    if not raw.strip():
        return []
    return list(
        csv.DictReader(
            io.StringIO(raw.decode("utf-8-sig", errors="replace"))
        )
    )


def read_json_suffix(z: zipfile.ZipFile, suffix: str):
    name = next((n for n in z.namelist() if n.endswith(suffix)), "")
    if not name:
        raise RuntimeError(f"ZIP missing member: {suffix}")
    return json.loads(z.read(name).decode("utf-8-sig"))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return

    fields, seen = [], set()
    for row in rows:
        for key in row:
            if key not in seen:
                seen.add(key)
                fields.append(key)

    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def is_target_member(member: str) -> bool:
    lower = member.lower()
    return any(token in lower for token in TARGET_MEMBER_TOKENS)


def signal_columns(fields: list[str], tokens: tuple[str, ...]) -> list[str]:
    result = []
    for field in fields:
        lower = clean(field).lower()
        if any(token in lower for token in tokens):
            result.append(field)
    return result


def main() -> int:
    root = Path.cwd().resolve()

    rec_zip = find_latest(
        root,
        "fa_full_market_owner_rights_reconciliation_v1_0_2_2026-27_*.zip",
    )
    harvest_zip = find_latest(
        root,
        "fa_non_rfa_evidence_gap_harvest_v1_2026-27_*.zip",
    )

    if rec_zip is None or harvest_zip is None:
        raise RuntimeError(
            "Missing V1.0.2 reconciliation or Non-RFA Evidence Gap Harvest V1."
        )

    with zipfile.ZipFile(rec_zip) as z:
        rec_summary = read_json_suffix(
            z, "owner_rights_reconciliation_summary.json"
        )
        rec_rows = read_csv_suffix(
            z, "full_market_owner_rights_reconciliation_226.csv"
        )
        salary_conflicts = read_csv_suffix(
            z, "prior_salary_conflicts.csv", required=False
        )

    with zipfile.ZipFile(harvest_zip) as z:
        harvest_summary = read_json_suffix(
            z, "non_rfa_gap_harvest_summary.json"
        )
        rights_unresolved = read_csv_suffix(
            z, "rights_still_unresolved.csv"
        )
        salary_unresolved = read_csv_suffix(
            z, "prior_salary_still_unresolved.csv"
        )

    rights_ids = {pid(r["player_id"]) for r in rights_unresolved}
    salary_ids = {pid(r["player_id"]) for r in salary_unresolved}

    non_rfa_ids = {
        pid(r["player_id"])
        for r in rec_rows
        if clean(r.get("exact_rfa_free_agent_amount_available")).lower()
        not in {"true", "1", "yes"}
    }
    conflict_ids = {
        pid(r["player_id"])
        for r in salary_conflicts
        if pid(r.get("player_id")) in non_rfa_ids
    }

    target_ids = rights_ids | salary_ids | conflict_ids
    rec_by_id = {pid(r["player_id"]): r for r in rec_rows}

    raw_rows: list[dict[str, Any]] = []
    schema_rows: list[dict[str, Any]] = []
    source_member_rows: list[dict[str, Any]] = []

    audit_dir = root / "outputs" / "audits"
    for zip_path in sorted(audit_dir.glob("*.zip")):
        if (
            "owner_rights_reconciliation" in zip_path.name.lower()
            or "non_rfa_raw_evidence_schema_probe" in zip_path.name.lower()
        ):
            continue

        try:
            with zipfile.ZipFile(zip_path) as z:
                for member in z.namelist():
                    if not member.lower().endswith(".csv"):
                        continue
                    if not is_target_member(member):
                        continue

                    try:
                        raw = z.read(member)
                        if not raw.strip():
                            continue
                        rows = list(
                            csv.DictReader(
                                io.StringIO(
                                    raw.decode("utf-8-sig", errors="replace")
                                )
                            )
                        )
                    except Exception:
                        continue

                    if not rows or "player_id" not in rows[0]:
                        continue

                    fields = list(rows[0].keys())
                    transaction_cols = signal_columns(
                        fields, TRANSACTION_SIGNAL_TOKENS
                    )
                    contract_cols = signal_columns(
                        fields, CONTRACT_SIGNAL_TOKENS
                    )

                    matched = 0
                    rights_matched = 0
                    salary_matched = 0
                    conflict_matched = 0

                    for row in rows:
                        player_id = pid(row.get("player_id"))
                        if player_id not in target_ids:
                            continue

                        matched += 1
                        if player_id in rights_ids:
                            rights_matched += 1
                        if player_id in salary_ids:
                            salary_matched += 1
                        if player_id in conflict_ids:
                            conflict_matched += 1

                        base = rec_by_id.get(player_id, {})
                        raw_rows.append({
                            "source_zip": zip_path.name,
                            "source_member": member,
                            "player_id": player_id,
                            "player_name": clean(
                                row.get("player_name")
                                or base.get("player_name")
                            ),
                            "resolved_prior_team": clean(
                                base.get("resolved_prior_team")
                            ),
                            "rights_target": player_id in rights_ids,
                            "salary_target": player_id in salary_ids,
                            "salary_conflict_target": player_id in conflict_ids,
                            **{
                                f"src__{k}": clean(v)
                                for k, v in row.items()
                            },
                        })

                    if matched:
                        schema_rows.append({
                            "source_zip": zip_path.name,
                            "source_member": member,
                            "row_count": len(rows),
                            "matched_target_row_count": matched,
                            "matched_rights_target_rows": rights_matched,
                            "matched_salary_target_rows": salary_matched,
                            "matched_salary_conflict_rows": conflict_matched,
                            "all_columns": "|".join(fields),
                            "transaction_signal_columns": "|".join(
                                transaction_cols
                            ),
                            "contract_signal_columns": "|".join(
                                contract_cols
                            ),
                        })

                        source_member_rows.append({
                            "source_zip": zip_path.name,
                            "source_member": member,
                            "matched_target_row_count": matched,
                            "transaction_signal_column_count": len(
                                transaction_cols
                            ),
                            "contract_signal_column_count": len(
                                contract_cols
                            ),
                        })
        except Exception:
            continue

    # Target-level coverage summary.
    coverage_rows = []
    for player_id in sorted(
        target_ids,
        key=lambda x: clean(rec_by_id.get(x, {}).get("player_name")).lower(),
    ):
        rows = [r for r in raw_rows if r["player_id"] == player_id]

        transaction_fields = set()
        contract_fields = set()
        source_members = set()

        for row in rows:
            source_members.add(
                f"{row['source_zip']}::{row['source_member']}"
            )
            for key, value in row.items():
                if not key.startswith("src__") or not clean(value):
                    continue
                field = key[5:]
                lower = field.lower()
                if any(token in lower for token in TRANSACTION_SIGNAL_TOKENS):
                    transaction_fields.add(field)
                if any(token in lower for token in CONTRACT_SIGNAL_TOKENS):
                    contract_fields.add(field)

        base = rec_by_id.get(player_id, {})
        coverage_rows.append({
            "player_id": player_id,
            "player_name": clean(base.get("player_name")),
            "resolved_prior_team": clean(base.get("resolved_prior_team")),
            "rights_target": player_id in rights_ids,
            "salary_target": player_id in salary_ids,
            "salary_conflict_target": player_id in conflict_ids,
            "raw_evidence_row_count": len(rows),
            "source_member_count": len(source_members),
            "transaction_signal_fields": "|".join(
                sorted(transaction_fields)
            ),
            "contract_signal_fields": "|".join(
                sorted(contract_fields)
            ),
            "has_transaction_signal_fields": bool(transaction_fields),
            "has_contract_signal_fields": bool(contract_fields),
        })

    rights_with_raw = sum(
        1 for row in coverage_rows
        if row["rights_target"] and row["raw_evidence_row_count"] > 0
    )
    salary_with_raw = sum(
        1 for row in coverage_rows
        if row["salary_target"] and row["raw_evidence_row_count"] > 0
    )
    conflict_with_raw = sum(
        1 for row in coverage_rows
        if row["salary_conflict_target"]
        and row["raw_evidence_row_count"] > 0
    )

    # Field-frequency diagnostics.
    transaction_field_counts = Counter()
    contract_field_counts = Counter()

    for schema in schema_rows:
        for field in clean(schema["transaction_signal_columns"]).split("|"):
            if field:
                transaction_field_counts[field] += 1
        for field in clean(schema["contract_signal_columns"]).split("|"):
            if field:
                contract_field_counts[field] += 1

    transaction_field_summary = [
        {
            "field_name": field,
            "source_member_coverage_count": count,
        }
        for field, count in transaction_field_counts.most_common()
    ]
    contract_field_summary = [
        {
            "field_name": field,
            "source_member_coverage_count": count,
        }
        for field, count in contract_field_counts.most_common()
    ]

    import simulation_franchise_checkpoint_v1 as checkpoint_module

    checkpoint_path = Path(checkpoint_module.DEFAULT_CHECKPOINT_PATH)
    before_hash = sha256_file(checkpoint_path)
    checkpoint = checkpoint_module.load_franchise_checkpoint()
    before_state = object_digest(checkpoint.simulation_state)

    if before_hash != EXPECTED_CHECKPOINT_SHA256:
        raise RuntimeError(
            "Canonical checkpoint changed before raw-evidence schema probe."
        )

    checks = []

    def add(
        check_id: str,
        passed: bool,
        detail: str,
        severity: str = "strict",
    ) -> None:
        checks.append({
            "check_id": check_id,
            "status": "PASS" if passed else "FAIL",
            "severity": severity,
            "detail": detail,
        })
        print(
            f"  {check_id}: {'PASS' if passed else 'FAIL'}",
            flush=True,
        )

    print("=" * 128, flush=True)
    print("2026 NON-RFA RAW EVIDENCE SCHEMA PROBE V1", flush=True)
    print("=" * 128, flush=True)
    print("Running checks...", flush=True)

    add(
        "upstream_reconciliation_passed",
        bool(rec_summary.get("passed"))
        and int(rec_summary.get("owner_resolved_count", -1)) == 226,
        "226/226 prior-team ownership remains proven.",
    )
    add(
        "upstream_gap_harvest_passed",
        bool(harvest_summary.get("passed")),
        "Initial gap harvest passed safely.",
    )
    add(
        "target_counts_match_gap_harvest",
        len(rights_ids) == 63
        and len(salary_ids) == 40
        and len(conflict_ids) == 4,
        (
            f"rights={len(rights_ids)}; salary={len(salary_ids)}; "
            f"non_rfa_salary_conflicts={len(conflict_ids)}"
        ),
    )
    add(
        "raw_target_sources_found",
        len(raw_rows) > 0 and len(schema_rows) > 0,
        f"raw_rows={len(raw_rows)}; source_members={len(schema_rows)}",
    )
    add(
        "rights_raw_evidence_coverage_is_diagnostic",
        True,
        f"rights_targets_with_raw_rows={rights_with_raw}/63",
        severity="diagnostic",
    )
    add(
        "salary_raw_evidence_coverage_is_diagnostic",
        True,
        f"salary_targets_with_raw_rows={salary_with_raw}/40",
        severity="diagnostic",
    )
    add(
        "salary_conflict_raw_evidence_coverage_is_diagnostic",
        True,
        f"salary_conflicts_with_raw_rows={conflict_with_raw}/4",
        severity="diagnostic",
    )
    add(
        "no_rights_or_salary_resolution_applied",
        True,
        "Probe exports raw evidence only.",
    )

    after_state = object_digest(checkpoint.simulation_state)
    after_hash = sha256_file(checkpoint_path)

    add(
        "loaded_simulation_state_unchanged",
        after_state == before_state,
        after_state,
    )
    add(
        "checkpoint_file_unchanged",
        after_hash
        == before_hash
        == EXPECTED_CHECKPOINT_SHA256,
        after_hash,
    )

    failed = [
        row["check_id"]
        for row in checks
        if row["severity"] == "strict"
        and row["status"] == "FAIL"
    ]

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    export_id = (
        f"fa_non_rfa_raw_evidence_schema_probe_v1_"
        f"{SEASON_LABEL}_{stamp}"
    )
    out_dir = root / "outputs" / "audits"
    out_dir.mkdir(parents=True, exist_ok=True)
    audit_zip = out_dir / f"{export_id}.zip"

    summary = {
        "version": VERSION,
        "rights_target_count": len(rights_ids),
        "salary_target_count": len(salary_ids),
        "non_rfa_salary_conflict_target_count": len(conflict_ids),
        "raw_evidence_row_count": len(raw_rows),
        "source_member_count": len(schema_rows),
        "rights_targets_with_raw_rows": rights_with_raw,
        "salary_targets_with_raw_rows": salary_with_raw,
        "salary_conflicts_with_raw_rows": conflict_with_raw,
        "distinct_transaction_signal_field_count": len(
            transaction_field_counts
        ),
        "distinct_contract_signal_field_count": len(
            contract_field_counts
        ),
        "rights_classifications_applied": 0,
        "salary_values_applied": 0,
        "state_mutation_performed": False,
        "checkpoint_write_performed": False,
        "passed": not failed,
        "failed_checks": failed,
        "next_slice": (
            "Inspect raw_target_evidence_rows.csv plus the transaction/contract "
            "field summaries. Build a resolver only from fields whose semantics "
            "are explicit enough to distinguish signing, trade/assignment, waiver "
            "events, contract seasons, and the applicable 2025-26 salary."
        ),
    }

    with tempfile.TemporaryDirectory(
        prefix="fa_non_rfa_raw_probe_"
    ) as tmpdir:
        export = Path(tmpdir) / export_id
        export.mkdir(parents=True)

        write_csv(
            export / "raw_target_evidence_rows.csv",
            raw_rows,
        )
        write_csv(
            export / "raw_target_source_schema.csv",
            schema_rows,
        )
        write_csv(
            export / "target_raw_evidence_coverage.csv",
            coverage_rows,
        )
        write_csv(
            export / "transaction_signal_field_summary.csv",
            transaction_field_summary,
        )
        write_csv(
            export / "contract_signal_field_summary.csv",
            contract_field_summary,
        )
        write_csv(
            export / "raw_evidence_probe_checks.csv",
            checks,
        )

        (export / "raw_evidence_probe_summary.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True),
            encoding="utf-8",
        )

        (export / "README.txt").write_text(
            """2026 NON-RFA RAW EVIDENCE SCHEMA PROBE V1
==========================================

Why this exists
---------------
The first gap harvest scanned thousands of evidence rows but resolved 0/40
salary gaps and marked 0/63 rights rows derivation-ready.

That result indicates a resolver/schema mismatch, not necessarily missing
evidence.

This probe exports the COMPLETE RAW ROWS for only the relevant sources and
target players:
- official/canonical player movement rows
- external transaction rows
- lifecycle contract spans/classification
- targeted lifecycle final rows
- continuity-related outputs

It also summarizes which transaction/action/type/date/team fields and which
contract/salary/season/year/date fields actually exist.

Nothing is resolved or applied here. The next resolver must be based on the
real source schema exposed by this probe, not guessed field names.

READ ONLY.
""",
            encoding="utf-8",
        )

        with zipfile.ZipFile(
            audit_zip, "w", zipfile.ZIP_DEFLATED
        ) as archive:
            for item in sorted(export.iterdir()):
                archive.write(
                    item,
                    arcname=f"{export_id}/{item.name}",
                )

    if failed:
        print("", flush=True)
        print(f"Diagnostic audit ZIP: {audit_zip}", flush=True)
        raise RuntimeError(
            "Non-RFA Raw Evidence Schema Probe V1 failed: "
            + ", ".join(failed)
        )

    print("", flush=True)
    print("=" * 128, flush=True)
    print("2026 NON-RFA RAW EVIDENCE SCHEMA PROBE V1 PASSED", flush=True)
    print("=" * 128, flush=True)
    print(f"Rights targets with raw evidence:  {rights_with_raw}/63", flush=True)
    print(f"Salary targets with raw evidence:  {salary_with_raw}/40", flush=True)
    print(f"Salary conflicts with raw evidence:{conflict_with_raw}/4", flush=True)
    print(f"Raw evidence rows exported:        {len(raw_rows)}", flush=True)
    print(f"Source members exported:           {len(schema_rows)}", flush=True)
    print(
        f"Transaction signal fields:         {len(transaction_field_counts)}",
        flush=True,
    )
    print(
        f"Contract signal fields:            {len(contract_field_counts)}",
        flush=True,
    )
    print("Rights classifications applied:     0", flush=True)
    print("Salary values applied:              0", flush=True)
    print("Checkpoint write:       NOT PERFORMED", flush=True)
    print(f"Audit ZIP: {audit_zip}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
