from __future__ import annotations

import importlib
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import simulation_career_awards_v2 as awards
import franchise_generated_player_portraits_v1 as portraits


def row(**kwargs):
    base = {
        "GP": 70,
        "MIN": 30.0,
        "PTS": 15.0,
        "AST": 4.0,
        "REB": 5.0,
        "STL": 1.0,
        "BLK": 0.5,
        "TO": 2.0,
        "TS%": 56.0,
    }
    base.update(kwargs)
    return base


tiny_prior = row(GP=82, MIN=18.4, PTS=7.0, AST=1.0, REB=3.0, TS=54.0)
tiny_prior["TS%"] = 54.0
tiny_current = row(GP=82, MIN=20.8, PTS=8.5, AST=1.0, REB=3.7, TS=55.6)
tiny_current["TS%"] = 55.6

breakout_prior = row(GP=68, MIN=27.0, PTS=16.8, AST=3.8, REB=4.9, TS=56.2)
breakout_prior["TS%"] = 56.2
breakout_current = row(GP=74, MIN=34.0, PTS=24.5, AST=6.1, REB=6.2, TS=60.4)
breakout_current["TS%"] = 60.4

tiny_metrics = awards._mip_breakout_metrics_v3(tiny_current, tiny_prior)
breakout_metrics = awards._mip_breakout_metrics_v3(
    breakout_current,
    breakout_prior,
)

fallback = portraits.generated_player_portrait_url(
    "GEN-2031-TEST",
    team="IND",
    player_name="Test Rookie",
)

checks = {
    "awards_version_is_v32": (
        awards.CAREER_AWARDS_VERSION
        == "simulation-career-awards-v3.2-2026-08-11"
    ),
    "prior_floor_is_rotation_level": (
        awards.MIP_PRIOR_MIN_GAMES >= 50
        and awards.MIP_PRIOR_MIN_MPG >= 18
    ),
    "current_floor_is_rotation_level": (
        awards.MIP_CURRENT_MIN_GAMES >= 50
        and awards.MIP_CURRENT_MIN_MPG >= 24
        and awards.MIP_CURRENT_MIN_PPG >= 10
    ),
    "tiny_role_bump_is_not_material": (
        not awards._mip_has_material_breakout(tiny_metrics)
    ),
    "tiny_role_bump_fails_current_floor": (
        not awards._mip_current_baseline_eligible(tiny_current)
    ),
    "real_breakout_is_material": (
        awards._mip_has_material_breakout(breakout_metrics)
    ),
    "real_breakout_clears_current_floor": (
        awards._mip_current_baseline_eligible(breakout_current)
    ),
    "real_breakout_score_clears_floor": (
        breakout_metrics["breakout_score"]
        >= awards.MIP_MIN_BREAKOUT_SCORE
    ),
    "portrait_system_is_stock_v2": (
        portraits.GENERATED_PORTRAIT_VERSION
        == "franchise-stock-player-portraits-v2-2026-08-11"
    ),
    "no_ai_face_fallback": (
        "STOCK%20PHOTO%20NEEDED" in fallback
        or "STOCK%20PHOTO" in fallback
    ),
    "stock_setup_script_exists": (
        (SRC / "build_generated_player_stock_portrait_pool_v1.py").exists()
    ),
}

failed = [name for name, passed in checks.items() if not passed]

print("AWARDS & STOCK PORTRAITS V3.2 CHECKS")
for name, passed in checks.items():
    print(f"  {name}: {'PASS' if passed else 'FAIL'}")

print()
print("Tiny role-bump score:", round(tiny_metrics["breakout_score"], 2))
print("Tiny impact gain:", round(tiny_metrics["impact_gain"], 2))
print("Real breakout score:", round(breakout_metrics["breakout_score"], 2))
print("Real breakout impact gain:", round(breakout_metrics["impact_gain"], 2))
print("Stock portrait pool installed:", portraits.stock_portrait_available())

if failed:
    raise AssertionError(
        "V3.2 validation failed: " + ", ".join(failed)
    )

# Optional live-checkpoint audit.
try:
    from simulation_franchise_checkpoint_v1 import load_franchise_checkpoint
    checkpoint = load_franchise_checkpoint()
except Exception as exc:
    checkpoint = None
    print("Checkpoint audit skipped:", exc)

if checkpoint is not None:
    payload = awards.build_regular_awards_v2(checkpoint.simulation_state)
    mip = payload.get("awards", {}).get("mip", [])
    print()
    print("LIVE MIP TOP FIVE")
    for idx, item in enumerate(mip[:5], start=1):
        print(
            f"  {idx}. {item.get('subject_name')} | "
            f"{item.get('subject_team')} | "
            f"{float(item.get('award_score', 0.0)):.1f} | "
            f"{item.get('detail', '')}"
        )
    if not mip:
        print("  No player met the strict V3.2 breakout floor.")

print()
print("AWARDS & STOCK PORTRAITS V3.2 VALIDATION PASSED")
