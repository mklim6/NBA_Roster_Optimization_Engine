from __future__ import annotations

import inspect
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

from franchise_draft_engine_v1 import (
    DRAFT_DEPTH_CHART_VERSION,
    team_depth_chart_rows,
)
from player_development_engine_v1 import (
    ENGINE_VERSION,
    PlayerDevelopmentProjection,
)


def player(pid, name, pos, ovr):
    return SimpleNamespace(
        player_id=pid,
        player_name=name,
        position=pos,
        overall_rating=ovr,
        age=23.0,
    )


def main() -> int:
    players = {
        "1": player("1", "Josh Giddey", "PG/SG", 88.7),
        "2": player("2", "Tre Jones", "PG", 82.0),
        "3": player("3", "Norman Powell", "SG/SF", 81.0),
        "4": player("4", "Matas Buzelis", "PF/SF", 87.2),
        "5": player("5", "Milan Stewart", "SF", 80.8),
        "6": player("6", "Jalen Smith", "C/PF", 80.3),
        "7": player("7", "Nic Claxton", "C", 82.1),
        "8": player("8", "Leonard Miller", "PF", 77.5),
        "9": player("9", "Wing Two", "SG", 78.0),
        "10": player("10", "Center Three", "C", 76.0),
    }
    team = SimpleNamespace(roster_player_ids=tuple(players))
    state = SimpleNamespace(
        teams={"CHI": team},
        players=players,
    )
    rows = team_depth_chart_rows(state, "CHI")
    visible = []
    for row in rows:
        for key in ("Starter", "Backup", "Third"):
            name = row[key]
            if name != "—":
                visible.append(name)

    annotations = getattr(PlayerDevelopmentProjection, "__annotations__", {})
    center_path = SRC / "franchise_development_center_v1.py"
    center_source = center_path.read_text(encoding="utf-8")
    checks = {
        "depth_version_current": DRAFT_DEPTH_CHART_VERSION == "unique-primary-position-v1-2026-08-11",
        "no_player_repeats_across_positions": len(visible) == len(set(visible)),
        "giddey_appears_once": visible.count("Josh Giddey") == 1,
        "buzelis_appears_once": visible.count("Matas Buzelis") == 1,
        "primary_assignment_is_respected": any(
            row["Position"] == "PG" and row["Starter"] == "Josh Giddey"
            for row in rows
        ) and any(
            row["Position"] == "PF" and row["Starter"] == "Matas Buzelis"
            for row in rows
        ),
        "development_engine_v2_is_on_disk": ENGINE_VERSION == "player-development-engine-v2.0-2026-08-11",
        "projection_contract_has_v2_exposure_fields": all(
            field in annotations
            for field in (
                "games_played", "minutes_per_game", "opportunity_score",
                "opportunity_component", "draft_pedigree_component",
                "breakout_component", "years_of_service",
            )
        ),
        "development_center_uses_safe_profile_fallbacks": 'getattr(\n                projection,\n                "games_played"' in center_source
        and 'profile.get("games_played", 0)' in center_source,
        "development_center_has_stale_runtime_guard": "EXPECTED_DEVELOPMENT_ENGINE_VERSION" in center_source
        and "runtime_fresh" in center_source,
    }
    failed = [name for name, ok in checks.items() if not ok]
    print("CHECKS")
    for name, ok in checks.items():
        print(("PASS" if ok else "FAIL"), name)
    print()
    print("DEPTH CHART")
    for row in rows:
        print(row["Position"], "|", row["Starter"], "|", row["Backup"], "|", row["Third"], "| depth", row["Depth"])
    print()
    print("Development engine:", ENGINE_VERSION)
    if failed:
        raise AssertionError("Hotfix validation failed: " + ", ".join(failed))
    print("DRAFT DEPTH + DEVELOPMENT CENTER HOTFIX VALIDATION PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
