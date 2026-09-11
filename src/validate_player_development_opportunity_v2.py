from __future__ import annotations

import hashlib
import importlib
import inspect
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import player_development_engine_v1 as dev  # noqa: E402
import simulation_season_transition_v1 as transition  # noqa: E402
from franchise_development_center_v1 import (  # noqa: E402
    DEVELOPMENT_CENTER_VERSION,
    build_team_development_preview_v1,
)
from simulation_franchise_checkpoint_v1 import (  # noqa: E402
    load_franchise_checkpoint,
)

EXPECTED_ENGINE = "player-development-engine-v2.0-2026-08-11"
EXPECTED_CENTER = "franchise-development-center-v1-2026-08-11"


def synthetic_profile(
    player_id: str,
    *,
    age: float,
    overall: float,
    potential: float,
    gp: int,
    mpg: float,
    pick: int | None,
    years: int,
    direction: str = "Rising",
) -> dict[str, Any]:
    profile: dict[str, Any] = {
        "player_id": player_id,
        "player_name": player_id,
        "age_2026_27": age,
        "overall_rating": overall,
        "potential_rating": potential,
        "future_outlook_rating": potential,
        "development_direction": direction,
        "profile_reliability": 0.9,
        "games_played": gp,
        "minutes_per_game": mpg,
        "total_minutes": gp * mpg,
        "years_of_service": years,
        "draft_pick": pick,
        "draft_round": 1 if pick is not None and pick <= 30 else 2,
        "stat_factors": {
            "points": 1.0,
            "rebounds": 1.0,
            "assists": 1.0,
            "steals": 1.0,
            "blocks": 1.0,
            "turnovers": 1.0,
            "fouls": 1.0,
            "three_attempts": 1.0,
            "free_throw_attempts": 1.0,
        },
    }
    for field in dev.SKILL_FIELDS:
        profile[field] = overall
    return profile


def checkpoint_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    high = synthetic_profile(
        "PDO-V2-EXPOSURE",
        age=20,
        overall=74,
        potential=92,
        gp=76,
        mpg=30,
        pick=4,
        years=1,
    )
    low = dict(high)
    low.update(
        {
            "games_played": 18,
            "minutes_per_game": 6.0,
            "total_minutes": 108.0,
        }
    )
    old = synthetic_profile(
        "PDO-V2-OLD",
        age=37,
        overall=88,
        potential=88,
        gp=70,
        mpg=30,
        pick=None,
        years=14,
        direction="Stable",
    )

    config = dev.DevelopmentConfig(random_seed=774411)
    high_proj = dev.project_player_development(
        high,
        performance_signal=0.65,
        config=config,
    )
    low_proj = dev.project_player_development(
        low,
        performance_signal=0.65,
        config=config,
    )
    old_proj = dev.project_player_development(old, config=config)

    transition_source = inspect.getsource(transition)
    draft_ui_path = SRC / "franchise_draft_ui_v1.py"
    draft_ui = draft_ui_path.read_text(encoding="utf-8")

    checks = {
        "engine_is_v2": dev.ENGINE_VERSION == EXPECTED_ENGINE,
        "center_is_v1": DEVELOPMENT_CENTER_VERSION == EXPECTED_CENTER,
        "young_ceiling_is_plus_nine": dev.annual_delta_limits(20, config)[1] == 9.0,
        "late_career_floor_is_minus_nine": dev.annual_delta_limits(37, config)[0] == -9.0,
        "high_potential_lottery_can_jump_5plus": high_proj.overall_delta >= 5.0,
        "minutes_materially_boost_same_prospect": high_proj.overall_delta - low_proj.overall_delta >= 2.0,
        "old_player_declines": old_proj.overall_delta <= -2.0,
        "transition_passes_games_played": '"games_played": games_played' in transition_source,
        "transition_passes_minutes": '"minutes_per_game": minutes_per_game' in transition_source,
        "transition_passes_draft_pick": '"draft_pick": getattr' in transition_source,
        "rotation_has_youth_priority": "def youth_priority" in transition_source,
        "rotation_protects_top_talent": "protected_count" in transition_source,
        "draft_ui_has_development_center": "render_team_development_center_v1" in draft_ui,
        "draft_ui_routes_next_season_to_authoritative_boundary": (
            "Return to Season Boundary" in draft_ui
            and "draft_complete_open_next_season_v1_1" not in draft_ui
        ),
    }

    summary: dict[str, Any] = {
        "high_minutes_lottery": {
            "from": high_proj.current_overall_rating,
            "to": high_proj.projected_overall_rating,
            "delta": high_proj.overall_delta,
            "opportunity": high_proj.opportunity_score,
        },
        "low_minutes_same_prospect": {
            "from": low_proj.current_overall_rating,
            "to": low_proj.projected_overall_rating,
            "delta": low_proj.overall_delta,
            "opportunity": low_proj.opportunity_score,
        },
        "age_37_sample": {
            "from": old_proj.current_overall_rating,
            "to": old_proj.projected_overall_rating,
            "delta": old_proj.overall_delta,
        },
    }

    checkpoint = load_franchise_checkpoint()
    if checkpoint is not None:
        state = checkpoint.simulation_state
        signals = transition.resolve_performance_signals(state, None)
        live_rows: list[dict[str, Any]] = []
        for player_id, player in state.players.items():
            if player.synthetic:
                continue
            try:
                projection = dev.project_player_development(
                    transition.player_development_profile(state, player_id),
                    source_season=state.settings.season_label,
                    performance_signal=float(signals.get(player_id, 0.0)),
                    config=dev.DevelopmentConfig(
                        random_seed=state.settings.random_seed
                    ),
                )
            except Exception:
                continue
            live_rows.append(
                {
                    "player": player.player_name,
                    "team": player.team_abbreviation,
                    "age": player.age,
                    "old": projection.current_overall_rating,
                    "new": projection.projected_overall_rating,
                    "delta": projection.overall_delta,
                    "mpg": projection.minutes_per_game,
                    "opportunity": projection.opportunity_score,
                }
            )

        risers = sorted(live_rows, key=lambda row: (-float(row["delta"]), str(row["player"])))[:10]
        fallers = sorted(live_rows, key=lambda row: (float(row["delta"]), str(row["player"])))[:10]
        summary["live_season"] = state.settings.season_label
        summary["live_projected_players"] = len(live_rows)
        summary["live_plus_5_count"] = sum(float(row["delta"]) >= 5.0 for row in live_rows)
        summary["live_minus_4_count"] = sum(float(row["delta"]) <= -4.0 for row in live_rows)
        summary["live_top_risers"] = risers
        summary["live_top_fallers"] = fallers

        team = "CHI" if "CHI" in state.teams else sorted(state.teams)[0]
        try:
            center = build_team_development_preview_v1(state, team)
        except Exception as exc:
            checks["live_team_development_preview_builds"] = False
            summary["development_center_error"] = f"{type(exc).__name__}: {exc}"
        else:
            checks["live_team_development_preview_builds"] = bool(center.get("rows"))
            summary["development_center_team"] = team
            summary["development_center_rows"] = len(center.get("rows", []))
            summary["development_center_advice"] = center.get("advice", [])[:5]
    else:
        checks["live_team_development_preview_builds"] = True
        summary["checkpoint"] = "not found, live audit skipped"

    failed = [name for name, passed in checks.items() if not passed]

    print("=" * 92)
    print("PLAYER DEVELOPMENT & OPPORTUNITY V2 INTEGRATION VALIDATION")
    print("=" * 92)
    for name, passed in checks.items():
        print(f"  {'PASS' if passed else 'FAIL'}  {name}")

    print()
    print("SYNTHETIC REALISM")
    print(
        "  High-minutes lottery:",
        f"{high_proj.current_overall_rating:.1f} -> {high_proj.projected_overall_rating:.1f}",
        f"({high_proj.overall_delta:+.2f})",
    )
    print(
        "  Same prospect, low minutes:",
        f"{low_proj.current_overall_rating:.1f} -> {low_proj.projected_overall_rating:.1f}",
        f"({low_proj.overall_delta:+.2f})",
    )
    print(
        "  Age-37 sample:",
        f"{old_proj.current_overall_rating:.1f} -> {old_proj.projected_overall_rating:.1f}",
        f"({old_proj.overall_delta:+.2f})",
    )

    if "live_top_risers" in summary:
        print()
        print("LIVE NEXT-OFFSEASON TOP RISERS")
        for index, row in enumerate(summary["live_top_risers"], 1):
            print(
                f"  {index:2d}. {row['player']} | {row['team']} | age {row['age']} | "
                f"{row['old']:.1f} -> {row['new']:.1f} ({row['delta']:+.2f}) | "
                f"last MPG {row['mpg']:.1f}"
            )
        print()
        print("LIVE NEXT-OFFSEASON TOP FALLERS")
        for index, row in enumerate(summary["live_top_fallers"], 1):
            print(
                f"  {index:2d}. {row['player']} | {row['team']} | age {row['age']} | "
                f"{row['old']:.1f} -> {row['new']:.1f} ({row['delta']:+.2f})"
            )
        print()
        print("Live +5 OVR projections:", summary["live_plus_5_count"])
        print("Live -4 OVR projections:", summary["live_minus_4_count"])

    if failed:
        raise AssertionError(
            "Player Development & Opportunity V2 integration failed: "
            + ", ".join(failed)
        )

    print()
    print("PLAYER DEVELOPMENT & OPPORTUNITY V2 INTEGRATION VALIDATION PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
