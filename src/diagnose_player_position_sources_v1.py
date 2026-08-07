from __future__ import annotations

import json
import math
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
OUTPUTS = ROOT / "outputs"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from freeform_trade_machine_engine_v3 import (  # noqa: E402
    load_runtime_data,
)


SCRIPT_VERSION = (
    "player-position-source-diagnostic-v1-2026-08-08"
)
OUTPUT_PATH = (
    OUTPUTS / "player_position_source_diagnostic_v1.json"
)

POSITION_VALUE_PATTERN = re.compile(
    r"^(PG|SG|SF|PF|C|G|F|G-F|F-G|F-C|C-F|"
    r"PG-SG|SG-PG|SG-SF|SF-SG|SF-PF|PF-SF|"
    r"PF-C|C-PF)([/,\-\s].*)?$",
    re.IGNORECASE,
)

COLUMN_NAME_PATTERN = re.compile(
    r"(position|(^|_)pos($|_)|height|role|archetype)",
    re.IGNORECASE,
)

SAMPLE_PLAYER_NAMES = (
    "Julius Randle",
    "Michael Porter Jr.",
    "Day'Ron Sharpe",
    "Trae Young",
    "Joel Embiid",
)


def clean_value(value: Any) -> str:
    if value is None:
        return ""

    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass

    text = re.sub(r"\s+", " ", str(value)).strip()

    if text.casefold() in {
        "",
        "nan",
        "none",
        "null",
        "<na>",
    }:
        return ""

    return text


def top_values(
    series: pd.Series,
    limit: int = 12,
) -> list[dict[str, Any]]:
    values = [
        clean_value(value)
        for value in series.tolist()
    ]
    values = [
        value
        for value in values
        if value
    ]
    counts = Counter(values)

    return [
        {
            "value": value,
            "count": count,
        }
        for value, count
        in counts.most_common(limit)
    ]


def position_match_count(
    series: pd.Series,
) -> int:
    return sum(
        bool(
            POSITION_VALUE_PATTERN.match(
                clean_value(value)
            )
        )
        for value in series.tolist()
        if clean_value(value)
    )


def find_name_column(
    frame: pd.DataFrame,
) -> str | None:
    for column in (
        "player_name",
        "player_display_name",
        "display_name",
        "name",
    ):
        if column in frame.columns:
            return column

    return None


def sample_player_records(
    frame: pd.DataFrame,
    candidate_columns: list[str],
) -> list[dict[str, Any]]:
    name_column = find_name_column(frame)

    if name_column is None:
        return []

    normalized_names = frame[name_column].map(
        lambda value: clean_value(value).casefold()
    )
    records = []

    for player_name in SAMPLE_PLAYER_NAMES:
        matches = frame[
            normalized_names
            == player_name.casefold()
        ]

        if matches.empty:
            continue

        row = matches.iloc[0]
        record = {
            "player_name": player_name,
        }

        if "player_id" in frame.columns:
            record["player_id"] = clean_value(
                row.get("player_id")
            )

        for column in candidate_columns:
            value = clean_value(
                row.get(column)
            )

            if value:
                record[column] = value

        records.append(record)

    return records


def inspect_frame(
    name: str,
    frame: pd.DataFrame,
) -> dict[str, Any]:
    candidate_columns = [
        str(column)
        for column in frame.columns
        if COLUMN_NAME_PATTERN.search(
            str(column)
        )
    ]
    candidate_details = []

    for column in candidate_columns:
        series = frame[column]
        nonblank = sum(
            bool(clean_value(value))
            for value in series.tolist()
        )
        matched = position_match_count(series)

        candidate_details.append(
            {
                "column": column,
                "dtype": str(series.dtype),
                "rows": int(len(series)),
                "nonblank": int(nonblank),
                "coverage": round(
                    nonblank / len(series),
                    4,
                )
                if len(series)
                else 0.0,
                "position_like_values": int(matched),
                "position_like_share": round(
                    matched / nonblank,
                    4,
                )
                if nonblank
                else 0.0,
                "unique_nonblank": int(
                    series.map(clean_value)
                    .replace("", pd.NA)
                    .nunique(dropna=True)
                ),
                "top_values": top_values(series),
            }
        )

    object_column_matches = []

    for column in frame.columns:
        series = frame[column]

        if not (
            pd.api.types.is_object_dtype(series)
            or pd.api.types.is_string_dtype(series)
        ):
            continue

        nonblank = sum(
            bool(clean_value(value))
            for value in series.tolist()
        )

        if not nonblank:
            continue

        matched = position_match_count(series)

        if matched:
            object_column_matches.append(
                {
                    "column": str(column),
                    "nonblank": int(nonblank),
                    "position_like_values": int(matched),
                    "position_like_share": round(
                        matched / nonblank,
                        4,
                    ),
                    "top_values": top_values(series),
                }
            )

    object_column_matches.sort(
        key=lambda item: (
            -item["position_like_share"],
            -item["position_like_values"],
            item["column"],
        )
    )
    candidate_details.sort(
        key=lambda item: (
            -item["position_like_share"],
            -item["coverage"],
            item["column"],
        )
    )

    return {
        "source": name,
        "rows": int(len(frame)),
        "columns": int(len(frame.columns)),
        "candidate_columns": candidate_details,
        "position_value_columns": (
            object_column_matches
        ),
        "sample_player_records": (
            sample_player_records(
                frame,
                candidate_columns,
            )
        ),
    }


def main() -> int:
    runtime = load_runtime_data()
    frames = {
        "trade_pool": runtime.trade_pool,
        "financial": runtime.financial,
        "market": runtime.market,
        "ratings": runtime.ratings,
        "player_cba": runtime.player_cba,
    }
    sources = [
        inspect_frame(name, frame)
        for name, frame in frames.items()
    ]

    ranked_candidates = []

    for source in sources:
        for candidate in (
            source["candidate_columns"]
        ):
            ranked_candidates.append(
                {
                    "source": source["source"],
                    **candidate,
                }
            )

        for candidate in (
            source["position_value_columns"]
        ):
            ranked_candidates.append(
                {
                    "source": source["source"],
                    "discovered_by_values": True,
                    **candidate,
                }
            )

    ranked_candidates.sort(
        key=lambda item: (
            -item.get(
                "position_like_share",
                0.0,
            ),
            -item.get(
                "position_like_values",
                0,
            ),
            -item.get("coverage", 0.0),
            item["source"],
            item["column"],
        )
    )

    report = {
        "script": SCRIPT_VERSION,
        "runtime_counts": {
            "trade_pool_players": int(
                len(runtime.trade_pool)
            ),
            "rating_players": int(
                len(runtime.ratings)
            ),
            "player_cba_rows": int(
                len(runtime.player_cba)
            ),
        },
        "ranked_candidates": (
            ranked_candidates[:30]
        ),
        "sources": sources,
    }

    OUTPUTS.mkdir(
        parents=True,
        exist_ok=True,
    )
    OUTPUT_PATH.write_text(
        json.dumps(
            report,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(
        json.dumps(
            {
                "script": SCRIPT_VERSION,
                "runtime_counts": (
                    report["runtime_counts"]
                ),
                "top_candidates": (
                    report[
                        "ranked_candidates"
                    ][:12]
                ),
                "output": str(OUTPUT_PATH),
            },
            indent=2,
        )
    )
    print(
        "\nPLAYER POSITION SOURCE DIAGNOSTIC PASSED"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())