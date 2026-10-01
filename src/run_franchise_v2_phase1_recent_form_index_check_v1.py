from __future__ import annotations

import math
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import franchise_free_agency_market_value_v2 as mv


FIELDS = (
    "minutes", "points", "rebounds", "assists", "steals", "blocks",
    "turnovers", "field_goals_made", "field_goals_attempted",
    "three_pointers_made", "three_pointers_attempted",
    "free_throws_made", "free_throws_attempted",
)


def reference_recent_totals(
    player_id: str,
    completed_games: Mapping[str, Any],
    schedule: Mapping[str, Any],
    limit: int = 10,
) -> Any | None:
    rows: list[tuple[int, str, Any]] = []
    for order, (game_id, game) in enumerate(completed_games.items()):
        day = order
        scheduled = schedule.get(game_id) if isinstance(schedule, Mapping) else None
        if scheduled is not None:
            try:
                day = int(getattr(scheduled, "day_index", order) or order)
            except (TypeError, ValueError):
                day = order
        for box in tuple(getattr(game, "player_box_scores", ()) or ()):
            if mv._clean(getattr(box, "player_id", "")) == player_id:
                rows.append((day, str(game_id), box))
                break
    rows.sort(key=lambda item: (item[0], item[1]), reverse=True)
    boxes = [row[2] for row in rows[: max(1, int(limit))]]
    if not boxes:
        return None

    result = SimpleNamespace(games_played=len(boxes))
    for field in FIELDS:
        setattr(
            result,
            field,
            sum(float(getattr(box, field, 0) or 0) for box in boxes),
        )
    return result


def box(pid: str, seed: int) -> SimpleNamespace:
    return SimpleNamespace(
        player_id=pid,
        minutes=20 + seed % 17,
        points=8 + seed % 29,
        rebounds=1 + seed % 11,
        assists=seed % 9,
        steals=seed % 4,
        blocks=seed % 3,
        turnovers=seed % 5,
        field_goals_made=3 + seed % 10,
        field_goals_attempted=8 + seed % 16,
        three_pointers_made=seed % 5,
        three_pointers_attempted=2 + seed % 8,
        free_throws_made=seed % 7,
        free_throws_attempted=1 + seed % 8,
    )


def payload(value: Any | None) -> tuple[Any, ...] | None:
    if value is None:
        return None
    return (
        int(getattr(value, "games_played", 0)),
        *tuple(float(getattr(value, field, 0.0)) for field in FIELDS),
    )


def main() -> int:
    completed = {}
    schedule = {}
    player_ids = ("A", "B", "C", "D")

    # Mix normal days, day_index=0 fallback behavior, duplicate player rows,
    # missing players, and non-monotonic game IDs.
    for i in range(35):
        gid = f"G{(i * 7) % 41:02d}"
        schedule[gid] = SimpleNamespace(day_index=(0 if i == 3 else (i * 2) % 19))
        rows = [box(pid, i * 10 + j) for j, pid in enumerate(player_ids)]
        if i == 7:
            rows.insert(1, box("A", 9999))  # old path must keep first A only
        completed[gid] = SimpleNamespace(player_box_scores=tuple(rows))

    mv._clear_recent_totals_cache()

    for limit in (1, 5, 10, 20):
        for pid in (*player_ids, "MISSING"):
            expected = payload(
                reference_recent_totals(pid, completed, schedule, limit=limit)
            )
            observed = payload(
                mv._recent_totals(pid, completed, schedule, limit=limit)
            )
            assert observed == expected, (pid, limit, observed, expected)

    after_equivalence = mv._recent_totals_cache_report()
    assert after_equivalence["builds"] == 1, after_equivalence
    assert after_equivalence["hits"] >= 1, after_equivalence

    # Same mapping mutated by a newly completed game must invalidate because
    # completed-game count changes.
    before = payload(mv._recent_totals("A", completed, schedule, limit=10))
    new_gid = "G_NEW"
    schedule[new_gid] = SimpleNamespace(day_index=999)
    completed[new_gid] = SimpleNamespace(
        player_box_scores=(box("A", 123456), box("B", 123457))
    )
    after = payload(mv._recent_totals("A", completed, schedule, limit=10))
    expected_after = payload(
        reference_recent_totals("A", completed, schedule, limit=10)
    )
    assert after == expected_after
    assert after != before
    after_mutation = mv._recent_totals_cache_report()
    assert after_mutation["builds"] == 2, after_mutation

    # Exact production-adjustment equivalence using the old recent-total
    # algorithm versus the indexed implementation.
    season_totals = SimpleNamespace(
        games_played=82,
        minutes=2500.0,
        points=1900.0,
        rebounds=420.0,
        assists=510.0,
        steals=80.0,
        blocks=35.0,
        turnovers=180.0,
        field_goals_made=700.0,
        field_goals_attempted=1450.0,
        free_throws_attempted=410.0,
    )
    standings = {
        "AAA": SimpleNamespace(wins=50, losses=32),
        "BBB": SimpleNamespace(wins=42, losses=40),
    }
    state = SimpleNamespace(
        player_season_totals={"A": season_totals},
        standings=standings,
        completed_games=completed,
        schedule=schedule,
        season_history=(),
    )
    player = SimpleNamespace(
        player_id="A",
        overall_rating=84.0,
    )

    optimized_recent = mv._recent_totals
    try:
        mv._recent_totals = reference_recent_totals
        expected_adjustments = mv.production_adjustments_v2(state, player)
    finally:
        mv._recent_totals = optimized_recent
    observed_adjustments = mv.production_adjustments_v2(state, player)
    assert observed_adjustments == expected_adjustments, (
        observed_adjustments,
        expected_adjustments,
    )

    # Lightweight speed sanity check. This is intentionally small and does not
    # profile the simulator.
    large_completed = {}
    large_schedule = {}
    for i in range(500):
        gid = f"L{i:04d}"
        large_schedule[gid] = SimpleNamespace(day_index=i)
        large_completed[gid] = SimpleNamespace(
            player_box_scores=tuple(box(f"P{j:02d}", i * 100 + j) for j in range(20))
        )

    queries = [f"P{j % 20:02d}" for j in range(200)]
    t0 = time.perf_counter()
    reference_results = [
        payload(reference_recent_totals(pid, large_completed, large_schedule, 10))
        for pid in queries
    ]
    reference_seconds = time.perf_counter() - t0

    mv._clear_recent_totals_cache()
    t1 = time.perf_counter()
    optimized_results = [
        payload(mv._recent_totals(pid, large_completed, large_schedule, 10))
        for pid in queries
    ]
    optimized_seconds = time.perf_counter() - t1
    assert optimized_results == reference_results
    assert mv._recent_totals_cache_report()["builds"] == 1

    speedup = (
        reference_seconds / optimized_seconds
        if optimized_seconds > 0
        else math.inf
    )

    print("FRANCHISE V2 PHASE 1 RECENT FORM INDEX CHECK PASSED")
    print("Recent totals exact equivalence: PASS")
    print("Duplicate player row first-match semantics: PASS")
    print("day_index/fallback ordering semantics: PASS")
    print("In-place append invalidation: PASS")
    print("Production adjustment exact equivalence: PASS")
    print("Market-value formula changed: NO")
    print(f"Micro benchmark reference: {reference_seconds:.3f}s")
    print(f"Micro benchmark indexed:   {optimized_seconds:.3f}s")
    print(f"Micro benchmark speedup:   {speedup:.1f}x")
    print(f"Cache report: {mv._recent_totals_cache_report()}")
    print("No franchise checkpoint was loaded or mutated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
