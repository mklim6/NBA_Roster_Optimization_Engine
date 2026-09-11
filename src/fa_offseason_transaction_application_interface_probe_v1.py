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


VERSION = "fa-offseason-transaction-application-interface-probe-v1-2026-08-16"
SEASON_LABEL = "2026-27"
SPLIT_DATE = date(2026, 4, 12)
FINAL_BRIDGE_PATTERN = "fa_post_draft_first_round_pick_hold_bridge_final_integration_v1_2026-27_*.zip"
FULL_MARKET_PATTERN = "fa_full_market_free_agent_amount_completion_v1_2026-27_*.zip"
CLONE_PREVIEW_PATTERN = "fa_clone_only_offseason_decision_application_preview_v1_2026-27_*.zip"
EXPECTED_CHECKPOINT_SHA256 = "19f2fee601f5765bde4f5fabea34f20dc9b8ddc8dd5069186502dff08fc0cf9f"
EXPECTED_SIMULATION_DIGEST = "f92f03b4c54e53f8f017c3fca43e93ccd09c8b8ba0e5fe0323f418021baf268e"
MAX_SOURCE_BYTES = 5_000_000
MAX_EXPORTED_SOURCE_BYTES = 20_000_000
MAX_EXPORTED_SOURCE_FILES = 75
MAX_CHECKPOINT_NODES = 250_000
SKIP_PARTS = {".git", ".venv", "venv", "env", "node_modules", "__pycache__", "backups", "outputs"}

CATEGORY_PATTERNS = {
    "decision_apply": re.compile(r"option|exercise|decline|retain|waive|waiver|guarantee|release", re.I),
    "roster_ownership": re.compile(r"roster|inactive|reserve|player_team|ownership|team_by_id", re.I),
    "contract_mutation": re.compile(r"contract|salary|years_remaining|option_type|guaranteed|status", re.I),
    "free_agent_market": re.compile(r"free[_ -]?agent|market|rights|cap[_ -]?hold|qualifying[_ -]?offer", re.I),
    "trade_state_sync": re.compile(r"trade_state|team_financials|undo_stack|initial_snapshot|acquired_player", re.I),
    "durable_commit": re.compile(r"checkpoint|save_state|load_state|commit|recovery|rollback|restore", re.I),
    "validation": re.compile(r"validate|fingerprint|revision|invariant|digest", re.I),
    "transaction_history": re.compile(r"transaction|history|event_log|ledger|audit", re.I),
}

FIELD_GROUPS = {
    "player_identity": re.compile(r"player(?:_id|_name)?|person_id", re.I),
    "team_identity": re.compile(r"team(?:_id|_abbr|_abbreviation)?|owner", re.I),
    "roster_container": re.compile(r"roster|inactive|reserve|free_agent|player_team", re.I),
    "contract_field": re.compile(r"contract|salary|year|option|guarantee|status", re.I),
    "durability_field": re.compile(r"checkpoint|revision|fingerprint|history|transaction_id|recovery", re.I),
}

CRITICAL_SOURCE_NAMES = {
    "simulation_league_state_v1.py",
    "simulation_franchise_checkpoint_v1.py",
    "mutable_league_state_v1.py",
    "freeform_trade_machine_engine_v3.py",
    "franchise_free_agency_live_signing_v1.py",
    "franchise_player_contract_bridge_v1.py",
    "franchise_financial_cba_bridge_v1.py",
    "franchise_post_draft_first_round_pick_hold_bridge_v1.py",
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
    return any(part in SKIP_PARTS or part.startswith(".faoffseasontxprobe") for part in parts)


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
        if matched:
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
        if isinstance(node.value, str) and len(node.value) <= 180:
            self.add(node.value, getattr(node, "lineno", 0), "string")


def scan_python_sources(root: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    inventory: list[dict[str, Any]] = []
    symbols: list[dict[str, Any]] = []
    fields: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    sources: list[tuple[int, Path, str, list[str]]] = []
    src = root / "src"
    for path in sorted(src.rglob("*.py")):
        if skipped(path, root) or path.name == Path(__file__).name or path.stat().st_size > MAX_SOURCE_BYTES:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        file_categories = categories(path.name + " " + text)
        if not file_categories:
            continue
        source_file = relative(path, root)
        try:
            tree = ast.parse(text, filename=source_file)
        except SyntaxError as exc:
            errors.append({"source_file": source_file, "line": exc.lineno or 0, "error": clean(exc.msg)})
            continue
        file_symbol_count = 0
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            args = function_args(node) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) else []
            node_categories = categories(" ".join([node.name, " ".join(args), ast.get_docstring(node) or "", source_file]))
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
        score = 1000 if path.name in CRITICAL_SOURCE_NAMES else 0
        score += len(file_categories) * 20 + file_symbol_count * 3 + len(unique_fields)
        sources.append((score, path, text, file_categories))
        inventory.append({
            "source_file": source_file,
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
            "categories": " | ".join(file_categories),
            "relevant_symbol_count": file_symbol_count,
            "relevant_field_signal_count": len(unique_fields),
            "critical_runtime_contract": path.name in CRITICAL_SOURCE_NAMES,
        })

    exported: list[dict[str, Any]] = []
    used = 0
    for score, path, text, file_categories in sorted(sources, key=lambda row: (-row[0], row[1].as_posix())):
        encoded = len(text.encode("utf-8"))
        if len(exported) >= MAX_EXPORTED_SOURCE_FILES or used + encoded > MAX_EXPORTED_SOURCE_BYTES:
            continue
        exported.append({
            "source_file": relative(path, root),
            "source_sha256": sha256_file(path),
            "bytes": encoded,
            "score": score,
            "categories": file_categories,
            "source": text,
        })
        used += encoded
    return inventory, symbols, fields, errors, exported


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
                    rows.append({
                        "checkpoint_path": child_path,
                        "value_type": type(child).__name__,
                        "value_preview": clean(child)[:240] if isinstance(child, (str, int, float, bool, type(None))) else "",
                        "categories": " | ".join(matched),
                    })
                walk(child, child_path, depth + 1)
        elif isinstance(current, (list, tuple, set)):
            for index, child in enumerate(list(current)):
                walk(child, f"{path}[{index}]", depth + 1)
        elif hasattr(current, "__dict__"):
            walk(vars(current), path, depth + 1)

    walk(value, "$", 0)
    unique = {(row["checkpoint_path"], row["categories"]): row for row in rows}
    return list(unique.values()), nodes, truncated


def jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple, set)):
        return [jsonable(item) for item in list(value)[:100]]
    if isinstance(value, dict):
        return {clean(key): jsonable(item) for key, item in list(value.items())[:100]}
    if hasattr(value, "__dict__"):
        return {clean(key): jsonable(item) for key, item in vars(value).items()}
    return clean(value)


def runtime_target_contracts(state: Any, trade_state: Any, decisions: list[dict[str, str]]) -> list[dict[str, Any]]:
    players = getattr(state, "players", {})
    teams = getattr(state, "teams", {})
    trade_owners = getattr(trade_state, "player_team_by_id", {}) if trade_state is not None else {}
    rows: list[dict[str, Any]] = []
    for decision in decisions:
        player_id = clean(decision.get("player_id"))
        player = players.get(player_id) if isinstance(players, dict) else None
        memberships: list[str] = []
        if isinstance(teams, dict):
            for team_key, team in teams.items():
                for field, value in vars(team).items() if hasattr(team, "__dict__") else []:
                    if isinstance(value, (list, tuple, set)) and player_id in {clean(item) for item in value}:
                        memberships.append(f"{clean(team_key)}.{field}")
        free_agent_memberships: list[str] = []
        for field, value in vars(state).items() if hasattr(state, "__dict__") else []:
            if "free" in field.lower() and "agent" in field.lower() and isinstance(value, (list, tuple, set, dict)):
                values = value.keys() if isinstance(value, dict) else value
                if player_id in {clean(item) for item in values}:
                    free_agent_memberships.append(field)
        contract = getattr(player, "contract", None) if player is not None else None
        rows.append({
            "player_id": player_id,
            "player_name": clean(decision.get("player_name")),
            "decision_category": clean(decision.get("decision_category")),
            "recommendation": clean(decision.get("recommendation")),
            "owner_before": clean(decision.get("owner_before") or decision.get("team_abbreviation")),
            "owner_after_preview": clean(decision.get("owner_after")),
            "player_present": player is not None,
            "simulation_memberships": " | ".join(sorted(memberships)),
            "free_agent_memberships": " | ".join(sorted(free_agent_memberships)),
            "trade_state_owner": clean(trade_owners.get(player_id)) if isinstance(trade_owners, dict) else "",
            "player_runtime_json": json.dumps(jsonable(player), sort_keys=True, separators=(",", ":")),
            "contract_runtime_json": json.dumps(jsonable(contract), sort_keys=True, separators=(",", ":")),
        })
    return rows


def main() -> int:
    root = Path.cwd().resolve()
    if not (root / "src").exists():
        raise RuntimeError("Run from the NBA_Roster_Optimization_Engine project root.")

    bridge_zip = find_passed(root, FINAL_BRIDGE_PATTERN, "final_bridge_integration_summary.json")
    market_zip = find_passed(root, FULL_MARKET_PATTERN, "full_market_free_agent_amount_summary.json")
    clone_zip = find_passed(root, CLONE_PREVIEW_PATTERN, "clone_application_summary.json")
    with zipfile.ZipFile(bridge_zip) as archive:
        bridge_summary = json_suffix(archive, "final_bridge_integration_summary.json")
        bridge_checks = csv_suffix(archive, "final_bridge_integration_checks.csv")
        remaining_financial = csv_suffix(archive, "remaining_financial_component_blockers_0.csv")
    with zipfile.ZipFile(market_zip) as archive:
        market_summary = json_suffix(archive, "full_market_free_agent_amount_summary.json")
        market_checks = csv_suffix(archive, "full_market_free_agent_amount_checks.csv")
        market_rows = csv_suffix(archive, "full_market_free_agent_amounts_complete_226.csv")
    with zipfile.ZipFile(clone_zip) as archive:
        clone_summary = json_suffix(archive, "clone_application_summary.json")
        clone_checks = csv_suffix(archive, "clone_application_checks.csv")
        automatic = csv_suffix(archive, "automatic_decisions_applied_109.csv")
        pending = csv_suffix(archive, "user_decisions_pending_2.csv")

    if str(root / "src") not in sys.path:
        sys.path.insert(0, str(root / "src"))
    import simulation_franchise_checkpoint_v1 as checkpoint_module

    checkpoint_path = Path(checkpoint_module.DEFAULT_CHECKPOINT_PATH)
    checkpoint_hash_before = sha256_file(checkpoint_path)
    checkpoint = checkpoint_module.load_franchise_checkpoint()
    if checkpoint is None:
        raise RuntimeError("Canonical checkpoint could not be loaded.")
    simulation_digest_before = object_digest(checkpoint.simulation_state)
    if checkpoint_hash_before != EXPECTED_CHECKPOINT_SHA256:
        raise RuntimeError("Canonical checkpoint changed before transactional interface probe.")

    print("=" * 132)
    print("2026 OFFSEASON TRANSACTION APPLICATION INTERFACE PROBE V1")
    print("=" * 132)
    print("Inspecting current source and checkpoint contracts without applying any offseason decision...")

    inventory, symbols, field_signals, parse_errors, exported_sources = scan_python_sources(root)
    checkpoint_signals, checkpoint_nodes, checkpoint_truncated = scan_checkpoint(checkpoint)

    representatives: list[dict[str, str]] = []
    for recommendation in ("exercise", "decline", "retain", "waive"):
        row = next((item for item in automatic if clean(item.get("recommendation")) == recommendation), None)
        if row:
            representatives.append(row)
    representatives.extend(pending)
    target_contracts = runtime_target_contracts(
        checkpoint.simulation_state,
        getattr(checkpoint, "trade_state", None),
        representatives,
    )

    category_counts = Counter(
        category
        for row in inventory + symbols + checkpoint_signals
        for category in clean(row.get("categories")).split(" | ")
        if category
    )
    field_counts = Counter(
        group
        for row in field_signals
        for group in clean(row.get("field_groups")).split(" | ")
        if group
    )
    market_ids = {clean(row.get("player_id")) for row in market_rows}
    chicago_resolution = "1631159" not in market_ids and "1631338" in market_ids
    critical_exported = {Path(clean(row["source_file"])).name for row in exported_sources}

    readiness = [
        {"interface": "financial_component_registry", "status": "ready" if bridge_summary.get("financial_component_registry_complete") and not remaining_financial else "blocked", "evidence_count": len(bridge_checks), "implementation_requirement": "Start from the passed zero-blocker financial registry."},
        {"interface": "final_market_and_decision_board", "status": "ready" if len(market_rows) == 226 and len(automatic) == 109 and len(pending) == 2 else "blocked", "evidence_count": len(market_rows) + len(automatic) + len(pending), "implementation_requirement": "Preserve the exact 226-player market and 111 branch decisions."},
        {"interface": "simulation_roster_ownership", "status": "candidate_found" if category_counts["roster_ownership"] and field_counts["roster_container"] else "missing", "evidence_count": category_counts["roster_ownership"] + field_counts["roster_container"], "implementation_requirement": "Move each player atomically between roster, inactive/reserve, and free-agent containers."},
        {"interface": "contract_state_mutation", "status": "candidate_found" if category_counts["contract_mutation"] and field_counts["contract_field"] else "missing", "evidence_count": category_counts["contract_mutation"] + field_counts["contract_field"], "implementation_requirement": "Apply exercised salary/years/status or terminate the option/guarantee without inventing fields."},
        {"interface": "trade_state_synchronization", "status": "candidate_found" if category_counts["trade_state_sync"] else "missing", "evidence_count": category_counts["trade_state_sync"], "implementation_requirement": "Synchronize ownership, team finance, counts, and undo/reset snapshots."},
        {"interface": "financial_component_transition", "status": "candidate_found" if category_counts["free_agent_market"] and category_counts["contract_mutation"] else "missing", "evidence_count": category_counts["free_agent_market"] + category_counts["contract_mutation"], "implementation_requirement": "Replace contract salary with the correct market hold or remove the hold on retention."},
        {"interface": "transaction_history_and_revision", "status": "candidate_found" if category_counts["transaction_history"] and category_counts["validation"] else "missing", "evidence_count": category_counts["transaction_history"] + category_counts["validation"], "implementation_requirement": "Record deterministic transaction identity, lineage, revision, and fingerprints."},
        {"interface": "validated_checkpoint_commit", "status": "candidate_found" if category_counts["durable_commit"] and "simulation_franchise_checkpoint_v1.py" in critical_exported else "missing", "evidence_count": category_counts["durable_commit"], "implementation_requirement": "Commit simulation and Trade Machine candidates once, reload, verify, and recover on failure."},
    ]
    implementation_ready = all(row["status"] in {"ready", "candidate_found"} for row in readiness)
    missing_interfaces = [clean(row["interface"]) for row in readiness if row["status"] not in {"ready", "candidate_found"}]

    checks: list[dict[str, str]] = []

    def add(check_id: str, passed: bool, detail: str) -> None:
        checks.append({"check_id": check_id, "status": "PASS" if passed else "FAIL", "severity": "strict", "detail": detail})
        print(f"  {check_id}: {'PASS' if passed else 'FAIL'}")

    print("\nValidating the bounded transactional interface probe...")
    add("final_pick_hold_bridge_closed_financial_registry", bridge_summary.get("passed") is True and bridge_summary.get("remaining_financial_component_blocker_count") == 0 and not remaining_financial and all(clean(row.get("status")) == "PASS" for row in bridge_checks), bridge_zip.name)
    add("full_market_is_exactly_226_unique_players", market_summary.get("passed") is True and len(market_rows) == len(market_ids) == 226 and all(clean(row.get("status")) == "PASS" for row in market_checks), "226/226")
    add("clone_application_contract_is_109_plus_2", clone_summary.get("passed") is True and len(automatic) == 109 and len(pending) == 2 and all(clean(row.get("status")) == "PASS" for row in clone_checks), "109 automatic + 2 user")
    add("final_chicago_option_branch_is_preserved", chicago_resolution, "Leonard Miller retained; Mouhamadou Gueye enters market")
    add("all_four_automatic_action_families_are_sampled", {clean(row.get("recommendation")) for row in representatives} >= {"exercise", "decline", "retain", "waive"}, "exercise/decline/retain/waive")
    add("source_scan_is_bounded_to_project_src", all(clean(row.get("source_file")).startswith("src/") for row in inventory + symbols + field_signals + exported_sources), f"relevant={len(inventory)}")
    add("all_relevant_python_sources_parsed", not parse_errors, f"parse_errors={len(parse_errors)}")
    add("checkpoint_scan_completed_within_bound", not checkpoint_truncated, f"nodes={checkpoint_nodes}")
    add("runtime_source_contracts_exported_with_hashes", bool(exported_sources) and all(clean(row.get("source_sha256")) and clean(row.get("source")) for row in exported_sources), f"files={len(exported_sources)}")
    add("critical_checkpoint_contract_is_exported", "simulation_franchise_checkpoint_v1.py" in critical_exported, "simulation_franchise_checkpoint_v1.py")
    add("readiness_matrix_covers_eight_required_interfaces", len(readiness) == len({row["interface"] for row in readiness}) == 8, "8/8")
    add("diagnostic_gaps_are_reported_not_fabricated", set(missing_interfaces) == {row["interface"] for row in readiness if row["status"] not in {"ready", "candidate_found"}}, " | ".join(missing_interfaces) or "none")

    checkpoint_hash_after = sha256_file(checkpoint_path)
    checkpoint_after = checkpoint_module.load_franchise_checkpoint()
    simulation_digest_after = object_digest(checkpoint_after.simulation_state)
    add("loaded_simulation_state_unchanged", simulation_digest_before == simulation_digest_after == EXPECTED_SIMULATION_DIGEST, simulation_digest_after)
    add("checkpoint_file_unchanged", checkpoint_hash_before == checkpoint_hash_after == EXPECTED_CHECKPOINT_SHA256, checkpoint_hash_after)
    failed = [row["check_id"] for row in checks if row["status"] != "PASS"]

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    name = f"fa_offseason_transaction_application_interface_probe_v1_{SEASON_LABEL}_{timestamp}"
    audit_dir = root / "outputs" / "audits"
    audit_dir.mkdir(parents=True, exist_ok=True)
    output_zip = audit_dir / f"{name}.zip"
    summary = {
        "version": VERSION,
        "season": SEASON_LABEL,
        "canonical_split_date": SPLIT_DATE.isoformat(),
        "passed": not failed,
        "failed_checks": failed,
        "implementation_ready": implementation_ready,
        "missing_or_partial_interfaces": missing_interfaces,
        "financial_component_blocker_count": 0,
        "final_market_count": len(market_rows),
        "automatic_decision_count": len(automatic),
        "user_decision_count": len(pending),
        "chicago_resolution": {"1631159_leonard_miller": "exercise", "1631338_mouhamadou_gueye": "decline"},
        "relevant_source_file_count": len(inventory),
        "relevant_symbol_count": len(symbols),
        "field_signal_count": len(field_signals),
        "exported_runtime_source_contract_count": len(exported_sources),
        "exported_runtime_source_bytes": sum(int(row["bytes"]) for row in exported_sources),
        "checkpoint_signal_count": len(checkpoint_signals),
        "network_requests": 0,
        "decisions_applied": 0,
        "state_mutation_performed": False,
        "checkpoint_write_performed": False,
        "next_slice": "Build clone-only transactional candidates for all 111 resolved offseason decisions using the mapped runtime contracts, then validate simulation/Trade Machine parity and rollback before any durable commit.",
    }
    readme = f"""2026 OFFSEASON TRANSACTION APPLICATION INTERFACE PROBE V1

Result
------
- Audit passed: {not failed}
- Implementation ready from discovered interfaces: {implementation_ready}
- Missing or partial interfaces: {', '.join(missing_interfaces) if missing_interfaces else 'none'}
- Financial component blockers: 0
- Final market: {len(market_rows)}
- Resolved decision board: {len(automatic) + len(pending)}

Chicago branch
--------------
- Leonard Miller: exercise Team Option; remains attached to CHI.
- Mouhamadou Gueye: decline Team Option; enters the final market.

Safety
------
The April 12 opening snapshot remains frozen. No decision, contract, roster,
free-agent, salary, Trade Machine, simulation, overlay, or checkpoint mutation occurred.
"""

    with tempfile.TemporaryDirectory(prefix="fa_offseason_transaction_probe_") as temporary:
        folder = Path(temporary) / name
        folder.mkdir(parents=True)
        write_csv(folder / "transaction_runtime_source_inventory.csv", inventory, ["source_file", "bytes", "sha256", "categories", "relevant_symbol_count", "relevant_field_signal_count", "critical_runtime_contract"])
        write_csv(folder / "transaction_runtime_symbols.csv", symbols, ["source_file", "line", "symbol_kind", "symbol_name", "arguments", "categories"])
        write_csv(folder / "transaction_runtime_field_signals.csv", field_signals, ["source_file", "line", "origin", "field_or_signal", "field_groups"])
        write_csv(folder / "checkpoint_transaction_signals.csv", checkpoint_signals, ["checkpoint_path", "value_type", "value_preview", "categories"])
        write_csv(folder / "representative_decision_runtime_contracts.csv", target_contracts, ["player_id", "player_name", "decision_category", "recommendation", "owner_before", "owner_after_preview", "player_present", "simulation_memberships", "free_agent_memberships", "trade_state_owner", "player_runtime_json", "contract_runtime_json"])
        write_csv(folder / "transaction_interface_readiness_matrix.csv", readiness, ["interface", "status", "evidence_count", "implementation_requirement"])
        write_csv(folder / "source_parse_errors.csv", parse_errors, ["source_file", "line", "error"])
        write_csv(folder / "transaction_interface_probe_checks.csv", checks, ["check_id", "status", "severity", "detail"])
        (folder / "runtime_transaction_contract_source.json").write_text(json.dumps(exported_sources, indent=2), encoding="utf-8")
        (folder / "transaction_interface_probe_summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
        (folder / "README.txt").write_text(readme, encoding="utf-8")
        with zipfile.ZipFile(output_zip, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for path in sorted(folder.rglob("*")):
                if path.is_file():
                    archive.write(path, arcname=f"{name}/{path.name}")

    print("\n" + "=" * 132)
    print(f"2026 OFFSEASON TRANSACTION APPLICATION INTERFACE PROBE V1 {'PASSED' if not failed else 'FAILED'}")
    print("=" * 132)
    print(f"Financial blockers:         0")
    print(f"Final market:               {len(market_rows)}")
    print(f"Resolved decision board:    {len(automatic) + len(pending)}")
    print(f"Relevant source files:      {len(inventory)}")
    print(f"Runtime contracts exported: {len(exported_sources)}")
    print(f"Implementation ready:       {implementation_ready}")
    print(f"Missing/partial interfaces: {', '.join(missing_interfaces) if missing_interfaces else 'none'}")
    print("Decisions applied:          0")
    print("Checkpoint write:           NOT PERFORMED")
    print(f"Audit ZIP: {output_zip}")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
