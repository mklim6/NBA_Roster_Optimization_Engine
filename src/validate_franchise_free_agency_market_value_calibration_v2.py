from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import ast
import importlib.util
import sys


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _totals(games, minutes, points, rebounds, assists, steals, blocks, turnovers, fga, fta):
    return SimpleNamespace(
        games_played=games,
        minutes=minutes,
        points=points,
        rebounds=rebounds,
        assists=assists,
        steals=steals,
        blocks=blocks,
        turnovers=turnovers,
        field_goals_attempted=fga,
        free_throws_attempted=fta,
    )


def _state(player, totals, team_games=82):
    standing = SimpleNamespace(wins=41, losses=max(0, team_games-41))
    return SimpleNamespace(
        player_season_totals={player.player_id: totals},
        standings={"CHI": standing},
        completed_games={},
        schedule={},
        season_history=[],
    )


def main() -> int:
    project = Path.cwd()
    mv_path = project / "src" / "franchise_free_agency_market_value_v2.py"
    dec_path = project / "src" / "franchise_free_agency_player_decision_v1.py"
    checks = {}
    for label, path in (("market_module", mv_path), ("decision_module", dec_path)):
        checks[f"{label}_exists"] = path.exists()
        try:
            ast.parse(path.read_text(encoding="utf-8"))
            checks[f"{label}_compiles"] = True
        except Exception:
            checks[f"{label}_compiles"] = False

    mv = _load(mv_path, "_fa_market_value_v2_fixture")
    cap = 164_961_000.0

    young = SimpleNamespace(player_id="Y", overall_rating=90.0, potential_rating=96.0, age=23)
    young_state = _state(young, _totals(78, 2600, 1900, 500, 520, 110, 45, 220, 1450, 450))
    young_v2 = mv.calibrated_market_value_v2(
        young_state, young, salary_cap=cap, prior_salary=8_000_000,
        minimum_salary_floor=1_500_000, maximum_legal_salary=0.25*cap,
    )
    young_old = mv.legacy_market_value_v1(
        young, salary_cap=cap, prior_salary=8_000_000,
        minimum_salary_floor=1_500_000, maximum_legal_salary=0.25*cap,
    )
    checks["young_breakout_not_dragged_down_by_old_salary"] = young_v2.final_reference >= young_old
    checks["young_breakout_respects_legal_max"] = young_v2.final_reference <= 0.25*cap + 0.01
    checks["young_breakout_prior_weight_is_light"] = young_v2.prior_salary_weight <= 0.08

    old_star = SimpleNamespace(player_id="O", overall_rating=94.0, potential_rating=94.0, age=36)
    old_state = _state(old_star, _totals(70, 2300, 1750, 430, 390, 90, 50, 200, 1300, 420))
    old_v2 = mv.calibrated_market_value_v2(
        old_state, old_star, salary_cap=cap, prior_salary=55_000_000,
        minimum_salary_floor=3_000_000, maximum_legal_salary=0.35*cap,
    )
    old_legacy = mv.legacy_market_value_v1(
        old_star, salary_cap=cap, prior_salary=55_000_000,
        minimum_salary_floor=3_000_000, maximum_legal_salary=0.35*cap,
    )
    checks["older_star_gets_modest_not_catastrophic_age_risk"] = (
        0.88 * old_legacy <= old_v2.final_reference <= 1.06 * old_legacy
    )

    injured = SimpleNamespace(player_id="I", overall_rating=87.0, potential_rating=87.0, age=34)
    injured_state = _state(injured, _totals(28, 760, 420, 140, 90, 25, 20, 60, 350, 100))
    healthy_state = _state(injured, _totals(76, 2200, 1250, 390, 260, 70, 55, 150, 980, 300))
    injured_v2 = mv.calibrated_market_value_v2(
        injured_state, injured, salary_cap=cap, prior_salary=28_000_000,
        minimum_salary_floor=2_500_000, maximum_legal_salary=0.35*cap,
    )
    healthy_v2 = mv.calibrated_market_value_v2(
        healthy_state, injured, salary_cap=cap, prior_salary=28_000_000,
        minimum_salary_floor=2_500_000, maximum_legal_salary=0.35*cap,
    )
    checks["availability_can_reduce_market_value"] = injured_v2.final_reference < healthy_v2.final_reference

    dec = dec_path.read_text(encoding="utf-8")
    checks["decision_engine_passes_state_into_v2"] = "market_salary_reference(player, preview, state)" in dec
    checks["decision_fingerprint_tracks_market_version"] = '"market_value_version": FREE_AGENCY_MARKET_VALUE_CALIBRATION_VERSION' in dec
    checks["legacy_public_decision_version_preserved"] = 'franchise-free-agency-player-decision-v1-2026-08-14' in dec
    checks["old_32_percent_prior_salary_blend_removed_from_live_path"] = "0.68 * rating_reference + 0.32 * prior" not in dec

    failed = [k for k,v in checks.items() if not v]
    print({"checks": checks, "failed_checks": failed, "passed": not failed})
    if failed:
        print("FRANCHISE FREE AGENCY MARKET VALUE CALIBRATION V2 VALIDATOR FAILED")
        return 1
    print("FRANCHISE FREE AGENCY MARKET VALUE CALIBRATION V2 VALIDATOR PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
