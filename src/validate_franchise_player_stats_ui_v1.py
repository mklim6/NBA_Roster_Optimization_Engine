from __future__ import annotations

import json
import py_compile
import sys
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
PAGE = ROOT / "pages" / "5_Franchise_Mode.py"
OUTPUTS = ROOT / "outputs"
REPORT = OUTPUTS / "franchise_player_stats_ui_validation_v1.json"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from franchise_player_stats_v1 import (  # noqa: E402
    FRANCHISE_PLAYER_STATS_VERSION,
    regular_season_player_rows,
)

VALIDATOR_VERSION = "franchise-player-stats-ui-validator-v1-2026-08-10"
EXPECTED_STATS_VERSION = "franchise-player-stats-v1-2026-08-10"


def compile_file(path: Path) -> str:
    try:
        py_compile.compile(str(path), doraise=True)
    except py_compile.PyCompileError as exc:
        return str(exc)
    return ""


def sample_state() -> SimpleNamespace:
    player = SimpleNamespace(
        player_name="Sample Guard",
        team_abbreviation="CHI",
        position="PG/SG",
    )
    totals = SimpleNamespace(
        games_played=10,
        games_started=8,
        minutes=320.0,
        points=250,
        rebounds=50,
        assists=80,
        steals=15,
        blocks=4,
        turnovers=30,
        fouls=20,
        field_goals_made=90,
        field_goals_attempted=180,
        three_pointers_made=30,
        three_pointers_attempted=75,
        free_throws_made=40,
        free_throws_attempted=50,
    )
    return SimpleNamespace(
        players={"P1": player},
        player_season_totals={"P1": totals},
    )


def run_validation() -> dict[str, object]:
    page_text = PAGE.read_text(encoding="utf-8")
    rows = regular_season_player_rows(
        sample_state(),
        minimum_games=1,
        limit=50,
    )
    row = rows[0]

    required_columns = (
        "Player", "Team", "Pos", "GP", "GS", "MIN", "PTS",
        "REB", "AST", "STL", "BLK", "TO", "PF",
        "FGM", "FGA", "FG%", "3PM", "3PA", "3P%",
        "FTM", "FTA", "FT%", "eFG%", "TS%",
    )
    compile_results = {
        str(path.relative_to(ROOT)): compile_file(path)
        for path in (
            PAGE,
            SRC / "franchise_player_stats_v1.py",
            Path(__file__),
        )
    }

    checks = {
        "validator_version_is_current": (
            VALIDATOR_VERSION
            == "franchise-player-stats-ui-validator-v1-2026-08-10"
        ),
        "stats_version_is_current": (
            FRANCHISE_PLAYER_STATS_VERSION == EXPECTED_STATS_VERSION
        ),
        "regular_season_page_uses_rich_stats_rows": (
            "regular_season_player_rows(" in page_text
            and "FRANCHISE_PLAYER_STATS_VERSION" in page_text
        ),
        "all_standard_columns_are_present": all(
            column in row for column in required_columns
        ),
        "field_goal_percentage_is_correct": row["FG%"] == 50.0,
        "three_point_percentage_is_correct": row["3P%"] == 40.0,
        "free_throw_percentage_is_correct": row["FT%"] == 80.0,
        "effective_fg_percentage_is_correct": row["eFG%"] == 58.3,
        "true_shooting_percentage_is_correct": row["TS%"] == 61.9,
        "shooting_volume_is_per_game": (
            row["FGM"] == 9.0
            and row["FGA"] == 18.0
            and row["3PM"] == 3.0
            and row["3PA"] == 7.5
            and row["FTM"] == 4.0
            and row["FTA"] == 5.0
        ),
        "turnovers_and_fouls_are_per_game": (
            row["TO"] == 3.0 and row["PF"] == 2.0
        ),
        "games_started_is_exposed": row["GS"] == 8,
        "all_modified_files_compile": all(
            not error for error in compile_results.values()
        ),
    }

    failed = [name for name, passed in checks.items() if not passed]
    report = {
        "script": VALIDATOR_VERSION,
        "stats_version": FRANCHISE_PLAYER_STATS_VERSION,
        "checks": checks,
        "failed_checks": failed,
        "sample_row": row,
        "required_columns": list(required_columns),
        "compile_results": compile_results,
        "passed": not failed,
    }

    OUTPUTS.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")

    if failed:
        raise AssertionError(
            "Franchise player stats UI validation failed: "
            + ", ".join(failed)
        )
    return report


def main() -> int:
    report = run_validation()
    print(json.dumps(report, indent=2))
    print("\nFRANCHISE PLAYER STATS UI V1 VALIDATION PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
