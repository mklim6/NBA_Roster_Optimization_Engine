from __future__ import annotations

import copy
import hashlib
import math
import random
import re
import time
from dataclasses import asdict
from typing import Any, Iterable

from franchise_draft_forfeitures_v1 import (
    expected_draft_pick_count,
    is_forfeited_source_asset,
)

DRAFT_ENGINE_VERSION = (
    "franchise-draft-engine-v1.1-2026-08-11+pick-forfeitures-v1-2026-09-07"
)
DRAFT_STATE_ATTR = "franchise_draft_state_v1"
DRAFT_DEPTH_CHART_VERSION = "unique-primary-position-v1-2026-08-11"
DRAFT_HISTORY_ATTR = "franchise_draft_history_v1"
DRAFT_LIFECYCLE_VERSION = "franchise-draft-lifecycle-v1.1.8-2026-08-10"
AI_PICK_CLOCK_SECONDS = 120
DRAFT_CLASS_SIZE = 80
AI_DRAFT_SCOUTING_CACHE_VERSION = "team-prospect-local-cache-v1-2026-09-29"

# The 3-2-1 lottery is the NBA rule for the 2027, 2028 and 2029 drafts.
LOTTERY_RULE_VERSION = "nba-3-2-1-lottery-2027-2029"

FIRST_NAMES = (
    "Aiden", "Andre", "Bryce", "Caleb", "Cameron", "Carter", "Darius",
    "Devin", "Eli", "Evan", "Isaiah", "Jalen", "Jamal", "Jayden", "Jordan",
    "Julian", "Kai", "Kendall", "Khalil", "Landon", "Malachi", "Marcus",
    "Mason", "Micah", "Miles", "Noah", "Owen", "Quentin", "Rafael", "Ryan",
    "Tariq", "Theo", "Tre", "Tristan", "Ty", "Xavier", "Zachary", "Zion",
    "Mateo", "Niko", "Luka", "Milan", "Emil", "Tomas", "Sasha", "Dante",
    "Keon", "Amari", "Cam", "Kobe", "Jaylen", "Terrence", "Malik", "Derrick",
)
LAST_NAMES = (
    "Anderson", "Bailey", "Banks", "Barrett", "Bennett", "Brooks", "Bryant",
    "Caldwell", "Carter", "Cole", "Collins", "Cooper", "Daniels", "Davis",
    "Edwards", "Ellis", "Evans", "Foster", "Franklin", "Gibson", "Grant",
    "Green", "Hall", "Harris", "Hayes", "Henderson", "Howard", "Jackson",
    "James", "Jefferson", "Johnson", "Jones", "King", "Lewis", "Marshall",
    "Martin", "Miller", "Mitchell", "Morgan", "Morris", "Nelson", "Owens",
    "Parker", "Powell", "Price", "Reed", "Richardson", "Robinson", "Scott",
    "Shaw", "Stewart", "Taylor", "Thomas", "Thompson", "Turner", "Walker",
    "Washington", "Watson", "Williams", "Wilson", "Wright", "Young", "Mercer",
    "Okafor", "Petrovic", "Jovanovic", "Kovacs", "Moreau", "Silva", "Santos",
)
SCHOOLS = (
    "Duke", "Kentucky", "UConn", "Kansas", "North Carolina", "Michigan State",
    "Michigan", "Illinois", "Gonzaga", "Arizona", "Baylor", "Houston", "Texas",
    "Arkansas", "Auburn", "Alabama", "Tennessee", "UCLA", "USC", "Villanova",
    "Indiana", "Purdue", "Creighton", "Iowa State", "Florida", "Ohio State",
    "Virginia", "Marquette", "Memphis", "Louisville", "BYU", "Oregon",
    "France", "Spain", "Serbia", "Australia", "Lithuania", "Germany", "Canada",
)
POSITIONS = ("PG", "SG", "SF", "PF", "C")

ARCHETYPES = {
    "PG": (
        "Lead Creator", "Pick-and-Roll Maestro", "Scoring Guard", "Two-Way Guard",
    ),
    "SG": (
        "Shot-Making Wing", "3-and-D Guard", "Slashing Scorer", "Secondary Creator",
    ),
    "SF": (
        "Two-Way Wing", "Point Forward", "Athletic Slasher", "Movement Shooter",
    ),
    "PF": (
        "Modern Forward", "Stretch Four", "Defensive Forward", "Interior Scorer",
    ),
    "C": (
        "Rim Protector", "Stretch Five", "Interior Anchor", "Playmaking Big",
    ),
}

POSITION_BASELINES = {
    "PG": dict(points=17.0, rebounds=4.0, assists=7.2, steals=1.3, blocks=0.3, turnovers=2.7, fouls=2.3, three_attempts=6.2, free_throw_attempts=4.0),
    "SG": dict(points=18.0, rebounds=4.5, assists=4.0, steals=1.2, blocks=0.4, turnovers=2.1, fouls=2.4, three_attempts=6.8, free_throw_attempts=4.2),
    "SF": dict(points=17.0, rebounds=6.0, assists=3.7, steals=1.2, blocks=0.7, turnovers=2.0, fouls=2.5, three_attempts=5.4, free_throw_attempts=4.1),
    "PF": dict(points=16.0, rebounds=8.0, assists=3.0, steals=1.0, blocks=1.1, turnovers=2.0, fouls=2.8, three_attempts=4.0, free_throw_attempts=4.5),
    "C": dict(points=15.0, rebounds=10.0, assists=2.8, steals=0.8, blocks=1.8, turnovers=2.1, fouls=3.0, three_attempts=1.7, free_throw_attempts=4.7),
}


def clean_text(value: Any) -> str:
    return str(value or "").strip()


def clean_team(value: Any) -> str:
    return clean_text(value).upper()


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, float(value)))


def enum_value(value: Any) -> str:
    return clean_text(getattr(value, "value", value)).lower()


def season_end_year(season_label: str) -> int:
    match = re.fullmatch(r"\s*(\d{4})-(\d{2}|\d{4})\s*", clean_text(season_label))
    if match is None:
        raise ValueError(f"Unrecognized season label: {season_label}")
    start = int(match.group(1))
    suffix = match.group(2)
    if len(suffix) == 4:
        return int(suffix)
    century = (start // 100) * 100
    end = century + int(suffix)
    if end < start:
        end += 100
    return end


def next_season_label(season_label: str) -> str:
    end = season_end_year(season_label)
    return f"{end}-{str(end + 1)[-2:]}"


def draft_year_for_state(state: Any) -> int:
    return season_end_year(state.settings.season_label)


def draft_state(state: Any) -> dict[str, Any] | None:
    value = getattr(
        state,
        DRAFT_STATE_ATTR,
        None,
    )
    if not isinstance(value, dict):
        return None

    # A completed Draft belongs to the season it opened. Once that
    # target season is live AND the source season is safely archived,
    # the completed Draft becomes historical rather than the active
    # Draft for the next offseason.
    try:
        required_year = draft_year_for_state(state)
        stored_year = int(
            value.get(
                "draft_year",
                -1,
            )
        )
    except (TypeError, ValueError, AttributeError):
        return value

    live_season = str(
        getattr(
            getattr(
                state,
                "settings",
                None,
            ),
            "season_label",
            "",
        )
        or ""
    ).strip()
    source_season = str(
        value.get(
            "source_season",
            "",
        )
        or ""
    ).strip()
    target_season = str(
        value.get(
            "target_season",
            "",
        )
        or ""
    ).strip()
    phase = str(
        value.get(
            "phase",
            "",
        )
        or ""
    ).strip()

    archived_labels = {
        str(
            getattr(
                archive,
                "season_label",
                "",
            )
            or ""
        ).strip()
        for archive in getattr(
            state,
            "season_history",
            [],
        )
    }

    consumed = bool(
        phase == "draft_complete"
        and stored_year != required_year
        and target_season
        and target_season == live_season
        and source_season
        and source_season in archived_labels
    )

    if consumed:
        return None

    return value


def draft_history(state: Any) -> list[dict[str, Any]]:
    value = getattr(state, DRAFT_HISTORY_ATTR, None)
    if not isinstance(value, list):
        value = []
        setattr(state, DRAFT_HISTORY_ATTR, value)
    return value


def postseason_is_complete(state: Any) -> bool:
    postseason = getattr(state, "postseason_state", None)
    return bool(
        postseason is not None
        and enum_value(getattr(postseason, "stage", "")) == "complete"
        and clean_team(getattr(postseason, "champion", ""))
    )


def draft_is_complete(state: Any) -> bool:
    current = draft_state(state)
    return bool(
        current
        and int(current.get("draft_year", -1)) == draft_year_for_state(state)
        and current.get("phase") == "draft_complete"
    )


def draft_is_required(state: Any) -> bool:
    return postseason_is_complete(state) and not draft_is_complete(state)


def _standing_record(state: Any, team: str) -> tuple[int, int, int]:
    standing = state.standings[team]
    wins = int(getattr(standing, "wins", 0) or 0)
    losses = int(getattr(standing, "losses", 0) or 0)
    point_diff = int(
        (getattr(standing, "points_for", 0) or 0)
        - (getattr(standing, "points_against", 0) or 0)
    )
    return wins, losses, point_diff


def reverse_record_order(state: Any, teams: Iterable[str]) -> list[str]:
    return sorted(
        {clean_team(team) for team in teams if clean_team(team)},
        key=lambda team: (
            _standing_record(state, team)[0],
            _standing_record(state, team)[2],
            team,
        ),
    )


def _play_in_78_loser(postseason: Any, conference: str) -> str:
    for game in getattr(postseason, "games", {}).values():
        if (
            clean_text(getattr(game, "conference", "")).lower()
            == conference.lower()
            and clean_text(getattr(game, "round_label", "")) == "Play-In 7 vs 8"
            and enum_value(getattr(game, "status", "")) == "completed"
        ):
            return clean_team(getattr(game, "loser", ""))
    return ""


def lottery_participants_321(state: Any) -> list[dict[str, Any]]:
    """Return the 16-team 3-2-1 lottery field for 2027-2029 drafts."""
    if not postseason_is_complete(state):
        raise ValueError("The draft lottery requires a completed postseason.")

    postseason = state.postseason_state
    entries: dict[str, dict[str, Any]] = {}
    non_play_in: list[str] = []

    for conference in ("East", "West"):
        seeds = list(getattr(postseason, "seed_order", {}).get(conference, ()))
        if len(seeds) < 15:
            raise ValueError(f"{conference} postseason seed order is incomplete.")

        # Seeds 11-15 miss both the Playoffs and Play-In.
        for team in seeds[10:15]:
            team = clean_team(team)
            non_play_in.append(team)
            entries[team] = {
                "team": team,
                "category": "missed_play_in",
                "balls": 3,
                "conference": conference,
                "seed": int(getattr(postseason, "seed_by_team", {}).get(team, 0) or 0),
            }

        # No. 9 and No. 10 Play-In seeds receive two balls.
        for team in seeds[8:10]:
            team = clean_team(team)
            entries[team] = {
                "team": team,
                "category": "play_in_9_10",
                "balls": 2,
                "conference": conference,
                "seed": int(getattr(postseason, "seed_by_team", {}).get(team, 0) or 0),
            }

        # Loser of the 7-v-8 opening game receives one ball.
        loser = _play_in_78_loser(postseason, conference)
        if loser:
            entries[loser] = {
                "team": loser,
                "category": "play_in_7_8_loser",
                "balls": 1,
                "conference": conference,
                "seed": int(getattr(postseason, "seed_by_team", {}).get(loser, 0) or 0),
            }

    if len(non_play_in) != 10:
        raise ValueError(f"Expected 10 teams outside the Play-In, found {len(non_play_in)}.")

    # The three worst records are draft-relegated from three balls to two.
    bottom_three = set(reverse_record_order(state, non_play_in)[:3])
    for team in bottom_three:
        entries[team]["balls"] = 2
        entries[team]["draft_relegated"] = True

    for entry in entries.values():
        entry.setdefault("draft_relegated", False)
        wins, losses, diff = _standing_record(state, entry["team"])
        entry["wins"] = wins
        entry["losses"] = losses
        entry["point_diff"] = diff

    if len(entries) != 16:
        # Defensive fallback for a legacy postseason save with incomplete play-in labels.
        ordered = reverse_record_order(state, state.standings)
        missing = [team for team in ordered if team not in entries]
        for team in missing:
            if len(entries) >= 16:
                break
            wins, losses, diff = _standing_record(state, team)
            entries[team] = {
                "team": team,
                "category": "legacy_postseason_fallback",
                "balls": 1,
                "conference": "",
                "seed": 0,
                "draft_relegated": team in bottom_three,
                "wins": wins,
                "losses": losses,
                "point_diff": diff,
            }

    if len(entries) != 16:
        raise ValueError(f"Expected 16 lottery teams, found {len(entries)}.")

    return sorted(
        entries.values(),
        key=lambda entry: (
            entry["wins"],
            entry["point_diff"],
            entry["team"],
        ),
    )


def _prior_own_pick_slot(history: list[dict[str, Any]], team: str, years_back: int) -> int | None:
    if len(history) < years_back:
        return None
    item = history[-years_back]
    slots = item.get("own_pick_results", {})
    try:
        return int(slots.get(team))
    except (TypeError, ValueError):
        return None


def _weighted_choice(rng: random.Random, candidates: list[dict[str, Any]]) -> dict[str, Any]:
    total = sum(max(0.0, float(item["balls"])) for item in candidates)
    if total <= 0:
        return rng.choice(candidates)
    needle = rng.random() * total
    running = 0.0
    for item in candidates:
        running += float(item["balls"])
        if needle <= running:
            return item
    return candidates[-1]


def run_lottery_321(state: Any, *, seed: int | None = None) -> list[dict[str, Any]]:
    participants = lottery_participants_321(state)
    year = draft_year_for_state(state)
    history = draft_history(state)
    rng = random.Random(
        int(seed if seed is not None else getattr(state.settings, "random_seed", 0))
        + year * 97
        + 321
    )

    remaining = [dict(item) for item in participants]
    order: list[dict[str, Any]] = []

    for slot in range(1, 17):
        eligible = []
        for item in remaining:
            team = item["team"]
            prior_one = _prior_own_pick_slot(history, team, 1)
            prior_two = _prior_own_pick_slot(history, team, 2)
            if slot == 1 and prior_one == 1:
                continue
            if slot <= 5 and prior_one is not None and prior_two is not None:
                if prior_one <= 5 and prior_two <= 5:
                    continue
            eligible.append(item)

        if not eligible:
            eligible = list(remaining)

        selected = _weighted_choice(rng, eligible)
        selected = dict(selected)
        selected["slot"] = slot
        order.append(selected)
        remaining = [item for item in remaining if item["team"] != selected["team"]]

    # Draft-relegated teams have a floor of No. 12.
    for team in [item["team"] for item in participants if item.get("draft_relegated")]:
        position = next(i for i, item in enumerate(order) if item["team"] == team)
        if position >= 12:
            swap_position = None
            for candidate in range(11, -1, -1):
                if not order[candidate].get("draft_relegated"):
                    swap_position = candidate
                    break
            if swap_position is not None:
                order[position], order[swap_position] = order[swap_position], order[position]

    for index, item in enumerate(order, start=1):
        item["slot"] = index

    return order


def _tokens(value: Any) -> list[str]:
    if isinstance(value, (tuple, list, set)):
        return [clean_text(item) for item in value if clean_text(item)]
    text = clean_text(value)
    return [token for token in re.split(r"\s*[|;,]\s*", text) if token]


def _boolish(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    text = clean_text(value).lower()
    if text in {"true", "1", "yes", "y"}:
        return True
    if text in {"false", "0", "no", "n"}:
        return False
    return None


def resolve_physical_pick_owner(runtime: Any, asset_id: str, origin_team: str) -> dict[str, str]:
    """Resolve deterministic direct ownership and flag complex rights conservatively."""
    origin_team = clean_team(origin_team)
    frame = getattr(runtime, "picks", None)
    if frame is None or not hasattr(frame, "to_dict"):
        return {
            "owner_team": origin_team,
            "resolution": "origin_fallback_no_runtime_inventory",
            "right_id": "",
        }

    direct_candidates = []
    complex_candidates = []
    legality_by_id = getattr(runtime, "right_legality_by_id", {}) or {}

    for record in frame.to_dict(orient="records"):
        if asset_id not in _tokens(record.get("source_assets")):
            continue
        right_id = clean_text(record.get("future_pick_right_id"))
        candidate_team = clean_team(record.get("candidate_team"))
        structure = clean_text(record.get("right_structure")).lower()
        standalone = _boolish(record.get("standalone_trade_asset_flag"))
        decision = legality_by_id.get(right_id, {}) if right_id else {}
        verified = _boolish(decision.get("current_owner_team_verified"))
        determination = clean_text(decision.get("right_legality_determination")).lower()
        evidence_blocked = determination in {"not_legal_as_modeled", "blocked"}
        source_asset_count = len(_tokens(record.get("source_assets")))

        if (
            candidate_team
            and structure == "direct_owned_pick"
            and source_asset_count == 1
            and standalone is True
            and verified is not False
            and not evidence_blocked
        ):
            direct_candidates.append((candidate_team, right_id))
        elif candidate_team:
            complex_candidates.append((candidate_team, right_id, structure))

    unique_direct = sorted(set(direct_candidates))
    if len(unique_direct) == 1:
        owner, right_id = unique_direct[0]
        return {
            "owner_team": owner,
            "resolution": "canonical_direct_owned_pick",
            "right_id": right_id,
        }

    if complex_candidates or len(unique_direct) > 1:
        return {
            "owner_team": origin_team,
            "resolution": "complex_right_requires_slot_resolution",
            "right_id": "",
        }

    return {
        "owner_team": origin_team,
        "resolution": "origin_team_retained",
        "right_id": "",
    }


def build_draft_order(state: Any, runtime: Any, lottery_order: list[dict[str, Any]]) -> list[dict[str, Any]]:
    year = draft_year_for_state(state)
    lottery_teams = [item["team"] for item in lottery_order]
    non_lottery = [team for team in state.standings if team not in set(lottery_teams)]
    round_one_origins = lottery_teams + reverse_record_order(state, non_lottery)
    if len(round_one_origins) != 30 or len(set(round_one_origins)) != 30:
        raise ValueError("Round-one draft order did not resolve to 30 unique origin teams.")

    round_two_origins = reverse_record_order(state, state.standings)
    picks = []
    overall = 0
    for round_number, origins in ((1, round_one_origins), (2, round_two_origins)):
        round_pick = 0
        for origin in origins:
            asset_id = f"{year}_R{round_number}_{origin}"
            if is_forfeited_source_asset(asset_id):
                continue
            overall += 1
            round_pick += 1
            ownership = resolve_physical_pick_owner(runtime, asset_id, origin)
            picks.append(
                {
                    "overall_pick": overall,
                    "round": round_number,
                    "round_pick": round_pick,
                    "origin_team": origin,
                    "owner_team": ownership["owner_team"],
                    "owner_resolution": ownership["resolution"],
                    "pick_right_id": ownership["right_id"],
                    "asset_id": asset_id,
                    "prospect_id": "",
                    "player_name": "",
                    "position": "",
                    "school": "",
                    "selected_by_user": False,
                }
            )
    return picks


def _prospect_seed(state: Any, draft_year: int, class_strength: int) -> int:
    return (
        int(getattr(state.settings, "random_seed", 0))
        + draft_year * 1009
        + int(class_strength) * 7919
    )


def _skill_profile(rng: random.Random, position: str, overall: float, potential: float, archetype: str) -> dict[str, float]:
    profile = {
        "scoring_rating": overall + rng.gauss(0.0, 4.0),
        "shooting_rating": overall + rng.gauss(0.0, 5.0),
        "playmaking_rating": overall + rng.gauss(0.0, 5.0),
        "rebounding_rating": overall + rng.gauss(0.0, 5.0),
        "defense_rating": overall + rng.gauss(0.0, 5.0),
        "efficiency_rating": overall + rng.gauss(0.0, 3.5),
        "availability_rating": overall + rng.gauss(2.0, 5.0),
    }

    if position == "PG":
        profile["playmaking_rating"] += 7.0
        profile["rebounding_rating"] -= 7.0
    elif position == "SG":
        profile["shooting_rating"] += 4.0
        profile["rebounding_rating"] -= 3.0
    elif position == "SF":
        profile["defense_rating"] += 2.0
    elif position == "PF":
        profile["rebounding_rating"] += 5.0
        profile["playmaking_rating"] -= 3.0
    elif position == "C":
        profile["rebounding_rating"] += 8.0
        profile["defense_rating"] += 6.0
        profile["playmaking_rating"] -= 5.0
        profile["shooting_rating"] -= 4.0

    if "Shooter" in archetype or "Stretch" in archetype or "Shot-Making" in archetype:
        profile["shooting_rating"] += 6.0
    if "Creator" in archetype or "Maestro" in archetype or "Point Forward" in archetype:
        profile["playmaking_rating"] += 5.0
    if "Defensive" in archetype or "Two-Way" in archetype or "Rim Protector" in archetype or "Anchor" in archetype:
        profile["defense_rating"] += 6.0

    return {key: round(clamp(value, 45.0, 97.0), 1) for key, value in profile.items()}


def _baseline_per_36(position: str, skills: dict[str, float]) -> dict[str, float]:
    base = POSITION_BASELINES[position]
    scoring = skills["scoring_rating"] / 75.0
    shooting = skills["shooting_rating"] / 75.0
    playmaking = skills["playmaking_rating"] / 75.0
    rebounding = skills["rebounding_rating"] / 75.0
    defense = skills["defense_rating"] / 75.0
    efficiency = skills["efficiency_rating"] / 75.0
    return {
        "points_per_36": round(base["points"] * scoring * (0.86 + 0.14 * efficiency), 2),
        "rebounds_per_36": round(base["rebounds"] * rebounding, 2),
        "assists_per_36": round(base["assists"] * playmaking, 2),
        "steals_per_36": round(base["steals"] * defense, 2),
        "blocks_per_36": round(base["blocks"] * defense, 2),
        "turnovers_per_36": round(base["turnovers"] * (1.1 - 0.12 * playmaking), 2),
        "fouls_per_36": round(base["fouls"] * (1.08 - 0.08 * defense), 2),
        "three_attempts_per_36": round(base["three_attempts"] * shooting, 2),
        "free_throw_attempts_per_36": round(base["free_throw_attempts"] * scoring, 2),
    }


def generate_draft_class(state: Any, class_strength: int, *, size: int = DRAFT_CLASS_SIZE) -> list[dict[str, Any]]:
    class_strength = int(clamp(class_strength, 1, 10))
    year = draft_year_for_state(state)
    rng = random.Random(_prospect_seed(state, year, class_strength))
    names_used = set()
    prospects = []
    strength_shift = (class_strength - 5.5) * 0.75

    for index in range(size):
        while True:
            name = f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}"
            if name not in names_used:
                names_used.add(name)
                break

        position = rng.choices(POSITIONS, weights=(0.19, 0.20, 0.22, 0.20, 0.19), k=1)[0]
        archetype = rng.choice(ARCHETYPES[position])
        age = round(clamp(rng.gauss(20.4, 1.2), 18.0, 23.5), 1)

        # Talent has a long right tail, with class strength affecting both depth and star odds.
        overall = clamp(rng.gauss(67.0 + strength_shift, 5.0), 53.0, 82.0)
        upside = abs(rng.gauss(8.0 + max(0.0, strength_shift) * 0.45, 4.5))
        potential = clamp(overall + upside, overall + 1.0, 96.0)
        if rng.random() < 0.06 + class_strength * 0.006:
            potential = clamp(potential + rng.uniform(3.0, 8.0), potential, 98.0)

        skills = _skill_profile(rng, position, overall, potential, archetype)
        baseline = _baseline_per_36(position, skills)
        readiness = clamp(0.62 * overall + 0.38 * skills["efficiency_rating"], 45.0, 96.0)
        athleticism = clamp(overall + rng.gauss(1.0, 7.0), 45.0, 98.0)
        confidence = clamp(rng.gauss(72.0, 12.0), 42.0, 96.0)
        star_probability = clamp((potential - 78.0) * 3.3 + (overall - 67.0) * 1.5, 1.0, 82.0)
        bust_probability = clamp(42.0 - (overall - 60.0) * 2.0 - (confidence - 60.0) * 0.25, 4.0, 55.0)
        big_board_score = (
            overall * 0.48
            + potential * 0.36
            + readiness * 0.08
            + athleticism * 0.08
        )

        prospect_id = f"GEN-{year}-{index + 1:03d}"
        scouting_noise = (100.0 - confidence) / 100.0 * 7.0
        scouted_overall = clamp(overall + rng.gauss(0.0, scouting_noise), 50.0, 90.0)
        scouted_potential = clamp(potential + rng.gauss(0.0, scouting_noise * 1.15), 55.0, 99.0)

        prospects.append(
            {
                "prospect_id": prospect_id,
                "player_name": name,
                "position": position,
                "archetype": archetype,
                "age": age,
                "school": rng.choice(SCHOOLS),
                "hidden_overall": round(overall, 1),
                "hidden_potential": round(potential, 1),
                "scouted_overall": round(scouted_overall, 1),
                "scouted_potential": round(scouted_potential, 1),
                "readiness": round(readiness, 1),
                "athleticism": round(athleticism, 1),
                "scouting_confidence": round(confidence, 1),
                "star_probability": round(star_probability, 1),
                "bust_probability": round(bust_probability, 1),
                "big_board_score": round(big_board_score, 3),
                "skills": skills,
                "baseline_per_36": baseline,
                "drafted": False,
                "drafted_by": "",
                "overall_pick": None,
                "round": None,
                "round_pick": None,
            }
        )

    prospects.sort(key=lambda row: (-row["big_board_score"], -row["hidden_potential"], row["player_name"]))
    # Strength-specific top-end shaping, still based on generated talent rather than fixed names.
    top_bonus = max(0.0, (class_strength - 4) * 0.55)
    for index, prospect in enumerate(prospects[:5]):
        bonus = max(0.0, top_bonus - index * 0.35)
        prospect["hidden_overall"] = round(clamp(prospect["hidden_overall"] + bonus, 55.0, 84.0), 1)
        prospect["hidden_potential"] = round(clamp(prospect["hidden_potential"] + bonus * 1.5, prospect["hidden_overall"] + 1.0, 98.0), 1)

    for rank, prospect in enumerate(prospects, start=1):
        prospect["big_board_rank"] = rank
        if rank <= 3:
            projected = "Top 3"
        elif rank <= 8:
            projected = "Lottery"
        elif rank <= 16:
            projected = "Mid 1st"
        elif rank <= 30:
            projected = "Late 1st"
        elif rank <= 45:
            projected = "Early 2nd"
        else:
            projected = "2nd / UDFA"
        prospect["projected_range"] = projected
        prospect["floor"] = (
            "High-level starter" if prospect["hidden_overall"] >= 75
            else "Rotation player" if prospect["hidden_overall"] >= 68
            else "Developmental reserve"
        )
        prospect["ceiling"] = (
            "Franchise cornerstone" if prospect["hidden_potential"] >= 93
            else "All-Star" if prospect["hidden_potential"] >= 88
            else "Quality starter" if prospect["hidden_potential"] >= 82
            else "Rotation contributor"
        )

    return prospects


# FRANCHISE_SEASON_LONG_SCOUTING_V1_2
def initialize_regular_season_scouting_state(
    state: Any,
    *,
    controlled_teams: Iterable[str] = (),
    class_strength: int = 5,
) -> dict[str, Any]:
    """Create the next Draft class during the live season, before the lottery.

    The class and team-specific scouting reports persist into the postseason,
    lottery and Draft Night. Lottery participants/order are intentionally left
    unresolved until the postseason is complete.
    """
    year = draft_year_for_state(state)
    existing = draft_state(state)
    if existing and int(existing.get("draft_year", -1)) == year:
        existing["controlled_teams"] = sorted(
            {clean_team(team) for team in controlled_teams if clean_team(team)}
        )
        if existing.get("phase") == "season_scouting" and not existing.get("prospects"):
            existing["prospects"] = generate_draft_class(
                state, int(existing.get("class_strength", class_strength) or class_strength)
            )
        return existing

    raw_existing = getattr(state, DRAFT_STATE_ATTR, None)
    if isinstance(raw_existing, dict) and raw_existing.get("phase") == "draft_complete":
        # Preserve staff/scouting evaluation accuracy before the next class replaces this draft state.
        try:
            from franchise_staff_system_v1 import archive_completed_scouting_accuracy
            archive_completed_scouting_accuracy(state, raw_existing)
        except Exception:
            # Draft lifecycle must never be blocked by an optional analytics archive.
            pass
        _archive_completed_draft(state, raw_existing)

    current = {
        "version": DRAFT_ENGINE_VERSION,
        "lottery_rule_version": LOTTERY_RULE_VERSION,
        "source_season": state.settings.season_label,
        "target_season": next_season_label(state.settings.season_label),
        "draft_year": year,
        "phase": "season_scouting",
        "class_strength": int(clamp(class_strength, 1, 10)),
        "lottery_participants": [],
        "lottery_order": [],
        "draft_order": [],
        "prospects": [],
        "current_pick_index": 0,
        "controlled_teams": sorted(
            {clean_team(team) for team in controlled_teams if clean_team(team)}
        ),
        "paused": True,
        "clock_deadline_ts": None,
        "clock_resume_pending": False,
        "clock_remaining_seconds": AI_PICK_CLOCK_SECONDS,
        "clock_seconds": AI_PICK_CLOCK_SECONDS,
        "completed_at_ts": None,
        "created_at_ts": time.time(),
    }
    current["prospects"] = generate_draft_class(state, current["class_strength"])
    setattr(state, DRAFT_STATE_ATTR, current)
    return current


def promote_regular_season_scouting_to_lottery(
    state: Any,
    *,
    controlled_teams: Iterable[str] = (),
) -> dict[str, Any]:
    """Lock the completed-season lottery field without discarding scouting."""
    if not postseason_is_complete(state):
        raise ValueError("The Draft Lottery requires a completed postseason.")
    current = draft_state(state)
    if current is None:
        raise ValueError("The season-long scouting class is not initialized.")
    if int(current.get("draft_year", -1)) != draft_year_for_state(state):
        raise ValueError("The live scouting class does not match the current Draft year.")
    if current.get("phase") != "season_scouting":
        return current
    current["controlled_teams"] = sorted(
        {clean_team(team) for team in controlled_teams if clean_team(team)}
    )
    current["lottery_participants"] = lottery_participants_321(state)
    current["lottery_order"] = []
    current["draft_order"] = []
    current["phase"] = "lottery_ready"
    return current


def initialize_draft_state(
    state: Any,
    runtime: Any,
    *,
    controlled_teams: Iterable[str] = (),
    class_strength: int = 5,
) -> dict[str, Any]:
    if not postseason_is_complete(state):
        raise ValueError("Draft initialization requires a completed postseason.")

    year = draft_year_for_state(state)
    _raw_existing_draft_v1_1_8 = getattr(
        state,
        DRAFT_STATE_ATTR,
        None,
    )
    if (
        isinstance(
            _raw_existing_draft_v1_1_8,
            dict,
        )
        and str(
            _raw_existing_draft_v1_1_8.get(
                "phase",
                "",
            )
        ).strip()
        == "draft_complete"
        and int(
            _raw_existing_draft_v1_1_8.get(
                "draft_year",
                -1,
            )
        )
        != year
    ):
        # Preserve the old completed board before a new
        # Draft becomes the live Draft state. The helper is
        # idempotent by draft year.
        _archive_completed_draft(
            state,
            _raw_existing_draft_v1_1_8,
        )

    existing = draft_state(state)
    if existing and int(existing.get("draft_year", -1)) == year:
        existing["controlled_teams"] = sorted({clean_team(team) for team in controlled_teams if clean_team(team)})
        if existing.get("phase") == "season_scouting":
            return promote_regular_season_scouting_to_lottery(
                state,
                controlled_teams=controlled_teams,
            )
        return existing

    participants = lottery_participants_321(state)
    current = {
        "version": DRAFT_ENGINE_VERSION,
        "lottery_rule_version": LOTTERY_RULE_VERSION,
        "source_season": state.settings.season_label,
        "target_season": next_season_label(state.settings.season_label),
        "draft_year": year,
        "phase": "lottery_ready",
        "class_strength": int(clamp(class_strength, 1, 10)),
        "lottery_participants": participants,
        "lottery_order": [],
        "draft_order": [],
        "prospects": [],
        "current_pick_index": 0,
        "controlled_teams": sorted({clean_team(team) for team in controlled_teams if clean_team(team)}),
        "paused": True,
        "clock_deadline_ts": None,
        "clock_resume_pending": False,
        "clock_remaining_seconds": AI_PICK_CLOCK_SECONDS,
        "clock_seconds": AI_PICK_CLOCK_SECONDS,
        "completed_at_ts": None,
        "created_at_ts": time.time(),
    }
    setattr(state, DRAFT_STATE_ATTR, current)
    return current


def conduct_lottery(state: Any, runtime: Any) -> dict[str, Any]:
    current = draft_state(state)
    if current is None:
        current = initialize_draft_state(state, runtime)
    if current["phase"] not in {"lottery_ready", "lottery_complete"}:
        return current
    if not current["lottery_order"]:
        current["lottery_order"] = run_lottery_321(state)
        current["draft_order"] = build_draft_order(state, runtime, current["lottery_order"])
    current["phase"] = "lottery_complete"
    return current


def reveal_draft_class(state: Any) -> dict[str, Any]:
    current = draft_state(state)
    if current is None or current["phase"] not in {"lottery_complete", "scouting"}:
        raise ValueError("Run the Draft Lottery before revealing the class.")
    if not current["prospects"]:
        current["prospects"] = generate_draft_class(state, int(current["class_strength"]))
    current["phase"] = "scouting"
    return current


def start_draft_night(state: Any, *, now_ts: float | None = None) -> dict[str, Any]:
    current = draft_state(state)
    if current is None or current["phase"] not in {"scouting", "draft_in_progress"}:
        raise ValueError("Reveal the draft class before starting Draft Night.")
    current["phase"] = "draft_in_progress"
    current["paused"] = False
    _configure_clock_for_current_pick(current, now_ts=now_ts)
    return current


def current_pick(current: dict[str, Any]) -> dict[str, Any] | None:
    index = int(current.get("current_pick_index", 0))
    order = current.get("draft_order", [])
    if index < 0 or index >= len(order):
        return None
    return order[index]


def available_prospects(current: dict[str, Any]) -> list[dict[str, Any]]:
    return [prospect for prospect in current.get("prospects", []) if not prospect.get("drafted")]


def is_user_pick(current: dict[str, Any], pick: dict[str, Any] | None = None) -> bool:
    pick = pick or current_pick(current)
    if not pick:
        return False
    return clean_team(pick["owner_team"]) in set(current.get("controlled_teams", []))


def _configure_clock_for_current_pick(current: dict[str, Any], *, now_ts: float | None = None) -> None:
    pick = current_pick(current)
    if pick is None:
        current["paused"] = True
        current["clock_deadline_ts"] = None
        current["clock_resume_pending"] = False
        return
    if is_user_pick(current, pick):
        current["paused"] = True
        current["clock_deadline_ts"] = None
        current["clock_resume_pending"] = False
        current["clock_remaining_seconds"] = int(current.get("clock_seconds", AI_PICK_CLOCK_SECONDS))
        return
    if current.get("paused"):
        return
    now = float(now_ts if now_ts is not None else time.time())
    if current.get("clock_resume_pending"):
        remaining = int(current.get("clock_remaining_seconds", current.get("clock_seconds", AI_PICK_CLOCK_SECONDS)))
        current["clock_resume_pending"] = False
        current["clock_deadline_ts"] = now + max(1, remaining)
        return
    current["clock_remaining_seconds"] = int(current.get("clock_seconds", AI_PICK_CLOCK_SECONDS))
    current["clock_deadline_ts"] = now + current["clock_remaining_seconds"]


def clock_remaining(current: dict[str, Any], *, now_ts: float | None = None) -> int | None:
    pick = current_pick(current)
    if pick is None or is_user_pick(current, pick):
        return None
    if current.get("paused"):
        return int(current.get("clock_remaining_seconds", AI_PICK_CLOCK_SECONDS))
    deadline = current.get("clock_deadline_ts")
    if deadline is None:
        return int(current.get("clock_seconds", AI_PICK_CLOCK_SECONDS))
    now = float(now_ts if now_ts is not None else time.time())
    return max(0, int(math.ceil(float(deadline) - now)))


def pause_draft(state: Any, *, now_ts: float | None = None) -> dict[str, Any]:
    current = draft_state(state)
    if current is None:
        raise ValueError("Draft state is not initialized.")
    if not current.get("paused"):
        remaining = clock_remaining(current, now_ts=now_ts)
        if remaining is not None:
            current["clock_remaining_seconds"] = remaining
    current["paused"] = True
    current["clock_deadline_ts"] = None
    current["clock_resume_pending"] = False
    return current


def resume_draft(state: Any, *, now_ts: float | None = None) -> dict[str, Any]:
    """Resume without charging checkpoint/rerun time against the pick clock."""
    current = draft_state(state)
    if current is None:
        raise ValueError("Draft state is not initialized.")
    if is_user_pick(current):
        current["paused"] = True
        current["clock_deadline_ts"] = None
        current["clock_resume_pending"] = False
        return current
    current["paused"] = False
    current["clock_deadline_ts"] = None
    current["clock_resume_pending"] = True
    current["clock_remaining_seconds"] = int(
        current.get("clock_remaining_seconds", current.get("clock_seconds", AI_PICK_CLOCK_SECONDS))
    )
    return current


def _primary_position(position: str) -> str:
    token = clean_text(position).upper().split("/")[0]
    return token if token in POSITIONS else "SF"


def _team_need_score(state: Any, team: str, position: str) -> float:
    # One player occupies one depth-chart position. Combo-position players are
    # assigned to the first (primary) position in the canonical position string
    # instead of being counted independently at every eligible position.
    roster = state.teams[team].roster_player_ids
    ratings: list[float] = []
    for player_id in roster:
        player = state.players.get(player_id)
        if player is None:
            continue
        if _primary_position(clean_text(player.position)) != position:
            continue
        ratings.append(float(player.overall_rating))
    ratings.sort(reverse=True)
    if not ratings:
        return 100.0
    depth_quality = sum(ratings[:2]) / min(2, len(ratings))
    return clamp(
        100.0 - depth_quality + (8.0 if len(ratings) < 2 else 0.0),
        5.0,
        100.0,
    )


def team_depth_chart_rows(state: Any, team: str) -> list[dict[str, Any]]:
    normalized_team = clean_team(team)
    roster_ids = list(state.teams[normalized_team].roster_player_ids)
    assigned: dict[str, list[dict[str, Any]]] = {
        position: [] for position in POSITIONS
    }

    for player_id in roster_ids:
        player = state.players.get(player_id)
        if player is None:
            continue
        position = _primary_position(clean_text(player.position))
        assigned[position].append({
            "player_id": clean_text(player_id),
            "name": clean_text(player.player_name),
            "overall": float(player.overall_rating),
            "age": float(getattr(player, "age", 0.0) or 0.0),
        })

    rows: list[dict[str, Any]] = []
    seen_player_ids: set[str] = set()
    for position in POSITIONS:
        players = sorted(
            assigned[position],
            key=lambda row: (-row["overall"], row["name"], row["player_id"]),
        )
        for item in players:
            if item["player_id"] in seen_player_ids:
                raise RuntimeError(
                    "Depth-chart assignment duplicated player " + item["player_id"]
                )
            seen_player_ids.add(item["player_id"])

        need_score = _team_need_score(state, normalized_team, position)
        priority = (
            "Critical" if need_score >= 32
            else "High" if need_score >= 24
            else "Medium" if need_score >= 17
            else "Stable"
        )
        rows.append({
            "Position": position,
            "Starter": players[0]["name"] if players else "—",
            "Starter OVR": round(players[0]["overall"], 1) if players else None,
            "Backup": players[1]["name"] if len(players) >= 2 else "—",
            "Backup OVR": round(players[1]["overall"], 1) if len(players) >= 2 else None,
            "Third": players[2]["name"] if len(players) >= 3 else "—",
            "Depth": len(players),
            "Need Score": round(need_score, 1),
            "Priority": priority,
        })
    rows.sort(
        key=lambda row: (
            -float(row["Need Score"]),
            POSITIONS.index(row["Position"]),
        )
    )
    return rows


def top_team_needs(state: Any, team: str, *, limit: int = 3) -> list[dict[str, Any]]:
    return team_depth_chart_rows(state, team)[:max(1, int(limit))]


def future_user_picks(state: Any, *, include_current: bool = False) -> list[dict[str, Any]]:
    current = draft_state(state)
    if current is None:
        return []
    controlled = set(current.get("controlled_teams", []))
    index = int(current.get("current_pick_index", 0))
    if not include_current:
        index += 1
    return [
        pick for pick in current.get("draft_order", [])[index:]
        if clean_team(pick.get("owner_team")) in controlled
    ]


def ai_prospect_score(
    state: Any,
    team: str,
    prospect: dict[str, Any],
    overall_pick: int,
    *,
    _scouting_estimate_cache: dict[tuple[str, str], tuple[float, float]] | None = None,
) -> float:
    # FRANCHISE_AI_IMPERFECT_SCOUTING_V1
    from franchise_scouting_discovery_v1 import ai_scouted_estimate_v1

    position = _primary_position(prospect["position"])
    need = _team_need_score(state, team, position)
    timeline_bonus = max(0.0, 22.0 - float(prospect["age"])) * 0.55

    # Scouting uncertainty is specific to the team/prospect pairing. During a
    # contiguous AI draft simulation the same team sees many of the same
    # surviving prospects again at its later pick. Reuse only that immutable
    # estimate; team need is intentionally recomputed above after every pick.
    cache_key = (
        clean_team(team),
        clean_text(prospect.get("prospect_id")),
    )
    cached = (
        _scouting_estimate_cache.get(cache_key)
        if _scouting_estimate_cache is not None
        else None
    )
    if cached is not None:
        estimated_overall, estimated_potential = cached
    else:
        try:
            scouting = ai_scouted_estimate_v1(state, team, prospect)
            estimated_overall = float(scouting["overall"])
            estimated_potential = float(scouting["potential"])
            if _scouting_estimate_cache is not None:
                _scouting_estimate_cache[cache_key] = (
                    estimated_overall,
                    estimated_potential,
                )
        except Exception:
            # Draft Night must remain available if scouting context is temporarily unavailable.
            # Fall back to public noisy estimates, never hidden exact ratings. A
            # transient failure is deliberately not cached.
            estimated_overall = float(prospect.get("scouted_overall", 70.0))
            estimated_potential = float(prospect.get("scouted_potential", estimated_overall + 6.0))
    estimated_board = estimated_overall * 0.57 + estimated_potential * 0.43
    pick_value_bias = max(0.0, 32.0 - overall_pick) * estimated_potential / 1000.0
    return (
        estimated_board * 0.70
        + need * 0.18
        + estimated_potential * 0.08
        + timeline_bonus
        + pick_value_bias
    )


def recommended_prospects(state: Any, team: str, *, limit: int = 8) -> list[dict[str, Any]]:
    current = draft_state(state)
    if current is None:
        return []
    pick = current_pick(current)
    overall = int(pick["overall_pick"]) if pick else 1
    rows = []
    for prospect in available_prospects(current):
        score = ai_prospect_score(state, team, prospect, overall)
        position = _primary_position(prospect["position"])
        need_score = _team_need_score(state, team, position)
        rows.append({
            **prospect,
            "team_fit_score": round(score, 2),
            "team_need_score": round(need_score, 1),
            "fit_reason": f"{position} need {need_score:.0f}/100 · {prospect['archetype']}",
        })
    rows.sort(key=lambda row: (-row["team_fit_score"], row["big_board_rank"]))
    return rows[:limit]


def choose_ai_prospect(
    state: Any,
    *,
    pick: dict[str, Any] | None = None,
    _scouting_estimate_cache: dict[tuple[str, str], tuple[float, float]] | None = None,
) -> dict[str, Any]:
    current = draft_state(state)
    if current is None:
        raise ValueError("Draft state is not initialized.")
    pick = pick or current_pick(current)
    if pick is None:
        raise ValueError("No draft pick is on the clock.")
    available = available_prospects(current)
    if not available:
        raise ValueError("No prospects remain available.")
    team = clean_team(pick["owner_team"])
    seed_text = f"{current['draft_year']}|{pick['overall_pick']}|{team}|{current['class_strength']}"
    seed = int(hashlib.sha256(seed_text.encode("utf-8")).hexdigest()[:12], 16)
    rng = random.Random(seed)
    board = sorted(
        available,
        key=lambda prospect: (
            -(
                ai_prospect_score(
                    state,
                    team,
                    prospect,
                    int(pick["overall_pick"]),
                    _scouting_estimate_cache=_scouting_estimate_cache,
                )
                + rng.gauss(0.0, 1.7)
            ),
            prospect["big_board_rank"],
        ),
    )
    return board[0]


def _stat_factors_from_skills(skills: dict[str, float]) -> dict[str, float]:
    return {
        "points": round(clamp(skills["scoring_rating"] / 75.0, 0.65, 1.35), 4),
        "rebounds": round(clamp(skills["rebounding_rating"] / 75.0, 0.65, 1.35), 4),
        "assists": round(clamp(skills["playmaking_rating"] / 75.0, 0.65, 1.35), 4),
        "steals": round(clamp(skills["defense_rating"] / 75.0, 0.65, 1.35), 4),
        "blocks": round(clamp(skills["defense_rating"] / 75.0, 0.65, 1.35), 4),
        "turnovers": round(clamp(1.12 - skills["playmaking_rating"] / 750.0, 0.8, 1.2), 4),
        "fouls": round(clamp(1.12 - skills["defense_rating"] / 800.0, 0.82, 1.18), 4),
        "three_attempts": round(clamp(skills["shooting_rating"] / 75.0, 0.65, 1.35), 4),
        "free_throw_attempts": round(clamp(skills["scoring_rating"] / 75.0, 0.65, 1.35), 4),
    }


def integrate_drafted_prospect(state: Any, pick: dict[str, Any], prospect: dict[str, Any]) -> None:
    from simulation_league_state_v1 import (
        ContractState,
        InjuryState,
        SimulationPlayerState,
    )

    player_id = prospect["prospect_id"]
    if player_id in state.players:
        return

    team = clean_team(pick["owner_team"])
    target_season = next_season_label(state.settings.season_label)
    player = SimulationPlayerState(
        player_id=player_id,
        player_name=prospect["player_name"],
        team_abbreviation=team,
        roster_status="active_roster",
        overall_rating=float(prospect["hidden_overall"]),
        position=prospect["position"],
        synthetic=True,  # Prevent an immediate pre-rookie development cycle during season transition.
        rating_source="generated-draft-class-v1",
        two_way=False,
        contract=ContractState(
            status="rookie_scale_pending",
            salary=None,
            years_remaining=4,
            option_type="rookie_scale",
            guaranteed=True,
        ),
        age=float(prospect["age"]),
        potential_rating=float(prospect["hidden_potential"]),
        future_outlook_rating=float(prospect["hidden_potential"]),
        development_direction="Rising",
        profile_reliability=float(prospect["scouting_confidence"]) / 100.0,
        skill_ratings=dict(prospect["skills"]),
        stat_factors=_stat_factors_from_skills(prospect["skills"]),
        baseline_per_36=dict(prospect["baseline_per_36"]),
        development_history=[],
    )
    setattr(player, "draft_year", draft_year_for_state(state))
    setattr(player, "draft_round", int(pick["round"]))
    setattr(player, "draft_pick", int(pick["overall_pick"]))
    setattr(player, "draft_round_pick", int(pick["round_pick"]))
    setattr(player, "drafted_by", team)
    setattr(player, "rookie_season", target_season)
    setattr(player, "rookie_season_start", season_end_year(state.settings.season_label))
    setattr(player, "years_of_service", 0)
    setattr(player, "rookie_eligible", False)
    setattr(player, "generated_prospect", True)
    setattr(player, "career_metadata_source", "generated_draft_v1")
    setattr(player, "draft_class_id", f"DRAFT-{draft_year_for_state(state)}")

    state.players[player_id] = player
    state.player_season_totals.setdefault(player_id, _empty_player_totals(player_id))
    state.injuries[player_id] = InjuryState(player_id=player_id)

    # Ensure Medical V2 / fatigue persistence immediately knows about the new
    # league member before the draft selection is checkpointed.
    from simulation_injury_fatigue_v1 import synchronize_injury_profile
    synchronize_injury_profile(state, player_id)

    team_state = state.teams[team]
    if player_id not in team_state.roster_player_ids:
        team_state.roster_player_ids = tuple(list(team_state.roster_player_ids) + [player_id])
    if player_id not in team_state.inactive_player_ids:
        team_state.inactive_player_ids = tuple(list(team_state.inactive_player_ids) + [player_id])


def _empty_player_totals(player_id: str) -> Any:
    from simulation_league_state_v1 import PlayerSeasonTotals
    return PlayerSeasonTotals(player_id=player_id)


def _record_pick(current: dict[str, Any], pick: dict[str, Any], prospect: dict[str, Any], *, selected_by_user: bool) -> None:
    pick["prospect_id"] = prospect["prospect_id"]
    pick["player_name"] = prospect["player_name"]
    pick["position"] = prospect["position"]
    pick["school"] = prospect["school"]
    pick["selected_by_user"] = bool(selected_by_user)
    prospect["drafted"] = True
    prospect["drafted_by"] = pick["owner_team"]
    prospect["overall_pick"] = pick["overall_pick"]
    prospect["round"] = pick["round"]
    prospect["round_pick"] = pick["round_pick"]


def make_selection(
    state: Any,
    prospect_id: str,
    *,
    selected_by_user: bool,
    now_ts: float | None = None,
    integrate: bool = True,
) -> dict[str, Any]:
    current = draft_state(state)
    if current is None or current.get("phase") != "draft_in_progress":
        raise ValueError("Draft Night is not in progress.")
    pick = current_pick(current)
    if pick is None:
        raise ValueError("No pick is currently on the clock.")
    prospect = next(
        (row for row in current["prospects"] if row["prospect_id"] == prospect_id and not row.get("drafted")),
        None,
    )
    if prospect is None:
        raise ValueError("The selected prospect is not available.")

    _record_pick(current, pick, prospect, selected_by_user=selected_by_user)
    if integrate:
        integrate_drafted_prospect(state, pick, prospect)

        # FA_POST_DRAFT_PICK_HOLD_BRIDGE_V1: draft-event hook
        from franchise_post_draft_first_round_pick_hold_bridge_v1 import (
            sync_post_draft_first_round_pick_hold_ledger,
        )
        sync_post_draft_first_round_pick_hold_ledger(
            state,
            current,
            draft_event_id=f"DRAFT-{int(current['draft_year'])}",
        )

    current["current_pick_index"] = int(current["current_pick_index"]) + 1
    current["clock_deadline_ts"] = None
    current["clock_resume_pending"] = False
    current["clock_remaining_seconds"] = int(current.get("clock_seconds", AI_PICK_CLOCK_SECONDS))

    if current["current_pick_index"] >= len(current["draft_order"]):
        current["phase"] = "draft_complete"
        current["paused"] = True
        current["completed_at_ts"] = float(now_ts if now_ts is not None else time.time())
        _archive_completed_draft(state, current)
    else:
        current["paused"] = False
        _configure_clock_for_current_pick(current, now_ts=now_ts)
    return pick


def make_ai_selection(
    state: Any,
    *,
    now_ts: float | None = None,
    integrate: bool = True,
    _scouting_estimate_cache: dict[tuple[str, str], tuple[float, float]] | None = None,
) -> dict[str, Any]:
    current = draft_state(state)
    if current is None:
        raise ValueError("Draft state is not initialized.")
    pick = current_pick(current)
    if pick is None:
        raise ValueError("No pick is on the clock.")
    prospect = choose_ai_prospect(
        state,
        pick=pick,
        _scouting_estimate_cache=_scouting_estimate_cache,
    )
    return make_selection(
        state,
        prospect["prospect_id"],
        selected_by_user=False,
        now_ts=now_ts,
        integrate=integrate,
    )


def catch_up_expired_ai_picks(state: Any, *, now_ts: float | None = None, integrate: bool = True, max_picks: int = 60) -> int:
    current = draft_state(state)
    if current is None or current.get("phase") != "draft_in_progress" or current.get("paused"):
        return 0
    now = float(now_ts if now_ts is not None else time.time())
    made = 0
    scouting_estimate_cache: dict[tuple[str, str], tuple[float, float]] = {}
    while made < max_picks:
        pick = current_pick(current)
        if pick is None or is_user_pick(current, pick) or current.get("paused"):
            break
        deadline = current.get("clock_deadline_ts")
        if deadline is None:
            _configure_clock_for_current_pick(current, now_ts=now)
            deadline = current.get("clock_deadline_ts")
        if deadline is None or float(deadline) > now:
            break
        selection_time = float(deadline)
        make_ai_selection(
            state,
            now_ts=selection_time,
            integrate=integrate,
            _scouting_estimate_cache=scouting_estimate_cache,
        )
        made += 1
        current = draft_state(state)
        if current is None or current.get("phase") != "draft_in_progress":
            break
    return made


def simulate_next_pick(state: Any, *, now_ts: float | None = None, integrate: bool = True) -> int:
    current = draft_state(state)
    if current is None or current.get("phase") != "draft_in_progress":
        return 0
    if is_user_pick(current):
        # User explicitly asked to simulate it, so the front-office AI may act.
        make_ai_selection(state, now_ts=now_ts, integrate=integrate)
        return 1
    make_ai_selection(state, now_ts=now_ts, integrate=integrate)
    return 1


def simulate_to_next_user_pick(state: Any, *, now_ts: float | None = None, integrate: bool = True, max_picks: int = 60) -> int:
    current = draft_state(state)
    if current is None:
        return 0
    made = 0
    scouting_estimate_cache: dict[tuple[str, str], tuple[float, float]] = {}
    while current.get("phase") == "draft_in_progress" and made < max_picks:
        if is_user_pick(current):
            break
        make_ai_selection(
            state,
            now_ts=now_ts,
            integrate=integrate,
            _scouting_estimate_cache=scouting_estimate_cache,
        )
        made += 1
        current = draft_state(state)
    return made


def simulate_to_next_round(state: Any, *, now_ts: float | None = None, integrate: bool = True) -> int:
    current = draft_state(state)
    pick = current_pick(current) if current else None
    if current is None or pick is None:
        return 0
    starting_round = int(pick["round"])
    made = 0
    scouting_estimate_cache: dict[tuple[str, str], tuple[float, float]] = {}
    while current.get("phase") == "draft_in_progress":
        pick = current_pick(current)
        if pick is None or int(pick["round"]) != starting_round:
            break
        make_ai_selection(
            state,
            now_ts=now_ts,
            integrate=integrate,
            _scouting_estimate_cache=scouting_estimate_cache,
        )
        made += 1
        current = draft_state(state)
    return made


def simulate_rest_of_draft(state: Any, *, now_ts: float | None = None, integrate: bool = True) -> int:
    current = draft_state(state)
    made = 0
    scouting_estimate_cache: dict[tuple[str, str], tuple[float, float]] = {}
    while current and current.get("phase") == "draft_in_progress":
        make_ai_selection(
            state,
            now_ts=now_ts,
            integrate=integrate,
            _scouting_estimate_cache=scouting_estimate_cache,
        )
        made += 1
        current = draft_state(state)
    return made


def remaining_user_picks(state: Any) -> list[dict[str, Any]]:
    current = draft_state(state)
    if current is None:
        return []
    controlled = set(current.get("controlled_teams", []))
    index = int(current.get("current_pick_index", 0))
    return [
        pick for pick in current.get("draft_order", [])[index:]
        if clean_team(pick.get("owner_team")) in controlled
    ]


def _archive_completed_draft(state: Any, current: dict[str, Any]) -> None:
    history = draft_history(state)
    year = int(current["draft_year"])
    if any(int(item.get("draft_year", -1)) == year for item in history):
        return
    own_results = {
        pick["origin_team"]: int(pick["overall_pick"])
        for pick in current["draft_order"]
        if int(pick["round"]) == 1
    }
    history.append(
        {
            "version": DRAFT_ENGINE_VERSION,
            "draft_year": year,
            "source_season": current["source_season"],
            "target_season": current["target_season"],
            "class_strength": current["class_strength"],
            "lottery_order": copy.deepcopy(current["lottery_order"]),
            "draft_order": copy.deepcopy(current["draft_order"]),
            "prospects": copy.deepcopy(current["prospects"]),
            "own_pick_results": own_results,
            "completed_at_ts": current.get("completed_at_ts"),
        }
    )


def activate_drafted_rookies_after_transition(state: Any, target_season: str) -> int:
    # GENERATED_ROOKIE_LIVE_CONTRACT_ACTIVATION_V1
    from franchise_generated_rookie_contract_activation_v1 import (
        activate_generated_rookie_contracts,
    )

    return activate_generated_rookie_contracts(
        state,
        target_season,
    )


def lottery_rows(state: Any) -> list[dict[str, Any]]:
    current = draft_state(state)
    if current is None:
        return []
    order_by_team = {item["team"]: item["slot"] for item in current.get("lottery_order", [])}
    rows = []
    for item in current.get("lottery_participants", []):
        rows.append(
            {
                "Team": item["team"],
                "Record": f"{item['wins']}-{item['losses']}",
                "Category": item["category"],
                "Lottery Balls": item["balls"],
                "Result": order_by_team.get(item["team"], "—"),
            }
        )
    return rows


def big_board_rows(state: Any, *, available_only: bool = False) -> list[dict[str, Any]]:
    current = draft_state(state)
    if current is None:
        return []
    rows = []
    for prospect in current.get("prospects", []):
        if available_only and prospect.get("drafted"):
            continue
        rows.append(
            {
                "Rank": prospect["big_board_rank"],
                "Prospect": prospect["player_name"],
                "Pos": prospect["position"],
                "Age": prospect["age"],
                "School / Club": prospect["school"],
                "Archetype": prospect["archetype"],
                "Scouted OVR": prospect["scouted_overall"],
                "Scouted POT": prospect["scouted_potential"],
                "Confidence": f"{prospect['scouting_confidence']:.0f}%",
                "Projected": prospect["projected_range"],
                "Ceiling": prospect["ceiling"],
                "Bust Risk": f"{prospect['bust_probability']:.0f}%",
                "Drafted": prospect.get("drafted", False),
            }
        )
    return rows


def draft_board_rows(state: Any) -> list[dict[str, Any]]:
    current = draft_state(state)
    if current is None:
        return []
    return [
        {
            "Pick": pick["overall_pick"],
            "Round": pick["round"],
            "Round Pick": pick["round_pick"],
            "Team": pick["owner_team"],
            "Origin": pick["origin_team"],
            "Player": pick.get("player_name") or "—",
            "Pos": pick.get("position") or "—",
            "School / Club": pick.get("school") or "—",
            "Ownership": pick.get("owner_resolution", ""),
        }
        for pick in current.get("draft_order", [])
    ]


def run_self_test() -> dict[str, Any]:
    class Box:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    teams = [f"T{index:02d}" for index in range(1, 31)]
    standings = {}
    for index, team in enumerate(teams):
        wins = 15 + index
        standings[team] = Box(
            wins=wins,
            losses=82 - wins,
            points_for=9000 + wins * 4,
            points_against=9300 - wins * 2,
        )

    east = tuple(teams[:15][::-1])
    west = tuple(teams[15:][::-1])
    games = {
        "E78": Box(conference="East", round_label="Play-In 7 vs 8", status="completed", loser=east[7]),
        "W78": Box(conference="West", round_label="Play-In 7 vs 8", status="completed", loser=west[7]),
    }
    postseason = Box(
        stage="complete",
        champion=east[0],
        runner_up=west[0],
        seed_order={"East": east, "West": west},
        seed_by_team={team: idx + 1 for order in (east, west) for idx, team in enumerate(order)},
        games=games,
    )
    state = Box(
        settings=Box(season_label="2027-28", random_seed=20260811),
        standings=standings,
        postseason_state=postseason,
        teams={},
        players={},
        player_season_totals={},
    )
    for team in teams:
        ids = []
        for idx in range(10):
            player_id = f"{team}-P{idx}"
            ids.append(player_id)
            state.players[player_id] = Box(overall_rating=70 + idx, position=POSITIONS[idx % 5])
        state.teams[team] = Box(roster_player_ids=tuple(ids), inactive_player_ids=tuple())

    class FakeFrame:
        def to_dict(self, orient="records"):
            return []
    runtime = Box(picks=FakeFrame(), right_legality_by_id={})

    sanction_teams = ["LAC", "IND", *teams[2:]]
    sanction_state = Box(
        settings=Box(season_label="2028-29", random_seed=20260907),
        standings={
            sanction_team: standings[base_team]
            for sanction_team, base_team in zip(sanction_teams, teams)
        },
    )
    sanction_lottery = [
        {"team": team}
        for team in sanction_teams[:16]
    ]
    sanction_order = build_draft_order(
        sanction_state,
        runtime,
        sanction_lottery,
    )

    participants = lottery_participants_321(state)
    lottery = run_lottery_321(state, seed=42)
    init = initialize_draft_state(state, runtime, controlled_teams=(lottery[4]["team"],), class_strength=7)
    conduct_lottery(state, runtime)
    reveal_draft_class(state)
    start_draft_night(state, now_ts=1000.0)

    clock_before = clock_remaining(init, now_ts=1001.0)
    user_team = init["controlled_teams"][0]
    sim_count = simulate_to_next_user_pick(state, now_ts=1002.0, integrate=False)
    stopped_on_user = bool(current_pick(init) and current_pick(init)["owner_team"] == user_team)
    if stopped_on_user:
        simulate_next_pick(state, now_ts=1003.0, integrate=False)
    rest_count = simulate_rest_of_draft(state, now_ts=1004.0, integrate=False)

    ball_counts = {1: 0, 2: 0, 3: 0}
    for row in participants:
        ball_counts[int(row["balls"])] += 1

    bottom_three = [row["team"] for row in participants if row.get("draft_relegated")]
    lottery_slot = {row["team"]: row["slot"] for row in lottery}
    checks = {
        "version_current": DRAFT_ENGINE_VERSION == (
            "franchise-draft-engine-v1.1-2026-08-11+"
            "pick-forfeitures-v1-2026-09-07"
        ),
        "lottery_has_16_teams": len(participants) == 16,
        "three_two_one_ball_distribution": ball_counts == {1: 2, 2: 7, 3: 7},
        "draft_relegated_floor_respected": all(lottery_slot[team] <= 12 for team in bottom_three),
        "draft_order_has_60_picks": len(init["draft_order"]) == 60,
        "2029_clippers_sanction_creates_59_pick_draft": (
            len(sanction_order) == expected_draft_pick_count(2029) == 59
        ),
        "2029_indiana_source_first_is_forfeited": (
            "2029_R1_IND"
            not in {pick["asset_id"] for pick in sanction_order}
        ),
        "forfeited_draft_numbering_is_contiguous": (
            [pick["overall_pick"] for pick in sanction_order]
            == list(range(1, 60))
            and sum(pick["round"] == 1 for pick in sanction_order) == 29
            and sum(pick["round"] == 2 for pick in sanction_order) == 30
        ),
        "draft_class_has_80_prospects": len(init["prospects"]) == 80,
        "ai_clock_is_120_seconds": init["clock_seconds"] == 120 and clock_before is not None,
        "sim_to_user_pick_stops": stopped_on_user,
        "draft_completes": init["phase"] == "draft_complete" and len([p for p in init["draft_order"] if p["prospect_id"]]) == 60,
        "history_archived": len(draft_history(state)) == 1,
    }
    failed = [name for name, passed in checks.items() if not passed]
    return {
        "script": DRAFT_ENGINE_VERSION,
        "lottery_rule": LOTTERY_RULE_VERSION,
        "checks": checks,
        "failed_checks": failed,
        "summary": {
            "lottery_ball_counts": ball_counts,
            "bottom_three": bottom_three,
            "simulated_to_user_pick": sim_count,
            "simulated_rest": rest_count,
        },
        "passed": not failed,
    }


if __name__ == "__main__":
    import json
    report = run_self_test()
    print(json.dumps(report, indent=2))
    if not report["passed"]:
        raise SystemExit(1)
