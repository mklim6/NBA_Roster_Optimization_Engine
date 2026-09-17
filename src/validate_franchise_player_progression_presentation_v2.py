from __future__ import annotations

import ast
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    path = root / "src" / "franchise_development_center_v1.py"
    source = path.read_text(encoding="utf-8")

    checks = {}
    try:
        tree = ast.parse(source)
        checks["module_compiles"] = True
    except Exception:
        tree = None
        checks["module_compiles"] = False

    checks["version_is_v2"] = (
        '"franchise-development-center-v2.0-presentation-2026-09-12"'
        in source
    )
    checks["existing_projection_engine_preserved"] = (
        "project_player_development(" in source
        and "player_development_profile(" in source
        and "resolve_performance_signals(" in source
    )
    checks["portrait_integration_present"] = (
        "player_image_url" in source and "def _safe_player_image(" in source
    )
    checks["spotlight_system_present"] = (
        "BREAKOUT WATCH" in source
        and "REGRESSION WATCH" in source
        and "ROLE CHANGE" in source
    )
    checks["player_detail_selector_present"] = (
        "development_center_v2_player_select" in source
    )
    checks["skill_breakdown_present"] = (
        "SKILL_LABELS_V2" in source and "dev2-skill-grid" in source
    )
    checks["development_driver_story_present"] = (
        "def _detail_component_story(" in source
    )
    checks["full_board_preserved"] = (
        'with st.expander("Full Development Board"' in source
    )
    checks["preview_remains_read_only"] = (
        "save_franchise_checkpoint" not in source
        and "commit_franchise_checkpoint" not in source
        and "player.overall_rating =" not in source
    )
    checks["season_boundary_authority_message_present"] = (
        "season-boundary transition remains the authority" in source
    )
    checks["responsive_layout_present"] = (
        "@media(max-width:1000px)" in source
        and "@media(max-width:650px)" in source
    )
    checks["incoming_rookie_support_preserved"] = (
        "Drafted this offseason" in source and "Incoming Rookie" in source
    )
    checks["original_table_columns_preserved"] = all(
        marker in source
        for marker in (
            '"Old OVR"', '"New OVR"', '"Δ OVR"', '"POT"',
            '"Last GP"', '"Last MPG"', '"Projected Role"',
            '"Minutes Guidance"', '"Drivers"'
        )
    )

    # AST-level safeguard: ensure no assignment target mutates player ratings.
    mutation_targets = []
    if tree is not None:
        for node in ast.walk(tree):
            if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                targets = []
                if isinstance(node, ast.Assign):
                    targets = node.targets
                else:
                    targets = [node.target]
                for target in targets:
                    if isinstance(target, ast.Attribute):
                        text = ast.unparse(target)
                        if text in {
                            "player.overall_rating",
                            "player.skill_ratings",
                            "player.potential_rating",
                        }:
                            mutation_targets.append(text)
    checks["no_player_rating_assignment_ast"] = not mutation_targets

    failed = [name for name, ok in checks.items() if not ok]
    print({
        "checks": checks,
        "mutation_targets": mutation_targets,
        "failed_checks": failed,
        "passed": not failed,
    })
    if failed:
        print("FRANCHISE PLAYER PROGRESSION PRESENTATION V2 VALIDATOR FAILED")
        return 1

    print("FRANCHISE PLAYER PROGRESSION PRESENTATION V2 VALIDATOR PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
