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
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any


VERSION = "fa-full-market-free-agent-amount-completion-v1-2026-08-15"
SEASON_LABEL = "2026-27"
EXPECTED_CHECKPOINT_SHA256 = (
    "19f2fee601f5765bde4f5fabea34f20dc9b8ddc8dd5069186502dff08fc0cf9f"
)
SALARY_CAP_2026_27 = 164_961_000
ESTIMATED_AVERAGE_PLAYER_SALARY_2025_26 = 13_870_000
CBA_URL = (
    "https://imgix.cosmicjs.com/25da5eb0-15eb-11ee-b5b3-fbd321202bdf-"
    "Final-2023-NBA-Collective-Bargaining-Agreement-6-28-23.pdf"
)
NBA_2025_26_CAP_URL = "https://www.nba.com/news/nba-salary-cap-set-2025-26-season"
NBA_2026_27_CAP_URL = "https://www.nba.com/news/nba-salary-cap-2026-27-season"
EAPS_SOURCE_URL = (
    "https://www.hoopsrumors.com/2025/06/salary-cap-tax-line-set-for-2025-26-nba-season.html"
)

# Article I / Exhibit C annual minimum scale values, adjusted by the final
# Salary Cap for each season. Values are first-year annual salaries.
MINIMUM_SALARY_2025_26 = {
    0: 1_272_870,
    1: 2_048_494,
    2: 2_296_274,
    3: 2_378_870,
    4: 2_461_463,
    5: 2_667_947,
    6: 2_874_436,
    7: 3_080_921,
    8: 3_287_409,
    9: 3_303_771,
    10: 3_634_153,
}
MINIMUM_SALARY_2026_27 = {
    0: 1_357_763,
    1: 2_185_116,
    2: 2_449_421,
    3: 2_537_526,
    4: 2_625_627,
    5: 2_845_883,
    6: 3_066_143,
    7: 3_286_399,
    8: 3_506_659,
    9: 3_524_115,
    10: 3_876_529,
}
MAXIMUM_SALARY_PERCENT = {"0_6": Decimal("0.25"), "7_9": Decimal("0.30"), "10_plus": Decimal("0.35")}
EXPECTED_RIGHTS_COUNTS = Counter(
    {"bird": 44, "early_bird": 14, "non_bird": 48, "not_applicable": 56}
)
EXPECTED_FORMULA_FAMILIES = Counter(
    {
        "prior_minimum_non_reimbursed_current_minimum": 60,
        "bird_190_pct": 17,
        "bird_150_pct": 14,
        "non_bird_120_pct": 9,
        "early_bird_130_pct": 4,
        "rookie_scale_declined_option_amount": 2,
        "exact_rfa_amount_preserved": 64,
        "no_veteran_free_agent_amount_required": 56,
    }
)
EXPECTED_NON_RFA_AMOUNT_TOTAL = 999_397_109
EXPECTED_RFA_AMOUNT_TOTAL = 232_178_464
EXPECTED_FULL_MARKET_AMOUNT_TOTAL = 1_231_575_573
ROOKIE_OPTION_EXCEPTION_IDS = {"1641724", "1641738"}


def clean(value: Any) -> str:
    return str(value or "").strip()


def pid(value: Any) -> str:
    text = clean(value)
    return text[:-2] if text.endswith(".0") and text[:-2].isdigit() else text


def as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return clean(value).lower() in {"true", "1", "yes", "y"}


def integer(value: Any, *, label: str) -> int:
    text = clean(value).replace("$", "").replace(",", "")
    if not text:
        raise RuntimeError(f"Missing integer value for {label}.")
    number = Decimal(text)
    if number <= 0 or number != number.to_integral_value():
        raise RuntimeError(f"Invalid integer value for {label}: {value!r}")
    return int(number)


def years_of_service(value: Any) -> int | None:
    text = clean(value)
    if not text:
        return None
    number = Decimal(text)
    if number < 0 or number != number.to_integral_value():
        return None
    return int(number)


def round_dollar(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


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


def optional_csv_suffix(archive: zipfile.ZipFile, suffix: str) -> list[dict[str, str]]:
    member = next((name for name in archive.namelist() if name.endswith(suffix)), "")
    if not member:
        return []
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


def service_bucket(service: int) -> str:
    if service >= 10:
        return "10_plus"
    if service >= 7:
        return "7_9"
    return "0_6"


def maximum_salary(service: int, prior_salary: int) -> int:
    cap_max = Decimal(SALARY_CAP_2026_27) * MAXIMUM_SALARY_PERCENT[service_bucket(service)]
    prior_max = Decimal(prior_salary) * Decimal("1.05")
    return round_dollar(max(cap_max, prior_max))


def current_non_reimbursed_minimum(service: int) -> int:
    # For a veteran with 3+ YOS, the Benefits Fund reimburses the portion above
    # the two-YOS minimum. The non-reimbursed Team Salary amount is therefore
    # the current two-YOS minimum. Players with 0-1 YOS use their own minimum.
    return MINIMUM_SALARY_2026_27[min(service, 2)]


def main() -> int:
    root = Path.cwd().resolve()
    registry_zip = latest(root, "fa_full_market_registry_completion_v1_2026-27_*.zip")
    rfa_zip = latest(root, "fa_qo_cap_hold_completion_v1_0_1_2026-27_*.zip")
    service_zip = latest(root, "fa_final_market_rfa_qo_eligibility_readiness_v1_2026-27_*.zip")
    legacy_rights_zip = latest(root, "fa_rights_registry_v2_preview_2026-27_*.zip")
    lifecycle_zip = latest(root, "fa_contract_option_lifecycle_readiness_v1_0_1_2026-27_*.zip")

    with zipfile.ZipFile(registry_zip) as archive:
        registry_summary = json_suffix(archive, "full_market_registry_completion_summary.json")
        registry_rows = csv_suffix(archive, "full_market_registry_complete_226.csv")
    with zipfile.ZipFile(rfa_zip) as archive:
        rfa_summary = json_suffix(archive, "qo_cap_hold_completion_summary.json")
        rfa_rows = csv_suffix(archive, "qo_exact_cap_holds_completed_64.csv")
    with zipfile.ZipFile(service_zip) as archive:
        service_rows = csv_suffix(archive, "rfa_qo_eligibility_readiness_all_226.csv")
    with zipfile.ZipFile(legacy_rights_zip) as archive:
        legacy_service_rows = csv_suffix(archive, "final_rights_registry_preview.csv")
    with zipfile.ZipFile(lifecycle_zip) as archive:
        lifecycle_summary = json_suffix(archive, "contract_option_summary.json")
        option_rows = csv_suffix(archive, "rookie_scale_option_exception_rows.csv")

    if not registry_summary.get("passed"):
        raise RuntimeError("Upstream full-market registry completion did not pass.")
    if not rfa_summary.get("passed"):
        raise RuntimeError("Upstream exact RFA cap-hold completion did not pass.")
    if not lifecycle_summary.get("passed"):
        raise RuntimeError("Upstream contract-option lifecycle audit did not pass.")

    registry_by_id = {pid(row.get("player_id")): row for row in registry_rows}
    rfa_by_id = {pid(row.get("player_id")): row for row in rfa_rows}
    option_by_id = {pid(row.get("player_id")): row for row in option_rows}

    service_evidence: dict[str, tuple[int, str]] = {}
    service_conflicts: list[dict[str, Any]] = []

    def merge_service(row: dict[str, str], source: str) -> None:
        player_id = pid(row.get("player_id"))
        service = years_of_service(row.get("years_of_service"))
        if not player_id or service is None:
            return
        prior = service_evidence.get(player_id)
        if prior and prior[0] != service:
            service_conflicts.append({
                "player_id": player_id,
                "player_name": clean(row.get("player_name")),
                "conflict_type": "years_of_service_mismatch",
                "detail": f"{prior[0]} ({prior[1]}) vs {service} ({source})",
            })
            return
        service_evidence.setdefault(player_id, (service, source))

    for row in service_rows:
        merge_service(row, "final_market_rfa_qo_eligibility_readiness")
    for row in legacy_service_rows:
        player_id = pid(row.get("player_id"))
        if player_id not in service_evidence:
            merge_service(row, "legacy_rights_registry_fallback")

    conflicts = list(service_conflicts)
    completed_rows: list[dict[str, Any]] = []
    amount_rows: list[dict[str, Any]] = []
    no_amount_rows: list[dict[str, Any]] = []

    for player_id in sorted(registry_by_id, key=lambda value: int(value)):
        row = registry_by_id[player_id]
        player_name = clean(row.get("player_name"))
        prior_team = clean(row.get("resolved_prior_team"))
        market_category = clean(row.get("market_category"))
        rights = clean(row.get("final_rights_classification"))

        base = {
            "player_id": player_id,
            "player_name": player_name,
            "prior_team": prior_team,
            "market_category": market_category,
            "rights_classification": rights,
            "prior_regular_salary_2025_26": clean(row.get("final_prior_regular_salary")),
            "estimated_average_player_salary_2025_26": ESTIMATED_AVERAGE_PLAYER_SALARY_2025_26,
            "salary_cap_2026_27": SALARY_CAP_2026_27,
            "amount_applied_to_simulation": False,
            "cap_hold_applied": False,
            "rights_renounced": False,
            "state_mutation_applied": False,
        }

        if market_category == "rfa_exact":
            exact = rfa_by_id.get(player_id)
            if not exact:
                conflicts.append({
                    "player_id": player_id,
                    "player_name": player_name,
                    "conflict_type": "missing_exact_rfa_amount",
                    "detail": "",
                })
                continue
            amount = integer(exact.get("exact_cap_hold_2026_27"), label=f"{player_name} exact RFA amount")
            completed = {
                **base,
                "years_of_service": "",
                "service_evidence_source": "not_required_exact_rfa_pipeline",
                "prior_applicable_minimum_2025_26": "",
                "current_non_reimbursed_minimum_2026_27": "",
                "applicable_maximum_salary_2026_27": "",
                "formula_multiplier": "",
                "raw_formula_amount": amount,
                "final_free_agent_amount_2026_27": amount,
                "formula_family": "exact_rfa_amount_preserved",
                "amount_status": "exact_ready_not_applied",
                "amount_evidence_mode": clean(exact.get("evidence_mode")),
                "amount_evidence_url": clean(exact.get("evidence_url")),
                "cba_authority_url": clean(exact.get("cba_authority_url")) or CBA_URL,
                "minimum_branch_triggered": False,
                "maximum_ceiling_triggered": False,
                "rookie_option_exception_triggered": False,
            }
            completed_rows.append(completed)
            amount_rows.append(completed)
            continue

        if rights == "not_applicable":
            completed = {
                **base,
                "years_of_service": "",
                "service_evidence_source": "not_required_by_final_rights_classification",
                "prior_applicable_minimum_2025_26": "",
                "current_non_reimbursed_minimum_2026_27": "",
                "applicable_maximum_salary_2026_27": "",
                "formula_multiplier": "",
                "raw_formula_amount": "",
                "final_free_agent_amount_2026_27": "",
                "formula_family": "no_veteran_free_agent_amount_required",
                "amount_status": "not_required",
                "amount_evidence_mode": "final_rights_classification_not_applicable",
                "amount_evidence_url": "",
                "cba_authority_url": CBA_URL,
                "minimum_branch_triggered": False,
                "maximum_ceiling_triggered": False,
                "rookie_option_exception_triggered": False,
            }
            completed_rows.append(completed)
            no_amount_rows.append(completed)
            continue

        if rights not in {"bird", "early_bird", "non_bird"}:
            conflicts.append({
                "player_id": player_id,
                "player_name": player_name,
                "conflict_type": "unsupported_rights_classification",
                "detail": rights,
            })
            continue

        prior_salary = integer(
            row.get("final_prior_regular_salary"), label=f"{player_name} prior salary"
        )
        service_record = service_evidence.get(player_id)
        if not service_record:
            conflicts.append({
                "player_id": player_id,
                "player_name": player_name,
                "conflict_type": "missing_years_of_service",
                "detail": rights,
            })
            continue
        service, service_source = service_record
        prior_minimum = MINIMUM_SALARY_2025_26[min(service, 10)]
        current_floor = current_non_reimbursed_minimum(service)
        maximum = maximum_salary(service, prior_salary)
        minimum_triggered = prior_salary <= prior_minimum
        rookie_option_triggered = player_id in ROOKIE_OPTION_EXCEPTION_IDS
        multiplier = ""

        if rookie_option_triggered:
            option = option_by_id.get(player_id)
            if not option or not as_bool(option.get("rookie_scale_first_round_option_exception")):
                conflicts.append({
                    "player_id": player_id,
                    "player_name": player_name,
                    "conflict_type": "missing_rookie_option_exception_evidence",
                    "detail": "",
                })
                continue
            raw_amount = integer(
                option.get("season_2026_27_base_salary"),
                label=f"{player_name} declined rookie option amount",
            )
            family = "rookie_scale_declined_option_amount"
            evidence_mode = "verified_pre_split_rookie_scale_fourth_year_option_declined"
            minimum_triggered = False
        elif minimum_triggered:
            raw_amount = current_floor
            family = "prior_minimum_non_reimbursed_current_minimum"
            evidence_mode = "cba_article_vii_section_4d_minimum_branch"
        else:
            if rights == "bird":
                multiplier = "1.50" if prior_salary >= ESTIMATED_AVERAGE_PLAYER_SALARY_2025_26 else "1.90"
                family = "bird_150_pct" if multiplier == "1.50" else "bird_190_pct"
            elif rights == "early_bird":
                multiplier = "1.30"
                family = "early_bird_130_pct"
            else:
                multiplier = "1.20"
                family = "non_bird_120_pct"
            raw_amount = round_dollar(Decimal(prior_salary) * Decimal(multiplier))
            evidence_mode = "cba_article_vii_section_4d_veteran_formula"

        final_amount = min(max(raw_amount, current_floor), maximum)
        maximum_triggered = final_amount < raw_amount
        completed = {
            **base,
            "years_of_service": service,
            "service_evidence_source": service_source,
            "prior_applicable_minimum_2025_26": prior_minimum,
            "current_non_reimbursed_minimum_2026_27": current_floor,
            "applicable_maximum_salary_2026_27": maximum,
            "formula_multiplier": multiplier,
            "raw_formula_amount": raw_amount,
            "final_free_agent_amount_2026_27": final_amount,
            "formula_family": family,
            "amount_status": "exact_ready_not_applied",
            "amount_evidence_mode": evidence_mode,
            "amount_evidence_url": EAPS_SOURCE_URL if rights == "bird" else "",
            "cba_authority_url": CBA_URL,
            "minimum_branch_triggered": minimum_triggered,
            "maximum_ceiling_triggered": maximum_triggered,
            "rookie_option_exception_triggered": rookie_option_triggered,
        }
        completed_rows.append(completed)
        amount_rows.append(completed)

    rights_counts = Counter(
        clean(row.get("rights_classification"))
        for row in completed_rows
        if row["market_category"] == "non_rfa"
    )
    formula_counts = Counter(clean(row.get("formula_family")) for row in completed_rows)
    salary_dependent_rows = [
        row for row in amount_rows if row["market_category"] == "non_rfa"
    ]
    exact_rfa_rows = [row for row in amount_rows if row["market_category"] == "rfa_exact"]
    minimum_rows = [row for row in salary_dependent_rows if row["minimum_branch_triggered"]]
    option_exception_rows = [row for row in salary_dependent_rows if row["rookie_option_exception_triggered"]]
    max_rows = [row for row in salary_dependent_rows if row["maximum_ceiling_triggered"]]
    non_rfa_total = sum(int(row["final_free_agent_amount_2026_27"]) for row in salary_dependent_rows)
    rfa_total = sum(int(row["final_free_agent_amount_2026_27"]) for row in exact_rfa_rows)
    full_total = non_rfa_total + rfa_total

    import simulation_franchise_checkpoint_v1 as checkpoint_module

    checkpoint_path = Path(checkpoint_module.DEFAULT_CHECKPOINT_PATH)
    checkpoint_hash_before = sha256_file(checkpoint_path)
    checkpoint = checkpoint_module.load_franchise_checkpoint()
    simulation_digest_before = object_digest(checkpoint.simulation_state)
    if checkpoint_hash_before != EXPECTED_CHECKPOINT_SHA256:
        raise RuntimeError("Canonical checkpoint changed before Free Agent Amount completion.")

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
    print("2026 FULL-MARKET FREE AGENT AMOUNT COMPLETION V1")
    print("=" * 132)
    print("Computing all 2026-27 Free Agent Amounts as read-only evidence...")

    add("all_required_upstream_audits_passed", bool(registry_summary.get("passed") and rfa_summary.get("passed") and lifecycle_summary.get("passed")), "Registry, exact-RFA, and lifecycle audits passed.")
    add("registry_has_exact_226_unique_players", len(registry_rows) == len(registry_by_id) == 226, f"rows={len(registry_rows)}, unique={len(registry_by_id)}")
    add("exact_rfa_source_has_64_unique_players", len(rfa_rows) == len(rfa_by_id) == 64, f"rows={len(rfa_rows)}, unique={len(rfa_by_id)}")
    add("full_market_partition_is_64_106_56", len(exact_rfa_rows) == 64 and len(salary_dependent_rows) == 106 and len(no_amount_rows) == 56, f"rfa={len(exact_rfa_rows)}, veteran={len(salary_dependent_rows)}, no_amount={len(no_amount_rows)}")
    add("all_106_veteran_formula_rows_have_exact_service", len(salary_dependent_rows) == 106 and all(clean(row.get("years_of_service")) for row in salary_dependent_rows), f"resolved={sum(bool(clean(row.get('years_of_service'))) for row in salary_dependent_rows)}/106")
    add("service_evidence_conflicts_are_zero", not service_conflicts, f"conflicts={len(service_conflicts)}")
    add("non_rfa_rights_distribution_matches_expected", rights_counts == EXPECTED_RIGHTS_COUNTS, repr(dict(rights_counts)))
    add("estimated_average_salary_constant_is_frozen", ESTIMATED_AVERAGE_PLAYER_SALARY_2025_26 == 13_870_000, f"EAPS={ESTIMATED_AVERAGE_PLAYER_SALARY_2025_26}")
    add("exact_two_rookie_option_exceptions_applied", {row["player_id"] for row in option_exception_rows} == ROOKIE_OPTION_EXCEPTION_IDS, repr(sorted(row["player_id"] for row in option_exception_rows)))
    add("minimum_salary_branch_count_matches_expected", len(minimum_rows) == 60, f"minimum_branch={len(minimum_rows)}")
    add("formula_family_distribution_matches_expected", formula_counts == EXPECTED_FORMULA_FAMILIES, repr(dict(formula_counts)))
    add("non_rfa_amount_total_matches_expected", non_rfa_total == EXPECTED_NON_RFA_AMOUNT_TOTAL, f"total={non_rfa_total}")
    add("exact_rfa_amount_total_matches_expected", rfa_total == EXPECTED_RFA_AMOUNT_TOTAL, f"total={rfa_total}")
    add("full_market_amount_total_matches_expected", full_total == EXPECTED_FULL_MARKET_AMOUNT_TOTAL, f"total={full_total}")
    add("all_170_required_amounts_are_exact_ready", len(amount_rows) == 170 and all(row["amount_status"] == "exact_ready_not_applied" and int(row["final_free_agent_amount_2026_27"]) > 0 for row in amount_rows), f"ready={len(amount_rows)}/170")
    add("all_56_no_amount_rows_are_explicitly_closed", len(no_amount_rows) == 56 and all(row["amount_status"] == "not_required" and row["final_free_agent_amount_2026_27"] == "" for row in no_amount_rows), f"closed={len(no_amount_rows)}/56")
    add("calculation_conflicts_are_zero", not conflicts, f"conflicts={len(conflicts)}")
    add("amounts_not_applied_to_simulation", all(not row["amount_applied_to_simulation"] and not row["cap_hold_applied"] and not row["state_mutation_applied"] for row in completed_rows), "Read-only evidence completion.")

    simulation_digest_after = object_digest(checkpoint.simulation_state)
    checkpoint_hash_after = sha256_file(checkpoint_path)
    add("loaded_simulation_state_unchanged", simulation_digest_after == simulation_digest_before, simulation_digest_after)
    add("checkpoint_file_unchanged", checkpoint_hash_after == checkpoint_hash_before == EXPECTED_CHECKPOINT_SHA256, checkpoint_hash_after)

    failed = [row["check_id"] for row in checks if row["status"] == "FAIL"]
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    export_id = f"fa_full_market_free_agent_amount_completion_v1_{SEASON_LABEL}_{timestamp}"
    output_dir = root / "outputs" / "audits"
    output_dir.mkdir(parents=True, exist_ok=True)
    audit_zip = output_dir / f"{export_id}.zip"
    summary = {
        "version": VERSION,
        "market_count": len(completed_rows),
        "exact_rfa_amount_count": len(exact_rfa_rows),
        "salary_dependent_non_rfa_amount_count": len(salary_dependent_rows),
        "not_required_amount_count": len(no_amount_rows),
        "amount_ready_count": len(amount_rows),
        "non_rfa_rights_counts": dict(sorted(rights_counts.items())),
        "formula_family_counts": dict(sorted(formula_counts.items())),
        "minimum_branch_count": len(minimum_rows),
        "maximum_ceiling_count": len(max_rows),
        "rookie_option_exception_count": len(option_exception_rows),
        "estimated_average_player_salary_2025_26": ESTIMATED_AVERAGE_PLAYER_SALARY_2025_26,
        "salary_cap_2026_27": SALARY_CAP_2026_27,
        "non_rfa_amount_total": non_rfa_total,
        "exact_rfa_amount_total": rfa_total,
        "full_market_amount_total": full_total,
        "calculation_conflict_count": len(conflicts),
        "amounts_applied": 0,
        "cap_holds_applied": 0,
        "rights_renouncements_applied": 0,
        "state_mutation_performed": False,
        "checkpoint_write_performed": False,
        "source_full_market_registry_audit": registry_zip.name,
        "source_exact_rfa_audit": rfa_zip.name,
        "source_service_audit": service_zip.name,
        "source_legacy_service_fallback_audit": legacy_rights_zip.name,
        "source_contract_option_lifecycle_audit": lifecycle_zip.name,
        "cba_authority_url": CBA_URL,
        "nba_2025_26_cap_url": NBA_2025_26_CAP_URL,
        "nba_2026_27_cap_url": NBA_2026_27_CAP_URL,
        "estimated_average_salary_source_url": EAPS_SOURCE_URL,
        "passed": not failed,
        "failed_checks": failed,
        "next_slice": (
            "Join these 170 exact amounts to the 30-team guaranteed-salary and roster-charge "
            "readiness layer, then preview team-by-team retained-versus-renounced cap holds."
        ),
    }

    with tempfile.TemporaryDirectory(prefix="fa_full_market_free_agent_amount_completion_") as temporary_directory:
        export = Path(temporary_directory) / export_id
        export.mkdir(parents=True)
        write_csv(export / "full_market_free_agent_amounts_complete_226.csv", completed_rows)
        write_csv(export / "full_market_exact_amounts_ready_170.csv", amount_rows)
        write_csv(export / "full_market_exact_rfa_amounts_64.csv", exact_rfa_rows)
        write_csv(export / "full_market_non_rfa_amounts_106.csv", salary_dependent_rows)
        write_csv(export / "full_market_no_amount_required_56.csv", no_amount_rows)
        write_csv(export / "full_market_minimum_branch_60.csv", minimum_rows)
        write_csv(export / "full_market_rookie_option_exceptions_2.csv", option_exception_rows)
        write_csv(export / "full_market_maximum_ceiling_rows.csv", max_rows)
        write_csv(export / "full_market_free_agent_amount_conflicts.csv", conflicts)
        write_csv(export / "full_market_free_agent_amount_checks.csv", checks)
        (export / "full_market_free_agent_amount_summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
        (export / "README.txt").write_text(
            """2026 FULL-MARKET FREE AGENT AMOUNT COMPLETION V1
================================================

Purpose
-------
Compute the exact 2026-27 Free Agent Amount for every amount-bearing player in
the validated 226-player market, while preserving all results as read-only
evidence.

Result
------
- 64/64 exact RFA amounts preserved
- 106/106 salary-dependent non-RFA amounts computed
- 56/56 not-applicable rows explicitly closed
- 170/170 amount-bearing rows exact and ready
- zero rights, cap-hold, Team Salary, roster, or checkpoint mutation

The veteran calculations implement CBA Article VII Section 4(d), the applicable
minimum/non-reimbursed minimum branch, the applicable Maximum Player Salary,
and the two verified declined rookie-scale fourth-year option amounts.
""",
            encoding="utf-8",
        )
        with zipfile.ZipFile(audit_zip, "w", zipfile.ZIP_DEFLATED) as archive:
            for item in sorted(export.iterdir()):
                archive.write(item, arcname=f"{export_id}/{item.name}")

    if failed:
        print("")
        print(f"Diagnostic audit ZIP: {audit_zip}")
        raise RuntimeError("Full-Market Free Agent Amount Completion V1 failed: " + ", ".join(failed))

    print("")
    print("=" * 132)
    print("2026 FULL-MARKET FREE AGENT AMOUNT COMPLETION V1 PASSED")
    print("=" * 132)
    print("Exact RFA amounts:              64/64")
    print("Non-RFA veteran amounts:       106/106")
    print("Not-required closures:           56/56")
    print("Full-market exact readiness:    226/226")
    print(f"Amount-bearing total:     ${full_total:,.0f}")
    print("Amounts applied:                  0")
    print("Cap holds applied:                0")
    print("Checkpoint write:        NOT PERFORMED")
    print(f"Audit ZIP: {audit_zip}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
