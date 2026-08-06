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


SCRIPT_VERSION = "future-pick-safe-rollover-clause-audit-v1-2026-08-04"

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

AUDIT_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_safe_rollover_clause_audit_2027_2029_v1.csv"
)

OVERRIDE_TEMPLATE_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_safe_rollover_clause_overrides_template_2027_2029_v1.csv"
)

METADATA_PATH = (
    OUTPUT_DIRECTORY
    / "future_pick_safe_rollover_clause_audit_metadata_v1.json"
)


MODELED_YEARS = {
    2027,
    2028,
    2029,
}

SAFE_TIER = "safe_linked_rollover_candidate"

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


def boolean_value(
    value: Any,
) -> bool:
    if isinstance(
        value,
        bool,
    ):
        return value

    return str(
        value
    ).strip().lower() in {
        "true",
        "1",
        "yes",
        "y",
    }


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


def year_near_phrase(
    text: str,
    year: int,
    phrases: list[str],
    window: int = 120,
) -> bool:
    lower = text.lower()

    year_matches = list(
        re.finditer(
            rf"\b{year}\b",
            lower,
        )
    )

    for match in year_matches:
        start = max(
            0,
            match.start()
            - window,
        )

        end = min(
            len(
                lower
            ),
            match.end()
            + window,
        )

        context = lower[
            start:end
        ]

        if any(
            phrase in context
            for phrase in phrases
        ):
            return True

    return False


def detect_fallback_round(
    text: str,
    fallback_year: int,
    default_round: int,
) -> tuple[
    int,
    bool,
]:
    lower = text.lower()

    patterns = [
        (
            1,
            re.compile(
                rf"\b{fallback_year}\b[^.;]{{0,100}}"
                r"\b(?:first|1st)[\s-]+round\b",
                re.IGNORECASE,
            ),
        ),
        (
            1,
            re.compile(
                r"\b(?:first|1st)[\s-]+round\b"
                rf"[^.;]{{0,100}}\b{fallback_year}\b",
                re.IGNORECASE,
            ),
        ),
        (
            2,
            re.compile(
                rf"\b{fallback_year}\b[^.;]{{0,100}}"
                r"\b(?:second|2nd)[\s-]+round\b",
                re.IGNORECASE,
            ),
        ),
        (
            2,
            re.compile(
                r"\b(?:second|2nd)[\s-]+round\b"
                rf"[^.;]{{0,100}}\b{fallback_year}\b",
                re.IGNORECASE,
            ),
        ),
    ]

    for round_number, pattern in patterns:
        if pattern.search(
            lower
        ):
            return (
                round_number,
                True,
            )

    return (
        int(
            default_round
        ),
        False,
    )


def detect_fallback_protection(
    text: str,
    fallback_year: int,
) -> dict[str, Any]:
    lower = text.lower()

    contexts = []

    for match in re.finditer(
        rf"\b{fallback_year}\b",
        lower,
    ):
        start = max(
            0,
            match.start()
            - 180,
        )

        end = min(
            len(
                lower
            ),
            match.end()
            + 180,
        )

        contexts.append(
            lower[
                start:end
            ]
        )

    context = " ".join(
        contexts
    )

    unprotected = bool(
        re.search(
            r"\bunprotected\b",
            context,
            re.IGNORECASE,
        )
    )

    lottery = bool(
        re.search(
            r"\blottery[\s-]*protected\b",
            context,
            re.IGNORECASE,
        )
    )

    top_n_match = re.search(
        r"\btop[\s-]*(\d+)[\s-]*protected\b",
        context,
        re.IGNORECASE,
    )

    range_match = re.search(
        (
            r"\bprotected\s+(?:for\s+)?(?:selections?\s+)?"
            r"(\d+)\s*(?:through|to|-|–)\s*(\d+)"
        ),
        context,
        re.IGNORECASE,
    )

    if unprotected:
        return {
            "fallback_protection_type_detected": (
                "unprotected"
            ),
            "fallback_protection_start_detected": (
                np.nan
            ),
            "fallback_protection_end_detected": (
                np.nan
            ),
            "fallback_protection_parse_success": (
                True
            ),
        }

    if lottery:
        return {
            "fallback_protection_type_detected": (
                "lottery"
            ),
            "fallback_protection_start_detected": (
                1.0
            ),
            "fallback_protection_end_detected": (
                16.0
            ),
            "fallback_protection_parse_success": (
                True
            ),
        }

    if top_n_match:
        return {
            "fallback_protection_type_detected": (
                "top_n"
            ),
            "fallback_protection_start_detected": (
                1.0
            ),
            "fallback_protection_end_detected": float(
                top_n_match.group(
                    1
                )
            ),
            "fallback_protection_parse_success": (
                True
            ),
        }

    if range_match:
        return {
            "fallback_protection_type_detected": (
                "protected_range"
            ),
            "fallback_protection_start_detected": float(
                range_match.group(
                    1
                )
            ),
            "fallback_protection_end_detected": float(
                range_match.group(
                    2
                )
            ),
            "fallback_protection_parse_success": (
                True
            ),
        }

    return {
        "fallback_protection_type_detected": (
            "not_explicitly_parsed"
        ),
        "fallback_protection_start_detected": (
            np.nan
        ),
        "fallback_protection_end_detected": (
            np.nan
        ),
        "fallback_protection_parse_success": (
            False
        ),
    }


def detect_clause_flags(
    text: str,
    fallback_year: int,
) -> dict[str, bool]:
    lower = text.lower()

    fallback_marker = year_near_phrase(
        text=text,
        year=fallback_year,
        phrases=[
            "instead convey",
            "will convey",
            "shall convey",
            "unprotected",
            "converts to",
            "becomes",
            "deferred to",
            "roll over",
            "rolls over",
            "if not conveyed",
            "if the pick does not convey",
            "if this pick does not convey",
        ],
    )

    nonconveyance_trigger = bool(
        re.search(
            (
                r"\bif\b[^.;]{0,160}\b"
                r"(?:does\s+not|doesn't|is\s+not|not)\s+convey"
            ),
            lower,
            re.IGNORECASE,
        )
        or re.search(
            r"\bif\s+not\s+conveyed\b",
            lower,
            re.IGNORECASE,
        )
    )

    extinguishment = bool(
        re.search(
            r"\b(?:obligation\s+)?(?:is|will\s+be)\s+extinguished\b",
            lower,
            re.IGNORECASE,
        )
    )

    conversion_to_seconds = bool(
        re.search(
            (
                r"\b(?:converts?|becomes?)\b[^.;]{0,140}"
                r"\bsecond[\s-]+round\b"
            ),
            lower,
            re.IGNORECASE,
        )
    )

    return {
        "fallback_clause_marker_detected": (
            fallback_marker
        ),
        "nonconveyance_trigger_detected": (
            nonconveyance_trigger
        ),
        "extinguishment_language_detected": (
            extinguishment
        ),
        "conversion_to_second_round_detected": (
            conversion_to_seconds
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
                "Required rollover-audit input was not found:\n"
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
            "swap_flag",
            "favorability_pool_flag",
            "multiple_claim_rows_flag",
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
            "claim_count_recomputed",
            "unique_asset_count_recomputed",
        ],
        "Refined dependency groups",
    )

    require_columns(
        valuations,
        [
            "claim_id",
            "valuation_status",
            "expected_transferred_value_score",
            "expected_retained_value_score",
            "conveyance_probability",
            "retention_probability",
        ],
        "Pick claim valuations",
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


def build_audit_rows(
    nodes: pd.DataFrame,
    groups: pd.DataFrame,
    valuations: pd.DataFrame,
) -> pd.DataFrame:
    safe_groups = groups.loc[
        groups[
            "refined_candidate_resolution_tier"
        ].eq(
            SAFE_TIER
        )
    ].copy()

    if safe_groups.empty:
        return pd.DataFrame()

    valuation_subset = valuations[
        [
            "claim_id",
            "valuation_status",
            "expected_transferred_value_score",
            "expected_retained_value_score",
            "conveyance_probability",
            "retention_probability",
        ]
    ].drop_duplicates(
        subset=[
            "claim_id"
        ]
    )

    rows = []

    for group in safe_groups.itertuples(
        index=False
    ):
        group_nodes = nodes.loc[
            nodes[
                "obligation_group_id"
            ].eq(
                group.obligation_group_id
            )
        ].copy()

        if len(
            group_nodes
        ) != 1:
            raise ValueError(
                "A safe rollover group no longer has exactly one claim: "
                f"{group.obligation_group_id}"
            )

        node = group_nodes.iloc[
            0
        ]

        claim_id = str(
            node[
                "claim_id"
            ]
        )

        valuation_match = valuation_subset.loc[
            valuation_subset[
                "claim_id"
            ].eq(
                claim_id
            )
        ]

        if len(
            valuation_match
        ) != 1:
            raise ValueError(
                "Expected exactly one valuation row for claim: "
                f"{claim_id}"
            )

        valuation = valuation_match.iloc[
            0
        ]

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

        mentioned_years = sorted(
            {
                int(
                    value
                )
                for value in node[
                    "mentioned_years_list"
                ]
            }
        )

        fallback_years = [
            year
            for year in mentioned_years
            if year
            != current_year
        ]

        fallback_year = (
            fallback_years[
                0
            ]
            if len(
                fallback_years
            )
            == 1
            else np.nan
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

        full_text = clean_text(
            node[
                "full_claim_text"
            ]
        )

        if np.isfinite(
            fallback_year
        ):
            fallback_round, fallback_round_explicit = (
                detect_fallback_round(
                    text=full_text,
                    fallback_year=int(
                        fallback_year
                    ),
                    default_round=current_round,
                )
            )

            fallback_protection = (
                detect_fallback_protection(
                    text=full_text,
                    fallback_year=int(
                        fallback_year
                    ),
                )
            )

            clause_flags = detect_clause_flags(
                text=full_text,
                fallback_year=int(
                    fallback_year
                ),
            )
        else:
            fallback_round = np.nan

            fallback_round_explicit = False

            fallback_protection = {
                "fallback_protection_type_detected": (
                    "not_available"
                ),
                "fallback_protection_start_detected": (
                    np.nan
                ),
                "fallback_protection_end_detected": (
                    np.nan
                ),
                "fallback_protection_parse_success": (
                    False
                ),
            }

            clause_flags = {
                "fallback_clause_marker_detected": (
                    False
                ),
                "nonconveyance_trigger_detected": (
                    False
                ),
                "extinguishment_language_detected": (
                    False
                ),
                "conversion_to_second_round_detected": (
                    False
                ),
            }

        auto_ready = (
            len(
                fallback_years
            )
            == 1
            and int(
                fallback_year
            )
            in MODELED_YEARS
            and beneficiary
            != ""
            and str(
                node[
                    "protection_type"
                ]
            )
            != "none_detected"
            and np.isfinite(
                numeric_value(
                    node[
                        "protection_start_pick"
                    ]
                )
            )
            and np.isfinite(
                numeric_value(
                    node[
                        "protection_end_pick"
                    ]
                )
            )
            and clause_flags[
                "fallback_clause_marker_detected"
            ]
            and fallback_protection[
                "fallback_protection_parse_success"
            ]
            and not clause_flags[
                "extinguishment_language_detected"
            ]
            and not boolean_value(
                node[
                    "swap_flag"
                ]
            )
            and not boolean_value(
                node[
                    "favorability_pool_flag"
                ]
            )
            and not boolean_value(
                node[
                    "multiple_claim_rows_flag"
                ]
            )
        )

        reasons = []

        if len(
            fallback_years
        ) != 1:
            reasons.append(
                "fallback_year_not_unique"
            )

        if (
            np.isfinite(
                fallback_year
            )
            and int(
                fallback_year
            )
            not in MODELED_YEARS
        ):
            reasons.append(
                "fallback_year_outside_simulation_bank"
            )

        if beneficiary == "":
            reasons.append(
                "beneficiary_not_unique"
            )

        if str(
            node[
                "protection_type"
            ]
        ) == "none_detected":
            reasons.append(
                "current_protection_not_parsed"
            )

        if not clause_flags[
            "fallback_clause_marker_detected"
        ]:
            reasons.append(
                "fallback_clause_marker_not_detected"
            )

        if not fallback_protection[
            "fallback_protection_parse_success"
        ]:
            reasons.append(
                "fallback_protection_not_explicitly_parsed"
            )

        if clause_flags[
            "extinguishment_language_detected"
        ]:
            reasons.append(
                "extinguishment_language_present"
            )

        row = {
            "obligation_group_id": (
                group.obligation_group_id
            ),
            "claim_id": (
                claim_id
            ),
            "asset_key": (
                node[
                    "asset_key"
                ]
            ),
            "originating_team": (
                node[
                    "originating_team"
                ]
            ),
            "candidate_beneficiary_team": (
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
            "current_protection_start_pick": (
                numeric_value(
                    node[
                        "protection_start_pick"
                    ]
                )
            ),
            "current_protection_end_pick": (
                numeric_value(
                    node[
                        "protection_end_pick"
                    ]
                )
            ),
            "fallback_draft_year_detected": (
                fallback_year
            ),
            "fallback_round_number_detected": (
                fallback_round
            ),
            "fallback_round_explicitly_detected": (
                fallback_round_explicit
            ),
            **fallback_protection,
            **clause_flags,
            "existing_valuation_status": (
                valuation[
                    "valuation_status"
                ]
            ),
            "existing_current_year_conveyance_probability": (
                numeric_value(
                    valuation[
                        "conveyance_probability"
                    ]
                )
            ),
            "existing_current_year_retention_probability": (
                numeric_value(
                    valuation[
                        "retention_probability"
                    ]
                )
            ),
            "existing_current_year_transferred_value_score": (
                numeric_value(
                    valuation[
                        "expected_transferred_value_score"
                    ]
                )
            ),
            "existing_current_year_retained_value_score": (
                numeric_value(
                    valuation[
                        "expected_retained_value_score"
                    ]
                )
            ),
            "automatic_rollover_valuation_ready": (
                auto_ready
            ),
            "audit_exclusion_reasons": "|".join(
                reasons
            ),
            "pick_heading": clean_text(
                node[
                    "pick_heading"
                ]
            ),
            "transaction_text": clean_text(
                node[
                    "transaction_text"
                ]
            ),
            "full_claim_text": (
                full_text
            ),
        }

        rows.append(
            row
        )

    return pd.DataFrame(
        rows
    ).sort_values(
        [
            "automatic_rollover_valuation_ready",
            "obligation_group_id",
        ],
        ascending=[
            False,
            True,
        ],
    ).reset_index(
        drop=True
    )


def build_override_template(
    audit: pd.DataFrame,
) -> pd.DataFrame:
    source_columns = [
        "obligation_group_id",
        "claim_id",
        "asset_key",
        "originating_team",
        "candidate_beneficiary_team",
        "current_draft_year",
        "current_round_number",
        "current_protection_type",
        "current_protection_start_pick",
        "current_protection_end_pick",
        "fallback_draft_year_detected",
        "fallback_round_number_detected",
        "fallback_protection_type_detected",
        "fallback_protection_start_detected",
        "fallback_protection_end_detected",
        "automatic_rollover_valuation_ready",
        "audit_exclusion_reasons",
        "full_claim_text",
    ]

    template = audit[
        source_columns
    ].copy()

    manual_columns = [
        "confirmed_beneficiary_team",
        "confirmed_current_protection_type",
        "confirmed_current_protection_start_pick",
        "confirmed_current_protection_end_pick",
        "confirmed_fallback_draft_year",
        "confirmed_fallback_round_number",
        "confirmed_fallback_protection_type",
        "confirmed_fallback_protection_start_pick",
        "confirmed_fallback_protection_end_pick",
        "confirmed_obligation_extinguishes",
        "confirmed_conversion_description",
        "source_verified",
        "review_notes",
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
    print("FUTURE NBA SAFE ROLLOVER CLAUSE AUDIT")
    print("=" * 80)
    print(
        f"Script version: {SCRIPT_VERSION}"
    )
    print()

    nodes, groups, valuations = load_inputs()

    audit = build_audit_rows(
        nodes=nodes,
        groups=groups,
        valuations=valuations,
    )

    if audit.empty:
        raise ValueError(
            "No safe rollover candidates were found."
        )

    audit.to_csv(
        AUDIT_PATH,
        index=False,
    )

    build_override_template(
        audit
    ).to_csv(
        OVERRIDE_TEMPLATE_PATH,
        index=False,
    )

    ready_count = int(
        audit[
            "automatic_rollover_valuation_ready"
        ].sum()
    )

    metadata = {
        "script_version": (
            SCRIPT_VERSION
        ),
        "created_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "safe_rollover_candidates_loaded": len(
            audit
        ),
        "automatic_rollover_valuation_ready": (
            ready_count
        ),
        "manual_clause_review_required": (
            len(
                audit
            )
            - ready_count
        ),
        "readiness_policy": [
            (
                "Exactly one modeled fallback draft year must be "
                "identified."
            ),
            (
                "The beneficiary and current protection must be "
                "unambiguous."
            ),
            (
                "The fallback protection must be explicitly parsed "
                "as unprotected, lottery-protected, top-N protected, "
                "or selection-range protected."
            ),
            (
                "Swap, favorability-pool, duplicate-claim, and "
                "extinguishment language prevents automatic valuation."
            ),
        ],
        "output_files": {
            "rollover_clause_audit": str(
                AUDIT_PATH
            ),
            "manual_override_template": str(
                OVERRIDE_TEMPLATE_PATH
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
    print("ROLLOVER CLAUSE AUDIT CREATED")
    print("=" * 80)
    print(
        f"Safe rollover candidates loaded: "
        f"{len(audit):,}"
    )
    print(
        "Ready for automatic rollover valuation: "
        f"{ready_count:,}"
    )
    print(
        "Still requiring clause review: "
        f"{len(audit) - ready_count:,}"
    )
    print()

    display_columns = [
        "obligation_group_id",
        "claim_id",
        "originating_team",
        "candidate_beneficiary_team",
        "current_draft_year",
        "current_protection_type",
        "current_protection_start_pick",
        "current_protection_end_pick",
        "fallback_draft_year_detected",
        "fallback_round_number_detected",
        "fallback_protection_type_detected",
        "automatic_rollover_valuation_ready",
        "audit_exclusion_reasons",
    ]

    print("ROLLOVER CANDIDATE SUMMARY")
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
            f"{row.claim_id} | "
            f"{row.originating_team} -> "
            f"{row.candidate_beneficiary_team}"
        )
        print(
            textwrap.fill(
                row.full_claim_text,
                width=110,
            )
        )
        print()

    print("SAVED FILES")
    print(AUDIT_PATH)
    print(OVERRIDE_TEMPLATE_PATH)
    print(METADATA_PATH)


if __name__ == "__main__":
    main()