from __future__ import annotations

import csv
import hashlib
import io
import json
import pickle
import re
import tempfile
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


VERSION = "fa-non-rfa-prior-salary-completion-v1-2026-08-15"
SEASON_LABEL = "2026-27"
PRIOR_SALARY_SEASON = "2025-26"
EXPECTED_CHECKPOINT_SHA256 = (
    "19f2fee601f5765bde4f5fabea34f20dc9b8ddc8dd5069186502dff08fc0cf9f"
)
EXPECTED_TARGET_RIGHTS_COUNTS = Counter(
    {"bird": 13, "early_bird": 3, "non_bird": 5, "not_applicable": 19}
)
EXPECTED_NUMERIC_TOTAL = 107_426_612


# These are exact 2025-26 base salaries, not cap hits, dead money, bought-out
# salary, waived salary, or a 2026-27 option/contract value.
SALARY_REGISTRY: dict[str, dict[str, Any]] = {
    "1628988": {
        "player_name": "Aaron Holiday",
        "salary": 3_080_921,
        "source_url": "https://www.salaryswish.com/players/aaron-holiday",
        "mode": "targeted_salaryswish_contract_page_2025_26",
        "reason": "Active Houston contract signed 2025-07-08; selected 2025-26 base salary and rejected the earlier unexercised team option.",
    },
    "1630264": {
        "player_name": "Anthony Gill",
        "salary": 2_667_947,
        "source_url": "https://www.salaryswish.com/players/anthony-gill",
        "mode": "targeted_salaryswish_contract_page_2025_26",
        "reason": "Selected the active 2025-26 Washington contract base salary and rejected the prior waived-contract amount.",
    },
    "1630314": {
        "player_name": "Brandon Williams",
        "salary": 2_270_735,
        "source_url": "https://www.salaryswish.com/players/brandon-williams",
        "mode": "targeted_salaryswish_contract_page_2025_26",
        "reason": "Selected the active 2025-26 Dallas contract base salary.",
    },
    "1629028": {
        "player_name": "Deandre Ayton",
        "salary": 8_104_000,
        "source_url": "https://www.salaryswish.com/players/deandre-ayton",
        "mode": "saved_salaryswish_snapshot_progression_2025_26",
        "reason": "Selected seasonList year 2026 from the saved SalarySwish baseSalaryList.",
    },
    "203939": {
        "player_name": "Dwight Powell",
        "salary": 4_000_000,
        "source_url": "https://www.salaryswish.com/players/dwight-powell",
        "mode": "targeted_salaryswish_contract_page_2025_26",
        "reason": "Selected the active 2025-26 Dallas contract base salary.",
    },
    "202066": {
        "player_name": "Garrett Temple",
        "salary": 3_634_153,
        "source_url": "https://www.salaryswish.com/players/garrett-temple",
        "mode": "targeted_salaryswish_contract_page_2025_26",
        "reason": "Selected the active 2025-26 Toronto contract base salary.",
    },
    "1627780": {
        "player_name": "Gary Payton II",
        "salary": 3_303_774,
        "source_url": "https://www.salaryswish.com/players/gary-paytonii",
        "mode": "targeted_salaryswish_contract_page_2025_26",
        "reason": "Selected the active Golden State contract signed 2025-09-29 and its 2025-26 base salary.",
    },
    "201145": {
        "player_name": "Jeff Green",
        "salary": 3_634_153,
        "source_url": "https://www.salaryswish.com/players/jeff-green",
        "mode": "targeted_salaryswish_contract_page_2025_26",
        "reason": "Selected the active 2025-26 Houston contract base salary.",
    },
    "1630579": {
        "player_name": "Jericho Sims",
        "salary": 2_461_463,
        "source_url": "https://www.salaryswish.com/players/jericho-sims",
        "mode": "saved_salaryswish_snapshot_progression_2025_26",
        "reason": "Selected seasonList year 2026 from the saved SalarySwish baseSalaryList.",
    },
    "1641724": {
        "player_name": "Jett Howard",
        "salary": 5_529_720,
        "source_url": "https://www.salaryswish.com/players/jett-howard",
        "mode": "targeted_salaryswish_contract_page_2025_26",
        "reason": "Selected the 2025-26 rookie-scale base salary; the 2026-27 option outcome is not the prior salary.",
    },
    "1628975": {
        "player_name": "Jevon Carter",
        "salary": 1_168_625,
        "source_url": "https://www.salaryswish.com/players/jevon-carter",
        "mode": "targeted_salaryswish_contract_page_plus_movement_timeline_2025_26",
        "reason": "Selected Orlando rest-of-season salary after Chicago waiver; rejected the waived Chicago contract amount.",
    },
    "1629111": {
        "player_name": "Jock Landale",
        "salary": 2_461_463,
        "source_url": "https://www.salaryswish.com/players/jock-landale",
        "mode": "targeted_salaryswish_contract_page_plus_movement_timeline_2025_26",
        "reason": "Selected the post-waiver Memphis contract salary; rejected the waived Houston contract amount.",
    },
    "1630228": {
        "player_name": "Jonathan Kuminga",
        "salary": 22_500_000,
        "source_url": "https://www.salaryswish.com/players/jonathan-kuminga",
        "mode": "saved_salaryswish_snapshot_progression_2025_26",
        "reason": "Selected seasonList year 2026 from the saved SalarySwish baseSalaryList.",
    },
    "203903": {
        "player_name": "Jordan Clarkson",
        "salary": 3_634_153,
        "source_url": "https://www.salaryswish.com/players/jordan-clarkson",
        "mode": "targeted_salaryswish_contract_page_plus_movement_timeline_2025_26",
        "reason": "Selected the New York contract salary after Utah waiver; rejected bought-out salary and dead-cap values.",
    },
    "1629645": {
        "player_name": "Kevin Porter Jr.",
        "salary": 5_134_000,
        "source_url": "https://www.salaryswish.com/players/kevin-porterjr",
        "mode": "targeted_salaryswish_contract_page_2025_26",
        "reason": "Selected the 2025-26 base salary from the Milwaukee contract signed 2025-07-07; rejected the 2026-27 option value.",
    },
    "203937": {
        "player_name": "Kyle Anderson",
        "salary": 898_095,
        "source_url": "https://www.salaryswish.com/players/kyle-anderson",
        "mode": "targeted_salaryswish_contract_page_plus_movement_timeline_2025_26",
        "reason": "Selected Minnesota rest-of-season salary after Memphis waiver; rejected buyout/dead-cap salary.",
    },
    "1629652": {
        "player_name": "Luguentz Dort",
        "salary": 17_722_222,
        "source_url": "https://www.salaryswish.com/players/luguentz-dort",
        "mode": "saved_salaryswish_snapshot_progression_2025_26",
        "reason": "Selected seasonList year 2026 base salary, not the higher cap hit, from the saved SalarySwish snapshot.",
    },
    "1629021": {
        "player_name": "Moritz Wagner",
        "salary": 5_000_000,
        "source_url": "https://www.salaryswish.com/players/moritz-wagner",
        "mode": "targeted_salaryswish_contract_page_2025_26",
        "reason": "Selected the active 2025-26 Orlando base salary and rejected the older unexercised team-option amount.",
    },
    "201587": {
        "player_name": "Nicolas Batum",
        "salary": 5_601_600,
        "source_url": "https://www.salaryswish.com/players/nicolas-batum",
        "mode": "saved_salaryswish_snapshot_progression_2025_26",
        "reason": "Selected seasonList year 2026 from the saved SalarySwish baseSalaryList.",
    },
    "1626192": {
        "player_name": "Pat Connaughton",
        "salary": 1_315_814,
        "source_url": "https://www.salaryswish.com/players/pat-connaughton",
        "mode": "saved_salaryswish_snapshot_progression_2025_26",
        "reason": "Selected seasonList year 2026 from the saved SalarySwish baseSalaryList.",
    },
    "1627752": {
        "player_name": "Taurean Prince",
        "salary": 3_303_774,
        "source_url": "https://www.salaryswish.com/players/taurean-prince",
        "mode": "saved_salaryswish_snapshot_progression_2025_26",
        "reason": "Selected seasonList year 2026 from the saved SalarySwish baseSalaryList.",
    },
}

SNAPSHOT_EXPECTED = {
    pid: int(record["salary"])
    for pid, record in SALARY_REGISTRY.items()
    if record["mode"] == "saved_salaryswish_snapshot_progression_2025_26"
}

CONFLICT_REQUIREMENTS = {
    "1629111": {
        "required_events": {("Waive", "2025-07-03", "HOU"), ("Signing", "2025-07-15", "MEM")},
        "required_candidates": {8_000_000, 2_461_463},
    },
    "203903": {
        "required_events": {("Waive", "2025-07-01", "UTA"), ("Signing", "2025-07-07", "NYK")},
        "required_candidates": {14_285_714, 3_634_153, 10_651_561},
    },
    "1628975": {
        "required_events": {("Waive", "2026-02-01", "CHI"), ("Signing", "2026-02-06", "ORL")},
        "required_candidates": {6_809_524, 1_168_625},
    },
    "203937": {
        "required_events": {("Waive", "2026-02-26", "MEM"), ("Signing", "2026-03-01", "MIN")},
        "required_candidates": {9_219_512, 898_095},
    },
}


def clean(value: Any) -> str:
    return str(value or "").strip()


def player_id(value: Any) -> str:
    text = clean(value)
    if text.endswith(".0") and text[:-2].isdigit():
        return text[:-2]
    return text


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


def read_csv_suffix(archive: zipfile.ZipFile, suffix: str) -> list[dict[str, str]]:
    member = next((name for name in archive.namelist() if name.endswith(suffix)), "")
    if not member:
        raise RuntimeError(f"ZIP missing member: {suffix}")
    text = archive.read(member).decode("utf-8-sig", errors="replace")
    return list(csv.DictReader(io.StringIO(text))) if text.strip() else []


def read_json_suffix(archive: zipfile.ZipFile, suffix: str) -> dict[str, Any]:
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


def money_value(value: Any) -> int | None:
    text = clean(value)
    if not text:
        return None
    match = re.search(r"\$?([0-9][0-9,]*)", text)
    return int(match.group(1).replace(",", "")) if match else None


def snapshot_salary(
    archive: zipfile.ZipFile,
    pid: str,
) -> tuple[int, str]:
    member = next(
        (
            name
            for name in archive.namelist()
            if "/snapshots/" in name and name.split("/")[-1].startswith(f"{pid}_")
        ),
        "",
    )
    if not member:
        raise RuntimeError(f"Missing SalarySwish snapshot for player_id={pid}")
    html = archive.read(member).decode("utf-8", errors="replace")
    match = re.search(r"salaryProgressionData\s*=\s*(\{.*?\});</script>", html)
    if not match:
        raise RuntimeError(f"Unparseable SalarySwish snapshot for player_id={pid}")
    progression = json.loads(match.group(1))["salaryProgressionData"]
    index = progression["seasonList"].index(2026)
    return int(progression["baseSalaryList"][index]), member


def main() -> int:
    root = Path.cwd().resolve()
    gap_zip = latest(root, "fa_non_rfa_evidence_gap_harvest_v1_2026-27_*.zip")
    raw_zip = latest(root, "fa_non_rfa_raw_evidence_schema_probe_v1_2026-27_*.zip")
    rights_zip = latest(root, "fa_non_rfa_rights_final_completion_v1_2026-27_*.zip")
    decision_zip = latest(root, "fa_unified_offseason_decision_preview_v1_1_2026-27_*.zip")

    with zipfile.ZipFile(gap_zip) as archive:
        gap_summary = read_json_suffix(archive, "non_rfa_gap_harvest_summary.json")
        unresolved_40 = read_csv_suffix(archive, "prior_salary_still_unresolved.csv")

    with zipfile.ZipFile(raw_zip) as archive:
        raw_summary = read_json_suffix(archive, "raw_evidence_probe_summary.json")
        raw_rows = read_csv_suffix(archive, "raw_target_evidence_rows.csv")

    with zipfile.ZipFile(rights_zip) as archive:
        rights_summary = read_json_suffix(archive, "non_rfa_rights_final_completion_summary.json")
        rights_rows = read_csv_suffix(archive, "non_rfa_rights_evidence_complete_162.csv")

    with zipfile.ZipFile(decision_zip) as archive:
        decision_summary = read_json_suffix(archive, "decision_preview_summary.json")
        snapshot_results = {
            pid: snapshot_salary(archive, pid) for pid in sorted(SNAPSHOT_EXPECTED)
        }

    if not gap_summary.get("passed"):
        raise RuntimeError("Upstream non-RFA gap harvest did not pass.")
    if not raw_summary.get("passed"):
        raise RuntimeError("Upstream raw evidence schema probe did not pass.")
    if not rights_summary.get("passed"):
        raise RuntimeError("Upstream final rights completion did not pass.")
    if not decision_summary.get("passed"):
        raise RuntimeError("Upstream unified decision preview did not pass.")

    target_by_id = {player_id(row.get("player_id")): row for row in unresolved_40}
    rights_by_id = {player_id(row.get("player_id")): row for row in rights_rows}
    duplicate_target_ids = len(target_by_id) != len(unresolved_40)
    duplicate_rights_ids = len(rights_by_id) != len(rights_rows)

    conflicts: list[dict[str, Any]] = []
    resolved_rows: list[dict[str, Any]] = []
    not_required_rows: list[dict[str, Any]] = []

    for pid in sorted(target_by_id, key=lambda value: int(value)):
        target = target_by_id[pid]
        rights = rights_by_id.get(pid, {})
        target_name = clean(target.get("player_name"))
        rights_name = clean(rights.get("player_name"))
        target_team = clean(target.get("prior_team"))
        rights_team = clean(rights.get("prior_team"))
        classification = clean(rights.get("final_rights_classification"))

        if not rights:
            conflicts.append({
                "player_id": pid,
                "player_name": target_name,
                "conflict_type": "missing_final_rights_row",
                "detail": "Target is absent from the final 162-player rights table.",
            })
            continue
        if target_name != rights_name or target_team != rights_team:
            conflicts.append({
                "player_id": pid,
                "player_name": target_name,
                "conflict_type": "player_identity_or_prior_team_mismatch",
                "detail": f"gap={target_name}|{target_team}; rights={rights_name}|{rights_team}",
            })

        base = {
            "player_id": pid,
            "player_name": target_name,
            "prior_team": target_team,
            "final_rights_classification": classification,
            "prior_salary_season": PRIOR_SALARY_SEASON,
        }

        if classification == "not_applicable":
            if pid in SALARY_REGISTRY:
                conflicts.append({
                    "player_id": pid,
                    "player_name": target_name,
                    "conflict_type": "not_applicable_player_has_numeric_registry_entry",
                    "detail": str(SALARY_REGISTRY[pid]["salary"]),
                })
            not_required_rows.append({
                **base,
                "prior_regular_salary": "",
                "resolution_status": "not_required",
                "resolution_reason": "prior_salary_not_required_for_free_agent_amount",
                "evidence_mode": "final_rights_classification_not_applicable",
                "source_url": "",
                "salary_applied_to_simulation": False,
            })
            continue

        record = SALARY_REGISTRY.get(pid)
        if not record:
            conflicts.append({
                "player_id": pid,
                "player_name": target_name,
                "conflict_type": "salary_dependent_target_missing_registry_entry",
                "detail": classification,
            })
            continue
        if clean(record["player_name"]) != target_name:
            conflicts.append({
                "player_id": pid,
                "player_name": target_name,
                "conflict_type": "salary_registry_player_name_mismatch",
                "detail": clean(record["player_name"]),
            })
        resolved_rows.append({
            **base,
            "prior_regular_salary": int(record["salary"]),
            "resolution_status": "numeric_resolved",
            "resolution_reason": clean(record["reason"]),
            "evidence_mode": clean(record["mode"]),
            "source_url": clean(record["source_url"]),
            "evidence_verified_as_of": "2026-08-15",
            "salary_applied_to_simulation": False,
        })

    complete_rows = sorted(
        [*resolved_rows, *not_required_rows], key=lambda row: int(row["player_id"])
    )

    conflict_resolution_rows: list[dict[str, Any]] = []
    raw_by_id: dict[str, list[dict[str, str]]] = {}
    for row in raw_rows:
        raw_by_id.setdefault(player_id(row.get("player_id")), []).append(row)

    for pid, requirement in CONFLICT_REQUIREMENTS.items():
        rows = raw_by_id.get(pid, [])
        observed_events = {
            (
                clean(row.get("src__transaction_type")),
                clean(row.get("src__transaction_date")),
                clean(row.get("src__team_abbreviation")),
            )
            for row in rows
            if clean(row.get("src__transaction_type"))
        }
        observed_candidates = {
            value
            for row in rows
            for value in [money_value(row.get("src__prior_base_salary"))]
            if value is not None
        }
        events_complete = requirement["required_events"].issubset(observed_events)
        candidates_complete = requirement["required_candidates"].issubset(observed_candidates)
        selected = int(SALARY_REGISTRY[pid]["salary"])
        conflict_resolution_rows.append({
            "player_id": pid,
            "player_name": SALARY_REGISTRY[pid]["player_name"],
            "selected_prior_regular_salary": selected,
            "required_events_verified": events_complete,
            "required_candidate_values_verified": candidates_complete,
            "required_events": "; ".join("|".join(item) for item in sorted(requirement["required_events"])),
            "required_candidate_values": "; ".join(str(item) for item in sorted(requirement["required_candidates"])),
            "observed_candidate_values": "; ".join(str(item) for item in sorted(observed_candidates)),
            "resolution_reason": SALARY_REGISTRY[pid]["reason"],
            "source_url": SALARY_REGISTRY[pid]["source_url"],
            "salary_applied_to_simulation": False,
        })

    snapshot_verification_rows = []
    for pid, expected in sorted(SNAPSHOT_EXPECTED.items()):
        observed, member = snapshot_results[pid]
        snapshot_verification_rows.append({
            "player_id": pid,
            "player_name": SALARY_REGISTRY[pid]["player_name"],
            "expected_2025_26_base_salary": expected,
            "observed_2025_26_base_salary": observed,
            "matched": observed == expected,
            "snapshot_member": member,
            "source_url": SALARY_REGISTRY[pid]["source_url"],
        })

    import simulation_franchise_checkpoint_v1 as checkpoint_module

    checkpoint_path = Path(checkpoint_module.DEFAULT_CHECKPOINT_PATH)
    checkpoint_hash_before = sha256_file(checkpoint_path)
    checkpoint = checkpoint_module.load_franchise_checkpoint()
    simulation_digest_before = object_digest(checkpoint.simulation_state)
    if checkpoint_hash_before != EXPECTED_CHECKPOINT_SHA256:
        raise RuntimeError(
            "Canonical checkpoint changed before prior-salary evidence completion."
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
    print("2026 NON-RFA PRIOR SALARY COMPLETION V1")
    print("=" * 132)
    print("Resolving the 40-player prior-salary blocker as evidence only...")

    add(
        "all_required_upstream_audits_passed",
        all(summary.get("passed") for summary in [gap_summary, raw_summary, rights_summary, decision_summary]),
        "Gap harvest, raw probe, final rights, and decision snapshot audits passed.",
    )
    add(
        "upstream_gap_is_exactly_40_players",
        len(unresolved_40) == 40 and int(gap_summary.get("prior_salary_gap_count", -1)) == 40 and not duplicate_target_ids,
        f"rows={len(unresolved_40)}, unique_ids={len(target_by_id)}",
    )
    add(
        "final_rights_table_is_exactly_162_complete_players",
        len(rights_rows) == 162 and not duplicate_rights_ids and int(rights_summary.get("final_resolved_count", -1)) == 162,
        f"rows={len(rights_rows)}, unique_ids={len(rights_by_id)}",
    )
    target_rights_counts = Counter(
        clean(rights_by_id.get(pid, {}).get("final_rights_classification"))
        for pid in target_by_id
    )
    add(
        "target_rights_distribution_matches_13_3_5_19",
        target_rights_counts == EXPECTED_TARGET_RIGHTS_COUNTS,
        repr(dict(target_rights_counts)),
    )
    add(
        "salary_registry_exactly_covers_21_dependent_players",
        len(SALARY_REGISTRY) == 21
        and set(SALARY_REGISTRY)
        == {pid for pid in target_by_id if clean(rights_by_id[pid].get("final_rights_classification")) != "not_applicable"},
        f"registry={len(SALARY_REGISTRY)}",
    )
    add(
        "exact_21_numeric_salaries_resolved",
        len(resolved_rows) == 21 and all(isinstance(row["prior_regular_salary"], int) and row["prior_regular_salary"] > 0 for row in resolved_rows),
        f"numeric_resolved={len(resolved_rows)}",
    )
    add(
        "numeric_salary_total_matches_expected",
        sum(int(row["prior_regular_salary"]) for row in resolved_rows) == EXPECTED_NUMERIC_TOTAL,
        f"total={sum(int(row['prior_regular_salary']) for row in resolved_rows)}",
    )
    add(
        "exact_19_not_applicable_rows_closed_without_fake_salary",
        len(not_required_rows) == 19
        and all(row["prior_regular_salary"] == "" and row["resolution_status"] == "not_required" for row in not_required_rows),
        f"not_required={len(not_required_rows)}",
    )
    add(
        "all_7_saved_snapshot_values_match_exactly",
        len(snapshot_verification_rows) == 7 and all(row["matched"] for row in snapshot_verification_rows),
        f"matched={sum(bool(row['matched']) for row in snapshot_verification_rows)}/7",
    )
    add(
        "all_4_conflict_timelines_and_candidates_verified",
        len(conflict_resolution_rows) == 4
        and all(row["required_events_verified"] and row["required_candidate_values_verified"] for row in conflict_resolution_rows),
        f"verified={sum(bool(row['required_events_verified'] and row['required_candidate_values_verified']) for row in conflict_resolution_rows)}/4",
    )
    add(
        "all_21_numeric_rows_retain_source_provenance",
        all(clean(row["source_url"]) and clean(row["evidence_mode"]) and clean(row["resolution_reason"]) for row in resolved_rows),
        "Every numeric resolution includes source URL, mode, and selection reason.",
    )
    add(
        "all_40_targets_closed_without_merge_conflicts",
        len(complete_rows) == 40 and not conflicts,
        f"closed={len(complete_rows)}/40, conflicts={len(conflicts)}",
    )
    add(
        "salary_evidence_not_applied_to_simulation",
        all(not row["salary_applied_to_simulation"] for row in complete_rows),
        "Evidence completion only.",
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
    export_id = f"fa_non_rfa_prior_salary_completion_v1_{SEASON_LABEL}_{timestamp}"
    output_dir = root / "outputs" / "audits"
    output_dir.mkdir(parents=True, exist_ok=True)
    audit_zip = output_dir / f"{export_id}.zip"

    summary = {
        "version": VERSION,
        "target_count": len(target_by_id),
        "numeric_salary_resolved_count": len(resolved_rows),
        "not_required_count": len(not_required_rows),
        "final_closed_count": len(complete_rows),
        "final_unresolved_count": 40 - len(complete_rows),
        "target_rights_counts": dict(sorted(target_rights_counts.items())),
        "numeric_salary_total": sum(int(row["prior_regular_salary"]) for row in resolved_rows),
        "saved_snapshot_value_count": len(snapshot_verification_rows),
        "salary_conflict_resolved_count": len(conflict_resolution_rows),
        "merge_conflict_count": len(conflicts),
        "salary_values_applied": 0,
        "cap_holds_computed": 0,
        "state_mutation_performed": False,
        "checkpoint_write_performed": False,
        "source_gap_harvest_audit": gap_zip.name,
        "source_raw_probe_audit": raw_zip.name,
        "source_final_rights_audit": rights_zip.name,
        "source_saved_snapshot_audit": decision_zip.name,
        "passed": not failed,
        "failed_checks": failed,
        "next_slice": (
            "Merge the 21 numeric prior salaries and 19 not-required closures into the "
            "226-player owner/rights registry, then compute full-market Free Agent "
            "Amounts and cap holds in a separate preview before any simulation application."
        ),
    }

    with tempfile.TemporaryDirectory(prefix="fa_non_rfa_prior_salary_completion_") as temporary_directory:
        export = Path(temporary_directory) / export_id
        export.mkdir(parents=True)
        write_csv(export / "non_rfa_prior_salary_resolution_40.csv", complete_rows)
        write_csv(export / "non_rfa_prior_salary_numeric_resolved_21.csv", resolved_rows)
        write_csv(export / "non_rfa_prior_salary_not_required_19.csv", not_required_rows)
        write_csv(export / "non_rfa_prior_salary_conflicts_resolved_4.csv", conflict_resolution_rows)
        write_csv(export / "non_rfa_prior_salary_saved_snapshot_verification_7.csv", snapshot_verification_rows)
        write_csv(export / "non_rfa_prior_salary_completion_conflicts.csv", conflicts)
        write_csv(export / "non_rfa_prior_salary_completion_checks.csv", checks)
        (export / "non_rfa_prior_salary_completion_summary.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8"
        )
        (export / "README.txt").write_text(
            """2026 NON-RFA PRIOR SALARY COMPLETION V1
===========================================

Purpose
-------
Close the 40-player prior-salary blocker left by the non-RFA evidence harvest.

Expected result
---------------
- 21 salary-dependent players receive exact 2025-26 prior regular salary evidence.
- 19 players classified not_applicable are closed as salary not required.
- Four multi-contract conflicts are resolved using canonical movement timelines.
- Seven saved SalarySwish snapshots are re-parsed and matched exactly.
- 40/40 targets are closed with source provenance.

This is an EVIDENCE-ONLY completion layer.
No salary is applied to simulation state.
No Free Agent Amount or cap hold is computed.
No roster, contract, QO, renouncement, Team Salary, or checkpoint write occurs.
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
            "Non-RFA Prior Salary Completion V1 failed: " + ", ".join(failed)
        )

    print("")
    print("=" * 132)
    print("2026 NON-RFA PRIOR SALARY COMPLETION V1 PASSED")
    print("=" * 132)
    print("Numeric salaries resolved: 21/21")
    print("Not-required closures:      19/19")
    print("Conflict cases resolved:      4/4")
    print("Final blocker closure:       40/40")
    print("Salary values applied:        0")
    print("Cap holds computed:           0")
    print(f"Audit ZIP: {audit_zip}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
