from __future__ import annotations

import copy
from collections import Counter
from dataclasses import asdict, dataclass, field
from typing import Any

from freeform_trade_machine_engine_v3 import normalize_player_id, normalize_team
from franchise_live_asset_ledger_v1 import FranchiseAssetLedger


PLAYER_SEARCH_VERSION = "franchise-player-search-v1-2026-08-12"


@dataclass(frozen=True)
class PlayerSearchMatch:
    player_id: str
    player_name: str
    current_team: str
    roster_status: str
    position: str
    age: float | None
    overall: float
    generated_player: bool


@dataclass(frozen=True)
class PlayerSeasonLocation:
    season_label: str
    team: str
    games_observed: int
    evidence: str


@dataclass(frozen=True)
class PlayerTransactionEvent:
    transaction_id: str
    season_label: str
    day_index: int
    from_team: str
    to_team: str
    counterpart_team: str


@dataclass(frozen=True)
class PlayerSearchProfile:
    version: str
    player_id: str
    player_name: str
    current_team: str
    current_location_label: str
    roster_status: str
    position: str
    age: float | None
    overall: float
    potential: float
    future_outlook: float
    generated_player: bool
    career_status: str
    availability: str
    salary: float | None
    years_remaining: int | None
    contract_status: str
    draft_year: int | None
    draft_team: str
    draft_round: int | None
    draft_pick: int | None
    draft_class_id: str
    current_games_played: int
    current_points_per_game: float | None
    current_rebounds_per_game: float | None
    current_assists_per_game: float | None
    season_locations: tuple[PlayerSeasonLocation, ...] = field(default_factory=tuple)
    transactions: tuple[PlayerTransactionEvent, ...] = field(default_factory=tuple)
    development_history: tuple[dict[str, Any], ...] = field(default_factory=tuple)


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _int_or_none(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _float_or_none(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number


def _player_row(ledger: FranchiseAssetLedger, player_id: str) -> dict[str, Any]:
    resolved = normalize_player_id(player_id)
    for row in ledger.player_rows:
        if normalize_player_id(row.get("player_id")) == resolved:
            return dict(row)
    raise KeyError(f"Player {resolved} is not present in the live asset ledger.")


def search_players(
    ledger: FranchiseAssetLedger,
    query: str,
    *,
    limit: int = 30,
) -> list[PlayerSearchMatch]:
    text = _clean(query).lower()
    if not text:
        return []

    ranked: list[tuple[tuple[int, int, str], PlayerSearchMatch]] = []
    tokens = [token for token in text.split() if token]
    for row in ledger.player_rows:
        name = _clean(row.get("player_name"))
        hay = name.lower()
        if not all(token in hay for token in tokens):
            continue
        if hay == text:
            quality = 0
        elif hay.startswith(text):
            quality = 1
        elif any(part.startswith(text) for part in hay.split()):
            quality = 2
        else:
            quality = 3
        match = PlayerSearchMatch(
            player_id=normalize_player_id(row.get("player_id")),
            player_name=name,
            current_team=normalize_team(row.get("team")),
            roster_status=_clean(row.get("roster_status")),
            position=_clean(row.get("position")) or "UNK",
            age=_float_or_none(row.get("age")),
            overall=float(row.get("overall") or 0.0),
            generated_player=bool(row.get("generated_player")),
        )
        ranked.append(
            (
                (quality, abs(len(hay) - len(text)), name.lower()),
                match,
            )
        )
    ranked.sort(key=lambda item: item[0])
    return [match for _, match in ranked[: max(1, int(limit))]]


def _archive_team(archive: Any, player_id: str) -> tuple[str, int]:
    counts: Counter[str] = Counter()
    for game in (getattr(archive, "completed_games", {}) or {}).values():
        for line in getattr(game, "player_box_scores", ()) or ():
            if normalize_player_id(getattr(line, "player_id", "")) != player_id:
                continue
            team = normalize_team(getattr(line, "team_abbreviation", ""))
            if team:
                counts[team] += 1
    if not counts:
        return "", 0
    team, games = counts.most_common(1)[0]
    return team, int(games)


def _transaction_events(state: Any, player_id: str) -> list[PlayerTransactionEvent]:
    events: list[PlayerTransactionEvent] = []
    for record in getattr(state, "franchise_transaction_history_v1", []) or []:
        if not isinstance(record, dict):
            continue
        a = normalize_team(record.get("team_a"))
        b = normalize_team(record.get("team_b"))
        a_ids = {normalize_player_id(v) for v in record.get("side_a_player_ids", [])}
        b_ids = {normalize_player_id(v) for v in record.get("side_b_player_ids", [])}
        if player_id in a_ids:
            source, destination = a, b
        elif player_id in b_ids:
            source, destination = b, a
        else:
            continue
        events.append(
            PlayerTransactionEvent(
                transaction_id=_clean(record.get("transaction_id")),
                season_label=_clean(record.get("season_label")),
                day_index=int(record.get("day_index", 0) or 0),
                from_team=source,
                to_team=destination,
                counterpart_team=destination,
            )
        )
    return events


def _attr_first(player: Any, names: tuple[str, ...]) -> Any:
    for name in names:
        if hasattr(player, name):
            value = getattr(player, name)
            if value not in (None, ""):
                return value
    return None


def build_player_search_profile(
    state: Any,
    ledger: FranchiseAssetLedger,
    player_id: str,
) -> PlayerSearchProfile:
    pid = normalize_player_id(player_id)
    row = _player_row(ledger, pid)
    player = getattr(state, "players", {}).get(pid)
    if player is None:
        # Some state dictionaries may retain a numeric/raw key.
        player = next(
            (
                value for key, value in getattr(state, "players", {}).items()
                if normalize_player_id(key) == pid
            ),
            None,
        )

    current_team = normalize_team(row.get("team"))
    roster_status = _clean(row.get("roster_status"))
    current_location = (
        current_team
        if current_team
        else "Free Agent"
        if roster_status == "free_agent"
        else _clean(row.get("career_status")).replace("_", " ").title()
        or "Unassigned"
    )

    locations: list[PlayerSeasonLocation] = []
    for archive in getattr(state, "season_history", []) or []:
        team, games = _archive_team(archive, pid)
        if team:
            locations.append(
                PlayerSeasonLocation(
                    season_label=_clean(getattr(archive, "season_label", "")),
                    team=team,
                    games_observed=games,
                    evidence="Archived game appearances",
                )
            )

    current_season = _clean(getattr(getattr(state, "settings", None), "season_label", ""))
    if current_team:
        locations.append(
            PlayerSeasonLocation(
                season_label=current_season,
                team=current_team,
                games_observed=int(
                    getattr(
                        (getattr(state, "player_season_totals", {}) or {}).get(pid),
                        "games_played",
                        0,
                    )
                    or 0
                ),
                evidence="Current live roster",
            )
        )

    totals = (getattr(state, "player_season_totals", {}) or {}).get(pid)
    gp = int(getattr(totals, "games_played", 0) or 0) if totals is not None else 0
    def per_game(field: str) -> float | None:
        if totals is None or gp <= 0:
            return None
        return round(float(getattr(totals, field, 0) or 0) / gp, 1)

    draft_year = _int_or_none(
        _attr_first(player, ("draft_year",)) if player is not None else row.get("draft_year")
    )
    draft_team = normalize_team(
        _attr_first(
            player,
            ("draft_team", "drafted_by_team", "draft_team_abbreviation", "rookie_team"),
        )
        if player is not None
        else ""
    )
    draft_round = _int_or_none(
        _attr_first(player, ("draft_round", "round_drafted"))
        if player is not None
        else None
    )
    draft_pick = _int_or_none(
        _attr_first(
            player,
            (
                "draft_pick_number",
                "draft_pick",
                "overall_pick",
                "pick_number",
                "draft_overall_pick",
            ),
        )
        if player is not None
        else None
    )
    draft_class_id = _clean(
        _attr_first(player, ("draft_class_id",)) if player is not None else row.get("draft_class_id")
    )

    development = tuple(
        copy.deepcopy(item)
        for item in (getattr(player, "development_history", []) or [])
        if isinstance(item, dict)
    ) if player is not None else ()

    return PlayerSearchProfile(
        version=PLAYER_SEARCH_VERSION,
        player_id=pid,
        player_name=_clean(row.get("player_name")) or pid,
        current_team=current_team,
        current_location_label=current_location,
        roster_status=roster_status,
        position=_clean(row.get("position")) or "UNK",
        age=_float_or_none(row.get("age")),
        overall=float(row.get("overall") or 0.0),
        potential=float(row.get("potential") or row.get("overall") or 0.0),
        future_outlook=float(row.get("future_outlook") or row.get("potential") or 0.0),
        generated_player=bool(row.get("generated_player")),
        career_status=_clean(row.get("career_status")) or "active",
        availability=_clean(row.get("availability")) or "unknown",
        salary=_float_or_none(row.get("salary")),
        years_remaining=_int_or_none(row.get("years_remaining")),
        contract_status=_clean(row.get("contract_status")),
        draft_year=draft_year,
        draft_team=draft_team,
        draft_round=draft_round,
        draft_pick=draft_pick,
        draft_class_id=draft_class_id,
        current_games_played=gp,
        current_points_per_game=per_game("points"),
        current_rebounds_per_game=per_game("rebounds"),
        current_assists_per_game=per_game("assists"),
        season_locations=tuple(locations),
        transactions=tuple(_transaction_events(state, pid)),
        development_history=development,
    )


def player_search_profile_to_dict(profile: PlayerSearchProfile) -> dict[str, Any]:
    return asdict(profile)
