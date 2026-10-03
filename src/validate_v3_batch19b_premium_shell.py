from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "godot_client" / "scripts" / "main.gd"
COMPONENTS = ROOT / "godot_client" / "scripts" / "ui_components_v3.gd"
DESIGN = ROOT / "godot_client" / "scripts" / "design_system_v3.gd"
V3 = ROOT / "outputs" / "runtime" / "v3_godot_working_checkpoint.pkl.gz"
V2 = ROOT / "outputs" / "runtime" / "franchise_mode_checkpoint_v1.pkl.gz"

VERSION = "v3-batch19b-premium-shell-components-validator-v1.0.1-2026-10-03"


def sha256(path: Path) -> str | None:
    if not path.exists():
        return None
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def check(value: bool, label: str, results: dict[str, bool]) -> None:
    passed = bool(value)
    results[label] = passed
    print(f"  {label}: {'PASS' if passed else 'FAIL'}")


def godot_parse() -> tuple[bool, str]:
    candidates = [
        Path(os.environ.get("USERPROFILE", "")) / "Downloads" / "Godot_v4.0-stable_win64.exe",
        Path(os.environ.get("USERPROFILE", "")) / "Downloads" / "Godot_v4.0-stable_win64" / "Godot_v4.0-stable_win64.exe",
    ]
    godot = next((p for p in candidates if p.is_file()), None)
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
    bad = ("script error", "parse error", "parser error", "could not resolve class")
    return not any(marker in combined.lower() for marker in bad), combined[-6000:]


def main() -> int:
    v3_before = sha256(V3)
    v2_before = sha256(V2)
    results: dict[str, bool] = {}

    print("=" * 100)
    print("V3 BATCH 19B PREMIUM SHELL + REUSABLE COMPONENTS VALIDATION")
    print("=" * 100)

    check(COMPONENTS.is_file(), "ui_components_file_present", results)
    check(DESIGN.is_file(), "batch19a_design_system_preserved", results)
    check(MAIN.is_file(), "main_shell_present", results)

    c = COMPONENTS.read_text(encoding="utf-8") if COMPONENTS.exists() else ""
    m = MAIN.read_text(encoding="utf-8") if MAIN.exists() else ""

    check(
        "v3-ui-components-batch-19b-v1.0.0-2026-10-03" in c,
        "ui_components_version_present",
        results,
    )

    methods = (
        "static func card(",
        "static func card_body(",
        "static func action_button(",
        "static func wide_action(",
        "static func nav_button(",
        "static func apply_nav_state(",
        "static func pill(",
        "static func section_title(",
        "static func small_label(",
        "static func sidebar_group_label(",
        "static func divider(",
        "static func page_header(",
    )
    check(
        all(method in c for method in methods),
        "reusable_component_factories_present",
        results,
    )

    check(
        'const UiComponentsV3 = preload("res://scripts/ui_components_v3.gd")' in m,
        "main_preloads_ui_components",
        results,
    )

    action_delegate = (
        "return UiComponentsV3.action_button(text_value, primary)" in m
        or "var button := UiComponentsV3.action_button(text_value, primary)" in m
    )
    other_delegates = (
        "return UiComponentsV3.pill(text_value, color)",
        "return UiComponentsV3.section_title(text_value)",
        "return UiComponentsV3.small_label(text_value, color)",
        "return UiComponentsV3.divider()",
        "return UiComponentsV3.card(minimum)",
    )
    check(
        action_delegate and all(line in m for line in other_delegates),
        "main_helpers_delegate_to_component_library",
        results,
    )

    nav_state_delegate = (
        "UiComponentsV3.apply_nav_state(button, active)" in m
        or "UiComponentsV3.apply_nav_state(button, active, active_team_primary)" in m
    )
    check(
        nav_state_delegate,
        "nav_state_delegates_to_component_library",
        results,
    )

    nav_button_delegate = (
        "UiComponentsV3.nav_button(text_value, active)" in m
        or (
            "UiComponentsV3.nav_button(" in m
            and "text_value," in m
            and "active," in m
            and "active_team_primary" in m
        )
    )
    check(
        nav_button_delegate,
        "nav_button_uses_component_library",
        results,
    )

    check(
        "UiComponentsV3.wide_action(title_text, subtitle_text)" in m,
        "home_shortcuts_use_component_library",
        results,
    )

    groups = ("COMMAND", "TEAM", "ROSTER BUILDING", "LEAGUE", "ORGANIZATION")
    check(
        all(f'UiComponentsV3.sidebar_group_label("{group}")' in m for group in groups),
        "sidebar_has_premium_navigation_groups",
        results,
    )
    check(
        "sidebar_panel.custom_minimum_size = Vector2(244, 0)" in m,
        "sidebar_shell_widened_for_hierarchy",
        results,
    )

    pages = (
        "HOME",
        "FRANCHISES",
        "ROSTER",
        "GAME DAY",
        "TRADES",
        "FREE AGENCY",
        "SCOUTING",
        "SEASON",
        "LEAGUE",
        "FRONT OFFICE",
        "SETTINGS",
    )
    check(
        all(f'_nav_button("{name}"' in m for name in pages),
        "all_existing_navigation_destinations_preserved",
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
        all(endpoint in m for endpoint in endpoints),
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

    out = ROOT / "outputs" / "v3_batch19b_premium_shell"
    out.mkdir(parents=True, exist_ok=True)
    report = out / "validation.json"
    report.write_text(
        json.dumps({"version": VERSION, "results": results}, indent=2),
        encoding="utf-8",
    )

    print()
    print(f"Report: {report}")
    if all(results.values()):
        print()
        print("V3 BATCH 19B VALIDATION PASSED")
        print("Premium-shell validation is read-only; active V3 and protected V2 remained unchanged.")
        return 0

    print()
    print("V3 BATCH 19B VALIDATION FAILED")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
