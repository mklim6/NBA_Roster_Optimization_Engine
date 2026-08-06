from __future__ import annotations

import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


SCRIPT_VERSION = "future-pick-dependency-candidate-refinement-v2-import-fix-2026-08-04"

PROJECT_ROOT = Path(__file__).resolve().parents[1]

CLAIM_NODES_PATH = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "future_pick_dependency_claim_nodes_2027_2029_v1.parquet"
)

GROUPS_PATH = (
    PROJECT_ROOT
    / "outputs"
    / "future_pick_dependency_groups_2027_2029_v1.csv"
)

PROCESSED_DIRECTORY = (
    PROJECT_ROOT
    / "data"
    / "processed"
)

OUTPUT_DIRECTORY = PROJECT_ROOT / "outputs"

REFINED_GROUPS_PARQUET_PATH = (
    PROCESSED_DIRECTORY
    / "future_pick_dependency_groups_refined_2027_2029_v2.parquet"
)

REFINED_GROUPS_CSV_PATH = (
    PROCESSED_DIRECTORY
    / "future_pick_dependency_groups_refined_2027_2029_v2.csv"
)

SAFE_FAVORABILITY_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_safe_favorability_candidates_2027_2029_v2.csv"
)

SAFE_SWAP_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_safe_swap_chain_candidates_2027_2029_v2.csv"
)

SAFE_ROLLOVER_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_safe_rollover_candidates_2027_2029_v2.csv"
)

SUSPICIOUS_GROUPS_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_dependency_suspicious_groups_2027_2029_v2.csv"
)

CLAIM_TEXT_REVIEW_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_dependency_claim_text_review_2027_2029_v2.csv"
)

MANUAL_QUEUE_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_dependency_manual_queue_2027_2029_v2.csv"
)

METADATA_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_dependency_candidate_refinement_metadata_v2.json"
)


MODELED_DRAFT_YEARS = {
    2027,
    2028,
    2029,
}

VALID_FAVORABILITY_TYPES = {
    "most_favorable",
    "least_favorable",
    "second_most_favorable",
    "second_least_favorable",
    "third_most_favorable",
    "third_least_favorable",
    "more_favorable",
    "less_favorable",
}

LIST_COLUMNS = [
    "mentioned_teams_list",
    "mentioned_years_list",
    "mentioned_rounds_list",
    "beneficiary_teams_list",
    "raw_calendar_years_list",
    "ignored_calendar_years_list",
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


def parse_json_list(
    value: Any,
) -> list[Any]:
    if isinstance(
        value,
        list,
    ):
        return value

    if value is None or (
        isinstance(
            value,
            float,
        )
        and np.isnan(
            value
        )
    ):
        return []

    text = str(
        value
    ).strip()

    if not text:
        return []

    try:
        parsed = json.loads(
            text
        )

        if isinstance(
            parsed,
            list,
        ):
            return parsed
    except json.JSONDecodeError:
        pass

    return [
        item
        for item in text.split(
            "|"
        )
        if item
    ]


def boolean_series(
    frame: pd.DataFrame,
    column: str,
) -> pd.Series:
    values = frame[
        column
    ]

    if pd.api.types.is_bool_dtype(
        values
    ):
        return values.fillna(
            False
        ).astype(
            bool
        )

    return (
        values.fillna(
            False
        )
        .astype(
            str
        )
        .str.strip()
        .str.lower()
        .isin(
            {
                "true",
                "1",
                "yes",
                "y",
            }
        )
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
]:
    for path in [
        CLAIM_NODES_PATH,
        GROUPS_PATH,
    ]:
        if not path.exists():
            raise FileNotFoundError(
                "Required dependency output was not found:\n"
                f"{path}"
            )

    nodes = normalize_columns(
        pd.read_parquet(
            CLAIM_NODES_PATH
        )
    )

    groups = normalize_columns(
        pd.read_csv(
            GROUPS_PATH
        )
    )

    require_columns(
        nodes,
        [
            "claim_id",
            "asset_key",
            "obligation_group_id",
            "draft_year",
            "round_number",
            "originating_team",
            "structural_family",
            "favorability_type",
            "rollover_language_detected",
            "rollover_or_fallback_language_flag",
            "swap_flag",
            "favorability_pool_flag",
            "protection_flag",
            "conditional_language_flag",
            "multiple_claim_rows_flag",
            "valuation_status",
            "pick_heading",
            "transaction_text",
            "full_claim_text",
            *LIST_COLUMNS,
        ],
        "Dependency claim nodes",
    )

    require_columns(
        groups,
        [
            "obligation_group_id",
            "candidate_resolution_tier",
            "claim_count",
            "unique_asset_count",
            "mentioned_team_count",
            "mentioned_year_count",
            "beneficiary_team_count",
            "has_swap",
            "has_favorability_pool",
            "has_protection",
            "has_rollover_or_fallback",
            "out_of_horizon_dependency",
        ],
        "Dependency groups",
    )

    for column in LIST_COLUMNS:
        nodes[
            column
        ] = nodes[
            column
        ].map(
            parse_json_list
        )

    for column in [
        "rollover_language_detected",
        "rollover_or_fallback_language_flag",
        "swap_flag",
        "favorability_pool_flag",
        "protection_flag",
        "conditional_language_flag",
        "multiple_claim_rows_flag",
    ]:
        nodes[
            column
        ] = boolean_series(
            nodes,
            column,
        )

    for column in [
        "has_swap",
        "has_favorability_pool",
        "has_protection",
        "has_rollover_or_fallback",
        "out_of_horizon_dependency",
    ]:
        groups[
            column
        ] = boolean_series(
            groups,
            column,
        )

    return (
        nodes,
        groups,
    )


def unique_flattened(
    series: pd.Series,
) -> list[Any]:
    values = set()

    for items in series:
        values.update(
            items
        )

    return sorted(
        values
    )


def evaluate_group(
    group_id: str,
    group_nodes: pd.DataFrame,
    original_group: pd.Series,
) -> dict[str, Any]:
    years = unique_flattened(
        group_nodes[
            "mentioned_years_list"
        ]
    )

    rounds = unique_flattened(
        group_nodes[
            "mentioned_rounds_list"
        ]
    )

    teams = unique_flattened(
        group_nodes[
            "mentioned_teams_list"
        ]
    )

    beneficiaries = unique_flattened(
        group_nodes[
            "beneficiary_teams_list"
        ]
    )

    families = sorted(
        set(
            group_nodes[
                "structural_family"
            ].astype(
                str
            )
        )
    )

    favorability_types = sorted(
        set(
            value
            for value in group_nodes[
                "favorability_type"
            ].astype(
                str
            )
            if value
            and value
            != "none"
        )
    )

    claim_count = len(
        group_nodes
    )

    unique_assets = int(
        group_nodes[
            "asset_key"
        ].nunique()
    )

    has_swap = bool(
        group_nodes[
            "swap_flag"
        ].any()
    )

    has_favorability = bool(
        group_nodes[
            "favorability_pool_flag"
        ].any()
    )

    has_protection = bool(
        group_nodes[
            "protection_flag"
        ].any()
    )

    has_rollover = bool(
        group_nodes[
            "rollover_language_detected"
        ].any()
        or group_nodes[
            "rollover_or_fallback_language_flag"
        ].any()
    )

    has_multiple_claim_asset = bool(
        group_nodes[
            "multiple_claim_rows_flag"
        ].any()
    )

    out_of_horizon = any(
        int(
            year
        )
        not in MODELED_DRAFT_YEARS
        for year in years
    )

    reasons = []

    safe_tier = "manual_dependency_review"

    if out_of_horizon:
        reasons.append(
            "true_out_of_horizon_dependency"
        )

    if has_multiple_claim_asset:
        reasons.append(
            "multiple_claims_on_same_asset"
        )

    if (
        has_rollover
        and len(
            years
        )
        < 2
    ):
        reasons.append(
            "rollover_language_without_second_pick_year"
        )

    if (
        has_rollover
        and (
            has_swap
            or has_favorability
        )
    ):
        reasons.append(
            "rollover_mixed_with_swap_or_favorability"
        )

    if (
        has_favorability
        and len(
            teams
        )
        > 5
    ):
        reasons.append(
            "favorability_pool_has_more_than_five_teams"
        )

    if (
        has_favorability
        and len(
            favorability_types
        )
        != 1
    ):
        reasons.append(
            "favorability_order_not_unique"
        )

    if (
        has_swap
        and len(
            beneficiaries
        )
        != 1
    ):
        reasons.append(
            "swap_beneficiary_not_unique"
        )

    if len(
        rounds
    ) != 1:
        reasons.append(
            "multiple_rounds_referenced"
        )

    if len(
        teams
    ) > 8:
        reasons.append(
            "claim_text_mentions_many_teams"
        )

    safe_favorability = (
        not out_of_horizon
        and not has_multiple_claim_asset
        and has_favorability
        and not has_swap
        and not has_protection
        and not has_rollover
        and len(
            years
        )
        == 1
        and len(
            rounds
        )
        == 1
        and 2
        <= len(
            teams
        )
        <= 5
        and len(
            beneficiaries
        )
        == 1
        and len(
            favorability_types
        )
        == 1
        and favorability_types[
            0
        ]
        in VALID_FAVORABILITY_TYPES
        and set(
            families
        )
        == {
            "favorability_pool"
        }
    )

    safe_swap = (
        not out_of_horizon
        and not has_multiple_claim_asset
        and has_swap
        and not has_favorability
        and not has_protection
        and not has_rollover
        and len(
            years
        )
        == 1
        and len(
            rounds
        )
        == 1
        and 2
        <= len(
            teams
        )
        <= 4
        and len(
            beneficiaries
        )
        == 1
        and claim_count
        <= 2
        and set(
            families
        )
        == {
            "swap_chain"
        }
    )

    safe_rollover = (
        not out_of_horizon
        and not has_multiple_claim_asset
        and has_rollover
        and not has_swap
        and not has_favorability
        and len(
            years
        )
        >= 2
        and len(
            rounds
        )
        == 1
        and len(
            beneficiaries
        )
        == 1
        and unique_assets
        == 1
        and claim_count
        == 1
        and (
            has_protection
            or bool(
                group_nodes[
                    "conditional_language_flag"
                ].any()
            )
        )
    )

    if safe_favorability:
        safe_tier = (
            "safe_same_year_favorability_candidate"
        )
    elif safe_swap:
        safe_tier = (
            "safe_same_year_swap_chain_candidate"
        )
    elif safe_rollover:
        safe_tier = (
            "safe_linked_rollover_candidate"
        )

    suspicious = bool(
        reasons
    )

    return {
        "obligation_group_id": (
            group_id
        ),
        "original_candidate_resolution_tier": (
            str(
                original_group[
                    "candidate_resolution_tier"
                ]
            )
        ),
        "refined_candidate_resolution_tier": (
            safe_tier
        ),
        "claim_count_recomputed": (
            claim_count
        ),
        "unique_asset_count_recomputed": (
            unique_assets
        ),
        "mentioned_teams_refined": "|".join(
            teams
        ),
        "mentioned_team_count_refined": len(
            teams
        ),
        "mentioned_years_refined": "|".join(
            str(
                value
            )
            for value in years
        ),
        "mentioned_year_count_refined": len(
            years
        ),
        "mentioned_rounds_refined": "|".join(
            str(
                value
            )
            for value in rounds
        ),
        "beneficiary_teams_refined": "|".join(
            beneficiaries
        ),
        "beneficiary_team_count_refined": len(
            beneficiaries
        ),
        "structural_families_refined": "|".join(
            families
        ),
        "favorability_types_refined": "|".join(
            favorability_types
        ),
        "has_swap_refined": (
            has_swap
        ),
        "has_favorability_refined": (
            has_favorability
        ),
        "has_protection_refined": (
            has_protection
        ),
        "has_rollover_refined": (
            has_rollover
        ),
        "has_multiple_claim_asset_refined": (
            has_multiple_claim_asset
        ),
        "out_of_horizon_refined": (
            out_of_horizon
        ),
        "suspicious_group_flag": (
            suspicious
        ),
        "suspicion_reasons": "|".join(
            reasons
        ),
        "source_verification_required": (
            True
        ),
        "refinement_scope_note": (
            "Conservative structural screening only. A group enters "
            "automatic valuation only when its teams, years, rounds, "
            "beneficiary, and claim type form an unambiguous pattern."
        ),
    }


def build_claim_text_review(
    nodes: pd.DataFrame,
    refined: pd.DataFrame,
) -> pd.DataFrame:
    columns = [
        "obligation_group_id",
        "claim_id",
        "asset_key",
        "draft_year",
        "round_number",
        "originating_team",
        "valuation_status",
        "structural_family",
        "favorability_type",
        "mentioned_teams",
        "mentioned_years",
        "mentioned_rounds",
        "beneficiary_teams",
        "pick_heading",
        "transaction_text",
        "full_claim_text",
    ]

    available = [
        column
        for column in columns
        if column in nodes.columns
    ]

    review = nodes[
        available
    ].copy()

    review = review.merge(
        refined[
            [
                "obligation_group_id",
                "original_candidate_resolution_tier",
                "refined_candidate_resolution_tier",
                "suspicious_group_flag",
                "suspicion_reasons",
            ]
        ],
        how="left",
        on="obligation_group_id",
        validate="many_to_one",
    )

    return review.sort_values(
        [
            "refined_candidate_resolution_tier",
            "obligation_group_id",
            "claim_id",
        ]
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
    print("FUTURE NBA PICK DEPENDENCY CANDIDATE REFINEMENT")
    print("=" * 80)
    print(
        f"Script version: {SCRIPT_VERSION}"
    )
    print()

    nodes, original_groups = load_inputs()

    original_lookup = (
        original_groups.set_index(
            "obligation_group_id"
        )
    )

    refined_rows = []

    for group_id, group_nodes in nodes.groupby(
        "obligation_group_id",
        sort=True,
    ):
        if group_id not in original_lookup.index:
            raise ValueError(
                "Dependency node group was not found in group summary: "
                f"{group_id}"
            )

        original_group = (
            original_lookup.loc[
                group_id
            ]
        )

        refined_rows.append(
            evaluate_group(
                group_id=group_id,
                group_nodes=group_nodes,
                original_group=original_group,
            )
        )

    refined = pd.DataFrame(
        refined_rows
    ).sort_values(
        [
            "refined_candidate_resolution_tier",
            "obligation_group_id",
        ]
    ).reset_index(
        drop=True
    )

    safe_favorability = refined.loc[
        refined[
            "refined_candidate_resolution_tier"
        ].eq(
            "safe_same_year_favorability_candidate"
        )
    ].copy()

    safe_swap = refined.loc[
        refined[
            "refined_candidate_resolution_tier"
        ].eq(
            "safe_same_year_swap_chain_candidate"
        )
    ].copy()

    safe_rollover = refined.loc[
        refined[
            "refined_candidate_resolution_tier"
        ].eq(
            "safe_linked_rollover_candidate"
        )
    ].copy()

    suspicious = refined.loc[
        refined[
            "suspicious_group_flag"
        ]
    ].copy()

    manual_queue = refined.loc[
        refined[
            "refined_candidate_resolution_tier"
        ].eq(
            "manual_dependency_review"
        )
    ].copy()

    claim_text_review = (
        build_claim_text_review(
            nodes=nodes,
            refined=refined,
        )
    )

    refined.to_parquet(
        REFINED_GROUPS_PARQUET_PATH,
        index=False,
    )

    refined.to_csv(
        REFINED_GROUPS_CSV_PATH,
        index=False,
    )

    safe_favorability.to_csv(
        SAFE_FAVORABILITY_PATH,
        index=False,
    )

    safe_swap.to_csv(
        SAFE_SWAP_PATH,
        index=False,
    )

    safe_rollover.to_csv(
        SAFE_ROLLOVER_PATH,
        index=False,
    )

    suspicious.to_csv(
        SUSPICIOUS_GROUPS_PATH,
        index=False,
    )

    claim_text_review.to_csv(
        CLAIM_TEXT_REVIEW_PATH,
        index=False,
    )

    manual_queue.to_csv(
        MANUAL_QUEUE_PATH,
        index=False,
    )

    tier_counts = (
        refined[
            "refined_candidate_resolution_tier"
        ]
        .value_counts()
        .to_dict()
    )

    reason_counts = defaultdict(
        int
    )

    for reason_text in refined[
        "suspicion_reasons"
    ].astype(
        str
    ):
        for reason in reason_text.split(
            "|"
        ):
            if reason:
                reason_counts[
                    reason
                ] += 1

    metadata = {
        "script_version": (
            SCRIPT_VERSION
        ),
        "created_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "claim_nodes_loaded": len(
            nodes
        ),
        "dependency_groups_loaded": len(
            original_groups
        ),
        "refined_groups_created": len(
            refined
        ),
        "safe_favorability_candidates": len(
            safe_favorability
        ),
        "safe_swap_chain_candidates": len(
            safe_swap
        ),
        "safe_rollover_candidates": len(
            safe_rollover
        ),
        "suspicious_groups": len(
            suspicious
        ),
        "manual_queue_groups": len(
            manual_queue
        ),
        "refined_tier_counts": (
            tier_counts
        ),
        "suspicion_reason_counts": dict(
            sorted(
                reason_counts.items()
            )
        ),
        "automatic_candidate_rules": [
            (
                "Favorable-pick pools require one year, one round, "
                "one beneficiary, two to five mentioned teams, one "
                "favorability order, and no protection or rollover."
            ),
            (
                "Swap chains require one year, one round, one "
                "beneficiary, two to four teams, no protection, and "
                "no rollover or favorability pool."
            ),
            (
                "Rollover candidates require at least two modeled "
                "draft years, one round, one beneficiary, one claim, "
                "one originating asset, and no swap or favorability pool."
            ),
        ],
        "limitations": [
            (
                "This script refines structural eligibility but does "
                "not assign asset value."
            ),
            (
                "All candidate groups still require source verification "
                "before entering trade recommendations."
            ),
            (
                "A manual queue is expected and preferable to assigning "
                "false precision to ambiguous transaction language."
            ),
        ],
        "output_files": {
            "refined_groups": str(
                REFINED_GROUPS_PARQUET_PATH
            ),
            "safe_favorability_candidates": str(
                SAFE_FAVORABILITY_PATH
            ),
            "safe_swap_candidates": str(
                SAFE_SWAP_PATH
            ),
            "safe_rollover_candidates": str(
                SAFE_ROLLOVER_PATH
            ),
            "suspicious_groups": str(
                SUSPICIOUS_GROUPS_PATH
            ),
            "claim_text_review": str(
                CLAIM_TEXT_REVIEW_PATH
            ),
            "manual_queue": str(
                MANUAL_QUEUE_PATH
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
    print("DEPENDENCY CANDIDATES REFINED")
    print("=" * 80)
    print(
        f"Claim nodes loaded: "
        f"{len(nodes):,}"
    )
    print(
        f"Dependency groups loaded: "
        f"{len(original_groups):,}"
    )
    print(
        "Safe favorability candidates: "
        f"{len(safe_favorability):,}"
    )
    print(
        "Safe swap-chain candidates: "
        f"{len(safe_swap):,}"
    )
    print(
        "Safe rollover candidates: "
        f"{len(safe_rollover):,}"
    )
    print(
        f"Suspicious groups: "
        f"{len(suspicious):,}"
    )
    print(
        f"Manual queue groups: "
        f"{len(manual_queue):,}"
    )
    print()

    print("REFINED GROUP CLASSIFICATIONS")
    tier_display = (
        refined[
            "refined_candidate_resolution_tier"
        ]
        .value_counts()
        .rename_axis(
            "refined_candidate_resolution_tier"
        )
        .reset_index(
            name="groups"
        )
    )

    print(
        tier_display.to_string(
            index=False
        )
    )
    print()

    print("SUSPICION REASONS")
    if reason_counts:
        reason_display = pd.DataFrame(
            [
                {
                    "reason": reason,
                    "groups": count,
                }
                for reason, count
                in sorted(
                    reason_counts.items(),
                    key=lambda item: (
                        -item[
                            1
                        ],
                        item[
                            0
                        ],
                    ),
                )
            ]
        )

        print(
            reason_display.to_string(
                index=False
            )
        )
    else:
        print(
            "No suspicious structural combinations were found."
        )

    print()
    print("SAFE AUTOMATIC CANDIDATES")
    safe_display = refined.loc[
        ~refined[
            "refined_candidate_resolution_tier"
        ].eq(
            "manual_dependency_review"
        )
    ].copy()

    if safe_display.empty:
        print(
            "No groups met the strict automatic-candidate rules."
        )
    else:
        print(
            safe_display[
                [
                    "obligation_group_id",
                    "refined_candidate_resolution_tier",
                    "claim_count_recomputed",
                    "unique_asset_count_recomputed",
                    "mentioned_teams_refined",
                    "mentioned_years_refined",
                    "mentioned_rounds_refined",
                    "beneficiary_teams_refined",
                    "favorability_types_refined",
                ]
            ].to_string(
                index=False
            )
        )

    print()
    print("SAVED FILES")
    print(REFINED_GROUPS_PARQUET_PATH)
    print(REFINED_GROUPS_CSV_PATH)
    print(SAFE_FAVORABILITY_PATH)
    print(SAFE_SWAP_PATH)
    print(SAFE_ROLLOVER_PATH)
    print(SUSPICIOUS_GROUPS_PATH)
    print(CLAIM_TEXT_REVIEW_PATH)
    print(MANUAL_QUEUE_PATH)
    print(METADATA_PATH)


if __name__ == "__main__":
    main()