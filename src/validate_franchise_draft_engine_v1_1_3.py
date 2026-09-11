from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
PAGE = ROOT / "pages" / "5_Franchise_Mode.py"
UI = SRC / "franchise_draft_ui_v1.py"
VERSION = "franchise-draft-engine-v1.1.3-validator-sprint-d-authority-2026-08-18"


def _ui_metadata() -> tuple[tuple[str, ...], str]:
    text = UI.read_text(encoding="utf-8")
    tree = ast.parse(text)
    params: tuple[str, ...] | None = None
    version = ""
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "DRAFT_UI_VERSION":
                    if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                        version = node.value.value
        if isinstance(node, ast.FunctionDef) and node.name == "render_draft_room_v1":
            params = tuple(arg.arg for arg in [*node.args.args, *node.args.kwonlyargs])
    if params is None:
        raise RuntimeError("render_draft_room_v1 was not found.")
    return params, version


def main() -> int:
    text = PAGE.read_text(encoding="utf-8")
    parameters, ui_version = _ui_metadata()

    checks = {
        "v112_direct_dispatch_retained": "_franchise_draft_ui_v1_live" in text,
        "src_path_repair_present": "_draft_src_text = str(_draft_ui_runtime_path.parent)" in text,
        "src_path_insert_present": "_draft_sys.path.insert(0, _draft_src_text)" in text,
        "stale_engine_evicted": '_draft_sys.modules.pop("franchise_draft_engine_v1", None)' in text,
        "direct_advance_callback_removed": "advance_next_season" not in parameters,
        "section_callback_supported": "set_section" in parameters,
        "ui_v11_active": ui_version.startswith("franchise-draft-ui-v1.1"),
        "draft_room_routes_to_authoritative_boundary": (
            "Return to Season Boundary" in UI.read_text(encoding="utf-8")
        ),
    }

    failed = [name for name, passed in checks.items() if not passed]
    print("DRAFT V1.1.3 CHECKS")
    for name, passed in checks.items():
        print(f"  {name}: " + ("PASS" if passed else "FAIL"))
    print("RENDER PARAMETERS:", parameters)
    print("UI VERSION:", ui_version)

    if failed:
        raise AssertionError(
            "Draft V1.1.3 validation failed: " + ", ".join(failed)
        )

    print()
    print("FRANCHISE DRAFT ENGINE V1.1.3 VALIDATION PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
