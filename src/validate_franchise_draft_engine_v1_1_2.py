from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "pages" / "5_Franchise_Mode.py"
UI = ROOT / "src" / "franchise_draft_ui_v1.py"
VERSION = "franchise-draft-engine-v1.1.2-validator-sprint-d-authority-2026-08-18"


def _renderer_parameters() -> tuple[str, ...]:
    tree = ast.parse(UI.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "render_draft_room_v1":
            return tuple(arg.arg for arg in [*node.args.args, *node.args.kwonlyargs])
    raise RuntimeError("render_draft_room_v1 was not found.")


def main() -> int:
    text = PAGE.read_text(encoding="utf-8")
    parameters = _renderer_parameters()

    checks = {
        "direct_dispatch_present": "_franchise_draft_ui_v1_live" in text,
        "direct_file_loader_present": "spec_from_file_location" in text,
        "stale_bound_renderer_bypassed": "_draft_renderer(" in text,
        "direct_advance_callback_removed": "advance_next_season" not in parameters,
        "section_callback_supported": "set_section" in parameters,
        "page_does_not_inject_direct_advance_callback": (
            "advance_next_season=advance_to_next_season_with_schedule" not in text
        ),
    }

    failed = [name for name, passed in checks.items() if not passed]
    print("DRAFT V1.1.2 CHECKS")
    for name, passed in checks.items():
        print(f"  {name}: " + ("PASS" if passed else "FAIL"))
    print("RENDER PARAMETERS:", parameters)

    if failed:
        raise AssertionError(
            "Draft V1.1.2 validation failed: " + ", ".join(failed)
        )

    print()
    print("FRANCHISE DRAFT ENGINE V1.1.2 VALIDATION PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
