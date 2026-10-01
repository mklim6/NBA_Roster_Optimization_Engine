from __future__ import annotations

import ast
import json
from pathlib import Path
from types import SimpleNamespace

from franchise_v2_league_sustainability_v1 import (
    build_league_sustainability_snapshot,
)


ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "pages" / "5_Franchise_Mode.py"
MODULE = ROOT / "src" / "franchise_v2_league_sustainability_v1.py"
VERSION = "franchise-v2-foundation-validator-v1-2026-09-23"


def _state(roster_size: int, free_agents: int = 150) -> SimpleNamespace:
    teams = {
        f"T{index:02d}": SimpleNamespace(
            roster_player_ids=tuple(
                f"T{index:02d}_P{player:02d}" for player in range(roster_size)
            )
        )
        for index in range(30)
    }
    return SimpleNamespace(
        teams=teams,
        free_agent_player_ids=tuple(f"FA{index:03d}" for index in range(free_agents)),
    )


def main() -> int:
    page_text = PAGE.read_text(encoding="utf-8")
    module_text = MODULE.read_text(encoding="utf-8")
    ast.parse(page_text)
    ast.parse(module_text)

    healthy = build_league_sustainability_snapshot(_state(15))
    sparse = build_league_sustainability_snapshot(_state(10, free_agents=552))

    checks = {
        "healthy_league_classified": healthy.status == "healthy",
        "healthy_population_reconciles": (
            healthy.rostered_players == 450
            and healthy.free_agent_count == 150
            and healthy.total_player_count == 600
        ),
        "healthy_all_teams_in_target": (
            healthy.teams_in_target == 30 and healthy.teams_below_target == 0
        ),
        "sparse_league_is_v2_priority": sparse.status == "needs_attention",
        "sparse_league_deficit_is_exact": (
            sparse.teams_below_target == 30
            and all(row["Players needed"] == 4 for row in sparse.team_rows)
        ),
        "league_hub_renders_sustainability_panel": (
            "render_league_sustainability_v1(state)" in page_text
        ),
        "next_season_uses_status_container": (
            '"Step 1 of 5 · Verifying the durable franchise checkpoint..."'
            in page_text
            and '"Step 5 of 5 · Archiving the season and building the schedule..."'
            in page_text
        ),
        "next_season_reports_100_percent": (
            "_season_boundary_progress.progress(" in page_text
            and 'state="complete"' in page_text
        ),
        "no_deprecated_width_argument_added": "use_container_width" not in module_text,
    }
    failed = [name for name, passed in checks.items() if not passed]
    print(
        json.dumps(
            {
                "version": VERSION,
                "checks": checks,
                "failed_checks": failed,
                "passed": not failed,
            },
            indent=2,
        )
    )
    if failed:
        raise AssertionError("Franchise V2 foundation failed: " + ", ".join(failed))
    print("FRANCHISE V2 FOUNDATION VALIDATOR PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

