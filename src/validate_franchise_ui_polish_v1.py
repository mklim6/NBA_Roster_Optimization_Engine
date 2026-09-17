from __future__ import annotations

import ast
import hashlib
import py_compile
from pathlib import Path

VERSION = "franchise-ui-polish-v2-validator-2026-09-11"
EXPECTED_POLISH_VERSION = "franchise-ui-polish-v2.0-2026-09-11"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    page = root / "pages" / "5_Franchise_Mode.py"
    module = root / "src" / "franchise_ui_polish_v1.py"

    checks: dict[str, bool] = {}
    checks["polish_module_exists"] = module.is_file()
    checks["franchise_page_exists"] = page.is_file()

    module_text = module.read_text(encoding="utf-8") if module.is_file() else ""
    page_text = page.read_text(encoding="utf-8") if page.is_file() else ""

    checks["polish_version_is_current"] = EXPECTED_POLISH_VERSION in module_text
    checks["polish_module_parses"] = False
    checks["franchise_page_parses"] = False
    try:
        ast.parse(module_text)
        checks["polish_module_parses"] = True
    except SyntaxError:
        pass
    try:
        ast.parse(page_text)
        checks["franchise_page_parses"] = True
    except SyntaxError:
        pass

    checks["polish_import_installed_once"] = (
        page_text.count(
            "from franchise_ui_polish_v1 import inject_franchise_ui_polish_v1"
        ) == 1
    )
    checks["polish_call_installed_once"] = (
        page_text.count("inject_franchise_ui_polish_v1(") == 1
    )
    checks["polish_call_uses_team_colors"] = (
        "inject_franchise_ui_polish_v1(\n    primary=primary,\n    secondary=secondary,\n)"
        in page_text.replace("\r\n", "\n")
    )
    checks["sticky_workspace_nav_present"] = ".st-key-franchise_active_section" in module_text
    checks["metric_card_polish_present"] = 'div[data-testid="stMetric"]' in module_text
    checks["sidebar_polish_present"] = '[data-testid="stSidebar"]' in module_text
    checks["table_polish_present"] = '[data-testid="stDataFrame"]' in module_text
    checks["mobile_rules_present"] = "@media (max-width:760px)" in module_text
    checks["reduced_motion_rules_present"] = "prefers-reduced-motion:reduce" in module_text
    checks["keyboard_focus_present"] = ":focus-visible" in module_text
    checks["presentation_only_contract"] = not any(
        token in module_text
        for token in (
            "save_franchise_checkpoint(",
            "commit_",
            "apply_rotation_plan(",
            "advance_franchise_scope(",
            "trade_state",
            "free_agency_transaction",
        )
    )

    if module.is_file():
        py_compile.compile(str(module), doraise=True)
    if page.is_file():
        py_compile.compile(str(page), doraise=True)

    failed = [name for name, passed in checks.items() if not passed]
    print({"version": VERSION, "checks": checks, "failed_checks": failed, "passed": not failed})
    if failed:
        print("FRANCHISE UI POLISH V2 VALIDATOR FAILED")
        return 1
    print("FRANCHISE UI POLISH V2 VALIDATOR PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
