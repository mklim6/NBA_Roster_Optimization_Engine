from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import json
import random
import statistics
import sys
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
OUTPUTS = ROOT / "outputs"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from freeform_trade_machine_engine_v3 import (  # noqa: E402
    load_runtime_data,
)
from mutable_league_state_v1 import (  # noqa: E402
    create_league_state,
)
from simulation_league_state_v1 import (  # noqa: E402
    GameStatus,
    LeaguePhase,
    ScheduledGame,
    SimulationLeagueState,
    SimulationLeagueStateError,
    add_scheduled_games,
    create_simulation_league_state,
    validate_simulation_league_state,
)
from state_runtime_adapter_v1 import (  # noqa: E402
    build_state_runtime,
)


SCHEDULE_ENGINE_VERSION = (
    "regular-season-schedule-engine-v1-2026-08-08"
)
SELF_TEST_REPORT = (
    OUTPUTS / "regular_season_schedule_v1_self_test.json"
)
SELF_TEST_SCHEDULE_CSV = (
    OUTPUTS / "regular_season_schedule_v1.csv"
)

TEAM_DIVISIONS: dict[
    str,
    dict[str, tuple[str, ...]],
] = {
    "East": {
        "Atlantic": (
            "BOS",
            "BKN",
            "NYK",
            "PHI",
            "TOR",
        ),
        "Central": (
            "CHI",
            "CLE",
            "DET",
            "IND",
            "MIL",
        ),
        "Southeast": (
            "ATL",
            "CHA",
            "MIA",
            "ORL",
            "WAS",
        ),
    },
    "West": {
        "Northwest": (
            "DEN",
            "MIN",
            "OKC",
            "POR",
            "UTA",
        ),
        "Pacific": (
            "GSW",
            "LAC",
            "LAL",
            "PHX",
            "SAC",
        ),
        "Southwest": (
            "DAL",
            "HOU",
            "MEM",
            "NOP",
            "SAS",
        ),
    },
}

ALL_TEAMS: tuple[str, ...] = tuple(
    team
    for conference in TEAM_DIVISIONS.values()
    for division in conference.values()
    for team in division
)

REGULAR_SEASON_GAMES_PER_TEAM = 82
LEAGUE_GAME_COUNT = 1230
HOME_GAMES_PER_TEAM = 41
AWAY_GAMES_PER_TEAM = 41
SCHEDULE_ROUND_COUNT = 87
CALENDAR_DAY_COUNT = 177
GLOBAL_OFF_DAY_COUNT = 3
GLOBAL_OFF_BEFORE_ROUNDS = (22, 44, 66)


class RegularSeasonScheduleError(RuntimeError):
    """Raised when schedule generation or installation fails."""


@dataclass(frozen=True)
class ScheduleRound:
    label: str
    category: str
    games: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class GeneratedRegularSeasonSchedule:
    engine_version: str
    season_label: str
    seed: int
    construction_seed: int
    generation_attempt: int
    games: tuple[ScheduledGame, ...]
    round_count: int
    calendar_days: int
    global_off_days: tuple[int, ...]
    signature: str


def pair_key(
    first_team: str,
    second_team: str,
) -> tuple[str, str]:
    return tuple(
        sorted(
            (
                str(first_team).strip().upper(),
                str(second_team).strip().upper(),
            )
        )
    )


def topology_maps() -> tuple[
    dict[str, str],
    dict[str, str],
]:
    conference_by_team: dict[str, str] = {}
    division_by_team: dict[str, str] = {}

    for conference, divisions in (
        TEAM_DIVISIONS.items()
    ):
        for division, teams in divisions.items():
            for team in teams:
                conference_by_team[team] = conference
                division_by_team[team] = division

    return conference_by_team, division_by_team


def circle_method_pairings(
    teams: Sequence[str],
) -> tuple[
    tuple[tuple[str, str], ...],
    ...,
]:
    rotation = [
        str(team).strip().upper()
        for team in teams
    ]

    if len(set(rotation)) != len(rotation):
        raise RegularSeasonScheduleError(
            "Round-robin teams must be unique."
        )

    if len(rotation) < 2:
        raise RegularSeasonScheduleError(
            "Round-robin generation requires at least two teams."
        )

    if len(rotation) % 2:
        rotation.append("")

    fixed = rotation[0]
    moving = rotation[1:]
    round_count = len(rotation) - 1
    rounds: list[tuple[tuple[str, str], ...]] = []

    for _ in range(round_count):
        current = [fixed, *moving]
        games: list[tuple[str, str]] = []

        for index in range(len(current) // 2):
            first = current[index]
            second = current[-1 - index]

            if first and second:
                games.append((first, second))

        rounds.append(tuple(games))
        moving = [moving[-1], *moving[:-1]]

    return tuple(rounds)


def balanced_round_orientation(
    pairings: Sequence[tuple[str, str]],
    round_index: int,
) -> tuple[tuple[str, str], ...]:
    games: list[tuple[str, str]] = []

    for slot_index, (
        first_team,
        second_team,
    ) in enumerate(pairings):
        if slot_index == 0:
            home_team = (
                first_team
                if round_index % 2 == 0
                else second_team
            )
        else:
            home_team = (
                second_team
                if round_index % 2 == 0
                else first_team
            )

        away_team = (
            second_team
            if home_team == first_team
            else first_team
        )
        games.append((home_team, away_team))

    return tuple(games)


def three_game_pair_map() -> tuple[
    set[tuple[str, str]],
    dict[tuple[str, str], str],
]:
    selected_pairs: set[tuple[str, str]] = set()
    home_advantage_team: dict[
        tuple[str, str],
        str,
    ] = {}

    for divisions in TEAM_DIVISIONS.values():
        division_names = list(divisions)
        division_pairs = (
            (
                division_names[0],
                division_names[1],
            ),
            (
                division_names[1],
                division_names[2],
            ),
            (
                division_names[2],
                division_names[0],
            ),
        )

        for left_name, right_name in division_pairs:
            left = divisions[left_name]
            right = divisions[right_name]

            for index in range(5):
                equal_index_pair = pair_key(
                    left[index],
                    right[index],
                )
                selected_pairs.add(equal_index_pair)
                home_advantage_team[
                    equal_index_pair
                ] = left[index]

                shifted_team = right[
                    (index + 1) % 5
                ]
                shifted_pair = pair_key(
                    left[index],
                    shifted_team,
                )
                selected_pairs.add(shifted_pair)
                home_advantage_team[
                    shifted_pair
                ] = shifted_team

    return selected_pairs, home_advantage_team


def matchup_blueprint() -> tuple[
    dict[tuple[str, str], int],
    dict[tuple[str, str], str],
]:
    conference_by_team, division_by_team = (
        topology_maps()
    )
    selected_three, home_advantage = (
        three_game_pair_map()
    )
    pair_counts: dict[tuple[str, str], int] = {}

    for first_index, first_team in enumerate(
        ALL_TEAMS
    ):
        for second_team in ALL_TEAMS[
            first_index + 1 :
        ]:
            key = pair_key(
                first_team,
                second_team,
            )

            if (
                conference_by_team[first_team]
                != conference_by_team[second_team]
            ):
                pair_counts[key] = 2
            elif (
                division_by_team[first_team]
                == division_by_team[second_team]
            ):
                pair_counts[key] = 4
            elif key in selected_three:
                pair_counts[key] = 3
            else:
                pair_counts[key] = 4

    return pair_counts, home_advantage


def baseline_rounds() -> tuple[
    tuple[ScheduleRound, ...],
    tuple[ScheduleRound, ...],
]:
    pair_rounds = circle_method_pairings(
        ALL_TEAMS
    )
    first_cycle: list[ScheduleRound] = []
    second_cycle: list[ScheduleRound] = []

    for round_index, pairs in enumerate(pair_rounds):
        first_games = balanced_round_orientation(
            pairs,
            round_index,
        )
        second_games = tuple(
            (away_team, home_team)
            for home_team, away_team in first_games
        )
        first_cycle.append(
            ScheduleRound(
                label=(
                    f"BASE-1-{round_index + 1:02d}"
                ),
                category="baseline_first_cycle",
                games=first_games,
            )
        )
        second_cycle.append(
            ScheduleRound(
                label=(
                    f"BASE-2-{round_index + 1:02d}"
                ),
                category="baseline_second_cycle",
                games=second_games,
            )
        )

    return tuple(first_cycle), tuple(second_cycle)


def conference_first_extra_rounds() -> tuple[
    tuple[ScheduleRound, ...],
    dict[tuple[str, str], str],
]:
    selected_three, home_advantage = (
        three_game_pair_map()
    )
    combined_pair_rounds: list[
        list[tuple[str, str]]
    ] = [[] for _ in range(15)]
    combined_oriented_rounds: list[
        list[tuple[str, str]]
    ] = [[] for _ in range(15)]

    for divisions in TEAM_DIVISIONS.values():
        conference_teams = tuple(
            team
            for division in divisions.values()
            for team in division
        )
        pair_rounds = circle_method_pairings(
            conference_teams
        )

        for round_index, pairings in enumerate(
            pair_rounds
        ):
            combined_pair_rounds[
                round_index
            ].extend(pairings)
            combined_oriented_rounds[
                round_index
            ].extend(
                balanced_round_orientation(
                    pairings,
                    round_index,
                )
            )

    first_extra_home: dict[
        tuple[str, str],
        str,
    ] = {}
    rounds: list[ScheduleRound] = []

    for round_index, (
        pairings,
        balanced_games,
    ) in enumerate(
        zip(
            combined_pair_rounds,
            combined_oriented_rounds,
            strict=True,
        )
    ):
        balanced_home = {
            pair_key(home_team, away_team): (
                home_team
            )
            for home_team, away_team
            in balanced_games
        }
        games: list[tuple[str, str]] = []

        for first_team, second_team in pairings:
            key = pair_key(
                first_team,
                second_team,
            )

            if key in selected_three:
                home_team = home_advantage[key]
            else:
                home_team = balanced_home[key]
                first_extra_home[key] = home_team

            away_team = (
                second_team
                if home_team == first_team
                else first_team
            )
            games.append((home_team, away_team))

        rounds.append(
            ScheduleRound(
                label=(
                    f"CONF-EXTRA-1-"
                    f"{round_index + 1:02d}"
                ),
                category="conference_first_extra",
                games=tuple(games),
            )
        )

    return tuple(rounds), first_extra_home


def conference_second_extra_rounds(
    first_extra_home: Mapping[
        tuple[str, str],
        str,
    ],
) -> tuple[ScheduleRound, ...]:
    division_rounds: list[ScheduleRound] = []

    for round_index in range(5):
        games: list[tuple[str, str]] = []

        for divisions in TEAM_DIVISIONS.values():
            for teams in divisions.values():
                division_pairings = (
                    circle_method_pairings(teams)[
                        round_index
                    ]
                )

                for first_team, second_team in (
                    division_pairings
                ):
                    key = pair_key(
                        first_team,
                        second_team,
                    )
                    first_home = first_extra_home[key]
                    second_home = (
                        second_team
                        if first_home == first_team
                        else first_team
                    )
                    second_away = (
                        second_team
                        if second_home == first_team
                        else first_team
                    )
                    games.append(
                        (
                            second_home,
                            second_away,
                        )
                    )

        division_rounds.append(
            ScheduleRound(
                label=(
                    f"DIVISION-EXTRA-2-"
                    f"{round_index + 1:02d}"
                ),
                category="division_second_extra",
                games=tuple(games),
            )
        )

    cross_division_rounds: list[
        ScheduleRound
    ] = []

    for division_pair_index in range(3):
        games_by_offset: dict[
            int,
            list[tuple[str, str]],
        ] = {
            2: [],
            3: [],
            4: [],
        }

        for divisions in TEAM_DIVISIONS.values():
            division_names = list(divisions)
            division_pairs = (
                (
                    division_names[0],
                    division_names[1],
                ),
                (
                    division_names[1],
                    division_names[2],
                ),
                (
                    division_names[2],
                    division_names[0],
                ),
            )
            left_name, right_name = (
                division_pairs[
                    division_pair_index
                ]
            )
            left = divisions[left_name]
            right = divisions[right_name]

            for offset in (2, 3, 4):
                for index in range(5):
                    first_team = left[index]
                    second_team = right[
                        (index + offset) % 5
                    ]
                    key = pair_key(
                        first_team,
                        second_team,
                    )
                    first_home = (
                        first_extra_home[key]
                    )
                    second_home = (
                        second_team
                        if first_home == first_team
                        else first_team
                    )
                    second_away = (
                        second_team
                        if second_home == first_team
                        else first_team
                    )
                    games_by_offset[
                        offset
                    ].append(
                        (
                            second_home,
                            second_away,
                        )
                    )

        for offset in (2, 3, 4):
            cross_division_rounds.append(
                ScheduleRound(
                    label=(
                        "CROSS-DIVISION-EXTRA-2-"
                        f"{division_pair_index + 1}-"
                        f"{offset}"
                    ),
                    category=(
                        "cross_division_second_extra"
                    ),
                    games=tuple(
                        games_by_offset[offset]
                    ),
                )
            )

    return tuple(
        [
            *division_rounds,
            *cross_division_rounds,
        ]
    )


def round_pair_set(
    schedule_round: ScheduleRound,
) -> set[tuple[str, str]]:
    return {
        pair_key(home_team, away_team)
        for home_team, away_team
        in schedule_round.games
    }


def order_schedule_rounds(
    *,
    seed: int,
) -> tuple[ScheduleRound, ...]:
    first_cycle, second_cycle = baseline_rounds()
    first_extra, first_extra_home = (
        conference_first_extra_rounds()
    )
    second_extra = (
        conference_second_extra_rounds(
            first_extra_home
        )
    )
    extras = [
        *first_extra,
        *second_extra,
    ]

    if len(extras) != 29:
        raise RegularSeasonScheduleError(
            "Expected 29 conference-extra rounds."
        )

    randomizer = random.Random(int(seed))
    ordered: list[ScheduleRound] = []
    last_pair_round: dict[
        tuple[str, str],
        int,
    ] = {}
    remaining_extra = list(range(len(extras)))
    remaining_second_cycle = list(
        range(len(second_cycle))
    )

    def append_round(
        schedule_round: ScheduleRound,
    ) -> None:
        round_index = len(ordered)
        ordered.append(schedule_round)

        for key in round_pair_set(
            schedule_round
        ):
            last_pair_round[key] = round_index

    def candidate_score(
        schedule_round: ScheduleRound,
        *,
        target_gap: int,
    ) -> tuple[float, int, float]:
        current_index = len(ordered)
        recent_gaps = [
            current_index
            - last_pair_round[key]
            for key in round_pair_set(
                schedule_round
            )
            if key in last_pair_round
        ]
        recency_penalty = sum(
            float(
                (target_gap - gap) ** 3
            )
            for gap in recent_gaps
            if gap < target_gap
        )
        immediate_overlap = sum(
            gap == 1
            for gap in recent_gaps
        )

        return (
            recency_penalty,
            immediate_overlap,
            randomizer.random(),
        )

    for first_round in first_cycle:
        append_round(first_round)

        selected_extra_index = min(
            remaining_extra,
            key=lambda index: candidate_score(
                extras[index],
                target_gap=8,
            ),
        )
        remaining_extra.remove(
            selected_extra_index
        )
        append_round(
            extras[selected_extra_index]
        )

        selected_second_index = min(
            remaining_second_cycle,
            key=lambda index: candidate_score(
                second_cycle[index],
                target_gap=12,
            ),
        )
        remaining_second_cycle.remove(
            selected_second_index
        )
        append_round(
            second_cycle[
                selected_second_index
            ]
        )

    if (
        remaining_extra
        or remaining_second_cycle
        or len(ordered) != SCHEDULE_ROUND_COUNT
    ):
        raise RegularSeasonScheduleError(
            "Schedule-round ordering did not reconcile."
        )

    return tuple(ordered)


def season_token(
    season_label: str,
) -> str:
    token = "".join(
        character
        for character in season_label
        if character.isdigit()
    )
    return token or "SEASON"


def schedule_signature(
    games: Iterable[ScheduledGame],
) -> str:
    payload = [
        (
            game.game_id,
            int(game.day_index),
            game.home_team,
            game.away_team,
            game.status.value,
        )
        for game in games
    ]
    encoded = json.dumps(
        payload,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def assign_rounds_to_calendar(
    rounds: Sequence[ScheduleRound],
    *,
    season_label: str,
    seed: int,
) -> tuple[
    tuple[ScheduledGame, ...],
    tuple[int, ...],
]:
    randomizer = random.Random(
        int(seed) + 7717
    )
    last_game_day = {
        team: -1000
        for team in ALL_TEAMS
    }
    provisional: list[
        tuple[int, int, int, str, str]
    ] = []
    day_index = 1
    odd_round_split_counter = 0
    global_off_days: list[int] = []

    for round_number, schedule_round in enumerate(
        rounds,
        start=1,
    ):
        if (
            round_number
            in GLOBAL_OFF_BEFORE_ROUNDS
        ):
            global_off_days.append(day_index)
            day_index += 1

        game_count = len(schedule_round.games)
        early_count = game_count // 2

        if game_count % 2:
            early_count += (
                odd_round_split_counter % 2
            )
            odd_round_split_counter += 1

        candidate_order: list[
            tuple[int, float, int]
        ] = []

        for slot_index, (
            home_team,
            away_team,
        ) in enumerate(schedule_round.games):
            back_to_back_penalty = sum(
                last_game_day[team]
                == day_index - 1
                for team in (
                    home_team,
                    away_team,
                )
            )
            candidate_order.append(
                (
                    back_to_back_penalty,
                    randomizer.random(),
                    slot_index,
                )
            )

        early_slots = {
            slot_index
            for _, _, slot_index in sorted(
                candidate_order
            )[:early_count]
        }

        for slot_index, (
            home_team,
            away_team,
        ) in enumerate(schedule_round.games):
            game_day = (
                day_index
                if slot_index in early_slots
                else day_index + 1
            )
            last_game_day[home_team] = game_day
            last_game_day[away_team] = game_day
            provisional.append(
                (
                    game_day,
                    round_number,
                    slot_index,
                    home_team,
                    away_team,
                )
            )

        day_index += 2

    if day_index - 1 != CALENDAR_DAY_COUNT:
        raise RegularSeasonScheduleError(
            "Calendar construction expected "
            f"{CALENDAR_DAY_COUNT} days, produced "
            f"{day_index - 1}."
        )

    ordered_games = sorted(
        provisional,
        key=lambda row: (
            row[0],
            row[1],
            row[2],
            row[3],
            row[4],
        ),
    )
    token = season_token(season_label)
    games = tuple(
        ScheduledGame(
            game_id=(
                f"REG-{token}-{game_number:04d}"
            ),
            day_index=game_day,
            home_team=home_team,
            away_team=away_team,
            status=GameStatus.SCHEDULED,
        )
        for game_number, (
            game_day,
            _,
            _,
            home_team,
            away_team,
        ) in enumerate(
            ordered_games,
            start=1,
        )
    )

    return games, tuple(global_off_days)


def generate_regular_season_schedule(
    state: SimulationLeagueState,
    *,
    seed: int | None = None,
) -> GeneratedRegularSeasonSchedule:
    validate_simulation_league_state(state)

    state_teams = set(state.teams)
    expected_teams = set(ALL_TEAMS)

    if state_teams != expected_teams:
        missing = sorted(
            expected_teams.difference(
                state_teams
            )
        )
        unexpected = sorted(
            state_teams.difference(
                expected_teams
            )
        )
        raise RegularSeasonScheduleError(
            "Schedule topology does not match the "
            "simulation league. Missing: "
            f"{missing}; unexpected: {unexpected}."
        )

    if state.settings.regular_season_games_per_team != 82:
        raise RegularSeasonScheduleError(
            "Schedule engine v1 requires an "
            "82-game regular season."
        )

    resolved_seed = int(
        state.settings.random_seed
        if seed is None
        else seed
    )
    last_error: Exception | None = None

    for generation_attempt in range(256):
        construction_seed = (
            resolved_seed * 1000
            + generation_attempt
        )
        rounds = order_schedule_rounds(
            seed=construction_seed
        )
        games, global_off_days = (
            assign_rounds_to_calendar(
                rounds,
                season_label=(
                    state.settings.season_label
                ),
                seed=construction_seed,
            )
        )

        generated = GeneratedRegularSeasonSchedule(
            engine_version=(
                SCHEDULE_ENGINE_VERSION
            ),
            season_label=(
                state.settings.season_label
            ),
            seed=resolved_seed,
            construction_seed=(
                construction_seed
            ),
            generation_attempt=(
                generation_attempt
            ),
            games=games,
            round_count=len(rounds),
            calendar_days=CALENDAR_DAY_COUNT,
            global_off_days=global_off_days,
            signature=schedule_signature(games),
        )

        try:
            validate_generated_schedule(
                generated
            )
        except RegularSeasonScheduleError as exc:
            last_error = exc
            continue

        return generated

    raise RegularSeasonScheduleError(
        "No schedule satisfying all calendar "
        "constraints was found in 256 deterministic "
        f"attempts. Last error: {last_error}"
    )


def team_game_rows(
    schedule: GeneratedRegularSeasonSchedule,
) -> dict[
    str,
    list[tuple[int, str, str]],
]:
    rows: dict[
        str,
        list[tuple[int, str, str]],
    ] = {
        team: []
        for team in ALL_TEAMS
    }

    for game in schedule.games:
        rows[game.home_team].append(
            (
                game.day_index,
                "H",
                game.away_team,
            )
        )
        rows[game.away_team].append(
            (
                game.day_index,
                "A",
                game.home_team,
            )
        )

    for team in rows:
        rows[team].sort()

    return rows


def maximum_games_in_window(
    game_days: Sequence[int],
    window_days: int,
) -> int:
    ordered = sorted(game_days)
    maximum = 0
    right_index = 0

    for left_index, first_day in enumerate(
        ordered
    ):
        right_index = max(
            right_index,
            left_index,
        )

        while (
            right_index < len(ordered)
            and ordered[right_index]
            <= first_day + window_days - 1
        ):
            right_index += 1

        maximum = max(
            maximum,
            right_index - left_index,
        )

    return maximum


def maximum_location_streak(
    rows: Sequence[tuple[int, str, str]],
) -> int:
    maximum = 0
    current = 0
    previous_location = ""

    for _, location, _ in rows:
        if location == previous_location:
            current += 1
        else:
            previous_location = location
            current = 1

        maximum = max(maximum, current)

    return maximum


def schedule_relationship_signature(
    schedule: GeneratedRegularSeasonSchedule,
) -> tuple[
    tuple[tuple[str, str], int, int, int],
    ...,
]:
    pair_totals: Counter[
        tuple[str, str]
    ] = Counter()
    pair_home_first: Counter[
        tuple[str, str]
    ] = Counter()

    for game in schedule.games:
        key = pair_key(
            game.home_team,
            game.away_team,
        )
        pair_totals[key] += 1

        if game.home_team == key[0]:
            pair_home_first[key] += 1

    return tuple(
        (
            key,
            pair_totals[key],
            pair_home_first[key],
            pair_totals[key]
            - pair_home_first[key],
        )
        for key in sorted(pair_totals)
    )


def validate_generated_schedule(
    schedule: GeneratedRegularSeasonSchedule,
) -> dict[str, Any]:
    conference_by_team, division_by_team = (
        topology_maps()
    )
    expected_pair_counts, _ = (
        matchup_blueprint()
    )
    team_rows = team_game_rows(schedule)
    game_ids = [
        game.game_id
        for game in schedule.games
    ]
    day_teams: dict[int, list[str]] = (
        defaultdict(list)
    )
    day_game_counts: Counter[int] = Counter()
    actual_pair_counts: Counter[
        tuple[str, str]
    ] = Counter()
    pair_game_days: dict[
        tuple[str, str],
        list[int],
    ] = defaultdict(list)

    for game in schedule.games:
        day_teams[game.day_index].extend(
            [
                game.home_team,
                game.away_team,
            ]
        )
        day_game_counts[game.day_index] += 1
        key = pair_key(
            game.home_team,
            game.away_team,
        )
        actual_pair_counts[key] += 1
        pair_game_days[key].append(
            game.day_index
        )

    team_game_counts = {
        team: len(rows)
        for team, rows in team_rows.items()
    }
    team_home_counts = {
        team: sum(
            location == "H"
            for _, location, _ in rows
        )
        for team, rows in team_rows.items()
    }
    team_away_counts = {
        team: sum(
            location == "A"
            for _, location, _ in rows
        )
        for team, rows in team_rows.items()
    }
    back_to_back_counts = {
        team: sum(
            second_day - first_day == 1
            for first_day, second_day in zip(
                [
                    day
                    for day, _, _ in rows
                ],
                [
                    day
                    for day, _, _
                    in rows[1:]
                ],
                strict=False,
            )
        )
        for team, rows in team_rows.items()
    }

    three_game_opponents: dict[str, int] = {}
    four_game_nondivision_opponents: dict[
        str,
        int,
    ] = {}
    division_frequency_valid = True
    cross_conference_frequency_valid = True

    for team in ALL_TEAMS:
        three_count = 0
        four_nondivision_count = 0

        for opponent in ALL_TEAMS:
            if team == opponent:
                continue

            games = actual_pair_counts[
                pair_key(team, opponent)
            ]

            if (
                division_by_team[team]
                == division_by_team[opponent]
            ):
                division_frequency_valid &= (
                    games == 4
                )
            elif (
                conference_by_team[team]
                == conference_by_team[opponent]
            ):
                if games == 3:
                    three_count += 1
                elif games == 4:
                    four_nondivision_count += 1
            else:
                cross_conference_frequency_valid &= (
                    games == 2
                )

        three_game_opponents[team] = three_count
        four_game_nondivision_opponents[
            team
        ] = four_nondivision_count

    minimum_rematch_gap = min(
        (
            second_day - first_day
            for days in pair_game_days.values()
            for first_day, second_day in zip(
                sorted(days),
                sorted(days)[1:],
                strict=False,
            )
        ),
        default=CALENDAR_DAY_COUNT,
    )
    max_home_away_streak = max(
        maximum_location_streak(rows)
        for rows in team_rows.values()
    )
    max_games_in_three_days = max(
        maximum_games_in_window(
            [
                day
                for day, _, _ in rows
            ],
            3,
        )
        for rows in team_rows.values()
    )
    max_games_in_four_days = max(
        maximum_games_in_window(
            [
                day
                for day, _, _ in rows
            ],
            4,
        )
        for rows in team_rows.values()
    )
    max_games_in_six_days = max(
        maximum_games_in_window(
            [
                day
                for day, _, _ in rows
            ],
            6,
        )
        for rows in team_rows.values()
    )
    active_days = sorted(day_game_counts)
    expected_active_days = (
        schedule.calendar_days
        - len(schedule.global_off_days)
    )

    checks = {
        "engine_version_is_current": (
            schedule.engine_version
            == SCHEDULE_ENGINE_VERSION
        ),
        "exactly_1230_games": (
            len(schedule.games)
            == LEAGUE_GAME_COUNT
        ),
        "exactly_87_schedule_rounds": (
            schedule.round_count
            == SCHEDULE_ROUND_COUNT
        ),
        "calendar_spans_177_days": (
            schedule.calendar_days
            == CALENDAR_DAY_COUNT
            and max(active_days, default=0)
            <= CALENDAR_DAY_COUNT
        ),
        "exactly_three_global_off_days": (
            len(schedule.global_off_days)
            == GLOBAL_OFF_DAY_COUNT
        ),
        "all_game_ids_are_unique": (
            len(game_ids)
            == len(set(game_ids))
        ),
        "all_games_begin_scheduled": all(
            game.status == GameStatus.SCHEDULED
            for game in schedule.games
        ),
        "all_games_use_valid_distinct_teams": all(
            game.home_team in ALL_TEAMS
            and game.away_team in ALL_TEAMS
            and game.home_team != game.away_team
            for game in schedule.games
        ),
        "every_team_plays_82_games": all(
            count
            == REGULAR_SEASON_GAMES_PER_TEAM
            for count in team_game_counts.values()
        ),
        "every_team_has_41_home_games": all(
            count == HOME_GAMES_PER_TEAM
            for count in team_home_counts.values()
        ),
        "every_team_has_41_away_games": all(
            count == AWAY_GAMES_PER_TEAM
            for count in team_away_counts.values()
        ),
        "matchup_blueprint_matches_exactly": (
            dict(actual_pair_counts)
            == expected_pair_counts
        ),
        "division_opponents_play_four_times": (
            division_frequency_valid
        ),
        "each_team_has_four_three_game_opponents": all(
            count == 4
            for count
            in three_game_opponents.values()
        ),
        "each_team_has_six_four_game_nondivision_opponents": all(
            count == 6
            for count
            in four_game_nondivision_opponents.values()
        ),
        "cross_conference_opponents_play_twice": (
            cross_conference_frequency_valid
        ),
        "no_team_plays_twice_on_one_day": all(
            len(participants)
            == len(set(participants))
            for participants in day_teams.values()
        ),
        "active_day_count_reconciles": (
            len(active_days)
            == expected_active_days
        ),
        "active_days_have_five_to_eight_games": all(
            5 <= count <= 8
            for count in day_game_counts.values()
        ),
        "no_three_games_in_three_days": (
            max_games_in_three_days <= 2
        ),
        "no_more_than_three_games_in_four_days": (
            max_games_in_four_days <= 3
        ),
        "no_more_than_four_games_in_six_days": (
            max_games_in_six_days <= 4
        ),
        "back_to_back_counts_are_plausible": all(
            5 <= count <= 15
            for count
            in back_to_back_counts.values()
        ),
        "home_away_streaks_are_bounded": (
            max_home_away_streak <= 7
        ),
        "repeat_opponents_are_spaced": (
            minimum_rematch_gap >= 3
        ),
        "stored_signature_matches_schedule": (
            schedule.signature
            == schedule_signature(
                schedule.games
            )
        ),
    }
    failed = [
        name
        for name, passed in checks.items()
        if not passed
    ]
    metrics = {
        "game_count": len(schedule.games),
        "round_count": schedule.round_count,
        "calendar_days": schedule.calendar_days,
        "active_days": len(active_days),
        "global_off_days": list(
            schedule.global_off_days
        ),
        "minimum_games_on_active_day": min(
            day_game_counts.values(),
            default=0,
        ),
        "maximum_games_on_active_day": max(
            day_game_counts.values(),
            default=0,
        ),
        "minimum_rematch_gap_days": (
            minimum_rematch_gap
        ),
        "maximum_home_away_streak": (
            max_home_away_streak
        ),
        "maximum_games_in_three_days": (
            max_games_in_three_days
        ),
        "maximum_games_in_four_days": (
            max_games_in_four_days
        ),
        "maximum_games_in_six_days": (
            max_games_in_six_days
        ),
        "back_to_back_minimum": min(
            back_to_back_counts.values()
        ),
        "back_to_back_maximum": max(
            back_to_back_counts.values()
        ),
        "back_to_back_average": round(
            statistics.mean(
                back_to_back_counts.values()
            ),
            3,
        ),
        "team_game_counts": team_game_counts,
        "team_home_counts": team_home_counts,
        "team_away_counts": team_away_counts,
        "back_to_back_counts": (
            back_to_back_counts
        ),
        "three_game_opponents": (
            three_game_opponents
        ),
        "four_game_nondivision_opponents": (
            four_game_nondivision_opponents
        ),
    }

    if failed:
        raise RegularSeasonScheduleError(
            "Regular-season schedule validation "
            "failed: "
            + ", ".join(failed)
        )

    return {
        "checks": checks,
        "failed_checks": failed,
        "metrics": metrics,
        "passed": not failed,
    }


def install_regular_season_schedule(
    state: SimulationLeagueState,
    schedule: GeneratedRegularSeasonSchedule,
) -> None:
    validate_simulation_league_state(state)
    validate_generated_schedule(schedule)

    if state.schedule:
        raise RegularSeasonScheduleError(
            "A regular-season schedule can only be "
            "installed into an empty schedule."
        )

    if state.completed_games:
        raise RegularSeasonScheduleError(
            "A schedule cannot be installed after "
            "games have been completed."
        )

    if state.phase != LeaguePhase.PRESEASON:
        raise RegularSeasonScheduleError(
            "A regular-season schedule can only be "
            "installed during preseason."
        )

    if (
        schedule.season_label
        != state.settings.season_label
    ):
        raise RegularSeasonScheduleError(
            "Schedule season does not match the "
            "simulation-state season."
        )

    add_scheduled_games(
        state,
        schedule.games,
    )
    validate_simulation_league_state(state)

    if (
        len(state.schedule)
        != LEAGUE_GAME_COUNT
        or state.phase
        != LeaguePhase.REGULAR_SEASON
    ):
        raise RegularSeasonScheduleError(
            "Installed schedule did not activate the "
            "regular season correctly."
        )


def write_schedule_csv(
    schedule: GeneratedRegularSeasonSchedule,
    path: Path,
) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with path.open(
        "w",
        newline="",
        encoding="utf-8",
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "game_id",
                "day_index",
                "home_team",
                "away_team",
                "status",
            ],
        )
        writer.writeheader()

        for game in schedule.games:
            writer.writerow(
                {
                    "game_id": game.game_id,
                    "day_index": game.day_index,
                    "home_team": game.home_team,
                    "away_team": game.away_team,
                    "status": game.status.value,
                }
            )


def run_self_test(
    *,
    seed: int = 20260808,
) -> dict[str, Any]:
    base_runtime = load_runtime_data()
    league_state = create_league_state(
        base_runtime
    )
    runtime = build_state_runtime(
        base_runtime,
        league_state,
    )
    state = create_simulation_league_state(
        runtime,
        league_state,
    )
    original_state = copy.deepcopy(state)

    schedule = generate_regular_season_schedule(
        state,
        seed=seed,
    )
    repeated = generate_regular_season_schedule(
        state,
        seed=seed,
    )
    alternate = generate_regular_season_schedule(
        state,
        seed=seed + 1,
    )
    validation = validate_generated_schedule(
        schedule
    )

    install_state = copy.deepcopy(state)
    install_regular_season_schedule(
        install_state,
        schedule,
    )

    duplicate_install_blocked = False
    try:
        install_regular_season_schedule(
            install_state,
            schedule,
        )
    except RegularSeasonScheduleError:
        duplicate_install_blocked = True

    checks = {
        "schedule_validation_passes": (
            validation["passed"]
        ),
        "same_seed_is_deterministic": (
            schedule.signature
            == repeated.signature
        ),
        "different_seed_changes_calendar": (
            schedule.signature
            != alternate.signature
        ),
        "different_seed_preserves_matchups": (
            schedule_relationship_signature(
                schedule
            )
            == schedule_relationship_signature(
                alternate
            )
        ),
        "generation_does_not_mutate_state": (
            state == original_state
        ),
        "installation_adds_all_games": (
            len(install_state.schedule)
            == LEAGUE_GAME_COUNT
        ),
        "installation_enters_regular_season": (
            install_state.phase
            == LeaguePhase.REGULAR_SEASON
        ),
        "installation_preserves_day_zero": (
            install_state.current_day_index
            == 0
        ),
        "installed_state_remains_valid": bool(
            validate_simulation_league_state(
                install_state
            )
        ),
        "duplicate_install_is_blocked": (
            duplicate_install_blocked
        ),
    }
    failed = [
        name
        for name, passed in checks.items()
        if not passed
    ]
    report = {
        "script": SCHEDULE_ENGINE_VERSION,
        "checks": checks,
        "failed_checks": failed,
        "schedule": {
            "season_label": (
                schedule.season_label
            ),
            "seed": schedule.seed,
            "construction_seed": (
                schedule.construction_seed
            ),
            "generation_attempt": (
                schedule.generation_attempt
            ),
            "signature": (
                schedule.signature
            ),
            **validation["metrics"],
        },
        "passed": not failed,
    }

    OUTPUTS.mkdir(
        parents=True,
        exist_ok=True,
    )
    SELF_TEST_REPORT.write_text(
        json.dumps(
            report,
            indent=2,
        ),
        encoding="utf-8",
    )
    write_schedule_csv(
        schedule,
        SELF_TEST_SCHEDULE_CSV,
    )

    if failed:
        raise AssertionError(
            "Regular-season schedule self-test "
            "failed: "
            + ", ".join(failed)
        )

    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--self-test",
        action="store_true",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=20260808,
    )
    args = parser.parse_args()

    if args.self_test:
        report = run_self_test(
            seed=args.seed
        )
        print(
            json.dumps(
                report,
                indent=2,
            )
        )
        print(
            "\nREGULAR SEASON SCHEDULE V1 "
            "SELF-TEST PASSED"
        )
        return 0

    print(
        json.dumps(
            {
                "script": (
                    SCHEDULE_ENGINE_VERSION
                ),
                "message": (
                    "Use --self-test to generate and "
                    "validate a complete 82-game schedule."
                ),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
