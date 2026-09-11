from __future__ import annotations

import math
import re
import unicodedata

from franchise_generated_player_portraits_v1 import player_image_url
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from franchise_command_center_v1 import (
    standings_rows,
    team_logo_url,
    team_name,
)
from franchise_player_stats_v1 import regular_season_player_rows
from simulation_injury_fatigue_v1 import team_health_summary
from simulation_league_state_v1 import (
    PlayerSeasonTotals,
    SeasonArchive,
    SimulationLeagueState,
    SimulationPlayerState,
)
from simulation_postseason_v1 import (
    PostseasonStage,
    completed_postseason_games,
    get_postseason_state,
)


CAREER_AWARDS_VERSION = (
    "simulation-career-awards-v3.2-2026-08-11"
)

ROOT = Path(__file__).resolve().parents[1]
UNIFIED_PLAYER_SEASONS = (
    ROOT
    / "data"
    / "processed"
    / "unified_player_seasons_2014_15_2025_26.parquet"
)
UNIFIED_PLAYER_SEASONS_CSV = (
    ROOT
    / "data"
    / "processed"
    / "unified_player_seasons_2014_15_2025_26.csv"
)
DRAFT_HISTORY_PARQUET = (
    ROOT
    / "data"
    / "raw"
    / "draft"
    / "nba_draft_history_2014_2022.parquet"
)
DRAFT_HISTORY_CSV = (
    ROOT
    / "data"
    / "raw"
    / "draft"
    / "nba_draft_history_2014_2022.csv"
)

MAJOR_AWARD_MIN_GAMES = 65
ROOKIE_MIN_GAMES = 41
ALL_ROOKIE_MIN_GAMES = 20
SIXTH_MAN_MIN_GAMES = 50
MIP_PRIOR_MIN_GAMES = 50
MIP_PRIOR_MIN_MPG = 18.0
MIP_CURRENT_MIN_GAMES = 50
MIP_CURRENT_MIN_MPG = 24.0
MIP_CURRENT_MIN_PPG = 10.0
MIP_MIN_IMPACT_GAIN = 3.0
MIP_MIN_BREAKOUT_SCORE = 12.0

AWARD_META = {
    "mvp": {
        "label": "Most Valuable Player",
        "short": "MVP",
        "icon": "🏆",
        "trophy": "Michael Jordan Trophy",
        "accent": "#f5b301",
    },
    "dpoy": {
        "label": "Defensive Player of the Year",
        "short": "DPOY",
        "icon": "🛡️",
        "trophy": "Hakeem Olajuwon Trophy",
        "accent": "#38bdf8",
    },
    "roy": {
        "label": "Rookie of the Year",
        "short": "ROY",
        "icon": "🌟",
        "trophy": "Wilt Chamberlain Trophy",
        "accent": "#22c55e",
    },
    "smoy": {
        "label": "Sixth Man of the Year",
        "short": "6MOY",
        "icon": "🔥",
        "trophy": "John Havlicek Trophy",
        "accent": "#c084fc",
    },
    "mip": {
        "label": "Most Improved Player",
        "short": "MIP",
        "icon": "📈",
        "trophy": "George Mikan Trophy",
        "accent": "#fb7185",
    },
    "clutch": {
        "label": "Clutch Player of the Year",
        "short": "CLUTCH",
        "icon": "⏱️",
        "trophy": "Jerry West Trophy",
        "accent": "#f97316",
    },
    "coach": {
        "label": "Coach of the Year",
        "short": "COY",
        "icon": "🎯",
        "trophy": "Red Auerbach Trophy",
        "accent": "#14b8a6",
    },
    "executive": {
        "label": "Executive of the Year",
        "short": "EOTY",
        "icon": "🧠",
        "trophy": "NBA Executive of the Year",
        "accent": "#60a5fa",
    },
}

PLAYOFF_AWARD_META = {
    "east_cf_mvp": {
        "label": "Eastern Conference Finals MVP",
        "short": "ECF MVP",
        "icon": "🕊️",
        "trophy": "Larry Bird Trophy",
        "accent": "#60a5fa",
    },
    "west_cf_mvp": {
        "label": "Western Conference Finals MVP",
        "short": "WCF MVP",
        "icon": "✨",
        "trophy": "Magic Johnson Trophy",
        "accent": "#f59e0b",
    },
    "finals_mvp": {
        "label": "NBA Finals MVP",
        "short": "FINALS MVP",
        "icon": "👑",
        "trophy": "Bill Russell Trophy",
        "accent": "#facc15",
    },
}


def season_start_from_label(value: Any) -> int | None:
    text = str(value or "").strip()
    match = re.match(r"^(\d{4})[-_/]", text)
    if match:
        return int(match.group(1))
    match = re.match(r"^(\d{4})$", text)
    if match:
        return int(match.group(1))
    return None


def season_label_from_start(start: int) -> str:
    return f"{int(start)}-{str(int(start) + 1)[-2:]}"


def normalized_name(value: Any) -> str:
    text = unicodedata.normalize(
        "NFKD",
        str(value or ""),
    )
    text = "".join(
        character
        for character in text
        if not unicodedata.combining(character)
    )
    text = re.sub(r"[^a-zA-Z0-9]+", " ", text).strip().lower()
    suffixes = {"jr", "sr", "ii", "iii", "iv"}
    parts = [part for part in text.split() if part not in suffixes]
    return " ".join(parts)


def player_headshot_url(
    player_id: Any,
    team: str = "",
    player_name: str = "",
    *,
    generated: bool | None = None,
) -> str:
    """Return an official NBA headshot or a deterministic generated portrait."""
    return player_image_url(
        player_id,
        team=team,
        player_name=player_name,
        generated=generated,
    )


def _safe_number(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return float(default)
    return number if math.isfinite(number) else float(default)


def _load_frame(
    parquet_path: Path,
    csv_path: Path,
) -> pd.DataFrame:
    if parquet_path.exists():
        return pd.read_parquet(parquet_path)
    if csv_path.exists():
        return pd.read_csv(csv_path)
    return pd.DataFrame()


def load_unified_player_history() -> pd.DataFrame:
    frame = _load_frame(
        UNIFIED_PLAYER_SEASONS,
        UNIFIED_PLAYER_SEASONS_CSV,
    )
    if frame.empty:
        return frame

    required = {"player_id", "player_name", "season"}
    if not required.issubset(frame.columns):
        return pd.DataFrame()

    frame = frame.copy()
    if "season_start" not in frame.columns:
        frame["season_start"] = frame["season"].map(
            season_start_from_label
        )
    frame["season_start"] = pd.to_numeric(
        frame["season_start"],
        errors="coerce",
    )
    frame["player_id_key"] = (
        frame["player_id"]
        .astype(str)
        .str.replace(r"\.0$", "", regex=True)
        .str.strip()
    )
    frame["player_name_key"] = frame["player_name"].map(
        normalized_name
    )
    return frame


def load_draft_history() -> pd.DataFrame:
    frame = _load_frame(
        DRAFT_HISTORY_PARQUET,
        DRAFT_HISTORY_CSV,
    )
    if frame.empty:
        return frame

    frame = frame.copy()
    frame.columns = [
        str(column).strip().lower()
        for column in frame.columns
    ]
    id_column = next(
        (
            column
            for column in ("person_id", "player_id")
            if column in frame.columns
        ),
        None,
    )
    if id_column is None or "draft_year" not in frame.columns:
        return pd.DataFrame()

    frame["player_id_key"] = (
        frame[id_column]
        .astype(str)
        .str.replace(r"\.0$", "", regex=True)
        .str.strip()
    )
    return frame


def _draft_row_lookup() -> dict[str, dict[str, Any]]:
    frame = load_draft_history()
    if frame.empty:
        return {}
    rows = {}
    for record in frame.to_dict(orient="records"):
        key = str(record.get("player_id_key", "")).strip()
        if key:
            rows[key] = record
    return rows


def _history_lookup() -> tuple[
    dict[str, pd.DataFrame],
    dict[str, pd.DataFrame],
]:
    frame = load_unified_player_history()
    if frame.empty:
        return {}, {}

    by_id = {
        str(key): group.copy()
        for key, group in frame.groupby("player_id_key")
    }
    by_name = {
        str(key): group.copy()
        for key, group in frame.groupby("player_name_key")
    }
    return by_id, by_name


def ensure_career_metadata(
    state: SimulationLeagueState,
) -> dict[str, int]:
    """Attach durable career metadata to live player objects.

    The project checkpoint system preserves extra runtime attributes on
    dataclass objects, so these fields survive ordinary checkpoint saves without
    changing the checkpoint format. Future generated prospects can set the same
    attributes when the draft engine is added.
    """

    current_start = season_start_from_label(
        state.settings.season_label
    )
    if current_start is None:
        raise ValueError(
            "Could not parse current franchise season label: "
            f"{state.settings.season_label}"
        )

    history_by_id, history_by_name = _history_lookup()
    draft_by_id = _draft_row_lookup()
    counts = {
        "players": 0,
        "historical_matches": 0,
        "draft_matches": 0,
        "current_rookies": 0,
        "newcomer_rookies": 0,
    }

    for player in state.players.values():
        counts["players"] += 1
        player_id = str(player.player_id or "").strip()
        history = history_by_id.get(player_id)
        if history is None:
            history = history_by_name.get(
                normalized_name(player.player_name)
            )

        existing_rookie_start = getattr(
            player,
            "rookie_season_start",
            None,
        )
        try:
            rookie_start: int | None = (
                int(existing_rookie_start)
                if existing_rookie_start is not None
                else None
            )
        except (TypeError, ValueError):
            rookie_start = None
        metadata_source = str(
            getattr(player, "career_metadata_source", "")
            or ""
        )

        if rookie_start is None and history is not None and not history.empty:
            valid_starts = pd.to_numeric(
                history["season_start"],
                errors="coerce",
            ).dropna()
            if not valid_starts.empty:
                rookie_start = int(valid_starts.min())
                metadata_source = "unified_player_history"
                counts["historical_matches"] += 1

        draft_row = draft_by_id.get(player_id)
        draft_year: int | None = None
        draft_round: str = ""
        draft_pick: int | None = None
        drafted_by: str = ""

        if draft_row:
            try:
                draft_year = int(float(draft_row.get("draft_year")))
            except (TypeError, ValueError):
                draft_year = None
            draft_round = str(
                draft_row.get("round_number", "")
                or draft_row.get("round", "")
                or ""
            ).strip()
            pick_value = (
                draft_row.get("overall_pick")
                or draft_row.get("overall_pick_number")
                or draft_row.get("overall_pick_no")
            )
            try:
                draft_pick = int(float(pick_value))
            except (TypeError, ValueError):
                draft_pick = None
            drafted_by = str(
                draft_row.get("team_abbreviation", "")
                or draft_row.get("team", "")
                or ""
            ).strip()
            counts["draft_matches"] += 1

        if rookie_start is None and draft_year is not None:
            rookie_start = draft_year
            metadata_source = "draft_history"

        # Current 2026 draft rookies are not present in the historical file.
        # Treat only young, history-free NBA newcomers as rookies. This catches
        # actual new rookies while avoiding the old V1 mistake of treating every
        # young veteran as a rookie.
        newcomer_rookie = False
        if rookie_start is None:
            age = _safe_number(getattr(player, "age", None), 99.0)
            if (
                current_start >= 2026
                and age <= 24.5
                and not bool(getattr(player, "synthetic", False))
            ):
                rookie_start = current_start
                metadata_source = "current_young_newcomer"
                newcomer_rookie = True
                counts["newcomer_rookies"] += 1

        rookie_season = (
            season_label_from_start(rookie_start)
            if rookie_start is not None
            else ""
        )
        years_of_service = (
            max(0, current_start - rookie_start)
            if rookie_start is not None
            else None
        )

        setattr(player, "rookie_season", rookie_season)
        setattr(player, "rookie_season_start", rookie_start)
        setattr(player, "draft_year", draft_year)
        setattr(player, "draft_round", draft_round)
        setattr(player, "draft_pick", draft_pick)
        setattr(player, "drafted_by", drafted_by)
        setattr(player, "years_of_service", years_of_service)
        setattr(player, "career_metadata_source", metadata_source)
        setattr(
            player,
            "rookie_eligible",
            rookie_start == current_start,
        )
        setattr(
            player,
            "generated_prospect",
            bool(getattr(player, "generated_prospect", False)),
        )

        if rookie_start == current_start:
            counts["current_rookies"] += 1

    setattr(
        state,
        "career_metadata_version",
        CAREER_AWARDS_VERSION,
    )
    setattr(
        state,
        "career_metadata_season",
        state.settings.season_label,
    )
    return counts


def is_rookie_eligible(
    player: SimulationPlayerState,
    season_label: str,
) -> bool:
    return bool(
        str(getattr(player, "rookie_season", ""))
        == str(season_label)
    )


def _player_lookup(
    state: SimulationLeagueState,
) -> dict[tuple[str, str], SimulationPlayerState]:
    return {
        (
            normalized_name(player.player_name),
            str(player.team_abbreviation),
        ): player
        for player in state.players.values()
    }


def _qualified_regular_rows(
    state: SimulationLeagueState,
) -> list[dict[str, Any]]:
    ensure_career_metadata(state)
    max_games = max(
        (
            standing.games_played
            for standing in state.standings.values()
        ),
        default=0,
    )
    # Load the whole played-player pool first. Individual awards apply
    # their own availability thresholds below. Keeping this pool broad is
    # important because All-Rookie teams need more candidates than the ROY
    # ballot and should not disappear just because fewer than ten rookies
    # reached the stricter ROY workload threshold.
    minimum_games = 1
    rows = regular_season_player_rows(
        state,
        minimum_games=minimum_games,
        limit=max(150, len(state.players)),
    )
    standings = {
        str(row["Team"]): row
        for row in standings_rows(state)
    }
    lookup = _player_lookup(state)
    enriched = []
    for row in rows:
        team = str(row.get("Team", ""))
        player = lookup.get(
            (normalized_name(row.get("Player", "")), team)
        )
        if player is None:
            continue
        standing = standings.get(team, {})
        enriched.append(
            {
                **row,
                "_player": player,
                "_player_id": player.player_id,
                "_age": _safe_number(player.age, 0.0),
                "_overall": _safe_number(player.overall_rating, 0.0),
                "_wins": int(standing.get("W", 0) or 0),
                "_losses": int(standing.get("L", 0) or 0),
                "_diff": _safe_number(standing.get("Diff", 0.0)),
                "_rank": int(standing.get("Rank", 30) or 30),
                "_rookie": is_rookie_eligible(
                    player,
                    state.settings.season_label,
                ),
            }
        )
    return enriched


def _prior_season_row_from_archive(
    archive: SeasonArchive,
    player_id: str,
) -> dict[str, float] | None:
    totals = archive.player_season_totals.get(player_id)
    if totals is None or totals.games_played <= 0:
        return None

    gp = float(totals.games_played)
    fga = float(getattr(totals, "field_goals_attempted", 0) or 0)
    fta = float(getattr(totals, "free_throws_attempted", 0) or 0)
    denominator = 2.0 * (fga + 0.44 * fta)
    true_shooting = (
        100.0 * float(totals.points) / denominator
        if denominator > 0
        else 0.0
    )

    return {
        "GP": gp,
        "MIN": totals.minutes / gp,
        "PTS": totals.points / gp,
        "REB": totals.rebounds / gp,
        "AST": totals.assists / gp,
        "STL": totals.steals / gp,
        "BLK": totals.blocks / gp,
        "TO": totals.turnovers / gp,
        "TS%": true_shooting,
    }


def _prior_season_row_from_history(
    player: SimulationPlayerState,
    prior_start: int,
) -> dict[str, float] | None:
    frame = load_unified_player_history()
    if frame.empty:
        return None

    player_id = str(player.player_id or "").strip()
    matched = frame.loc[
        frame["player_id_key"].eq(player_id)
        & frame["season_start"].eq(prior_start)
    ]
    if matched.empty:
        name_key = normalized_name(player.player_name)
        matched = frame.loc[
            frame["player_name_key"].eq(name_key)
            & frame["season_start"].eq(prior_start)
        ]
    if matched.empty:
        return None

    row = matched.iloc[0]
    mapping = {
        "GP": "base_gp",
        "MIN": "minutes_per_game",
        "PTS": "points_per_game",
        "REB": "rebounds_per_game",
        "AST": "assists_per_game",
        "STL": "steals_per_game",
        "BLK": "blocks_per_game",
        "TO": "turnovers_per_game",
    }

    result: dict[str, float] = {}
    for target, source_column in mapping.items():
        if source_column in matched.columns:
            result[target] = _safe_number(row.get(source_column))

    direct_ts_columns = (
        "true_shooting_percentage",
        "ts_pct",
        "base_ts_pct",
        "true_shooting_pct",
    )
    for column in direct_ts_columns:
        if column in matched.columns:
            value = _safe_number(row.get(column))
            if 0.0 < value <= 1.5:
                value *= 100.0
            if value > 0.0:
                result["TS%"] = value
                break

    if "TS%" not in result:
        points = _safe_number(
            row.get("base_pts")
            if "base_pts" in matched.columns
            else row.get("points_per_game")
        )
        fga = _safe_number(
            row.get("base_fga")
            if "base_fga" in matched.columns
            else row.get("field_goals_attempted_per_game")
        )
        fta = _safe_number(
            row.get("base_fta")
            if "base_fta" in matched.columns
            else row.get("free_throws_attempted_per_game")
        )
        denominator = 2.0 * (fga + 0.44 * fta)
        if denominator > 0:
            result["TS%"] = 100.0 * points / denominator

    return result if result else None


def prior_season_row(
    state: SimulationLeagueState,
    player: SimulationPlayerState,
) -> dict[str, float] | None:
    current_start = season_start_from_label(state.settings.season_label)
    if current_start is None:
        return None
    prior_start = current_start - 1
    prior_label = season_label_from_start(prior_start)

    for archive in reversed(state.season_history):
        if archive.season_label == prior_label:
            result = _prior_season_row_from_archive(
                archive,
                player.player_id,
            )
            if result:
                return result

    return _prior_season_row_from_history(
        player,
        prior_start,
    )


def _award_candidate(
    key: str,
    row: dict[str, Any],
    score: float,
    *,
    detail: str = "",
) -> dict[str, Any]:
    player = row["_player"]
    return {
        "award_key": key,
        "subject_name": player.player_name,
        "subject_team": player.team_abbreviation,
        "subject_pos": player.position,
        "image_url": player_headshot_url(
            player.player_id,
            player.team_abbreviation,
            player.player_name,
            generated=bool(
                getattr(player, "synthetic", False)
                or str(
                    getattr(
                        player,
                        "rating_source",
                        "",
                    )
                    or ""
                ).startswith("generated-")
            ),
        ),
        "award_score": float(score),
        "summary": row,
        "detail": detail,
        "player_id": player.player_id,
    }


def _rank_candidates(
    candidates: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    return sorted(
        candidates,
        key=lambda item: (
            -float(item.get("award_score", 0.0)),
            str(item.get("subject_name", "")),
        ),
    )


def _wins_bonus(
    row: dict[str, Any],
    max_wins: int,
    scale: float,
) -> float:
    return scale * row["_wins"] / max(1, max_wins)


def _efficiency_bonus(row: dict[str, Any]) -> float:
    return max(0.0, _safe_number(row.get("TS%")) - 54.0)


def _mip_impact_value(stats: dict[str, Any]) -> float:
    """Compact all-around production used only for season-over-season change."""
    return (
        _safe_number(stats.get("PTS"))
        + _safe_number(stats.get("AST")) * 1.25
        + _safe_number(stats.get("REB")) * 0.90
        + _safe_number(stats.get("STL")) * 2.25
        + _safe_number(stats.get("BLK")) * 2.00
        - _safe_number(stats.get("TO")) * 0.55
    )


def _mip_prior_baseline_eligible(
    prior: dict[str, Any] | None,
) -> bool:
    if not prior:
        return False
    return bool(
        _safe_number(prior.get("GP")) >= MIP_PRIOR_MIN_GAMES
        and _safe_number(prior.get("MIN")) >= MIP_PRIOR_MIN_MPG
    )


def _mip_current_baseline_eligible(
    current: dict[str, Any],
) -> bool:
    """Require the winner to have become a real rotation-level contributor."""
    return bool(
        _safe_number(current.get("GP")) >= MIP_CURRENT_MIN_GAMES
        and _safe_number(current.get("MIN")) >= MIP_CURRENT_MIN_MPG
        and _safe_number(current.get("PTS")) >= MIP_CURRENT_MIN_PPG
    )


def _mip_has_material_breakout(
    metrics: dict[str, float],
) -> bool:
    """Reject tiny role bumps even when they happen to lead a quiet season."""
    scoring_jump = metrics["pts_delta"] >= 3.0
    creation_jump = metrics["ast_delta"] >= 1.5
    rebounding_jump = metrics["reb_delta"] >= 2.0
    defensive_jump = (
        metrics["stl_delta"] + metrics["blk_delta"]
    ) >= 0.8
    role_and_rate_jump = bool(
        metrics["min_delta"] >= 5.0
        and metrics["per36_gain"] >= 1.5
    )
    efficiency_breakout = bool(
        metrics["ts_delta"] >= 4.0
        and metrics["impact_gain"] >= 2.5
    )

    return bool(
        metrics["impact_gain"] >= MIP_MIN_IMPACT_GAIN
        and (
            scoring_jump
            or creation_jump
            or rebounding_jump
            or defensive_jump
            or role_and_rate_jump
            or efficiency_breakout
        )
    )


def _mip_breakout_metrics_v3(
    current: dict[str, Any],
    prior: dict[str, Any],
) -> dict[str, float]:
    deltas = {
        "pts_delta": _safe_number(current.get("PTS")) - _safe_number(prior.get("PTS")),
        "ast_delta": _safe_number(current.get("AST")) - _safe_number(prior.get("AST")),
        "reb_delta": _safe_number(current.get("REB")) - _safe_number(prior.get("REB")),
        "stl_delta": _safe_number(current.get("STL")) - _safe_number(prior.get("STL")),
        "blk_delta": _safe_number(current.get("BLK")) - _safe_number(prior.get("BLK")),
        "to_delta": _safe_number(current.get("TO")) - _safe_number(prior.get("TO")),
        "min_delta": _safe_number(current.get("MIN")) - _safe_number(prior.get("MIN")),
        "ts_delta": _safe_number(current.get("TS%")) - _safe_number(prior.get("TS%")),
    }

    current_impact = _mip_impact_value(current)
    prior_impact = _mip_impact_value(prior)
    impact_gain = current_impact - prior_impact

    current_min = max(1.0, _safe_number(current.get("MIN")))
    prior_min = max(1.0, _safe_number(prior.get("MIN")))
    current_per36 = current_impact * 36.0 / current_min
    prior_per36 = prior_impact * 36.0 / prior_min
    per36_gain = current_per36 - prior_per36
    relative_gain = impact_gain / max(8.0, prior_impact)

    direct_stat_jump = (
        deltas["pts_delta"] * 3.00
        + deltas["ast_delta"] * 2.00
        + deltas["reb_delta"] * 1.25
        + deltas["stl_delta"] * 4.00
        + deltas["blk_delta"] * 4.00
        - max(0.0, deltas["to_delta"]) * 0.50
    )
    rate_component = max(-6.0, min(14.0, per36_gain)) * 0.60
    efficiency_component = max(-6.0, min(10.0, deltas["ts_delta"])) * 0.40
    role_component = max(-6.0, min(12.0, deltas["min_delta"])) * 0.15
    relative_component = max(-0.50, min(1.25, relative_gain)) * 8.0

    score = (
        direct_stat_jump
        + rate_component
        + efficiency_component
        + role_component
        + relative_component
    )

    return {
        **deltas,
        "current_impact": current_impact,
        "prior_impact": prior_impact,
        "impact_gain": impact_gain,
        "per36_gain": per36_gain,
        "relative_gain": relative_gain,
        "breakout_score": score,
    }


def _signed(value: float, digits: int = 1) -> str:
    return f"{value:+.{digits}f}"


def _mip_detail_v3(
    prior: dict[str, Any],
    current: dict[str, Any],
    metrics: dict[str, float],
) -> str:
    pieces = [
        f"{_signed(metrics['pts_delta'])} PTS",
        f"{_signed(metrics['ast_delta'])} AST",
        f"{_signed(metrics['reb_delta'])} REB",
        f"{_signed(metrics['min_delta'])} MIN",
    ]
    if _safe_number(prior.get("TS%")) > 0 and _safe_number(current.get("TS%")) > 0:
        pieces.append(f"{_signed(metrics['ts_delta'])} TS")
    return (
        " · ".join(pieces)
        + f" · prior baseline {int(_safe_number(prior.get('GP')))} GP / "
        f"{_safe_number(prior.get('MIN')):.1f} MPG"
    )


def build_regular_awards_v2(
    state: SimulationLeagueState,
) -> dict[str, Any]:
    pool = _qualified_regular_rows(state)
    if not pool:
        return {
            "ready": False,
            "reason": "No qualified regular-season player sample is available.",
        }

    max_wins = max((row["_wins"] for row in pool), default=1)
    major = [
        row
        for row in pool
        if int(_safe_number(row.get("GP")))
        >= min(
            MAJOR_AWARD_MIN_GAMES,
            max(
                (
                    standing.games_played
                    for standing in state.standings.values()
                ),
                default=MAJOR_AWARD_MIN_GAMES,
            ),
        )
    ]
    if not major:
        major = pool

    mvp = _rank_candidates(
        _award_candidate(
            "mvp",
            row,
            _safe_number(row.get("PTS")) * 1.65
            + _safe_number(row.get("AST")) * 1.15
            + _safe_number(row.get("REB")) * 0.78
            + _safe_number(row.get("STL")) * 2.0
            + _safe_number(row.get("BLK")) * 1.7
            + _efficiency_bonus(row) * 0.85
            + _wins_bonus(row, max_wins, 18.0)
            + _safe_number(row.get("MIN")) * 0.14,
        )
        for row in major
    )

    dpoy = _rank_candidates(
        _award_candidate(
            "dpoy",
            row,
            _safe_number(row.get("BLK")) * 6.2
            + _safe_number(row.get("STL")) * 6.1
            + _safe_number(row.get("REB")) * 1.1
            + _wins_bonus(row, max_wins, 13.0)
            + _safe_number(row.get("MIN")) * 0.1,
        )
        for row in major
    )

    max_team_games = max(
        (
            standing.games_played
            for standing in state.standings.values()
        ),
        default=0,
    )
    rookie_threshold = min(
        ROOKIE_MIN_GAMES,
        max(1, max_team_games),
    )
    rookie_rows = [
        row
        for row in pool
        if row["_rookie"]
    ]
    roy_rows = [
        row
        for row in rookie_rows
        if int(_safe_number(row.get("GP")))
        >= rookie_threshold
    ]

    def rookie_candidate(
        row: dict[str, Any],
    ) -> dict[str, Any]:
        return _award_candidate(
            "roy",
            row,
            _safe_number(row.get("PTS")) * 1.45
            + _safe_number(row.get("AST")) * 1.0
            + _safe_number(row.get("REB")) * 0.85
            + _safe_number(row.get("STL")) * 1.8
            + _safe_number(row.get("BLK")) * 1.55
            + _efficiency_bonus(row) * 0.45
            + _wins_bonus(row, max_wins, 8.0),
            detail=(
                "Rookie season: "
                f"{getattr(row['_player'], 'rookie_season', '')}"
            ),
        )

    roy = _rank_candidates(
        rookie_candidate(row)
        for row in roy_rows
    )

    # All-Rookie honors intentionally use a broader participation floor than
    # Rookie of the Year. The goal is to select the ten best rookies who
    # meaningfully appeared in the season, not to duplicate the ROY gate.
    all_rookie_threshold = min(
        ALL_ROOKIE_MIN_GAMES,
        max(1, max_team_games),
    )
    all_rookie_rows = [
        row
        for row in rookie_rows
        if int(_safe_number(row.get("GP")))
        >= all_rookie_threshold
    ]
    if len(all_rookie_rows) < 10:
        included = {
            str(row["_player_id"])
            for row in all_rookie_rows
        }
        fallback_rows = [
            row
            for row in rookie_rows
            if (
                int(_safe_number(row.get("GP"))) >= 1
                and str(row["_player_id"]) not in included
            )
        ]
        all_rookie_rows.extend(
            fallback_rows
        )

    all_rookie_ranked = _rank_candidates(
        rookie_candidate(row)
        for row in all_rookie_rows
    )


    sixth = [
        row
        for row in pool
        if int(_safe_number(row.get("GP"))) >= SIXTH_MAN_MIN_GAMES
        and int(_safe_number(row.get("GS")))
        < (
            int(_safe_number(row.get("GP")))
            - int(_safe_number(row.get("GS")))
        )
    ]
    smoy = _rank_candidates(
        _award_candidate(
            "smoy",
            row,
            _safe_number(row.get("PTS")) * 1.55
            + _safe_number(row.get("AST")) * 0.9
            + _safe_number(row.get("REB")) * 0.55
            + _efficiency_bonus(row) * 0.5
            + _wins_bonus(row, max_wins, 10.0)
            + _safe_number(row.get("MIN")) * 0.24,
            detail=(
                f"Bench games: "
                f"{int(_safe_number(row.get('GP')) - _safe_number(row.get('GS')))}"
            ),
        )
        for row in sixth
    )

    mip_candidates = []
    for row in major:
        player = row["_player"]
        if row["_rookie"]:
            continue

        prior = prior_season_row(state, player)
        if not _mip_prior_baseline_eligible(prior):
            continue
        if not _mip_current_baseline_eligible(row):
            continue

        metrics = _mip_breakout_metrics_v3(
            row,
            prior,
        )
        score = metrics["breakout_score"]

        # Most Improved should represent a genuine breakout, not simply the
        # largest tiny increase in an unusually stagnant league season.
        if (
            score < MIP_MIN_BREAKOUT_SCORE
            or not _mip_has_material_breakout(metrics)
        ):
            continue

        candidate = _award_candidate(
            "mip",
            row,
            score,
            detail=_mip_detail_v3(
                prior,
                row,
                metrics,
            ),
        )
        candidate["mip_metrics"] = metrics
        candidate["mip_prior"] = dict(prior)
        mip_candidates.append(candidate)

    mip = _rank_candidates(mip_candidates)

    clutch = _rank_candidates(
        _award_candidate(
            "clutch",
            row,
            _safe_number(row.get("PTS")) * 1.18
            + _safe_number(row.get("FT%")) * 0.08
            + _safe_number(row.get("3P%")) * 0.06
            + _wins_bonus(row, max_wins, 13.0)
            + _safe_number(row.get("AST")) * 0.45,
        )
        for row in major
    )

    standings = standings_rows(state)
    coach = []
    executive = []
    league_average_wins = sum(
        int(row.get("W", 0) or 0)
        for row in standings
    ) / max(1, len(standings))
    for row in standings:
        team = str(row.get("Team", ""))
        wins = _safe_number(row.get("W"))
        diff = _safe_number(row.get("Diff"))
        rank = _safe_number(row.get("Rank"), 30.0)
        health = team_health_summary(
            state,
            team,
            day_index=state.current_day_index,
        )
        adversity = (
            _safe_number(health.get("out")) * 0.7
            + _safe_number(health.get("limited")) * 0.25
        )
        coach.append(
            {
                "award_key": "coach",
                "subject_name": f"{team_name(team)} coaching staff",
                "subject_team": team,
                "image_url": team_logo_url(team),
                "award_score": (
                    (wins - league_average_wins) * 2.0
                    + diff * 0.22
                    + max(0.0, 31.0 - rank) * 0.7
                    + adversity
                ),
                "summary": row,
                "detail": "Team results, point differential, and injury adversity.",
            }
        )
        executive.append(
            {
                "award_key": "executive",
                "subject_name": f"{team_name(team)} front office",
                "subject_team": team,
                "image_url": team_logo_url(team),
                "award_score": (
                    (wins - league_average_wins) * 1.6
                    + diff * 0.18
                    + max(0.0, 31.0 - rank) * 0.55
                    + max(0.0, 42.0 - wins) * 0.05
                ),
                "summary": row,
                "detail": (
                    "Team trajectory proxy. Trade, draft, and contract value "
                    "will become explicit inputs as those franchise systems mature."
                ),
            }
        )
    coach = _rank_candidates(coach)
    executive = _rank_candidates(executive)

    awards = {
        "mvp": mvp,
        "dpoy": dpoy,
        "roy": roy,
        "smoy": smoy,
        "mip": mip,
        "clutch": clutch,
        "coach": coach,
        "executive": executive,
    }

    all_nba = {
        "All-NBA First Team": mvp[:5],
        "All-NBA Second Team": mvp[5:10],
        "All-NBA Third Team": mvp[10:15],
    }
    all_defense = {
        "All-Defensive First Team": dpoy[:5],
        "All-Defensive Second Team": dpoy[5:10],
    }
    all_rookie = {
        "All-Rookie First Team": all_rookie_ranked[:5],
        "All-Rookie Second Team": all_rookie_ranked[5:10],
    }

    return {
        "ready": True,
        "awards": awards,
        "all_nba": all_nba,
        "all_defense": all_defense,
        "all_rookie": all_rookie,
        "rookie_count": len(rookie_rows),
        "rookie_award_eligible_count": len(roy_rows),
        "all_rookie_eligible_count": len(all_rookie_ranked),
        "metadata_version": CAREER_AWARDS_VERSION,
    }


def _postseason_player_aggregates(
    state: SimulationLeagueState,
    *,
    stage: PostseasonStage,
    conference: str | None = None,
    team: str | None = None,
) -> dict[str, dict[str, Any]]:
    players = state.players
    rows: dict[str, dict[str, Any]] = {}
    for game, completed in completed_postseason_games(state):
        if game.stage != stage:
            continue
        if conference is not None and str(game.conference) != conference:
            continue
        for box in completed.player_box_scores:
            if team is not None and box.team_abbreviation != team:
                continue
            row = rows.setdefault(
                box.player_id,
                {
                    "player_id": box.player_id,
                    "player_name": (
                        players[box.player_id].player_name
                        if box.player_id in players
                        else box.player_id
                    ),
                    "team": box.team_abbreviation,
                    "games": 0,
                    "minutes": 0.0,
                    "points": 0,
                    "rebounds": 0,
                    "assists": 0,
                    "steals": 0,
                    "blocks": 0,
                    "turnovers": 0,
                },
            )
            row["games"] += 1
            row["minutes"] += box.minutes
            row["points"] += box.points
            row["rebounds"] += box.rebounds
            row["assists"] += box.assists
            row["steals"] += box.steals
            row["blocks"] += box.blocks
            row["turnovers"] += box.turnovers
    return rows


def _postseason_award_winner(
    rows: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    ranked = []
    for row in rows.values():
        gp = max(1, int(row["games"]))
        ppg = row["points"] / gp
        rpg = row["rebounds"] / gp
        apg = row["assists"] / gp
        spg = row["steals"] / gp
        bpg = row["blocks"] / gp
        tov = row["turnovers"] / gp
        score = (
            ppg * 1.55
            + rpg * 0.82
            + apg * 1.05
            + spg * 2.1
            + bpg * 2.1
            - tov * 0.35
        )
        ranked.append(
            {
                **row,
                "PPG": ppg,
                "RPG": rpg,
                "APG": apg,
                "SPG": spg,
                "BPG": bpg,
                "award_score": score,
                "image_url": player_headshot_url(
                    row["player_id"],
                    row.get("team", ""),
                    row.get("player_name", ""),
                ),
            }
        )
    ranked.sort(
        key=lambda item: (
            -item["award_score"],
            item["player_name"],
        )
    )
    return ranked[0] if ranked else None


def build_playoff_honors_v2(
    state: SimulationLeagueState,
) -> dict[str, Any]:
    postseason = get_postseason_state(
        state,
        required=False,
    )
    if postseason is None:
        return {"ready": False}

    honors: dict[str, Any] = {
        "ready": True,
        "champion": postseason.champion,
        "runner_up": postseason.runner_up,
        "conference_champions": dict(
            postseason.conference_champions
        ),
    }

    for conference, key in (
        ("East", "east_cf_mvp"),
        ("West", "west_cf_mvp"),
    ):
        winner_team = postseason.conference_champions.get(
            conference,
            "",
        )
        rows = _postseason_player_aggregates(
            state,
            stage=PostseasonStage.CONFERENCE_FINALS,
            conference=conference,
            team=winner_team or None,
        )
        honors[key] = _postseason_award_winner(rows)

    # Finals MVP is a series award, not a champion-only eligibility rule.
    # Score every player who appeared in the NBA Finals. A losing-team player
    # can therefore win in an extraordinary series, as has happened in NBA
    # history.
    finals_rows = _postseason_player_aggregates(
        state,
        stage=PostseasonStage.NBA_FINALS,
        team=None,
    )
    honors["finals_mvp"] = _postseason_award_winner(
        finals_rows
    )
    return honors


def _vote_table(
    candidates: list[dict[str, Any]],
    *,
    label: str,
) -> pd.DataFrame:
    top = candidates[:5]
    if not top:
        return pd.DataFrame()
    best = max(
        float(item["award_score"])
        for item in top
    )
    weights = [
        2.0 ** ((float(item["award_score"]) - best) / 6.0)
        for item in top
    ]
    total = sum(weights) or 1.0
    first_votes = [
        int(round(100 * weight / total))
        for weight in weights
    ]
    if first_votes:
        first_votes[0] += 100 - sum(first_votes)
    scoring = [10, 7, 5, 3, 1]
    rows = []
    for index, item in enumerate(top):
        rows.append(
            {
                "Rank": index + 1,
                label: item["subject_name"],
                "Team": item["subject_team"],
                "Award Score": round(
                    item["award_score"],
                    1,
                ),
                "Model Vote Share": (
                    f"{100 * weights[index] / total:.1f}%"
                ),
                "First-Place Votes": first_votes[index],
                "Voting Pts": first_votes[index] * scoring[index],
                "Eligibility / context": item.get("detail", ""),
            }
        )
    return pd.DataFrame(rows)


def _mip_vote_table_v3(
    candidates: list[dict[str, Any]],
) -> pd.DataFrame:
    top = candidates[:5]
    if not top:
        return pd.DataFrame()

    best = max(float(item["award_score"]) for item in top)
    weights = [
        2.0 ** ((float(item["award_score"]) - best) / 6.0)
        for item in top
    ]
    total = sum(weights) or 1.0
    first_votes = [
        int(round(100 * weight / total))
        for weight in weights
    ]
    if first_votes:
        first_votes[0] += 100 - sum(first_votes)

    rows = []
    for index, item in enumerate(top):
        metrics = item.get("mip_metrics", {})
        prior = item.get("mip_prior", {})
        rows.append(
            {
                "Rank": index + 1,
                "Player": item["subject_name"],
                "Team": item["subject_team"],
                "Breakout Score": round(float(item["award_score"]), 1),
                "PTS Δ": _signed(_safe_number(metrics.get("pts_delta"))),
                "AST Δ": _signed(_safe_number(metrics.get("ast_delta"))),
                "REB Δ": _signed(_safe_number(metrics.get("reb_delta"))),
                "MIN Δ": _signed(_safe_number(metrics.get("min_delta"))),
                "TS Δ": (
                    _signed(_safe_number(metrics.get("ts_delta")))
                    if _safe_number(prior.get("TS%")) > 0
                    else "—"
                ),
                "Prior baseline": (
                    f"{int(_safe_number(prior.get('GP')))} GP · "
                    f"{_safe_number(prior.get('MIN')):.1f} MPG"
                ),
                "Model Vote Share": f"{100 * weights[index] / total:.1f}%",
                "First-Place Votes": first_votes[index],
            }
        )
    return pd.DataFrame(rows)


def inject_career_awards_styles() -> None:
    import streamlit as st

    st.markdown(
        """
<style>
.fm-v2-awards-stage {
  position:relative;
  overflow:hidden;
  border:1px solid rgba(255,255,255,.13);
  border-radius:30px;
  padding:26px 28px;
  margin:18px 0 14px;
  background:
    radial-gradient(circle at 15% 0%,rgba(250,204,21,.18),transparent 26%),
    radial-gradient(circle at 86% 12%,rgba(59,130,246,.17),transparent 27%),
    linear-gradient(130deg,#101525,#080b13 74%);
  box-shadow:0 24px 60px rgba(0,0,0,.34);
}
.fm-v2-awards-kicker {
  color:#fde68a;
  font-size:.67rem;
  font-weight:950;
  letter-spacing:.20em;
}
.fm-v2-awards-title {
  color:#fff;
  font-size:2.15rem;
  font-weight:1000;
  letter-spacing:-.04em;
  margin-top:5px;
}
.fm-v2-awards-copy {
  max-width:850px;
  color:#abb7c8;
  font-size:.86rem;
  line-height:1.6;
  margin-top:7px;
}
.fm-v2-award-grid {
  display:grid;
  grid-template-columns:repeat(4,minmax(0,1fr));
  gap:12px;
  margin:14px 0 16px;
}
.fm-v2-award-card {
  position:relative;
  overflow:hidden;
  min-height:245px;
  border:1px solid rgba(255,255,255,.10);
  border-radius:22px;
  padding:14px;
  background:
    radial-gradient(circle at 80% 8%,color-mix(in srgb,var(--award) 28%,transparent),transparent 32%),
    linear-gradient(150deg,color-mix(in srgb,var(--award) 13%,#101522),#090d16 62%);
}
.fm-v2-award-chip {
  display:inline-flex;
  gap:6px;
  align-items:center;
  padding:5px 8px;
  border:1px solid color-mix(in srgb,var(--award) 55%,rgba(255,255,255,.12));
  border-radius:999px;
  color:#fff;
  font-size:.60rem;
  font-weight:950;
  letter-spacing:.09em;
}
.fm-v2-award-winner {
  display:grid;
  grid-template-columns:72px 1fr;
  gap:10px;
  align-items:center;
  margin-top:14px;
}
.fm-v2-award-photo {
  width:72px;
  height:72px;
  object-fit:cover;
  object-position:top center;
  border-radius:18px;
  border:1px solid rgba(255,255,255,.14);
  background:#101827;
}
.fm-v2-award-logo {
  width:72px;
  height:72px;
  object-fit:contain;
  padding:10px;
  border-radius:18px;
  border:1px solid rgba(255,255,255,.14);
  background:#101827;
}
.fm-v2-award-name {
  color:#fff;
  font-size:1.06rem;
  font-weight:950;
  line-height:1.1;
}
.fm-v2-award-team {
  color:#9dacbf;
  font-size:.68rem;
  margin-top:4px;
}
.fm-v2-award-trophy {
  color:#e8edf6;
  font-size:.70rem;
  font-weight:850;
  margin-top:12px;
}
.fm-v2-award-detail {
  color:#99a7b8;
  font-size:.68rem;
  line-height:1.45;
  margin-top:7px;
}
.fm-playoff-honors {
  border:1px solid rgba(250,204,21,.24);
  border-radius:30px;
  padding:22px;
  margin:14px 0 18px;
  background:
    radial-gradient(circle at 86% 12%,rgba(250,204,21,.16),transparent 30%),
    linear-gradient(135deg,#15121c,#080c14 68%);
  box-shadow:0 24px 60px rgba(0,0,0,.34);
}
.fm-playoff-honors-title {
  color:#fff;
  font-size:1.65rem;
  font-weight:1000;
  letter-spacing:-.03em;
}
.fm-playoff-honors-copy {
  color:#aab5c5;
  font-size:.80rem;
  margin-top:5px;
}
.fm-playoff-trophy-grid {
  display:grid;
  grid-template-columns:repeat(3,minmax(0,1fr));
  gap:12px;
  margin-top:15px;
}
.fm-playoff-trophy-card {
  border:1px solid rgba(255,255,255,.10);
  border-radius:20px;
  padding:14px;
  background:rgba(255,255,255,.045);
}
.fm-playoff-trophy-name {
  color:#fde68a;
  font-size:.62rem;
  font-weight:950;
  letter-spacing:.11em;
}
.fm-playoff-player {
  display:flex;
  gap:10px;
  align-items:center;
  margin-top:10px;
}
.fm-playoff-player img {
  width:68px;
  height:68px;
  object-fit:cover;
  object-position:top;
  border-radius:18px;
  background:#111827;
}
.fm-playoff-player strong {
  color:#fff;
  font-size:1rem;
}
.fm-playoff-player span {
  display:block;
  color:#9aa8ba;
  font-size:.68rem;
  margin-top:3px;
}
.fm-championship-hero {
  position:relative;
  overflow:hidden;
  min-height:360px;
  border:1px solid rgba(250,204,21,.28);
  border-radius:32px;
  padding:30px;
  margin:18px 0;
  background:
    radial-gradient(circle at 78% 26%,rgba(250,204,21,.22),transparent 28%),
    radial-gradient(circle at 20% 0%,rgba(255,255,255,.10),transparent 22%),
    linear-gradient(125deg,#17120a,#0b1019 57%,#080a10);
  box-shadow:0 32px 80px rgba(0,0,0,.40);
}
.fm-championship-kicker {
  color:#fde68a;
  font-size:.68rem;
  font-weight:1000;
  letter-spacing:.22em;
}
.fm-championship-lockup {
  display:flex;
  align-items:center;
  gap:18px;
  margin-top:14px;
}
.fm-championship-logo {
  width:110px;
  height:110px;
  object-fit:contain;
  filter:drop-shadow(0 14px 26px rgba(0,0,0,.4));
}
.fm-championship-name {
  color:#fff;
  font-size:2.55rem;
  line-height:.98;
  font-weight:1000;
  letter-spacing:-.045em;
}
.fm-championship-sub {
  color:#b8c2d0;
  margin-top:8px;
  font-size:.82rem;
}
.fm-championship-players {
  position:absolute;
  right:18px;
  bottom:0;
  width:46%;
  height:96%;
}
.fm-championship-player {
  position:absolute;
  bottom:0;
  width:220px;
  height:285px;
}
.fm-championship-player img {
  width:100%;
  height:100%;
  object-fit:contain;
  object-position:bottom center;
  filter:drop-shadow(0 20px 24px rgba(0,0,0,.45));
}
.fm-championship-player:nth-child(1){right:120px;z-index:3;}
.fm-championship-player:nth-child(2){right:-10px;z-index:2;transform:scale(.88);opacity:.9;}
.fm-championship-player:nth-child(3){right:255px;z-index:1;transform:scale(.80);opacity:.78;}
.fm-championship-fmvp {
  display:inline-flex;
  align-items:center;
  gap:8px;
  margin-top:24px;
  padding:10px 13px;
  border:1px solid rgba(250,204,21,.35);
  border-radius:14px;
  background:rgba(0,0,0,.22);
  color:#fff;
  font-size:.75rem;
  font-weight:850;
}
@media(max-width:1100px){
  .fm-v2-award-grid{grid-template-columns:repeat(2,minmax(0,1fr));}
  .fm-playoff-trophy-grid{grid-template-columns:1fr;}
  .fm-championship-players{opacity:.38;width:52%;}
}
</style>
        """,
        unsafe_allow_html=True,
    )


def _award_card(
    key: str,
    winner: dict[str, Any] | None,
) -> str:
    meta = AWARD_META[key]
    if winner is None:
        return (
            '<div class="fm-v2-award-card" '
            f'style="--award:{meta["accent"]};">'
            f'<div class="fm-v2-award-chip">{meta["icon"]} {meta["short"]}</div>'
            '<div class="fm-v2-award-detail">No eligible candidate pool yet.</div>'
            '</div>'
        )
    logo_style = key in {"coach", "executive"}
    photo_class = (
        "fm-v2-award-logo"
        if logo_style
        else "fm-v2-award-photo"
    )
    return (
        '<div class="fm-v2-award-card" '
        f'style="--award:{meta["accent"]};">'
        f'<div class="fm-v2-award-chip">{meta["icon"]} {meta["short"]}</div>'
        '<div class="fm-v2-award-winner">'
        f'<img class="{photo_class}" src="{winner.get("image_url", "")}">'
        '<div>'
        f'<div class="fm-v2-award-name">{winner["subject_name"]}</div>'
        f'<div class="fm-v2-award-team">{winner["subject_team"]}</div>'
        '</div></div>'
        f'<div class="fm-v2-award-trophy">{meta["trophy"]}</div>'
        f'<div class="fm-v2-award-detail">{winner.get("detail", "")}</div>'
        '</div>'
    )


def render_awards_showcase_v2(
    state: SimulationLeagueState,
) -> None:
    import streamlit as st

    payload = build_regular_awards_v2(state)
    if not payload.get("ready"):
        st.info(payload.get("reason", "Awards are not ready."))
        return

    st.markdown(
        (
            '<div class="fm-v2-awards-stage">'
            '<div class="fm-v2-awards-kicker">AWARDS ACCURACY V3.1</div>'
            '<div class="fm-v2-awards-title">League Honors & Trophy Room</div>'
            '<div class="fm-v2-awards-copy">'
            'Rookie ballots use durable career metadata, generated players receive persistent franchise portraits, and Most Improved now requires a material breakout from one meaningful rotation season to another. Tiny minute bumps and marginal stat changes cannot win simply because the league had a quiet improvement year.'
            '</div></div>'
        ),
        unsafe_allow_html=True,
    )

    cards = []
    for key in (
        "mvp",
        "dpoy",
        "roy",
        "smoy",
        "mip",
        "clutch",
        "coach",
        "executive",
    ):
        candidates = payload["awards"].get(key, [])
        cards.append(
            _award_card(
                key,
                candidates[0] if candidates else None,
            )
        )
    st.markdown(
        '<div class="fm-v2-award-grid">'
        + "".join(cards)
        + '</div>',
        unsafe_allow_html=True,
    )

    tabs = st.tabs(
        [
            "MVP",
            "Defense",
            "Rookies",
            "Sixth Man",
            "Most Improved",
            "Clutch",
            "Coach & Executive",
            "All-NBA",
            "Defense & Rookie Teams",
        ]
    )
    with tabs[0]:
        st.dataframe(
            _vote_table(payload["awards"]["mvp"], label="Player"),
            hide_index=True,
            width="stretch",
        )
    with tabs[1]:
        st.dataframe(
            _vote_table(payload["awards"]["dpoy"], label="Player"),
            hide_index=True,
            width="stretch",
        )
    with tabs[2]:
        st.caption(
            f"{payload['rookie_count']} true rookies played this season. "
            f"{payload['rookie_award_eligible_count']} cleared the ROY workload floor, "
            f"while All-Rookie teams use a broader participation pool so both "
            f"five-player teams can be filled when at least ten rookies appeared."
        )
        st.dataframe(
            _vote_table(payload["awards"]["roy"], label="Player"),
            hide_index=True,
            width="stretch",
        )
    with tabs[3]:
        st.dataframe(
            _vote_table(payload["awards"]["smoy"], label="Player"),
            hide_index=True,
            width="stretch",
        )
    with tabs[4]:
        st.caption(
            "MIP now requires a real two-season rotation baseline: at least "
            f"{MIP_PRIOR_MIN_GAMES} prior games / {MIP_PRIOR_MIN_MPG:.0f} prior MPG and "
            f"{MIP_CURRENT_MIN_GAMES} current games / {MIP_CURRENT_MIN_MPG:.0f} current MPG / "
            f"{MIP_CURRENT_MIN_PPG:.0f}+ current PPG. Tiny role bumps are excluded even if "
            "they are the largest increase in a quiet season."
        )
        st.dataframe(
            _mip_vote_table_v3(payload["awards"]["mip"]),
            hide_index=True,
            width="stretch",
        )
    with tabs[5]:
        st.dataframe(
            _vote_table(payload["awards"]["clutch"], label="Player"),
            hide_index=True,
            width="stretch",
        )
    with tabs[6]:
        left, right = st.columns(2)
        with left:
            st.markdown("#### Coach of the Year")
            st.dataframe(
                _vote_table(payload["awards"]["coach"], label="Candidate"),
                hide_index=True,
                width="stretch",
            )
        with right:
            st.markdown("#### Executive of the Year")
            st.dataframe(
                _vote_table(payload["awards"]["executive"], label="Candidate"),
                hide_index=True,
                width="stretch",
            )
    with tabs[7]:
        for label, entries in payload["all_nba"].items():
            st.markdown(f"#### {label}")
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "Player": row["subject_name"],
                            "Team": row["subject_team"],
                            "Pos": row["subject_pos"],
                            "Award Score": round(row["award_score"], 1),
                        }
                        for row in entries
                    ]
                ),
                hide_index=True,
                width="stretch",
            )
    with tabs[8]:
        left, right = st.columns(2)
        with left:
            for label, entries in payload["all_defense"].items():
                st.markdown(f"#### {label}")
                st.dataframe(
                    pd.DataFrame(
                        [
                            {
                                "Player": row["subject_name"],
                                "Team": row["subject_team"],
                                "Pos": row["subject_pos"],
                                "Award Score": round(row["award_score"], 1),
                            }
                            for row in entries
                        ]
                    ),
                    hide_index=True,
                    width="stretch",
                )
        with right:
            for label, entries in payload["all_rookie"].items():
                st.markdown(f"#### {label}")
                st.dataframe(
                    pd.DataFrame(
                        [
                            {
                                "Player": row["subject_name"],
                                "Team": row["subject_team"],
                                "Pos": row["subject_pos"],
                                "Rookie Season": getattr(
                                    state.players[row["player_id"]],
                                    "rookie_season",
                                    "",
                                ),
                                "Award Score": round(row["award_score"], 1),
                            }
                            for row in entries
                        ]
                    ),
                    hide_index=True,
                    width="stretch",
                )


def _playoff_card(
    key: str,
    winner: dict[str, Any] | None,
) -> str:
    meta = PLAYOFF_AWARD_META[key]
    if winner is None:
        return (
            '<div class="fm-playoff-trophy-card">'
            f'<div class="fm-playoff-trophy-name">{meta["trophy"]}</div>'
            '<div class="fm-v2-award-detail">Not awarded yet.</div>'
            '</div>'
        )
    return (
        '<div class="fm-playoff-trophy-card">'
        f'<div class="fm-playoff-trophy-name">{meta["icon"]} {meta["trophy"]}</div>'
        '<div class="fm-playoff-player">'
        f'<img src="{winner["image_url"]}">'
        '<div>'
        f'<strong>{winner["player_name"]}</strong>'
        f'<span>{winner["team"]} · {winner["PPG"]:.1f} PPG · '
        f'{winner["RPG"]:.1f} REB · {winner["APG"]:.1f} AST</span>'
        '</div></div></div>'
    )


def render_playoff_honors_v2(
    state: SimulationLeagueState,
) -> None:
    import streamlit as st

    honors = build_playoff_honors_v2(state)
    if not honors.get("ready"):
        return
    postseason = get_postseason_state(state, required=False)
    complete = bool(
        postseason is not None
        and postseason.stage == PostseasonStage.COMPLETE
    )
    st.markdown(
        (
            '<div class="fm-playoff-honors">'
            '<div class="fm-v2-awards-kicker">POSTSEASON HONORS</div>'
            '<div class="fm-playoff-honors-title">Road to the Larry O’Brien Trophy</div>'
            '<div class="fm-playoff-honors-copy">'
            'Conference Finals MVPs are calculated only from their conference-final series. Finals MVP is calculated only from NBA Finals games, not the entire postseason.'
            '</div>'
            '<div class="fm-playoff-trophy-grid">'
            + _playoff_card("east_cf_mvp", honors.get("east_cf_mvp"))
            + _playoff_card("west_cf_mvp", honors.get("west_cf_mvp"))
            + _playoff_card("finals_mvp", honors.get("finals_mvp"))
            + '</div>'
            + (
                '<div class="fm-v2-award-detail" style="margin-top:14px;">'
                f'NBA Champion: <b style="color:white;">{team_name(honors.get("champion", ""))}</b> · '
                f'Runner-up: {team_name(honors.get("runner_up", ""))}'
                '</div>'
                if complete and honors.get("champion")
                else ""
            )
            + '</div>'
        ),
        unsafe_allow_html=True,
    )


def render_championship_ceremony_v2(
    state: SimulationLeagueState,
) -> None:
    import streamlit as st

    postseason = get_postseason_state(
        state,
        required=False,
    )
    if (
        postseason is None
        or postseason.stage != PostseasonStage.COMPLETE
        or not postseason.champion
    ):
        return

    honors = build_playoff_honors_v2(state)
    finals_rows = _postseason_player_aggregates(
        state,
        stage=PostseasonStage.NBA_FINALS,
        team=postseason.champion,
    )
    top_players = []
    for row in finals_rows.values():
        gp = max(1, int(row["games"]))
        score = (
            row["points"] / gp * 1.5
            + row["rebounds"] / gp * 0.8
            + row["assists"] / gp * 1.0
            + row["steals"] / gp * 2.0
            + row["blocks"] / gp * 2.0
        )
        top_players.append((score, row))
    top_players.sort(key=lambda item: -item[0])

    player_art = []
    for _, row in top_players[:3]:
        player_art.append(
            '<div class="fm-championship-player">'
            f'<img src="{player_headshot_url(row["player_id"], row.get("team", ""), row.get("player_name", ""))}" '
            f'alt="{row["player_name"]}">'
            '</div>'
        )

    fmvp = honors.get("finals_mvp")
    fmvp_copy = (
        f'👑 Bill Russell Trophy · {fmvp["player_name"]} · '
        f'{fmvp["PPG"]:.1f} PPG, {fmvp["RPG"]:.1f} REB, '
        f'{fmvp["APG"]:.1f} AST'
        if fmvp
        else "👑 Bill Russell Trophy · Finals MVP pending"
    )

    st.markdown(
        (
            '<div class="fm-championship-hero">'
            '<div class="fm-championship-kicker">LARRY O’BRIEN TROPHY · NBA CHAMPIONS</div>'
            '<div class="fm-championship-lockup">'
            f'<img class="fm-championship-logo" src="{team_logo_url(postseason.champion)}">'
            '<div>'
            f'<div class="fm-championship-name">{team_name(postseason.champion)}</div>'
            '<div class="fm-championship-sub">'
            f'Defeated {team_name(postseason.runner_up)} in the NBA Finals · '
            f'{len(postseason.completed_games)} postseason games completed'
            '</div>'
            '</div></div>'
            f'<div class="fm-championship-fmvp">{fmvp_copy}</div>'
            '<div class="fm-championship-players">'
            + ''.join(player_art)
            + '</div>'
            '</div>'
        ),
        unsafe_allow_html=True,
    )
    render_playoff_honors_v2(state)


def career_metadata_summary(
    state: SimulationLeagueState,
) -> pd.DataFrame:
    ensure_career_metadata(state)
    rows = []
    for player in state.players.values():
        rows.append(
            {
                "Player": player.player_name,
                "Team": player.team_abbreviation,
                "Age": player.age,
                "Draft Year": getattr(player, "draft_year", None),
                "Rookie Season": getattr(player, "rookie_season", ""),
                "Years of Service": getattr(player, "years_of_service", None),
                "Rookie Eligible": getattr(player, "rookie_eligible", False),
                "Metadata Source": getattr(player, "career_metadata_source", ""),
            }
        )
    return pd.DataFrame(rows)


if __name__ == "__main__":
    assert season_start_from_label("2026-27") == 2026
    assert season_label_from_start(2026) == "2026-27"
    print("CAREER AWARDS V2 STATIC SELF-TEST PASSED")
