from __future__ import annotations

import argparse
import calendar
import copy
import html
import json
import sys
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Iterable, Sequence


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
OUTPUTS = ROOT / "outputs"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from regular_season_schedule_v1 import (  # noqa: E402
    ALL_TEAMS,
    LEAGUE_GAME_COUNT,
)
from regular_season_simulation_controller_v1 import (  # noqa: E402
    SimulationScope,
    build_installed_state,
    build_regular_season_simulation_plan,
    regular_season_state_fingerprint,
    simulate_regular_season_scope,
)
from simulation_league_state_v1 import (  # noqa: E402
    GameStatus,
    SimulationLeagueState,
    validate_simulation_league_state,
)


CALENDAR_VERSION = (
    "franchise-calendar-v1-2026-08-08"
)
SELF_TEST_REPORT = (
    OUTPUTS
    / "franchise_calendar_v1_self_test.json"
)


class FranchiseCalendarError(RuntimeError):
    """Raised when calendar or controlled-team state is invalid."""


@dataclass(frozen=True)
class TeamCalendarGame:
    game_id: str
    day_index: int
    calendar_date: date
    team: str
    opponent: str
    location: str
    status: str
    result: str
    team_score: int | None
    opponent_score: int | None
    overtime_periods: int
    is_controlled_team: bool
    is_current_day: bool
    is_past_day: bool


@dataclass(frozen=True)
class MonthCalendarCell:
    calendar_date: date
    in_month: bool
    day_index: int | None
    game: TeamCalendarGame | None
    is_current_day: bool
    is_past_day: bool


@dataclass(frozen=True)
class TeamMonthCalendar:
    version: str
    season_label: str
    team: str
    year: int
    month: int
    month_label: str
    weekday_labels: tuple[str, ...]
    weeks: tuple[
        tuple[MonthCalendarCell, ...],
        ...,
    ]
    scheduled_games: int
    completed_games: int
    upcoming_games: int
    home_games: int
    away_games: int


@dataclass(frozen=True)
class ControlledTeamPause:
    version: str
    controlled_teams: tuple[str, ...]
    requested_scope: SimulationScope
    requested_target_day: int
    next_unplayed_day: int
    pause_day: int | None
    pause_game_ids: tuple[str, ...]
    auto_game_ids: tuple[str, ...]
    auto_target_day: int | None
    can_auto_advance: bool
    requires_user_action: bool
    reason: str


def season_start_year(
    season_label: str,
) -> int:
    try:
        first = str(season_label).split(
            "-",
            maxsplit=1,
        )[0]
        year = int(first)
    except (TypeError, ValueError, IndexError) as exc:
        raise FranchiseCalendarError(
            "Season labels must begin with a "
            "four-digit year."
        ) from exc

    if year < 2000 or year > 2200:
        raise FranchiseCalendarError(
            f"Unsupported season start year: {year}."
        )

    return year


def season_start_date(
    season_label: str,
) -> date:
    """Return the generated schedule's display-date anchor.

    The generated schedule is a realistic placeholder rather than an
    official NBA release. Day 1 is anchored to October 20 of the season's
    starting year so the 177-day calendar runs through mid-April.
    """
    return date(
        season_start_year(season_label),
        10,
        20,
    )


def date_for_day_index(
    season_label: str,
    day_index: int,
) -> date:
    resolved_day = int(day_index)

    if resolved_day < 1:
        raise FranchiseCalendarError(
            "Regular-season day indices begin at 1."
        )

    return season_start_date(
        season_label
    ) + timedelta(
        days=resolved_day - 1
    )


def day_index_for_date(
    season_label: str,
    calendar_date: date,
) -> int:
    return (
        calendar_date
        - season_start_date(season_label)
    ).days + 1


def normalize_controlled_teams(
    teams: Iterable[str],
    *,
    available_teams: Iterable[str] = ALL_TEAMS,
) -> tuple[str, ...]:
    available = {
        str(team).strip().upper()
        for team in available_teams
    }
    resolved = tuple(
        sorted(
            {
                str(team).strip().upper()
                for team in teams
                if str(team).strip()
            }
        )
    )
    invalid = [
        team
        for team in resolved
        if team not in available
    ]

    if invalid:
        raise FranchiseCalendarError(
            "Unknown controlled team(s): "
            + ", ".join(invalid)
        )

    return resolved


def team_schedule_games(
    state: SimulationLeagueState,
    team: str,
) -> tuple[Any, ...]:
    resolved_team = str(team).strip().upper()

    if resolved_team not in state.teams:
        raise FranchiseCalendarError(
            f"Unknown simulation team: {resolved_team}."
        )

    return tuple(
        sorted(
            (
                game
                for game in state.schedule.values()
                if resolved_team
                in (
                    game.home_team,
                    game.away_team,
                )
            ),
            key=lambda game: (
                int(game.day_index),
                game.game_id,
            ),
        )
    )


def team_game_card(
    state: SimulationLeagueState,
    team: str,
    game: Any,
    *,
    controlled_teams: Sequence[str] = (),
) -> TeamCalendarGame:
    resolved_team = str(team).strip().upper()
    is_home = (
        game.home_team == resolved_team
    )
    opponent = (
        game.away_team
        if is_home
        else game.home_team
    )
    completed = state.completed_games.get(
        game.game_id
    )
    team_score: int | None = None
    opponent_score: int | None = None
    result = ""

    if completed is not None:
        team_score = (
            completed.home_score
            if is_home
            else completed.away_score
        )
        opponent_score = (
            completed.away_score
            if is_home
            else completed.home_score
        )
        result = (
            "W"
            if team_score > opponent_score
            else "L"
        )

    current_day = int(
        state.current_day_index
    )
    game_day = int(game.day_index)

    return TeamCalendarGame(
        game_id=game.game_id,
        day_index=game_day,
        calendar_date=date_for_day_index(
            state.settings.season_label,
            game_day,
        ),
        team=resolved_team,
        opponent=opponent,
        location=(
            "HOME"
            if is_home
            else "AWAY"
        ),
        status=game.status.value,
        result=result,
        team_score=team_score,
        opponent_score=opponent_score,
        overtime_periods=(
            completed.overtime_periods
            if completed is not None
            else 0
        ),
        is_controlled_team=(
            resolved_team
            in set(
                normalize_controlled_teams(
                    controlled_teams,
                    available_teams=state.teams,
                )
            )
        ),
        is_current_day=(
            current_day > 0
            and game_day == current_day
        ),
        is_past_day=(
            game_day < current_day
        ),
    )


def available_calendar_months(
    state: SimulationLeagueState,
) -> tuple[tuple[int, int], ...]:
    if not state.schedule:
        start = season_start_date(
            state.settings.season_label
        )
        return ((start.year, start.month),)

    dates = sorted(
        {
            date_for_day_index(
                state.settings.season_label,
                game.day_index,
            )
            for game in state.schedule.values()
        }
    )
    return tuple(
        dict.fromkeys(
            (
                value.year,
                value.month,
            )
            for value in dates
        )
    )


def default_calendar_month(
    state: SimulationLeagueState,
    team: str,
) -> tuple[int, int]:
    games = team_schedule_games(
        state,
        team,
    )

    if not games:
        start = season_start_date(
            state.settings.season_label
        )
        return start.year, start.month

    unplayed = [
        game
        for game in games
        if game.status == GameStatus.SCHEDULED
    ]
    target = (
        unplayed[0]
        if unplayed
        else games[-1]
    )
    target_date = date_for_day_index(
        state.settings.season_label,
        target.day_index,
    )
    return (
        target_date.year,
        target_date.month,
    )


def build_team_month_calendar(
    state: SimulationLeagueState,
    team: str,
    *,
    year: int,
    month: int,
    controlled_teams: Sequence[str] = (),
) -> TeamMonthCalendar:
    validate_simulation_league_state(
        state
    )
    resolved_team = str(team).strip().upper()
    month_games: dict[
        date,
        TeamCalendarGame,
    ] = {}

    for scheduled in team_schedule_games(
        state,
        resolved_team,
    ):
        card = team_game_card(
            state,
            resolved_team,
            scheduled,
            controlled_teams=(
                controlled_teams
            ),
        )

        if (
            card.calendar_date.year == int(year)
            and card.calendar_date.month
            == int(month)
        ):
            month_games[
                card.calendar_date
            ] = card

    month_grid = calendar.Calendar(
        firstweekday=calendar.MONDAY
    ).monthdatescalendar(
        int(year),
        int(month),
    )
    current_day = int(
        state.current_day_index
    )
    weeks: list[
        tuple[MonthCalendarCell, ...]
    ] = []

    for week in month_grid:
        cells: list[MonthCalendarCell] = []

        for calendar_date in week:
            in_month = (
                calendar_date.month
                == int(month)
            )
            day_index = day_index_for_date(
                state.settings.season_label,
                calendar_date,
            )
            in_season_window = (
                1 <= day_index <= 177
            )
            card = month_games.get(
                calendar_date
            )
            cells.append(
                MonthCalendarCell(
                    calendar_date=(
                        calendar_date
                    ),
                    in_month=in_month,
                    day_index=(
                        day_index
                        if in_season_window
                        else None
                    ),
                    game=card,
                    is_current_day=(
                        current_day > 0
                        and day_index
                        == current_day
                    ),
                    is_past_day=(
                        current_day > 0
                        and day_index
                        < current_day
                    ),
                )
            )

        weeks.append(tuple(cells))

    cards = list(
        month_games.values()
    )
    completed = sum(
        card.status
        == GameStatus.COMPLETED.value
        for card in cards
    )
    home = sum(
        card.location == "HOME"
        for card in cards
    )

    return TeamMonthCalendar(
        version=CALENDAR_VERSION,
        season_label=(
            state.settings.season_label
        ),
        team=resolved_team,
        year=int(year),
        month=int(month),
        month_label=date(
            int(year),
            int(month),
            1,
        ).strftime("%B %Y"),
        weekday_labels=(
            "MON",
            "TUE",
            "WED",
            "THU",
            "FRI",
            "SAT",
            "SUN",
        ),
        weeks=tuple(weeks),
        scheduled_games=len(cards),
        completed_games=completed,
        upcoming_games=(
            len(cards) - completed
        ),
        home_games=home,
        away_games=(
            len(cards) - home
        ),
    )


def calendar_html(
    month_calendar: TeamMonthCalendar,
) -> str:
    def esc(value: Any) -> str:
        return html.escape(
            str(value)
        )

    weekday_html = "".join(
        (
            '<div class="fc-weekday">'
            f"{esc(label)}"
            "</div>"
        )
        for label in (
            month_calendar.weekday_labels
        )
    )
    cells: list[str] = []

    for week in month_calendar.weeks:
        for cell in week:
            classes = ["fc-day"]

            if not cell.in_month:
                classes.append("outside")

            if cell.is_current_day:
                classes.append("current")

            if cell.is_past_day:
                classes.append("past")

            body = (
                '<div class="fc-rest">'
                "OUTSIDE MONTH"
                "</div>"
                if not cell.in_month
                else '<div class="fc-rest">REST</div>'
            )

            if (
                cell.in_month
                and cell.game is not None
            ):
                game = cell.game
                classes.append(
                    "home"
                    if game.location == "HOME"
                    else "away"
                )
                location = (
                    "vs"
                    if game.location == "HOME"
                    else "@"
                )

                if game.result:
                    score = (
                        f"{game.result} "
                        f"{game.team_score}-"
                        f"{game.opponent_score}"
                    )
                    status_html = (
                        '<div class="fc-result">'
                        f"{esc(score)}"
                        "</div>"
                    )
                else:
                    status_html = (
                        '<div class="fc-upcoming">'
                        "UPCOMING"
                        "</div>"
                    )

                body = (
                    '<div class="fc-game">'
                    '<div class="fc-opponent">'
                    f"{location} "
                    f"{esc(game.opponent)}"
                    "</div>"
                    f"{status_html}"
                    "</div>"
                )

            cells.append(
                (
                    f'<div class="{" ".join(classes)}">'
                    '<div class="fc-date">'
                    f"{cell.calendar_date.day}"
                    "</div>"
                    f"{body}"
                    "</div>"
                )
            )

    return (
        '<div class="fc-calendar">'
        f"{weekday_html}"
        f"{''.join(cells)}"
        "</div>"
    )


def controlled_games_on_day(
    state: SimulationLeagueState,
    *,
    controlled_teams: Sequence[str],
    day_index: int,
) -> tuple[Any, ...]:
    controlled = set(
        normalize_controlled_teams(
            controlled_teams,
            available_teams=state.teams,
        )
    )

    if not controlled:
        return ()

    return tuple(
        sorted(
            (
                game
                for game in state.schedule.values()
                if int(game.day_index)
                == int(day_index)
                and game.status
                == GameStatus.SCHEDULED
                and bool(
                    controlled.intersection(
                        {
                            game.home_team,
                            game.away_team,
                        }
                    )
                )
            ),
            key=lambda game: game.game_id,
        )
    )


def controlled_team_pause(
    state: SimulationLeagueState,
    *,
    controlled_teams: Sequence[str],
    scope: SimulationScope | str,
    target_day: int | None = None,
) -> ControlledTeamPause:
    controlled = normalize_controlled_teams(
        controlled_teams,
        available_teams=state.teams,
    )
    plan = (
        build_regular_season_simulation_plan(
            state,
            scope=scope,
            target_day=target_day,
        )
    )
    planned_games = [
        state.schedule[game_id]
        for game_id in plan.game_ids
    ]

    if not controlled:
        return ControlledTeamPause(
            version=CALENDAR_VERSION,
            controlled_teams=(),
            requested_scope=plan.scope,
            requested_target_day=(
                plan.target_day
            ),
            next_unplayed_day=(
                plan.start_day
            ),
            pause_day=None,
            pause_game_ids=(),
            auto_game_ids=plan.game_ids,
            auto_target_day=(
                plan.target_day
            ),
            can_auto_advance=True,
            requires_user_action=False,
            reason=(
                "No teams are user controlled."
            ),
        )

    controlled_set = set(controlled)
    pause_candidates = [
        game
        for game in planned_games
        if controlled_set.intersection(
            {
                game.home_team,
                game.away_team,
            }
        )
    ]

    if not pause_candidates:
        return ControlledTeamPause(
            version=CALENDAR_VERSION,
            controlled_teams=controlled,
            requested_scope=plan.scope,
            requested_target_day=(
                plan.target_day
            ),
            next_unplayed_day=(
                plan.start_day
            ),
            pause_day=None,
            pause_game_ids=(),
            auto_game_ids=plan.game_ids,
            auto_target_day=(
                plan.target_day
            ),
            can_auto_advance=True,
            requires_user_action=False,
            reason=(
                "The requested range contains no "
                "controlled-team games."
            ),
        )

    pause_day = min(
        int(game.day_index)
        for game in pause_candidates
    )
    pause_games = tuple(
        game.game_id
        for game in planned_games
        if int(game.day_index)
        == pause_day
        and controlled_set.intersection(
            {
                game.home_team,
                game.away_team,
            }
        )
    )
    auto_games = tuple(
        game.game_id
        for game in planned_games
        if int(game.day_index)
        < pause_day
    )
    auto_target_day = (
        max(
            int(
                state.schedule[
                    game_id
                ].day_index
            )
            for game_id in auto_games
        )
        if auto_games
        else None
    )

    return ControlledTeamPause(
        version=CALENDAR_VERSION,
        controlled_teams=controlled,
        requested_scope=plan.scope,
        requested_target_day=(
            plan.target_day
        ),
        next_unplayed_day=plan.start_day,
        pause_day=pause_day,
        pause_game_ids=pause_games,
        auto_game_ids=auto_games,
        auto_target_day=(
            auto_target_day
        ),
        can_auto_advance=bool(
            auto_games
        ),
        requires_user_action=True,
        reason=(
            "Simulation pauses before the first "
            "controlled-team game day."
        ),
    )


def run_self_test(
    *,
    seed: int = 20260808,
) -> dict[str, Any]:
    state = build_installed_state(
        seed=seed
    )
    source_fingerprint = (
        regular_season_state_fingerprint(
            state
        )
    )
    controlled = (
        "CHI",
        "OKC",
    )
    default_year, default_month = (
        default_calendar_month(
            state,
            "CHI",
        )
    )
    month = build_team_month_calendar(
        state,
        "CHI",
        year=default_year,
        month=default_month,
        controlled_teams=controlled,
    )
    html_output = calendar_html(month)
    week_pause = controlled_team_pause(
        state,
        controlled_teams=controlled,
        scope=SimulationScope.NEXT_WEEK,
    )
    no_control_pause = controlled_team_pause(
        state,
        controlled_teams=(),
        scope=SimulationScope.NEXT_DAY,
    )

    first_game = team_schedule_games(
        state,
        "CHI",
    )[0]
    through_first_game_state, _ = (
        simulate_regular_season_scope(
            state,
            scope=SimulationScope.THROUGH_DAY,
            target_day=int(
                first_game.day_index
            ),
        )
    )
    completed_month = (
        build_team_month_calendar(
            through_first_game_state,
            "CHI",
            year=default_year,
            month=default_month,
            controlled_teams=controlled,
        )
    )
    completed_cards = [
        cell.game
        for week in completed_month.weeks
        for cell in week
        if (
            cell.game is not None
            and cell.game.status
            == GameStatus.COMPLETED.value
        )
    ]

    checks = {
        "calendar_version_is_current": (
            month.version
            == CALENDAR_VERSION
        ),
        "controlled_teams_normalize": (
            normalize_controlled_teams(
                ["okc", "CHI", "chi"],
                available_teams=state.teams,
            )
            == controlled
        ),
        "season_anchor_is_october_20": (
            season_start_date(
                state.settings.season_label
            )
            == date(2026, 10, 20)
        ),
        "day_index_round_trip": all(
            day_index_for_date(
                state.settings.season_label,
                date_for_day_index(
                    state.settings.season_label,
                    day_index,
                ),
            )
            == day_index
            for day_index in (
                1,
                42,
                88,
                177,
            )
        ),
        "installed_schedule_has_1230_games": (
            len(state.schedule)
            == LEAGUE_GAME_COUNT
        ),
        "team_calendar_has_82_games": (
            len(
                team_schedule_games(
                    state,
                    "CHI",
                )
            )
            == 82
        ),
        "month_grid_has_complete_weeks": (
            bool(month.weeks)
            and all(
                len(week) == 7
                for week in month.weeks
            )
        ),
        "month_counts_reconcile": (
            month.scheduled_games
            == month.home_games
            + month.away_games
            and month.scheduled_games
            == month.completed_games
            + month.upcoming_games
        ),
        "calendar_html_has_home_away_and_rest_states": (
            "fc-calendar" in html_output
            and "fc-day" in html_output
            and "REST" in html_output
            and (
                " home" in html_output
                or " away" in html_output
            )
        ),
        "controlled_pause_is_nonmutating": (
            regular_season_state_fingerprint(
                state
            )
            == source_fingerprint
        ),
        "controlled_pause_identifies_user_game": (
            week_pause.requires_user_action
            and bool(
                week_pause.pause_game_ids
            )
        ),
        "controlled_pause_only_auto_advances_before_pause_day": all(
            state.schedule[
                game_id
            ].day_index
            < week_pause.pause_day
            for game_id
            in week_pause.auto_game_ids
        ),
        "uncontrolled_scope_can_auto_advance": (
            no_control_pause
            .can_auto_advance
            and not no_control_pause
            .requires_user_action
        ),
        "completed_game_card_has_result_and_score": (
            bool(completed_cards)
            and all(
                card.result in {"W", "L"}
                and card.team_score
                is not None
                and card.opponent_score
                is not None
                for card in completed_cards
            )
        ),
        "simulated_calendar_state_remains_valid": bool(
            validate_simulation_league_state(
                through_first_game_state
            )
        ),
    }
    failed = [
        name
        for name, passed in checks.items()
        if not passed
    ]
    report = {
        "script": CALENDAR_VERSION,
        "checks": checks,
        "failed_checks": failed,
        "summary": {
            "season_label": (
                state.settings.season_label
            ),
            "controlled_teams": list(
                controlled
            ),
            "month": month.month_label,
            "month_games": (
                month.scheduled_games
            ),
            "pause": asdict(
                week_pause
            ),
            "completed_cards": len(
                completed_cards
            ),
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
            default=str,
        ),
        encoding="utf-8",
    )

    if failed:
        raise AssertionError(
            "Franchise calendar self-test failed: "
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
                default=str,
            )
        )
        print(
            "\nFRANCHISE CALENDAR V1 "
            "SELF-TEST PASSED"
        )
        return 0

    print(
        json.dumps(
            {
                "script": (
                    CALENDAR_VERSION
                ),
                "message": (
                    "Use --self-test to validate "
                    "calendar rendering and controlled-"
                    "team pause behavior."
                ),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())