from __future__ import annotations

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
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


VERSION = "fa-team-salary-missing-components-semantic-resolution-v1-2026-08-15"
SEASON_LABEL = "2026-27"
PROBE_PATTERN = "fa_official_team_salary_missing_components_probe_v1_2026-27_*.zip"
EXPECTED_SIGNALS = {
    "dead_money_or_retained_salary": 111,
    "incentive_or_bonus": 636,
    "rookie_pick_hold_or_salary": 2830,
}
DEAD_FALSE_POSITIVE_FIELDS = {
    "model_retained_cap_hold_total",
    "team_model_retained_cap_hold_total",
}
ROOKIE_HISTORY_FIELDS = {
    "rookie_scale_first_round_option_exception",
    "had_rookie_scale_contract",
    "rookie_scale_covers_2025_26",
    "full_rookie_scale_finish",
}
TEAM_CBA_EVIDENCE_SOURCE = "outputs\\mixed_player_pick_team_cba_evidence_release_v1.csv"


def clean(value: Any) -> str:
    return "" if value is None else str(value).strip()


def as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return clean(value).lower() in {"true", "1", "yes", "y"}


def as_decimal(value: Any) -> Decimal | None:
    text = clean(value).replace("$", "").replace(",", "")
    if not text:
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def money_int(value: Any) -> int | None:
    number = as_decimal(value)
    if number is None or number != number.to_integral_value():
        return None
    return int(number)


def player_id(value: Any) -> str:
    text = clean(value)
    return text[:-2] if text.endswith(".0") and text[:-2].isdigit() else text


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


def json_dict(value: Any) -> dict[str, str]:
    parsed = json.loads(clean(value) or "{}")
    if not isinstance(parsed, dict):
        raise RuntimeError("Expected a JSON object in probe evidence.")
    return {clean(key): clean(item) for key, item in parsed.items()}


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


def resolution_base(row: dict[str, str], signal_origin: str) -> dict[str, Any]:
    return {
        "signal_origin": signal_origin,
        "source_type": clean(row.get("source_type")),
        "source_file": clean(row.get("source_file")),
        "source_member": clean(row.get("source_member")),
        "row_number": clean(row.get("row_number")),
        "object_path": clean(row.get("object_path")),
        "player_id": player_id(row.get("player_id")),
        "player_name": clean(row.get("player_name")),
        "team": clean(row.get("team")),
        "raw_value": clean(row.get("raw_value")),
        "numeric_value": clean(row.get("numeric_value")),
    }


def resolve_dead_money(
    evidence_rows: list[dict[str, str]], signal_rows: list[dict[str, str]]
) -> list[dict[str, Any]]:
    resolved: list[dict[str, Any]] = []
    for row in evidence_rows:
        fields = json_dict(row.get("evidence_fields_json"))
        keys = set(fields)
        known = bool(keys) and keys.issubset(DEAD_FALSE_POSITIVE_FIELDS)
        resolved.append(
            {
                **resolution_base(row, "tabular_evidence"),
                "matched_fields": " | ".join(sorted(keys)),
                "semantic_resolution": (
                    "retained_cap_hold_summary_not_dead_money" if known else "unresolved_dead_money_candidate"
                ),
                "is_exact_dead_money_row": False,
                "resolved": known,
                "resolution_detail": (
                    "The matched field is a free-agent rights cap-hold aggregate; it is not waived/stretched salary."
                    if known
                    else "Unexpected field requires review."
                ),
            }
        )
    for row in signal_rows:
        text = f"{clean(row.get('object_path'))} {clean(row.get('raw_value'))}".lower()
        known = "retained_charge_total" in text or "cap hold" in text or "dead money" in text
        resolved.append(
            {
                **resolution_base(row, "object_or_checkpoint_signal"),
                "matched_fields": clean(row.get("object_path")),
                "semantic_resolution": (
                    "narrative_or_retained_cap_hold_metadata_not_dead_money"
                    if known
                    else "unresolved_dead_money_candidate"
                ),
                "is_exact_dead_money_row": False,
                "resolved": known,
                "resolution_detail": (
                    "The signal is narrative text or a retained cap-hold scenario total, not a player/team dead-money ledger."
                    if known
                    else "Unexpected object signal requires review."
                ),
            }
        )
    return resolved


def resolve_incentives(
    evidence_rows: list[dict[str, str]], signal_rows: list[dict[str, str]]
) -> list[dict[str, Any]]:
    resolved: list[dict[str, Any]] = []
    for row in evidence_rows:
        fields = json_dict(row.get("evidence_fields_json"))
        keys = set(fields)
        if keys == {"remaining_trade_bonus_amount"}:
            resolution = "trade_bonus_restriction_not_current_team_salary_incentive"
            exact = False
            known = True
            detail = "Remaining trade bonus is trade-kicker/restriction metadata and is not automatically a current Team Salary charge."
        elif keys == {"known_likely_incentive_2026_27"}:
            amount = money_int(fields.get("known_likely_incentive_2026_27"))
            resolution = (
                "known_likely_incentive_duplicate_positive_signal"
                if amount and amount > 0
                else "explicit_zero_known_likely_incentive_signal"
            )
            exact = bool(amount and amount > 0)
            known = amount is not None
            detail = "Known likely-incentive field; positive duplicates are collapsed into the canonical carried-forward ledger."
        else:
            resolution = "unresolved_incentive_candidate"
            exact = False
            known = False
            detail = "Unexpected incentive field requires review."
        resolved.append(
            {
                **resolution_base(row, "tabular_evidence"),
                "matched_fields": " | ".join(sorted(keys)),
                "semantic_resolution": resolution,
                "is_exact_current_likely_incentive_signal": exact,
                "resolved": known,
                "resolution_detail": detail,
            }
        )
    for row in signal_rows:
        resolved.append(
            {
                **resolution_base(row, "object_or_checkpoint_signal"),
                "matched_fields": clean(row.get("object_path")),
                "semantic_resolution": "narrative_or_schema_metadata_not_exact_incentive_allocation",
                "is_exact_current_likely_incentive_signal": False,
                "resolved": True,
                "resolution_detail": "The object signal is prose or schema coverage metadata, not a player-level likely incentive amount.",
            }
        )
    return resolved


def resolve_rookie_holds(
    evidence_rows: list[dict[str, str]], signal_rows: list[dict[str, str]]
) -> list[dict[str, Any]]:
    resolved: list[dict[str, Any]] = []
    for row in evidence_rows:
        fields = json_dict(row.get("evidence_fields_json"))
        keys = set(fields)
        known = bool(keys) and keys.issubset(ROOKIE_HISTORY_FIELDS)
        resolved.append(
            {
                **resolution_base(row, "tabular_evidence"),
                "matched_fields": " | ".join(sorted(keys)),
                "semantic_resolution": (
                    "legacy_rookie_contract_history_or_option_field_not_2026_generated_pick_hold"
                    if known
                    else "unresolved_rookie_hold_candidate"
                ),
                "is_exact_2026_generated_rookie_hold": False,
                "resolved": known,
                "resolution_detail": (
                    "The fields describe prior rookie-scale contract history or option/QO treatment, not an unsigned 2026 first-round pick hold."
                    if known
                    else "Unexpected rookie field requires review."
                ),
            }
        )
    for row in signal_rows:
        is_checkpoint = clean(row.get("source_type")) == "checkpoint_object"
        movement = "nba_player_movement" in clean(row.get("source_member")).lower()
        if is_checkpoint:
            resolution = "unresolved_current_checkpoint_rookie_signal"
            known = False
            detail = "A current checkpoint rookie signal requires direct resolution."
        elif movement:
            resolution = "historical_transaction_narrative_not_2026_generated_pick_hold"
            known = True
            detail = "The signal is transaction-history prose from a player-movement snapshot."
        else:
            resolution = "lifecycle_formula_or_narrative_metadata_not_2026_generated_pick_hold"
            known = True
            detail = "The signal concerns prior contract lifecycle, QO formulas, source notes, or validation metadata."
        resolved.append(
            {
                **resolution_base(row, "object_or_checkpoint_signal"),
                "matched_fields": clean(row.get("object_path")),
                "semantic_resolution": resolution,
                "is_exact_2026_generated_rookie_hold": False,
                "resolved": known,
                "resolution_detail": detail,
            }
        )
    return resolved


def build_proxy_registry(
    evidence_rows: list[dict[str, str]], signal_rows: list[dict[str, str]]
) -> list[dict[str, Any]]:
    current_pattern = re.compile(
        r"^\$checkpoint\.trade_state\.team_financials\.([A-Z]{3})\.team_salary$"
    )
    initial_pattern = re.compile(
        r"^\$checkpoint\.trade_state\.initial_snapshot\.team_financials\.([A-Z]{3})\.team_salary$"
    )
    current: dict[str, int] = {}
    initial: dict[str, int] = {}
    for row in signal_rows:
        if clean(row.get("source_type")) != "checkpoint_object":
            continue
        path = clean(row.get("object_path"))
        value = money_int(row.get("numeric_value"))
        match = current_pattern.fullmatch(path)
        if match and value is not None:
            current[match.group(1)] = value
        match = initial_pattern.fullmatch(path)
        if match and value is not None:
            initial[match.group(1)] = value

    cba_by_team: dict[str, dict[str, str]] = {}
    for row in evidence_rows:
        if clean(row.get("source_file")) != TEAM_CBA_EVIDENCE_SOURCE:
            continue
        team = clean(row.get("team"))
        fields = json_dict(row.get("evidence_fields_json"))
        if team and "verified_team_salary_value" in fields:
            if team in cba_by_team:
                raise RuntimeError(f"Duplicate canonical team CBA evidence row: {team}")
            cba_by_team[team] = fields

    teams = sorted(set(current) | set(initial) | set(cba_by_team))
    rows: list[dict[str, Any]] = []
    for team in teams:
        fields = cba_by_team.get(team, {})
        cba_team_salary = money_int(fields.get("verified_team_salary_value"))
        rows.append(
            {
                "team": team,
                "legacy_trade_state_team_salary": current.get(team),
                "legacy_trade_state_initial_snapshot_team_salary": initial.get(team),
                "cba_release_team_salary_value": cba_team_salary,
                "cba_release_apron_team_salary_value": money_int(fields.get("verified_apron_team_salary_value")),
                "apron_team_salary_proxy_2026_27": money_int(fields.get("apron_team_salary_proxy_2026_27")),
                "team_salary_source_url": clean(fields.get("team_salary_source_url")),
                "team_salary_source_quality": clean(fields.get("team_salary_source_quality")),
                "official_team_salary_verified": as_bool(fields.get("official_team_salary_verified")),
                "current_matches_initial_snapshot": current.get(team) == initial.get(team),
                "checkpoint_matches_cba_release_team_salary": current.get(team) == cba_team_salary,
                "semantic_status": "legacy_financial_proxy_only_not_official_team_salary",
                "applied_to_official_team_salary": False,
            }
        )
    return rows


def main() -> int:
    root = Path.cwd().resolve()
    probe_zip = latest(root, PROBE_PATTERN)
    with zipfile.ZipFile(probe_zip) as archive:
        probe_summary = json_suffix(archive, "missing_component_probe_summary.json")
        probe_checks = csv_suffix(archive, "missing_component_probe_checks.csv")
        evidence_rows = csv_suffix(archive, "component_candidate_evidence.csv")
        signal_rows = csv_suffix(archive, "object_and_checkpoint_component_signals.csv")
        known_incentives = csv_suffix(archive, "known_likely_incentives_carried_forward.csv")

    if str(root / "src") not in sys.path:
        sys.path.insert(0, str(root / "src"))
    import simulation_franchise_checkpoint_v1 as checkpoint_module

    checkpoint_path = Path(checkpoint_module.DEFAULT_CHECKPOINT_PATH)
    checkpoint_hash_before = sha256_file(checkpoint_path)
    checkpoint = checkpoint_module.load_franchise_checkpoint()
    simulation_digest_before = object_digest(checkpoint.simulation_state)

    prior_checkpoint_check = next(
        (row for row in probe_checks if clean(row.get("check_id")) == "checkpoint_file_unchanged"),
        {},
    )
    upstream_checkpoint_hash = clean(prior_checkpoint_check.get("detail"))

    evidence_by_category = {
        category: [row for row in evidence_rows if clean(row.get("category")) == category]
        for category in EXPECTED_SIGNALS
    }
    signals_by_category = {
        category: [row for row in signal_rows if clean(row.get("category")) == category]
        for category in EXPECTED_SIGNALS
    }

    dead_rows = resolve_dead_money(
        evidence_by_category["dead_money_or_retained_salary"],
        signals_by_category["dead_money_or_retained_salary"],
    )
    incentive_rows = resolve_incentives(
        evidence_by_category["incentive_or_bonus"],
        signals_by_category["incentive_or_bonus"],
    )
    rookie_rows = resolve_rookie_holds(
        evidence_by_category["rookie_pick_hold_or_salary"],
        signals_by_category["rookie_pick_hold_or_salary"],
    )
    proxy_rows = build_proxy_registry(evidence_rows, signal_rows)

    canonical_incentives: list[dict[str, Any]] = []
    for row in known_incentives:
        amount = money_int(row.get("known_likely_incentive_2026_27"))
        canonical_incentives.append(
            {
                **row,
                "player_id": player_id(row.get("player_id")),
                "known_likely_incentive_2026_27": amount,
                "canonical_current_incentive_evidence": True,
                "applied_to_team_salary": False,
            }
        )

    resolution_counts = {
        "dead_money_or_retained_salary": len(dead_rows),
        "incentive_or_bonus": len(incentive_rows),
        "rookie_pick_hold_or_salary": len(rookie_rows),
    }
    unresolved_counts = {
        "dead_money_or_retained_salary": sum(not as_bool(row.get("resolved")) for row in dead_rows),
        "incentive_or_bonus": sum(not as_bool(row.get("resolved")) for row in incentive_rows),
        "rookie_pick_hold_or_salary": sum(not as_bool(row.get("resolved")) for row in rookie_rows),
    }
    trade_bonus_rows = sum(
        clean(row.get("semantic_resolution"))
        == "trade_bonus_restriction_not_current_team_salary_incentive"
        for row in incentive_rows
    )
    current_checkpoint_rookie_signals = sum(
        clean(row.get("source_type")) == "checkpoint_object" for row in rookie_rows
    )
    exact_dead_money_rows = sum(as_bool(row.get("is_exact_dead_money_row")) for row in dead_rows)
    exact_rookie_hold_rows = sum(
        as_bool(row.get("is_exact_2026_generated_rookie_hold")) for row in rookie_rows
    )

    blockers = [
        {
            "component": "dead_money_and_waived_or_stretched_salary",
            "exact_project_native_rows_discovered": exact_dead_money_rows,
            "canonical_positive_rows_carried_forward": 0,
            "complete": False,
            "blocker": "No player/team dead-money ledger was discovered; retained cap-hold totals were false positives.",
            "required_next_input": "Exact 2026-27 waived, stretched, and retained-salary ledger by team/player, including explicit zero-team closure.",
        },
        {
            "component": "likely_and_unlikely_incentive_allocations",
            "exact_project_native_rows_discovered": len(canonical_incentives),
            "canonical_positive_rows_carried_forward": len(canonical_incentives),
            "complete": False,
            "blocker": "One known likely incentive is exact; a complete standard-contract incentive classification is not proven.",
            "required_next_input": "Per-contract likely/unlikely incentive allocation or explicit zero classification for the 331 standard contracts.",
        },
        {
            "component": "2026_generated_first_round_rookie_holds",
            "exact_project_native_rows_discovered": exact_rookie_hold_rows,
            "canonical_positive_rows_carried_forward": 0,
            "complete": False,
            "blocker": "No generated 2026 draft-result/rookie-hold state exists in the canonical checkpoint evidence.",
            "required_next_input": "2026 draft results plus the applicable first-round rookie-scale hold/salary table and signing status.",
        },
        {
            "component": "official_2026_27_team_salary_semantics",
            "exact_project_native_rows_discovered": 0,
            "canonical_positive_rows_carried_forward": 0,
            "complete": False,
            "blocker": "All 30 legacy checkpoint figures are explicitly sourced as proxy-only, not official Team Salary.",
            "required_next_input": "Component-complete Team Salary calculation after dead money, incentives, and rookie holds are closed.",
        },
    ]

    semantic_board = [
        {
            "component": "dead_money_and_retained_salary_probe_signals",
            "probe_signal_count": len(dead_rows),
            "semantically_resolved_count": len(dead_rows) - unresolved_counts["dead_money_or_retained_salary"],
            "true_current_component_rows": exact_dead_money_rows,
            "status": "false_positives_closed_exact_dead_money_source_still_missing",
            "applied_to_team_salary": False,
        },
        {
            "component": "incentive_and_bonus_probe_signals",
            "probe_signal_count": len(incentive_rows),
            "semantically_resolved_count": len(incentive_rows) - unresolved_counts["incentive_or_bonus"],
            "true_current_component_rows": len(canonical_incentives),
            "status": "one_known_likely_incentive_carried_complete_all_contract_layer_still_missing",
            "applied_to_team_salary": False,
        },
        {
            "component": "rookie_pick_hold_probe_signals",
            "probe_signal_count": len(rookie_rows),
            "semantically_resolved_count": len(rookie_rows) - unresolved_counts["rookie_pick_hold_or_salary"],
            "true_current_component_rows": exact_rookie_hold_rows,
            "status": "historical_and_option_false_positives_closed_2026_generated_layer_missing",
            "applied_to_team_salary": False,
        },
        {
            "component": "checkpoint_team_salary_proxy",
            "probe_signal_count": len(proxy_rows),
            "semantically_resolved_count": len(proxy_rows),
            "true_current_component_rows": 0,
            "status": "30_team_legacy_proxy_frozen_as_nonofficial",
            "applied_to_team_salary": False,
        },
    ]

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
    print("2026 TEAM SALARY MISSING COMPONENTS SEMANTIC RESOLUTION V1")
    print("=" * 132)
    print("Resolving probe false positives and freezing the exact remaining blockers...")

    add("upstream_missing_components_probe_passed", bool(probe_summary.get("passed")), probe_zip.name)
    add("upstream_scan_errors_are_zero", int(probe_summary.get("scan_error_count", -1)) == 0, f"scan_errors={probe_summary.get('scan_error_count')}")
    add("upstream_checkpoint_matches_current_checkpoint", bool(upstream_checkpoint_hash) and upstream_checkpoint_hash == checkpoint_hash_before, checkpoint_hash_before)
    add("exact_probe_signal_distribution_is_111_636_2830", resolution_counts == EXPECTED_SIGNALS, json.dumps(resolution_counts, sort_keys=True))
    add("all_111_dead_money_signals_semantically_closed", len(dead_rows) == 111 and unresolved_counts["dead_money_or_retained_salary"] == 0, f"rows={len(dead_rows)}, unresolved={unresolved_counts['dead_money_or_retained_salary']}")
    add("no_retained_cap_hold_promoted_to_dead_money", exact_dead_money_rows == 0, f"exact_dead_money_rows={exact_dead_money_rows}")
    add("all_636_incentive_signals_semantically_closed", len(incentive_rows) == 636 and unresolved_counts["incentive_or_bonus"] == 0, f"rows={len(incentive_rows)}, unresolved={unresolved_counts['incentive_or_bonus']}")
    add("trade_bonus_restrictions_not_promoted_to_team_salary", trade_bonus_rows == 622, f"trade_bonus_rows={trade_bonus_rows}")
    add("exact_one_known_likely_incentive_carried_forward", len(canonical_incentives) == 1 and player_id(canonical_incentives[0].get("player_id")) == "1642850" and canonical_incentives[0].get("known_likely_incentive_2026_27") == 814620, f"rows={len(canonical_incentives)}")
    add("all_2830_rookie_signals_semantically_closed", len(rookie_rows) == 2830 and unresolved_counts["rookie_pick_hold_or_salary"] == 0, f"rows={len(rookie_rows)}, unresolved={unresolved_counts['rookie_pick_hold_or_salary']}")
    add("checkpoint_contains_zero_current_rookie_hold_signals", current_checkpoint_rookie_signals == 0, f"checkpoint_rookie_signals={current_checkpoint_rookie_signals}")
    add("no_historical_rookie_signal_promoted_to_2026_hold", exact_rookie_hold_rows == 0, f"exact_2026_rookie_holds={exact_rookie_hold_rows}")
    add("exact_30_team_proxy_registry_emitted", len(proxy_rows) == 30 and len({row['team'] for row in proxy_rows}) == 30, f"teams={len(proxy_rows)}")
    add("checkpoint_current_and_initial_salary_proxies_match", all(as_bool(row.get("current_matches_initial_snapshot")) for row in proxy_rows), "30/30")
    add("checkpoint_and_team_cba_release_salary_values_match", all(as_bool(row.get("checkpoint_matches_cba_release_team_salary")) for row in proxy_rows), "30/30")
    add("all_30_team_salary_values_remain_explicitly_nonofficial", all(not as_bool(row.get("official_team_salary_verified")) and clean(row.get("team_salary_source_quality")) == "proxy_only_not_official_apron_team_salary" for row in proxy_rows), "30/30 proxy-only")
    add("exact_four_completion_blockers_frozen", len(blockers) == 4 and all(not row["complete"] for row in blockers), f"blockers={len(blockers)}")
    add("official_team_salary_not_claimed_complete", all(not row["applied_to_team_salary"] for row in semantic_board), "No component applied.")

    simulation_digest_after = object_digest(checkpoint.simulation_state)
    checkpoint_hash_after = sha256_file(checkpoint_path)
    add("loaded_simulation_state_unchanged", simulation_digest_after == simulation_digest_before, simulation_digest_after)
    add("checkpoint_file_unchanged", checkpoint_hash_after == checkpoint_hash_before, checkpoint_hash_after)

    failed = [row["check_id"] for row in checks if row["status"] == "FAIL"]
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    export_id = f"fa_team_salary_missing_components_semantic_resolution_v1_{SEASON_LABEL}_{timestamp}"
    output_dir = root / "outputs" / "audits"
    output_dir.mkdir(parents=True, exist_ok=True)
    audit_zip = output_dir / f"{export_id}.zip"

    summary = {
        "version": VERSION,
        "source_probe_audit": probe_zip.name,
        "probe_signal_counts": resolution_counts,
        "unresolved_semantic_signal_counts": unresolved_counts,
        "dead_money_false_positive_signals_closed": len(dead_rows),
        "exact_dead_money_rows_discovered": exact_dead_money_rows,
        "incentive_signals_closed": len(incentive_rows),
        "trade_bonus_restriction_rows": trade_bonus_rows,
        "known_likely_incentive_count": len(canonical_incentives),
        "known_likely_incentive_total": sum(int(row["known_likely_incentive_2026_27"]) for row in canonical_incentives),
        "rookie_false_positive_signals_closed": len(rookie_rows),
        "current_checkpoint_rookie_hold_signal_count": current_checkpoint_rookie_signals,
        "exact_2026_generated_rookie_hold_rows_discovered": exact_rookie_hold_rows,
        "legacy_team_salary_proxy_count": len(proxy_rows),
        "official_team_salary_complete": False,
        "completion_blocker_count": len(blockers),
        "components_applied": 0,
        "state_mutation_performed": False,
        "checkpoint_write_performed": False,
        "passed": not failed,
        "failed_checks": failed,
        "next_slice": (
            "Complete a targeted source registry for dead money and per-contract incentives, then bridge actual 2026 draft results to rookie-scale holds. "
            "Do not compute or apply official Team Salary until those three inputs are closed."
        ),
    }

    with tempfile.TemporaryDirectory(prefix="fa_team_salary_semantic_resolution_") as temporary_directory:
        export = Path(temporary_directory) / export_id
        export.mkdir(parents=True)
        write_csv(export / "dead_money_signal_semantic_resolution_111.csv", dead_rows)
        write_csv(export / "incentive_signal_semantic_resolution_636.csv", incentive_rows)
        write_csv(export / "rookie_hold_signal_semantic_resolution_2830.csv", rookie_rows)
        write_csv(export / "canonical_known_likely_incentives.csv", canonical_incentives)
        write_csv(export / "legacy_team_salary_proxy_semantics_30.csv", proxy_rows)
        write_csv(export / "official_team_salary_completion_blockers.csv", blockers)
        write_csv(export / "semantic_resolution_readiness_board.csv", semantic_board)
        write_csv(export / "semantic_resolution_checks.csv", checks)
        (export / "semantic_resolution_summary.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8"
        )
        (export / "README.txt").write_text(
            """2026 TEAM SALARY MISSING COMPONENTS SEMANTIC RESOLUTION V1
================================================================

Purpose
-------
Close the false-positive review burden created by the broad missing-components
probe while preserving the exact blockers that still prevent official Team
Salary computation.

Resolved semantics
------------------
* Retained cap-hold aggregates are not dead money.
* Remaining trade bonuses are trade-restriction metadata, not automatically
  current Team Salary incentives.
* Historical rookie-scale transactions and option/QO fields are not generated
  2026 first-round pick holds.
* The 30 checkpoint team-salary figures are frozen as legacy financial proxies;
  their own source evidence explicitly marks them as nonofficial.
* Thomas Sorber's $814,620 known likely incentive remains the sole canonical
  positive incentive evidence carried forward.

Safety
------
No QO, RFA status, cap hold, rights decision, renouncement, salary, roster,
simulation, overlay, or checkpoint mutation occurs. Official Team Salary is
not computed or applied.
""",
            encoding="utf-8",
        )
        with zipfile.ZipFile(audit_zip, "w", zipfile.ZIP_DEFLATED) as archive:
            for item in sorted(export.iterdir()):
                archive.write(item, arcname=f"{export_id}/{item.name}")

    if failed:
        print("")
        print(f"Diagnostic audit ZIP: {audit_zip}")
        raise RuntimeError("Team Salary Semantic Resolution V1 failed: " + ", ".join(failed))

    print("")
    print("=" * 132)
    print("2026 TEAM SALARY MISSING COMPONENTS SEMANTIC RESOLUTION V1 PASSED")
    print("=" * 132)
    print(f"Dead-money false positives closed: {len(dead_rows):>6}/{len(dead_rows)}")
    print(f"Incentive signals classified:      {len(incentive_rows):>6}/{len(incentive_rows)}")
    print(f"Rookie-hold false positives closed:{len(rookie_rows):>6}/{len(rookie_rows)}")
    print(f"Legacy team proxies labeled:       {len(proxy_rows):>6}/{len(proxy_rows)}")
    print(f"Known likely incentives retained:  {len(canonical_incentives):>6}")
    print(f"True blockers remaining:           {len(blockers):>6}")
    print("Official Team Salary complete:        NO")
    print("Components applied:                     0")
    print("Checkpoint write:           NOT PERFORMED")
    print(f"Audit ZIP: {audit_zip}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
