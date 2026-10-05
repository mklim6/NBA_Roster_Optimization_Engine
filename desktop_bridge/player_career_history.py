"""Recorded career events only; no synthetic growth trajectories."""
from __future__ import annotations

import math


def number(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def career_history(player):
    events = []
    for raw in getattr(player, "development_history", ()) or ():
        if not isinstance(raw, dict):
            continue
        before = number(raw.get("current_overall_rating"))
        after = number(raw.get("projected_overall_rating"))
        events.append(dict(kind="season", season=str(raw.get("source_season", "Unknown season")),
                           target_season=str(raw.get("target_season", "")), before=before, after=after,
                           delta=None if before is None or after is None else round(after-before, 3),
                           skills={str(k).removesuffix("_rating"): number(v) for k, v in raw.get("skill_deltas", {}).items()} if isinstance(raw.get("skill_deltas"), dict) else {},
                           headline="Annual development", focus=""))
    for raw in getattr(player, "training_camp_history", ()) or ():
        if not isinstance(raw, dict):
            continue
        before = number(raw.get("overall_before"))
        after = number(raw.get("overall_after"))
        focus = str(raw.get("focus", ""))
        skills = {focus: number(raw.get("gain"))} if focus else {}
        cost_before, cost_after = number(raw.get("tradeoff_before")), number(raw.get("tradeoff_after"))
        if raw.get("tradeoff") and cost_before is not None and cost_after is not None:
            skills[str(raw["tradeoff"])] = round(cost_after-cost_before, 3)
        events.append(dict(kind="camp", season=str(raw.get("season", "Unknown season")), target_season="",
                           before=before, after=after, delta=None if before is None or after is None else round(after-before, 3),
                           skills=skills, headline="Focused training camp", focus=focus))
    events.sort(key=lambda row: (row["season"], 0 if row["kind"] == "camp" else 1))
    known = [row for row in events if row["delta"] is not None]
    return dict(events=events[-40:], total_events=len(events), camp_events=sum(e["kind"] == "camp" for e in events),
                annual_events=sum(e["kind"] == "season" for e in events),
                recorded_change=round(sum(e["delta"] for e in known), 3) if known else None,
                best_gain=max((e["delta"] for e in known), default=None),
                coverage="Recorded events only. Gaps and unrecorded changes are not inferred.")
