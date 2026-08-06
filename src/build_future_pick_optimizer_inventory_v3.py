from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


SCRIPT_VERSION = (
    "future-pick-optimizer-inventory-build-v3-2026-08-04"
)

RELEASE_NAME = (
    "future_pick_optimizer_inventory_2027_2029_final_v1"
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]

DIRECT_RIGHTS_PATH = (
    PROJECT_ROOT
    / "outputs"
    / "future_pick_optimizer_direct_candidate_rows_v1.csv"
)

COMPONENT_RIGHTS_PATH = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "future_pick_optimizer_candidate_rights_discovery_v1.parquet"
)

COMPONENT_PRIMARY_ROWS_PATH = (
    PROJECT_ROOT
    / "outputs"
    / "future_pick_optimizer_component_primary_rows_v1.csv"
)

FILE_CATALOG_PATH = (
    PROJECT_ROOT
    / "outputs"
    / "future_pick_optimizer_candidate_rights_file_catalog_v1.csv"
)

SOURCE_OVERLAP_AUDIT_PATH = (
    PROJECT_ROOT
    / "outputs"
    / "future_pick_optimizer_source_asset_overlap_audit_v1.csv"
)

READINESS_AUDIT_PATH = (
    PROJECT_ROOT
    / "outputs"
    / "future_pick_optimizer_inventory_readiness_audit_v1.csv"
)

FINAL_VALUATION_PATH = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "future_pick_claim_value_layer_2027_2029_final.parquet"
)

FINAL_TEAM_SUMMARY_PATH = (
    PROJECT_ROOT
    / "outputs"
    / "future_pick_candidate_team_value_summary_final.csv"
)

PROCESSED_DIRECTORY = (
    PROJECT_ROOT
    / "data"
    / "processed"
)

OUTPUT_DIRECTORY = PROJECT_ROOT / "outputs"

FINAL_INVENTORY_PARQUET_PATH = (
    PROCESSED_DIRECTORY
    / "future_pick_optimizer_inventory_2027_2029_final.parquet"
)

FINAL_INVENTORY_CSV_PATH = (
    PROCESSED_DIRECTORY
    / "future_pick_optimizer_inventory_2027_2029_final.csv"
)

TEAM_RECONCILIATION_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_optimizer_inventory_team_reconciliation_final.csv"
)

SOURCE_COVERAGE_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_optimizer_inventory_source_coverage_final.csv"
)

VALIDATION_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_optimizer_inventory_validation_final.csv"
)

INVENTORY_SUMMARY_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_optimizer_inventory_summary_final.csv"
)

MANIFEST_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_optimizer_inventory_manifest_final.csv"
)

METADATA_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_optimizer_inventory_metadata_final.json"
)


FINAL_TEAM_VALUE_COLUMN = (
    "candidate_total_pick_asset_value_score_final"
)

EXPECTED_DIRECT_RIGHT_ROWS = 99
EXPECTED_COMPONENT_RIGHT_ROWS = 66
EXPECTED_INVENTORY_ROWS = 165
EXPECTED_TEAM_ROWS = 30

VALUE_TOLERANCE = 1e-6
PICK_COUNT_TOLERANCE = 1e-10


def normalize_columns(
    frame: pd.DataFrame,
) -> pd.DataFrame:
    output = frame.copy()

    output.columns = [
        str(column)
        .strip()
        .lower()
        .replace(" ", "_")
        for column in output.columns
    ]

    return output


def clean_text(
    value: Any,
) -> str:
    if value is None:
        return ""

    try:
        if pd.isna(value):
            return ""
    except (
        TypeError,
        ValueError,
    ):
        pass

    return re.sub(
        r"\s+",
        " ",
        str(value),
    ).strip()


def numeric_value(
    value: Any,
) -> float:
    return float(
        pd.to_numeric(
            pd.Series(
                [
                    value
                ]
            ),
            errors="coerce",
        ).iloc[
            0
        ]
    )


def finite_or_nan(
    value: Any,
) -> float:
    number = numeric_value(
        value
    )

    return (
        number
        if np.isfinite(
            number
        )
        else np.nan
    )


def finite_or_zero(
    value: Any,
) -> float:
    number = finite_or_nan(
        value
    )

    return (
        number
        if np.isfinite(
            number
        )
        else 0.0
    )


def json_safe(
    value: Any,
) -> Any:
    if isinstance(
        value,
        dict,
    ):
        return {
            str(key): json_safe(item)
            for key, item in value.items()
        }

    if isinstance(
        value,
        (
            list,
            tuple,
        ),
    ):
        return [
            json_safe(item)
            for item in value
        ]

    if isinstance(
        value,
        np.integer,
    ):
        return int(value)

    if isinstance(
        value,
        np.floating,
    ):
        return (
            None
            if np.isnan(value)
            else float(value)
        )

    if isinstance(
        value,
        float,
    ):
        return (
            None
            if math.isnan(value)
            else value
        )

    try:
        if pd.isna(value):
            return None
    except (
        TypeError,
        ValueError,
    ):
        pass

    return value


def require_columns(
    frame: pd.DataFrame,
    columns: list[str],
    frame_name: str,
) -> None:
    missing = [
        column
        for column in columns
        if column not in frame.columns
    ]

    if missing:
        raise ValueError(
            f"{frame_name} is missing required columns:\n"
            + "\n".join(
                missing
            )
        )


def parse_bool_series(
    series: pd.Series,
) -> pd.Series:
    if pd.api.types.is_bool_dtype(
        series
    ):
        return series.fillna(
            False
        ).astype(
            bool
        )

    normalized = (
        series
        .fillna("")
        .astype(str)
        .str.strip()
        .str.lower()
    )

    return normalized.isin(
        {
            "true",
            "1",
            "yes",
            "passed",
        }
    )


def parse_source_assets(
    value: Any,
) -> list[str]:
    text = clean_text(
        value
    ).upper()

    if not text:
        return []

    matches = re.findall(
        r"20(?:27|28|29)_R[12]_[A-Z]{3}",
        text,
    )

    if matches:
        return sorted(
            set(
                matches
            )
        )

    return sorted(
        {
            token.strip()
            for token in re.split(
                r"[|,;]+",
                text,
            )
            if token.strip()
        }
    )


TEAM_NAME_TO_CODE = {
    "ATLANTA": "ATL",
    "BOSTON": "BOS",
    "BROOKLYN": "BKN",
    "CHARLOTTE": "CHA",
    "CHICAGO": "CHI",
    "CLEVELAND": "CLE",
    "DALLAS": "DAL",
    "DENVER": "DEN",
    "DETROIT": "DET",
    "GOLDEN STATE": "GSW",
    "HOUSTON": "HOU",
    "INDIANA": "IND",
    "LOS ANGELES CLIPPERS": "LAC",
    "LA CLIPPERS": "LAC",
    "LOS ANGELES LAKERS": "LAL",
    "LA LAKERS": "LAL",
    "MEMPHIS": "MEM",
    "MIAMI": "MIA",
    "MILWAUKEE": "MIL",
    "MINNESOTA": "MIN",
    "NEW ORLEANS": "NOP",
    "NEW YORK": "NYK",
    "OKLAHOMA CITY": "OKC",
    "ORLANDO": "ORL",
    "PHILADELPHIA": "PHI",
    "PHOENIX": "PHX",
    "PORTLAND": "POR",
    "SACRAMENTO": "SAC",
    "SAN ANTONIO": "SAS",
    "TORONTO": "TOR",
    "UTAH": "UTA",
    "WASHINGTON": "WAS",
}

VALID_TEAM_CODES = {
    "ATL", "BOS", "BKN", "CHA", "CHI", "CLE", "DAL", "DEN",
    "DET", "GSW", "HOU", "IND", "LAC", "LAL", "MEM", "MIA",
    "MIL", "MIN", "NOP", "NYK", "OKC", "ORL", "PHI", "PHX",
    "POR", "SAC", "SAS", "TOR", "UTA", "WAS",
}


def parse_raw_component_payload(
    value: Any,
) -> dict[str, Any]:
    text = clean_text(
        value
    )

    if not text:
        return {}

    try:
        parsed = json.loads(
            text
        )
    except json.JSONDecodeError:
        return {}

    return parsed if isinstance(
        parsed,
        dict,
    ) else {}


def extract_team_codes_from_text(
    value: Any,
) -> list[str]:
    text = clean_text(
        value
    ).upper()

    teams: set[str] = set()

    for name, code in TEAM_NAME_TO_CODE.items():
        if re.search(
            rf"\\b{re.escape(name)}\\b",
            text,
        ):
            teams.add(
                code
            )

    for token in re.findall(
        r"\\b[A-Z]{3}\\b",
        text,
    ):
        if token in VALID_TEAM_CODES:
            teams.add(
                token
            )

    return sorted(
        teams
    )


def infer_component_year(
    value: Any,
) -> int | None:
    years = sorted({
        int(year)
        for year in re.findall(
            r"\\b20(?:27|28|29)\\b",
            clean_text(value),
        )
    })

    return years[0] if len(years) == 1 else None


def infer_component_round(
    value: Any,
) -> int | None:
    text = clean_text(
        value
    ).lower()

    first = bool(re.search(
        r"\\b(?:1st|first)(?:[- ]round|s\\b|\\s+picks?\\b)?",
        text,
    ))

    second = bool(re.search(
        r"\\b(?:2nd|second)(?:[- ]round|s\\b|\\s+picks?\\b)?",
        text,
    ))

    if first and not second:
        return 1

    if second and not first:
        return 2

    return None


def recover_component_source_assets(
    row_dict: dict[str, Any],
) -> tuple[list[str], str]:
    assets = parse_source_assets(
        row_dict.get(
            "source_assets",
            "",
        )
    )

    if assets:
        return assets, "normalized_source_assets"

    raw = parse_raw_component_payload(
        row_dict.get(
            "raw_row_json",
            "",
        )
    )

    assets = parse_source_assets(
        json.dumps(
            json_safe(raw),
            sort_keys=True,
        )
    )

    if assets:
        return assets, "raw_json_explicit_asset_keys"

    description = " ".join(
        clean_text(raw.get(field, ""))
        for field in [
            "right_description",
            "description",
            "right_name",
            "selection_rule",
            "allocation_rule",
            "source_description",
            "source_teams",
            "sources",
        ]
        if clean_text(raw.get(field, ""))
    )

    component_file = clean_text(
        row_dict.get(
            "candidate_right_file",
            "",
        )
    )

    combined = " ".join(
        value
        for value in [
            description,
            component_file.replace("_", " "),
        ]
        if value
    )

    year = infer_component_year(
        combined
    )

    round_number = infer_component_round(
        combined
    )

    teams = extract_team_codes_from_text(
        description
    )

    if not teams:
        teams = extract_team_codes_from_text(
            component_file.replace("_", " ")
        )

    if year is None or round_number is None or not teams:
        return [], "unresolved"

    assets = sorted({
        f"{year}_R{round_number}_{team}"
        for team in teams
    })

    declared_count = finite_or_nan(
        raw.get(
            "source_asset_count",
            row_dict.get(
                "source_asset_count",
                np.nan,
            ),
        )
    )

    if (
        np.isfinite(declared_count)
        and int(declared_count) != len(assets)
    ):
        raise RuntimeError(
            "Recovered component sources do not match the declared "
            "source-asset count:\\n"
            + json.dumps(
                {
                    "candidate_right_file": component_file,
                    "candidate_team": row_dict.get("candidate_team", ""),
                    "recovered_assets": assets,
                    "declared_source_asset_count": int(declared_count),
                    "raw_row_json": raw,
                },
                indent=2,
                sort_keys=True,
            )
        )

    return assets, "legacy_description_inference"


SOURCE_ALLOCATION_TABLE_CACHE: dict[
    str,
    pd.DataFrame,
] = {}


def component_file_tokens(
    value: Any,
) -> set[str]:
    text = clean_text(
        value
    ).lower()

    tokens = {
        token
        for token in re.findall(
            r"[a-z0-9]+",
            text,
        )
        if token
        not in {
            "future",
            "pick",
            "candidate",
            "rights",
            "right",
            "source",
            "asset",
            "assets",
            "allocation",
            "allocations",
            "joint",
            "component",
            "parquet",
            "csv",
            "v1",
            "v2",
            "v3",
        }
    }

    return tokens


def load_source_allocation_candidates() -> list[
    tuple[
        Path,
        pd.DataFrame,
        str,
        str,
        str,
    ]
]:
    cache_key = str(
        PROCESSED_DIRECTORY.resolve()
    )

    if cache_key in SOURCE_ALLOCATION_TABLE_CACHE:
        cached = SOURCE_ALLOCATION_TABLE_CACHE[
            cache_key
        ]

        rows = []

        for path_text, group in cached.groupby(
            "_allocation_file_path",
            sort=True,
        ):
            path = Path(
                path_text
            )

            candidate_team_column = clean_text(
                group[
                    "_candidate_team_column"
                ].iloc[
                    0
                ]
            )

            source_asset_column = clean_text(
                group[
                    "_source_asset_column"
                ].iloc[
                    0
                ]
            )

            probability_column = clean_text(
                group[
                    "_probability_column"
                ].iloc[
                    0
                ]
            )

            clean_group = group.drop(
                columns=[
                    "_allocation_file_path",
                    "_candidate_team_column",
                    "_source_asset_column",
                    "_probability_column",
                ],
                errors="ignore",
            ).reset_index(
                drop=True
            )

            rows.append(
                (
                    path,
                    clean_group,
                    candidate_team_column,
                    source_asset_column,
                    probability_column,
                )
            )

        return rows

    paths = sorted(
        {
            *PROCESSED_DIRECTORY.glob(
                "future_pick_*source_allocations_v*.parquet"
            ),
            *PROCESSED_DIRECTORY.glob(
                "future_pick_*source_asset_allocations_v*.parquet"
            ),
            *PROCESSED_DIRECTORY.glob(
                "future_pick_*source_allocation_v*.parquet"
            ),
            *PROCESSED_DIRECTORY.glob(
                "future_pick_*source_asset_allocation_v*.parquet"
            ),
        }
    )

    candidate_tables = []
    cache_frames = []

    for path in paths:
        try:
            frame = normalize_columns(
                pd.read_parquet(
                    path
                )
            )
        except Exception:
            continue

        candidate_team_column = ""

        for column in [
            "candidate_team",
            "candidate_beneficiary_team",
            "allocated_team",
            "owner_team",
            "destination_team",
        ]:
            if column in frame.columns:
                candidate_team_column = column
                break

        source_asset_column = ""

        for column in [
            "source_asset_key",
            "asset_key",
            "source_asset",
            "physical_source_asset",
        ]:
            if column in frame.columns:
                source_asset_column = column
                break

        probability_column = ""

        for column in [
            "allocation_probability",
            "expected_pick_count",
            "expected_source_pick_count",
            "candidate_expected_pick_count",
            "conveyance_probability",
        ]:
            if column in frame.columns:
                probability_column = column
                break

        if (
            not candidate_team_column
            or not source_asset_column
            or not probability_column
        ):
            continue

        candidate_tables.append(
            (
                path,
                frame,
                candidate_team_column,
                source_asset_column,
                probability_column,
            )
        )

        cache_frame = frame.copy()

        cache_frame[
            "_allocation_file_path"
        ] = str(
            path
        )

        cache_frame[
            "_candidate_team_column"
        ] = candidate_team_column

        cache_frame[
            "_source_asset_column"
        ] = source_asset_column

        cache_frame[
            "_probability_column"
        ] = probability_column

        cache_frames.append(
            cache_frame
        )

    SOURCE_ALLOCATION_TABLE_CACHE[
        cache_key
    ] = (
        pd.concat(
            cache_frames,
            ignore_index=True,
            sort=False,
        )
        if cache_frames
        else pd.DataFrame(
            columns=[
                "_allocation_file_path",
                "_candidate_team_column",
                "_source_asset_column",
                "_probability_column",
            ]
        )
    )

    return candidate_tables


def recover_pick_count_from_source_allocations(
    row_dict: dict[str, Any],
    source_assets: list[str],
) -> tuple[
    float | None,
    str,
]:
    candidate_team = clean_text(
        row_dict.get(
            "candidate_team",
            "",
        )
    ).upper()

    candidate_right_file = clean_text(
        row_dict.get(
            "candidate_right_file",
            "",
        )
    )

    if (
        not candidate_team
        or not source_assets
    ):
        return (
            None,
            "",
        )

    target_assets = {
        clean_text(
            asset
        ).upper()
        for asset in source_assets
        if clean_text(
            asset
        )
    }

    right_tokens = component_file_tokens(
        candidate_right_file
    )

    matches = []

    for (
        path,
        frame,
        candidate_team_column,
        source_asset_column,
        probability_column,
    ) in load_source_allocation_candidates():
        team_values = (
            frame[
                candidate_team_column
            ]
            .fillna("")
            .astype(str)
            .str.strip()
            .str.upper()
        )

        asset_values = (
            frame[
                source_asset_column
            ]
            .fillna("")
            .astype(str)
            .str.strip()
            .str.upper()
        )

        mask = (
            team_values.eq(
                candidate_team
            )
            & asset_values.isin(
                target_assets
            )
        )

        matched = frame.loc[
            mask
        ].copy()

        if matched.empty:
            continue

        matched_assets = {
            clean_text(
                asset
            ).upper()
            for asset in matched[
                source_asset_column
            ]
            if clean_text(
                asset
            )
        }

        coverage = (
            len(
                matched_assets
                & target_assets
            )
            / len(
                target_assets
            )
        )

        allocation_tokens = component_file_tokens(
            path.name
        )

        token_union = (
            right_tokens
            | allocation_tokens
        )

        token_score = (
            len(
                right_tokens
                & allocation_tokens
            )
            / len(
                token_union
            )
            if token_union
            else 0.0
        )

        probabilities = pd.to_numeric(
            matched[
                probability_column
            ],
            errors="coerce",
        )

        if probabilities.isna().any():
            continue

        expected_pick_count = float(
            probabilities.sum()
        )

        if (
            expected_pick_count
            < -PICK_COUNT_TOLERANCE
            or expected_pick_count
            > len(
                target_assets
            )
            + PICK_COUNT_TOLERANCE
        ):
            continue

        score = (
            coverage
            * 100.0
            + token_score
            * 10.0
            + len(
                matched_assets
                & target_assets
            )
        )

        matches.append(
            {
                "score": score,
                "coverage": coverage,
                "token_score": token_score,
                "expected_pick_count": (
                    expected_pick_count
                ),
                "allocation_file": path.name,
                "probability_column": (
                    probability_column
                ),
                "matched_assets": sorted(
                    matched_assets
                    & target_assets
                ),
            }
        )

    if not matches:
        return (
            None,
            "",
        )

    matches = sorted(
        matches,
        key=lambda item: (
            item[
                "score"
            ],
            item[
                "coverage"
            ],
            item[
                "token_score"
            ],
            item[
                "allocation_file"
            ],
        ),
        reverse=True,
    )

    best = matches[
        0
    ]

    if best[
        "coverage"
    ] < 1.0:
        return (
            None,
            "",
        )

    if len(
        matches
    ) > 1:
        second = matches[
            1
        ]

        if (
            abs(
                best[
                    "score"
                ]
                - second[
                    "score"
                ]
            )
            <= 1e-12
            and abs(
                best[
                    "expected_pick_count"
                ]
                - second[
                    "expected_pick_count"
                ]
            )
            > PICK_COUNT_TOLERANCE
        ):
            raise RuntimeError(
                "Multiple source-allocation files tie for the best "
                "legacy expected-pick-count recovery but disagree:\n"
                + json.dumps(
                    {
                        "candidate_right_file": (
                            candidate_right_file
                        ),
                        "candidate_team": (
                            candidate_team
                        ),
                        "source_assets": sorted(
                            target_assets
                        ),
                        "best_matches": matches[
                            :2
                        ],
                    },
                    indent=2,
                    sort_keys=True,
                )
            )

    return (
        float(
            best[
                "expected_pick_count"
            ]
        ),
        (
            "source_allocation_probability_sum:"
            f"{best['allocation_file']}:"
            f"{best['probability_column']}"
        ),
    )


def recover_component_expected_pick_count(
    row_dict: dict[str, Any],
    source_assets: list[str],
) -> tuple[float, str]:
    value = finite_or_nan(
        row_dict.get(
            "expected_pick_count",
            np.nan,
        )
    )

    if np.isfinite(value):
        return float(value), "normalized_expected_pick_count"

    raw = parse_raw_component_payload(
        row_dict.get(
            "raw_row_json",
            "",
        )
    )

    for field in [
        "expected_pick_count",
        "expected_source_pick_count",
        "candidate_expected_pick_count",
        "expected_number_of_picks",
        "pick_count",
    ]:
        value = finite_or_nan(
            raw.get(
                field,
                np.nan,
            )
        )

        if np.isfinite(value):
            return float(value), f"raw_json_{field}"

    (
        allocation_pick_count,
        allocation_recovery_method,
    ) = recover_pick_count_from_source_allocations(
        row_dict=row_dict,
        source_assets=source_assets,
    )

    if allocation_pick_count is not None:
        return (
            float(
                allocation_pick_count
            ),
            allocation_recovery_method,
        )

    description = " ".join(
        clean_text(raw.get(field, ""))
        for field in [
            "right_description",
            "description",
            "right_name",
            "selection_rule",
            "allocation_rule",
        ]
    ).lower()

    if re.search(
        r"\\b(?:most|best)\\b.*\\b(?:least|worst)\\b",
        description,
    ):
        return 2.0, "legacy_description_two_pick_inference"

    if len(source_assets) == 1:
        return 1.0, "single_source_default"

    raise RuntimeError(
        "A component-right row has no recoverable expected pick count:\\n"
        + json.dumps(
            json_safe(row_dict),
            indent=2,
            sort_keys=True,
        )
    )


def parse_asset_key(
    asset_key: str,
) -> tuple[
    int | None,
    int | None,
    str,
]:
    match = re.fullmatch(
        r"(20\d{2})_R([12])_([A-Z]{3})",
        clean_text(
            asset_key
        ).upper(),
    )

    if not match:
        return (
            None,
            None,
            "",
        )

    return (
        int(
            match.group(
                1
            )
        ),
        int(
            match.group(
                2
            )
        ),
        match.group(
            3
        ),
    )


def stable_right_id(
    right_type: str,
    candidate_team: str,
    source_assets: str,
    source_reference: str,
) -> str:
    payload = "|".join(
        [
            clean_text(
                right_type
            ),
            clean_text(
                candidate_team
            ),
            clean_text(
                source_assets
            ),
            clean_text(
                source_reference
            ),
        ]
    )

    digest = hashlib.sha256(
        payload.encode(
            "utf-8"
        )
    ).hexdigest()[
        :16
    ]

    return (
        "FPR_"
        + digest.upper()
    )


def file_sha256(
    path: Path,
) -> str:
    digest = hashlib.sha256()

    with path.open(
        "rb"
    ) as file:
        for chunk in iter(
            lambda: file.read(
                1024 * 1024
            ),
            b"",
        ):
            digest.update(
                chunk
            )

    return digest.hexdigest()


def file_manifest_row(
    path: Path,
    role: str,
) -> dict[str, Any]:
    return {
        "file_role": role,
        "file_name": path.name,
        "file_path": str(
            path
        ),
        "file_size_bytes": int(
            path.stat().st_size
        ),
        "sha256": file_sha256(
            path
        ),
        "release_name": RELEASE_NAME,
        "release_version": SCRIPT_VERSION,
    }


def load_inputs() -> tuple[
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
]:
    required_paths = [
        DIRECT_RIGHTS_PATH,
        COMPONENT_RIGHTS_PATH,
        COMPONENT_PRIMARY_ROWS_PATH,
        FILE_CATALOG_PATH,
        SOURCE_OVERLAP_AUDIT_PATH,
        READINESS_AUDIT_PATH,
        FINAL_VALUATION_PATH,
        FINAL_TEAM_SUMMARY_PATH,
    ]

    for path in required_paths:
        if not path.exists():
            raise FileNotFoundError(
                "Required optimizer-inventory input was not found:\n"
                f"{path}"
            )

    direct_rights = normalize_columns(
        pd.read_csv(
            DIRECT_RIGHTS_PATH
        )
    )

    component_rights = normalize_columns(
        pd.read_parquet(
            COMPONENT_RIGHTS_PATH
        )
    )

    component_primary_rows = normalize_columns(
        pd.read_csv(
            COMPONENT_PRIMARY_ROWS_PATH
        )
    )

    file_catalog = normalize_columns(
        pd.read_csv(
            FILE_CATALOG_PATH
        )
    )

    source_overlap = normalize_columns(
        pd.read_csv(
            SOURCE_OVERLAP_AUDIT_PATH
        )
    )

    readiness_audit = normalize_columns(
        pd.read_csv(
            READINESS_AUDIT_PATH
        )
    )

    valuations = normalize_columns(
        pd.read_parquet(
            FINAL_VALUATION_PATH
        )
    )

    team_summary = normalize_columns(
        pd.read_csv(
            FINAL_TEAM_SUMMARY_PATH
        )
    )

    return (
        direct_rights,
        component_rights,
        component_primary_rows,
        file_catalog,
        source_overlap,
        readiness_audit,
        valuations,
        team_summary,
    )


def validate_inputs(
    direct_rights: pd.DataFrame,
    component_rights: pd.DataFrame,
    component_primary_rows: pd.DataFrame,
    file_catalog: pd.DataFrame,
    source_overlap: pd.DataFrame,
    readiness_audit: pd.DataFrame,
    valuations: pd.DataFrame,
    team_summary: pd.DataFrame,
) -> None:
    require_columns(
        direct_rights,
        [
            "claim_id",
            "asset_key",
            "candidate_team",
            "candidate_asset_value_score",
            "valuation_method",
            "valuation_status",
        ],
        "Direct candidate rows",
    )

    require_columns(
        component_rights,
        [
            "candidate_right_file",
            "row_number",
            "candidate_team",
            "expected_candidate_right_value_score",
            "expected_pick_count",
            "source_assets",
        ],
        "Normalized component rights",
    )

    require_columns(
        component_primary_rows,
        [
            "claim_id",
            "asset_key",
            "valuation_method",
            "source_asset_value_score",
        ],
        "Component primary rows",
    )

    require_columns(
        file_catalog,
        [
            "candidate_right_file",
            "normalizable",
            "probable_active_component_file",
        ],
        "Candidate-right file catalog",
    )

    require_columns(
        readiness_audit,
        [
            "check_name",
            "passed",
            "blocking_for_inventory_build",
        ],
        "Inventory readiness audit",
    )

    require_columns(
        valuations,
        [
            "claim_id",
            "asset_key",
            "valuation_method",
            "valuation_status",
        ],
        "Canonical valuation layer",
    )

    require_columns(
        team_summary,
        [
            "candidate_beneficiary_team",
            FINAL_TEAM_VALUE_COLUMN,
        ],
        "Canonical team summary",
    )

    blocking = (
        parse_bool_series(
            readiness_audit[
                "blocking_for_inventory_build"
            ]
        )
    )

    passed = parse_bool_series(
        readiness_audit[
            "passed"
        ]
    )

    failed_blocking = readiness_audit.loc[
        blocking
        & ~passed
    ]

    if not failed_blocking.empty:
        raise RuntimeError(
            "The inventory-readiness audit has blocking failures:\n"
            + failed_blocking.to_string(
                index=False
            )
        )

    if len(
        direct_rights
    ) != EXPECTED_DIRECT_RIGHT_ROWS:
        raise RuntimeError(
            "Direct-right row count changed. "
            f"Expected {EXPECTED_DIRECT_RIGHT_ROWS}, "
            f"found {len(direct_rights)}."
        )

    if len(
        component_rights
    ) != EXPECTED_COMPONENT_RIGHT_ROWS:
        raise RuntimeError(
            "Component-right row count changed. "
            f"Expected {EXPECTED_COMPONENT_RIGHT_ROWS}, "
            f"found {len(component_rights)}."
        )

    if len(
        team_summary
    ) != EXPECTED_TEAM_ROWS:
        raise RuntimeError(
            "Canonical team-summary row count changed."
        )

    normalizable = parse_bool_series(
        file_catalog[
            "normalizable"
        ]
    )

    active = parse_bool_series(
        file_catalog[
            "probable_active_component_file"
        ]
    )

    if not normalizable.all():
        raise RuntimeError(
            "At least one selected candidate-right file is not "
            "normalizable."
        )

    if not active.all():
        raise RuntimeError(
            "At least one selected candidate-right file is not marked "
            "as an active component file."
        )

    if (
        not source_overlap.empty
        and "cross_file_overlap_flag"
        in source_overlap.columns
        and parse_bool_series(
            source_overlap[
                "cross_file_overlap_flag"
            ]
        ).any()
    ):
        raise RuntimeError(
            "Cross-file source overlaps remain unresolved."
        )


def classify_direct_structure(
    valuation_method: str,
) -> str:
    method = clean_text(
        valuation_method
    ).lower()

    if method == "direct_asset_value":
        return "direct_owned_pick"

    if "swap_option" in method:
        return "two_team_swap_option"

    if "protection" in method:
        return "protected_or_conditional_pick"

    if "rollover" in method:
        return "linked_rollover_right"

    if "multi_asset_candidate_right" in method:
        return "composite_candidate_right"

    if "multi_pick_favorability_pool" in method:
        return "integrated_pool_candidate_right"

    if "conditional" in method:
        return "conditional_candidate_right"

    return "single_claim_candidate_right"


def direct_expected_pick_count(
    row: pd.Series,
) -> float:
    method = clean_text(
        row.get(
            "valuation_method",
            "",
        )
    ).lower()

    conveyance_probability = finite_or_nan(
        row.get(
            "conveyance_probability",
            np.nan,
        )
    )

    if (
        np.isfinite(
            conveyance_probability
        )
        and 0.0
        <= conveyance_probability
        <= 1.0
        and (
            "protection" in method
            or "conditional" in method
            or "rollover" in method
        )
    ):
        return float(
            conveyance_probability
        )

    return 1.0


def direct_display_name(
    candidate_team: str,
    asset_key: str,
    structure: str,
) -> str:
    year, round_number, source_team = parse_asset_key(
        asset_key
    )

    if year is None:
        return (
            f"{candidate_team} future-pick right from {asset_key}"
        )

    round_label = (
        "first"
        if round_number == 1
        else "second"
    )

    return (
        f"{candidate_team} {structure.replace('_', ' ')}: "
        f"{source_team} {year} {round_label}"
    )


def build_direct_inventory(
    direct_rights: pd.DataFrame,
) -> pd.DataFrame:
    rows = []

    for row in direct_rights.itertuples(
        index=False
    ):
        row_dict = row._asdict()

        claim_id = clean_text(
            row_dict.get(
                "claim_id",
                "",
            )
        )

        asset_key = clean_text(
            row_dict.get(
                "asset_key",
                "",
            )
        ).upper()

        candidate_team = clean_text(
            row_dict.get(
                "candidate_team",
                "",
            )
        ).upper()

        valuation_method = clean_text(
            row_dict.get(
                "valuation_method",
                "",
            )
        )

        structure = classify_direct_structure(
            valuation_method
        )

        year, round_number, source_team = parse_asset_key(
            asset_key
        )

        source_reference = claim_id

        rows.append(
            {
                "future_pick_right_id": stable_right_id(
                    right_type="direct",
                    candidate_team=candidate_team,
                    source_assets=asset_key,
                    source_reference=source_reference,
                ),
                "candidate_team": candidate_team,
                "right_display_name": direct_display_name(
                    candidate_team=candidate_team,
                    asset_key=asset_key,
                    structure=structure,
                ),
                "right_origin": "canonical_claim_row",
                "right_structure": structure,
                "source_assets": asset_key,
                "source_asset_count": 1,
                "primary_source_asset": asset_key,
                "draft_year_min": year,
                "draft_year_max": year,
                "round_numbers": (
                    str(
                        round_number
                    )
                    if round_number is not None
                    else ""
                ),
                "originating_teams": source_team,
                "expected_pick_count": direct_expected_pick_count(
                    pd.Series(
                        row_dict
                    )
                ),
                "candidate_right_value_score": finite_or_zero(
                    row_dict.get(
                        "candidate_asset_value_score",
                        np.nan,
                    )
                ),
                "claim_id": claim_id,
                "valuation_method": valuation_method,
                "valuation_status": clean_text(
                    row_dict.get(
                        "valuation_status",
                        "",
                    )
                ),
                "component_right_file": "",
                "component_right_row_number": np.nan,
                "component_method_match_score": np.nan,
                "component_raw_row_json": "",
                "source_assets_recovery_method": (
                    "canonical_claim_asset_key"
                ),
                "expected_pick_count_recovery_method": (
                    "canonical_claim_rule"
                ),
                "tradability_status": (
                    "requires_trade_date_cba_and_ownership_validation"
                ),
                "inventory_release": RELEASE_NAME,
                "inventory_release_version": SCRIPT_VERSION,
            }
        )

    return pd.DataFrame(
        rows
    )


def component_display_name(
    candidate_team: str,
    source_assets: list[str],
) -> str:
    years = sorted(
        {
            parse_asset_key(
                asset
            )[
                0
            ]
            for asset in source_assets
            if parse_asset_key(
                asset
            )[
                0
            ]
            is not None
        }
    )

    rounds = sorted(
        {
            parse_asset_key(
                asset
            )[
                1
            ]
            for asset in source_assets
            if parse_asset_key(
                asset
            )[
                1
            ]
            is not None
        }
    )

    year_text = (
        str(
            years[
                0
            ]
        )
        if len(
            years
        )
        == 1
        else "-".join(
            str(
                value
            )
            for value in years
        )
    )

    round_text = (
        "first-round"
        if rounds == [
            1
        ]
        else (
            "second-round"
            if rounds == [
                2
            ]
            else "mixed-round"
        )
    )

    return (
        f"{candidate_team} {year_text} {round_text} "
        f"component right across {len(source_assets)} source asset"
        + (
            ""
            if len(
                source_assets
            )
            == 1
            else "s"
        )
    )


def build_component_inventory(
    component_rights: pd.DataFrame,
) -> pd.DataFrame:
    rows = []

    for row in component_rights.itertuples(
        index=False
    ):
        row_dict = row._asdict()

        (
            source_assets,
            source_assets_recovery_method,
        ) = recover_component_source_assets(
            row_dict
        )

        if not source_assets:
            raise RuntimeError(
                "A component-right row has no recoverable source assets:\n"
                + json.dumps(
                    json_safe(
                        row_dict
                    ),
                    indent=2,
                    sort_keys=True,
                )
            )

        (
            expected_pick_count,
            expected_pick_count_recovery_method,
        ) = recover_component_expected_pick_count(
            row_dict=row_dict,
            source_assets=source_assets,
        )

        candidate_team = clean_text(
            row_dict.get(
                "candidate_team",
                "",
            )
        ).upper()

        component_file = clean_text(
            row_dict.get(
                "candidate_right_file",
                "",
            )
        )

        row_number = int(
            finite_or_zero(
                row_dict.get(
                    "row_number",
                    0,
                )
            )
        )

        years = sorted(
            {
                parse_asset_key(
                    asset
                )[
                    0
                ]
                for asset in source_assets
                if parse_asset_key(
                    asset
                )[
                    0
                ]
                is not None
            }
        )

        rounds = sorted(
            {
                parse_asset_key(
                    asset
                )[
                    1
                ]
                for asset in source_assets
                if parse_asset_key(
                    asset
                )[
                    1
                ]
                is not None
            }
        )

        originating_teams = sorted(
            {
                parse_asset_key(
                    asset
                )[
                    2
                ]
                for asset in source_assets
                if parse_asset_key(
                    asset
                )[
                    2
                ]
            }
        )

        source_assets_text = "|".join(
            source_assets
        )

        source_reference = (
            f"{component_file}#{row_number}"
        )

        rows.append(
            {
                "future_pick_right_id": stable_right_id(
                    right_type="component",
                    candidate_team=candidate_team,
                    source_assets=source_assets_text,
                    source_reference=source_reference,
                ),
                "candidate_team": candidate_team,
                "right_display_name": component_display_name(
                    candidate_team=candidate_team,
                    source_assets=source_assets,
                ),
                "right_origin": "component_candidate_right_file",
                "right_structure": "joint_component_candidate_right",
                "source_assets": source_assets_text,
                "source_asset_count": len(
                    source_assets
                ),
                "primary_source_asset": (
                    source_assets[
                        0
                    ]
                    if len(
                        source_assets
                    )
                    == 1
                    else ""
                ),
                "draft_year_min": (
                    min(
                        years
                    )
                    if years
                    else np.nan
                ),
                "draft_year_max": (
                    max(
                        years
                    )
                    if years
                    else np.nan
                ),
                "round_numbers": "|".join(
                    str(
                        value
                    )
                    for value in rounds
                ),
                "originating_teams": "|".join(
                    originating_teams
                ),
                "expected_pick_count": expected_pick_count,
                "candidate_right_value_score": finite_or_zero(
                    row_dict.get(
                        "expected_candidate_right_value_score",
                        np.nan,
                    )
                ),
                "claim_id": "",
                "valuation_method": clean_text(
                    row_dict.get(
                        "best_matching_final_valuation_method",
                        "",
                    )
                ),
                "valuation_status": (
                    "valued_component_candidate_right"
                ),
                "component_right_file": component_file,
                "component_right_row_number": row_number,
                "component_method_match_score": finite_or_nan(
                    row_dict.get(
                        "method_match_score",
                        np.nan,
                    )
                ),
                "component_raw_row_json": clean_text(
                    row_dict.get(
                        "raw_row_json",
                        "",
                    )
                ),
                "source_assets_recovery_method": (
                    source_assets_recovery_method
                ),
                "expected_pick_count_recovery_method": (
                    expected_pick_count_recovery_method
                ),
                "tradability_status": (
                    "requires_trade_date_cba_and_ownership_validation"
                ),
                "inventory_release": RELEASE_NAME,
                "inventory_release_version": SCRIPT_VERSION,
            }
        )

    return pd.DataFrame(
        rows
    )


def build_team_reconciliation(
    inventory: pd.DataFrame,
    team_summary: pd.DataFrame,
) -> pd.DataFrame:
    inventory_totals = (
        inventory.groupby(
            "candidate_team",
            as_index=False,
        )
        .agg(
            optimizer_inventory_right_rows=(
                "future_pick_right_id",
                "size",
            ),
            optimizer_inventory_expected_pick_count=(
                "expected_pick_count",
                "sum",
            ),
            optimizer_inventory_value_score=(
                "candidate_right_value_score",
                "sum",
            ),
        )
    )

    canonical = team_summary[
        [
            "candidate_beneficiary_team",
            FINAL_TEAM_VALUE_COLUMN,
        ]
    ].copy()

    canonical = canonical.rename(
        columns={
            "candidate_beneficiary_team": "candidate_team",
            FINAL_TEAM_VALUE_COLUMN: (
                "canonical_final_team_value_score"
            ),
        }
    )

    output = canonical.merge(
        inventory_totals,
        how="outer",
        on="candidate_team",
        validate="one_to_one",
    )

    for column in [
        "canonical_final_team_value_score",
        "optimizer_inventory_value_score",
        "optimizer_inventory_expected_pick_count",
        "optimizer_inventory_right_rows",
    ]:
        output[
            column
        ] = pd.to_numeric(
            output[
                column
            ],
            errors="coerce",
        ).fillna(
            0.0
        )

    output[
        "value_difference"
    ] = (
        output[
            "optimizer_inventory_value_score"
        ]
        - output[
            "canonical_final_team_value_score"
        ]
    )

    output[
        "absolute_value_difference"
    ] = output[
        "value_difference"
    ].abs()

    output[
        "team_reconciliation_passed"
    ] = (
        output[
            "absolute_value_difference"
        ]
        <= VALUE_TOLERANCE
    )

    return output.sort_values(
        "canonical_final_team_value_score",
        ascending=False,
    ).reset_index(
        drop=True
    )


def build_source_coverage(
    inventory: pd.DataFrame,
    component_primary_rows: pd.DataFrame,
) -> pd.DataFrame:
    primary_assets = set(
        component_primary_rows[
            "asset_key"
        ]
        .fillna("")
        .astype(str)
        .str.upper()
        .str.strip()
    )

    primary_assets.discard(
        ""
    )

    component_inventory = inventory.loc[
        inventory[
            "right_origin"
        ].eq(
            "component_candidate_right_file"
        )
    ]

    rows = []

    for asset_key in sorted(
        primary_assets
    ):
        matches = component_inventory.loc[
            component_inventory[
                "source_assets"
            ]
            .fillna("")
            .astype(str)
            .map(
                lambda value: asset_key
                in parse_source_assets(
                    value
                )
            )
        ]

        rows.append(
            {
                "source_asset_key": asset_key,
                "candidate_right_rows_referencing_source": int(
                    len(
                        matches
                    )
                ),
                "candidate_teams": "|".join(
                    sorted(
                        set(
                            matches[
                                "candidate_team"
                            ].astype(str)
                        )
                    )
                ),
                "component_right_files": "|".join(
                    sorted(
                        set(
                            matches[
                                "component_right_file"
                            ].astype(str)
                        )
                    )
                ),
                "source_covered_by_inventory": bool(
                    not matches.empty
                ),
            }
        )

    return pd.DataFrame(
        rows
    )


def build_inventory_summary(
    inventory: pd.DataFrame,
) -> pd.DataFrame:
    return (
        inventory.groupby(
            [
                "right_origin",
                "right_structure",
            ],
            dropna=False,
            as_index=False,
        )
        .agg(
            right_rows=(
                "future_pick_right_id",
                "size",
            ),
            candidate_teams=(
                "candidate_team",
                "nunique",
            ),
            source_asset_references=(
                "source_asset_count",
                "sum",
            ),
            expected_pick_count=(
                "expected_pick_count",
                "sum",
            ),
            total_value_score=(
                "candidate_right_value_score",
                "sum",
            ),
        )
        .sort_values(
            [
                "right_rows",
                "right_origin",
                "right_structure",
            ],
            ascending=[
                False,
                True,
                True,
            ],
        )
        .reset_index(
            drop=True
        )
    )


def build_validation(
    inventory: pd.DataFrame,
    direct_inventory: pd.DataFrame,
    component_inventory: pd.DataFrame,
    team_reconciliation: pd.DataFrame,
    source_coverage: pd.DataFrame,
    valuations: pd.DataFrame,
) -> pd.DataFrame:
    values = pd.to_numeric(
        inventory[
            "candidate_right_value_score"
        ],
        errors="coerce",
    )

    pick_counts = pd.to_numeric(
        inventory[
            "expected_pick_count"
        ],
        errors="coerce",
    )

    duplicate_ids = int(
        inventory[
            "future_pick_right_id"
        ].duplicated().sum()
    )

    invalid_team_rows = int(
        inventory[
            "candidate_team"
        ]
        .fillna("")
        .astype(str)
        .str.fullmatch(
            r"[A-Z]{3}"
        )
        .eq(
            False
        )
        .sum()
    )

    direct_component_asset_overlap = set(
        direct_inventory[
            "primary_source_asset"
        ]
        .fillna("")
        .astype(str)
    ) & set(
        component_inventory[
            "source_assets"
        ]
        .fillna("")
        .astype(str)
        .map(
            parse_source_assets
        )
        .explode()
        .dropna()
        .astype(str)
    )

    direct_component_asset_overlap.discard(
        ""
    )

    all_claims_valued = bool(
        valuations[
            "valuation_status"
        ]
        .fillna("")
        .astype(str)
        .str.startswith(
            "valued_"
        )
        .all()
    )

    system_inventory_value = float(
        values.sum()
    )

    system_canonical_value = float(
        team_reconciliation[
            "canonical_final_team_value_score"
        ].sum()
    )

    checks = [
        {
            "check_name": "expected_inventory_row_count",
            "observed_value": int(
                len(
                    inventory
                )
            ),
            "expected_value": EXPECTED_INVENTORY_ROWS,
            "passed": len(
                inventory
            ) == EXPECTED_INVENTORY_ROWS,
        },
        {
            "check_name": "expected_direct_right_row_count",
            "observed_value": int(
                len(
                    direct_inventory
                )
            ),
            "expected_value": EXPECTED_DIRECT_RIGHT_ROWS,
            "passed": len(
                direct_inventory
            ) == EXPECTED_DIRECT_RIGHT_ROWS,
        },
        {
            "check_name": "expected_component_right_row_count",
            "observed_value": int(
                len(
                    component_inventory
                )
            ),
            "expected_value": EXPECTED_COMPONENT_RIGHT_ROWS,
            "passed": len(
                component_inventory
            ) == EXPECTED_COMPONENT_RIGHT_ROWS,
        },
        {
            "check_name": "unique_future_pick_right_ids",
            "observed_value": duplicate_ids,
            "expected_value": 0,
            "passed": duplicate_ids == 0,
        },
        {
            "check_name": "finite_inventory_values",
            "observed_value": int(
                values.notna().sum()
            ),
            "expected_value": int(
                len(
                    inventory
                )
            ),
            "passed": values.notna().all(),
        },
        {
            "check_name": "nonnegative_inventory_values",
            "observed_value": int(
                values.lt(
                    -VALUE_TOLERANCE
                ).sum()
            ),
            "expected_value": 0,
            "passed": bool(
                not values.lt(
                    -VALUE_TOLERANCE
                ).any()
            ),
        },
        {
            "check_name": "finite_expected_pick_counts",
            "observed_value": int(
                pick_counts.notna().sum()
            ),
            "expected_value": int(
                len(
                    inventory
                )
            ),
            "passed": pick_counts.notna().all(),
        },
        {
            "check_name": "nonnegative_expected_pick_counts",
            "observed_value": int(
                pick_counts.lt(
                    -PICK_COUNT_TOLERANCE
                ).sum()
            ),
            "expected_value": 0,
            "passed": bool(
                not pick_counts.lt(
                    -PICK_COUNT_TOLERANCE
                ).any()
            ),
        },
        {
            "check_name": "valid_candidate_team_codes",
            "observed_value": invalid_team_rows,
            "expected_value": 0,
            "passed": invalid_team_rows == 0,
        },
        {
            "check_name": "team_reconciliation_rows",
            "observed_value": int(
                len(
                    team_reconciliation
                )
            ),
            "expected_value": EXPECTED_TEAM_ROWS,
            "passed": len(
                team_reconciliation
            ) == EXPECTED_TEAM_ROWS,
        },
        {
            "check_name": "all_team_value_reconciliations",
            "observed_value": int(
                team_reconciliation[
                    "team_reconciliation_passed"
                ].sum()
            ),
            "expected_value": EXPECTED_TEAM_ROWS,
            "passed": bool(
                team_reconciliation[
                    "team_reconciliation_passed"
                ].all()
            ),
        },
        {
            "check_name": "system_value_reconciliation",
            "observed_value": (
                system_inventory_value
                - system_canonical_value
            ),
            "expected_value": 0.0,
            "passed": abs(
                system_inventory_value
                - system_canonical_value
            )
            <= VALUE_TOLERANCE,
        },
        {
            "check_name": "all_component_primary_sources_covered",
            "observed_value": int(
                source_coverage[
                    "source_covered_by_inventory"
                ].sum()
            )
            if not source_coverage.empty
            else 0,
            "expected_value": int(
                len(
                    source_coverage
                )
            ),
            "passed": bool(
                not source_coverage.empty
                and source_coverage[
                    "source_covered_by_inventory"
                ].all()
            ),
        },
        {
            "check_name": "direct_component_source_overlap",
            "observed_value": int(
                len(
                    direct_component_asset_overlap
                )
            ),
            "expected_value": 0,
            "passed": len(
                direct_component_asset_overlap
            )
            == 0,
        },
        {
            "check_name": "canonical_claim_layer_fully_valued",
            "observed_value": all_claims_valued,
            "expected_value": True,
            "passed": all_claims_valued,
        },
    ]

    return pd.DataFrame(
        checks
    )


def main() -> None:
    PROCESSED_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    OUTPUT_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    print("=" * 80)
    print("FUTURE PICK OPTIMIZER INVENTORY BUILD")
    print("=" * 80)
    print(f"Script version: {SCRIPT_VERSION}")
    print(f"Release name: {RELEASE_NAME}")
    print()

    (
        direct_rights,
        component_rights,
        component_primary_rows,
        file_catalog,
        source_overlap,
        readiness_audit,
        valuations,
        team_summary,
    ) = load_inputs()

    validate_inputs(
        direct_rights=direct_rights,
        component_rights=component_rights,
        component_primary_rows=component_primary_rows,
        file_catalog=file_catalog,
        source_overlap=source_overlap,
        readiness_audit=readiness_audit,
        valuations=valuations,
        team_summary=team_summary,
    )

    direct_inventory = build_direct_inventory(
        direct_rights
    )

    component_inventory = build_component_inventory(
        component_rights
    )

    inventory = pd.concat(
        [
            direct_inventory,
            component_inventory,
        ],
        ignore_index=True,
        sort=False,
    )

    inventory[
        "candidate_right_value_score"
    ] = pd.to_numeric(
        inventory[
            "candidate_right_value_score"
        ],
        errors="raise",
    )

    inventory[
        "expected_pick_count"
    ] = pd.to_numeric(
        inventory[
            "expected_pick_count"
        ],
        errors="raise",
    )

    inventory = inventory.sort_values(
        [
            "candidate_team",
            "draft_year_min",
            "round_numbers",
            "right_origin",
            "future_pick_right_id",
        ],
        na_position="last",
    ).reset_index(
        drop=True
    )

    team_reconciliation = build_team_reconciliation(
        inventory=inventory,
        team_summary=team_summary,
    )

    source_coverage = build_source_coverage(
        inventory=inventory,
        component_primary_rows=component_primary_rows,
    )

    inventory_summary = build_inventory_summary(
        inventory
    )

    validation = build_validation(
        inventory=inventory,
        direct_inventory=direct_inventory,
        component_inventory=component_inventory,
        team_reconciliation=team_reconciliation,
        source_coverage=source_coverage,
        valuations=valuations,
    )

    FINAL_INVENTORY_PARQUET_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    inventory.to_parquet(
        FINAL_INVENTORY_PARQUET_PATH,
        index=False,
    )

    inventory.to_csv(
        FINAL_INVENTORY_CSV_PATH,
        index=False,
    )

    team_reconciliation.to_csv(
        TEAM_RECONCILIATION_PATH,
        index=False,
    )

    source_coverage.to_csv(
        SOURCE_COVERAGE_PATH,
        index=False,
    )

    validation.to_csv(
        VALIDATION_PATH,
        index=False,
    )

    inventory_summary.to_csv(
        INVENTORY_SUMMARY_PATH,
        index=False,
    )

    failed = validation.loc[
        ~validation[
            "passed"
        ]
    ]

    manifest_rows = [
        file_manifest_row(
            DIRECT_RIGHTS_PATH,
            "input_direct_rights",
        ),
        file_manifest_row(
            COMPONENT_RIGHTS_PATH,
            "input_component_rights",
        ),
        file_manifest_row(
            COMPONENT_PRIMARY_ROWS_PATH,
            "input_component_primary_rows",
        ),
        file_manifest_row(
            READINESS_AUDIT_PATH,
            "input_readiness_audit",
        ),
        file_manifest_row(
            FINAL_VALUATION_PATH,
            "input_canonical_valuation_layer",
        ),
        file_manifest_row(
            FINAL_TEAM_SUMMARY_PATH,
            "input_canonical_team_summary",
        ),
        file_manifest_row(
            FINAL_INVENTORY_PARQUET_PATH,
            "final_optimizer_inventory_parquet",
        ),
        file_manifest_row(
            FINAL_INVENTORY_CSV_PATH,
            "final_optimizer_inventory_csv",
        ),
        file_manifest_row(
            TEAM_RECONCILIATION_PATH,
            "final_team_reconciliation",
        ),
        file_manifest_row(
            SOURCE_COVERAGE_PATH,
            "final_source_coverage",
        ),
        file_manifest_row(
            VALIDATION_PATH,
            "final_inventory_validation",
        ),
        file_manifest_row(
            INVENTORY_SUMMARY_PATH,
            "final_inventory_summary",
        ),
    ]

    manifest = pd.DataFrame(
        manifest_rows
    )

    manifest.to_csv(
        MANIFEST_PATH,
        index=False,
    )

    metadata = {
        "script_version": SCRIPT_VERSION,
        "release_name": RELEASE_NAME,
        "created_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "inventory_rows": int(
            len(
                inventory
            )
        ),
        "direct_right_rows": int(
            len(
                direct_inventory
            )
        ),
        "component_right_rows": int(
            len(
                component_inventory
            )
        ),
        "candidate_teams": int(
            inventory[
                "candidate_team"
            ].nunique()
        ),
        "total_expected_pick_count": float(
            inventory[
                "expected_pick_count"
            ].sum()
        ),
        "total_inventory_value_score": float(
            inventory[
                "candidate_right_value_score"
            ].sum()
        ),
        "canonical_team_value_score": float(
            team_reconciliation[
                "canonical_final_team_value_score"
            ].sum()
        ),
        "maximum_team_value_difference": float(
            team_reconciliation[
                "absolute_value_difference"
            ].max()
        ),
        "component_primary_sources": int(
            len(
                source_coverage
            )
        ),
        "component_primary_sources_covered": int(
            source_coverage[
                "source_covered_by_inventory"
            ].sum()
        )
        if not source_coverage.empty
        else 0,
        "validation_checks": int(
            len(
                validation
            )
        ),
        "validation_checks_passed": int(
            validation[
                "passed"
            ].sum()
        ),
        "release_valid": bool(
            failed.empty
        ),
        "failed_checks": (
            failed[
                "check_name"
            ].astype(str).tolist()
        ),
        "output_files": {
            "inventory_parquet": str(
                FINAL_INVENTORY_PARQUET_PATH
            ),
            "inventory_csv": str(
                FINAL_INVENTORY_CSV_PATH
            ),
            "team_reconciliation": str(
                TEAM_RECONCILIATION_PATH
            ),
            "source_coverage": str(
                SOURCE_COVERAGE_PATH
            ),
            "validation": str(
                VALIDATION_PATH
            ),
            "inventory_summary": str(
                INVENTORY_SUMMARY_PATH
            ),
            "manifest": str(
                MANIFEST_PATH
            ),
        },
    }

    with METADATA_PATH.open(
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            json_safe(
                metadata
            ),
            file,
            indent=2,
        )

    print("=" * 80)
    print("OPTIMIZER INVENTORY BUILD COMPLETE")
    print("=" * 80)
    print(
        "Inventory rows: "
        f"{len(inventory):,}"
    )
    print(
        "Direct or single-claim rights: "
        f"{len(direct_inventory):,}"
    )
    print(
        "Component candidate rights: "
        f"{len(component_inventory):,}"
    )
    print(
        "Candidate teams: "
        f"{inventory['candidate_team'].nunique():,}"
    )
    print(
        "Total expected pick count: "
        f"{inventory['expected_pick_count'].sum():.4f}"
    )
    print(
        "Total inventory value score: "
        f"{inventory['candidate_right_value_score'].sum():.4f}"
    )
    print(
        "Canonical team value score: "
        f"{team_reconciliation['canonical_final_team_value_score'].sum():.4f}"
    )
    print(
        "Maximum team value difference: "
        f"{team_reconciliation['absolute_value_difference'].max():.10f}"
    )
    print(
        "Component primary sources covered: "
        f"{int(source_coverage['source_covered_by_inventory'].sum()):,}"
        f"/{len(source_coverage):,}"
    )
    print(
        "Validation checks passed: "
        f"{int(validation['passed'].sum()):,}"
        f"/{len(validation):,}"
    )
    print(
        "Inventory release valid: "
        f"{bool(failed.empty)}"
    )
    print()

    print("INVENTORY SUMMARY")
    display_summary = inventory_summary.copy()

    for column in [
        "expected_pick_count",
        "total_value_score",
    ]:
        display_summary[
            column
        ] = pd.to_numeric(
            display_summary[
                column
            ],
            errors="coerce",
        ).round(
            4
        )

    print(
        display_summary.to_string(
            index=False
        )
    )
    print()

    print("TOP 10 TEAMS BY INVENTORY VALUE")
    display_teams = team_reconciliation.head(
        10
    ).copy()

    for column in [
        "optimizer_inventory_expected_pick_count",
        "optimizer_inventory_value_score",
        "canonical_final_team_value_score",
        "value_difference",
    ]:
        display_teams[
            column
        ] = pd.to_numeric(
            display_teams[
                column
            ],
            errors="coerce",
        ).round(
            6
        )

    print(
        display_teams.to_string(
            index=False
        )
    )
    print()

    print("VALIDATION")
    print(
        validation.to_string(
            index=False
        )
    )
    print()

    print("SAVED FILES")

    for path in [
        FINAL_INVENTORY_PARQUET_PATH,
        FINAL_INVENTORY_CSV_PATH,
        TEAM_RECONCILIATION_PATH,
        SOURCE_COVERAGE_PATH,
        VALIDATION_PATH,
        INVENTORY_SUMMARY_PATH,
        MANIFEST_PATH,
        METADATA_PATH,
    ]:
        print(
            path
        )

    if not failed.empty:
        raise RuntimeError(
            "The optimizer inventory was created for diagnosis but "
            "failed release validation:\n"
            + failed.to_string(
                index=False
            )
        )


if __name__ == "__main__":
    main()