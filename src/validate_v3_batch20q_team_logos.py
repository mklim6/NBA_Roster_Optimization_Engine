from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import shutil
import tempfile

ROOT = Path(__file__).resolve().parents[1]
VERSION = "v3-batch20q-logos-v1.0.0-2026-10-03"


def save_hashes() -> dict[str, str]:
    return {name: hashlib.sha256((ROOT / "outputs/runtime" / name).read_bytes()).hexdigest()
            for name in ("v3_godot_working_checkpoint.pkl.gz", "franchise_mode_checkpoint_v1.pkl.gz")}


def main() -> int:
    before = save_hashes()
    godot = Path(os.environ.get("USERPROFILE", "")) / "Downloads/Godot_v4.0-stable_win64.exe"
    console = godot.with_name(godot.stem + "_console.exe")
    if console.is_file():
        godot = console
    manifest = json.loads((ROOT / "godot_client/assets/team_logos/SOURCES.json").read_text(encoding="utf-8"))
    assets = manifest["assets"]
    results = {"all_30_asset_sources_and_hashes": len(assets) == 30 and len({a["team"] for a in assets}) == 30 and all(a["source_url"].startswith("https://cdn.nba.com/logos/nba/") and hashlib.sha256((ROOT / "godot_client/assets/team_logos" / a["file"]).read_text(encoding="utf-8").encode("utf-8")).hexdigest() == a["sha256"] for a in assets)}
    with tempfile.TemporaryDirectory(prefix="v3_home_hero_smoke_") as scratch:
        marker = Path(scratch) / "passed.json"
        script = Path(scratch) / "game_day.gd"
        script.write_text("""extends SceneTree
func _initialize():
    var page = load("res://scripts/main.gd").new()
    root.add_child(page)
    await process_frame
    var branding = load("res://scripts/team_branding_v3.gd")
    var design = load("res://scripts/design_system_v3.gd")
    for team in design.TEAM_BRANDS.keys():
        var texture = branding.logo_texture(team)
        assert(texture != null, team)
        assert(texture.get_width() > 0 and texture.get_height() > 0)
        assert(branding.logo_texture(team) == texture)
        page._apply_active_team_brand(team)
        assert(page.team_logo.texture == texture)
        assert(page.team_logo.team == team)
    assert(branding.logo_texture("../BOS") == null)
    assert(branding.logo_texture("UNKNOWN") == null)
    var fallback = load("res://scripts/team_logo_v3.gd").new()
    root.add_child(fallback)
    fallback.configure("UNKNOWN")
    fallback.size = Vector2(64, 64)
    await process_frame
    assert(fallback.texture == null)
    assert(fallback.team == "UNKNOWN")
    assert(fallback.mouse_filter == Control.MOUSE_FILTER_IGNORE)
    page.matchup_banner.set_matchup("BOS", "LAL", true)
    assert(page.matchup_banner.logos[0] != null)
    assert(page.matchup_banner.logos[1] != null)
    for width in [330, 520, 680]:
        page.matchup_banner.visible = true
        page.matchup_banner.size = Vector2(width, 100)
        page.matchup_banner.queue_redraw()
        await process_frame
    page.matchup_banner.set_matchup("BOS", "UNKNOWN", false)
    assert(page.matchup_banner.logos[1] == null)
    page._show_page("FRANCHISES")
    page._show_page("HOME")
    assert(page.home_page.visible)
    var output = FileAccess.open(MARKER_PATH, FileAccess.WRITE)
    output.store_string(JSON.stringify({"all_30_svg_logos_decode_and_cache": true, "home_brand_switches": true, "unknown_team_fallback_and_path_protection": true, "matchup_resize_and_fallback": true, "home_navigation": true}))
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
    with tempfile.TemporaryDirectory(prefix="v3_logo_first_run_") as scratch:
        probe = Path(scratch)
        (probe / "scripts").mkdir()
        for name in ("team_branding_v3.gd", "design_system_v3.gd", "team_logo_v3.gd"):
            shutil.copy2(ROOT / "godot_client/scripts" / name, probe / "scripts" / name)
        shutil.copytree(ROOT / "godot_client/assets/team_logos", probe / "assets/team_logos", ignore=shutil.ignore_patterns("*.import"))
        (probe / "project.godot").write_text('config_version=5\n[application]\nconfig/name="Logo first-run probe"\n[rendering]\nrenderer/rendering_method="gl_compatibility"\n', encoding="utf-8")
        (probe / "probe.gd").write_text('extends SceneTree\nfunc _initialize():\n    var brand = load("res://scripts/team_branding_v3.gd")\n    var design = load("res://scripts/design_system_v3.gd")\n    for team in design.TEAM_BRANDS:\n        assert(brand.logo_texture(team) != null, team)\n    quit(0)\n', encoding="utf-8")
        try:
            proc = subprocess.run([str(godot), "--headless", "--path", str(probe), "--script", str(probe / "probe.gd")], capture_output=True, text=True, timeout=30)
            combined = proc.stdout + proc.stderr
            results["offline_first_run_without_import_cache"] = proc.returncode == 0 and "error" not in combined.lower()
            if not results["offline_first_run_without_import_cache"]:
                print(combined[-7000:])
        except (subprocess.TimeoutExpired, OSError) as exc:
            results["offline_first_run_without_import_cache"] = False
            print(exc)
    results["active_v3_and_protected_v2_unchanged"] = save_hashes() == before
    output = ROOT / "outputs/v3_batch20q_home_hero"
    output.mkdir(parents=True, exist_ok=True)
    (output / "validation.json").write_text(json.dumps({"version": VERSION, "results": results}, indent=2), encoding="utf-8")
    for label, passed in results.items():
        print(f"{label}: {'PASS' if passed else 'FAIL'}")
    passed = all(results.values())
    print("V3 BATCH 20Q VALIDATION " + ("PASSED" if passed else "FAILED"))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
