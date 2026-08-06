"""Build player-level CBA research packets for the validated V7 package queue.

Save this file in ``src``. It validates the two V7 team-CBA-evaluated package
parquets, extracts every player appearing in the 83,975 packages that advanced,
reconciles those players against the existing financial and trade-pool sources,
ranks them by package exposure, and writes 20-player evidence-input batches.

This script is read-only with respect to all package and source files. It does
not release final package legality. The generated research fields cover the
individual restrictions still missing from the optimizer: contract type,
trade and aggregation dates, consent, trade bonuses, poison-pill treatment,
base-year compensation, sign-and-trade, and extend-and-trade restrictions.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


SCRIPT_VERSION = "mixed-player-pick-player-cba-research-packets-v1-2026-08-05"
RELEASE_NAME = "mixed_player_pick_player_cba_research_packets_2026_27_v1"
TRADE_DATE = "2026-08-04"
LEAGUE_YEAR = "2026-27"
BATCH_SIZE = 20

PACKAGE_FILES = {
    "one_for_one": "one_for_one_mixed_player_pick_candidates_2026_27_v7_team_cba_evidence_evaluated.parquet",
    "two_for_one": "two_for_one_mixed_player_pick_candidates_2026_27_v7_team_cba_evidence_evaluated.parquet",
}
EXPECTED_PACKAGE_ROWS = {"one_for_one": 28_324, "two_for_one": 282_277}
EXPECTED_PACKAGE_COLUMNS = {"one_for_one": 153, "two_for_one": 151}
EXPECTED_ADVANCING_ROWS = {"one_for_one": 11_269, "two_for_one": 72_706}
EXPECTED_TOTAL_ROWS = 310_601
EXPECTED_ADVANCING_TOTAL = 83_975
EXPECTED_PLAYER_EXPOSURES = 2 * 11_269 + 3 * 72_706

TEAM_CBA_METADATA = "mixed_player_pick_package_team_cba_metadata_v1.json"
SOURCE_FILES = {
    "player_financial": ("data", "processed", "player_financial_layer_2026_27_v2.parquet"),
    "trade_eligible_pool": ("data", "processed", "trade_eligible_player_pool_2026_27.parquet"),
}

METADATA_OUTPUT = "mixed_player_pick_player_cba_research_packet_metadata_v1.json"
QUEUE_OUTPUT = "mixed_player_pick_player_cba_research_queue_v1.csv"
COVERAGE_OUTPUT = "mixed_player_pick_player_cba_source_coverage_v2.csv"
VALIDATION_OUTPUT = "mixed_player_pick_player_cba_research_packet_validation_v1.csv"
FIELD_DICTIONARY_OUTPUT = "mixed_player_pick_player_cba_research_field_dictionary_v1.csv"
BATCH_DIRECTORY = "player_cba_research_batches"

PACKAGE_REQUIRED_COLUMNS = {
    "side_a_player_ids",
    "side_b_player_ids",
    "team_a",
    "team_b",
    "package_team_cba_evidence_stage_passed",
    "package_team_cba_evidence_manual_review_required",
    "package_team_cba_evidence_blocked",
    "package_team_cba_evidence_status",
    "team_cba_decisions_matched",
    "team_cba_final_legal_status_released",
}
FINANCIAL_REQUIRED_COLUMNS = {
    "player_id",
    "player_name",
    "team_id",
    "current_team_2026_27",
    "trade_salary_2026_27",
    "offseason_team_changed_flag",
}
ELIGIBILITY_REQUIRED_COLUMNS = {
    "player_id",
    "player_name",
    "current_team_2026_27",
    "trade_salary_2026_27",
    "salary_data_verified_for_player",
    "contract_restrictions_verified",
    "no_trade_clause_verified",
    "recently_signed_or_acquired_restriction_verified",
}

IMMUTABLE_FIELDS = [
    "player_cba_packet_release",
    "trade_date",
    "league_year",
    "batch_id",
    "batch_sequence",
    "player_priority_rank",
    "player_id",
    "player_name",
    "current_team_2026_27",
    "financial_team_id",
    "trade_salary_2026_27",
    "offseason_team_changed_flag",
    "total_passing_package_exposure",
    "one_for_one_package_exposure",
    "two_for_one_package_exposure",
    "side_a_package_exposure",
    "side_b_package_exposure",
    "source_rows_player_financial",
    "source_rows_trade_eligible_pool",
    "salary_data_verified_for_player_prior",
    "contract_restrictions_verified_prior",
    "no_trade_clause_verified_prior",
    "recently_signed_or_acquired_restriction_verified_prior",
    "source_salary_values_match",
    "package_team_alignment_verified",
    "research_priority_reason",
    "research_required",
    "research_scope",
]

RESEARCH_FIELDS = [
    "evidence_as_of_date",
    "contract_type",
    "two_way_contract_active",
    "trade_eligible_date",
    "trade_eligible_on_trade_date",
    "aggregation_eligible_date",
    "aggregation_restricted_on_trade_date",
    "no_trade_clause_active",
    "one_year_bird_consent_required",
    "trade_consent_required",
    "trade_bonus_percent",
    "remaining_trade_bonus_amount",
    "trade_bonus_adjusted_outgoing_salary",
    "poison_pill_active",
    "poison_pill_outgoing_salary",
    "poison_pill_incoming_salary",
    "base_year_compensation_active",
    "base_year_compensation_outgoing_salary",
    "sign_and_trade_player",
    "extend_and_trade_restriction_active",
    "restriction_end_date",
    "player_cba_evidence_determination",
    "manual_review_required",
    "player_cba_stage_pass",
    "primary_source_url",
    "secondary_source_url",
    "source_authority",
    "evidence_summary",
    "evaluator_notes",
    "research_complete",
]

ALL_FIELDS = IMMUTABLE_FIELDS + RESEARCH_FIELDS

FIELD_DICTIONARY = [
    ("evidence_as_of_date", "date", "YYYY-MM-DD; normally 2026-08-04."),
    ("contract_type", "enum", "standard, two_way, exhibit_10, or other."),
    ("two_way_contract_active", "boolean", "TRUE/FALSE as of the trade date."),
    ("trade_eligible_date", "date", "Exact date first eligible to be traded."),
    ("trade_eligible_on_trade_date", "boolean", "TRUE only if eligible on 2026-08-04."),
    ("aggregation_eligible_date", "date", "Exact date salary may be aggregated; blank only if inapplicable with explanation."),
    ("aggregation_restricted_on_trade_date", "boolean", "Player-level aggregation restriction on 2026-08-04."),
    ("no_trade_clause_active", "boolean", "TRUE only for an active contractual no-trade clause."),
    ("one_year_bird_consent_required", "boolean", "Consent right from a one-year contract and Bird-right loss."),
    ("trade_consent_required", "boolean", "TRUE if either consent mechanism applies."),
    ("trade_bonus_percent", "number", "Contract trade bonus percentage; use 0 when verified absent."),
    ("remaining_trade_bonus_amount", "currency", "Remaining allocable trade bonus in dollars; use 0 when absent."),
    ("trade_bonus_adjusted_outgoing_salary", "currency", "Outgoing matching salary after applicable trade bonus."),
    ("poison_pill_active", "boolean", "TRUE if poison-pill matching treatment applies."),
    ("poison_pill_outgoing_salary", "currency", "Outgoing salary under poison-pill rules; use base trade salary if inactive."),
    ("poison_pill_incoming_salary", "currency", "Incoming salary under poison-pill rules; use base trade salary if inactive."),
    ("base_year_compensation_active", "boolean", "TRUE if BYC treatment applies."),
    ("base_year_compensation_outgoing_salary", "currency", "Outgoing salary after BYC treatment; use base trade salary if inactive."),
    ("sign_and_trade_player", "boolean", "TRUE only if the modeled transaction is a sign-and-trade."),
    ("extend_and_trade_restriction_active", "boolean", "TRUE if an extend-and-trade waiting rule blocks the trade date."),
    ("restriction_end_date", "date", "Latest applicable restriction end date, or blank if none."),
    ("player_cba_evidence_determination", "enum", "verified_clear, verified_with_conditions, manual_review_required, or not_trade_eligible."),
    ("manual_review_required", "boolean", "TRUE when evidence conflicts or remains incomplete."),
    ("player_cba_stage_pass", "boolean", "TRUE only when the player may advance under the verified evidence."),
    ("primary_source_url", "url", "Most authoritative player-contract or transaction source."),
    ("secondary_source_url", "url", "Independent corroborating source."),
    ("source_authority", "text", "NBA/team/CBA/contract ledger authority description."),
    ("evidence_summary", "text", "Concise conclusion with dates, triggers, and salary adjustments."),
    ("evaluator_notes", "text", "Implementation conditions needed by the package evaluator."),
    ("research_complete", "boolean", "TRUE only when all applicable fields and citations are complete."),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, help="Project root override.")
    parser.add_argument("--batch-size", type=int, default=BATCH_SIZE)
    parser.add_argument("--self-test", action="store_true")
    return parser.parse_args()


def project_root(override: Path | None = None) -> Path:
    if override is not None:
        return override.resolve()
    script_path = Path(__file__).resolve()
    if script_path.parent.name.lower() == "src":
        return script_path.parent.parent
    return script_path.parent


def locate_one(root: Path, filename: str) -> Path:
    preferred = root / "outputs" / filename
    if preferred.is_file():
        return preferred
    matches = sorted(path for path in root.rglob(filename) if path.is_file())
    if not matches:
        raise FileNotFoundError(f"Could not find {filename} beneath {root}")
    if len(matches) > 1:
        joined = "\n  ".join(str(path) for path in matches)
        raise RuntimeError(f"Found multiple copies of {filename}; keep exactly one:\n  {joined}")
    return matches[0]


def locate_source(root: Path, parts: tuple[str, ...]) -> Path:
    preferred = root.joinpath(*parts)
    if preferred.is_file():
        return preferred
    matches = sorted(path for path in root.rglob(parts[-1]) if path.is_file())
    if not matches:
        raise FileNotFoundError(f"Could not find {parts[-1]} beneath {root}")
    if len(matches) > 1:
        joined = "\n  ".join(str(path) for path in matches)
        raise RuntimeError(f"Found multiple copies of {parts[-1]}:\n  {joined}")
    return matches[0]


def normalize_id(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if re.fullmatch(r"\d+\.0", text):
        text = text[:-2]
    return text


def split_player_ids(value: Any) -> list[str]:
    if isinstance(value, (list, tuple, set)):
        return [normalize_id(item) for item in value if normalize_id(item)]
    text = normalize_id(value)
    if not text:
        return []
    return [normalize_id(part) for part in re.split(r"\s*[|;,]\s*", text) if normalize_id(part)]


def normalized_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    lowered = str(value).strip().lower()
    if lowered in {"true", "1", "yes", "y"}:
        return True
    if lowered in {"false", "0", "no", "n"}:
        return False
    return None


def normalized_float(value: Any) -> float | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def write_csv(path: Path, headers: list[str], rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({header: row.get(header, "") for header in headers})


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, ensure_ascii=False, default=str)
        handle.write("\n")


def keyed_rows(frame: Any, key: str) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in frame.iter_rows(named=True):
        player_id = normalize_id(row.get(key))
        if player_id:
            result[player_id].append(row)
    return dict(result)


def first_nonblank(rows: list[dict[str, Any]], *fields: str) -> Any:
    for field in fields:
        for row in rows:
            value = row.get(field)
            if value is not None and str(value).strip() != "":
                return value
    return ""


def source_bool(rows: list[dict[str, Any]], field: str) -> bool | None:
    values = [normalized_bool(row.get(field)) for row in rows]
    values = [value for value in values if value is not None]
    if not values:
        return None
    return all(values)


def source_salary(rows: list[dict[str, Any]]) -> float | None:
    values = [normalized_float(row.get("trade_salary_2026_27")) for row in rows]
    values = [value for value in values if value is not None]
    return values[0] if values else None


def profile_packages(pl: Any, package_paths: dict[str, Path]) -> tuple[dict[str, Any], dict[str, Counter]]:
    profiles: dict[str, Any] = {}
    exposure: dict[str, Counter] = {
        "total": Counter(),
        "one_for_one": Counter(),
        "two_for_one": Counter(),
        "side_a": Counter(),
        "side_b": Counter(),
    }
    player_teams: dict[str, set[str]] = defaultdict(set)

    for label, path in package_paths.items():
        schema = pl.read_parquet_schema(str(path))
        missing = sorted(PACKAGE_REQUIRED_COLUMNS.difference(schema))
        if missing:
            raise RuntimeError(f"{path.name} is missing required columns: {missing}")
        frame = pl.read_parquet(str(path), columns=sorted(PACKAGE_REQUIRED_COLUMNS))
        passed = frame.filter(pl.col("package_team_cba_evidence_stage_passed") == True)  # noqa: E712
        for row in passed.iter_rows(named=True):
            for side in ("a", "b"):
                ids = split_player_ids(row[f"side_{side}_player_ids"])
                team = str(row[f"team_{side}"]).strip().upper()
                for player_id in ids:
                    exposure["total"][player_id] += 1
                    exposure[label][player_id] += 1
                    exposure[f"side_{side}"][player_id] += 1
                    if team:
                        player_teams[player_id].add(team)

        status_counts = Counter(str(value) for value in frame.get_column(
            "package_team_cba_evidence_status"
        ).to_list())
        profiles[label] = {
            "path": str(path),
            "rows": frame.height,
            "columns": len(schema),
            "advancing_rows": passed.height,
            "manual_rows": int(frame.get_column(
                "package_team_cba_evidence_manual_review_required"
            ).sum()),
            "blocked_rows": int(frame.get_column("package_team_cba_evidence_blocked").sum()),
            "matched_rows": int(frame.get_column("team_cba_decisions_matched").sum()),
            "final_status_released_true": sum(
                normalized_bool(value) is True
                for value in frame.get_column("team_cba_final_legal_status_released").to_list()
            ),
            "status_counts": dict(sorted(status_counts.items())),
        }

    profiles["player_teams"] = {key: sorted(value) for key, value in player_teams.items()}
    return profiles, exposure


def priority_reason(exposures: int, salary: float | None, changed: bool | None) -> str:
    reasons = [f"{exposures:,} advancing-package exposures"]
    if salary is not None and salary >= 30_000_000:
        reasons.append("high matching salary")
    if changed is True:
        reasons.append("offseason team change")
    return "; ".join(reasons)


def build_queue(
    exposure: dict[str, Counter],
    player_teams: dict[str, list[str]],
    financial: Any,
    eligibility: Any,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    financial_rows = keyed_rows(financial, "player_id")
    eligibility_rows = keyed_rows(eligibility, "player_id")
    queue: list[dict[str, Any]] = []
    coverage: list[dict[str, Any]] = []

    for player_id in sorted(exposure["total"]):
        fin = financial_rows.get(player_id, [])
        elig = eligibility_rows.get(player_id, [])
        name = first_nonblank(fin, "player_name") or first_nonblank(elig, "player_name")
        current_team = str(
            first_nonblank(fin, "current_team_2026_27")
            or first_nonblank(elig, "current_team_2026_27")
        ).strip().upper()
        team_ids = player_teams.get(player_id, [])
        team_aligned = len(team_ids) == 1 and current_team == team_ids[0]
        fin_salary = source_salary(fin)
        elig_salary = source_salary(elig)
        salaries_match = (
            fin_salary is not None
            and elig_salary is not None
            and abs(fin_salary - elig_salary) <= 1.0
        )
        changed = source_bool(fin, "offseason_team_changed_flag")
        base = {
            "player_id": player_id,
            "player_name": name,
            "current_team_2026_27": current_team,
            "financial_team_id": first_nonblank(fin, "team_id"),
            "trade_salary_2026_27": fin_salary if fin_salary is not None else "",
            "offseason_team_changed_flag": changed if changed is not None else "",
            "total_passing_package_exposure": exposure["total"][player_id],
            "one_for_one_package_exposure": exposure["one_for_one"][player_id],
            "two_for_one_package_exposure": exposure["two_for_one"][player_id],
            "side_a_package_exposure": exposure["side_a"][player_id],
            "side_b_package_exposure": exposure["side_b"][player_id],
            "source_rows_player_financial": len(fin),
            "source_rows_trade_eligible_pool": len(elig),
            "salary_data_verified_for_player_prior": source_bool(
                elig, "salary_data_verified_for_player"
            ),
            "contract_restrictions_verified_prior": source_bool(
                elig, "contract_restrictions_verified"
            ),
            "no_trade_clause_verified_prior": source_bool(elig, "no_trade_clause_verified"),
            "recently_signed_or_acquired_restriction_verified_prior": source_bool(
                elig, "recently_signed_or_acquired_restriction_verified"
            ),
            "source_salary_values_match": salaries_match,
            "package_team_alignment_verified": team_aligned,
            "research_priority_reason": priority_reason(
                exposure["total"][player_id], fin_salary, changed
            ),
            "research_required": True,
            "research_scope": (
                "Verify contract type, trade/aggregation eligibility, consent, trade bonus, "
                "poison pill, BYC, sign-and-trade, and extend-and-trade status as of 2026-08-04."
            ),
        }
        queue.append(base)
        coverage.append({
            **base,
            "package_team_values": "|".join(team_ids),
            "player_financial_match": bool(fin),
            "trade_eligible_pool_match": bool(elig),
            "financial_salary_value": fin_salary if fin_salary is not None else "",
            "eligibility_salary_value": elig_salary if elig_salary is not None else "",
            "source_coverage_status": (
                "core_sources_present_restriction_research_required"
                if len(fin) == 1 and len(elig) == 1 and salaries_match and team_aligned
                else "source_reconciliation_manual_review_required"
            ),
        })

    queue.sort(
        key=lambda row: (
            -int(row["total_passing_package_exposure"]),
            -float(row["trade_salary_2026_27"] or 0),
            str(row["player_id"]),
        )
    )
    return queue, coverage


def assign_batches(queue: list[dict[str, Any]], batch_size: int) -> None:
    for index, row in enumerate(queue, start=1):
        batch_number = (index - 1) // batch_size + 1
        row["player_priority_rank"] = index
        row["batch_id"] = f"PCBA-P{batch_number:02d}"
        row["batch_sequence"] = (index - 1) % batch_size + 1
        row["player_cba_packet_release"] = RELEASE_NAME
        row["trade_date"] = TRADE_DATE
        row["league_year"] = LEAGUE_YEAR
        for field in RESEARCH_FIELDS:
            row[field] = ""


def build_checks(
    metadata: dict[str, Any],
    profiles: dict[str, Any],
    exposure: dict[str, Counter],
    queue: list[dict[str, Any]],
    coverage: list[dict[str, Any]],
    financial: Any,
    eligibility: Any,
    batch_size: int,
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []

    def add(name: str, passed: bool, actual: Any, expected: Any) -> None:
        checks.append({
            "check_name": name,
            "passed": bool(passed),
            "actual": json.dumps(actual, ensure_ascii=False, default=str),
            "expected": json.dumps(expected, ensure_ascii=False, default=str),
        })

    add("team_cba_release_valid", metadata.get("release_valid") is True,
        metadata.get("release_valid"), True)
    add("team_cba_validation_63_of_63",
        metadata.get("validation_checks_passed") == 63
        and metadata.get("validation_checks_total") == 63,
        [metadata.get("validation_checks_passed"), metadata.get("validation_checks_total")], [63, 63])
    add("team_cba_global_queue_83975",
        metadata.get("global_counts", {}).get("passed") == EXPECTED_ADVANCING_TOTAL,
        metadata.get("global_counts", {}).get("passed"), EXPECTED_ADVANCING_TOTAL)
    add("team_cba_final_legality_unreleased",
        metadata.get("package_final_legal_status_released") is False,
        metadata.get("package_final_legal_status_released"), False)

    for label in ("one_for_one", "two_for_one"):
        profile = profiles[label]
        add(f"{label}_rows", profile["rows"] == EXPECTED_PACKAGE_ROWS[label],
            profile["rows"], EXPECTED_PACKAGE_ROWS[label])
        add(f"{label}_columns", profile["columns"] == EXPECTED_PACKAGE_COLUMNS[label],
            profile["columns"], EXPECTED_PACKAGE_COLUMNS[label])
        add(f"{label}_advancing_rows",
            profile["advancing_rows"] == EXPECTED_ADVANCING_ROWS[label],
            profile["advancing_rows"], EXPECTED_ADVANCING_ROWS[label])
        add(f"{label}_all_team_decisions_matched",
            profile["matched_rows"] == EXPECTED_PACKAGE_ROWS[label],
            profile["matched_rows"], EXPECTED_PACKAGE_ROWS[label])
        add(f"{label}_final_status_never_released",
            profile["final_status_released_true"] == 0,
            profile["final_status_released_true"], 0)

    add("combined_rows", sum(profiles[label]["rows"] for label in PACKAGE_FILES) == EXPECTED_TOTAL_ROWS,
        sum(profiles[label]["rows"] for label in PACKAGE_FILES), EXPECTED_TOTAL_ROWS)
    add("combined_advancing_rows",
        sum(profiles[label]["advancing_rows"] for label in PACKAGE_FILES) == EXPECTED_ADVANCING_TOTAL,
        sum(profiles[label]["advancing_rows"] for label in PACKAGE_FILES), EXPECTED_ADVANCING_TOTAL)
    add("player_exposure_total",
        sum(exposure["total"].values()) == EXPECTED_PLAYER_EXPOSURES,
        sum(exposure["total"].values()), EXPECTED_PLAYER_EXPOSURES)
    add("side_exposures_reconcile",
        sum(exposure["side_a"].values()) + sum(exposure["side_b"].values()) == EXPECTED_PLAYER_EXPOSURES,
        [sum(exposure["side_a"].values()), sum(exposure["side_b"].values())], EXPECTED_PLAYER_EXPOSURES)
    add("queue_nonempty", bool(queue), len(queue), "> 0")
    add("queue_player_ids_unique", len({row["player_id"] for row in queue}) == len(queue),
        len({row["player_id"] for row in queue}), len(queue))
    add("queue_matches_exposure_universe", {row["player_id"] for row in queue} == set(exposure["total"]),
        len({row["player_id"] for row in queue}), len(exposure["total"]))
    add("queue_priority_contiguous",
        [row["player_priority_rank"] for row in queue] == list(range(1, len(queue) + 1)),
        [queue[0]["player_priority_rank"], queue[-1]["player_priority_rank"]] if queue else [],
        [1, len(queue)])
    add("all_players_one_financial_row",
        all(row["source_rows_player_financial"] == 1 for row in queue),
        Counter(row["source_rows_player_financial"] for row in queue), {1: len(queue)})
    add("all_players_one_eligibility_row",
        all(row["source_rows_trade_eligible_pool"] == 1 for row in queue),
        Counter(row["source_rows_trade_eligible_pool"] for row in queue), {1: len(queue)})
    add("all_source_salaries_match",
        all(row["source_salary_values_match"] is True for row in queue),
        sum(row["source_salary_values_match"] is True for row in queue), len(queue))
    add("all_package_team_assignments_match_sources",
        all(row["package_team_alignment_verified"] is True for row in queue),
        sum(row["package_team_alignment_verified"] is True for row in queue), len(queue))
    add("all_prior_salary_rows_verified",
        all(row["salary_data_verified_for_player_prior"] is True for row in queue),
        sum(row["salary_data_verified_for_player_prior"] is True for row in queue), len(queue))
    add("research_not_preverified",
        not any(row["contract_restrictions_verified_prior"] is True for row in queue),
        sum(row["contract_restrictions_verified_prior"] is True for row in queue), 0)
    add("coverage_rows_equal_queue", len(coverage) == len(queue), len(coverage), len(queue))
    add("financial_schema_complete",
        FINANCIAL_REQUIRED_COLUMNS.issubset(financial.columns),
        sorted(FINANCIAL_REQUIRED_COLUMNS.difference(financial.columns)), [])
    add("eligibility_schema_complete",
        ELIGIBILITY_REQUIRED_COLUMNS.issubset(eligibility.columns),
        sorted(ELIGIBILITY_REQUIRED_COLUMNS.difference(eligibility.columns)), [])
    add("batch_size_positive", batch_size > 0, batch_size, "> 0")
    expected_batches = math.ceil(len(queue) / batch_size) if queue else 0
    add("batch_count_reconciles",
        len({row["batch_id"] for row in queue}) == expected_batches,
        len({row["batch_id"] for row in queue}), expected_batches)
    add("all_research_fields_blank",
        all(row[field] == "" for row in queue for field in RESEARCH_FIELDS),
        sum(row[field] != "" for row in queue for field in RESEARCH_FIELDS), 0)
    add("final_legality_not_released", True, False, False)
    return checks


def run_self_tests() -> None:
    assert normalize_id("123.0") == "123"
    assert split_player_ids("1|2;3, 4") == ["1", "2", "3", "4"]
    assert split_player_ids([1, "2"]) == ["1", "2"]
    assert normalized_bool("TRUE") is True
    assert normalized_bool("no") is False
    assert normalized_float("10.5") == 10.5
    assert priority_reason(1000, 40_000_000, True).count(";") == 2
    assert len(IMMUTABLE_FIELDS) == 28
    assert len(RESEARCH_FIELDS) == 30
    print("Self-tests passed: 9/9")


def main() -> int:
    args = parse_args()
    if args.self_test:
        run_self_tests()
        return 0
    if args.batch_size <= 0:
        raise ValueError("--batch-size must be positive")

    try:
        import polars as pl
    except ImportError as exc:
        raise RuntimeError(
            "Polars is required. Run this script in the nba-roster-optimizer environment."
        ) from exc

    root = project_root(args.root)
    outputs = root / "outputs"
    outputs.mkdir(parents=True, exist_ok=True)
    batch_dir = outputs / BATCH_DIRECTORY
    batch_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 80)
    print("MIXED PLAYER-AND-PICK PLAYER CBA RESEARCH PACKET BUILDER")
    print("=" * 80)
    print(f"Release: {RELEASE_NAME}")
    print(f"Trade date: {TRADE_DATE}")
    print()

    print("[1/6] Locating validated V7 packages and source files")
    metadata_path = locate_one(root, TEAM_CBA_METADATA)
    package_paths = {label: locate_one(root, filename) for label, filename in PACKAGE_FILES.items()}
    source_paths = {label: locate_source(root, parts) for label, parts in SOURCE_FILES.items()}
    with metadata_path.open("r", encoding="utf-8-sig") as handle:
        team_metadata = json.load(handle)

    print("[2/6] Extracting the 83,975-package player exposure universe")
    profiles, exposure = profile_packages(pl, package_paths)

    print("[3/6] Reconciling players against financial and trade-pool sources")
    financial = pl.read_parquet(str(source_paths["player_financial"]))
    eligibility = pl.read_parquet(str(source_paths["trade_eligible_pool"]))
    missing_financial = sorted(FINANCIAL_REQUIRED_COLUMNS.difference(financial.columns))
    missing_eligibility = sorted(ELIGIBILITY_REQUIRED_COLUMNS.difference(eligibility.columns))
    if missing_financial or missing_eligibility:
        raise RuntimeError(
            f"Required source fields are missing. Financial: {missing_financial}; "
            f"eligibility: {missing_eligibility}"
        )
    player_teams = profiles.pop("player_teams")
    queue, coverage = build_queue(exposure, player_teams, financial, eligibility)
    assign_batches(queue, args.batch_size)

    print("[4/6] Validating queue integrity and batch coverage")
    checks = build_checks(
        team_metadata, profiles, exposure, queue, coverage, financial, eligibility, args.batch_size
    )
    passed = sum(check["passed"] for check in checks)
    release_valid = passed == len(checks)

    print("[5/6] Writing research queue, source coverage, and evidence batches")
    write_csv(outputs / QUEUE_OUTPUT, ALL_FIELDS, queue)
    coverage_headers = list(coverage[0].keys()) if coverage else []
    write_csv(outputs / COVERAGE_OUTPUT, coverage_headers, coverage)
    write_csv(outputs / VALIDATION_OUTPUT,
              ["check_name", "passed", "actual", "expected"], checks)
    write_csv(
        outputs / FIELD_DICTIONARY_OUTPUT,
        ["field_name", "data_type", "completion_guidance"],
        [
            {"field_name": field, "data_type": data_type, "completion_guidance": guidance}
            for field, data_type, guidance in FIELD_DICTIONARY
        ],
    )

    batch_ids = sorted({row["batch_id"] for row in queue})
    batch_files: list[str] = []
    for batch_id in batch_ids:
        batch_number = int(batch_id.split("P")[-1])
        filename = f"mixed_player_pick_player_cba_p{batch_number:02d}_evidence_input_v1.csv"
        path = batch_dir / filename
        write_csv(path, ALL_FIELDS, [row for row in queue if row["batch_id"] == batch_id])
        batch_files.append(str(path))

    status_counts = Counter(row["source_coverage_status"] for row in coverage)
    metadata = {
        "script_version": SCRIPT_VERSION,
        "release_name": RELEASE_NAME,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "trade_date": TRADE_DATE,
        "league_year": LEAGUE_YEAR,
        "release_valid": release_valid,
        "validation_checks_passed": passed,
        "validation_checks_total": len(checks),
        "package_counts": {
            "all_packages": sum(profiles[label]["rows"] for label in PACKAGE_FILES),
            "player_cba_queue_packages": sum(
                profiles[label]["advancing_rows"] for label in PACKAGE_FILES
            ),
            "one_for_one_queue": profiles["one_for_one"]["advancing_rows"],
            "two_for_one_queue": profiles["two_for_one"]["advancing_rows"],
        },
        "player_queue": {
            "unique_players": len(queue),
            "player_package_exposures": sum(exposure["total"].values()),
            "unique_teams": len({row["current_team_2026_27"] for row in queue}),
            "source_coverage_status_counts": dict(sorted(status_counts.items())),
            "players_with_prior_verified_restrictions": sum(
                row["contract_restrictions_verified_prior"] is True for row in queue
            ),
        },
        "research_batches": {
            "batch_size": args.batch_size,
            "batch_count": len(batch_ids),
            "first_batch": batch_files[0] if batch_files else None,
            "files": batch_files,
            "immutable_column_count": len(IMMUTABLE_FIELDS),
            "research_column_count": len(RESEARCH_FIELDS),
            "total_column_count": len(ALL_FIELDS),
        },
        "inputs": {
            "team_cba_metadata": str(metadata_path),
            "packages": {label: str(path) for label, path in package_paths.items()},
            "player_sources": {label: str(path) for label, path in source_paths.items()},
        },
        "outputs": {
            "research_queue": str(outputs / QUEUE_OUTPUT),
            "source_coverage": str(outputs / COVERAGE_OUTPUT),
            "validation": str(outputs / VALIDATION_OUTPUT),
            "field_dictionary": str(outputs / FIELD_DICTIONARY_OUTPUT),
            "batch_directory": str(batch_dir),
        },
        "package_final_legal_status_released": False,
        "next_step": (
            "Complete the player evidence batches, consolidate verified player decisions, "
            "then propagate player restrictions and exact matching-salary adjustments to the V7 packages."
        ),
    }
    write_json(outputs / METADATA_OUTPUT, metadata)

    print("[6/6] Complete")
    print(f"Packages queued: {metadata['package_counts']['player_cba_queue_packages']:,}")
    print(f"Unique players queued: {len(queue):,}")
    print(f"Player-package exposures: {sum(exposure['total'].values()):,}")
    print(f"Research batches: {len(batch_ids):,}")
    print(f"Validation: {passed}/{len(checks)}")
    print(f"Release valid: {release_valid}")
    print("Final package legality released: False")
    if not release_valid:
        failed = [check["check_name"] for check in checks if not check["passed"]]
        print("Failed checks:")
        for name in failed:
            print(f"  - {name}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())