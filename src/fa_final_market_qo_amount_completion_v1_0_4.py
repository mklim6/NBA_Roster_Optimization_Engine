from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import tempfile
import unicodedata
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

VERSION = "fa-final-market-qo-amount-completion-v1.0.4-2026-08-14"
SEASON_LABEL = "2026-27"
EXPECTED_CHECKPOINT_SHA256 = (
    "19f2fee601f5765bde4f5fabea34f20dc9b8ddc8dd5069186502dff08fc0cf9f"
)
EXPECTED_ELIGIBLE = 64
EXPECTED_MAX_LAST_MILE = 6

# 2026-27 full-season minimum salaries.
# Source: SalarySwish 2026-27 Minimum Salary & Two-Way Calculator.
MINIMUM_SALARY_BY_YOS = {
    2: 2_449_421,
    3: 2_537_526,
}

# These are the only six names V1.0.3 surfaced to its last-mile fallback.
# The registry is branch-specific:
# - prior_salary = 2025-26 Regular Salary under the controlling pre-split contract
# - starter criteria are checked using 2025-26 plus 2024-25 regular-season
#   GS/MIN and are all definitively unmet
# - QO = max(round(135% prior salary), 2026-27 minimum salary + 200,000)
#
# SalarySwish is used only as financial/stat evidence. NBA/NBPA CBA remains
# the rule authority.
FORMULA_REGISTRY = {
    "andre jackson jr": {
        "canonical_name": "Andre Jackson Jr.",
        "prior_salary_2025_26": 2_221_677,
        "years_of_service_for_minimum": 3,
        "gs_2025_26": 1,
        "min_2025_26": 408,
        "gs_2024_25": 43,
        "min_2024_25": 980,
        "contract_source_url": "https://www.salaryswish.com/players/andre-jackson-jr",
    },
    "jonathan mogbo": {
        "canonical_name": "Jonathan Mogbo",
        "prior_salary_2025_26": 1_955_377,
        "years_of_service_for_minimum": 2,
        "gs_2025_26": 0,
        "min_2025_26": 249,
        "gs_2024_25": 18,
        "min_2024_25": 1286,
        "contract_source_url": "https://www.salaryswish.com/players/jonathan-mogbo",
    },
    "julian phillips": {
        "canonical_name": "Julian Phillips",
        "prior_salary_2025_26": 2_221_677,
        "years_of_service_for_minimum": 3,
        "gs_2025_26": 2,
        "min_2025_26": 428,
        "gs_2024_25": 5,
        "min_2024_25": 1123,
        "contract_source_url": "https://www.salaryswish.com/players/julian-phillips",
    },
    "mouhamadou gueye": {
        "canonical_name": "Mouhamadou Gueye",
        "prior_salary_2025_26": 47_092,
        "years_of_service_for_minimum": 2,
        "gs_2025_26": 0,
        "min_2025_26": 45,
        "gs_2024_25": 0,
        "min_2024_25": 0,
        "contract_source_url": "https://www.salaryswish.com/players/mouhamadou-gueye",
    },
    "tolu smith": {
        "canonical_name": "Tolu Smith",
        "prior_salary_2025_26": 70_638,
        "years_of_service_for_minimum": 2,
        "gs_2025_26": 0,
        "min_2025_26": 137,
        "gs_2024_25": 0,
        "min_2024_25": 22,
        "contract_source_url": "https://www.salaryswish.com/players/tolu-smith-iii",
    },
    "tolu smith iii": {
        "canonical_name": "Tolu Smith",
        "prior_salary_2025_26": 70_638,
        "years_of_service_for_minimum": 2,
        "gs_2025_26": 0,
        "min_2025_26": 137,
        "gs_2024_25": 0,
        "min_2024_25": 22,
        "contract_source_url": "https://www.salaryswish.com/players/tolu-smith-iii",
    },
    "trayce jackson davis": {
        "canonical_name": "Trayce Jackson-Davis",
        "prior_salary_2025_26": 2_221_677,
        "years_of_service_for_minimum": 3,
        "gs_2025_26": 1,
        "min_2025_26": 496,
        "gs_2024_25": 37,
        "min_2024_25": 967,
        "contract_source_url": "https://www.salaryswish.com/players/trayce-jackson-davis",
    },
}

MINIMUM_SOURCE_URL = "https://www.salaryswish.com/minimum-salary-calculator"
QO_RULE_SOURCE_URL = "https://www.salaryswish.com/qualifying-offer-calculator"
NBA_RULE_SOURCE_URL = "https://www.nba.com/news/free-agency-explained"


def clean(value: Any) -> str:
    return str(value or "").strip()


def pid(value: Any) -> str:
    text = clean(value)
    if text.endswith(".0") and text[:-2].isdigit():
        return text[:-2]
    return text


def normalize_name(value: Any) -> str:
    text = unicodedata.normalize("NFKD", clean(value))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower().replace("’", "'").replace("‘", "'")
    text = text.replace("-", " ")
    text = "".join(ch if ch.isalnum() or ch.isspace() else " " for ch in text)
    return " ".join(text.split())


def boolish(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    text = clean(value).lower()
    if text in {"", "0", "false", "f", "no", "n", "none", "null"}:
        return False
    if text in {"1", "true", "t", "yes", "y"}:
        return True
    raise ValueError(f"Unrecognized boolean-like value: {value!r}")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def find_latest(root: Path, pattern: str) -> Path:
    candidates = [p for p in root.rglob(pattern) if p.is_file()]
    if not candidates:
        raise RuntimeError(f"Could not locate required upstream audit: {pattern}")
    return max(candidates, key=lambda p: p.stat().st_mtime)


def read_csv_member(
    archive: zipfile.ZipFile,
    suffix: str,
    *,
    required: bool = True,
) -> list[dict[str, str]]:
    member = next((n for n in archive.namelist() if n.endswith(suffix)), "")
    if not member:
        if required:
            raise RuntimeError(f"ZIP missing member: {suffix}")
        return []
    text = archive.read(member).decode("utf-8-sig")
    return list(csv.DictReader(io.StringIO(text))) if text.strip() else []


def read_json_member(
    archive: zipfile.ZipFile,
    suffix: str,
    *,
    required: bool = True,
) -> dict[str, Any]:
    member = next((n for n in archive.namelist() if n.endswith(suffix)), "")
    if not member:
        if required:
            raise RuntimeError(f"ZIP missing member: {suffix}")
        return {}
    return json.loads(archive.read(member).decode("utf-8-sig"))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return

    fields: list[str] = []
    seen = set()
    for row in rows:
        for key in row:
            if key not in seen:
                seen.add(key)
                fields.append(key)

    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def starter_criteria_unmet(registry: dict[str, Any]) -> tuple[bool, dict[str, float]]:
    gs_current = int(registry["gs_2025_26"])
    min_current = int(registry["min_2025_26"])
    gs_prior = int(registry["gs_2024_25"])
    min_prior = int(registry["min_2024_25"])

    avg_gs = (gs_current + gs_prior) / 2.0
    avg_min = (min_current + min_prior) / 2.0

    met = (
        gs_current >= 41
        or avg_gs >= 41.0
        or min_current >= 2000
        or avg_min >= 2000.0
    )
    return (not met), {
        "gs_2025_26": gs_current,
        "min_2025_26": min_current,
        "gs_2024_25": gs_prior,
        "min_2024_25": min_prior,
        "two_year_avg_gs": avg_gs,
        "two_year_avg_min": avg_min,
    }


def round_half_up_positive(value: float) -> int:
    return int(math.floor(value + 0.5))


def formula_resolution(
    *,
    player_id: str,
    player_name: str,
    registry: dict[str, Any],
) -> dict[str, Any]:
    yos = int(registry["years_of_service_for_minimum"])
    if yos not in MINIMUM_SALARY_BY_YOS:
        raise RuntimeError(
            f"No 2026-27 minimum salary registered for {yos} YOS."
        )

    unmet, stats = starter_criteria_unmet(registry)
    if not unmet:
        raise RuntimeError(
            f"Starter Criteria unexpectedly met for {player_name}; "
            "last-mile standard formula must fail closed."
        )

    prior_salary = int(registry["prior_salary_2025_26"])
    minimum_salary = int(MINIMUM_SALARY_BY_YOS[yos])

    previous_salary_method_raw = prior_salary * 1.35
    previous_salary_method = round_half_up_positive(previous_salary_method_raw)
    minimum_salary_method = minimum_salary + 200_000
    exact_qo = max(previous_salary_method, minimum_salary_method)
    winning_method = (
        "135_percent_previous_salary"
        if previous_salary_method >= minimum_salary_method
        else "minimum_salary_plus_200000"
    )

    return {
        "player_id": player_id,
        "player_name": player_name,
        "canonical_name": registry["canonical_name"],
        "formula_family": "standard_veteran_qo",
        "starter_criteria": "Unmet",
        **stats,
        "prior_salary_2025_26": prior_salary,
        "years_of_service_for_2026_27_minimum": yos,
        "minimum_salary_2026_27": minimum_salary,
        "previous_salary_method_raw": previous_salary_method_raw,
        "previous_salary_method_rounded": previous_salary_method,
        "minimum_salary_method": minimum_salary_method,
        "winning_method": winning_method,
        "exact_qo_base_compensation": exact_qo,
        "qo_guaranteed_component": "",
        "source_type": "branch_specific_cba_formula_completion",
        "contract_stats_source_url": registry["contract_source_url"],
        "minimum_salary_source_url": MINIMUM_SOURCE_URL,
        "qo_formula_source_url": QO_RULE_SOURCE_URL,
        "nba_rule_source_url": NBA_RULE_SOURCE_URL,
        "real_world_option_outcome_used_for_formula": False,
        "real_world_qo_issuance_imported": False,
        "qualifying_offer_issued": False,
        "rfa_status_applied": False,
        "state_mutation_applied": False,
    }


def main() -> int:
    root = Path.cwd().resolve()

    eligibility_zip = find_latest(
        root,
        "fa_final_market_rfa_qo_eligibility_readiness_v1_2026-27_*.zip",
    )
    v103_zip = find_latest(
        root,
        "fa_final_market_qo_amount_completion_v1_0_3_2026-27_*.zip",
    )

    with zipfile.ZipFile(eligibility_zip) as archive:
        eligibility_summary = read_json_member(
            archive,
            "rfa_qo_rebuild_summary.json",
        )
        eligible_rows = read_csv_member(
            archive,
            "rfa_qo_structurally_eligible.csv",
        )

    with zipfile.ZipFile(v103_zip) as archive:
        v103_summary = read_json_member(
            archive,
            "qo_amount_completion_summary.json",
        )
        partial_completed = read_csv_member(
            archive,
            "qo_exact_amounts_completed_64.csv",
            required=False,
        )
        unresolved = read_csv_member(
            archive,
            "qo_v1_0_3_fallback_unresolved.csv",
            required=False,
        )
        fallback_resolved = read_csv_member(
            archive,
            "qo_v1_0_3_fallback_resolved.csv",
            required=False,
        )

    if len(eligible_rows) != EXPECTED_ELIGIBLE:
        raise RuntimeError(
            f"Expected {EXPECTED_ELIGIBLE} structurally eligible rows, "
            f"got {len(eligible_rows)}."
        )

    if not unresolved:
        raise RuntimeError(
            "V1.0.3 contains no unresolved rows. Do not run V1.0.4 on an "
            "already-complete amount table."
        )

    if len(unresolved) > EXPECTED_MAX_LAST_MILE:
        raise RuntimeError(
            f"Expected at most {EXPECTED_MAX_LAST_MILE} V1.0.3 last-mile rows, "
            f"got {len(unresolved)}."
        )

    import simulation_franchise_checkpoint_v1 as checkpoint_module

    checkpoint_path = Path(checkpoint_module.DEFAULT_CHECKPOINT_PATH)
    checkpoint_hash_before = sha256_file(checkpoint_path)

    if checkpoint_hash_before != EXPECTED_CHECKPOINT_SHA256:
        raise RuntimeError(
            "Canonical checkpoint changed before QO amount V1.0.4.\n"
            f"Expected: {EXPECTED_CHECKPOINT_SHA256}\n"
            f"Actual:   {checkpoint_hash_before}"
        )

    eligible_ids = {pid(row.get("player_id")) for row in eligible_rows}
    partial_by_id: dict[str, dict[str, str]] = {}
    duplicates = []

    for row in partial_completed:
        player_id = pid(row.get("player_id"))
        if not player_id:
            continue
        if player_id in partial_by_id:
            duplicates.append(player_id)
        partial_by_id[player_id] = row

    if duplicates:
        raise RuntimeError(
            "Duplicate player IDs in V1.0.3 partial completed table: "
            + repr(sorted(set(duplicates)))
        )

    unresolved_ids = {pid(row.get("player_id")) for row in unresolved}
    overlap = unresolved_ids & set(partial_by_id)
    if overlap:
        raise RuntimeError(
            "V1.0.3 unresolved players unexpectedly already exist in its "
            "partial completed table: " + repr(sorted(overlap))
        )

    formula_rows: list[dict[str, Any]] = []
    unsupported_rows: list[dict[str, Any]] = []

    print("=" * 128, flush=True)
    print("2026 FINAL-MARKET QO AMOUNT COMPLETION V1.0.4", flush=True)
    print("=" * 128, flush=True)
    print(f"Structurally eligible:              {len(eligible_rows)}", flush=True)
    print(f"V1.0.3 partial completed frozen:    {len(partial_completed)}", flush=True)
    print(f"V1.0.3 fallback-resolved rows:      {len(fallback_resolved)}", flush=True)
    print(f"Actual V1.0.3 unresolved rows:      {len(unresolved)}", flush=True)
    print("POLICY: resolve only the actual V1.0.3 unresolved subset.", flush=True)
    print("QO ISSUANCE: NOT PERFORMED", flush=True)
    print("", flush=True)

    for index, row in enumerate(
        sorted(unresolved, key=lambda r: clean(r.get("player_name")).lower()),
        start=1,
    ):
        player_id = pid(row.get("player_id"))
        player_name = clean(row.get("player_name"))
        key = normalize_name(player_name)
        registry = FORMULA_REGISTRY.get(key)

        print(
            f"[{index:02d}/{len(unresolved):02d}] {player_name}",
            flush=True,
        )

        if registry is None:
            unsupported_rows.append({
                "player_id": player_id,
                "player_name": player_name,
                "normalized_name": key,
                "status": "not_in_last_mile_formula_registry",
            })
            continue

        formula_rows.append(
            formula_resolution(
                player_id=player_id,
                player_name=player_name,
                registry=registry,
            )
        )

    final_rows: list[dict[str, Any]] = []

    for row in partial_completed:
        final_rows.append({
            **row,
            "v1_0_4_resolution_layer": "frozen_v1_0_3_partial",
        })

    for row in formula_rows:
        final_rows.append({
            "player_id": row["player_id"],
            "player_name": row["player_name"],
            "formula_family": row["formula_family"],
            "exact_qo_base_compensation": row[
                "exact_qo_base_compensation"
            ],
            "qo_guaranteed_component": row[
                "qo_guaranteed_component"
            ],
            "selected_pre_split_signing_date": "",
            "source_type": row["source_type"],
            "source_url": row["contract_stats_source_url"],
            "real_world_qo_issuance_imported": False,
            "qualifying_offer_issued": False,
            "rfa_status_applied": False,
            "state_mutation_applied": False,
            "v1_0_4_resolution_layer": "last_mile_cba_formula",
        })

    final_ids = {pid(row.get("player_id")) for row in final_rows}

    checks: list[dict[str, Any]] = []

    def check(
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
        print(f"  {check_id}: {'PASS' if passed else 'FAIL'}", flush=True)

    print("", flush=True)
    print("Running strict V1.0.4 checks...", flush=True)

    check(
        "upstream_eligibility_rebuild_passed",
        bool(eligibility_summary.get("passed")),
        "64-player structural eligibility universe remains upstream source.",
    )
    check(
        "v1_0_3_diagnostic_loaded",
        bool(v103_summary),
        (
            f"partial_completed={len(partial_completed)} "
            f"unresolved={len(unresolved)}"
        ),
    )
    check(
        "v1_0_3_unresolved_count_is_between_1_and_6",
        1 <= len(unresolved) <= EXPECTED_MAX_LAST_MILE,
        f"unresolved={len(unresolved)}",
    )
    check(
        "every_unresolved_name_is_supported_by_formula_registry",
        not unsupported_rows
        and len(formula_rows) == len(unresolved),
        (
            f"resolved={len(formula_rows)} "
            f"unsupported={len(unsupported_rows)}"
        ),
    )
    check(
        "all_last_mile_starter_criteria_are_unmet",
        all(row["starter_criteria"] == "Unmet" for row in formula_rows),
        "No special starter-criteria QO branch is used.",
    )
    check(
        "all_last_mile_qo_amounts_positive",
        all(
            float(row["exact_qo_base_compensation"]) > 0
            for row in formula_rows
        ),
        "All branch-specific formula amounts are positive.",
    )
    check(
        "all_last_mile_minimum_salaries_are_2026_27_exact",
        all(
            int(row["minimum_salary_2026_27"])
            == MINIMUM_SALARY_BY_YOS[
                int(row["years_of_service_for_2026_27_minimum"])
            ]
            for row in formula_rows
        ),
        "Only exact 2026-27 minimum salary scale values are used.",
    )
    check(
        "exact_64_completed_qo_amounts",
        len(final_rows) == EXPECTED_ELIGIBLE
        and final_ids == eligible_ids,
        f"rows={len(final_rows)} unique={len(final_ids)}",
    )
    check(
        "no_real_world_qo_issuance_imported",
        all(
            not boolish(row.get("real_world_qo_issuance_imported"))
            and not boolish(row.get("qualifying_offer_issued"))
            and not boolish(row.get("rfa_status_applied"))
            for row in final_rows
        ),
        "Amount completion only.",
    )
    check(
        "checkpoint_file_unchanged",
        sha256_file(checkpoint_path)
        == checkpoint_hash_before
        == EXPECTED_CHECKPOINT_SHA256,
        sha256_file(checkpoint_path),
    )

    failed = [
        row["check_id"]
        for row in checks
        if row["severity"] == "strict"
        and row["status"] == "FAIL"
    ]

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    export_id = (
        f"fa_final_market_qo_amount_completion_v1_0_4_"
        f"{SEASON_LABEL}_{stamp}"
    )
    out_dir = root / "outputs" / "audits"
    out_dir.mkdir(parents=True, exist_ok=True)
    audit_zip = out_dir / f"{export_id}.zip"

    with tempfile.TemporaryDirectory(prefix="fa_qo_v104_") as tmpdir:
        export = Path(tmpdir) / export_id
        export.mkdir(parents=True)

        write_csv(
            export / "qo_v1_0_3_actual_unresolved_input.csv",
            unresolved,
        )
        write_csv(
            export / "qo_last_mile_formula_resolutions.csv",
            formula_rows,
        )
        write_csv(
            export / "qo_last_mile_unsupported.csv",
            unsupported_rows,
        )
        write_csv(
            export / "qo_exact_amounts_completed_64.csv",
            sorted(
                final_rows,
                key=lambda row: clean(row.get("player_name")).lower(),
            ),
        )
        write_csv(
            export / "qo_amount_completion_checks.csv",
            checks,
        )

        summary = {
            "version": VERSION,
            "structurally_eligible_count": len(eligible_rows),
            "v1_0_3_partial_frozen_count": len(partial_completed),
            "v1_0_3_actual_unresolved_count": len(unresolved),
            "last_mile_formula_resolved_count": len(formula_rows),
            "last_mile_unsupported_count": len(unsupported_rows),
            "completed_exact_qo_count": len(final_rows),
            "real_world_qo_issuance_imported": False,
            "qualifying_offers_issued": 0,
            "rfa_statuses_applied": 0,
            "state_mutation_performed": False,
            "checkpoint_write_performed": False,
            "passed": not failed,
            "failed_checks": failed,
            "next_slice": (
                "If 64/64 exact, stop QO amount research and build the "
                "simulator-owned QO issuance decision board."
            ),
        }

        (export / "qo_amount_completion_summary.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True),
            encoding="utf-8",
        )

        (export / "README.txt").write_text(
            """2026 FINAL-MARKET QO AMOUNT COMPLETION V1.0.4
================================================

This is the final last-mile QO amount pass.

It DOES NOT parse all 41 players again.

It freezes every QO already present in the V1.0.3 partial completed table and
reads the exact unresolved subset from:
    qo_v1_0_3_fallback_unresolved.csv

Only that subset is resolved.

Why these final cases are formula-driven:
They are simulator-specific Team Option declines. Current real-world pages may
show a QO for a later free-agency year because the real team exercised the
option, so copying the current displayed QO would be temporally wrong.

For each supported unresolved player:
- Starter Criteria is definitively Unmet from 2025-26 / 2024-25 GS and MIN.
- Standard-veteran QO rule:
    greater of
    1) 135% of 2025-26 prior salary
    2) exact 2026-27 applicable minimum salary + $200,000

2026-27 minimum salaries used:
- 2 YOS: $2,449,421
- 3 YOS: $2,537,526

No real-world option result is used to calculate the branch QO.
No real-world QO issuance is imported.
No state mutation.
READ ONLY.
""",
            encoding="utf-8",
        )

        with zipfile.ZipFile(audit_zip, "w", zipfile.ZIP_DEFLATED) as archive:
            for item in sorted(export.iterdir()):
                archive.write(item, arcname=f"{export_id}/{item.name}")

    if failed:
        print("", flush=True)
        print(f"Diagnostic audit ZIP: {audit_zip}", flush=True)
        raise RuntimeError(
            "Final-Market QO Amount Completion V1.0.4 failed: "
            + ", ".join(failed)
        )

    print("", flush=True)
    print("=" * 128, flush=True)
    print("2026 FINAL-MARKET QO AMOUNT COMPLETION V1.0.4 PASSED", flush=True)
    print("=" * 128, flush=True)
    print("Structurally eligible:             64", flush=True)
    print(f"V1.0.3 completed frozen:           {len(partial_completed)}", flush=True)
    print(f"Last-mile formula rows:             {len(formula_rows)}", flush=True)
    print("Unresolved remaining:               0", flush=True)
    print("Exact QO amounts completed:        64/64", flush=True)
    print("Real-world QO issuance used:        NO", flush=True)
    print("Qualifying offers issued:            0", flush=True)
    print("RFA statuses applied:                0", flush=True)
    print("Checkpoint write:        NOT PERFORMED", flush=True)
    print(f"Audit ZIP: {audit_zip}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
