from __future__ import annotations

from pathlib import Path
import hashlib
import importlib.util
import py_compile

ROOT = Path(__file__).resolve().parents[1]
VERSION = "franchise-visual-overhaul-v3-validator-2026-09-11"


def contains(path: Path, text: str) -> bool:
    return text in path.read_text(encoding="utf-8")


def main() -> int:
    home = ROOT / "Home.py"
    page = ROOT / "pages" / "5_Franchise_Mode.py"
    module = ROOT / "src" / "franchise_visual_overhaul_v3.py"
    retention = ROOT / "src" / "franchise_retention_experience_v1.py"
    broadcast = ROOT / "src" / "franchise_game_day_broadcast_v1.py"

    checks = {
        "visual_module_exists": module.exists(),
        "codex_retention_module_preserved": retention.exists() and contains(retention, "FRANCHISE_RETENTION_EXPERIENCE_VERSION"),
        "codex_game_day_broadcast_preserved": broadcast.exists() and contains(broadcast, "FRANCHISE_GAME_DAY_BROADCAST_VERSION"),
        "franchise_imports_visual_v3": contains(page, "from franchise_visual_overhaul_v3 import"),
        "franchise_injects_visual_v3": contains(page, "inject_franchise_visual_overhaul_v3("),
        "command_center_renders_showcase": contains(page, "render_franchise_showcase_v3("),
        "retention_hub_still_rendered": contains(page, "render_franchise_retention_hub_v1("),
        "game_day_broadcast_still_rendered": contains(page, "render_game_day_broadcast_v1("),
        "home_imports_visual_v3": contains(home, "from src.franchise_visual_overhaul_v3 import"),
        "home_renders_flagship_v3": contains(home, "render_home_flagship_v3()"),
        "visual_module_is_presentation_only": all(
            forbidden not in module.read_text(encoding="utf-8")
            for forbidden in (
                "save_franchise_checkpoint",
                "commit_trade",
                "commit_signing",
                "install_regular_season_schedule",
                "advance_franchise",
                "pickle.dump",
            )
        ),
    }

    compile_targets = [home, page, module, retention, broadcast]
    for target in compile_targets:
        try:
            py_compile.compile(str(target), doraise=True)
            checks[f"compiles::{target.name}"] = True
        except Exception:
            checks[f"compiles::{target.name}"] = False

    failed = [key for key, value in checks.items() if not value]
    import json
    print(json.dumps({"version": VERSION, "checks": checks, "failed_checks": failed, "passed": not failed}, indent=2))
    if failed:
        print("\nFRANCHISE VISUAL OVERHAUL V3 VALIDATOR FAILED")
        return 1
    print("\nFRANCHISE VISUAL OVERHAUL V3 VALIDATOR PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
