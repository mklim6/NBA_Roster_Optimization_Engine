"""Audit exact full-CBA source coverage for the mixed-package release.

Save this file in ``src``. It validates the 149,141-package V6 queue, extracts
its 395 unique players and 30 teams, and profiles the strongest reusable local
salary, eligibility, team-cap, and rule sources identified by the readiness
inventory. It writes compact player/team coverage tables and an exact missing-
evidence queue. It does not modify package candidates or release final legality.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


SCRIPT_VERSION = "mixed-player-pick-full-cba-source-coverage-audit-v1-2026-08-05"
RELEASE_NAME = "mixed_player_pick_full_cba_source_coverage_2026_27_v1"
TRADE_DATE = "2026-08-04"
LEAGUE_YEAR = "2026-27"

READINESS_METADATA_FILENAME = "mixed_player_pick_full_cba_readiness_metadata_v1.json"
PACKAGE_FILES = {
    "one_for_one": "one_for_one_mixed_player_pick_candidates_2026_27_v6_right_legality_evaluated.parquet",
    "two_for_one": "two_for_one_mixed_player_pick_candidates_2026_27_v6_right_legality_evaluated.parquet",
}
EXPECTED_PACKAGE_ROWS = {"one_for_one": 28_324, "two_for_one": 282_277}
EXPECTED_PASSED_ROWS = {"one_for_one": 20_797, "two_for_one": 128_344}
EXPECTED_QUEUE_PLAYERS = 395
EXPECTED_QUEUE_TEAMS = 30
EXPECTED_QUEUE_PACKAGES = 149_141

SOURCE_FILES = {
    "player_financial": ("data", "processed", "player_financial_layer_2026_27_v2.parquet"),
    "trade_eligible_pool": ("data", "processed", "trade_eligible_player_pool_2026_27.parquet"),
    "team_salary_profiles": ("data", "processed", "team_trade_salary_profiles_2026_27.csv"),
    "trade_salary_rules": ("outputs", "trade_salary_precheck_metadata_2026_27.json"),
    "player_financial_metadata": ("outputs", "player_financial_layer_metadata_2026_27.json"),
    "two_for_one_salary_rules": ("outputs", "two_for_one_trade_salary_precheck_metadata_2026_27.json"),
}

METADATA_OUTPUT = "mixed_player_pick_full_cba_source_coverage_metadata_v1.json"
PLAYER_OUTPUT = "mixed_player_pick_full_cba_player_source_coverage_v1.csv"
TEAM_OUTPUT = "mixed_player_pick_full_cba_team_source_coverage_v1.csv"
SCHEMA_OUTPUT = "mixed_player_pick_full_cba_selected_source_schema_v1.csv"
MISSING_OUTPUT = "mixed_player_pick_full_cba_missing_evidence_queue_v1.csv"
VALIDATION_OUTPUT = "mixed_player_pick_full_cba_source_coverage_validation_v1.csv"

PLAYER_FINANCIAL_REQUIRED = {"player_id", "team_id", "trade_salary_2026_27"}
ELIGIBILITY_REQUIRED = {
    "player_id",
    "trade_salary_2026_27",
    "salary_data_verified_for_player",
    "recently_signed_or_acquired_restriction_verified",
    "no_trade_clause_verified",
}
TEAM_PROFILE_REQUIRED = {
    "team_abbreviation",
    "apron_team_salary_proxy_2026_27",
    "official_team_salary_verified",
    "team_salary_source_quality",
    "salary_proxy_tier",
    "distance_to_first_apron_proxy",
    "distance_to_second_apron_proxy",
}
RULE_THRESHOLD_KEYS = {
    "salary_cap_2026_27",
    "luxury_tax_2026_27",
    "first_apron_2026_27",
    "second_apron_2026_27",
}

MISSING_EVIDENCE = (
    {
        "priority_order": 1,
        "evidence_level": "player",
        "concept": "contract_type",
        "existing_proxy": "salary_data_verified_for_player",
        "required_evidence": "Standard, two-way, Exhibit 10, or other contract classification as of the trade date.",
    },
    {
        "priority_order": 2,
        "evidence_level": "player",
        "concept": "trade_eligible_date",
        "existing_proxy": "recently_signed_or_acquired_restriction_verified",
        "required_evidence": "Exact date the player becomes trade eligible and the rule producing that date.",
    },
    {
        "priority_order": 3,
        "evidence_level": "player",
        "concept": "aggregation_eligible_date",
        "existing_proxy": "recently_signed_or_acquired_restriction_verified",
        "required_evidence": "Exact date the player can be aggregated with other outgoing salary.",
    },
    {
        "priority_order": 4,
        "evidence_level": "player_team",
        "concept": "aggregation_restricted",
        "existing_proxy": "base_salary_precheck_passed",
        "required_evidence": "Player-level recent-acquisition status plus team second-apron aggregation prohibition.",
    },
    {
        "priority_order": 5,
        "evidence_level": "player",
        "concept": "trade_bonus",
        "existing_proxy": "trade_salary_2026_27",
        "required_evidence": "Trade bonus percentage, remaining allocation, responsibility, and adjusted matching salary.",
    },
    {
        "priority_order": 6,
        "evidence_level": "player",
        "concept": "poison_pill",
        "existing_proxy": "trade_salary_2026_27",
        "required_evidence": "Poison-pill status and separate outgoing and incoming salary amounts when applicable.",
    },
    {
        "priority_order": 7,
        "evidence_level": "player",
        "concept": "base_year_compensation",
        "existing_proxy": "trade_salary_2026_27",
        "required_evidence": "BYC applicability and outgoing salary calculation when applicable.",
    },
    {
        "priority_order": 8,
        "evidence_level": "player",
        "concept": "trade_consent",
        "existing_proxy": "no_trade_clause_verified",
        "required_evidence": "No-trade clause or one-year Bird-right consent requirement and current consent status.",
    },
    {
        "priority_order": 9,
        "evidence_level": "player",
        "concept": "sign_and_trade",
        "existing_proxy": "none",
        "required_evidence": "Sign-and-trade status, receiving-team apron restriction, and hard-cap trigger.",
    },
    {
        "priority_order": 10,
        "evidence_level": "player",
        "concept": "extension_restriction",
        "existing_proxy": "none",
        "required_evidence": "Extend-and-trade restriction and any applicable waiting date.",
    },
    {
        "priority_order": 11,
        "evidence_level": "player",
        "concept": "two_way_status",
        "existing_proxy": "none",
        "required_evidence": "Two-way contract status and whether the player may be included in the modeled transaction.",
    },
    {
        "priority_order": 12,
        "evidence_level": "team",
        "concept": "hard_cap",
        "existing_proxy": "apron_team_salary_proxy_2026_27",
        "required_evidence": "Hard-cap activation status and applicable first- or second-apron ceiling as of the trade date.",
    },
    {
        "priority_order": 13,
        "evidence_level": "team",
        "concept": "standard_roster_count",
        "existing_proxy": "none",
        "required_evidence": "Standard-contract roster count immediately before the transaction.",
    },
    {
        "priority_order": 14,
        "evidence_level": "team",
        "concept": "two_way_count",
        "existing_proxy": "none",
        "required_evidence": "Two-way roster count immediately before the transaction.",
    },
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, help="Project root override.")
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Run dependency-free helper tests without reading project files.",
    )
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
    filename = parts[-1]
    matches = sorted(path for path in root.rglob(filename) if path.is_file())
    if not matches:
        raise FileNotFoundError(f"Could not find selected source {filename} beneath {root}")
    if len(matches) > 1:
        joined = "\n  ".join(str(path) for path in matches)
        raise RuntimeError(f"Found multiple copies of selected source {filename}:\n  {joined}")
    return matches[0]


def normalize_id(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if re.fullmatch(r"\d+\.0", text):
        text = text[:-2]
    return text


def split_player_ids(value: Any) -> list[str]:
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


def safe_json(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): safe_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [safe_json(item) for item in value]
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            pass
    return str(value)


def write_csv(path: Path, headers: list[str], rows: Iterable[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers, extrasaction="raise")
        writer.writeheader()
        writer.writerows(rows)


def read_table(pl: Any, path: Path) -> Any:
    if path.suffix.lower() == ".parquet":
        return pl.read_parquet(str(path))
    if path.suffix.lower() == ".csv":
        return pl.read_csv(str(path), infer_schema_length=10_000)
    raise ValueError(f"Unsupported table source: {path}")


def flatten_json(value: Any, prefix: str = "") -> list[tuple[str, Any]]:
    rows: list[tuple[str, Any]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            rows.append((path, child))
            rows.extend(flatten_json(child, path))
    elif isinstance(value, list):
        for index, child in enumerate(value[:3]):
            path = f"{prefix}[{index}]"
            rows.extend(flatten_json(child, path))
    return rows


def json_values_by_leaf(value: Any) -> dict[str, list[Any]]:
    result: dict[str, list[Any]] = defaultdict(list)
    for path, item in flatten_json(value):
        leaf = re.sub(r"\[\d+\]$", "", path.rsplit(".", 1)[-1])
        if not isinstance(item, (dict, list)):
            result[leaf].append(item)
    return dict(result)


def compact_values(values: Iterable[Any], limit: int = 12) -> str:
    unique: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value is None:
            continue
        text = str(value)
        if text in seen:
            continue
        seen.add(text)
        unique.append(text)
        if len(unique) >= limit:
            break
    return "|".join(unique)


def value_counts(frame: Any, column: str) -> dict[str, int]:
    if column not in frame.columns:
        return {}
    result: Counter[str] = Counter()
    for value in frame.get_column(column).to_list():
        key = "<null>" if value is None else str(value)
        result[key] += 1
    return dict(sorted(result.items()))


def find_first(columns: Iterable[str], candidates: Iterable[str]) -> str | None:
    column_set = set(columns)
    for candidate in candidates:
        if candidate in column_set:
            return candidate
    return None


def semantic_tags(field_name: str) -> list[str]:
    lowered = field_name.lower()
    patterns = {
        "identity": ("player_id", "team_id", "team_abbreviation"),
        "salary": ("salary", "payroll", "cap_room"),
        "apron": ("apron",),
        "trade_restriction": (
            "eligible",
            "eligibility",
            "restriction",
            "no_trade",
            "consent",
            "aggregation",
            "sign_and_trade",
            "extension",
            "two_way",
            "poison",
            "bonus",
            "base_year",
            "byc",
        ),
        "authority": ("source", "verified", "as_of", "effective_date", "url"),
        "roster": ("roster", "standard_contract", "two_way_count"),
    }
    return [tag for tag, tokens in patterns.items() if any(token in lowered for token in tokens)]


def extract_queue(pl: Any, package_paths: dict[str, Path]) -> tuple[dict[str, Any], set[str], set[str]]:
    profiles: dict[str, Any] = {}
    all_players: set[str] = set()
    all_teams: set[str] = set()
    for label, path in package_paths.items():
        frame = pl.read_parquet(
            str(path),
            columns=[
                "package_right_legality_stage_passed",
                "side_a_player_ids",
                "side_b_player_ids",
                "team_a",
                "team_b",
            ],
        )
        passed = frame.filter(pl.col("package_right_legality_stage_passed") == True)  # noqa: E712
        player_ids: set[str] = set()
        for column in ("side_a_player_ids", "side_b_player_ids"):
            for value in passed.get_column(column).drop_nulls().unique().to_list():
                player_ids.update(split_player_ids(value))
        teams = {
            str(value)
            for column in ("team_a", "team_b")
            for value in passed.get_column(column).drop_nulls().unique().to_list()
        }
        all_players.update(player_ids)
        all_teams.update(teams)
        profiles[label] = {
            "path": str(path),
            "rows": frame.height,
            "passed_rows": passed.height,
            "unique_players": len(player_ids),
            "teams": sorted(teams),
        }
    return profiles, all_players, all_teams


def keyed_rows(frame: Any, key_column: str) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = defaultdict(list)
    if key_column not in frame.columns:
        return result
    for row in frame.iter_rows(named=True):
        key = normalize_id(row.get(key_column))
        if key:
            result[key].append(row)
    return dict(result)


def row_field_values(rows: list[dict[str, Any]], column: str | None) -> list[Any]:
    if not column:
        return []
    return [row.get(column) for row in rows if row.get(column) is not None]


def build_player_coverage(
    queue_players: set[str],
    financial: Any,
    eligibility: Any,
) -> list[dict[str, Any]]:
    financial_rows = keyed_rows(financial, "player_id")
    eligibility_rows = keyed_rows(eligibility, "player_id")
    financial_name = find_first(
        financial.columns,
        ("player_name", "player_display_name", "full_name", "name"),
    )
    eligibility_name = find_first(
        eligibility.columns,
        ("player_name", "player_display_name", "full_name", "name"),
    )
    rows: list[dict[str, Any]] = []
    for player_id in sorted(queue_players):
        fin = financial_rows.get(player_id, [])
        elig = eligibility_rows.get(player_id, [])
        names = row_field_values(fin, financial_name) + row_field_values(elig, eligibility_name)
        salary_values = row_field_values(fin, "trade_salary_2026_27")
        salary_verified = row_field_values(elig, "salary_data_verified_for_player")
        restriction_verified = row_field_values(
            elig, "recently_signed_or_acquired_restriction_verified"
        )
        no_trade_verified = row_field_values(elig, "no_trade_clause_verified")
        if not fin:
            status = "missing_player_financial_source"
        elif not elig:
            status = "missing_trade_eligible_pool_source"
        elif len(fin) > 1 or len(elig) > 1:
            status = "duplicate_source_rows_review_required"
        elif not salary_values:
            status = "missing_trade_salary"
        else:
            status = "core_sources_present_full_cba_restriction_evidence_still_required"
        rows.append(
            {
                "player_id": player_id,
                "player_name": compact_values(names),
                "in_player_financial_layer": bool(fin),
                "player_financial_row_count": len(fin),
                "financial_team_ids": compact_values(row_field_values(fin, "team_id")),
                "trade_salary_2026_27_values": compact_values(salary_values),
                "trade_salary_nonnull": bool(salary_values),
                "in_trade_eligible_pool": bool(elig),
                "trade_eligible_pool_row_count": len(elig),
                "salary_data_verified_values": compact_values(salary_verified),
                "recently_signed_or_acquired_restriction_verified_values": compact_values(
                    restriction_verified
                ),
                "no_trade_clause_verified_values": compact_values(no_trade_verified),
                "source_coverage_status": status,
            }
        )
    return rows


def build_team_coverage(queue_teams: set[str], team_profile: Any) -> list[dict[str, Any]]:
    team_rows = keyed_rows(team_profile, "team_abbreviation")
    as_of_column = find_first(
        team_profile.columns,
        ("as_of_date", "snapshot_date", "effective_date", "trade_date"),
    )
    selected_columns = (
        "apron_team_salary_proxy_2026_27",
        "official_team_salary_verified",
        "team_salary_source_quality",
        "salary_proxy_tier",
        "salary_cap_room_proxy",
        "distance_to_first_apron_proxy",
        "distance_to_second_apron_proxy",
        "salary_precheck_scope_note",
        "payroll_scope_note",
    )
    rows: list[dict[str, Any]] = []
    for team in sorted(queue_teams):
        matches = team_rows.get(team, [])
        row: dict[str, Any] = {
            "team_abbreviation": team,
            "in_team_salary_profiles": bool(matches),
            "team_profile_row_count": len(matches),
            "profile_as_of_date_field": as_of_column or "",
            "profile_as_of_date_values": compact_values(row_field_values(matches, as_of_column)),
        }
        for column in selected_columns:
            row[column] = compact_values(row_field_values(matches, column))
        verified_values = [normalized_bool(value) for value in row_field_values(
            matches, "official_team_salary_verified"
        )]
        if not matches:
            status = "missing_team_salary_profile"
        elif len(matches) > 1:
            status = "duplicate_team_profile_rows_review_required"
        elif not as_of_column:
            status = "proxy_present_missing_snapshot_date_and_full_cba_fields"
        elif not verified_values or not all(value is True for value in verified_values):
            status = "proxy_present_not_officially_verified"
        else:
            status = "core_team_profile_present_full_cba_fields_still_required"
        row["source_coverage_status"] = status
        rows.append(row)
    return rows


def build_schema_rows(
    table_sources: dict[str, tuple[Path, Any]],
    json_sources: dict[str, tuple[Path, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for source_id, (path, frame) in table_sources.items():
        for position, (field_name, dtype) in enumerate(frame.schema.items(), start=1):
            samples = compact_values(frame.get_column(field_name).drop_nulls().head(5).to_list(), 5)
            rows.append(
                {
                    "source_id": source_id,
                    "source_path": str(path),
                    "source_format": path.suffix.lower(),
                    "field_position": position,
                    "field_name": field_name,
                    "dtype": str(dtype),
                    "semantic_tags": "|".join(semantic_tags(field_name)),
                    "sample_values": samples,
                }
            )
    for source_id, (path, payload) in json_sources.items():
        for position, (field_path, value) in enumerate(flatten_json(payload), start=1):
            if isinstance(value, (dict, list)):
                continue
            rows.append(
                {
                    "source_id": source_id,
                    "source_path": str(path),
                    "source_format": ".json",
                    "field_position": position,
                    "field_name": field_path,
                    "dtype": type(value).__name__,
                    "semantic_tags": "|".join(semantic_tags(field_path)),
                    "sample_values": str(value),
                }
            )
    return rows


def threshold_profile(payload: Any) -> dict[str, Any]:
    values = json_values_by_leaf(payload)
    result: dict[str, Any] = {}
    for key in sorted(RULE_THRESHOLD_KEYS):
        candidates = values.get(key, [])
        result[key] = candidates[0] if candidates else None
    numeric = [result[key] for key in (
        "salary_cap_2026_27",
        "luxury_tax_2026_27",
        "first_apron_2026_27",
        "second_apron_2026_27",
    )]
    result["thresholds_present"] = all(isinstance(value, (int, float)) for value in numeric)
    result["thresholds_monotonic"] = bool(
        result["thresholds_present"] and numeric == sorted(numeric) and len(set(numeric)) == 4
    )
    source_fields = {
        path: value
        for path, value in flatten_json(payload)
        if not isinstance(value, (dict, list))
        and any(token in path.lower() for token in ("source", "url", "authority", "as_of"))
    }
    result["source_fields"] = source_fields
    result["source_fields_present"] = bool(source_fields)
    return result


def validate_integrity(
    readiness: dict[str, Any],
    package_profiles: dict[str, Any],
    queue_players: set[str],
    queue_teams: set[str],
    financial: Any,
    eligibility: Any,
    team_profile: Any,
    thresholds: dict[str, Any],
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []

    def add(category: str, name: str, passed: bool, observed: Any, expected: Any) -> None:
        checks.append(
            {
                "check_category": category,
                "check_name": name,
                "passed": bool(passed),
                "observed": json.dumps(safe_json(observed), sort_keys=True),
                "expected": json.dumps(safe_json(expected), sort_keys=True),
            }
        )

    add("integrity", "readiness_audit_valid", readiness.get("audit_valid") is True,
        readiness.get("audit_valid"), True)
    add("integrity", "readiness_validation_23_of_23",
        readiness.get("validation_checks_passed") == 23
        and readiness.get("validation_checks_total") == 23,
        [readiness.get("validation_checks_passed"), readiness.get("validation_checks_total")], [23, 23])
    add("integrity", "readiness_queue_count",
        readiness.get("combined_package_counts", {}).get("right_legality_passed") == EXPECTED_QUEUE_PACKAGES,
        readiness.get("combined_package_counts", {}).get("right_legality_passed"), EXPECTED_QUEUE_PACKAGES)
    for label, profile in package_profiles.items():
        add("integrity", f"{label}_rows", profile["rows"] == EXPECTED_PACKAGE_ROWS[label],
            profile["rows"], EXPECTED_PACKAGE_ROWS[label])
        add("integrity", f"{label}_passed_rows", profile["passed_rows"] == EXPECTED_PASSED_ROWS[label],
            profile["passed_rows"], EXPECTED_PASSED_ROWS[label])
    add("integrity", "queue_unique_players", len(queue_players) == EXPECTED_QUEUE_PLAYERS,
        len(queue_players), EXPECTED_QUEUE_PLAYERS)
    add("integrity", "queue_unique_teams", len(queue_teams) == EXPECTED_QUEUE_TEAMS,
        len(queue_teams), EXPECTED_QUEUE_TEAMS)
    add("integrity", "player_financial_required_columns",
        PLAYER_FINANCIAL_REQUIRED.issubset(financial.columns),
        sorted(PLAYER_FINANCIAL_REQUIRED.difference(financial.columns)), [])
    add("integrity", "eligibility_required_columns",
        ELIGIBILITY_REQUIRED.issubset(eligibility.columns),
        sorted(ELIGIBILITY_REQUIRED.difference(eligibility.columns)), [])
    add("integrity", "team_profile_required_columns",
        TEAM_PROFILE_REQUIRED.issubset(team_profile.columns),
        sorted(TEAM_PROFILE_REQUIRED.difference(team_profile.columns)), [])
    add("integrity", "rule_thresholds_present", thresholds["thresholds_present"],
        {key: thresholds[key] for key in sorted(RULE_THRESHOLD_KEYS)}, "four numeric thresholds")
    add("integrity", "rule_thresholds_monotonic", thresholds["thresholds_monotonic"],
        [thresholds[key] for key in (
            "salary_cap_2026_27", "luxury_tax_2026_27", "first_apron_2026_27", "second_apron_2026_27"
        )], "strictly increasing")
    add("readiness", "all_395_players_in_financial_source",
        queue_players.issubset(set(keyed_rows(financial, "player_id"))),
        len(queue_players.intersection(set(keyed_rows(financial, "player_id")))), len(queue_players))
    add("readiness", "all_395_players_in_eligibility_source",
        queue_players.issubset(set(keyed_rows(eligibility, "player_id"))),
        len(queue_players.intersection(set(keyed_rows(eligibility, "player_id")))), len(queue_players))
    add("readiness", "all_30_teams_in_salary_profile",
        queue_teams.issubset(set(keyed_rows(team_profile, "team_abbreviation"))),
        len(queue_teams.intersection(set(keyed_rows(team_profile, "team_abbreviation")))), len(queue_teams))
    add("readiness", "team_profile_has_snapshot_date",
        find_first(team_profile.columns, ("as_of_date", "snapshot_date", "effective_date", "trade_date")) is not None,
        find_first(team_profile.columns, ("as_of_date", "snapshot_date", "effective_date", "trade_date")),
        "one explicit snapshot date field")
    official_values = [normalized_bool(value) for value in team_profile.get_column(
        "official_team_salary_verified"
    ).to_list()] if "official_team_salary_verified" in team_profile.columns else []
    add("readiness", "all_team_salaries_officially_verified",
        bool(official_values) and all(value is True for value in official_values),
        Counter(str(value) for value in official_values), {"True": team_profile.height})
    add("readiness", "threshold_source_fields_present", thresholds["source_fields_present"],
        thresholds["source_fields"], "at least one source or authority field")
    add("readiness", "fourteen_missing_concepts_resolved", False,
        [row["concept"] for row in MISSING_EVIDENCE], [])
    return checks


def run_self_tests() -> None:
    assert split_player_ids("1|2;3, 4") == ["1", "2", "3", "4"]
    assert normalize_id("123.0") == "123"
    assert normalized_bool("TRUE") is True
    assert normalized_bool("no") is False
    flattened = dict(flatten_json({"a": {"b": 1}}))
    assert flattened["a.b"] == 1
    assert "trade_restriction" in semantic_tags("aggregation_eligible_date")
    print("Self-tests passed: 6/6")


def main() -> int:
    args = parse_args()
    if args.self_test:
        run_self_tests()
        return 0

    try:
        import polars as pl
    except ImportError as exc:
        raise RuntimeError(
            "Polars is required. Run this script in the nba-roster-optimizer environment."
        ) from exc

    root = project_root(args.root)
    outputs = root / "outputs"
    outputs.mkdir(parents=True, exist_ok=True)

    print("=" * 80)
    print("MIXED PLAYER-AND-PICK FULL CBA SOURCE COVERAGE AUDIT")
    print("=" * 80)
    print(f"Script version: {SCRIPT_VERSION}")
    print(f"Release name: {RELEASE_NAME}")
    print(f"Trade date: {TRADE_DATE}")
    print()

    print("[1/7] Loading readiness metadata and V6 package candidates")
    readiness_path = locate_one(root, READINESS_METADATA_FILENAME)
    with readiness_path.open("r", encoding="utf-8-sig") as handle:
        readiness = json.load(handle)
    package_paths = {label: locate_one(root, filename) for label, filename in PACKAGE_FILES.items()}

    print("[2/7] Extracting the exact 395-player and 30-team review universe")
    package_profiles, queue_players, queue_teams = extract_queue(pl, package_paths)

    print("[3/7] Loading selected player, team, and rule sources")
    source_paths = {source_id: locate_source(root, parts) for source_id, parts in SOURCE_FILES.items()}
    financial = read_table(pl, source_paths["player_financial"])
    eligibility = read_table(pl, source_paths["trade_eligible_pool"])
    team_profile = read_table(pl, source_paths["team_salary_profiles"])
    json_sources: dict[str, tuple[Path, Any]] = {}
    for source_id in ("trade_salary_rules", "player_financial_metadata", "two_for_one_salary_rules"):
        path = source_paths[source_id]
        with path.open("r", encoding="utf-8-sig") as handle:
            json_sources[source_id] = (path, json.load(handle))

    print("[4/7] Measuring player and team coverage")
    player_rows = build_player_coverage(queue_players, financial, eligibility)
    team_rows = build_team_coverage(queue_teams, team_profile)

    print("[5/7] Auditing exact schemas, thresholds, and source authority")
    table_sources = {
        "player_financial": (source_paths["player_financial"], financial),
        "trade_eligible_pool": (source_paths["trade_eligible_pool"], eligibility),
        "team_salary_profiles": (source_paths["team_salary_profiles"], team_profile),
    }
    schema_rows = build_schema_rows(table_sources, json_sources)
    thresholds = threshold_profile(json_sources["trade_salary_rules"][1])

    print("[6/7] Validating integrity and separating unresolved readiness gates")
    validation_rows = validate_integrity(
        readiness,
        package_profiles,
        queue_players,
        queue_teams,
        financial,
        eligibility,
        team_profile,
        thresholds,
    )
    integrity_rows = [row for row in validation_rows if row["check_category"] == "integrity"]
    readiness_rows = [row for row in validation_rows if row["check_category"] == "readiness"]
    audit_valid = all(row["passed"] for row in integrity_rows)
    source_readiness_checks_passed = sum(row["passed"] for row in readiness_rows)

    player_status_counts = Counter(row["source_coverage_status"] for row in player_rows)
    team_status_counts = Counter(row["source_coverage_status"] for row in team_rows)
    player_financial_matches = sum(row["in_player_financial_layer"] for row in player_rows)
    eligibility_matches = sum(row["in_trade_eligible_pool"] for row in player_rows)
    team_matches = sum(row["in_team_salary_profiles"] for row in team_rows)

    missing_rows = [
        {
            **row,
            "inventory_source_count": 0,
            "trade_date": TRADE_DATE,
            "league_year": LEAGUE_YEAR,
            "automatic_release_policy": "required_before_final_legal_release",
        }
        for row in MISSING_EVIDENCE
    ]
    team_as_of_field = find_first(
        team_profile.columns, ("as_of_date", "snapshot_date", "effective_date", "trade_date")
    )
    if not team_as_of_field:
        missing_rows.append(
            {
                "priority_order": 15,
                "evidence_level": "team",
                "concept": "team_salary_snapshot_as_of_date",
                "existing_proxy": "none",
                "required_evidence": "Explicit effective date for each 30-team salary and apron snapshot row.",
                "inventory_source_count": 0,
                "trade_date": TRADE_DATE,
                "league_year": LEAGUE_YEAR,
                "automatic_release_policy": "required_before_final_legal_release",
            }
        )

    full_cba_source_ready = all(row["passed"] for row in readiness_rows) and not missing_rows
    metadata = {
        "script_version": SCRIPT_VERSION,
        "release_name": RELEASE_NAME,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "trade_date": TRADE_DATE,
        "league_year": LEAGUE_YEAR,
        "audit_valid": audit_valid,
        "integrity_checks_passed": sum(row["passed"] for row in integrity_rows),
        "integrity_checks_total": len(integrity_rows),
        "source_readiness_checks_passed": source_readiness_checks_passed,
        "source_readiness_checks_total": len(readiness_rows),
        "readiness_release": readiness.get("release_name"),
        "package_profiles": package_profiles,
        "queue": {
            "packages": sum(profile["passed_rows"] for profile in package_profiles.values()),
            "unique_players": len(queue_players),
            "teams": len(queue_teams),
        },
        "selected_source_paths": {key: str(value) for key, value in source_paths.items()},
        "source_profiles": {
            "player_financial": {
                "rows": financial.height,
                "columns": len(financial.columns),
                "queue_players_matched": player_financial_matches,
                "queue_players_unmatched": len(queue_players) - player_financial_matches,
                "required_columns_missing": sorted(PLAYER_FINANCIAL_REQUIRED.difference(financial.columns)),
            },
            "trade_eligible_pool": {
                "rows": eligibility.height,
                "columns": len(eligibility.columns),
                "queue_players_matched": eligibility_matches,
                "queue_players_unmatched": len(queue_players) - eligibility_matches,
                "required_columns_missing": sorted(ELIGIBILITY_REQUIRED.difference(eligibility.columns)),
                "salary_data_verified_counts": value_counts(eligibility, "salary_data_verified_for_player"),
                "recently_signed_or_acquired_restriction_verified_counts": value_counts(
                    eligibility, "recently_signed_or_acquired_restriction_verified"
                ),
                "no_trade_clause_verified_counts": value_counts(eligibility, "no_trade_clause_verified"),
            },
            "team_salary_profiles": {
                "rows": team_profile.height,
                "columns": len(team_profile.columns),
                "queue_teams_matched": team_matches,
                "queue_teams_unmatched": len(queue_teams) - team_matches,
                "required_columns_missing": sorted(TEAM_PROFILE_REQUIRED.difference(team_profile.columns)),
                "official_team_salary_verified_counts": value_counts(
                    team_profile, "official_team_salary_verified"
                ),
                "team_salary_source_quality_counts": value_counts(
                    team_profile, "team_salary_source_quality"
                ),
                "salary_proxy_tier_counts": value_counts(team_profile, "salary_proxy_tier"),
                "explicit_snapshot_date_field": team_as_of_field,
            },
        },
        "player_coverage_status_counts": dict(sorted(player_status_counts.items())),
        "team_coverage_status_counts": dict(sorted(team_status_counts.items())),
        "threshold_profile": thresholds,
        "inventory_level_missing_concepts": [row["concept"] for row in MISSING_EVIDENCE],
        "coverage_quality_missing_concepts": [
            row["concept"] for row in missing_rows if row["concept"] not in {item["concept"] for item in MISSING_EVIDENCE}
        ],
        "missing_evidence_rows": len(missing_rows),
        "full_cba_source_ready": full_cba_source_ready,
        "full_cba_final_legal_status_released": False,
        "non_destructive": True,
        "player_coverage_file": str(outputs / PLAYER_OUTPUT),
        "team_coverage_file": str(outputs / TEAM_OUTPUT),
        "selected_source_schema_file": str(outputs / SCHEMA_OUTPUT),
        "missing_evidence_queue_file": str(outputs / MISSING_OUTPUT),
        "validation_file": str(outputs / VALIDATION_OUTPUT),
    }

    print("[7/7] Saving coverage, schema, missing evidence, validation, and metadata")
    with (outputs / METADATA_OUTPUT).open("w", encoding="utf-8") as handle:
        json.dump(safe_json(metadata), handle, indent=2)
        handle.write("\n")
    write_csv(
        outputs / PLAYER_OUTPUT,
        [
            "player_id",
            "player_name",
            "in_player_financial_layer",
            "player_financial_row_count",
            "financial_team_ids",
            "trade_salary_2026_27_values",
            "trade_salary_nonnull",
            "in_trade_eligible_pool",
            "trade_eligible_pool_row_count",
            "salary_data_verified_values",
            "recently_signed_or_acquired_restriction_verified_values",
            "no_trade_clause_verified_values",
            "source_coverage_status",
        ],
        player_rows,
    )
    write_csv(
        outputs / TEAM_OUTPUT,
        [
            "team_abbreviation",
            "in_team_salary_profiles",
            "team_profile_row_count",
            "profile_as_of_date_field",
            "profile_as_of_date_values",
            "apron_team_salary_proxy_2026_27",
            "official_team_salary_verified",
            "team_salary_source_quality",
            "salary_proxy_tier",
            "salary_cap_room_proxy",
            "distance_to_first_apron_proxy",
            "distance_to_second_apron_proxy",
            "salary_precheck_scope_note",
            "payroll_scope_note",
            "source_coverage_status",
        ],
        team_rows,
    )
    write_csv(
        outputs / SCHEMA_OUTPUT,
        [
            "source_id",
            "source_path",
            "source_format",
            "field_position",
            "field_name",
            "dtype",
            "semantic_tags",
            "sample_values",
        ],
        schema_rows,
    )
    write_csv(
        outputs / MISSING_OUTPUT,
        [
            "priority_order",
            "evidence_level",
            "concept",
            "inventory_source_count",
            "existing_proxy",
            "required_evidence",
            "trade_date",
            "league_year",
            "automatic_release_policy",
        ],
        missing_rows,
    )
    write_csv(
        outputs / VALIDATION_OUTPUT,
        ["check_category", "check_name", "passed", "observed", "expected"],
        validation_rows,
    )

    print()
    print("=" * 80)
    print("FULL CBA SOURCE COVERAGE AUDIT COMPLETE")
    print("=" * 80)
    print(f"Packages in queue: {metadata['queue']['packages']:,}")
    print(f"Unique players: {len(queue_players):,}")
    print(f"Teams: {len(queue_teams):,}")
    print(f"Player financial matches: {player_financial_matches}/{len(queue_players)}")
    print(f"Trade-eligible pool matches: {eligibility_matches}/{len(queue_players)}")
    print(f"Team salary profile matches: {team_matches}/{len(queue_teams)}")
    print(f"Integrity checks passed: {metadata['integrity_checks_passed']}/{metadata['integrity_checks_total']}")
    print(f"Source readiness checks passed: {source_readiness_checks_passed}/{len(readiness_rows)}")
    print(f"Missing evidence concepts queued: {len(missing_rows)}")
    print(f"Audit valid: {audit_valid}")
    print(f"Final package legality released: {full_cba_source_ready}")
    print()
    print("NEXT REVIEW FILES")
    print(outputs / METADATA_OUTPUT)
    print(outputs / MISSING_OUTPUT)
    print()
    print("SAVED FILES")
    for filename in (
        METADATA_OUTPUT,
        PLAYER_OUTPUT,
        TEAM_OUTPUT,
        SCHEMA_OUTPUT,
        MISSING_OUTPUT,
        VALIDATION_OUTPUT,
    ):
        print(outputs / filename)

    return 0 if audit_valid else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise