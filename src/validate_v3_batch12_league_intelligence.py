from __future__ import annotations

import hashlib
import py_compile
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from desktop_bridge.league_intelligence_foundation import (  # noqa: E402
    LEAGUE_INTELLIGENCE_FOUNDATION_VERSION,
    build_league_intelligence_payload,
)
from simulation_franchise_checkpoint_v1 import (  # noqa: E402
    DEFAULT_CHECKPOINT_PATH,
    load_franchise_checkpoint,
)


V3_WORKING = ROOT / "outputs" / "runtime" / "v3_godot_working_checkpoint.pkl.gz"
REPORT_DIR = ROOT / "outputs" / "v3_batch12_league_intelligence"

TEAM_NAMES = {
    "ATL": "Atlanta Hawks", "BKN": "Brooklyn Nets", "BOS": "Boston Celtics",
    "CHA": "Charlotte Hornets", "CHI": "Chicago Bulls", "CLE": "Cleveland Cavaliers",
    "DAL": "Dallas Mavericks", "DEN": "Denver Nuggets", "DET": "Detroit Pistons",
    "GSW": "Golden State Warriors", "HOU": "Houston Rockets", "IND": "Indiana Pacers",
    "LAC": "LA Clippers", "LAL": "Los Angeles Lakers", "MEM": "Memphis Grizzlies",
    "MIA": "Miami Heat", "MIL": "Milwaukee Bucks", "MIN": "Minnesota Timberwolves",
    "NOP": "New Orleans Pelicans", "NYK": "New York Knicks", "OKC": "Oklahoma City Thunder",
    "ORL": "Orlando Magic", "PHI": "Philadelphia 76ers", "PHX": "Phoenix Suns",
    "POR": "Portland Trail Blazers", "SAC": "Sacramento Kings", "SAS": "San Antonio Spurs",
    "TOR": "Toronto Raptors", "UTA": "Utah Jazz", "WAS": "Washington Wizards",
}


def file_sha(path: Path) -> str | None:
    if not path.exists():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def check(name: str, condition: bool, checks: list[tuple[str, bool]]) -> None:
    passed = bool(condition)
    checks.append((name, passed))
    print(f"  {name}: {'PASS' if passed else 'FAIL'}")


def main() -> int:
    print("=" * 88)
    print("V3 BATCH 12 LEAGUE INTELLIGENCE CENTER VALIDATION")
    print("=" * 88)

    checks: list[tuple[str, bool]] = []
    server_path = ROOT / "desktop_bridge" / "server.py"
    foundation_path = ROOT / "desktop_bridge" / "league_intelligence_foundation.py"
    main_gd_path = ROOT / "godot_client" / "scripts" / "main.gd"
    league_gd_path = ROOT / "godot_client" / "scripts" / "league_intelligence_center_v3.gd"
    validator_path = Path(__file__).resolve()

    server_text = server_path.read_text(encoding="utf-8")
    main_text = main_gd_path.read_text(encoding="utf-8")
    league_text = league_gd_path.read_text(encoding="utf-8")

    check(
        "batch12_foundation_version",
        LEAGUE_INTELLIGENCE_FOUNDATION_VERSION.startswith("v3-league-intelligence-foundation-batch-12"),
        checks,
    )
    check(
        "league_endpoint_registered",
        'Route("/v3/league-intelligence", league_intelligence, methods=["GET"])' in server_text,
        checks,
    )
    check(
        "league_foundation_imported",
        "from desktop_bridge.league_intelligence_foundation import build_league_intelligence_payload" in server_text,
        checks,
    )
    check(
        "godot_league_center_preloaded",
        'preload("res://scripts/league_intelligence_center_v3.gd")' in main_text,
        checks,
    )
    check(
        "godot_league_center_instantiated",
        "league_page = LeagueIntelligenceCenterV3.new()" in main_text,
        checks,
    )
    check(
        "godot_league_live_endpoint",
        'const LEAGUE_URL := "http://127.0.0.1:8765/v3/league-intelligence"' in league_text,
        checks,
    )
    check(
        "godot_no_python_style_payload_fallback",
        all(token not in league_text for token in (') or "', ') or 0', ') or []', ') or {}')),
        checks,
    )
    check(
        "league_page_sections_present",
        all(
            label in league_text
            for label in (
                "EASTERN CONFERENCE",
                "WESTERN CONFERENCE",
                "STATISTICAL LEADERS",
                "PLAYOFF PICTURE",
                "SCHEDULE + RESULTS",
                "AWARD WATCH",
                "POSTSEASON / BRACKET",
                "LEAGUE HISTORY",
            )
        ),
        checks,
    )

    compile_ok = True
    for path in (foundation_path, server_path, validator_path):
        try:
            py_compile.compile(str(path), doraise=True)
        except Exception as exc:
            compile_ok = False
            print(f"    compile failure: {path.name}: {type(exc).__name__}: {exc}")
    check("modified_python_files_compile", compile_ok, checks)

    v2_path = Path(DEFAULT_CHECKPOINT_PATH)
    working_before = file_sha(V3_WORKING)
    v2_before = file_sha(v2_path)
    dynamic_ok = False
    payload: dict[str, Any] = {}
    dynamic_error = ""

    try:
        checkpoint = load_franchise_checkpoint(path=V3_WORKING, allow_backup=False)
        if checkpoint is None:
            raise RuntimeError("V3 working checkpoint is not initialized.")
        payload = build_league_intelligence_payload(checkpoint, team_names=TEAM_NAMES)
        standings = payload.get("standings", {})
        east = list(standings.get("east", []) or [])
        west = list(standings.get("west", []) or [])
        schedule = dict(payload.get("schedule", {}) or {})
        leaders = dict(payload.get("leaders", {}) or {})
        playoff = dict(payload.get("playoff_picture", {}) or {})

        check("dynamic_read_only_payload", payload.get("read_only") is True, checks)
        check("dynamic_v3_working_save_only", payload.get("working_save_only") is True, checks)
        check("dynamic_protected_v2_read_only", payload.get("active_v2_read_only") is True, checks)
        check("dynamic_full_east_standings", len(east) == 15, checks)
        check("dynamic_full_west_standings", len(west) == 15, checks)
        check(
            "dynamic_standings_records_consistent",
            all(int(row.get("wins", 0)) + int(row.get("losses", 0)) == int(row.get("games_played", 0)) for row in east + west),
            checks,
        )
        check(
            "dynamic_schedule_partition_consistent",
            int(schedule.get("completed_games", 0)) + int(schedule.get("remaining_games", 0)) == int(schedule.get("total_games", 0)),
            checks,
        )
        check(
            "dynamic_five_leader_categories",
            set(leaders) >= {"scoring", "rebounds", "assists", "steals", "blocks"},
            checks,
        )
        check(
            "dynamic_playoff_picture_both_conferences",
            len(playoff.get("east", []) or []) <= 10 and len(playoff.get("west", []) or []) <= 10 and bool(playoff.get("east")) and bool(playoff.get("west")),
            checks,
        )
        check(
            "dynamic_award_watch_labeled",
            "projection_note" in dict(payload.get("award_watch", {}) or {}),
            checks,
        )
        check(
            "dynamic_postseason_context_exposed",
            "active" in dict(payload.get("postseason", {}) or {}),
            checks,
        )
        check(
            "dynamic_season_history_exposed",
            isinstance(payload.get("season_history"), list),
            checks,
        )
        dynamic_ok = True
    except Exception as exc:
        dynamic_error = f"{type(exc).__name__}: {exc}"
        check("dynamic_read_only_payload", False, checks)
        print(f"    Dynamic failure: {dynamic_error}")

    working_after = file_sha(V3_WORKING)
    v2_after = file_sha(v2_path)
    check(
        "validator_never_changes_working_save",
        working_before is not None and working_before == working_after,
        checks,
    )
    check(
        "validator_never_changes_v2_checkpoint",
        v2_before is not None and v2_before == v2_after,
        checks,
    )

    failed = [name for name, passed in checks if not passed]
    if dynamic_ok:
        season = dict(payload.get("season", {}) or {})
        schedule = dict(payload.get("schedule", {}) or {})
        active = dict(payload.get("active_team_standing", {}) or {})
        print("\nDynamic live probe: PASS")
        print(f"  Season: {season.get('label', '')}")
        print(f"  Phase: {season.get('phase', '')}")
        print(f"  League games: {schedule.get('completed_games', 0)} / {schedule.get('total_games', 0)}")
        print(f"  Active team: {payload.get('team', '')} #{active.get('rank', '?')} {active.get('conference', '')}")
        print(f"  East teams: {len(payload.get('standings', {}).get('east', []))}")
        print(f"  West teams: {len(payload.get('standings', {}).get('west', []))}")
    print("Godot parser: SKIP (Godot CLI not on PATH; static wiring checks only)")

    if failed:
        print("\nBATCH 12 VALIDATION FAILED")
        print("Failed checks: " + ", ".join(failed))
        return 1

    print("\nBATCH 12 VALIDATION PASSED")
    print("No league-intelligence action was durably executed by this validator.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
