
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = "v3-50b-r2e-0.7-trade-validator-contrast-hotfix-2026-10-06"


def _sha(path: Path) -> str | None:
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _save_hashes() -> dict[str, str | None]:
    runtime = ROOT / "outputs" / "runtime"
    return {
        name: _sha(runtime / name)
        for name in (
            "v3_godot_working_checkpoint.pkl.gz",
            "franchise_mode_checkpoint_v1.pkl.gz",
        )
    }


def _godot() -> Path | None:
    user = Path(os.environ.get("USERPROFILE", ""))
    candidates = [
        user / "Downloads" / "Godot_v4.0-stable_win64_console.exe",
        user / "Downloads" / "Godot_v4.0-stable_win64.exe",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


GDSCRIPT = r'''extends SceneTree
const Branding = preload("res://scripts/team_branding_v3.gd")


func pass_step(label: String) -> void:
    print("PASS • " + label)

func fail_step(label: String) -> void:
    push_error("R2E_DIAGNOSTIC_FAIL • " + label)
    print("FAIL • " + label)
    quit(2)

func _initialize() -> void:
    print("STEP 1 • construct Trade Center")
    root.size = Vector2i(1440, 900)
    var page = load("res://scripts/trade_center_v3.gd").new()
    root.add_child(page)
    page.size = Vector2(1126, 900)
    pass_step("trade script loads and page instantiates")

    print("STEP 2 • wait for initial page ready")
    await process_frame
    pass_step("initial page ready")

    print("STEP 3 • verify premium surfaces")
    var hero = page.find_child("TradeNegotiationHero", true, false)
    if hero == null:
        fail_step("negotiation hero missing")
        return
    pass_step("negotiation hero exists")
    if page.find_child("TradeFinderPremiumSurface", true, false) == null:
        fail_step("premium finder surface missing")
        return
    pass_step("premium finder surface exists")
    if page.find_child("TradePackageControlSurface", true, false) == null:
        fail_step("premium package control missing")
        return
    pass_step("premium package control exists")
    if page.find_child("TradeLegalityDeskSurface", true, false) == null:
        fail_step("premium legality desk missing")
        return
    pass_step("premium legality desk exists")

    print("STEP 4 • seed synthetic teams and assets")
    page.active_team = "BOS"
    page.partner_selector.add_item("SAS")
    page.foundation_payload = {
        "trade_assets": {
            "players": [
                {"player_id": "a0", "name": "Outgoing Guard", "position": "PG", "overall": 84.0, "age": 26, "salary": 18000000},
                {"player_id": "a1", "name": "Outgoing Wing", "position": "SF", "overall": 79.0, "age": 24, "salary": 9000000},
            ]
        },
        "draft_assets": {
            "owned": [
                {"asset_id": "p0", "display_name": "2029 BOS first", "engine_ready": true}
            ]
        }
    }
    page.partner_payload = {
        "team": "SAS",
        "players": [
            {"player_id": "b0", "name": "Incoming Center", "position": "C", "overall": 88.0, "age": 25, "salary": 24000000}
        ],
        "picks": []
    }
    pass_step("synthetic payload assigned")

    print("STEP 5 • render asset boards")
    page._render_active_assets()
    pass_step("active assets rendered")
    page._render_partner_assets()
    pass_step("partner assets rendered")

    print("STEP 6 • select package assets")
    page._on_asset_toggled(true, "active_player", "a0")
    pass_step("outgoing player selected")
    page._on_asset_toggled(true, "active_pick", "p0")
    pass_step("outgoing pick selected")
    page._on_asset_toggled(true, "partner_player", "b0")
    pass_step("incoming player selected")
    await process_frame
    pass_step("selected package frame completed")

    print("STEP 7 • verify negotiation hero identities")
    hero = page.find_child("TradeNegotiationHero", true, false)
    if hero == null:
        fail_step("hero disappeared after package update")
        return
    var left_logo = hero.find_child("NegotiationActiveTeamLogo", true, false)
    var right_logo = hero.find_child("NegotiationPartnerTeamLogo", true, false)
    if left_logo == null:
        fail_step("active-team logo missing")
        return
    if right_logo == null:
        fail_step("partner-team logo missing")
        return
    if not ("team" in left_logo):
        fail_step("active-team logo lacks team property")
        return
    if not ("team" in right_logo):
        fail_step("partner-team logo lacks team property")
        return
    if str(left_logo.team) != "BOS":
        fail_step("active-team logo identity incorrect")
        return
    pass_step("active-team identity in hero")
    if str(right_logo.team) != "SAS":
        fail_step("partner-team logo identity incorrect")
        return
    pass_step("partner-team identity in hero")

    print("STEP 8 • verify package state chip")
    var state_chip = hero.find_child("NegotiationStateChip", true, false)
    if state_chip == null:
        fail_step("negotiation state chip missing")
        return
    if not ("text" in state_chip):
        fail_step("negotiation state chip lacks text property")
        return
    if str(state_chip.text) != "PACKAGE NEEDS PREVIEW":
        fail_step("negotiation state chip text mismatch: " + str(state_chip.text))
        return
    pass_step("hero follows package state")

    print("STEP 9 • render Trade Finder proposal")
    page.proposals = [{
        "partner_team": "SAS",
        "response_label": "Interested",
        "deal_type": "player_swap",
        "incoming": ["Incoming Center"],
        "outgoing": ["Outgoing Guard"],
        "side_a_player_ids": ["a0"],
        "side_b_player_ids": ["b0"],
        "side_a_pick_asset_ids": [],
        "side_b_pick_asset_ids": [],
    }]
    page._render_proposals()
    pass_step("proposal render returned")
    if page.proposal_rows.get_child_count() != 1:
        fail_step("proposal row count")
        return
    var proposal = page.proposal_rows.get_child(0)
    if not proposal is Button:
        fail_step("proposal is not Button")
        return
    if proposal.custom_minimum_size.y < 100.0:
        fail_step("proposal card height")
        return
    pass_step("proposal is a large selectable offer card")
    var proposal_logo = proposal.get_child(0) if proposal.get_child_count() > 0 else null
    if proposal_logo == null:
        fail_step("proposal logo missing")
        return
    if not ("team" in proposal_logo):
        fail_step("proposal logo lacks team property")
        return
    if str(proposal_logo.team) != "SAS":
        fail_step("proposal logo identity mismatch")
        return
    pass_step("proposal carries partner branding")

    print("STEP 10 • reapply BOS brand")
    page.apply_team_brand("BOS", Color("007a33"), Color("ba9653"))
    pass_step("apply_team_brand returned")
    await process_frame
    pass_step("brand frame completed")
    var expected_foreground: Color = Branding.readable_foreground(Color("007a33"))
    if page.preview_button.get_theme_color("font_color") != expected_foreground:
        fail_step("primary action contrast")
        return
    pass_step("primary action contrast preserved")

    print("STEP 11 • confirm network idle")
    if page.foundation_request.get_http_client_status() != HTTPClient.STATUS_DISCONNECTED:
        fail_step("foundation request unexpectedly active")
        return
    pass_step("foundation request idle")
    if page.partner_assets_request.get_http_client_status() != HTTPClient.STATUS_DISCONNECTED:
        fail_step("partner request unexpectedly active")
        return
    pass_step("partner request idle")
    if page.preview_request.get_http_client_status() != HTTPClient.STATUS_DISCONNECTED:
        fail_step("preview request unexpectedly active")
        return
    pass_step("preview request idle")
    if page.execute_request.get_http_client_status() != HTTPClient.STATUS_DISCONNECTED:
        fail_step("execute request unexpectedly active")
        return
    pass_step("execution request idle")

    print("STEP 12 • write pass marker and quit")
    var marker = FileAccess.open(MARKER_PATH, FileAccess.WRITE)
    if marker == null:
        fail_step("could not create pass marker")
        return
    marker.store_string("PASS")
    marker.close()
    print("R2E_DIAGNOSTIC_PASS")
    quit(0)
'''


def main() -> int:
    before = _save_hashes()
    godot = _godot()
    if godot is None:
        print("[FAIL] Godot executable not found in Downloads.")
        return 2

    with tempfile.TemporaryDirectory(prefix="v3_r2e_trade_diag_") as td:
        marker = Path(td) / "pass.txt"
        script = Path(td) / "trade_visual_diag.gd"
        script.write_text(
            GDSCRIPT.replace("MARKER_PATH", json.dumps(marker.as_posix())),
            encoding="utf-8",
        )
        try:
            proc = subprocess.run(
                [
                    str(godot),
                    "--headless",
                    "--path",
                    "godot_client",
                    "--script",
                    str(script),
                ],
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=25,
            )
            combined = proc.stdout.decode("utf-8", errors="replace")
            print(combined)
            runtime_ok = (
                proc.returncode == 0
                and marker.is_file()
                and "R2E_DIAGNOSTIC_PASS" in combined
            )
        except subprocess.TimeoutExpired as exc:
            partial = exc.stdout or b""
            if isinstance(partial, str):
                combined = partial
            else:
                combined = partial.decode("utf-8", errors="replace")
            print(combined)
            print("\n[FAIL] Godot diagnostic timed out after 25 seconds.")
            print("The last STEP/PASS line above identifies the exact runtime stop point.")
            runtime_ok = False
        except OSError as exc:
            print(f"[FAIL] Could not run Godot: {exc}")
            runtime_ok = False

    after = _save_hashes()
    safe = before == after
    print(f"godot_runtime_completed: {'PASS' if runtime_ok else 'FAIL'}")
    print(f"active_v3_and_protected_v2_unchanged: {'PASS' if safe else 'FAIL'}")

    if runtime_ok and safe:
        print("\nV3 50B-R2E.0.1 TRADE RUNTIME DIAGNOSTIC PASSED")
        return 0

    print("\nV3 50B-R2E.0.1 TRADE RUNTIME DIAGNOSTIC FOUND A CONCRETE STOP POINT")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
