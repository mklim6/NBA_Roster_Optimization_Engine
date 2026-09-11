from __future__ import annotations

import copy
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "pages" / "5_Franchise_Mode.py"
VERSION = "franchise-draft-engine-validator-v1-2026-08-11"


def main() -> int:
    from franchise_draft_engine_v1 import (
        AI_PICK_CLOCK_SECONDS,
        DRAFT_ENGINE_VERSION,
        LOTTERY_RULE_VERSION,
        run_self_test,
    )

    self_test = run_self_test()
    page = PAGE.read_text(encoding="utf-8")
    career = (ROOT / "src" / "simulation_career_awards_v2.py").read_text(encoding="utf-8")
    checks = {
        "draft_engine_self_test": bool(self_test.get("passed")),
        "engine_version_current": DRAFT_ENGINE_VERSION == (
            "franchise-draft-engine-v1.1-2026-08-11+"
            "pick-forfeitures-v1-2026-09-07"
        ),
        "lottery_rule_is_321": LOTTERY_RULE_VERSION == "nba-3-2-1-lottery-2027-2029",
        "ai_clock_is_two_minutes": AI_PICK_CLOCK_SECONDS == 120,
        "draft_room_navigation": '"Draft Room"' in page and '"Draft Room": "Draft"' in page,
        "draft_ui_renderer": "_draft_renderer(" in page
        and "def render_draft_room_v1(" in (ROOT / "src" / "franchise_draft_ui_v1.py").read_text(encoding="utf-8"),
        "postseason_gate": "draft_is_complete(state)" in page,
        "draft_lottery_entry": "Enter NBA Draft Lottery" in page,
        "rookie_activation_after_transition": "activate_drafted_rookies_after_transition(" in page,
        "open_next_season_preserved": '"Open next season"' in page,
        "generated_rookie_metadata_persists": all(
            marker in career
            for marker in (
                'setattr(player, "draft_year", draft_year)',
                'setattr(player, "draft_round", draft_round)',
                'setattr(player, "draft_pick", draft_pick)',
                '"generated_prospect",',
            )
        ),
        "medical_profile_sync_for_draftees": "synchronize_injury_profile(state, player_id)" in (ROOT / "src" / "franchise_draft_engine_v1.py").read_text(encoding="utf-8"),
    }

    checkpoint_summary = {"found": False}
    try:
        from simulation_franchise_checkpoint_v1 import load_franchise_checkpoint
        from franchise_draft_engine_v1 import lottery_participants_321
        checkpoint = load_franchise_checkpoint()
        if checkpoint is not None:
            checkpoint_summary["found"] = True
            state = checkpoint.simulation_state
            checkpoint_summary["season"] = state.settings.season_label
            postseason = getattr(state, "postseason_state", None)
            if postseason is not None and str(getattr(postseason.stage, "value", postseason.stage)).lower() == "complete":
                participants = lottery_participants_321(copy.deepcopy(state))
                checkpoint_summary["lottery_participants"] = len(participants)
                checks["live_completed_checkpoint_has_16_lottery_teams"] = len(participants) == 16
    except Exception as exc:
        checkpoint_summary["error"] = str(exc)

    failed = [name for name, passed in checks.items() if not passed]
    report = {
        "script": VERSION,
        "checks": checks,
        "self_test": self_test,
        "checkpoint": checkpoint_summary,
        "failed_checks": failed,
        "passed": not failed,
    }
    print(json.dumps(report, indent=2))
    if failed:
        raise AssertionError("Draft Engine V1 validation failed: " + ", ".join(failed))
    print()
    print("FRANCHISE DRAFT ENGINE V1 VALIDATION PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
