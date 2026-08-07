"""
Audit the active NBA player-rating release against the current 2KRatings snapshot.

This script:
1. Downloads current NBA 2K roster pages for all 30 teams plus Free Agency.
2. Extracts player name, team, OVR, position, and 2K archetype.
3. Loads app_data/player_ratings_2026_27_v2.json.
4. Matches the two player pools conservatively.
5. Writes player-level, tier-level, team-level, and unmatched audit outputs.

It does NOT overwrite or promote the live ratings release.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
import time
import unicodedata
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher
from io import StringIO
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd
import requests
from bs4 import BeautifulSoup


SCRIPT_VERSION = "player-ratings-current-2k-audit-v1-2026-08-06"
SOURCE_BASE = "https://www.2kratings.com"
SOURCE_INDEX = f"{SOURCE_BASE}/current-teams"
SOURCE_LABEL = "2KRatings current NBA 2K27 snapshot"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/150.0.0.0 Safari/537.36"
)

TEAM_PAGES: dict[str, str] = {
    "ATL": "atlanta-hawks",
    "BOS": "boston-celtics",
    "BKN": "brooklyn-nets",
    "CHA": "charlotte-hornets",
    "CHI": "chicago-bulls",
    "CLE": "cleveland-cavaliers",
    "DAL": "dallas-mavericks",
    "DEN": "denver-nuggets",
    "DET": "detroit-pistons",
    "GSW": "golden-state-warriors",
    "HOU": "houston-rockets",
    "IND": "indiana-pacers",
    "LAC": "los-angeles-clippers",
    "LAL": "los-angeles-lakers",
    "MEM": "memphis-grizzlies",
    "MIA": "miami-heat",
    "MIL": "milwaukee-bucks",
    "MIN": "minnesota-timberwolves",
    "NOP": "new-orleans-pelicans",
    "NYK": "new-york-knicks",
    "OKC": "oklahoma-city-thunder",
    "ORL": "orlando-magic",
    "PHI": "philadelphia-76ers",
    "PHX": "phoenix-suns",
    "POR": "portland-trail-blazers",
    "SAC": "sacramento-kings",
    "SAS": "san-antonio-spurs",
    "TOR": "toronto-raptors",
    "UTA": "utah-jazz",
    "WAS": "washington-wizards",
    "FA": "free-agency",
}

TEAM_NAME_TO_ABBR = {
    "atlanta hawks": "ATL",
    "boston celtics": "BOS",
    "brooklyn nets": "BKN",
    "charlotte hornets": "CHA",
    "chicago bulls": "CHI",
    "cleveland cavaliers": "CLE",
    "dallas mavericks": "DAL",
    "denver nuggets": "DEN",
    "detroit pistons": "DET",
    "golden state warriors": "GSW",
    "houston rockets": "HOU",
    "indiana pacers": "IND",
    "los angeles clippers": "LAC",
    "la clippers": "LAC",
    "los angeles lakers": "LAL",
    "memphis grizzlies": "MEM",
    "miami heat": "MIA",
    "milwaukee bucks": "MIL",
    "minnesota timberwolves": "MIN",
    "new orleans pelicans": "NOP",
    "new york knicks": "NYK",
    "oklahoma city thunder": "OKC",
    "orlando magic": "ORL",
    "philadelphia 76ers": "PHI",
    "phoenix suns": "PHX",
    "portland trail blazers": "POR",
    "sacramento kings": "SAC",
    "san antonio spurs": "SAS",
    "toronto raptors": "TOR",
    "utah jazz": "UTA",
    "washington wizards": "WAS",
    "free agency": "FA",
}

MODEL_FIELD_ALIASES = {
    "player_id": (
        "player_id",
        "nba_player_id",
        "person_id",
        "id",
    ),
    "player_name": (
        "player_name",
        "player_display_name",
        "full_name",
        "name",
    ),
    "team": (
        "team_abbreviation",
        "current_team_2026_27",
        "current_team",
        "team",
        "branding_team",
    ),
    "overall_rating": (
        "overall_rating",
        "overall",
        "ovr",
    ),
    "potential_rating": (
        "potential_rating",
        "potential",
        "pot",
    ),
    "future_rating": (
        "future_rating",
        "future_outlook_rating",
        "future_outlook",
        "fut",
    ),
    "contract_value_rating": (
        "contract_value_rating",
        "contract_value",
        "cv",
    ),
    "trade_value_rating": (
        "trade_value_rating",
        "trade_value",
        "tv",
    ),
    "league_rank": (
        "league_overall_rank",
        "league_rank",
        "overall_rank",
        "rank",
    ),
    "age": (
        "age",
        "player_age",
    ),
    "position": (
        "position",
        "position_group",
        "primary_position",
    ),
    "role": (
        "role_label",
        "role_archetype",
        "player_role",
        "archetype",
        "role",
    ),
}

NAME_ALIASES = {
    "pj washington": "p j washington",
    "rj barrett": "r j barrett",
    "cj mccollum": "c j mccollum",
    "tj mcconnell": "t j mcconnell",
    "aj green": "a j green",
    "gg jackson": "g g jackson",
    "cam thomas": "cameron thomas",
    "nicolas claxton": "nic claxton",
    "ron holland": "ronald holland",
    "ronald holland ii": "ronald holland",
    "gary trent": "gary trent",
    "gary trent jr": "gary trent",
    "wendell moore": "wendell moore",
    "wendell moore jr": "wendell moore",
    "jabari smith": "jabari smith",
    "jabari smith jr": "jabari smith",
    "michael porter": "michael porter",
    "michael porter jr": "michael porter",
    "kel el ware": "kelel ware",
    "kel'el ware": "kelel ware",
}


@dataclass(frozen=True)
class Match:
    model_index: int
    source_index: int
    method: str
    score: float


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--ratings-json",
        type=Path,
        default=Path("app_data/player_ratings_2026_27_v2.json"),
        help="Active player-rating JSON.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("outputs"),
        help="Directory for audit outputs.",
    )
    parser.add_argument(
        "--request-delay",
        type=float,
        default=0.65,
        help="Delay in seconds between source page requests.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="HTTP timeout in seconds.",
    )
    parser.add_argument(
        "--use-cache",
        action="store_true",
        help="Reuse cached HTML pages when available.",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Run dependency-free helper tests.",
    )
    return parser.parse_args()


def project_root() -> Path:
    script_path = Path(__file__).resolve()
    if script_path.parent.name.lower() == "src":
        return script_path.parent.parent
    return Path.cwd()


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    return " ".join(str(value).strip().split())


def normalized_team(value: Any) -> str:
    text = clean_text(value).upper()
    aliases = {
        "BRK": "BKN",
        "BRO": "BKN",
        "CHO": "CHA",
        "CHH": "CHA",
        "PHO": "PHX",
        "NOH": "NOP",
        "NOK": "NOP",
        "GS": "GSW",
        "SA": "SAS",
        "NY": "NYK",
        "FA": "FA",
        "FREE AGENT": "FA",
        "FREE AGENCY": "FA",
    }
    return aliases.get(text, text)


def normalize_name(value: Any) -> str:
    text = unicodedata.normalize("NFKD", clean_text(value))
    text = "".join(
        char for char in text if not unicodedata.combining(char)
    )
    text = text.casefold()
    text = text.replace("&", " and ")
    text = re.sub(r"['’`.-]", " ", text)
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    tokens = [
        token
        for token in text.split()
        if token not in {"jr", "sr", "ii", "iii", "iv", "v"}
    ]
    normalized = " ".join(tokens)
    normalized = NAME_ALIASES.get(normalized, normalized)
    return " ".join(normalized.split())


def safe_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def safe_int(value: Any) -> int | None:
    number = safe_float(value)
    if number is None:
        return None
    return int(round(number))


def first_value(record: dict[str, Any], aliases: Iterable[str]) -> Any:
    for alias in aliases:
        if alias in record:
            value = record.get(alias)
            if value is not None and clean_text(value) != "":
                return value
    return None


def extract_json_records(
    payload: Any,
) -> list[dict[str, Any]]:
    """Recursively locate player records in any supported app payload."""

    name_aliases = set(
        MODEL_FIELD_ALIASES["player_name"]
    )
    overall_aliases = set(
        MODEL_FIELD_ALIASES["overall_rating"]
    )
    player_id_aliases = set(
        MODEL_FIELD_ALIASES["player_id"]
    )

    def is_player_record(
        value: Any,
    ) -> bool:
        if not isinstance(value, dict):
            return False

        keys = set(value)

        has_name = bool(keys.intersection(name_aliases))
        has_overall = bool(
            keys.intersection(overall_aliases)
        )
        has_player_id = bool(
            keys.intersection(player_id_aliases)
        )

        return (
            has_name
            and has_overall
            and (
                has_player_id
                or len(value) >= 8
            )
        )

    discovered: list[dict[str, Any]] = []

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            if is_player_record(value):
                discovered.append(dict(value))
                return

            for nested_value in value.values():
                walk(nested_value)

        elif isinstance(value, list):
            for nested_value in value:
                walk(nested_value)

    walk(payload)

    if not discovered:
        top_level_description = (
            sorted(payload.keys())
            if isinstance(payload, dict)
            else type(payload).__name__
        )

        raise ValueError(
            "Could not locate player records anywhere inside "
            "the rating JSON. Top-level structure: "
            f"{top_level_description}"
        )

    deduplicated: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()

    for record in discovered:
        player_id = clean_text(
            first_value(
                record,
                MODEL_FIELD_ALIASES["player_id"],
            )
        )
        player_name = normalize_name(
            first_value(
                record,
                MODEL_FIELD_ALIASES["player_name"],
            )
        )
        team = normalized_team(
            first_value(
                record,
                MODEL_FIELD_ALIASES["team"],
            )
        )

        identity = (
            player_id,
            player_name,
            team,
        )

        if identity in seen:
            continue

        seen.add(identity)
        deduplicated.append(record)

    return deduplicated



def load_model_ratings(path: Path) -> pd.DataFrame:
    if not path.is_file():
        raise FileNotFoundError(f"Rating JSON not found: {path}")

    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    records = extract_json_records(payload)

    rows: list[dict[str, Any]] = []
    for record in records:
        player_id = clean_text(
            first_value(record, MODEL_FIELD_ALIASES["player_id"])
        )
        player_name = clean_text(
            first_value(record, MODEL_FIELD_ALIASES["player_name"])
        )
        team = normalized_team(
            first_value(record, MODEL_FIELD_ALIASES["team"])
        )

        if not player_name:
            continue

        rows.append(
            {
                "player_id": player_id,
                "model_player_name": player_name,
                "model_name_key": normalize_name(player_name),
                "model_team": team,
                "model_overall": safe_float(
                    first_value(
                        record,
                        MODEL_FIELD_ALIASES["overall_rating"],
                    )
                ),
                "model_potential": safe_float(
                    first_value(
                        record,
                        MODEL_FIELD_ALIASES["potential_rating"],
                    )
                ),
                "model_future": safe_float(
                    first_value(
                        record,
                        MODEL_FIELD_ALIASES["future_rating"],
                    )
                ),
                "model_contract_value": safe_float(
                    first_value(
                        record,
                        MODEL_FIELD_ALIASES["contract_value_rating"],
                    )
                ),
                "model_trade_value": safe_float(
                    first_value(
                        record,
                        MODEL_FIELD_ALIASES["trade_value_rating"],
                    )
                ),
                "model_league_rank": safe_int(
                    first_value(
                        record,
                        MODEL_FIELD_ALIASES["league_rank"],
                    )
                ),
                "model_age": safe_float(
                    first_value(record, MODEL_FIELD_ALIASES["age"])
                ),
                "model_position": clean_text(
                    first_value(
                        record,
                        MODEL_FIELD_ALIASES["position"],
                    )
                ),
                "model_role": clean_text(
                    first_value(record, MODEL_FIELD_ALIASES["role"])
                ),
            }
        )

    frame = pd.DataFrame(rows)
    if frame.empty:
        raise RuntimeError("No player rows were loaded from the rating JSON.")

    frame["model_overall"] = pd.to_numeric(
        frame["model_overall"], errors="coerce"
    )
    frame["model_league_rank"] = (
        frame["model_overall"]
        .rank(method="min", ascending=False)
        .astype("Int64")
        .where(frame["model_league_rank"].isna(), frame["model_league_rank"])
    )

    return frame.reset_index(drop=True)


def fetch_html(
    session: requests.Session,
    url: str,
    cache_path: Path,
    timeout: float,
    use_cache: bool,
) -> str:
    if use_cache and cache_path.is_file():
        return cache_path.read_text(encoding="utf-8", errors="replace")

    response = session.get(url, timeout=timeout)
    response.raise_for_status()
    html = response.text

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(html, encoding="utf-8")
    return html


def choose_player_anchor(cell: Any) -> Any | None:
    candidates = []
    for anchor in cell.find_all("a", href=True):
        text = clean_text(anchor.get_text(" ", strip=True))
        href = clean_text(anchor.get("href"))
        if not text:
            continue
        if href.startswith("/teams/"):
            continue
        if "compare" in href:
            continue
        candidates.append((len(text), anchor))

    if not candidates:
        return None
    return max(candidates, key=lambda item: item[0])[1]


def parse_position_and_archetype(
    cell: Any,
    player_name: str,
) -> tuple[str, str]:
    strings = [
        clean_text(value)
        for value in cell.stripped_strings
        if clean_text(value)
    ]

    filtered = []
    for value in strings:
        if normalize_name(value) == normalize_name(player_name):
            continue
        if value.lower() in {"badges", "nba all-star", "hall of fame"}:
            continue
        if re.fullmatch(r"\d+", value):
            continue
        filtered.append(value)

    position = ""
    archetype = ""

    position_pattern = re.compile(
        r"^(PG|SG|SF|PF|C)(\s*/\s*(PG|SG|SF|PF|C))?$",
        flags=re.IGNORECASE,
    )
    height_pattern = re.compile(r"^\d+'\d+\"$")

    for value in filtered:
        if position_pattern.match(value):
            position = value.upper().replace(" ", "")
            break

    for value in reversed(filtered):
        if position_pattern.match(value):
            continue
        if height_pattern.match(value):
            continue
        if re.fullmatch(r"\d{1,3}", value):
            continue
        if len(value) < 3:
            continue
        archetype = value
        break

    return position, archetype


def parse_current_roster_table(
    html: str,
    team_abbr: str,
    source_url: str,
) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    roster_table = None
    player_index = None
    ovr_index = None

    for table in soup.find_all("table"):
        headers = [
            clean_text(header.get_text(" ", strip=True))
            for header in table.find_all("th")
        ]
        upper = [header.upper() for header in headers]

        if "PLAYER" in upper and "OVR" in upper:
            roster_table = table
            player_index = upper.index("PLAYER")
            ovr_index = upper.index("OVR")
            break

    if roster_table is None or player_index is None or ovr_index is None:
        raise RuntimeError(
            f"Could not locate the current roster table for {team_abbr}: "
            f"{source_url}"
        )

    rows: list[dict[str, Any]] = []

    for row in roster_table.find_all("tr"):
        cells = row.find_all(["td", "th"])
        required_index = max(player_index, ovr_index)
        if len(cells) <= required_index:
            continue

        player_cell = cells[player_index]
        overall_text = clean_text(cells[ovr_index].get_text(" ", strip=True))
        overall_match = re.search(r"\b(\d{2})\b", overall_text)

        anchor = choose_player_anchor(player_cell)
        if anchor is not None:
            player_name = clean_text(anchor.get_text(" ", strip=True))
            player_url = anchor.get("href", "")
            if player_url.startswith("/"):
                player_url = SOURCE_BASE + player_url
        else:
            player_name = ""
            player_url = ""

        if not player_name:
            raw_parts = [
                clean_text(value)
                for value in player_cell.stripped_strings
                if clean_text(value)
            ]
            raw_parts = [
                value
                for value in raw_parts
                if not re.fullmatch(r"\d+", value)
            ]
            if raw_parts:
                player_name = raw_parts[0]

        if not player_name:
            continue

        position, archetype = parse_position_and_archetype(
            player_cell,
            player_name,
        )

        rows.append(
            {
                "source_player_name": player_name,
                "source_name_key": normalize_name(player_name),
                "source_team": team_abbr,
                "source_overall": (
                    int(overall_match.group(1))
                    if overall_match
                    else np.nan
                ),
                "source_position": position,
                "source_archetype": archetype,
                "source_player_url": player_url,
                "source_team_url": source_url,
                "source_overall_released": bool(overall_match),
            }
        )

    if not rows:
        raise RuntimeError(
            f"No roster rows were extracted for {team_abbr}: {source_url}"
        )

    return rows


def scrape_current_2k(
    cache_dir: Path,
    request_delay: float,
    timeout: float,
    use_cache: bool,
) -> pd.DataFrame:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": SOURCE_INDEX,
        }
    )

    all_rows: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []

    for position, (team, slug) in enumerate(TEAM_PAGES.items(), start=1):
        url = f"{SOURCE_BASE}/teams/{slug}"
        cache_path = cache_dir / f"{team.lower()}_{slug}.html"

        try:
            html = fetch_html(
                session=session,
                url=url,
                cache_path=cache_path,
                timeout=timeout,
                use_cache=use_cache,
            )
            rows = parse_current_roster_table(html, team, url)
            all_rows.extend(rows)
            print(
                f"[{position:02d}/{len(TEAM_PAGES)}] "
                f"{team}: {len(rows)} rows"
            )
        except Exception as error:
            failures.append(
                {
                    "team": team,
                    "url": url,
                    "error": f"{type(error).__name__}: {error}",
                }
            )
            print(
                f"[{position:02d}/{len(TEAM_PAGES)}] "
                f"{team}: FAILED - {error}",
                file=sys.stderr,
            )

        if position < len(TEAM_PAGES):
            time.sleep(max(request_delay, 0.0))

    if not all_rows:
        raise RuntimeError(
            "No 2K roster rows were collected. "
            "Check the internet connection and source availability."
        )

    frame = pd.DataFrame(all_rows)
    frame = frame.drop_duplicates(
        subset=["source_name_key", "source_team"],
        keep="first",
    ).reset_index(drop=True)

    if failures:
        failure_path = cache_dir.parent / (
            "current_2k_ratings_scrape_failures_v1.csv"
        )
        pd.DataFrame(failures).to_csv(failure_path, index=False)
        print(f"Scrape failures written to: {failure_path}")

    return frame


def similarity(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    return 100.0 * SequenceMatcher(None, left, right).ratio()


def candidate_match(
    model_row: pd.Series,
    source: pd.DataFrame,
    available_source: set[int],
) -> tuple[int | None, str, float]:
    name_key = clean_text(model_row["model_name_key"])
    team = normalized_team(model_row["model_team"])

    candidates = source.loc[
        source.index.isin(available_source)
    ].copy()

    if candidates.empty:
        return None, "unmatched", 0.0

    exact = candidates.loc[
        candidates["source_name_key"].eq(name_key)
    ].copy()

    if not exact.empty:
        same_team = exact.loc[exact["source_team"].eq(team)]
        if len(same_team) == 1:
            return int(same_team.index[0]), "exact_name_team", 100.0
        if len(exact) == 1:
            return int(exact.index[0]), "exact_name", 100.0

    same_team = candidates.loc[
        candidates["source_team"].eq(team)
    ].copy()

    if not same_team.empty:
        same_team["__score"] = same_team["source_name_key"].map(
            lambda value: similarity(name_key, value)
        )
        same_team = same_team.sort_values("__score", ascending=False)
        best = same_team.iloc[0]
        second_score = (
            float(same_team.iloc[1]["__score"])
            if len(same_team) > 1
            else 0.0
        )
        best_score = float(best["__score"])

        if best_score >= 88.0 and best_score - second_score >= 4.0:
            return int(best.name), "fuzzy_name_team", best_score

    candidates["__score"] = candidates["source_name_key"].map(
        lambda value: similarity(name_key, value)
    )
    candidates = candidates.sort_values("__score", ascending=False)
    best = candidates.iloc[0]
    second_score = (
        float(candidates.iloc[1]["__score"])
        if len(candidates) > 1
        else 0.0
    )
    best_score = float(best["__score"])

    if best_score >= 95.0 and best_score - second_score >= 4.0:
        return int(best.name), "fuzzy_name_global", best_score

    return None, "unmatched", best_score


def match_players(
    model: pd.DataFrame,
    source: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    matches: list[Match] = []
    available_source = set(source.index.astype(int).tolist())

    model_order = model.assign(
        __has_team=model["model_team"].ne("").astype(int),
        __has_ovr=model["model_overall"].notna().astype(int),
    ).sort_values(
        ["__has_team", "__has_ovr", "model_overall"],
        ascending=[False, False, False],
    )

    for model_index, model_row in model_order.iterrows():
        source_index, method, score = candidate_match(
            model_row,
            source,
            available_source,
        )

        if source_index is None:
            continue

        matches.append(
            Match(
                model_index=int(model_index),
                source_index=int(source_index),
                method=method,
                score=score,
            )
        )
        available_source.discard(int(source_index))

    match_frame = pd.DataFrame(
        [
            {
                "model_index": match.model_index,
                "source_index": match.source_index,
                "match_method": match.method,
                "match_score": round(match.score, 2),
            }
            for match in matches
        ]
    )

    if match_frame.empty:
        raise RuntimeError("No players matched between the two sources.")

    audit = (
        match_frame
        .merge(
            model.reset_index(names="model_index"),
            on="model_index",
            how="left",
            validate="one_to_one",
        )
        .merge(
            source.reset_index(names="source_index"),
            on="source_index",
            how="left",
            validate="one_to_one",
        )
    )

    audit["overall_difference"] = (
        audit["model_overall"] - audit["source_overall"]
    )
    audit["absolute_difference"] = audit["overall_difference"].abs()
    audit["model_rank_recomputed"] = (
        audit["model_overall"]
        .rank(method="min", ascending=False)
        .astype("Int64")
    )
    audit["source_rank"] = (
        audit["source_overall"]
        .rank(method="min", ascending=False)
        .astype("Int64")
    )
    audit["rank_difference"] = (
        audit["model_rank_recomputed"] - audit["source_rank"]
    )

    matched_model = set(match_frame["model_index"].astype(int))
    matched_source = set(match_frame["source_index"].astype(int))

    unmatched_model = model.loc[
        ~model.index.isin(matched_model)
    ].copy()
    unmatched_source = source.loc[
        ~source.index.isin(matched_source)
    ].copy()

    return (
        audit.sort_values(
            ["absolute_difference", "model_overall"],
            ascending=[False, False],
        ).reset_index(drop=True),
        unmatched_model.reset_index(drop=True),
        unmatched_source.reset_index(drop=True),
    )


def rank_bucket(rank: Any) -> str:
    value = safe_int(rank)
    if value is None:
        return "Unranked"
    if value <= 10:
        return "001-010"
    if value <= 25:
        return "011-025"
    if value <= 50:
        return "026-050"
    if value <= 100:
        return "051-100"
    if value <= 150:
        return "101-150"
    if value <= 250:
        return "151-250"
    if value <= 400:
        return "251-400"
    return "401+"


def difference_band(value: Any) -> str:
    number = safe_float(value)
    if number is None:
        return "missing"
    if number >= 8:
        return "+8 or more"
    if number >= 5:
        return "+5 to +7.9"
    if number >= 2:
        return "+2 to +4.9"
    if number > -2:
        return "within 2"
    if number > -5:
        return "-2 to -4.9"
    if number > -8:
        return "-5 to -7.9"
    return "-8 or less"


def summarize_groups(
    audit: pd.DataFrame,
    group_column: str,
) -> pd.DataFrame:
    valid = audit.loc[
        audit["model_overall"].notna()
        & audit["source_overall"].notna()
    ].copy()

    if valid.empty:
        return pd.DataFrame()

    grouped = (
        valid.groupby(group_column, dropna=False)
        .agg(
            players=("player_id", "count"),
            model_mean=("model_overall", "mean"),
            source_mean=("source_overall", "mean"),
            mean_difference=("overall_difference", "mean"),
            median_difference=("overall_difference", "median"),
            mae=("absolute_difference", "mean"),
            model_median=("model_overall", "median"),
            source_median=("source_overall", "median"),
        )
        .reset_index()
    )

    numeric_columns = [
        column
        for column in grouped.columns
        if column not in {group_column, "players"}
    ]
    grouped[numeric_columns] = grouped[numeric_columns].round(2)
    return grouped


def quantile_anchor_table(
    audit: pd.DataFrame,
) -> pd.DataFrame:
    valid = audit.loc[
        audit["model_overall"].notna()
        & audit["source_overall"].notna()
    ].copy()

    if valid.empty:
        return pd.DataFrame()

    quantiles = [
        0.00,
        0.05,
        0.10,
        0.20,
        0.30,
        0.40,
        0.50,
        0.60,
        0.70,
        0.80,
        0.90,
        0.95,
        0.98,
        1.00,
    ]

    rows = []
    for quantile in quantiles:
        rows.append(
            {
                "quantile": quantile,
                "model_overall": round(
                    float(valid["model_overall"].quantile(quantile)),
                    2,
                ),
                "source_2k_overall": round(
                    float(valid["source_overall"].quantile(quantile)),
                    2,
                ),
            }
        )

    return pd.DataFrame(rows)


def build_summary(
    model: pd.DataFrame,
    source: pd.DataFrame,
    audit: pd.DataFrame,
    unmatched_model: pd.DataFrame,
    unmatched_source: pd.DataFrame,
) -> dict[str, Any]:
    valid = audit.loc[
        audit["model_overall"].notna()
        & audit["source_overall"].notna()
    ].copy()

    if valid.empty:
        raise RuntimeError("No matched rows have both overall ratings.")

    correlation = valid[["model_overall", "source_overall"]].corr().iloc[0, 1]

    return {
        "script_version": SCRIPT_VERSION,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "source": {
            "label": SOURCE_LABEL,
            "index_url": SOURCE_INDEX,
            "independent_fan_site": True,
            "snapshot_game_label": "NBA 2K27",
        },
        "counts": {
            "model_players": int(len(model)),
            "source_players_total": int(len(source)),
            "source_players_with_released_overall": int(
                source["source_overall"].notna().sum()
            ),
            "matched_players": int(len(audit)),
            "matched_with_both_overalls": int(len(valid)),
            "unmatched_model_players": int(len(unmatched_model)),
            "unmatched_source_players": int(len(unmatched_source)),
        },
        "overall_comparison": {
            "model_mean": round(float(valid["model_overall"].mean()), 3),
            "source_mean": round(float(valid["source_overall"].mean()), 3),
            "model_median": round(float(valid["model_overall"].median()), 3),
            "source_median": round(float(valid["source_overall"].median()), 3),
            "mean_difference_model_minus_2k": round(
                float(valid["overall_difference"].mean()),
                3,
            ),
            "median_difference_model_minus_2k": round(
                float(valid["overall_difference"].median()),
                3,
            ),
            "mean_absolute_error": round(
                float(valid["absolute_difference"].mean()),
                3,
            ),
            "root_mean_squared_error": round(
                float(
                    np.sqrt(
                        np.mean(
                            np.square(valid["overall_difference"])
                        )
                    )
                ),
                3,
            ),
            "pearson_correlation": round(float(correlation), 4),
            "model_90_plus": int((valid["model_overall"] >= 90).sum()),
            "source_90_plus": int((valid["source_overall"] >= 90).sum()),
            "model_85_plus": int((valid["model_overall"] >= 85).sum()),
            "source_85_plus": int((valid["source_overall"] >= 85).sum()),
            "model_80_plus": int((valid["model_overall"] >= 80).sum()),
            "source_80_plus": int((valid["source_overall"] >= 80).sum()),
        },
        "difference_bands": {
            str(key): int(value)
            for key, value in (
                valid["overall_difference"]
                .map(difference_band)
                .value_counts()
                .to_dict()
                .items()
            )
        },
        "match_methods": {
            str(key): int(value)
            for key, value in audit["match_method"].value_counts().to_dict().items()
        },
    }


def run_self_test() -> None:
    checks = {
        "accent_normalization": (
            normalize_name("Nikola Jokić") == "nikola jokic"
        ),
        "suffix_normalization": (
            normalize_name("Michael Porter Jr.") == "michael porter"
        ),
        "apostrophe_normalization": (
            normalize_name("Kel'el Ware") == "kelel ware"
        ),
        "team_normalization": normalized_team("PHO") == "PHX",
        "difference_band_positive": difference_band(5.3) == "+5 to +7.9",
        "rank_bucket_122": rank_bucket(122) == "101-150",
    }

    print(json.dumps({"checks": checks}, indent=2))
    if not all(checks.values()):
        raise AssertionError("One or more helper self-tests failed.")


def main() -> int:
    args = parse_args()
    if args.self_test:
        run_self_test()
        return 0

    root = project_root()
    ratings_path = (
        args.ratings_json
        if args.ratings_json.is_absolute()
        else root / args.ratings_json
    )
    output_dir = (
        args.output_dir
        if args.output_dir.is_absolute()
        else root / args.output_dir
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    cache_dir = output_dir / "current_2k_html_cache_v1"

    print("=" * 88)
    print("CURRENT 2K PLAYER-RATINGS AUDIT")
    print("=" * 88)
    print("Project root:", root)
    print("Ratings JSON:", ratings_path)
    print("Source index:", SOURCE_INDEX)

    model = load_model_ratings(ratings_path)
    print("Model players loaded:", len(model))

    source = scrape_current_2k(
        cache_dir=cache_dir,
        request_delay=args.request_delay,
        timeout=args.timeout,
        use_cache=args.use_cache,
    )
    print("2K rows collected:", len(source))
    print(
        "2K released OVR rows:",
        int(source["source_overall"].notna().sum()),
    )

    audit, unmatched_model, unmatched_source = match_players(model, source)

    audit["model_rank_bucket"] = audit["model_league_rank"].map(rank_bucket)
    audit["source_rank_bucket"] = audit["source_rank"].map(rank_bucket)
    audit["difference_band"] = audit["overall_difference"].map(difference_band)
    audit["team_match"] = (
        audit["model_team"].eq(audit["source_team"])
        | audit["model_team"].eq("")
        | audit["source_team"].eq("FA")
        | audit["model_team"].eq("FA")
    )

    tier_summary = summarize_groups(audit, "model_rank_bucket")
    team_summary = summarize_groups(audit, "model_team")
    difference_summary = summarize_groups(audit, "difference_band")
    quantile_anchors = quantile_anchor_table(audit)
    summary = build_summary(
        model=model,
        source=source,
        audit=audit,
        unmatched_model=unmatched_model,
        unmatched_source=unmatched_source,
    )

    source_path = output_dir / "current_2k_ratings_snapshot_v1.csv"
    audit_path = output_dir / "player_ratings_vs_current_2k_audit_v1.csv"
    unmatched_model_path = (
        output_dir / "player_ratings_vs_current_2k_unmatched_model_v1.csv"
    )
    unmatched_source_path = (
        output_dir / "player_ratings_vs_current_2k_unmatched_source_v1.csv"
    )
    tier_path = output_dir / "player_ratings_vs_current_2k_tier_summary_v1.csv"
    team_path = output_dir / "player_ratings_vs_current_2k_team_summary_v1.csv"
    difference_path = (
        output_dir / "player_ratings_vs_current_2k_difference_summary_v1.csv"
    )
    quantile_path = (
        output_dir / "player_ratings_vs_current_2k_quantile_anchors_v1.csv"
    )
    summary_path = output_dir / "player_ratings_vs_current_2k_summary_v1.json"

    source.to_csv(source_path, index=False)
    audit.to_csv(audit_path, index=False)
    unmatched_model.to_csv(unmatched_model_path, index=False)
    unmatched_source.to_csv(unmatched_source_path, index=False)
    tier_summary.to_csv(tier_path, index=False)
    team_summary.to_csv(team_path, index=False)
    difference_summary.to_csv(difference_path, index=False)
    quantile_anchors.to_csv(quantile_path, index=False)
    summary_path.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    top_overrated = (
        audit.loc[audit["overall_difference"].notna()]
        .nlargest(20, "overall_difference")
        [
            [
                "model_player_name",
                "model_team",
                "model_overall",
                "source_overall",
                "overall_difference",
                "model_league_rank",
                "source_rank",
                "match_method",
            ]
        ]
    )

    top_underrated = (
        audit.loc[audit["overall_difference"].notna()]
        .nsmallest(20, "overall_difference")
        [
            [
                "model_player_name",
                "model_team",
                "model_overall",
                "source_overall",
                "overall_difference",
                "model_league_rank",
                "source_rank",
                "match_method",
            ]
        ]
    )

    print("\n" + "=" * 88)
    print("AUDIT COMPLETE")
    print("=" * 88)
    print(json.dumps(summary["counts"], indent=2))
    print(json.dumps(summary["overall_comparison"], indent=2))

    print("\nTOP 20 MODEL OVERRATINGS")
    print(top_overrated.to_string(index=False))

    print("\nTOP 20 MODEL UNDERRATINGS")
    print(top_underrated.to_string(index=False))

    print("\nOutputs:")
    for path in (
        source_path,
        audit_path,
        unmatched_model_path,
        unmatched_source_path,
        tier_path,
        team_path,
        difference_path,
        quantile_path,
        summary_path,
    ):
        print(" ", path)

    print(
        "\nNo live rating file was modified. "
        "Review the audit before recalibrating."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())