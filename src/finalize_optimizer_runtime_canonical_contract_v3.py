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
    "optimizer-runtime-canonical-contract-v3-team-key-2026-08-04"
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIRECTORY = PROJECT_ROOT / "outputs"
PROCESSED_DIRECTORY = PROJECT_ROOT / "data" / "processed"

PLAYER_VALUE_PATH = (
    PROCESSED_DIRECTORY
    / "player_trade_market_value_layer_2026_27_v3.parquet"
)

V2_CONTRACT_PATH = (
    OUTPUT_DIRECTORY
    / "optimizer_runtime_canonical_contract_v2.csv"
)

V2_READINESS_PATH = (
    OUTPUT_DIRECTORY
    / "optimizer_runtime_canonical_contract_readiness_v2.csv"
)

TEAM_KEY_CANDIDATES_PATH = (
    OUTPUT_DIRECTORY
    / "optimizer_runtime_player_team_key_candidates_v3.csv"
)

CONTRACT_PATH = (
    OUTPUT_DIRECTORY
    / "optimizer_runtime_canonical_contract_v3.csv"
)

READINESS_PATH = (
    OUTPUT_DIRECTORY
    / "optimizer_runtime_canonical_contract_readiness_v3.csv"
)

METADATA_PATH = (
    OUTPUT_DIRECTORY
    / "optimizer_runtime_canonical_contract_metadata_v3.json"
)


NBA_TEAM_CODES = {
    "ATL",
    "BKN",
    "BOS",
    "CHA",
    "CHI",
    "CLE",
    "DAL",
    "DEN",
    "DET",
    "GSW",
    "HOU",
    "IND",
    "LAC",
    "LAL",
    "MEM",
    "MIA",
    "MIL",
    "MIN",
    "NOP",
    "NYK",
    "OKC",
    "ORL",
    "PHI",
    "PHX",
    "POR",
    "SAC",
    "SAS",
    "TOR",
    "UTA",
    "WAS",
}

NAME_EXCLUSION_PATTERNS = [
    r"score",
    r"delta",
    r"percentile",
    r"salary",
    r"value",
    r"fit",
    r"need",
    r"supply",
    r"retention",
    r"contribution",
    r"survival",
    r"market",
    r"proxy",
    r"method",
    r"flag",
    r"count",
    r"rank",
    r"tier",
]

VALUE_TOLERANCE = 1e-12


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


def normalize_name(
    value: Any,
) -> str:
    return (
        clean_text(value)
        .lower()
        .replace(" ", "_")
        .replace("-", "_")
    )


def json_safe(
    value: Any,
) -> Any:
    if isinstance(value, dict):
        return {
            str(key): json_safe(item)
            for key, item in value.items()
        }

    if isinstance(
        value,
        (
            list,
            tuple,
            set,
        ),
    ):
        return [
            json_safe(item)
            for item in value
        ]

    if isinstance(value, np.integer):
        return int(value)

    if isinstance(value, np.floating):
        return (
            None
            if np.isnan(value)
            else float(value)
        )

    if isinstance(value, float):
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


def parse_bool_series(
    series: pd.Series,
) -> pd.Series:
    if pd.api.types.is_bool_dtype(series):
        return series.fillna(False).astype(bool)

    return (
        series
        .fillna("")
        .astype(str)
        .str.strip()
        .str.lower()
        .isin(
            {
                "true",
                "1",
                "yes",
                "passed",
            }
        )
    )


def require_file(
    path: Path,
    label: str,
) -> None:
    if not path.exists():
        raise FileNotFoundError(
            f"Required {label} was not found:\n{path}"
        )


def name_prior_score(
    normalized_name: str,
) -> float:
    exact_scores = {
        "team_abbreviation": 200.0,
        "current_team_abbreviation": 195.0,
        "current_team": 190.0,
        "team": 185.0,
        "recent_team": 180.0,
        "player_team": 175.0,
        "team_abbr": 170.0,
    }

    if normalized_name in exact_scores:
        return exact_scores[normalized_name]

    score = 0.0

    if "team_abbreviation" in normalized_name:
        score += 150.0

    if normalized_name.endswith("_team"):
        score += 120.0

    if normalized_name.startswith("team_"):
        score += 90.0

    if "team" in normalized_name:
        score += 60.0

    if any(
        re.search(pattern, normalized_name)
        for pattern in NAME_EXCLUSION_PATTERNS
    ):
        score -= 120.0

    return score


def analyze_team_candidate(
    frame: pd.DataFrame,
    column: str,
) -> dict[str, Any]:
    series = frame[column]

    normalized_values = (
        series
        .dropna()
        .astype(str)
        .str.upper()
        .str.strip()
    )

    normalized_values = normalized_values.loc[
        normalized_values.ne("")
    ]

    non_null_count = int(
        len(normalized_values)
    )

    unique_values = sorted(
        set(normalized_values)
    )

    unique_count = len(unique_values)

    known_mask = normalized_values.isin(
        NBA_TEAM_CODES
    )

    three_letter_mask = normalized_values.str.fullmatch(
        r"[A-Z]{3}"
    )

    known_count = int(
        known_mask.sum()
    )

    three_letter_count = int(
        three_letter_mask.sum()
    )

    known_ratio = (
        known_count
        / non_null_count
        if non_null_count
        else 0.0
    )

    three_letter_ratio = (
        three_letter_count
        / non_null_count
        if non_null_count
        else 0.0
    )

    known_unique_values = sorted(
        set(unique_values)
        & NBA_TEAM_CODES
    )

    unknown_unique_values = sorted(
        set(unique_values)
        - NBA_TEAM_CODES
    )

    non_null_ratio = (
        non_null_count
        / len(frame)
        if len(frame)
        else 0.0
    )

    score = name_prior_score(
        normalize_name(column)
    )

    if known_ratio >= 0.999:
        score += 250.0
    elif known_ratio >= 0.95:
        score += 220.0
    elif known_ratio >= 0.80:
        score += 150.0
    elif known_ratio >= 0.50:
        score += 75.0

    if three_letter_ratio >= 0.99:
        score += 75.0
    elif three_letter_ratio >= 0.90:
        score += 50.0

    if len(known_unique_values) == 30:
        score += 200.0
    elif len(known_unique_values) >= 28:
        score += 140.0
    elif len(known_unique_values) >= 20:
        score += 80.0

    if 28 <= unique_count <= 32:
        score += 75.0
    elif unique_count > 50:
        score -= 100.0

    if non_null_ratio >= 0.99:
        score += 30.0
    elif non_null_ratio >= 0.90:
        score += 20.0

    candidate_passed = bool(
        non_null_count > 0
        and known_ratio >= 0.95
        and len(known_unique_values) >= 28
        and unique_count <= 35
    )

    return {
        "column_name": str(column),
        "normalized_column_name": normalize_name(
            column
        ),
        "dtype": str(series.dtype),
        "row_count": int(len(frame)),
        "non_null_count": non_null_count,
        "non_null_ratio": non_null_ratio,
        "unique_count": unique_count,
        "known_nba_team_value_count": known_count,
        "known_nba_team_value_ratio": known_ratio,
        "three_letter_value_ratio": (
            three_letter_ratio
        ),
        "known_nba_unique_team_count": len(
            known_unique_values
        ),
        "known_nba_unique_teams": "|".join(
            known_unique_values
        ),
        "unknown_unique_value_count": len(
            unknown_unique_values
        ),
        "unknown_unique_values": "|".join(
            unknown_unique_values[:50]
        ),
        "name_prior_score": name_prior_score(
            normalize_name(column)
        ),
        "team_key_candidate_score": score,
        "team_key_candidate_passed": (
            candidate_passed
        ),
    }


def build_candidate_table(
    frame: pd.DataFrame,
) -> pd.DataFrame:
    rows = [
        analyze_team_candidate(
            frame,
            str(column),
        )
        for column in frame.columns
    ]

    output = pd.DataFrame(rows)

    return output.sort_values(
        [
            "team_key_candidate_passed",
            "team_key_candidate_score",
            "known_nba_team_value_ratio",
            "known_nba_unique_team_count",
            "column_name",
        ],
        ascending=[
            False,
            False,
            False,
            False,
            True,
        ],
    ).reset_index(drop=True)


def select_team_key(
    candidates: pd.DataFrame,
) -> pd.Series:
    passing = candidates.loc[
        candidates[
            "team_key_candidate_passed"
        ]
    ].copy()

    if passing.empty:
        raise RuntimeError(
            "No player-team key candidate passed the data-based "
            "validation.\n\nTop candidates:\n"
            + candidates.head(20).to_string(
                index=False
            )
        )

    selected = passing.iloc[0]

    if (
        int(
            selected[
                "known_nba_unique_team_count"
            ]
        )
        < 28
        or float(
            selected[
                "known_nba_team_value_ratio"
            ]
        )
        < 0.95
    ):
        raise RuntimeError(
            "The highest-scoring team-key candidate did not meet the "
            "minimum NBA-team coverage requirements."
        )

    return selected


def patch_contract(
    contract: pd.DataFrame,
    selected_column: str,
) -> pd.DataFrame:
    output = contract.copy()

    required_columns = {
        "contract_branch",
        "contract_element",
        "artifact_role",
        "selected_column",
        "required",
        "resolved",
    }

    missing = sorted(
        required_columns
        - set(output.columns)
    )

    if missing:
        raise ValueError(
            "The V2 contract is missing required columns:\n"
            + "\n".join(missing)
        )

    mask = (
        output[
            "contract_branch"
        ]
        .fillna("")
        .astype(str)
        .eq(
            "shared_assets"
        )
        & output[
            "contract_element"
        ]
        .fillna("")
        .astype(str)
        .eq(
            "player_team_key"
        )
        & output[
            "artifact_role"
        ]
        .fillna("")
        .astype(str)
        .eq(
            "player_value_layer"
        )
    )

    if int(mask.sum()) != 1:
        raise RuntimeError(
            "Expected exactly one unresolved player-team-key contract "
            f"row, found {int(mask.sum())}."
        )

    output.loc[
        mask,
        "selected_column",
    ] = selected_column

    output.loc[
        mask,
        "resolved",
    ] = True

    output.loc[
        mask,
        "notes",
    ] = (
        "Resolved by data-based NBA team-code detection in V3."
    )

    return output


def build_readiness(
    *,
    v2_readiness: pd.DataFrame,
    contract: pd.DataFrame,
    selected: pd.Series,
    player_frame: pd.DataFrame,
) -> pd.DataFrame:
    v2 = v2_readiness.copy()

    if "passed" not in v2.columns:
        raise ValueError(
            "The V2 readiness table has no passed column."
        )

    v2[
        "passed"
    ] = parse_bool_series(
        v2[
            "passed"
        ]
    )

    preserved = v2.loc[
        ~v2[
            "check_name"
        ]
        .fillna("")
        .astype(str)
        .eq(
            "all_required_contract_elements_resolved"
        )
    ].copy()

    preserved[
        "source_validation_version"
    ] = "v2_preserved"

    required_mask = parse_bool_series(
        contract[
            "required"
        ]
    )

    resolved_mask = parse_bool_series(
        contract[
            "resolved"
        ]
    )

    required_rows = contract.loc[
        required_mask
    ].copy()

    required_resolved = resolved_mask.loc[
        required_mask
    ]

    selected_column = clean_text(
        selected[
            "column_name"
        ]
    )

    selected_values = (
        player_frame[
            selected_column
        ]
        .dropna()
        .astype(str)
        .str.upper()
        .str.strip()
    )

    selected_values = selected_values.loc[
        selected_values.ne("")
    ]

    known_unique = sorted(
        set(selected_values)
        & NBA_TEAM_CODES
    )

    unknown_unique = sorted(
        set(selected_values)
        - NBA_TEAM_CODES
    )

    new_checks = pd.DataFrame(
        [
            {
                "check_name": (
                    "player_team_key_selected"
                ),
                "observed_value": selected_column,
                "expected_value": "nonempty",
                "passed": bool(selected_column),
                "blocking_for_orchestrator": True,
                "source_validation_version": "v3",
            },
            {
                "check_name": (
                    "player_team_key_known_value_ratio"
                ),
                "observed_value": float(
                    selected[
                        "known_nba_team_value_ratio"
                    ]
                ),
                "expected_value": ">=0.95",
                "passed": bool(
                    float(
                        selected[
                            "known_nba_team_value_ratio"
                        ]
                    )
                    >= 0.95
                ),
                "blocking_for_orchestrator": True,
                "source_validation_version": "v3",
            },
            {
                "check_name": (
                    "player_team_key_unique_nba_teams"
                ),
                "observed_value": len(
                    known_unique
                ),
                "expected_value": 30,
                "passed": len(
                    known_unique
                )
                == 30,
                "blocking_for_orchestrator": True,
                "source_validation_version": "v3",
            },
            {
                "check_name": (
                    "player_team_key_unknown_values"
                ),
                "observed_value": len(
                    unknown_unique
                ),
                "expected_value": 0,
                "passed": len(
                    unknown_unique
                )
                == 0,
                "blocking_for_orchestrator": True,
                "source_validation_version": "v3",
            },
            {
                "check_name": (
                    "all_required_contract_elements_resolved"
                ),
                "observed_value": int(
                    required_resolved.sum()
                ),
                "expected_value": int(
                    len(required_rows)
                ),
                "passed": bool(
                    required_resolved.all()
                ),
                "blocking_for_orchestrator": True,
                "source_validation_version": "v3",
            },
        ]
    )

    return pd.concat(
        [
            preserved,
            new_checks,
        ],
        ignore_index=True,
        sort=False,
    )


def main() -> None:
    OUTPUT_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    require_file(
        PLAYER_VALUE_PATH,
        "player-value layer",
    )

    require_file(
        V2_CONTRACT_PATH,
        "V2 canonical contract",
    )

    require_file(
        V2_READINESS_PATH,
        "V2 canonical readiness table",
    )

    print("=" * 80)
    print("OPTIMIZER CANONICAL RUNTIME CONTRACT V3")
    print("=" * 80)
    print(f"Script version: {SCRIPT_VERSION}")
    print()

    player_frame = pd.read_parquet(
        PLAYER_VALUE_PATH
    )

    contract_v2 = pd.read_csv(
        V2_CONTRACT_PATH
    )

    readiness_v2 = pd.read_csv(
        V2_READINESS_PATH
    )

    candidates = build_candidate_table(
        player_frame
    )

    selected = select_team_key(
        candidates
    )

    selected_column = clean_text(
        selected[
            "column_name"
        ]
    )

    contract = patch_contract(
        contract_v2,
        selected_column,
    )

    readiness = build_readiness(
        v2_readiness=readiness_v2,
        contract=contract,
        selected=selected,
        player_frame=player_frame,
    )

    candidates.to_csv(
        TEAM_KEY_CANDIDATES_PATH,
        index=False,
    )

    contract.to_csv(
        CONTRACT_PATH,
        index=False,
    )

    readiness.to_csv(
        READINESS_PATH,
        index=False,
    )

    blocking_mask = (
        parse_bool_series(
            readiness[
                "blocking_for_orchestrator"
            ]
        )
        & ~parse_bool_series(
            readiness[
                "passed"
            ]
        )
    )

    blocking_failures = readiness.loc[
        blocking_mask
    ].copy()

    required_mask = parse_bool_series(
        contract[
            "required"
        ]
    )

    resolved_mask = parse_bool_series(
        contract[
            "resolved"
        ]
    )

    metadata = {
        "script_version": SCRIPT_VERSION,
        "created_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "player_value_path": str(
            PLAYER_VALUE_PATH
        ),
        "player_value_rows": int(
            len(player_frame)
        ),
        "player_value_columns": int(
            len(player_frame.columns)
        ),
        "selected_player_team_key": (
            selected_column
        ),
        "selected_team_key_score": float(
            selected[
                "team_key_candidate_score"
            ]
        ),
        "selected_team_key_known_value_ratio": float(
            selected[
                "known_nba_team_value_ratio"
            ]
        ),
        "selected_team_key_unique_nba_teams": int(
            selected[
                "known_nba_unique_team_count"
            ]
        ),
        "selected_team_key_unknown_unique_values": int(
            selected[
                "unknown_unique_value_count"
            ]
        ),
        "required_contract_elements": int(
            required_mask.sum()
        ),
        "resolved_required_contract_elements": int(
            resolved_mask.loc[
                required_mask
            ].sum()
        ),
        "readiness_checks": int(
            len(readiness)
        ),
        "readiness_checks_passed": int(
            parse_bool_series(
                readiness[
                    "passed"
                ]
            ).sum()
        ),
        "blocking_failures": int(
            len(blocking_failures)
        ),
        "canonical_orchestrator_contract_ready": bool(
            blocking_failures.empty
        ),
        "output_files": {
            "team_key_candidates": str(
                TEAM_KEY_CANDIDATES_PATH
            ),
            "contract": str(
                CONTRACT_PATH
            ),
            "readiness": str(
                READINESS_PATH
            ),
        },
    }

    with METADATA_PATH.open(
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            json_safe(metadata),
            file,
            indent=2,
        )

    print("=" * 80)
    print("CANONICAL RUNTIME CONTRACT V3 CREATED")
    print("=" * 80)
    print(
        "Selected player-team key: "
        f"{selected_column}"
    )
    print(
        "NBA team-code value ratio: "
        f"{float(selected['known_nba_team_value_ratio']):.6f}"
    )
    print(
        "Unique NBA teams represented: "
        f"{int(selected['known_nba_unique_team_count'])}/30"
    )
    print(
        "Unknown unique team values: "
        f"{int(selected['unknown_unique_value_count'])}"
    )
    print(
        "Required contract elements resolved: "
        f"{int(resolved_mask.loc[required_mask].sum())}"
        f"/{int(required_mask.sum())}"
    )
    print(
        "Readiness checks passed: "
        f"{int(parse_bool_series(readiness['passed']).sum())}"
        f"/{len(readiness)}"
    )
    print(
        "Blocking failures: "
        f"{len(blocking_failures)}"
    )
    print(
        "Canonical orchestrator contract ready: "
        f"{bool(blocking_failures.empty)}"
    )
    print()

    print("TOP PLAYER-TEAM KEY CANDIDATES")
    display_candidates = candidates.head(
        15
    ).copy()

    for column in [
        "non_null_ratio",
        "known_nba_team_value_ratio",
        "three_letter_value_ratio",
        "name_prior_score",
        "team_key_candidate_score",
    ]:
        display_candidates[
            column
        ] = pd.to_numeric(
            display_candidates[
                column
            ],
            errors="coerce",
        ).round(
            6
        )

    print(
        display_candidates[
            [
                "column_name",
                "dtype",
                "non_null_count",
                "non_null_ratio",
                "unique_count",
                "known_nba_team_value_ratio",
                "known_nba_unique_team_count",
                "unknown_unique_value_count",
                "name_prior_score",
                "team_key_candidate_score",
                "team_key_candidate_passed",
            ]
        ].to_string(
            index=False
        )
    )
    print()

    print("PATCHED SHARED-ASSET CONTRACT")
    print(
        contract.loc[
            contract[
                "contract_branch"
            ]
            .fillna("")
            .astype(str)
            .eq(
                "shared_assets"
            )
        ][
            [
                "contract_element",
                "artifact_role",
                "selected_column",
                "required",
                "resolved",
                "notes",
            ]
        ].to_string(
            index=False
        )
    )
    print()

    print("READINESS")
    print(
        readiness.to_string(
            index=False
        )
    )
    print()

    print("SAVED FILES")

    for path in [
        TEAM_KEY_CANDIDATES_PATH,
        CONTRACT_PATH,
        READINESS_PATH,
        METADATA_PATH,
    ]:
        print(path)

    if not blocking_failures.empty:
        raise RuntimeError(
            "Canonical runtime contract V3 still has blocking "
            "failures:\n"
            + blocking_failures.to_string(
                index=False
            )
        )


if __name__ == "__main__":
    main()