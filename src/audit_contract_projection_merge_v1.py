from __future__ import annotations

import html
import json
import math
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


SCRIPT_VERSION = (
    "contract-financial-layer-v2-unicode-obligations-2026-08-03"
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]

RAW_CONTRACTS_PATH = (
    PROJECT_ROOT
    / "data"
    / "raw"
    / "contracts"
    / "basketball_reference_player_contracts_2026_27.parquet"
)

PROJECTION_BOARD_PATH = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "current_player_projection_board_2025_26_to_2026_27.parquet"
)

RAW_DIRECTORY = (
    PROJECT_ROOT
    / "data"
    / "raw"
    / "contracts"
)

PROCESSED_DIRECTORY = (
    PROJECT_ROOT
    / "data"
    / "processed"
)

OUTPUT_DIRECTORY = (
    PROJECT_ROOT
    / "outputs"
)

CLEAN_CONTRACTS_PARQUET_PATH = (
    RAW_DIRECTORY
    / "basketball_reference_player_contracts_2026_27_v2_clean.parquet"
)

CLEAN_CONTRACTS_CSV_PATH = (
    RAW_DIRECTORY
    / "basketball_reference_player_contracts_2026_27_v2_clean.csv"
)

FINANCIAL_LAYER_PARQUET_PATH = (
    PROCESSED_DIRECTORY
    / "player_financial_layer_2026_27_v2.parquet"
)

FINANCIAL_LAYER_CSV_PATH = (
    PROCESSED_DIRECTORY
    / "player_financial_layer_2026_27_v2.csv"
)

TEAM_SUMMARY_PATH = (
    OUTPUT_DIRECTORY
    / "player_financial_layer_team_summary_2026_27_v2.csv"
)

UNMATCHED_BOARD_PATH = (
    OUTPUT_DIRECTORY
    / "player_financial_layer_unmatched_board_players_2026_27_v2.csv"
)

CONTRACT_ONLY_PATH = (
    OUTPUT_DIRECTORY
    / "player_financial_layer_contract_only_rows_2026_27_v2.csv"
)

MULTI_TEAM_OBLIGATIONS_PATH = (
    OUTPUT_DIRECTORY
    / "player_financial_layer_multi_team_obligations_2026_27_v2.csv"
)

MATCH_AUDIT_PATH = (
    OUTPUT_DIRECTORY
    / "player_financial_layer_match_audit_2026_27_v2.csv"
)

METADATA_PATH = (
    OUTPUT_DIRECTORY
    / "player_financial_layer_metadata_2026_27_v2.json"
)

SALARY_CAP_2026_27 = 164_961_000
LUXURY_TAX_2026_27 = 200_428_000
FIRST_APRON_2026_27 = 209_015_000
SECOND_APRON_2026_27 = 221_686_000

SALARY_COLUMNS = [
    "salary_2026_27",
    "salary_2027_28",
    "salary_2028_29",
    "salary_2029_30",
    "salary_2030_31",
    "salary_2031_32",
]

BREF_TEAM_TO_NBA = {
    "BRK": "BKN",
    "CHO": "CHA",
    "PHO": "PHX",
}

# These aliases reconcile common initial/suffix or published-name variants.
# They do not join different people.
NORMALIZED_NAME_ALIASES = {
    "aj green": "a j green",
    "aj johnson": "a j johnson",
    "aj lawson": "a j lawson",
    "cj mccollum": "c j mccollum",
    "dj carton": "d j carton",
    "gg jackson": "g g jackson",
    "gg jackson ii": "g g jackson",
    "kj martin": "k j martin",
    "pj tucker": "p j tucker",
    "pj washington": "p j washington",
    "rj barrett": "r j barrett",
    "ronald holland": "ron holland",
    "ron holland": "ron holland",
    "tj mcconnell": "t j mcconnell",
}

MOJIBAKE_MARKERS = (
    "Ã",
    "Â",
    "Å",
    "Ä",
    "Ð",
    "Ñ",
    "â",
    "ð",
    "�",
    "¼",
    "½",
)


def mojibake_score(value: str) -> int:
    return sum(
        value.count(marker)
        for marker in MOJIBAKE_MARKERS
    )


def candidate_repairs(value: str) -> list[str]:
    candidates = [value]

    for source_encoding in (
        "latin-1",
        "cp1252",
    ):
        try:
            repaired = value.encode(
                source_encoding
            ).decode("utf-8")
            candidates.append(repaired)
        except (
            UnicodeEncodeError,
            UnicodeDecodeError,
        ):
            pass

    return candidates


def repair_mojibake(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""

    current = html.unescape(
        str(value).strip()
    )

    # Two passes repair common double-decoding cases while preserving
    # already-correct Unicode whenever it has the lower error score.
    for _ in range(2):
        candidates = candidate_repairs(
            current
        )

        current = min(
            candidates,
            key=lambda candidate: (
                mojibake_score(candidate),
                candidate.count("�"),
                abs(
                    len(candidate)
                    - len(current)
                ),
            ),
        )

    return unicodedata.normalize(
        "NFC",
        current,
    )


def normalize_name(value: Any) -> str:
    repaired = repair_mojibake(value)

    normalized = unicodedata.normalize(
        "NFKD",
        repaired,
    )

    normalized = "".join(
        character
        for character in normalized
        if not unicodedata.combining(
            character
        )
    )

    normalized = normalized.lower()

    normalized = normalized.replace(
        "’",
        "'",
    )

    normalized = normalized.replace(
        "`",
        "'",
    )

    normalized = re.sub(
        r"\b(jr|sr|ii|iii|iv)\b\.?",
        "",
        normalized,
    )

    normalized = re.sub(
        r"[^a-z0-9]+",
        " ",
        normalized,
    )

    normalized = re.sub(
        r"\s+",
        " ",
        normalized,
    ).strip()

    return NORMALIZED_NAME_ALIASES.get(
        normalized,
        normalized,
    )


def normalize_team(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""

    team = str(value).strip().upper()

    return BREF_TEAM_TO_NBA.get(
        team,
        team,
    )


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
            + "\n".join(missing)
        )


def load_raw_contracts() -> pd.DataFrame:
    if not RAW_CONTRACTS_PATH.exists():
        raise FileNotFoundError(
            "The v1 raw contract table was not found at:\n"
            f"{RAW_CONTRACTS_PATH}"
        )

    contracts = pd.read_parquet(
        RAW_CONTRACTS_PATH
    ).copy()

    require_columns(
        contracts,
        [
            "contract_player_name",
            "contract_team_2026_27",
            "salary_2026_27",
        ],
        "Raw contract table",
    )

    for column in SALARY_COLUMNS + [
        "guaranteed_remaining",
        "total_listed_future_salary",
        "future_salary_commitment_2027_28_plus",
    ]:
        if column in contracts.columns:
            contracts[column] = pd.to_numeric(
                contracts[column],
                errors="coerce",
            )

    contracts[
        "contract_player_name_original"
    ] = contracts[
        "contract_player_name"
    ].astype(str)

    contracts[
        "contract_player_name"
    ] = contracts[
        "contract_player_name"
    ].map(
        repair_mojibake
    )

    contracts[
        "contract_team_2026_27"
    ] = contracts[
        "contract_team_2026_27"
    ].map(
        normalize_team
    )

    contracts[
        "normalized_player_name"
    ] = contracts[
        "contract_player_name"
    ].map(
        normalize_name
    )

    contracts[
        "unicode_repair_applied"
    ] = contracts[
        "contract_player_name_original"
    ].ne(
        contracts[
            "contract_player_name"
        ]
    )

    exact_key_columns = [
        "normalized_player_name",
        "contract_team_2026_27",
        *[
            column
            for column in SALARY_COLUMNS
            if column in contracts.columns
        ],
        *[
            column
            for column in [
                "guaranteed_remaining",
                "total_listed_future_salary",
                "future_salary_commitment_2027_28_plus",
            ]
            if column in contracts.columns
        ],
    ]

    contracts[
        "exact_duplicate_row_count"
    ] = (
        contracts.groupby(
            exact_key_columns,
            dropna=False,
        )[
            "contract_player_name"
        ]
        .transform("size")
        .astype(int)
    )

    contracts = contracts.drop_duplicates(
        subset=exact_key_columns,
        keep="first",
    ).reset_index(drop=True)

    contracts[
        "normalized_name_contract_row_count"
    ] = (
        contracts.groupby(
            "normalized_player_name"
        )[
            "contract_player_name"
        ]
        .transform("size")
        .astype(int)
    )

    contracts[
        "multi_team_salary_obligation_flag"
    ] = (
        contracts.groupby(
            "normalized_player_name"
        )[
            "contract_team_2026_27"
        ]
        .transform("nunique")
        .gt(1)
    )

    contracts[
        "contract_row_id"
    ] = np.arange(
        1,
        len(contracts) + 1,
    )

    return contracts


def load_projection_board() -> pd.DataFrame:
    if not PROJECTION_BOARD_PATH.exists():
        raise FileNotFoundError(
            "Projection board was not found at:\n"
            f"{PROJECTION_BOARD_PATH}"
        )

    board = pd.read_parquet(
        PROJECTION_BOARD_PATH
    ).copy()

    required = [
        "player_id",
        "player_name",
        "main_pool_eligible",
        "projected_expected_contribution",
        "projected_survival_probability",
        "projected_active_downside_contribution_80",
        "projected_active_upside_contribution_80",
        "survival_weighted_active_downside_score",
    ]

    require_columns(
        board,
        required,
        "Projection board",
    )

    if "team_abbreviation" in board.columns:
        board = board.rename(
            columns={
                "team_abbreviation": (
                    "performance_team_2025_26"
                )
            }
        )
    elif (
        "performance_team_2025_26"
        not in board.columns
    ):
        raise ValueError(
            "Projection board does not contain a team column."
        )

    if board["player_id"].duplicated().any():
        raise ValueError(
            "Projection board contains duplicate player IDs."
        )

    board[
        "performance_team_2025_26"
    ] = board[
        "performance_team_2025_26"
    ].map(
        normalize_team
    )

    board[
        "normalized_player_name"
    ] = board[
        "player_name"
    ].map(
        normalize_name
    )

    return board


def choose_contract_row(
    player: pd.Series,
    candidate_rows: pd.DataFrame,
) -> tuple[pd.Series | None, str]:
    if candidate_rows.empty:
        return (
            None,
            "unmatched_no_2026_27_contract_row",
        )

    if len(candidate_rows) == 1:
        return (
            candidate_rows.iloc[0],
            "matched_unique_normalized_name",
        )

    performance_team = str(
        player[
            "performance_team_2025_26"
        ]
    )

    same_team = candidate_rows.loc[
        candidate_rows[
            "contract_team_2026_27"
        ].eq(performance_team)
    ]

    if len(same_team) == 1:
        return (
            same_team.iloc[0],
            (
                "matched_multi_team_obligation_"
                "by_2025_26_team"
            ),
        )

    if len(same_team) > 1:
        same_team = same_team.sort_values(
            [
                "salary_2026_27",
                "guaranteed_remaining",
            ],
            ascending=[
                False,
                False,
            ],
            na_position="last",
        )

        return (
            same_team.iloc[0],
            (
                "matched_same_team_duplicate_"
                "highest_salary"
            ),
        )

    return (
        None,
        "unresolved_multi_team_salary_obligation",
    )


def merge_board_and_contracts(
    board: pd.DataFrame,
    contracts: pd.DataFrame,
) -> tuple[
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
]:
    grouped_contracts = {
        normalized_name: group.copy()
        for (
            normalized_name,
            group,
        ) in contracts.groupby(
            "normalized_player_name",
            sort=False,
        )
    }

    contract_payload_columns = [
        column
        for column in contracts.columns
        if column
        not in {
            "normalized_player_name",
        }
    ]

    output_rows: list[dict[str, Any]] = []
    audit_rows: list[dict[str, Any]] = []
    selected_contract_row_ids: set[int] = set()

    for _, player in board.iterrows():
        normalized_name = player[
            "normalized_player_name"
        ]

        candidates = grouped_contracts.get(
            normalized_name,
            contracts.iloc[0:0],
        )

        selected, status = (
            choose_contract_row(
                player=player,
                candidate_rows=candidates,
            )
        )

        row = player.to_dict()

        row[
            "candidate_contract_row_count"
        ] = int(len(candidates))

        row[
            "contract_match_status"
        ] = status

        if selected is None:
            for column in contract_payload_columns:
                row[column] = pd.NA

            row[
                "under_contract_2026_27"
            ] = False

            row[
                "current_team_2026_27"
            ] = pd.NA

            row[
                "trade_salary_2026_27"
            ] = np.nan

            selected_contract_row_id = None
        else:
            for column in contract_payload_columns:
                row[column] = selected[
                    column
                ]

            row[
                "under_contract_2026_27"
            ] = True

            row[
                "current_team_2026_27"
            ] = selected[
                "contract_team_2026_27"
            ]

            row[
                "trade_salary_2026_27"
            ] = selected[
                "salary_2026_27"
            ]

            selected_contract_row_id = int(
                selected[
                    "contract_row_id"
                ]
            )

            selected_contract_row_ids.add(
                selected_contract_row_id
            )

        row[
            "offseason_team_changed_flag"
        ] = bool(
            selected is not None
            and str(
                row[
                    "performance_team_2025_26"
                ]
            )
            != str(
                row[
                    "current_team_2026_27"
                ]
            )
        )

        output_rows.append(row)

        audit_rows.append(
            {
                "player_id": player[
                    "player_id"
                ],
                "player_name": player[
                    "player_name"
                ],
                "normalized_player_name": (
                    normalized_name
                ),
                "performance_team_2025_26": (
                    player[
                        "performance_team_2025_26"
                    ]
                ),
                "candidate_contract_row_count": (
                    len(candidates)
                ),
                "contract_match_status": status,
                "selected_contract_row_id": (
                    selected_contract_row_id
                ),
                "selected_contract_name": (
                    selected[
                        "contract_player_name"
                    ]
                    if selected is not None
                    else pd.NA
                ),
                "selected_contract_team": (
                    selected[
                        "contract_team_2026_27"
                    ]
                    if selected is not None
                    else pd.NA
                ),
                "selected_salary_2026_27": (
                    selected[
                        "salary_2026_27"
                    ]
                    if selected is not None
                    else np.nan
                ),
            }
        )

    financial = pd.DataFrame(
        output_rows
    )

    match_audit = pd.DataFrame(
        audit_rows
    )

    unselected_contracts = contracts.loc[
        ~contracts[
            "contract_row_id"
        ].isin(
            selected_contract_row_ids
        )
    ].copy()

    return (
        financial,
        match_audit,
        unselected_contracts,
    )


def add_value_metrics(
    financial: pd.DataFrame,
) -> pd.DataFrame:
    output = financial.copy()

    salary = pd.to_numeric(
        output[
            "trade_salary_2026_27"
        ],
        errors="coerce",
    )

    expected = pd.to_numeric(
        output[
            "projected_expected_contribution"
        ],
        errors="coerce",
    )

    downside = pd.to_numeric(
        output[
            "survival_weighted_active_downside_score"
        ],
        errors="coerce",
    )

    output[
        "projected_contribution_per_trade_salary_million"
    ] = np.where(
        salary > 0,
        expected
        / (
            salary
            / 1_000_000.0
        ),
        np.nan,
    )

    output[
        "downside_contribution_per_trade_salary_million"
    ] = np.where(
        salary > 0,
        downside
        / (
            salary
            / 1_000_000.0
        ),
        np.nan,
    )

    matched = salary.notna()

    output[
        "salary_percentile_2026_27"
    ] = np.nan

    output[
        "expected_contribution_percentile"
    ] = np.nan

    output[
        "survival_weighted_downside_percentile"
    ] = np.nan

    if matched.any():
        output.loc[
            matched,
            "salary_percentile_2026_27",
        ] = (
            salary.loc[matched]
            .rank(
                method="average",
                pct=True,
            )
            * 100.0
        )

        output.loc[
            matched,
            "expected_contribution_percentile",
        ] = (
            expected.loc[matched]
            .rank(
                method="average",
                pct=True,
            )
            * 100.0
        )

        output.loc[
            matched,
            "survival_weighted_downside_percentile",
        ] = (
            downside.loc[matched]
            .rank(
                method="average",
                pct=True,
            )
            * 100.0
        )

    output[
        "projected_contract_value_score"
    ] = (
        output[
            "expected_contribution_percentile"
        ]
        - output[
            "salary_percentile_2026_27"
        ]
    )

    output[
        "downside_contract_value_score"
    ] = (
        output[
            "survival_weighted_downside_percentile"
        ]
        - output[
            "salary_percentile_2026_27"
        ]
    )

    output[
        "trade_salary_scope_note"
    ] = (
        "Selected active-contract salary row used for "
        "trade matching. Multi-team obligations are kept "
        "separately and may represent dead money, retained "
        "salary, stretch amounts, or another team charge."
    )

    return output


def classify_salary_proxy(
    salary: float,
) -> str:
    if salary > SECOND_APRON_2026_27:
        return "above_second_apron_proxy"

    if salary > FIRST_APRON_2026_27:
        return "between_aprons_proxy"

    if salary > LUXURY_TAX_2026_27:
        return "tax_to_first_apron_proxy"

    if salary > SALARY_CAP_2026_27:
        return "over_cap_below_tax_proxy"

    return "below_cap_proxy"


def build_team_summary(
    financial: pd.DataFrame,
    contracts: pd.DataFrame,
) -> pd.DataFrame:
    selected = financial.loc[
        financial[
            "under_contract_2026_27"
        ].fillna(False)
        & financial[
            "current_team_2026_27"
        ].notna()
    ].copy()

    active_summary = (
        selected.groupby(
            "current_team_2026_27",
            as_index=False,
        )
        .agg(
            projected_active_contract_players=(
                "player_id",
                "size",
            ),
            selected_trade_salary_proxy=(
                "trade_salary_2026_27",
                "sum",
            ),
            projected_expected_contribution=(
                "projected_expected_contribution",
                "sum",
            ),
            survival_weighted_active_downside=(
                "survival_weighted_active_downside_score",
                "sum",
            ),
            average_contract_value_score=(
                "projected_contract_value_score",
                "mean",
            ),
        )
        .rename(
            columns={
                "current_team_2026_27": (
                    "team_abbreviation"
                )
            }
        )
    )

    obligation_summary = (
        contracts.groupby(
            "contract_team_2026_27",
            as_index=False,
        )
        .agg(
            listed_salary_obligation_rows=(
                "contract_row_id",
                "size",
            ),
            listed_salary_obligation_proxy=(
                "salary_2026_27",
                "sum",
            ),
        )
        .rename(
            columns={
                "contract_team_2026_27": (
                    "team_abbreviation"
                )
            }
        )
    )

    teams = sorted(
        set(
            active_summary[
                "team_abbreviation"
            ]
        )
        | set(
            obligation_summary[
                "team_abbreviation"
            ]
        )
    )

    summary = pd.DataFrame(
        {
            "team_abbreviation": teams,
        }
    )

    summary = (
        summary.merge(
            active_summary,
            how="left",
            on="team_abbreviation",
            validate="one_to_one",
        )
        .merge(
            obligation_summary,
            how="left",
            on="team_abbreviation",
            validate="one_to_one",
        )
    )

    numeric_columns = [
        "projected_active_contract_players",
        "selected_trade_salary_proxy",
        "projected_expected_contribution",
        "survival_weighted_active_downside",
        "average_contract_value_score",
        "listed_salary_obligation_rows",
        "listed_salary_obligation_proxy",
    ]

    for column in numeric_columns:
        summary[column] = pd.to_numeric(
            summary[column],
            errors="coerce",
        ).fillna(0.0)

    summary[
        "listed_obligations_minus_selected_trade_salary"
    ] = (
        summary[
            "listed_salary_obligation_proxy"
        ]
        - summary[
            "selected_trade_salary_proxy"
        ]
    )

    summary[
        "listed_salary_obligation_proxy_tier"
    ] = summary[
        "listed_salary_obligation_proxy"
    ].map(
        classify_salary_proxy
    )

    summary[
        "payroll_scope_note"
    ] = (
        "Basketball-Reference listed salary obligations "
        "are a payroll proxy, not official Apron Team Salary."
    )

    return summary.sort_values(
        "listed_salary_obligation_proxy",
        ascending=False,
    ).reset_index(drop=True)


def json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): json_safe(item)
            for key, item in value.items()
        }

    if isinstance(value, (list, tuple)):
        return [
            json_safe(item)
            for item in value
        ]

    if isinstance(value, np.integer):
        return int(value)

    if isinstance(value, np.floating):
        if np.isnan(value):
            return None
        return float(value)

    if isinstance(value, float):
        if math.isnan(value):
            return None
        return value

    if isinstance(value, pd.Timestamp):
        return value.isoformat()

    if pd.isna(value):
        return None

    return value


def format_money(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""

    return f"${float(value):,.0f}"


def main() -> None:
    RAW_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    PROCESSED_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    OUTPUT_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    print("=" * 80)
    print("CONTRACT AND FINANCIAL LAYER V2")
    print("=" * 80)
    print(f"Script version: {SCRIPT_VERSION}")
    print()

    contracts = load_raw_contracts()
    board = load_projection_board()

    (
        financial,
        match_audit,
        unselected_contracts,
    ) = merge_board_and_contracts(
        board=board,
        contracts=contracts,
    )

    financial = add_value_metrics(
        financial
    )

    team_summary = build_team_summary(
        financial=financial,
        contracts=contracts,
    )

    matched_mask = financial[
        "under_contract_2026_27"
    ].fillna(False).astype(bool)

    main_pool_mask = financial[
        "main_pool_eligible"
    ].fillna(False).astype(bool)

    unmatched_board = financial.loc[
        ~matched_mask
    ].copy()

    contract_only = unselected_contracts.copy()

    multi_team_obligations = (
        contracts.loc[
            contracts[
                "multi_team_salary_obligation_flag"
            ].fillna(False)
        ]
        .sort_values(
            [
                "normalized_player_name",
                "contract_team_2026_27",
            ]
        )
        .reset_index(drop=True)
    )

    total_listed_salary = float(
        contracts[
            "salary_2026_27"
        ].fillna(0.0).sum()
    )

    selected_trade_salary = float(
        financial[
            "trade_salary_2026_27"
        ].fillna(0.0).sum()
    )

    contract_name_set = set(
        contracts[
            "normalized_player_name"
        ].dropna()
    )

    represented_contract_salary = float(
        contracts.loc[
            contracts[
                "normalized_player_name"
            ].isin(
                set(
                    financial.loc[
                        matched_mask,
                        "normalized_player_name",
                    ]
                )
            ),
            "salary_2026_27",
        ]
        .fillna(0.0)
        .sum()
    )

    metadata = {
        "script_version": SCRIPT_VERSION,
        "created_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "raw_contract_rows_before_exact_deduplication": (
            int(
                pd.read_parquet(
                    RAW_CONTRACTS_PATH
                ).shape[0]
            )
        ),
        "clean_contract_rows": len(
            contracts
        ),
        "unicode_repaired_contract_rows": int(
            contracts[
                "unicode_repair_applied"
            ].sum()
        ),
        "projection_board_rows": len(
            financial
        ),
        "matched_projection_board_players": int(
            matched_mask.sum()
        ),
        "overall_player_match_rate": float(
            matched_mask.mean()
        ),
        "main_pool_players": int(
            main_pool_mask.sum()
        ),
        "main_pool_matched_players": int(
            (
                main_pool_mask
                & matched_mask
            ).sum()
        ),
        "main_pool_match_rate": float(
            (
                main_pool_mask
                & matched_mask
            ).sum()
            / main_pool_mask.sum()
        ),
        "multi_team_salary_obligation_rows": int(
            len(
                multi_team_obligations
            )
        ),
        "unresolved_multi_team_board_players": int(
            financial[
                "contract_match_status"
            ].eq(
                "unresolved_multi_team_salary_obligation"
            ).sum()
        ),
        "total_listed_salary_obligation_proxy": (
            total_listed_salary
        ),
        "selected_trade_salary_proxy": (
            selected_trade_salary
        ),
        "salary_obligation_share_with_player_projection": (
            represented_contract_salary
            / total_listed_salary
            if total_listed_salary
            else None
        ),
        "contract_normalized_names": len(
            contract_name_set
        ),
        "limitations": [
            (
                "Selected trade salary is inferred from the "
                "unique contract row or the row matching the "
                "player's 2025-26 performance team."
            ),
            (
                "A multi-team obligation that cannot be resolved "
                "from the 2025-26 team remains unmatched."
            ),
            (
                "Listed salary obligations are not official "
                "Apron Team Salary."
            ),
            (
                "Players without 2025-26 NBA statistics cannot "
                "receive a projection from the current model."
            ),
        ],
    }

    contracts.to_parquet(
        CLEAN_CONTRACTS_PARQUET_PATH,
        index=False,
    )

    contracts.to_csv(
        CLEAN_CONTRACTS_CSV_PATH,
        index=False,
    )

    financial.to_parquet(
        FINANCIAL_LAYER_PARQUET_PATH,
        index=False,
    )

    financial.to_csv(
        FINANCIAL_LAYER_CSV_PATH,
        index=False,
    )

    team_summary.to_csv(
        TEAM_SUMMARY_PATH,
        index=False,
    )

    unmatched_board.to_csv(
        UNMATCHED_BOARD_PATH,
        index=False,
    )

    contract_only.to_csv(
        CONTRACT_ONLY_PATH,
        index=False,
    )

    multi_team_obligations.to_csv(
        MULTI_TEAM_OBLIGATIONS_PATH,
        index=False,
    )

    match_audit.to_csv(
        MATCH_AUDIT_PATH,
        index=False,
    )

    with METADATA_PATH.open(
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            json_safe(metadata),
            file,
            indent=2,
            ensure_ascii=False,
        )

    print("=" * 80)
    print("FINANCIAL LAYER V2 CREATED")
    print("=" * 80)
    print(
        "Raw contract rows: "
        f"{metadata['raw_contract_rows_before_exact_deduplication']:,}"
    )
    print(
        "Clean contract rows: "
        f"{metadata['clean_contract_rows']:,}"
    )
    print(
        "Unicode-repaired rows: "
        f"{metadata['unicode_repaired_contract_rows']:,}"
    )
    print(
        "Matched projection-board players: "
        f"{metadata['matched_projection_board_players']:,}"
    )
    print(
        "Overall player match rate: "
        f"{metadata['overall_player_match_rate']:.2%}"
    )
    print(
        "Main-pool match rate: "
        f"{metadata['main_pool_match_rate']:.2%}"
    )
    print(
        "Salary-obligation share represented by projections: "
        f"{metadata['salary_obligation_share_with_player_projection']:.2%}"
    )
    print(
        "Multi-team salary-obligation rows: "
        f"{metadata['multi_team_salary_obligation_rows']:,}"
    )
    print(
        "Unresolved multi-team board players: "
        f"{metadata['unresolved_multi_team_board_players']:,}"
    )
    print()

    print("MATCH STATUS COUNTS")
    print(
        financial[
            "contract_match_status"
        ]
        .value_counts(
            dropna=False
        )
        .to_string()
    )
    print()

    print("CHECKED STAR MATCHES")
    star_names = [
        "Nikola Jokić",
        "Luka Dončić",
        "Alperen Sengun",
        "Kristaps Porziņģis",
        "Nikola Jović",
        "Dennis Schröder",
        "Jusuf Nurkić",
        "Egor Dëmin",
        "Vít Krejčí",
        "Tidjane Salaün",
        "Karlo Matković",
        "Ronald Holland II",
        "Damian Lillard",
        "Bradley Beal",
    ]

    star_check = financial.loc[
        financial[
            "player_name"
        ].isin(
            star_names
        ),
        [
            "player_name",
            "performance_team_2025_26",
            "current_team_2026_27",
            "trade_salary_2026_27",
            "contract_match_status",
        ],
    ].copy()

    star_check[
        "trade_salary_2026_27"
    ] = star_check[
        "trade_salary_2026_27"
    ].map(
        format_money
    )

    print(
        star_check.to_string(
            index=False,
        )
    )
    print()

    print("TOP UNMATCHED MAIN-POOL PLAYERS")
    unmatched_display = (
        unmatched_board.loc[
            unmatched_board[
                "main_pool_eligible"
            ].fillna(False).astype(bool),
            [
                "player_name",
                "performance_team_2025_26",
                "projected_expected_contribution",
                "contract_match_status",
            ],
        ]
        .sort_values(
            "projected_expected_contribution",
            ascending=False,
        )
        .head(30)
        .copy()
    )

    unmatched_display[
        "projected_expected_contribution"
    ] = pd.to_numeric(
        unmatched_display[
            "projected_expected_contribution"
        ],
        errors="coerce",
    ).round(3)

    print(
        unmatched_display.to_string(
            index=False,
        )
    )
    print()

    print("SAVED FILES")
    print(CLEAN_CONTRACTS_PARQUET_PATH)
    print(CLEAN_CONTRACTS_CSV_PATH)
    print(FINANCIAL_LAYER_PARQUET_PATH)
    print(FINANCIAL_LAYER_CSV_PATH)
    print(TEAM_SUMMARY_PATH)
    print(UNMATCHED_BOARD_PATH)
    print(CONTRACT_ONLY_PATH)
    print(MULTI_TEAM_OBLIGATIONS_PATH)
    print(MATCH_AUDIT_PATH)
    print(METADATA_PATH)


if __name__ == "__main__":
    main()