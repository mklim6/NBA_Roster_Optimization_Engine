from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "godot_client" / "scripts" / "main.gd"
PORTRAIT = ROOT / "godot_client" / "scripts" / "player_portrait_v3.gd"
TEAM_LOGO = ROOT / "godot_client" / "scripts" / "team_logo_v3.gd"
V3 = ROOT / "outputs" / "runtime" / "v3_godot_working_checkpoint.pkl.gz"
V2 = ROOT / "outputs" / "runtime" / "franchise_mode_checkpoint_v1.pkl.gz"

VERSION = "v3-batch20a4-portrait-integration-validator-v1.0.0-2026-10-03"


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
        return False, "Godot executable not found; parser and runtime checks could not run."

    # The editor scan alone can miss runtime-loaded scripts. Boot the actual
    # shell and both portrait views, and honor exit status even if the executable
    # does not forward its diagnostics to captured stderr.
    console = godot.with_name(godot.stem + "_console.exe")
    if console.is_file():
        godot = console
    diagnostics = []
    markers = ("script error", "parse error", "parser error", "could not resolve class", "failed to load script")
    with tempfile.TemporaryDirectory(prefix="v3_portrait_smoke_") as scratch:
        script = Path(scratch) / "portrait_smoke.gd"
        marker = Path(scratch) / "passed.txt"
        script.write_text("""extends SceneTree
func _initialize():
    var shell = load("res://scripts/main.gd").new()
    root.add_child(shell)
    await process_frame
    var player = {"player_id": "offline_fixture", "name": "Portrait Fixture"}
    var row = shell._roster_row(player)
    root.add_child(row)
    shell._show_player_detail(player)
    await process_frame
    await process_frame
    var portrait_script = load("res://scripts/player_portrait_v3.gd")
    var portraits = []
    collect_portraits(root, portrait_script, portraits)
    assert(portraits.size() == 2)
    for portrait in portraits:
        assert(portrait.fallback_label.text == "PF")
        assert(portrait.fallback_label.visible)
    var output = FileAccess.open(MARKER_PATH, FileAccess.WRITE)
    output.store_string("PASS")
    output.close()
    quit(0)
func collect_portraits(node, script, found):
    if node.get_script() == script:
        found.append(node)
    for child in node.get_children():
        collect_portraits(child, script, found)
""".replace("MARKER_PATH", json.dumps(marker.as_posix())), encoding="utf-8")
        try:
            proc = subprocess.run(
                [str(godot), "--headless", "--path", "godot_client", "--script", str(script)],
                cwd=ROOT, capture_output=True, text=True, timeout=30,
            )
        except subprocess.TimeoutExpired:
            return False, "Roster/profile runtime smoke timed out before its completion marker."
        combined = (proc.stdout or "") + "\n" + (proc.stderr or "")
        diagnostics.append(f"roster/profile runtime smoke: exit {proc.returncode}\n{combined}")
        if proc.returncode != 0 or not marker.exists() or any(m in combined.lower() for m in markers):
            return False, "\n".join(diagnostics)[-7000:]
    return True, "\n".join(diagnostics)[-7000:]


def main() -> int:
    v3_before = sha256(V3)
    v2_before = sha256(V2)
    results: dict[str, bool] = {}

    print("=" * 100)
    print("V3 BATCH 20A.4 PORTRAIT INTEGRATION VALIDATION")
    print("=" * 100)

    main_text = MAIN.read_text(encoding="utf-8") if MAIN.exists() else ""
    portrait_text = PORTRAIT.read_text(encoding="utf-8") if PORTRAIT.exists() else ""

    check(
        not any(re.match(r"^\s*\\t", line) for line in main_text.splitlines()),
        "main_has_no_literal_backslash_tab_indentation",
        results,
    )
    check(MAIN.is_file(), "main_shell_present", results)
    check(PORTRAIT.is_file(), "player_portrait_component_present", results)
    check(not TEAM_LOGO.exists(), "team_logo_still_deferred", results)

    check(
        "class_name PlayerPortraitV3" not in portrait_text,
        "portrait_global_class_registration_removed",
        results,
    )
    check(
        'preload("res://scripts/player_portrait_v3.gd")' not in main_text,
        "startup_preload_removed",
        results,
    )
    check(
        'load("res://scripts/player_portrait_v3.gd")' in main_text,
        "portrait_script_loaded_only_at_runtime",
        results,
    )
    check(
        "portrait_script.new()" in main_text
        and "portrait.configure(player)" in main_text,
        "roster_lazy_portrait_instantiation_present",
        results,
    )
    check(
        "profile_portrait_script.new()" in main_text
        and "profile_portrait.configure(player)" in main_text,
        "profile_lazy_portrait_instantiation_present",
        results,
    )
    check(
        "https://cdn.nba.com/headshots/nba/latest/260x190/%s.png" in portrait_text,
        "real_nba_headshot_source_preserved",
        results,
    )
    check(
        "user://v3_media_cache/player_headshots" in portrait_text,
        "headshot_cache_preserved",
        results,
    )
    check(
        "generated_player_stock_portraits" in portrait_text,
        "generated_portrait_fallback_preserved",
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
    check(all(endpoint in main_text for endpoint in endpoints), "bridge_endpoint_contract_preserved", results)

    parse_ok, parse_tail = godot_parse()
    check(parse_ok, "godot_main_roster_profile_runtime_smoke", results)
    if not parse_ok:
        print(parse_tail)

    check(sha256(V3) == v3_before, "validator_never_changes_active_v3_save", results)
    check(sha256(V2) == v2_before, "validator_never_changes_active_v2_save", results)

    out = ROOT / "outputs" / "v3_batch20a4_portrait_integration"
    out.mkdir(parents=True, exist_ok=True)
    report = out / "validation.json"
    report.write_text(json.dumps({"version": VERSION, "results": results}, indent=2), encoding="utf-8")

    print()
    print(f"Report: {report}")
    if all(results.values()):
        print()
        print("V3 BATCH 20A.4 VALIDATION PASSED")
        print("Portrait media is absent from startup and loads only when roster/profile UI is actually rendered.")
        return 0

    print()
    print("V3 BATCH 20A.4 VALIDATION FAILED")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
