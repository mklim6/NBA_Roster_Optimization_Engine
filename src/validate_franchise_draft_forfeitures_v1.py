from __future__ import annotations

from franchise_draft_forfeitures_v1 import (
    DRAFT_PICK_FORFEITURES,
    apply_draft_pick_forfeitures,
    expected_draft_pick_count,
)


def main() -> int:
    source_ids = {item.source_asset_id for item in DRAFT_PICK_FORFEITURES}
    fixture_rows = [
        {
            "asset_id": f"fixture-{source_id}",
            "draft_year": int(source_id[:4]),
            "round": 1,
            "origin_team": source_id.rsplit("_", 1)[-1],
            "current_owner": "LAC",
            "asset_type": "fixture",
            "source_assets": source_id,
            "tradability_status": "Engine Ready",
            "manual_review_required": False,
            "engine_ready": True,
        }
        for source_id in sorted(source_ids)
    ]
    fixture_rows.append(
        {
            "asset_id": "fixture-2029-lac-phi-swap",
            "draft_year": 2029,
            "round": 1,
            "origin_team": "LAC, PHI",
            "current_owner": "LAC",
            "asset_type": "fixture",
            "source_assets": "2029_R1_LAC | 2029_R1_PHI",
            "tradability_status": "Manual Review",
            "manual_review_required": True,
            "engine_ready": False,
        }
    )

    resolved = apply_draft_pick_forfeitures(fixture_rows)
    forfeited = [
        row
        for row in resolved
        if row.get("forfeiture_status") == "forfeited"
    ]
    swap = next(
        row
        for row in resolved
        if row["asset_id"] == "fixture-2029-lac-phi-swap"
    )
    checks = {
        "five_exact_forfeited_assets": (
            len(DRAFT_PICK_FORFEITURES) == 5
            and source_ids
            == {
                "2029_R1_IND",
                "2030_R1_LAC",
                "2031_R1_LAC",
                "2032_R1_LAC",
                "2033_R1_LAC",
            }
        ),
        "affected_drafts_have_59_picks": all(
            expected_draft_pick_count(year) == 59
            for year in range(2029, 2034)
        ),
        "unaffected_drafts_have_60_picks": (
            expected_draft_pick_count(2028) == 60
            and expected_draft_pick_count(2034) == 60
        ),
        "forfeitures_are_not_tradeable_or_owned": all(
            not row["current_owner"]
            and not row["engine_ready"]
            and row["asset_type"] == "forfeited_draft_pick"
            for row in forfeited
        ),
        "separate_2029_lac_phi_swap_is_preserved": (
            swap["forfeiture_status"] == "active"
            and swap["current_owner"] == "LAC"
        ),
    }
    failed = [name for name, passed in checks.items() if not passed]
    print("DRAFT PICK FORFEITURE V1 CHECKS")
    for name, passed in checks.items():
        print(f"  {name}: {'PASS' if passed else 'FAIL'}")
    if failed:
        raise AssertionError(
            "Draft-pick forfeiture validation failed: " + ", ".join(failed)
        )
    print("\nDRAFT PICK FORFEITURE V1 VALIDATION PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
