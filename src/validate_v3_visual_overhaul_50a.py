from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "godot_client/scripts/main.gd"
UI = ROOT / "godot_client/scripts/ui_components_v3.gd"
BRANDING = ROOT / "godot_client/scripts/team_branding_v3.gd"
EXP49_HERO = ROOT / "godot_client/scripts/franchise_hero_v3.gd"
HOME_ART = ROOT / "godot_client/scripts/franchise_home_art_v50a.gd"
HOME_BRIEF = ROOT / "godot_client/scripts/franchise_story_hq_v50a.gd"
CORE_STAGE = ROOT / "godot_client/scripts/franchise_core_stage_v50a.gd"
HERO_PLAYER = ROOT / "godot_client/scripts/hero_player_portrait_v50a.gd"

checks: list[tuple[str, bool]] = []


def check(name: str, value: bool) -> None:
    checks.append((name, bool(value)))


def text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.is_file() else ""


main = text(MAIN)
ui = text(UI)
branding = text(BRANDING)
hero = text(EXP49_HERO)
home_art = text(HOME_ART)
home_brief = text(HOME_BRIEF)
core_stage = text(CORE_STAGE)
hero_player = text(HERO_PLAYER)

check("main_exists", MAIN.is_file())
check("50a_marker", "# V3_50A_VISUAL_PARITY" in main)
check("50a2_marker", "# V3_50A2_POLISH" in main)
check("50a3_marker", "# V3_50A3_STREAMLIT_EVOLUTION" in main)
check("50a4_marker", "# V3_50A4_BROADCAST_HERO" in main)
check("exp49_rebuild_preload_preserved", 'const RebuildHQV3 = preload("res://scripts/rebuild_hq_v3.gd")' in main)
check("exp49_rebuild_page_preserved", "rebuild_page = RebuildHQV3.new()" in main)
check("exp49_rebuild_navigation_preserved", 'elif page_name == "REBUILD HQ":' in main)
check("sidebar_more_subordinate", "sidebar_panel.custom_minimum_size = Vector2(184, 0)" in main)
check("nav_height_preserved", "button.custom_minimum_size = Vector2(0, 32)" in ui)
check("active_nav_density_preserved", "box.content_margin_top = 6.0" in branding)
check("home_margin_tightened", "_set_margins(outer, 22, 14, 22, 24)" in main)
check("team_first_hero", "func _build_home_hero() -> Control:" in main)
check("streamlit_context_nav", "func _build_home_nav_strip() -> Control:" in main and '_home_quick_button("HOME", "HOME", true)' in main)
check("context_nav_rebrands", "var home_context_buttons: Array = []" in main and "_style_home_quick_button" in main)
check("smooth_broadcast_gradient", 'v3-visual-overhaul-50a4-home-art' in home_art and "var bands := 256" in home_art and "fade_bands := 24" not in home_art)
check("court_grid_removed_from_home_art", "Broadcast-style half court" not in home_art)
check("hero_logo_floats", 'team_badge_panel.add_theme_stylebox_override("panel", StyleBoxEmpty.new())' in main)
check("hero_name_scale", 'team_name_label.add_theme_font_size_override("font_size", 46)' in main)
check("next_up_broadcast_rail", "next_panel.custom_minimum_size = Vector2(0, 62)" in main and "matchup_phase.visible = false" in main)
check("legacy_matchup_banner_retained_hidden", "matchup_banner = MatchupBannerV3.new()" in main and "matchup_banner.visible = false" in main)
check("core_stage_present", CORE_STAGE.is_file() and 'v3-visual-overhaul-50a4-franchise-core-stage' in core_stage)
check("transparent_hero_portrait_present", HERO_PLAYER.is_file() and 'v3-visual-overhaul-50a4-hero-player' in hero_player)
check("floating_player_cutouts", "home_featured_players = FranchiseCoreStageV50A.new()" in main and "PlayerPortraitV3.new()" not in main[main.find("func _build_home_hero"):main.find("func _build_team_card")])
check("featured_star_centered", "portrait.z_index = 3 if index == 1 else 1" in core_stage and "w * 0.292" in core_stage)
check("featured_portraits_overlap", "w * 0.005" in core_stage and "w * 0.650" in core_stage and "center_w := w * 0.405" in core_stage)
check("hero_portrait_has_no_card_panel", "extends Control" in hero_player and "extends PanelContainer" not in hero_player)
check("home_roster_reader", "var home_roster_request: HTTPRequest" in main and "func _request_home_featured_players() -> void:" in main)
check("home_roster_callback", "home_roster_request.request_completed.connect(_on_home_roster_completed)" in main)
check("metric_ribbon_flattened", "panel.custom_minimum_size = Vector2(0, 62)" in main)
check("identity_eyebrow_uses_team_context", 'team_card_eyebrow_label.text = "%s  •  %s"' in main)
check("next_game_detail_single_line", 'next_game_detail.text = "%s  •  %s  •  %s  •  Game %s"' in main)
check("engine_status_hidden_from_home", "engine_strip.visible = false" in main)
check("command_deck_streamlit_style", 'v3-visual-overhaul-50a3-command-deck' in home_brief and '"COMMAND DECK"' in home_brief)
check("command_deck_density", "panel.custom_minimum_size = Vector2(0, 74)" in home_brief and "next_panel.custom_minimum_size = Vector2(0, 66)" in home_brief)
check("active_brand_broadcast_preserved", "franchise_hero_art.apply_team_brand" in main)
check("official_team_logo_preserved", "team_logo.configure(team_key)" in main)
check("summary_endpoint_preserved", 'const SUMMARY_URL := "http://127.0.0.1:8765/v3/franchise-summary"' in main)
check("roster_endpoint_preserved", 'const ROSTER_URL := "http://127.0.0.1:8765/v3/roster"' in main)
check("bridge_endpoint_preserved", 'const BRIDGE_URL := "http://127.0.0.1:8765/health"' in main)
check(
    "exp49_player_portrait_api_fixed",
    "portrait.configure(player)" in hero
    and 'portrait.configure(str(player.get("player_id", "")), str(player.get("name", "")))' not in hero,
)

sidebar_start = main.find("func _build_sidebar() -> Control:")
sidebar_end = main.find("func _build_main_area() -> Control:")
sidebar = main[sidebar_start:sidebar_end] if sidebar_start >= 0 and sidebar_end > sidebar_start else ""
check("guided_sidebar_hides_pulse", '_nav_button("PULSE")' not in sidebar)
check("guided_sidebar_hides_theater", '_nav_button("THEATER")' not in sidebar)
check("guided_sidebar_hides_stories", '_nav_button("STORIES")' not in sidebar)
check("guided_sidebar_hides_front_office", '_nav_button("FRONT OFFICE")' not in sidebar)

# Runtime parse gate on the user's Windows system.
godot = Path(os.environ.get("USERPROFILE", "")) / "Downloads" / "Godot_v4.0-stable_win64.exe"
console = godot.with_name(godot.stem + "_console.exe")
if console.is_file():
    godot = console

if godot.is_file():
    probe = ROOT / "godot_client" / "_validate_visual50a_runtime.gd"
    probe.write_text(
        '''extends SceneTree\n\nfunc _initialize() -> void:\n\tvar main_script = load("res://scripts/main.gd")\n\tvar hero_script = load("res://scripts/franchise_hero_v3.gd")\n\tvar art_script = load("res://scripts/franchise_home_art_v50a.gd")\n\tvar brief_script = load("res://scripts/franchise_story_hq_v50a.gd")\n\tvar core_stage_script = load("res://scripts/franchise_core_stage_v50a.gd")\n\tvar hero_player_script = load("res://scripts/hero_player_portrait_v50a.gd")\n\tif main_script == null or hero_script == null or art_script == null or brief_script == null or core_stage_script == null or hero_player_script == null:\n\t\tquit(2)\n\t\treturn\n\tvar hero = hero_script.new()\n\tif hero == null:\n\t\tquit(3)\n\t\treturn\n\tprint("VISUAL50A4_RUNTIME_PASS")\n\tquit()\n''',
        encoding="utf-8",
        newline="\n",
    )
    try:
        run = subprocess.run(
            [str(godot), "--headless", "--path", str(ROOT / "godot_client"), "--script", str(probe)],
            cwd=str(ROOT),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=60,
            check=False,
        )
        output = run.stdout or ""
        check(
            "godot_runtime_parse",
            run.returncode == 0
            and "VISUAL50A4_RUNTIME_PASS" in output
            and "SCRIPT ERROR" not in output
            and "Parse Error" not in output,
        )
        if not checks[-1][1]:
            print(output)
    finally:
        probe.unlink(missing_ok=True)
else:
    print("[SKIP] godot_runtime_parse — Godot executable not found at the normal Downloads path.")

failed = [name for name, ok in checks if not ok]
for name, ok in checks:
    print(f"[{'PASS' if ok else 'FAIL'}] {name}")

print()
print(f"Visual Overhaul 50A.4 gate: {len(checks) - len(failed)}/{len(checks)} passed")
if failed:
    print("Failures:")
    for name in failed:
        print(f"  - {name}")
    raise SystemExit(1)

print("50A.4 broadcast-hero gate passed. Expansion 49 navigation, endpoints and protected gameplay boundaries remain intact.")
