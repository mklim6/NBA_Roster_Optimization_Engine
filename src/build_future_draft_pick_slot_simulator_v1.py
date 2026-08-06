from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


SCRIPT_VERSION = "future-draft-pick-slot-simulator-v1-2026-08-04"

PROJECT_ROOT = Path(__file__).resolve().parents[1]

TEAM_PROJECTIONS_PATH = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "future_team_strength_projections_2026_27_to_2032_33_v1.parquet"
)

CALIBRATED_PICK_CURVE_PATH = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "historical_draft_pick_value_curve_1_60_v2_calibrated.parquet"
)

PROCESSED_DIRECTORY = (
    PROJECT_ROOT
    / "data"
    / "processed"
)

OUTPUT_DIRECTORY = PROJECT_ROOT / "outputs"

FIRST_ROUND_DISTRIBUTIONS_PATH = (
    PROCESSED_DIRECTORY
    / "future_own_first_round_pick_distributions_2027_2029_v1.parquet"
)

FIRST_ROUND_DISTRIBUTIONS_CSV_PATH = (
    PROCESSED_DIRECTORY
    / "future_own_first_round_pick_distributions_2027_2029_v1.csv"
)

SECOND_ROUND_DISTRIBUTIONS_PATH = (
    PROCESSED_DIRECTORY
    / "future_own_second_round_pick_distributions_2027_2029_v1.parquet"
)

SECOND_ROUND_DISTRIBUTIONS_CSV_PATH = (
    PROCESSED_DIRECTORY
    / "future_own_second_round_pick_distributions_2027_2029_v1.csv"
)

COMBINED_PICK_ASSETS_PATH = (
    PROCESSED_DIRECTORY
    / "future_originating_team_pick_values_2027_2029_v1.parquet"
)

COMBINED_PICK_ASSETS_CSV_PATH = (
    PROCESSED_DIRECTORY
    / "future_originating_team_pick_values_2027_2029_v1.csv"
)

SELECTED_PICK_SUMMARY_PATH = (
    OUTPUT_DIRECTORY
    / "future_draft_pick_slot_selected_teams_v1.csv"
)

LOTTERY_GROUP_AUDIT_PATH = (
    OUTPUT_DIRECTORY
    / "future_draft_pick_lottery_group_audit_v1.csv"
)

METADATA_PATH = (
    OUTPUT_DIRECTORY
    / "future_draft_pick_slot_simulator_metadata_v1.json"
)


OFFICIAL_DRAFT_YEARS = [
    2027,
    2028,
    2029,
]

TEAM_PROJECTION_SEASON_BY_DRAFT_YEAR = {
    2027: "2026-27",
    2028: "2027-28",
    2029: "2028-29",
}

EASTERN_CONFERENCE_TEAMS = {
    "ATL",
    "BOS",
    "BKN",
    "CHA",
    "CHI",
    "CLE",
    "DET",
    "IND",
    "MIA",
    "MIL",
    "NYK",
    "ORL",
    "PHI",
    "TOR",
    "WAS",
}

WESTERN_CONFERENCE_TEAMS = {
    "DAL",
    "DEN",
    "GSW",
    "HOU",
    "LAC",
    "LAL",
    "MEM",
    "MIN",
    "NOP",
    "OKC",
    "PHX",
    "POR",
    "SAC",
    "SAS",
    "UTA",
}

# Top-five results of each team's own pick entering the new system.
# These are needed only for the new consecutive-pick restrictions.
INITIAL_OWN_PICK_HISTORY = {
    "DAL": {
        2025: 1,
    },
    "SAS": {
        2025: 2,
    },
    "PHI": {
        2025: 3,
    },
    "CHA": {
        2025: 4,
    },
    "UTA": {
        2025: 5,
        2026: 2,
    },
    "WAS": {
        2026: 1,
    },
    "MEM": {
        2026: 3,
    },
    "CHI": {
        2026: 4,
    },
    "LAC": {
        2026: 5,
    },
}

LOTTERY_BALLS_BY_GROUP = {
    "draft_relegated_bottom_three": 2,
    "other_non_play_in_bottom_ten": 3,
    "conference_seed_9_or_10": 2,
    "loser_of_7_8_play_in_game": 1,
}

TIME_DISCOUNT_RATE_BY_YEARS_AHEAD = 0.92

REQUIRED_TEAM_COLUMNS = [
    "projection_season",
    "team_abbreviation",
    "team_strength_mean",
    "team_strength_sd",
]

REQUIRED_PICK_CURVE_COLUMNS = [
    "overall_pick",
    "historical_pick_value_score",
    "historical_pick_value_rating_60_99",
    "rotation_probability_calibrated",
    "starter_probability_calibrated",
    "star_proxy_probability_calibrated",
    "year4_active_probability_calibrated",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Simulate 2027-2029 NBA first- and second-round "
            "own-pick slot distributions from projected team strength "
            "under the official 3-2-1 Lottery structure."
        )
    )

    parser.add_argument(
        "--simulations",
        type=int,
        default=50_000,
        help=(
            "Number of multi-year draft simulations. "
            "The default is 50,000."
        ),
    )

    parser.add_argument(
        "--random-seed",
        type=int,
        default=20260804,
        help="Random seed for reproducibility.",
    )

    return parser.parse_args()


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
            + "\n".join(missing)
        )


def numeric_series(
    frame: pd.DataFrame,
    column: str,
    fill_value: float | None = None,
) -> pd.Series:
    values = pd.to_numeric(
        frame[column],
        errors="coerce",
    )

    if fill_value is not None:
        values = values.fillna(
            fill_value
        )

    return values.astype(float)


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


def load_inputs() -> tuple[
    pd.DataFrame,
    pd.DataFrame,
]:
    for path in [
        TEAM_PROJECTIONS_PATH,
        CALIBRATED_PICK_CURVE_PATH,
    ]:
        if not path.exists():
            raise FileNotFoundError(
                f"Required file was not found:\n{path}"
            )

    team_projections = normalize_columns(
        pd.read_parquet(
            TEAM_PROJECTIONS_PATH
        )
    )

    pick_curve = normalize_columns(
        pd.read_parquet(
            CALIBRATED_PICK_CURVE_PATH
        )
    )

    require_columns(
        team_projections,
        REQUIRED_TEAM_COLUMNS,
        "Future team-strength projections",
    )

    require_columns(
        pick_curve,
        REQUIRED_PICK_CURVE_COLUMNS,
        "Calibrated historical pick curve",
    )

    team_projections[
        "team_strength_mean"
    ] = numeric_series(
        team_projections,
        "team_strength_mean",
    )

    team_projections[
        "team_strength_sd"
    ] = numeric_series(
        team_projections,
        "team_strength_sd",
    ).clip(
        lower=1e-6,
    )

    pick_curve[
        "overall_pick"
    ] = numeric_series(
        pick_curve,
        "overall_pick",
    ).round().astype(int)

    return (
        team_projections,
        pick_curve.sort_values(
            "overall_pick"
        ).reset_index(
            drop=True
        ),
    )


def validate_team_universe(
    team_projections: pd.DataFrame,
) -> list[str]:
    required_seasons = set(
        TEAM_PROJECTION_SEASON_BY_DRAFT_YEAR.values()
    )

    available_seasons = set(
        team_projections[
            "projection_season"
        ].astype(str).unique()
    )

    missing_seasons = (
        required_seasons
        - available_seasons
    )

    if missing_seasons:
        raise ValueError(
            "Team-strength projections are missing seasons:\n"
            + "\n".join(
                sorted(
                    missing_seasons
                )
            )
        )

    teams = sorted(
        team_projections.loc[
            team_projections[
                "projection_season"
            ].isin(
                required_seasons
            ),
            "team_abbreviation",
        ]
        .astype(str)
        .unique()
        .tolist()
    )

    expected_teams = (
        EASTERN_CONFERENCE_TEAMS
        | WESTERN_CONFERENCE_TEAMS
    )

    if set(
        teams
    ) != expected_teams:
        missing = sorted(
            expected_teams
            - set(
                teams
            )
        )

        unexpected = sorted(
            set(
                teams
            )
            - expected_teams
        )

        raise ValueError(
            "Team universe does not match the expected 30 teams.\n"
            f"Missing: {missing}\n"
            f"Unexpected: {unexpected}"
        )

    counts = (
        team_projections.loc[
            team_projections[
                "projection_season"
            ].isin(
                required_seasons
            )
        ]
        .groupby(
            "projection_season"
        )[
            "team_abbreviation"
        ]
        .nunique()
    )

    if not counts.eq(
        30
    ).all():
        raise ValueError(
            "Every simulated season must contain exactly 30 teams.\n"
            + counts.to_string()
        )

    return teams


def conference_for_team(
    team: str,
) -> str:
    if team in EASTERN_CONFERENCE_TEAMS:
        return "East"

    if team in WESTERN_CONFERENCE_TEAMS:
        return "West"

    raise ValueError(
        f"Unknown team abbreviation: {team}"
    )


def strength_draws_for_draft_year(
    team_projections: pd.DataFrame,
    draft_year: int,
    simulations: int,
    rng: np.random.Generator,
) -> tuple[
    list[str],
    np.ndarray,
]:
    season = (
        TEAM_PROJECTION_SEASON_BY_DRAFT_YEAR[
            draft_year
        ]
    )

    frame = (
        team_projections.loc[
            team_projections[
                "projection_season"
            ].eq(
                season
            )
        ]
        .sort_values(
            "team_abbreviation"
        )
        .reset_index(
            drop=True
        )
    )

    teams = frame[
        "team_abbreviation"
    ].astype(str).tolist()

    means = frame[
        "team_strength_mean"
    ].to_numpy(
        dtype=float
    )

    standard_deviations = frame[
        "team_strength_sd"
    ].to_numpy(
        dtype=float
    )

    draws = rng.normal(
        loc=means,
        scale=standard_deviations,
        size=(
            simulations,
            len(
                teams
            ),
        ),
    )

    return (
        teams,
        draws,
    )


def logistic_win_probability(
    strength_a: float,
    strength_b: float,
    scale: float,
) -> float:
    difference = (
        strength_a
        - strength_b
    )

    clipped = float(
        np.clip(
            difference
            / scale,
            -20.0,
            20.0,
        )
    )

    return float(
        1.0
        / (
            1.0
            + np.exp(
                -clipped
            )
        )
    )


def previous_own_pick_slot(
    simulated_history: dict[
        str,
        dict[
            int,
            int,
        ],
    ],
    team: str,
    draft_year: int,
) -> int | None:
    if (
        team in simulated_history
        and draft_year
        in simulated_history[
            team
        ]
    ):
        return simulated_history[
            team
        ][
            draft_year
        ]

    if (
        team in INITIAL_OWN_PICK_HISTORY
        and draft_year
        in INITIAL_OWN_PICK_HISTORY[
            team
        ]
    ):
        return INITIAL_OWN_PICK_HISTORY[
            team
        ][
            draft_year
        ]

    return None


def no_number_one_eligibility(
    simulated_history: dict[
        str,
        dict[
            int,
            int,
        ],
    ],
    team: str,
    draft_year: int,
) -> bool:
    previous_slot = previous_own_pick_slot(
        simulated_history=simulated_history,
        team=team,
        draft_year=(
            draft_year
            - 1
        ),
    )

    return previous_slot != 1


def top_five_eligibility(
    simulated_history: dict[
        str,
        dict[
            int,
            int,
        ],
    ],
    team: str,
    draft_year: int,
) -> bool:
    previous_one = previous_own_pick_slot(
        simulated_history=simulated_history,
        team=team,
        draft_year=(
            draft_year
            - 1
        ),
    )

    previous_two = previous_own_pick_slot(
        simulated_history=simulated_history,
        team=team,
        draft_year=(
            draft_year
            - 2
        ),
    )

    had_two_consecutive_top_five = (
        previous_one is not None
        and previous_two is not None
        and previous_one <= 5
        and previous_two <= 5
    )

    return not had_two_consecutive_top_five


def weighted_lottery_permutation(
    participants: list[str],
    balls_by_team: dict[str, int],
    simulated_history: dict[
        str,
        dict[
            int,
            int,
        ],
    ],
    draft_year: int,
    rng: np.random.Generator,
) -> list[str]:
    remaining = list(
        participants
    )

    order = []

    for pick_number in range(
        1,
        17,
    ):
        eligible = []

        for team in remaining:
            if (
                pick_number == 1
                and not no_number_one_eligibility(
                    simulated_history=(
                        simulated_history
                    ),
                    team=team,
                    draft_year=draft_year,
                )
            ):
                continue

            if (
                pick_number <= 5
                and not top_five_eligibility(
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
                "No eligible teams remained for a lottery pick. "
                "The restriction implementation needs review."
            )

        weights = np.array(
            [
                balls_by_team[
                    team
                ]
                for team
                in eligible
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

    return order


def simulate_one_draft(
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

    for conference, conference_teams in [
        (
            "East",
            EASTERN_CONFERENCE_TEAMS,
        ),
        (
            "West",
            WESTERN_CONFERENCE_TEAMS,
        ),
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
                        for team
                        in ordered
                    ],
                    ddof=1,
                )
            )
            * 0.55,
            1.0,
        )

        probability_seven_wins = (
            logistic_win_probability(
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
            "Expected exactly two 7/8 play-in losers."
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

    for team in bottom_three:
        group = (
            "draft_relegated_bottom_three"
        )

        balls_by_team[
            team
        ] = LOTTERY_BALLS_BY_GROUP[
            group
        ]

        group_by_team[
            team
        ] = group

    for team in other_bottom_seven:
        group = (
            "other_non_play_in_bottom_ten"
        )

        balls_by_team[
            team
        ] = LOTTERY_BALLS_BY_GROUP[
            group
        ]

        group_by_team[
            team
        ] = group

    for team in nine_ten_seeds:
        group = (
            "conference_seed_9_or_10"
        )

        balls_by_team[
            team
        ] = LOTTERY_BALLS_BY_GROUP[
            group
        ]

        group_by_team[
            team
        ] = group

    for team in seven_eight_losers:
        group = (
            "loser_of_7_8_play_in_game"
        )

        balls_by_team[
            team
        ] = LOTTERY_BALLS_BY_GROUP[
            group
        ]

        group_by_team[
            team
        ] = group

    lottery_order = (
        weighted_lottery_permutation(
            participants=participants,
            balls_by_team=(
                balls_by_team
            ),
            simulated_history=(
                simulated_history
            ),
            draft_year=draft_year,
            rng=rng,
        )
    )

    first_round_slots = {
        team: pick
        for pick, team
        in enumerate(
            lottery_order,
            start=1,
        )
    }

    non_lottery_teams = [
        team
        for team in teams
        if team
        not in first_round_slots
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
        for rank, team
        in enumerate(
            league_order_best_to_worst,
            start=1,
        )
    }

    second_round_slots = {
        team: (
            61
            - rank
        )
        for team, rank
        in league_rank.items()
    }

    return (
        first_round_slots,
        second_round_slots,
        group_by_team,
        balls_by_team,
    )


def summarize_slot_distribution(
    slot_matrix: np.ndarray,
    teams: list[str],
    draft_year: int,
    round_number: int,
    pick_curve: pd.DataFrame,
) -> pd.DataFrame:
    pick_lookup = (
        pick_curve.set_index(
            "overall_pick"
        )
    )

    value_scores = pick_lookup[
        "historical_pick_value_score"
    ].to_dict()

    display_ratings = pick_lookup[
        (
            "historical_pick_value_"
            "rating_60_99"
        )
    ].to_dict()

    rotation_probabilities = (
        pick_lookup[
            "rotation_probability_calibrated"
        ].to_dict()
    )

    starter_probabilities = (
        pick_lookup[
            "starter_probability_calibrated"
        ].to_dict()
    )

    star_probabilities = (
        pick_lookup[
            "star_proxy_probability_calibrated"
        ].to_dict()
    )

    year4_probabilities = (
        pick_lookup[
            "year4_active_probability_calibrated"
        ].to_dict()
    )

    years_ahead = (
        draft_year
        - 2026
    )

    time_discount_factor = (
        TIME_DISCOUNT_RATE_BY_YEARS_AHEAD
        ** years_ahead
    )

    rows = []

    for team_index, team in enumerate(
        teams
    ):
        slots = slot_matrix[
            :,
            team_index,
        ].astype(int)

        values = np.array(
            [
                value_scores[
                    int(
                        slot
                    )
                ]
                for slot in slots
            ],
            dtype=float,
        )

        ratings = np.array(
            [
                display_ratings[
                    int(
                        slot
                    )
                ]
                for slot in slots
            ],
            dtype=float,
        )

        rotation = np.array(
            [
                rotation_probabilities[
                    int(
                        slot
                    )
                ]
                for slot in slots
            ],
            dtype=float,
        )

        starter = np.array(
            [
                starter_probabilities[
                    int(
                        slot
                    )
                ]
                for slot in slots
            ],
            dtype=float,
        )

        star = np.array(
            [
                star_probabilities[
                    int(
                        slot
                    )
                ]
                for slot in slots
            ],
            dtype=float,
        )

        year4 = np.array(
            [
                year4_probabilities[
                    int(
                        slot
                    )
                ]
                for slot in slots
            ],
            dtype=float,
        )

        row = {
            "originating_team": (
                team
            ),
            "draft_year": (
                draft_year
            ),
            "round_number": (
                round_number
            ),
            "pick_asset_label": (
                f"{draft_year} {team} "
                f"Round {round_number}"
            ),
            "expected_overall_pick": float(
                np.mean(
                    slots
                )
            ),
            "median_overall_pick": float(
                np.median(
                    slots
                )
            ),
            "overall_pick_p10": float(
                np.quantile(
                    slots,
                    0.10,
                )
            ),
            "overall_pick_p90": float(
                np.quantile(
                    slots,
                    0.90,
                )
            ),
            "expected_historical_pick_value_score": float(
                np.mean(
                    values
                )
            ),
            "time_discount_factor": (
                time_discount_factor
            ),
            "time_discounted_pick_value_score": float(
                np.mean(
                    values
                )
                * time_discount_factor
            ),
            "expected_pick_value_rating_60_99": float(
                np.mean(
                    ratings
                )
            ),
            "expected_rotation_probability": float(
                np.mean(
                    rotation
                )
            ),
            "expected_starter_probability": float(
                np.mean(
                    starter
                )
            ),
            "expected_star_proxy_probability": float(
                np.mean(
                    star
                )
            ),
            "expected_year4_active_probability": float(
                np.mean(
                    year4
                )
            ),
            "pick_value_score_sd": float(
                np.std(
                    values,
                    ddof=1,
                )
            ),
            "pick_slot_sd": float(
                np.std(
                    slots,
                    ddof=1,
                )
            ),
        }

        if round_number == 1:
            row.update(
                {
                    "number_one_probability": float(
                        np.mean(
                            slots == 1
                        )
                    ),
                    "top_three_probability": float(
                        np.mean(
                            slots <= 3
                        )
                    ),
                    "top_five_probability": float(
                        np.mean(
                            slots <= 5
                        )
                    ),
                    "top_ten_probability": float(
                        np.mean(
                            slots <= 10
                        )
                    ),
                    "lottery_top_16_probability": float(
                        np.mean(
                            slots <= 16
                        )
                    ),
                    "late_first_probability": float(
                        np.mean(
                            slots >= 25
                        )
                    ),
                }
            )
        else:
            row.update(
                {
                    "early_second_probability": float(
                        np.mean(
                            slots <= 40
                        )
                    ),
                    "middle_second_probability": float(
                        np.mean(
                            (
                                slots >= 41
                            )
                            & (
                                slots <= 50
                            )
                        )
                    ),
                    "late_second_probability": float(
                        np.mean(
                            slots >= 51
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


def simulate_all_drafts(
    team_projections: pd.DataFrame,
    pick_curve: pd.DataFrame,
    teams: list[str],
    simulations: int,
    random_seed: int,
) -> tuple[
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
]:
    if simulations < 5_000:
        raise ValueError(
            "--simulations must be at least 5,000."
        )

    rng = np.random.default_rng(
        random_seed
    )

    strength_draws = {}

    for draft_year in OFFICIAL_DRAFT_YEARS:
        (
            year_teams,
            draws,
        ) = strength_draws_for_draft_year(
            team_projections=(
                team_projections
            ),
            draft_year=draft_year,
            simulations=simulations,
            rng=rng,
        )

        if year_teams != teams:
            raise ValueError(
                "Team order changed between projection seasons."
            )

        strength_draws[
            draft_year
        ] = draws

    team_to_index = {
        team: index
        for index, team in enumerate(
            teams
        )
    }

    first_round_slots = {
        draft_year: np.zeros(
            (
                simulations,
                len(
                    teams
                ),
            ),
            dtype=np.int16,
        )
        for draft_year in (
            OFFICIAL_DRAFT_YEARS
        )
    }

    second_round_slots = {
        draft_year: np.zeros(
            (
                simulations,
                len(
                    teams
                ),
            ),
            dtype=np.int16,
        )
        for draft_year in (
            OFFICIAL_DRAFT_YEARS
        )
    }

    group_counts = {
        (
            draft_year,
            team,
            group,
        ): 0
        for draft_year in OFFICIAL_DRAFT_YEARS
        for team in teams
        for group in (
            LOTTERY_BALLS_BY_GROUP
        )
    }

    restriction_counts = {
        (
            draft_year,
            team,
            "number_one_ineligible",
        ): 0
        for draft_year in (
            OFFICIAL_DRAFT_YEARS
        )
        for team in teams
    }

    restriction_counts.update(
        {
            (
                draft_year,
                team,
                "top_five_ineligible",
            ): 0
            for draft_year in (
                OFFICIAL_DRAFT_YEARS
            )
            for team in teams
        }
    )

    for simulation_index in range(
        simulations
    ):
        simulated_history: dict[
            str,
            dict[
                int,
                int,
            ],
        ] = {}

        for draft_year in (
            OFFICIAL_DRAFT_YEARS
        ):
            for team in teams:
                if not no_number_one_eligibility(
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

                if not top_five_eligibility(
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
                balls,
            ) = simulate_one_draft(
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

                first_round_slots[
                    draft_year
                ][
                    simulation_index,
                    team_index,
                ] = first_slots[
                    team
                ]

                second_round_slots[
                    draft_year
                ][
                    simulation_index,
                    team_index,
                ] = second_slots[
                    team
                ]

                simulated_history.setdefault(
                    team,
                    {},
                )[
                    draft_year
                ] = first_slots[
                    team
                ]

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

    first_summaries = []

    second_summaries = []

    for draft_year in OFFICIAL_DRAFT_YEARS:
        first_summary = (
            summarize_slot_distribution(
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
        )

        second_summary = (
            summarize_slot_distribution(
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
        )

        for team in teams:
            mask = (
                first_summary[
                    "originating_team"
                ].eq(
                    team
                )
            )

            first_summary.loc[
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
                / simulations
            )

            first_summary.loc[
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
                / simulations
            )

        first_summaries.append(
            first_summary
        )

        second_summaries.append(
            second_summary
        )

    first_output = pd.concat(
        first_summaries,
        ignore_index=True,
    )

    second_output = pd.concat(
        second_summaries,
        ignore_index=True,
    )

    group_rows = []

    for (
        draft_year,
        team,
        group,
    ), count in group_counts.items():
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
                    / simulations
                ),
                "lottery_balls": (
                    LOTTERY_BALLS_BY_GROUP[
                        group
                    ]
                ),
            }
        )

    group_audit = pd.DataFrame(
        group_rows
    )

    return (
        first_output,
        second_output,
        group_audit,
    )


def main() -> None:
    args = parse_args()

    for directory in [
        PROCESSED_DIRECTORY,
        OUTPUT_DIRECTORY,
    ]:
        directory.mkdir(
            parents=True,
            exist_ok=True,
        )

    print("=" * 80)
    print("FUTURE NBA DRAFT-PICK SLOT SIMULATOR")
    print("=" * 80)
    print(
        f"Script version: {SCRIPT_VERSION}"
    )
    print(
        "Official draft years simulated: "
        + ", ".join(
            str(
                year
            )
            for year in OFFICIAL_DRAFT_YEARS
        )
    )
    print(
        f"Multi-year simulations: "
        f"{args.simulations:,}"
    )
    print()

    (
        team_projections,
        pick_curve,
    ) = load_inputs()

    teams = validate_team_universe(
        team_projections
    )

    (
        first_round,
        second_round,
        group_audit,
    ) = simulate_all_drafts(
        team_projections=team_projections,
        pick_curve=pick_curve,
        teams=teams,
        simulations=args.simulations,
        random_seed=args.random_seed,
    )

    first_round[
        "official_rule_status"
    ] = (
        "Official 3-2-1 Lottery structure for 2027-2029"
    )

    first_round[
        "restriction_implementation_note"
    ] = (
        "No. 1 in consecutive drafts and top-five in three "
        "consecutive drafts are enforced. The redistribution "
        "mechanism is modeled as an eligible-team redraw because "
        "the NBA has not yet published a detailed drawing protocol."
    )

    second_round[
        "official_rule_status"
    ] = (
        "Second-round slot proxy from inverse simulated "
        "regular-season strength"
    )

    combined = pd.concat(
        [
            first_round,
            second_round,
        ],
        ignore_index=True,
        sort=False,
    )

    first_round.to_parquet(
        FIRST_ROUND_DISTRIBUTIONS_PATH,
        index=False,
    )

    first_round.to_csv(
        FIRST_ROUND_DISTRIBUTIONS_CSV_PATH,
        index=False,
    )

    second_round.to_parquet(
        SECOND_ROUND_DISTRIBUTIONS_PATH,
        index=False,
    )

    second_round.to_csv(
        SECOND_ROUND_DISTRIBUTIONS_CSV_PATH,
        index=False,
    )

    combined.to_parquet(
        COMBINED_PICK_ASSETS_PATH,
        index=False,
    )

    combined.to_csv(
        COMBINED_PICK_ASSETS_CSV_PATH,
        index=False,
    )

    group_audit.to_csv(
        LOTTERY_GROUP_AUDIT_PATH,
        index=False,
    )

    selected_teams = [
        "BKN",
        "GSW",
        "LAC",
        "OKC",
        "ORL",
        "PHI",
        "SAS",
        "UTA",
        "WAS",
    ]

    selected_summary = combined.loc[
        combined[
            "originating_team"
        ].isin(
            selected_teams
        ),
        [
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
            *[
                column
                for column in [
                    "number_one_probability",
                    "top_five_probability",
                    "top_ten_probability",
                    "lottery_top_16_probability",
                    "early_second_probability",
                    "late_second_probability",
                ]
                if column
                in combined.columns
            ],
        ],
    ].copy()

    selected_summary.to_csv(
        SELECTED_PICK_SUMMARY_PATH,
        index=False,
    )

    metadata = {
        "script_version": SCRIPT_VERSION,
        "created_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "draft_years": (
            OFFICIAL_DRAFT_YEARS
        ),
        "simulations": int(
            args.simulations
        ),
        "random_seed": int(
            args.random_seed
        ),
        "teams": len(
            teams
        ),
        "lottery_balls_by_group": (
            LOTTERY_BALLS_BY_GROUP
        ),
        "time_discount_rate_per_year": (
            TIME_DISCOUNT_RATE_BY_YEARS_AHEAD
        ),
        "prior_own_pick_history_used": (
            INITIAL_OWN_PICK_HISTORY
        ),
        "official_rules_encoded": [
            (
                "Sixteen teams participate in the lottery."
            ),
            (
                "The three worst non-play-in teams receive "
                "two balls each."
            ),
            (
                "The next seven non-play-in teams receive "
                "three balls each."
            ),
            (
                "Conference seeds 9 and 10 receive two balls."
            ),
            (
                "The loser of each conference 7-vs-8 "
                "Play-In game receives one ball."
            ),
            (
                "The drawing orders all first 16 picks."
            ),
            (
                "No own pick may be No. 1 in consecutive drafts."
            ),
            (
                "No own pick may be top five in three "
                "consecutive drafts."
            ),
        ],
        "important_inferences": [
            (
                "The detailed NBA drawing protocol for applying "
                "the consecutive-pick restrictions has not yet "
                "been published. This model redistributes an "
                "ineligible selection through an eligible-team redraw."
            ),
            (
                "The 7-vs-8 Play-In loser is simulated from relative "
                "team strength with a logistic game model."
            ),
            (
                "Second-round order is approximated from inverse "
                "regular-season strength and does not include "
                "forfeitures or tie-break procedures."
            ),
        ],
        "limitations": [
            (
                "This creates values for each originating team's "
                "own pick. It does not yet map the pick to its "
                "current owner."
            ),
            (
                "Protections, swaps, rollover language, and "
                "conveyance dependencies are not yet applied."
            ),
            (
                "Rules after the 2029 Draft are intentionally "
                "excluded because the NBA has not finalized them."
            ),
            (
                "Draft-class quality adjustments are not yet included."
            ),
        ],
        "output_files": {
            "first_round_distributions": str(
                FIRST_ROUND_DISTRIBUTIONS_PATH
            ),
            "second_round_distributions": str(
                SECOND_ROUND_DISTRIBUTIONS_PATH
            ),
            "combined_pick_assets": str(
                COMBINED_PICK_ASSETS_PATH
            ),
            "selected_summary": str(
                SELECTED_PICK_SUMMARY_PATH
            ),
            "lottery_group_audit": str(
                LOTTERY_GROUP_AUDIT_PATH
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
    print("FUTURE PICK-SLOT DISTRIBUTIONS CREATED")
    print("=" * 80)
    print(
        "First-round originating-team assets: "
        f"{len(first_round):,}"
    )
    print(
        "Second-round originating-team assets: "
        f"{len(second_round):,}"
    )
    print(
        "Combined pick-asset rows: "
        f"{len(combined):,}"
    )
    print()

    for draft_year in (
        OFFICIAL_DRAFT_YEARS
    ):
        print(
            f"HIGHEST-VALUE FIRST-ROUND PICKS: {draft_year}"
        )

        display = (
            first_round.loc[
                first_round[
                    "draft_year"
                ].eq(
                    draft_year
                )
            ]
            .sort_values(
                (
                    "time_discounted_"
                    "pick_value_score"
                ),
                ascending=False,
            )
            .head(
                10
            )[
                [
                    "originating_team",
                    "expected_overall_pick",
                    "overall_pick_p10",
                    "overall_pick_p90",
                    "expected_pick_value_rating_60_99",
                    "number_one_probability",
                    "top_five_probability",
                    "top_ten_probability",
                    "lottery_top_16_probability",
                    (
                        "time_discounted_"
                        "pick_value_score"
                    ),
                ]
            ]
            .copy()
        )

        for column in [
            "number_one_probability",
            "top_five_probability",
            "top_ten_probability",
            "lottery_top_16_probability",
        ]:
            display[column] = (
                display[column]
                * 100.0
            )

        for column in display.columns:
            if column != "originating_team":
                display[column] = (
                    pd.to_numeric(
                        display[column],
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
    print(FIRST_ROUND_DISTRIBUTIONS_PATH)
    print(FIRST_ROUND_DISTRIBUTIONS_CSV_PATH)
    print(SECOND_ROUND_DISTRIBUTIONS_PATH)
    print(SECOND_ROUND_DISTRIBUTIONS_CSV_PATH)
    print(COMBINED_PICK_ASSETS_PATH)
    print(COMBINED_PICK_ASSETS_CSV_PATH)
    print(SELECTED_PICK_SUMMARY_PATH)
    print(LOTTERY_GROUP_AUDIT_PATH)
    print(METADATA_PATH)


if __name__ == "__main__":
    main()