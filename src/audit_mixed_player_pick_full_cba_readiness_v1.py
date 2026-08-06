"""Audit full-CBA data readiness for mixed player-and-pick packages.

Save this file in ``src``. It reads the two V6 right-legality-evaluated
package parquets and the propagation metadata, validates the 149,141-package
automatic-review queue, and scans local structured data sources for fields
needed by the remaining salary, apron, aggregation, player-restriction, roster,
and trade-date gates.

This script is intentionally read-only with respect to package candidates. It
does not make final CBA decisions and never releases ``optimizer_package_final_legal``.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


SCRIPT_VERSION = "mixed-player-pick-full-cba-readiness-audit-v1-2026-08-05"
RELEASE_NAME = "mixed_player_pick_full_cba_readiness_2026_27_v1"

PROPAGATION_METADATA_FILENAME = "mixed_player_pick_package_right_legality_metadata_v1.json"
PACKAGE_FILES = {
    "one_for_one": "one_for_one_mixed_player_pick_candidates_2026_27_v6_right_legality_evaluated.parquet",
    "two_for_one": "two_for_one_mixed_player_pick_candidates_2026_27_v6_right_legality_evaluated.parquet",
}
EXPECTED_PACKAGE_ROWS = {"one_for_one": 28_324, "two_for_one": 282_277}
EXPECTED_PACKAGE_COLUMNS = {"one_for_one": 95, "two_for_one": 93}
EXPECTED_RESULTS = {
    "one_for_one": {"passed": 20_797, "manual": 805, "blocked": 6_722},
    "two_for_one": {"passed": 128_344, "manual": 2_946, "blocked": 150_987},
}
EXPECTED_GLOBAL = {"rows": 310_601, "passed": 149_141, "manual": 3_751, "blocked": 157_709}

METADATA_OUTPUT = "mixed_player_pick_full_cba_readiness_metadata_v1.json"
REQUIREMENT_OUTPUT = "mixed_player_pick_full_cba_requirement_matrix_v1.csv"
SOURCE_FIELD_OUTPUT = "mixed_player_pick_full_cba_source_field_inventory_v1.csv"
VALIDATION_OUTPUT = "mixed_player_pick_full_cba_readiness_validation_v1.csv"

PACKAGE_REQUIRED_COLUMNS = {
    "optimizer_candidate_id",
    "team_a",
    "team_b",
    "side_a_player_ids",
    "side_b_player_ids",
    "side_a_player_trade_salary",
    "side_b_player_trade_salary",
    "base_salary_precheck_passed",
    "base_final_trade_legality_verified",
    "pick_trade_date_legality_verified",
    "optimizer_package_final_legal",
    "package_right_legality_stage_passed",
    "package_right_legality_manual_review_required",
    "package_right_legality_blocked",
    "package_right_legality_status",
}

STRUCTURED_EXTENSIONS = {".parquet", ".csv", ".json"}
SOURCE_FILENAME_TOKENS = (
    "salary",
    "contract",
    "payroll",
    "apron",
    "tax",
    "cap",
    "roster",
    "player",
    "trade",
    "transaction",
    "restriction",
    "eligibility",
    "signing",
    "exception",
    "team",
)
EXCLUDED_FILENAME_TOKENS = (
    "one_for_one_mixed_player_pick_candidates",
    "two_for_one_mixed_player_pick_candidates",
    "mixed_player_pick_right_legality",
    "mixed_player_pick_stepien",
    "mixed_player_pick_package_right",
    "right_legality_research_batches",
    "evidence_review",
    "evidence_completed",
    "readiness_validation",
    "requirement_matrix",
    "source_field_inventory",
)


CONCEPT_PATTERNS: dict[str, tuple[str, ...]] = {
    "player_id": (
        r"(^|_)(player|person|nba)_?id($|_)",
        r"(^|_)player_ids?($|_)",
    ),
    "team_id": (
        r"^(team|club|team_id|club_id|team_code|team_abbr|team_abbreviation)$",
        r"^team_ids?$",
    ),
    "season": (r"(^|_)(season|league_year)($|_)",),
    "as_of_date": (r"(^|_)(as_of|snapshot|effective)(_date)?($|_)",),
    "trade_date": (r"(^|_)trade_date($|_)", r"(^|_)transaction_date($|_)"),
    "trade_salary": (
        r"(^|_)(trade_salary|matching_salary|outgoing_salary|incoming_salary)($|_)",
        r"(^|_)salary_for_trade($|_)",
    ),
    "base_salary": (r"(^|_)(base_salary|salary|cap_hit|current_salary)($|_)",),
    "contract_type": (r"(^|_)(contract_type|contract_status|roster_status)($|_)",),
    "signed_date": (r"(^|_)(signed|signing)(_date)?($|_)",),
    "acquired_date": (r"(^|_)(acquired|acquisition)(_date)?($|_)",),
    "trade_eligible_date": (
        r"(^|_)trade_eligib(le|ility)(_date)?($|_)",
        r"(^|_)eligible_to_be_traded(_date)?($|_)",
    ),
    "aggregation_eligible_date": (
        r"(^|_)aggregation_eligib(le|ility)(_date)?($|_)",
        r"(^|_)aggregate_eligib(le|ility)(_date)?($|_)",
    ),
    "aggregation_restricted": (
        r"(^|_)(aggregation|aggregate)(_restricted|_restriction|_prohibited|_allowed)($|_)",
    ),
    "no_trade_clause": (r"(^|_)(no_trade|no_trade_clause|ntc)($|_)",),
    "trade_consent": (r"(^|_)(trade_consent|consent_required|player_consent)($|_)",),
    "trade_bonus": (r"(^|_)(trade_bonus|trade_kicker)($|_)",),
    "poison_pill": (r"(^|_)(poison_pill|ppp)($|_)",),
    "base_year_compensation": (r"(^|_)(base_year_compensation|byc)($|_)",),
    "sign_and_trade": (r"(^|_)(sign_and_trade|s_and_t)($|_)",),
    "extension_restriction": (
        r"(^|_)(extension_trade_restriction|extended_and_traded|extend_and_trade)($|_)",
    ),
    "two_way_status": (r"^(two_way|two_way_status|two_way_contract|is_two_way)$",),
    "team_salary": (r"(^|_)(team_salary|total_team_salary|payroll|tax_salary)($|_)",),
    "salary_cap": (r"(^|_)(salary_cap|cap_amount|cap_threshold)($|_)",),
    "tax_level": (r"(^|_)(tax_level|luxury_tax|tax_threshold)($|_)",),
    "first_apron": (r"(^|_)(first_apron|apron_1|first_tax_apron)($|_)",),
    "second_apron": (r"(^|_)(second_apron|apron_2|second_tax_apron)($|_)",),
    "hard_cap": (r"(^|_)(hard_cap|hard_capped|hard_cap_status|hard_cap_level)($|_)",),
    "cap_room": (r"(^|_)(cap_room|room_under_cap|salary_cap_room)($|_)",),
    "standard_roster_count": (
        r"(^|_)(standard_roster_count|standard_contract_count|active_roster_count)($|_)",
    ),
    "two_way_count": (r"(^|_)(two_way_count|two_way_roster_count)($|_)",),
    "trade_exception": (
        r"(^|_)(trade_exception|traded_player_exception|tpe)(_amount|_id|_expiry)?($|_)",
    ),
    "cash_consideration": (r"(^|_)(cash_consideration|cash_sent|cash_received)($|_)",),
}

REQUIREMENT_GROUPS: tuple[dict[str, Any], ...] = (
    {
        "gate_order": 1,
        "group_id": "package_identity_and_aggregate_salary",
        "description": "Teams, player IDs, aggregate outgoing salary, and the prior salary precheck.",
        "required_concepts": (),
        "package_native": True,
        "next_action": "Reuse the validated V6 package fields.",
    },
    {
        "gate_order": 2,
        "group_id": "trade_date_and_season_context",
        "description": "Exact transaction date and league-year context for every time-sensitive restriction.",
        "required_concepts": ("trade_date", "season"),
        "package_native": False,
        "next_action": "Identify one authoritative trade-date and league-year source or configuration.",
    },
    {
        "gate_order": 3,
        "group_id": "player_contract_and_trade_salary_detail",
        "description": "Per-player salary and contract attributes, including trade-bonus, poison-pill, and BYC adjustments.",
        "required_concepts": (
            "player_id",
            "team_id",
            "trade_salary",
            "contract_type",
            "trade_bonus",
            "poison_pill",
            "base_year_compensation",
        ),
        "package_native": False,
        "next_action": "Validate a player-level contract source covering every player in the 149,141-package queue.",
    },
    {
        "gate_order": 4,
        "group_id": "player_transaction_restrictions",
        "description": "Trade eligibility, recent acquisition aggregation, consent, sign-and-trade, extension, and two-way status.",
        "required_concepts": (
            "player_id",
            "signed_date",
            "acquired_date",
            "trade_eligible_date",
            "aggregation_eligible_date",
            "aggregation_restricted",
            "no_trade_clause",
            "trade_consent",
            "sign_and_trade",
            "extension_restriction",
            "two_way_status",
        ),
        "package_native": False,
        "next_action": "Validate a player restriction table as of the modeled trade date.",
    },
    {
        "gate_order": 5,
        "group_id": "team_cap_apron_and_hard_cap",
        "description": "Pre-trade team salary, cap room, apron position, and hard-cap state for both teams.",
        "required_concepts": (
            "team_id",
            "as_of_date",
            "team_salary",
            "salary_cap",
            "tax_level",
            "first_apron",
            "second_apron",
            "hard_cap",
            "cap_room",
        ),
        "package_native": False,
        "next_action": "Validate a 30-team cap and apron snapshot for the modeled trade date.",
    },
    {
        "gate_order": 6,
        "group_id": "post_trade_roster_limits",
        "description": "Standard-contract and two-way roster counts before and after each package.",
        "required_concepts": ("team_id", "as_of_date", "standard_roster_count", "two_way_count"),
        "package_native": False,
        "next_action": "Validate team roster counts or a roster table from which both counts can be derived.",
    },
    {
        "gate_order": 7,
        "group_id": "exceptions_and_cash_policy",
        "description": "Trade exceptions and cash consideration if the evaluator will allow either mechanism.",
        "required_concepts": ("team_id", "trade_exception", "cash_consideration"),
        "package_native": False,
        "optional_with_conservative_policy": True,
        "next_action": "Either validate exception/cash data or configure the evaluator to forbid both mechanisms.",
    },
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        help="Project root. Defaults to the parent of src when the script is saved in src.",
    )
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


def normalize_field_name(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", str(value).strip().lower())
    return normalized.strip("_")


def match_concepts(fields: Iterable[str]) -> dict[str, list[str]]:
    matches: dict[str, list[str]] = {}
    normalized_pairs = [(str(field), normalize_field_name(str(field))) for field in fields]
    for concept, patterns in CONCEPT_PATTERNS.items():
        concept_matches = sorted(
            {
                original
                for original, normalized in normalized_pairs
                if any(re.search(pattern, normalized) for pattern in patterns)
            }
        )
        if concept_matches:
            matches[concept] = concept_matches
    return matches


def split_player_ids(value: Any) -> list[str]:
    if value is None:
        return []
    text = str(value).strip()
    if not text:
        return []
    return [part.strip() for part in re.split(r"\s*[|;,]\s*", text) if part.strip()]


def should_exclude_source(path: Path) -> bool:
    lowered = str(path).lower().replace("\\", "/")
    if path.name in PACKAGE_FILES.values():
        return True
    return any(token in lowered for token in EXCLUDED_FILENAME_TOKENS)


def flatten_json_keys(value: Any, prefix: str = "", depth: int = 0) -> list[str]:
    if depth > 2:
        return []
    keys: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key)
            qualified = f"{prefix}_{key_text}" if prefix else key_text
            keys.extend((key_text, qualified))
            keys.extend(flatten_json_keys(child, qualified, depth + 1))
    elif isinstance(value, list) and value:
        keys.extend(flatten_json_keys(value[0], prefix, depth + 1))
    return sorted(set(keys))


def read_source_fields(pl: Any, path: Path) -> tuple[list[str], str]:
    try:
        if path.suffix.lower() == ".parquet":
            return list(pl.read_parquet_schema(str(path)).keys()), ""
        if path.suffix.lower() == ".csv":
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                return [str(value) for value in next(csv.reader(handle), [])], ""
        if path.suffix.lower() == ".json":
            if path.stat().st_size > 20_000_000:
                return [], "json_larger_than_20mb_skipped"
            with path.open("r", encoding="utf-8-sig") as handle:
                return flatten_json_keys(json.load(handle)), ""
    except Exception as exc:
        return [], f"{type(exc).__name__}: {exc}"
    return [], "unsupported_extension"


def source_search_paths(root: Path) -> list[Path]:
    search_roots = [root / "data", root / "outputs"]
    paths: set[Path] = set()
    for search_root in search_roots:
        if not search_root.is_dir():
            continue
        for extension in STRUCTURED_EXTENSIONS:
            paths.update(path for path in search_root.rglob(f"*{extension}") if path.is_file())
    return sorted(path for path in paths if not should_exclude_source(path))


def relative_display(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def scan_sources(pl: Any, root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in source_search_paths(root):
        fields, read_error = read_source_fields(pl, path)
        concept_matches = match_concepts(fields)
        lowered_name = path.name.lower()
        filename_tokens = [token for token in SOURCE_FILENAME_TOKENS if token in lowered_name]
        if not concept_matches and not filename_tokens and not read_error:
            continue
        concept_columns = {
            concept: columns for concept, columns in sorted(concept_matches.items())
        }
        source_score = 3 * len(concept_matches) + len(filename_tokens)
        rows.append(
            {
                "relative_path": relative_display(path, root),
                "extension": path.suffix.lower(),
                "size_bytes": path.stat().st_size,
                "field_count": len(fields),
                "filename_tokens": "|".join(filename_tokens),
                "matched_concepts": "|".join(sorted(concept_matches)),
                "matched_concept_columns_json": json.dumps(concept_columns, sort_keys=True),
                "source_score": source_score,
                "read_error": read_error,
            }
        )
    return sorted(rows, key=lambda row: (-int(row["source_score"]), str(row["relative_path"])))


def value_counts_map(frame: Any, column: str) -> dict[str, int]:
    result: dict[str, int] = {}
    for row in frame.group_by(column).len().to_dicts():
        key = "<null>" if row[column] is None else str(row[column])
        result[key] = int(row["len"])
    return dict(sorted(result.items()))


def profile_package(pl: Any, label: str, path: Path) -> dict[str, Any]:
    schema = pl.read_parquet_schema(str(path))
    missing_columns = sorted(PACKAGE_REQUIRED_COLUMNS.difference(schema))
    if missing_columns:
        raise RuntimeError(f"{label} is missing required V6 columns: {missing_columns}")

    selected_columns = sorted(PACKAGE_REQUIRED_COLUMNS)
    frame = pl.read_parquet(str(path), columns=selected_columns)
    passed = frame.filter(pl.col("package_right_legality_stage_passed") == True)  # noqa: E712
    manual = frame.filter(pl.col("package_right_legality_manual_review_required") == True)  # noqa: E712
    blocked = frame.filter(pl.col("package_right_legality_blocked") == True)  # noqa: E712

    player_ids: set[str] = set()
    for column in ("side_a_player_ids", "side_b_player_ids"):
        for value in passed.get_column(column).drop_nulls().unique().to_list():
            player_ids.update(split_player_ids(value))
    string_dtype = getattr(pl, "String", pl.Utf8)
    teams = sorted(
        set(passed.get_column("team_a").drop_nulls().cast(string_dtype).unique().to_list())
        | set(passed.get_column("team_b").drop_nulls().cast(string_dtype).unique().to_list())
    )

    base_precheck_counts = value_counts_map(passed, "base_salary_precheck_passed")
    return {
        "label": label,
        "path": str(path),
        "rows": frame.height,
        "columns": len(schema),
        "expected_rows": EXPECTED_PACKAGE_ROWS[label],
        "expected_columns": EXPECTED_PACKAGE_COLUMNS[label],
        "missing_required_columns": missing_columns,
        "right_legality_passed": passed.height,
        "right_legality_manual_review": manual.height,
        "right_legality_blocked": blocked.height,
        "right_legality_status_counts": value_counts_map(frame, "package_right_legality_status"),
        "final_legal_count": int(frame.get_column("optimizer_package_final_legal").sum()),
        "base_salary_precheck_counts_within_passed_queue": base_precheck_counts,
        "unique_player_ids_within_passed_queue": len(player_ids),
        "sample_player_ids_within_passed_queue": sorted(player_ids)[:20],
        "_player_ids_internal": sorted(player_ids),
        "teams_within_passed_queue": teams,
    }


def parse_inventory_concepts(row: dict[str, Any]) -> set[str]:
    return {value for value in str(row.get("matched_concepts", "")).split("|") if value}


def build_requirement_rows(source_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for group in REQUIREMENT_GROUPS:
        required = set(group["required_concepts"])
        if group["package_native"]:
            matched = set()
            missing = set()
            status = "package_native_fields_present"
            top_sources: list[str] = []
        else:
            relevant_sources: list[tuple[int, str, set[str]]] = []
            matched = set()
            for source in source_rows:
                source_concepts = parse_inventory_concepts(source)
                overlap = required.intersection(source_concepts)
                if overlap:
                    matched.update(overlap)
                    relevant_sources.append(
                        (len(overlap), str(source["relative_path"]), overlap)
                    )
            missing = required.difference(matched)
            if not matched:
                status = "no_candidate_evidence_fields_found"
            elif missing:
                status = "candidate_evidence_incomplete"
            else:
                status = "candidate_fields_found_not_validated"
            relevant_sources.sort(key=lambda item: (-item[0], item[1]))
            top_sources = [item[1] for item in relevant_sources[:8]]

        rows.append(
            {
                "gate_order": group["gate_order"],
                "group_id": group["group_id"],
                "description": group["description"],
                "required_for_automatic_release": not bool(
                    group.get("optional_with_conservative_policy", False)
                ),
                "optional_with_conservative_policy": bool(
                    group.get("optional_with_conservative_policy", False)
                ),
                "package_native_coverage": bool(group["package_native"]),
                "required_concepts": "|".join(sorted(required)),
                "matched_candidate_concepts": "|".join(sorted(matched)),
                "missing_candidate_concepts": "|".join(sorted(missing)),
                "readiness_status": status,
                "top_candidate_files": "|".join(top_sources),
                "next_action": group["next_action"],
            }
        )
    return rows


def validate_release(
    propagation_metadata: dict[str, Any],
    package_profiles: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []

    def add(check_name: str, passed: bool, observed: Any, expected: Any) -> None:
        checks.append(
            {
                "check_name": check_name,
                "passed": bool(passed),
                "observed": safe_json(observed),
                "expected": safe_json(expected),
            }
        )

    add("propagation_release_valid", propagation_metadata.get("release_valid") is True,
        propagation_metadata.get("release_valid"), True)
    add("propagation_validation_46_of_46",
        propagation_metadata.get("validation_checks_passed") == 46
        and propagation_metadata.get("validation_checks_total") == 46,
        [propagation_metadata.get("validation_checks_passed"), propagation_metadata.get("validation_checks_total")],
        [46, 46])
    add("propagation_final_legal_unreleased",
        propagation_metadata.get("package_final_legal_status_released") is False,
        propagation_metadata.get("package_final_legal_status_released"), False)

    for label, profile in package_profiles.items():
        expected = EXPECTED_RESULTS[label]
        add(f"{label}_rows", profile["rows"] == EXPECTED_PACKAGE_ROWS[label],
            profile["rows"], EXPECTED_PACKAGE_ROWS[label])
        add(f"{label}_columns", profile["columns"] == EXPECTED_PACKAGE_COLUMNS[label],
            profile["columns"], EXPECTED_PACKAGE_COLUMNS[label])
        add(f"{label}_required_columns", not profile["missing_required_columns"],
            profile["missing_required_columns"], [])
        add(f"{label}_passed_count", profile["right_legality_passed"] == expected["passed"],
            profile["right_legality_passed"], expected["passed"])
        add(f"{label}_manual_count", profile["right_legality_manual_review"] == expected["manual"],
            profile["right_legality_manual_review"], expected["manual"])
        add(f"{label}_blocked_count", profile["right_legality_blocked"] == expected["blocked"],
            profile["right_legality_blocked"], expected["blocked"])
        add(f"{label}_exclusive_partition",
            profile["right_legality_passed"] + profile["right_legality_manual_review"]
            + profile["right_legality_blocked"] == profile["rows"],
            profile["right_legality_passed"] + profile["right_legality_manual_review"]
            + profile["right_legality_blocked"], profile["rows"])
        add(f"{label}_final_legal_zero", profile["final_legal_count"] == 0,
            profile["final_legal_count"], 0)

    global_observed = {
        "rows": sum(profile["rows"] for profile in package_profiles.values()),
        "passed": sum(profile["right_legality_passed"] for profile in package_profiles.values()),
        "manual": sum(profile["right_legality_manual_review"] for profile in package_profiles.values()),
        "blocked": sum(profile["right_legality_blocked"] for profile in package_profiles.values()),
    }
    for key, expected in EXPECTED_GLOBAL.items():
        add(f"global_{key}", global_observed[key] == expected, global_observed[key], expected)
    return checks


def run_self_tests() -> None:
    assert split_player_ids("1|2;3, 4") == ["1", "2", "3", "4"]
    assert split_player_ids("") == []
    concepts = match_concepts(
        ["player_id", "first_apron_amount", "trade_eligibility_date", "two_way_count"]
    )
    assert set(concepts) == {"player_id", "first_apron", "trade_eligible_date", "two_way_count"}
    assert should_exclude_source(Path(PACKAGE_FILES["one_for_one"]))
    assert not should_exclude_source(Path("data/processed/player_contracts_2026.csv"))
    print("Self-tests passed: 5/5")


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
    print("MIXED PLAYER-AND-PICK FULL CBA READINESS AUDIT")
    print("=" * 80)
    print(f"Script version: {SCRIPT_VERSION}")
    print(f"Release name: {RELEASE_NAME}")
    print()

    print("[1/6] Loading propagation metadata and V6 package candidates")
    metadata_path = locate_one(root, PROPAGATION_METADATA_FILENAME)
    with metadata_path.open("r", encoding="utf-8-sig") as handle:
        propagation_metadata = json.load(handle)
    package_paths = {label: locate_one(root, filename) for label, filename in PACKAGE_FILES.items()}

    print("[2/6] Validating the 149,141-package full-CBA queue")
    package_profiles = {
        label: profile_package(pl, label, path) for label, path in package_paths.items()
    }

    print("[3/6] Scanning structured project data for reusable CBA evidence")
    source_rows = scan_sources(pl, root)

    print("[4/6] Building the remaining requirement matrix")
    requirement_rows = build_requirement_rows(source_rows)

    print("[5/6] Validating the non-destructive readiness release")
    validation_rows = validate_release(propagation_metadata, package_profiles)
    audit_valid = all(row["passed"] for row in validation_rows)
    validation_passed = sum(bool(row["passed"]) for row in validation_rows)

    required_groups = [
        row for row in requirement_rows if row["required_for_automatic_release"]
    ]
    required_groups_with_complete_candidate_fields = sum(
        row["readiness_status"] in {
            "package_native_fields_present",
            "candidate_fields_found_not_validated",
        }
        for row in required_groups
    )
    full_cba_automatic_release_ready = False

    combined_player_ids = {
        player_id
        for profile in package_profiles.values()
        for player_id in profile["_player_ids_internal"]
    }
    combined = {
        "rows": sum(profile["rows"] for profile in package_profiles.values()),
        "right_legality_passed": sum(
            profile["right_legality_passed"] for profile in package_profiles.values()
        ),
        "right_legality_manual_review": sum(
            profile["right_legality_manual_review"] for profile in package_profiles.values()
        ),
        "right_legality_blocked": sum(
            profile["right_legality_blocked"] for profile in package_profiles.values()
        ),
        "unique_player_ids": len(combined_player_ids),
        "sample_player_ids": sorted(combined_player_ids)[:20],
        "teams": sorted(
            {
                team
                for profile in package_profiles.values()
                for team in profile["teams_within_passed_queue"]
            }
        ),
    }
    for profile in package_profiles.values():
        profile.pop("_player_ids_internal", None)

    metadata = {
        "script_version": SCRIPT_VERSION,
        "release_name": RELEASE_NAME,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "audit_valid": audit_valid,
        "validation_checks_passed": validation_passed,
        "validation_checks_total": len(validation_rows),
        "propagation_metadata_path": str(metadata_path),
        "propagation_release_name": propagation_metadata.get("release_name"),
        "package_profiles": package_profiles,
        "combined_package_counts": combined,
        "structured_source_candidates_found": len(source_rows),
        "required_groups_total": len(required_groups),
        "required_groups_with_complete_candidate_fields": required_groups_with_complete_candidate_fields,
        "full_cba_automatic_release_ready": full_cba_automatic_release_ready,
        "readiness_note": (
            "This audit locates candidate evidence fields only. Candidate sources must be validated, "
            "joined to every queued player/team, and evaluated under an authoritative 2026-27 CBA "
            "rules configuration before final package legality can be released."
        ),
        "conservative_policy_option": (
            "Trade exceptions and cash may be forbidden by policy if no validated source is available; "
            "all other required groups must be fully evidenced."
        ),
        "requirement_matrix_file": str(outputs / REQUIREMENT_OUTPUT),
        "source_field_inventory_file": str(outputs / SOURCE_FIELD_OUTPUT),
        "validation_file": str(outputs / VALIDATION_OUTPUT),
        "non_destructive": True,
        "package_final_legal_status_released": False,
    }

    print("[6/6] Saving audit metadata, requirements, source fields, and validation")
    with (outputs / METADATA_OUTPUT).open("w", encoding="utf-8") as handle:
        json.dump(safe_json(metadata), handle, indent=2, sort_keys=False)
        handle.write("\n")
    write_csv(
        outputs / REQUIREMENT_OUTPUT,
        [
            "gate_order",
            "group_id",
            "description",
            "required_for_automatic_release",
            "optional_with_conservative_policy",
            "package_native_coverage",
            "required_concepts",
            "matched_candidate_concepts",
            "missing_candidate_concepts",
            "readiness_status",
            "top_candidate_files",
            "next_action",
        ],
        requirement_rows,
    )
    write_csv(
        outputs / SOURCE_FIELD_OUTPUT,
        [
            "relative_path",
            "extension",
            "size_bytes",
            "field_count",
            "filename_tokens",
            "matched_concepts",
            "matched_concept_columns_json",
            "source_score",
            "read_error",
        ],
        source_rows,
    )
    write_csv(
        outputs / VALIDATION_OUTPUT,
        ["check_name", "passed", "observed", "expected"],
        validation_rows,
    )

    print()
    print("=" * 80)
    print("FULL CBA READINESS AUDIT COMPLETE")
    print("=" * 80)
    print(f"Packages audited: {combined['rows']:,}")
    print(f"Packages queued for full CBA validation: {combined['right_legality_passed']:,}")
    print(f"Packages retained in manual review: {combined['right_legality_manual_review']:,}")
    print(f"Packages already blocked: {combined['right_legality_blocked']:,}")
    print(f"Structured source candidates found: {len(source_rows):,}")
    print(f"Validation checks passed: {validation_passed}/{len(validation_rows)}")
    print(f"Audit valid: {audit_valid}")
    print(f"Final package legality released: {full_cba_automatic_release_ready}")
    print()
    print("NEXT REVIEW FILE")
    print(outputs / METADATA_OUTPUT)
    print()
    print("SAVED FILES")
    for filename in (METADATA_OUTPUT, REQUIREMENT_OUTPUT, SOURCE_FIELD_OUTPUT, VALIDATION_OUTPUT):
        print(outputs / filename)

    return 0 if audit_valid else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise