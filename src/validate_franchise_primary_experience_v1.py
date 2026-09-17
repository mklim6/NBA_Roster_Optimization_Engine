from __future__ import annotations

from pathlib import Path
import py_compile
import sys

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
NAV = SRC / "franchise_primary_navigation_v1.py"
PAGES = [
    ROOT / "Home.py",
    ROOT / "pages/1_Trade_Lab.py",
    ROOT / "pages/2_Player_Ratings.py",
    ROOT / "pages/3_Trade_Machine.py",
    ROOT / "pages/4_Game_Simulator.py",
    ROOT / "pages/5_Franchise_Mode.py",
    ROOT / "pages/6_Free_Agency.py",
]

checks = {}
checks["navigation_module_exists"] = NAV.exists()
if NAV.exists():
    text = NAV.read_text(encoding="utf-8")
    checks["navigation_version_is_current"] = "franchise-primary-navigation-v1-2026-09-11" in text
    checks["native_sidebar_navigation_hidden"] = 'stSidebarNav' in text and 'display:none' in text
    checks["franchise_is_main_experience"] = "Main Experience" in text and 'pages/5_Franchise_Mode.py' in text
    checks["supporting_tools_are_grouped"] = "Supporting Tools" in text and "Sandboxes & Analysis" in text
    checks["navigation_has_no_engine_imports"] = all(token not in text for token in [
        "simulation_franchise_checkpoint", "franchise_trade_transaction", "franchise_free_agency_transaction",
        "franchise_draft_engine", "pickle", "joblib"
    ])
    try:
        py_compile.compile(str(NAV), doraise=True)
        checks["navigation_module_compiles"] = True
    except Exception:
        checks["navigation_module_compiles"] = False

for page in PAGES:
    key = page.name.replace(".py", "")
    if page.exists():
        page_text = page.read_text(encoding="utf-8")
        checks[f"{key}_has_primary_nav_hook"] = "FRANCHISE_PRIMARY_NAV_V1" in page_text
        try:
            py_compile.compile(str(page), doraise=True)
            checks[f"{key}_compiles"] = True
        except Exception:
            checks[f"{key}_compiles"] = False
    else:
        checks[f"{key}_exists"] = False

home = ROOT / "Home.py"
if home.exists():
    home_text = home.read_text(encoding="utf-8")
    checks["home_title_is_franchise_first"] = "NBA Franchise Simulator" in home_text
    checks["home_calls_franchise_flagship"] = "Flagship franchise management simulator" in home_text

failed = [k for k, v in checks.items() if not v]
print({"version": "franchise-primary-experience-v1-validator-2026-09-11", "checks": checks, "failed_checks": failed, "passed": not failed})
if failed:
    print("FRANCHISE PRIMARY EXPERIENCE V1 VALIDATOR FAILED")
    sys.exit(1)
print("FRANCHISE PRIMARY EXPERIENCE V1 VALIDATOR PASSED")
