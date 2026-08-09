from __future__ import annotations

import argparse
import copy
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OUTPUTS = ROOT / "outputs"

ALIGNMENT_VERSION = (
    "simulation-league-alignment-v1-2026-08-08"
)
SELF_TEST_REPORT = (
    OUTPUTS
    / "simulation_league_alignment_v1_self_test.json"
)


class SimulationLeagueAlignmentError(
    RuntimeError
):
    """Raised when NBA team alignment metadata is invalid."""


@dataclass(frozen=True)
class TeamAlignment:
    team: str
    conference: str
    division: str


_ALIGNMENT_ROWS = (
    ("ATL", "East", "Southeast"),
    ("BOS", "East", "Atlantic"),
    ("BKN", "East", "Atlantic"),
    ("CHA", "East", "Southeast"),
    ("CHI", "East", "Central"),
    ("CLE", "East", "Central"),
    ("DET", "East", "Central"),
    ("IND", "East", "Central"),
    ("MIA", "East", "Southeast"),
    ("MIL", "East", "Central"),
    ("NYK", "East", "Atlantic"),
    ("ORL", "East", "Southeast"),
    ("PHI", "East", "Atlantic"),
    ("TOR", "East", "Atlantic"),
    ("WAS", "East", "Southeast"),
    ("DAL", "West", "Southwest"),
    ("DEN", "West", "Northwest"),
    ("GSW", "West", "Pacific"),
    ("HOU", "West", "Southwest"),
    ("LAC", "West", "Pacific"),
    ("LAL", "West", "Pacific"),
    ("MEM", "West", "Southwest"),
    ("MIN", "West", "Northwest"),
    ("NOP", "West", "Southwest"),
    ("OKC", "West", "Northwest"),
    ("PHX", "West", "Pacific"),
    ("POR", "West", "Northwest"),
    ("SAC", "West", "Pacific"),
    ("SAS", "West", "Southwest"),
    ("UTA", "West", "Northwest"),
)

NBA_ALIGNMENT: dict[str, TeamAlignment] = {
    team: TeamAlignment(
        team=team,
        conference=conference,
        division=division,
    )
    for team, conference, division
    in _ALIGNMENT_ROWS
}

CONFERENCE_TEAMS = {
    conference: tuple(
        sorted(
            team
            for team, alignment
            in NBA_ALIGNMENT.items()
            if alignment.conference
            == conference
        )
    )
    for conference in ("East", "West")
}

DIVISION_TEAMS = {
    division: tuple(
        sorted(
            team
            for team, alignment
            in NBA_ALIGNMENT.items()
            if alignment.division
            == division
        )
    )
    for division in (
        "Atlantic",
        "Central",
        "Southeast",
        "Northwest",
        "Pacific",
        "Southwest",
    )
}


def normalize_team(
    team: Any,
) -> str:
    return str(team).strip().upper()


def alignment_for_team(
    team: Any,
) -> TeamAlignment:
    resolved = normalize_team(team)

    try:
        return NBA_ALIGNMENT[resolved]
    except KeyError as exc:
        raise SimulationLeagueAlignmentError(
            f"Unknown NBA team: {resolved!r}."
        ) from exc


def conference_for_team(
    team: Any,
) -> str:
    return alignment_for_team(
        team
    ).conference


def division_for_team(
    team: Any,
) -> str:
    return alignment_for_team(
        team
    ).division


def apply_nba_team_alignment(
    state: Any,
    *,
    copy_state: bool = False,
) -> Any:
    """Populate canonical conference/division metadata.

    The operation changes only static team-alignment fields. Schedules,
    results, standings, rosters, rotations, injuries, and statistics are
    untouched.
    """
    target = (
        copy.deepcopy(state)
        if copy_state
        else state
    )
    teams = getattr(
        target,
        "teams",
        None,
    )

    if not isinstance(teams, dict):
        raise SimulationLeagueAlignmentError(
            "Simulation state has no team mapping."
        )

    unknown = sorted(
        set(teams).difference(
            NBA_ALIGNMENT
        )
    )

    if unknown:
        raise SimulationLeagueAlignmentError(
            "Unknown simulation team(s): "
            + ", ".join(unknown)
        )

    for team, team_state in teams.items():
        alignment = NBA_ALIGNMENT[
            team
        ]
        team_state.conference = (
            alignment.conference
        )
        team_state.division = (
            alignment.division
        )

    return target


def alignment_is_complete(
    state: Any,
) -> bool:
    teams = getattr(
        state,
        "teams",
        None,
    )

    if not isinstance(teams, dict):
        return False

    return all(
        team in NBA_ALIGNMENT
        and getattr(
            team_state,
            "conference",
            "",
        )
        == NBA_ALIGNMENT[
            team
        ].conference
        and getattr(
            team_state,
            "division",
            "",
        )
        == NBA_ALIGNMENT[
            team
        ].division
        for team, team_state
        in teams.items()
    )


def run_self_test() -> dict[str, Any]:
    from types import SimpleNamespace

    fake_state = SimpleNamespace(
        teams={
            team: SimpleNamespace(
                conference="",
                division="",
            )
            for team in NBA_ALIGNMENT
        },
        schedule={
            "sentinel": "unchanged"
        },
        completed_games={
            "sentinel": "unchanged"
        },
    )
    source_schedule = copy.deepcopy(
        fake_state.schedule
    )
    source_completed = copy.deepcopy(
        fake_state.completed_games
    )
    apply_nba_team_alignment(
        fake_state
    )

    checks = {
        "alignment_version_is_current": (
            ALIGNMENT_VERSION.endswith(
                "2026-08-08"
            )
        ),
        "all_30_teams_are_mapped": (
            len(NBA_ALIGNMENT) == 30
        ),
        "east_has_15_teams": (
            len(
                CONFERENCE_TEAMS["East"]
            )
            == 15
        ),
        "west_has_15_teams": (
            len(
                CONFERENCE_TEAMS["West"]
            )
            == 15
        ),
        "six_divisions_have_five_teams": (
            len(DIVISION_TEAMS) == 6
            and all(
                len(teams) == 5
                for teams
                in DIVISION_TEAMS.values()
            )
        ),
        "okc_alignment_is_correct": (
            conference_for_team("OKC")
            == "West"
            and division_for_team("OKC")
            == "Northwest"
        ),
        "chicago_alignment_is_correct": (
            conference_for_team("CHI")
            == "East"
            and division_for_team("CHI")
            == "Central"
        ),
        "alignment_populates_state": (
            alignment_is_complete(
                fake_state
            )
        ),
        "alignment_does_not_touch_schedule": (
            fake_state.schedule
            == source_schedule
        ),
        "alignment_does_not_touch_results": (
            fake_state.completed_games
            == source_completed
        ),
    }
    failed = [
        name
        for name, passed
        in checks.items()
        if not passed
    ]
    report = {
        "script": ALIGNMENT_VERSION,
        "checks": checks,
        "failed_checks": failed,
        "summary": {
            "east": list(
                CONFERENCE_TEAMS["East"]
            ),
            "west": list(
                CONFERENCE_TEAMS["West"]
            ),
            "divisions": {
                division: list(teams)
                for division, teams
                in DIVISION_TEAMS.items()
            },
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

    if failed:
        raise AssertionError(
            "NBA alignment self-test failed: "
            + ", ".join(failed)
        )

    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--self-test",
        action="store_true",
    )
    args = parser.parse_args()

    if args.self_test:
        report = run_self_test()
        print(
            json.dumps(
                report,
                indent=2,
            )
        )
        print(
            "\nSIMULATION LEAGUE ALIGNMENT "
            "V1 SELF-TEST PASSED"
        )
        return 0

    print(
        json.dumps(
            {
                "script": ALIGNMENT_VERSION,
                "teams": len(
                    NBA_ALIGNMENT
                ),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
