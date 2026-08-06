from __future__ import annotations

import importlib.util
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType
from typing import Any

import numpy as np
import pandas as pd


SCRIPT_VERSION = "future-draft-pick-simulation-bank-v2-2026-08-04"

PROJECT_ROOT = Path(__file__).resolve().parents[1]

V1_SIMULATOR_PATH = (
    PROJECT_ROOT
    / "src"
    / "build_future_draft_pick_slot_simulator_v1.py"
)

V1_FIRST_ROUND_SUMMARY_PATH = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "future_own_first_round_pick_distributions_2027_2029_v1.parquet"
)

V1_SECOND_ROUND_SUMMARY_PATH = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "future_own_second_round_pick_distributions_2027_2029_v1.parquet"
)

PROCESSED_DIRECTORY = (
    PROJECT_ROOT
    / "data"
    / "processed"
)

OUTPUT_DIRECTORY = PROJECT_ROOT / "outputs"

SIMULATION_BANK_PATH = (
    PROCESSED_DIRECTORY
    / "future_draft_pick_simulation_bank_2027_2029_v2.npz"
)

TEAM_INDEX_PATH = (
    PROCESSED_DIRECTORY
    / "future_draft_pick_simulation_bank_team_index_v2.csv"
)

VALIDATION_PATH = (
    OUTPUT_DIRECTORY
    / "future_draft_pick_simulation_bank_validation_v2.csv"
)

SELECTED_TEAM_AUDIT_PATH = (
    OUTPUT_DIRECTORY
    / "future_draft_pick_simulation_bank_selected_teams_v2.csv"
)

METADATA_PATH = (
    OUTPUT_DIRECTORY
    / "future_draft_pick_simulation_bank_metadata_v2.json"
)


SIMULATIONS = 50_000
RANDOM_SEED = 20260804

EXPECTED_DRAFT_YEARS = [
    2027,
    2028,
    2029,
]

SELECTED_TEAMS = [
    "BKN",
    "GSW",
    "IND",
    "LAC",
    "OKC",
    "SAS",
    "UTA",
    "WAS",
]


def load_v1_simulator() -> ModuleType:
    if not V1_SIMULATOR_PATH.exists():
        raise FileNotFoundError(
            "The V1 future-pick simulator was not found:\n"
            f"{V1_SIMULATOR_PATH}"
        )

    specification = importlib.util.spec_from_file_location(
        "future_pick_simulator_v1",
        V1_SIMULATOR_PATH,
    )

    if (
        specification is None
        or specification.loader is None
    ):
        raise ImportError(
            "Could not create an import specification for:\n"
            f"{V1_SIMULATOR_PATH}"
        )

    module = importlib.util.module_from_spec(
        specification
    )

    specification.loader.exec_module(
        module
    )

    required_attributes = [
        "OFFICIAL_DRAFT_YEARS",
        "load_inputs",
        "validate_team_universe",
        "strength_draws_for_draft_year",
        "simulate_one_draft",
    ]

    missing = [
        attribute
        for attribute in required_attributes
        if not hasattr(
            module,
            attribute,
        )
    ]

    if missing:
        raise AttributeError(
            "The V1 simulator is missing required functions or "
            "constants:\n"
            + "\n".join(
                missing
            )
        )

    return module


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


def build_simulation_bank(
    simulator: ModuleType,
) -> tuple[
    list[str],
    list[int],
    dict[int, np.ndarray],
    dict[int, np.ndarray],
]:
    (
        team_projections,
        _,
    ) = simulator.load_inputs()

    teams = simulator.validate_team_universe(
        team_projections
    )

    draft_years = [
        int(
            year
        )
        for year in simulator.OFFICIAL_DRAFT_YEARS
    ]

    if draft_years != EXPECTED_DRAFT_YEARS:
        raise ValueError(
            "The imported simulator's draft years do not match "
            "the expected 2027-2029 range.\n"
            f"Imported: {draft_years}\n"
            f"Expected: {EXPECTED_DRAFT_YEARS}"
        )

    rng = np.random.default_rng(
        RANDOM_SEED
    )

    strength_draws: dict[
        int,
        np.ndarray,
    ] = {}

    for draft_year in draft_years:
        (
            year_teams,
            draws,
        ) = simulator.strength_draws_for_draft_year(
            team_projections=(
                team_projections
            ),
            draft_year=draft_year,
            simulations=SIMULATIONS,
            rng=rng,
        )

        if year_teams != teams:
            raise ValueError(
                "Team ordering changed between projection seasons."
            )

        strength_draws[
            draft_year
        ] = draws

    first_round_slots = {
        draft_year: np.zeros(
            (
                SIMULATIONS,
                len(
                    teams
                ),
            ),
            dtype=np.int16,
        )
        for draft_year in draft_years
    }

    second_round_slots = {
        draft_year: np.zeros(
            (
                SIMULATIONS,
                len(
                    teams
                ),
            ),
            dtype=np.int16,
        )
        for draft_year in draft_years
    }

    team_to_index = {
        team: index
        for index, team in enumerate(
            teams
        )
    }

    progress_interval = 5_000

    for simulation_index in range(
        SIMULATIONS
    ):
        simulated_history: dict[
            str,
            dict[
                int,
                int,
            ],
        ] = {}

        for draft_year in draft_years:
            (
                first_slots,
                second_slots,
                _,
                _,
            ) = simulator.simulate_one_draft(
                teams=teams,
                strengths=(
                    strength_draws[
                        draft_year
                    ][
                        simulation_index,
                        :,
                    ]
                ),
                simulated_history=(
                    simulated_history
                ),
                draft_year=draft_year,
                rng=rng,
            )

            for team in teams:
                team_index = (
                    team_to_index[
                        team
                    ]
                )

                first_slot = int(
                    first_slots[
                        team
                    ]
                )

                second_slot = int(
                    second_slots[
                        team
                    ]
                )

                first_round_slots[
                    draft_year
                ][
                    simulation_index,
                    team_index,
                ] = first_slot

                second_round_slots[
                    draft_year
                ][
                    simulation_index,
                    team_index,
                ] = second_slot

                simulated_history.setdefault(
                    team,
                    {},
                )[
                    draft_year
                ] = first_slot

        completed = (
            simulation_index
            + 1
        )

        if (
            completed
            % progress_interval
            == 0
        ):
            print(
                "Completed simulations: "
                f"{completed:,} / {SIMULATIONS:,}"
            )

    return (
        teams,
        draft_years,
        first_round_slots,
        second_round_slots,
    )


def save_simulation_bank(
    teams: list[str],
    draft_years: list[int],
    first_round_slots: dict[
        int,
        np.ndarray,
    ],
    second_round_slots: dict[
        int,
        np.ndarray,
    ],
) -> None:
    arrays: dict[
        str,
        np.ndarray,
    ] = {
        "team_abbreviations": np.array(
            teams,
            dtype="U3",
        ),
        "draft_years": np.array(
            draft_years,
            dtype=np.int16,
        ),
        "simulation_ids": np.arange(
            SIMULATIONS,
            dtype=np.int32,
        ),
    }

    for draft_year in draft_years:
        arrays[
            f"first_round_{draft_year}"
        ] = first_round_slots[
            draft_year
        ]

        arrays[
            f"second_round_{draft_year}"
        ] = second_round_slots[
            draft_year
        ]

    np.savez_compressed(
        SIMULATION_BANK_PATH,
        **arrays,
    )

    team_index = pd.DataFrame(
        {
            "team_index": np.arange(
                len(
                    teams
                ),
                dtype=int,
            ),
            "team_abbreviation": teams,
        }
    )

    team_index.to_csv(
        TEAM_INDEX_PATH,
        index=False,
    )


def build_distribution_summary(
    matrix: np.ndarray,
    teams: list[str],
    draft_year: int,
    round_number: int,
) -> pd.DataFrame:
    rows = []

    for team_index, team in enumerate(
        teams
    ):
        slots = matrix[
            :,
            team_index,
        ].astype(
            int
        )

        row = {
            "draft_year": (
                draft_year
            ),
            "round_number": (
                round_number
            ),
            "originating_team": (
                team
            ),
            "expected_overall_pick_bank": float(
                np.mean(
                    slots
                )
            ),
            "median_overall_pick_bank": float(
                np.median(
                    slots
                )
            ),
            "overall_pick_p10_bank": float(
                np.quantile(
                    slots,
                    0.10,
                )
            ),
            "overall_pick_p90_bank": float(
                np.quantile(
                    slots,
                    0.90,
                )
            ),
            "pick_slot_sd_bank": float(
                np.std(
                    slots,
                    ddof=1,
                )
            ),
        }

        if round_number == 1:
            row.update(
                {
                    "number_one_probability_bank": float(
                        np.mean(
                            slots
                            == 1
                        )
                    ),
                    "top_five_probability_bank": float(
                        np.mean(
                            slots
                            <= 5
                        )
                    ),
                    "top_ten_probability_bank": float(
                        np.mean(
                            slots
                            <= 10
                        )
                    ),
                    "lottery_top_16_probability_bank": float(
                        np.mean(
                            slots
                            <= 16
                        )
                    ),
                }
            )
        else:
            row.update(
                {
                    "early_second_probability_bank": float(
                        np.mean(
                            slots
                            <= 40
                        )
                    ),
                    "late_second_probability_bank": float(
                        np.mean(
                            slots
                            >= 51
                        )
                    ),
                }
            )

        rows.append(
            row
        )

    return pd.DataFrame(
        rows
    )


def validate_against_v1(
    teams: list[str],
    draft_years: list[int],
    first_round_slots: dict[
        int,
        np.ndarray,
    ],
    second_round_slots: dict[
        int,
        np.ndarray,
    ],
) -> pd.DataFrame:
    for path in [
        V1_FIRST_ROUND_SUMMARY_PATH,
        V1_SECOND_ROUND_SUMMARY_PATH,
    ]:
        if not path.exists():
            raise FileNotFoundError(
                "A V1 summary required for validation was not found:\n"
                f"{path}"
            )

    v1_first = pd.read_parquet(
        V1_FIRST_ROUND_SUMMARY_PATH
    )

    v1_second = pd.read_parquet(
        V1_SECOND_ROUND_SUMMARY_PATH
    )

    summary_frames = []

    for draft_year in draft_years:
        summary_frames.append(
            build_distribution_summary(
                matrix=(
                    first_round_slots[
                        draft_year
                    ]
                ),
                teams=teams,
                draft_year=draft_year,
                round_number=1,
            )
        )

        summary_frames.append(
            build_distribution_summary(
                matrix=(
                    second_round_slots[
                        draft_year
                    ]
                ),
                teams=teams,
                draft_year=draft_year,
                round_number=2,
            )
        )

    bank_summary = pd.concat(
        summary_frames,
        ignore_index=True,
    )

    v1 = pd.concat(
        [
            v1_first,
            v1_second,
        ],
        ignore_index=True,
        sort=False,
    )

    merged = bank_summary.merge(
        v1,
        how="left",
        on=[
            "draft_year",
            "round_number",
            "originating_team",
        ],
        validate="one_to_one",
    )

    if merged[
        "expected_overall_pick"
    ].isna().any():
        raise ValueError(
            "Some simulation-bank rows did not match the V1 summaries."
        )

    merged[
        "expected_pick_difference"
    ] = (
        merged[
            "expected_overall_pick_bank"
        ]
        - merged[
            "expected_overall_pick"
        ]
    )

    merged[
        "p10_difference"
    ] = (
        merged[
            "overall_pick_p10_bank"
        ]
        - merged[
            "overall_pick_p10"
        ]
    )

    merged[
        "p90_difference"
    ] = (
        merged[
            "overall_pick_p90_bank"
        ]
        - merged[
            "overall_pick_p90"
        ]
    )

    merged[
        "slot_sd_difference"
    ] = (
        merged[
            "pick_slot_sd_bank"
        ]
        - merged[
            "pick_slot_sd"
        ]
    )

    probability_pairs = [
        (
            "number_one_probability_bank",
            "number_one_probability",
            "number_one_probability_difference",
        ),
        (
            "top_five_probability_bank",
            "top_five_probability",
            "top_five_probability_difference",
        ),
        (
            "top_ten_probability_bank",
            "top_ten_probability",
            "top_ten_probability_difference",
        ),
        (
            "lottery_top_16_probability_bank",
            "lottery_top_16_probability",
            "lottery_probability_difference",
        ),
        (
            "early_second_probability_bank",
            "early_second_probability",
            "early_second_probability_difference",
        ),
        (
            "late_second_probability_bank",
            "late_second_probability",
            "late_second_probability_difference",
        ),
    ]

    for (
        bank_column,
        v1_column,
        difference_column,
    ) in probability_pairs:
        if (
            bank_column in merged.columns
            and v1_column in merged.columns
        ):
            merged[
                difference_column
            ] = (
                merged[
                    bank_column
                ]
                - merged[
                    v1_column
                ]
            )

    absolute_difference_columns = [
        column
        for column in merged.columns
        if column.endswith(
            "_difference"
        )
    ]

    merged[
        "maximum_absolute_validation_difference"
    ] = (
        merged[
            absolute_difference_columns
        ]
        .abs()
        .max(
            axis=1
        )
    )

    maximum_difference = float(
        merged[
            "maximum_absolute_validation_difference"
        ].max()
    )

    if maximum_difference > 1e-10:
        raise ValueError(
            "The saved simulation bank does not exactly reproduce "
            "the V1 summary distributions.\n"
            f"Maximum absolute difference: {maximum_difference}"
        )

    return merged.sort_values(
        [
            "draft_year",
            "round_number",
            "originating_team",
        ]
    ).reset_index(
        drop=True
    )


def build_selected_team_audit(
    validation: pd.DataFrame,
) -> pd.DataFrame:
    columns = [
        "draft_year",
        "round_number",
        "originating_team",
        "expected_overall_pick_bank",
        "overall_pick_p10_bank",
        "overall_pick_p90_bank",
        "pick_slot_sd_bank",
        "number_one_probability_bank",
        "top_five_probability_bank",
        "top_ten_probability_bank",
        "lottery_top_16_probability_bank",
        "early_second_probability_bank",
        "late_second_probability_bank",
    ]

    available_columns = [
        column
        for column in columns
        if column in validation.columns
    ]

    return validation.loc[
        validation[
            "originating_team"
        ].isin(
            SELECTED_TEAMS
        ),
        available_columns,
    ].sort_values(
        [
            "draft_year",
            "round_number",
            "originating_team",
        ]
    ).reset_index(
        drop=True
    )


def main() -> None:
    PROCESSED_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    OUTPUT_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    print("=" * 80)
    print("FUTURE NBA DRAFT-PICK SIMULATION BANK V2")
    print("=" * 80)
    print(
        f"Script version: {SCRIPT_VERSION}"
    )
    print(
        f"Simulations: {SIMULATIONS:,}"
    )
    print(
        f"Random seed: {RANDOM_SEED}"
    )
    print()

    simulator = load_v1_simulator()

    (
        teams,
        draft_years,
        first_round_slots,
        second_round_slots,
    ) = build_simulation_bank(
        simulator
    )

    save_simulation_bank(
        teams=teams,
        draft_years=draft_years,
        first_round_slots=(
            first_round_slots
        ),
        second_round_slots=(
            second_round_slots
        ),
    )

    validation = validate_against_v1(
        teams=teams,
        draft_years=draft_years,
        first_round_slots=(
            first_round_slots
        ),
        second_round_slots=(
            second_round_slots
        ),
    )

    validation.to_csv(
        VALIDATION_PATH,
        index=False,
    )

    selected_audit = (
        build_selected_team_audit(
            validation
        )
    )

    selected_audit.to_csv(
        SELECTED_TEAM_AUDIT_PATH,
        index=False,
    )

    archive_size_bytes = (
        SIMULATION_BANK_PATH.stat().st_size
    )

    maximum_difference = float(
        validation[
            "maximum_absolute_validation_difference"
        ].max()
    )

    metadata = {
        "script_version": (
            SCRIPT_VERSION
        ),
        "created_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "simulations": (
            SIMULATIONS
        ),
        "random_seed": (
            RANDOM_SEED
        ),
        "teams": teams,
        "draft_years": (
            draft_years
        ),
        "rounds": [
            1,
            2,
        ],
        "matrix_shape_per_year_round": [
            SIMULATIONS,
            len(
                teams
            ),
        ],
        "stored_slot_values": (
            SIMULATIONS
            * len(
                teams
            )
            * len(
                draft_years
            )
            * 2
        ),
        "archive_size_bytes": (
            archive_size_bytes
        ),
        "maximum_absolute_validation_difference": (
            maximum_difference
        ),
        "exactly_matches_v1_summaries": (
            maximum_difference
            <= 1e-10
        ),
        "intended_uses": [
            (
                "Calculate protected-pick conveyance probabilities."
            ),
            (
                "Value pick swaps as options using joint team outcomes."
            ),
            (
                "Order most-favorable and least-favorable pick pools."
            ),
            (
                "Model linked obligations across the 2027-2029 drafts."
            ),
        ],
        "output_files": {
            "simulation_bank": str(
                SIMULATION_BANK_PATH
            ),
            "team_index": str(
                TEAM_INDEX_PATH
            ),
            "validation": str(
                VALIDATION_PATH
            ),
            "selected_team_audit": str(
                SELECTED_TEAM_AUDIT_PATH
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
    print("SIMULATION BANK CREATED AND VALIDATED")
    print("=" * 80)
    print(
        f"Teams: {len(teams):,}"
    )
    print(
        "Draft years: "
        + ", ".join(
            str(
                year
            )
            for year in draft_years
        )
    )
    print(
        "Matrix shape per year and round: "
        f"{SIMULATIONS:,} x {len(teams):,}"
    )
    print(
        "Total simulated slot values stored: "
        f"{metadata['stored_slot_values']:,}"
    )
    print(
        "Compressed archive size: "
        f"{archive_size_bytes / 1_048_576:.2f} MB"
    )
    print(
        "Maximum difference from V1 summaries: "
        f"{maximum_difference:.12f}"
    )
    print(
        "Exact V1 summary match: "
        f"{metadata['exactly_matches_v1_summaries']}"
    )
    print()

    print("SELECTED TEAM AUDIT")
    display = selected_audit.copy()

    for column in display.columns:
        if column not in {
            "originating_team",
            "draft_year",
            "round_number",
        }:
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
                    4
                )
            )

    print(
        display.to_string(
            index=False
        )
    )
    print()

    print("SAVED FILES")
    print(SIMULATION_BANK_PATH)
    print(TEAM_INDEX_PATH)
    print(VALIDATION_PATH)
    print(SELECTED_TEAM_AUDIT_PATH)
    print(METADATA_PATH)


if __name__ == "__main__":
    main()