from __future__ import annotations

import argparse
import html as html_standard
import json
import math
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import requests
from lxml import html


SCRIPT_VERSION = "future-pick-obligation-ledger-v2-realgm-destination-fix-2026-08-04"

PROJECT_ROOT = Path(__file__).resolve().parents[1]

PICK_VALUES_PATH = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "future_originating_team_pick_values_2027_2029_v1.parquet"
)

RAW_DIRECTORY = (
    PROJECT_ROOT
    / "data"
    / "raw"
    / "draft"
    / "future_pick_transactions"
)

PROCESSED_DIRECTORY = (
    PROJECT_ROOT
    / "data"
    / "processed"
)

OUTPUT_DIRECTORY = PROJECT_ROOT / "outputs"

SOURCE_HTML_PATH = (
    RAW_DIRECTORY
    / "realgm_future_draft_pick_details_v2.html"
)

PARSED_BLOCKS_PARQUET_PATH = (
    RAW_DIRECTORY
    / "realgm_future_pick_outgoing_blocks_2027_2029_v2.parquet"
)

PARSED_BLOCKS_CSV_PATH = (
    RAW_DIRECTORY
    / "realgm_future_pick_outgoing_blocks_2027_2029_v2.csv"
)

CLAIMS_PARQUET_PATH = (
    PROCESSED_DIRECTORY
    / "future_pick_obligation_claims_2027_2029_v2.parquet"
)

CLAIMS_CSV_PATH = (
    PROCESSED_DIRECTORY
    / "future_pick_obligation_claims_2027_2029_v2.csv"
)

RESOLVED_CANDIDATES_PARQUET_PATH = (
    PROCESSED_DIRECTORY
    / "future_pick_ownership_resolved_candidates_2027_2029_v2.parquet"
)

RESOLVED_CANDIDATES_CSV_PATH = (
    PROCESSED_DIRECTORY
    / "future_pick_ownership_resolved_candidates_2027_2029_v2.csv"
)

MANUAL_REVIEW_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_obligation_manual_review_2027_2029_v2.csv"
)

MANUAL_OVERRIDE_TEMPLATE_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_obligation_manual_overrides_template_2027_2029_v2.csv"
)

TEAM_SUMMARY_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_ownership_candidate_team_summary_2027_2029_v2.csv"
)

PARSER_AUDIT_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_obligation_parser_audit_v2.csv"
)

METADATA_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_obligation_ledger_metadata_v2.json"
)


SOURCE_URL = (
    "https://basketball.realgm.com/"
    "nba/draft/future_drafts/detailed"
)

DRAFT_YEARS = [
    2027,
    2028,
    2029,
]

ROUNDS = [
    1,
    2,
]

REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/150.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://basketball.realgm.com/",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}

TEAM_ALIASES = {
    # RealGM headings frequently use only a city or market name,
    # such as "to Brooklyn", "to Dallas", or "to San Antonio".
    # These aliases must be present in addition to full team names
    # and nicknames, or straightforward transfers are misclassified
    # as having no parsed destination.
    "atlanta": "ATL",
    "boston": "BOS",
    "brooklyn": "BKN",
    "charlotte": "CHA",
    "chicago": "CHI",
    "cleveland": "CLE",
    "dallas": "DAL",
    "denver": "DEN",
    "detroit": "DET",
    "golden state": "GSW",
    "houston": "HOU",
    "indiana": "IND",
    "l a clippers": "LAC",
    "la clippers": "LAC",
    "los angeles clippers": "LAC",
    "l a lakers": "LAL",
    "la lakers": "LAL",
    "los angeles lakers": "LAL",
    "memphis": "MEM",
    "miami": "MIA",
    "milwaukee": "MIL",
    "minnesota": "MIN",
    "new orleans": "NOP",
    "new york": "NYK",
    "oklahoma city": "OKC",
    "orlando": "ORL",
    "philadelphia": "PHI",
    "phoenix": "PHX",
    "portland": "POR",
    "sacramento": "SAC",
    "san antonio": "SAS",
    "toronto": "TOR",
    "utah": "UTA",
    "washington": "WAS",
    "atlanta hawks": "ATL",
    "hawks": "ATL",
    "boston celtics": "BOS",
    "celtics": "BOS",
    "brooklyn nets": "BKN",
    "nets": "BKN",
    "charlotte hornets": "CHA",
    "hornets": "CHA",
    "chicago bulls": "CHI",
    "bulls": "CHI",
    "cleveland cavaliers": "CLE",
    "cavaliers": "CLE",
    "cavs": "CLE",
    "dallas mavericks": "DAL",
    "mavericks": "DAL",
    "mavs": "DAL",
    "denver nuggets": "DEN",
    "nuggets": "DEN",
    "detroit pistons": "DET",
    "pistons": "DET",
    "golden state warriors": "GSW",
    "warriors": "GSW",
    "houston rockets": "HOU",
    "rockets": "HOU",
    "indiana pacers": "IND",
    "pacers": "IND",
    "l a clippers": "LAC",
    "la clippers": "LAC",
    "los angeles clippers": "LAC",
    "clippers": "LAC",
    "l a lakers": "LAL",
    "la lakers": "LAL",
    "los angeles lakers": "LAL",
    "lakers": "LAL",
    "memphis grizzlies": "MEM",
    "grizzlies": "MEM",
    "miami heat": "MIA",
    "heat": "MIA",
    "milwaukee bucks": "MIL",
    "bucks": "MIL",
    "minnesota timberwolves": "MIN",
    "timberwolves": "MIN",
    "wolves": "MIN",
    "new orleans pelicans": "NOP",
    "pelicans": "NOP",
    "new york knicks": "NYK",
    "knicks": "NYK",
    "oklahoma city thunder": "OKC",
    "thunder": "OKC",
    "orlando magic": "ORL",
    "magic": "ORL",
    "philadelphia 76ers": "PHI",
    "76ers": "PHI",
    "sixers": "PHI",
    "phoenix suns": "PHX",
    "suns": "PHX",
    "portland trail blazers": "POR",
    "portland trailblazers": "POR",
    "trail blazers": "POR",
    "trailblazers": "POR",
    "blazers": "POR",
    "sacramento kings": "SAC",
    "kings": "SAC",
    "san antonio spurs": "SAS",
    "spurs": "SAS",
    "toronto raptors": "TOR",
    "raptors": "TOR",
    "utah jazz": "UTA",
    "jazz": "UTA",
    "washington wizards": "WAS",
    "wizards": "WAS",
}

TEAM_CODES = sorted(
    set(
        TEAM_ALIASES.values()
    )
)

PICK_VALUE_COLUMNS = [
    "expected_overall_pick",
    "median_overall_pick",
    "overall_pick_p10",
    "overall_pick_p90",
    "expected_historical_pick_value_score",
    "time_discount_factor",
    "time_discounted_pick_value_score",
    "expected_pick_value_rating_60_99",
    "expected_rotation_probability",
    "expected_starter_probability",
    "expected_star_proxy_probability",
    "expected_year4_active_probability",
    "pick_value_score_sd",
    "pick_slot_sd",
]

PICK_HEADING_PATTERN = re.compile(
    r"^(?P<year>20\d{2})\s+"
    r"(?P<round>first|second)\s+round\s+"
    r"draft\s+pick\s+to\s+",
    re.IGNORECASE,
)

PROTECTION_PATTERNS = [
    (
        "protected_range",
        re.compile(
            r"protected\s+for\s+selections?\s+"
            r"(\d+)\s*(?:through|to|-|–)\s*(\d+)",
            re.IGNORECASE,
        ),
    ),
    (
        "protected_single",
        re.compile(
            r"protected\s+for\s+selection\s+(\d+)",
            re.IGNORECASE,
        ),
    ),
    (
        "top_n",
        re.compile(
            r"protected\s+(?:for\s+)?(?:selections?\s+)?"
            r"1\s*(?:through|to|-|–)\s*(\d+)",
            re.IGNORECASE,
        ),
    ),
    (
        "barred_range",
        re.compile(
            r"barred\s+from\s+selections?\s+"
            r"(\d+)\s*(?:through|to|-|–)\s*(\d+)",
            re.IGNORECASE,
        ),
    ),
    (
        "lottery",
        re.compile(
            r"lottery[\s-]*protected",
            re.IGNORECASE,
        ),
    ),
]

FAVORABILITY_PHRASES = [
    "most favorable",
    "least favorable",
    "more favorable",
    "less favorable",
    "second most favorable",
    "second least favorable",
    "third most favorable",
]

CONDITIONAL_PHRASES = [
    " if ",
    " unless ",
    "may convey",
    "may receive",
    "depending on",
    "at least",
    "converts to",
    "becomes",
    "obligation will be extinguished",
    "obligation to",
    "connects to",
    "overlaps with",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build a 2027-2029 NBA future-pick obligation ledger "
            "from RealGM's detailed future-draft page."
        )
    )

    parser.add_argument(
        "--force-download",
        action="store_true",
        help=(
            "Download RealGM again even when a cached HTML file exists."
        ),
    )

    return parser.parse_args()


def clean_text(
    value: Any,
) -> str:
    if value is None:
        return ""

    return re.sub(
        r"\s+",
        " ",
        str(
            value
        ),
    ).strip()


def normalize_team_text(
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


def normalize_team_label(
    value: Any,
) -> str | None:
    text = normalize_team_text(
        value
    )

    if text in TEAM_ALIASES:
        return TEAM_ALIASES[
            text
        ]

    for alias in sorted(
        TEAM_ALIASES,
        key=len,
        reverse=True,
    ):
        if re.search(
            rf"\b{re.escape(alias)}\b",
            text,
        ):
            return TEAM_ALIASES[
                alias
            ]

    return None


def teams_from_text(
    value: Any,
) -> list[str]:
    text = normalize_team_text(
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
                for existing in occupied_spans
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

    output = []

    for _, team in matches:
        if team not in output:
            output.append(
                team
            )

    return output


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
    output = pd.to_numeric(
        frame[
            column
        ],
        errors="coerce",
    )

    if fill_value is not None:
        output = output.fillna(
            fill_value
        )

    return output.astype(
        float
    )


def looks_like_realgm_page(
    text: str,
) -> bool:
    lower = text.lower()

    return (
        "nba future draft pick details"
        in lower
        and "future traded pick details"
        in lower
        and len(
            text
        )
        > 25_000
    )


def download_with_requests() -> str:
    session = requests.Session()

    session.headers.update(
        REQUEST_HEADERS
    )

    session.get(
        "https://basketball.realgm.com/",
        timeout=45,
    )

    response = session.get(
        SOURCE_URL,
        timeout=60,
    )

    response.raise_for_status()

    return response.text


def download_with_curl() -> str:
    command = [
        "curl.exe",
        "-L",
        "--compressed",
        "--silent",
        "--show-error",
        "--max-time",
        "90",
        "-A",
        REQUEST_HEADERS[
            "User-Agent"
        ],
        "-e",
        REQUEST_HEADERS[
            "Referer"
        ],
        SOURCE_URL,
    ]

    completed = subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    return completed.stdout


def load_or_download_source(
    force_download: bool,
) -> str:
    if (
        SOURCE_HTML_PATH.exists()
        and not force_download
    ):
        cached = SOURCE_HTML_PATH.read_text(
            encoding="utf-8",
            errors="replace",
        )

        if looks_like_realgm_page(
            cached
        ):
            print(
                "Loading cached RealGM future-pick page."
            )

            return cached

    errors = []

    try:
        text = download_with_requests()

        if not looks_like_realgm_page(
            text
        ):
            raise RuntimeError(
                "Requests response did not contain the expected page."
            )

        SOURCE_HTML_PATH.write_text(
            text,
            encoding="utf-8",
        )

        return text
    except Exception as error:
        errors.append(
            f"requests: {type(error).__name__}: {error}"
        )

    try:
        text = download_with_curl()

        if not looks_like_realgm_page(
            text
        ):
            raise RuntimeError(
                "curl response did not contain the expected page."
            )

        SOURCE_HTML_PATH.write_text(
            text,
            encoding="utf-8",
        )

        return text
    except Exception as error:
        errors.append(
            f"curl.exe: {type(error).__name__}: {error}"
        )

    raise RuntimeError(
        "RealGM could not be downloaded through requests or curl.exe.\n"
        + "\n".join(
            errors
        )
    )


def cell_lines(
    cell: Any,
) -> list[str]:
    lines = []

    for text_node in cell.xpath(
        ".//text()"
    ):
        text = clean_text(
            html_standard.unescape(
                str(
                    text_node
                )
            )
        )

        if text:
            lines.append(
                text
            )

    return lines


def split_outgoing_blocks(
    cell: Any,
) -> list[dict[str, Any]]:
    lines = cell_lines(
        cell
    )

    blocks = []

    current_title = None
    current_detail_lines = []

    def flush() -> None:
        nonlocal current_title
        nonlocal current_detail_lines

        if current_title is None:
            return

        match = PICK_HEADING_PATTERN.match(
            current_title
        )

        if match is None:
            current_title = None
            current_detail_lines = []
            return

        round_number = (
            1
            if match.group(
                "round"
            ).lower()
            == "first"
            else 2
        )

        blocks.append(
            {
                "draft_year": int(
                    match.group(
                        "year"
                    )
                ),
                "round_number": (
                    round_number
                ),
                "pick_heading": (
                    current_title
                ),
                "transaction_text": clean_text(
                    " ".join(
                        current_detail_lines
                    )
                ),
                "full_obligation_text": clean_text(
                    " ".join(
                        [
                            current_title,
                            *current_detail_lines,
                        ]
                    )
                ),
            }
        )

        current_title = None
        current_detail_lines = []

    for line in lines:
        if PICK_HEADING_PATTERN.match(
            line
        ):
            flush()

            current_title = line
            current_detail_lines = []
        elif current_title is not None:
            current_detail_lines.append(
                line
            )

    flush()

    return blocks


def parse_realgm_page(
    source_html: str,
) -> tuple[
    pd.DataFrame,
    pd.DataFrame,
]:
    document = html.fromstring(
        source_html
    )

    section_rows = []

    outgoing_blocks = []

    headings = document.xpath(
        "//h2[contains(normalize-space(.), "
        "'Future Traded Pick Details')]"
    )

    for heading in headings:
        heading_text = clean_text(
            heading.text_content()
        )

        team_name = re.sub(
            r"\s+Future Traded Pick Details\s*$",
            "",
            heading_text,
            flags=re.IGNORECASE,
        )

        team_code = normalize_team_label(
            team_name
        )

        if team_code is None:
            continue

        following_tables = heading.xpath(
            "following::table[1]"
        )

        if not following_tables:
            continue

        table = following_tables[
            0
        ]

        team_rows_found = 0
        team_blocks_found = 0

        for row in table.xpath(
            ".//tr"
        ):
            cells = row.xpath(
                "./td"
            )

            if len(
                cells
            ) < 3:
                continue

            year_text = clean_text(
                cells[
                    0
                ].text_content()
            )

            year_match = re.search(
                r"\b(20\d{2})\b",
                year_text,
            )

            if year_match is None:
                continue

            draft_year = int(
                year_match.group(
                    1
                )
            )

            if draft_year not in DRAFT_YEARS:
                continue

            incoming_text = clean_text(
                " ".join(
                    cell_lines(
                        cells[
                            1
                        ]
                    )
                )
            )

            outgoing_text = clean_text(
                " ".join(
                    cell_lines(
                        cells[
                            2
                        ]
                    )
                )
            )

            blocks = split_outgoing_blocks(
                cells[
                    2
                ]
            )

            team_rows_found += 1
            team_blocks_found += len(
                blocks
            )

            section_rows.append(
                {
                    "team_abbreviation": (
                        team_code
                    ),
                    "team_name": (
                        team_name
                    ),
                    "draft_year": (
                        draft_year
                    ),
                    "incoming_text": (
                        incoming_text
                    ),
                    "outgoing_text": (
                        outgoing_text
                    ),
                    "outgoing_blocks_found": len(
                        blocks
                    ),
                }
            )

            for block_index, block in enumerate(
                blocks,
                start=1,
            ):
                block[
                    "originating_team"
                ] = team_code

                block[
                    "team_name"
                ] = team_name

                block[
                    "source_block_sequence"
                ] = block_index

                block[
                    "source_url"
                ] = SOURCE_URL

                outgoing_blocks.append(
                    block
                )

        if team_rows_found > 0:
            pass

    sections = pd.DataFrame(
        section_rows
    )

    blocks = pd.DataFrame(
        outgoing_blocks
    )

    if sections.empty:
        raise RuntimeError(
            "No team-year sections were parsed from RealGM."
        )

    parsed_teams = set(
        sections[
            "team_abbreviation"
        ].unique()
    )

    missing_teams = (
        set(
            TEAM_CODES
        )
        - parsed_teams
    )

    if missing_teams:
        raise ValueError(
            "RealGM parser did not find every NBA team.\n"
            f"Missing: {sorted(missing_teams)}"
        )

    team_year_counts = (
        sections.groupby(
            "team_abbreviation"
        )[
            "draft_year"
        ]
        .nunique()
    )

    if not team_year_counts.eq(
        len(
            DRAFT_YEARS
        )
    ).all():
        raise ValueError(
            "Every team should have one parsed row for each "
            "2027-2029 draft year.\n"
            + team_year_counts.to_string()
        )

    if len(
        blocks
    ) < 35:
        raise ValueError(
            "Too few outgoing pick blocks were parsed. "
            f"Only {len(blocks)} were found, so the page structure "
            "should be reviewed before continuing."
        )

    return (
        sections.sort_values(
            [
                "team_abbreviation",
                "draft_year",
            ]
        ).reset_index(
            drop=True
        ),
        blocks.sort_values(
            [
                "draft_year",
                "round_number",
                "originating_team",
                "source_block_sequence",
            ]
        ).reset_index(
            drop=True
        ),
    )


def destination_phrase(
    heading: str,
) -> str:
    lower = heading.lower()

    marker = " draft pick to "

    position = lower.find(
        marker
    )

    if position < 0:
        return ""

    phrase = heading[
        position
        + len(
            marker
        ):
    ]

    phrase = phrase.split(
        "(",
        1,
    )[
        0
    ]

    return clean_text(
        phrase
    )


def extract_protection(
    text: str,
) -> tuple[
    str,
    float,
    float,
]:
    for protection_type, pattern in (
        PROTECTION_PATTERNS
    ):
        match = pattern.search(
            text
        )

        if match is None:
            continue

        if protection_type == "lottery":
            return (
                "lottery",
                1.0,
                16.0,
            )

        if protection_type == "protected_single":
            value = float(
                match.group(
                    1
                )
            )

            return (
                "single_pick",
                value,
                value,
            )

        if protection_type == "top_n":
            return (
                "top_n",
                1.0,
                float(
                    match.group(
                        1
                    )
                ),
            )

        return (
            protection_type,
            float(
                match.group(
                    1
                )
            ),
            float(
                match.group(
                    2
                )
            ),
        )

    return (
        "none_detected",
        np.nan,
        np.nan,
    )


def classify_outgoing_block(
    row: pd.Series,
) -> pd.Series:
    heading = clean_text(
        row[
            "pick_heading"
        ]
    )

    full_text = clean_text(
        row[
            "full_obligation_text"
        ]
    )

    lower = (
        f" {full_text.lower()} "
    )

    origin = str(
        row[
            "originating_team"
        ]
    )

    destination = destination_phrase(
        heading
    )

    destination_teams = teams_from_text(
        destination
    )

    destination_teams = [
        team
        for team in destination_teams
        if team != origin
    ]

    protection_type, protection_start, protection_end = (
        extract_protection(
            full_text
        )
    )

    protection_flag = (
        protection_type
        != "none_detected"
    )

    swap_flag = (
        "swap" in lower
    )

    favorability_flag = any(
        phrase in lower
        for phrase in FAVORABILITY_PHRASES
    )

    conditional_flag = (
        protection_flag
        or any(
            phrase in lower
            for phrase in CONDITIONAL_PHRASES
        )
    )

    multiple_destinations = (
        len(
            destination_teams
        )
        != 1
    )

    if swap_flag:
        claim_type = "swap_right_or_swap_chain"
        resolution_status = "manual_review_swap"
        owner_candidate = ""
    elif favorability_flag:
        claim_type = "multi_pick_favorability_pool"
        resolution_status = (
            "manual_review_multi_pick_pool"
        )
        owner_candidate = ""
    elif conditional_flag:
        claim_type = "conditional_transfer"
        resolution_status = (
            "manual_review_conditional"
        )
        owner_candidate = ""
    elif multiple_destinations:
        claim_type = "multi_destination_or_unparsed"
        resolution_status = (
            "manual_review_destination"
        )
        owner_candidate = ""
    else:
        claim_type = "outright_transfer"
        resolution_status = (
            "resolved_outright_candidate"
        )
        owner_candidate = destination_teams[
            0
        ]

    dates = re.findall(
        r"\b(\d{1,2}/\d{1,2}/\d{4})\b",
        full_text,
    )

    return pd.Series(
        {
            "destination_phrase": (
                destination
            ),
            "destination_team_sequence": (
                "|".join(
                    destination_teams
                )
            ),
            "destination_team_count": len(
                destination_teams
            ),
            "destination_parse_success": (
                len(destination_teams) >= 1
            ),
            "single_destination_parse_success": (
                len(destination_teams) == 1
            ),
            "claim_type": (
                claim_type
            ),
            "resolution_status": (
                resolution_status
            ),
            "resolved_owner_candidate": (
                owner_candidate
            ),
            "swap_flag": (
                swap_flag
            ),
            "favorability_pool_flag": (
                favorability_flag
            ),
            "conditional_language_flag": (
                conditional_flag
            ),
            "protection_flag": (
                protection_flag
            ),
            "protection_type": (
                protection_type
            ),
            "protection_start_pick": (
                protection_start
            ),
            "protection_end_pick": (
                protection_end
            ),
            "rollover_or_fallback_language_flag": any(
                phrase in lower
                for phrase in [
                    "instead convey",
                    "unprotected in",
                    "obligation will be extinguished",
                    "converts to",
                    "becomes",
                ]
            ),
            "transaction_date_last_detected": (
                dates[
                    -1
                ]
                if dates
                else ""
            ),
        }
    )


def load_pick_values() -> pd.DataFrame:
    if not PICK_VALUES_PATH.exists():
        raise FileNotFoundError(
            "Future pick-value file was not found:\n"
            f"{PICK_VALUES_PATH}"
        )

    values = normalize_columns(
        pd.read_parquet(
            PICK_VALUES_PATH
        )
    )

    require_columns(
        values,
        [
            "originating_team",
            "draft_year",
            "round_number",
            *PICK_VALUE_COLUMNS,
        ],
        "Future originating-team pick values",
    )

    values[
        "draft_year"
    ] = numeric_series(
        values,
        "draft_year",
    ).round().astype(int)

    values[
        "round_number"
    ] = numeric_series(
        values,
        "round_number",
    ).round().astype(int)

    duplicate_mask = values.duplicated(
        subset=[
            "originating_team",
            "draft_year",
            "round_number",
        ],
        keep=False,
    )

    if duplicate_mask.any():
        raise ValueError(
            "Future pick-value input contains duplicate asset keys."
        )

    return values


def build_complete_claim_ledger(
    outgoing_blocks: pd.DataFrame,
    pick_values: pd.DataFrame,
) -> pd.DataFrame:
    base_assets = pd.DataFrame(
        [
            {
                "originating_team": (
                    team
                ),
                "draft_year": (
                    draft_year
                ),
                "round_number": (
                    round_number
                ),
            }
            for team in TEAM_CODES
            for draft_year in DRAFT_YEARS
            for round_number in ROUNDS
        ]
    )

    expected_assets = (
        len(
            TEAM_CODES
        )
        * len(
            DRAFT_YEARS
        )
        * len(
            ROUNDS
        )
    )

    if len(
        base_assets
    ) != expected_assets:
        raise RuntimeError(
            "Base asset universe did not contain 180 picks."
        )

    base_assets[
        "asset_key"
    ] = (
        base_assets[
            "draft_year"
        ].astype(str)
        + "_R"
        + base_assets[
            "round_number"
        ].astype(str)
        + "_"
        + base_assets[
            "originating_team"
        ]
    )

    outgoing = outgoing_blocks.copy()

    outgoing[
        "asset_key"
    ] = (
        outgoing[
            "draft_year"
        ].astype(str)
        + "_R"
        + outgoing[
            "round_number"
        ].astype(str)
        + "_"
        + outgoing[
            "originating_team"
        ]
    )

    outgoing_keys = set(
        outgoing[
            "asset_key"
        ].unique()
    )

    own_rows = base_assets.loc[
        ~base_assets[
            "asset_key"
        ].isin(
            outgoing_keys
        )
    ].copy()

    own_rows[
        "team_name"
    ] = ""

    own_rows[
        "source_block_sequence"
    ] = 0

    own_rows[
        "pick_heading"
    ] = ""

    own_rows[
        "transaction_text"
    ] = ""

    own_rows[
        "full_obligation_text"
    ] = ""

    own_rows[
        "source_url"
    ] = SOURCE_URL

    own_rows[
        "destination_phrase"
    ] = ""

    own_rows[
        "destination_team_sequence"
    ] = ""

    own_rows[
        "destination_team_count"
    ] = 0

    own_rows[
        "claim_type"
    ] = "own_pick_retained"

    own_rows[
        "resolution_status"
    ] = "resolved_own"

    own_rows[
        "resolved_owner_candidate"
    ] = own_rows[
        "originating_team"
    ]

    for column in [
        "swap_flag",
        "favorability_pool_flag",
        "conditional_language_flag",
        "protection_flag",
        "rollover_or_fallback_language_flag",
    ]:
        own_rows[
            column
        ] = False

    own_rows[
        "protection_type"
    ] = "none_detected"

    own_rows[
        "protection_start_pick"
    ] = np.nan

    own_rows[
        "protection_end_pick"
    ] = np.nan

    own_rows[
        "transaction_date_last_detected"
    ] = ""

    claim_columns = sorted(
        set(
            own_rows.columns
        )
        | set(
            outgoing.columns
        )
    )

    own_rows = own_rows.reindex(
        columns=claim_columns
    )

    outgoing = outgoing.reindex(
        columns=claim_columns
    )

    claims = pd.concat(
        [
            own_rows,
            outgoing,
        ],
        ignore_index=True,
        sort=False,
    )

    claims[
        "claim_sequence_for_asset"
    ] = (
        claims.sort_values(
            [
                "asset_key",
                "source_block_sequence",
            ]
        )
        .groupby(
            "asset_key"
        )
        .cumcount()
        + 1
    )

    claims[
        "asset_claim_count"
    ] = (
        claims.groupby(
            "asset_key"
        )[
            "asset_key"
        ]
        .transform(
            "size"
        )
    )

    claims[
        "multiple_claim_rows_flag"
    ] = (
        claims[
            "asset_claim_count"
        ]
        > 1
    )

    claims[
        "claim_id"
    ] = (
        claims[
            "asset_key"
        ]
        + "_C"
        + claims[
            "claim_sequence_for_asset"
        ].astype(str)
    )

    claims[
        "requires_manual_review"
    ] = (
        claims[
            "resolution_status"
        ].astype(str).str.startswith(
            "manual_review"
        )
        | claims[
            "multiple_claim_rows_flag"
        ]
    )

    claims = claims.merge(
        pick_values[
            [
                "originating_team",
                "draft_year",
                "round_number",
                *PICK_VALUE_COLUMNS,
            ]
        ],
        how="left",
        on=[
            "originating_team",
            "draft_year",
            "round_number",
        ],
        validate="many_to_one",
    )

    if claims[
        "time_discounted_pick_value_score"
    ].isna().any():
        raise ValueError(
            "Some claims failed to match the simulated pick values."
        )

    if claims[
        "asset_key"
    ].nunique() != expected_assets:
        raise ValueError(
            "The completed ledger does not represent all 180 "
            "origin-year-round assets."
        )

    claims[
        "source_scope_note"
    ] = (
        "RealGM outgoing-pick transaction claim. Straightforward "
        "ownership is only a candidate until reviewed. Protections, "
        "swaps, pooled selections, rollover clauses, and overlapping "
        "claims remain outside automatic resolution."
    )

    return claims.sort_values(
        [
            "draft_year",
            "round_number",
            "originating_team",
            "claim_sequence_for_asset",
        ]
    ).reset_index(
        drop=True
    )


def build_override_template(
    manual_review: pd.DataFrame,
) -> pd.DataFrame:
    source_columns = [
        "claim_id",
        "asset_key",
        "draft_year",
        "round_number",
        "originating_team",
        "destination_phrase",
        "destination_team_sequence",
        "claim_type",
        "resolution_status",
        "protection_type",
        "protection_start_pick",
        "protection_end_pick",
        "pick_heading",
        "transaction_text",
    ]

    template = manual_review[
        source_columns
    ].copy()

    manual_columns = [
        "manual_final_owner",
        "manual_asset_status",
        "manual_protection_type",
        "manual_protection_start_pick",
        "manual_protection_end_pick",
        "manual_swap_controller",
        "manual_swap_pool",
        "manual_rollover_description",
        "manual_conveyance_dependency",
        "manual_tradability_status",
        "manual_review_notes",
        "manual_source_verified",
    ]

    for column in manual_columns:
        template[
            column
        ] = ""

    return template


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
    args = parse_args()

    for directory in [
        RAW_DIRECTORY,
        PROCESSED_DIRECTORY,
        OUTPUT_DIRECTORY,
    ]:
        directory.mkdir(
            parents=True,
            exist_ok=True,
        )

    print("=" * 80)
    print("FUTURE NBA DRAFT-PICK OBLIGATION LEDGER V2")
    print("=" * 80)
    print(
        f"Script version: {SCRIPT_VERSION}"
    )
    print(
        f"Source: {SOURCE_URL}"
    )
    print()

    source_html = load_or_download_source(
        force_download=(
            args.force_download
        )
    )

    (
        parser_audit,
        outgoing_blocks,
    ) = parse_realgm_page(
        source_html
    )

    classifications = (
        outgoing_blocks.apply(
            classify_outgoing_block,
            axis=1,
        )
    )

    outgoing_blocks = pd.concat(
        [
            outgoing_blocks,
            classifications,
        ],
        axis=1,
    )

    pick_values = load_pick_values()

    claims = build_complete_claim_ledger(
        outgoing_blocks=(
            outgoing_blocks
        ),
        pick_values=pick_values,
    )

    resolved = claims.loc[
        claims[
            "resolution_status"
        ].isin(
            [
                "resolved_own",
                "resolved_outright_candidate",
            ]
        )
        & ~claims[
            "multiple_claim_rows_flag"
        ]
    ].copy()

    manual_review = claims.loc[
        ~claims[
            "claim_id"
        ].isin(
            resolved[
                "claim_id"
            ]
        )
    ].copy()

    outgoing_blocks.to_parquet(
        PARSED_BLOCKS_PARQUET_PATH,
        index=False,
    )

    outgoing_blocks.to_csv(
        PARSED_BLOCKS_CSV_PATH,
        index=False,
    )

    claims.to_parquet(
        CLAIMS_PARQUET_PATH,
        index=False,
    )

    claims.to_csv(
        CLAIMS_CSV_PATH,
        index=False,
    )

    resolved.to_parquet(
        RESOLVED_CANDIDATES_PARQUET_PATH,
        index=False,
    )

    resolved.to_csv(
        RESOLVED_CANDIDATES_CSV_PATH,
        index=False,
    )

    manual_review.to_csv(
        MANUAL_REVIEW_PATH,
        index=False,
    )

    build_override_template(
        manual_review
    ).to_csv(
        MANUAL_OVERRIDE_TEMPLATE_PATH,
        index=False,
    )

    parser_audit.to_csv(
        PARSER_AUDIT_PATH,
        index=False,
    )

    team_summary = (
        resolved.groupby(
            [
                "resolved_owner_candidate",
                "draft_year",
                "round_number",
            ],
            as_index=False,
        )
        .agg(
            resolved_assets=(
                "asset_key",
                "nunique",
            ),
            total_time_discounted_pick_value=(
                "time_discounted_pick_value_score",
                "sum",
            ),
            average_pick_value_rating=(
                "expected_pick_value_rating_60_99",
                "mean",
            ),
            average_expected_pick=(
                "expected_overall_pick",
                "mean",
            ),
        )
        .sort_values(
            [
                "draft_year",
                "round_number",
                "total_time_discounted_pick_value",
            ],
            ascending=[
                True,
                True,
                False,
            ],
        )
        .reset_index(
            drop=True
        )
    )

    team_summary.to_csv(
        TEAM_SUMMARY_PATH,
        index=False,
    )

    metadata = {
        "script_version": (
            SCRIPT_VERSION
        ),
        "created_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "source_url": SOURCE_URL,
        "draft_years": (
            DRAFT_YEARS
        ),
        "teams_parsed": int(
            parser_audit[
                "team_abbreviation"
            ].nunique()
        ),
        "team_year_rows_parsed": len(
            parser_audit
        ),
        "outgoing_obligation_blocks": len(
            outgoing_blocks
        ),
        "unique_assets_represented": int(
            claims[
                "asset_key"
            ].nunique()
        ),
        "total_claim_rows": len(
            claims
        ),
        "resolved_candidate_rows": len(
            resolved
        ),
        "manual_review_rows": len(
            manual_review
        ),
        "assets_with_multiple_claim_rows": int(
            claims.loc[
                claims[
                    "multiple_claim_rows_flag"
                ],
                "asset_key",
            ].nunique()
        ),
        "claim_type_counts": (
            claims[
                "claim_type"
            ]
            .value_counts(
                dropna=False
            )
            .to_dict()
        ),
        "automatic_resolution_policy": [
            (
                "Every team begins with its own first and second "
                "for each modeled year."
            ),
            (
                "A successfully parsed outgoing obligation replaces "
                "the own-pick assumption for that asset."
            ),
            (
                "Only unconditional one-destination transfers are "
                "treated as ownership candidates."
            ),
            (
                "Protections, swaps, favorable-pick pools, fallback "
                "language, multiple destinations, and overlapping "
                "claims require manual review."
            ),
        ],
        "limitations": [
            (
                "RealGM is a detailed public transaction ledger, "
                "not an official NBA ownership registry."
            ),
            (
                "Resolved ownership rows are candidates until the "
                "transaction description is independently reviewed."
            ),
            (
                "This stage does not yet calculate protection "
                "conveyance probability or swap-option value."
            ),
            (
                "This stage does not yet determine current CBA "
                "tradability."
            ),
        ],
        "output_files": {
            "cached_source_html": str(
                SOURCE_HTML_PATH
            ),
            "parsed_outgoing_blocks": str(
                PARSED_BLOCKS_PARQUET_PATH
            ),
            "complete_claim_ledger": str(
                CLAIMS_PARQUET_PATH
            ),
            "resolved_candidates": str(
                RESOLVED_CANDIDATES_PARQUET_PATH
            ),
            "manual_review": str(
                MANUAL_REVIEW_PATH
            ),
            "manual_override_template": str(
                MANUAL_OVERRIDE_TEMPLATE_PATH
            ),
            "parser_audit": str(
                PARSER_AUDIT_PATH
            ),
            "team_summary": str(
                TEAM_SUMMARY_PATH
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

    print()
    print("=" * 80)
    print("FUTURE PICK OBLIGATION LEDGER V2 CREATED")
    print("=" * 80)
    print(
        f"Teams parsed: "
        f"{metadata['teams_parsed']:,}"
    )
    print(
        "Team-year rows parsed: "
        f"{metadata['team_year_rows_parsed']:,}"
    )
    print(
        "Outgoing obligation blocks parsed: "
        f"{metadata['outgoing_obligation_blocks']:,}"
    )
    print(
        "Unique origin-year-round assets represented: "
        f"{metadata['unique_assets_represented']:,}"
    )
    print(
        f"Total claim rows: "
        f"{metadata['total_claim_rows']:,}"
    )
    print(
        "Automatically resolved ownership candidates: "
        f"{metadata['resolved_candidate_rows']:,}"
    )
    print(
        f"Rows requiring review: "
        f"{metadata['manual_review_rows']:,}"
    )
    print(
        "Assets with multiple claim rows: "
        f"{metadata['assets_with_multiple_claim_rows']:,}"
    )
    print()

    print("DESTINATION PARSING")
    outgoing_claims = claims.loc[
        claims["source_block_sequence"].fillna(0).gt(0)
    ].copy()

    print(
        "Outgoing rows with at least one parsed destination: "
        f"{int(outgoing_claims['destination_parse_success'].fillna(False).sum()):,} "
        f"/ {len(outgoing_claims):,}"
    )
    print(
        "Outgoing rows with exactly one parsed destination: "
        f"{int(outgoing_claims['single_destination_parse_success'].fillna(False).sum()):,} "
        f"/ {len(outgoing_claims):,}"
    )
    print()

    print("CLAIM TYPES")
    claim_display = (
        claims[
            "claim_type"
        ]
        .value_counts()
        .rename_axis(
            "claim_type"
        )
        .reset_index(
            name="rows"
        )
    )

    print(
        claim_display.to_string(
            index=False
        )
    )
    print()

    print("TOP 30 RESOLVED OWNERSHIP CANDIDATES")
    display = (
        resolved.sort_values(
            "time_discounted_pick_value_score",
            ascending=False,
        )
        .head(
            30
        )[
            [
                "asset_key",
                "originating_team",
                "resolved_owner_candidate",
                "draft_year",
                "round_number",
                "expected_overall_pick",
                "expected_pick_value_rating_60_99",
                "time_discounted_pick_value_score",
                "claim_type",
            ]
        ]
        .copy()
    )

    for column in [
        "expected_overall_pick",
        "expected_pick_value_rating_60_99",
        "time_discounted_pick_value_score",
    ]:
        display[
            column
        ] = (
            pd.to_numeric(
                display[
                    column
                ],
                errors="coerce",
            )
            .round(
                2
            )
        )

    print(
        display.to_string(
            index=False
        )
    )
    print()

    print("SAVED FILES")
    print(SOURCE_HTML_PATH)
    print(PARSED_BLOCKS_PARQUET_PATH)
    print(PARSED_BLOCKS_CSV_PATH)
    print(CLAIMS_PARQUET_PATH)
    print(CLAIMS_CSV_PATH)
    print(RESOLVED_CANDIDATES_PARQUET_PATH)
    print(RESOLVED_CANDIDATES_CSV_PATH)
    print(MANUAL_REVIEW_PATH)
    print(MANUAL_OVERRIDE_TEMPLATE_PATH)
    print(TEAM_SUMMARY_PATH)
    print(PARSER_AUDIT_PATH)
    print(METADATA_PATH)


if __name__ == "__main__":
    main()