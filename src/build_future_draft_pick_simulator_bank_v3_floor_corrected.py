from __future__ import annotations

import importlib.util
import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType
from typing import Any

import numpy as np
import pandas as pd


SCRIPT_VERSION = (
    "future-draft-pick-simulator-bank-v3-floor-corrected-2026-08-04"
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]

V1_SIMULATOR_PATH = (
    PROJECT_ROOT
    / "src"
    / "build_future_draft_pick_slot_simulator_v1.py"
)

OLD_V2_BANK_PATH = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "future_draft_pick_simulation_bank_2027_2029_v2.npz"
)

PROCESSED_DIRECTORY = (
    PROJECT_ROOT
    / "data"
    / "processed"
)

OUTPUT_DIRECTORY = PROJECT_ROOT / "outputs"

SIMULATION_BANK_PATH = (
    PROCESSED_DIRECTORY
    / "future_draft_pick_simulation_bank_2027_2029_v3_floor_corrected.npz"
)

TEAM_INDEX_PATH = (
    PROCESSED_DIRECTORY
    / "future_draft_pick_simulation_bank_team_index_v3_floor_corrected.csv"
)

FIRST_ROUND_PARQUET_PATH = (
    PROCESSED_DIRECTORY
    / "future_own_first_round_pick_distributions_2027_2029_v3_floor_corrected.parquet"
)

FIRST_ROUND_CSV_PATH = (
    PROCESSED_DIRECTORY
    / "future_own_first_round_pick_distributions_2027_2029_v3_floor_corrected.csv"
)

SECOND_ROUND_PARQUET_PATH = (
    PROCESSED_DIRECTORY
    / "future_own_second_round_pick_distributions_2027_2029_v3_floor_corrected.parquet"
)

SECOND_ROUND_CSV_PATH = (
    PROCESSED_DIRECTORY
    / "future_own_second_round_pick_distributions_2027_2029_v3_floor_corrected.csv"
)

COMBINED_PICK_VALUES_PARQUET_PATH = (
    PROCESSED_DIRECTORY
    / "future_originating_team_pick_values_2027_2029_v3_floor_corrected.parquet"
)

COMBINED_PICK_VALUES_CSV_PATH = (
    PROCESSED_DIRECTORY
    / "future_originating_team_pick_values_2027_2029_v3_floor_corrected.csv"
)

FLOOR_AUDIT_PATH = (
    OUTPUT_DIRECTORY
    / "future_draft_pick_relegated_floor_audit_v3.csv"
)

GROUP_AUDIT_PATH = (
    OUTPUT_DIRECTORY
    / "future_draft_pick_lottery_group_audit_v3_floor_corrected.csv"
)

V2_COMPARISON_PATH = (
    OUTPUT_DIRECTORY
    / "future_draft_pick_v2_to_v3_summary_comparison.csv"
)

SELECTED_TEAMS_PATH = (
    OUTPUT_DIRECTORY
    / "future_draft_pick_selected_teams_v3_floor_corrected.csv"
)

METADATA_PATH = (
    OUTPUT_DIRECTORY
    / "future_draft_pick_simulator_bank_metadata_v3_floor_corrected.json"
)


SIMULATIONS = 50_000
RANDOM_SEED = 20260804
PICK_FLOOR = 12

EXPECTED_DRAFT_YEARS = [
    2027,
    2028,
    2029,
]

SELECTED_TEAMS = [
    "BKN",
    "CHA",
    "DAL",
    "DEN",
    "GSW",
    "IND",
    "LAC",
    "MIA",
    "OKC",
    "SAS",
    "UTA",
    "WAS",
]


def load_v1_simulator() -> ModuleType:
    if not V1_SIMULATOR_PATH.exists():
        raise FileNotFoundError(
            "The V1 simulator source was not found:\n"
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
            "Could not import the V1 simulator source:\n"
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
        "EASTERN_CONFERENCE_TEAMS",
        "WESTERN_CONFERENCE_TEAMS",
        "LOTTERY_BALLS_BY_GROUP",
        "INITIAL_OWN_PICK_HISTORY",
        "TIME_DISCOUNT_RATE_BY_YEARS_AHEAD",
        "load_inputs",
        "validate_team_universe",
        "strength_draws_for_draft_year",
        "logistic_win_probability",
        "no_number_one_eligibility",
        "top_five_eligibility",
        "summarize_slot_distribution",
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
            "The V1 simulator is missing required attributes:\n"
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


def corrected_weighted_lottery_permutation(
    simulator: ModuleType,
    participants: list[str],
    balls_by_team: dict[str, int],
    draft_relegated_teams: list[str],
    simulated_history: dict[
        str,
        dict[
            int,
            int,
        ],
    ],
    draft_year: int,
    rng: np.random.Generator,
) -> tuple[
    list[str],
    int,
]:
    remaining = list(
        participants
    )

    relegated_set = set(
        draft_relegated_teams
    )

    if len(
        relegated_set
    ) != 3:
        raise ValueError(
            "Exactly three draft-relegated teams are required."
        )

    if not relegated_set.issubset(
        set(
            participants
        )
    ):
        raise ValueError(
            "Every draft-relegated team must be a lottery participant."
        )

    order = []

    forced_floor_selections = 0

    for pick_number in range(
        1,
        17,
    ):
        remaining_relegated = [
            team
            for team in remaining
            if team in relegated_set
        ]

        slots_remaining_through_floor = (
            PICK_FLOOR
            - pick_number
            + 1
            if pick_number
            <= PICK_FLOOR
            else 0
        )

        floor_force_active = (
            pick_number
            <= PICK_FLOOR
            and len(
                remaining_relegated
            )
            > 0
            and len(
                remaining_relegated
            )
            == slots_remaining_through_floor
        )

        candidate_pool = (
            remaining_relegated
            if floor_force_active
            else remaining
        )

        eligible = []

        for team in candidate_pool:
            if (
                pick_number
                == 1
                and not simulator.no_number_one_eligibility(
                    simulated_history=(
                        simulated_history
                    ),
                    team=team,
                    draft_year=draft_year,
                )
            ):
                continue

            if (
                pick_number
                <= 5
                and not simulator.top_five_eligibility(
                    simulated_history=(
                        simulated_history
                    ),
                    team=team,
                    draft_year=draft_year,
                )
            ):
                continue

            eligible.append(
                team
            )

        if not eligible:
            raise RuntimeError(
                "No eligible teams remained for a lottery selection. "
                f"Draft year: {draft_year}; pick: {pick_number}; "
                f"floor_force_active: {floor_force_active}; "
                f"remaining_relegated: {remaining_relegated}"
            )

        weights = np.array(
            [
                balls_by_team[
                    team
                ]
                for team in eligible
            ],
            dtype=float,
        )

        probabilities = (
            weights
            / weights.sum()
        )

        selected_index = int(
            rng.choice(
                len(
                    eligible
                ),
                p=probabilities,
            )
        )

        selected_team = eligible[
            selected_index
        ]

        order.append(
            selected_team
        )

        remaining.remove(
            selected_team
        )

        if floor_force_active:
            forced_floor_selections += 1

    return (
        order,
        forced_floor_selections,
    )


def corrected_simulate_one_draft(
    simulator: ModuleType,
    teams: list[str],
    strengths: np.ndarray,
    simulated_history: dict[
        str,
        dict[
            int,
            int,
        ],
    ],
    draft_year: int,
    rng: np.random.Generator,
) -> tuple[
    dict[str, int],
    dict[str, int],
    dict[str, str],
    dict[str, int],
    list[str],
    int,
]:
    team_to_index = {
        team: index
        for index, team in enumerate(
            teams
        )
    }

    conference_ranks: dict[
        str,
        int,
    ] = {}

    seven_eight_losers = []

    non_play_in_teams = []

    for conference_teams in [
        simulator.EASTERN_CONFERENCE_TEAMS,
        simulator.WESTERN_CONFERENCE_TEAMS,
    ]:
        ordered = sorted(
            conference_teams,
            key=lambda team: (
                strengths[
                    team_to_index[
                        team
                    ]
                ]
            ),
            reverse=True,
        )

        for rank, team in enumerate(
            ordered,
            start=1,
        ):
            conference_ranks[
                team
            ] = rank

        seed_seven = ordered[
            6
        ]

        seed_eight = ordered[
            7
        ]

        scale = max(
            float(
                np.std(
                    [
                        strengths[
                            team_to_index[
                                team
                            ]
                        ]
                        for team in ordered
                    ],
                    ddof=1,
                )
            )
            * 0.55,
            1.0,
        )

        probability_seven_wins = (
            simulator.logistic_win_probability(
                strength_a=(
                    strengths[
                        team_to_index[
                            seed_seven
                        ]
                    ]
                ),
                strength_b=(
                    strengths[
                        team_to_index[
                            seed_eight
                        ]
                    ]
                ),
                scale=scale,
            )
        )

        if (
            rng.random()
            < probability_seven_wins
        ):
            loser = seed_eight
        else:
            loser = seed_seven

        seven_eight_losers.append(
            loser
        )

        non_play_in_teams.extend(
            ordered[
                10:
            ]
        )

    if len(
        non_play_in_teams
    ) != 10:
        raise RuntimeError(
            "Expected exactly 10 non-play-in teams."
        )

    if len(
        seven_eight_losers
    ) != 2:
        raise RuntimeError(
            "Expected exactly two 7-vs-8 Play-In losers."
        )

    bottom_three = sorted(
        non_play_in_teams,
        key=lambda team: (
            strengths[
                team_to_index[
                    team
                ]
            ]
        ),
    )[
        :3
    ]

    other_bottom_seven = [
        team
        for team in non_play_in_teams
        if team not in bottom_three
    ]

    nine_ten_seeds = [
        team
        for team, rank
        in conference_ranks.items()
        if rank in {
            9,
            10,
        }
    ]

    participants = (
        bottom_three
        + other_bottom_seven
        + nine_ten_seeds
        + seven_eight_losers
    )

    if len(
        participants
    ) != 16:
        raise RuntimeError(
            "Expected exactly 16 lottery participants."
        )

    if len(
        set(
            participants
        )
    ) != 16:
        raise RuntimeError(
            "Lottery participants were not unique."
        )

    balls_by_team = {}

    group_by_team = {}

    group_members = [
        (
            bottom_three,
            "draft_relegated_bottom_three",
        ),
        (
            other_bottom_seven,
            "other_non_play_in_bottom_ten",
        ),
        (
            nine_ten_seeds,
            "conference_seed_9_or_10",
        ),
        (
            seven_eight_losers,
            "loser_of_7_8_play_in_game",
        ),
    ]

    for members, group in group_members:
        for team in members:
            balls_by_team[
                team
            ] = simulator.LOTTERY_BALLS_BY_GROUP[
                group
            ]

            group_by_team[
                team
            ] = group

    (
        lottery_order,
        forced_floor_selections,
    ) = corrected_weighted_lottery_permutation(
        simulator=simulator,
        participants=participants,
        balls_by_team=balls_by_team,
        draft_relegated_teams=bottom_three,
        simulated_history=simulated_history,
        draft_year=draft_year,
        rng=rng,
    )

    first_round_slots = {
        team: pick
        for pick, team in enumerate(
            lottery_order,
            start=1,
        )
    }

    non_lottery_teams = [
        team
        for team in teams
        if team not in first_round_slots
    ]

    non_lottery_order = sorted(
        non_lottery_teams,
        key=lambda team: (
            strengths[
                team_to_index[
                    team
                ]
            ]
        ),
    )

    for pick, team in enumerate(
        non_lottery_order,
        start=17,
    ):
        first_round_slots[
            team
        ] = pick

    league_order_best_to_worst = sorted(
        teams,
        key=lambda team: (
            strengths[
                team_to_index[
                    team
                ]
            ]
        ),
        reverse=True,
    )

    league_rank = {
        team: rank
        for rank, team in enumerate(
            league_order_best_to_worst,
            start=1,
        )
    }

    second_round_slots = {
        team: (
            61
            - rank
        )
        for team, rank in league_rank.items()
    }

    return (
        first_round_slots,
        second_round_slots,
        group_by_team,
        balls_by_team,
        bottom_three,
        forced_floor_selections,
    )


def simulate_corrected_bank(
    simulator: ModuleType,
    team_projections: pd.DataFrame,
    teams: list[str],
) -> tuple[
    dict[int, np.ndarray],
    dict[int, np.ndarray],
    pd.DataFrame,
    pd.DataFrame,
    dict[tuple[int, str, str], int],
]:
    rng = np.random.default_rng(
        RANDOM_SEED
    )

    draft_years = [
        int(
            year
        )
        for year in simulator.OFFICIAL_DRAFT_YEARS
    ]

    if draft_years != EXPECTED_DRAFT_YEARS:
        raise ValueError(
            "Unexpected official draft years from the V1 simulator: "
            f"{draft_years}"
        )

    strength_draws = {}

    for draft_year in draft_years:
        (
            year_teams,
            draws,
        ) = simulator.strength_draws_for_draft_year(
            team_projections=team_projections,
            draft_year=draft_year,
            simulations=SIMULATIONS,
            rng=rng,
        )

        if year_teams != teams:
            raise ValueError(
                "Team order changed across draft-year strength draws."
            )

        strength_draws[
            draft_year
        ] = draws

    first_round_slots = {
        draft_year: np.empty(
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
        draft_year: np.empty(
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

    restriction_counts: dict[
        tuple[int, str, str],
        int,
    ] = defaultdict(
        int
    )

    group_counts: dict[
        tuple[int, str, str],
        int,
    ] = defaultdict(
        int
    )

    floor_counts = {
        draft_year: {
            "draft_relegated_team_checks": 0,
            "draft_relegated_floor_violation_count": 0,
            "maximum_draft_relegated_pick_observed": 0,
            "simulations_with_forced_floor_selection": 0,
            "forced_floor_selection_count": 0,
        }
        for draft_year in draft_years
    }

    violation_examples = []

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
            for team in teams:
                if not simulator.no_number_one_eligibility(
                    simulated_history=(
                        simulated_history
                    ),
                    team=team,
                    draft_year=draft_year,
                ):
                    restriction_counts[
                        (
                            draft_year,
                            team,
                            "number_one_ineligible",
                        )
                    ] += 1

                if not simulator.top_five_eligibility(
                    simulated_history=(
                        simulated_history
                    ),
                    team=team,
                    draft_year=draft_year,
                ):
                    restriction_counts[
                        (
                            draft_year,
                            team,
                            "top_five_ineligible",
                        )
                    ] += 1

            (
                first_slots,
                second_slots,
                groups,
                _,
                bottom_three,
                forced_floor_selections,
            ) = corrected_simulate_one_draft(
                simulator=simulator,
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

            if forced_floor_selections > 0:
                floor_counts[
                    draft_year
                ][
                    "simulations_with_forced_floor_selection"
                ] += 1

            floor_counts[
                draft_year
            ][
                "forced_floor_selection_count"
            ] += forced_floor_selections

            for team in bottom_three:
                slot = int(
                    first_slots[
                        team
                    ]
                )

                floor_counts[
                    draft_year
                ][
                    "draft_relegated_team_checks"
                ] += 1

                floor_counts[
                    draft_year
                ][
                    "maximum_draft_relegated_pick_observed"
                ] = max(
                    floor_counts[
                        draft_year
                    ][
                        "maximum_draft_relegated_pick_observed"
                    ],
                    slot,
                )

                if slot > PICK_FLOOR:
                    floor_counts[
                        draft_year
                    ][
                        "draft_relegated_floor_violation_count"
                    ] += 1

                    if len(
                        violation_examples
                    ) < 20:
                        violation_examples.append(
                            {
                                "simulation_index": (
                                    simulation_index
                                ),
                                "draft_year": (
                                    draft_year
                                ),
                                "team": (
                                    team
                                ),
                                "pick": (
                                    slot
                                ),
                            }
                        )

            for team in teams:
                team_index = team_to_index[
                    team
                ]

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

                if team in groups:
                    group_counts[
                        (
                            draft_year,
                            team,
                            groups[
                                team
                            ],
                        )
                    ] += 1

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

    floor_rows = []

    for draft_year in draft_years:
        counts = floor_counts[
            draft_year
        ]

        floor_rows.append(
            {
                "draft_year": (
                    draft_year
                ),
                **counts,
                "floor_rule_pick": (
                    PICK_FLOOR
                ),
                "floor_violation_rate": (
                    counts[
                        "draft_relegated_floor_violation_count"
                    ]
                    / max(
                        counts[
                            "draft_relegated_team_checks"
                        ],
                        1,
                    )
                ),
                "forced_floor_simulation_rate": (
                    counts[
                        "simulations_with_forced_floor_selection"
                    ]
                    / SIMULATIONS
                ),
                "floor_rule_passed": (
                    counts[
                        "draft_relegated_floor_violation_count"
                    ]
                    == 0
                    and counts[
                        "maximum_draft_relegated_pick_observed"
                    ]
                    <= PICK_FLOOR
                ),
            }
        )

    floor_audit = pd.DataFrame(
        floor_rows
    )

    if not floor_audit[
        "floor_rule_passed"
    ].all():
        raise RuntimeError(
            "The corrected simulator still produced a draft-relegated "
            "pick-floor violation.\n"
            + json.dumps(
                violation_examples,
                indent=2,
            )
        )

    group_rows = []

    for (
        draft_year,
        team,
        group,
    ), count in sorted(
        group_counts.items()
    ):
        group_rows.append(
            {
                "draft_year": (
                    draft_year
                ),
                "originating_team": (
                    team
                ),
                "lottery_group": (
                    group
                ),
                "group_probability": (
                    count
                    / SIMULATIONS
                ),
                "lottery_balls": (
                    simulator.LOTTERY_BALLS_BY_GROUP[
                        group
                    ]
                ),
            }
        )

    group_audit = pd.DataFrame(
        group_rows
    )

    return (
        first_round_slots,
        second_round_slots,
        floor_audit,
        group_audit,
        restriction_counts,
    )


def build_full_summaries(
    simulator: ModuleType,
    teams: list[str],
    pick_curve: pd.DataFrame,
    first_round_slots: dict[
        int,
        np.ndarray,
    ],
    second_round_slots: dict[
        int,
        np.ndarray,
    ],
    restriction_counts: dict[
        tuple[int, str, str],
        int,
    ],
) -> tuple[
    pd.DataFrame,
    pd.DataFrame,
]:
    first_frames = []

    second_frames = []

    for draft_year in EXPECTED_DRAFT_YEARS:
        first = simulator.summarize_slot_distribution(
            slot_matrix=(
                first_round_slots[
                    draft_year
                ]
            ),
            teams=teams,
            draft_year=draft_year,
            round_number=1,
            pick_curve=pick_curve,
        )

        second = simulator.summarize_slot_distribution(
            slot_matrix=(
                second_round_slots[
                    draft_year
                ]
            ),
            teams=teams,
            draft_year=draft_year,
            round_number=2,
            pick_curve=pick_curve,
        )

        for team in teams:
            mask = first[
                "originating_team"
            ].eq(
                team
            )

            first.loc[
                mask,
                "number_one_restriction_probability",
            ] = (
                restriction_counts[
                    (
                        draft_year,
                        team,
                        "number_one_ineligible",
                    )
                ]
                / SIMULATIONS
            )

            first.loc[
                mask,
                "top_five_restriction_probability",
            ] = (
                restriction_counts[
                    (
                        draft_year,
                        team,
                        "top_five_ineligible",
                    )
                ]
                / SIMULATIONS
            )

        first[
            "official_rule_status"
        ] = (
            "Official 3-2-1 Lottery structure for 2027-2029 "
            "with draft-relegated No. 12 floor enforced"
        )

        first[
            "draft_relegated_floor_pick"
        ] = (
            PICK_FLOOR
        )

        first[
            "restriction_implementation_note"
        ] = (
            "Consecutive No. 1 and top-five restrictions use an "
            "eligible-team redraw. The bottom-three floor forces "
            "remaining draft-relegated teams into the remaining "
            "selections through No. 12 when mathematically necessary."
        )

        second[
            "official_rule_status"
        ] = (
            "Second-round slot proxy from inverse simulated "
            "regular-season strength"
        )

        first_frames.append(
            first
        )

        second_frames.append(
            second
        )

    return (
        pd.concat(
            first_frames,
            ignore_index=True,
        ),
        pd.concat(
            second_frames,
            ignore_index=True,
        ),
    )


def save_bank(
    teams: list[str],
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
            EXPECTED_DRAFT_YEARS,
            dtype=np.int16,
        ),
        "simulation_ids": np.arange(
            SIMULATIONS,
            dtype=np.int32,
        ),
        "draft_relegated_floor_pick": np.array(
            [
                PICK_FLOOR
            ],
            dtype=np.int16,
        ),
    }

    for draft_year in EXPECTED_DRAFT_YEARS:
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

    pd.DataFrame(
        {
            "team_index": np.arange(
                len(
                    teams
                ),
                dtype=int,
            ),
            "team_abbreviation": teams,
        }
    ).to_csv(
        TEAM_INDEX_PATH,
        index=False,
    )


def build_basic_summary(
    matrices: dict[
        int,
        np.ndarray,
    ],
    teams: list[str],
    round_number: int,
    suffix: str,
) -> pd.DataFrame:
    rows = []

    for draft_year in EXPECTED_DRAFT_YEARS:
        matrix = matrices[
            draft_year
        ]

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
                f"expected_overall_pick_{suffix}": float(
                    np.mean(
                        slots
                    )
                ),
                f"overall_pick_p10_{suffix}": float(
                    np.quantile(
                        slots,
                        0.10,
                    )
                ),
                f"overall_pick_p90_{suffix}": float(
                    np.quantile(
                        slots,
                        0.90,
                    )
                ),
                f"pick_slot_sd_{suffix}": float(
                    np.std(
                        slots,
                        ddof=1,
                    )
                ),
            }

            if round_number == 1:
                row.update(
                    {
                        f"number_one_probability_{suffix}": float(
                            np.mean(
                                slots
                                == 1
                            )
                        ),
                        f"top_five_probability_{suffix}": float(
                            np.mean(
                                slots
                                <= 5
                            )
                        ),
                        f"top_ten_probability_{suffix}": float(
                            np.mean(
                                slots
                                <= 10
                            )
                        ),
                        f"lottery_top_16_probability_{suffix}": float(
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
                        f"early_second_probability_{suffix}": float(
                            np.mean(
                                slots
                                <= 40
                            )
                        ),
                        f"late_second_probability_{suffix}": float(
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


def compare_to_v2(
    teams: list[str],
    first_round_slots: dict[
        int,
        np.ndarray,
    ],
    second_round_slots: dict[
        int,
        np.ndarray,
    ],
) -> pd.DataFrame:
    v3 = pd.concat(
        [
            build_basic_summary(
                matrices=first_round_slots,
                teams=teams,
                round_number=1,
                suffix="v3",
            ),
            build_basic_summary(
                matrices=second_round_slots,
                teams=teams,
                round_number=2,
                suffix="v3",
            ),
        ],
        ignore_index=True,
        sort=False,
    )

    if not OLD_V2_BANK_PATH.exists():
        v3[
            "v2_bank_available"
        ] = False

        return v3

    with np.load(
        OLD_V2_BANK_PATH,
        allow_pickle=False,
    ) as archive:
        v2_teams = [
            str(
                value
            )
            for value in archive[
                "team_abbreviations"
            ].tolist()
        ]

        v2_years = [
            int(
                value
            )
            for value in archive[
                "draft_years"
            ].tolist()
        ]

        if (
            v2_teams
            != teams
            or v2_years
            != EXPECTED_DRAFT_YEARS
        ):
            raise ValueError(
                "The V2 bank team or year order does not match V3."
            )

        v2_first = {
            year: archive[
                f"first_round_{year}"
            ].copy()
            for year in EXPECTED_DRAFT_YEARS
        }

        v2_second = {
            year: archive[
                f"second_round_{year}"
            ].copy()
            for year in EXPECTED_DRAFT_YEARS
        }

    v2 = pd.concat(
        [
            build_basic_summary(
                matrices=v2_first,
                teams=teams,
                round_number=1,
                suffix="v2",
            ),
            build_basic_summary(
                matrices=v2_second,
                teams=teams,
                round_number=2,
                suffix="v2",
            ),
        ],
        ignore_index=True,
        sort=False,
    )

    merged = v3.merge(
        v2,
        how="left",
        on=[
            "draft_year",
            "round_number",
            "originating_team",
        ],
        validate="one_to_one",
    )

    metric_stems = [
        "expected_overall_pick",
        "overall_pick_p10",
        "overall_pick_p90",
        "pick_slot_sd",
        "number_one_probability",
        "top_five_probability",
        "top_ten_probability",
        "lottery_top_16_probability",
        "early_second_probability",
        "late_second_probability",
    ]

    for stem in metric_stems:
        v3_column = (
            f"{stem}_v3"
        )

        v2_column = (
            f"{stem}_v2"
        )

        if (
            v3_column in merged.columns
            and v2_column in merged.columns
        ):
            merged[
                f"{stem}_change_v3_minus_v2"
            ] = (
                merged[
                    v3_column
                ]
                - merged[
                    v2_column
                ]
            )

    merged[
        "v2_bank_available"
    ] = True

    return merged.sort_values(
        [
            "draft_year",
            "round_number",
            "originating_team",
        ]
    ).reset_index(
        drop=True
    )


def build_selected_team_output(
    combined: pd.DataFrame,
) -> pd.DataFrame:
    columns = [
        "originating_team",
        "draft_year",
        "round_number",
        "expected_overall_pick",
        "overall_pick_p10",
        "overall_pick_p90",
        "expected_historical_pick_value_score",
        "time_discounted_pick_value_score",
        "expected_pick_value_rating_60_99",
        "pick_slot_sd",
        "number_one_probability",
        "top_five_probability",
        "top_ten_probability",
        "lottery_top_16_probability",
        "early_second_probability",
        "late_second_probability",
    ]

    available = [
        column
        for column in columns
        if column in combined.columns
    ]

    return combined.loc[
        combined[
            "originating_team"
        ].isin(
            SELECTED_TEAMS
        ),
        available,
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
    for directory in [
        PROCESSED_DIRECTORY,
        OUTPUT_DIRECTORY,
    ]:
        directory.mkdir(
            parents=True,
            exist_ok=True,
        )

    print("=" * 80)
    print("FUTURE NBA DRAFT-PICK SIMULATOR AND BANK V3")
    print("=" * 80)
    print(
        f"Script version: {SCRIPT_VERSION}"
    )
    print(
        "Draft-relegated pick floor enforced: "
        f"No. {PICK_FLOOR}"
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
        team_projections,
        pick_curve,
    ) = simulator.load_inputs()

    teams = simulator.validate_team_universe(
        team_projections
    )

    (
        first_round_slots,
        second_round_slots,
        floor_audit,
        group_audit,
        restriction_counts,
    ) = simulate_corrected_bank(
        simulator=simulator,
        team_projections=team_projections,
        teams=teams,
    )

    (
        first_round,
        second_round,
    ) = build_full_summaries(
        simulator=simulator,
        teams=teams,
        pick_curve=pick_curve,
        first_round_slots=first_round_slots,
        second_round_slots=second_round_slots,
        restriction_counts=restriction_counts,
    )

    combined = pd.concat(
        [
            first_round,
            second_round,
        ],
        ignore_index=True,
        sort=False,
    )

    comparison = compare_to_v2(
        teams=teams,
        first_round_slots=first_round_slots,
        second_round_slots=second_round_slots,
    )

    selected = build_selected_team_output(
        combined
    )

    save_bank(
        teams=teams,
        first_round_slots=first_round_slots,
        second_round_slots=second_round_slots,
    )

    first_round.to_parquet(
        FIRST_ROUND_PARQUET_PATH,
        index=False,
    )

    first_round.to_csv(
        FIRST_ROUND_CSV_PATH,
        index=False,
    )

    second_round.to_parquet(
        SECOND_ROUND_PARQUET_PATH,
        index=False,
    )

    second_round.to_csv(
        SECOND_ROUND_CSV_PATH,
        index=False,
    )

    combined.to_parquet(
        COMBINED_PICK_VALUES_PARQUET_PATH,
        index=False,
    )

    combined.to_csv(
        COMBINED_PICK_VALUES_CSV_PATH,
        index=False,
    )

    floor_audit.to_csv(
        FLOOR_AUDIT_PATH,
        index=False,
    )

    group_audit.to_csv(
        GROUP_AUDIT_PATH,
        index=False,
    )

    comparison.to_csv(
        V2_COMPARISON_PATH,
        index=False,
    )

    selected.to_csv(
        SELECTED_TEAMS_PATH,
        index=False,
    )

    archive_size_mb = (
        SIMULATION_BANK_PATH.stat().st_size
        / (
            1024
            ** 2
        )
    )

    first_comparison = comparison.loc[
        comparison[
            "round_number"
        ].eq(
            1
        )
    ].copy()

    max_expected_pick_change = float(
        first_comparison[
            "expected_overall_pick_change_v3_minus_v2"
        ].abs().max()
    ) if (
        "expected_overall_pick_change_v3_minus_v2"
        in first_comparison.columns
    ) else np.nan

    metadata = {
        "script_version": (
            SCRIPT_VERSION
        ),
        "created_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "draft_years": (
            EXPECTED_DRAFT_YEARS
        ),
        "simulations": (
            SIMULATIONS
        ),
        "random_seed": (
            RANDOM_SEED
        ),
        "teams": len(
            teams
        ),
        "draft_relegated_pick_floor": (
            PICK_FLOOR
        ),
        "total_slot_values_stored": (
            SIMULATIONS
            * len(
                teams
            )
            * len(
                EXPECTED_DRAFT_YEARS
            )
            * 2
        ),
        "compressed_archive_size_mb": (
            archive_size_mb
        ),
        "floor_violation_count_total": int(
            floor_audit[
                "draft_relegated_floor_violation_count"
            ].sum()
        ),
        "floor_rule_passed_all_years": bool(
            floor_audit[
                "floor_rule_passed"
            ].all()
        ),
        "maximum_first_round_expected_pick_change_vs_v2": (
            max_expected_pick_change
        ),
        "official_rules_encoded": [
            (
                "Sixteen teams participate in the lottery."
            ),
            (
                "The three draft-relegated teams receive two balls "
                "and each has a floor of pick No. 12."
            ),
            (
                "The next seven non-play-in teams receive three balls."
            ),
            (
                "Conference seeds 9 and 10 receive two balls."
            ),
            (
                "Each conference's 7-vs-8 Play-In loser receives one ball."
            ),
            (
                "All first 16 selections are drawn."
            ),
            (
                "No own pick may be No. 1 in consecutive drafts."
            ),
            (
                "No own pick may be top five in three consecutive drafts."
            ),
        ],
        "floor_implementation": (
            "When the number of selections remaining through No. 12 "
            "equals the number of unselected draft-relegated teams, "
            "the remaining draft-relegated teams become the eligible "
            "pool for those selections. Their lottery-ball weights "
            "remain in effect within that forced pool."
        ),
        "important_limitations": [
            (
                "The NBA has not published a fully detailed mechanical "
                "drawing protocol for every interaction among the new "
                "restrictions. Eligible-team redraw remains a modeling "
                "assumption for the consecutive-pick restrictions."
            ),
            (
                "The 7-vs-8 Play-In loser is simulated from projected "
                "team strength."
            ),
            (
                "Second-round order is an inverse-strength proxy and "
                "does not model forfeitures or tie-break procedures."
            ),
            (
                "Current ownership, protection, swap, and rollover "
                "clauses must be applied in downstream layers."
            ),
        ],
        "output_files": {
            "simulation_bank": str(
                SIMULATION_BANK_PATH
            ),
            "team_index": str(
                TEAM_INDEX_PATH
            ),
            "first_round_distributions": str(
                FIRST_ROUND_PARQUET_PATH
            ),
            "second_round_distributions": str(
                SECOND_ROUND_PARQUET_PATH
            ),
            "combined_pick_values": str(
                COMBINED_PICK_VALUES_PARQUET_PATH
            ),
            "floor_audit": str(
                FLOOR_AUDIT_PATH
            ),
            "lottery_group_audit": str(
                GROUP_AUDIT_PATH
            ),
            "v2_comparison": str(
                V2_COMPARISON_PATH
            ),
            "selected_teams": str(
                SELECTED_TEAMS_PATH
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
    print("FLOOR-CORRECTED SIMULATION BANK CREATED")
    print("=" * 80)
    print(
        f"Teams: {len(teams):,}"
    )
    print(
        "Draft years: "
        + ", ".join(
            str(
                value
            )
            for value in EXPECTED_DRAFT_YEARS
        )
    )
    print(
        "Matrix shape per year and round: "
        f"{SIMULATIONS:,} x {len(teams):,}"
    )
    print(
        "Total simulated slot values stored: "
        f"{metadata['total_slot_values_stored']:,}"
    )
    print(
        f"Compressed archive size: "
        f"{archive_size_mb:.2f} MB"
    )
    print(
        "Total draft-relegated floor violations: "
        f"{metadata['floor_violation_count_total']:,}"
    )
    print(
        "Floor rule passed all years: "
        f"{metadata['floor_rule_passed_all_years']}"
    )
    print()

    print("DRAFT-RELEGATED FLOOR AUDIT")
    floor_display = floor_audit.copy()

    for column in [
        "floor_violation_rate",
        "forced_floor_simulation_rate",
    ]:
        floor_display[
            column
        ] = (
            floor_display[
                column
            ]
            * 100.0
        ).round(
            4
        )

    print(
        floor_display.to_string(
            index=False
        )
    )
    print()

    if (
        "expected_overall_pick_change_v3_minus_v2"
        in first_comparison.columns
    ):
        print("LARGEST FIRST-ROUND CHANGES FROM V2")
        change_display = (
            first_comparison.assign(
                absolute_change=(
                    first_comparison[
                        "expected_overall_pick_change_v3_minus_v2"
                    ].abs()
                )
            )
            .sort_values(
                "absolute_change",
                ascending=False,
            )
            .head(
                20
            )[
                [
                    "draft_year",
                    "originating_team",
                    "expected_overall_pick_v2",
                    "expected_overall_pick_v3",
                    "expected_overall_pick_change_v3_minus_v2",
                    "overall_pick_p90_v2",
                    "overall_pick_p90_v3",
                ]
            ]
            .copy()
        )

        for column in change_display.columns:
            if column not in {
                "originating_team"
            }:
                change_display[
                    column
                ] = pd.to_numeric(
                    change_display[
                        column
                    ],
                    errors="coerce",
                ).round(
                    4
                )

        print(
            change_display.to_string(
                index=False
            )
        )
        print()

    print("SELECTED TEAM AUDIT")
    selected_display = selected.copy()

    numeric_columns = [
        column
        for column in selected_display.columns
        if column
        != "originating_team"
    ]

    for column in numeric_columns:
        selected_display[
            column
        ] = pd.to_numeric(
            selected_display[
                column
            ],
            errors="coerce",
        ).round(
            4
        )

    print(
        selected_display.to_string(
            index=False
        )
    )
    print()

    print("SAVED FILES")
    print(SIMULATION_BANK_PATH)
    print(TEAM_INDEX_PATH)
    print(FIRST_ROUND_PARQUET_PATH)
    print(FIRST_ROUND_CSV_PATH)
    print(SECOND_ROUND_PARQUET_PATH)
    print(SECOND_ROUND_CSV_PATH)
    print(COMBINED_PICK_VALUES_PARQUET_PATH)
    print(COMBINED_PICK_VALUES_CSV_PATH)
    print(FLOOR_AUDIT_PATH)
    print(GROUP_AUDIT_PATH)
    print(V2_COMPARISON_PATH)
    print(SELECTED_TEAMS_PATH)
    print(METADATA_PATH)


if __name__ == "__main__":
    main()
