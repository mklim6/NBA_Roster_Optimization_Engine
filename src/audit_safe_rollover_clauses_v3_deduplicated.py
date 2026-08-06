from __future__ import annotations

import json
import math
import re
import textwrap
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


SCRIPT_VERSION = "future-pick-safe-rollover-clause-audit-v3-deduplicated-2026-08-04"

PROJECT_ROOT = Path(__file__).resolve().parents[1]

CLAIM_NODES_PATH = (
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

VALUATIONS_PATH = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "future_pick_claim_value_layer_2027_2029_v1.parquet"
)

OUTPUT_DIRECTORY = PROJECT_ROOT / "outputs"

STRICT_AUDIT_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_safe_rollover_clause_audit_2027_2029_v3_deduplicated.csv"
)

VALUATION_READY_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_rollover_valuation_ready_2027_2029_v3.csv"
)

MANUAL_REVIEW_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_rollover_manual_review_2027_2029_v3.csv"
)

METADATA_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_safe_rollover_clause_audit_metadata_v3.json"
)


SAFE_TIER = "safe_linked_rollover_candidate"

MODELED_YEARS = {
    2027,
    2028,
    2029,
}

TEAM_ALIASES = {
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
    "los angeles clippers": "LAC",
    "l.a. clippers": "LAC",
    "la clippers": "LAC",
    "los angeles lakers": "LAL",
    "l.a. lakers": "LAL",
    "la lakers": "LAL",
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
}

ROUND_WORDS = {
    "first": 1,
    "1st": 1,
    "second": 2,
    "2nd": 2,
}

LIST_COLUMNS = [
    "mentioned_teams_list",
    "mentioned_years_list",
    "mentioned_rounds_list",
    "beneficiary_teams_list",
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

    if value is None:
        return []

    if isinstance(
        value,
        float,
    ) and np.isnan(
        value
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


def team_code(
    value: str,
) -> str:
    normalized = (
        clean_text(
            value
        )
        .lower()
        .replace(
            "’",
            "'",
        )
        .replace(
            "s'",
            "",
        )
        .replace(
            "'s",
            "",
        )
        .strip()
    )

    return TEAM_ALIASES.get(
        normalized,
        "",
    )


def detect_onward_chain(
    text: str,
) -> bool:
    lower = text.lower()

    patterns = [
        r"\bmay\s+convey\b",
        r"\bwhich\s+may\s+then\s+convey\b",
        r"\bsee\s+.+?\s+incoming\b",
        r"\bsubject\s+to\s+swap\b",
        r"\bmost\s+favorable\b",
        r"\bleast\s+favorable\b",
    ]

    return any(
        re.search(
            pattern,
            lower,
            re.IGNORECASE,
        )
        is not None
        for pattern in patterns
    )


def protection_ladder(
    text: str,
) -> list[dict[str, Any]]:
    rows = []

    pattern = re.compile(
        (
            r"protected\s+for\s+selections?\s+"
            r"(\d+)\s*[-–]\s*(\d+)"
            r"(?:\s+in\s+(20[2-3]\d))?"
        ),
        re.IGNORECASE,
    )

    for match in pattern.finditer(
        text
    ):
        rows.append(
            {
                "start_pick": int(
                    match.group(
                        1
                    )
                ),
                "end_pick": int(
                    match.group(
                        2
                    )
                ),
                "draft_year": (
                    int(
                        match.group(
                            3
                        )
                    )
                    if match.group(
                        3
                    )
                    else None
                ),
            }
        )

    compact_pattern = re.compile(
        (
            r"(\d+)\s*[-–]\s*(\d+)\s+in\s+(20[2-3]\d)"
        ),
        re.IGNORECASE,
    )

    for match in compact_pattern.finditer(
        text
    ):
        candidate = {
            "start_pick": int(
                match.group(
                    1
                )
            ),
            "end_pick": int(
                match.group(
                    2
                )
            ),
            "draft_year": int(
                match.group(
                    3
                )
            ),
        }

        if candidate not in rows:
            rows.append(
                candidate
            )

    # full_claim_text can contain the same source clause more than
    # once because it combines the heading, transaction text, and
    # full obligation text. Count unique protection stages rather
    # than repeated textual copies.
    unique_rows = []

    seen = set()

    for row in rows:
        key = (
            row[
                "start_pick"
            ],
            row[
                "end_pick"
            ],
            row[
                "draft_year"
            ],
        )

        if key in seen:
            continue

        seen.add(
            key
        )

        unique_rows.append(
            row
        )

    return unique_rows


def parse_explicit_instead_convey(
    text: str,
    current_origin: str,
) -> dict[str, Any] | None:
    pattern = re.compile(
        (
            r"(?:will|shall)\s+instead\s+convey\s+"
            r"(?:(?P<owner>[A-Za-z.\s]+?)'s|its)\s+"
            r"(?P<year>20[2-3]\d)\s+"
            r"(?P<round>first|second|1st|2nd)"
            r"[\s-]+round\s+pick\s+to\s+"
            r"(?P<beneficiary>[A-Za-z.\s]+?)"
            r"(?:\s*\[|;|\.|,|$)"
        ),
        re.IGNORECASE,
    )

    match = pattern.search(
        text
    )

    if match is None:
        return None

    owner_text = clean_text(
        match.group(
            "owner"
        )
    )

    owner_code = (
        team_code(
            owner_text
        )
        if owner_text
        else current_origin
    )

    beneficiary_text = clean_text(
        match.group(
            "beneficiary"
        )
    )

    return {
        "fallback_parse_method": (
            "explicit_instead_convey"
        ),
        "fallback_originating_team": (
            owner_code
        ),
        "fallback_originating_team_text": (
            owner_text
        ),
        "fallback_draft_year": int(
            match.group(
                "year"
            )
        ),
        "fallback_round_number": (
            ROUND_WORDS[
                match.group(
                    "round"
                ).lower()
            ]
        ),
        "fallback_beneficiary_team": (
            team_code(
                beneficiary_text
            )
        ),
        "fallback_beneficiary_team_text": (
            beneficiary_text
        ),
        "fallback_protection_type": (
            "unprotected"
        ),
        "fallback_protection_start_pick": (
            np.nan
        ),
        "fallback_protection_end_pick": (
            np.nan
        ),
    }


def parse_same_origin_unprotected_rollover(
    text: str,
    current_origin: str,
    current_round: int,
    beneficiary: str,
) -> dict[str, Any] | None:
    pattern = re.compile(
        r"\bunprotected\s+in\s+(20[2-3]\d)\b",
        re.IGNORECASE,
    )

    match = pattern.search(
        text
    )

    if match is None:
        return None

    return {
        "fallback_parse_method": (
            "same_origin_unprotected_rollover"
        ),
        "fallback_originating_team": (
            current_origin
        ),
        "fallback_originating_team_text": (
            current_origin
        ),
        "fallback_draft_year": int(
            match.group(
                1
            )
        ),
        "fallback_round_number": (
            current_round
        ),
        "fallback_beneficiary_team": (
            beneficiary
        ),
        "fallback_beneficiary_team_text": (
            beneficiary
        ),
        "fallback_protection_type": (
            "unprotected"
        ),
        "fallback_protection_start_pick": (
            np.nan
        ),
        "fallback_protection_end_pick": (
            np.nan
        ),
    }


def parse_terminal_second_round_fallback(
    text: str,
    current_origin: str,
    beneficiary: str,
) -> dict[str, Any] | None:
    pattern = re.compile(
        (
            r"(?:will|shall)\s+instead\s+convey\s+"
            r"(?:its|[A-Za-z.\s]+?'s)\s+"
            r"(?P<year>20[2-3]\d)\s+"
            r"(?P<round>second|2nd)[\s-]+round\s+pick\s+to\s+"
            r"(?P<beneficiary>[A-Za-z.\s]+?)"
            r"(?:;|\.|\[|,|$)"
        ),
        re.IGNORECASE,
    )

    match = pattern.search(
        text
    )

    if match is None:
        return None

    beneficiary_text = clean_text(
        match.group(
            "beneficiary"
        )
    )

    return {
        "fallback_parse_method": (
            "terminal_second_round_fallback"
        ),
        "fallback_originating_team": (
            current_origin
        ),
        "fallback_originating_team_text": (
            current_origin
        ),
        "fallback_draft_year": int(
            match.group(
                "year"
            )
        ),
        "fallback_round_number": 2,
        "fallback_beneficiary_team": (
            team_code(
                beneficiary_text
            )
            or beneficiary
        ),
        "fallback_beneficiary_team_text": (
            beneficiary_text
        ),
        "fallback_protection_type": (
            "unprotected"
        ),
        "fallback_protection_start_pick": (
            np.nan
        ),
        "fallback_protection_end_pick": (
            np.nan
        ),
    }


def load_inputs() -> tuple[
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
]:
    for path in [
        CLAIM_NODES_PATH,
        REFINED_GROUPS_PATH,
        VALUATIONS_PATH,
    ]:
        if not path.exists():
            raise FileNotFoundError(
                "Required strict-audit input was not found:\n"
                f"{path}"
            )

    nodes = normalize_columns(
        pd.read_parquet(
            CLAIM_NODES_PATH
        )
    )

    groups = normalize_columns(
        pd.read_parquet(
            REFINED_GROUPS_PATH
        )
    )

    valuations = normalize_columns(
        pd.read_parquet(
            VALUATIONS_PATH
        )
    )

    require_columns(
        nodes,
        [
            "obligation_group_id",
            "claim_id",
            "asset_key",
            "draft_year",
            "round_number",
            "originating_team",
            "protection_type",
            "protection_start_pick",
            "protection_end_pick",
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
            "refined_candidate_resolution_tier",
        ],
        "Refined dependency groups",
    )

    require_columns(
        valuations,
        [
            "claim_id",
            "valuation_status",
            "conveyance_probability",
            "retention_probability",
            "expected_transferred_value_score",
            "expected_retained_value_score",
        ],
        "Claim valuations",
    )

    for column in LIST_COLUMNS:
        nodes[
            column
        ] = nodes[
            column
        ].map(
            parse_json_list
        )

    return (
        nodes,
        groups,
        valuations,
    )


def audit_claim(
    node: pd.Series,
    valuation: pd.Series,
) -> dict[str, Any]:
    text = clean_text(
        node[
            "full_claim_text"
        ]
    )

    current_origin = str(
        node[
            "originating_team"
        ]
    )

    current_year = int(
        node[
            "draft_year"
        ]
    )

    current_round = int(
        node[
            "round_number"
        ]
    )

    beneficiaries = [
        str(
            value
        )
        for value in node[
            "beneficiary_teams_list"
        ]
    ]

    beneficiary = (
        beneficiaries[
            0
        ]
        if len(
            beneficiaries
        )
        == 1
        else ""
    )

    ladder = protection_ladder(
        text
    )

    onward_chain = detect_onward_chain(
        text
    )

    explicit_fallback = (
        parse_explicit_instead_convey(
            text=text,
            current_origin=current_origin,
        )
    )

    same_origin_rollover = (
        parse_same_origin_unprotected_rollover(
            text=text,
            current_origin=current_origin,
            current_round=current_round,
            beneficiary=beneficiary,
        )
    )

    terminal_second = (
        parse_terminal_second_round_fallback(
            text=text,
            current_origin=current_origin,
            beneficiary=beneficiary,
        )
    )

    fallback = (
        explicit_fallback
        or same_origin_rollover
        or terminal_second
    )

    reasons = []

    if fallback is None:
        reasons.append(
            "fallback_asset_not_unambiguously_parsed"
        )

    if beneficiary == "":
        reasons.append(
            "current_beneficiary_not_unique"
        )

    if onward_chain:
        reasons.append(
            "onward_conveyance_or_pool_language_present"
        )

    if len(
        ladder
    ) > 1:
        reasons.append(
            "multi_year_protection_ladder"
        )

    if fallback is not None:
        if not fallback[
            "fallback_originating_team"
        ]:
            reasons.append(
                "fallback_originating_team_not_parsed"
            )

        if not fallback[
            "fallback_beneficiary_team"
        ]:
            reasons.append(
                "fallback_beneficiary_not_parsed"
            )

        if fallback[
            "fallback_draft_year"
        ] not in MODELED_YEARS:
            reasons.append(
                "fallback_year_outside_simulation_bank"
            )

        if fallback[
            "fallback_round_number"
        ] not in {
            1,
            2,
        }:
            reasons.append(
                "fallback_round_not_parsed"
            )

    automatic_ready = (
        fallback is not None
        and not reasons
    )

    row = {
        "obligation_group_id": (
            node[
                "obligation_group_id"
            ]
        ),
        "claim_id": (
            node[
                "claim_id"
            ]
        ),
        "asset_key": (
            node[
                "asset_key"
            ]
        ),
        "current_originating_team": (
            current_origin
        ),
        "current_beneficiary_team": (
            beneficiary
        ),
        "current_draft_year": (
            current_year
        ),
        "current_round_number": (
            current_round
        ),
        "current_protection_type": (
            node[
                "protection_type"
            ]
        ),
        "current_protection_start_pick": numeric_value(
            node[
                "protection_start_pick"
            ]
        ),
        "current_protection_end_pick": numeric_value(
            node[
                "protection_end_pick"
            ]
        ),
        "protection_ladder_json": json.dumps(
            ladder
        ),
        "protection_ladder_stage_count": len(
            ladder
        ),
        "onward_chain_language_detected": (
            onward_chain
        ),
        "strict_automatic_valuation_ready": (
            automatic_ready
        ),
        "strict_exclusion_reasons": "|".join(
            reasons
        ),
        "existing_valuation_status": (
            valuation[
                "valuation_status"
            ]
        ),
        "current_conveyance_probability": numeric_value(
            valuation[
                "conveyance_probability"
            ]
        ),
        "current_retention_probability": numeric_value(
            valuation[
                "retention_probability"
            ]
        ),
        "current_expected_transferred_value_score": numeric_value(
            valuation[
                "expected_transferred_value_score"
            ]
        ),
        "current_expected_retained_value_score": numeric_value(
            valuation[
                "expected_retained_value_score"
            ]
        ),
        "full_claim_text": (
            text
        ),
    }

    fallback_defaults = {
        "fallback_parse_method": "",
        "fallback_originating_team": "",
        "fallback_originating_team_text": "",
        "fallback_draft_year": np.nan,
        "fallback_round_number": np.nan,
        "fallback_beneficiary_team": "",
        "fallback_beneficiary_team_text": "",
        "fallback_protection_type": "",
        "fallback_protection_start_pick": np.nan,
        "fallback_protection_end_pick": np.nan,
    }

    row.update(
        fallback_defaults
    )

    if fallback is not None:
        row.update(
            fallback
        )

    return row


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


def main() -> None:
    OUTPUT_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    print("=" * 80)
    print("FUTURE NBA STRICT ROLLOVER CLAUSE AUDIT V3")
    print("=" * 80)
    print(
        f"Script version: {SCRIPT_VERSION}"
    )
    print()

    nodes, groups, valuations = load_inputs()

    safe_group_ids = set(
        groups.loc[
            groups[
                "refined_candidate_resolution_tier"
            ].eq(
                SAFE_TIER
            ),
            "obligation_group_id",
        ].astype(
            str
        )
    )

    safe_nodes = nodes.loc[
        nodes[
            "obligation_group_id"
        ].astype(
            str
        ).isin(
            safe_group_ids
        )
    ].copy()

    valuation_lookup = (
        valuations.drop_duplicates(
            subset=[
                "claim_id"
            ]
        )
        .set_index(
            "claim_id"
        )
    )

    rows = []

    for _, node in safe_nodes.iterrows():
        claim_id = str(
            node[
                "claim_id"
            ]
        )

        if claim_id not in valuation_lookup.index:
            raise ValueError(
                "Missing valuation row for claim: "
                f"{claim_id}"
            )

        rows.append(
            audit_claim(
                node=node,
                valuation=valuation_lookup.loc[
                    claim_id
                ],
            )
        )

    audit = pd.DataFrame(
        rows
    ).sort_values(
        [
            "strict_automatic_valuation_ready",
            "obligation_group_id",
        ],
        ascending=[
            False,
            True,
        ],
    ).reset_index(
        drop=True
    )

    ready = audit.loc[
        audit[
            "strict_automatic_valuation_ready"
        ]
    ].copy()

    manual = audit.loc[
        ~audit[
            "strict_automatic_valuation_ready"
        ]
    ].copy()

    audit.to_csv(
        STRICT_AUDIT_PATH,
        index=False,
    )

    ready.to_csv(
        VALUATION_READY_PATH,
        index=False,
    )

    manual.to_csv(
        MANUAL_REVIEW_PATH,
        index=False,
    )

    metadata = {
        "script_version": (
            SCRIPT_VERSION
        ),
        "created_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "rollover_candidates_loaded": len(
            audit
        ),
        "strict_automatic_valuation_ready": len(
            ready
        ),
        "strict_manual_review": len(
            manual
        ),
        "strict_policy": [
            (
                "The fallback originating team, year, round, and "
                "beneficiary must be parsed from the actual clause."
            ),
            (
                "Multi-year protection ladders are not treated as "
                "simple two-stage rollovers."
            ),
            (
                "Onward-conveyance, pool, or chain language blocks "
                "automatic valuation."
            ),
            (
                "Third-party fallback picks are allowed only when the "
                "specific originating team and pick are explicit."
            ),
        ],
        "output_files": {
            "strict_audit": str(
                STRICT_AUDIT_PATH
            ),
            "valuation_ready": str(
                VALUATION_READY_PATH
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
    print("STRICT ROLLOVER AUDIT V3 CREATED")
    print("=" * 80)
    print(
        f"Candidates loaded: "
        f"{len(audit):,}"
    )
    print(
        "Ready for strict automatic valuation: "
        f"{len(ready):,}"
    )
    print(
        f"Blocked for manual review: "
        f"{len(manual):,}"
    )
    print()

    display_columns = [
        "obligation_group_id",
        "claim_id",
        "current_originating_team",
        "current_beneficiary_team",
        "current_draft_year",
        "current_protection_type",
        "current_protection_start_pick",
        "current_protection_end_pick",
        "fallback_parse_method",
        "fallback_originating_team",
        "fallback_draft_year",
        "fallback_round_number",
        "fallback_beneficiary_team",
        "fallback_protection_type",
        "protection_ladder_stage_count",
        "onward_chain_language_detected",
        "strict_automatic_valuation_ready",
        "strict_exclusion_reasons",
    ]

    print("STRICT ROLLOVER SUMMARY")
    print(
        audit[
            display_columns
        ].to_string(
            index=False
        )
    )
    print()

    print("FULL CLAIM TEXT")
    for row in audit.itertuples(
        index=False
    ):
        print("-" * 80)
        print(
            f"{row.obligation_group_id} | "
            f"{row.claim_id}"
        )
        print(
            textwrap.fill(
                row.full_claim_text,
                width=110,
            )
        )
        print()

    print("SAVED FILES")
    print(STRICT_AUDIT_PATH)
    print(VALUATION_READY_PATH)
    print(MANUAL_REVIEW_PATH)
    print(METADATA_PATH)


if __name__ == "__main__":
    main()