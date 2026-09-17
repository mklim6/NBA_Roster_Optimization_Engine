from __future__ import annotations

import ast
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from franchise_offseason_headquarters_v1 import (  # noqa: E402
    FRANCHISE_OFFSEASON_HEADQUARTERS_VERSION,
    build_offseason_headquarters_model_v1,
)


def _state(
    *,
    history: int = 1,
    completed: int = 1230,
    day: int = 0,
    active_markets: int = 0,
    signings: int = 0,
    roster: int = 15,
) -> SimpleNamespace:
    return SimpleNamespace(
        phase="offseason",
        settings=SimpleNamespace(season_label="2027-28"),
        season_history=[object()] * history,
        completed_games={str(i): object() for i in range(completed)},
        teams={
            "CHI": SimpleNamespace(
                roster_player_ids=tuple(str(i) for i in range(roster))
            )
        },
        free_agent_player_ids=tuple(str(i) for i in range(200)),
        free_agency_market_calendar_v1={
            "offseason_day": day,
            "active_markets": {
                str(i): {} for i in range(active_markets)
            },
        },
        free_agency_transaction_history=[
            {"team_abbreviation": "CHI"}
        ] * signings,
        offseason_rfa_rights_qo_decisions_v1=[
            {"prior_team": "CHI"}
        ],
        offseason_non_rfa_rights_decisions_v1=[],
    )


def _model(*, draft_phase: str | None, **state_kwargs):
    draft = (
        None
        if draft_phase is None
        else {"phase": draft_phase, "prospects": [{}] * 80}
    )
    return build_offseason_headquarters_model_v1(
        state=_state(**state_kwargs),
        active_team="CHI",
        postseason_state=SimpleNamespace(stage="complete"),
        draft_state_payload=draft,
        team_name_resolver=lambda _: "Chicago Bulls",
        blocking_count=0,
    )


def main() -> int:
    page_path = ROOT / "pages" / "5_Franchise_Mode.py"
    module_path = SRC / "franchise_offseason_headquarters_v1.py"
    page = page_path.read_text(encoding="utf-8") if page_path.exists() else ""
    module = module_path.read_text(encoding="utf-8") if module_path.exists() else ""

    checks = {
        "module_exists": module_path.exists(),
        "page_exists": page_path.exists(),
    }
    try:
        ast.parse(module)
        checks["module_compiles"] = True
    except Exception:
        checks["module_compiles"] = False
    try:
        ast.parse(page)
        checks["page_compiles"] = True
    except Exception:
        checks["page_compiles"] = False

    checks["version_is_v1_family"] = (
        FRANCHISE_OFFSEASON_HEADQUARTERS_VERSION.startswith(
            "franchise-offseason-headquarters-v1."
        )
    )
    checks["page_imports_hq"] = page.count(
        "from franchise_offseason_headquarters_v1 import ("
    ) == 1
    checks["visuals_injected_once"] = page.count(
        "inject_franchise_offseason_headquarters_visuals_v1("
    ) == 1
    checks["full_hq_rendered_once"] = page.count(
        "render_franchise_offseason_headquarters_v1("
    ) == 1
    checks["command_center_preview_rendered_once"] = page.count(
        "render_franchise_offseason_headquarters_preview_v1("
    ) == 1
    checks["legacy_plain_offseason_block_removed"] = (
        "FRANCHISE_FLAGSHIP_OFFSEASON_EXPERIENCE_V1" not in page
    )
    checks["mobile_layout_present"] = (
        "@media(max-width:760px)" in module
        and "@media(max-width:440px)" in module
    )
    checks["stage_sequence_present"] = all(
        token in module
        for token in (
            '"season_review"', '"lottery"', '"scouting"',
            '"draft"', '"rights"', '"free_agency"',
            '"roster_finalization"', '"opening_night"',
        )
    )
    checks["navigation_only_no_checkpoint_commit"] = all(
        forbidden not in module
        for forbidden in (
            "save_franchise_checkpoint",
            "commit_negotiated_user_winner_live",
            "commit_draft",
            "setattr(state",
        )
    )

    post_title = _model(draft_phase=None)
    lottery = _model(draft_phase="lottery_ready")
    scouting = _model(draft_phase="scouting")
    draft = _model(draft_phase="draft_in_progress")
    rights = _model(draft_phase="draft_complete", day=1)
    free_agency = _model(
        draft_phase="draft_complete",
        day=5,
        active_markets=2,
    )
    roster = _model(
        draft_phase="draft_complete",
        day=27,
        signings=2,
    )
    opening = build_offseason_headquarters_model_v1(
        state=_state(history=0, completed=0, day=0),
        active_team="CHI",
        postseason_state=None,
        draft_state_payload=None,
        team_name_resolver=lambda _: "Chicago Bulls",
        blocking_count=0,
    )

    checks["post_title_routes_to_season_review"] = (
        post_title.current_key == "season_review"
    )
    checks["lottery_stage_detected"] = lottery.current_key == "lottery"
    checks["scouting_stage_detected"] = scouting.current_key == "scouting"
    checks["draft_stage_detected"] = draft.current_key == "draft"
    checks["rights_stage_detected"] = rights.current_key == "rights"
    checks["free_agency_stage_detected"] = (
        free_agency.current_key == "free_agency"
    )
    checks["late_offseason_routes_to_roster_finalization"] = (
        roster.current_key == "roster_finalization"
    )
    checks["opening_offseason_skips_prior_season_steps"] = (
        opening.current_key == "roster_finalization"
        and opening.opening_offseason
        and sum(stage.status == "not_required" for stage in opening.stages) == 6
    )
    checks["existing_authoritative_transition_is_not_reimplemented"] = (
        "Open next season control remains below" in module
    )

    failed = [name for name, ok in checks.items() if not ok]
    print({"checks": checks, "failed_checks": failed, "passed": not failed})
    if failed:
        print("FRANCHISE OFFSEASON HEADQUARTERS V1 VALIDATOR FAILED")
        return 1
    print("FRANCHISE OFFSEASON HEADQUARTERS V1 VALIDATOR PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
