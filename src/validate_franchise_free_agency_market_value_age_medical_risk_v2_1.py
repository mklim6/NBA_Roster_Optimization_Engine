from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import ast
import importlib.util
import sys


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _totals(games=82, minutes=2500):
    return SimpleNamespace(
        games_played=games,
        minutes=minutes,
        points=1800,
        rebounds=500,
        assists=400,
        steals=100,
        blocks=50,
        turnovers=180,
        field_goals_attempted=1300,
        free_throws_attempted=400,
    )


def _standing(games=82):
    return SimpleNamespace(wins=41, losses=games-41)


def _player(pid, age, overall, availability):
    return SimpleNamespace(
        player_id=pid,
        player_name=pid,
        age=float(age),
        overall_rating=float(overall),
        potential_rating=float(overall),
        skill_ratings={"availability_rating": float(availability)},
    )


def _state(player, *, games=82, durability=.90, injuries=0, missed=0):
    return SimpleNamespace(
        player_season_totals={player.player_id: _totals(games=games)},
        standings={"A": _standing(82)},
        completed_games={},
        schedule={},
        season_history=[],
        injury_fatigue_profiles={
            player.player_id: SimpleNamespace(
                durability=durability,
                injuries_suffered=injuries,
                season_games_missed=missed,
            )
        },
    )


def main() -> int:
    project = Path.cwd()
    path = project / "src" / "franchise_free_agency_market_value_v2.py"
    audit = project / "src" / "audit_franchise_free_agency_market_value_v2.py"
    checks = {}
    for label, target in (("market", path), ("audit", audit)):
        checks[f"{label}_exists"] = target.exists()
        try:
            ast.parse(target.read_text(encoding="utf-8"))
            checks[f"{label}_compiles"] = True
        except Exception:
            checks[f"{label}_compiles"] = False

    mv = _load(path, "_mv_v21_fixture")
    cap = 164_961_000.0

    # Kawhi-like: age 35, elite OVR, poor persistent availability history,
    # even if he happened to play 82 games in the current simulated season.
    old_risk_star = _player("RISK35", 35, 94.9, 58)
    risk_state = _state(old_risk_star, games=82, durability=.76, injuries=0, missed=0)
    risk = mv.calibrated_market_value_v2(
        risk_state,
        old_risk_star,
        salary_cap=cap,
        prior_salary=50_300_000,
        minimum_salary_floor=4_186_651,
        maximum_legal_salary=62_355_258,
    )
    checks["age_35_elite_star_no_longer_gets_superstar_age_immunity"] = risk.age_risk_factor <= .92
    checks["persistent_availability_risk_survives_one_healthy_sim_season"] = risk.medical_risk_factor <= .68
    checks["kawhi_like_risk_profile_is_heavily_discounted"] = risk.final_reference <= 40_000_000

    # Healthy old star: age alone matters, but no medical-history penalty.
    healthy_old = _player("HEALTH38", 38, 91.8, 94)
    healthy_state = _state(healthy_old, games=82, durability=.97, injuries=0, missed=0)
    healthy = mv.calibrated_market_value_v2(
        healthy_state,
        healthy_old,
        salary_cap=cap,
        prior_salary=62_587_158,
        minimum_salary_floor=4_186_651,
        maximum_legal_salary=65_716_515.9,
    )
    checks["healthy_old_star_gets_age_discount_without_fake_medical_penalty"] = (
        healthy.age_risk_factor == .80 and healthy.medical_risk_factor == 1.0
    )

    # Any real recent injury history at 35+ must matter materially.
    mild_history = _player("HIST35", 35, 88, 84)
    mild_state = _state(mild_history, games=78, durability=.90, injuries=1, missed=2)
    mild = mv.calibrated_market_value_v2(
        mild_state,
        mild_history,
        salary_cap=cap,
        prior_salary=30_000_000,
        minimum_salary_floor=4_186_651,
        maximum_legal_salary=62_355_258,
    )
    checks["age_35_any_injury_history_gets_at_least_material_discount"] = mild.medical_risk_factor <= .86

    # Younger players are not crushed by the same medical logic.
    young = _player("YOUNG25", 25, 88, 60)
    young_state = _state(young, games=55, durability=.78, injuries=2, missed=15)
    young_mv = mv.calibrated_market_value_v2(
        young_state,
        young,
        salary_cap=cap,
        prior_salary=12_000_000,
        minimum_salary_floor=2_740_528,
        maximum_legal_salary=44_539_470,
    )
    checks["young_high_risk_player_not_given_old_age_medical_cliff"] = young_mv.medical_risk_factor >= .94

    text = path.read_text(encoding="utf-8")
    checks["version_is_v2_1_or_later"] = any(
        marker in text
        for marker in (
            "v2.1-age-medical-risk-2026-09-12",
            "v2.2-veteran-medical-risk",
            "v2.3-veteran-star-balance",
        )
    )
    checks["archived_availability_is_used_for_long_term_franchise"] = "season_history" in text and "_season_availability_samples" in text
    checks["availability_rating_is_used_as_persistent_history_proxy"] = "availability_rating" in text and "medical_risk_adjustment_v2_1" in text
    checks["legal_salary_clipping_still_present"] = "final = min(final, maximum)" in text

    failed = [k for k, v in checks.items() if not v]
    print({"checks": checks, "failed_checks": failed, "passed": not failed})
    if failed:
        print("FRANCHISE FREE AGENCY MARKET VALUE AGE/MEDICAL RISK V2.1 VALIDATOR FAILED")
        return 1
    print("FRANCHISE FREE AGENCY MARKET VALUE AGE/MEDICAL RISK V2.1 VALIDATOR PASSED")
    print(f"Kawhi-like fixture fair value: ${risk.final_reference/1_000_000:.2f}M")
    print(f"Healthy age-38 star fixture fair value: ${healthy.final_reference/1_000_000:.2f}M")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
