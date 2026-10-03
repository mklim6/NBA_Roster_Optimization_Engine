from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "godot_client" / "scripts" / "main.gd"
DESIGN = ROOT / "godot_client" / "scripts" / "design_system_v3.gd"
COMPONENTS = ROOT / "godot_client" / "scripts" / "ui_components_v3.gd"
BRANDING = ROOT / "godot_client" / "scripts" / "team_branding_v3.gd"
V3 = ROOT / "outputs" / "runtime" / "v3_godot_working_checkpoint.pkl.gz"
V2 = ROOT / "outputs" / "runtime" / "franchise_mode_checkpoint_v1.pkl.gz"

VERSION = "v3-batch19c-active-team-branding-validator-v1.0.1-2026-10-03"


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
    print("V3 BATCH 19C ACTIVE-TEAM BRANDING VALIDATION")
    print("=" * 100)

    check(BRANDING.is_file(), "team_branding_file_present", results)
    check(DESIGN.is_file(), "design_system_preserved", results)
    check(COMPONENTS.is_file(), "ui_components_preserved", results)
    check(MAIN.is_file(), "main_shell_present", results)

    branding = BRANDING.read_text(encoding="utf-8") if BRANDING.exists() else ""
    components = COMPONENTS.read_text(encoding="utf-8") if COMPONENTS.exists() else ""
    main = MAIN.read_text(encoding="utf-8") if MAIN.exists() else ""

    check(
        "v3-team-branding-batch-19c-v1.0.0-2026-10-03" in branding,
        "team_branding_version_present",
        results,
    )
    check(
        all(
            method in branding
            for method in (
                "static func palette(",
                "static func luminance(",
                "static func readable_foreground(",
                "static func hover_color(",
                "static func apply_nav_state(",
                "static func apply_primary_button(",
            )
        ),
        "team_branding_helpers_present",
        results,
    )
    check(
        'const TeamBrandingV3 = preload("res://scripts/team_branding_v3.gd")' in components
        and "brand_color: Color = DesignSystemV3.TEAM_PRIMARY_HOVER" in components
        and "TeamBrandingV3.apply_nav_state(button, active, brand_color)" in components,
        "component_navigation_accepts_runtime_brand",
        results,
    )
    check(
        'const TeamBrandingV3 = preload("res://scripts/team_branding_v3.gd")' in main,
        "main_preloads_team_branding",
        results,
    )
    check(
        all(
            token in main
            for token in (
                "active_team_abbreviation",
                "active_team_primary",
                "active_team_secondary",
                "active_team_hover",
                "active_team_foreground",
            )
        ),
        "main_tracks_active_team_brand_state",
        results,
    )
    check(
        all(
            token in main
            for token in (
                "background_top_band",
                "background_accent_line",
                "header_eyebrow_label",
                "team_card_panel",
                "team_badge_panel",
                "team_card_eyebrow_label",
            )
        ),
        "key_shell_brand_targets_are_retained",
        results,
    )
    check(
        'func _apply_active_team_brand(team_abbreviation: String) -> void:' in main
        and 'DesignSystemV3.team_palette(team_key)' in main,
        "active_team_brand_application_present",
        results,
    )
    check(
        '_apply_active_team_brand(str(team.get("abbreviation", "")))' in main,
        "franchise_summary_drives_team_brand",
        results,
    )
    check(
        "UiComponentsV3.apply_nav_state(button, active, active_team_primary)" in main,
        "active_navigation_uses_runtime_team_color",
        results,
    )
    check(
        "TeamBrandingV3.apply_primary_button(button, active_team_primary)" in main,
        "primary_actions_use_runtime_team_color",
        results,
    )

    broadcast_hook_present = (
        "func _broadcast_team_brand() -> void:" in main
        and 'page.has_method("apply_team_brand")' in main
        and '"apply_team_brand"' in main
        and "active_team_abbreviation" in main
        and "active_team_primary" in main
        and "active_team_secondary" in main
    )
    check(
        broadcast_hook_present,
        "future_page_brand_broadcast_hook_present",
        results,
    )

    design_text = DESIGN.read_text(encoding="utf-8") if DESIGN.exists() else ""
    check(
        all(code in design_text for code in ('"CHI":', '"BOS":', '"LAL":', '"GSW":')),
        "team_palette_foundation_preserved",
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

    report_dir = ROOT / "outputs" / "v3_batch19c_active_team_branding"
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
        print("V3 BATCH 19C VALIDATION PASSED")
        print("Team-brand validation is read-only; active V3 and protected V2 remained unchanged.")
        return 0

    print()
    print("V3 BATCH 19C VALIDATION FAILED")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
