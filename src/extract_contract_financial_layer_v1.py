from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import requests


SCRIPT_VERSION = "contract-financial-layer-v1-2026-08-03"

PROJECT_ROOT = Path(__file__).resolve().parents[1]

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

OUTPUT_DIRECTORY = PROJECT_ROOT / "outputs"

RAW_HTML_PATH = (
    RAW_DIRECTORY
    / "basketball_reference_player_contracts_2026_27.html"
)

RAW_CONTRACTS_PARQUET_PATH = (
    RAW_DIRECTORY
    / "basketball_reference_player_contracts_2026_27.parquet"
)

RAW_CONTRACTS_CSV_PATH = (
    RAW_DIRECTORY
    / "basketball_reference_player_contracts_2026_27.csv"
)

FINANCIAL_LAYER_PARQUET_PATH = (
    PROCESSED_DIRECTORY
    / "player_financial_layer_2026_27.parquet"
)

FINANCIAL_LAYER_CSV_PATH = (
    PROCESSED_DIRECTORY
    / "player_financial_layer_2026_27.csv"
)

TEAM_SUMMARY_PATH = (
    OUTPUT_DIRECTORY
    / "player_financial_layer_team_summary_2026_27.csv"
)

UNMATCHED_PATH = (
    OUTPUT_DIRECTORY
    / "player_financial_layer_unmatched_2026_27.csv"
)

AMBIGUOUS_PATH = (
    OUTPUT_DIRECTORY
    / "player_financial_layer_ambiguous_names_2026_27.csv"
)

METADATA_PATH = (
    OUTPUT_DIRECTORY
    / "player_financial_layer_metadata_2026_27.json"
)

CONTRACTS_URL = (
    "https://www.basketball-reference.com/contracts/players.html"
)

SOURCE_LABEL = "Basketball-Reference player contracts"

SALARY_CAP_2026_27 = 164_961_000
MINIMUM_TEAM_SALARY_2026_27 = 148_465_000
LUXURY_TAX_2026_27 = 200_428_000
FIRST_APRON_2026_27 = 209_015_000
SECOND_APRON_2026_27 = 221_686_000

CONTRACT_SEASONS = [
    "2026-27",
    "2027-28",
    "2028-29",
    "2029-30",
    "2030-31",
    "2031-32",
]

BREF_TEAM_TO_NBA = {
    "BRK": "BKN",
    "CHO": "CHA",
    "PHO": "PHX",
}

# Only use explicit aliases that are highly likely to refer to the same player.
# The script never performs an automatic fuzzy merge.
NAME_ALIASES = {
    "aj green": "a j green",
    "aj lawson": "a j lawson",
    "cj mccollum": "c j mccollum",
    "dj carton's": "d j carton",
    "dj carton": "d j carton",
    "gg jackson": "g g jackson",
    "kj martin": "k j martin",
    "pj tucker": "p j tucker",
    "pj washington": "p j washington",
    "rj barrett": "r j barrett",
    "tj mcconnell": "t j mcconnell",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Download 2026-27 NBA player contracts and merge "
            "them into the current projection board."
        )
    )

    parser.add_argument(
        "--html-file",
        type=Path,
        default=None,
        help=(
            "Optional saved Basketball-Reference HTML file. "
            "When supplied, the script parses this file instead "
            "of downloading the page."
        ),
    )

    parser.add_argument(
        "--force-download",
        action="store_true",
        help=(
            "Download the contracts page again even when a saved "
            "raw HTML file already exists."
        ),
    )

    return parser.parse_args()


def normalize_text(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""

    text = str(value).strip()

    text = unicodedata.normalize(
        "NFKD",
        text,
    )

    text = "".join(
        character
        for character in text
        if not unicodedata.combining(character)
    )

    text = text.lower()

    text = text.replace("’", "'")
    text = text.replace("`", "'")

    text = re.sub(
        r"\b(jr|sr|ii|iii|iv)\b\.?",
        "",
        text,
    )

    text = re.sub(
        r"[^a-z0-9]+",
        " ",
        text,
    )

    text = re.sub(
        r"\s+",
        " ",
        text,
    ).strip()

    return NAME_ALIASES.get(
        text,
        text,
    )


def normalize_team(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""

    team = str(value).strip().upper()

    return BREF_TEAM_TO_NBA.get(
        team,
        team,
    )


def flatten_column(column: Any) -> str:
    if isinstance(column, tuple):
        parts = [
            str(part).strip()
            for part in column
            if str(part).strip()
            and not str(part).startswith("Unnamed")
        ]

        if parts:
            return parts[-1]

        return ""

    text = str(column).strip()

    if text.startswith("Unnamed"):
        return ""

    return text


def parse_money(value: Any) -> float:
    if value is None or pd.isna(value):
        return np.nan

    text = str(value).strip()

    if not text or text.lower() in {
        "nan",
        "none",
        "-",
        "—",
    }:
        return np.nan

    negative = text.startswith("(") and text.endswith(")")

    digits = re.sub(
        r"[^0-9.]",
        "",
        text,
    )

    if not digits:
        return np.nan

    amount = float(digits)

    if negative:
        amount *= -1.0

    return amount


def download_contract_html() -> str:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/150.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    }

    response = requests.get(
        CONTRACTS_URL,
        headers=headers,
        timeout=60,
    )

    if response.status_code != 200:
        raise RuntimeError(
            "Basketball-Reference returned HTTP "
            f"{response.status_code}. Wait before retrying or "
            "save the contracts page manually and run this "
            "script with --html-file."
        )

    html = response.text

    if "Player Contracts" not in html:
        raise RuntimeError(
            "The downloaded page did not look like the expected "
            "Basketball-Reference contracts page."
        )

    return html


def load_contract_html(
    html_file: Path | None,
    force_download: bool,
) -> tuple[str, str]:
    RAW_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    if html_file is not None:
        if not html_file.exists():
            raise FileNotFoundError(
                f"HTML file not found: {html_file}"
            )

        return (
            html_file.read_text(
                encoding="utf-8",
                errors="replace",
            ),
            str(html_file.resolve()),
        )

    if RAW_HTML_PATH.exists() and not force_download:
        return (
            RAW_HTML_PATH.read_text(
                encoding="utf-8",
                errors="replace",
            ),
            str(RAW_HTML_PATH),
        )

    html = download_contract_html()

    RAW_HTML_PATH.write_text(
        html,
        encoding="utf-8",
    )

    return html, CONTRACTS_URL


def identify_contract_table(
    tables: list[pd.DataFrame],
) -> pd.DataFrame:
    for table in tables:
        candidate = table.copy()

        candidate.columns = [
            flatten_column(column)
            for column in candidate.columns
        ]

        available = set(candidate.columns)

        if {
            "Player",
            "Tm",
            "2026-27",
            "Guaranteed",
        }.issubset(available):
            return candidate

    available_tables = [
        list(map(str, table.columns))
        for table in tables
    ]

    raise ValueError(
        "Could not identify the player contracts table. "
        f"Parsed table columns: {available_tables}"
    )


def parse_contract_table(
    html: str,
) -> pd.DataFrame:
    try:
        tables = pd.read_html(
            StringIO(html),
        )
    except ImportError as error:
        raise RuntimeError(
            "pandas could not parse HTML tables. Install lxml "
            "inside the nba-roster-optimizer environment."
        ) from error

    raw = identify_contract_table(
        tables
    )

    raw = raw.loc[
        raw["Player"].astype(str).ne("Player")
    ].copy()

    raw = raw.loc[
        raw["Player"].notna()
    ].copy()

    raw = raw.loc[
        raw["Player"].astype(str).str.strip().ne("")
    ].copy()

    rename_map = {
        "Rk": "contract_rank",
        "Player": "contract_player_name",
        "Tm": "contract_team_bref",
        "Guaranteed": "guaranteed_remaining",
    }

    for season in CONTRACT_SEASONS:
        rename_map[season] = (
            "salary_"
            + season.replace("-", "_")
        )

    contracts = raw.rename(
        columns=rename_map
    )

    selected_columns = [
        column
        for column in [
            "contract_rank",
            "contract_player_name",
            "contract_team_bref",
            *[
                "salary_"
                + season.replace("-", "_")
                for season in CONTRACT_SEASONS
            ],
            "guaranteed_remaining",
        ]
        if column in contracts.columns
    ]

    contracts = contracts[
        selected_columns
    ].copy()

    money_columns = [
        column
        for column in contracts.columns
        if column.startswith("salary_")
        or column == "guaranteed_remaining"
    ]

    for column in money_columns:
        contracts[column] = contracts[
            column
        ].map(parse_money)

    if "contract_rank" in contracts.columns:
        contracts["contract_rank"] = pd.to_numeric(
            contracts["contract_rank"],
            errors="coerce",
        ).astype("Int64")

    contracts["contract_team_2026_27"] = (
        contracts["contract_team_bref"]
        .map(normalize_team)
    )

    contracts["normalized_player_name"] = (
        contracts["contract_player_name"]
        .map(normalize_text)
    )

    current_salary_column = "salary_2026_27"

    contracts = contracts.loc[
        contracts[current_salary_column]
        .notna()
    ].copy()

    contracts["under_contract_2026_27"] = True

    contracts[
        "contract_years_remaining_including_2026_27"
    ] = (
        contracts[
            [
                "salary_"
                + season.replace("-", "_")
                for season in CONTRACT_SEASONS
            ]
        ]
        .notna()
        .sum(axis=1)
        .astype(int)
    )

    contracts["total_listed_future_salary"] = (
        contracts[
            [
                "salary_"
                + season.replace("-", "_")
                for season in CONTRACT_SEASONS
            ]
        ]
        .sum(
            axis=1,
            min_count=1,
        )
    )

    contracts[
        "future_salary_commitment_2027_28_plus"
    ] = (
        contracts[
            [
                "salary_"
                + season.replace("-", "_")
                for season in CONTRACT_SEASONS[1:]
            ]
        ]
        .sum(
            axis=1,
            min_count=1,
        )
        .fillna(0.0)
    )

    contracts["salary_cap_share_2026_27"] = (
        contracts[current_salary_column]
        / SALARY_CAP_2026_27
    )

    contracts[
        "option_type_2026_27"
    ] = "not_extracted_from_color_key"

    contracts[
        "guarantee_note"
    ] = (
        "Basketball-Reference guarantee total; "
        "individual season guarantee dates are not available "
        "in the parsed table."
    )

    contracts = contracts.sort_values(
        [
            current_salary_column,
            "contract_player_name",
        ],
        ascending=[
            False,
            True,
        ],
    ).reset_index(drop=True)

    duplicate_mask = contracts.duplicated(
        subset=["normalized_player_name"],
        keep=False,
    )

    contracts[
        "normalized_name_is_ambiguous"
    ] = duplicate_mask

    return contracts


def load_projection_board() -> pd.DataFrame:
    if not PROJECTION_BOARD_PATH.exists():
        raise FileNotFoundError(
            "Projection board not found at:\n"
            f"{PROJECTION_BOARD_PATH}"
        )

    board = pd.read_parquet(
        PROJECTION_BOARD_PATH
    )

    required = {
        "player_id",
        "player_name",
        "team_abbreviation",
        "main_pool_eligible",
        "projected_expected_contribution",
        "projected_survival_probability",
        "projected_active_downside_contribution_80",
        "projected_active_upside_contribution_80",
        "survival_weighted_active_downside_score",
    }

    missing = sorted(
        required.difference(board.columns)
    )

    if missing:
        raise ValueError(
            "Projection board is missing required columns:\n"
            + "\n".join(missing)
        )

    board = board.copy()

    if board["player_id"].duplicated().any():
        raise ValueError(
            "Projection board contains duplicate player IDs."
        )

    board = board.rename(
        columns={
            "team_abbreviation": (
                "performance_team_2025_26"
            )
        }
    )

    board["normalized_player_name"] = (
        board["player_name"]
        .map(normalize_text)
    )

    return board


def build_contract_lookup(
    contracts: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    ambiguous = contracts.loc[
        contracts[
            "normalized_name_is_ambiguous"
        ]
    ].copy()

    unique = contracts.loc[
        ~contracts[
            "normalized_name_is_ambiguous"
        ]
    ].copy()

    unique = unique.drop_duplicates(
        subset=["normalized_player_name"],
        keep="first",
    )

    return unique, ambiguous


def merge_financial_layer(
    board: pd.DataFrame,
    contracts: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    unique_contracts, ambiguous = (
        build_contract_lookup(
            contracts
        )
    )

    contract_columns = [
        column
        for column in unique_contracts.columns
        if column != "normalized_name_is_ambiguous"
    ]

    merged = board.merge(
        unique_contracts[
            contract_columns
        ],
        how="left",
        on="normalized_player_name",
        validate="many_to_one",
    )

    ambiguous_names = set(
        ambiguous[
            "normalized_player_name"
        ].dropna()
    )

    merged[
        "contract_match_status"
    ] = np.select(
        [
            merged["normalized_player_name"]
            .isin(ambiguous_names),
            merged["salary_2026_27"]
            .notna(),
        ],
        [
            "ambiguous_normalized_name",
            "matched_unique_normalized_name",
        ],
        default="unmatched_no_2026_27_contract",
    )

    matched_mask = merged[
        "contract_match_status"
    ].eq(
        "matched_unique_normalized_name"
    )

    merged["under_contract_2026_27"] = (
        matched_mask
    )

    merged[
        "current_team_2026_27"
    ] = np.where(
        matched_mask,
        merged["contract_team_2026_27"],
        pd.NA,
    )

    merged[
        "offseason_team_changed_flag"
    ] = (
        matched_mask
        & merged[
            "performance_team_2025_26"
        ].notna()
        & merged[
            "contract_team_2026_27"
        ].notna()
        & merged[
            "performance_team_2025_26"
        ].ne(
            merged[
                "contract_team_2026_27"
            ]
        )
    )

    merged[
        "trade_salary_2026_27"
    ] = merged["salary_2026_27"]

    salary = pd.to_numeric(
        merged["salary_2026_27"],
        errors="coerce",
    )

    expected = pd.to_numeric(
        merged[
            "projected_expected_contribution"
        ],
        errors="coerce",
    )

    downside = pd.to_numeric(
        merged[
            "survival_weighted_active_downside_score"
        ],
        errors="coerce",
    )

    merged[
        "projected_contribution_per_salary_million"
    ] = np.where(
        salary > 0,
        expected / (salary / 1_000_000),
        np.nan,
    )

    merged[
        "downside_contribution_per_salary_million"
    ] = np.where(
        salary > 0,
        downside / (salary / 1_000_000),
        np.nan,
    )

    contracted_mask = salary.notna()

    merged["salary_percentile_2026_27"] = np.nan
    merged[
        "expected_contribution_percentile"
    ] = np.nan
    merged[
        "survival_weighted_downside_percentile"
    ] = np.nan

    if contracted_mask.any():
        merged.loc[
            contracted_mask,
            "salary_percentile_2026_27",
        ] = (
            salary.loc[contracted_mask]
            .rank(
                method="average",
                pct=True,
            )
            * 100.0
        )

        merged.loc[
            contracted_mask,
            "expected_contribution_percentile",
        ] = (
            expected.loc[contracted_mask]
            .rank(
                method="average",
                pct=True,
            )
            * 100.0
        )

        merged.loc[
            contracted_mask,
            "survival_weighted_downside_percentile",
        ] = (
            downside.loc[contracted_mask]
            .rank(
                method="average",
                pct=True,
            )
            * 100.0
        )

    merged[
        "projected_contract_value_score"
    ] = (
        merged[
            "expected_contribution_percentile"
        ]
        - merged[
            "salary_percentile_2026_27"
        ]
    )

    merged[
        "downside_contract_value_score"
    ] = (
        merged[
            "survival_weighted_downside_percentile"
        ]
        - merged[
            "salary_percentile_2026_27"
        ]
    )

    merged[
        "salary_data_scope_note"
    ] = (
        "Listed player salary only. This is not a complete "
        "official Apron Team Salary calculation and excludes "
        "items such as dead money, cap holds, certain bonuses, "
        "and other team charges."
    )

    merged = merged.sort_values(
        [
            "under_contract_2026_27",
            "projected_contract_value_score",
            "projected_expected_contribution",
        ],
        ascending=[
            False,
            False,
            False,
        ],
        na_position="last",
    ).reset_index(drop=True)

    return merged, ambiguous


def classify_known_salary_proxy(
    known_salary: float,
) -> str:
    if known_salary > SECOND_APRON_2026_27:
        return "above_second_apron_proxy"

    if known_salary > FIRST_APRON_2026_27:
        return "between_aprons_proxy"

    if known_salary > LUXURY_TAX_2026_27:
        return "tax_to_first_apron_proxy"

    if known_salary > SALARY_CAP_2026_27:
        return "over_cap_below_tax_proxy"

    return "below_cap_proxy"


def build_team_summary(
    financial: pd.DataFrame,
) -> pd.DataFrame:
    contracted = financial.loc[
        financial[
            "under_contract_2026_27"
        ]
        & financial[
            "current_team_2026_27"
        ].notna()
    ].copy()

    summary = (
        contracted.groupby(
            "current_team_2026_27",
            as_index=False,
        )
        .agg(
            matched_contract_players=(
                "player_id",
                "size",
            ),
            known_player_salary_2026_27=(
                "salary_2026_27",
                "sum",
            ),
            known_guaranteed_remaining=(
                "guaranteed_remaining",
                "sum",
            ),
            known_future_salary_2027_28_plus=(
                "future_salary_commitment_2027_28_plus",
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
            main_pool_contract_players=(
                "main_pool_eligible",
                "sum",
            ),
        )
    )

    summary[
        "known_salary_vs_cap"
    ] = (
        summary["known_player_salary_2026_27"]
        - SALARY_CAP_2026_27
    )

    summary[
        "known_salary_vs_tax"
    ] = (
        summary["known_player_salary_2026_27"]
        - LUXURY_TAX_2026_27
    )

    summary[
        "known_salary_vs_first_apron"
    ] = (
        summary["known_player_salary_2026_27"]
        - FIRST_APRON_2026_27
    )

    summary[
        "known_salary_vs_second_apron"
    ] = (
        summary["known_player_salary_2026_27"]
        - SECOND_APRON_2026_27
    )

    summary[
        "known_salary_proxy_tier"
    ] = summary[
        "known_player_salary_2026_27"
    ].map(
        classify_known_salary_proxy
    )

    summary[
        "payroll_scope"
    ] = (
        "known player contracts only; not official Apron Team Salary"
    )

    return summary.sort_values(
        "known_player_salary_2026_27",
        ascending=False,
    ).reset_index(drop=True)


def make_json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): make_json_safe(item)
            for key, item in value.items()
        }

    if isinstance(value, (list, tuple)):
        return [
            make_json_safe(item)
            for item in value
        ]

    if isinstance(value, (np.integer,)):
        return int(value)

    if isinstance(value, (np.floating,)):
        if np.isnan(value):
            return None
        return float(value)

    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()

    if pd.isna(value):
        return None

    return value


def save_outputs(
    contracts: pd.DataFrame,
    financial: pd.DataFrame,
    team_summary: pd.DataFrame,
    ambiguous: pd.DataFrame,
    source_location: str,
) -> dict[str, Any]:
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

    contracts.to_parquet(
        RAW_CONTRACTS_PARQUET_PATH,
        index=False,
    )

    contracts.to_csv(
        RAW_CONTRACTS_CSV_PATH,
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

    unmatched = financial.loc[
        ~financial[
            "contract_match_status"
        ].eq(
            "matched_unique_normalized_name"
        ),
        [
            column
            for column in [
                "player_id",
                "player_name",
                "performance_team_2025_26",
                "main_pool_eligible",
                "projected_expected_contribution",
                "contract_match_status",
                "normalized_player_name",
            ]
            if column in financial.columns
        ],
    ].copy()

    unmatched.to_csv(
        UNMATCHED_PATH,
        index=False,
    )

    ambiguous.to_csv(
        AMBIGUOUS_PATH,
        index=False,
    )

    matched = financial[
        "under_contract_2026_27"
    ].fillna(False)

    main_pool = financial[
        "main_pool_eligible"
    ].fillna(False).astype(bool)

    metadata = {
        "script_version": SCRIPT_VERSION,
        "created_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "contract_source": SOURCE_LABEL,
        "contract_source_location": source_location,
        "contract_source_url": CONTRACTS_URL,
        "contract_source_note": (
            "Basketball-Reference states that salaries are "
            "updated monthly. Option colors are not yet "
            "reliably extracted in this v1 parser."
        ),
        "salary_cap_source": (
            "NBA official 2026-27 salary cap release"
        ),
        "salary_cap_2026_27": SALARY_CAP_2026_27,
        "minimum_team_salary_2026_27": (
            MINIMUM_TEAM_SALARY_2026_27
        ),
        "luxury_tax_2026_27": LUXURY_TAX_2026_27,
        "first_apron_2026_27": FIRST_APRON_2026_27,
        "second_apron_2026_27": SECOND_APRON_2026_27,
        "contract_rows": len(contracts),
        "projection_board_rows": len(financial),
        "matched_players": int(matched.sum()),
        "unmatched_or_ambiguous_players": int(
            (~matched).sum()
        ),
        "overall_match_rate": float(
            matched.mean()
        ),
        "main_pool_players": int(
            main_pool.sum()
        ),
        "main_pool_matched_players": int(
            (main_pool & matched).sum()
        ),
        "main_pool_match_rate": float(
            (
                (main_pool & matched).sum()
                / main_pool.sum()
            )
            if main_pool.sum()
            else np.nan
        ),
        "offseason_team_changes_detected": int(
            financial[
                "offseason_team_changed_flag"
            ].fillna(False).sum()
        ),
        "ambiguous_contract_name_rows": len(
            ambiguous
        ),
        "limitations": [
            (
                "The player contract table does not equal "
                "official Team Salary or Apron Team Salary."
            ),
            (
                "Dead money, cap holds, incomplete-roster "
                "charges, bonuses, exceptions, and certain "
                "other accounting items are not captured."
            ),
            (
                "Option type and individual guarantee dates "
                "are not reliably extracted in v1."
            ),
            (
                "Unmatched players may be free agents, "
                "two-way players, unsigned players, or "
                "name-matching exceptions."
            ),
        ],
        "output_files": {
            "raw_contracts_parquet": str(
                RAW_CONTRACTS_PARQUET_PATH
            ),
            "financial_layer_parquet": str(
                FINANCIAL_LAYER_PARQUET_PATH
            ),
            "team_summary": str(
                TEAM_SUMMARY_PATH
            ),
            "unmatched": str(
                UNMATCHED_PATH
            ),
            "ambiguous": str(
                AMBIGUOUS_PATH
            ),
        },
    }

    with METADATA_PATH.open(
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            make_json_safe(metadata),
            file,
            indent=2,
        )

    return metadata


def print_money(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""

    return f"${float(value):,.0f}"


def main() -> None:
    args = parse_args()

    print("=" * 80)
    print("NBA CONTRACT AND FINANCIAL LAYER")
    print("=" * 80)
    print(f"Script version: {SCRIPT_VERSION}")
    print(f"Projection board: {PROJECTION_BOARD_PATH}")
    print(f"Contracts URL: {CONTRACTS_URL}")
    print()

    html, source_location = load_contract_html(
        html_file=args.html_file,
        force_download=args.force_download,
    )

    contracts = parse_contract_table(
        html
    )

    board = load_projection_board()

    financial, ambiguous = (
        merge_financial_layer(
            board=board,
            contracts=contracts,
        )
    )

    team_summary = build_team_summary(
        financial
    )

    metadata = save_outputs(
        contracts=contracts,
        financial=financial,
        team_summary=team_summary,
        ambiguous=ambiguous,
        source_location=source_location,
    )

    print("=" * 80)
    print("FINANCIAL LAYER CREATED")
    print("=" * 80)
    print(
        f"Contract rows: "
        f"{metadata['contract_rows']:,}"
    )
    print(
        f"Projection-board players: "
        f"{metadata['projection_board_rows']:,}"
    )
    print(
        f"Matched players: "
        f"{metadata['matched_players']:,}"
    )
    print(
        "Overall match rate: "
        f"{metadata['overall_match_rate']:.2%}"
    )
    print(
        f"Main optimizer pool: "
        f"{metadata['main_pool_players']:,}"
    )
    print(
        "Main-pool match rate: "
        f"{metadata['main_pool_match_rate']:.2%}"
    )
    print(
        "Offseason team changes detected: "
        f"{metadata['offseason_team_changes_detected']:,}"
    )
    print(
        "Ambiguous normalized contract rows: "
        f"{metadata['ambiguous_contract_name_rows']:,}"
    )
    print()

    matched_main = financial.loc[
        financial[
            "under_contract_2026_27"
        ]
        & financial[
            "main_pool_eligible"
        ].fillna(False)
    ].copy()

    display_columns = [
        "player_name",
        "performance_team_2025_26",
        "current_team_2026_27",
        "salary_2026_27",
        "contract_years_remaining_including_2026_27",
        "projected_expected_contribution",
        "projected_contract_value_score",
        "downside_contract_value_score",
    ]

    print("TOP 20 PROJECTED CONTRACT VALUES")
    if matched_main.empty:
        print("No matched main-pool contracts.")
    else:
        display = matched_main.sort_values(
            [
                "projected_contract_value_score",
                "projected_expected_contribution",
            ],
            ascending=[
                False,
                False,
            ],
        ).head(20)[display_columns].copy()

        display["salary_2026_27"] = (
            display["salary_2026_27"]
            .map(print_money)
        )

        numeric_display = [
            "projected_expected_contribution",
            "projected_contract_value_score",
            "downside_contract_value_score",
        ]

        display[numeric_display] = (
            display[numeric_display]
            .round(3)
        )

        print(
            display.to_string(
                index=False,
            )
        )

    print()
    print("KNOWN PLAYER-SALARY PROXY BY TEAM")
    team_display = team_summary[
        [
            "current_team_2026_27",
            "matched_contract_players",
            "known_player_salary_2026_27",
            "known_salary_proxy_tier",
        ]
    ].copy()

    team_display[
        "known_player_salary_2026_27"
    ] = (
        team_display[
            "known_player_salary_2026_27"
        ].map(print_money)
    )

    print(
        team_display.to_string(
            index=False,
        )
    )

    print()
    print("IMPORTANT SCOPE NOTE")
    print(
        "Known player salary is a payroll proxy, not an "
        "official Team Salary or Apron Team Salary calculation."
    )

    print()
    print("SAVED FILES")
    print(RAW_CONTRACTS_PARQUET_PATH)
    print(RAW_CONTRACTS_CSV_PATH)
    print(FINANCIAL_LAYER_PARQUET_PATH)
    print(FINANCIAL_LAYER_CSV_PATH)
    print(TEAM_SUMMARY_PATH)
    print(UNMATCHED_PATH)
    print(AMBIGUOUS_PATH)
    print(METADATA_PATH)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print()
        print("=" * 80)
        print("FINANCIAL LAYER FAILED")
        print("=" * 80)
        print(f"{type(error).__name__}: {error}")
        sys.exit(1)