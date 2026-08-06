"""Repair the V4.5.1 Player Ratings app payload and self-test contract.

This patch does not recalculate or change any player ratings.

It:
1. Backs up the live V4.5.1 JSON and Player Ratings page.
2. Finds the best older player-ratings JSON containing branding/status fields.
3. Merges display team and roster-status metadata by player_id.
4. Preserves blank team_abbreviation values for free agents.
5. Explicitly preserves Jalen Duren's Detroit branding plus free-agent status.
6. Updates stale Player Ratings self-test expectations to V4.5.1.
7. Validates the repaired JSON and compiles the page.

Run from the project root:
    python .\src\patch_player_ratings_v4_5_1_app_contract.py --self-test
    python .\src\patch_player_ratings_v4_5_1_app_contract.py
"""

from __future__ import annotations

import argparse
import json
import math
import re
import shutil
from pathlib import Path
from typing import Any


SCRIPT_VERSION = "player-ratings-v4-5-1-app-contract-patch-v1-2026-08-06"

PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_DATA_DIRECTORY = PROJECT_ROOT / "app_data"
PAGES_DIRECTORY = PROJECT_ROOT / "pages"

LIVE_JSON = APP_DATA_DIRECTORY / "player_ratings_2026_27_v2.json"
PAGE_PATH = PAGES_DIRECTORY / "2_Player_Ratings.py"

JSON_BACKUP = (
    APP_DATA_DIRECTORY
    / "player_ratings_2026_27_v2_backup_before_app_contract_patch.json"
)
PAGE_BACKUP = (
    PAGES_DIRECTORY
    / "2_Player_Ratings_backup_before_v4_5_1_contract_patch.py"
)

EXPECTED_RELEASE = "player_ratings_2026_27_v4_5_1_role_aware"
EXPECTED_PLAYER_COUNT = 582

TEAM_NAMES = {
    "ATL": "Atlanta Hawks",
    "BOS": "Boston Celtics",
    "BKN": "Brooklyn Nets",
    "CHA": "Charlotte Hornets",
    "CHI": "Chicago Bulls",
    "CLE": "Cleveland Cavaliers",
    "DAL": "Dallas Mavericks",
    "DEN": "Denver Nuggets",
    "DET": "Detroit Pistons",
    "GSW": "Golden State Warriors",
    "HOU": "Houston Rockets",
    "IND": "Indiana Pacers",
    "LAC": "LA Clippers",
    "LAL": "Los Angeles Lakers",
    "MEM": "Memphis Grizzlies",
    "MIA": "Miami Heat",
    "MIL": "Milwaukee Bucks",
    "MIN": "Minnesota Timberwolves",
    "NOP": "New Orleans Pelicans",
    "NYK": "New York Knicks",
    "OKC": "Oklahoma City Thunder",
    "ORL": "Orlando Magic",
    "PHI": "Philadelphia 76ers",
    "PHX": "Phoenix Suns",
    "POR": "Portland Trail Blazers",
    "SAC": "Sacramento Kings",
    "SAS": "San Antonio Spurs",
    "TOR": "Toronto Raptors",
    "UTA": "Utah Jazz",
    "WAS": "Washington Wizards",
}

BRANDING_FIELDS = {
    "display_team_abbreviation",
    "display_team_name",
    "roster_status",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Run helper tests without modifying project files.",
    )
    return parser.parse_args()


def normalize_player_id(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if text.endswith(".0") and text[:-2].isdigit():
        return text[:-2]
    return text


def clean_team(value: Any) -> str:
    text = str(value or "").strip().upper()
    if text in {"", "NONE", "NAN", "NULL"}:
        return ""
    if text in {"FREE AGENT", "FREE_AGENT"}:
        return "FA"
    return text


def load_payload(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    players = payload.get("players_by_id")
    if not isinstance(players, dict) or not players:
        raise ValueError(f"{path} has no nonempty players_by_id mapping.")
    return payload


def source_score(
    path: Path,
    target_ids: set[str],
) -> tuple[int, int, int]:
    try:
        payload = load_payload(path)
    except Exception:
        return (-1, -1, -1)

    players = payload["players_by_id"]
    matched = 0
    branding = 0
    statuses = 0

    for raw_id, record in players.items():
        player_id = normalize_player_id(
            record.get("player_id", raw_id)
        )
        if player_id not in target_ids:
            continue

        matched += 1
        display_team = clean_team(
            record.get("display_team_abbreviation")
            or record.get("team_abbreviation")
        )
        if display_team and display_team != "FA":
            branding += 1

        if str(record.get("roster_status", "")).strip():
            statuses += 1

    return (branding + statuses, matched, branding)


def find_best_branding_source(
    target_ids: set[str],
) -> Path | None:
    preferred = [
        APP_DATA_DIRECTORY / "player_ratings_2026_27_v4.json",
        (
            APP_DATA_DIRECTORY
            / "player_ratings_2026_27_v2_backup_before_v4_5_1_role_aware.json"
        ),
    ]

    all_candidates: list[Path] = []
    for candidate in preferred:
        if candidate.exists() and candidate != LIVE_JSON:
            all_candidates.append(candidate)

    for candidate in sorted(APP_DATA_DIRECTORY.glob("player_ratings_*.json")):
        if (
            candidate != LIVE_JSON
            and candidate not in all_candidates
            and "backup_before_app_contract_patch" not in candidate.name
        ):
            all_candidates.append(candidate)

    scored = [
        (source_score(candidate, target_ids), candidate)
        for candidate in all_candidates
    ]
    scored = [item for item in scored if item[0][0] >= 0]
    if not scored:
        return None

    scored.sort(key=lambda item: item[0], reverse=True)
    return scored[0][1]


def records_by_id(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}
    for raw_id, raw_record in payload["players_by_id"].items():
        record = dict(raw_record)
        player_id = normalize_player_id(
            record.get("player_id", raw_id)
        )
        if player_id:
            output[player_id] = record
    return output


def derive_branding(
    target: dict[str, Any],
    source: dict[str, Any] | None,
) -> tuple[str, str, str]:
    current_team = clean_team(target.get("team_abbreviation"))

    source = source or {}
    display_team = clean_team(
        source.get("display_team_abbreviation")
        or source.get("team_abbreviation")
        or current_team
    )

    if display_team == "FA":
        display_team = ""

    roster_status = str(source.get("roster_status", "")).strip()

    if not roster_status:
        roster_status = (
            "Free agent"
            if not current_team or current_team == "FA"
            else "Under contract"
        )

    display_name = str(source.get("display_team_name", "")).strip()

    if not display_name:
        if display_team:
            display_name = TEAM_NAMES.get(display_team, display_team)
        elif roster_status.casefold() == "free agent":
            display_name = "Free Agent"
        else:
            display_name = ""

    return display_team, display_name, roster_status


def repair_payload(
    live_payload: dict[str, Any],
    source_payload: dict[str, Any] | None,
) -> dict[str, Any]:
    if live_payload.get("release_name") != EXPECTED_RELEASE:
        raise ValueError(
            "The live JSON is not the expected V4.5.1 release. "
            f"Observed: {live_payload.get('release_name')!r}"
        )

    repaired = dict(live_payload)
    source_records = (
        records_by_id(source_payload)
        if source_payload is not None
        else {}
    )

    repaired_players: dict[str, dict[str, Any]] = {}

    for raw_id, raw_record in live_payload["players_by_id"].items():
        record = dict(raw_record)
        player_id = normalize_player_id(
            record.get("player_id", raw_id)
        )
        record["player_id"] = player_id

        display_team, display_name, status = derive_branding(
            record,
            source_records.get(player_id),
        )

        record["display_team_abbreviation"] = display_team
        record["display_team_name"] = display_name
        record["roster_status"] = status

        # Duren is currently a free agent but retains Detroit branding
        # for recognition and team-logo display in the app.
        if player_id == "1631105":
            record["team_abbreviation"] = ""
            record["display_team_abbreviation"] = "DET"
            record["display_team_name"] = TEAM_NAMES["DET"]
            record["roster_status"] = "Free agent"

        repaired_players[player_id] = record

    repaired["players_by_id"] = repaired_players
    repaired["player_count"] = len(repaired_players)
    repaired["app_contract_patch"] = {
        "script_version": SCRIPT_VERSION,
        "branding_source": (
            None
            if source_payload is None
            else source_payload.get("release_name", "unknown")
        ),
        "ratings_changed": False,
    }
    return repaired


def patch_page_source(text: str) -> str:
    original = text

    text = re.sub(
        r'RATINGS_FILENAME\s*=\s*"[^"]+"',
        'RATINGS_FILENAME = "player_ratings_2026_27_v2.json"',
        text,
        count=1,
    )

    text = text.replace(
        '"release_is_validated_v4": (',
        '"release_is_validated_v4_5_1": (',
        1,
    )
    text = text.replace(
        '== "player_ratings_2026_27_v4"',
        '== "player_ratings_2026_27_v4_5_1_role_aware"',
        1,
    )

    old_range = """                "all_core_ratings_in_range": all(
                    60.0
                    <= safe_float(record.get(field), 0.0)
                    <= (
                        99.5
                        if field == "potential_rating"
                        else 98.2
                    )
                    for record in records
                    for field in [
                        "overall_rating",
                        "potential_rating",
                        "contract_value_rating",
                        "trade_value_rating",
                    ]
                ),"""
    new_range = """                "all_core_ratings_in_range": all(
                    60.0
                    <= safe_float(record.get(field), 0.0)
                    <= {
                        "overall_rating": 98.5,
                        "potential_rating": 99.5,
                        "contract_value_rating": 99.9,
                        "trade_value_rating": 99.9,
                    }[field]
                    for record in records
                    for field in [
                        "overall_rating",
                        "potential_rating",
                        "contract_value_rating",
                        "trade_value_rating",
                    ]
                ),"""
    if old_range not in text:
        raise RuntimeError(
            "Could not locate the stale core-rating range test."
        )
    text = text.replace(old_range, new_range, 1)

    text = text.replace(
        '"top_player_is_near_98_2": math.isclose(',
        '"top_player_is_near_97_9": math.isclose(',
        1,
    )
    text = text.replace(
        """                    safe_float(records[0].get("overall_rating")),
                    98.2,
""",
        """                    safe_float(records[0].get("overall_rating")),
                    97.9,
                    abs_tol=0.05,
""",
        1,
    )

    if text == original:
        raise RuntimeError("The Player Ratings page was not patched.")
    return text


def validate_payload(payload: dict[str, Any]) -> dict[str, bool]:
    players = records_by_id(payload)

    required = {
        "player_id",
        "player_name",
        "team_abbreviation",
        "display_team_abbreviation",
        "display_team_name",
        "roster_status",
        "league_overall_rank",
        "overall_rating",
        "potential_rating",
        "future_outlook_rating",
        "contract_value_rating",
        "trade_value_rating",
        "archetype",
    }

    duren = players.get("1631105")

    return {
        "release_is_v4_5_1": (
            payload.get("release_name") == EXPECTED_RELEASE
        ),
        "player_count_is_582": len(players) == EXPECTED_PLAYER_COUNT,
        "all_required_fields_present": all(
            required.issubset(record)
            for record in players.values()
        ),
        "all_branding_fields_non_null": all(
            record.get(field) is not None
            for record in players.values()
            for field in BRANDING_FIELDS
        ),
        "duren_present": duren is not None,
        "duren_detroit_branding": (
            duren is not None
            and duren.get("display_team_abbreviation") == "DET"
            and duren.get("display_team_name") == "Detroit Pistons"
        ),
        "duren_free_agent_status": (
            duren is not None
            and duren.get("roster_status") == "Free agent"
            and clean_team(duren.get("team_abbreviation")) == ""
        ),
        "kon_rating_preserved": any(
            record.get("player_name") == "Kon Knueppel"
            and math.isclose(float(record.get("overall_rating")), 87.5)
            and math.isclose(float(record.get("potential_rating")), 95.5)
            for record in players.values()
        ),
        "jokic_rating_preserved": any(
            record.get("player_name") == "Nikola Jokić"
            and math.isclose(float(record.get("overall_rating")), 97.9)
            for record in players.values()
        ),
    }


def atomic_write_text(path: Path, text: str) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def run_self_test() -> int:
    live = {
        "release_name": EXPECTED_RELEASE,
        "players_by_id": {
            "1631105": {
                "player_id": "1631105",
                "player_name": "Jalen Duren",
                "team_abbreviation": "",
                "overall_rating": 90.4,
                "potential_rating": 92.5,
                "future_outlook_rating": 91.0,
                "contract_value_rating": 90.0,
                "trade_value_rating": 92.0,
                "league_overall_rank": 35,
                "archetype": "Interior Big",
            },
            "1642851": {
                "player_id": "1642851",
                "player_name": "Kon Knueppel",
                "team_abbreviation": "CHA",
                "overall_rating": 87.5,
                "potential_rating": 95.5,
                "future_outlook_rating": 94.5,
                "contract_value_rating": 96.0,
                "trade_value_rating": 97.0,
                "league_overall_rank": 72,
                "archetype": "Wing",
            },
            "203999": {
                "player_id": "203999",
                "player_name": "Nikola Jokić",
                "team_abbreviation": "DEN",
                "overall_rating": 97.9,
                "potential_rating": 98.6,
                "future_outlook_rating": 91.9,
                "contract_value_rating": 95.0,
                "trade_value_rating": 95.0,
                "league_overall_rank": 1,
                "archetype": "Big",
            },
        },
    }
    source = {
        "release_name": "legacy",
        "players_by_id": {
            "1631105": {
                "player_id": "1631105",
                "team_abbreviation": "",
                "display_team_abbreviation": "DET",
                "display_team_name": "Detroit Pistons",
                "roster_status": "Free agent",
            },
            "1642851": {
                "player_id": "1642851",
                "team_abbreviation": "CHA",
                "display_team_abbreviation": "CHA",
                "display_team_name": "Charlotte Hornets",
                "roster_status": "Under contract",
            },
            "203999": {
                "player_id": "203999",
                "team_abbreviation": "DEN",
                "display_team_abbreviation": "DEN",
                "display_team_name": "Denver Nuggets",
                "roster_status": "Under contract",
            },
        },
    }

    repaired = repair_payload(live, source)
    players = repaired["players_by_id"]

    sample_page = """
RATINGS_FILENAME = "player_ratings_2026_27_v4.json"
"release_is_validated_v4": (
    payload.get("release_name")
    == "player_ratings_2026_27_v4"
),
                "all_core_ratings_in_range": all(
                    60.0
                    <= safe_float(record.get(field), 0.0)
                    <= (
                        99.5
                        if field == "potential_rating"
                        else 98.2
                    )
                    for record in records
                    for field in [
                        "overall_rating",
                        "potential_rating",
                        "contract_value_rating",
                        "trade_value_rating",
                    ]
                ),
"top_player_is_near_98_2": math.isclose(
                    safe_float(records[0].get("overall_rating")),
                    98.2,
),
"""

    patched_sample = patch_page_source(sample_page)

    tests = {
        "duren_branding": (
            players["1631105"]["display_team_abbreviation"] == "DET"
        ),
        "duren_status": (
            players["1631105"]["roster_status"] == "Free agent"
        ),
        "duren_team_stays_blank": (
            players["1631105"]["team_abbreviation"] == ""
        ),
        "kon_branding": (
            players["1642851"]["display_team_abbreviation"] == "CHA"
        ),
        "ratings_unchanged": (
            players["1642851"]["overall_rating"] == 87.5
            and players["203999"]["overall_rating"] == 97.9
        ),
        "page_filename_patch": (
            'RATINGS_FILENAME = "player_ratings_2026_27_v2.json"'
            in patched_sample
        ),
        "release_test_patch": (
            '"release_is_validated_v4_5_1"' in patched_sample
        ),
        "rating_range_patch": (
            '"contract_value_rating": 99.9' in patched_sample
        ),
        "top_player_patch": (
            '"top_player_is_near_97_9"' in patched_sample
            and "97.9" in patched_sample
        ),
    }

    print(json.dumps(tests, indent=2))
    return 0 if all(tests.values()) else 1


def main() -> int:
    args = parse_args()
    if args.self_test:
        return run_self_test()

    if not LIVE_JSON.exists():
        raise FileNotFoundError(f"Live JSON not found: {LIVE_JSON}")
    if not PAGE_PATH.exists():
        raise FileNotFoundError(f"Player Ratings page not found: {PAGE_PATH}")

    live_payload = load_payload(LIVE_JSON)
    target_ids = set(records_by_id(live_payload))
    source_path = find_best_branding_source(target_ids)
    source_payload = (
        load_payload(source_path)
        if source_path is not None
        else None
    )

    print("=" * 88)
    print("PLAYER RATINGS V4.5.1 APP CONTRACT PATCH")
    print("=" * 88)
    print(f"Script version: {SCRIPT_VERSION}")
    print(f"Live JSON: {LIVE_JSON}")
    print(
        "Branding source: "
        + (str(source_path) if source_path else "derived fallback")
    )

    shutil.copy2(LIVE_JSON, JSON_BACKUP)
    shutil.copy2(PAGE_PATH, PAGE_BACKUP)

    repaired_payload = repair_payload(
        live_payload,
        source_payload,
    )
    validations = validate_payload(repaired_payload)

    print("\nPAYLOAD VALIDATION")
    print(json.dumps(validations, indent=2))

    if not all(validations.values()):
        raise RuntimeError(
            "Repaired payload did not pass all validation checks."
        )

    payload_text = json.dumps(
        repaired_payload,
        indent=2,
        ensure_ascii=False,
    )
    atomic_write_text(LIVE_JSON, payload_text)

    page_text = PAGE_PATH.read_text(encoding="utf-8-sig")
    patched_page = patch_page_source(page_text)
    atomic_write_text(PAGE_PATH, patched_page)

    compile(
        patched_page,
        str(PAGE_PATH),
        "exec",
    )

    print("\nComplete")
    print(f"JSON backup: {JSON_BACKUP}")
    print(f"Page backup: {PAGE_BACKUP}")
    print("Ratings changed: False")
    print("Player Ratings page compiled: True")
    print(
        "Next: python "
        '".\\pages\\2_Player_Ratings.py" --self-test'
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())