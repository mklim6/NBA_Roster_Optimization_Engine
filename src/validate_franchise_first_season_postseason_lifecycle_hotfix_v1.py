from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import ast
import importlib.util

def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def main() -> int:
    project = Path.cwd()
    opening_path = project / "src" / "franchise_opening_night_ux_v1.py"
    onboarding_path = project / "src" / "franchise_onboarding_progression_v1.py"
    visual_path = project / "src" / "franchise_visual_overhaul_v3.py"
    page_path = project / "pages" / "5_Franchise_Mode.py"

    checks = {}
    for label, path in (
        ("opening_source", opening_path),
        ("onboarding_source", onboarding_path),
        ("visual_source", visual_path),
        ("franchise_page", page_path),
    ):
        checks[f"{label}_exists"] = path.exists()
        if path.exists():
            try:
                ast.parse(path.read_text(encoding="utf-8"))
                checks[f"{label}_compiles"] = True
            except Exception:
                checks[f"{label}_compiles"] = False

    opening = _load(opening_path, "_opening_lifecycle_fixture")
    initial = SimpleNamespace(
        phase=SimpleNamespace(value="offseason"),
        transition_count=0,
        season_history=(),
        completed_games={},
    )
    completed_first_year = SimpleNamespace(
        phase=SimpleNamespace(value="offseason"),
        transition_count=0,
        season_history=(),
        completed_games={f"g{i}": object() for i in range(1230)},
    )
    checks["true_opening_offseason_still_detected"] = bool(opening.is_opening_offseason(initial))
    checks["completed_first_season_not_misread_as_opening"] = not bool(
        opening.is_opening_offseason(completed_first_year)
    )

    onboarding = _load(onboarding_path, "_onboarding_lifecycle_fixture")
    idx = onboarding._journey_index(
        phase_name="offseason",
        has_history=False,
        regular_season_complete=True,
        postseason_complete=True,
        draft_complete=False,
    )
    checks["hud_moves_to_offseason_after_first_postseason"] = idx == 3
    action = onboarding._next_action(
        phase_name="offseason",
        has_history=False,
        regular_season_complete=True,
        postseason_complete=True,
        draft_complete=False,
        blocking_count=0,
        next_game_id=None,
    )
    checks["hud_recommends_offseason_build_not_season_opener"] = (
        isinstance(action, tuple)
        and len(action) >= 4
        and action[2] == "Free Agency"
        and action[3] == "Open Free Agency"
    )

    page_text = page_path.read_text(encoding="utf-8")
    checks["opening_control_uses_strict_predicate"] = (
        "def render_opening_regular_season_control_v1" in page_text
        and "if not is_opening_offseason(state):" in page_text
    )
    checks["season_boundary_uses_strict_predicate"] = (
        "if is_opening_offseason(state):" in page_text
        and "completed first season can still have" in page_text
    )
    visual_text = visual_path.read_text(encoding="utf-8")
    checks["showcase_opening_copy_requires_zero_completed_games"] = (
        'and not dict(getattr(state, "completed_games", {}) or {})' in visual_text
    )

    failed = [k for k, v in checks.items() if not v]
    print({"checks": checks, "failed_checks": failed, "passed": not failed})
    if failed:
        print("FRANCHISE FIRST-SEASON POSTSEASON LIFECYCLE HOTFIX V1 VALIDATOR FAILED")
        return 1
    print("FRANCHISE FIRST-SEASON POSTSEASON LIFECYCLE HOTFIX V1 VALIDATOR PASSED")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
