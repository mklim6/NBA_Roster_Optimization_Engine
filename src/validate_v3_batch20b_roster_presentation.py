from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
from types import SimpleNamespace
from unittest.mock import patch
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "godot_client" / "scripts" / "main.gd"
PORTRAIT = ROOT / "godot_client" / "scripts" / "player_portrait_v3.gd"
V3 = ROOT / "outputs" / "runtime" / "v3_godot_working_checkpoint.pkl.gz"
V2 = ROOT / "outputs" / "runtime" / "franchise_mode_checkpoint_v1.pkl.gz"

VERSION = "v3-batch20b-roster-presentation-v1.0.0-2026-10-03"
MARKER = "# Batch 20B roster presentation upgrade"


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


def godot_executable() -> Path | None:
    profile = Path(os.environ.get("USERPROFILE", ""))
    candidates = [
        profile / "Downloads" / "Godot_v4.0-stable_win64.exe",
        profile / "Downloads" / "Godot_v4.0-stable_win64" / "Godot_v4.0-stable_win64.exe",
    ]
    return next((p for p in candidates if p.is_file()), None)


def godot_roster_smoke() -> tuple[bool, str]:
    godot = godot_executable()
    if godot is None:
        return False, "Godot 4.0 executable was not found in the expected Downloads location."

    console = godot.with_name(godot.stem + "_console.exe")
    if console.is_file():
        godot = console

    with tempfile.TemporaryDirectory(prefix="v3_batch20b_smoke_") as scratch:
        script = Path(scratch) / "batch20b_smoke.gd"
        marker = Path(scratch) / "passed.txt"
        script.write_text(
            """extends SceneTree
func _initialize():
    var shell = load("res://scripts/main.gd").new()
    root.add_child(shell)
    await process_frame
    assert(shell._display_text(null) == "N/A")
    assert(shell._display_text("") == "N/A")
    assert(shell._display_text("-$30.8M") == "-$30.8M")
    shell._apply_roster_payload({"financial": {"cap_room_estimate_display": null}})
    assert(shell.roster_cap_value.text == "N/A")
    shell._apply_roster_payload({"financial": {"cap_room_estimate_display": "-$30.8M"}})
    assert(shell.roster_cap_value.text == "-$30.8M")
    var player = {
        "player_id": "offline_fixture",
        "name": "Presentation Fixture",
        "position": "SF",
        "age": 26.0,
        "overall": 91.0,
        "potential": 94.0,
        "future_outlook": 92.0,
        "development_direction": "Rising",
        "is_starter": true,
        "in_rotation": true,
        "target_minutes": 34,
        "role": "Primary Starter",
        "rotation_order": 1,
        "contract": {
            "salary_display": "$42.0M",
            "years_remaining": 3,
            "status": "under_contract",
            "option_type": ""
        },
        "morale": {
            "status": "Happy",
            "score": 88.0,
            "role_satisfaction": 91.0,
            "expected_role": "Starter",
            "recent_minutes": 34.0,
            "trade_request_risk": 0.0,
            "trade_request_status": ""
        },
        "health": {
            "display": "Healthy",
            "status": "healthy",
            "fatigue": 4.0,
            "durability": 0.9,
            "risk_tier": "low",
            "season_games_missed": 0,
            "injuries_suffered": 0
        },
        "season_stats": {"ppg": 25.0, "rpg": 7.0, "apg": 5.0},
        "skills": {}
    }
    var row = shell._roster_row(player)
    root.add_child(row)
    assert(row.find_child("RosterOverallBadge", true, false) != null)
    shell._show_player_detail(player)
    await process_frame
    assert(shell.player_detail_overlay != null)
    assert(shell.player_detail_overlay.find_child("ProfileOverallTile", true, false) != null)
    assert(shell.player_detail_overlay.find_child("ProfilePotentialTile", true, false) != null)
    var portrait_script = load("res://scripts/player_portrait_v3.gd")
    var portraits = []
    collect_portraits(root, portrait_script, portraits)
    assert(portraits.size() >= 2)
    var output = FileAccess.open(MARKER_PATH, FileAccess.WRITE)
    output.store_string("PASS")
    output.close()
    quit(0)
func collect_portraits(node, script, found):
    if node.get_script() == script:
        found.append(node)
    for child in node.get_children():
        collect_portraits(child, script, found)
""".replace("MARKER_PATH", json.dumps(marker.as_posix())),
            encoding="utf-8",
        )
        try:
            proc = subprocess.run(
                [str(godot), "--headless", "--path", "godot_client", "--script", str(script)],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=30,
            )
        except subprocess.TimeoutExpired:
            return False, "Batch 20B roster/profile runtime smoke timed out."

        combined = (proc.stdout or "") + "\n" + (proc.stderr or "")
        bad_markers = (
            "script error",
            "parse error",
            "parser error",
            "could not resolve class",
            "failed to load script",
            "assertion failed",
        )
        ok = (
            proc.returncode == 0
            and marker.exists()
            and not any(item in combined.lower() for item in bad_markers)
        )
        return ok, combined[-7000:]


def financial_summary_checks(results: dict[str, bool]) -> None:
    import sys
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from desktop_bridge import server

    state = SimpleNamespace(
        settings=SimpleNamespace(season_label="2026-27"),
        teams={"BOS": SimpleNamespace(roster_player_ids=["fixture"])},
        players={"fixture": SimpleNamespace(contract=SimpleNamespace(salary=200_000_000.0))},
    )
    before = repr(vars(state))
    thresholds = server._desktop_season_thresholds("2026-27")
    summary = server._roster_financial_summary(state, "BOS")
    check(summary["cap_room_estimate"] == thresholds["salary_cap"] - 200_000_000.0
          and summary["cap_room_estimate_display"].startswith("-$"),
          "fresh_franchise_cap_uses_canonical_season_rules", results)
    check(repr(vars(state)) == before, "cap_summary_does_not_mutate_state", results)
    state.settings.season_label = "2027-28"
    future = server._roster_financial_summary(state, "BOS")
    check(future["salary_cap"] == server._desktop_season_thresholds("2027-28")["salary_cap"]
          and future["salary_cap"] > summary["salary_cap"],
          "future_season_cap_uses_existing_growth_model", results)
    state.franchise_active_financial_snapshot_v1 = {"thresholds": {"salary_cap": 210_000_000.0}}
    with patch.object(server, "_desktop_season_thresholds", side_effect=AssertionError("unexpected fallback")):
        saved = server._roster_financial_summary(state, "BOS")
    check(saved["cap_room_estimate"] == 10_000_000.0,
          "saved_financial_thresholds_remain_authoritative", results)
    del state.franchise_active_financial_snapshot_v1
    with patch.object(server, "_desktop_season_thresholds", side_effect=ValueError("missing rules")):
        unknown = server._roster_financial_summary(state, "BOS")
    check(unknown["salary_cap"] is None and unknown["cap_room_estimate"] is None
          and unknown["threshold_source"] == "unavailable",
          "missing_rules_do_not_fabricate_cap_space", results)


def main() -> int:
    v3_before = sha256(V3)
    v2_before = sha256(V2)
    results: dict[str, bool] = {}

    print("=" * 100)
    print("V3 BATCH 20B ROSTER PRESENTATION VALIDATION")
    print("=" * 100)

    main_text = MAIN.read_text(encoding="utf-8") if MAIN.exists() else ""
    portrait_text = PORTRAIT.read_text(encoding="utf-8") if PORTRAIT.exists() else ""

    check(MAIN.is_file(), "main_shell_present", results)
    check(PORTRAIT.is_file(), "player_portrait_component_present", results)
    check(MARKER in main_text, "batch20b_marker_present", results)
    check(
        not any(re.match(r"^\s*\\t", line) for line in main_text.splitlines()),
        "main_has_no_literal_backslash_tab_indentation",
        results,
    )
    check(
        'load("res://scripts/player_portrait_v3.gd")' in main_text
        and 'preload("res://scripts/player_portrait_v3.gd")' not in main_text,
        "batch20a_lazy_portrait_loading_preserved",
        results,
    )
    check(
        'badge.name = "RosterOverallBadge"' in main_text
        and '_roster_rating_badge(player.get("overall", null))' in main_text,
        "roster_rating_badge_present",
        results,
    )
    check(
        'tile.name = "ProfileOverallTile"' in main_text
        and 'tile.name = "ProfilePotentialTile"' in main_text,
        "profile_rating_tiles_present",
        results,
    )
    check(
        "func _rating_tone(value) -> Color:" in main_text,
        "rating_hierarchy_helper_present",
        results,
    )
    check(
        "ACTIVE STANDARD CONTRACTS" in main_text
        and "LOCKER ROOM PULSE" in main_text,
        "roster_summary_hierarchy_present",
        results,
    )
    check(
        "https://cdn.nba.com/headshots/nba/latest/260x190/%s.png" in portrait_text
        and "user://v3_media_cache/player_headshots" in portrait_text,
        "real_headshot_source_and_cache_preserved",
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
        all(endpoint in main_text for endpoint in endpoints),
        "bridge_endpoint_contract_preserved",
        results,
    )

    financial_summary_checks(results)

    smoke_ok, smoke_tail = godot_roster_smoke()
    check(smoke_ok, "godot_roster_profile_runtime_smoke", results)
    if not smoke_ok:
        print(smoke_tail)

    check(sha256(V3) == v3_before, "validator_never_changes_active_v3_save", results)
    check(sha256(V2) == v2_before, "validator_never_changes_active_v2_save", results)

    out = ROOT / "outputs" / "v3_batch20b_roster_presentation"
    out.mkdir(parents=True, exist_ok=True)
    report = out / "validation.json"
    report.write_text(
        json.dumps({"version": VERSION, "results": results}, indent=2),
        encoding="utf-8",
    )

    print()
    print(f"Report: {report}")
    if all(results.values()):
        print()
        print("V3 BATCH 20B VALIDATION PASSED")
        print("Roster presentation upgraded while 20A media, bridge contracts, and both save boundaries remain protected.")
        return 0

    print()
    print("V3 BATCH 20B VALIDATION FAILED")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
