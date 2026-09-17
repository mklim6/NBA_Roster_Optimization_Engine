from __future__ import annotations

import copy
from typing import Any


FRANCHISE_HISTORY_AWARDS_ARCHIVE_VERSION = (
    "franchise-history-awards-archive-v1.0-2026-09-16"
)
HISTORY_AWARDS_ATTR = "awards_snapshot_v2"


def _winner(rows: Any) -> dict[str, Any] | None:
    if not rows:
        return None
    row = list(rows)[0]
    return copy.deepcopy(dict(row)) if isinstance(row, dict) else None


def build_compact_awards_archive_v1(state: Any) -> dict[str, Any]:
    from simulation_career_awards_v2 import (
        build_playoff_honors_v2,
        build_regular_awards_v2,
    )

    regular = build_regular_awards_v2(state)
    playoff = build_playoff_honors_v2(state)
    awards = regular.get("awards", {}) if isinstance(regular, dict) else {}
    compact_awards = {
        key: _winner(awards.get(key, []))
        for key in ("mvp", "dpoy", "roy", "smoy", "mip", "clutch", "coach", "executive")
    }
    teams = {}
    for key in ("all_nba", "all_defense", "all_rookie"):
        group = regular.get(key, {}) if isinstance(regular, dict) else {}
        teams[key] = {
            label: [copy.deepcopy(dict(row)) for row in list(rows or [])]
            for label, rows in dict(group or {}).items()
        }
    postseason = {
        key: copy.deepcopy(playoff.get(key)) if isinstance(playoff, dict) else None
        for key in (
            "champion", "runner_up", "conference_champions",
            "east_cf_mvp", "west_cf_mvp", "finals_mvp",
        )
    }
    return {
        "version": FRANCHISE_HISTORY_AWARDS_ARCHIVE_VERSION,
        "season": str(getattr(getattr(state, "settings", None), "season_label", "") or ""),
        "regular_ready": bool(regular.get("ready", False)) if isinstance(regular, dict) else False,
        "playoff_ready": bool(playoff.get("ready", False)) if isinstance(playoff, dict) else False,
        "awards": compact_awards,
        "teams": teams,
        "postseason": postseason,
        "rookie_count": int(regular.get("rookie_count", 0) or 0) if isinstance(regular, dict) else 0,
        "rookie_award_eligible_count": int(regular.get("rookie_award_eligible_count", 0) or 0) if isinstance(regular, dict) else 0,
    }


def attach_awards_archive_v1(state: Any, archive: Any) -> dict[str, Any]:
    try:
        payload = build_compact_awards_archive_v1(state)
    except Exception as exc:
        # Historical presentation must never block the certified season
        # boundary. Preserve a durable diagnostic instead and continue.
        payload = {
            "version": FRANCHISE_HISTORY_AWARDS_ARCHIVE_VERSION,
            "season": str(getattr(getattr(state, "settings", None), "season_label", "") or ""),
            "ready": False,
            "error_type": type(exc).__name__,
            "error": str(exc),
            "awards": {},
            "teams": {},
            "postseason": {},
        }
    setattr(archive, HISTORY_AWARDS_ATTR, payload)
    return payload


def historical_awards_rows_v1(state: Any, award_key: str) -> list[dict[str, Any]]:
    rows = []
    for archive in list(getattr(state, "season_history", ()) or ()):
        payload = getattr(archive, HISTORY_AWARDS_ATTR, None)
        if not isinstance(payload, dict):
            continue
        winner = (payload.get("awards", {}) or {}).get(award_key)
        if not isinstance(winner, dict):
            continue
        rows.append({
            "season": str(getattr(archive, "season_label", "") or payload.get("season", "")),
            "award": award_key,
            "winner": winner.get("subject_name", winner.get("player_name", "")),
            "team": winner.get("subject_team", winner.get("team", "")),
            "detail": winner.get("detail", ""),
        })
    return rows


__all__ = [
    "FRANCHISE_HISTORY_AWARDS_ARCHIVE_VERSION",
    "HISTORY_AWARDS_ATTR",
    "build_compact_awards_archive_v1",
    "attach_awards_archive_v1",
    "historical_awards_rows_v1",
]
