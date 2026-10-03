from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

REPORT_DIR = ROOT / "outputs" / "v3_batch18c_long_actions"
REPORT_PATH = REPORT_DIR / "validation.json"
VALIDATOR_VERSION = "v3-batch18c-long-actions-validator-v1.0.1-2026-10-03"


def _sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _godot_parse() -> tuple[bool, str]:
    candidates = [
        shutil.which("godot4"),
        shutil.which("godot"),
        str(Path.home() / "Downloads" / "Godot_v4.0-stable_win64.exe"),
    ]
    godot = next((value for value in candidates if value and Path(value).is_file()), None)
    if not godot:
        return False, "Godot executable not found."
    try:
        result = subprocess.run(
            [godot, "--headless", "--path", str(ROOT / "godot_client"), "--editor", "--quit"],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"
    output = (result.stdout + "\n" + result.stderr).strip()
    lowered = output.lower()
    fatal = any(marker in lowered for marker in ("script error", "parse error", "error at:"))
    return (not fatal), output[-6000:]


def main() -> int:
    from desktop_bridge import server

    active_v3 = Path(server.V3_WORKING_CHECKPOINT_PATH)
    active_v2 = Path(server.DEFAULT_CHECKPOINT_PATH)
    v3_before = _sha256(active_v3)
    v2_before = _sha256(active_v2)

    manager = ROOT / "godot_client" / "scripts" / "long_action_manager_v3.gd"
    main_gd = ROOT / "godot_client" / "scripts" / "main.gd"
    game_day = ROOT / "godot_client" / "scripts" / "game_day_center_v3.gd"
    trades = ROOT / "godot_client" / "scripts" / "trade_center_v3.gd"
    free_agency = ROOT / "godot_client" / "scripts" / "free_agency_center_v3.gd"
    scouting = ROOT / "godot_client" / "scripts" / "scouting_draft_center_v3.gd"
    season = ROOT / "godot_client" / "scripts" / "season_lifecycle_center_v3.gd"

    texts = {path.name: path.read_text(encoding="utf-8") for path in [manager, main_gd, game_day, trades, free_agency, scouting, season]}
    manager_text = texts[manager.name]
    main_text = texts[main_gd.name]

    checks: dict[str, bool] = {
        "long_action_manager_version_present": "v3-long-action-manager-batch-18c-v1.0.0-2026-10-03" in manager_text,
        "manager_blocks_second_action": "if _busy:" in manager_text and "_rejected_starts += 1" in manager_text,
        "manager_tracks_elapsed_time": "Time.get_ticks_msec()" in manager_text and "elapsed_seconds" in manager_text,
        "manager_emits_start_and_finish": "signal action_started" in manager_text and "signal action_finished" in manager_text,
        "main_preloads_long_action_manager": 'preload("res://scripts/long_action_manager_v3.gd")' in main_text,
        "main_instantiates_long_action_manager": "long_action_manager = LongActionManagerV3.new()" in main_text,
        "main_builds_blocking_progress_overlay": (
            "_build_long_action_overlay" in main_text
            and "MOUSE_FILTER_STOP" in main_text
            and "long_action_elapsed_label" in main_text
            and "long_action_spinner_label" in main_text
        ),
        "main_wires_long_action_manager_to_pages": (
            "set_long_action_manager" in main_text
            and all(name in main_text for name in ["game_day_page", "trades_page", "free_agency_page", "scouting_page", "season_page"])
        ),
        "game_day_long_action_wired": (
            "game_day_simulation" in texts[game_day.name]
            and "_begin_long_action" in texts[game_day.name]
            and "_finish_long_action" in texts[game_day.name]
        ),
        "trade_long_action_wired": (
            "trade_execution" in texts[trades.name]
            and "_begin_long_action" in texts[trades.name]
            and "_finish_long_action" in texts[trades.name]
        ),
        "free_agency_long_action_wired": (
            "free_agency_signing" in texts[free_agency.name]
            and "_begin_long_action" in texts[free_agency.name]
            and "_finish_long_action" in texts[free_agency.name]
        ),
        "season_long_action_wired": (
            "season_lifecycle_commit" in texts[season.name]
            and "_begin_long_action" in texts[season.name]
            and "_finish_long_action" in texts[season.name]
        ),
        "scouting_draft_long_actions_wired": all(
            token in texts[scouting.name]
            for token in (
                "scouting_week_advance",
                "draft_selection",
                "cpu_draft_advance",
                "post_draft_roster_cut",
                "_begin_long_action",
                "_finish_long_action",
            )
        ),
        "batch18b_validator_preserved": (ROOT / "src" / "validate_v3_batch18b_request_coordination.py").is_file(),
        "batch18a_validator_preserved": (ROOT / "src" / "validate_v3_batch18a_runtime_performance.py").is_file(),
        "batch17c_validator_preserved": (ROOT / "src" / "validate_v3_batch17c_settings_tutorial.py").is_file(),
        "batch17b_validator_preserved": (ROOT / "src" / "validate_v3_batch17b_new_franchise.py").is_file(),
        "batch17a_validator_preserved": (ROOT / "src" / "validate_v3_batch17a_save_manager.py").is_file(),
    }

    godot_ok, godot_output = _godot_parse()
    checks["godot_headless_parse"] = godot_ok

    v3_after = _sha256(active_v3)
    v2_after = _sha256(active_v2)
    checks["validator_never_changes_active_v3_save"] = v3_before == v3_after
    checks["validator_never_changes_active_v2_save"] = v2_before == v2_after

    passed = all(checks.values())
    report = {
        "validator_version": VALIDATOR_VERSION,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "checks": checks,
        "godot_output_tail": godot_output,
        "safety": {
            "active_v3_before": v3_before,
            "active_v3_after": v3_after,
            "active_v2_before": v2_before,
            "active_v2_after": v2_after,
        },
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print("=" * 100)
    print("V3 BATCH 18C LONG ACTIONS + RESPONSIVE PROGRESS VALIDATION")
    print("=" * 100)
    for name, value in checks.items():
        print(f"  {name}: {'PASS' if value else 'FAIL'}")
    print()
    print(f"Godot parser: {'PASS' if godot_ok else 'FAIL'}")
    print(f"Report: {REPORT_PATH}")
    print()
    if passed:
        print("V3 BATCH 18C VALIDATION PASSED")
        print("Long-action validation is read-only; active V3 and protected V2 remained unchanged.")
        return 0
    print("V3 BATCH 18C VALIDATION FAILED")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
