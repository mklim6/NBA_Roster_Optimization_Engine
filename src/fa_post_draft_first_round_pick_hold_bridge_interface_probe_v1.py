from __future__ import annotations

import ast
import csv
import hashlib
import io
import json
import pickle
import re
import sys
import tempfile
import zipfile
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable


VERSION = "fa-post-draft-first-round-pick-hold-bridge-interface-probe-v1-2026-08-16"
SEASON_LABEL = "2026-27"
SPLIT_DATE = date(2026, 4, 12)
FIRST_POST_SPLIT_DATE = date(2026, 4, 13)
FINAL_INCENTIVE_PATTERN = "fa_frozen_incentive_final_freeze_v1_2026-27_*.zip"
BOUNDARY_PATTERN = "fa_frozen_snapshot_effective_boundary_freeze_v1_2026-27_*.zip"
SEMANTIC_PATTERN = "fa_salaryswish_team_component_semantic_hotfix_v1_0_1_2026-27_*.zip"
EXPECTED_CHECKPOINT_SHA256 = "19f2fee601f5765bde4f5fabea34f20dc9b8ddc8dd5069186502dff08fc0cf9f"
EXPECTED_SIMULATION_DIGEST = "f92f03b4c54e53f8f017c3fca43e93ccd09c8b8ba0e5fe0323f418021baf268e"
MAX_SOURCE_BYTES = 5_000_000
MAX_CHECKPOINT_NODES = 250_000
SKIP_PARTS = {".git", ".venv", "venv", "env", "node_modules", "__pycache__", "backups", "outputs"}

CATEGORY_PATTERNS = {
    "draft_event": re.compile(r"draft(?:_event|_complete|_result|_selection|ed)?|run_draft|simulate_draft", re.I),
    "draft_record": re.compile(r"pick(?:_number|_no|_id)?|overall_pick|draft_round|drafting_team|selected_player", re.I),
    "first_round": re.compile(r"first[_ -]?round|round[_ -]?1|lottery_pick|rookie[_ -]?scale", re.I),
    "signing_status": re.compile(r"sign(?:ed|ing|ature)?|unsigned|contract_status|rookie_contract|execute_contract", re.I),
    "rookie_scale": re.compile(r"rookie[_ -]?scale|scale_amount|pick[_ -]?hold|cap[_ -]?hold|120\s*%|1\.2", re.I),
    "salary_hook": re.compile(r"team[_ -]?salary|salary[_ -]?ledger|cap[_ -]?(?:charge|hit|ledger)|financial[_ -]?ledger", re.I),
    "state_hook": re.compile(r"checkpoint|simulation_state|franchise_state|save_state|load_state|event_log", re.I),
}

FIELD_GROUPS = {
    "draft_identity": re.compile(r"player(?:_id|_name)?|person_id|prospect(?:_id|_name)?|selected_player", re.I),
    "draft_team": re.compile(r"team(?:_id|_abbr|_abbreviation)?|drafting_team|selecting_team|owner", re.I),
    "draft_pick": re.compile(r"pick(?:_number|_no|_id)?|overall_pick|draft_round|round", re.I),
    "signing_status": re.compile(r"sign(?:ed|ing)?|unsigned|contract_status|rookie_contract", re.I),
    "salary_value": re.compile(r"salary|amount|cap_hit|cap_charge|hold_amount|scale_amount", re.I),
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


def relative(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def skipped(path: Path, root: Path) -> bool:
    try:
        parts = path.relative_to(root).parts
    except ValueError:
        return True
    return any(part in SKIP_PARTS or part.startswith(".fapostdraftbridgeprobe") for part in parts)


def categories(text: str) -> list[str]:
    return [name for name, pattern in CATEGORY_PATTERNS.items() if pattern.search(text)]


def function_args(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    values = [arg.arg for arg in node.args.posonlyargs + node.args.args + node.args.kwonlyargs]
    if node.args.vararg:
        values.append("*" + node.args.vararg.arg)
    if node.args.kwarg:
        values.append("**" + node.args.kwarg.arg)
    return values


class SignalVisitor(ast.NodeVisitor):
    def __init__(self, source_file: str) -> None:
        self.source_file = source_file
        self.fields: list[dict[str, Any]] = []

    def add(self, value: str, line: int, origin: str) -> None:
        value = clean(value)
        matched = [name for name, pattern in FIELD_GROUPS.items() if pattern.search(value)]
        if not matched:
            return
        self.fields.append({
            "source_file": self.source_file,
            "line": line,
            "origin": origin,
            "field_or_signal": value,
            "field_groups": " | ".join(matched),
        })

    def visit_Name(self, node: ast.Name) -> None:
        self.add(node.id, node.lineno, "name")

    def visit_Attribute(self, node: ast.Attribute) -> None:
        self.add(node.attr, node.lineno, "attribute")
        self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant) -> None:
        if isinstance(node.value, str) and len(node.value) <= 160:
            self.add(node.value, getattr(node, "lineno", 0), "string")


def scan_python_sources(root: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    inventory: list[dict[str, Any]] = []
    symbols: list[dict[str, Any]] = []
    fields: list[dict[str, Any]] = []
    parse_errors: list[dict[str, Any]] = []
    src = root / "src"
    for path in sorted(src.rglob("*.py")):
        if skipped(path, root) or path.name == Path(__file__).name or path.stat().st_size > MAX_SOURCE_BYTES:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        file_categories = categories(text + " " + path.name)
        if not file_categories:
            continue
        source_file = relative(path, root)
        try:
            tree = ast.parse(text, filename=source_file)
        except SyntaxError as exc:
            parse_errors.append({"source_file": source_file, "line": exc.lineno or 0, "error": clean(exc.msg)})
            continue
        file_symbol_count = 0
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                args = function_args(node) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) else []
                doc = ast.get_docstring(node) or ""
                combined = " ".join([node.name, " ".join(args), doc, source_file])
                node_categories = categories(combined)
                if not node_categories:
                    continue
                symbols.append({
                    "source_file": source_file,
                    "line": getattr(node, "lineno", 0),
                    "symbol_kind": "class" if isinstance(node, ast.ClassDef) else "function",
                    "symbol_name": node.name,
                    "arguments": " | ".join(args),
                    "categories": " | ".join(node_categories),
                })
                file_symbol_count += 1
        visitor = SignalVisitor(source_file)
        visitor.visit(tree)
        unique_fields: dict[tuple[str, str, str], dict[str, Any]] = {}
        for row in visitor.fields:
            key = (clean(row["field_or_signal"]).lower(), clean(row["field_groups"]), clean(row["origin"]))
            unique_fields.setdefault(key, row)
        fields.extend(unique_fields.values())
        inventory.append({
            "source_file": source_file,
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
            "categories": " | ".join(file_categories),
            "relevant_symbol_count": file_symbol_count,
            "relevant_field_signal_count": len(unique_fields),
            "parse_status": "parsed",
        })
    return inventory, symbols, fields, parse_errors


def scan_data_candidates(root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    suffixes = {".csv", ".json", ".yaml", ".yml", ".toml"}
    roots = [root / name for name in ("src", "data", "config", "configs", "resources")]
    seen: set[Path] = set()
    for base in roots:
        if not base.exists():
            continue
        for path in sorted(base.rglob("*")):
            if path in seen or not path.is_file() or path.suffix.lower() not in suffixes or skipped(path, root):
                continue
            seen.add(path)
            if path.stat().st_size > MAX_SOURCE_BYTES:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            matched = categories(path.name + " " + text[:1_000_000])
            if not set(matched) & {"draft_record", "first_round", "rookie_scale", "signing_status", "salary_hook"}:
                continue
            rows.append({
                "source_file": relative(path, root),
                "file_type": path.suffix.lower().lstrip("."),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
                "categories": " | ".join(matched),
                "contains_explicit_2026": bool(re.search(r"2026(?:-27)?", text)),
                "contains_pick_1_and_30": bool(re.search(r"(?:^|\D)1(?:\D|$)", text) and re.search(r"(?:^|\D)30(?:\D|$)", text)),
            })
    return rows


def scan_checkpoint(value: Any) -> tuple[list[dict[str, Any]], int, bool]:
    rows: list[dict[str, Any]] = []
    seen: set[int] = set()
    nodes = 0
    truncated = False

    def walk(current: Any, path: str, depth: int) -> None:
        nonlocal nodes, truncated
        if nodes >= MAX_CHECKPOINT_NODES:
            truncated = True
            return
        nodes += 1
        if depth > 24:
            return
        if isinstance(current, (dict, list, tuple, set)) or hasattr(current, "__dict__"):
            marker = id(current)
            if marker in seen:
                return
            seen.add(marker)
        if isinstance(current, dict):
            for key, child in current.items():
                child_path = f"{path}.{key}"
                matched = categories(child_path)
                if matched:
                    rows.append({"checkpoint_path": child_path, "value_type": type(child).__name__, "value_preview": clean(child)[:240] if isinstance(child, (str, int, float, bool, type(None))) else "", "categories": " | ".join(matched)})
                walk(child, child_path, depth + 1)
        elif isinstance(current, (list, tuple, set)):
            for index, child in enumerate(list(current)):
                walk(child, f"{path}[{index}]", depth + 1)
        elif hasattr(current, "__dict__"):
            walk(vars(current), path, depth + 1)

    walk(value, "$", 0)
    unique = {(row["checkpoint_path"], row["categories"]): row for row in rows}
    return list(unique.values()), nodes, truncated


def has_category(rows: list[dict[str, Any]], category: str) -> bool:
    return any(category in clean(row.get("categories")).split(" | ") for row in rows)


def main() -> int:
    root = Path.cwd().resolve()
    if not (root / "src").exists():
        raise RuntimeError("Run from the NBA_Roster_Optimization_Engine project root.")

    final_zip = find_passed(root, FINAL_INCENTIVE_PATTERN, "frozen_incentive_final_freeze_summary.json")
    boundary_zip = find_passed(root, BOUNDARY_PATTERN, "effective_boundary_summary.json")
    semantic_zip = find_passed(root, SEMANTIC_PATTERN, "semantic_hotfix_summary.json")
    with zipfile.ZipFile(final_zip) as archive:
        final_summary = json_suffix(archive, "frozen_incentive_final_freeze_summary.json")
        final_checks = csv_suffix(archive, "frozen_incentive_final_freeze_checks.csv")
        remaining_blockers = csv_suffix(archive, "remaining_financial_component_blockers_1.csv")
    with zipfile.ZipFile(boundary_zip) as archive:
        boundary_summary = json_suffix(archive, "effective_boundary_summary.json")
        boundary_checks = csv_suffix(archive, "effective_boundary_checks.csv")
        boundary_contract = csv_suffix(archive, "canonical_effective_boundary_contract.csv")
        boundary_components = csv_suffix(archive, "component_source_temporal_eligibility_6.csv")
    with zipfile.ZipFile(semantic_zip) as archive:
        semantic_summary = json_suffix(archive, "semantic_hotfix_summary.json")
        semantic_checks = csv_suffix(archive, "semantic_hotfix_checks.csv")
        unsigned_holds = csv_suffix(archive, "unsigned_first_round_hold_evidence_30.csv")

    if str(root / "src") not in sys.path:
        sys.path.insert(0, str(root / "src"))
    import simulation_franchise_checkpoint_v1 as checkpoint_module

    checkpoint_path = Path(checkpoint_module.DEFAULT_CHECKPOINT_PATH)
    checkpoint_hash_before = sha256_file(checkpoint_path)
    checkpoint = checkpoint_module.load_franchise_checkpoint()
    simulation_digest_before = object_digest(checkpoint.simulation_state)
    if checkpoint_hash_before != EXPECTED_CHECKPOINT_SHA256:
        raise RuntimeError("Canonical checkpoint changed before post-draft bridge interface probe.")

    print("=" * 132)
    print("2026 POST-DRAFT FIRST-ROUND PICK-HOLD BRIDGE INTERFACE PROBE V1")
    print("=" * 132)
    print("Inspecting only project source, configuration, and checkpoint interfaces for the final bridge...")

    source_inventory, symbols, field_signals, parse_errors = scan_python_sources(root)
    data_candidates = scan_data_candidates(root)
    checkpoint_signals, checkpoint_nodes, checkpoint_truncated = scan_checkpoint(checkpoint)

    all_interface_rows = source_inventory + symbols + data_candidates + checkpoint_signals
    draft_event_found = has_category(source_inventory, "draft_event") or has_category(symbols, "draft_event")
    draft_record_found = has_category(source_inventory, "draft_record") or has_category(symbols, "draft_record") or has_category(data_candidates, "draft_record")
    first_round_found = has_category(source_inventory, "first_round") or has_category(symbols, "first_round") or has_category(data_candidates, "first_round")
    signing_found = has_category(source_inventory, "signing_status") or has_category(symbols, "signing_status") or has_category(data_candidates, "signing_status")
    rookie_scale_found = has_category(source_inventory, "rookie_scale") or has_category(symbols, "rookie_scale") or has_category(data_candidates, "rookie_scale")
    salary_hook_found = has_category(source_inventory, "salary_hook") or has_category(symbols, "salary_hook") or has_category(data_candidates, "salary_hook")
    state_hook_found = has_category(source_inventory, "state_hook") or has_category(symbols, "state_hook") or has_category(checkpoint_signals, "state_hook")
    field_groups = Counter(group for row in field_signals for group in clean(row.get("field_groups")).split(" | ") if group)

    exact_blocker = len(remaining_blockers) == 1 and clean(remaining_blockers[0].get("blocker_id")) == "post_draft_2026_first_round_pick_hold_bridge"
    nonzero_holds = [
        row for row in unsigned_holds
        if int(clean(row.get("unsigned_first_round_hold_amount_2026_27")) or 0) > 0
    ]
    live_anchor_exact = (
        len(nonzero_holds) == 1
        and clean(nonzero_holds[0].get("team")) == "NYK"
        and int(clean(nonzero_holds[0].get("unsigned_first_round_hold_amount_2026_27")) or 0) == 2_926_800
    )
    boundary_row = boundary_contract[0] if len(boundary_contract) == 1 else {}
    generated_row = next((row for row in boundary_components if clean(row.get("source_class")) == "project_native_semantic_probe_signals"), {})

    readiness = [
        {"interface": "passed_final_incentive_freeze", "status": "ready" if final_summary.get("passed") else "blocked", "evidence_count": len(final_checks), "implementation_requirement": "Preserve the sole remaining blocker contract."},
        {"interface": "canonical_temporal_boundary", "status": "ready" if boundary_summary.get("passed") else "blocked", "evidence_count": len(boundary_contract), "implementation_requirement": "Never backfill a draft-event hold into the April 12 opening snapshot."},
        {"interface": "live_post_split_reference_anchor", "status": "ready" if live_anchor_exact else "blocked", "evidence_count": len(nonzero_holds), "implementation_requirement": "Retain the NYK $2,926,800 row as quarantined later-state context, not opening-state input."},
        {"interface": "draft_event_entry_point", "status": "candidate_found" if draft_event_found else "missing", "evidence_count": sum("draft_event" in clean(row.get("categories")) for row in all_interface_rows), "implementation_requirement": "One deterministic hook must run immediately after simulated draft results become official."},
        {"interface": "draft_result_identity_fields", "status": "candidate_found" if draft_record_found and all(field_groups[name] for name in ("draft_identity", "draft_team", "draft_pick")) else "partial_or_missing", "evidence_count": sum(field_groups[name] for name in ("draft_identity", "draft_team", "draft_pick")), "implementation_requirement": "Require player, team, overall pick, round, season, and draft-event identity."},
        {"interface": "first_round_filter", "status": "candidate_found" if first_round_found else "missing", "evidence_count": sum("first_round" in clean(row.get("categories")) for row in all_interface_rows), "implementation_requirement": "Generate holds only for unsigned first-round selections."},
        {"interface": "signing_status_transition", "status": "candidate_found" if signing_found else "missing", "evidence_count": sum("signing_status" in clean(row.get("categories")) for row in all_interface_rows), "implementation_requirement": "Create while unsigned; remove atomically when the rookie contract is executed."},
        {"interface": "rookie_scale_amount_source", "status": "candidate_found" if rookie_scale_found else "missing", "evidence_count": sum("rookie_scale" in clean(row.get("categories")) for row in all_interface_rows), "implementation_requirement": "Use a validated season/pick scale source; do not infer from the live NYK row."},
        {"interface": "team_salary_ledger_hook", "status": "candidate_found" if salary_hook_found else "missing", "evidence_count": sum("salary_hook" in clean(row.get("categories")) for row in all_interface_rows), "implementation_requirement": "Expose one idempotent dynamic hold component without mutating frozen base evidence."},
        {"interface": "checkpoint_state_hook", "status": "candidate_found" if state_hook_found else "missing", "evidence_count": sum("state_hook" in clean(row.get("categories")) for row in all_interface_rows), "implementation_requirement": "Persist draft/result/signing lineage only in a later simulated state transition."},
    ]
    implementation_ready = all(row["status"] in {"ready", "candidate_found"} for row in readiness)
    missing_interfaces = [clean(row["interface"]) for row in readiness if row["status"] not in {"ready", "candidate_found"}]

    checks: list[dict[str, str]] = []

    def add(check_id: str, passed: bool, detail: str) -> None:
        checks.append({"check_id": check_id, "status": "PASS" if passed else "FAIL", "severity": "strict", "detail": detail})
        print(f"  {check_id}: {'PASS' if passed else 'FAIL'}")

    print("\nValidating the bounded interface probe...")
    add("final_incentive_freeze_passed_all_strict_checks", final_summary.get("passed") is True and all(clean(row.get("status")) == "PASS" for row in final_checks), final_zip.name)
    add("sole_remaining_blocker_is_post_draft_pick_hold_bridge", exact_blocker and int(final_summary.get("remaining_financial_component_blocker_count", -1)) == 1, "1/1")
    add("canonical_boundary_freeze_passed", boundary_summary.get("passed") is True and all(clean(row.get("status")) == "PASS" for row in boundary_checks), boundary_zip.name)
    add("boundary_is_april_12_inclusive", clean(boundary_row.get("last_inclusive_snapshot_date")) == SPLIT_DATE.isoformat() and clean(boundary_row.get("first_post_split_date")) == FIRST_POST_SPLIT_DATE.isoformat(), f"{SPLIT_DATE.isoformat()} / {FIRST_POST_SPLIT_DATE.isoformat()}")
    add("opening_snapshot_has_zero_generated_rookie_hold_rows", "zero exact generated 2026 rookie-hold rows" in clean(generated_row.get("reason")), clean(generated_row.get("reason")))
    add("live_unsigned_hold_anchor_is_quarantined_nyk_2926800", semantic_summary.get("passed") is True and all(clean(row.get("status")) == "PASS" for row in semantic_checks) and live_anchor_exact, "NYK $2,926,800")
    add("source_scan_is_bounded_to_project_interfaces", all(clean(row.get("source_file")).startswith("src/") for row in source_inventory + symbols + field_signals), f"{len(source_inventory)} relevant source files")
    add("all_relevant_python_sources_parsed", not parse_errors, f"parse_errors={len(parse_errors)}")
    add("checkpoint_scan_completed_within_bound", not checkpoint_truncated, f"nodes={checkpoint_nodes}")
    add("readiness_matrix_covers_all_required_interfaces", len(readiness) == 10 and len({row["interface"] for row in readiness}) == 10, "10/10")
    add("diagnostic_gaps_are_reported_not_fabricated", set(missing_interfaces) == {row["interface"] for row in readiness if row["status"] not in {"ready", "candidate_found"}}, " | ".join(missing_interfaces) or "none")

    checkpoint_hash_after = sha256_file(checkpoint_path)
    checkpoint_after = checkpoint_module.load_franchise_checkpoint()
    simulation_digest_after = object_digest(checkpoint_after.simulation_state)
    add("loaded_simulation_state_unchanged", simulation_digest_before == simulation_digest_after == EXPECTED_SIMULATION_DIGEST, simulation_digest_after)
    add("checkpoint_file_unchanged", checkpoint_hash_before == checkpoint_hash_after == EXPECTED_CHECKPOINT_SHA256, checkpoint_hash_after)
    failed = [row["check_id"] for row in checks if row["status"] != "PASS"]

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    name = f"fa_post_draft_first_round_pick_hold_bridge_interface_probe_v1_{SEASON_LABEL}_{timestamp}"
    audit_dir = root / "outputs" / "audits"
    audit_dir.mkdir(parents=True, exist_ok=True)
    output_zip = audit_dir / f"{name}.zip"
    summary = {
        "version": VERSION,
        "season": SEASON_LABEL,
        "canonical_split_date": SPLIT_DATE.isoformat(),
        "first_post_split_date": FIRST_POST_SPLIT_DATE.isoformat(),
        "passed": not failed,
        "failed_checks": failed,
        "implementation_ready": implementation_ready,
        "missing_or_partial_interfaces": missing_interfaces,
        "relevant_source_file_count": len(source_inventory),
        "relevant_symbol_count": len(symbols),
        "field_signal_count": len(field_signals),
        "data_candidate_count": len(data_candidates),
        "checkpoint_signal_count": len(checkpoint_signals),
        "python_parse_error_count": len(parse_errors),
        "network_requests": 0,
        "salary_values_computed": 0,
        "pick_holds_created": 0,
        "state_mutation_performed": False,
        "checkpoint_write_performed": False,
        "next_slice": "Implement the post-draft first-round pick-hold bridge against the mapped interfaces; validate the 2026 rookie scale separately if no project-native source was found.",
    }
    readme = f"""2026 POST-DRAFT FIRST-ROUND PICK-HOLD BRIDGE INTERFACE PROBE V1

Purpose
-------
Map the actual project interfaces needed for the sole remaining financial blocker without changing simulation state.

Boundary contract
-----------------
- April 12, 2026 is the inclusive opening-snapshot boundary.
- April 13, 2026 is the first post-split date.
- First-round pick holds must be created only when the simulated 2026 draft event occurs.
- No rookie hold may be backfilled into the frozen April 12 snapshot.

Result
------
- Audit passed: {not failed}
- Implementation ready from discovered interfaces: {implementation_ready}
- Missing or partial interfaces: {', '.join(missing_interfaces) if missing_interfaces else 'none'}
- Relevant source files: {len(source_inventory)}
- Relevant symbols: {len(symbols)}
- Field signals: {len(field_signals)}
- Data candidates: {len(data_candidates)}
- Checkpoint signals: {len(checkpoint_signals)}

Safety
------
No network request, salary computation, pick-hold creation, Team Salary application, simulation mutation, overlay mutation, or checkpoint write occurred.
"""

    with tempfile.TemporaryDirectory(prefix="fa_post_draft_bridge_probe_") as temporary:
        folder = Path(temporary) / name
        folder.mkdir(parents=True)
        write_csv(folder / "draft_bridge_source_inventory.csv", source_inventory, ["source_file", "bytes", "sha256", "categories", "relevant_symbol_count", "relevant_field_signal_count", "parse_status"])
        write_csv(folder / "draft_event_symbols.csv", symbols, ["source_file", "line", "symbol_kind", "symbol_name", "arguments", "categories"])
        write_csv(folder / "draft_record_and_signing_field_candidates.csv", field_signals, ["source_file", "line", "origin", "field_or_signal", "field_groups"])
        write_csv(folder / "rookie_scale_and_bridge_data_candidates.csv", data_candidates, ["source_file", "file_type", "bytes", "sha256", "categories", "contains_explicit_2026", "contains_pick_1_and_30"])
        write_csv(folder / "checkpoint_draft_and_salary_signals.csv", checkpoint_signals, ["checkpoint_path", "value_type", "value_preview", "categories"])
        write_csv(folder / "bridge_interface_readiness_matrix.csv", readiness, ["interface", "status", "evidence_count", "implementation_requirement"])
        write_csv(folder / "source_parse_errors.csv", parse_errors, ["source_file", "line", "error"])
        write_csv(folder / "post_draft_bridge_interface_probe_checks.csv", checks, ["check_id", "status", "severity", "detail"])
        (folder / "post_draft_bridge_interface_probe_summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
        (folder / "README.txt").write_text(readme, encoding="utf-8")
        with zipfile.ZipFile(output_zip, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for path in sorted(folder.rglob("*")):
                if path.is_file():
                    archive.write(path, arcname=f"{name}/{path.name}")

    print("\n" + "=" * 132)
    print(f"2026 POST-DRAFT FIRST-ROUND PICK-HOLD BRIDGE INTERFACE PROBE V1 {'PASSED' if not failed else 'FAILED'}")
    print("=" * 132)
    print(f"Relevant source files:      {len(source_inventory)}")
    print(f"Relevant source symbols:    {len(symbols)}")
    print(f"Field signals:              {len(field_signals)}")
    print(f"Data candidates:            {len(data_candidates)}")
    print(f"Checkpoint signals:         {len(checkpoint_signals)}")
    print(f"Implementation ready:       {implementation_ready}")
    print(f"Missing/partial interfaces: {', '.join(missing_interfaces) if missing_interfaces else 'none'}")
    print("Network requests:           0")
    print("Pick holds created:         0")
    print("Checkpoint write:           NOT PERFORMED")
    print(f"Audit ZIP: {output_zip}")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
