from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace


def _load(path: Path):
    spec = importlib.util.spec_from_file_location("offseason_hq_v12", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load module")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    path = root / "src" / "franchise_offseason_headquarters_v1.py"
    source = path.read_text(encoding="utf-8")
    module = _load(path)

    checks = {}
    try:
        ast.parse(source)
        checks["module_compiles"] = True
    except Exception:
        checks["module_compiles"] = False

    checks["version_is_v1_2"] = (
        "v1.2-presentation-scale-2026-09-12"
        in module.FRANCHISE_OFFSEASON_HEADQUARTERS_VERSION
    )
    checks["presentation_scale_marker_present"] = (
        "FRANCHISE_OFFSEASON_HEADQUARTERS_V1_2_PRESENTATION_SCALE" in source
    )
    checks["desktop_stage_rail_is_four_columns"] = (
        ".ohq-rail{grid-template-columns:repeat(4,minmax(0,1fr));gap:10px"
        in source
    )
    checks["hero_title_is_large"] = (
        ".ohq-title{margin:.45rem 0 .5rem;font-size:2.05rem" in source
    )
    checks["stage_names_are_readable"] = (
        ".ohq-stage-name{margin-top:6px;font-size:.77rem" in source
    )
    checks["decision_labels_are_readable"] = (
        ".ohq-v11-check-label{margin-top:6px;font-size:.68rem" in source
    )
    checks["priority_copy_is_readable"] = (
        ".ohq-v11-priority span{margin-top:5px;font-size:.62rem" in source
    )
    checks["finance_values_are_larger"] = (
        ".ohq-v11-fin-card strong{margin-top:6px;font-size:.96rem" in source
    )
    checks["responsive_two_column_stage_rail"] = (
        ".ohq-rail{grid-template-columns:repeat(2,minmax(0,1fr))}" in source
    )
    checks["mobile_single_column_stage_rail"] = (
        ".ohq-rail,.ohq-v11-checks,.ohq-actions{grid-template-columns:1fr}" in source
    )
    checks["navigation_logic_untouched"] = (
        'set_section("Draft Room")' in source
        and 'set_section("Free Agency")' in source
        and 'set_section("Trade Center")' in source
        and 'set_section("Team Management")' in source
    )
    checks["no_checkpoint_commit_added"] = (
        "save_franchise_checkpoint" not in source
        and "commit_franchise_checkpoint" not in source
    )

    players = {
        f"P{i}": SimpleNamespace(player_id=f"P{i}", display_name=f"Player {i}")
        for i in range(9)
    }
    state = SimpleNamespace(
        phase="offseason",
        settings=SimpleNamespace(season_label="2027-28"),
        season_history=[{"season": "2026-27"}],
        completed_games={f"G{i}": object() for i in range(1230)},
        free_agency_market_calendar_v1={
            "offseason_day": 0,
            "active_markets": {},
        },
        teams={"CHI": SimpleNamespace(roster_player_ids=tuple(players))},
        players=players,
        free_agent_player_ids=(),
        free_agency_transaction_history=[],
        offseason_rfa_rights_qo_decisions_v1=[],
        offseason_non_rfa_rights_decisions_v1=[],
    )
    model = module.build_offseason_headquarters_model_v1(
        state=state,
        active_team="CHI",
        postseason_state=SimpleNamespace(stage="complete"),
        draft_state_payload={"phase": "draft_in_progress", "prospects": [{"player_id": "D1"}]},
        team_name_resolver=lambda _: "Chicago Bulls",
    )
    checks["draft_stage_still_detected"] = model.current_key == "draft"
    checks["eight_stage_progression_preserved"] = len(model.stages) == 8

    failed = [name for name, ok in checks.items() if not ok]
    print({"checks": checks, "failed_checks": failed, "passed": not failed})
    if failed:
        print("FRANCHISE OFFSEASON HEADQUARTERS V1.2 VALIDATOR FAILED")
        return 1
    print("FRANCHISE OFFSEASON HEADQUARTERS V1.2 VALIDATOR PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
