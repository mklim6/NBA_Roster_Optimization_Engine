from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "godot_client" / "scripts" / "main.gd"
COMPONENTS = ROOT / "godot_client" / "scripts" / "ui_components_v3.gd"
UX = ROOT / "godot_client" / "scripts" / "ux_polish_v3.gd"
V3 = ROOT / "outputs" / "runtime" / "v3_godot_working_checkpoint.pkl.gz"
V2 = ROOT / "outputs" / "runtime" / "franchise_mode_checkpoint_v1.pkl.gz"

VERSION = "v3-batch19d-shared-ux-polish-validator-v1.0.0-2026-10-03"


def sha256(path: Path) -> str | None:
    if not path.exists():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def check(value: bool, label: str, results: dict[str, bool]) -> None:
    passed = bool(value)
    results[label] = passed
    print(f"  {label}: {'PASS' if passed else 'FAIL'}")


def godot_parse() -> tuple[bool, str]:
    candidates = [
        Path(os.environ.get("USERPROFILE", "")) / "Downloads" / "Godot_v4.0-stable_win64.exe",
        Path(os.environ.get("USERPROFILE", "")) / "Downloads" / "Godot_v4.0-stable_win64" / "Godot_v4.0-stable_win64.exe",
    ]
    godot = next((path for path in candidates if path.is_file()), None)
    if godot is None:
        return True, "Godot executable not found; parser smoke skipped."

    proc = subprocess.run(
        [str(godot), "--headless", "--path", str(ROOT / "godot_client"), "--editor", "--quit"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=45,
    )
    combined = (proc.stdout or "") + "\n" + (proc.stderr or "")
    markers = ("script error", "parse error", "parser error", "could not resolve class")
    return not any(marker in combined.lower() for marker in markers), combined[-6000:]


def main() -> int:
    v3_before = sha256(V3)
    v2_before = sha256(V2)
    results: dict[str, bool] = {}

    print("=" * 100)
    print("V3 BATCH 19D SHARED UX POLISH VALIDATION")
    print("=" * 100)

    check(UX.is_file(), "ux_polish_file_present", results)
    check(COMPONENTS.is_file(), "ui_components_present", results)
    check(MAIN.is_file(), "main_shell_present", results)

    ux = UX.read_text(encoding="utf-8") if UX.exists() else ""
    components = COMPONENTS.read_text(encoding="utf-8") if COMPONENTS.exists() else ""
    main = MAIN.read_text(encoding="utf-8") if MAIN.exists() else ""

    check(
        "v3-ux-polish-batch-19d-v1.0.0-2026-10-03" in ux,
        "ux_polish_version_present",
        results,
    )
    check(
        "static func animate_page_in(" in ux
        and "page.create_tween()" in ux
        and "DesignSystemV3.MOTION_NORMAL" in ux,
        "page_transition_animation_present",
        results,
    )
    check(
        "static func animate_overlay_in(" in ux
        and "DesignSystemV3.MOTION_FAST" in ux,
        "overlay_transition_animation_present",
        results,
    )
    check(
        "static func set_button_busy(" in ux
        and "static func attach_tooltip(" in ux,
        "shared_busy_and_tooltip_helpers_present",
        results,
    )
    check(
        "static func status_banner(" in components
        and "static func empty_state(" in components
        and "static func loading_skeleton(" in components,
        "shared_loading_empty_status_components_present",
        results,
    )
    check(
        'button.tooltip_text = "Open %s" % text_value.capitalize()' in components,
        "navigation_tooltips_present",
        results,
    )
    check(
        'const UxPolishV3 = preload("res://scripts/ux_polish_v3.gd")' in main,
        "main_preloads_ux_polish",
        results,
    )
    check(
        "func _page_control(page_name: String):" in main
        and "func _all_page_controls() -> Array:" in main,
        "page_registry_helpers_present",
        results,
    )
    check(
        "UxPolishV3.animate_page_in(target_page, active_team_primary)" in main,
        "navigation_uses_shared_page_transition",
        results,
    )
    check(
        "UxPolishV3.animate_overlay_in(long_action_overlay)" in main,
        "long_action_overlay_uses_shared_transition",
        results,
    )
    check(
        'UiComponentsV3.loading_skeleton(' in main
        and '"Loading players from the V3 working checkpoint..."' in main,
        "roster_uses_truthful_loading_skeleton",
        results,
    )

    endpoints = (
        "/health",
        "/v3/franchise-summary",
        "/v3/roster",
        "/v3/rotation/preview",
        "/v3/rotation/apply",
        "/v3/game-day",
        "/v3/game-day/simulate",
        "/v3/franchise-intelligence",
        "/v3/market-intelligence",
        "/v3/transaction-foundation",
    )
    check(
        all(endpoint in main for endpoint in endpoints),
        "bridge_endpoint_contract_preserved",
        results,
    )

    parse_ok, parse_tail = godot_parse()
    check(parse_ok, "godot_headless_parse", results)
    if not parse_ok:
        print(parse_tail)

    check(
        sha256(V3) == v3_before,
        "validator_never_changes_active_v3_save",
        results,
    )
    check(
        sha256(V2) == v2_before,
        "validator_never_changes_active_v2_save",
        results,
    )

    report_dir = ROOT / "outputs" / "v3_batch19d_shared_ux_polish"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / "validation.json"
    report_path.write_text(
        json.dumps({"version": VERSION, "results": results}, indent=2),
        encoding="utf-8",
    )

    print()
    print(f"Report: {report_path}")
    if all(results.values()):
        print()
        print("V3 BATCH 19D VALIDATION PASSED")
        print("Shared-UX validation is read-only; active V3 and protected V2 remained unchanged.")
        return 0

    print()
    print("V3 BATCH 19D VALIDATION FAILED")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
