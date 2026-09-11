from __future__ import annotations

import csv
import hashlib
import io
import json
import pickle
import re
import tempfile
import types
import zipfile
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable


VERSION = "fa-official-team-salary-missing-components-probe-v1-2026-08-15"
SEASON_LABEL = "2026-27"
EXPECTED_CHECKPOINT_SHA256 = (
    "19f2fee601f5765bde4f5fabea34f20dc9b8ddc8dd5069186502dff08fc0cf9f"
)
MAX_EVIDENCE_ROWS = 100_000
MAX_CHECKPOINT_NODES = 1_000_000

CATEGORY_PATTERNS = {
    "dead_money_or_retained_salary": re.compile(
        r"dead[_ ]?(money|cap)|waiv(?:ed|er|ing)?[_ ]?(salary|amount|cap|charge)|"
        r"stretch(?:ed|ing)?[_ ]?(salary|amount|cap|charge)|retained[_ ]?(salary|amount|cap|charge)",
        re.I,
    ),
    "incentive_or_bonus": re.compile(
        r"incentive|likely[_ ]?(bonus|incentive)|unlikely[_ ]?(bonus|incentive)|"
        r"performance[_ ]?bonus|signing[_ ]?bonus|bonus[_ ]?(allocation|amount|cap|charge)",
        re.I,
    ),
    "rookie_pick_hold_or_salary": re.compile(
        r"rookie[_ ]?scale[_ ]?pending|rookie.*(?:salary|hold|amount|scale)|"
        r"draft.*(?:salary|hold|amount)|unsigned.*first.*round|first[_ ]?round.*(?:cap[_ ]?hold|salary|amount)",
        re.I,
    ),
    "team_salary_or_cap_hit_snapshot": re.compile(
        r"team[_ ]?salary|cap[_ ]?hit|cap[_ ]?charge|salary[_ ]?charge", re.I
    ),
    "waiver_or_draft_status_signal": re.compile(
        r"waiv(?:ed|er|ing)|stretch(?:ed|ing)?|rookie[_ ]?scale[_ ]?pending|"
        r"draft(?:ed|_result|_status)|unsigned[_ ]?pick",
        re.I,
    ),
}

SKIP_PARTS = {
    ".git",
    ".venv",
    "venv",
    "env",
    "node_modules",
    "__pycache__",
    "backups",
}


def clean(value: Any) -> str:
    return str(value or "").strip()


def pid(value: Any) -> str:
    text = clean(value)
    return text[:-2] if text.endswith(".0") and text[:-2].isdigit() else text


def as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return clean(value).lower() in {"true", "1", "yes", "y"}


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


def should_skip(path: Path, root: Path) -> bool:
    try:
        relative = path.relative_to(root)
    except ValueError:
        return True
    return any(part in SKIP_PARTS or part.startswith(".faofficialteamsalaryprobe") for part in relative.parts)


def categories_for(label: str, value: Any = "") -> list[str]:
    combined = f"{label} {clean(value)}"
    return [name for name, pattern in CATEGORY_PATTERNS.items() if pattern.search(combined)]


def numeric_text(value: Any) -> str:
    if value is None or isinstance(value, bool):
        return ""
    if isinstance(value, (int, float, Decimal)):
        return clean(value)
    text = clean(value).replace("$", "").replace(",", "")
    if not text:
        return ""
    try:
        Decimal(text)
        return text
    except InvalidOperation:
        return ""


def identity_columns(fieldnames: list[str]) -> dict[str, str]:
    lower = {name.lower(): name for name in fieldnames}

    def first(options: Iterable[str]) -> str:
        return next((lower[name] for name in options if name in lower), "")

    return {
        "player_id": first(("player_id", "nba_player_id", "person_id")),
        "player_name": first(("player_name", "name", "full_name")),
        "team": first(
            (
                "team",
                "team_abbreviation",
                "team_abbr",
                "owner",
                "current_team",
                "prior_team",
                "drafting_team",
            )
        ),
        "season": first(("season", "season_label", "salary_cap_year")),
        "pick": first(("pick", "pick_number", "overall_pick", "draft_pick")),
    }


def scan_csv_text(
    text: str,
    *,
    source_type: str,
    source_file: str,
    source_member: str,
    schema_rows: list[dict[str, Any]],
    evidence_rows: list[dict[str, Any]],
) -> None:
    reader = csv.DictReader(io.StringIO(text))
    fieldnames = list(reader.fieldnames or [])
    rows = list(reader)
    identities = identity_columns(fieldnames)
    for category in CATEGORY_PATTERNS:
        matched = [field for field in fieldnames if category in categories_for(field)]
        if not matched:
            continue
        schema_rows.append(
            {
                "source_type": source_type,
                "source_file": source_file,
                "source_member": source_member,
                "row_count": len(rows),
                "category": category,
                "matched_columns": " | ".join(matched),
                **{f"{key}_column": value for key, value in identities.items()},
            }
        )
        for row_number, row in enumerate(rows, start=2):
            nonblank = {field: clean(row.get(field)) for field in matched if clean(row.get(field))}
            if not nonblank or len(evidence_rows) >= MAX_EVIDENCE_ROWS:
                continue
            numbers = {
                field: numeric_text(value)
                for field, value in nonblank.items()
                if numeric_text(value)
            }
            evidence_rows.append(
                {
                    "source_type": source_type,
                    "source_file": source_file,
                    "source_member": source_member,
                    "row_number": row_number,
                    "category": category,
                    "player_id": pid(row.get(identities["player_id"])) if identities["player_id"] else "",
                    "player_name": clean(row.get(identities["player_name"])) if identities["player_name"] else "",
                    "team": clean(row.get(identities["team"])) if identities["team"] else "",
                    "season": clean(row.get(identities["season"])) if identities["season"] else "",
                    "pick_number": clean(row.get(identities["pick"])) if identities["pick"] else "",
                    "evidence_fields_json": json.dumps(nonblank, sort_keys=True),
                    "numeric_fields_json": json.dumps(numbers, sort_keys=True),
                    "has_numeric_candidate": bool(numbers),
                }
            )


def scan_json_value(
    value: Any,
    *,
    source_type: str,
    source_file: str,
    source_member: str,
    signal_rows: list[dict[str, Any]],
    path: str = "$",
    depth: int = 0,
) -> None:
    if depth > 20 or len(signal_rows) >= MAX_EVIDENCE_ROWS:
        return
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if isinstance(child, (str, int, float, bool, type(None))):
                for category in categories_for(child_path, child):
                    signal_rows.append(
                        {
                            "source_type": source_type,
                            "source_file": source_file,
                            "source_member": source_member,
                            "object_path": child_path,
                            "category": category,
                            "raw_value": clean(child),
                            "numeric_value": numeric_text(child),
                        }
                    )
            else:
                scan_json_value(
                    child,
                    source_type=source_type,
                    source_file=source_file,
                    source_member=source_member,
                    signal_rows=signal_rows,
                    path=child_path,
                    depth=depth + 1,
                )
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            scan_json_value(
                child,
                source_type=source_type,
                source_file=source_file,
                source_member=source_member,
                signal_rows=signal_rows,
                path=f"{path}[{index}]",
                depth=depth + 1,
            )


def scan_checkpoint(checkpoint: Any) -> tuple[list[dict[str, Any]], int, bool]:
    signals: list[dict[str, Any]] = []
    seen: set[int] = set()
    node_count = 0
    truncated = False

    def walk(value: Any, path: str, depth: int) -> None:
        nonlocal node_count, truncated
        node_count += 1
        if node_count > MAX_CHECKPOINT_NODES:
            truncated = True
            return
        if depth > 24 or truncated:
            return
        if isinstance(value, (str, int, float, bool, type(None), Decimal)):
            for category in categories_for(path, value):
                signals.append(
                    {
                        "source_type": "checkpoint_object",
                        "source_file": "canonical_checkpoint",
                        "source_member": "",
                        "object_path": path,
                        "category": category,
                        "raw_value": clean(value),
                        "numeric_value": numeric_text(value),
                    }
                )
            return
        if isinstance(value, (types.ModuleType, type)) or callable(value):
            return
        object_id = id(value)
        if object_id in seen:
            return
        seen.add(object_id)
        if isinstance(value, dict):
            for key, child in value.items():
                walk(child, f"{path}.{key}", depth + 1)
        elif isinstance(value, (list, tuple, set)):
            for index, child in enumerate(value):
                walk(child, f"{path}[{index}]", depth + 1)
        elif hasattr(value, "__dict__"):
            for key, child in vars(value).items():
                if not key.startswith("__"):
                    walk(child, f"{path}.{key}", depth + 1)

    walk(checkpoint, "$checkpoint", 0)
    return signals, node_count, truncated


def main() -> int:
    root = Path.cwd().resolve()
    posture_zip = latest(root, "fa_team_base_salary_and_rights_posture_preview_v1_2026-27_*.zip")
    with zipfile.ZipFile(posture_zip) as archive:
        posture_summary = json_suffix(archive, "team_base_salary_and_rights_posture_summary.json")
        salary_rows = csv_suffix(archive, "active_listed_salary_evidence_361.csv")
        standard_rows = csv_suffix(archive, "standard_contract_salary_base_331.csv")
        two_way_rows = csv_suffix(archive, "two_way_salary_excluded_30.csv")

    if not posture_summary.get("passed"):
        raise RuntimeError("Upstream team base-salary and rights posture preview did not pass.")

    import simulation_franchise_checkpoint_v1 as checkpoint_module

    checkpoint_path = Path(checkpoint_module.DEFAULT_CHECKPOINT_PATH)
    checkpoint_hash_before = sha256_file(checkpoint_path)
    checkpoint = checkpoint_module.load_franchise_checkpoint()
    simulation_digest_before = object_digest(checkpoint.simulation_state)
    if checkpoint_hash_before != EXPECTED_CHECKPOINT_SHA256:
        raise RuntimeError("Canonical checkpoint changed before missing-components probe.")

    schema_rows: list[dict[str, Any]] = []
    evidence_rows: list[dict[str, Any]] = []
    json_signal_rows: list[dict[str, Any]] = []
    inventory_rows: list[dict[str, Any]] = []
    scan_errors: list[dict[str, Any]] = []
    scanned_zip_count = 0
    scanned_csv_member_count = 0
    scanned_json_member_count = 0

    zip_paths = sorted(
        path
        for path in root.rglob("*.zip")
        if path.is_file()
        and not should_skip(path, root)
        and not path.name.startswith("fa_official_team_salary_missing_components_probe_v1_")
    )
    for zip_path in zip_paths:
        if zip_path == posture_zip:
            # It is still scanned below; this explicit equality is retained for provenance clarity.
            pass
        try:
            with zipfile.ZipFile(zip_path) as archive:
                scanned_zip_count += 1
                for member in archive.namelist():
                    lower_member = member.lower()
                    if any(term in lower_member for term in ("draft", "lottery", "rookie", "waiv", "dead", "incent", "bonus")):
                        inventory_rows.append(
                            {
                                "source_type": "zip_member_inventory",
                                "source_file": str(zip_path.relative_to(root)),
                                "source_member": member,
                                "signal_terms": " | ".join(
                                    term
                                    for term in ("draft", "lottery", "rookie", "waiv", "dead", "incent", "bonus")
                                    if term in lower_member
                                ),
                            }
                        )
                    if member.endswith(".csv"):
                        scanned_csv_member_count += 1
                        scan_csv_text(
                            archive.read(member).decode("utf-8-sig", errors="replace"),
                            source_type="zip_csv",
                            source_file=str(zip_path.relative_to(root)),
                            source_member=member,
                            schema_rows=schema_rows,
                            evidence_rows=evidence_rows,
                        )
                    elif member.endswith(".json"):
                        scanned_json_member_count += 1
                        try:
                            value = json.loads(archive.read(member).decode("utf-8-sig"))
                            scan_json_value(
                                value,
                                source_type="zip_json",
                                source_file=str(zip_path.relative_to(root)),
                                source_member=member,
                                signal_rows=json_signal_rows,
                            )
                        except Exception as exc:
                            scan_errors.append(
                                {
                                    "source_file": str(zip_path.relative_to(root)),
                                    "source_member": member,
                                    "error_type": type(exc).__name__,
                                    "detail": str(exc),
                                }
                            )
        except Exception as exc:
            scan_errors.append(
                {
                    "source_file": str(zip_path.relative_to(root)),
                    "source_member": "",
                    "error_type": type(exc).__name__,
                    "detail": str(exc),
                }
            )

    # Scan standalone CSV/JSON evidence not already sealed into audit ZIPs.
    standalone_paths = sorted(
        path
        for path in root.rglob("*")
        if path.is_file()
        and path.suffix.lower() in {".csv", ".json"}
        and not should_skip(path, root)
        and "outputs/audits" not in path.as_posix()
    )
    for path in standalone_paths:
        try:
            relative = str(path.relative_to(root))
            lower_path = relative.lower()
            if any(term in lower_path for term in ("draft", "lottery", "rookie", "waiv", "dead", "incent", "bonus")):
                inventory_rows.append(
                    {
                        "source_type": "standalone_file_inventory",
                        "source_file": relative,
                        "source_member": "",
                        "signal_terms": " | ".join(
                            term
                            for term in ("draft", "lottery", "rookie", "waiv", "dead", "incent", "bonus")
                            if term in lower_path
                        ),
                    }
                )
            if path.suffix.lower() == ".csv":
                scan_csv_text(
                    path.read_text(encoding="utf-8-sig", errors="replace"),
                    source_type="standalone_csv",
                    source_file=relative,
                    source_member="",
                    schema_rows=schema_rows,
                    evidence_rows=evidence_rows,
                )
            else:
                scan_json_value(
                    json.loads(path.read_text(encoding="utf-8-sig")),
                    source_type="standalone_json",
                    source_file=relative,
                    source_member="",
                    signal_rows=json_signal_rows,
                )
        except Exception as exc:
            scan_errors.append(
                {
                    "source_file": str(path.relative_to(root)),
                    "source_member": "",
                    "error_type": type(exc).__name__,
                    "detail": str(exc),
                }
            )

    checkpoint_signal_rows, checkpoint_node_count, checkpoint_truncated = scan_checkpoint(checkpoint)
    all_signal_rows = json_signal_rows + checkpoint_signal_rows

    # Explicitly preserve the one already-known incentive without promoting it to completeness.
    known_incentive_rows = [
        row
        for row in salary_rows
        if clean(row.get("known_likely_incentive_2026_27"))
        and Decimal(clean(row.get("known_likely_incentive_2026_27"))) > 0
    ]

    category_counts = Counter(row["category"] for row in evidence_rows + all_signal_rows)
    numeric_category_counts = Counter(
        row["category"]
        for row in evidence_rows
        if as_bool(row.get("has_numeric_candidate"))
    )
    numeric_category_counts.update(
        row["category"] for row in all_signal_rows if clean(row.get("numeric_value"))
    )
    rookie_pending_signals = [
        row
        for row in all_signal_rows
        if "rookie_scale_pending" in clean(row.get("raw_value")).lower()
        or "rookie_scale_pending" in clean(row.get("object_path")).lower()
    ]

    readiness_rows = []
    for component, category in (
        ("dead_money_and_retained_salary", "dead_money_or_retained_salary"),
        ("incentives_and_bonus_allocations", "incentive_or_bonus"),
        ("2026_rookie_pick_holds", "rookie_pick_hold_or_salary"),
    ):
        signal_count = category_counts[category]
        numeric_count = numeric_category_counts[category]
        if component == "incentives_and_bonus_allocations":
            numeric_count = max(numeric_count, len(known_incentive_rows))
            signal_count = max(signal_count, len(known_incentive_rows))
        readiness_rows.append(
            {
                "component": component,
                "evidence_signal_count": signal_count,
                "numeric_candidate_count": numeric_count,
                "rookie_scale_pending_signal_count": (
                    len(rookie_pending_signals) if component == "2026_rookie_pick_holds" else 0
                ),
                "complete_exact_30_team_layer_ready": False,
                "status": (
                    "candidate_evidence_found_requires_semantic_resolution"
                    if signal_count
                    else "source_evidence_not_found_in_current_project_tree"
                ),
                "applied_to_team_salary": False,
                "state_mutation_applied": False,
            }
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
    print("2026 OFFICIAL TEAM SALARY MISSING COMPONENTS PROBE V1")
    print("=" * 132)
    print("Discovering dead money, incentives, and 2026 rookie-pick evidence without mutation...")

    add("upstream_team_posture_preview_passed", bool(posture_summary.get("passed")), posture_zip.name)
    add("upstream_population_is_exact_361_331_30", len(salary_rows) == 361 and len(standard_rows) == 331 and len(two_way_rows) == 30, f"salary={len(salary_rows)}, standard={len(standard_rows)}, two_way={len(two_way_rows)}")
    add("project_audit_zip_scan_completed", scanned_zip_count > 0, f"zips={scanned_zip_count}, csv_members={scanned_csv_member_count}, json_members={scanned_json_member_count}")
    add("checkpoint_recursive_scan_completed", checkpoint_node_count > 0 and not checkpoint_truncated, f"nodes={checkpoint_node_count}, truncated={checkpoint_truncated}")
    add("exact_three_missing_component_rows_emitted", len(readiness_rows) == 3, f"rows={len(readiness_rows)}")
    add("all_discovered_schema_rows_retain_provenance", all(clean(row.get("source_file")) and clean(row.get("category")) for row in schema_rows), f"schema_rows={len(schema_rows)}")
    add("all_candidate_evidence_rows_retain_provenance", all(clean(row.get("source_file")) and clean(row.get("category")) for row in evidence_rows), f"evidence_rows={len(evidence_rows)}")
    add("all_object_signal_rows_retain_paths", all(clean(row.get("source_file")) and clean(row.get("object_path")) and clean(row.get("category")) for row in all_signal_rows), f"signal_rows={len(all_signal_rows)}")
    add("known_thomas_sorber_incentive_carried_forward", len(known_incentive_rows) == 1 and pid(known_incentive_rows[0].get("player_id")) == "1642850" and int(Decimal(clean(known_incentive_rows[0].get("known_likely_incentive_2026_27")))) == 814620, f"rows={len(known_incentive_rows)}")
    add("scan_errors_are_exported_not_silenced", all(clean(row.get("source_file")) and clean(row.get("error_type")) for row in scan_errors), f"scan_errors={len(scan_errors)}")
    add("no_missing_component_claimed_complete", all(not row["complete_exact_30_team_layer_ready"] for row in readiness_rows), "Probe is evidence discovery only.")
    add("no_team_salary_component_applied", all(not row["applied_to_team_salary"] and not row["state_mutation_applied"] for row in readiness_rows), "No salary mutation.")

    simulation_digest_after = object_digest(checkpoint.simulation_state)
    checkpoint_hash_after = sha256_file(checkpoint_path)
    add("loaded_simulation_state_unchanged", simulation_digest_after == simulation_digest_before, simulation_digest_after)
    add("checkpoint_file_unchanged", checkpoint_hash_after == checkpoint_hash_before == EXPECTED_CHECKPOINT_SHA256, checkpoint_hash_after)

    failed = [row["check_id"] for row in checks if row["status"] == "FAIL"]
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    export_id = f"fa_official_team_salary_missing_components_probe_v1_{SEASON_LABEL}_{timestamp}"
    output_dir = root / "outputs" / "audits"
    output_dir.mkdir(parents=True, exist_ok=True)
    audit_zip = output_dir / f"{export_id}.zip"
    summary = {
        "version": VERSION,
        "source_team_posture_audit": posture_zip.name,
        "attached_salary_count": len(salary_rows),
        "standard_contract_count": len(standard_rows),
        "two_way_contract_count": len(two_way_rows),
        "scanned_zip_count": scanned_zip_count,
        "scanned_csv_member_count": scanned_csv_member_count,
        "scanned_json_member_count": scanned_json_member_count,
        "standalone_file_count": len(standalone_paths),
        "checkpoint_node_count": checkpoint_node_count,
        "checkpoint_scan_truncated": checkpoint_truncated,
        "schema_signal_count": len(schema_rows),
        "candidate_evidence_count": len(evidence_rows),
        "object_signal_count": len(all_signal_rows),
        "inventory_signal_count": len(inventory_rows),
        "scan_error_count": len(scan_errors),
        "category_signal_counts": dict(sorted(category_counts.items())),
        "numeric_category_counts": dict(sorted(numeric_category_counts.items())),
        "rookie_scale_pending_signal_count": len(rookie_pending_signals),
        "known_likely_incentive_count": len(known_incentive_rows),
        "known_likely_incentive_total": sum(int(Decimal(clean(row.get("known_likely_incentive_2026_27")))) for row in known_incentive_rows),
        "component_readiness": readiness_rows,
        "official_team_salary_complete": False,
        "components_applied": 0,
        "state_mutation_performed": False,
        "checkpoint_write_performed": False,
        "passed": not failed,
        "failed_checks": failed,
        "next_slice": (
            "Use the discovered source schemas and checkpoint signals to resolve exact dead-money, "
            "incentive, and 2026 rookie-pick hold targets without revising rights decisions."
        ),
    }

    with tempfile.TemporaryDirectory(prefix="fa_official_team_salary_missing_components_probe_") as temporary_directory:
        export = Path(temporary_directory) / export_id
        export.mkdir(parents=True)
        write_csv(export / "component_source_schema_discovery.csv", schema_rows)
        write_csv(export / "component_candidate_evidence.csv", evidence_rows)
        write_csv(export / "object_and_checkpoint_component_signals.csv", all_signal_rows)
        write_csv(export / "draft_waiver_incentive_source_inventory.csv", inventory_rows)
        write_csv(export / "known_likely_incentives_carried_forward.csv", known_incentive_rows)
        write_csv(export / "missing_component_readiness_board.csv", readiness_rows)
        write_csv(export / "missing_component_scan_errors.csv", scan_errors)
        write_csv(export / "missing_component_probe_checks.csv", checks)
        (export / "missing_component_probe_summary.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8"
        )
        (export / "README.txt").write_text(
            """2026 OFFICIAL TEAM SALARY MISSING COMPONENTS PROBE V1
======================================================

Purpose
-------
Discover the project-native sources needed to finish official 2026-27 Team
Salary: dead money/retained salary, incentives/bonus allocations, and generated
2026 rookie-pick cap holds.

This probe recursively inspects the loaded checkpoint and scans project audit
ZIP/CSV/JSON schemas. It preserves every candidate with source provenance, but
does not promote a field merely because its name looks financially relevant.

Safety
------
No QO, RFA status, cap hold, rights decision, renouncement, salary, roster,
simulation, overlay, or checkpoint mutation occurs.
""",
            encoding="utf-8",
        )
        with zipfile.ZipFile(audit_zip, "w", zipfile.ZIP_DEFLATED) as archive:
            for item in sorted(export.iterdir()):
                archive.write(item, arcname=f"{export_id}/{item.name}")

    if failed:
        print("")
        print(f"Diagnostic audit ZIP: {audit_zip}")
        raise RuntimeError("Missing Components Probe V1 failed: " + ", ".join(failed))

    print("")
    print("=" * 132)
    print("2026 OFFICIAL TEAM SALARY MISSING COMPONENTS PROBE V1 PASSED")
    print("=" * 132)
    print(f"Audit ZIPs scanned:          {scanned_zip_count}")
    print(f"CSV members scanned:         {scanned_csv_member_count}")
    print(f"JSON members scanned:        {scanned_json_member_count}")
    print(f"Checkpoint nodes scanned:    {checkpoint_node_count}")
    print(f"Schema signals:              {len(schema_rows)}")
    print(f"Candidate evidence rows:     {len(evidence_rows)}")
    print(f"Object/checkpoint signals:   {len(all_signal_rows)}")
    print(f"Rookie-scale pending signals:{len(rookie_pending_signals):>6}")
    print("Components applied:                    0")
    print("Official Team Salary complete:        NO")
    print("Checkpoint write:          NOT PERFORMED")
    print(f"Audit ZIP: {audit_zip}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
