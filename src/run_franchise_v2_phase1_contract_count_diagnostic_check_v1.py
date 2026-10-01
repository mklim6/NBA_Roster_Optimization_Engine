from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import run_franchise_v2_roster_lifecycle_trace_v1 as trace


def _player(*, roster_status: str, two_way: bool = False) -> SimpleNamespace:
    return SimpleNamespace(
        player_name=roster_status,
        roster_status=roster_status,
        two_way=two_way,
    )


def main() -> int:
    state = SimpleNamespace(
        phase="regular_season",
        settings=SimpleNamespace(
            season_label="CHECK",
            minimum_game_players=2,
        ),
        teams={
            "TST": SimpleNamespace(
                roster_player_ids=("STD", "TW", "E10", "MISSING"),
            )
        },
        players={
            "STD": _player(roster_status="active_roster", two_way=False),
            "TW": _player(roster_status="two_way", two_way=True),
            "E10": _player(roster_status="exhibit_10", two_way=False),
        },
        free_agent_player_ids=(),
    )

    breakdown = trace._roster_contract_breakdown(
        state,
        state.teams["TST"].roster_player_ids,
    )

    expected = {
        "standard_player_ids": ("STD",),
        "two_way_player_ids": ("TW",),
        "other_player_ids": ("E10",),
        "unclassified_player_ids": ("MISSING",),
    }
    if breakdown != expected:
        raise AssertionError(
            f"Unexpected contract classification: {breakdown!r}"
        )

    tracer = trace.RosterLifecycleTracer(
        Path("focused-check-unused-output"),
        target_min=1,
        target_max=2,
    )
    tracer.capture_state(
        state,
        label="focused contract classification",
        source="synthetic",
    )
    if tracer.errors:
        raise AssertionError(f"Tracer captured errors: {tracer.errors!r}")
    if len(tracer.team_rows) != 1:
        raise AssertionError(
            f"Expected one team row, got {len(tracer.team_rows)}"
        )

    row = tracer.team_rows[0]
    checks = {
        "total_roster_count": row.get("total_roster_count") == 4,
        "standard_contract_count": row.get("standard_contract_count") == 1,
        "two_way_contract_count": row.get("two_way_contract_count") == 1,
        "other_roster_count": row.get("other_roster_count") == 1,
        "unclassified_roster_count": row.get("unclassified_roster_count") == 1,
        "contract_count_reconciles_to_total": (
            row.get("contract_count_reconciles_to_total") is True
        ),
        "standard_target_uses_standard_count": (
            row.get("standard_below_v2_target") is False
            and row.get("standard_above_v2_target") is False
        ),
        "legacy_total_roster_retained": row.get("roster_count") == 4,
    }

    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise AssertionError("Focused checker failed: " + ", ".join(failed))

    print("FRANCHISE V2 PHASE 1 CONTRACT COUNT DIAGNOSTIC CHECK V1")
    for name in checks:
        print(f"  {name}: PASS")
    print("  active franchise checkpoint loaded/mutated: NO")
    print("FOCUSED CHECK PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
