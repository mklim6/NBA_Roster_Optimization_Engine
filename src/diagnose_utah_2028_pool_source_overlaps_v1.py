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
    "future-pick-utah-2028-pool-source-overlap-diagnostic-v1-2026-08-04"
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
    / "future_pick_claim_value_layer_2027_2029_v6_utah_pool_enriched.parquet"
)

DEPENDENCY_NODES_PATH = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "future_pick_dependency_claim_nodes_2027_2029_v1.parquet"
)

POOL_VALUES_PATH = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "future_pick_utah_2028_second_favorability_pool_values_v1.parquet"
)

POOL_SELECTION_PATH = (
    PROJECT_ROOT
    / "outputs"
    / "future_pick_utah_2028_second_pool_selection_breakdown_v1.csv"
)

MIA_RESOLUTION_PATH = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "future_pick_mia_2028_second_conditional_pool_resolution_v1.parquet"
)

OUTPUT_DIRECTORY = PROJECT_ROOT / "outputs"

SOURCE_CLAIMS_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_utah_2028_pool_source_claims_v1.csv"
)

SOURCE_SUMMARY_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_utah_2028_pool_source_asset_summary_v1.csv"
)

OVERLAP_QUEUE_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_utah_2028_pool_overlap_resolution_queue_v1.csv"
)

TEXT_MATCHES_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_utah_2028_pool_related_text_matches_v1.csv"
)

METADATA_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_utah_2028_pool_source_overlap_metadata_v1.json"
)


POOL_SOURCE_ASSETS = {
    "DET": "2028_R2_DET",
    "CHA": "2028_R2_CHA",
    "LAC": "2028_R2_LAC",
    "MIA": "2028_R2_MIA",
    "NYK": "2028_R2_NYK",
}

TEXT_COLUMNS = [
    "pick_heading",
    "transaction_text",
    "full_obligation_text",
    "full_claim_text",
]

DESTINATION_COLUMNS = [
    "candidate_current_owner",
    "single_destination_team",
    "destination_team_sequence",
    "candidate_beneficiary_team",
    "candidate_retaining_team",
    "candidate_counterparty_team",
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


def text_blob(
    frame: pd.DataFrame,
) -> pd.Series:
    output = pd.Series(
        "",
        index=frame.index,
        dtype=str,
    )

    for column in TEXT_COLUMNS:
        if column in frame.columns:
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


def collect_nonempty(
    frame: pd.DataFrame,
    columns: list[str],
) -> str:
    values = set()

    for column in columns:
        if column not in frame.columns:
            continue

        for value in frame[
            column
        ]:
            text = clean_text(
                value
            )

            if not text:
                continue

            for token in re.split(
                r"[|,;/]+",
                text,
            ):
                token = token.strip()

                if token:
                    values.add(
                        token
                    )

    return "|".join(
        sorted(
            values
        )
    )


def load_inputs() -> tuple[
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
]:
    for path in [
        CLAIMS_PATH,
        VALUATIONS_PATH,
        DEPENDENCY_NODES_PATH,
        POOL_VALUES_PATH,
        POOL_SELECTION_PATH,
        MIA_RESOLUTION_PATH,
    ]:
        if not path.exists():
            raise FileNotFoundError(
                "Required Utah-pool overlap input was not found:\n"
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

    dependency_nodes = normalize_columns(
        pd.read_parquet(
            DEPENDENCY_NODES_PATH
        )
    )

    pool_values = normalize_columns(
        pd.read_parquet(
            POOL_VALUES_PATH
        )
    )

    pool_selection = normalize_columns(
        pd.read_csv(
            POOL_SELECTION_PATH
        )
    )

    mia_resolution = normalize_columns(
        pd.read_parquet(
            MIA_RESOLUTION_PATH
        )
    )

    require_columns(
        claims,
        [
            "claim_id",
            "asset_key",
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
        ],
        "V6 valuation layer",
    )

    require_columns(
        dependency_nodes,
        [
            "claim_id",
            "obligation_group_id",
            "structural_family",
        ],
        "Dependency claim nodes",
    )

    require_columns(
        pool_values,
        [
            "pool_claim_id",
            "expected_utah_pool_pick",
            "expected_utah_pool_value_score",
        ],
        "Utah pool values",
    )

    require_columns(
        pool_selection,
        [
            "selected_source_team",
            "selection_probability",
            "expected_pool_value_component_score",
        ],
        "Utah pool selection breakdown",
    )

    require_columns(
        mia_resolution,
        [
            "candidate_team",
            "branch_probability",
            "branch_expected_value_score",
        ],
        "Miami component resolution",
    )

    return (
        claims,
        valuations,
        dependency_nodes,
        pool_values,
        pool_selection,
        mia_resolution,
    )


def merge_context(
    claims: pd.DataFrame,
    valuations: pd.DataFrame,
    dependency_nodes: pd.DataFrame,
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
            "expected_total_candidate_asset_value_score",
            "automatic_exclusion_reason",
            "valuation_scope_note",
            "favorability_pool_value_modeled_flag",
            "expected_favorability_pool_value_score",
            "favorability_pool_team_integration_hold_flag",
        ]
        if column in valuations.columns
    ]

    dependency_columns = [
        column
        for column in [
            "claim_id",
            "obligation_group_id",
            "structural_family",
            "mentioned_teams",
            "mentioned_years",
            "mentioned_rounds",
            "beneficiary_teams",
            "swap_flag",
            "favorability_pool_flag",
            "protection_flag",
            "rollover_or_fallback_language_flag",
        ]
        if column in dependency_nodes.columns
    ]

    output = claims.merge(
        valuations[
            valuation_columns
        ].drop_duplicates(
            subset=[
                "claim_id"
            ]
        ),
        how="left",
        on="claim_id",
        validate="one_to_one",
    )

    output = output.merge(
        dependency_nodes[
            dependency_columns
        ].drop_duplicates(
            subset=[
                "claim_id"
            ]
        ),
        how="left",
        on="claim_id",
        validate="one_to_one",
        suffixes=(
            "",
            "_dependency",
        ),
    )

    output[
        "_text_blob"
    ] = text_blob(
        output
    )

    return output


def source_related_text_mask(
    frame: pd.DataFrame,
) -> pd.Series:
    pattern = re.compile(
        (
            r"Utah will receive the least"
            r"|Detroit may convey this pick to Utah"
            r"|2028 second round draft pick to Utah"
            r"|2028 2nd round pick to Utah"
            r"|2028_R2_(?:DET|CHA|LAC|MIA|NYK)"
            r"|Detroit's 2028 2nd"
            r"|Charlotte's 2028 2nd"
            r"|Clippers' 2028 2nd"
            r"|Miami's 2028 2nd"
            r"|New York's 2028 2nd"
        ),
        re.IGNORECASE,
    )

    return frame[
        "_text_blob"
    ].map(
        lambda value: bool(
            pattern.search(
                value
            )
        )
    )


def classify_source_asset(
    source_team: str,
    source_claims: pd.DataFrame,
    selection_probability: float,
    selection_value: float,
    mia_resolution: pd.DataFrame,
) -> tuple[
    str,
    bool,
    str,
]:
    direct = source_claims.loc[
        source_claims[
            "valuation_status"
        ].fillna(
            ""
        ).astype(
            str
        ).eq(
            "valued_direct_candidate"
        )
    ]

    if source_team == "MIA":
        resolved_teams = set(
            mia_resolution[
                "candidate_team"
            ].astype(
                str
            )
        )

        fully_resolved = (
            resolved_teams
            == {
                "CHA",
                "DET",
                "UTA",
            }
        )

        return (
            "already_resolved_conditional_pool_component",
            fully_resolved,
            (
                "Miami's source asset is already partitioned among "
                "Charlotte, Detroit, and Utah."
            ),
        )

    if source_team in {
        "CHA",
        "LAC",
    }:
        return (
            "charlotte_clippers_composite_requires_joint_reallocation",
            False,
            (
                "Charlotte receives the more favorable pick while Detroit "
                "receives the less favorable pick. Utah can then take the "
                "Detroit-side composite. Both source assets must be modeled "
                "together before team totals are adjusted."
            ),
        )

    if source_team == "DET":
        return (
            "detroit_protected_own_pick_requires_overlap_reallocation",
            False,
            (
                "Detroit's own second is unavailable to Utah at picks "
                "56-60. Audit any existing Detroit ownership or outgoing "
                "claim before transferring selected scenarios to Utah."
            ),
        )

    if source_team == "NYK":
        return (
            "new_york_to_detroit_then_utah_requires_branch_reallocation",
            False,
            (
                "New York's second first transfers to Detroit and is then "
                "eligible for Utah's least-favorable pool. Split its value "
                "between Utah-selected and Detroit-retained scenarios."
            ),
        )

    if len(
        direct
    ) == 1:
        return (
            "single_direct_overlap_requires_reallocation",
            False,
            (
                "A direct candidate owner exists. Utah's selected component "
                "must be removed from that owner's unconditional value."
            ),
        )

    return (
        "source_asset_requires_manual_review",
        False,
        (
            "The current claim layer does not provide a safe automatic "
            "team-level integration rule."
        ),
    )


def build_source_summary(
    merged: pd.DataFrame,
    pool_selection: pd.DataFrame,
    mia_resolution: pd.DataFrame,
) -> pd.DataFrame:
    rows = []

    for source_team, source_asset_key in POOL_SOURCE_ASSETS.items():
        source_claims = merged.loc[
            merged[
                "asset_key"
            ].astype(
                str
            ).eq(
                source_asset_key
            )
        ].copy()

        selection_match = pool_selection.loc[
            pool_selection[
                "selected_source_team"
            ].astype(
                str
            ).eq(
                source_team
            )
        ]

        if len(
            selection_match
        ) != 1:
            raise ValueError(
                "Expected one Utah-pool selection row for source team "
                f"{source_team}; found {len(selection_match)}."
            )

        selection_row = selection_match.iloc[
            0
        ]

        selection_probability = numeric_value(
            selection_row[
                "selection_probability"
            ]
        )

        selection_value = numeric_value(
            selection_row[
                "expected_pool_value_component_score"
            ]
        )

        (
            integration_state,
            automatic_ready,
            integration_note,
        ) = classify_source_asset(
            source_team=source_team,
            source_claims=source_claims,
            selection_probability=selection_probability,
            selection_value=selection_value,
            mia_resolution=mia_resolution,
        )

        direct_claims = source_claims.loc[
            source_claims[
                "valuation_status"
            ].fillna(
                ""
            ).astype(
                str
            ).eq(
                "valued_direct_candidate"
            )
        ]

        rows.append(
            {
                "source_team": (
                    source_team
                ),
                "source_asset_key": (
                    source_asset_key
                ),
                "exact_claim_rows": len(
                    source_claims
                ),
                "direct_candidate_claim_rows": len(
                    direct_claims
                ),
                "claim_ids": collect_nonempty(
                    source_claims,
                    [
                        "claim_id",
                    ],
                ),
                "claim_types": collect_nonempty(
                    source_claims,
                    [
                        "claim_type",
                    ],
                ),
                "resolution_statuses": collect_nonempty(
                    source_claims,
                    [
                        "resolution_status",
                    ],
                ),
                "valuation_methods": collect_nonempty(
                    source_claims,
                    [
                        "valuation_method",
                    ],
                ),
                "valuation_statuses": collect_nonempty(
                    source_claims,
                    [
                        "valuation_status",
                    ],
                ),
                "candidate_teams_from_claim_layer": collect_nonempty(
                    source_claims,
                    DESTINATION_COLUMNS,
                ),
                "obligation_group_ids": collect_nonempty(
                    source_claims,
                    [
                        "obligation_group_id",
                    ],
                ),
                "structural_families": collect_nonempty(
                    source_claims,
                    [
                        "structural_family",
                    ],
                ),
                "utah_pool_selection_probability": (
                    selection_probability
                ),
                "utah_pool_selected_value_component_score": (
                    selection_value
                ),
                "integration_state": (
                    integration_state
                ),
                "automatic_team_integration_ready": (
                    automatic_ready
                ),
                "integration_note": (
                    integration_note
                ),
            }
        )

    return pd.DataFrame(
        rows
    )


def main() -> None:
    OUTPUT_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    print("=" * 80)
    print("UTAH 2028 POOL SOURCE-ASSET OVERLAP DIAGNOSTIC")
    print("=" * 80)
    print(
        f"Script version: {SCRIPT_VERSION}"
    )
    print()

    (
        claims,
        valuations,
        dependency_nodes,
        pool_values,
        pool_selection,
        mia_resolution,
    ) = load_inputs()

    merged = merge_context(
        claims=claims,
        valuations=valuations,
        dependency_nodes=dependency_nodes,
    )

    source_asset_keys = set(
        POOL_SOURCE_ASSETS.values()
    )

    exact_source_claims = merged.loc[
        merged[
            "asset_key"
        ].astype(
            str
        ).isin(
            source_asset_keys
        )
    ].copy()

    exact_source_claims[
        "pool_source_team"
    ] = exact_source_claims[
        "asset_key"
    ].astype(
        str
    ).map(
        {
            asset_key: source_team
            for source_team, asset_key
            in POOL_SOURCE_ASSETS.items()
        }
    )

    related_text = merged.loc[
        source_related_text_mask(
            merged
        )
    ].copy()

    source_summary = build_source_summary(
        merged=merged,
        pool_selection=pool_selection,
        mia_resolution=mia_resolution,
    )

    overlap_queue = source_summary.loc[
        ~source_summary[
            "automatic_team_integration_ready"
        ]
    ].copy()

    pool = pool_values.iloc[
        0
    ]

    exact_source_claims.to_csv(
        SOURCE_CLAIMS_PATH,
        index=False,
    )

    source_summary.to_csv(
        SOURCE_SUMMARY_PATH,
        index=False,
    )

    overlap_queue.to_csv(
        OVERLAP_QUEUE_PATH,
        index=False,
    )

    related_text.to_csv(
        TEXT_MATCHES_PATH,
        index=False,
    )

    metadata = {
        "script_version": (
            SCRIPT_VERSION
        ),
        "created_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "expected_utah_pool_pick": numeric_value(
            pool[
                "expected_utah_pool_pick"
            ]
        ),
        "expected_utah_pool_value_score": numeric_value(
            pool[
                "expected_utah_pool_value_score"
            ]
        ),
        "pool_source_assets": (
            POOL_SOURCE_ASSETS
        ),
        "exact_source_claim_rows": len(
            exact_source_claims
        ),
        "related_text_match_rows": len(
            related_text
        ),
        "automatic_team_integration_ready_sources": int(
            source_summary[
                "automatic_team_integration_ready"
            ].sum()
        ),
        "source_assets_still_requiring_reallocation_logic": int(
            (
                ~source_summary[
                    "automatic_team_integration_ready"
                ]
            ).sum()
        ),
        "output_files": {
            "exact_source_claims": str(
                SOURCE_CLAIMS_PATH
            ),
            "source_summary": str(
                SOURCE_SUMMARY_PATH
            ),
            "overlap_resolution_queue": str(
                OVERLAP_QUEUE_PATH
            ),
            "related_text_matches": str(
                TEXT_MATCHES_PATH
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
    print("UTAH POOL SOURCE OVERLAP DIAGNOSTIC CREATED")
    print("=" * 80)
    print(
        "Expected Utah pool pick: "
        f"{numeric_value(pool['expected_utah_pool_pick']):.4f}"
    )
    print(
        "Expected Utah pool value score: "
        f"{numeric_value(pool['expected_utah_pool_value_score']):.4f}"
    )
    print(
        f"Exact source-asset claim rows: "
        f"{len(exact_source_claims):,}"
    )
    print(
        f"Related transaction-text rows: "
        f"{len(related_text):,}"
    )
    print(
        "Source assets automatically ready: "
        f"{int(source_summary['automatic_team_integration_ready'].sum()):,}"
    )
    print(
        "Source assets requiring reallocation logic: "
        f"{int((~source_summary['automatic_team_integration_ready']).sum()):,}"
    )
    print()

    print("SOURCE-ASSET SUMMARY")
    display = source_summary.copy()

    display[
        "utah_pool_selection_probability"
    ] = (
        pd.to_numeric(
            display[
                "utah_pool_selection_probability"
            ],
            errors="coerce",
        )
        * 100.0
    ).round(
        2
    )

    display[
        "utah_pool_selected_value_component_score"
    ] = pd.to_numeric(
        display[
            "utah_pool_selected_value_component_score"
        ],
        errors="coerce",
    ).round(
        4
    )

    print(
        display[
            [
                "source_team",
                "source_asset_key",
                "exact_claim_rows",
                "direct_candidate_claim_rows",
                "claim_ids",
                "claim_types",
                "resolution_statuses",
                "candidate_teams_from_claim_layer",
                "utah_pool_selection_probability",
                "utah_pool_selected_value_component_score",
                "integration_state",
                "automatic_team_integration_ready",
            ]
        ].to_string(
            index=False
        )
    )
    print()

    print("EXACT SOURCE CLAIM TEXT")
    if exact_source_claims.empty:
        print(
            "No exact source claims were found."
        )
    else:
        for row in exact_source_claims.itertuples(
            index=False
        ):
            print("-" * 80)
            print(
                f"Source: {getattr(row, 'pool_source_team', '')} | "
                f"Claim: {getattr(row, 'claim_id', '')} | "
                f"Asset: {getattr(row, 'asset_key', '')}"
            )

            for column in TEXT_COLUMNS:
                if hasattr(
                    row,
                    column,
                ):
                    text = clean_text(
                        getattr(
                            row,
                            column,
                            "",
                        )
                    )

                    if text:
                        print(
                            f"{column}: {text}"
                        )

    print()
    print("SAVED FILES")
    print(SOURCE_CLAIMS_PATH)
    print(SOURCE_SUMMARY_PATH)
    print(OVERLAP_QUEUE_PATH)
    print(TEXT_MATCHES_PATH)
    print(METADATA_PATH)


if __name__ == "__main__":
    main()