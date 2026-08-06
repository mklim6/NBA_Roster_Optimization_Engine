from __future__ import annotations

import itertools
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


SCRIPT_VERSION = (
    "future-pick-optimizer-team-value-attribution-diagnostic-v1-2026-08-04"
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]

FINAL_VALUATION_PATH = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "future_pick_claim_value_layer_2027_2029_final.parquet"
)

BEST_POLICY_TEAMS_PATH = (
    PROJECT_ROOT
    / "outputs"
    / "future_pick_optimizer_best_policy_remaining_teams_v2.csv"
)

BEST_POLICY_CLAIM_EFFECTS_PATH = (
    PROJECT_ROOT
    / "outputs"
    / "future_pick_optimizer_best_policy_claim_effects_v2.csv"
)

CLAIM_INVOLVEMENT_PATH = (
    PROJECT_ROOT
    / "outputs"
    / "future_pick_optimizer_remaining_team_claim_involvement_v2.csv"
)

ROW_ACCOUNTING_PATH = (
    PROJECT_ROOT
    / "outputs"
    / "future_pick_optimizer_claim_row_accounting_diagnostic_v1.csv"
)

REJECTED_INVENTORY_PATH = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "future_pick_optimizer_inventory_2027_2029_final.parquet"
)

OUTPUT_DIRECTORY = PROJECT_ROOT / "outputs"

VALUATION_ROWS_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_optimizer_remaining_team_valuation_rows_v1.csv"
)

OUTPUT_FILE_ROWS_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_optimizer_remaining_team_output_file_rows_v1.csv"
)

CORRECTION_CANDIDATES_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_optimizer_remaining_team_correction_candidates_v1.csv"
)

EXACT_MATCHES_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_optimizer_remaining_team_exact_value_matches_v1.csv"
)

TEAM_SUMMARY_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_optimizer_remaining_team_attribution_summary_v1.csv"
)

CLE_MIN_UTA_SOURCE_RECOVERY_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_optimizer_cle_min_uta_2027_source_recovery_v1.csv"
)

METADATA_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_optimizer_team_value_attribution_metadata_v1.json"
)


VALUE_TOLERANCE = 1e-6
MAX_COMBINATION_TERMS = 2
MAX_CANDIDATES_PER_TEAM = 200

TARGET_COMPONENT_FILE = (
    "future_pick_cle_min_uta_2027_candidate_rights_v1.parquet"
)

VALUE_NAME_PATTERN = re.compile(
    r"(?:value|adjustment|baseline|difference|remainder|retained|"
    r"transferred|option|score)",
    flags=re.IGNORECASE,
)

TEAM_COLUMN_PATTERN = re.compile(
    r"(?:^team$|_team$|team_|beneficiary|retaining|counterparty|"
    r"destination|owner)",
    flags=re.IGNORECASE,
)

EXCLUDED_VALUE_COLUMN_PATTERN = re.compile(
    r"(?:probability|count|rank|year|round|row|index|flag|passed|"
    r"size|bytes)",
    flags=re.IGNORECASE,
)


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


def parse_source_assets(
    value: Any,
) -> list[str]:
    return sorted(
        set(
            re.findall(
                r"20(?:27|28|29)_R[12]_[A-Z]{3}",
                clean_text(
                    value
                ).upper(),
            )
        )
    )


def team_columns(
    frame: pd.DataFrame,
) -> list[str]:
    return [
        column
        for column in frame.columns
        if TEAM_COLUMN_PATTERN.search(
            column
        )
    ]


def value_columns(
    frame: pd.DataFrame,
) -> list[str]:
    output = []

    for column in frame.columns:
        if not VALUE_NAME_PATTERN.search(
            column
        ):
            continue

        if EXCLUDED_VALUE_COLUMN_PATTERN.search(
            column
        ):
            continue

        numeric = pd.to_numeric(
            frame[
                column
            ],
            errors="coerce",
        )

        if numeric.notna().any():
            output.append(
                column
            )

    return output


def row_mentions_team(
    row: pd.Series,
    team: str,
    columns: list[str],
) -> bool:
    target = team.upper()

    for column in columns:
        value = clean_text(
            row.get(
                column,
                "",
            )
        ).upper()

        if not value:
            continue

        if value == target:
            return True

        if re.search(
            rf"\b{re.escape(target)}\b",
            value,
        ):
            return True

    return False


def extract_nonzero_values(
    row: pd.Series,
    columns: list[str],
) -> dict[str, float]:
    output = {}

    for column in columns:
        value = finite_or_nan(
            row.get(
                column,
                np.nan,
            )
        )

        if (
            np.isfinite(
                value
            )
            and abs(
                value
            )
            > 1e-12
        ):
            output[
                column
            ] = float(
                value
            )

    return output


def load_inputs() -> tuple[
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
]:
    required_paths = [
        FINAL_VALUATION_PATH,
        BEST_POLICY_TEAMS_PATH,
        BEST_POLICY_CLAIM_EFFECTS_PATH,
        CLAIM_INVOLVEMENT_PATH,
        ROW_ACCOUNTING_PATH,
        REJECTED_INVENTORY_PATH,
    ]

    for path in required_paths:
        if not path.exists():
            raise FileNotFoundError(
                "Required attribution input was not found:\n"
                f"{path}"
            )

    valuations = normalize_columns(
        pd.read_parquet(
            FINAL_VALUATION_PATH
        )
    )

    remaining_teams = normalize_columns(
        pd.read_csv(
            BEST_POLICY_TEAMS_PATH
        )
    )

    claim_effects = normalize_columns(
        pd.read_csv(
            BEST_POLICY_CLAIM_EFFECTS_PATH
        )
    )

    involvement = normalize_columns(
        pd.read_csv(
            CLAIM_INVOLVEMENT_PATH
        )
    )

    row_accounting = normalize_columns(
        pd.read_csv(
            ROW_ACCOUNTING_PATH
        )
    )

    rejected_inventory = normalize_columns(
        pd.read_parquet(
            REJECTED_INVENTORY_PATH
        )
    )

    require_columns(
        remaining_teams,
        [
            "candidate_team",
            "policy_value_difference",
        ],
        "Remaining-team table",
    )

    return (
        valuations,
        remaining_teams,
        claim_effects,
        involvement,
        row_accounting,
        rejected_inventory,
    )


def build_valuation_rows(
    valuations: pd.DataFrame,
    target_teams: list[str],
) -> pd.DataFrame:
    possible_team_columns = team_columns(
        valuations
    )

    searchable_text_columns = [
        column
        for column in valuations.columns
        if (
            pd.api.types.is_object_dtype(
                valuations[
                    column
                ]
            )
            or pd.api.types.is_string_dtype(
                valuations[
                    column
                ]
            )
        )
    ]

    search_columns = sorted(
        set(
            possible_team_columns
            + searchable_text_columns
        )
    )

    possible_value_columns = value_columns(
        valuations
    )

    rows = []

    for team in target_teams:
        for row_number, row in valuations.iterrows():
            if not row_mentions_team(
                row=row,
                team=team,
                columns=search_columns,
            ):
                continue

            values = extract_nonzero_values(
                row=row,
                columns=possible_value_columns,
            )

            rows.append(
                {
                    "candidate_team": team,
                    "valuation_row_number": int(
                        row_number
                    ),
                    "claim_id": clean_text(
                        row.get(
                            "claim_id",
                            "",
                        )
                    ),
                    "asset_key": clean_text(
                        row.get(
                            "asset_key",
                            "",
                        )
                    ),
                    "valuation_method": clean_text(
                        row.get(
                            "valuation_method",
                            "",
                        )
                    ),
                    "valuation_status": clean_text(
                        row.get(
                            "valuation_status",
                            "",
                        )
                    ),
                    "candidate_beneficiary_team": clean_text(
                        row.get(
                            "candidate_beneficiary_team",
                            "",
                        )
                    ).upper(),
                    "candidate_retaining_team": clean_text(
                        row.get(
                            "candidate_retaining_team",
                            "",
                        )
                    ).upper(),
                    "candidate_counterparty_team": clean_text(
                        row.get(
                            "candidate_counterparty_team",
                            "",
                        )
                    ).upper(),
                    "nonzero_value_columns_json": json.dumps(
                        values,
                        sort_keys=True,
                    ),
                    "nonzero_value_column_count": len(
                        values
                    ),
                    "valuation_scope_note": clean_text(
                        row.get(
                            "valuation_scope_note",
                            "",
                        )
                    ),
                }
            )

    return pd.DataFrame(
        rows
    )


def candidate_output_files() -> list[Path]:
    patterns = [
        "future_pick_*team_adjustments*.csv",
        "future_pick_*baseline_audit*.csv",
        "future_pick_*component_reconciliation*.csv",
        "future_pick_*source_reconciliation*.csv",
        "future_pick_*candidate_rights*.csv",
        "future_pick_*event_summary*.csv",
        "future_pick_*metadata*.csv",
    ]

    paths = set()

    for pattern in patterns:
        paths.update(
            OUTPUT_DIRECTORY.glob(
                pattern
            )
        )

    processed_directory = (
        PROJECT_ROOT
        / "data"
        / "processed"
    )

    for pattern in [
        "future_pick_*candidate_rights*.csv",
        "future_pick_*event_summary*.csv",
        "future_pick_*source_allocations*.csv",
        "future_pick_*source_asset_allocations*.csv",
    ]:
        paths.update(
            processed_directory.glob(
                pattern
            )
        )

    return sorted(
        paths
    )


def build_output_file_rows(
    target_teams: list[str],
) -> pd.DataFrame:
    rows = []

    for path in candidate_output_files():
        try:
            frame = normalize_columns(
                pd.read_csv(
                    path
                )
            )
        except (
            pd.errors.EmptyDataError,
            UnicodeDecodeError,
            OSError,
        ):
            continue

        if frame.empty:
            continue

        if len(
            frame
        ) > 100_000:
            continue

        possible_team_columns = team_columns(
            frame
        )

        searchable_columns = sorted(
            set(
                possible_team_columns
                + [
                    column
                    for column in frame.columns
                    if (
                        pd.api.types.is_object_dtype(
                            frame[
                                column
                            ]
                        )
                        or pd.api.types.is_string_dtype(
                            frame[
                                column
                            ]
                        )
                    )
                ]
            )
        )

        possible_value_columns = value_columns(
            frame
        )

        for team in target_teams:
            for row_number, row in frame.iterrows():
                if not row_mentions_team(
                    row=row,
                    team=team,
                    columns=searchable_columns,
                ):
                    continue

                values = extract_nonzero_values(
                    row=row,
                    columns=possible_value_columns,
                )

                rows.append(
                    {
                        "candidate_team": team,
                        "source_file": path.name,
                        "source_directory": str(
                            path.parent
                        ),
                        "source_row_number": int(
                            row_number
                        ),
                        "nonzero_value_columns_json": json.dumps(
                            values,
                            sort_keys=True,
                        ),
                        "nonzero_value_column_count": len(
                            values
                        ),
                        "full_row_json": json.dumps(
                            json_safe(
                                row.to_dict()
                            ),
                            sort_keys=True,
                        ),
                    }
                )

    return pd.DataFrame(
        rows
    )


def append_value_candidates(
    rows: list[dict[str, Any]],
    *,
    team: str,
    source_type: str,
    source_reference: str,
    row_reference: str,
    values: dict[str, float],
) -> None:
    for column, value in values.items():
        rows.append(
            {
                "candidate_team": team,
                "source_type": source_type,
                "source_reference": source_reference,
                "row_reference": row_reference,
                "value_column": column,
                "raw_value_score": float(
                    value
                ),
                "absolute_value_score": abs(
                    float(
                        value
                    )
                ),
            }
        )


def build_correction_candidates(
    valuation_rows: pd.DataFrame,
    output_rows: pd.DataFrame,
    row_accounting: pd.DataFrame,
    target_teams: list[str],
) -> pd.DataFrame:
    rows = []

    for row in valuation_rows.itertuples(
        index=False
    ):
        values = json.loads(
            row.nonzero_value_columns_json
        )

        append_value_candidates(
            rows,
            team=row.candidate_team,
            source_type="canonical_valuation_row",
            source_reference=row.claim_id,
            row_reference=str(
                row.valuation_row_number
            ),
            values=values,
        )

    for row in output_rows.itertuples(
        index=False
    ):
        values = json.loads(
            row.nonzero_value_columns_json
        )

        append_value_candidates(
            rows,
            team=row.candidate_team,
            source_type="output_file_row",
            source_reference=row.source_file,
            row_reference=str(
                row.source_row_number
            ),
            values=values,
        )

    accounting_value_columns = value_columns(
        row_accounting
    )

    accounting_search_columns = [
        column
        for column in [
            "candidate_beneficiary_team",
            "candidate_retaining_team",
            "candidate_counterparty_team",
        ]
        if column in row_accounting.columns
    ]

    for team in target_teams:
        for row_number, row in row_accounting.iterrows():
            if not row_mentions_team(
                row=row,
                team=team,
                columns=accounting_search_columns,
            ):
                continue

            values = extract_nonzero_values(
                row=row,
                columns=accounting_value_columns,
            )

            append_value_candidates(
                rows,
                team=team,
                source_type="claim_row_accounting",
                source_reference=clean_text(
                    row.get(
                        "claim_id",
                        "",
                    )
                ),
                row_reference=str(
                    row_number
                ),
                values=values,
            )

    output = pd.DataFrame(
        rows
    )

    if output.empty:
        return output

    output[
        "candidate_identity"
    ] = (
        output[
            "source_type"
        ]
        .astype(str)
        + "|"
        + output[
            "source_reference"
        ]
        .astype(str)
        + "|"
        + output[
            "row_reference"
        ]
        .astype(str)
        + "|"
        + output[
            "value_column"
        ]
        .astype(str)
        + "|"
        + output[
            "raw_value_score"
        ]
        .round(
            10
        )
        .astype(str)
    )

    output = output.drop_duplicates(
        subset=[
            "candidate_team",
            "candidate_identity",
        ]
    )

    return output.sort_values(
        [
            "candidate_team",
            "absolute_value_score",
            "source_type",
            "source_reference",
        ],
        ascending=[
            True,
            False,
            True,
            True,
        ],
    ).reset_index(
        drop=True
    )


def find_exact_matches(
    remaining_teams: pd.DataFrame,
    candidates: pd.DataFrame,
) -> pd.DataFrame:
    rows = []

    for team_row in remaining_teams.itertuples(
        index=False
    ):
        team = clean_text(
            team_row.candidate_team
        ).upper()

        policy_difference = float(
            team_row.policy_value_difference
        )

        required_correction = (
            -policy_difference
        )

        team_candidates = candidates.loc[
            candidates[
                "candidate_team"
            ].eq(
                team
            )
        ].copy()

        team_candidates = team_candidates.loc[
            team_candidates[
                "absolute_value_score"
            ]
            <= abs(
                required_correction
            )
            * 5.0
            + 1.0
        ]

        team_candidates = team_candidates.head(
            MAX_CANDIDATES_PER_TEAM
        )

        signed_terms = []

        for row in team_candidates.itertuples(
            index=False
        ):
            for sign in [
                1.0,
                -1.0,
            ]:
                signed_terms.append(
                    {
                        "signed_value": sign
                        * float(
                            row.raw_value_score
                        ),
                        "operation": (
                            "add"
                            if sign
                            > 0
                            else "subtract"
                        ),
                        "source_type": row.source_type,
                        "source_reference": (
                            row.source_reference
                        ),
                        "row_reference": row.row_reference,
                        "value_column": row.value_column,
                        "raw_value_score": float(
                            row.raw_value_score
                        ),
                        "candidate_identity": (
                            row.candidate_identity
                        ),
                    }
                )

        seen = set()

        for term_count in range(
            1,
            MAX_COMBINATION_TERMS
            + 1,
        ):
            for combination in itertools.combinations(
                signed_terms,
                term_count,
            ):
                identities = [
                    term[
                        "candidate_identity"
                    ]
                    for term in combination
                ]

                if len(
                    set(
                        identities
                    )
                ) != len(
                    identities
                ):
                    continue

                total = sum(
                    term[
                        "signed_value"
                    ]
                    for term in combination
                )

                difference = (
                    total
                    - required_correction
                )

                if abs(
                    difference
                ) > VALUE_TOLERANCE:
                    continue

                key = tuple(
                    sorted(
                        (
                            term[
                                "candidate_identity"
                            ],
                            term[
                                "operation"
                            ],
                        )
                        for term in combination
                    )
                )

                if key in seen:
                    continue

                seen.add(
                    key
                )

                rows.append(
                    {
                        "candidate_team": team,
                        "policy_value_difference": (
                            policy_difference
                        ),
                        "required_correction": (
                            required_correction
                        ),
                        "term_count": term_count,
                        "matched_correction": total,
                        "match_difference": difference,
                        "match_terms_json": json.dumps(
                            combination,
                            sort_keys=True,
                        ),
                    }
                )

    output = pd.DataFrame(
        rows
    )

    if output.empty:
        return output

    return output.sort_values(
        [
            "candidate_team",
            "term_count",
            "match_difference",
        ]
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
            TARGET_COMPONENT_FILE
        )
    ].copy()

    output_rows = []

    for row in rows.itertuples(
        index=False
    ):
        row_dict = row._asdict()

        source_assets = parse_source_assets(
            row_dict.get(
                "source_assets",
                "",
            )
        )

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

        if not source_assets:
            year_match = re.search(
                r"\b20(?:27|28|29)\b",
                description,
            )

            round_number = (
                1
                if re.search(
                    r"\b(?:first|1st)\b",
                    description,
                    flags=re.IGNORECASE,
                )
                else (
                    2
                    if re.search(
                        r"\b(?:second|2nd)\b",
                        description,
                        flags=re.IGNORECASE,
                    )
                    else None
                )
            )

            teams = sorted(
                set(
                    re.findall(
                        r"\b(?:ATL|BOS|BKN|CHA|CHI|CLE|DAL|DEN|DET|"
                        r"GSW|HOU|IND|LAC|LAL|MEM|MIA|MIL|MIN|NOP|"
                        r"NYK|OKC|ORL|PHI|PHX|POR|SAC|SAS|TOR|UTA|"
                        r"WAS)\b",
                        description.upper(),
                    )
                )
            )

            if (
                year_match
                and round_number is not None
                and teams
            ):
                source_assets = [
                    f"{year_match.group(0)}_R{round_number}_{team}"
                    for team in teams
                ]

        output_rows.append(
            {
                "component_right_file": TARGET_COMPONENT_FILE,
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
                "raw_right_description": description,
                "recovered_source_assets": "|".join(
                    source_assets
                ),
                "recovered_source_asset_count": len(
                    source_assets
                ),
                "source_recovery_passed": bool(
                    source_assets
                ),
            }
        )

    return pd.DataFrame(
        output_rows
    )


def build_team_summary(
    remaining_teams: pd.DataFrame,
    valuation_rows: pd.DataFrame,
    output_rows: pd.DataFrame,
    exact_matches: pd.DataFrame,
) -> pd.DataFrame:
    summary = remaining_teams[
        [
            "candidate_team",
            "policy_value_difference",
            "absolute_policy_value_difference",
        ]
    ].copy()

    valuation_counts = (
        valuation_rows.groupby(
            "candidate_team",
            as_index=False,
        )
        .agg(
            valuation_rows_involving_team=(
                "valuation_row_number",
                "size",
            )
        )
    )

    output_counts = (
        output_rows.groupby(
            "candidate_team",
            as_index=False,
        )
        .agg(
            output_file_rows_involving_team=(
                "source_row_number",
                "size",
            ),
            output_files_involving_team=(
                "source_file",
                "nunique",
            ),
        )
    )

    if exact_matches.empty:
        match_counts = pd.DataFrame(
            {
                "candidate_team": summary[
                    "candidate_team"
                ],
                "exact_value_match_count": 0,
                "single_term_exact_match_count": 0,
            }
        )
    else:
        match_counts = (
            exact_matches.groupby(
                "candidate_team",
                as_index=False,
            )
            .agg(
                exact_value_match_count=(
                    "term_count",
                    "size",
                ),
                single_term_exact_match_count=(
                    "term_count",
                    lambda values: int(
                        (
                            values
                            == 1
                        ).sum()
                    ),
                ),
            )
        )

    output = (
        summary.merge(
            valuation_counts,
            how="left",
            on="candidate_team",
        )
        .merge(
            output_counts,
            how="left",
            on="candidate_team",
        )
        .merge(
            match_counts,
            how="left",
            on="candidate_team",
        )
    )

    count_columns = [
        "valuation_rows_involving_team",
        "output_file_rows_involving_team",
        "output_files_involving_team",
        "exact_value_match_count",
        "single_term_exact_match_count",
    ]

    for column in count_columns:
        output[
            column
        ] = pd.to_numeric(
            output[
                column
            ],
            errors="coerce",
        ).fillna(
            0
        ).astype(
            int
        )

    output[
        "required_correction"
    ] = (
        -pd.to_numeric(
            output[
                "policy_value_difference"
            ],
            errors="coerce",
        )
    )

    return output.sort_values(
        "absolute_policy_value_difference",
        ascending=False,
    ).reset_index(
        drop=True
    )


def main() -> None:
    OUTPUT_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    print("=" * 80)
    print("FUTURE PICK OPTIMIZER TEAM-VALUE ATTRIBUTION DIAGNOSTIC")
    print("=" * 80)
    print(f"Script version: {SCRIPT_VERSION}")
    print()

    (
        valuations,
        remaining_teams,
        claim_effects,
        involvement,
        row_accounting,
        rejected_inventory,
    ) = load_inputs()

    target_teams = sorted(
        set(
            remaining_teams[
                "candidate_team"
            ]
            .fillna("")
            .astype(str)
            .str.upper()
        )
    )

    valuation_rows = build_valuation_rows(
        valuations=valuations,
        target_teams=target_teams,
    )

    output_rows = build_output_file_rows(
        target_teams=target_teams
    )

    candidates = build_correction_candidates(
        valuation_rows=valuation_rows,
        output_rows=output_rows,
        row_accounting=row_accounting,
        target_teams=target_teams,
    )

    exact_matches = find_exact_matches(
        remaining_teams=remaining_teams,
        candidates=candidates,
    )

    cle_min_uta_sources = recover_cle_min_uta_sources(
        rejected_inventory=rejected_inventory
    )

    team_summary = build_team_summary(
        remaining_teams=remaining_teams,
        valuation_rows=valuation_rows,
        output_rows=output_rows,
        exact_matches=exact_matches,
    )

    valuation_rows.to_csv(
        VALUATION_ROWS_PATH,
        index=False,
    )

    output_rows.to_csv(
        OUTPUT_FILE_ROWS_PATH,
        index=False,
    )

    candidates.to_csv(
        CORRECTION_CANDIDATES_PATH,
        index=False,
    )

    exact_matches.to_csv(
        EXACT_MATCHES_PATH,
        index=False,
    )

    team_summary.to_csv(
        TEAM_SUMMARY_PATH,
        index=False,
    )

    cle_min_uta_sources.to_csv(
        CLE_MIN_UTA_SOURCE_RECOVERY_PATH,
        index=False,
    )

    metadata = {
        "script_version": SCRIPT_VERSION,
        "created_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "target_teams": target_teams,
        "valuation_rows": int(
            len(
                valuation_rows
            )
        ),
        "output_file_rows": int(
            len(
                output_rows
            )
        ),
        "correction_candidates": int(
            len(
                candidates
            )
        ),
        "exact_value_matches": int(
            len(
                exact_matches
            )
        ),
        "single_term_exact_matches": int(
            (
                exact_matches[
                    "term_count"
                ]
                == 1
            ).sum()
        )
        if not exact_matches.empty
        else 0,
        "cle_min_uta_rows": int(
            len(
                cle_min_uta_sources
            )
        ),
        "cle_min_uta_source_recovery_passed": bool(
            not cle_min_uta_sources.empty
            and cle_min_uta_sources[
                "source_recovery_passed"
            ].all()
        ),
        "outputs": {
            "valuation_rows": str(
                VALUATION_ROWS_PATH
            ),
            "output_file_rows": str(
                OUTPUT_FILE_ROWS_PATH
            ),
            "correction_candidates": str(
                CORRECTION_CANDIDATES_PATH
            ),
            "exact_matches": str(
                EXACT_MATCHES_PATH
            ),
            "team_summary": str(
                TEAM_SUMMARY_PATH
            ),
            "cle_min_uta_source_recovery": str(
                CLE_MIN_UTA_SOURCE_RECOVERY_PATH
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
    print("TEAM-VALUE ATTRIBUTION DIAGNOSTIC CREATED")
    print("=" * 80)
    print(
        "Target teams: "
        + "|".join(
            target_teams
        )
    )
    print(
        "Canonical valuation rows involving target teams: "
        f"{len(valuation_rows):,}"
    )
    print(
        "Adjustment or component file rows involving target teams: "
        f"{len(output_rows):,}"
    )
    print(
        "Candidate correction values collected: "
        f"{len(candidates):,}"
    )
    print(
        "Exact one- or two-term correction matches: "
        f"{len(exact_matches):,}"
    )
    print(
        "CLE-MIN-UTA candidate-right rows recovered: "
        f"{len(cle_min_uta_sources):,}"
    )
    print()

    print("TEAM ATTRIBUTION SUMMARY")
    display_summary = team_summary.copy()

    for column in [
        "policy_value_difference",
        "absolute_policy_value_difference",
        "required_correction",
    ]:
        display_summary[
            column
        ] = pd.to_numeric(
            display_summary[
                column
            ],
            errors="coerce",
        ).round(
            6
        )

    print(
        display_summary.to_string(
            index=False
        )
    )
    print()

    print("SINGLE-TERM EXACT CORRECTION MATCHES")

    if exact_matches.empty:
        print(
            "No exact correction matches were found."
        )
    else:
        single_matches = exact_matches.loc[
            exact_matches[
                "term_count"
            ]
            == 1
        ].copy()

        if single_matches.empty:
            print(
                "No single-term exact matches were found."
            )
        else:
            for row in single_matches.itertuples(
                index=False
            ):
                terms = json.loads(
                    row.match_terms_json
                )

                term = terms[
                    0
                ]

                print(
                    f"{row.candidate_team}: correction "
                    f"{row.required_correction:.6f} = "
                    f"{term['operation']} "
                    f"{term['raw_value_score']:.6f} from "
                    f"{term['source_type']} / "
                    f"{term['source_reference']} / "
                    f"{term['value_column']}"
                )

    print()
    print("BEST TWO-TERM EXACT MATCH PER TEAM")

    if exact_matches.empty:
        print(
            "No exact matches were found."
        )
    else:
        two_matches = (
            exact_matches.loc[
                exact_matches[
                    "term_count"
                ]
                == 2
            ]
            .sort_values(
                [
                    "candidate_team",
                    "match_difference",
                ]
            )
            .groupby(
                "candidate_team",
                as_index=False,
            )
            .head(
                1
            )
        )

        if two_matches.empty:
            print(
                "No two-term exact matches were found."
            )
        else:
            for row in two_matches.itertuples(
                index=False
            ):
                terms = json.loads(
                    row.match_terms_json
                )

                descriptions = [
                    (
                        f"{term['operation']} "
                        f"{term['raw_value_score']:.6f} "
                        f"({term['source_reference']} / "
                        f"{term['value_column']})"
                    )
                    for term in terms
                ]

                print(
                    f"{row.candidate_team}: correction "
                    f"{row.required_correction:.6f} = "
                    + " + ".join(
                        descriptions
                    )
                )

    print()
    print("CLE-MIN-UTA 2027 SOURCE RECOVERY")

    if cle_min_uta_sources.empty:
        print(
            "No rejected inventory rows were found for the "
            "CLE-MIN-UTA component."
        )
    else:
        print(
            cle_min_uta_sources.to_string(
                index=False
            )
        )

    print()
    print("SAVED FILES")

    for path in [
        VALUATION_ROWS_PATH,
        OUTPUT_FILE_ROWS_PATH,
        CORRECTION_CANDIDATES_PATH,
        EXACT_MATCHES_PATH,
        TEAM_SUMMARY_PATH,
        CLE_MIN_UTA_SOURCE_RECOVERY_PATH,
        METADATA_PATH,
    ]:
        print(
            path
        )


if __name__ == "__main__":
    main()