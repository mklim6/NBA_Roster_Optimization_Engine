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
    "future-pick-dallas-fallback-ownership-diagnostic-v1-2026-08-04"
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]

CLAIMS_PATH = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "future_pick_obligation_claims_2027_2029_v3_floor_corrected.parquet"
)

VALUATIONS_PATH = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "future_pick_claim_value_layer_2027_2029_v3_floor_corrected.parquet"
)

ROLLOVER_VALUES_PATH = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "future_pick_linked_rollover_values_2027_2029_v1_v3_bank.parquet"
)

OUTPUT_DIRECTORY = PROJECT_ROOT / "outputs"

DIAGNOSTIC_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_dallas_fallback_2028_mia_second_diagnostic_v1.csv"
)

TEXT_MATCH_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_dallas_fallback_2028_mia_second_text_matches_v1.csv"
)

METADATA_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_dallas_fallback_ownership_diagnostic_metadata_v1.json"
)


TARGET_ROLLOVER_CLAIM_ID = "2027_R1_DAL_C1"
TARGET_FALLBACK_ASSET_KEY = "2028_R2_MIA"

TEXT_COLUMNS = [
    "pick_heading",
    "transaction_text",
    "full_obligation_text",
]

DISPLAY_COLUMNS = [
    "claim_id",
    "asset_key",
    "draft_year",
    "round_number",
    "originating_team",
    "claim_type",
    "resolution_status",
    "candidate_current_owner",
    "destination_team_sequence",
    "destination_team_count",
    "single_destination_team",
    "single_destination_parse_success",
    "destination_parse_success",
    "swap_flag",
    "favorability_pool_flag",
    "conditional_language_flag",
    "protection_flag",
    "rollover_or_fallback_language_flag",
    "multiple_claim_rows_flag",
    "valuation_method",
    "valuation_status",
    "candidate_beneficiary_team",
    "candidate_retaining_team",
    "expected_transferred_value_score",
    "expected_retained_value_score",
    "expected_total_candidate_asset_value_score",
    "automatic_exclusion_reason",
    "pick_heading",
    "transaction_text",
    "full_obligation_text",
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

    return re.sub(
        r"\s+",
        " ",
        str(
            value
        ),
    ).strip()


def boolean_value(
    value: Any,
) -> bool:
    if isinstance(
        value,
        bool,
    ):
        return value

    return (
        str(
            value
        )
        .strip()
        .lower()
        in {
            "true",
            "1",
            "yes",
            "y",
        }
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
]:
    for path in [
        CLAIMS_PATH,
        VALUATIONS_PATH,
        ROLLOVER_VALUES_PATH,
    ]:
        if not path.exists():
            raise FileNotFoundError(
                "Required diagnostic input was not found:\n"
                f"{path}"
            )

    claims = normalize_columns(
        pd.read_parquet(
            CLAIMS_PATH
        )
    )

    valuations = normalize_columns(
        pd.read_parquet(
            VALUATIONS_PATH
        )
    )

    rollovers = normalize_columns(
        pd.read_parquet(
            ROLLOVER_VALUES_PATH
        )
    )

    require_columns(
        claims,
        [
            "claim_id",
            "asset_key",
            "draft_year",
            "round_number",
            "originating_team",
            "claim_type",
            "resolution_status",
        ],
        "V3 obligation claims",
    )

    require_columns(
        valuations,
        [
            "claim_id",
            "valuation_method",
            "valuation_status",
            "candidate_beneficiary_team",
            "expected_total_candidate_asset_value_score",
        ],
        "V3 claim valuations",
    )

    require_columns(
        rollovers,
        [
            "claim_id",
            "fallback_asset_key",
            "expected_fallback_transfer_value_score",
            "fallback_overlap_status",
        ],
        "Linked rollover values",
    )

    return (
        claims,
        valuations,
        rollovers,
    )


def build_text_blob(
    frame: pd.DataFrame,
) -> pd.Series:
    available = [
        column
        for column in TEXT_COLUMNS
        if column in frame.columns
    ]

    if not available:
        return pd.Series(
            "",
            index=frame.index,
            dtype=str,
        )

    output = pd.Series(
        "",
        index=frame.index,
        dtype=str,
    )

    for column in available:
        output = (
            output
            + " "
            + frame[
                column
            ].fillna(
                ""
            ).astype(
                str
            )
        )

    return output.map(
        clean_text
    )


def merge_claims_and_values(
    claims: pd.DataFrame,
    valuations: pd.DataFrame,
) -> pd.DataFrame:
    valuation_columns = [
        column
        for column in [
            "claim_id",
            "valuation_method",
            "valuation_status",
            "candidate_beneficiary_team",
            "candidate_retaining_team",
            "candidate_counterparty_team",
            "expected_transferred_value_score",
            "expected_retained_value_score",
            "expected_swap_option_value_score",
            "expected_total_candidate_asset_value_score",
            "automatic_exclusion_reason",
            "valuation_scope_note",
        ]
        if column in valuations.columns
    ]

    valuation_subset = valuations[
        valuation_columns
    ].drop_duplicates(
        subset=[
            "claim_id"
        ]
    )

    return claims.merge(
        valuation_subset,
        how="left",
        on="claim_id",
        validate="one_to_one",
    )


def classify_ownership_state(
    target: pd.DataFrame,
) -> tuple[
    str,
    str,
    bool,
]:
    if target.empty:
        return (
            "target_asset_missing_from_ledger",
            (
                "The fallback asset does not have a claim row. "
                "Its conditional value can be added to Charlotte, "
                "but the missing ledger row should be repaired."
            ),
            False,
        )

    direct = target.loc[
        target[
            "valuation_status"
        ].fillna(
            ""
        ).astype(
            str
        ).eq(
            "valued_direct_candidate"
        )
    ]

    if len(
        direct
    ) == 1:
        owner = clean_text(
            direct.iloc[
                0
            ].get(
                "candidate_beneficiary_team",
                "",
            )
        )

        return (
            "single_direct_owner_found",
            (
                "A direct owner exists and the linked-rollover "
                "adjustment can be balanced automatically."
            ),
            bool(
                owner
            ),
        )

    if len(
        direct
    ) > 1:
        return (
            "multiple_direct_owners_found",
            (
                "Multiple direct claims would double-count the fallback. "
                "Manual ownership resolution is required."
            ),
            False,
        )

    claim_types = sorted(
        set(
            target[
                "claim_type"
            ].fillna(
                ""
            ).astype(
                str
            )
        )
    )

    resolution_statuses = sorted(
        set(
            target[
                "resolution_status"
            ].fillna(
                ""
            ).astype(
                str
            )
        )
    )

    destination_teams = []

    for column in [
        "single_destination_team",
        "candidate_current_owner",
        "destination_team_sequence",
    ]:
        if column not in target.columns:
            continue

        for value in target[
            column
        ]:
            text = clean_text(
                value
            )

            if text:
                destination_teams.append(
                    text
                )

    destination_teams = sorted(
        set(
            destination_teams
        )
    )

    own_retained_only = all(
        value
        in {
            "own_retained",
            "own retained",
        }
        for value in claim_types
        if value
    ) and bool(
        claim_types
    )

    if (
        own_retained_only
        and not destination_teams
    ):
        return (
            "own_retained_claim_without_direct_valuation",
            (
                "The ledger says Miami retains the fallback asset, "
                "but the valuation layer excluded it from direct assets. "
                "This is likely resolvable by assigning the non-triggered "
                "share to Miami and the triggered share to Charlotte."
            ),
            True,
        )

    return (
        "non_direct_claim_requires_text_review",
        (
            "No direct owner was valued. Review claim type, resolution "
            "status, destination parsing, and transaction language before "
            "changing the team summary."
        ),
        False,
    )


def main() -> None:
    OUTPUT_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    print("=" * 80)
    print("DALLAS ROLLOVER FALLBACK OWNERSHIP DIAGNOSTIC")
    print("=" * 80)
    print(
        f"Script version: {SCRIPT_VERSION}"
    )
    print()

    (
        claims,
        valuations,
        rollovers,
    ) = load_inputs()

    merged = merge_claims_and_values(
        claims,
        valuations,
    )

    merged[
        "_text_blob"
    ] = build_text_blob(
        merged
    )

    target = merged.loc[
        merged[
            "asset_key"
        ].astype(
            str
        ).eq(
            TARGET_FALLBACK_ASSET_KEY
        )
    ].copy()

    text_pattern = re.compile(
        (
            r"(?:Miami(?:'s|’s)?\s+2028\s+"
            r"(?:second|2nd)[\s-]+round)"
            r"|(?:2028_R2_MIA)"
            r"|(?:2028\s+MIA\s+Round\s+2)"
        ),
        re.IGNORECASE,
    )

    text_matches = merged.loc[
        merged[
            "_text_blob"
        ].map(
            lambda text: bool(
                text_pattern.search(
                    text
                )
            )
        )
    ].copy()

    rollover_match = rollovers.loc[
        rollovers[
            "claim_id"
        ].astype(
            str
        ).eq(
            TARGET_ROLLOVER_CLAIM_ID
        )
    ]

    if len(
        rollover_match
    ) != 1:
        raise ValueError(
            "Expected exactly one Dallas rollover value row."
        )

    rollover_row = rollover_match.iloc[
        0
    ]

    (
        ownership_state,
        ownership_note,
        likely_auto_resolvable,
    ) = classify_ownership_state(
        target
    )

    target[
        "diagnostic_target_asset_key"
    ] = TARGET_FALLBACK_ASSET_KEY

    target[
        "dallas_rollover_claim_id"
    ] = TARGET_ROLLOVER_CLAIM_ID

    target[
        "dallas_fallback_transfer_value_score"
    ] = numeric_value(
        rollover_row[
            "expected_fallback_transfer_value_score"
        ]
    )

    target[
        "diagnostic_ownership_state"
    ] = ownership_state

    target[
        "diagnostic_ownership_note"
    ] = ownership_note

    target[
        "likely_auto_resolvable_after_review"
    ] = likely_auto_resolvable

    output_columns = [
        column
        for column in [
            "diagnostic_target_asset_key",
            "dallas_rollover_claim_id",
            "dallas_fallback_transfer_value_score",
            "diagnostic_ownership_state",
            "diagnostic_ownership_note",
            "likely_auto_resolvable_after_review",
            *DISPLAY_COLUMNS,
        ]
        if column in target.columns
    ]

    target_output = target[
        output_columns
    ].copy()

    target_output.to_csv(
        DIAGNOSTIC_PATH,
        index=False,
    )

    text_output_columns = [
        column
        for column in [
            "claim_id",
            "asset_key",
            "claim_type",
            "resolution_status",
            "destination_team_sequence",
            "valuation_method",
            "valuation_status",
            "candidate_beneficiary_team",
            "automatic_exclusion_reason",
            "pick_heading",
            "transaction_text",
            "full_obligation_text",
        ]
        if column in text_matches.columns
    ]

    text_matches[
        text_output_columns
    ].to_csv(
        TEXT_MATCH_PATH,
        index=False,
    )

    metadata = {
        "script_version": (
            SCRIPT_VERSION
        ),
        "created_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "target_fallback_asset_key": (
            TARGET_FALLBACK_ASSET_KEY
        ),
        "target_claim_rows_found": len(
            target
        ),
        "all_text_match_rows_found": len(
            text_matches
        ),
        "dallas_fallback_transfer_value_score": numeric_value(
            rollover_row[
                "expected_fallback_transfer_value_score"
            ]
        ),
        "existing_rollover_overlap_status": clean_text(
            rollover_row[
                "fallback_overlap_status"
            ]
        ),
        "diagnostic_ownership_state": (
            ownership_state
        ),
        "diagnostic_ownership_note": (
            ownership_note
        ),
        "likely_auto_resolvable_after_review": (
            likely_auto_resolvable
        ),
        "output_files": {
            "target_asset_diagnostic": str(
                DIAGNOSTIC_PATH
            ),
            "all_text_matches": str(
                TEXT_MATCH_PATH
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
    print("DALLAS FALLBACK DIAGNOSTIC CREATED")
    print("=" * 80)
    print(
        f"Target fallback asset: "
        f"{TARGET_FALLBACK_ASSET_KEY}"
    )
    print(
        f"Exact asset claim rows found: "
        f"{len(target):,}"
    )
    print(
        f"All transaction-text matches found: "
        f"{len(text_matches):,}"
    )
    print(
        "Conditional fallback value awaiting allocation: "
        f"{numeric_value(rollover_row['expected_fallback_transfer_value_score']):.4f}"
    )
    print(
        f"Diagnostic ownership state: "
        f"{ownership_state}"
    )
    print(
        "Likely automatically resolvable after review: "
        f"{likely_auto_resolvable}"
    )
    print()

    print("TARGET FALLBACK CLAIM ROWS")
    if target_output.empty:
        print(
            "No exact asset claim rows were found."
        )
    else:
        terminal_columns = [
            column
            for column in [
                "claim_id",
                "asset_key",
                "claim_type",
                "resolution_status",
                "candidate_current_owner",
                "destination_team_sequence",
                "destination_team_count",
                "multiple_claim_rows_flag",
                "valuation_method",
                "valuation_status",
                "candidate_beneficiary_team",
                "automatic_exclusion_reason",
            ]
            if column in target_output.columns
        ]

        print(
            target_output[
                terminal_columns
            ].to_string(
                index=False
            )
        )

    print()
    print("TARGET CLAIM TEXT")
    if target.empty:
        print(
            "No target claim text was available."
        )
    else:
        for row in target.itertuples(
            index=False
        ):
            print("-" * 80)
            print(
                f"Claim: {getattr(row, 'claim_id', '')}"
            )

            for column in TEXT_COLUMNS:
                if column in target.columns:
                    value = clean_text(
                        getattr(
                            row,
                            column,
                            "",
                        )
                    )

                    if value:
                        print(
                            f"{column}: {value}"
                        )

    print()
    print("SAVED FILES")
    print(DIAGNOSTIC_PATH)
    print(TEXT_MATCH_PATH)
    print(METADATA_PATH)


if __name__ == "__main__":
    main()