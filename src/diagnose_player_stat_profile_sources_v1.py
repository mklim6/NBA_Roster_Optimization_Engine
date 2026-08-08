from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
APP_DATA = ROOT / "app_data"
PROCESSED = ROOT / "data" / "processed"
OUTPUTS = ROOT / "outputs"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from freeform_trade_machine_engine_v3 import load_runtime_data  # noqa: E402


SCRIPT_VERSION = "player-stat-profile-source-diagnostic-v1-2026-08-08"
REPORT_PATH = OUTPUTS / "player_stat_profile_source_diagnostic_v1.json"

STAT_GROUPS: dict[str, tuple[str, ...]] = {
    "identity": (
        "player_id",
        "person_id",
        "player_name",
        "player_display_name",
        "display_name",
        "name",
        "team",
        "team_abbreviation",
        "position",
        "age",
    ),
    "playing_time": (
        "games",
        "gp",
        "games_played",
        "minutes",
        "min",
        "mpg",
        "minutes_per_game",
    ),
    "scoring": (
        "points",
        "pts",
        "ppg",
        "points_per_game",
        "field_goals",
        "fgm",
        "fga",
        "fg_pct",
        "three",
        "3p",
        "three_point",
        "ftm",
        "fta",
        "ft_pct",
        "true_shooting",
        "ts_pct",
        "usage",
        "usg",
    ),
    "rebounding": (
        "rebounds",
        "reb",
        "rpg",
        "rebounds_per_game",
        "offensive_rebounds",
        "oreb",
        "defensive_rebounds",
        "dreb",
        "reb_pct",
    ),
    "playmaking": (
        "assists",
        "ast",
        "apg",
        "assists_per_game",
        "assist_pct",
        "ast_pct",
        "turnovers",
        "tov",
        "turnover_pct",
    ),
    "defense": (
        "steals",
        "stl",
        "spg",
        "blocks",
        "blk",
        "bpg",
        "personal_fouls",
        "pf",
        "deflections",
    ),
    "advanced": (
        "offensive_rating",
        "defensive_rating",
        "net_rating",
        "pace",
        "pie",
        "bpm",
        "vorp",
        "win_shares",
        "epm",
        "raptor",
        "lebron",
    ),
    "projection": (
        "overall",
        "overall_rating",
        "potential",
        "future",
        "projection",
        "expected_contribution",
        "upside",
        "downside",
        "survival",
        "rotation_probability",
    ),
}

SAMPLE_NAMES = {
    "Nikola Jokic",
    "Nikola Jokić",
    "Stephen Curry",
    "Victor Wembanyama",
    "Trae Young",
    "Jalen Duren",
    "Julius Randle",
}


def normalize(value: Any) -> str:
    return str(value or "").strip().lower()


def finite_number(value: Any) -> bool:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(result)


def runtime_field_report(
    records: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    key_counts: Counter[str] = Counter()
    numeric_counts: Counter[str] = Counter()
    samples: dict[str, dict[str, Any]] = {}

    for player_id, record in records.items():
        for key, value in record.items():
            if value is None or value == "":
                continue
            key_counts[key] += 1
            if finite_number(value):
                numeric_counts[key] += 1

        name = (
            record.get("player_name")
            or record.get("player_display_name")
            or record.get("display_name")
            or record.get("name")
            or ""
        )
        if str(name).strip() in SAMPLE_NAMES:
            samples[str(name).strip()] = {
                "player_id": player_id,
                **record,
            }

    grouped_fields: dict[str, list[dict[str, Any]]] = {}
    for group, tokens in STAT_GROUPS.items():
        matches = []
        for key, count in key_counts.items():
            normalized_key = normalize(key)
            if any(token in normalized_key for token in tokens):
                matches.append(
                    {
                        "field": key,
                        "non_null_records": count,
                        "numeric_records": numeric_counts[key],
                    }
                )
        grouped_fields[group] = sorted(
            matches,
            key=lambda row: (
                -row["non_null_records"],
                row["field"],
            ),
        )

    return {
        "player_records": len(records),
        "unique_fields": len(key_counts),
        "all_fields": [
            {
                "field": key,
                "non_null_records": count,
                "numeric_records": numeric_counts[key],
            }
            for key, count in sorted(
                key_counts.items(),
                key=lambda item: (-item[1], item[0]),
            )
        ],
        "grouped_fields": grouped_fields,
        "sample_players": samples,
    }


def candidate_files() -> list[Path]:
    roots = [
        APP_DATA,
        PROCESSED,
        OUTPUTS,
    ]
    keywords = (
        "player",
        "rating",
        "projection",
        "performance",
        "stat",
        "board",
        "contribution",
    )
    extensions = {
        ".parquet",
        ".csv",
        ".json",
    }

    candidates: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if (
                path.is_file()
                and path.suffix.lower() in extensions
                and any(
                    keyword in path.name.lower()
                    for keyword in keywords
                )
            ):
                candidates.append(path)

    return sorted(
        candidates,
        key=lambda value: str(value).lower(),
    )


def dataframe_schema(path: Path) -> tuple[list[str], int | None]:
    suffix = path.suffix.lower()

    if suffix == ".parquet":
        frame = pd.read_parquet(path)
        return list(frame.columns), len(frame)

    if suffix == ".csv":
        frame = pd.read_csv(path, nrows=5)
        return list(frame.columns), None

    raise ValueError(
        f"Unsupported tabular extension: {path.suffix}"
    )


def json_schema(path: Path) -> tuple[list[str], int | None]:
    payload = json.loads(path.read_text(encoding="utf-8"))

    if isinstance(payload, list):
        rows = [
            row for row in payload
            if isinstance(row, dict)
        ]
        keys = sorted(
            {
                key
                for row in rows[:1000]
                for key in row
            }
        )
        return keys, len(rows)

    if isinstance(payload, dict):
        if all(
            isinstance(value, dict)
            for value in payload.values()
        ):
            rows = list(payload.values())
            keys = sorted(
                {
                    key
                    for row in rows[:1000]
                    for key in row
                }
            )
            return keys, len(rows)

        return sorted(payload), None

    return [], None


def profile_relevant_columns(
    columns: list[str],
) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = defaultdict(list)

    for column in columns:
        normalized_column = normalize(column)
        for group, tokens in STAT_GROUPS.items():
            if any(
                token in normalized_column
                for token in tokens
            ):
                grouped[group].append(column)

    return {
        group: sorted(set(values))
        for group, values in grouped.items()
        if values
    }


def inspect_candidate_file(
    path: Path,
) -> dict[str, Any]:
    relative = str(path.relative_to(ROOT))

    try:
        if path.suffix.lower() == ".json":
            columns, rows = json_schema(path)
        else:
            columns, rows = dataframe_schema(path)
    except Exception as exc:
        return {
            "path": relative,
            "readable": False,
            "error": f"{type(exc).__name__}: {exc}",
        }

    grouped = profile_relevant_columns(columns)
    stat_group_count = sum(
        group in grouped
        for group in (
            "playing_time",
            "scoring",
            "rebounding",
            "playmaking",
            "defense",
        )
    )

    return {
        "path": relative,
        "readable": True,
        "rows": rows,
        "column_count": len(columns),
        "stat_group_count": stat_group_count,
        "profile_relevant_columns": grouped,
        "all_columns": columns,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--max-files",
        type=int,
        default=100,
    )
    args = parser.parse_args()

    runtime = load_runtime_data()
    runtime_report = runtime_field_report(
        runtime.ratings_by_id
    )

    file_reports = [
        inspect_candidate_file(path)
        for path in candidate_files()[: args.max_files]
    ]
    ranked_files = sorted(
        file_reports,
        key=lambda row: (
            -int(row.get("stat_group_count", -1)),
            -int(row.get("column_count", -1)),
            row["path"],
        ),
    )

    report = {
        "script": SCRIPT_VERSION,
        "runtime_ratings": runtime_report,
        "candidate_files_scanned": len(file_reports),
        "ranked_candidate_files": ranked_files,
    }

    OUTPUTS.mkdir(
        parents=True,
        exist_ok=True,
    )
    REPORT_PATH.write_text(
        json.dumps(
            report,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )

    print("=" * 88)
    print("PLAYER STAT PROFILE SOURCE DIAGNOSTIC")
    print("=" * 88)
    print(
        "Runtime rating records:",
        runtime_report["player_records"],
    )
    print(
        "Runtime unique fields:",
        runtime_report["unique_fields"],
    )

    print("\nRUNTIME FIELD GROUPS")
    for group, fields in (
        runtime_report["grouped_fields"].items()
    ):
        names = [
            row["field"]
            for row in fields[:20]
        ]
        print(f"{group:14s}: {', '.join(names) or '(none)'}")

    print("\nSAMPLE PLAYER RUNTIME RECORDS")
    if runtime_report["sample_players"]:
        for name, record in (
            runtime_report["sample_players"].items()
        ):
            print(f"\n{name}")
            print(
                json.dumps(
                    record,
                    indent=2,
                    default=str,
                )
            )
    else:
        print("No requested sample names were found.")

    print("\nTOP LOCAL DATA SOURCES")
    for item in ranked_files[:15]:
        if not item.get("readable"):
            print(
                f"- {item['path']} | ERROR: "
                f"{item['error']}"
            )
            continue

        groups = ", ".join(
            item["profile_relevant_columns"]
        )
        print(
            f"- {item['path']} | "
            f"columns={item['column_count']} | "
            f"rows={item['rows']} | "
            f"groups={groups or '(none)'}"
        )

    print(f"\nFull report: {REPORT_PATH}")
    print("\nPLAYER STAT PROFILE SOURCE DIAGNOSTIC PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
