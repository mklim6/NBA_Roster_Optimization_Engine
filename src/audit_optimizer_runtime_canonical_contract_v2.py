from __future__ import annotations

import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


SCRIPT_VERSION = (
    "optimizer-runtime-canonical-contract-audit-v2-2026-08-04"
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIRECTORY = PROJECT_ROOT / "outputs"
PROCESSED_DIRECTORY = PROJECT_ROOT / "data" / "processed"

CANONICAL_FILES = {
    "player_value_layer": (
        PROCESSED_DIRECTORY
        / "player_trade_market_value_layer_2026_27_v3.parquet"
    ),
    "one_for_one_runtime": (
        OUTPUT_DIRECTORY
        / "one_for_one_trade_realism_scores_2026_27_v3.parquet"
    ),
    "two_for_one_runtime": (
        OUTPUT_DIRECTORY
        / "two_for_one_trade_realism_scores_2026_27_v2.parquet"
    ),
    "future_pick_inventory": (
        PROCESSED_DIRECTORY
        / "future_pick_optimizer_inventory_2027_2029_final.parquet"
    ),
    "team_salary_profiles": (
        PROCESSED_DIRECTORY
        / "team_trade_salary_profiles_2026_27.csv"
    ),
}

SCHEMA_PATH = (
    OUTPUT_DIRECTORY
    / "optimizer_runtime_canonical_contract_schema_v2.csv"
)

COLUMN_CLASSIFICATION_PATH = (
    OUTPUT_DIRECTORY
    / "optimizer_runtime_canonical_contract_columns_v2.csv"
)

SAMPLE_PATH = (
    OUTPUT_DIRECTORY
    / "optimizer_runtime_canonical_contract_samples_v2.csv"
)

CONTRACT_PATH = (
    OUTPUT_DIRECTORY
    / "optimizer_runtime_canonical_contract_v2.csv"
)

READINESS_PATH = (
    OUTPUT_DIRECTORY
    / "optimizer_runtime_canonical_contract_readiness_v2.csv"
)

METADATA_PATH = (
    OUTPUT_DIRECTORY
    / "optimizer_runtime_canonical_contract_metadata_v2.json"
)


COLUMN_CLASS_PATTERNS = {
    "team_key": [
        r"^team$",
        r"^team_[ab]$",
        r"^team_abbreviation$",
        r"^candidate_team$",
        r"^sending_team$",
        r"^receiving_team$",
        r"^one_side_team$",
        r"^two_side_team$",
        r"^team_sending_(?:one|two)$",
        r".*_team$",
        r"^team_.*",
    ],
    "player_id": [
        r"^player_id$",
        r"^player_[ab]_id$",
        r"^player_[12]_id$",
        r"^[ps][12]?_player_id$",
        r"^one_side_player_id$",
        r"^two_side_player_[12]_id$",
        r".*player.*_id$",
    ],
    "player_name": [
        r"^player_name$",
        r"^player_[ab]_name$",
        r"^player_[12]_name$",
        r"^[ps][12]?_player_name$",
        r"^one_side_player_name$",
        r"^two_side_player_[12]_name$",
        r".*player.*name$",
    ],
    "package_id": [
        r"^pair_id$",
        r"^package_id$",
        r"^trade_id$",
        r"^candidate_id$",
        r"^recommendation_id$",
    ],
    "salary": [
        r"salary",
        r"cap_hit",
        r"apron",
        r"trade_exception",
    ],
    "salary_pass": [
        r"salary.*pass",
        r"both_teams_salary_precheck_pass",
        r"salary_precheck_pass",
    ],
    "fit": [
        r"fit_score",
        r"package_fit",
        r"trade_fit",
        r"basketball_fit",
        r"minimum_team_.*fit",
        r"average_team_.*fit",
    ],
    "realism": [
        r"realism",
        r"plausibility",
        r"acceptance",
        r"probability",
        r"market_score",
        r"realistic",
    ],
    "value": [
        r"value",
        r"surplus",
        r"asset_score",
        r"market_value",
    ],
    "legality": [
        r"legal",
        r"valid_trade",
        r"tradability",
        r"standalone_trade_asset",
        r"stepien",
        r"frozen_pick",
        r"encumber",
        r"ownership",
    ],
    "pick_identifier": [
        r"future_pick_right_id",
        r"source_assets",
        r"primary_source_asset",
        r"right_structure",
    ],
}


def clean_text(value: Any) -> str:
    if value is None:
        return ""

    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass

    return re.sub(
        r"\s+",
        " ",
        str(value),
    ).strip()


def normalize_name(value: Any) -> str:
    return (
        clean_text(value)
        .lower()
        .replace(" ", "_")
        .replace("-", "_")
    )


def json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): json_safe(item)
            for key, item in value.items()
        }

    if isinstance(value, (list, tuple, set)):
        return [json_safe(item) for item in value]

    if isinstance(value, np.integer):
        return int(value)

    if isinstance(value, np.floating):
        return None if np.isnan(value) else float(value)

    if isinstance(value, float):
        return None if math.isnan(value) else value

    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass

    return value


def classify_column(column: str) -> list[str]:
    normalized = normalize_name(column)
    classes = []

    for class_name, patterns in COLUMN_CLASS_PATTERNS.items():
        if any(
            re.search(
                pattern,
                normalized,
                flags=re.IGNORECASE,
            )
            for pattern in patterns
        ):
            classes.append(class_name)

    return classes


def read_frame(path: Path) -> pd.DataFrame:
    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path)

    if path.suffix.lower() == ".csv":
        return pd.read_csv(path)

    raise ValueError(
        f"Unsupported canonical file type: {path}"
    )


def inspect_files() -> tuple[
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    dict[str, pd.DataFrame],
]:
    schema_rows = []
    column_rows = []
    sample_rows = []
    frames: dict[str, pd.DataFrame] = {}

    for index, (role, path) in enumerate(
        CANONICAL_FILES.items(),
        start=1,
    ):
        print(
            f"[{index:02d}/{len(CANONICAL_FILES):02d}] "
            f"Inspecting {path.relative_to(PROJECT_ROOT)}"
        )

        if not path.exists():
            schema_rows.append(
                {
                    "artifact_role": role,
                    "file_path": str(path),
                    "relative_file_path": str(
                        path.relative_to(PROJECT_ROOT)
                    ),
                    "file_exists": False,
                    "row_count": np.nan,
                    "column_count": np.nan,
                    "file_size_bytes": np.nan,
                    "inspection_passed": False,
                    "inspection_error": "file_not_found",
                }
            )
            continue

        try:
            frame = read_frame(path)
            frames[role] = frame

            schema_rows.append(
                {
                    "artifact_role": role,
                    "file_path": str(path),
                    "relative_file_path": str(
                        path.relative_to(PROJECT_ROOT)
                    ),
                    "file_exists": True,
                    "row_count": int(len(frame)),
                    "column_count": int(len(frame.columns)),
                    "file_size_bytes": int(
                        path.stat().st_size
                    ),
                    "inspection_passed": True,
                    "inspection_error": "",
                }
            )

            for column in frame.columns:
                series = frame[column]
                classes = classify_column(str(column))

                column_rows.append(
                    {
                        "artifact_role": role,
                        "relative_file_path": str(
                            path.relative_to(PROJECT_ROOT)
                        ),
                        "column_name": str(column),
                        "normalized_column_name": normalize_name(
                            column
                        ),
                        "dtype": str(series.dtype),
                        "non_null_rows": int(
                            series.notna().sum()
                        ),
                        "unique_non_null_values": int(
                            series.nunique(
                                dropna=True
                            )
                        ),
                        "column_classes": "|".join(classes),
                        **{
                            f"is_{class_name}": bool(
                                class_name in classes
                            )
                            for class_name in COLUMN_CLASS_PATTERNS
                        },
                    }
                )

            sample = frame.head(3).copy()

            for row_number, row in sample.iterrows():
                sample_rows.append(
                    {
                        "artifact_role": role,
                        "relative_file_path": str(
                            path.relative_to(PROJECT_ROOT)
                        ),
                        "sample_row_number": int(row_number),
                        "sample_row_json": json.dumps(
                            json_safe(row.to_dict()),
                            sort_keys=True,
                        ),
                    }
                )
        except Exception as error:
            schema_rows.append(
                {
                    "artifact_role": role,
                    "file_path": str(path),
                    "relative_file_path": str(
                        path.relative_to(PROJECT_ROOT)
                    ),
                    "file_exists": True,
                    "row_count": np.nan,
                    "column_count": np.nan,
                    "file_size_bytes": int(
                        path.stat().st_size
                    ),
                    "inspection_passed": False,
                    "inspection_error": clean_text(error),
                }
            )

    return (
        pd.DataFrame(schema_rows),
        pd.DataFrame(column_rows),
        pd.DataFrame(sample_rows),
        frames,
    )


def columns_for_class(
    columns: pd.DataFrame,
    role: str,
    class_name: str,
) -> list[str]:
    flag_column = f"is_{class_name}"

    if flag_column not in columns.columns:
        return []

    return sorted(
        columns.loc[
            columns[
                "artifact_role"
            ].eq(role)
            & columns[
                flag_column
            ].fillna(False).astype(bool),
            "column_name",
        ].tolist()
    )


def choose_first_existing(
    frame: pd.DataFrame,
    candidates: list[str],
) -> str:
    normalized_lookup = {
        normalize_name(column): str(column)
        for column in frame.columns
    }

    for candidate in candidates:
        if candidate in normalized_lookup:
            return normalized_lookup[candidate]

    return ""


def build_contract(
    columns: pd.DataFrame,
    frames: dict[str, pd.DataFrame],
) -> pd.DataFrame:
    rows = []

    player_frame = frames.get(
        "player_value_layer",
        pd.DataFrame(),
    )

    one_frame = frames.get(
        "one_for_one_runtime",
        pd.DataFrame(),
    )

    two_frame = frames.get(
        "two_for_one_runtime",
        pd.DataFrame(),
    )

    pick_frame = frames.get(
        "future_pick_inventory",
        pd.DataFrame(),
    )

    one_package_id = choose_first_existing(
        one_frame,
        [
            "pair_id",
            "package_id",
            "trade_id",
        ],
    )

    two_package_id = choose_first_existing(
        two_frame,
        [
            "package_id",
            "pair_id",
            "trade_id",
        ],
    )

    player_id = choose_first_existing(
        player_frame,
        [
            "player_id",
            "nba_player_id",
            "person_id",
        ],
    )

    player_team = choose_first_existing(
        player_frame,
        [
            "team_abbreviation",
            "team",
            "current_team",
        ],
    )

    player_value = choose_first_existing(
        player_frame,
        [
            "surplus_value_score",
            "trade_value_score",
            "player_value_score",
        ],
    )

    pick_id = choose_first_existing(
        pick_frame,
        [
            "future_pick_right_id",
        ],
    )

    pick_team = choose_first_existing(
        pick_frame,
        [
            "candidate_team",
        ],
    )

    pick_value = choose_first_existing(
        pick_frame,
        [
            "candidate_right_value_score",
        ],
    )

    pick_standalone = choose_first_existing(
        pick_frame,
        [
            "standalone_trade_asset_flag",
        ],
    )

    rows.extend(
        [
            {
                "contract_branch": "shared_assets",
                "contract_element": "player_asset_key",
                "artifact_role": "player_value_layer",
                "selected_column": player_id,
                "required": True,
                "resolved": bool(player_id),
                "notes": "Unique player identifier.",
            },
            {
                "contract_branch": "shared_assets",
                "contract_element": "player_team_key",
                "artifact_role": "player_value_layer",
                "selected_column": player_team,
                "required": True,
                "resolved": bool(player_team),
                "notes": "Current team used for package ownership.",
            },
            {
                "contract_branch": "shared_assets",
                "contract_element": "player_value_score",
                "artifact_role": "player_value_layer",
                "selected_column": player_value,
                "required": True,
                "resolved": bool(player_value),
                "notes": "Player-side value contribution.",
            },
            {
                "contract_branch": "shared_assets",
                "contract_element": "pick_asset_key",
                "artifact_role": "future_pick_inventory",
                "selected_column": pick_id,
                "required": True,
                "resolved": bool(pick_id),
                "notes": "Unique future-pick right identifier.",
            },
            {
                "contract_branch": "shared_assets",
                "contract_element": "pick_team_key",
                "artifact_role": "future_pick_inventory",
                "selected_column": pick_team,
                "required": True,
                "resolved": bool(pick_team),
                "notes": "Team currently credited with the right.",
            },
            {
                "contract_branch": "shared_assets",
                "contract_element": "pick_value_score",
                "artifact_role": "future_pick_inventory",
                "selected_column": pick_value,
                "required": True,
                "resolved": bool(pick_value),
                "notes": "Pick-side value contribution.",
            },
            {
                "contract_branch": "shared_assets",
                "contract_element": "pick_standalone_filter",
                "artifact_role": "future_pick_inventory",
                "selected_column": pick_standalone,
                "required": True,
                "resolved": bool(pick_standalone),
                "notes": (
                    "Only standalone rights enter package enumeration."
                ),
            },
        ]
    )

    for branch, role, frame, package_id in [
        (
            "one_for_one",
            "one_for_one_runtime",
            one_frame,
            one_package_id,
        ),
        (
            "two_for_one",
            "two_for_one_runtime",
            two_frame,
            two_package_id,
        ),
    ]:
        rows.append(
            {
                "contract_branch": branch,
                "contract_element": "package_identifier",
                "artifact_role": role,
                "selected_column": package_id,
                "required": False,
                "resolved": bool(package_id),
                "notes": (
                    "Use existing package ID when available, otherwise "
                    "construct a deterministic ID from team and player IDs."
                ),
            }
        )

        for class_name in [
            "team_key",
            "player_id",
            "player_name",
            "salary",
            "salary_pass",
            "fit",
            "realism",
            "value",
            "legality",
        ]:
            class_columns = columns_for_class(
                columns,
                role,
                class_name,
            )

            rows.append(
                {
                    "contract_branch": branch,
                    "contract_element": (
                        f"{class_name}_columns"
                    ),
                    "artifact_role": role,
                    "selected_column": "|".join(
                        class_columns
                    ),
                    "required": class_name in {
                        "team_key",
                        "player_id",
                        "salary",
                        "salary_pass",
                        "fit",
                        "realism",
                        "value",
                    },
                    "resolved": bool(class_columns),
                    "notes": (
                        f"Detected {class_name.replace('_', ' ')} "
                        "columns in the enriched runtime artifact."
                    ),
                }
            )

    return pd.DataFrame(rows)


def build_readiness(
    schemas: pd.DataFrame,
    columns: pd.DataFrame,
    frames: dict[str, pd.DataFrame],
    contract: pd.DataFrame,
) -> pd.DataFrame:
    schema_lookup = (
        schemas.set_index("artifact_role")
        if not schemas.empty
        else pd.DataFrame()
    )

    checks = []

    expected_rows = {
        "player_value_layer": 395,
        "one_for_one_runtime": 17147,
        "two_for_one_runtime": 100033,
        "future_pick_inventory": 174,
        "team_salary_profiles": 30,
    }

    for role, expected in expected_rows.items():
        if role in schema_lookup.index:
            row = schema_lookup.loc[role]

            if isinstance(row, pd.DataFrame):
                row = row.iloc[0]

            observed = (
                int(row["row_count"])
                if pd.notna(row["row_count"])
                else None
            )

            passed = bool(
                row["inspection_passed"]
                and observed == expected
            )
        else:
            observed = None
            passed = False

        checks.append(
            {
                "check_name": f"{role}_row_count",
                "observed_value": observed,
                "expected_value": expected,
                "passed": passed,
                "blocking_for_orchestrator": True,
            }
        )

    player_frame = frames.get(
        "player_value_layer",
        pd.DataFrame(),
    )

    pick_frame = frames.get(
        "future_pick_inventory",
        pd.DataFrame(),
    )

    checks.extend(
        [
            {
                "check_name": "player_surplus_value_column",
                "observed_value": (
                    "surplus_value_score"
                    in player_frame.columns
                ),
                "expected_value": True,
                "passed": (
                    "surplus_value_score"
                    in player_frame.columns
                ),
                "blocking_for_orchestrator": True,
            },
            {
                "check_name": "pick_value_column",
                "observed_value": (
                    "candidate_right_value_score"
                    in pick_frame.columns
                ),
                "expected_value": True,
                "passed": (
                    "candidate_right_value_score"
                    in pick_frame.columns
                ),
                "blocking_for_orchestrator": True,
            },
            {
                "check_name": "pick_standalone_column",
                "observed_value": (
                    "standalone_trade_asset_flag"
                    in pick_frame.columns
                ),
                "expected_value": True,
                "passed": (
                    "standalone_trade_asset_flag"
                    in pick_frame.columns
                ),
                "blocking_for_orchestrator": True,
            },
            {
                "check_name": "standalone_pick_row_count",
                "observed_value": int(
                    pick_frame[
                        "standalone_trade_asset_flag"
                    ]
                    .fillna(False)
                    .astype(bool)
                    .sum()
                )
                if (
                    not pick_frame.empty
                    and "standalone_trade_asset_flag"
                    in pick_frame.columns
                )
                else None,
                "expected_value": 172,
                "passed": bool(
                    not pick_frame.empty
                    and "standalone_trade_asset_flag"
                    in pick_frame.columns
                    and int(
                        pick_frame[
                            "standalone_trade_asset_flag"
                        ]
                        .fillna(False)
                        .astype(bool)
                        .sum()
                    )
                    == 172
                ),
                "blocking_for_orchestrator": True,
            },
        ]
    )

    for branch in [
        "one_for_one",
        "two_for_one",
    ]:
        branch_rows = contract.loc[
            contract[
                "contract_branch"
            ].eq(branch)
        ]

        for element in [
            "team_key_columns",
            "player_id_columns",
            "salary_columns",
            "salary_pass_columns",
            "fit_columns",
            "realism_columns",
            "value_columns",
        ]:
            matched = branch_rows.loc[
                branch_rows[
                    "contract_element"
                ].eq(element)
            ]

            resolved = bool(
                not matched.empty
                and matched[
                    "resolved"
                ].fillna(False).astype(bool).all()
            )

            checks.append(
                {
                    "check_name": (
                        f"{branch}_{element}_resolved"
                    ),
                    "observed_value": resolved,
                    "expected_value": True,
                    "passed": resolved,
                    "blocking_for_orchestrator": True,
                }
            )

    required_contract = contract.loc[
        contract[
            "required"
        ].fillna(False).astype(bool)
    ]

    checks.append(
        {
            "check_name": "all_required_contract_elements_resolved",
            "observed_value": int(
                required_contract[
                    "resolved"
                ].fillna(False).astype(bool).sum()
            ),
            "expected_value": int(
                len(required_contract)
            ),
            "passed": bool(
                required_contract[
                    "resolved"
                ].fillna(False).astype(bool).all()
            ),
            "blocking_for_orchestrator": True,
        }
    )

    return pd.DataFrame(checks)


def main() -> None:
    OUTPUT_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    print("=" * 80)
    print("OPTIMIZER CANONICAL RUNTIME CONTRACT AUDIT")
    print("=" * 80)
    print(f"Script version: {SCRIPT_VERSION}")
    print()

    (
        schemas,
        columns,
        samples,
        frames,
    ) = inspect_files()

    contract = build_contract(
        columns,
        frames,
    )

    readiness = build_readiness(
        schemas=schemas,
        columns=columns,
        frames=frames,
        contract=contract,
    )

    schemas.to_csv(
        SCHEMA_PATH,
        index=False,
    )

    columns.to_csv(
        COLUMN_CLASSIFICATION_PATH,
        index=False,
    )

    samples.to_csv(
        SAMPLE_PATH,
        index=False,
    )

    contract.to_csv(
        CONTRACT_PATH,
        index=False,
    )

    readiness.to_csv(
        READINESS_PATH,
        index=False,
    )

    blocking_failures = readiness.loc[
        readiness[
            "blocking_for_orchestrator"
        ]
        & ~readiness[
            "passed"
        ]
    ]

    metadata = {
        "script_version": SCRIPT_VERSION,
        "created_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "canonical_files": {
            role: str(path)
            for role, path in CANONICAL_FILES.items()
        },
        "artifacts_inspected": int(
            schemas[
                "inspection_passed"
            ].fillna(False).astype(bool).sum()
        ),
        "columns_classified": int(len(columns)),
        "contract_rows": int(len(contract)),
        "readiness_checks": int(len(readiness)),
        "readiness_checks_passed": int(
            readiness[
                "passed"
            ].sum()
        ),
        "blocking_failures": int(
            len(blocking_failures)
        ),
        "canonical_orchestrator_contract_ready": bool(
            blocking_failures.empty
        ),
        "output_files": {
            "schema": str(SCHEMA_PATH),
            "columns": str(
                COLUMN_CLASSIFICATION_PATH
            ),
            "samples": str(SAMPLE_PATH),
            "contract": str(CONTRACT_PATH),
            "readiness": str(READINESS_PATH),
        },
    }

    with METADATA_PATH.open(
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            json_safe(metadata),
            file,
            indent=2,
        )

    print()
    print("=" * 80)
    print("OPTIMIZER CANONICAL RUNTIME CONTRACT AUDIT COMPLETE")
    print("=" * 80)
    print(
        "Canonical artifacts inspected: "
        f"{int(schemas['inspection_passed'].fillna(False).astype(bool).sum()):,}"
        f"/{len(CANONICAL_FILES):,}"
    )
    print(
        "Columns classified: "
        f"{len(columns):,}"
    )
    print(
        "Contract rows: "
        f"{len(contract):,}"
    )
    print(
        "Readiness checks passed: "
        f"{int(readiness['passed'].sum()):,}"
        f"/{len(readiness):,}"
    )
    print(
        "Blocking failures: "
        f"{len(blocking_failures):,}"
    )
    print(
        "Canonical orchestrator contract ready: "
        f"{bool(blocking_failures.empty)}"
    )
    print()

    print("CANONICAL ARTIFACT SCHEMA")
    print(
        schemas[
            [
                "artifact_role",
                "relative_file_path",
                "row_count",
                "column_count",
                "inspection_passed",
                "inspection_error",
            ]
        ].to_string(index=False)
    )
    print()

    print("RUNTIME COLUMN CONTRACT")

    display_contract = contract.loc[
        contract[
            "contract_branch"
        ].isin(
            [
                "shared_assets",
                "one_for_one",
                "two_for_one",
            ]
        )
    ]

    print(
        display_contract[
            [
                "contract_branch",
                "contract_element",
                "artifact_role",
                "selected_column",
                "required",
                "resolved",
            ]
        ].to_string(index=False)
    )
    print()

    print("READINESS")
    print(
        readiness.to_string(index=False)
    )
    print()

    print("SAVED FILES")

    for path in [
        SCHEMA_PATH,
        COLUMN_CLASSIFICATION_PATH,
        SAMPLE_PATH,
        CONTRACT_PATH,
        READINESS_PATH,
        METADATA_PATH,
    ]:
        print(path)

    if not blocking_failures.empty:
        raise RuntimeError(
            "Canonical runtime contract still has blocking failures:\n"
            + blocking_failures.to_string(index=False)
        )


if __name__ == "__main__":
    main()