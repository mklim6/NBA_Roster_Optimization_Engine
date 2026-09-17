from __future__ import annotations

import py_compile
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "pages" / "5_Franchise_Mode.py"
MODULE = ROOT / "src" / "franchise_premium_roster_v1.py"

page = PAGE.read_text(encoding="utf-8")
module = MODULE.read_text(encoding="utf-8")

checks = {
    "premium_module_exists": MODULE.is_file(),
    "page_imports_premium_roster": "from franchise_premium_roster_v1 import (" in page,
    "page_injects_premium_styles": "inject_franchise_premium_roster_visuals_v1(" in page,
    "team_management_renders_depth_chart": "render_franchise_premium_roster_v1(" in page,
    "team_management_reuses_rotation_rows": "rotation_rows = _premium_rotation_rows_v1" in page,
    "visual_court_exists": "fpr-court-shell" in module and "fpr-slot-pg" in module and "fpr-slot-c" in module,
    "premium_player_cards_exist": "fpr-player-card" in module and "Premium player card gallery" in module,
    "contract_context_exists": "contract_label_v1" in module and "years_remaining" in module,
    "development_context_exists": "development_label_v1" in module and "potential_rating" in module,
    "recent_form_uses_saved_games": "recent_form_v1" in module and "completed_games" in module and "player_box_scores" in module,
    "health_and_fatigue_context_exists": "availability" in module and "fatigue" in module,
    "archetype_badges_exist": "archetype_label_v1" in module,
    "role_badges_exist": "role_label_v1" in module,
    "morale_not_fabricated": "does not store a morale variable" in module,
    "native_navigation_v22_preserved": "from franchise_game_navigation_native_v2_2 import (" in page,
    "legacy_workspace_preserved": "render_franchise_timeline_trophy_room_v1" in page,
    "runtime_bridge_preserved": "franchise_game_flow_runtime_bridge_v1" in page,
    "no_save_or_simulation_mutation_in_module": all(
        token not in module
        for token in (
            "save_franchise_checkpoint(",
            "set_franchise_state(",
            "apply_rotation_plan(",
            "simulate_scheduled_game(",
            "advance_franchise_scope(",
        )
    ),
}

compile_error = ""
try:
    py_compile.compile(str(PAGE), doraise=True)
    py_compile.compile(str(MODULE), doraise=True)
    checks["python_compile"] = True
except Exception as exc:
    checks["python_compile"] = False
    compile_error = f"{type(exc).__name__}: {exc}"

smoke = r'''
import sys
from types import SimpleNamespace as NS
sys.path.insert(0, SRC)
import franchise_premium_roster_v1 as m
contract = NS(status="under_contract", salary=12000000.0, years_remaining=3, option_type="", guaranteed=True)
players = {}
rows = []
positions = ["PG", "SG", "SF", "PF", "C", "SG", "PF"]
for i, pos in enumerate(positions):
    pid = f"P{i}"
    players[pid] = NS(
        player_id=pid,
        player_name=f"Player {i}",
        position=pos,
        overall_rating=90-i,
        contract=contract,
        age=25,
        potential_rating=92-i,
        development_direction="Rising" if i < 2 else "Stable",
        skill_ratings={
            "scoring_rating": 82-i,
            "shooting_rating": 80-i,
            "playmaking_rating": 79-i,
            "rebounding_rating": 72+i,
            "defense_rating": 77+i,
            "efficiency_rating": 81,
        },
    )
    rows.append({
        "player_id": pid, "player": f"Player {i}", "position": pos,
        "overall": 90-i, "starter": i < 5, "in_rotation": True,
        "minutes": 34-i if i < 5 else 20-i, "rotation_order": i+1,
        "availability": "healthy", "fatigue": 25+i*3,
    })
box = NS(player_id="P0", minutes=34.0, points=24, rebounds=4, assists=8)
game = NS(home_team="CHI", away_team="HOU", player_box_scores=(box,))
schedule = {"G1": NS(day_index=1)}
state = NS(players=players, schedule=schedule, completed_games={"G1": game})
assert set(m.assign_depth_chart_v1(rows)) == {"PG","SG","SF","PF","C"}
assert m.contract_label_v1(players["P0"])[0] == "$12.0M"
assert m.recent_form_v1(state, "P0", "CHI")[-1]["points"] == 24
assert m.archetype_label_v1(players["P0"])
assert m.role_label_v1(rows[0])
print("PREMIUM ROSTER FRESH IMPORT OK")
'''
proc = subprocess.run(
    [sys.executable, "-c", smoke.replace("SRC", repr(str((ROOT / "src").resolve())))],
    cwd=str(ROOT),
    text=True,
    capture_output=True,
)
checks["fresh_process_module_contract"] = (
    proc.returncode == 0 and "PREMIUM ROSTER FRESH IMPORT OK" in proc.stdout
)

failed = [name for name, ok in checks.items() if not ok]
print({
    "version": "franchise-premium-player-cards-depth-chart-v1-validator-2026-09-11",
    "checks": checks,
    "failed_checks": failed,
    "compile_error": compile_error,
    "fresh_import_stdout": proc.stdout.strip(),
    "fresh_import_stderr": proc.stderr.strip(),
    "passed": not failed,
})
if failed:
    raise SystemExit("FRANCHISE PREMIUM PLAYER CARDS + DEPTH CHART V1 VALIDATOR FAILED")
print("FRANCHISE PREMIUM PLAYER CARDS + DEPTH CHART V1 VALIDATOR PASSED")
