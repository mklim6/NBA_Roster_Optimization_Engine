"""Build team logo and player headshot asset mappings for the mixed trade app.

This script reads the finalized app JSON bundle and the existing 2026-27 player
market, resolves the players shown in app-facing concepts to NBA player IDs, and
writes a small visual-asset JSON file for Streamlit.

Output:
    app_data/mixed_trade_visual_assets_2026_27_v1.json
"""

from __future__ import annotations

import argparse
import json
import math
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


SCRIPT_VERSION = "mixed-trade-visual-assets-v1-2026-08-06"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_DATA_DIRECTORY = PROJECT_ROOT / "app_data"
DATA_DIRECTORY = PROJECT_ROOT / "data" / "processed"

BUNDLE_PATH = (
    APP_DATA_DIRECTORY
    / "mixed_player_pick_release_2026_27_v1.json"
)
PLAYER_MARKET_CANDIDATES = [
    DATA_DIRECTORY
    / "player_trade_market_value_layer_2026_27_v4_protected.parquet",
    DATA_DIRECTORY
    / "player_trade_market_value_layer_2026_27_v4_protected.csv",
    DATA_DIRECTORY
    / "player_trade_market_value_layer_2026_27.parquet",
    DATA_DIRECTORY
    / "player_trade_market_value_layer_2026_27.csv",
]
OUTPUT_PATH = (
    APP_DATA_DIRECTORY
    / "mixed_trade_visual_assets_2026_27_v1.json"
)
VALIDATION_PATH = (
    PROJECT_ROOT
    / "outputs"
    / "mixed_trade_visual_assets_validation_v1.csv"
)

TEAM_IDS = {
    "ATL": 1610612737,
    "BOS": 1610612738,
    "CLE": 1610612739,
    "NOP": 1610612740,
    "CHI": 1610612741,
    "DAL": 1610612742,
    "DEN": 1610612743,
    "GSW": 1610612744,
    "HOU": 1610612745,
    "LAC": 1610612746,
    "LAL": 1610612747,
    "MIA": 1610612748,
    "MIL": 1610612749,
    "MIN": 1610612750,
    "BKN": 1610612751,
    "NYK": 1610612752,
    "ORL": 1610612753,
    "IND": 1610612754,
    "PHI": 1610612755,
    "PHX": 1610612756,
    "POR": 1610612757,
    "SAC": 1610612758,
    "SAS": 1610612759,
    "OKC": 1610612760,
    "TOR": 1610612761,
    "UTA": 1610612762,
    "MEM": 1610612763,
    "WAS": 1610612764,
    "DET": 1610612765,
    "CHA": 1610612766,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Run helper tests without reading project files.",
    )
    return parser.parse_args()


def normalized_name(value: Any) -> str:
    text = "" if value is None else str(value)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(
        character
        for character in text
        if not unicodedata.combining(character)
    )
    text = text.lower().replace(".", "")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def player_key(name: Any, team: Any) -> str:
    return f"{normalized_name(name)}|{str(team).strip().upper()}"


def clean_player_id(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    try:
        numeric = float(value)
        if math.isfinite(numeric) and numeric.is_integer():
            return str(int(numeric))
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    return text[:-2] if text.endswith(".0") else text


def split_players(value: Any) -> list[str]:
    return [
        part.strip()
        for part in str(value).split("|")
        if part.strip()
    ]


def locate_player_market() -> Path:
    for path in PLAYER_MARKET_CANDIDATES:
        if path.exists():
            return path
    raise FileNotFoundError(
        "No supported player market file was found:\n"
        + "\n".join(str(path) for path in PLAYER_MARKET_CANDIDATES)
    )


def read_player_market(path: Path) -> pd.DataFrame:
    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path)
    return pd.read_csv(path)


def collect_app_players(
    bundle: dict[str, Any],
) -> list[dict[str, str]]:
    collected: dict[str, dict[str, str]] = {}

    recommendations = bundle.get("recommendations_by_team", {})
    if not isinstance(recommendations, dict):
        raise ValueError("recommendations_by_team must be an object.")

    for recommendation_team, rows in recommendations.items():
        for row in rows:
            counterpart_team = str(row["counterpart_team"]).strip()
            for name in split_players(row["outgoing_players"]):
                key = player_key(name, recommendation_team)
                collected[key] = {
                    "player_name": name,
                    "team_abbreviation": recommendation_team,
                }
            for name in split_players(row["incoming_players"]):
                key = player_key(name, counterpart_team)
                collected[key] = {
                    "player_name": name,
                    "team_abbreviation": counterpart_team,
                }

    return sorted(
        collected.values(),
        key=lambda row: (
            row["team_abbreviation"],
            normalized_name(row["player_name"]),
        ),
    )


def build_player_lookup(
    market: pd.DataFrame,
) -> dict[str, dict[str, Any]]:
    required = {
        "player_id",
        "player_name",
        "current_team_2026_27",
    }
    missing = sorted(required.difference(market.columns))
    if missing:
        raise ValueError(
            "Player market is missing required columns:\n"
            + "\n".join(missing)
        )

    lookup: dict[str, dict[str, Any]] = {}
    for _, row in market.iterrows():
        player_id = clean_player_id(row["player_id"])
        if not player_id:
            continue

        key = player_key(
            row["player_name"],
            row["current_team_2026_27"],
        )
        lookup[key] = {
            "player_id": player_id,
            "player_name": str(row["player_name"]).strip(),
            "team_abbreviation": str(
                row["current_team_2026_27"]
            ).strip(),
        }
    return lookup


def team_logo_url(team_id: int) -> str:
    return (
        f"https://cdn.nba.com/logos/nba/{team_id}/"
        "global/L/logo.svg"
    )


def player_headshot_url(player_id: str) -> str:
    return (
        "https://cdn.nba.com/headshots/nba/latest/"
        f"260x190/{player_id}.png"
    )


def run_self_test() -> int:
    tests = {
        "accent_normalization": (
            normalized_name("Nikola Jović") == "nikola jovic"
        ),
        "period_normalization": (
            normalized_name("P.J. Washington")
            == "pj washington"
        ),
        "player_id_cleaning": clean_player_id(1630180.0) == "1630180",
        "team_count": len(TEAM_IDS) == 30,
        "logo_url": (
            team_logo_url(1610612751)
            == "https://cdn.nba.com/logos/nba/1610612751/global/L/logo.svg"
        ),
        "headshot_url": (
            player_headshot_url("1630180")
            == "https://cdn.nba.com/headshots/nba/latest/260x190/1630180.png"
        ),
    }
    print(json.dumps(tests, indent=2))
    return 0 if all(tests.values()) else 1


def main() -> int:
    args = parse_args()
    if args.self_test:
        return run_self_test()

    APP_DATA_DIRECTORY.mkdir(parents=True, exist_ok=True)
    VALIDATION_PATH.parent.mkdir(parents=True, exist_ok=True)

    if not BUNDLE_PATH.exists():
        raise FileNotFoundError(f"App bundle not found: {BUNDLE_PATH}")

    bundle = json.loads(BUNDLE_PATH.read_text(encoding="utf-8"))
    player_market_path = locate_player_market()
    market = read_player_market(player_market_path)

    app_players = collect_app_players(bundle)
    lookup = build_player_lookup(market)

    resolved_players: dict[str, dict[str, Any]] = {}
    unresolved_players: list[dict[str, str]] = []

    for player in app_players:
        key = player_key(
            player["player_name"],
            player["team_abbreviation"],
        )
        match = lookup.get(key)
        if match is None:
            unresolved_players.append(player)
            continue

        resolved_players[key] = {
            **match,
            "headshot_url": player_headshot_url(match["player_id"]),
        }

    team_assets = {
        abbreviation: {
            "team_id": team_id,
            "logo_url": team_logo_url(team_id),
        }
        for abbreviation, team_id in TEAM_IDS.items()
    }

    output = {
        "release_name": "mixed_trade_visual_assets_2026_27_v1",
        "script_version": SCRIPT_VERSION,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "player_market_source": str(player_market_path),
        "counts": {
            "teams": len(team_assets),
            "app_players": len(app_players),
            "resolved_players": len(resolved_players),
            "unresolved_players": len(unresolved_players),
        },
        "teams": team_assets,
        "players": resolved_players,
        "unresolved_players": unresolved_players,
        "fallbacks": {
            "player_headshot": "",
            "team_logo": "",
        },
    }

    OUTPUT_PATH.write_text(
        json.dumps(output, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    validation_rows = [
        {
            "check_name": "all_30_team_logos_created",
            "passed": len(team_assets) == 30,
            "observed": len(team_assets),
            "expected": 30,
        },
        {
            "check_name": "app_players_found",
            "passed": len(app_players) > 0,
            "observed": len(app_players),
            "expected": ">0",
        },
        {
            "check_name": "all_app_players_resolved",
            "passed": len(unresolved_players) == 0,
            "observed": len(unresolved_players),
            "expected": 0,
        },
        {
            "check_name": "every_resolved_player_has_headshot_url",
            "passed": all(
                bool(row["headshot_url"])
                for row in resolved_players.values()
            ),
            "observed": sum(
                bool(row["headshot_url"])
                for row in resolved_players.values()
            ),
            "expected": len(resolved_players),
        },
    ]
    pd.DataFrame(validation_rows).to_csv(
        VALIDATION_PATH,
        index=False,
    )

    release_valid = all(
        bool(row["passed"]) for row in validation_rows
    )

    print("=" * 80)
    print("MIXED TRADE VISUAL ASSET MAP")
    print("=" * 80)
    print(f"Player market: {player_market_path}")
    print(f"Teams: {len(team_assets)}")
    print(
        f"Players resolved: {len(resolved_players)}/"
        f"{len(app_players)}"
    )
    if unresolved_players:
        print("Unresolved players:")
        for player in unresolved_players:
            print(
                "  "
                f"{player['player_name']} | "
                f"{player['team_abbreviation']}"
            )
    print(
        f"Validation: "
        f"{sum(bool(row['passed']) for row in validation_rows)}/"
        f"{len(validation_rows)}"
    )
    print(f"Release valid: {release_valid}")
    print(f"Saved: {OUTPUT_PATH}")
    return 0 if release_valid else 1


if __name__ == "__main__":
    raise SystemExit(main())