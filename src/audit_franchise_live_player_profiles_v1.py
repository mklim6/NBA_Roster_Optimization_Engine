"""Harvest official G League evidence for live-start supplemental players.

The September 7 live-start branch materializes a small set of real players
that are absent from the older runtime.  This read-only audit checks whether
the NBA G League publishes a 2025-26 traditional-stat line for each player and
normalizes any available line to per-36 rates.  It never edits the live-start
configuration or active franchise checkpoint.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import math
import re
import sys
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from typing import Any, Mapping

import pandas as pd
import requests


VERSION = "franchise-live-player-profile-audit-v1.1-2026-09-09"
SOURCE_SEASON = "2025-26"
SOURCE_URL_TEMPLATE = "https://gleague.nba.com/player/{player_id}"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/150.0.0.0 Safari/537.36"
)
REQUIRED_COLUMNS = {
    "Season",
    "GP",
    "MIN",
    "PTS",
    "REB",
    "ASST",
    "STL",
    "BLK",
    "TOV",
    "PF",
    "3PA",
    "FTA",
}
PER_36_FIELDS = {
    "points_per_36": "PTS",
    "rebounds_per_36": "REB",
    "assists_per_36": "ASST",
    "steals_per_36": "STL",
    "blocks_per_36": "BLK",
    "turnovers_per_36": "TOV",
    "fouls_per_36": "PF",
    "three_attempts_per_36": "3PA",
    "free_throw_attempts_per_36": "FTA",
}


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    root = project_root()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=root / "app_data" / "nba_live_franchise_start_2026_09_07.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=root / "outputs" / "franchise_live_player_profile_audit_v1.json",
    )
    parser.add_argument("--timeout", type=float, default=20.0)
    return parser.parse_args()


def clean_text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def finite_number(value: Any) -> float | None:
    if clean_text(value) in {"-", "--", "—", "–"}:
        return 0.0
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def normalized_columns(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    result.columns = [
        re.sub(r"\s+", " ", clean_text(column)).strip()
        for column in result.columns
    ]
    return result


def traditional_table(html: str) -> pd.DataFrame | None:
    try:
        tables = pd.read_html(StringIO(html))
    except (ValueError, ImportError):
        return None
    for frame in tables:
        candidate = normalized_columns(frame)
        if REQUIRED_COLUMNS.issubset(candidate.columns):
            return candidate
    return None


def season_row(frame: pd.DataFrame) -> Mapping[str, Any] | None:
    rows = frame.loc[frame["Season"].astype(str).eq(SOURCE_SEASON)]
    if rows.empty:
        rows = frame.loc[~frame["Season"].astype(str).str.lower().eq("total")]
    if rows.empty:
        return None
    return rows.iloc[-1].to_dict()


def derived_baseline(row: Mapping[str, Any]) -> dict[str, float] | None:
    minutes = finite_number(row.get("MIN"))
    if minutes is None or minutes <= 0.0:
        return None
    baseline: dict[str, float] = {}
    for target, source in PER_36_FIELDS.items():
        value = finite_number(row.get(source))
        if value is None:
            return None
        baseline[target] = round(value * 36.0 / minutes, 4)
    return baseline


def derived_shooting(row: Mapping[str, Any]) -> dict[str, float] | None:
    values = {
        field: finite_number(row.get(field))
        for field in ("GP", "PTS", "3PA", "FTA", "FG%", "3P%", "FT%")
    }
    if any(value is None for value in values.values()) or values["GP"] <= 0.0:
        return None
    percentages = {
        field: values[field] / 100.0 if values[field] > 1.0 else values[field]
        for field in ("FG%", "3P%", "FT%")
    }
    if not all(0.0 <= value <= 1.0 for value in percentages.values()):
        return None
    three_made = values["3PA"] * percentages["3P%"]
    free_throws_made = values["FTA"] * percentages["FT%"]
    two_made = max(
        0.0,
        (values["PTS"] - 3.0 * three_made - free_throws_made) / 2.0,
    )
    field_goals_made = two_made + three_made
    if percentages["FG%"] <= 0.0:
        return None
    field_goal_attempts_per_game = field_goals_made / percentages["FG%"]
    if field_goal_attempts_per_game + 1e-9 < values["3PA"]:
        return None
    return {
        "field_goal_percentage": round(percentages["FG%"], 3),
        "three_point_percentage": round(percentages["3P%"], 3),
        "free_throw_percentage": round(percentages["FT%"], 3),
        "field_goal_attempts": round(
            field_goal_attempts_per_game * values["GP"], 2
        ),
        "three_point_attempts": round(values["3PA"] * values["GP"], 2),
        "free_throw_attempts": round(values["FTA"] * values["GP"], 2),
    }


def source_line(row: Mapping[str, Any]) -> dict[str, Any]:
    fields = (
        "Season",
        "Team",
        "Age",
        "GP",
        "GS",
        "MIN",
        "PTS",
        "REB",
        "ASST",
        "STL",
        "BLK",
        "TOV",
        "PF",
        "3PA",
        "FTA",
        "FG%",
        "3P%",
        "FT%",
    )
    return {field: row.get(field) for field in fields if field in row}


def audit_player(
    session: requests.Session,
    profile: Mapping[str, Any],
    *,
    timeout: float,
) -> dict[str, Any]:
    player_id = clean_text(profile.get("player_id"))
    source_url = SOURCE_URL_TEMPLATE.format(player_id=player_id)
    result: dict[str, Any] = {
        "player_id": player_id,
        "player_name": clean_text(profile.get("player_name")),
        "source_url": source_url,
        "source_season": SOURCE_SEASON,
        "evidence_status": "unavailable",
    }
    for request_attempt in range(2):
        try:
            response = session.get(source_url, timeout=timeout)
            result["http_status"] = int(response.status_code)
            response.raise_for_status()
            frame = traditional_table(response.text)
            if frame is None:
                result["evidence_status"] = "no_traditional_table"
                return result
            row = season_row(frame)
            if row is None:
                result["evidence_status"] = "no_season_row"
                return result
            baseline = derived_baseline(row)
            shooting = derived_shooting(row)
            if baseline is None or shooting is None:
                result["evidence_status"] = "incomplete_stat_line"
                return result
            result.update(
                {
                    "evidence_status": "official_gleague_stat_line",
                    "source_line": source_line(row),
                    "observed_per_36": baseline,
                    "observed_shooting": shooting,
                    "shooting_attempts_method": (
                        "estimated_from_official_rounded_per_game_line"
                    ),
                    "request_attempts": request_attempt + 1,
                }
            )
            return result
        except requests.Timeout as exc:
            if request_attempt == 0:
                continue
            result["request_attempts"] = request_attempt + 1
            result["error"] = f"{type(exc).__name__}: {exc}"
            return result
        except requests.RequestException as exc:
            result["request_attempts"] = request_attempt + 1
            result["error"] = f"{type(exc).__name__}: {exc}"
            return result
    return result


def main() -> int:
    args = parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    profiles = config.get("missing_player_profiles", [])
    if not isinstance(profiles, list):
        raise ValueError("missing_player_profiles must be an array")

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    valid_profiles = [profile for profile in profiles if isinstance(profile, Mapping)]
    with ThreadPoolExecutor(max_workers=4) as executor:
        players = list(
            executor.map(
                lambda profile: audit_player(
                    session,
                    profile,
                    timeout=args.timeout,
                ),
                valid_profiles,
            )
        )
    covered = [
        row for row in players
        if row.get("evidence_status") == "official_gleague_stat_line"
    ]
    report = {
        "version": VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "read_only": True,
        "config": str(args.config.resolve()),
        "source_season": SOURCE_SEASON,
        "counts": {
            "supplemental_players": len(players),
            "official_gleague_stat_lines": len(covered),
            "remaining_without_gleague_stat_line": len(players) - len(covered),
        },
        "players": players,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report["counts"], indent=2))
    print(args.output.resolve())
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
