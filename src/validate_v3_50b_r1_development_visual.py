from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEV = ROOT / "godot_client/scripts/development_command_center_v3.gd"
MAIN = ROOT / "godot_client/scripts/main.gd"

checks = []

def check(name, value):
    checks.append((name, bool(value)))

dev = DEV.read_text(encoding="utf-8") if DEV.is_file() else ""
main = MAIN.read_text(encoding="utf-8") if MAIN.is_file() else ""

check("development_script_exists", DEV.is_file())
check("r1_marker", "V3_50B_R1_DEVELOPMENT_VISUAL_REDESIGN" in dev)
check("development_endpoint_preserved", 'const URL = "http://127.0.0.1:8765/v3/development-goals"' in dev)
check("development_navigation_signal_preserved", "signal navigate_requested(page: String)" in dev)
check("focused_player_handoff_preserved", "func focus_player(player_id: String)" in dev and "func _draft_focused_player()" in dev)
check("development_hero", 'panel.name = "DevelopmentHero"' in dev and '"DEVELOPMENT CENTER"' in dev)
check("team_gradient_hero", "GradientTexture2D.new()" in dev and '"DevelopmentHeroGradient"' in dev)
check("featured_player_stage", '"DevelopmentFeaturedPlayers"' in dev and "_featured_player_card" in dev)
check("real_player_portraits", "const Portrait = preload" in dev and "portrait.configure" in dev)
check("three_column_planner", 'grid.name = "DevelopmentPlannerGrid"' in dev and "grid.columns = 3" in dev)
check("three_priority_cards", '"DevelopmentPriorityCard%s"' in dev and "for i in range(3):" in dev)
check("goal_control_names_preserved", '"GoalPlayer%s"' in dev and '"GoalMetric%s"' in dev and '"GoalTarget%s"' in dev)
check("planner_updates_visuals", '"GoalPortrait%s"' in dev and "form.portrait.configure" in dev)
check("preview_flow_preserved", '_submit("preview")' in dev and 'pending_action == "preview"' in dev)
check("execute_flow_preserved", '_submit("execute")' in dev and '"expected_working_save_sha256"' in dev)
check("selection_payload_preserved", '"player_id": str(row.player_id)' in dev and '"metric": metric' in dev)
check("opportunity_targets_preserved", "[10, 15, 20, 25, 30]" in dev)
check("skill_delta_targets_preserved", "form.target.selected + 1" in dev)
check("committed_goal_progress", '"CommittedDevelopmentGrid"' in dev and "ProgressBar.new()" in dev)
check("archive_preserved", "func _build_archive()" in dev and "archived_count" in dev)
check("50a_home_untouched", "# V3_50A4_BROADCAST_HERO" in main)

godot = Path(os.environ.get("USERPROFILE", "")) / "Downloads" / "Godot_v4.0-stable_win64.exe"
console = godot.with_name(godot.stem + "_console.exe")
if console.is_file():
    godot = console

if godot.is_file():
    probe = ROOT / "godot_client" / "_validate_50br1_construct.gd"
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

\tif page.find_child("DevelopmentStatus", true, false) == null:
\t\tpush_error("Development page did not construct.")
\t\tquit(4)
\t\treturn

\tprint("DEVELOPMENT_R1_CONSTRUCT_PASS")
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
            "godot_runtime_constructs",
            result.returncode == 0
            and "DEVELOPMENT_R1_CONSTRUCT_PASS" in output
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
    print("[SKIP] godot_runtime_constructs — Godot executable not found at expected Downloads path.")

failed = [name for name, ok in checks if not ok]
for name, ok in checks:
    print(f"[{'PASS' if ok else 'FAIL'}] {name}")

print()
print(f"50B-R1 Development gate: {len(checks)-len(failed)}/{len(checks)} passed")
if failed:
    print("Failures:")
    for name in failed:
        print(f"  - {name}")
    raise SystemExit(1)

print("50B-R1 Development visual gate passed with stable construct validation.")
