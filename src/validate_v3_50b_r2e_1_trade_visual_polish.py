
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TRADE = ROOT / "godot_client" / "scripts" / "trade_center_v3.gd"


def sha(path: Path) -> str | None:
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def saves() -> dict[str, str | None]:
    runtime = ROOT / "outputs" / "runtime"
    return {
        name: sha(runtime / name)
        for name in (
            "v3_godot_working_checkpoint.pkl.gz",
            "franchise_mode_checkpoint_v1.pkl.gz",
        )
    }


def godot() -> Path:
    user = Path(os.environ.get("USERPROFILE", ""))
    for p in (
        user / "Downloads" / "Godot_v4.0-stable_win64_console.exe",
        user / "Downloads" / "Godot_v4.0-stable_win64.exe",
    ):
        if p.is_file():
            return p
    raise FileNotFoundError("Godot executable not found.")


GDSCRIPT = r'''extends SceneTree

func fail(label: String) -> void:
    push_error("R2E1_FAIL • " + label)
    quit(2)

func _initialize() -> void:
    root.size = Vector2i(1440, 900)
    var page = load("res://scripts/trade_center_v3.gd").new()
    root.add_child(page)
    page.size = Vector2(1126, 900)
    await process_frame

    if page.package_stage.visible:
        fail("empty package detail should be hidden")
        return
    print("PASS • empty duplicate package detail hidden")

    page.active_team = "BOS"
    page.partner_selector.add_item("ATL")
    page.foundation_payload = {
        "trade_assets": {
            "players": [
                {"player_id": "a0", "name": "Outgoing Player", "position": "SG", "overall": 84.0, "age": 25, "salary": 18000000}
            ]
        },
        "draft_assets": {"owned": []}
    }
    page.partner_payload = {
        "team": "ATL",
        "players": [
            {"player_id": "b0", "name": "Incoming Player", "position": "SF", "overall": 86.0, "age": 24, "salary": 21000000}
        ],
        "picks": []
    }
    page._render_active_assets()
    page._render_partner_assets()
    page._on_asset_toggled(true, "active_player", "a0")
    page._on_asset_toggled(true, "partner_player", "b0")
    await process_frame

    if not page.package_stage.visible:
        fail("package detail should appear after selecting assets")
        return
    print("PASS • package detail appears for active negotiation")

    page.proposals = []
    page._render_proposals()
    if page.trade_finder_surface.custom_minimum_size.y > 140:
        fail("empty Trade Finder did not compact")
        return
    if page.trade_finder_scroll.custom_minimum_size.y > 55:
        fail("empty Trade Finder scroll did not compact")
        return
    print("PASS • empty Trade Finder compact")

    page.proposals = [{
        "partner_team": "ATL",
        "response_label": "Interested",
        "deal_type": "player_swap",
        "incoming": ["Incoming Player"],
        "outgoing": ["Outgoing Player"],
        "side_a_player_ids": ["a0"],
        "side_b_player_ids": ["b0"],
        "side_a_pick_asset_ids": [],
        "side_b_pick_asset_ids": [],
    }]
    page._render_proposals()
    if page.trade_finder_surface.custom_minimum_size.y < 200:
        fail("populated Trade Finder did not expand")
        return
    if page.trade_finder_scroll.custom_minimum_size.y < 150:
        fail("populated Trade Finder scroll did not expand")
        return
    print("PASS • populated Trade Finder expands")

    if page.find_child("TradeLegalityDeskSurface", true, false) == null:
        fail("legality desk missing")
        return
    print("PASS • legality desk preserved")

    if page.execute_request.get_http_client_status() != HTTPClient.STATUS_DISCONNECTED:
        fail("execution request unexpectedly active")
        return
    print("PASS • no execution request")

    var marker = FileAccess.open(MARKER_PATH, FileAccess.WRITE)
    marker.store_string("PASS")
    marker.close()
    print("R2E1_RUNTIME_PASS")
    quit(0)
'''


def main() -> int:
    before = saves()
    text = TRADE.read_text(encoding="utf-8")
    checks = {
        "r2e1_marker": "50B-R2E.1 visual density + empty-state polish" in text,
        "r2e6_asset_panel_preserved": "50B-R2E.0.6 stable asset-panel compiler hotfix" in text,
        "empty_package_detail_policy": "package_stage.visible = has_assets" in text,
        "compact_trade_finder_policy": "Refresh Market to scan again." in text,
        "legality_rule_rail": all(x in text for x in ("SALARY MATCH", "DRAFT RIGHTS", "CONTRACTS", "CBA RULES")),
        "trade_endpoints_preserved": all(x in text for x in (
            "/v3/transaction-foundation?trade_finder=1",
            "/v3/trade/team-assets",
            "/v3/trade/preview",
            "/v3/trade/execute",
        )),
    }
    for k, v in checks.items():
        print(f"[{'PASS' if v else 'FAIL'}] {k}")

    with tempfile.TemporaryDirectory(prefix="r2e1_") as td:
        marker = Path(td) / "pass.txt"
        script = Path(td) / "runtime.gd"
        script.write_text(
            GDSCRIPT.replace("MARKER_PATH", json.dumps(marker.as_posix())),
            encoding="utf-8",
        )
        try:
            proc = subprocess.run(
                [str(godot()), "--headless", "--path", "godot_client", "--script", str(script)],
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=25,
            )
            output = proc.stdout.decode("utf-8", errors="replace")
            print(output)
            runtime_ok = marker.is_file() and "R2E1_RUNTIME_PASS" in output
        except subprocess.TimeoutExpired as exc:
            partial = exc.stdout or b""
            output = partial if isinstance(partial, str) else partial.decode("utf-8", errors="replace")
            print(output)
            runtime_ok = False

    checks["godot_runtime"] = runtime_ok
    checks["saves_unchanged"] = before == saves()
    print(f"[{'PASS' if runtime_ok else 'FAIL'}] godot_runtime")
    print(f"[{'PASS' if checks['saves_unchanged'] else 'FAIL'}] active_v3_and_protected_v2_unchanged")

    if not all(checks.values()):
        print("50B-R2E.1 VISUAL POLISH GATE FAILED")
        return 1

    print("50B-R2E.1 VISUAL POLISH GATE PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
