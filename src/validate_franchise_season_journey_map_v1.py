from __future__ import annotations
from pathlib import Path
import importlib.util
import json
import py_compile
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "pages" / "5_Franchise_Mode.py"
MODULE = ROOT / "src" / "franchise_season_journey_map_v1.py"
VERSION = "franchise-season-journey-map-v1-validator-2026-09-11"

page = PAGE.read_text(encoding="utf-8") if PAGE.is_file() else ""
module_text = MODULE.read_text(encoding="utf-8") if MODULE.is_file() else ""
compile_error = ""
try:
    py_compile.compile(str(PAGE), doraise=True)
    py_compile.compile(str(MODULE), doraise=True)
except Exception as exc:
    compile_error = str(exc)

fixture_game_1 = SimpleNamespace(game_id="g1", day_index=1, home_team="CHI", away_team="BOS", status=SimpleNamespace(value="completed"))
fixture_game_2 = SimpleNamespace(game_id="g2", day_index=5, home_team="NYK", away_team="CHI", status=SimpleNamespace(value="scheduled"))
fixture = SimpleNamespace(
    settings=SimpleNamespace(season_label="2026-27"),
    phase=SimpleNamespace(value="regular_season"),
    season_history=[],
    schedule={"g1": fixture_game_1, "g2": fixture_game_2},
    completed_games={"g1": object()},
)
fixture_model_ok = False
fixture_detail = ""
if MODULE.is_file():
    try:
        import sys
        from types import ModuleType
        if "streamlit" not in sys.modules:
            sys.modules["streamlit"] = ModuleType("streamlit")
        spec = importlib.util.spec_from_file_location("_journey_validator_live", MODULE)
        mod = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        sys.modules[spec.name] = mod
        spec.loader.exec_module(mod)
        model = mod.build_season_journey_model_v1(
            state=fixture,
            active_team="CHI",
            postseason_state=None,
            draft_state_payload=None,
            team_name_resolver=lambda t: {"NYK":"New York Knicks","BOS":"Boston Celtics"}.get(t,t),
            date_resolver=lambda day: f"Day {day}",
        )
        fixture_model_ok = (
            model.current_key == "regular"
            and model.current_label == "Regular Season"
            and "1/2" in model.current_detail
            and model.next_event_label == "Next Game"
            and "New York Knicks" in model.next_event_detail
        )
        fixture_detail = repr(model)
    except Exception as exc:
        fixture_detail = str(exc)

checks = {
    "journey_module_exists": MODULE.is_file(),
    "page_imports_journey_layer": "from franchise_season_journey_map_v1 import" in page,
    "page_injects_journey_visuals": "inject_franchise_season_journey_visuals_v1(" in page,
    "home_has_compact_journey": "render_franchise_season_journey_preview_v1(" in page,
    "league_hub_has_full_journey": "render_franchise_season_journey_map_v1(" in page,
    "journey_uses_durable_postseason_state": "postseason_state=get_postseason_state(state, required=False)" in page,
    "journey_uses_durable_draft_state": "draft_state_payload=draft_state(state)" in page,
    "actual_next_game_date_resolver": "date_resolver=lambda day_index: date_for_day_index(" in page,
    "seven_lifecycle_milestones": all(label in module_text for label in ["Opening Night","Regular Season","Playoffs","Draft Lottery","Scouting","Draft Night","Offseason Build"]),
    "read_only_copy_present": "This map is read-only" in module_text,
    "no_checkpoint_write_in_module": "save_current_franchise_checkpoint" not in module_text and "set_franchise_state" not in module_text,
    "fixture_regular_season_routing": fixture_model_ok,
    "python_compile": not compile_error,
    "version_current": "franchise-season-journey-map-v1.0-2026-09-11" in module_text,
}
failed = [key for key, value in checks.items() if not value]
print(json.dumps({"version": VERSION, "checks": checks, "failed_checks": failed, "fixture_detail": fixture_detail, "compile_error": compile_error, "passed": not failed}, indent=2))
if failed:
    raise SystemExit(1)
print("FRANCHISE SEASON JOURNEY MAP V1 VALIDATOR PASSED")
