from __future__ import annotations

import csv
import json
import math
import statistics
import sys
from collections import Counter, defaultdict
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Iterable


AUDIT_VERSION = "player-development-league-churn-audit-v1-2026-08-11"

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
OUTPUTS = ROOT / "outputs"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from simulation_franchise_checkpoint_v1 import load_franchise_checkpoint  # noqa: E402


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def season_start_year(label: str) -> int:
    text = str(label or "").strip()
    try:
        return int(text.split("-", 1)[0])
    except (TypeError, ValueError):
        return -1


def quantile(values: Iterable[float], q: float) -> float | None:
    cleaned = sorted(
        safe_float(value)
        for value in values
        if math.isfinite(safe_float(value, float("nan")))
    )
    if not cleaned:
        return None
    if len(cleaned) == 1:
        return cleaned[0]

    position = (len(cleaned) - 1) * q
    low = int(math.floor(position))
    high = int(math.ceil(position))
    if low == high:
        return cleaned[low]

    weight = position - low
    return cleaned[low] * (1.0 - weight) + cleaned[high] * weight


def round_or_none(value: float | None, digits: int = 3) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)


def total_value(totals: Any, name: str) -> float:
    return safe_float(getattr(totals, name, 0.0))


def rate_row(totals: Any) -> dict[str, float]:
    gp = total_value(totals, "games_played")
    minutes = total_value(totals, "minutes")

    def per_game(field: str) -> float:
        return total_value(totals, field) / gp if gp > 0 else 0.0

    def per36(field: str) -> float:
        return 36.0 * total_value(totals, field) / minutes if minutes > 0 else 0.0

    fgm = total_value(totals, "field_goals_made")
    fga = total_value(totals, "field_goals_attempted")
    tpm = total_value(totals, "three_pointers_made")
    tpa = total_value(totals, "three_pointers_attempted")
    ftm = total_value(totals, "free_throws_made")
    fta = total_value(totals, "free_throws_attempted")
    pts = total_value(totals, "points")

    fg = fgm / fga if fga > 0 else 0.0
    tp = tpm / tpa if tpa > 0 else 0.0
    ft = ftm / fta if fta > 0 else 0.0
    efg = (fgm + 0.5 * tpm) / fga if fga > 0 else 0.0
    ts_denominator = 2.0 * (fga + 0.44 * fta)
    ts = pts / ts_denominator if ts_denominator > 0 else 0.0

    pts36 = per36("points")
    reb36 = per36("rebounds")
    ast36 = per36("assists")
    stl36 = per36("steals")
    blk36 = per36("blocks")
    tov36 = per36("turnovers")

    # This is an audit-only production index, not a player rating.
    production36 = (
        pts36
        + 1.20 * reb36
        + 1.50 * ast36
        + 3.00 * stl36
        + 3.00 * blk36
        - 1.30 * tov36
    )

    return {
        "gp": gp,
        "gs": total_value(totals, "games_started"),
        "mpg": minutes / gp if gp > 0 else 0.0,
        "ppg": per_game("points"),
        "rpg": per_game("rebounds"),
        "apg": per_game("assists"),
        "spg": per_game("steals"),
        "bpg": per_game("blocks"),
        "topg": per_game("turnovers"),
        "pfpg": per_game("fouls"),
        "fga_pg": fga / gp if gp > 0 else 0.0,
        "tpa_pg": tpa / gp if gp > 0 else 0.0,
        "fta_pg": fta / gp if gp > 0 else 0.0,
        "fg_pct": 100.0 * fg,
        "three_pct": 100.0 * tp,
        "ft_pct": 100.0 * ft,
        "efg_pct": 100.0 * efg,
        "ts_pct": 100.0 * ts,
        "pts36": pts36,
        "reb36": reb36,
        "ast36": ast36,
        "stl36": stl36,
        "blk36": blk36,
        "tov36": tov36,
        "production36": production36,
    }


def build_team_map(completed_games: dict[str, Any]) -> dict[str, str]:
    appearances: dict[str, Counter[str]] = defaultdict(Counter)

    for game in completed_games.values():
        for box in getattr(game, "player_box_scores", ()) or ():
            player_id = str(getattr(box, "player_id", "") or "").strip()
            team = str(
                getattr(box, "team_abbreviation", "") or ""
            ).strip().upper()
            if player_id and team:
                appearances[player_id][team] += 1

    result: dict[str, str] = {}
    for player_id, counts in appearances.items():
        if counts:
            result[player_id] = counts.most_common(1)[0][0]
    return result


def current_season_has_results(state: Any) -> bool:
    if len(getattr(state, "completed_games", {}) or {}) >= 1000:
        return True

    totals = getattr(state, "player_season_totals", {}) or {}
    max_gp = max(
        (
            safe_int(getattr(item, "games_played", 0))
            for item in totals.values()
        ),
        default=0,
    )
    return max_gp >= 60


def completed_season_sources(state: Any) -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = []

    for archive in getattr(state, "season_history", []) or []:
        label = str(getattr(archive, "season_label", "") or "").strip()
        if not label:
            continue
        sources.append(
            {
                "season_label": label,
                "player_season_totals": (
                    getattr(archive, "player_season_totals", {}) or {}
                ),
                "completed_games": (
                    getattr(archive, "completed_games", {}) or {}
                ),
                "kind": "archive",
            }
        )

    if current_season_has_results(state):
        sources.append(
            {
                "season_label": str(state.settings.season_label),
                "player_season_totals": (
                    getattr(state, "player_season_totals", {}) or {}
                ),
                "completed_games": (
                    getattr(state, "completed_games", {}) or {}
                ),
                "kind": "live",
            }
        )

    unique: dict[str, dict[str, Any]] = {}
    for source in sources:
        unique[source["season_label"]] = source

    return sorted(
        unique.values(),
        key=lambda item: season_start_year(item["season_label"]),
    )


def matching_development_entry(
    player: Any,
    prior_season: str,
    current_season: str,
) -> dict[str, Any] | None:
    matches = [
        entry
        for entry in getattr(player, "development_history", []) or []
        if str(entry.get("source_season", "")).strip() == prior_season
        and str(entry.get("target_season", "")).strip() == current_season
    ]
    return matches[-1] if matches else None


def age_bucket(age: float | None) -> str:
    if age is None or not math.isfinite(age):
        return "unknown"
    if age <= 21:
        return "19-21"
    if age <= 24:
        return "22-24"
    if age <= 27:
        return "25-27"
    if age <= 30:
        return "28-30"
    if age <= 33:
        return "31-33"
    return "34+"


def generated_player(player: Any) -> bool:
    player_id = str(getattr(player, "player_id", "") or "").strip()
    return bool(
        getattr(player, "generated", False)
        or getattr(player, "is_generated", False)
        or (
            player_id
            and not player_id.isdigit()
            and not bool(getattr(player, "synthetic", False))
        )
    )


def material_breakout(row: dict[str, Any]) -> bool:
    return bool(
        row["prior_gp"] >= 50
        and row["prior_mpg"] >= 18.0
        and row["current_gp"] >= 50
        and row["current_mpg"] >= 24.0
        and row["current_ppg"] >= 10.0
        and row["impact_gain"] >= 3.0
        and (
            row["ppg_delta"] >= 3.0
            or row["apg_delta"] >= 1.5
            or row["rpg_delta"] >= 2.0
            or (row["mpg_delta"] >= 5.0 and row["production36_delta"] >= 1.5)
            or (row["ts_delta"] >= 4.0 and row["impact_gain"] >= 2.5)
        )
    )


def material_regression(row: dict[str, Any]) -> bool:
    return bool(
        row["prior_gp"] >= 40
        and row["current_gp"] >= 30
        and (
            row["ppg_delta"] <= -3.0
            or row["apg_delta"] <= -1.5
            or row["rpg_delta"] <= -2.0
            or row["mpg_delta"] <= -5.0
            or row["production36_delta"] <= -3.0
        )
    )


def classify_rating_delta(delta: float | None) -> str:
    if delta is None:
        return "unknown"
    if delta >= 5.0:
        return "+5_or_more"
    if delta >= 3.0:
        return "+3_to_4.99"
    if delta >= 1.0:
        return "+1_to_2.99"
    if delta > -1.0:
        return "roughly_stable"
    if delta > -3.0:
        return "-1_to_-2.99"
    if delta > -5.0:
        return "-3_to_-4.99"
    return "-5_or_worse"


def summarize_bucket(rows: list[dict[str, Any]], bucket: str) -> dict[str, Any]:
    subset = [
        row
        for row in rows
        if row["age_bucket"] == bucket
        and row["has_consecutive_stats"]
    ]

    rating_deltas = [
        row["overall_delta"]
        for row in subset
        if row["overall_delta"] is not None
    ]
    ppg = [row["ppg_delta"] for row in subset]
    mpg = [row["mpg_delta"] for row in subset]
    production = [row["production36_delta"] for row in subset]

    return {
        "age_bucket": bucket,
        "players": len(subset),
        "players_with_rating_delta": len(rating_deltas),
        "avg_overall_delta": round_or_none(
            statistics.fmean(rating_deltas) if rating_deltas else None
        ),
        "median_overall_delta": round_or_none(
            statistics.median(rating_deltas) if rating_deltas else None
        ),
        "p10_overall_delta": round_or_none(quantile(rating_deltas, 0.10)),
        "p90_overall_delta": round_or_none(quantile(rating_deltas, 0.90)),
        "avg_ppg_delta": round_or_none(
            statistics.fmean(ppg) if ppg else None
        ),
        "p10_ppg_delta": round_or_none(quantile(ppg, 0.10)),
        "p90_ppg_delta": round_or_none(quantile(ppg, 0.90)),
        "avg_mpg_delta": round_or_none(
            statistics.fmean(mpg) if mpg else None
        ),
        "p10_mpg_delta": round_or_none(quantile(mpg, 0.10)),
        "p90_mpg_delta": round_or_none(quantile(mpg, 0.90)),
        "avg_production36_delta": round_or_none(
            statistics.fmean(production) if production else None
        ),
        "p10_production36_delta": round_or_none(quantile(production, 0.10)),
        "p90_production36_delta": round_or_none(quantile(production, 0.90)),
        "material_breakouts": sum(row["material_breakout"] for row in subset),
        "material_regressions": sum(row["material_regression"] for row in subset),
        "role_changes_5plus_mpg": sum(
            abs(row["mpg_delta"]) >= 5.0
            for row in subset
        ),
    }


def diagnose(rows: list[dict[str, Any]], age_rows: list[dict[str, Any]]) -> dict[str, Any]:
    consecutive = [row for row in rows if row["has_consecutive_stats"]]
    rating_rows = [
        row for row in consecutive
        if row["overall_delta"] is not None
    ]

    rating_deltas = [row["overall_delta"] for row in rating_rows]
    ppg_deltas = [row["ppg_delta"] for row in consecutive]
    mpg_deltas = [row["mpg_delta"] for row in consecutive]

    by_bucket = {
        row["age_bucket"]: row
        for row in age_rows
    }

    breakout_count = sum(row["material_breakout"] for row in consecutive)
    regression_count = sum(row["material_regression"] for row in consecutive)
    role_change_count = sum(abs(row["mpg_delta"]) >= 5.0 for row in consecutive)

    young = by_bucket.get("19-21", {})
    young_2 = by_bucket.get("22-24", {})
    old = by_bucket.get("34+", {})

    young_p90_candidates = [
        value
        for value in (
            young.get("p90_overall_delta"),
            young_2.get("p90_overall_delta"),
        )
        if value is not None
    ]
    young_p90 = max(young_p90_candidates) if young_p90_candidates else None
    old_median = old.get("median_overall_delta")

    rating_sd = (
        statistics.pstdev(rating_deltas)
        if len(rating_deltas) >= 2
        else 0.0
    )

    flags = {
        "rating_distribution_has_width": rating_sd >= 0.90,
        "young_tail_has_real_growth": (
            young_p90 is not None and young_p90 >= 1.50
        ),
        "older_players_show_median_decline": (
            old_median is not None and old_median <= -0.50
        ),
        "league_has_multiple_material_breakouts": breakout_count >= 5,
        "league_has_multiple_material_regressions": regression_count >= 5,
        "roles_move_meaningfully": role_change_count >= max(8, int(0.03 * max(len(consecutive), 1))),
        "ppg_distribution_has_breakout_tail": (
            (quantile(ppg_deltas, 0.90) or 0.0) >= 2.50
        ),
        "mpg_distribution_has_role_tail": (
            (quantile([abs(x) for x in mpg_deltas], 0.90) or 0.0) >= 4.0
        ),
    }

    concerns = [
        name
        for name, passed in flags.items()
        if not passed
    ]

    if len(concerns) >= 4:
        overall = "strong_evidence_of_low_league_churn"
    elif len(concerns) >= 2:
        overall = "some_evidence_of_compressed_development_or_roles"
    else:
        overall = "development_and_role_churn_look_broadly_healthy"

    return {
        "overall_diagnosis": overall,
        "checks": flags,
        "failed_checks": concerns,
        "consecutive_players": len(consecutive),
        "rating_delta_players": len(rating_rows),
        "material_breakouts": breakout_count,
        "material_regressions": regression_count,
        "role_changes_5plus_mpg": role_change_count,
        "rating_delta_sd": round(rating_sd, 3),
        "rating_delta_p10": round_or_none(quantile(rating_deltas, 0.10)),
        "rating_delta_median": round_or_none(quantile(rating_deltas, 0.50)),
        "rating_delta_p90": round_or_none(quantile(rating_deltas, 0.90)),
        "ppg_delta_p10": round_or_none(quantile(ppg_deltas, 0.10)),
        "ppg_delta_median": round_or_none(quantile(ppg_deltas, 0.50)),
        "ppg_delta_p90": round_or_none(quantile(ppg_deltas, 0.90)),
        "absolute_mpg_delta_p90": round_or_none(
            quantile([abs(x) for x in mpg_deltas], 0.90)
        ),
        "young_rating_p90": young_p90,
        "old_rating_median": old_median,
    }


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return

    fieldnames: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row:
            if key not in seen:
                seen.add(key)
                fieldnames.append(key)

    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    checkpoint = load_franchise_checkpoint()
    if checkpoint is None:
        raise RuntimeError(
            "No durable franchise checkpoint could be loaded."
        )

    state = checkpoint.simulation_state
    sources = completed_season_sources(state)

    if len(sources) < 2:
        raise RuntimeError(
            "At least two completed seasons are required for the churn audit. "
            f"Found {len(sources)}."
        )

    prior_source = sources[-2]
    current_source = sources[-1]

    prior_season = prior_source["season_label"]
    current_season = current_source["season_label"]

    prior_totals = prior_source["player_season_totals"]
    current_totals = current_source["player_season_totals"]

    prior_teams = build_team_map(prior_source["completed_games"])
    current_teams = build_team_map(current_source["completed_games"])

    rows: list[dict[str, Any]] = []

    all_player_ids = sorted(
        set(prior_totals)
        | set(current_totals)
        | set(getattr(state, "players", {}))
    )

    for player_id in all_player_ids:
        player = getattr(state, "players", {}).get(player_id)
        if player is None:
            continue

        prior = prior_totals.get(player_id)
        current = current_totals.get(player_id)

        prior_rates = rate_row(prior) if prior is not None else rate_row(object())
        current_rates = rate_row(current) if current is not None else rate_row(object())

        has_consecutive = bool(
            prior is not None
            and current is not None
            and prior_rates["gp"] > 0
            and current_rates["gp"] > 0
        )

        development = matching_development_entry(
            player,
            prior_season,
            current_season,
        )

        source_age = (
            safe_float(development.get("source_age"), float("nan"))
            if development
            else float("nan")
        )
        target_age = (
            safe_float(development.get("target_age"), float("nan"))
            if development
            else safe_float(getattr(player, "age", None), float("nan"))
        )

        prior_overall = (
            safe_float(development.get("current_overall_rating"))
            if development
            else None
        )
        current_overall = (
            safe_float(development.get("projected_overall_rating"))
            if development
            else safe_float(getattr(player, "overall_rating", 0.0))
        )
        overall_delta = (
            safe_float(development.get("overall_delta"))
            if development
            else None
        )

        if has_consecutive:
            ppg_delta = current_rates["ppg"] - prior_rates["ppg"]
            rpg_delta = current_rates["rpg"] - prior_rates["rpg"]
            apg_delta = current_rates["apg"] - prior_rates["apg"]
            spg_delta = current_rates["spg"] - prior_rates["spg"]
            bpg_delta = current_rates["bpg"] - prior_rates["bpg"]
            topg_delta = current_rates["topg"] - prior_rates["topg"]
            mpg_delta = current_rates["mpg"] - prior_rates["mpg"]
            ts_delta = current_rates["ts_pct"] - prior_rates["ts_pct"]
            production36_delta = (
                current_rates["production36"]
                - prior_rates["production36"]
            )
            impact_gain = (
                ppg_delta
                + 0.85 * rpg_delta
                + 1.10 * apg_delta
                + 2.25 * spg_delta
                + 2.25 * bpg_delta
                - 0.60 * topg_delta
                + 0.15 * mpg_delta
                + 0.08 * ts_delta
            )
        else:
            ppg_delta = rpg_delta = apg_delta = 0.0
            spg_delta = bpg_delta = topg_delta = 0.0
            mpg_delta = ts_delta = production36_delta = 0.0
            impact_gain = 0.0

        row = {
            "player_id": player_id,
            "player": str(getattr(player, "player_name", "") or ""),
            "position": str(getattr(player, "position", "") or ""),
            "generated_player": generated_player(player),
            "synthetic_replacement": bool(getattr(player, "synthetic", False)),
            "prior_season": prior_season,
            "current_season": current_season,
            "prior_team": prior_teams.get(player_id, ""),
            "current_team": current_teams.get(
                player_id,
                str(getattr(player, "team_abbreviation", "") or ""),
            ),
            "source_age": None if not math.isfinite(source_age) else round(source_age, 2),
            "current_age": None if not math.isfinite(target_age) else round(target_age, 2),
            "age_bucket": age_bucket(
                None if not math.isfinite(target_age) else target_age
            ),
            "prior_overall": (
                None if prior_overall is None else round(prior_overall, 3)
            ),
            "current_overall": round(current_overall, 3),
            "overall_delta": (
                None if overall_delta is None else round(overall_delta, 3)
            ),
            "overall_delta_band": classify_rating_delta(overall_delta),
            "development_performance_signal": (
                round(safe_float(development.get("performance_signal")), 4)
                if development
                else None
            ),
            "has_consecutive_stats": has_consecutive,
            "prior_gp": round(prior_rates["gp"], 0),
            "current_gp": round(current_rates["gp"], 0),
            "prior_gs": round(prior_rates["gs"], 0),
            "current_gs": round(current_rates["gs"], 0),
            "prior_mpg": round(prior_rates["mpg"], 2),
            "current_mpg": round(current_rates["mpg"], 2),
            "mpg_delta": round(mpg_delta, 2),
            "prior_ppg": round(prior_rates["ppg"], 2),
            "current_ppg": round(current_rates["ppg"], 2),
            "ppg_delta": round(ppg_delta, 2),
            "prior_rpg": round(prior_rates["rpg"], 2),
            "current_rpg": round(current_rates["rpg"], 2),
            "rpg_delta": round(rpg_delta, 2),
            "prior_apg": round(prior_rates["apg"], 2),
            "current_apg": round(current_rates["apg"], 2),
            "apg_delta": round(apg_delta, 2),
            "prior_spg": round(prior_rates["spg"], 2),
            "current_spg": round(current_rates["spg"], 2),
            "spg_delta": round(spg_delta, 2),
            "prior_bpg": round(prior_rates["bpg"], 2),
            "current_bpg": round(current_rates["bpg"], 2),
            "bpg_delta": round(bpg_delta, 2),
            "prior_topg": round(prior_rates["topg"], 2),
            "current_topg": round(current_rates["topg"], 2),
            "topg_delta": round(topg_delta, 2),
            "prior_ts_pct": round(prior_rates["ts_pct"], 2),
            "current_ts_pct": round(current_rates["ts_pct"], 2),
            "ts_delta": round(ts_delta, 2),
            "prior_production36": round(prior_rates["production36"], 2),
            "current_production36": round(current_rates["production36"], 2),
            "production36_delta": round(production36_delta, 2),
            "impact_gain": round(impact_gain, 2),
        }

        row["material_breakout"] = material_breakout(row)
        row["material_regression"] = material_regression(row)
        rows.append(row)

    buckets = [
        "19-21",
        "22-24",
        "25-27",
        "28-30",
        "31-33",
        "34+",
        "unknown",
    ]
    age_rows = [
        summarize_bucket(rows, bucket)
        for bucket in buckets
    ]

    consecutive = [
        row for row in rows if row["has_consecutive_stats"]
    ]
    rating_rows = [
        row for row in consecutive if row["overall_delta"] is not None
    ]

    rating_distribution = Counter(
        row["overall_delta_band"]
        for row in rating_rows
    )

    top_breakouts = sorted(
        consecutive,
        key=lambda row: (
            -row["impact_gain"],
            -row["ppg_delta"],
            row["player"],
        ),
    )[:30]

    top_regressions = sorted(
        consecutive,
        key=lambda row: (
            row["impact_gain"],
            row["ppg_delta"],
            row["player"],
        ),
    )[:30]

    diagnosis = diagnose(rows, age_rows)

    summary = {
        "audit_version": AUDIT_VERSION,
        "checkpoint_saved_at_utc": str(
            getattr(checkpoint, "saved_at_utc", "")
        ),
        "checkpoint_reason": str(
            getattr(checkpoint, "reason", "")
        ),
        "live_season": str(state.settings.season_label),
        "prior_season_audited": prior_season,
        "current_season_audited": current_season,
        "prior_source_kind": prior_source["kind"],
        "current_source_kind": current_source["kind"],
        "total_live_players": len(getattr(state, "players", {})),
        "players_with_consecutive_stats": len(consecutive),
        "players_with_rating_transition": len(rating_rows),
        "new_or_nonconsecutive_players": sum(
            not row["has_consecutive_stats"] for row in rows
        ),
        "generated_players_in_rows": sum(
            row["generated_player"] for row in rows
        ),
        "rating_delta_distribution": dict(rating_distribution),
        "age_bucket_summary": age_rows,
        "diagnosis": diagnosis,
        "top_breakouts": [
            {
                key: row[key]
                for key in (
                    "player_id",
                    "player",
                    "current_age",
                    "current_team",
                    "overall_delta",
                    "mpg_delta",
                    "ppg_delta",
                    "rpg_delta",
                    "apg_delta",
                    "ts_delta",
                    "production36_delta",
                    "impact_gain",
                    "material_breakout",
                )
            }
            for row in top_breakouts[:15]
        ],
        "top_regressions": [
            {
                key: row[key]
                for key in (
                    "player_id",
                    "player",
                    "current_age",
                    "current_team",
                    "overall_delta",
                    "mpg_delta",
                    "ppg_delta",
                    "rpg_delta",
                    "apg_delta",
                    "ts_delta",
                    "production36_delta",
                    "impact_gain",
                    "material_regression",
                )
            }
            for row in top_regressions[:15]
        ],
    }

    OUTPUTS.mkdir(parents=True, exist_ok=True)

    player_csv = OUTPUTS / "player_development_churn_audit_v1.csv"
    age_csv = OUTPUTS / "player_development_age_bucket_summary_v1.csv"
    breakouts_csv = OUTPUTS / "player_development_top_breakouts_v1.csv"
    regressions_csv = OUTPUTS / "player_development_top_regressions_v1.csv"
    summary_json = OUTPUTS / "player_development_churn_summary_v1.json"

    write_csv(player_csv, rows)
    write_csv(age_csv, age_rows)
    write_csv(breakouts_csv, top_breakouts)
    write_csv(regressions_csv, top_regressions)

    summary_json.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print("=" * 92)
    print("PLAYER DEVELOPMENT & LEAGUE CHURN AUDIT V1")
    print("=" * 92)
    print("Audit version:", AUDIT_VERSION)
    print("Checkpoint:", getattr(checkpoint, "saved_at_utc", ""))
    print("Season pair:", prior_season, "->", current_season)
    print("Consecutive players:", len(consecutive))
    print("Rating-transition players:", len(rating_rows))
    print()

    print("RATING DELTA DISTRIBUTION")
    for label in (
        "+5_or_more",
        "+3_to_4.99",
        "+1_to_2.99",
        "roughly_stable",
        "-1_to_-2.99",
        "-3_to_-4.99",
        "-5_or_worse",
    ):
        print(f"  {label:18s}: {rating_distribution.get(label, 0)}")

    print()
    print("AGE BUCKETS")
    for row in age_rows:
        if not row["players"]:
            continue
        print(
            f"  {row['age_bucket']:7s} | n={row['players']:3d} | "
            f"OVR med={row['median_overall_delta']} | "
            f"OVR p90={row['p90_overall_delta']} | "
            f"PPG p90={row['p90_ppg_delta']} | "
            f"breakouts={row['material_breakouts']} | "
            f"regressions={row['material_regressions']} | "
            f"5+ MPG role moves={row['role_changes_5plus_mpg']}"
        )

    print()
    print("LEAGUE CHURN DIAGNOSIS")
    print(" ", diagnosis["overall_diagnosis"])
    for name, passed in diagnosis["checks"].items():
        print(f"  {'PASS' if passed else 'FLAG'}  {name}")

    print()
    print("KEY DISTRIBUTION METRICS")
    for key in (
        "rating_delta_sd",
        "rating_delta_p10",
        "rating_delta_median",
        "rating_delta_p90",
        "ppg_delta_p10",
        "ppg_delta_median",
        "ppg_delta_p90",
        "absolute_mpg_delta_p90",
        "young_rating_p90",
        "old_rating_median",
        "material_breakouts",
        "material_regressions",
        "role_changes_5plus_mpg",
    ):
        print(f"  {key}: {diagnosis.get(key)}")

    print()
    print("TOP STATISTICAL RISERS")
    for index, row in enumerate(top_breakouts[:10], start=1):
        print(
            f"  {index:2d}. {row['player']} | age {row['current_age']} | "
            f"OVR {row['overall_delta']} | MPG {row['mpg_delta']:+.2f} | "
            f"PTS {row['ppg_delta']:+.2f} | AST {row['apg_delta']:+.2f} | "
            f"REB {row['rpg_delta']:+.2f} | impact {row['impact_gain']:+.2f}"
        )

    print()
    print("TOP STATISTICAL FALLERS")
    for index, row in enumerate(top_regressions[:10], start=1):
        print(
            f"  {index:2d}. {row['player']} | age {row['current_age']} | "
            f"OVR {row['overall_delta']} | MPG {row['mpg_delta']:+.2f} | "
            f"PTS {row['ppg_delta']:+.2f} | AST {row['apg_delta']:+.2f} | "
            f"REB {row['rpg_delta']:+.2f} | impact {row['impact_gain']:+.2f}"
        )

    print()
    print("OUTPUTS")
    for path in (
        player_csv,
        age_csv,
        breakouts_csv,
        regressions_csv,
        summary_json,
    ):
        print(" ", path)

    print()
    print("READ-ONLY AUDIT: NO FRANCHISE STATE WAS MODIFIED.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
