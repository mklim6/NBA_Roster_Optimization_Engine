from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import franchise_free_agency_contract_salary_legality_v1_3 as salary
import franchise_free_agency_cpu_execution_v1 as execution


def _state(season: str, player_id: str):
    return SimpleNamespace(
        settings=SimpleNamespace(season_label=season),
        players={
            player_id: SimpleNamespace(
                player_id=player_id,
                player_name="Service Evidence Test",
            )
        },
    )


def main() -> int:
    ratings_path = ROOT / "app_data" / "player_ratings_2026_27_v2.json"
    payload = json.loads(ratings_path.read_text(encoding="utf-8"))
    rows = payload.get("players_by_id", {})

    candidate_id = None
    baseline = None
    for player_id, row in rows.items():
        raw = row.get("career_seasons") if isinstance(row, dict) else None
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        if math.isfinite(value) and value >= 0 and value.is_integer():
            candidate_id = str(player_id)
            baseline = int(value)
            break

    assert candidate_id is not None
    assert baseline is not None

    anchor_state = _state("2026-27", candidate_id)
    service, source = salary.resolve_years_of_service_for_state(
        anchor_state,
        candidate_id,
    )
    assert service == baseline, (service, baseline, source)
    assert "career_seasons" in source

    future_state = _state("2028-29", candidate_id)
    future_service, future_source = salary.resolve_years_of_service_for_state(
        future_state,
        candidate_id,
    )
    assert future_service == baseline + 2, (
        future_service,
        baseline + 2,
        future_source,
    )

    generated_state = _state("2031-32", "GEN-2027-001")
    generated_service, generated_source = salary.resolve_years_of_service_for_state(
        generated_state,
        "GEN-2027-001",
    )
    assert generated_service == 4, generated_service
    assert generated_source == "generated_player_id_draft_year_progression"

    report = execution.cpu_execution_contract_report()
    assert report["sustainable_completion_preserves_locked_financial_gate"] is True
    assert report["sustainable_completion_requires_player_acceptance"] is True
    assert report["sustainable_completion_uses_market_clearance_override"] is False
    assert report["sustainable_completion_uses_synthetic_players"] is False

    print("FRANCHISE V2 PHASE 1 SERVICE EVIDENCE CHECK PASSED")
    print(f"Baseline player evidence: PASS ({candidate_id}, service={baseline})")
    print("Future-season service progression: PASS")
    print("Generated-player service progression: PASS")
    print("Age inference used: NO")
    print("Financial/CBA gate preserved: PASS")
    print("Player acceptance preserved: PASS")
    print("No franchise checkpoint was loaded or mutated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
