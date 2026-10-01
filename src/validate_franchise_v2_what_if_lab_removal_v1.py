from __future__ import annotations

import hashlib
import py_compile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "pages" / "5_Franchise_Mode.py"
SRC = ROOT / "src"
ACTIVE = ROOT / "outputs" / "runtime" / "franchise_mode_checkpoint_v1.pkl.gz"

EXPECTED_PAGE_SHA = "d2c1e07b11797d988c341659a979863c510880e716e7cf3feab19b3aebf74514"

EXPECTED_VALIDATORS = {
    "validate_franchise_cpu_autonomous_trade_market_v6a.py": "aeae3cfed75015f9ce4295694049400fe0a49b66d0ae98535663ed4e0868ea84",
    "validate_franchise_cpu_incoming_trade_offers_v6b.py": "e2acb0d7dbc8080e3e1dde5a7cc23388c358aed10bf5d1274b9458104e5f3852",
    "validate_franchise_postgame_performance_offer_hotfix_v6_0_1.py": "6dc39c6106b76e5ff865ee8251d4d1116cababf3625f56c5d967d6e7e98d92d1",
    "validate_franchise_game_day_league_calendar_sync_v1.py": "1e898f56a8a76ae460a26182fee1d2306969cfdb46a9de223839360dcf87a3ca",
    "validate_franchise_command_center_v1.py": "b26da15b5b6fa274be79279d1a2e8f1944bf182c64bc4eb2d137be46f6928c3b",
    "validate_franchise_health_game_day_repair_v1.py": "d329dbdd1dbaf25fa7b544ee97d91b5ce93f31bee7bc35755f1300c2b8fd1280",
    "validate_injury_fatigue_v1.py": "16831fe020c6aec61a2cfb17ed51ae45647ae737a4e54639f188de563a656ee7",
    "validate_simulation_postseason_v1.py": "deab1f108bc8e2a54f9902a9a54bffacd15127de540db04cbec9e56ec946f8ec",
}


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def main() -> int:
    active_before = sha(ACTIVE) if ACTIVE.is_file() else ""

    page = PAGE.read_text(encoding="utf-8")
    checks = {
        "exact_removed_page": sha(PAGE) == EXPECTED_PAGE_SHA,
        "advanced_lab_removed": "Advanced What-If Lab" not in page,
        "regular_preview_button_removed": "Run what-if simulation" not in page,
        "regular_preview_result_removed": "What-if result only" not in page,
        "postseason_preview_button_removed": (
            "What-if preview" not in page
            and "What-if next game" not in page
        ),
        "sandbox_result_copy_removed": "Sandbox result only." not in page,
        "sandbox_medical_copy_removed": "Sandbox medical outcome" not in page,
        "regular_commit_false_path_removed": "commit=False" not in page,
        "postseason_preview_execution_removed": "simulate_postseason_game(" not in page,
        "regular_game_commit_preserved": (
            '"Simulate game"' in page
            and "commit_game_transactionally(" in page
            and "catch_up_cpu_schedule_v1(" in page
            and "run_cpu_autonomous_trade_market_v1(" in page
            and "run_cpu_incoming_trade_offer_tick_v1(" in page
        ),
        "rest_decisions_preserved": "Players to rest or sit" in page,
        "postseason_commit_preserved": (
            "Simulate & commit" in page
            and "commit_postseason_game(" in page
            and "Sim current stage" in page
            and "Sim to champion" in page
        ),
        "postseason_bulk_simulation_preserved": (
            "advance_postseason_with_progress(" in page
            and "PostseasonSimulationScope" in page
        ),
        "legacy_regular_preview_state_is_cleanup_only": (
            page.count('"franchise_game_preview"') == 1
            and page.count('"franchise_game_preview_request"') == 1
            and 'st.session_state["franchise_game_preview"] =' not in page
            and 'st.session_state["franchise_game_preview_request"] =' not in page
        ),
    }

    for name, expected in EXPECTED_VALIDATORS.items():
        path = SRC / name
        checks[f"validator_{name}"] = (
            path.is_file()
            and sha(path) == expected
        )
        if path.is_file():
            py_compile.compile(str(path), doraise=True)

    py_compile.compile(str(PAGE), doraise=True)

    active_after = sha(ACTIVE) if ACTIVE.is_file() else ""
    checks["active_checkpoint_unchanged"] = active_before == active_after

    print("FRANCHISE V2 WHAT-IF LAB REMOVAL V1")
    for name, passed in checks.items():
        print(f"  {name}: {'PASS' if passed else 'FAIL'}")

    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        print("VALIDATION FAILED")
        for name in failed:
            print(f"  - {name}")
        return 1

    print("VALIDATION PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
