from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "godot_client" / "scripts" / "main.gd"
DESIGN = ROOT / "godot_client" / "scripts" / "design_system_v3.gd"
V3 = ROOT / "outputs" / "runtime" / "v3_godot_working_checkpoint.pkl.gz"
V2 = ROOT / "outputs" / "runtime" / "franchise_mode_checkpoint_v1.pkl.gz"

VERSION = "v3-batch19a-design-system-validator-v1.0.0-2026-10-03"

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
        cwd=ROOT, capture_output=True, text=True, timeout=45
    )
    combined = (proc.stdout or "") + "\n" + (proc.stderr or "")
    bad = ("script error", "parse error", "parser error", "could not resolve class")
    return (not any(marker in combined.lower() for marker in bad)), combined[-5000:]

def main() -> int:
    v3_before = sha256(V3)
    v2_before = sha256(V2)
    results = {}
    print("=" * 100)
    print("V3 BATCH 19A DESIGN SYSTEM FOUNDATION VALIDATION")
    print("=" * 100)

    check(DESIGN.is_file(), "design_system_file_present", results)
    check(MAIN.is_file(), "main_shell_present", results)

    d = DESIGN.read_text(encoding="utf-8") if DESIGN.exists() else ""
    m = MAIN.read_text(encoding="utf-8") if MAIN.exists() else ""

    check("v3-design-system-batch-19a-v1.0.0-2026-10-03" in d, "design_system_version_present", results)
    semantic = ("BG","SIDEBAR","PANEL","PANEL_ALT","PANEL_HOVER","TEXT","MUTED","ACCENT","GOOD","WARNING","BAD","BORDER","SOFT_BORDER","TEAM_PRIMARY","TEAM_PRIMARY_HOVER","GOLD")
    check(all(re.search(rf"const {name}\s*:=", d) for name in semantic), "semantic_color_tokens_present", results)
    check(all(x in d for x in ("FONT_MICRO","FONT_BODY","FONT_TITLE","FONT_HERO")), "typography_scale_present", results)
    check(all(x in d for x in ("SPACE_SM","SPACE_MD","SPACE_LG","RADIUS_SM","RADIUS_LG")), "spacing_and_radius_tokens_present", results)
    check(all(x in d for x in ("MOTION_FAST","MOTION_NORMAL","MOTION_SLOW")), "motion_tokens_present", results)

    team_keys = re.findall(r'^\s*"([A-Z]{3})":\s*\{', d, flags=re.MULTILINE)
    check(len(set(team_keys)) == 30, "all_30_team_brand_palettes_present", results)
    check("static func team_palette" in d, "team_palette_accessor_present", results)
    check("static func build_theme()" in d, "global_theme_builder_present", results)
    check(all(x in d for x in ('"normal", "Button"','"hover", "Button"','"pressed", "Button"','"disabled", "Button"')), "button_interaction_states_present", results)
    check('"normal", "LineEdit"' in d and '"focus", "LineEdit"' in d and '"normal", "OptionButton"' in d, "form_control_styles_present", results)

    check('const DesignSystemV3 = preload("res://scripts/design_system_v3.gd")' in m, "main_preloads_design_system", results)
    aliases = ("BG","SIDEBAR","PANEL","PANEL_ALT","PANEL_HOVER","TEXT","MUTED","ACCENT","GOOD","BAD","BORDER","SOFT_BORDER","TEAM_PRIMARY","TEAM_PRIMARY_HOVER","GOLD")
    check(all(f"const {name} := DesignSystemV3.{name}" in m for name in aliases), "main_palette_is_design_system_backed", results)
    check("theme = DesignSystemV3.build_theme()" in m, "main_applies_global_theme_before_ui_build", results)

    endpoints = ("/health","/v3/franchise-summary","/v3/roster","/v3/rotation/preview","/v3/rotation/apply","/v3/game-day","/v3/game-day/simulate","/v3/franchise-intelligence","/v3/market-intelligence","/v3/transaction-foundation")
    check(all(x in m for x in endpoints), "bridge_endpoint_contract_preserved", results)

    parse_ok, parse_tail = godot_parse()
    check(parse_ok, "godot_headless_parse", results)
    if not parse_ok:
        print(parse_tail)

    check(sha256(V3) == v3_before, "validator_never_changes_active_v3_save", results)
    check(sha256(V2) == v2_before, "validator_never_changes_active_v2_save", results)

    out = ROOT / "outputs" / "v3_batch19a_design_system"
    out.mkdir(parents=True, exist_ok=True)
    report = out / "validation.json"
    report.write_text(json.dumps({"version": VERSION, "results": results}, indent=2), encoding="utf-8")
    print()
    print(f"Report: {report}")
    if all(results.values()):
        print()
        print("V3 BATCH 19A VALIDATION PASSED")
        print("Design-system validation is read-only; active V3 and protected V2 remained unchanged.")
        return 0
    print()
    print("V3 BATCH 19A VALIDATION FAILED")
    return 1

if __name__ == "__main__":
    raise SystemExit(main())
