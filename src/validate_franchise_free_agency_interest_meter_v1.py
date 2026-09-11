from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
PAGE = ROOT / "pages" / "6_Free_Agency.py"
CHECKPOINT = ROOT / "outputs" / "runtime" / "franchise_mode_checkpoint_v1.pkl.gz"

import sys
sys.path.insert(0, str(SRC))

from franchise_free_agency_interest_meter_v1 import (
    FREE_AGENCY_INTEREST_METER_SCOPE,
    FREE_AGENCY_INTEREST_METER_UI_VERSION,
    FREE_AGENCY_INTEREST_METER_VERSION,
    _rows_from_decisions,
    interest_band,
    interest_meter_value,
)

EXPECTED = "franchise-free-agency-player-interest-meter-v1-2026-08-14"
EXPECTED_UI = "franchise-free-agency-player-interest-meter-ui-v1-2026-08-14"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else ""


def fake(team, utility, threshold, status, salary, years, salary_score, role, winning, security, career):
    return SimpleNamespace(
        team_abbreviation=team,
        utility_score=utility,
        acceptance_threshold=threshold,
        status=status,
        annual_salary=salary,
        years=years,
        guaranteed=True,
        option_type="",
        salary_score=salary_score,
        role_score=role,
        winning_score=winning,
        security_score=security,
        career_fit_score=career,
    )


def main() -> int:
    before = sha(CHECKPOINT)
    page = PAGE.read_text(encoding="utf-8")
    decisions = [
        fake("BKN", 78.2, 61.0, "accept", 27_000_000, 4, 91, 75, 55, 95, 70),
        fake("DAL", 63.4, 61.0, "accept", 25_500_000, 3, 87, 68, 72, 82, 66),
        fake("DET", 57.8, 61.0, "counter", 23_000_000, 3, 80, 92, 42, 82, 85),
        fake("WAS", 39.1, 61.0, "decline", 15_000_000, 2, 51, 80, 25, 63, 62),
    ]
    rows = _rows_from_decisions(decisions, user_team_abbreviation="DAL")

    checks = {
        "interest_meter_version_is_current": FREE_AGENCY_INTEREST_METER_VERSION == EXPECTED,
        "interest_meter_ui_version_is_current": FREE_AGENCY_INTEREST_METER_UI_VERSION == EXPECTED_UI,
        "interest_meter_is_display_only": "display_only" in FREE_AGENCY_INTEREST_METER_SCOPE,
        "meter_clamps_low": interest_meter_value(-5) == 0,
        "meter_clamps_high": interest_meter_value(120) == 100,
        "meter_rounds_utility": interest_meter_value(72.6) == 73,
        "very_high_band_works": interest_band(78, 61, "accept") == "Very high",
        "high_band_works": interest_band(63, 61, "accept") == "High",
        "counter_band_works": interest_band(58, 61, "counter") == "Medium",
        "low_band_works": interest_band(39, 61, "decline") == "Low",
        "rows_include_every_offer": len(rows) == 4,
        "rows_rank_by_interest": [r.team_abbreviation for r in rows] == ["BKN", "DAL", "DET", "WAS"],
        "user_offer_is_identified": next(r for r in rows if r.team_abbreviation == "DAL").is_user_offer,
        "gap_to_acceptance_is_exact": abs(next(r for r in rows if r.team_abbreviation == "DET").gap_to_acceptance + 3.2) < 1e-9,
        "component_scores_are_preserved": next(r for r in rows if r.team_abbreviation == "DET").role_score == 92.0,
        "page_imports_interest_meter": "from franchise_free_agency_interest_meter_v1 import" in page,
        "page_has_player_interest_section": 'st.markdown("#### Player interest by team")' in page,
        "page_explains_not_probability": "not a signing probability" in page.lower(),
        "page_renders_visual_meter": "st.progress(" in page and "interest_meter_value" in page,
        "page_shows_acceptance_line": "Acceptance line" in page,
        "page_lists_all_offer_interest": '"Interest": row.interest_score' in page,
        "page_lists_interest_components": '"Role": row.role_score' in page and '"Winning": row.winning_score' in page,
        "page_does_not_add_direct_checkpoint_save": "save_franchise_checkpoint(" not in page,
        "page_does_not_add_direct_transaction_commit": "commit_contract_legal_free_agency_preview_live(" not in page,
        "page_compiles": True,
        "validator_did_not_write_checkpoint": before == sha(CHECKPOINT),
    }

    try:
        compile(page, str(PAGE), "exec")
    except Exception:
        checks["page_compiles"] = False

    print("=" * 108)
    print("FREE AGENCY PLAYER INTEREST METER V1 VALIDATION")
    print("=" * 108)
    for name, passed in checks.items():
        print(f"  {name}: {'PASS' if passed else 'FAIL'}")
    print("\nTOY INTEREST BOARD")
    for row in rows:
        print(
            f"  #{row.rank} {row.team_abbreviation} · {row.interest_score:.1f}/100 · {row.interest_band} · "
            f"threshold {row.acceptance_threshold:.1f} · {row.player_decision_status.upper()}"
        )
    failed = [name for name, passed in checks.items() if not passed]
    print(f"\nfailed_checks: {failed}")
    if failed:
        print("\nFREE AGENCY PLAYER INTEREST METER V1 VALIDATION FAILED")
        return 1
    print("\nFREE AGENCY PLAYER INTEREST METER V1 VALIDATION PASSED")
    print("DISPLAY ONLY: the meter does not create offers, advance negotiations, sign players, or write the checkpoint.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
