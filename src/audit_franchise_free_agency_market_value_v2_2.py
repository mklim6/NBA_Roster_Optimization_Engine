from __future__ import annotations

from pathlib import Path
import csv
import math

from simulation_franchise_checkpoint_v1 import load_franchise_checkpoint
from franchise_free_agency_financial_bridge_v1_2 import resolve_free_agency_financial_environment
from franchise_free_agency_prior_salary_v1 import resolve_prior_salary
from franchise_free_agency_contract_salary_legality_v1_3 import (
    resolve_years_of_service,
    minimum_salary_floor_for_state,
    maximum_initial_salary_for_state,
)
from franchise_free_agency_market_value_v2 import (
    FREE_AGENCY_MARKET_VALUE_CALIBRATION_VERSION,
    calibrated_market_value_v2,
    legacy_market_value_v1,
)


def _num(value):
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def main() -> int:
    checkpoint = load_franchise_checkpoint()
    if checkpoint is None:
        print("No active franchise checkpoint was found. Audit did not modify anything.")
        return 1
    state = checkpoint.simulation_state
    env = resolve_free_agency_financial_environment(state)
    if env.status != "pass" or env.salary_cap is None:
        print(f"Free Agency financial environment is not audit-ready: {env.reason}")
        return 1

    rows = []
    for player_id in tuple(getattr(state, "free_agent_player_ids", ()) or ()):
        player = getattr(state, "players", {}).get(player_id)
        if player is None:
            continue
        service, service_source = resolve_years_of_service(player)
        contract = getattr(player, "contract", None)
        prior = _num(getattr(contract, "salary", None)) if contract is not None else None
        if prior is None or prior <= 0:
            prior = _num(resolve_prior_salary(state, player_id))
        minimum = minimum_salary_floor_for_state(
            state,
            years_of_service=service,
            contract_years=1,
        )
        maximum = maximum_initial_salary_for_state(
            state,
            years_of_service=service,
            prior_salary=prior,
        )
        old = legacy_market_value_v1(
            player,
            salary_cap=float(env.salary_cap),
            prior_salary=prior,
            minimum_salary_floor=minimum,
            maximum_legal_salary=maximum,
        )
        v2 = calibrated_market_value_v2(
            state,
            player,
            salary_cap=float(env.salary_cap),
            prior_salary=prior,
            minimum_salary_floor=minimum,
            maximum_legal_salary=maximum,
        )
        rows.append({
            "player_id": player_id,
            "player_name": getattr(player, "player_name", player_id),
            "position": getattr(player, "position", ""),
            "age": getattr(player, "age", None),
            "overall": getattr(player, "overall_rating", None),
            "potential": getattr(player, "potential_rating", None),
            "years_of_service": service,
            "service_source": service_source,
            "prior_salary": prior,
            "legacy_fair_value": old,
            "v2_fair_value": v2.final_reference,
            "change_dollars": v2.final_reference - old,
            "change_pct": ((v2.final_reference / old) - 1.0) if old else None,
            "age_factor": v2.age_risk_factor,
            "medical_risk_factor": v2.medical_risk_factor,
            "medical_risk_tier": v2.medical_risk_tier,
            "availability_rating": v2.availability_rating,
            "durability": v2.durability,
            "recent_injuries_suffered": v2.recent_injuries_suffered,
            "medical_games_missed": v2.medical_games_missed,
            "multi_season_availability_rate": v2.multi_season_availability_rate,
            "production_factor": v2.production_factor,
            "efficiency_factor": v2.efficiency_factor,
            "availability_factor": v2.availability_factor,
            "recent_form_factor": v2.recent_form_factor,
            "evidence_games": v2.evidence_games,
            "evidence_minutes": v2.evidence_minutes,
            "true_shooting": v2.true_shooting,
            "availability_rate": v2.availability_rate,
            "prior_salary_weight": v2.prior_salary_weight,
            "minimum_salary_floor": minimum,
            "maximum_legal_salary": maximum,
        })

    rows.sort(key=lambda r: (-float(r["v2_fair_value"] or 0.0), str(r["player_name"])))
    out_dir = Path("outputs") / "free_agency"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "market_value_calibration_v2_2_audit.csv"
    with out_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()) if rows else ["player_id"])
        writer.writeheader()
        writer.writerows(rows)

    print(f"FREE AGENCY MARKET VALUE V2.2 VETERAN MEDICAL-RISK AUDIT COMPLETE · {len(rows)} player(s)")
    print(f"Version: {FREE_AGENCY_MARKET_VALUE_CALIBRATION_VERSION}")
    print(f"Output: {out_path.resolve()}")
    print("Active checkpoint mutation: NONE")
    print("\nTop 15 V2.2 fair values:")
    for row in rows[:15]:
        old = float(row["legacy_fair_value"] or 0.0)
        new = float(row["v2_fair_value"] or 0.0)
        pct = ((new / old) - 1.0) * 100.0 if old else 0.0
        print(f"  {row['player_name']:<28} {new/1_000_000:6.2f}M  ({pct:+5.1f}% vs V1)")

    print("\nAge 34+ medical-risk watch:")
    older = [r for r in rows if (r.get("age") or 0) >= 34 and r.get("medical_risk_tier") not in {"none", None, ""}]
    older.sort(key=lambda r: (-float(r.get("v2_fair_value") or 0.0), str(r.get("player_name") or "")))
    for row in older[:20]:
        av = row.get("availability_rating")
        av_text = "?" if av is None else f"{float(av):.1f}"
        print(
            f"  {row['player_name']:<28} age={float(row['age']):.0f} "
            f"fair={float(row['v2_fair_value'])/1_000_000:5.2f}M "
            f"medical={row['medical_risk_tier']:<8} x{float(row['medical_risk_factor']):.2f} "
            f"AVL={av_text}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
