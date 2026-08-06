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
    "future-pick-optimizer-final-correction-validation-v3-2026-08-04"
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]

POLICY_TEAM_COMPARISON_PATH = (
    PROJECT_ROOT
    / "outputs"
    / "future_pick_optimizer_reconciliation_policy_team_comparison_v1.csv"
)

FINAL_VALUATION_PATH = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "future_pick_claim_value_layer_2027_2029_final.parquet"
)

REJECTED_INVENTORY_PATH = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "future_pick_optimizer_inventory_2027_2029_final.parquet"
)

UTAH_POOL_RIGHTS_FILE_STEM = (
    "future_pick_utah_2028_pool_candidate_rights_ledger_v1"
)

UTAH_POOL_ADJUSTMENTS_FILE_STEM = (
    "future_pick_utah_2028_pool_full_team_adjustments_v1"
)

OUTPUT_DIRECTORY = PROJECT_ROOT / "outputs"

CORRECTION_LEDGER_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_optimizer_final_correction_ledger_v2.csv"
)

CORRECTED_TEAM_RECONCILIATION_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_optimizer_corrected_team_reconciliation_proof_v2.csv"
)

UTAH_CORRECTION_CANDIDATES_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_optimizer_utah_pool_correction_candidates_v2.csv"
)

UTAH_SELECTED_CORRECTIONS_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_optimizer_utah_pool_selected_corrections_v2.csv"
)

MIA_ROLLOVER_AUDIT_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_optimizer_mia_rollover_correction_audit_v2.csv"
)

CLE_MIN_UTA_RECOVERY_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_optimizer_cle_min_uta_2027_first_round_recovery_v2.csv"
)

VALIDATION_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_optimizer_final_correction_validation_v2.csv"
)

METADATA_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_optimizer_final_correction_metadata_v2.json"
)


BEST_POLICY = "role_split_swap_to_beneficiary"

UTAH_CORRECTION_TEAMS = {
    "CHA",
    "DET",
    "PHI",
    "UTA",
}

MIA_CLAIM_ID = "2027_R1_MIA_C1"

CLE_MIN_UTA_COMPONENT_FILE = (
    "future_pick_cle_min_uta_2027_candidate_rights_v1.parquet"
)

VALUE_TOLERANCE = 1e-6
EXPECTED_TEAM_ROWS = 30

UTAH_VALUE_COLUMN_PRIORITY = {
    ("adjustments", "net_team_adjustment_value_score"): 0,
    ("rights", "expected_candidate_right_value_score"): 1,
    ("adjustments", "full_integrated_right_value_score"): 2,
    ("rights", "full_integrated_right_value_score"): 3,
    ("rights", "candidate_right_value_score"): 4,
    ("adjustments", "candidate_right_value_score"): 5,
    ("adjustments", "expected_candidate_right_value_score"): 6,
    ("rights", "net_team_adjustment_value_score"): 7,
    ("rights", "expected_value_score"): 8,
    ("adjustments", "expected_value_score"): 9,
}

KNOWN_UTAH_VALUE_COLUMNS = [
    "net_team_adjustment_value_score",
    "expected_candidate_right_value_score",
    "full_integrated_right_value_score",
    "candidate_right_value_score",
    "expected_value_score",
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


def finite_or_nan(
    value: Any,
) -> float:
    number = pd.to_numeric(
        pd.Series(
            [
                value
            ]
        ),
        errors="coerce",
    ).iloc[
        0
    ]

    return (
        float(
            number
        )
        if pd.notna(
            number
        )
        and np.isfinite(
            number
        )
        else np.nan
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


def first_existing_column(
    frame: pd.DataFrame,
    candidates: list[str],
) -> str:
    for column in candidates:
        if column in frame.columns:
            return column

    return ""


def resolve_project_table(
    file_stem: str,
) -> Path:
    directories = [
        PROJECT_ROOT / "outputs",
        PROJECT_ROOT / "data" / "processed",
    ]

    candidates = []

    for directory in directories:
        for suffix in [
            ".parquet",
            ".csv",
        ]:
            path = directory / f"{file_stem}{suffix}"

            if path.exists():
                candidates.append(
                    path
                )

    if not candidates:
        searched = [
            str(
                directory
                / f"{file_stem}{suffix}"
            )
            for directory in directories
            for suffix in [
                ".parquet",
                ".csv",
            ]
        ]

        raise FileNotFoundError(
            "Required project table was not found. Searched:\n"
            + "\n".join(
                searched
            )
        )

    return sorted(
        candidates,
        key=lambda path: (
            0
            if path.suffix.lower()
            == ".parquet"
            else 1,
            0
            if "processed" in path.parts
            else 1,
            str(
                path
            ),
        ),
    )[
        0
    ]


def read_project_table(
    path: Path,
) -> pd.DataFrame:
    if path.suffix.lower() == ".parquet":
        return normalize_columns(
            pd.read_parquet(
                path
            )
        )

    if path.suffix.lower() == ".csv":
        return normalize_columns(
            pd.read_csv(
                path
            )
        )

    raise ValueError(
        f"Unsupported table extension: {path}"
    )


def load_inputs() -> tuple[
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    Path,
    Path,
]:
    rights_path = resolve_project_table(
        UTAH_POOL_RIGHTS_FILE_STEM
    )

    adjustments_path = resolve_project_table(
        UTAH_POOL_ADJUSTMENTS_FILE_STEM
    )

    for path in [
        POLICY_TEAM_COMPARISON_PATH,
        FINAL_VALUATION_PATH,
        REJECTED_INVENTORY_PATH,
    ]:
        if not path.exists():
            raise FileNotFoundError(
                "Required correction-validation input was not found:\n"
                f"{path}"
            )

    policy_teams = normalize_columns(
        pd.read_csv(
            POLICY_TEAM_COMPARISON_PATH
        )
    )

    valuations = normalize_columns(
        pd.read_parquet(
            FINAL_VALUATION_PATH
        )
    )

    rejected_inventory = normalize_columns(
        pd.read_parquet(
            REJECTED_INVENTORY_PATH
        )
    )

    rights = read_project_table(
        rights_path
    )

    adjustments = read_project_table(
        adjustments_path
    )

    require_columns(
        policy_teams,
        [
            "policy",
            "candidate_team",
            "canonical_final_team_value_score",
            "policy_inventory_value_score",
            "policy_value_difference",
        ],
        "Policy team comparison",
    )

    require_columns(
        valuations,
        [
            "claim_id",
            "asset_key",
            "valuation_method",
        ],
        "Canonical valuation layer",
    )

    return (
        policy_teams,
        valuations,
        rights,
        adjustments,
        rejected_inventory,
        rights_path,
        adjustments_path,
    )


def best_policy_team_rows(
    policy_teams: pd.DataFrame,
) -> pd.DataFrame:
    output = policy_teams.loc[
        policy_teams[
            "policy"
        ]
        .fillna("")
        .astype(str)
        .eq(
            BEST_POLICY
        )
    ].copy()

    if len(
        output
    ) != EXPECTED_TEAM_ROWS:
        raise RuntimeError(
            "Best-policy comparison does not contain 30 teams."
        )

    output[
        "candidate_team"
    ] = (
        output[
            "candidate_team"
        ]
        .fillna("")
        .astype(str)
        .str.upper()
        .str.strip()
    )

    output[
        "required_correction"
    ] = (
        -pd.to_numeric(
            output[
                "policy_value_difference"
            ],
            errors="raise",
        )
    )

    return output


def collect_utah_candidates_from_table(
    frame: pd.DataFrame,
    source_kind: str,
    source_path: Path,
    requirements: pd.DataFrame,
) -> pd.DataFrame:
    team_column = first_existing_column(
        frame,
        [
            "candidate_team",
            "candidate_beneficiary_team",
            "team",
        ],
    )

    if not team_column:
        raise RuntimeError(
            f"Could not identify a team column in {source_path}."
        )

    available_value_columns = [
        column
        for column in KNOWN_UTAH_VALUE_COLUMNS
        if column in frame.columns
        and pd.to_numeric(
            frame[
                column
            ],
            errors="coerce",
        ).notna().any()
    ]

    if not available_value_columns:
        raise RuntimeError(
            f"No recognized Utah-pool value columns were found in "
            f"{source_path}."
        )

    normalized = frame.copy()

    normalized[
        "_candidate_team"
    ] = (
        normalized[
            team_column
        ]
        .fillna("")
        .astype(str)
        .str.upper()
        .str.strip()
    )

    requirement_lookup = (
        requirements.set_index(
            "candidate_team"
        )[
            "required_correction"
        ]
        .to_dict()
    )

    rows = []

    for row_number, row in normalized.iterrows():
        team = clean_text(
            row.get(
                "_candidate_team",
                "",
            )
        )

        if team not in UTAH_CORRECTION_TEAMS:
            continue

        required = float(
            requirement_lookup[
                team
            ]
        )

        for value_column in available_value_columns:
            value = finite_or_nan(
                row.get(
                    value_column,
                    np.nan,
                )
            )

            if not np.isfinite(
                value
            ):
                continue

            difference = (
                value
                - required
            )

            rows.append(
                {
                    "candidate_team": team,
                    "required_correction": required,
                    "source_kind": source_kind,
                    "source_file": source_path.name,
                    "source_path": str(
                        source_path
                    ),
                    "source_row_number": int(
                        row_number
                    ),
                    "detected_team_column": team_column,
                    "value_column": value_column,
                    "candidate_correction_value_score": float(
                        value
                    ),
                    "candidate_minus_required": float(
                        difference
                    ),
                    "absolute_candidate_minus_required": abs(
                        float(
                            difference
                        )
                    ),
                    "exact_required_correction_match": bool(
                        abs(
                            difference
                        )
                        <= VALUE_TOLERANCE
                    ),
                    "selection_priority": int(
                        UTAH_VALUE_COLUMN_PRIORITY.get(
                            (
                                source_kind,
                                value_column,
                            ),
                            100,
                        )
                    ),
                    "source_row_json": json.dumps(
                        json_safe(
                            row.drop(
                                labels=[
                                    "_candidate_team",
                                ],
                                errors="ignore",
                            ).to_dict()
                        ),
                        sort_keys=True,
                    ),
                }
            )

    return pd.DataFrame(
        rows
    )


def select_utah_corrections(
    policy_rows: pd.DataFrame,
    rights: pd.DataFrame,
    adjustments: pd.DataFrame,
    rights_path: Path,
    adjustments_path: Path,
) -> tuple[
    pd.DataFrame,
    pd.DataFrame,
]:
    requirements = policy_rows.loc[
        policy_rows[
            "candidate_team"
        ].isin(
            UTAH_CORRECTION_TEAMS
        ),
        [
            "candidate_team",
            "required_correction",
        ],
    ].copy()

    candidate_frames = [
        collect_utah_candidates_from_table(
            frame=rights,
            source_kind="rights",
            source_path=rights_path,
            requirements=requirements,
        ),
        collect_utah_candidates_from_table(
            frame=adjustments,
            source_kind="adjustments",
            source_path=adjustments_path,
            requirements=requirements,
        ),
    ]

    candidates = pd.concat(
        candidate_frames,
        ignore_index=True,
        sort=False,
    )

    exact = candidates.loc[
        candidates[
            "exact_required_correction_match"
        ]
    ].copy()

    selected_rows = []

    for team in sorted(
        UTAH_CORRECTION_TEAMS
    ):
        matches = exact.loc[
            exact[
                "candidate_team"
            ].eq(
                team
            )
        ].sort_values(
            [
                "selection_priority",
                "source_kind",
                "value_column",
                "source_row_number",
            ]
        )

        if matches.empty:
            team_candidates = candidates.loc[
                candidates[
                    "candidate_team"
                ].eq(
                    team
                )
            ].sort_values(
                "absolute_candidate_minus_required"
            )

            raise RuntimeError(
                f"No Utah-pool value exactly matches {team}'s "
                "required correction.\n"
                + team_candidates.head(
                    20
                ).to_string(
                    index=False
                )
            )

        selected_rows.append(
            matches.iloc[
                0
            ].to_dict()
        )

    selected = pd.DataFrame(
        selected_rows
    )

    selected[
        "correction_value_score"
    ] = selected[
        "candidate_correction_value_score"
    ]

    selected[
        "correction_type"
    ] = (
        "add_missing_utah_2028_pool_increment"
    )

    selected[
        "source_right_rows"
    ] = 1

    selected[
        "source_reference"
    ] = (
        selected[
            "source_file"
        ]
        + ":"
        + selected[
            "value_column"
        ]
    )

    selected[
        "claim_id"
    ] = ""

    selected[
        "correction_sign"
    ] = 1.0

    return (
        candidates.sort_values(
            [
                "candidate_team",
                "exact_required_correction_match",
                "selection_priority",
                "absolute_candidate_minus_required",
            ],
            ascending=[
                True,
                False,
                True,
                True,
            ],
        ).reset_index(
            drop=True
        ),
        selected.sort_values(
            "candidate_team"
        ).reset_index(
            drop=True
        ),
    )


def build_mia_correction(
    valuations: pd.DataFrame,
) -> tuple[
    pd.DataFrame,
    float,
]:
    row = valuations.loc[
        valuations[
            "claim_id"
        ]
        .fillna("")
        .astype(str)
        .eq(
            MIA_CLAIM_ID
        )
    ].copy()

    if len(
        row
    ) != 1:
        raise RuntimeError(
            f"Expected exactly one {MIA_CLAIM_ID} row, "
            f"found {len(row)}."
        )

    fallback_column = first_existing_column(
        row,
        [
            "expected_fallback_transfer_value_score",
            "fallback_transfer_value_score",
        ],
    )

    retained_column = first_existing_column(
        row,
        [
            "expected_retained_value_score",
            "retained_value_score",
        ],
    )

    if not fallback_column or not retained_column:
        raise RuntimeError(
            "Miami rollover row is missing fallback or retained value."
        )

    fallback_value = finite_or_nan(
        row.iloc[
            0
        ][
            fallback_column
        ]
    )

    retained_value = finite_or_nan(
        row.iloc[
            0
        ][
            retained_column
        ]
    )

    if not np.isfinite(
        fallback_value
    ) or not np.isfinite(
        retained_value
    ):
        raise RuntimeError(
            "Miami fallback or retained value is not finite."
        )

    audit = row.copy()

    audit[
        "detected_fallback_column"
    ] = fallback_column

    audit[
        "detected_retained_column"
    ] = retained_column

    audit[
        "fallback_value_to_remove_from_mia"
    ] = fallback_value

    audit[
        "mia_net_retained_value_after_fallback"
    ] = (
        retained_value
        - fallback_value
    )

    return (
        audit,
        float(
            fallback_value
        ),
    )


def build_correction_ledger(
    utah_selected: pd.DataFrame,
    mia_fallback_value: float,
) -> pd.DataFrame:
    utah = utah_selected[
        [
            "candidate_team",
            "correction_value_score",
            "source_right_rows",
            "correction_type",
            "source_reference",
            "claim_id",
            "correction_sign",
            "required_correction",
            "source_kind",
            "source_file",
            "source_path",
            "source_row_number",
            "value_column",
        ]
    ].copy()

    mia = pd.DataFrame(
        [
            {
                "candidate_team": "MIA",
                "correction_value_score": (
                    -mia_fallback_value
                ),
                "source_right_rows": 1,
                "correction_type": (
                    "subtract_rollover_fallback_from_retaining_team"
                ),
                "source_reference": MIA_CLAIM_ID,
                "claim_id": MIA_CLAIM_ID,
                "correction_sign": -1.0,
                "required_correction": (
                    -mia_fallback_value
                ),
                "source_kind": "canonical_valuation",
                "source_file": FINAL_VALUATION_PATH.name,
                "source_path": str(
                    FINAL_VALUATION_PATH
                ),
                "source_row_number": np.nan,
                "value_column": (
                    "expected_fallback_transfer_value_score"
                ),
            }
        ]
    )

    return pd.concat(
        [
            utah,
            mia,
        ],
        ignore_index=True,
        sort=False,
    ).sort_values(
        "candidate_team"
    ).reset_index(
        drop=True
    )


def apply_corrections(
    policy_rows: pd.DataFrame,
    correction_ledger: pd.DataFrame,
) -> pd.DataFrame:
    corrections = (
        correction_ledger.groupby(
            "candidate_team",
            as_index=False,
        )
        .agg(
            correction_value_score=(
                "correction_value_score",
                "sum",
            ),
            correction_rows=(
                "correction_type",
                "size",
            ),
            correction_types=(
                "correction_type",
                lambda values: "|".join(
                    sorted(
                        set(
                            clean_text(
                                value
                            )
                            for value in values
                        )
                    )
                ),
            ),
        )
    )

    output = policy_rows.merge(
        corrections,
        how="left",
        on="candidate_team",
        validate="one_to_one",
    )

    output[
        "correction_value_score"
    ] = pd.to_numeric(
        output[
            "correction_value_score"
        ],
        errors="coerce",
    ).fillna(
        0.0
    )

    output[
        "correction_rows"
    ] = pd.to_numeric(
        output[
            "correction_rows"
        ],
        errors="coerce",
    ).fillna(
        0
    ).astype(
        int
    )

    output[
        "corrected_inventory_value_score"
    ] = (
        pd.to_numeric(
            output[
                "policy_inventory_value_score"
            ],
            errors="raise",
        )
        + output[
            "correction_value_score"
        ]
    )

    output[
        "corrected_value_difference"
    ] = (
        output[
            "corrected_inventory_value_score"
        ]
        - pd.to_numeric(
            output[
                "canonical_final_team_value_score"
            ],
            errors="raise",
        )
    )

    output[
        "absolute_corrected_value_difference"
    ] = output[
        "corrected_value_difference"
    ].abs()

    output[
        "corrected_team_reconciliation_passed"
    ] = (
        output[
            "absolute_corrected_value_difference"
        ]
        <= VALUE_TOLERANCE
    )

    return output.sort_values(
        [
            "corrected_team_reconciliation_passed",
            "absolute_corrected_value_difference",
            "candidate_team",
        ],
        ascending=[
            True,
            False,
            True,
        ],
    ).reset_index(
        drop=True
    )


def recover_cle_min_uta_sources(
    rejected_inventory: pd.DataFrame,
) -> pd.DataFrame:
    rows = rejected_inventory.loc[
        rejected_inventory[
            "component_right_file"
        ]
        .fillna("")
        .astype(str)
        .eq(
            CLE_MIN_UTA_COMPONENT_FILE
        )
    ].copy()

    output_rows = []

    for row in rows.itertuples(
        index=False
    ):
        row_dict = row._asdict()

        raw_json = clean_text(
            row_dict.get(
                "component_raw_row_json",
                "",
            )
        )

        try:
            raw = (
                json.loads(
                    raw_json
                )
                if raw_json
                else {}
            )
        except json.JSONDecodeError:
            raw = {}

        description = clean_text(
            raw.get(
                "right_description",
                "",
            )
        )

        year_match = re.search(
            r"\b20(?:27|28|29)\b",
            description,
        )

        round_number = (
            1
            if re.search(
                r"\b(?:firsts?|1st(?:-round)?(?:\s+picks?)?)\b",
                description,
                flags=re.IGNORECASE,
            )
            else (
                2
                if re.search(
                    r"\b(?:seconds?|2nd(?:-round)?(?:\s+picks?)?)\b",
                    description,
                    flags=re.IGNORECASE,
                )
                else None
            )
        )

        teams = sorted(
            set(
                re.findall(
                    r"\b(?:CLE|MIN|UTA)\b",
                    description.upper(),
                )
            )
        )

        source_assets = (
            [
                f"{year_match.group(0)}_R{round_number}_{team}"
                for team in teams
            ]
            if (
                year_match
                and round_number is not None
                and teams
            )
            else []
        )

        declared_source_count = finite_or_nan(
            raw.get(
                "source_asset_count",
                np.nan,
            )
        )

        output_rows.append(
            {
                "candidate_team": clean_text(
                    row_dict.get(
                        "candidate_team",
                        "",
                    )
                ).upper(),
                "candidate_right_value_score": finite_or_nan(
                    row_dict.get(
                        "candidate_right_value_score",
                        np.nan,
                    )
                ),
                "expected_pick_count": finite_or_nan(
                    row_dict.get(
                        "expected_pick_count",
                        np.nan,
                    )
                ),
                "right_description": description,
                "recovered_draft_year": (
                    int(
                        year_match.group(
                            0
                        )
                    )
                    if year_match
                    else np.nan
                ),
                "recovered_round_number": round_number,
                "recovered_source_assets": "|".join(
                    source_assets
                ),
                "recovered_source_asset_count": len(
                    source_assets
                ),
                "declared_source_asset_count": (
                    declared_source_count
                ),
                "source_count_reconciliation_passed": bool(
                    source_assets
                    and (
                        not np.isfinite(
                            declared_source_count
                        )
                        or len(
                            source_assets
                        )
                        == int(
                            declared_source_count
                        )
                    )
                ),
            }
        )

    return pd.DataFrame(
        output_rows
    ).sort_values(
        "candidate_team"
    ).reset_index(
        drop=True
    )


def build_validation(
    corrected: pd.DataFrame,
    correction_ledger: pd.DataFrame,
    utah_candidates: pd.DataFrame,
    utah_selected: pd.DataFrame,
    cle_recovery: pd.DataFrame,
) -> pd.DataFrame:
    system_difference = float(
        corrected[
            "corrected_value_difference"
        ].sum()
    )

    maximum_difference = float(
        corrected[
            "absolute_corrected_value_difference"
        ].max()
    )

    selected_matches = int(
        utah_selected[
            "exact_required_correction_match"
        ].sum()
    )

    checks = [
        {
            "check_name": "corrected_team_row_count",
            "observed_value": int(
                len(
                    corrected
                )
            ),
            "expected_value": EXPECTED_TEAM_ROWS,
            "passed": len(
                corrected
            )
            == EXPECTED_TEAM_ROWS,
        },
        {
            "check_name": "all_corrected_teams_reconciled",
            "observed_value": int(
                corrected[
                    "corrected_team_reconciliation_passed"
                ].sum()
            ),
            "expected_value": EXPECTED_TEAM_ROWS,
            "passed": bool(
                corrected[
                    "corrected_team_reconciliation_passed"
                ].all()
            ),
        },
        {
            "check_name": "corrected_system_value_difference",
            "observed_value": system_difference,
            "expected_value": 0.0,
            "passed": abs(
                system_difference
            )
            <= VALUE_TOLERANCE,
        },
        {
            "check_name": "maximum_corrected_team_difference",
            "observed_value": maximum_difference,
            "expected_value": 0.0,
            "passed": maximum_difference
            <= VALUE_TOLERANCE,
        },
        {
            "check_name": "correction_team_count",
            "observed_value": int(
                correction_ledger[
                    "candidate_team"
                ].nunique()
            ),
            "expected_value": 5,
            "passed": correction_ledger[
                "candidate_team"
            ].nunique()
            == 5,
        },
        {
            "check_name": "utah_pool_candidate_values_found",
            "observed_value": int(
                len(
                    utah_candidates
                )
            ),
            "expected_value": ">0",
            "passed": len(
                utah_candidates
            )
            > 0,
        },
        {
            "check_name": "utah_pool_selected_team_count",
            "observed_value": int(
                utah_selected[
                    "candidate_team"
                ].nunique()
            ),
            "expected_value": 4,
            "passed": utah_selected[
                "candidate_team"
            ].nunique()
            == 4,
        },
        {
            "check_name": "utah_pool_selected_values_match_gaps",
            "observed_value": selected_matches,
            "expected_value": 4,
            "passed": bool(
                len(
                    utah_selected
                )
                == 4
                and utah_selected[
                    "exact_required_correction_match"
                ].all()
            ),
        },
        {
            "check_name": "cle_min_uta_candidate_rows",
            "observed_value": int(
                len(
                    cle_recovery
                )
            ),
            "expected_value": 3,
            "passed": len(
                cle_recovery
            )
            == 3,
        },
        {
            "check_name": "cle_min_uta_all_sources_recovered",
            "observed_value": int(
                cle_recovery[
                    "source_count_reconciliation_passed"
                ].sum()
            ),
            "expected_value": 3,
            "passed": bool(
                len(
                    cle_recovery
                )
                == 3
                and cle_recovery[
                    "source_count_reconciliation_passed"
                ].all()
            ),
        },
        {
            "check_name": "cle_min_uta_round_is_first",
            "observed_value": "|".join(
                sorted(
                    set(
                        pd.to_numeric(
                            cle_recovery[
                                "recovered_round_number"
                            ],
                            errors="coerce",
                        )
                        .dropna()
                        .astype(int)
                        .astype(str)
                    )
                )
            ),
            "expected_value": "1",
            "passed": bool(
                pd.to_numeric(
                    cle_recovery[
                        "recovered_round_number"
                    ],
                    errors="coerce",
                )
                .eq(
                    1
                )
                .all()
            ),
        },
    ]

    return pd.DataFrame(
        checks
    )


def main() -> None:
    OUTPUT_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    print("=" * 80)
    print("FUTURE PICK OPTIMIZER FINAL CORRECTION VALIDATION")
    print("=" * 80)
    print(f"Script version: {SCRIPT_VERSION}")
    print()

    (
        policy_teams,
        valuations,
        rights,
        adjustments,
        rejected_inventory,
        rights_path,
        adjustments_path,
    ) = load_inputs()

    policy_rows = best_policy_team_rows(
        policy_teams
    )

    (
        utah_candidates,
        utah_selected,
    ) = select_utah_corrections(
        policy_rows=policy_rows,
        rights=rights,
        adjustments=adjustments,
        rights_path=rights_path,
        adjustments_path=adjustments_path,
    )

    (
        mia_audit,
        mia_fallback_value,
    ) = build_mia_correction(
        valuations
    )

    correction_ledger = build_correction_ledger(
        utah_selected=utah_selected,
        mia_fallback_value=mia_fallback_value,
    )

    corrected = apply_corrections(
        policy_rows=policy_rows,
        correction_ledger=correction_ledger,
    )

    cle_recovery = recover_cle_min_uta_sources(
        rejected_inventory
    )

    validation = build_validation(
        corrected=corrected,
        correction_ledger=correction_ledger,
        utah_candidates=utah_candidates,
        utah_selected=utah_selected,
        cle_recovery=cle_recovery,
    )

    utah_candidates.to_csv(
        UTAH_CORRECTION_CANDIDATES_PATH,
        index=False,
    )

    utah_selected.to_csv(
        UTAH_SELECTED_CORRECTIONS_PATH,
        index=False,
    )

    mia_audit.to_csv(
        MIA_ROLLOVER_AUDIT_PATH,
        index=False,
    )

    correction_ledger.to_csv(
        CORRECTION_LEDGER_PATH,
        index=False,
    )

    corrected.to_csv(
        CORRECTED_TEAM_RECONCILIATION_PATH,
        index=False,
    )

    cle_recovery.to_csv(
        CLE_MIN_UTA_RECOVERY_PATH,
        index=False,
    )

    validation.to_csv(
        VALIDATION_PATH,
        index=False,
    )

    failed = validation.loc[
        ~validation[
            "passed"
        ]
    ]

    metadata = {
        "script_version": SCRIPT_VERSION,
        "created_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "best_policy": BEST_POLICY,
        "resolved_utah_pool_rights_path": str(
            rights_path
        ),
        "resolved_utah_pool_adjustments_path": str(
            adjustments_path
        ),
        "utah_pool_candidate_values": int(
            len(
                utah_candidates
            )
        ),
        "utah_pool_selected_corrections": int(
            len(
                utah_selected
            )
        ),
        "utah_pool_correction_total": float(
            utah_selected[
                "correction_value_score"
            ].sum()
        ),
        "mia_fallback_value_removed": float(
            mia_fallback_value
        ),
        "net_correction_total": float(
            correction_ledger[
                "correction_value_score"
            ].sum()
        ),
        "teams_reconciled": int(
            corrected[
                "corrected_team_reconciliation_passed"
            ].sum()
        ),
        "team_count": int(
            len(
                corrected
            )
        ),
        "corrected_system_difference": float(
            corrected[
                "corrected_value_difference"
            ].sum()
        ),
        "maximum_corrected_team_difference": float(
            corrected[
                "absolute_corrected_value_difference"
            ].max()
        ),
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
        "validation_passed": bool(
            failed.empty
        ),
        "outputs": {
            "correction_ledger": str(
                CORRECTION_LEDGER_PATH
            ),
            "corrected_team_reconciliation": str(
                CORRECTED_TEAM_RECONCILIATION_PATH
            ),
            "utah_correction_candidates": str(
                UTAH_CORRECTION_CANDIDATES_PATH
            ),
            "utah_selected_corrections": str(
                UTAH_SELECTED_CORRECTIONS_PATH
            ),
            "mia_rollover_audit": str(
                MIA_ROLLOVER_AUDIT_PATH
            ),
            "cle_min_uta_recovery": str(
                CLE_MIN_UTA_RECOVERY_PATH
            ),
            "validation": str(
                VALIDATION_PATH
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
    print("FINAL CORRECTION VALIDATION CREATED")
    print("=" * 80)
    print(
        "Resolved Utah-pool rights file: "
        f"{rights_path}"
    )
    print(
        "Resolved Utah-pool adjustments file: "
        f"{adjustments_path}"
    )
    print(
        "Utah-pool candidate values examined: "
        f"{len(utah_candidates):,}"
    )
    print(
        "Utah-pool correction teams: "
        f"{utah_selected['candidate_team'].nunique():,}"
    )
    print(
        "Utah-pool correction total: "
        f"{utah_selected['correction_value_score'].sum():.6f}"
    )
    print(
        "Miami fallback value removed: "
        f"{mia_fallback_value:.6f}"
    )
    print(
        "Net correction total: "
        f"{correction_ledger['correction_value_score'].sum():.6f}"
    )
    print(
        "Teams reconciled after corrections: "
        f"{int(corrected['corrected_team_reconciliation_passed'].sum()):,}"
        f"/{len(corrected):,}"
    )
    print(
        "Corrected system difference: "
        f"{corrected['corrected_value_difference'].sum():.10f}"
    )
    print(
        "Maximum corrected team difference: "
        f"{corrected['absolute_corrected_value_difference'].max():.10f}"
    )
    print(
        "CLE-MIN-UTA source recoveries passed: "
        f"{int(cle_recovery['source_count_reconciliation_passed'].sum()):,}"
        f"/{len(cle_recovery):,}"
    )
    print(
        "Validation checks passed: "
        f"{int(validation['passed'].sum()):,}"
        f"/{len(validation):,}"
    )
    print(
        "Final correction model valid: "
        f"{bool(failed.empty)}"
    )
    print()

    print("SELECTED UTAH-POOL CORRECTIONS")
    display_utah = utah_selected.copy()

    for column in [
        "required_correction",
        "candidate_correction_value_score",
        "candidate_minus_required",
    ]:
        display_utah[
            column
        ] = pd.to_numeric(
            display_utah[
                column
            ],
            errors="coerce",
        ).round(
            6
        )

    print(
        display_utah[
            [
                "candidate_team",
                "required_correction",
                "source_kind",
                "source_file",
                "value_column",
                "candidate_correction_value_score",
                "candidate_minus_required",
                "selection_priority",
            ]
        ].to_string(
            index=False
        )
    )
    print()

    print("CORRECTION LEDGER")
    display_ledger = correction_ledger.copy()

    display_ledger[
        "correction_value_score"
    ] = pd.to_numeric(
        display_ledger[
            "correction_value_score"
        ],
        errors="coerce",
    ).round(
        6
    )

    print(
        display_ledger[
            [
                "candidate_team",
                "correction_value_score",
                "correction_type",
                "source_reference",
                "value_column",
            ]
        ].to_string(
            index=False
        )
    )
    print()

    print("CORRECTED TEAM RECONCILIATION")
    corrected_display = corrected.loc[
        corrected[
            "correction_value_score"
        ].abs()
        > VALUE_TOLERANCE
    ].copy()

    for column in [
        "canonical_final_team_value_score",
        "policy_inventory_value_score",
        "correction_value_score",
        "corrected_inventory_value_score",
        "corrected_value_difference",
    ]:
        corrected_display[
            column
        ] = pd.to_numeric(
            corrected_display[
                column
            ],
            errors="coerce",
        ).round(
            6
        )

    print(
        corrected_display[
            [
                "candidate_team",
                "canonical_final_team_value_score",
                "policy_inventory_value_score",
                "correction_value_score",
                "corrected_inventory_value_score",
                "corrected_value_difference",
                "corrected_team_reconciliation_passed",
            ]
        ].to_string(
            index=False
        )
    )
    print()

    print("CLE-MIN-UTA 2027 FIRST-ROUND SOURCE RECOVERY")
    print(
        cle_recovery.to_string(
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
        CORRECTION_LEDGER_PATH,
        CORRECTED_TEAM_RECONCILIATION_PATH,
        UTAH_CORRECTION_CANDIDATES_PATH,
        UTAH_SELECTED_CORRECTIONS_PATH,
        MIA_ROLLOVER_AUDIT_PATH,
        CLE_MIN_UTA_RECOVERY_PATH,
        VALIDATION_PATH,
        METADATA_PATH,
    ]:
        print(
            path
        )

    if not failed.empty:
        raise RuntimeError(
            "The final correction model failed validation:\n"
            + failed.to_string(
                index=False
            )
        )


if __name__ == "__main__":
    main()