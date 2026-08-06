from __future__ import annotations

import hashlib
import json
import math
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


SCRIPT_VERSION = "future-pick-dependency-graph-v1-context-year-fix-2026-08-04"

PROJECT_ROOT = Path(__file__).resolve().parents[1]

CLAIMS_PATH = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "future_pick_obligation_claims_2027_2029_v2.parquet"
)

VALUATIONS_PATH = (
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

CLAIM_NODES_PARQUET_PATH = (
    PROCESSED_DIRECTORY
    / "future_pick_dependency_claim_nodes_2027_2029_v1.parquet"
)

CLAIM_NODES_CSV_PATH = (
    PROCESSED_DIRECTORY
    / "future_pick_dependency_claim_nodes_2027_2029_v1.csv"
)

DEPENDENCY_EDGES_PARQUET_PATH = (
    PROCESSED_DIRECTORY
    / "future_pick_dependency_edges_2027_2029_v1.parquet"
)

DEPENDENCY_EDGES_CSV_PATH = (
    PROCESSED_DIRECTORY
    / "future_pick_dependency_edges_2027_2029_v1.csv"
)

GROUP_SUMMARY_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_dependency_groups_2027_2029_v1.csv"
)

FAVORABILITY_POOL_CANDIDATES_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_favorability_pool_candidates_2027_2029_v1.csv"
)

SWAP_CHAIN_CANDIDATES_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_swap_chain_candidates_2027_2029_v1.csv"
)

ROLLOVER_CANDIDATES_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_rollover_dependency_candidates_2027_2029_v1.csv"
)

MANUAL_REVIEW_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_dependency_manual_review_2027_2029_v1.csv"
)

METADATA_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_dependency_graph_metadata_v1.json"
)


MODELED_DRAFT_YEARS = {
    2027,
    2028,
    2029,
}

TEAM_ALIASES = {
    "atlanta hawks": "ATL",
    "atlanta": "ATL",
    "hawks": "ATL",
    "boston celtics": "BOS",
    "boston": "BOS",
    "celtics": "BOS",
    "brooklyn nets": "BKN",
    "brooklyn": "BKN",
    "nets": "BKN",
    "charlotte hornets": "CHA",
    "charlotte": "CHA",
    "hornets": "CHA",
    "chicago bulls": "CHI",
    "chicago": "CHI",
    "bulls": "CHI",
    "cleveland cavaliers": "CLE",
    "cleveland": "CLE",
    "cavaliers": "CLE",
    "cavs": "CLE",
    "dallas mavericks": "DAL",
    "dallas": "DAL",
    "mavericks": "DAL",
    "mavs": "DAL",
    "denver nuggets": "DEN",
    "denver": "DEN",
    "nuggets": "DEN",
    "detroit pistons": "DET",
    "detroit": "DET",
    "pistons": "DET",
    "golden state warriors": "GSW",
    "golden state": "GSW",
    "warriors": "GSW",
    "houston rockets": "HOU",
    "houston": "HOU",
    "rockets": "HOU",
    "indiana pacers": "IND",
    "indiana": "IND",
    "pacers": "IND",
    "los angeles clippers": "LAC",
    "la clippers": "LAC",
    "clippers": "LAC",
    "los angeles lakers": "LAL",
    "la lakers": "LAL",
    "lakers": "LAL",
    "memphis grizzlies": "MEM",
    "memphis": "MEM",
    "grizzlies": "MEM",
    "miami heat": "MIA",
    "miami": "MIA",
    "heat": "MIA",
    "milwaukee bucks": "MIL",
    "milwaukee": "MIL",
    "bucks": "MIL",
    "minnesota timberwolves": "MIN",
    "minnesota": "MIN",
    "timberwolves": "MIN",
    "wolves": "MIN",
    "new orleans pelicans": "NOP",
    "new orleans": "NOP",
    "pelicans": "NOP",
    "new york knicks": "NYK",
    "new york": "NYK",
    "knicks": "NYK",
    "oklahoma city thunder": "OKC",
    "oklahoma city": "OKC",
    "thunder": "OKC",
    "orlando magic": "ORL",
    "orlando": "ORL",
    "magic": "ORL",
    "philadelphia 76ers": "PHI",
    "philadelphia": "PHI",
    "76ers": "PHI",
    "sixers": "PHI",
    "phoenix suns": "PHX",
    "phoenix": "PHX",
    "suns": "PHX",
    "portland trail blazers": "POR",
    "portland": "POR",
    "trail blazers": "POR",
    "trailblazers": "POR",
    "blazers": "POR",
    "sacramento kings": "SAC",
    "sacramento": "SAC",
    "kings": "SAC",
    "san antonio spurs": "SAS",
    "san antonio": "SAS",
    "spurs": "SAS",
    "toronto raptors": "TOR",
    "toronto": "TOR",
    "raptors": "TOR",
    "utah jazz": "UTA",
    "utah": "UTA",
    "jazz": "UTA",
    "washington wizards": "WAS",
    "washington": "WAS",
    "wizards": "WAS",
}

TEAM_CODES = sorted(
    set(
        TEAM_ALIASES.values()
    )
)

FAVORABILITY_PATTERNS = [
    (
        "second_most_favorable",
        re.compile(
            r"\bsecond\s+most\s+favorable\b",
            re.IGNORECASE,
        ),
    ),
    (
        "second_least_favorable",
        re.compile(
            r"\bsecond\s+least\s+favorable\b",
            re.IGNORECASE,
        ),
    ),
    (
        "third_most_favorable",
        re.compile(
            r"\bthird\s+most\s+favorable\b",
            re.IGNORECASE,
        ),
    ),
    (
        "third_least_favorable",
        re.compile(
            r"\bthird\s+least\s+favorable\b",
            re.IGNORECASE,
        ),
    ),
    (
        "most_favorable",
        re.compile(
            r"\bmost\s+favorable\b",
            re.IGNORECASE,
        ),
    ),
    (
        "least_favorable",
        re.compile(
            r"\bleast\s+favorable\b",
            re.IGNORECASE,
        ),
    ),
    (
        "more_favorable",
        re.compile(
            r"\bmore\s+favorable\b",
            re.IGNORECASE,
        ),
    ),
    (
        "less_favorable",
        re.compile(
            r"\bless\s+favorable\b",
            re.IGNORECASE,
        ),
    ),
]

ROLLOVER_PHRASES = [
    "instead convey",
    "will convey",
    "shall convey",
    "unprotected in",
    "converts to",
    "becomes",
    "roll over",
    "rolls over",
    "deferred to",
    "obligation will be extinguished",
    "obligation is extinguished",
]

DEPENDENCY_STATUS_VALUES = {
    "requires_dependency_review",
    "valued_partial_rollover_component",
}


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
    fill_value: float | None = None,
) -> pd.Series:
    values = pd.to_numeric(
        frame[
            column
        ],
        errors="coerce",
    )

    if fill_value is not None:
        values = values.fillna(
            fill_value
        )

    return values.astype(
        float
    )


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
        values.astype(
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


def clean_text(
    value: Any,
) -> str:
    if value is None or pd.isna(
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


def normalize_search_text(
    value: Any,
) -> str:
    text = clean_text(
        value
    ).lower()

    text = re.sub(
        r"[^a-z0-9]+",
        " ",
        text,
    )

    return clean_text(
        text
    )


def unique_preserving_order(
    values: list[Any],
) -> list[Any]:
    output = []
    seen = set()

    for value in values:
        if value in seen:
            continue

        seen.add(
            value
        )

        output.append(
            value
        )

    return output


def teams_from_text(
    value: Any,
) -> list[str]:
    text = normalize_search_text(
        value
    )

    matches = []
    occupied_spans = []

    for alias in sorted(
        TEAM_ALIASES,
        key=len,
        reverse=True,
    ):
        for match in re.finditer(
            rf"\b{re.escape(alias)}\b",
            text,
        ):
            span = match.span()

            overlaps = any(
                not (
                    span[
                        1
                    ]
                    <= existing[
                        0
                    ]
                    or span[
                        0
                    ]
                    >= existing[
                        1
                    ]
                )
                for existing
                in occupied_spans
            )

            if overlaps:
                continue

            occupied_spans.append(
                span
            )

            matches.append(
                (
                    span[
                        0
                    ],
                    TEAM_ALIASES[
                        alias
                    ],
                )
            )

    matches.sort(
        key=lambda item: item[
            0
        ]
    )

    return unique_preserving_order(
        [
            team
            for _, team
            in matches
        ]
    )


def all_calendar_years_from_text(
    value: Any,
) -> list[int]:
    return unique_preserving_order(
        [
            int(
                match
            )
            for match in re.findall(
                r"\b(20[2-3]\d)\b",
                clean_text(
                    value
                ),
            )
        ]
    )


def remove_transaction_dates(
    value: Any,
) -> str:
    text = clean_text(
        value
    )

    # RealGM transaction descriptions include dates such as
    # 6/26/2025 and 2025-06-26. Those years describe when a trade
    # occurred, not a draft-pick dependency.
    text = re.sub(
        r"\b\d{1,2}/\d{1,2}/20\d{2}\b",
        " ",
        text,
    )

    text = re.sub(
        r"\b20\d{2}-\d{1,2}-\d{1,2}\b",
        " ",
        text,
    )

    text = re.sub(
        (
            r"\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|"
            r"May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|"
            r"Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
            r"\s+\d{1,2},?\s+20\d{2}\b"
        ),
        " ",
        text,
        flags=re.IGNORECASE,
    )

    return clean_text(
        text
    )


def years_from_text(
    value: Any,
) -> list[int]:
    text = remove_transaction_dates(
        value
    )

    contextual_patterns = [
        # "2028 first round draft pick"
        re.compile(
            (
                r"\b(20[2-3]\d)\s+"
                r"(?:first|second|1st|2nd)[\s-]+round"
                r"(?:\s+draft)?(?:\s+pick)?\b"
            ),
            re.IGNORECASE,
        ),
        # "2028 draft pick" or "2028 pick"
        re.compile(
            r"\b(20[2-3]\d)\s+(?:draft\s+)?pick\b",
            re.IGNORECASE,
        ),
        # "first-round pick in 2028"
        re.compile(
            (
                r"\b(?:first|second|1st|2nd)[\s-]+round"
                r"(?:\s+draft)?\s+pick"
                r"(?:\s+(?:in|for|of|from))?\s+(20[2-3]\d)\b"
            ),
            re.IGNORECASE,
        ),
        # "unprotected in 2028"
        re.compile(
            r"\bunprotected\s+in\s+(20[2-3]\d)\b",
            re.IGNORECASE,
        ),
        # Rollover and fallback clauses.
        re.compile(
            (
                r"\b(?:instead\s+convey|will\s+convey|shall\s+convey|"
                r"converts?\s+to|becomes?|deferred\s+to|"
                r"rolls?\s+over\s+to|fallback\s+in)"
                r"[^.;]{0,140}?\b(20[2-3]\d)\b"
            ),
            re.IGNORECASE,
        ),
        # "in 2028, a second-round pick"
        re.compile(
            (
                r"\bin\s+(20[2-3]\d)\b"
                r"[^.;]{0,80}?"
                r"\b(?:first|second|1st|2nd)[\s-]+round\b"
            ),
            re.IGNORECASE,
        ),
    ]

    years = []

    for pattern in contextual_patterns:
        years.extend(
            int(
                match
            )
            for match in pattern.findall(
                text
            )
        )

    return unique_preserving_order(
        years
    )


def rounds_from_text(
    value: Any,
    default_round: int,
) -> list[int]:
    text = clean_text(
        value
    ).lower()

    rounds = []

    if re.search(
        r"\bfirst[\s-]+round\b",
        text,
    ):
        rounds.append(
            1
        )

    if re.search(
        r"\bsecond[\s-]+round\b",
        text,
    ):
        rounds.append(
            2
        )

    if not rounds:
        rounds.append(
            int(
                default_round
            )
        )

    return unique_preserving_order(
        rounds
    )


def favorability_type(
    value: Any,
) -> str:
    text = clean_text(
        value
    )

    for label, pattern in (
        FAVORABILITY_PATTERNS
    ):
        if pattern.search(
            text
        ):
            return label

    return "none"


def has_rollover_language(
    value: Any,
) -> bool:
    lower = (
        " "
        + clean_text(
            value
        ).lower()
        + " "
    )

    return any(
        phrase in lower
        for phrase in ROLLOVER_PHRASES
    )


def structural_family(
    row: pd.Series,
) -> str:
    if bool(
        row[
            "favorability_pool_flag"
        ]
    ):
        return "favorability_pool"

    if bool(
        row[
            "swap_flag"
        ]
    ):
        return "swap_chain"

    if (
        bool(
            row[
                "rollover_language_detected"
            ]
        )
        or bool(
            row[
                "rollover_or_fallback_language_flag"
            ]
        )
    ):
        return "rollover_dependency"

    if bool(
        row[
            "protection_flag"
        ]
    ):
        return "protected_transfer"

    if bool(
        row[
            "conditional_language_flag"
        ]
    ):
        return "conditional_transfer"

    return "other_complex_claim"


def hash_identifier(
    prefix: str,
    values: list[str],
) -> str:
    digest = hashlib.sha1(
        "|".join(
            values
        ).encode(
            "utf-8"
        )
    ).hexdigest()[
        :12
    ]

    return (
        f"{prefix}_{digest}"
    )


class UnionFind:
    def __init__(
        self,
        items: list[str],
    ) -> None:
        self.parent = {
            item: item
            for item in items
        }

        self.rank = {
            item: 0
            for item in items
        }

    def find(
        self,
        item: str,
    ) -> str:
        parent = self.parent[
            item
        ]

        if parent != item:
            self.parent[
                item
            ] = self.find(
                parent
            )

        return self.parent[
            item
        ]

    def union(
        self,
        item_a: str,
        item_b: str,
    ) -> None:
        root_a = self.find(
            item_a
        )

        root_b = self.find(
            item_b
        )

        if root_a == root_b:
            return

        rank_a = self.rank[
            root_a
        ]

        rank_b = self.rank[
            root_b
        ]

        if rank_a < rank_b:
            self.parent[
                root_a
            ] = root_b
        elif rank_a > rank_b:
            self.parent[
                root_b
            ] = root_a
        else:
            self.parent[
                root_b
            ] = root_a

            self.rank[
                root_a
            ] += 1


def load_inputs() -> pd.DataFrame:
    for path in [
        CLAIMS_PATH,
        VALUATIONS_PATH,
    ]:
        if not path.exists():
            raise FileNotFoundError(
                "Required dependency input was not found:\n"
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

    require_columns(
        claims,
        [
            "claim_id",
            "asset_key",
            "draft_year",
            "round_number",
            "originating_team",
            "destination_team_sequence",
            "destination_team_count",
            "transaction_date_last_detected",
            "swap_flag",
            "favorability_pool_flag",
            "conditional_language_flag",
            "protection_flag",
            "rollover_or_fallback_language_flag",
            "multiple_claim_rows_flag",
            "pick_heading",
            "transaction_text",
            "full_obligation_text",
        ],
        "Future-pick claims",
    )

    require_columns(
        valuations,
        [
            "claim_id",
            "valuation_method",
            "valuation_status",
            "expected_total_candidate_asset_value_score",
            "automatic_exclusion_reason",
        ],
        "Future-pick claim valuations",
    )

    valuation_subset = valuations[
        [
            "claim_id",
            "valuation_method",
            "valuation_status",
            "expected_total_candidate_asset_value_score",
            "automatic_exclusion_reason",
        ]
    ].drop_duplicates(
        subset=[
            "claim_id"
        ]
    )

    merged = claims.merge(
        valuation_subset,
        how="left",
        on="claim_id",
        validate="one_to_one",
    )

    if merged[
        "valuation_status"
    ].isna().any():
        raise ValueError(
            "Some claims did not match the valuation output."
        )

    merged[
        "draft_year"
    ] = numeric_series(
        merged,
        "draft_year",
    ).round().astype(
        int
    )

    merged[
        "round_number"
    ] = numeric_series(
        merged,
        "round_number",
    ).round().astype(
        int
    )

    for column in [
        "destination_team_count",
        "expected_total_candidate_asset_value_score",
    ]:
        merged[
            column
        ] = numeric_series(
            merged,
            column,
        )

    for column in [
        "swap_flag",
        "favorability_pool_flag",
        "conditional_language_flag",
        "protection_flag",
        "rollover_or_fallback_language_flag",
        "multiple_claim_rows_flag",
    ]:
        merged[
            column
        ] = boolean_series(
            merged,
            column,
        )

    dependency_mask = (
        merged[
            "valuation_status"
        ].isin(
            DEPENDENCY_STATUS_VALUES
        )
    )

    output = merged.loc[
        dependency_mask
    ].copy()

    if output.empty:
        raise ValueError(
            "No claims require dependency processing."
        )

    return output.reset_index(
        drop=True
    )


def enrich_claim_nodes(
    claims: pd.DataFrame,
) -> pd.DataFrame:
    output = claims.copy()

    output[
        "full_claim_text"
    ] = (
        output[
            "pick_heading"
        ].fillna(
            ""
        ).astype(
            str
        )
        + " "
        + output[
            "transaction_text"
        ].fillna(
            ""
        ).astype(
            str
        )
        + " "
        + output[
            "full_obligation_text"
        ].fillna(
            ""
        ).astype(
            str
        )
    ).map(
        clean_text
    )

    parsed_teams = []

    parsed_years = []

    parsed_raw_calendar_years = []

    parsed_ignored_calendar_years = []

    parsed_rounds = []

    parsed_favorability = []

    parsed_rollover = []

    beneficiary_teams = []

    for row in output.itertuples(
        index=False
    ):
        text = row.full_claim_text

        teams = teams_from_text(
            text
        )

        teams = unique_preserving_order(
            [
                row.originating_team,
                *teams,
            ]
        )

        contextual_years = years_from_text(
            text
        )

        raw_calendar_years = (
            all_calendar_years_from_text(
                text
            )
        )

        years = unique_preserving_order(
            [
                int(
                    row.draft_year
                ),
                *contextual_years,
            ]
        )

        ignored_calendar_years = [
            year
            for year in raw_calendar_years
            if year not in years
        ]

        rounds = rounds_from_text(
            text,
            default_round=int(
                row.round_number
            ),
        )

        destination_teams = [
            token
            for token in re.split(
                r"[|,;/ ]+",
                clean_text(
                    row.destination_team_sequence
                ),
            )
            if token in TEAM_CODES
        ]

        parsed_teams.append(
            teams
        )

        parsed_years.append(
            years
        )

        parsed_raw_calendar_years.append(
            raw_calendar_years
        )

        parsed_ignored_calendar_years.append(
            ignored_calendar_years
        )

        parsed_rounds.append(
            rounds
        )

        parsed_favorability.append(
            favorability_type(
                text
            )
        )

        parsed_rollover.append(
            has_rollover_language(
                text
            )
        )

        beneficiary_teams.append(
            unique_preserving_order(
                destination_teams
            )
        )

    output[
        "mentioned_teams_list"
    ] = parsed_teams

    output[
        "mentioned_years_list"
    ] = parsed_years

    output[
        "raw_calendar_years_list"
    ] = parsed_raw_calendar_years

    output[
        "ignored_calendar_years_list"
    ] = parsed_ignored_calendar_years

    output[
        "mentioned_rounds_list"
    ] = parsed_rounds

    output[
        "favorability_type"
    ] = parsed_favorability

    output[
        "rollover_language_detected"
    ] = parsed_rollover

    output[
        "beneficiary_teams_list"
    ] = beneficiary_teams

    output[
        "mentioned_teams"
    ] = output[
        "mentioned_teams_list"
    ].map(
        lambda values: "|".join(
            values
        )
    )

    output[
        "mentioned_years"
    ] = output[
        "mentioned_years_list"
    ].map(
        lambda values: "|".join(
            str(
                value
            )
            for value in values
        )
    )

    output[
        "mentioned_rounds"
    ] = output[
        "mentioned_rounds_list"
    ].map(
        lambda values: "|".join(
            str(
                value
            )
            for value in values
        )
    )

    output[
        "beneficiary_teams"
    ] = output[
        "beneficiary_teams_list"
    ].map(
        lambda values: "|".join(
            values
        )
    )

    output[
        "structural_family"
    ] = output.apply(
        structural_family,
        axis=1,
    )

    output[
        "out_of_horizon_dependency_flag"
    ] = output[
        "mentioned_years_list"
    ].map(
        lambda values: any(
            year
            not in MODELED_DRAFT_YEARS
            for year in values
        )
    )

    output[
        "same_year_only_flag"
    ] = output[
        "mentioned_years_list"
    ].map(
        lambda values: len(
            set(
                values
            )
        )
        == 1
    )

    output[
        "same_round_only_flag"
    ] = output[
        "mentioned_rounds_list"
    ].map(
        lambda values: len(
            set(
                values
            )
        )
        == 1
    )

    output[
        "mentioned_team_count"
    ] = output[
        "mentioned_teams_list"
    ].map(
        len
    )

    output[
        "mentioned_year_count"
    ] = output[
        "mentioned_years_list"
    ].map(
        len
    )

    output[
        "beneficiary_team_count"
    ] = output[
        "beneficiary_teams_list"
    ].map(
        len
    )

    return output


def build_dependency_groups(
    nodes: pd.DataFrame,
) -> pd.DataFrame:
    claim_ids = nodes[
        "claim_id"
    ].astype(
        str
    ).tolist()

    union_find = UnionFind(
        claim_ids
    )

    records = {
        str(
            row.claim_id
        ): row
        for row in nodes.itertuples(
            index=False
        )
    }

    by_asset = defaultdict(
        list
    )

    for row in records.values():
        by_asset[
            row.asset_key
        ].append(
            row.claim_id
        )

    for grouped_ids in by_asset.values():
        for claim_id in grouped_ids[
            1:
        ]:
            union_find.union(
                grouped_ids[
                    0
                ],
                claim_id,
            )

    dated_claims = [
        row
        for row in records.values()
        if clean_text(
            row.transaction_date_last_detected
        )
    ]

    for index, row_a in enumerate(
        dated_claims
    ):
        teams_a = set(
            row_a.mentioned_teams_list
        )

        beneficiaries_a = set(
            row_a.beneficiary_teams_list
        )

        for row_b in dated_claims[
            index
            + 1:
        ]:
            if (
                row_a.transaction_date_last_detected
                != row_b.transaction_date_last_detected
            ):
                continue

            if (
                row_a.draft_year
                != row_b.draft_year
                or row_a.round_number
                != row_b.round_number
            ):
                continue

            if (
                row_a.structural_family
                != row_b.structural_family
            ):
                continue

            teams_b = set(
                row_b.mentioned_teams_list
            )

            beneficiaries_b = set(
                row_b.beneficiary_teams_list
            )

            shared_team = bool(
                teams_a
                & teams_b
            )

            same_beneficiary = bool(
                beneficiaries_a
                and beneficiaries_b
                and beneficiaries_a
                == beneficiaries_b
            )

            if (
                shared_team
                or same_beneficiary
            ):
                union_find.union(
                    row_a.claim_id,
                    row_b.claim_id,
                )

    root_to_claims = defaultdict(
        list
    )

    for claim_id in claim_ids:
        root_to_claims[
            union_find.find(
                claim_id
            )
        ].append(
            claim_id
        )

    claim_to_group = {}

    for grouped_claims in root_to_claims.values():
        group_id = hash_identifier(
            "OBL",
            sorted(
                grouped_claims
            ),
        )

        for claim_id in grouped_claims:
            claim_to_group[
                claim_id
            ] = group_id

    output = nodes.copy()

    output[
        "obligation_group_id"
    ] = output[
        "claim_id"
    ].map(
        claim_to_group
    )

    return output


def build_dependency_edges(
    nodes: pd.DataFrame,
) -> pd.DataFrame:
    rows = []

    existing_asset_keys = set(
        nodes[
            "asset_key"
        ].astype(
            str
        )
    )

    for row in nodes.itertuples(
        index=False
    ):
        rows.append(
            {
                "obligation_group_id": (
                    row.obligation_group_id
                ),
                "claim_id": (
                    row.claim_id
                ),
                "source_node_type": (
                    "claim"
                ),
                "source_node_id": (
                    row.claim_id
                ),
                "target_node_type": (
                    "origin_asset"
                ),
                "target_node_id": (
                    row.asset_key
                ),
                "edge_type": (
                    "claims_originating_asset"
                ),
                "edge_scope": (
                    "modeled"
                ),
            }
        )

        for team in row.mentioned_teams_list:
            for year in row.mentioned_years_list:
                for round_number in (
                    row.mentioned_rounds_list
                ):
                    asset_key = (
                        f"{year}_R"
                        f"{round_number}_"
                        f"{team}"
                    )

                    if (
                        asset_key
                        == row.asset_key
                    ):
                        continue

                    rows.append(
                        {
                            "obligation_group_id": (
                                row.obligation_group_id
                            ),
                            "claim_id": (
                                row.claim_id
                            ),
                            "source_node_type": (
                                "claim"
                            ),
                            "source_node_id": (
                                row.claim_id
                            ),
                            "target_node_type": (
                                "referenced_asset"
                            ),
                            "target_node_id": (
                                asset_key
                            ),
                            "edge_type": (
                                "references_pick_asset"
                            ),
                            "edge_scope": (
                                "modeled"
                                if year
                                in MODELED_DRAFT_YEARS
                                else "outside_modeled_horizon"
                            ),
                            "referenced_asset_exists_in_dependency_nodes": (
                                asset_key
                                in existing_asset_keys
                            ),
                        }
                    )

        for beneficiary in (
            row.beneficiary_teams_list
        ):
            rows.append(
                {
                    "obligation_group_id": (
                        row.obligation_group_id
                    ),
                    "claim_id": (
                        row.claim_id
                    ),
                    "source_node_type": (
                        "claim"
                    ),
                    "source_node_id": (
                        row.claim_id
                    ),
                    "target_node_type": (
                        "team"
                    ),
                    "target_node_id": (
                        beneficiary
                    ),
                    "edge_type": (
                        "candidate_beneficiary"
                    ),
                    "edge_scope": (
                        "modeled"
                    ),
                }
            )

    edges = pd.DataFrame(
        rows
    )

    if edges.empty:
        raise ValueError(
            "No dependency edges were created."
        )

    return edges.drop_duplicates().sort_values(
        [
            "obligation_group_id",
            "claim_id",
            "edge_type",
            "target_node_id",
        ]
    ).reset_index(
        drop=True
    )


def classify_group(
    group: pd.DataFrame,
) -> str:
    families = set(
        group[
            "structural_family"
        ].astype(
            str
        )
    )

    favorability_types = set(
        value
        for value in group[
            "favorability_type"
        ].astype(
            str
        )
        if value
        != "none"
    )

    all_years = set()

    all_rounds = set()

    all_teams = set()

    beneficiaries = set()

    for values in group[
        "mentioned_years_list"
    ]:
        all_years.update(
            values
        )

    for values in group[
        "mentioned_rounds_list"
    ]:
        all_rounds.update(
            values
        )

    for values in group[
        "mentioned_teams_list"
    ]:
        all_teams.update(
            values
        )

    for values in group[
        "beneficiary_teams_list"
    ]:
        beneficiaries.update(
            values
        )

    out_of_horizon = any(
        year
        not in MODELED_DRAFT_YEARS
        for year in all_years
    )

    has_rollover = bool(
        group[
            "rollover_language_detected"
        ].any()
        or group[
            "rollover_or_fallback_language_flag"
        ].any()
    )

    has_protection = bool(
        group[
            "protection_flag"
        ].any()
    )

    multiple_assets = (
        group[
            "asset_key"
        ].nunique()
        > 1
    )

    if out_of_horizon:
        return (
            "out_of_horizon_dependency"
        )

    if (
        "favorability_pool"
        in families
        and len(
            all_years
        )
        == 1
        and len(
            all_rounds
        )
        == 1
        and len(
            all_teams
        )
        >= 2
        and len(
            beneficiaries
        )
        == 1
        and len(
            favorability_types
        )
        == 1
        and not has_rollover
        and not has_protection
    ):
        return (
            "same_year_favorability_pool_candidate"
        )

    if (
        "swap_chain"
        in families
        and len(
            all_years
        )
        == 1
        and len(
            all_rounds
        )
        == 1
        and len(
            all_teams
        )
        >= 2
        and len(
            beneficiaries
        )
        >= 1
        and not has_rollover
        and not has_protection
    ):
        return (
            "same_year_swap_chain_candidate"
        )

    if (
        has_rollover
        and all(
            year
            in MODELED_DRAFT_YEARS
            for year in all_years
        )
    ):
        return (
            "linked_rollover_candidate"
        )

    if (
        "swap_chain"
        in families
        and has_protection
    ):
        return (
            "protected_swap_chain"
        )

    if multiple_assets:
        return (
            "overlapping_multi_asset_claim_group"
        )

    return (
        "manual_complex_text_review"
    )


def build_group_summary(
    nodes: pd.DataFrame,
) -> pd.DataFrame:
    rows = []

    for group_id, group in nodes.groupby(
        "obligation_group_id",
        sort=True,
    ):
        all_teams = sorted(
            set(
                team
                for values
                in group[
                    "mentioned_teams_list"
                ]
                for team
                in values
            )
        )

        all_years = sorted(
            set(
                year
                for values
                in group[
                    "mentioned_years_list"
                ]
                for year
                in values
            )
        )

        all_rounds = sorted(
            set(
                round_number
                for values
                in group[
                    "mentioned_rounds_list"
                ]
                for round_number
                in values
            )
        )

        beneficiaries = sorted(
            set(
                team
                for values
                in group[
                    "beneficiary_teams_list"
                ]
                for team
                in values
            )
        )

        favorability_types = sorted(
            set(
                value
                for value in group[
                    "favorability_type"
                ].astype(
                    str
                )
                if value
                != "none"
            )
        )

        transaction_dates = sorted(
            set(
                clean_text(
                    value
                )
                for value in group[
                    "transaction_date_last_detected"
                ]
                if clean_text(
                    value
                )
            )
        )

        resolution_tier = classify_group(
            group
        )

        rows.append(
            {
                "obligation_group_id": (
                    group_id
                ),
                "candidate_resolution_tier": (
                    resolution_tier
                ),
                "claim_count": len(
                    group
                ),
                "unique_asset_count": (
                    group[
                        "asset_key"
                    ].nunique()
                ),
                "claim_ids": "|".join(
                    sorted(
                        group[
                            "claim_id"
                        ].astype(
                            str
                        )
                    )
                ),
                "asset_keys": "|".join(
                    sorted(
                        group[
                            "asset_key"
                        ].astype(
                            str
                        ).unique()
                    )
                ),
                "structural_families": "|".join(
                    sorted(
                        group[
                            "structural_family"
                        ].astype(
                            str
                        ).unique()
                    )
                ),
                "mentioned_teams": "|".join(
                    all_teams
                ),
                "mentioned_team_count": len(
                    all_teams
                ),
                "mentioned_years": "|".join(
                    str(
                        value
                    )
                    for value in all_years
                ),
                "mentioned_year_count": len(
                    all_years
                ),
                "mentioned_rounds": "|".join(
                    str(
                        value
                    )
                    for value in all_rounds
                ),
                "beneficiary_teams": "|".join(
                    beneficiaries
                ),
                "beneficiary_team_count": len(
                    beneficiaries
                ),
                "favorability_types": "|".join(
                    favorability_types
                ),
                "transaction_dates": "|".join(
                    transaction_dates
                ),
                "has_swap": bool(
                    group[
                        "swap_flag"
                    ].any()
                ),
                "has_favorability_pool": bool(
                    group[
                        "favorability_pool_flag"
                    ].any()
                ),
                "has_protection": bool(
                    group[
                        "protection_flag"
                    ].any()
                ),
                "has_rollover_or_fallback": bool(
                    group[
                        "rollover_language_detected"
                    ].any()
                    or group[
                        "rollover_or_fallback_language_flag"
                    ].any()
                ),
                "out_of_horizon_dependency": bool(
                    group[
                        "out_of_horizon_dependency_flag"
                    ].any()
                ),
                "already_valued_partial_component_count": int(
                    group[
                        "valuation_status"
                    ].eq(
                        "valued_partial_rollover_component"
                    ).sum()
                ),
                "requires_dependency_review_count": int(
                    group[
                        "valuation_status"
                    ].eq(
                        "requires_dependency_review"
                    ).sum()
                ),
                "source_verification_required": (
                    True
                ),
                "group_scope_note": (
                    "Candidate dependency grouping derived from "
                    "transaction text, dates, shared teams, and asset "
                    "references. It is not yet a final legal ownership "
                    "or priority determination."
                ),
            }
        )

    return pd.DataFrame(
        rows
    ).sort_values(
        [
            "candidate_resolution_tier",
            "obligation_group_id",
        ]
    ).reset_index(
        drop=True
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
            for key, item
            in value.items()
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
    print("FUTURE NBA PICK DEPENDENCY GRAPH")
    print("=" * 80)
    print(
        f"Script version: {SCRIPT_VERSION}"
    )
    print()

    claims = load_inputs()

    nodes = enrich_claim_nodes(
        claims
    )

    nodes = build_dependency_groups(
        nodes
    )

    edges = build_dependency_edges(
        nodes
    )

    groups = build_group_summary(
        nodes
    )

    favorability_candidates = groups.loc[
        groups[
            "candidate_resolution_tier"
        ].eq(
            "same_year_favorability_pool_candidate"
        )
    ].copy()

    swap_candidates = groups.loc[
        groups[
            "candidate_resolution_tier"
        ].eq(
            "same_year_swap_chain_candidate"
        )
    ].copy()

    rollover_candidates = groups.loc[
        groups[
            "candidate_resolution_tier"
        ].eq(
            "linked_rollover_candidate"
        )
    ].copy()

    automatic_candidate_group_ids = set(
        pd.concat(
            [
                favorability_candidates[
                    [
                        "obligation_group_id"
                    ]
                ],
                swap_candidates[
                    [
                        "obligation_group_id"
                    ]
                ],
                rollover_candidates[
                    [
                        "obligation_group_id"
                    ]
                ],
            ],
            ignore_index=True,
        )[
            "obligation_group_id"
        ]
    )

    manual_review = groups.loc[
        ~groups[
            "obligation_group_id"
        ].isin(
            automatic_candidate_group_ids
        )
    ].copy()

    serializable_nodes = nodes.copy()

    for column in [
        "mentioned_teams_list",
        "mentioned_years_list",
        "raw_calendar_years_list",
        "ignored_calendar_years_list",
        "mentioned_rounds_list",
        "beneficiary_teams_list",
    ]:
        serializable_nodes[
            column
        ] = serializable_nodes[
            column
        ].map(
            json.dumps
        )

    serializable_nodes.to_parquet(
        CLAIM_NODES_PARQUET_PATH,
        index=False,
    )

    serializable_nodes.to_csv(
        CLAIM_NODES_CSV_PATH,
        index=False,
    )

    edges.to_parquet(
        DEPENDENCY_EDGES_PARQUET_PATH,
        index=False,
    )

    edges.to_csv(
        DEPENDENCY_EDGES_CSV_PATH,
        index=False,
    )

    groups.to_csv(
        GROUP_SUMMARY_PATH,
        index=False,
    )

    favorability_candidates.to_csv(
        FAVORABILITY_POOL_CANDIDATES_PATH,
        index=False,
    )

    swap_candidates.to_csv(
        SWAP_CHAIN_CANDIDATES_PATH,
        index=False,
    )

    rollover_candidates.to_csv(
        ROLLOVER_CANDIDATES_PATH,
        index=False,
    )

    manual_review.to_csv(
        MANUAL_REVIEW_PATH,
        index=False,
    )

    tier_counts = (
        groups[
            "candidate_resolution_tier"
        ]
        .value_counts()
        .to_dict()
    )

    metadata = {
        "script_version": (
            SCRIPT_VERSION
        ),
        "created_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "dependency_claim_rows_loaded": len(
            claims
        ),
        "claim_nodes_created": len(
            nodes
        ),
        "dependency_edges_created": len(
            edges
        ),
        "obligation_groups_created": len(
            groups
        ),
        "same_year_favorability_pool_candidates": len(
            favorability_candidates
        ),
        "same_year_swap_chain_candidates": len(
            swap_candidates
        ),
        "linked_rollover_candidates": len(
            rollover_candidates
        ),
        "manual_review_groups": len(
            manual_review
        ),
        "candidate_resolution_tier_counts": (
            tier_counts
        ),
        "claims_with_ignored_calendar_years": int(
            nodes[
                "ignored_calendar_years_list"
            ].map(
                bool
            ).sum()
        ),
        "claims_with_true_out_of_horizon_dependency": int(
            nodes[
                "out_of_horizon_dependency_flag"
            ].sum()
        ),
        "year_parsing_method": [
            (
                "Transaction dates are removed before dependency-year "
                "extraction."
            ),
            (
                "A year is treated as a pick dependency only when it "
                "appears near draft-pick, round, protection, rollover, "
                "conversion, or conveyance language."
            ),
            (
                "All other four-digit calendar years are retained as "
                "ignored-year diagnostics."
            ),
        ],
        "grouping_method": [
            (
                "All claims involving the same originating asset "
                "are connected."
            ),
            (
                "Claims sharing transaction date, draft year, round, "
                "structural family, and a common team or beneficiary "
                "are connected as candidate obligation groups."
            ),
            (
                "Each claim is connected to every referenced "
                "team-year-round asset found in its transaction text."
            ),
        ],
        "limitations": [
            (
                "Dependency groups are parsing candidates, not final "
                "legal ownership or priority determinations."
            ),
            (
                "References outside 2027-2029 cannot be valued by the "
                "current simulation bank."
            ),
            (
                "Favorable-pick order, swap priority, and rollover "
                "execution still require a dedicated evaluator."
            ),
            (
                "Source verification is required before any grouped "
                "asset enters a trade recommendation."
            ),
        ],
        "output_files": {
            "claim_nodes": str(
                CLAIM_NODES_PARQUET_PATH
            ),
            "dependency_edges": str(
                DEPENDENCY_EDGES_PARQUET_PATH
            ),
            "group_summary": str(
                GROUP_SUMMARY_PATH
            ),
            "favorability_pool_candidates": str(
                FAVORABILITY_POOL_CANDIDATES_PATH
            ),
            "swap_chain_candidates": str(
                SWAP_CHAIN_CANDIDATES_PATH
            ),
            "rollover_candidates": str(
                ROLLOVER_CANDIDATES_PATH
            ),
            "manual_review": str(
                MANUAL_REVIEW_PATH
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
    print("FUTURE PICK DEPENDENCY GRAPH CREATED")
    print("=" * 80)
    print(
        f"Dependency claim rows loaded: "
        f"{len(claims):,}"
    )
    print(
        f"Claim nodes created: "
        f"{len(nodes):,}"
    )
    print(
        f"Dependency edges created: "
        f"{len(edges):,}"
    )
    print(
        f"Obligation groups created: "
        f"{len(groups):,}"
    )
    print(
        "Claims with ignored calendar years: "
        f"{int(nodes['ignored_calendar_years_list'].map(bool).sum()):,}"
    )
    print(
        "Claims with a true out-of-horizon pick dependency: "
        f"{int(nodes['out_of_horizon_dependency_flag'].sum()):,}"
    )
    print(
        "Same-year favorability-pool candidates: "
        f"{len(favorability_candidates):,}"
    )
    print(
        "Same-year swap-chain candidates: "
        f"{len(swap_candidates):,}"
    )
    print(
        "Linked rollover candidates: "
        f"{len(rollover_candidates):,}"
    )
    print(
        f"Manual-review groups: "
        f"{len(manual_review):,}"
    )
    print()

    print("GROUP CLASSIFICATIONS")
    tier_display = (
        groups[
            "candidate_resolution_tier"
        ]
        .value_counts()
        .rename_axis(
            "candidate_resolution_tier"
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

    print("TOP AUTOMATIC EVALUATION CANDIDATES")
    candidate_display = pd.concat(
        [
            favorability_candidates,
            swap_candidates,
            rollover_candidates,
        ],
        ignore_index=True,
    ).head(
        30
    )

    if candidate_display.empty:
        print(
            "No groups met the conservative automatic-candidate rules."
        )
    else:
        print(
            candidate_display[
                [
                    "obligation_group_id",
                    "candidate_resolution_tier",
                    "claim_count",
                    "unique_asset_count",
                    "mentioned_teams",
                    "mentioned_years",
                    "mentioned_rounds",
                    "beneficiary_teams",
                    "favorability_types",
                ]
            ].to_string(
                index=False
            )
        )

    print()
    print("SAVED FILES")
    print(CLAIM_NODES_PARQUET_PATH)
    print(CLAIM_NODES_CSV_PATH)
    print(DEPENDENCY_EDGES_PARQUET_PATH)
    print(DEPENDENCY_EDGES_CSV_PATH)
    print(GROUP_SUMMARY_PATH)
    print(FAVORABILITY_POOL_CANDIDATES_PATH)
    print(SWAP_CHAIN_CANDIDATES_PATH)
    print(ROLLOVER_CANDIDATES_PATH)
    print(MANUAL_REVIEW_PATH)
    print(METADATA_PATH)


if __name__ == "__main__":
    main()