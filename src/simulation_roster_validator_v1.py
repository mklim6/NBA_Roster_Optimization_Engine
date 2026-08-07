from __future__ import annotations

import argparse
import copy
import csv
import json
import math
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
OUTPUTS = ROOT / "outputs"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from freeform_trade_machine_engine_v3 import (  # noqa: E402
    RuntimeData,
    load_runtime_data,
    normalize_player_id,
    normalize_team,
    to_bool,
    to_float,
)
from mutable_league_state_v1 import (  # noqa: E402
    LeagueState,
    create_league_state,
)
from state_runtime_adapter_v1 import (  # noqa: E402
    build_state_runtime,
)


VALIDATOR_VERSION = (
    "simulation-roster-validator-v1-2026-08-07"
)
READINESS_REPORT = (
    OUTPUTS / "simulation_roster_readiness_v1.json"
)
TEAM_SUMMARY_CSV = (
    OUTPUTS / "simulation_roster_team_summary_v1.csv"
)
SELF_TEST_REPORT = (
    OUTPUTS
    / "simulation_roster_validator_v1_self_test.json"
)

RATING_FIELDS = (
    "overall_rating",
    "current_overall_rating",
    "player_overall_rating",
    "ovr",
    "rating",
)
POSITION_FIELDS = (
    "position",
    "primary_position",
    "position_group",
    "player_position",
    "listed_position",
    "pos",
)
NAME_FIELDS = (
    "player_name",
    "player_display_name",
    "display_name",
    "name",
)
TWO_WAY_FIELDS = (
    "two_way_contract_active",
    "two_way_flag",
    "is_two_way",
    "two_way_contract",
)


class SimulationRosterValidationError(RuntimeError):
    """Raised when a simulation roster cannot be constructed."""


@dataclass(frozen=True)
class RosterValidationConfig:
    minimum_game_players: int = 8
    target_rotation_size: int = 10
    starting_lineup_size: int = 5
    fallback_overall_rating: float = 67.0
    replacement_overall_rating: float = 66.0
    auto_fill_replacements: bool = True
    oversized_roster_warning: int = 18


@dataclass(frozen=True)
class SimulationPlayer:
    player_id: str
    player_name: str
    team_abbreviation: str
    overall_rating: float
    position: str
    synthetic: bool
    rating_source: str
    two_way: bool


@dataclass
class TeamSimulationRoster:
    team_abbreviation: str
    real_players: list[SimulationPlayer]
    simulation_players: list[SimulationPlayer]
    starting_five_ids: tuple[str, ...]
    rotation_player_ids: tuple[str, ...]
    replacement_player_ids: tuple[str, ...]
    warnings: tuple[str, ...]
    ready_for_game: bool

    @property
    def real_player_count(self) -> int:
        return len(self.real_players)

    @property
    def simulation_player_count(self) -> int:
        return len(self.simulation_players)

    @property
    def replacement_count(self) -> int:
        return len(self.replacement_player_ids)


@dataclass
class SimulationRosterSnapshot:
    validator_version: str
    state_revision: int
    config: RosterValidationConfig
    teams: dict[str, TeamSimulationRoster]
    unassigned_player_ids: tuple[str, ...]
    unknown_team_assignments: dict[str, str]
    fallback_rating_player_ids: tuple[str, ...]
    replacement_player_ids: tuple[str, ...]
    checks: dict[str, bool] = field(default_factory=dict)

    @property
    def ready(self) -> bool:
        return all(self.checks.values())


def clean_text(value: Any) -> str:
    if value is None:
        return ""

    try:
        if math.isnan(float(value)):
            return ""
    except (TypeError, ValueError):
        pass

    return re.sub(r"\s+", " ", str(value)).strip()


def validate_config(
    config: RosterValidationConfig,
) -> None:
    if config.starting_lineup_size < 5:
        raise SimulationRosterValidationError(
            "The simulator requires at least five starters."
        )

    if (
        config.minimum_game_players
        < config.starting_lineup_size
    ):
        raise SimulationRosterValidationError(
            "Minimum game players cannot be smaller than "
            "the starting lineup."
        )

    if (
        config.target_rotation_size
        < config.minimum_game_players
    ):
        raise SimulationRosterValidationError(
            "Target rotation size cannot be smaller than "
            "the minimum game roster."
        )

    if config.fallback_overall_rating <= 0:
        raise SimulationRosterValidationError(
            "Fallback rating must be positive."
        )

    if config.replacement_overall_rating <= 0:
        raise SimulationRosterValidationError(
            "Replacement rating must be positive."
        )


def first_present(
    records: Iterable[dict[str, Any]],
    fields: Iterable[str],
) -> Any:
    for record in records:
        for field_name in fields:
            value = record.get(field_name)

            if clean_text(value):
                return value

    return None


def normalize_position(value: Any) -> str:
    text = clean_text(value).upper()

    if not text:
        return "UNK"

    text = (
        text.replace("POINT GUARD", "PG")
        .replace("SHOOTING GUARD", "SG")
        .replace("SMALL FORWARD", "SF")
        .replace("POWER FORWARD", "PF")
        .replace("CENTER", "C")
        .replace("FORWARD", "F")
        .replace("GUARD", "G")
        .replace(" ", "")
    )
    tokens = [
        token
        for token in re.split(r"[/,\-|]+", text)
        if token
    ]
    valid = []

    for token in tokens:
        if token in {"PG", "SG", "SF", "PF", "C"}:
            valid.append(token)
        elif token == "G":
            valid.extend(["PG", "SG"])
        elif token == "F":
            valid.extend(["SF", "PF"])

    if not valid:
        return "UNK"

    return "/".join(dict.fromkeys(valid))


def extract_overall_rating(
    rating_record: dict[str, Any],
    fallback: float,
) -> tuple[float, str]:
    for field_name in RATING_FIELDS:
        value = to_float(
            rating_record.get(field_name)
        )

        if value is not None and math.isfinite(value):
            return round(float(value), 1), field_name

    return round(float(fallback), 1), "fallback"


def player_records(
    runtime: RuntimeData,
    player_id: str,
) -> tuple[dict[str, Any], ...]:
    player_id = normalize_player_id(player_id)

    return (
        runtime.ratings_by_id.get(player_id, {}),
        runtime.trade_by_id.get(player_id, {}),
        runtime.financial_by_id.get(player_id, {}),
        runtime.market_by_id.get(player_id, {}),
        runtime.player_cba_by_id.get(player_id, {}),
    )


def player_name(
    runtime: RuntimeData,
    player_id: str,
) -> str:
    value = first_present(
        player_records(runtime, player_id),
        NAME_FIELDS,
    )
    return clean_text(value) or player_id


def player_position(
    runtime: RuntimeData,
    player_id: str,
) -> str:
    value = first_present(
        player_records(runtime, player_id),
        POSITION_FIELDS,
    )
    return normalize_position(value)


def player_is_two_way(
    runtime: RuntimeData,
    player_id: str,
) -> bool:
    for record in player_records(runtime, player_id):
        for field_name in TWO_WAY_FIELDS:
            value = to_bool(
                record.get(field_name)
            )
            if value is not None:
                return value

    return False


def simulation_player_from_runtime(
    runtime: RuntimeData,
    *,
    player_id: str,
    team: str,
    config: RosterValidationConfig,
) -> SimulationPlayer:
    player_id = normalize_player_id(player_id)
    rating_record = runtime.ratings_by_id.get(
        player_id,
        {},
    )
    rating, source = extract_overall_rating(
        rating_record,
        config.fallback_overall_rating,
    )

    return SimulationPlayer(
        player_id=player_id,
        player_name=player_name(runtime, player_id),
        team_abbreviation=normalize_team(team),
        overall_rating=rating,
        position=player_position(runtime, player_id),
        synthetic=False,
        rating_source=source,
        two_way=player_is_two_way(
            runtime,
            player_id,
        ),
    )


def replacement_player(
    *,
    team: str,
    sequence: int,
    config: RosterValidationConfig,
) -> SimulationPlayer:
    team = normalize_team(team)
    player_id = (
        f"SIM_REPL_{team}_{sequence:02d}"
    )

    return SimulationPlayer(
        player_id=player_id,
        player_name=(
            f"{team} Emergency Replacement {sequence}"
        ),
        team_abbreviation=team,
        overall_rating=round(
            config.replacement_overall_rating,
            1,
        ),
        position="UNK",
        synthetic=True,
        rating_source="replacement",
        two_way=False,
    )


def rating_sort_key(
    player: SimulationPlayer,
) -> tuple[float, str, str]:
    return (
        -player.overall_rating,
        player.player_name.casefold(),
        player.player_id,
    )


def position_tokens(
    player: SimulationPlayer,
) -> set[str]:
    return {
        token
        for token in player.position.split("/")
        if token and token != "UNK"
    }


def choose_best_matching(
    players: list[SimulationPlayer],
    selected: set[str],
    allowed_positions: set[str],
) -> SimulationPlayer | None:
    candidates = [
        player
        for player in players
        if (
            player.player_id not in selected
            and position_tokens(player).intersection(
                allowed_positions
            )
        )
    ]

    return (
        sorted(candidates, key=rating_sort_key)[0]
        if candidates
        else None
    )


def choose_starting_five(
    players: list[SimulationPlayer],
    lineup_size: int,
) -> tuple[str, ...]:
    ordered = sorted(
        players,
        key=rating_sort_key,
    )
    selected: list[SimulationPlayer] = []
    selected_ids: set[str] = set()

    role_preferences = (
        {"PG", "SG"},
        {"SF", "PF"},
        {"C", "PF"},
    )

    for positions in role_preferences:
        player = choose_best_matching(
            ordered,
            selected_ids,
            positions,
        )

        if player is not None:
            selected.append(player)
            selected_ids.add(player.player_id)

    for player in ordered:
        if len(selected) >= lineup_size:
            break

        if player.player_id in selected_ids:
            continue

        selected.append(player)
        selected_ids.add(player.player_id)

    return tuple(
        player.player_id
        for player in selected[:lineup_size]
    )


def choose_rotation(
    players: list[SimulationPlayer],
    starter_ids: tuple[str, ...],
    target_size: int,
) -> tuple[str, ...]:
    by_id = {
        player.player_id: player
        for player in players
    }
    ordered = sorted(
        players,
        key=rating_sort_key,
    )
    rotation: list[str] = [
        player_id
        for player_id in starter_ids
        if player_id in by_id
    ]

    for player in ordered:
        if len(rotation) >= target_size:
            break

        if player.player_id not in rotation:
            rotation.append(player.player_id)

    return tuple(rotation)


def state_signature(
    state: LeagueState,
) -> dict[str, Any]:
    return {
        "revision": state.state_revision,
        "players": tuple(
            sorted(state.player_team_by_id.items())
        ),
        "picks": tuple(
            sorted(state.pick_team_by_id.items())
        ),
        "transactions": len(
            state.transaction_history
        ),
        "undo_depth": len(state.undo_stack),
    }


def runtime_signature(
    runtime: RuntimeData,
) -> dict[str, Any]:
    return {
        "trade_players": tuple(
            sorted(runtime.trade_by_id)
        ),
        "financial_players": tuple(
            sorted(runtime.financial_by_id)
        ),
        "rating_players": tuple(
            sorted(runtime.ratings_by_id)
        ),
        "teams": tuple(
            sorted(runtime.team_cba_by_team)
        ),
    }


def build_simulation_roster_snapshot(
    runtime: RuntimeData,
    state: LeagueState,
    *,
    config: RosterValidationConfig | None = None,
) -> SimulationRosterSnapshot:
    resolved_config = (
        config or RosterValidationConfig()
    )
    validate_config(resolved_config)

    valid_teams = tuple(
        sorted(state.team_financials)
    )
    valid_team_set = set(valid_teams)
    player_ids_by_team = {
        team: []
        for team in valid_teams
    }
    unassigned: list[str] = []
    unknown_assignments: dict[str, str] = {}

    for raw_player_id, raw_team in (
        state.player_team_by_id.items()
    ):
        player_id = normalize_player_id(
            raw_player_id
        )
        team = normalize_team(raw_team)

        if not team:
            unassigned.append(player_id)
        elif team not in valid_team_set:
            unknown_assignments[player_id] = team
        else:
            player_ids_by_team[team].append(
                player_id
            )

    team_rosters: dict[
        str,
        TeamSimulationRoster,
    ] = {}
    fallback_ids: list[str] = []
    all_replacement_ids: list[str] = []

    for team in valid_teams:
        real_players = [
            simulation_player_from_runtime(
                runtime,
                player_id=player_id,
                team=team,
                config=resolved_config,
            )
            for player_id in sorted(
                player_ids_by_team[team]
            )
        ]
        real_players.sort(key=rating_sort_key)

        fallback_ids.extend(
            player.player_id
            for player in real_players
            if player.rating_source == "fallback"
        )

        simulation_players = list(real_players)
        replacement_ids: list[str] = []

        if (
            resolved_config.auto_fill_replacements
            and len(simulation_players)
            < resolved_config.minimum_game_players
        ):
            needed = (
                resolved_config.minimum_game_players
                - len(simulation_players)
            )

            for sequence in range(1, needed + 1):
                player = replacement_player(
                    team=team,
                    sequence=sequence,
                    config=resolved_config,
                )
                simulation_players.append(player)
                replacement_ids.append(
                    player.player_id
                )
                all_replacement_ids.append(
                    player.player_id
                )

        simulation_players.sort(
            key=rating_sort_key
        )
        starter_ids = choose_starting_five(
            simulation_players,
            resolved_config.starting_lineup_size,
        )
        rotation_target = min(
            resolved_config.target_rotation_size,
            len(simulation_players),
        )
        rotation_ids = choose_rotation(
            simulation_players,
            starter_ids,
            rotation_target,
        )

        warnings: list[str] = []

        if replacement_ids:
            warnings.append(
                f"{team} requires {len(replacement_ids)} "
                "simulation-only emergency replacement "
                "player(s)."
            )

        unknown_position_count = sum(
            player.position == "UNK"
            for player in real_players
        )
        if unknown_position_count:
            warnings.append(
                f"{unknown_position_count} real player(s) "
                "have no normalized position."
            )

        fallback_count = sum(
            player.rating_source == "fallback"
            for player in real_players
        )
        if fallback_count:
            warnings.append(
                f"{fallback_count} real player(s) use the "
                "replacement-level fallback rating."
            )

        if (
            len(real_players)
            > resolved_config.oversized_roster_warning
        ):
            warnings.append(
                f"{team} has {len(real_players)} assigned "
                "players, above the current simulator warning "
                "threshold."
            )

        ready = bool(
            len(simulation_players)
            >= resolved_config.minimum_game_players
            and len(starter_ids)
            == resolved_config.starting_lineup_size
            and len(rotation_ids)
            >= resolved_config.minimum_game_players
        )

        team_rosters[team] = TeamSimulationRoster(
            team_abbreviation=team,
            real_players=real_players,
            simulation_players=simulation_players,
            starting_five_ids=starter_ids,
            rotation_player_ids=rotation_ids,
            replacement_player_ids=tuple(
                replacement_ids
            ),
            warnings=tuple(warnings),
            ready_for_game=ready,
        )

    all_simulation_ids = [
        player.player_id
        for roster in team_rosters.values()
        for player in roster.simulation_players
    ]
    finite_ratings = all(
        math.isfinite(player.overall_rating)
        and player.overall_rating > 0
        for roster in team_rosters.values()
        for player in roster.simulation_players
    )

    checks = {
        "exactly_30_teams": (
            len(team_rosters) == 30
        ),
        "no_unknown_team_assignments": (
            not unknown_assignments
        ),
        "simulation_player_ids_unique": (
            len(all_simulation_ids)
            == len(set(all_simulation_ids))
        ),
        "all_teams_ready_for_game": all(
            roster.ready_for_game
            for roster in team_rosters.values()
        ),
        "all_teams_have_starting_five": all(
            len(roster.starting_five_ids)
            == resolved_config.starting_lineup_size
            for roster in team_rosters.values()
        ),
        "all_teams_have_minimum_rotation": all(
            len(roster.rotation_player_ids)
            >= resolved_config.minimum_game_players
            for roster in team_rosters.values()
        ),
        "all_simulation_ratings_finite": (
            finite_ratings
        ),
    }

    return SimulationRosterSnapshot(
        validator_version=VALIDATOR_VERSION,
        state_revision=state.state_revision,
        config=resolved_config,
        teams=team_rosters,
        unassigned_player_ids=tuple(
            sorted(unassigned)
        ),
        unknown_team_assignments=dict(
            sorted(unknown_assignments.items())
        ),
        fallback_rating_player_ids=tuple(
            sorted(set(fallback_ids))
        ),
        replacement_player_ids=tuple(
            sorted(all_replacement_ids)
        ),
        checks=checks,
    )


def team_summary_rows(
    snapshot: SimulationRosterSnapshot,
) -> list[dict[str, Any]]:
    return [
        {
            "team_abbreviation": team,
            "real_player_count": (
                roster.real_player_count
            ),
            "simulation_player_count": (
                roster.simulation_player_count
            ),
            "replacement_count": (
                roster.replacement_count
            ),
            "starting_five_count": len(
                roster.starting_five_ids
            ),
            "rotation_count": len(
                roster.rotation_player_ids
            ),
            "fallback_rating_count": sum(
                player.rating_source == "fallback"
                for player in roster.real_players
            ),
            "unknown_position_count": sum(
                player.position == "UNK"
                for player in roster.real_players
            ),
            "ready_for_game": (
                roster.ready_for_game
            ),
            "warnings": " | ".join(
                roster.warnings
            ),
        }
        for team, roster in sorted(
            snapshot.teams.items()
        )
    ]


def snapshot_report(
    snapshot: SimulationRosterSnapshot,
) -> dict[str, Any]:
    rows = team_summary_rows(snapshot)
    return {
        "script": VALIDATOR_VERSION,
        "state_revision": snapshot.state_revision,
        "config": asdict(snapshot.config),
        "checks": snapshot.checks,
        "failed_checks": [
            name
            for name, passed
            in snapshot.checks.items()
            if not passed
        ],
        "summary": {
            "teams": len(snapshot.teams),
            "ready_teams": sum(
                row["ready_for_game"]
                for row in rows
            ),
            "real_assigned_players": sum(
                row["real_player_count"]
                for row in rows
            ),
            "unassigned_players": len(
                snapshot.unassigned_player_ids
            ),
            "unknown_team_assignments": len(
                snapshot.unknown_team_assignments
            ),
            "fallback_rating_players": len(
                snapshot.fallback_rating_player_ids
            ),
            "replacement_players": len(
                snapshot.replacement_player_ids
            ),
        },
        "team_summary": rows,
        "passed": snapshot.ready,
    }


def write_outputs(
    snapshot: SimulationRosterSnapshot,
) -> dict[str, Any]:
    report = snapshot_report(snapshot)
    OUTPUTS.mkdir(
        parents=True,
        exist_ok=True,
    )
    READINESS_REPORT.write_text(
        json.dumps(
            report,
            indent=2,
        ),
        encoding="utf-8",
    )

    rows = report["team_summary"]
    with TEAM_SUMMARY_CSV.open(
        "w",
        encoding="utf-8",
        newline="",
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=list(rows[0])
            if rows
            else [
                "team_abbreviation",
                "ready_for_game",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)

    return report


def depleted_state(
    state: LeagueState,
    team: str,
    keep_players: int,
) -> LeagueState:
    result = copy.deepcopy(state)
    team = normalize_team(team)
    assigned = sorted(
        player_id
        for player_id, owner in (
            result.player_team_by_id.items()
        )
        if normalize_team(owner) == team
    )

    for player_id in assigned[keep_players:]:
        result.player_team_by_id[player_id] = ""

    result.state_revision += 1
    return result


def run_self_test() -> dict[str, Any]:
    runtime = load_runtime_data()
    state = create_league_state(runtime)
    adapted = build_state_runtime(
        runtime,
        state,
    )

    state_before = state_signature(state)
    runtime_before = runtime_signature(adapted)

    baseline = build_simulation_roster_snapshot(
        adapted,
        state,
    )
    baseline_report = snapshot_report(baseline)

    checks: dict[str, bool] = {
        "baseline_snapshot_passes": baseline.ready,
        "baseline_has_30_teams": (
            len(baseline.teams) == 30
        ),
        "baseline_all_teams_have_starting_five": (
            all(
                len(roster.starting_five_ids) == 5
                for roster in baseline.teams.values()
            )
        ),
        "baseline_all_teams_have_minimum_rotation": (
            all(
                len(roster.rotation_player_ids) >= 8
                for roster in baseline.teams.values()
            )
        ),
        "baseline_simulation_ids_unique": (
            baseline.checks[
                "simulation_player_ids_unique"
            ]
        ),
        "baseline_ratings_finite": (
            baseline.checks[
                "all_simulation_ratings_finite"
            ]
        ),
        "builder_does_not_mutate_state": (
            state_signature(state)
            == state_before
        ),
        "builder_does_not_mutate_runtime": (
            runtime_signature(adapted)
            == runtime_before
        ),
    }

    most_populated_team = max(
        baseline.teams,
        key=lambda team: (
            baseline.teams[
                team
            ].real_player_count
        ),
    )
    damaged = depleted_state(
        state,
        most_populated_team,
        keep_players=3,
    )
    damaged_runtime = build_state_runtime(
        runtime,
        damaged,
    )
    repaired = build_simulation_roster_snapshot(
        damaged_runtime,
        damaged,
    )
    repaired_team = repaired.teams[
        most_populated_team
    ]

    checks[
        "autofill_repairs_depleted_team"
    ] = bool(
        repaired_team.real_player_count == 3
        and repaired_team.simulation_player_count == 8
        and repaired_team.replacement_count == 5
        and repaired_team.ready_for_game
    )
    checks[
        "autofill_produces_starting_five"
    ] = (
        len(repaired_team.starting_five_ids) == 5
    )
    checks[
        "autofill_produces_minimum_rotation"
    ] = (
        len(repaired_team.rotation_player_ids) == 8
    )

    repaired_again = (
        build_simulation_roster_snapshot(
            damaged_runtime,
            damaged,
        )
    )
    checks[
        "replacement_generation_is_deterministic"
    ] = (
        repaired_team.replacement_player_ids
        == repaired_again.teams[
            most_populated_team
        ].replacement_player_ids
    )

    no_fill = build_simulation_roster_snapshot(
        damaged_runtime,
        damaged,
        config=RosterValidationConfig(
            auto_fill_replacements=False,
        ),
    )
    checks[
        "depleted_team_fails_without_autofill"
    ] = (
        not no_fill.teams[
            most_populated_team
        ].ready_for_game
        and not no_fill.ready
    )

    fallback_rating, fallback_source = (
        extract_overall_rating({}, 67.0)
    )
    checks[
        "missing_rating_uses_safe_fallback"
    ] = (
        fallback_rating == 67.0
        and fallback_source == "fallback"
    )

    invalid_config_blocked = False
    try:
        build_simulation_roster_snapshot(
            adapted,
            state,
            config=RosterValidationConfig(
                minimum_game_players=4,
            ),
        )
    except SimulationRosterValidationError:
        invalid_config_blocked = True

    checks[
        "invalid_config_is_rejected"
    ] = invalid_config_blocked

    failed = [
        name
        for name, passed in checks.items()
        if not passed
    ]
    report = {
        "script": VALIDATOR_VERSION,
        "checks": checks,
        "failed_checks": failed,
        "details": {
            "baseline": baseline_report[
                "summary"
            ],
            "depleted_team": (
                most_populated_team
            ),
            "depleted_team_real_players": (
                repaired_team.real_player_count
            ),
            "depleted_team_replacements": (
                list(
                    repaired_team
                    .replacement_player_ids
                )
            ),
            "depleted_team_rotation": list(
                repaired_team.rotation_player_ids
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
        ),
        encoding="utf-8",
    )

    if failed:
        raise AssertionError(
            "Simulation roster validator V1 self-test "
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
        "--no-autofill",
        action="store_true",
    )
    parser.add_argument(
        "--minimum-game-players",
        type=int,
        default=8,
    )
    parser.add_argument(
        "--rotation-size",
        type=int,
        default=10,
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
            "\nSIMULATION ROSTER VALIDATOR V1 "
            "SELF-TEST PASSED"
        )
        return 0

    runtime = load_runtime_data()
    state = create_league_state(runtime)
    adapted = build_state_runtime(
        runtime,
        state,
    )
    snapshot = build_simulation_roster_snapshot(
        adapted,
        state,
        config=RosterValidationConfig(
            minimum_game_players=max(
                args.minimum_game_players,
                5,
            ),
            target_rotation_size=max(
                args.rotation_size,
                args.minimum_game_players,
                5,
            ),
            auto_fill_replacements=(
                not args.no_autofill
            ),
        ),
    )
    report = write_outputs(snapshot)
    print(
        json.dumps(
            {
                "script": report["script"],
                "checks": report["checks"],
                "failed_checks": (
                    report["failed_checks"]
                ),
                "summary": report["summary"],
                "outputs": {
                    "readiness_report": str(
                        READINESS_REPORT
                    ),
                    "team_summary_csv": str(
                        TEAM_SUMMARY_CSV
                    ),
                },
                "passed": report["passed"],
            },
            indent=2,
        )
    )

    if not report["passed"]:
        return 1

    print(
        "\nSIMULATION ROSTER READINESS PASSED"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())