from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


SCRIPT_VERSION = (
    "future-pick-dallas-conditional-split-integration-v1-2026-08-04"
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]

ROLLOVER_VALUES_PATH = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "future_pick_linked_rollover_values_2027_2029_v1_v3_bank.parquet"
)

V4_VALUATIONS_PATH = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "future_pick_claim_value_layer_2027_2029_v4_rollover_enriched.parquet"
)

V4_TEAM_SUMMARY_PATH = (
    PROJECT_ROOT
    / "outputs"
    / "future_pick_candidate_team_value_summary_v4_rollover_adjusted_provisional.csv"
)

ROLLOVER_ADJUSTMENTS_PATH = (
    PROJECT_ROOT
    / "outputs"
    / "future_pick_rollover_team_adjustment_candidates_v1.csv"
)

DIAGNOSTIC_PATH = (
    PROJECT_ROOT
    / "outputs"
    / "future_pick_dallas_fallback_2028_mia_second_diagnostic_v1.csv"
)

TEXT_MATCHES_PATH = (
    PROJECT_ROOT
    / "outputs"
    / "future_pick_dallas_fallback_2028_mia_second_text_matches_v1.csv"
)

PROCESSED_DIRECTORY = (
    PROJECT_ROOT
    / "data"
    / "processed"
)

OUTPUT_DIRECTORY = PROJECT_ROOT / "outputs"

BRANCH_LEDGER_PARQUET_PATH = (
    PROCESSED_DIRECTORY
    / "future_pick_conditional_branch_ledger_2027_2029_v1.parquet"
)

BRANCH_LEDGER_CSV_PATH = (
    PROCESSED_DIRECTORY
    / "future_pick_conditional_branch_ledger_2027_2029_v1.csv"
)

V5_VALUATIONS_PARQUET_PATH = (
    PROCESSED_DIRECTORY
    / "future_pick_claim_value_layer_2027_2029_v5_conditional_split_enriched.parquet"
)

V5_VALUATIONS_CSV_PATH = (
    PROCESSED_DIRECTORY
    / "future_pick_claim_value_layer_2027_2029_v5_conditional_split_enriched.csv"
)

V5_TEAM_SUMMARY_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_candidate_team_value_summary_v5_conditional_split_provisional.csv"
)

UNALLOCATED_CHAIN_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_unallocated_conditional_chain_values_v1.csv"
)

CHAIN_REVIEW_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_detroit_utah_2028_mia_second_chain_review_v1.csv"
)

RECONCILIATION_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_dallas_conditional_split_reconciliation_v1.csv"
)

METADATA_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_dallas_conditional_split_metadata_v1.json"
)


TARGET_ROLLOVER_CLAIM_ID = "2027_R1_DAL_C1"
TARGET_FALLBACK_CLAIM_ID = "2028_R2_MIA_C1"
TARGET_FALLBACK_ASSET_KEY = "2028_R2_MIA"

CHARLOTTE_TEAM = "CHA"

DOWNSTREAM_CHAIN_TEAMS = [
    "DET",
    "UTA",
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


def clean_text(
    value: Any,
) -> str:
    if value is None:
        return ""

    if isinstance(
        value,
        float,
    ) and np.isnan(
        value
    ):
        return ""

    return " ".join(
        str(
            value
        ).split()
    )


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


def load_inputs() -> tuple[
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
]:
    required_paths = [
        ROLLOVER_VALUES_PATH,
        V4_VALUATIONS_PATH,
        V4_TEAM_SUMMARY_PATH,
        ROLLOVER_ADJUSTMENTS_PATH,
        DIAGNOSTIC_PATH,
        TEXT_MATCHES_PATH,
    ]

    for path in required_paths:
        if not path.exists():
            raise FileNotFoundError(
                "Required conditional-split input was not found:\n"
                f"{path}"
            )

    rollover_values = normalize_columns(
        pd.read_parquet(
            ROLLOVER_VALUES_PATH
        )
    )

    valuations = normalize_columns(
        pd.read_parquet(
            V4_VALUATIONS_PATH
        )
    )

    team_summary = normalize_columns(
        pd.read_csv(
            V4_TEAM_SUMMARY_PATH
        )
    )

    rollover_adjustments = normalize_columns(
        pd.read_csv(
            ROLLOVER_ADJUSTMENTS_PATH
        )
    )

    diagnostic = normalize_columns(
        pd.read_csv(
            DIAGNOSTIC_PATH
        )
    )

    text_matches = normalize_columns(
        pd.read_csv(
            TEXT_MATCHES_PATH
        )
    )

    require_columns(
        rollover_values,
        [
            "claim_id",
            "candidate_beneficiary_team",
            "current_conveyance_probability",
            "current_protection_probability",
            "fallback_asset_key",
            "expected_fallback_transfer_value_score",
            "fallback_unconditional_asset_value_score",
            "expected_fallback_value_retained_by_existing_holder",
            "expected_total_rollover_obligation_value_score",
            "joint_simulation_count",
        ],
        "Linked rollover values",
    )

    require_columns(
        valuations,
        [
            "claim_id",
            "valuation_method",
            "valuation_status",
            "expected_total_candidate_asset_value_score",
        ],
        "V4 valuation layer",
    )

    require_columns(
        team_summary,
        [
            "candidate_beneficiary_team",
            (
                "candidate_total_pick_asset_value_score_"
                "after_rollovers_provisional"
            ),
        ],
        "V4 provisional team summary",
    )

    require_columns(
        rollover_adjustments,
        [
            "claim_id",
            "team",
            "rollover_adjustment_value_score",
            "adjustment_type",
            "automatic_adjustment_ready",
        ],
        "Rollover adjustment candidates",
    )

    require_columns(
        diagnostic,
        [
            "claim_id",
            "asset_key",
            "claim_type",
            "resolution_status",
            "diagnostic_ownership_state",
        ],
        "Dallas fallback diagnostic",
    )

    return (
        rollover_values,
        valuations,
        team_summary,
        rollover_adjustments,
        diagnostic,
        text_matches,
    )


def select_target_rollover(
    rollover_values: pd.DataFrame,
) -> pd.Series:
    match = rollover_values.loc[
        rollover_values[
            "claim_id"
        ].astype(
            str
        ).eq(
            TARGET_ROLLOVER_CLAIM_ID
        )
    ]

    if len(
        match
    ) != 1:
        raise ValueError(
            "Expected exactly one Dallas rollover value row. "
            f"Found {len(match)}."
        )

    row = match.iloc[
        0
    ]

    if clean_text(
        row[
            "fallback_asset_key"
        ]
    ) != TARGET_FALLBACK_ASSET_KEY:
        raise ValueError(
            "Dallas rollover fallback asset does not match the expected "
            f"asset {TARGET_FALLBACK_ASSET_KEY}."
        )

    if clean_text(
        row[
            "candidate_beneficiary_team"
        ]
    ) != CHARLOTTE_TEAM:
        raise ValueError(
            "Dallas rollover beneficiary is not Charlotte."
        )

    return row


def validate_diagnostic(
    diagnostic: pd.DataFrame,
) -> pd.Series:
    match = diagnostic.loc[
        diagnostic[
            "claim_id"
        ].astype(
            str
        ).eq(
            TARGET_FALLBACK_CLAIM_ID
        )
        & diagnostic[
            "asset_key"
        ].astype(
            str
        ).eq(
            TARGET_FALLBACK_ASSET_KEY
        )
    ]

    if len(
        match
    ) != 1:
        raise ValueError(
            "Expected one exact diagnostic row for the fallback asset. "
            f"Found {len(match)}."
        )

    row = match.iloc[
        0
    ]

    if clean_text(
        row[
            "claim_type"
        ]
    ) != "conditional_transfer":
        raise ValueError(
            "The fallback asset is not labeled as a conditional transfer."
        )

    return row


def build_branch_ledger(
    rollover_row: pd.Series,
    diagnostic_row: pd.Series,
) -> pd.DataFrame:
    charlotte_value = numeric_value(
        rollover_row[
            "expected_fallback_transfer_value_score"
        ]
    )

    downstream_value = numeric_value(
        rollover_row[
            "expected_fallback_value_retained_by_existing_holder"
        ]
    )

    unconditional_value = numeric_value(
        rollover_row[
            "fallback_unconditional_asset_value_score"
        ]
    )

    charlotte_probability = numeric_value(
        rollover_row[
            "current_protection_probability"
        ]
    )

    downstream_probability = numeric_value(
        rollover_row[
            "current_conveyance_probability"
        ]
    )

    branch_sum = (
        charlotte_value
        + downstream_value
    )

    if abs(
        branch_sum
        - unconditional_value
    ) > 1e-8:
        raise RuntimeError(
            "Conditional branch values do not reconcile to the "
            "unconditional fallback asset value."
        )

    probability_sum = (
        charlotte_probability
        + downstream_probability
    )

    if abs(
        probability_sum
        - 1.0
    ) > 1e-12:
        raise RuntimeError(
            "Conditional branch probabilities do not sum to one."
        )

    common = {
        "source_rollover_claim_id": (
            TARGET_ROLLOVER_CLAIM_ID
        ),
        "fallback_claim_id": (
            TARGET_FALLBACK_CLAIM_ID
        ),
        "fallback_asset_key": (
            TARGET_FALLBACK_ASSET_KEY
        ),
        "fallback_unconditional_asset_value_score": (
            unconditional_value
        ),
        "joint_simulation_count": int(
            numeric_value(
                rollover_row[
                    "joint_simulation_count"
                ]
            )
        ),
        "source_claim_type": (
            diagnostic_row[
                "claim_type"
            ]
        ),
        "source_resolution_status": (
            diagnostic_row[
                "resolution_status"
            ]
        ),
    }

    rows = [
        {
            **common,
            "conditional_branch_id": (
                "2028_R2_MIA_TO_CHA_IF_DAL_2027_R1_PROTECTED"
            ),
            "branch_trigger": (
                "Dallas 2027 first does not convey to Charlotte "
                "because it lands in protected selections 1-2"
            ),
            "branch_probability": (
                charlotte_probability
            ),
            "branch_candidate_team": (
                CHARLOTTE_TEAM
            ),
            "branch_candidate_team_group": (
                CHARLOTTE_TEAM
            ),
            "branch_expected_value_score": (
                charlotte_value
            ),
            "branch_allocation_status": (
                "resolved_candidate_allocation"
            ),
            "branch_team_summary_action": (
                "add_to_charlotte"
            ),
            "branch_scope_note": (
                "Detroit's conditional claim is extinguished and "
                "Charlotte receives Miami's 2028 second-round pick."
            ),
        },
        {
            **common,
            "conditional_branch_id": (
                "2028_R2_MIA_TO_DET_UTA_CHAIN_IF_DAL_2027_R1_CONVEYS"
            ),
            "branch_trigger": (
                "Dallas 2027 first conveys to Charlotte"
            ),
            "branch_probability": (
                downstream_probability
            ),
            "branch_candidate_team": "",
            "branch_candidate_team_group": (
                "|".join(
                    DOWNSTREAM_CHAIN_TEAMS
                )
            ),
            "branch_expected_value_score": (
                downstream_value
            ),
            "branch_allocation_status": (
                "unresolved_downstream_conveyance_chain"
            ),
            "branch_team_summary_action": (
                "hold_unallocated_until_detroit_utah_chain_resolved"
            ),
            "branch_scope_note": (
                "Miami's 2028 second goes to the Detroit side of the "
                "obligation, but the source states Detroit may convey "
                "the pick to Utah."
            ),
        },
    ]

    return pd.DataFrame(
        rows
    )


def validate_existing_adjustments(
    adjustments: pd.DataFrame,
) -> None:
    existing = adjustments.loc[
        adjustments[
            "claim_id"
        ].astype(
            str
        ).eq(
            TARGET_ROLLOVER_CLAIM_ID
        )
    ]

    if len(
        existing
    ) != 1:
        raise ValueError(
            "Expected exactly one prior Dallas rollover adjustment row."
        )

    row = existing.iloc[
        0
    ]

    automatic_ready = (
        str(
            row[
                "automatic_adjustment_ready"
            ]
        )
        .strip()
        .lower()
        in {
            "true",
            "1",
            "yes",
        }
    )

    if automatic_ready:
        raise RuntimeError(
            "The Dallas fallback was already automatically added. "
            "Running this integration would double-count it."
        )

    if clean_text(
        row[
            "adjustment_type"
        ]
    ) != "manual_integration_hold":
        raise RuntimeError(
            "The previous Dallas adjustment is not the expected "
            "manual-integration hold."
        )


def update_team_summary(
    team_summary: pd.DataFrame,
    branch_ledger: pd.DataFrame,
) -> pd.DataFrame:
    output = team_summary.copy()

    charlotte_branch = branch_ledger.loc[
        branch_ledger[
            "branch_candidate_team"
        ].eq(
            CHARLOTTE_TEAM
        )
        & branch_ledger[
            "branch_allocation_status"
        ].eq(
            "resolved_candidate_allocation"
        )
    ]

    if len(
        charlotte_branch
    ) != 1:
        raise ValueError(
            "Expected exactly one resolved Charlotte branch."
        )

    charlotte_value = float(
        charlotte_branch.iloc[
            0
        ][
            "branch_expected_value_score"
        ]
    )

    team_column = (
        "candidate_beneficiary_team"
    )

    total_column = (
        "candidate_total_pick_asset_value_score_"
        "after_rollovers_provisional"
    )

    mask = output[
        team_column
    ].astype(
        str
    ).eq(
        CHARLOTTE_TEAM
    )

    if int(
        mask.sum()
    ) != 1:
        raise ValueError(
            "Expected exactly one Charlotte row in the V4 team summary."
        )

    output[
        "candidate_total_pick_asset_value_score_before_conditional_split"
    ] = pd.to_numeric(
        output[
            total_column
        ],
        errors="coerce",
    )

    output[
        "resolved_conditional_split_adjustment_value_score"
    ] = 0.0

    output.loc[
        mask,
        "resolved_conditional_split_adjustment_value_score",
    ] = charlotte_value

    output[
        "candidate_total_pick_asset_value_score_after_conditional_split_provisional"
    ] = (
        output[
            "candidate_total_pick_asset_value_score_before_conditional_split"
        ]
        + output[
            "resolved_conditional_split_adjustment_value_score"
        ]
    )

    unresolved_value = float(
        branch_ledger.loc[
            branch_ledger[
                "branch_allocation_status"
            ].eq(
                "unresolved_downstream_conveyance_chain"
            ),
            "branch_expected_value_score",
        ].sum()
    )

    output[
        "leaguewide_unallocated_conditional_chain_value_score"
    ] = (
        unresolved_value
    )

    output[
        "conditional_split_team_summary_status"
    ] = (
        "provisional_with_unallocated_detroit_utah_chain"
    )

    output[
        "conditional_split_scope_note"
    ] = (
        "Charlotte's certain branch of Miami's 2028 second-round "
        "conditional asset is included. The complementary Detroit-or-"
        "Utah branch remains outside team totals pending downstream "
        "chain resolution."
    )

    return output.sort_values(
        (
            "candidate_total_pick_asset_value_score_"
            "after_conditional_split_provisional"
        ),
        ascending=False,
    ).reset_index(
        drop=True
    )


def enrich_valuation_layer(
    valuations: pd.DataFrame,
    branch_ledger: pd.DataFrame,
) -> pd.DataFrame:
    output = valuations.copy()

    target_mask = output[
        "claim_id"
    ].astype(
        str
    ).eq(
        TARGET_FALLBACK_CLAIM_ID
    )

    if int(
        target_mask.sum()
    ) != 1:
        raise ValueError(
            "Expected exactly one fallback claim valuation row."
        )

    charlotte_value = float(
        branch_ledger.loc[
            branch_ledger[
                "branch_candidate_team"
            ].eq(
                CHARLOTTE_TEAM
            ),
            "branch_expected_value_score",
        ].sum()
    )

    unresolved_value = float(
        branch_ledger.loc[
            branch_ledger[
                "branch_allocation_status"
            ].eq(
                "unresolved_downstream_conveyance_chain"
            ),
            "branch_expected_value_score",
        ].sum()
    )

    unconditional_value = float(
        branch_ledger[
            "fallback_unconditional_asset_value_score"
        ].iloc[
            0
        ]
    )

    added_columns = {
        "conditional_split_value_modeled_flag": False,
        "conditional_split_resolved_branch_value_score": 0.0,
        "conditional_split_unresolved_branch_value_score": 0.0,
        "conditional_split_unconditional_asset_value_score": np.nan,
        "conditional_split_resolved_candidate_team": "",
        "conditional_split_unresolved_team_group": "",
        "conditional_split_allocation_status": "",
    }

    for column, default in added_columns.items():
        if column not in output.columns:
            output[
                column
            ] = default

    output.loc[
        target_mask,
        "valuation_method",
    ] = (
        "joint_conditional_split_asset"
    )

    output.loc[
        target_mask,
        "valuation_status",
    ] = (
        "valued_conditional_split_partial_allocation"
    )

    output.loc[
        target_mask,
        "conditional_split_value_modeled_flag",
    ] = True

    output.loc[
        target_mask,
        "conditional_split_resolved_branch_value_score",
    ] = charlotte_value

    output.loc[
        target_mask,
        "conditional_split_unresolved_branch_value_score",
    ] = unresolved_value

    output.loc[
        target_mask,
        "conditional_split_unconditional_asset_value_score",
    ] = unconditional_value

    output.loc[
        target_mask,
        "conditional_split_resolved_candidate_team",
    ] = CHARLOTTE_TEAM

    output.loc[
        target_mask,
        "conditional_split_unresolved_team_group",
    ] = (
        "|".join(
            DOWNSTREAM_CHAIN_TEAMS
        )
    )

    output.loc[
        target_mask,
        "conditional_split_allocation_status",
    ] = (
        "charlotte_branch_resolved_detroit_utah_branch_unresolved"
    )

    if (
        "automatic_exclusion_reason"
        in output.columns
    ):
        output.loc[
            target_mask,
            "automatic_exclusion_reason",
        ] = (
            "downstream_detroit_utah_chain_unresolved"
        )

    if (
        "valuation_scope_note"
        in output.columns
    ):
        output.loc[
            target_mask,
            "valuation_scope_note",
        ] = (
            "The unconditional asset value is fully modeled as two "
            "mutually exclusive branches. Charlotte's branch is assigned; "
            "the Detroit-or-Utah branch is held outside team totals."
        )

    # Keep the generic candidate-total field blank because the asset is
    # split among branches and has no single candidate owner.
    output.loc[
        target_mask,
        "expected_total_candidate_asset_value_score",
    ] = np.nan

    return output


def build_chain_review(
    text_matches: pd.DataFrame,
    branch_ledger: pd.DataFrame,
) -> pd.DataFrame:
    output = text_matches.copy()

    output[
        "chain_review_target_asset_key"
    ] = (
        TARGET_FALLBACK_ASSET_KEY
    )

    output[
        "chain_review_candidate_teams"
    ] = (
        "|".join(
            DOWNSTREAM_CHAIN_TEAMS
        )
    )

    output[
        "downstream_branch_expected_value_score"
    ] = float(
        branch_ledger.loc[
            branch_ledger[
                "branch_allocation_status"
            ].eq(
                "unresolved_downstream_conveyance_chain"
            ),
            "branch_expected_value_score",
        ].sum()
    )

    output[
        "chain_review_status"
    ] = (
        "resolve_detroit_to_utah_onward_conveyance_before_team_assignment"
    )

    return output


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
    print("DALLAS CONDITIONAL SECOND-ROUND SPLIT INTEGRATION")
    print("=" * 80)
    print(
        f"Script version: {SCRIPT_VERSION}"
    )
    print()

    (
        rollover_values,
        valuations,
        team_summary,
        rollover_adjustments,
        diagnostic,
        text_matches,
    ) = load_inputs()

    rollover_row = select_target_rollover(
        rollover_values
    )

    diagnostic_row = validate_diagnostic(
        diagnostic
    )

    validate_existing_adjustments(
        rollover_adjustments
    )

    branch_ledger = build_branch_ledger(
        rollover_row=rollover_row,
        diagnostic_row=diagnostic_row,
    )

    updated_team_summary = update_team_summary(
        team_summary=team_summary,
        branch_ledger=branch_ledger,
    )

    enriched_valuations = enrich_valuation_layer(
        valuations=valuations,
        branch_ledger=branch_ledger,
    )

    chain_review = build_chain_review(
        text_matches=text_matches,
        branch_ledger=branch_ledger,
    )

    unresolved = branch_ledger.loc[
        branch_ledger[
            "branch_allocation_status"
        ].eq(
            "unresolved_downstream_conveyance_chain"
        )
    ].copy()

    unconditional_value = float(
        branch_ledger[
            "fallback_unconditional_asset_value_score"
        ].iloc[
            0
        ]
    )

    allocated_value = float(
        branch_ledger.loc[
            branch_ledger[
                "branch_allocation_status"
            ].eq(
                "resolved_candidate_allocation"
            ),
            "branch_expected_value_score",
        ].sum()
    )

    unallocated_value = float(
        unresolved[
            "branch_expected_value_score"
        ].sum()
    )

    branch_probability_sum = float(
        branch_ledger[
            "branch_probability"
        ].sum()
    )

    branch_value_sum = float(
        branch_ledger[
            "branch_expected_value_score"
        ].sum()
    )

    reconciliation = pd.DataFrame(
        [
            {
                "fallback_asset_key": (
                    TARGET_FALLBACK_ASSET_KEY
                ),
                "unconditional_asset_value_score": (
                    unconditional_value
                ),
                "resolved_candidate_branch_value_score": (
                    allocated_value
                ),
                "unallocated_chain_branch_value_score": (
                    unallocated_value
                ),
                "branch_value_sum": (
                    branch_value_sum
                ),
                "branch_value_difference": (
                    branch_value_sum
                    - unconditional_value
                ),
                "branch_probability_sum": (
                    branch_probability_sum
                ),
                "branch_probability_difference_from_one": (
                    branch_probability_sum
                    - 1.0
                ),
                "value_reconciliation_passed": (
                    abs(
                        branch_value_sum
                        - unconditional_value
                    )
                    <= 1e-8
                ),
                "probability_reconciliation_passed": (
                    abs(
                        branch_probability_sum
                        - 1.0
                    )
                    <= 1e-12
                ),
            }
        ]
    )

    if not bool(
        reconciliation[
            "value_reconciliation_passed"
        ].all()
        and reconciliation[
            "probability_reconciliation_passed"
        ].all()
    ):
        raise RuntimeError(
            "Conditional branch reconciliation failed."
        )

    branch_ledger.to_parquet(
        BRANCH_LEDGER_PARQUET_PATH,
        index=False,
    )

    branch_ledger.to_csv(
        BRANCH_LEDGER_CSV_PATH,
        index=False,
    )

    enriched_valuations.to_parquet(
        V5_VALUATIONS_PARQUET_PATH,
        index=False,
    )

    enriched_valuations.to_csv(
        V5_VALUATIONS_CSV_PATH,
        index=False,
    )

    updated_team_summary.to_csv(
        V5_TEAM_SUMMARY_PATH,
        index=False,
    )

    unresolved.to_csv(
        UNALLOCATED_CHAIN_PATH,
        index=False,
    )

    chain_review.to_csv(
        CHAIN_REVIEW_PATH,
        index=False,
    )

    reconciliation.to_csv(
        RECONCILIATION_PATH,
        index=False,
    )

    charlotte_before = numeric_value(
        team_summary.loc[
            team_summary[
                "candidate_beneficiary_team"
            ].astype(
                str
            ).eq(
                CHARLOTTE_TEAM
            ),
            (
                "candidate_total_pick_asset_value_score_"
                "after_rollovers_provisional"
            ),
        ].iloc[
            0
        ]
    )

    charlotte_after = numeric_value(
        updated_team_summary.loc[
            updated_team_summary[
                "candidate_beneficiary_team"
            ].astype(
                str
            ).eq(
                CHARLOTTE_TEAM
            ),
            (
                "candidate_total_pick_asset_value_score_"
                "after_conditional_split_provisional"
            ),
        ].iloc[
            0
        ]
    )

    metadata = {
        "script_version": (
            SCRIPT_VERSION
        ),
        "created_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "target_rollover_claim_id": (
            TARGET_ROLLOVER_CLAIM_ID
        ),
        "target_fallback_claim_id": (
            TARGET_FALLBACK_CLAIM_ID
        ),
        "target_fallback_asset_key": (
            TARGET_FALLBACK_ASSET_KEY
        ),
        "conditional_branches_created": len(
            branch_ledger
        ),
        "resolved_candidate_branches": int(
            branch_ledger[
                "branch_allocation_status"
            ].eq(
                "resolved_candidate_allocation"
            ).sum()
        ),
        "unresolved_chain_branches": len(
            unresolved
        ),
        "unconditional_fallback_asset_value_score": (
            unconditional_value
        ),
        "charlotte_branch_value_score": (
            allocated_value
        ),
        "detroit_utah_unallocated_branch_value_score": (
            unallocated_value
        ),
        "charlotte_team_value_before_split": (
            charlotte_before
        ),
        "charlotte_team_value_after_split": (
            charlotte_after
        ),
        "all_reconciliation_checks_passed": bool(
            reconciliation[
                "value_reconciliation_passed"
            ].all()
            and reconciliation[
                "probability_reconciliation_passed"
            ].all()
        ),
        "accounting_policy": [
            (
                "The unconditional Miami 2028 second-round value is "
                "partitioned across mutually exclusive Dallas-conveyance "
                "branches."
            ),
            (
                "Charlotte's branch is added because its ownership is "
                "explicit when Dallas's 2027 first is protected."
            ),
            (
                "The complementary value remains unallocated because "
                "Detroit may convey the pick to Utah."
            ),
            (
                "The generic single-owner candidate value remains blank "
                "for the split fallback claim to prevent double-counting."
            ),
        ],
        "output_files": {
            "conditional_branch_ledger": str(
                BRANCH_LEDGER_PARQUET_PATH
            ),
            "v5_enriched_valuation_layer": str(
                V5_VALUATIONS_PARQUET_PATH
            ),
            "v5_provisional_team_summary": str(
                V5_TEAM_SUMMARY_PATH
            ),
            "unallocated_chain_values": str(
                UNALLOCATED_CHAIN_PATH
            ),
            "detroit_utah_chain_review": str(
                CHAIN_REVIEW_PATH
            ),
            "reconciliation": str(
                RECONCILIATION_PATH
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
    print("CONDITIONAL SPLIT INTEGRATED")
    print("=" * 80)
    print(
        f"Fallback asset: "
        f"{TARGET_FALLBACK_ASSET_KEY}"
    )
    print(
        f"Conditional branches created: "
        f"{len(branch_ledger):,}"
    )
    print(
        "Resolved Charlotte branch value: "
        f"{allocated_value:.4f}"
    )
    print(
        "Unallocated Detroit-or-Utah branch value: "
        f"{unallocated_value:.4f}"
    )
    print(
        "Unconditional fallback asset value: "
        f"{unconditional_value:.4f}"
    )
    print(
        "Charlotte provisional value before split: "
        f"{charlotte_before:.4f}"
    )
    print(
        "Charlotte provisional value after split: "
        f"{charlotte_after:.4f}"
    )
    print(
        "All reconciliation checks passed: "
        f"{bool(metadata['all_reconciliation_checks_passed'])}"
    )
    print()

    print("CONDITIONAL BRANCH LEDGER")
    display = branch_ledger[
        [
            "conditional_branch_id",
            "branch_probability",
            "branch_candidate_team",
            "branch_candidate_team_group",
            "branch_expected_value_score",
            "branch_allocation_status",
        ]
    ].copy()

    display[
        "branch_probability"
    ] = (
        pd.to_numeric(
            display[
                "branch_probability"
            ],
            errors="coerce",
        )
        * 100.0
    ).round(
        2
    )

    display[
        "branch_expected_value_score"
    ] = pd.to_numeric(
        display[
            "branch_expected_value_score"
        ],
        errors="coerce",
    ).round(
        4
    )

    print(
        display.to_string(
            index=False
        )
    )
    print()

    print("SAVED FILES")
    print(BRANCH_LEDGER_PARQUET_PATH)
    print(BRANCH_LEDGER_CSV_PATH)
    print(V5_VALUATIONS_PARQUET_PATH)
    print(V5_VALUATIONS_CSV_PATH)
    print(V5_TEAM_SUMMARY_PATH)
    print(UNALLOCATED_CHAIN_PATH)
    print(CHAIN_REVIEW_PATH)
    print(RECONCILIATION_PATH)
    print(METADATA_PATH)


if __name__ == "__main__":
    main()