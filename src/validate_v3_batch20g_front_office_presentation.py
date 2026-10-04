from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
VERSION = "v3-batch20g-game-day-v1.0.0-2026-10-03"


def save_hashes() -> dict[str, str]:
    return {name: hashlib.sha256((ROOT / "outputs/runtime" / name).read_bytes()).hexdigest()
            for name in ("v3_godot_working_checkpoint.pkl.gz", "franchise_mode_checkpoint_v1.pkl.gz")}


def main() -> int:
    before = save_hashes()
    godot = Path(os.environ.get("USERPROFILE", "")) / "Downloads/Godot_v4.0-stable_win64.exe"
    console = godot.with_name(godot.stem + "_console.exe")
    if console.is_file():
        godot = console
    results = {}
    with tempfile.TemporaryDirectory(prefix="v3_front_office_smoke_") as scratch:
        marker = Path(scratch) / "passed.json"
        script = Path(scratch) / "game_day.gd"
        script.write_text("""extends SceneTree
func _initialize():
    var page = load("res://scripts/front_office_center_v3.gd").new()
    root.add_child(page)
    await process_frame
    page.payload = {"season": {"label": "2026-27", "phase": "regular_season"}, "team": {"abbreviation": "BOS", "roster_size": 14, "active_players": 10, "inactive_players": 4}, "rotation": {"rotation_players": 10, "total_target_minutes": 240}, "team_health": {"injured_count": 0, "injuries": [], "workload_watch": []}, "chemistry": {"frustrated_players": 0, "trade_pressure_players": 0}, "morale": {"attention": []}}
    page._render_payload()
    assert(page.roster_value.text == "14 PLAYERS • 10 ROTATION")
    assert("Injured / limited: 0" in page.health_text.text)
    assert("No active injuries" in page.health_text.text)
    assert("No major morale alerts" in page.morale_text.text)
    assert("Frustrated: 0" in page.morale_text.text)
    assert("240 target minutes" in page.workload_text.text)
    page.payload.team_health.injuries = [{"name": "Fixture Player", "status": "Out", "games_remaining": 3}]
    page.payload.morale.attention = [{"name": "Fixture Player", "status": "Unhappy", "trade_request_risk": 20}]
    page._render_payload()
    assert("Fixture Player" in page.health_text.text)
    assert("3 games" in page.health_text.text)
    assert("trade risk 20%" in page.morale_text.text)
    page.payload = {"season": null, "team": null, "rotation": null, "team_health": null, "morale": null, "chemistry": null, "financial": null}
    page._render_payload()
    assert(page.roster_value.text == "N/A PLAYERS • N/A ROTATION")
    assert("not been evaluated" in page.health_text.text)
    assert(not "No active injuries" in page.health_text.text)
    assert("not been evaluated" in page.morale_text.text)
    assert(not "No major morale alerts" in page.morale_text.text)
    assert("Frustrated: N/A" in page.morale_text.text)
    assert("N/A target minutes" in page.workload_text.text)
    assert("Roster size: N/A" in page.financial_text.text)
    assert(page._count_text(0) == "0")
    assert(page._count_text(null) == "N/A")
    assert("not been evaluated" in page._render_morale({"full_roster": [{"score": null, "trade_request_risk": null, "status": ""}], "attention": []}, {}))
    assert("No major morale alerts" in page._render_morale({"full_roster": [{"score": 80, "trade_request_risk": 0, "status": "Content"}], "attention": []}, {}))
    page.apply_team_brand("LAL", Color("fdb927"), Color("552583"))
    assert(page.refresh_button.get_theme_stylebox("normal").bg_color == Color("fdb927"))
    assert(page.refresh_button.get_theme_color("font_color") == Color("0a0d12"))
    assert(page.request.get_http_client_status() == HTTPClient.STATUS_DISCONNECTED)
    var output = FileAccess.open(MARKER_PATH, FileAccess.WRITE)
    output.store_string(JSON.stringify({"known_zero_and_missing_counts": true, "health_and_morale_alerts": true, "null_summary_and_stale_refresh": true, "active_team_branding": true, "render_never_requests_or_writes": true}))
    output.close()
    quit(0)
""".replace("MARKER_PATH", json.dumps(marker.as_posix())), encoding="utf-8")
        try:
            proc = subprocess.run([str(godot), "--headless", "--path", "godot_client", "--script", str(script)],
                                  cwd=ROOT, capture_output=True, text=True, timeout=30)
            combined = proc.stdout + "\n" + proc.stderr
            bad = ("script error", "parse error", "assertion failed", "failed to load script")
            results["godot_runtime_completed"] = proc.returncode == 0 and marker.exists() and not any(m in combined.lower() for m in bad)
            if results["godot_runtime_completed"]:
                results.update(json.loads(marker.read_text(encoding="utf-8")))
            else:
                print(combined[-7000:])
        except (subprocess.TimeoutExpired, OSError) as exc:
            results["godot_runtime_completed"] = False
            print(exc)
    results["active_v3_and_protected_v2_unchanged"] = save_hashes() == before
    output = ROOT / "outputs/v3_batch20g_front_office_presentation"
    output.mkdir(parents=True, exist_ok=True)
    (output / "validation.json").write_text(json.dumps({"version": VERSION, "results": results}, indent=2), encoding="utf-8")
    for label, passed in results.items():
        print(f"{label}: {'PASS' if passed else 'FAIL'}")
    passed = all(results.values())
    print("V3 BATCH 20G VALIDATION " + ("PASSED" if passed else "FAILED"))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
