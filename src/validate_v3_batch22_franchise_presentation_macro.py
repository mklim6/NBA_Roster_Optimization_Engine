from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
V3 = ROOT / "outputs/runtime/v3_godot_working_checkpoint.pkl.gz"
V2 = ROOT / "outputs/runtime/franchise_mode_checkpoint_v1.pkl.gz"
VERSION = "v3-batch22-franchise-presentation-macro-v1.0.0-2026-10-04"

PAGES = [
    ("FREE AGENCY", "res://scripts/free_agency_center_v3.gd"),
    ("TRADES", "res://scripts/trade_center_v3.gd"),
    ("SCOUTING", "res://scripts/scouting_draft_center_v3.gd"),
    ("FRONT OFFICE", "res://scripts/front_office_center_v3.gd"),
    ("LEAGUE", "res://scripts/league_intelligence_center_v3.gd"),
]


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else "missing"


def save_hashes() -> dict[str, str]:
    return {"v3": digest(V3), "v2": digest(V2)}


def main() -> int:
    before = save_hashes()
    results: dict[str, bool] = {}

    identity = ROOT / "godot_client/scripts/page_identity_v3.gd"
    results["shared_page_identity_component_present"] = identity.is_file()

    static_pages_ok = True
    for _, script_path in PAGES:
        file_path = ROOT / "godot_client" / script_path.replace("res://", "")
        text = file_path.read_text(encoding="utf-8") if file_path.exists() else ""
        if (
            "# Batch 22 franchise presentation macro" not in text
            or "PageIdentityV3" not in text
            or "page_brand_bar" not in text
        ):
            static_pages_ok = False
    results["five_major_pages_macro_styled"] = static_pages_ok

    game_day = (ROOT / "godot_client/scripts/game_day_center_v3.gd").read_text(encoding="utf-8")
    results["game_day_21b1_preserved_and_repaired"] = all(
        token in game_day for token in [
            "# Batch 21B.1 cinematic Game Day polish",
            "# Batch 22 franchise presentation macro",
            "if team_badge != null:",
            "BroadcastCenterPlate",
            "postgame_home_logo",
        ]
    )
    results["simulation_safety_contract_preserved"] = all(
        token in game_day for token in [
            "if not simulate_armed:",
            'simulation_button.text = "CONFIRM & SIMULATE"',
            "persisted_after_reload",
            "active_v2_unchanged",
            "working_save_only",
        ]
    )

    godot = Path(os.environ.get("USERPROFILE", "")) / "Downloads/Godot_v4.0-stable_win64.exe"
    console = godot.with_name(godot.stem + "_console.exe")
    if console.is_file():
        godot = console

    with tempfile.TemporaryDirectory(prefix="v3_batch22_macro_") as scratch:
        marker = Path(scratch) / "passed.json"
        script = Path(scratch) / "macro_smoke.gd"
        specs = json.dumps([{"name": n, "script": p} for n, p in PAGES])
        script.write_text(
            """extends SceneTree
func _initialize():
    var page_results := {}
    var page_specs = PAGE_SPECS

    for spec in page_specs:
        var page = load(spec["script"]).new()
        root.add_child(page)
        await process_frame
        if page.has_method("apply_team_brand"):
            page.call("apply_team_brand", "BOS", Color("007a33"), Color("ba9653"))
        await process_frame

        var identity = page.get("page_identity")
        var brand_bar = page.get("page_brand_bar")
        assert(identity != null)
        assert(brand_bar != null)
        assert(identity.team == "BOS")
        assert(brand_bar.color == Color("007a33"))

        page_results[spec["name"]] = true
        page.queue_free()
        await process_frame

    var game_day = load("res://scripts/game_day_center_v3.gd").new()
    root.add_child(game_day)
    await process_frame
    game_day.apply_team_brand("BOS", Color("007a33"), Color("ba9653"))
    await process_frame
    assert(game_day.matchup_card != null)
    assert(game_day.simulation_button != null)

    var output = FileAccess.open(MARKER_PATH, FileAccess.WRITE)
    output.store_string(JSON.stringify({
        "page_runtime_smoke": page_results,
        "game_day_branding_runtime": true
    }))
    output.close()
    quit(0)
""".replace("PAGE_SPECS", specs).replace("MARKER_PATH", json.dumps(marker.as_posix())),
            encoding="utf-8",
        )

        try:
            proc = subprocess.run(
                [str(godot), "--headless", "--path", "godot_client", "--script", str(script)],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=45,
            )
            combined = (proc.stdout or "") + "\n" + (proc.stderr or "")
            bad = ("script error", "parse error", "parser error", "assertion failed", "failed to load script")
            results["godot_macro_runtime_completed"] = (
                proc.returncode == 0 and marker.exists()
                and not any(token in combined.lower() for token in bad)
            )
            if results["godot_macro_runtime_completed"]:
                payload = json.loads(marker.read_text(encoding="utf-8"))
                results["all_five_pages_construct_and_brand"] = all(
                    payload.get("page_runtime_smoke", {}).values()
                )
                results["game_day_branding_runtime"] = bool(payload.get("game_day_branding_runtime", False))
            else:
                print(combined[-10000:])
        except (subprocess.TimeoutExpired, OSError) as exc:
            results["godot_macro_runtime_completed"] = False
            print(exc)

    results["active_v3_and_protected_v2_unchanged"] = save_hashes() == before

    out = ROOT / "outputs/v3_batch22_franchise_presentation_macro"
    out.mkdir(parents=True, exist_ok=True)
    (out / "validation.json").write_text(
        json.dumps({"version": VERSION, "results": results}, indent=2),
        encoding="utf-8",
    )

    for key, passed in results.items():
        if isinstance(passed, bool):
            print(f"{key}: {'PASS' if passed else 'FAIL'}")
        else:
            print(f"{key}: {passed}")

    passed = all(v for v in results.values() if isinstance(v, bool))
    print("V3 BATCH 22 MACRO VALIDATION " + ("PASSED" if passed else "FAILED"))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
