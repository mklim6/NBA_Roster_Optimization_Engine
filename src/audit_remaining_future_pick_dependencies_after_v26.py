from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


SCRIPT_VERSION = (
    "future-pick-residual-dependency-audit-v1-after-v26-2026-08-04"
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
    / "future_pick_claim_value_layer_2027_2029_v26_atl_mia_cha_okc_enriched.parquet"
)

DEPENDENCY_NODES_PATH = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "future_pick_dependency_claim_nodes_2027_2029_v1.parquet"
)

REFINED_GROUPS_PATH = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "future_pick_dependency_groups_refined_2027_2029_v2.parquet"
)

TEAM_SUMMARY_PATH = (
    PROJECT_ROOT
    / "outputs"
    / "future_pick_candidate_team_value_summary_v26_atl_mia_cha_okc_provisional.csv"
)

OUTPUT_DIRECTORY = PROJECT_ROOT / "outputs"

CLAIM_AUDIT_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_residual_claim_audit_after_v26.csv"
)

GROUP_AUDIT_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_residual_dependency_group_audit_after_v26.csv"
)

ASSET_AUDIT_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_residual_unique_asset_exposure_after_v26.csv"
)

OUT_OF_HORIZON_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_modeled_out_of_horizon_tails_after_v26.csv"
)

VALUATION_STATUS_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_valuation_status_counts_after_v26.csv"
)

TEAM_SUMMARY_AUDIT_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_team_summary_integrity_audit_after_v26.csv"
)

METADATA_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_residual_dependency_audit_metadata_after_v26.json"
)


VALUED_STATUS_PREFIX = "valued_"

TEXT_COLUMNS = [
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

    return " ".join(
        str(
            value
        ).split()
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


def join_unique(
    values: pd.Series,
) -> str:
    cleaned = sorted(
        {
            clean_text(
                value
            )
            for value in values
            if clean_text(
                value
            )
        }
    )

    return "|".join(
        cleaned
    )


def combine_text(
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


def load_inputs() -> tuple[
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
        TEAM_SUMMARY_PATH,
    ]:
        if not path.exists():
            raise FileNotFoundError(
                "Required residual-audit input was not found:\n"
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

    refined_groups = (
        normalize_columns(
            pd.read_parquet(
                REFINED_GROUPS_PATH
            )
        )
        if REFINED_GROUPS_PATH.exists()
        else pd.DataFrame()
    )

    team_summary = normalize_columns(
        pd.read_csv(
            TEAM_SUMMARY_PATH
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
            "time_discounted_pick_value_score",
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
        "V26 valuation layer",
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
        team_summary,
        [
            "candidate_beneficiary_team",
            (
                "candidate_total_pick_asset_value_score_"
                "after_atl_mia_cha_okc_component_provisional"
            ),
        ],
        "V26 provisional team summary",
    )

    return (
        claims,
        valuations,
        dependency_nodes,
        refined_groups,
        team_summary,
    )


def merge_claim_context(
    claims: pd.DataFrame,
    valuations: pd.DataFrame,
    dependency_nodes: pd.DataFrame,
) -> pd.DataFrame:
    valuation_columns = [
        column
        for column in valuations.columns
        if column
        in {
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
            "denver_joint_out_of_horizon_2030_flag",
            "denver_joint_out_of_horizon_probability",
            "favorability_pool_team_integration_hold_flag",
            "rollover_team_aggregation_hold_flag",
            "team_aggregation_hold_flag",
        }
    ]

    dependency_columns = [
        column
        for column in dependency_nodes.columns
        if column
        in {
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
        }
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
        "_combined_text"
    ] = combine_text(
        output
    )

    output[
        "valuation_status"
    ] = output[
        "valuation_status"
    ].fillna(
        ""
    ).astype(
        str
    )

    output[
        "valuation_method"
    ] = output[
        "valuation_method"
    ].fillna(
        ""
    ).astype(
        str
    )

    output[
        "claim_fully_valued"
    ] = output[
        "valuation_status"
    ].str.startswith(
        VALUED_STATUS_PREFIX
    )

    output[
        "claim_unresolved"
    ] = (
        ~output[
            "claim_fully_valued"
        ]
    )

    out_of_horizon_flag = pd.Series(
        False,
        index=output.index,
        dtype=bool,
    )

    if (
        "denver_joint_out_of_horizon_2030_flag"
        in output.columns
    ):
        out_of_horizon_flag = (
            output[
                "denver_joint_out_of_horizon_2030_flag"
            ]
            .fillna(
                False
            )
            .astype(
                bool
            )
        )

    output[
        "modeled_out_of_horizon_tail"
    ] = (
        out_of_horizon_flag
    )

    output[
        "audit_state"
    ] = np.select(
        [
            output[
                "claim_unresolved"
            ],
            output[
                "modeled_out_of_horizon_tail"
            ],
        ],
        [
            "unresolved_in_current_horizon",
            "valued_with_out_of_horizon_tail",
        ],
        default="valued_in_current_horizon",
    )

    output[
        "effective_obligation_group_id"
    ] = output[
        "obligation_group_id"
    ].fillna(
        ""
    ).astype(
        str
    )

    missing_group = output[
        "effective_obligation_group_id"
    ].eq(
        ""
    )

    output.loc[
        missing_group,
        "effective_obligation_group_id",
    ] = (
        "UNGROUPED_"
        + output.loc[
            missing_group,
            "asset_key",
        ].astype(
            str
        )
    )

    output[
        "asset_exposure_score"
    ] = numeric_series(
        output,
        "time_discounted_pick_value_score",
    )

    return output


def build_asset_exposure(
    unresolved: pd.DataFrame,
) -> pd.DataFrame:
    if unresolved.empty:
        return pd.DataFrame(
            columns=[
                "asset_key",
                "draft_year",
                "round_number",
                "originating_team",
                "claim_rows",
                "obligation_groups",
                "claim_types",
                "structural_families",
                "unconditional_asset_exposure_score",
            ]
        )

    asset_rows = []

    for asset_key, group in unresolved.groupby(
        "asset_key",
        dropna=False,
    ):
        exposure_values = pd.to_numeric(
            group[
                "asset_exposure_score"
            ],
            errors="coerce",
        ).dropna()

        exposure = (
            float(
                exposure_values.iloc[
                    0
                ]
            )
            if not exposure_values.empty
            else np.nan
        )

        if (
            not exposure_values.empty
            and (
                exposure_values
                - exposure
            ).abs().max()
            > 1e-8
        ):
            raise ValueError(
                "Claims for the same asset carry different exposure "
                f"values: {asset_key}"
            )

        asset_rows.append(
            {
                "asset_key": (
                    asset_key
                ),
                "draft_year": int(
                    pd.to_numeric(
                        group[
                            "draft_year"
                        ],
                        errors="coerce",
                    ).dropna().iloc[
                        0
                    ]
                ),
                "round_number": int(
                    pd.to_numeric(
                        group[
                            "round_number"
                        ],
                        errors="coerce",
                    ).dropna().iloc[
                        0
                    ]
                ),
                "originating_team": join_unique(
                    group[
                        "originating_team"
                    ]
                ),
                "claim_rows": len(
                    group
                ),
                "obligation_groups": join_unique(
                    group[
                        "effective_obligation_group_id"
                    ]
                ),
                "claim_types": join_unique(
                    group[
                        "claim_type"
                    ]
                ),
                "structural_families": join_unique(
                    group[
                        "structural_family"
                    ]
                ),
                "unconditional_asset_exposure_score": (
                    exposure
                ),
            }
        )

    return pd.DataFrame(
        asset_rows
    ).sort_values(
        [
            "unconditional_asset_exposure_score",
            "asset_key",
        ],
        ascending=[
            False,
            True,
        ],
        na_position="last",
    ).reset_index(
        drop=True
    )


def build_group_audit(
    unresolved: pd.DataFrame,
    asset_exposure: pd.DataFrame,
    refined_groups: pd.DataFrame,
) -> pd.DataFrame:
    if unresolved.empty:
        return pd.DataFrame(
            columns=[
                "effective_obligation_group_id",
                "claim_rows",
                "unique_assets",
                "unique_asset_exposure_score",
            ]
        )

    asset_exposure_lookup = (
        asset_exposure.set_index(
            "asset_key"
        )[
            "unconditional_asset_exposure_score"
        ].to_dict()
    )

    rows = []

    for group_id, group in unresolved.groupby(
        "effective_obligation_group_id",
        dropna=False,
    ):
        assets = sorted(
            set(
                group[
                    "asset_key"
                ].astype(
                    str
                )
            )
        )

        exposure = float(
            sum(
                finite_value
                for finite_value in [
                    asset_exposure_lookup.get(
                        asset,
                        np.nan,
                    )
                    for asset in assets
                ]
                if np.isfinite(
                    finite_value
                )
            )
        )

        years = pd.to_numeric(
            group[
                "draft_year"
            ],
            errors="coerce",
        ).dropna().astype(
            int
        )

        automatic_reasons = (
            group[
                "automatic_exclusion_reason"
            ]
            if "automatic_exclusion_reason"
            in group.columns
            else pd.Series(
                "",
                index=group.index,
            )
        )

        rows.append(
            {
                "effective_obligation_group_id": (
                    group_id
                ),
                "claim_rows": len(
                    group
                ),
                "unique_assets": len(
                    assets
                ),
                "asset_keys": "|".join(
                    assets
                ),
                "draft_years": "|".join(
                    str(
                        year
                    )
                    for year in sorted(
                        set(
                            years.tolist()
                        )
                    )
                ),
                "originating_teams": join_unique(
                    group[
                        "originating_team"
                    ]
                ),
                "claim_types": join_unique(
                    group[
                        "claim_type"
                    ]
                ),
                "resolution_statuses": join_unique(
                    group[
                        "resolution_status"
                    ]
                ),
                "structural_families": join_unique(
                    group[
                        "structural_family"
                    ]
                ),
                "mentioned_teams": (
                    join_unique(
                        group[
                            "mentioned_teams"
                        ]
                    )
                    if "mentioned_teams"
                    in group.columns
                    else ""
                ),
                "beneficiary_teams": (
                    join_unique(
                        group[
                            "beneficiary_teams"
                        ]
                    )
                    if "beneficiary_teams"
                    in group.columns
                    else ""
                ),
                "automatic_exclusion_reasons": join_unique(
                    automatic_reasons
                ),
                "unique_asset_exposure_score": (
                    exposure
                ),
                "contains_2029_or_earlier_only": bool(
                    (
                        years
                        <= 2029
                    ).all()
                ),
                "contains_out_of_horizon_text": bool(
                    group[
                        "_combined_text"
                    ].str.contains(
                        r"\b2030\b|\b2031\b|\b2032\b|\b2033\b",
                        case=False,
                        regex=True,
                        na=False,
                    ).any()
                ),
            }
        )

    output = pd.DataFrame(
        rows
    )

    if not refined_groups.empty:
        refined_group_id_column = None

        for candidate in [
            "obligation_group_id",
            "effective_obligation_group_id",
        ]:
            if candidate in refined_groups.columns:
                refined_group_id_column = candidate
                break

        if refined_group_id_column is not None:
            refined_columns = [
                column
                for column in [
                    refined_group_id_column,
                    "dependency_class",
                    "refined_candidate_resolution_tier",
                    "refined_status",
                    "safe_rollover_candidate",
                    "suspicious_candidate",
                    "manual_review_required",
                ]
                if column in refined_groups.columns
            ]

            refined_subset = (
                refined_groups[
                    refined_columns
                ]
                .drop_duplicates(
                    subset=[
                        refined_group_id_column
                    ]
                )
                .rename(
                    columns={
                        refined_group_id_column: (
                            "effective_obligation_group_id"
                        )
                    }
                )
            )

            output = output.merge(
                refined_subset,
                how="left",
                on="effective_obligation_group_id",
                validate="one_to_one",
            )

    output[
        "review_order"
    ] = output[
        "unique_asset_exposure_score"
    ].rank(
        method="first",
        ascending=False,
    ).astype(
        int
    )

    return output.sort_values(
        [
            "review_order",
            "effective_obligation_group_id",
        ]
    ).reset_index(
        drop=True
    )


def build_team_summary_audit(
    team_summary: pd.DataFrame,
) -> pd.DataFrame:
    team_column = (
        "candidate_beneficiary_team"
    )

    value_column = (
        "candidate_total_pick_asset_value_score_"
        "after_atl_mia_cha_okc_component_provisional"
    )

    duplicate_teams = (
        team_summary[
            team_column
        ].astype(
            str
        ).duplicated(
            keep=False
        )
    )

    values = pd.to_numeric(
        team_summary[
            value_column
        ],
        errors="coerce",
    )

    return pd.DataFrame(
        [
            {
                "team_rows": len(
                    team_summary
                ),
                "unique_teams": int(
                    team_summary[
                        team_column
                    ].astype(
                        str
                    ).nunique()
                ),
                "duplicate_team_rows": int(
                    duplicate_teams.sum()
                ),
                "missing_team_names": int(
                    team_summary[
                        team_column
                    ].fillna(
                        ""
                    ).astype(
                        str
                    ).eq(
                        ""
                    ).sum()
                ),
                "missing_team_values": int(
                    values.isna().sum()
                ),
                "negative_team_values": int(
                    (
                        values
                        < 0
                    ).sum()
                ),
                "leaguewide_candidate_value_score": float(
                    values.sum()
                ),
                "integrity_passed": bool(
                    duplicate_teams.sum()
                    == 0
                    and values.isna().sum()
                    == 0
                    and (
                        values
                        < 0
                    ).sum()
                    == 0
                ),
            }
        ]
    )


def main() -> None:
    OUTPUT_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    print("=" * 80)
    print("FUTURE PICK RESIDUAL DEPENDENCY AUDIT AFTER V26")
    print("=" * 80)
    print(
        f"Script version: {SCRIPT_VERSION}"
    )
    print()

    (
        claims,
        valuations,
        dependency_nodes,
        refined_groups,
        team_summary,
    ) = load_inputs()

    claim_audit = merge_claim_context(
        claims=claims,
        valuations=valuations,
        dependency_nodes=dependency_nodes,
    )

    unresolved = claim_audit.loc[
        claim_audit[
            "claim_unresolved"
        ]
    ].copy()

    out_of_horizon = claim_audit.loc[
        claim_audit[
            "modeled_out_of_horizon_tail"
        ]
    ].copy()

    asset_exposure = build_asset_exposure(
        unresolved
    )

    group_audit = build_group_audit(
        unresolved=unresolved,
        asset_exposure=asset_exposure,
        refined_groups=refined_groups,
    )

    status_counts = (
        claim_audit.groupby(
            [
                "audit_state",
                "valuation_method",
                "valuation_status",
            ],
            dropna=False,
        )
        .size()
        .reset_index(
            name="claim_rows"
        )
        .sort_values(
            [
                "audit_state",
                "claim_rows",
                "valuation_method",
            ],
            ascending=[
                True,
                False,
                True,
            ],
        )
        .reset_index(
            drop=True
        )
    )

    team_summary_audit = build_team_summary_audit(
        team_summary
    )

    claim_audit.to_csv(
        CLAIM_AUDIT_PATH,
        index=False,
    )

    group_audit.to_csv(
        GROUP_AUDIT_PATH,
        index=False,
    )

    asset_exposure.to_csv(
        ASSET_AUDIT_PATH,
        index=False,
    )

    out_of_horizon.to_csv(
        OUT_OF_HORIZON_PATH,
        index=False,
    )

    status_counts.to_csv(
        VALUATION_STATUS_PATH,
        index=False,
    )

    team_summary_audit.to_csv(
        TEAM_SUMMARY_AUDIT_PATH,
        index=False,
    )

    largest_group = (
        group_audit.iloc[
            0
        ].to_dict()
        if not group_audit.empty
        else {}
    )

    metadata = {
        "script_version": (
            SCRIPT_VERSION
        ),
        "created_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "total_claim_rows": len(
            claim_audit
        ),
        "fully_valued_claim_rows": int(
            claim_audit[
                "claim_fully_valued"
            ].sum()
        ),
        "unresolved_claim_rows": len(
            unresolved
        ),
        "unresolved_unique_assets": int(
            unresolved[
                "asset_key"
            ].astype(
                str
            ).nunique()
        ),
        "unresolved_dependency_groups": int(
            unresolved[
                "effective_obligation_group_id"
            ].astype(
                str
            ).nunique()
        ),
        "modeled_out_of_horizon_tail_rows": len(
            out_of_horizon
        ),
        "unique_unresolved_asset_exposure_score": float(
            asset_exposure[
                "unconditional_asset_exposure_score"
            ].sum()
        )
        if not asset_exposure.empty
        else 0.0,
        "largest_unresolved_group_by_unique_asset_exposure": (
            largest_group
        ),
        "team_summary_integrity_passed": bool(
            team_summary_audit.iloc[
                0
            ][
                "integrity_passed"
            ]
        ),
        "interpretation_note": (
            "Unresolved exposure is the sum of unique underlying pick "
            "values associated with unresolved claims. It is an exposure "
            "ceiling, not an additive candidate-right value, because pools "
            "and swap chains may share physical picks."
        ),
        "output_files": {
            "claim_audit": str(
                CLAIM_AUDIT_PATH
            ),
            "dependency_group_audit": str(
                GROUP_AUDIT_PATH
            ),
            "unique_asset_exposure": str(
                ASSET_AUDIT_PATH
            ),
            "out_of_horizon_tails": str(
                OUT_OF_HORIZON_PATH
            ),
            "valuation_status_counts": str(
                VALUATION_STATUS_PATH
            ),
            "team_summary_integrity": str(
                TEAM_SUMMARY_AUDIT_PATH
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
    print("RESIDUAL DEPENDENCY AUDIT AFTER V26 CREATED")
    print("=" * 80)
    print(
        f"Total claim rows: "
        f"{len(claim_audit):,}"
    )
    print(
        "Fully valued claim rows: "
        f"{int(claim_audit['claim_fully_valued'].sum()):,}"
    )
    print(
        f"Unresolved claim rows: "
        f"{len(unresolved):,}"
    )
    print(
        "Unresolved unique assets: "
        f"{unresolved['asset_key'].astype(str).nunique():,}"
    )
    print(
        "Unresolved dependency groups: "
        f"{unresolved['effective_obligation_group_id'].astype(str).nunique():,}"
    )
    print(
        "Modeled rows with out-of-horizon tails: "
        f"{len(out_of_horizon):,}"
    )
    print(
        "Unique unresolved asset exposure score: "
        f"{asset_exposure['unconditional_asset_exposure_score'].sum():.4f}"
        if not asset_exposure.empty
        else
        "Unique unresolved asset exposure score: 0.0000"
    )
    print(
        "Team summary integrity passed: "
        f"{bool(team_summary_audit.iloc[0]['integrity_passed'])}"
    )
    print()

    print("TOP UNRESOLVED DEPENDENCY GROUPS")
    if group_audit.empty:
        print(
            "No unresolved dependency groups remain."
        )
    else:
        display_columns = [
            "review_order",
            "effective_obligation_group_id",
            "claim_rows",
            "unique_assets",
            "unique_asset_exposure_score",
            "draft_years",
            "originating_teams",
            "claim_types",
            "structural_families",
            "beneficiary_teams",
            "contains_out_of_horizon_text",
            "automatic_exclusion_reasons",
        ]

        available_columns = [
            column
            for column in display_columns
            if column in group_audit.columns
        ]

        display = group_audit[
            available_columns
        ].head(
            20
        ).copy()

        if (
            "unique_asset_exposure_score"
            in display.columns
        ):
            display[
                "unique_asset_exposure_score"
            ] = pd.to_numeric(
                display[
                    "unique_asset_exposure_score"
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
    print("TOP UNRESOLVED UNIQUE ASSETS")
    if asset_exposure.empty:
        print(
            "No unresolved assets remain."
        )
    else:
        display_assets = asset_exposure.head(
            20
        ).copy()

        display_assets[
            "unconditional_asset_exposure_score"
        ] = pd.to_numeric(
            display_assets[
                "unconditional_asset_exposure_score"
            ],
            errors="coerce",
        ).round(
            4
        )

        print(
            display_assets.to_string(
                index=False
            )
        )

    print()
    print("VALUATION STATUS COUNTS")
    print(
        status_counts.to_string(
            index=False
        )
    )

    print()
    print("SAVED FILES")
    print(CLAIM_AUDIT_PATH)
    print(GROUP_AUDIT_PATH)
    print(ASSET_AUDIT_PATH)
    print(OUT_OF_HORIZON_PATH)
    print(VALUATION_STATUS_PATH)
    print(TEAM_SUMMARY_AUDIT_PATH)
    print(METADATA_PATH)


if __name__ == "__main__":
    main()