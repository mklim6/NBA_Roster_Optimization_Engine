
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


def save_hashes() -> dict[str, str | None]:
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
    for candidate in (
        user / "Downloads" / "Godot_v4.0-stable_win64_console.exe",
        user / "Downloads" / "Godot_v4.0-stable_win64.exe",
    ):
        if candidate.is_file():
            return candidate
    raise FileNotFoundError("Godot executable not found in Downloads.")


GDSCRIPT = r'''extends SceneTree

func fail(label: String) -> void:
    push_error("R2E_0_6_FAIL • " + label)
    quit(2)

func _initialize() -> void:
    root.size = Vector2i(1440, 900)

    print("STEP 1 • load Trade Center")
    var script = ResourceLoader.load("res://scripts/trade_center_v3.gd", "", ResourceLoader.CACHE_MODE_IGNORE)
    if script == null:
        fail("script load")
        return
    print("PASS • script loaded")

    print("STEP 2 • instantiate Trade Center")
    var page = script.new()
    if page == null:
        fail("script.new returned null")
        return
    print("PASS • page instantiated")

    print("STEP 3 • build page")
    root.add_child(page)
    page.size = Vector2(1126, 900)
    await process_frame
    print("PASS • page ready")

    if page.find_child("TradeNegotiationHero", true, false) == null:
        fail("negotiation hero missing")
        return
    print("PASS • negotiation hero")

    for name in [
        "TradeMarketStatusSurface",
        "TradeFinderPremiumSurface",
        "TradePackageControlSurface",
        "TradeLegalityDeskSurface",
    ]:
        if page.find_child(name, true, false) == null:
            fail(name + " missing")
            return
    print("PASS • premium outer surfaces")

    var outgoing = page.find_child("OutgoingAssetsScroll", true, false)
    var incoming = page.find_child("IncomingAssetsScroll", true, false)
    if outgoing == null or incoming == null:
        fail("asset boards missing")
        return
    if outgoing.custom_minimum_size.y < 400 or incoming.custom_minimum_size.y < 400:
        fail("asset board height")
        return
    print("PASS • stable asset boards")

    if page.execute_request.get_http_client_status() != HTTPClient.STATUS_DISCONNECTED:
        fail("execution request unexpectedly active")
        return
    print("PASS • no trade execution request")

    var marker = FileAccess.open(MARKER_PATH, FileAccess.WRITE)
    marker.store_string("PASS")
    marker.close()
    print("R2E_0_6_RUNTIME_PASS")
    quit(0)
'''


def check(name: str, value: bool, results: dict[str, bool]) -> None:
    results[name] = bool(value)
    print(f"[{'PASS' if value else 'FAIL'}] {name}")


def main() -> int:
    before = save_hashes()
    results: dict[str, bool] = {}
    text = TRADE.read_text(encoding="utf-8")

    check("asset_panel_hotfix_marker", "50B-R2E.0.6 stable asset-panel compiler hotfix" in text, results)
    check("r2e_visual_identity_preserved", "FRONT OFFICE • NEGOTIATION ROOM" in text, results)
    check("negotiation_hero_preserved", "TradeNegotiationHero" in text, results)
    check("premium_outer_surfaces_preserved", all(token in text for token in (
        "TradeMarketStatusSurface",
        "TradeFinderPremiumSurface",
        "TradePackageControlSurface",
        "TradeLegalityDeskSurface",
    )), results)
    check("stable_asset_panel_restored", all(token in text for token in (
        'var card := _card(Vector2(0, 0))',
        '"ACTIVE FRANCHISE" if active_side else "TRADE PARTNER"',
        'scroll.custom_minimum_size = Vector2(0, 400)',
    )), results)
    check("trade_endpoints_preserved", all(token in text for token in (
        "/v3/transaction-foundation?trade_finder=1",
        "/v3/trade/team-assets",
        "/v3/trade/preview",
        "/v3/trade/execute",
    )), results)

    with tempfile.TemporaryDirectory(prefix="v3_r2e_0_6_") as td:
        marker = Path(td) / "pass.txt"
        script_path = Path(td) / "runtime.gd"
        script_path.write_text(
            GDSCRIPT.replace("MARKER_PATH", json.dumps(marker.as_posix())),
            encoding="utf-8",
        )
        try:
            proc = subprocess.run(
                [str(godot()), "--headless", "--path", "godot_client", "--script", str(script_path)],
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=20,
            )
            output = proc.stdout.decode("utf-8", errors="replace")
            print(output)
            runtime_ok = marker.is_file() and "R2E_0_6_RUNTIME_PASS" in output
        except subprocess.TimeoutExpired as exc:
            partial = exc.stdout or b""
            output = partial if isinstance(partial, str) else partial.decode("utf-8", errors="replace")
            print(output)
            print("[FAIL] Runtime timed out after 20 seconds.")
            runtime_ok = False
        except OSError as exc:
            print(f"[FAIL] Godot launch failed: {exc}")
            runtime_ok = False

    check("godot_trade_instantiates_and_builds", runtime_ok, results)
    check("active_v3_and_protected_v2_unchanged", before == save_hashes(), results)

    failed = [name for name, passed in results.items() if not passed]
    print()
    if failed:
        print("50B-R2E.0.6 TRADE ASSET-PANEL HOTFIX GATE FAILED")
        print("Failures: " + ", ".join(failed))
        return 1

    print("50B-R2E.0.6 TRADE ASSET-PANEL HOTFIX GATE PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
