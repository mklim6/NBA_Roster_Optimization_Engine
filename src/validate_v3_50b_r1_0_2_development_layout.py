from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEV = ROOT / "godot_client/scripts/development_command_center_v3.gd"

checks = []

def check(name, value):
    checks.append((name, bool(value)))

text = DEV.read_text(encoding="utf-8") if DEV.is_file() else ""

check("development_exists", DEV.is_file())
check("r1_design_preserved", "V3_50B_R1_DEVELOPMENT_VISUAL_REDESIGN" in text)
check("hero_height_repaired", "Vector2(0, 272)" in text)
check("nowrap_helper", "func _nowrap_label(" in text)
check("watch_title_nowrap", '_nowrap_label("CORE DEVELOPMENT WATCH"' in text)
check("rules_nowrap", "_nowrap_label(_short_rules()" in text)
check("featured_grid_three_columns", 'featured := GridContainer.new()' in text and "featured.columns = 3" in text)
check("featured_card_min_width", "Vector2(300, 124)" in text)
check("priority_labels_nowrap", '"PRIORITY %s"' in text and "priority_label := _nowrap_label" in text)
check("player_name_nowrap", '_nowrap_label("Select a player"' in text)
check("typed_color_hotfix_preserved", "var tone: Color =" in text and "var normal_fill: Color =" in text)
check("development_endpoint_preserved", 'const URL = "http://127.0.0.1:8765/v3/development-goals"' in text)
check("preview_execute_preserved", '_submit("preview")' in text and '_submit("execute")' in text)
check("three_goal_controls_preserved", '"GoalPlayer%s"' in text and '"GoalMetric%s"' in text and '"GoalTarget%s"' in text)
check("focused_player_preserved", "func focus_player(player_id: String)" in text and "func _draft_focused_player()" in text)

godot = Path(os.environ.get("USERPROFILE", "")) / "Downloads" / "Godot_v4.0-stable_win64.exe"
console = godot.with_name(godot.stem + "_console.exe")
if console.is_file():
    godot = console

if godot.is_file():
    probe = ROOT / "godot_client" / "_validate_50br102c_construct.gd"
    probe.write_text(
        """extends SceneTree

func _initialize() -> void:
\tvar script = load("res://scripts/development_command_center_v3.gd")
\tif script == null:
\t\tpush_error("Development script failed to load.")
\t\tquit(2)
\t\treturn

\tvar page = script.new()
\tif page == null:
\t\tpush_error("Development page failed to instantiate.")
\t\tquit(3)
\t\treturn

\tpage.size = Vector2(1280, 900)
\troot.add_child(page)

\tvar status = page.find_child("DevelopmentStatus", true, false)
\tif status == null:
\t\tpush_error("Development _ready() did not construct the expected status node.")
\t\tquit(4)
\t\treturn

\tpage.apply_team_brand("BOS", Color("007a33"), Color("ba9653"))

\tprint("DEVELOPMENT_R102C_CONSTRUCT_PASS")
\tquit()
""",
        encoding="utf-8",
    )
    try:
        result = subprocess.run(
            [str(godot), "--headless", "--path", str(ROOT / "godot_client"), "--script", str(probe)],
            cwd=str(ROOT),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=60,
            check=False,
        )
        output = result.stdout or ""
        check(
            "godot_compile_and_construct",
            result.returncode == 0
            and "DEVELOPMENT_R102C_CONSTRUCT_PASS" in output
            and "SCRIPT ERROR" not in output
            and "Parse Error" not in output,
        )
        if not checks[-1][1]:
            print("--- GODOT CONSTRUCT OUTPUT ---")
            print(output)
            print("--- END GODOT CONSTRUCT OUTPUT ---")
    finally:
        probe.unlink(missing_ok=True)
else:
    print("[SKIP] godot_compile_and_construct — Godot executable not found at expected Downloads path.")

failed = [name for name, ok in checks if not ok]
for name, ok in checks:
    print(f"[{'PASS' if ok else 'FAIL'}] {name}")

print()
print(f"50B-R1.0.2C Development freeze gate: {len(checks)-len(failed)}/{len(checks)} passed")
if failed:
    print("Failures:")
    for name in failed:
        print(f"  - {name}")
    raise SystemExit(1)

print("50B-R1.0.2C Development freeze gate passed.")
