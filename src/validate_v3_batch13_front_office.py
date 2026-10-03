from __future__ import annotations

import hashlib
import json
import py_compile
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from simulation_franchise_checkpoint_v1 import (  # noqa: E402
    DEFAULT_CHECKPOINT_PATH,
    load_franchise_checkpoint,
)
from desktop_bridge.front_office_foundation import (  # noqa: E402
    FRONT_OFFICE_FOUNDATION_VERSION,
    build_front_office_intelligence_payload,
)
from desktop_bridge.server import (  # noqa: E402
    TEAM_NAMES,
    V3_WORKING_CHECKPOINT_PATH,
    _roster_payload,
)


REPORT_DIR = ROOT / "outputs" / "v3_batch13_front_office"
REPORT_PATH = REPORT_DIR / "validation.json"


def sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def check(name: str, condition: Any, results: dict[str, bool]) -> None:
    results[name] = bool(condition)
    print(f"  {name}: {'PASS' if condition else 'FAIL'}")


def active_team(checkpoint: Any) -> str:
    preferences = dict(getattr(checkpoint, "preferences", {}) or {})
    return str(preferences.get("franchise_pref_active_team", "") or "").strip().upper()


def compile_files(results: dict[str, bool]) -> None:
    files = [
        ROOT / "desktop_bridge" / "front_office_foundation.py",
        ROOT / "desktop_bridge" / "server.py",
        ROOT / "src" / "validate_v3_batch13_front_office.py",
    ]
    ok = True
    for path in files:
        try:
            py_compile.compile(str(path), doraise=True)
        except Exception as exc:
            ok = False
            print(f"    compile failure: {path}: {type(exc).__name__}: {exc}")
    check("modified_python_files_compile", ok, results)


def static_checks(results: dict[str, bool]) -> None:
    foundation = (ROOT / "desktop_bridge" / "front_office_foundation.py").read_text(
        encoding="utf-8"
    )
    server = (ROOT / "desktop_bridge" / "server.py").read_text(encoding="utf-8")
    main = (ROOT / "godot_client" / "scripts" / "main.gd").read_text(encoding="utf-8")
    godot = (
        ROOT / "godot_client" / "scripts" / "front_office_center_v3.gd"
    ).read_text(encoding="utf-8")

    check(
        "batch13_foundation_version",
        "batch-13-health-development-2026-10-03" in FRONT_OFFICE_FOUNDATION_VERSION,
        results,
    )
    check(
        "front_office_endpoint_registered",
        'Route("/v3/front-office", front_office_intelligence, methods=["GET"])' in server,
        results,
    )
    check(
        "front_office_foundation_imported",
        "from desktop_bridge.front_office_foundation import build_front_office_intelligence_payload"
        in server,
        results,
    )
    check(
        "front_office_endpoint_read_only",
        "async def front_office_intelligence" in server
        and 'Route("/v3/front-office", front_office_intelligence, methods=["POST"])'
        not in server,
        results,
    )
    check(
        "godot_front_office_center_preloaded",
        'FrontOfficeCenterV3 = preload("res://scripts/front_office_center_v3.gd")' in main,
        results,
    )
    check(
        "godot_front_office_center_instantiated",
        "front_office_page = FrontOfficeCenterV3.new()" in main,
        results,
    )
    check(
        "godot_front_office_live_endpoint",
        'FRONT_OFFICE_URL := "http://127.0.0.1:8765/v3/front-office"' in godot,
        results,
    )
    check(
        "front_office_sections_present",
        all(
            token in godot
            for token in (
                "TEAM HEALTH",
                "MORALE + ROLE HEALTH",
                "DEVELOPMENT CORE",
                "ROTATION + WORKLOAD",
                "FINANCIAL / ROSTER HEALTH",
                "STAFF ROOM",
            )
        ),
        results,
    )
    check(
        "staff_writes_explicitly_disabled",
        '"write_actions_enabled": False' in foundation
        and "Staff writes: DISABLED" in godot,
        results,
    )
    check(
        "development_uses_production_player_state",
        all(
            token in foundation
            for token in (
                "potential_rating",
                "future_outlook_rating",
                "development_direction",
                "development_history",
            )
        ),
        results,
    )
    check(
        "health_uses_production_roster_snapshot",
        all(
            token in foundation
            for token in (
                "fatigue",
                "durability",
                "risk_tier",
                "games_remaining",
            )
        ),
        results,
    )
    check(
        "morale_uses_production_roster_snapshot",
        all(
            token in foundation
            for token in (
                "role_satisfaction",
                "trade_request_risk",
                "trade_request_status",
            )
        ),
        results,
    )
    check(
        "godot_safe_payload_conversion_helpers",
        all(token in godot for token in ("func _text(", "func _int_value(", "func _float_value(")),
        results,
    )
    check(
        "godot_trade_risk_uses_percent_points",
        'line += " • trade risk %.0f%%" % risk' in godot
        and 'trade risk %.0f%%" % (risk * 100.0)' not in godot,
        results,
    )
    compile_files(results)


def dynamic_checks(results: dict[str, bool]) -> dict[str, Any]:
    working = Path(V3_WORKING_CHECKPOINT_PATH)
    v2 = Path(DEFAULT_CHECKPOINT_PATH)
    working_before = sha256(working)
    v2_before = sha256(v2)
    detail: dict[str, Any] = {}

    try:
        checkpoint = load_franchise_checkpoint(path=working, allow_backup=False)
        if checkpoint is None:
            raise RuntimeError("V3 working checkpoint could not be loaded.")
        team = active_team(checkpoint)
        if not team:
            raise RuntimeError("Active franchise team is missing from the V3 checkpoint.")
        state = checkpoint.simulation_state
        roster = _roster_payload(
            state,
            team,
            source="v3_working_checkpoint",
            editable=True,
        )
        payload = build_front_office_intelligence_payload(
            state,
            team,
            roster,
            team_names=TEAM_NAMES,
        )

        development = dict(payload.get("development", {}) or {})
        health = dict(payload.get("team_health", {}) or {})
        morale = dict(payload.get("morale", {}) or {})
        staff = dict(payload.get("staff", {}) or {})
        competitive = dict(payload.get("competitive", {}) or {})
        season = dict(payload.get("season", {}) or {})
        roster_players = list(roster.get("players", []) or [])

        check("dynamic_read_only_payload", payload.get("read_only") is True, results)
        check("dynamic_v3_working_save_only", payload.get("working_save_only") is True, results)
        check("dynamic_protected_v2_read_only", payload.get("active_v2_read_only") is True, results)
        check("dynamic_front_office_writes_disabled", payload.get("write_actions_enabled") is False, results)
        check("dynamic_active_team_matches", payload.get("team", {}).get("abbreviation") == team, results)
        check(
            "dynamic_development_roster_covered",
            len(development.get("full_roster", [])) == len(roster_players),
            results,
        )
        check(
            "dynamic_development_core_present",
            len(development.get("core", [])) > 0,
            results,
        )
        check(
            "dynamic_workload_watch_present",
            len(health.get("workload_watch", [])) > 0,
            results,
        )
        check("dynamic_injury_context_exposed", "injuries" in health, results)
        check("dynamic_morale_context_exposed", "full_roster" in morale, results)
        morale_rows = list(morale.get("full_roster", []) or [])
        trade_risks = []
        for row in morale_rows:
            value = row.get("trade_request_risk") if isinstance(row, dict) else None
            if value is None:
                continue
            try:
                trade_risks.append(float(value))
            except (TypeError, ValueError):
                pass
        check(
            "dynamic_trade_risk_is_percent_point_scale",
            bool(trade_risks) and all(0.0 <= value <= 100.0 for value in trade_risks),
            results,
        )
        check(
            "dynamic_staff_truthful_and_read_only",
            "standalone_authority_exposed" in staff
            and staff.get("write_actions_enabled") is False
            and bool(str(staff.get("status", "")).strip()),
            results,
        )
        check("dynamic_financial_context_exposed", "financial" in payload, results)
        check("dynamic_rotation_context_exposed", "rotation" in payload, results)

        detail = {
            "season": season.get("label"),
            "phase": season.get("phase"),
            "team": team,
            "record": competitive.get("record"),
            "conference_rank": competitive.get("conference_rank"),
            "conference": competitive.get("conference"),
            "injured_players": health.get("injured_count", 0),
            "morale_attention": morale.get("attention_count", 0),
            "development_core": len(development.get("core", [])),
            "workload_watch": len(health.get("workload_watch", [])),
            "staff_authority_exposed": staff.get("standalone_authority_exposed", False),
            "staff_status": staff.get("status", ""),
            "max_trade_request_risk_pct": max(trade_risks) if trade_risks else None,
        }
    except Exception as exc:
        check("dynamic_read_only_payload", False, results)
        detail = {
            "exception_type": type(exc).__name__,
            "failure_reason": str(exc),
        }

    working_after = sha256(working)
    v2_after = sha256(v2)
    check(
        "validator_never_changes_working_save",
        working_before is not None and working_before == working_after,
        results,
    )
    check(
        "validator_never_changes_v2_checkpoint",
        v2_before is not None and v2_before == v2_after,
        results,
    )
    return detail


def main() -> int:
    print("=" * 88)
    print("V3 BATCH 13 FRONT OFFICE + TEAM HEALTH + DEVELOPMENT VALIDATION")
    print("=" * 88)
    results: dict[str, bool] = {}
    static_checks(results)
    detail = dynamic_checks(results)

    print("\nDynamic live probe: " + ("PASS" if results.get("dynamic_read_only_payload") else "FAIL"))
    if "failure_reason" in detail:
        print(f"  Failure reason: {detail['failure_reason']}")
        print(f"  Exception type: {detail.get('exception_type', '')}")
    else:
        print(f"  Season: {detail.get('season')}")
        print(f"  Phase: {detail.get('phase')}")
        print(
            "  Team: "
            f"{detail.get('team')} #{detail.get('conference_rank')} {detail.get('conference')} "
            f"({detail.get('record')})"
        )
        print(f"  Injured players: {detail.get('injured_players')}")
        print(f"  Morale attention: {detail.get('morale_attention')}")
        print(f"  Development core: {detail.get('development_core')}")
        print(f"  Workload watch: {detail.get('workload_watch')}")
        print(f"  Standalone staff authority exposed: {detail.get('staff_authority_exposed')}")
        print(f"  Max trade-request risk: {detail.get('max_trade_request_risk_pct')}%")

    print("Godot parser: SKIP (Godot CLI not on PATH; static wiring checks only)")

    passed = all(results.values())
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(
        json.dumps(
            {
                "passed": passed,
                "checks": results,
                "dynamic": detail,
            },
            indent=2,
            sort_keys=True,
            default=str,
        ),
        encoding="utf-8",
    )
    print(f"Report: {REPORT_PATH}")
    print()
    print("BATCH 13 VALIDATION PASSED" if passed else "BATCH 13 VALIDATION FAILED")
    print("No front-office action was durably executed by this validator.")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
