from __future__ import annotations

import csv
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any


PREVIEW_VERSION = "retirement-population-preview-v1-2026-08-11"
RETIREMENT_MIN_AGE = 33
ABSOLUTE_MAX_ACTIVE_AGE = 46
MIN_TEAM_ROSTER_AFTER_RETIREMENTS = 12

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
OUTPUTS = ROOT / "outputs"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from simulation_franchise_checkpoint_v1 import load_franchise_checkpoint


def clean(value: Any) -> str:
    return str(value or "").strip()


def number(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def integer(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def hash_unit(*parts: Any) -> float:
    text = "|".join(clean(part) for part in parts)
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    value = int.from_bytes(digest[:8], "big")
    return value / float((1 << 64) - 1)


def longevity_score(player_id: str) -> float:
    return hash_unit(PREVIEW_VERSION, "longevity", player_id)


def longevity_tier(score: float) -> str:
    if score >= 0.992:
        return "historic_outlier"
    if score >= 0.965:
        return "elite_longevity"
    if score >= 0.900:
        return "above_average_longevity"
    return "normal_longevity"


def age_probability(age: float) -> float:
    if age < 33:
        return 0.0
    if age < 34:
        return 0.010
    if age < 35:
        return 0.025
    if age < 36:
        return 0.060
    if age < 37:
        return 0.120
    if age < 38:
        return 0.220
    if age < 39:
        return 0.360
    if age < 40:
        return 0.520
    if age < 41:
        return 0.690
    if age < 42:
        return 0.800
    if age < 43:
        return 0.875
    if age < 44:
        return 0.925
    if age < 45:
        return 0.960
    if age < 46:
        return 0.985
    return 1.0


def season_usage(state: Any, player_id: str) -> tuple[int, float]:
    totals = getattr(state, "player_season_totals", {}).get(player_id)
    if totals is None:
        return 0, 0.0
    gp = max(0, integer(getattr(totals, "games_played", 0), 0))
    minutes = max(0.0, number(getattr(totals, "minutes", 0.0), 0.0))
    mpg = minutes / gp if gp > 0 else 0.0
    return gp, mpg


def previous_overall_delta(player: Any) -> float:
    history = list(getattr(player, "development_history", []) or [])
    if not history:
        return 0.0
    latest = history[-1]
    if isinstance(latest, dict):
        return number(latest.get("overall_delta"), 0.0)
    return number(getattr(latest, "overall_delta", 0.0), 0.0)


def contract_years(player: Any) -> int:
    contract = getattr(player, "contract", None)
    if contract is None:
        return 0
    return max(0, integer(getattr(contract, "years_remaining", 0), 0))


def retirement_probability(
    *,
    age: float,
    overall: float,
    gp: int,
    mpg: float,
    previous_delta: float,
    years_remaining: int,
    longevity: float,
    free_agent: bool,
) -> float:
    probability = age_probability(age)

    if probability <= 0.0:
        return 0.0

    if overall >= 90.0:
        probability -= 0.24
    elif overall >= 85.0:
        probability -= 0.18
    elif overall >= 80.0:
        probability -= 0.10
    elif overall < 68.0:
        probability += 0.16
    elif overall < 72.0:
        probability += 0.09

    if mpg >= 30.0:
        probability -= 0.12
    elif mpg >= 24.0:
        probability -= 0.08
    elif mpg < 6.0:
        probability += 0.12
    elif mpg < 12.0:
        probability += 0.07

    if gp >= 70:
        probability -= 0.04
    elif gp == 0:
        probability += 0.12
    elif gp < 25:
        probability += 0.07

    if previous_delta <= -5.0:
        probability += 0.10
    elif previous_delta <= -3.0:
        probability += 0.06
    elif previous_delta >= 2.0:
        probability -= 0.04

    if years_remaining >= 2:
        probability -= 0.06
    elif years_remaining == 1:
        probability -= 0.025

    if free_agent:
        probability += 0.08

    if longevity >= 0.992:
        probability -= 0.36
    elif longevity >= 0.965:
        probability -= 0.22
    elif longevity >= 0.900:
        probability -= 0.09

    if age >= ABSOLUTE_MAX_ACTIVE_AGE:
        probability = 1.0

    return round(max(0.0, min(1.0, probability)), 6)


def target_season(label: str) -> str:
    try:
        start = int(str(label).split("-", 1)[0])
    except (TypeError, ValueError):
        return ""
    return f"{start + 1}-{(start + 2) % 100:02d}"


def build_rows(state: Any) -> list[dict[str, Any]]:
    source = str(state.settings.season_label)
    target = target_season(source)
    free_agents = set(getattr(state, "free_agent_player_ids", ()) or ())
    rows: list[dict[str, Any]] = []

    for player_id, player in sorted(state.players.items()):
        if bool(getattr(player, "synthetic", False)):
            continue

        age = number(getattr(player, "age", 0.0), 0.0)
        if age < RETIREMENT_MIN_AGE:
            continue

        overall = number(getattr(player, "overall_rating", 0.0), 0.0)
        gp, mpg = season_usage(state, player_id)
        previous_delta = previous_overall_delta(player)
        years = contract_years(player)
        long_score = longevity_score(str(player_id))
        probability = retirement_probability(
            age=age,
            overall=overall,
            gp=gp,
            mpg=mpg,
            previous_delta=previous_delta,
            years_remaining=years,
            longevity=long_score,
            free_agent=player_id in free_agents,
        )
        roll = hash_unit(
            PREVIEW_VERSION,
            source,
            target,
            "retirement-roll",
            player_id,
        )

        rows.append(
            {
                "player_id": str(player_id),
                "player_name": str(getattr(player, "player_name", player_id)),
                "team": str(getattr(player, "team_abbreviation", "") or "FA"),
                "age": round(age, 2),
                "overall": round(overall, 3),
                "games_played": gp,
                "minutes_per_game": round(mpg, 2),
                "previous_overall_delta": round(previous_delta, 3),
                "contract_years_remaining": years,
                "free_agent": player_id in free_agents,
                "longevity_score": round(long_score, 6),
                "longevity_tier": longevity_tier(long_score),
                "retirement_probability": probability,
                "retirement_roll": round(roll, 6),
                "raw_retire": bool(probability > 0 and roll < probability),
                "source_season": source,
                "target_season": target,
            }
        )

    return rows


def apply_roster_floor(state: Any, rows: list[dict[str, Any]]) -> None:
    by_id = {row["player_id"]: row for row in rows}

    for team in state.teams.values():
        roster = list(team.roster_player_ids)
        proposed = [
            by_id[player_id]
            for player_id in roster
            if player_id in by_id and by_id[player_id]["raw_retire"]
        ]

        allowed = max(
            0,
            len(roster) - MIN_TEAM_ROSTER_AFTER_RETIREMENTS,
        )

        for row in rows:
            if row["player_id"] in roster:
                row.setdefault("roster_floor_protected", False)

        if len(proposed) <= allowed:
            continue

        protect_count = len(proposed) - allowed
        protected = sorted(
            proposed,
            key=lambda row: (
                row["retirement_probability"],
                -row["overall"],
                row["player_name"],
            ),
        )[:protect_count]

        for row in protected:
            row["roster_floor_protected"] = True

    for row in rows:
        row.setdefault("roster_floor_protected", False)
        row["projected_retire"] = bool(
            row["raw_retire"]
            and not row["roster_floor_protected"]
        )


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    checkpoint = load_franchise_checkpoint()
    if checkpoint is None:
        raise RuntimeError("No durable franchise checkpoint could be loaded.")

    state = checkpoint.simulation_state
    rows = build_rows(state)
    apply_roster_floor(state, rows)

    retirees = [row for row in rows if row["projected_retire"]]
    retirees.sort(
        key=lambda row: (
            -row["age"],
            -row["retirement_probability"],
            row["player_name"],
        )
    )

    age_40_before = sum(
        number(getattr(player, "age", 0.0), 0.0) >= 40
        for player in state.players.values()
    )
    retiring_ids = {row["player_id"] for row in retirees}
    age_40_after = sum(
        (
            number(getattr(player, "age", 0.0), 0.0) >= 40
            and str(player_id) not in retiring_ids
        )
        for player_id, player in state.players.items()
    )

    summary = {
        "preview_version": PREVIEW_VERSION,
        "season": state.settings.season_label,
        "target_season": target_season(state.settings.season_label),
        "players_before": len(state.players),
        "projected_retirements": len(retirees),
        "players_after_retirements": len(state.players) - len(retirees),
        "rostered_retirements": sum(not row["free_agent"] for row in retirees),
        "free_agent_retirements": sum(row["free_agent"] for row in retirees),
        "age_40_plus_before": age_40_before,
        "age_40_plus_after": age_40_after,
        "retirement_age_distribution": {},
    }

    for row in retirees:
        bucket = str(int(row["age"]))
        summary["retirement_age_distribution"][bucket] = (
            summary["retirement_age_distribution"].get(bucket, 0) + 1
        )

    OUTPUTS.mkdir(parents=True, exist_ok=True)
    all_path = OUTPUTS / "retirement_population_preview_v1.csv"
    retiree_path = OUTPUTS / "projected_retirees_v1.csv"
    summary_path = OUTPUTS / "retirement_population_preview_v1.json"

    write_csv(all_path, rows)
    write_csv(retiree_path, retirees)
    summary_path.write_text(
        json.dumps(summary, indent=2),
        encoding="utf-8",
    )

    print("=" * 92)
    print("RETIREMENT & LEAGUE POPULATION PREVIEW V1")
    print("=" * 92)
    print("Season:", state.settings.season_label, "->", summary["target_season"])
    print("Players:", summary["players_before"], "->", summary["players_after_retirements"])
    print("Projected retirements:", summary["projected_retirements"])
    print("Rostered retirements:", summary["rostered_retirements"])
    print("Free-agent retirements:", summary["free_agent_retirements"])
    print("Age 40+:", summary["age_40_plus_before"], "->", summary["age_40_plus_after"])
    print()
    print("PROJECTED RETIREES")
    for row in retirees[:40]:
        print(
            f"  {row['player_name'][:28]:28s} | "
            f"age {row['age']:4.1f} | "
            f"OVR {row['overall']:5.1f} | "
            f"GP {row['games_played']:2d} | "
            f"MPG {row['minutes_per_game']:4.1f} | "
            f"retire {row['retirement_probability'] * 100:5.1f}% | "
            f"{row['longevity_tier']}"
        )

    print()
    print("OUTPUTS")
    print(" ", all_path)
    print(" ", retiree_path)
    print(" ", summary_path)
    print()
    print("READ-ONLY PREVIEW: NO FRANCHISE STATE WAS MODIFIED.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
