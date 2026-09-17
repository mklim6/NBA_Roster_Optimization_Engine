from __future__ import annotations

import importlib.util
import json
import py_compile
from pathlib import Path
from types import SimpleNamespace


VERSION = "franchise-visual-overhaul-v4-validator-2026-09-11"
ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "pages" / "5_Franchise_Mode.py"
VISUAL = ROOT / "src" / "franchise_visual_overhaul_v4.py"
CAREER = ROOT / "src" / "simulation_career_awards_v2.py"


def _contains(path: Path, text: str) -> bool:
    return text in path.read_text(encoding="utf-8")


def _compile(path: Path) -> bool:
    try:
        py_compile.compile(str(path), doraise=True)
        return True
    except Exception:
        return False


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not import {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _career_cache_fixture() -> bool:
    module = _load(CAREER, "career_v4_validation")
    calls = {"history": 0, "draft": 0}

    def fake_history():
        calls["history"] += 1
        return {}, {}

    def fake_draft():
        calls["draft"] += 1
        return {}

    module._history_lookup = fake_history
    module._draft_row_lookup = fake_draft
    player = SimpleNamespace(
        player_id="fixture-1",
        player_name="Fixture Rookie",
        team_abbreviation="CHI",
        age=22.0,
        synthetic=False,
    )
    state = SimpleNamespace(
        settings=SimpleNamespace(season_label="2026-27"),
        players={"fixture-1": player},
    )
    first = module.ensure_career_metadata(state)
    second = module.ensure_career_metadata(state)
    if first != second or calls != {"history": 1, "draft": 1}:
        return False
    state.players["fixture-2"] = SimpleNamespace(
        player_id="fixture-2",
        player_name="Fixture Two",
        team_abbreviation="CHI",
        age=23.0,
        synthetic=False,
    )
    module.ensure_career_metadata(state)
    return calls == {"history": 2, "draft": 2}


def main() -> int:
    page_text = PAGE.read_text(encoding="utf-8")
    visual_text = VISUAL.read_text(encoding="utf-8")
    career_text = CAREER.read_text(encoding="utf-8")

    checks = {
        "visual_v4_module_exists": VISUAL.exists(),
        "page_and_modules_compile": all(_compile(path) for path in (PAGE, VISUAL, CAREER)),
        "page_imports_visual_v4": "from franchise_visual_overhaul_v4 import" in page_text,
        "page_injects_visual_v4": "inject_franchise_visual_overhaul_v4(" in page_text,
        "command_center_uses_custom_metrics": "render_command_center_metrics_v4(snapshot)" in page_text,
        "legacy_command_center_metric_row_removed": "\n    metrics = st.columns(6)\n" not in page_text,
        "schedule_ribbon_rendered_twice": page_text.count("render_schedule_ribbon_v4(") >= 2,
        "game_day_broadcast_preserved": "render_game_day_broadcast_v1(" in page_text,
        "retention_hub_preserved": "render_franchise_retention_hub_v1(" in page_text,
        "v3_layer_preserved": "inject_franchise_visual_overhaul_v3(" in page_text,
        "hero_font_collision_override_exists": ".fxv2-team-name" in visual_text and "3.85rem" in visual_text,
        "recent_form_compact_metric_exists": "fx4-metric-value compact" in visual_text,
        "nba2k_style_schedule_rail_exists": "fx4-rail-shell" in visual_text and "FRANCHISE CALENDAR" in visual_text,
        "career_runtime_cache_exists": "CAREER_METADATA_RUNTIME_CACHE_VERSION" in career_text,
        "career_cache_invalidates_on_registry_change": "career_metadata_runtime_signature_v1" in career_text,
        "career_cache_fixture_passes": _career_cache_fixture(),
        "visual_layer_does_not_mutate_checkpoint": "set_franchise_state" not in visual_text and "checkpoint" not in visual_text.lower(),
    }
    failed = [name for name, passed in checks.items() if not passed]
    result = {
        "version": VERSION,
        "checks": checks,
        "failed_checks": failed,
        "passed": not failed,
    }
    print(json.dumps(result, indent=2))
    if failed:
        print("\nFRANCHISE VISUAL OVERHAUL V4 VALIDATOR FAILED")
        return 1
    print("\nFRANCHISE VISUAL OVERHAUL V4 VALIDATOR PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
