from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
APP_DATA = ROOT / "app_data"
OUTPUTS = ROOT / "outputs"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from freeform_trade_machine_engine_v3 import (  # noqa: E402
    load_runtime_data,
    normalize_player_id,
    normalize_team,
)
from mutable_league_state_v1 import (  # noqa: E402
    create_league_state,
)


SCRIPT_VERSION = (
    "build-player-positions-v1-2026-08-08"
)
OUTPUT_PATH = (
    APP_DATA / "player_positions_2026_27_v1.json"
)
REPORT_PATH = (
    OUTPUTS / "player_positions_2026_27_v1_report.json"
)

DEFAULT_SEASONS = (
    "2026-27",
    "2025-26",
    "2024-25",
)

POSITION_MAP = {
    "POINT GUARD": "PG",
    "SHOOTING GUARD": "SG",
    "SMALL FORWARD": "SF",
    "POWER FORWARD": "PF",
    "CENTER": "C",
    "GUARD": "PG/SG",
    "FORWARD": "SF/PF",
    "GUARD-FORWARD": "SG/SF",
    "FORWARD-GUARD": "SF/SG",
    "FORWARD-CENTER": "PF/C",
    "CENTER-FORWARD": "C/PF",
    "PG": "PG",
    "SG": "SG",
    "SF": "SF",
    "PF": "PF",
    "C": "C",
    "G": "PG/SG",
    "F": "SF/PF",
    "G-F": "SG/SF",
    "F-G": "SF/SG",
    "F-C": "PF/C",
    "C-F": "C/PF",
}


class PositionBuildError(RuntimeError):
    """Raised when position enrichment cannot be built."""


def clean_text(value: Any) -> str:
    if value is None:
        return ""

    text = re.sub(
        r"\s+",
        " ",
        str(value),
    ).strip()

    if text.casefold() in {
        "",
        "nan",
        "none",
        "null",
        "<na>",
    }:
        return ""

    return text


def normalize_position(value: Any) -> str:
    text = clean_text(value).upper()

    if not text:
        return "UNK"

    text = (
        text.replace("–", "-")
        .replace("—", "-")
        .replace("/", "-")
        .replace(" / ", "-")
    )
    text = re.sub(
        r"\s*-\s*",
        "-",
        text,
    )

    if text in POSITION_MAP:
        return POSITION_MAP[text]

    tokens = [
        token
        for token in re.split(
            r"[,|]+",
            text,
        )
        if token
    ]
    normalized = []

    for token in tokens:
        mapped = POSITION_MAP.get(
            token.strip()
        )

        if mapped:
            normalized.extend(
                mapped.split("/")
            )

    normalized = list(
        dict.fromkeys(normalized)
    )

    if normalized:
        return "/".join(normalized)

    return "UNK"


def player_name_from_record(
    record: dict[str, Any],
    player_id: str,
) -> str:
    for field_name in (
        "player_name",
        "player_display_name",
        "display_name",
        "name",
    ):
        value = clean_text(
            record.get(field_name)
        )

        if value:
            return value

    return player_id


def fetch_player_index(
    season: str,
    *,
    attempts: int = 3,
    timeout: int = 60,
) -> list[dict[str, Any]]:
    try:
        from nba_api.stats.endpoints import (
            playerindex,
        )
    except ImportError as exc:
        raise PositionBuildError(
            "nba_api is not installed in this environment."
        ) from exc

    last_error: Exception | None = None

    for attempt in range(1, attempts + 1):
        try:
            endpoint = playerindex.PlayerIndex(
                league_id="00",
                season=season,
                historical_nullable=1,
                timeout=timeout,
            )
            frame = endpoint.get_data_frames()[0]
            return frame.to_dict(
                orient="records"
            )
        except Exception as exc:  # noqa: BLE001
            last_error = exc

            if attempt < attempts:
                time.sleep(2.0 * attempt)

    raise PositionBuildError(
        f"NBA PlayerIndex failed for {season}: "
        f"{last_error}"
    )


def merge_season_rows(
    seasons: tuple[str, ...],
) -> tuple[
    dict[str, dict[str, Any]],
    list[dict[str, Any]],
]:
    players: dict[str, dict[str, Any]] = {}
    season_reports = []

    for season in seasons:
        try:
            rows = fetch_player_index(season)
        except PositionBuildError as exc:
            season_reports.append(
                {
                    "season": season,
                    "status": "failed",
                    "rows": 0,
                    "known_positions": 0,
                    "error": str(exc),
                }
            )
            continue

        known_positions = 0

        for row in rows:
            player_id = normalize_player_id(
                row.get("PERSON_ID")
            )
            position = normalize_position(
                row.get("POSITION")
            )

            if not player_id:
                continue

            if position != "UNK":
                known_positions += 1

            existing = players.get(player_id)

            if (
                existing is None
                or (
                    existing["position"]
                    == "UNK"
                    and position != "UNK"
                )
            ):
                players[player_id] = {
                    "player_id": player_id,
                    "player_name": clean_text(
                        " ".join(
                            [
                                clean_text(
                                    row.get(
                                        "PLAYER_FIRST_NAME"
                                    )
                                ),
                                clean_text(
                                    row.get(
                                        "PLAYER_LAST_NAME"
                                    )
                                ),
                            ]
                        )
                    ),
                    "position": position,
                    "raw_position": clean_text(
                        row.get("POSITION")
                    ),
                    "height": clean_text(
                        row.get("HEIGHT")
                    ),
                    "weight": clean_text(
                        row.get("WEIGHT")
                    ),
                    "roster_status": clean_text(
                        row.get("ROSTER_STATUS")
                    ),
                    "team_abbreviation": normalize_team(
                        row.get(
                            "TEAM_ABBREVIATION"
                        )
                    ),
                    "source_season": season,
                }

        season_reports.append(
            {
                "season": season,
                "status": "passed",
                "rows": len(rows),
                "known_positions": known_positions,
                "error": "",
            }
        )

    if not players:
        errors = "; ".join(
            item["error"]
            for item in season_reports
            if item["error"]
        )
        raise PositionBuildError(
            "No PlayerIndex data could be loaded. "
            + errors
        )

    return players, season_reports


def build_position_payload(
    seasons: tuple[str, ...],
) -> tuple[dict[str, Any], dict[str, Any]]:
    runtime = load_runtime_data()
    league_state = create_league_state(
        runtime
    )
    source_players, season_reports = (
        merge_season_rows(seasons)
    )

    runtime_ids = tuple(
        sorted(runtime.ratings_by_id)
    )
    active_ids = {
        player_id
        for player_id, team
        in league_state.player_team_by_id.items()
        if normalize_team(team)
    }
    players_by_id: dict[
        str,
        dict[str, Any],
    ] = {}
    missing_active = []
    missing_all = []

    for player_id in runtime_ids:
        rating_record = (
            runtime.ratings_by_id.get(
                player_id,
                {},
            )
        )
        source = source_players.get(
            player_id
        )
        name = player_name_from_record(
            rating_record,
            player_id,
        )

        if source is None:
            record = {
                "player_id": player_id,
                "player_name": name,
                "position": "UNK",
                "raw_position": "",
                "height": "",
                "weight": "",
                "roster_status": "",
                "team_abbreviation": "",
                "source_season": "",
                "source": "unresolved",
            }
            missing_all.append(
                {
                    "player_id": player_id,
                    "player_name": name,
                }
            )

            if player_id in active_ids:
                missing_active.append(
                    {
                        "player_id": player_id,
                        "player_name": name,
                    }
                )
        else:
            record = {
                **source,
                "player_name": (
                    source["player_name"]
                    or name
                ),
                "source": (
                    "nba_stats_player_index"
                ),
            }

            if record["position"] == "UNK":
                missing_all.append(
                    {
                        "player_id": player_id,
                        "player_name": name,
                    }
                )

                if player_id in active_ids:
                    missing_active.append(
                        {
                            "player_id": player_id,
                            "player_name": name,
                        }
                    )

        players_by_id[player_id] = record

    active_known = (
        len(active_ids) - len(missing_active)
    )
    all_known = (
        len(runtime_ids) - len(missing_all)
    )
    position_counts = Counter(
        record["position"]
        for record in players_by_id.values()
    )

    payload = {
        "schema_version": (
            "player-positions-v1"
        ),
        "script_version": SCRIPT_VERSION,
        "generated_at_utc": (
            datetime.now(timezone.utc)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z")
        ),
        "source": {
            "provider": "NBA Stats PlayerIndex",
            "endpoint": "playerindex",
            "seasons_attempted": list(
                seasons
            ),
            "season_results": season_reports,
        },
        "summary": {
            "runtime_players": len(
                runtime_ids
            ),
            "active_roster_players": len(
                active_ids
            ),
            "known_positions_all": (
                all_known
            ),
            "known_positions_active": (
                active_known
            ),
            "coverage_all": round(
                all_known / len(runtime_ids),
                4,
            )
            if runtime_ids
            else 0.0,
            "coverage_active": round(
                active_known / len(active_ids),
                4,
            )
            if active_ids
            else 0.0,
            "position_counts": dict(
                sorted(
                    position_counts.items()
                )
            ),
        },
        "players_by_id": players_by_id,
    }
    report = {
        "script": SCRIPT_VERSION,
        "summary": payload["summary"],
        "season_results": season_reports,
        "missing_active_count": len(
            missing_active
        ),
        "missing_active_players": (
            missing_active[:50]
        ),
        "missing_all_count": len(
            missing_all
        ),
        "missing_all_players": (
            missing_all[:50]
        ),
        "output": str(OUTPUT_PATH),
        "passed": bool(
            active_known > 0
            and payload["summary"][
                "coverage_active"
            ]
            >= 0.90
        ),
    }

    return payload, report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--seasons",
        nargs="*",
        default=list(DEFAULT_SEASONS),
    )
    args = parser.parse_args()
    seasons = tuple(
        dict.fromkeys(
            season.strip()
            for season in args.seasons
            if season.strip()
        )
    )

    if not seasons:
        raise PositionBuildError(
            "At least one season is required."
        )

    payload, report = (
        build_position_payload(seasons)
    )
    APP_DATA.mkdir(
        parents=True,
        exist_ok=True,
    )
    OUTPUTS.mkdir(
        parents=True,
        exist_ok=True,
    )
    OUTPUT_PATH.write_text(
        json.dumps(
            payload,
            indent=2,
        ),
        encoding="utf-8",
    )
    REPORT_PATH.write_text(
        json.dumps(
            report,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(
        json.dumps(
            report,
            indent=2,
        )
    )

    if not report["passed"]:
        print(
            "\nPLAYER POSITION BUILD COMPLETED "
            "WITH LOW ACTIVE-ROSTER COVERAGE"
        )
        return 1

    print(
        "\nPLAYER POSITION BUILD V1 PASSED"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())