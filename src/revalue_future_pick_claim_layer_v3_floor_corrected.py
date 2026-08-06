from __future__ import annotations

import importlib.util
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType
from typing import Any

import numpy as np
import pandas as pd


SCRIPT_VERSION = (
    "future-pick-claim-layer-v3-floor-corrected-2026-08-04"
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]

SOURCE_CLAIMS_PATH = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "future_pick_obligation_claims_2027_2029_v2.parquet"
)

V3_PICK_VALUES_PATH = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "future_originating_team_pick_values_2027_2029_v3_floor_corrected.parquet"
)

V3_SIMULATION_BANK_PATH = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "future_draft_pick_simulation_bank_2027_2029_v3_floor_corrected.npz"
)

VALUATION_ENGINE_PATH = (
    PROJECT_ROOT
    / "src"
    / "value_future_pick_protections_and_swaps_v1.py"
)

OLD_VALUATIONS_PATH = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "future_pick_claim_value_layer_2027_2029_v1.parquet"
)

PROCESSED_DIRECTORY = (
    PROJECT_ROOT
    / "data"
    / "processed"
)

OUTPUT_DIRECTORY = PROJECT_ROOT / "outputs"

V3_CLAIMS_PARQUET_PATH = (
    PROCESSED_DIRECTORY
    / "future_pick_obligation_claims_2027_2029_v3_floor_corrected.parquet"
)

V3_CLAIMS_CSV_PATH = (
    PROCESSED_DIRECTORY
    / "future_pick_obligation_claims_2027_2029_v3_floor_corrected.csv"
)

V3_VALUATIONS_PARQUET_PATH = (
    PROCESSED_DIRECTORY
    / "future_pick_claim_value_layer_2027_2029_v3_floor_corrected.parquet"
)

V3_VALUATIONS_CSV_PATH = (
    PROCESSED_DIRECTORY
    / "future_pick_claim_value_layer_2027_2029_v3_floor_corrected.csv"
)

V3_DIRECT_VALUES_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_direct_asset_values_2027_2029_v3_floor_corrected.csv"
)

V3_PROTECTION_VALUES_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_protection_value_components_2027_2029_v3_floor_corrected.csv"
)

V3_SWAP_VALUES_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_simple_swap_option_values_2027_2029_v3_floor_corrected.csv"
)

V3_UNRESOLVED_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_unresolved_complex_claims_2027_2029_v3_floor_corrected.csv"
)

V3_TEAM_SUMMARY_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_candidate_team_value_summary_2027_2029_v3_floor_corrected.csv"
)

V3_VALUATION_METADATA_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_conditional_swap_value_metadata_v3_floor_corrected.json"
)

V1_TO_V3_COMPARISON_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_claim_value_v1_to_v3_comparison.csv"
)

REBASE_AUDIT_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_claim_rebase_audit_v3_floor_corrected.csv"
)

WRAPPER_METADATA_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_claim_layer_rebase_metadata_v3_floor_corrected.json"
)


KEY_COLUMNS = [
    "draft_year",
    "round_number",
    "originating_team",
]

VALUE_COLUMNS = [
    "expected_overall_pick",
    "time_discount_factor",
    "time_discounted_pick_value_score",
    "expected_pick_value_rating_60_99",
]

COMPARISON_COLUMNS = [
    "conveyance_probability",
    "retention_probability",
    "swap_exercise_probability",
    "expected_transferred_value_score",
    "expected_retained_value_score",
    "expected_swap_option_value_score",
    "expected_total_candidate_asset_value_score",
]


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


def numeric_series(
    frame: pd.DataFrame,
    column: str,
) -> pd.Series:
    return pd.to_numeric(
        frame[
            column
        ],
        errors="coerce",
    ).astype(
        float
    )


def json_safe(
    value: Any,
) -> Any:
    if isinstance(
        value,
        dict,
    ):
        return {
            str(key): json_safe(
                item
            )
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
            json_safe(
                item
            )
            for item in value
        ]

    if isinstance(
        value,
        np.integer,
    ):
        return int(
            value
        )

    if isinstance(
        value,
        np.floating,
    ):
        if np.isnan(
            value
        ):
            return None

        return float(
            value
        )

    if isinstance(
        value,
        float,
    ):
        if math.isnan(
            value
        ):
            return None

        return value

    if pd.isna(
        value
    ):
        return None

    return value


def load_valuation_engine() -> ModuleType:
    if not VALUATION_ENGINE_PATH.exists():
        raise FileNotFoundError(
            "The protection and swap valuation engine was not found:\n"
            f"{VALUATION_ENGINE_PATH}"
        )

    specification = importlib.util.spec_from_file_location(
        "future_pick_valuation_engine",
        VALUATION_ENGINE_PATH,
    )

    if (
        specification is None
        or specification.loader is None
    ):
        raise ImportError(
            "Could not import the valuation engine:\n"
            f"{VALUATION_ENGINE_PATH}"
        )

    module = importlib.util.module_from_spec(
        specification
    )

    specification.loader.exec_module(
        module
    )

    required_attributes = [
        "main",
        "load_claims",
        "SimulationBank",
        "SlotValueLookup",
        "classify_and_value",
        "build_team_candidate_summary",
    ]

    missing = [
        attribute
        for attribute in required_attributes
        if not hasattr(
            module,
            attribute,
        )
    ]

    if missing:
        raise AttributeError(
            "The local valuation engine is missing required functions:\n"
            + "\n".join(
                missing
            )
        )

    return module


def build_rebased_claims() -> tuple[
    pd.DataFrame,
    pd.DataFrame,
]:
    for path in [
        SOURCE_CLAIMS_PATH,
        V3_PICK_VALUES_PATH,
        V3_SIMULATION_BANK_PATH,
    ]:
        if not path.exists():
            raise FileNotFoundError(
                "A required V3 rebase input was not found:\n"
                f"{path}"
            )

    claims = normalize_columns(
        pd.read_parquet(
            SOURCE_CLAIMS_PATH
        )
    )

    pick_values = normalize_columns(
        pd.read_parquet(
            V3_PICK_VALUES_PATH
        )
    )

    require_columns(
        claims,
        [
            "claim_id",
            *KEY_COLUMNS,
            *VALUE_COLUMNS,
        ],
        "Source obligation claims",
    )

    require_columns(
        pick_values,
        [
            *KEY_COLUMNS,
            *VALUE_COLUMNS,
        ],
        "V3 originating-team pick values",
    )

    for frame in [
        claims,
        pick_values,
    ]:
        frame[
            "draft_year"
        ] = numeric_series(
            frame,
            "draft_year",
        ).round().astype(
            int
        )

        frame[
            "round_number"
        ] = numeric_series(
            frame,
            "round_number",
        ).round().astype(
            int
        )

        frame[
            "originating_team"
        ] = (
            frame[
                "originating_team"
            ]
            .astype(
                str
            )
            .str.strip()
        )

    duplicate_mask = pick_values.duplicated(
        subset=KEY_COLUMNS,
        keep=False,
    )

    if duplicate_mask.any():
        raise ValueError(
            "The V3 pick-value table contains duplicate team-year-round rows."
        )

    v3_subset = pick_values[
        [
            *KEY_COLUMNS,
            *VALUE_COLUMNS,
        ]
    ].copy()

    v3_subset = v3_subset.rename(
        columns={
            column: (
                f"{column}_v3"
            )
            for column in VALUE_COLUMNS
        }
    )

    merged = claims.merge(
        v3_subset,
        how="left",
        on=KEY_COLUMNS,
        validate="many_to_one",
    )

    missing_v3 = merged[
        "expected_overall_pick_v3"
    ].isna()

    if missing_v3.any():
        missing_rows = (
            merged.loc[
                missing_v3,
                KEY_COLUMNS,
            ]
            .drop_duplicates()
            .to_dict(
                orient="records"
            )
        )

        raise ValueError(
            "Some claims did not match the V3 pick-value table:\n"
            + json.dumps(
                missing_rows,
                indent=2,
            )
        )

    audit_rows = []

    for column in VALUE_COLUMNS:
        old_values = numeric_series(
            merged,
            column,
        )

        new_column = (
            f"{column}_v3"
        )

        new_values = numeric_series(
            merged,
            new_column,
        )

        merged[
            column
        ] = new_values

        difference = (
            new_values
            - old_values
        )

        audit_rows.append(
            {
                "field": (
                    column
                ),
                "rows": len(
                    merged
                ),
                "changed_rows": int(
                    (
                        difference.abs()
                        > 1e-12
                    ).sum()
                ),
                "mean_change_v3_minus_previous": float(
                    difference.mean()
                ),
                "maximum_absolute_change": float(
                    difference.abs().max()
                ),
            }
        )

    merged = merged.drop(
        columns=[
            f"{column}_v3"
            for column in VALUE_COLUMNS
        ]
    )

    merged[
        "pick_value_source_version"
    ] = (
        "future-originating-team-pick-values-v3-floor-corrected"
    )

    merged[
        "simulation_bank_source_version"
    ] = (
        "future-draft-pick-simulation-bank-v3-floor-corrected"
    )

    merged[
        "claim_value_rebased_at_utc"
    ] = datetime.now(
        timezone.utc
    ).isoformat()

    if merged[
        "claim_id"
    ].duplicated().any():
        raise ValueError(
            "The rebased claims contain duplicate claim IDs."
        )

    return (
        merged,
        pd.DataFrame(
            audit_rows
        ),
    )


def configure_engine(
    module: ModuleType,
) -> None:
    module.SCRIPT_VERSION = (
        "future-pick-conditional-swap-value-v3-floor-corrected-2026-08-04"
    )

    module.CLAIMS_PATH = (
        V3_CLAIMS_PARQUET_PATH
    )

    module.SIMULATION_BANK_PATH = (
        V3_SIMULATION_BANK_PATH
    )

    module.ALL_VALUATIONS_PARQUET_PATH = (
        V3_VALUATIONS_PARQUET_PATH
    )

    module.ALL_VALUATIONS_CSV_PATH = (
        V3_VALUATIONS_CSV_PATH
    )

    module.DIRECT_ASSET_VALUES_PATH = (
        V3_DIRECT_VALUES_PATH
    )

    module.PROTECTION_VALUATIONS_PATH = (
        V3_PROTECTION_VALUES_PATH
    )

    module.SWAP_VALUATIONS_PATH = (
        V3_SWAP_VALUES_PATH
    )

    module.UNRESOLVED_REVIEW_PATH = (
        V3_UNRESOLVED_PATH
    )

    module.TEAM_CANDIDATE_SUMMARY_PATH = (
        V3_TEAM_SUMMARY_PATH
    )

    module.METADATA_PATH = (
        V3_VALUATION_METADATA_PATH
    )


def build_valuation_comparison(
    new_valuations: pd.DataFrame,
) -> pd.DataFrame:
    if not OLD_VALUATIONS_PATH.exists():
        output = new_valuations[
            [
                "claim_id",
                "valuation_method",
                "valuation_status",
            ]
        ].copy()

        output[
            "previous_valuation_available"
        ] = False

        return output

    old = normalize_columns(
        pd.read_parquet(
            OLD_VALUATIONS_PATH
        )
    )

    new = normalize_columns(
        new_valuations
    )

    require_columns(
        old,
        [
            "claim_id",
            "valuation_method",
            "valuation_status",
        ],
        "Previous valuations",
    )

    require_columns(
        new,
        [
            "claim_id",
            "valuation_method",
            "valuation_status",
        ],
        "V3 valuations",
    )

    old_columns = [
        "claim_id",
        "valuation_method",
        "valuation_status",
        *[
            column
            for column in COMPARISON_COLUMNS
            if column in old.columns
        ],
    ]

    new_columns = [
        "claim_id",
        "valuation_method",
        "valuation_status",
        *[
            column
            for column in COMPARISON_COLUMNS
            if column in new.columns
        ],
    ]

    old_subset = old[
        old_columns
    ].copy().rename(
        columns={
            column: (
                f"{column}_previous"
            )
            for column in old_columns
            if column
            != "claim_id"
        }
    )

    new_subset = new[
        new_columns
    ].copy().rename(
        columns={
            column: (
                f"{column}_v3"
            )
            for column in new_columns
            if column
            != "claim_id"
        }
    )

    comparison = new_subset.merge(
        old_subset,
        how="left",
        on="claim_id",
        validate="one_to_one",
    )

    for column in COMPARISON_COLUMNS:
        new_column = (
            f"{column}_v3"
        )

        old_column = (
            f"{column}_previous"
        )

        if (
            new_column in comparison.columns
            and old_column in comparison.columns
        ):
            comparison[
                f"{column}_change_v3_minus_previous"
            ] = (
                pd.to_numeric(
                    comparison[
                        new_column
                    ],
                    errors="coerce",
                )
                - pd.to_numeric(
                    comparison[
                        old_column
                    ],
                    errors="coerce",
                )
            )

    comparison[
        "previous_valuation_available"
    ] = (
        comparison[
            "valuation_method_previous"
        ].notna()
    )

    change_columns = [
        column
        for column in comparison.columns
        if column.endswith(
            "_change_v3_minus_previous"
        )
    ]

    if change_columns:
        comparison[
            "maximum_absolute_value_change"
        ] = (
            comparison[
                change_columns
            ]
            .abs()
            .max(
                axis=1
            )
        )
    else:
        comparison[
            "maximum_absolute_value_change"
        ] = np.nan

    return comparison.sort_values(
        [
            "maximum_absolute_value_change",
            "claim_id",
        ],
        ascending=[
            False,
            True,
        ],
        na_position="last",
    ).reset_index(
        drop=True
    )


def main() -> None:
    for directory in [
        PROCESSED_DIRECTORY,
        OUTPUT_DIRECTORY,
    ]:
        directory.mkdir(
            parents=True,
            exist_ok=True,
        )

    print("=" * 80)
    print("FUTURE NBA PICK CLAIM LAYER V3 REBASE")
    print("=" * 80)
    print(
        f"Script version: {SCRIPT_VERSION}"
    )
    print()

    (
        rebased_claims,
        rebase_audit,
    ) = build_rebased_claims()

    rebased_claims.to_parquet(
        V3_CLAIMS_PARQUET_PATH,
        index=False,
    )

    rebased_claims.to_csv(
        V3_CLAIMS_CSV_PATH,
        index=False,
    )

    rebase_audit.to_csv(
        REBASE_AUDIT_PATH,
        index=False,
    )

    engine = load_valuation_engine()

    configure_engine(
        engine
    )

    print(
        "Running the existing protection and swap engine "
        "against the floor-corrected V3 bank."
    )
    print()

    engine.main()

    if not V3_VALUATIONS_PARQUET_PATH.exists():
        raise RuntimeError(
            "The V3 valuation engine did not create its expected output."
        )

    valuations = pd.read_parquet(
        V3_VALUATIONS_PARQUET_PATH
    )

    comparison = build_valuation_comparison(
        valuations
    )

    comparison.to_csv(
        V1_TO_V3_COMPARISON_PATH,
        index=False,
    )

    method_counts = (
        valuations[
            "valuation_method"
        ]
        .value_counts(
            dropna=False
        )
        .to_dict()
    )

    change_summary = {}

    if (
        "maximum_absolute_value_change"
        in comparison.columns
    ):
        finite_changes = pd.to_numeric(
            comparison[
                "maximum_absolute_value_change"
            ],
            errors="coerce",
        ).dropna()

        if not finite_changes.empty:
            change_summary = {
                "mean_maximum_absolute_claim_change": float(
                    finite_changes.mean()
                ),
                "maximum_absolute_claim_change": float(
                    finite_changes.max()
                ),
                "claims_changed_more_than_0_01": int(
                    (
                        finite_changes
                        > 0.01
                    ).sum()
                ),
                "claims_changed_more_than_0_10": int(
                    (
                        finite_changes
                        > 0.10
                    ).sum()
                ),
            }

    metadata = {
        "script_version": (
            SCRIPT_VERSION
        ),
        "created_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "source_claim_rows": len(
            rebased_claims
        ),
        "v3_valuation_rows": len(
            valuations
        ),
        "valuation_method_counts": (
            method_counts
        ),
        "rebase_field_audit": (
            rebase_audit.to_dict(
                orient="records"
            )
        ),
        "comparison_summary": (
            change_summary
        ),
        "source_files": {
            "source_claims": str(
                SOURCE_CLAIMS_PATH
            ),
            "v3_originating_pick_values": str(
                V3_PICK_VALUES_PATH
            ),
            "v3_simulation_bank": str(
                V3_SIMULATION_BANK_PATH
            ),
            "valuation_engine": str(
                VALUATION_ENGINE_PATH
            ),
        },
        "output_files": {
            "rebased_claims": str(
                V3_CLAIMS_PARQUET_PATH
            ),
            "v3_valuations": str(
                V3_VALUATIONS_PARQUET_PATH
            ),
            "v3_team_summary": str(
                V3_TEAM_SUMMARY_PATH
            ),
            "rebase_audit": str(
                REBASE_AUDIT_PATH
            ),
            "previous_to_v3_comparison": str(
                V1_TO_V3_COMPARISON_PATH
            ),
        },
        "scope_note": (
            "This script updates originating-pick values, current-year "
            "protection components, and simple swap options to the "
            "floor-corrected V3 simulation bank. Linked rollover fallback "
            "value remains a separate downstream calculation."
        ),
    }

    with WRAPPER_METADATA_PATH.open(
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

    print()
    print("=" * 80)
    print("V3 CLAIM AND VALUATION LAYER CREATED")
    print("=" * 80)
    print(
        f"Rebased claim rows: "
        f"{len(rebased_claims):,}"
    )
    print(
        f"V3 valuation rows: "
        f"{len(valuations):,}"
    )
    print()

    print("REBASE FIELD AUDIT")
    display_audit = rebase_audit.copy()

    for column in [
        "mean_change_v3_minus_previous",
        "maximum_absolute_change",
    ]:
        display_audit[
            column
        ] = pd.to_numeric(
            display_audit[
                column
            ],
            errors="coerce",
        ).round(
            6
        )

    print(
        display_audit.to_string(
            index=False
        )
    )
    print()

    print("VALUATION METHODS")
    method_display = (
        valuations[
            "valuation_method"
        ]
        .value_counts(
            dropna=False
        )
        .rename_axis(
            "valuation_method"
        )
        .reset_index(
            name="rows"
        )
    )

    print(
        method_display.to_string(
            index=False
        )
    )
    print()

    if change_summary:
        print("CHANGE SUMMARY VERSUS PREVIOUS LAYER")
        for key, value in change_summary.items():
            if isinstance(
                value,
                float,
            ):
                print(
                    f"{key}: {value:.6f}"
                )
            else:
                print(
                    f"{key}: {value:,}"
                )
        print()

    if (
        "maximum_absolute_value_change"
        in comparison.columns
    ):
        print("LARGEST CLAIM-VALUE CHANGES")
        display_columns = [
            "claim_id",
            "valuation_method_v3",
            "valuation_status_v3",
            "maximum_absolute_value_change",
        ]

        for column in [
            (
                "expected_transferred_value_score_"
                "change_v3_minus_previous"
            ),
            (
                "expected_retained_value_score_"
                "change_v3_minus_previous"
            ),
            (
                "expected_swap_option_value_score_"
                "change_v3_minus_previous"
            ),
        ]:
            if column in comparison.columns:
                display_columns.append(
                    column
                )

        largest = comparison[
            display_columns
        ].head(
            20
        ).copy()

        numeric_columns = [
            column
            for column in largest.columns
            if column
            not in {
                "claim_id",
                "valuation_method_v3",
                "valuation_status_v3",
            }
        ]

        for column in numeric_columns:
            largest[
                column
            ] = pd.to_numeric(
                largest[
                    column
                ],
                errors="coerce",
            ).round(
                6
            )

        print(
            largest.to_string(
                index=False
            )
        )
        print()

    print("SAVED FILES")
    print(V3_CLAIMS_PARQUET_PATH)
    print(V3_CLAIMS_CSV_PATH)
    print(V3_VALUATIONS_PARQUET_PATH)
    print(V3_VALUATIONS_CSV_PATH)
    print(V3_DIRECT_VALUES_PATH)
    print(V3_PROTECTION_VALUES_PATH)
    print(V3_SWAP_VALUES_PATH)
    print(V3_UNRESOLVED_PATH)
    print(V3_TEAM_SUMMARY_PATH)
    print(V3_VALUATION_METADATA_PATH)
    print(REBASE_AUDIT_PATH)
    print(V1_TO_V3_COMPARISON_PATH)
    print(WRAPPER_METADATA_PATH)


if __name__ == "__main__":
    main()
