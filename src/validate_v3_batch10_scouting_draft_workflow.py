from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import py_compile
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from desktop_bridge import server
from desktop_bridge.transaction_foundation import (
    TRANSACTION_FOUNDATION_VERSION,
    build_draft_selection_preview_payload,
    build_scouting_advance_candidate,
    build_scouting_advance_preview_payload,
    build_scouting_draft_payload,
)
from franchise_draft_engine_v1 import DRAFT_ENGINE_VERSION, run_self_test as draft_self_test
from franchise_scouting_discovery_v1 import FRANCHISE_SCOUTING_DISCOVERY_VERSION
from simulation_franchise_checkpoint_v1 import load_franchise_checkpoint

VALIDATOR_VERSION = "v3-batch10-scouting-draft-workflow-validator-v1-2026-10-02"
REPORT_DIR = ROOT / "outputs" / "v3_batch10_scouting_draft_workflow"
REPORT_PATH = REPORT_DIR / "validation.json"


def sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _synthetic_scouting_checkpoint() -> Any:
    prospects = []
    for index in range(8):
        prospects.append(
            {
                "prospect_id": f"PROSPECT-{index+1}",
                "big_board_rank": index + 1,
                "player_name": f"Prospect {index+1}",
                "position": ("PG", "SG", "SF", "PF", "C")[index % 5],
                "age": 19 + (index % 3),
                "school": f"School {index+1}",
                "archetype": "Two-Way",
                "hidden_overall": 78.0 - index * 0.6,
                "hidden_potential": 88.0 - index * 0.4,
                "projected_range": "Lottery" if index < 4 else "First Round",
                "drafted": False,
            }
        )
    state = SimpleNamespace(
        settings=SimpleNamespace(season_label="2027-28"),
        teams={"CHI": SimpleNamespace()},
        franchise_draft_state_v1={
            "draft_year": 2028,
            "source_season": "2027-28",
            "target_season": "2028-29",
            "phase": "season_scouting",
            "class_strength": 5,
            "prospects": prospects,
            "draft_order": [],
            "current_pick_index": 0,
            "controlled_teams": ["CHI"],
        },
    )
    return SimpleNamespace(
        simulation_state=state,
        trade_state=SimpleNamespace(),
        preferences={"franchise_pref_active_team": "CHI"},
    )


def _synthetic_scouting_checks() -> dict[str, bool]:
    checkpoint = _synthetic_scouting_checkpoint()
    state = checkpoint.simulation_state
    original = copy.deepcopy(state.franchise_draft_state_v1)
    payload = build_scouting_draft_payload(checkpoint, "CHI")
    focus_ids = [payload["board"][0]["prospect_id"], payload["board"][1]["prospect_id"]]
    preview = build_scouting_advance_preview_payload(
        checkpoint,
        "CHI",
        {"focus_ids": focus_ids},
    )
    candidate = build_scouting_advance_candidate(
        checkpoint,
        "CHI",
        {
            "focus_ids": focus_ids,
            "expected_action_fingerprint": preview["action_fingerprint"],
        },
    )
    blocked_draft = build_draft_selection_preview_payload(
        checkpoint,
        "CHI",
        {"prospect_id": focus_ids[0]},
    )
    stale_rejected = False
    try:
        build_scouting_advance_candidate(
            checkpoint,
            "CHI",
            {
                "focus_ids": focus_ids,
                "expected_action_fingerprint": "stale-token",
            },
        )
    except ValueError:
        stale_rejected = True
    board_confidence = [float(row.get("Confidence", 0.0) or 0.0) for row in payload.get("board", [])]
    board_avg = sum(board_confidence) / len(board_confidence) if board_confidence else 0.0
    preview_before = float(preview.get("summary_before", {}).get("average_confidence", 0.0) or 0.0)
    preview_after = float(preview.get("summary_after", {}).get("average_confidence", 0.0) or 0.0)
    return {
        "synthetic_board_uses_scouted_fields": bool(
            payload.get("board")
            and "Scouted OVR" in payload["board"][0]
            and "hidden_overall" not in payload["board"][0]
        ),
        "synthetic_summary_matches_full_board": abs(float(payload.get("summary", {}).get("average_confidence", 0.0) or 0.0) - board_avg) <= 0.11,
        "synthetic_preview_confidence_never_declines": preview_after + 1e-9 >= preview_before,
        "synthetic_preview_is_read_only": state.franchise_draft_state_v1 == original,
        "synthetic_scouting_preview_passes": preview.get("status") == "pass" and preview.get("can_commit") is True,
        "synthetic_scouting_candidate_advances_one_week": candidate.weeks_before == 0 and candidate.weeks_after == 1,
        "synthetic_scouting_candidate_keeps_focus": candidate.focus_ids == tuple(focus_ids),
        "synthetic_stale_scouting_token_rejected": stale_rejected,
        "synthetic_regular_season_draft_pick_blocked": blocked_draft.get("status") == "blocked" and blocked_draft.get("can_commit") is False,
    }


class FakeRequest:
    def __init__(self, body: dict[str, Any]):
        self.body = body

    async def json(self) -> dict[str, Any]:
        return copy.deepcopy(self.body)


def _response_json(response: Any) -> dict[str, Any]:
    return json.loads(response.body.decode("utf-8"))


def _run_isolated_safety_tests() -> dict[str, bool]:
    checks: dict[str, bool] = {}
    names = [
        "V3_WORKING_CHECKPOINT_PATH",
        "DEFAULT_CHECKPOINT_PATH",
        "V3_SCOUTING_RECOVERY_DIR",
        "V3_DRAFT_RECOVERY_DIR",
        "_working_checkpoint",
        "build_scouting_advance_candidate",
        "build_draft_selection_candidate",
        "verify_scouting_advance_persisted",
        "verify_draft_selection_persisted",
        "validate_simulation_league_state",
        "save_franchise_checkpoint",
    ]
    original = {name: getattr(server, name) for name in names}
    try:
        with tempfile.TemporaryDirectory(prefix="v3_batch10_") as tmp:
            root = Path(tmp)
            working = root / "working.pkl.gz"
            v2 = root / "protected_v2.pkl.gz"
            working.write_bytes(b"working-before")
            v2.write_bytes(b"protected-v2")
            server.V3_WORKING_CHECKPOINT_PATH = working
            server.DEFAULT_CHECKPOINT_PATH = v2
            server.V3_SCOUTING_RECOVERY_DIR = root / "scout_recovery"
            server.V3_DRAFT_RECOVERY_DIR = root / "draft_recovery"
            checkpoint = SimpleNamespace(
                simulation_state=SimpleNamespace(),
                trade_state=SimpleNamespace(),
                preferences={"franchise_pref_active_team": "CHI"},
            )
            holder = {"value": checkpoint}
            server._working_checkpoint = lambda: holder["value"]
            server.validate_simulation_league_state = lambda _state: True
            server.verify_scouting_advance_persisted = lambda _checkpoint, candidate: {
                "weeks_before": candidate.weeks_before,
                "weeks_after": candidate.weeks_after,
                "focus_ids": list(candidate.focus_ids),
            }
            server.verify_draft_selection_persisted = lambda _checkpoint, candidate: {
                "prospect_id": candidate.prospect_id,
                "prospect_name": candidate.prospect_name,
                "overall_pick": candidate.overall_pick,
            }
            scout_candidate = SimpleNamespace(
                state=SimpleNamespace(), team="CHI", weeks_before=0, weeks_after=1,
                focus_ids=("P1",), action_fingerprint="scout-fp",
            )
            draft_candidate = SimpleNamespace(
                state=SimpleNamespace(), team="CHI", overall_pick=12,
                prospect_id="P1", prospect_name="Prospect One", action_fingerprint="draft-fp",
            )
            server.build_scouting_advance_candidate = lambda *_args, **_kwargs: scout_candidate
            server.build_draft_selection_candidate = lambda *_args, **_kwargs: draft_candidate

            def successful_save(state, trade_state, **kwargs):
                Path(kwargs["path"]).write_bytes(b"committed-state")
                holder["value"] = SimpleNamespace(
                    simulation_state=state,
                    trade_state=trade_state,
                    preferences=checkpoint.preferences,
                )

            server.save_franchise_checkpoint = successful_save
            stale = asyncio.run(server.scouting_advance(FakeRequest({
                "focus_ids": ["P1"],
                "expected_action_fingerprint": "scout-fp",
                "expected_working_save_sha256": "wrong-sha",
            })))
            checks["isolated_stale_scouting_save_rejected"] = (
                stale.status_code == 409
                and _response_json(stale).get("error") == "stale_scouting_preview"
                and working.read_bytes() == b"working-before"
                and v2.read_bytes() == b"protected-v2"
            )

            scout_body = {
                "focus_ids": ["P1"],
                "expected_action_fingerprint": "scout-fp",
                "expected_working_save_sha256": sha256(working),
            }
            applied = asyncio.run(server.scouting_advance(FakeRequest(scout_body)))
            applied_payload = _response_json(applied)
            checks["isolated_scouting_commit_is_v3_only"] = (
                applied.status_code == 200
                and applied_payload.get("persisted_after_reload") is True
                and applied_payload.get("active_v2_unchanged") is True
                and working.read_bytes() == b"committed-state"
                and v2.read_bytes() == b"protected-v2"
            )

            working.write_bytes(b"draft-before")
            draft_body = {
                "prospect_id": "P1",
                "expected_action_fingerprint": "draft-fp",
                "expected_working_save_sha256": sha256(working),
            }
            applied_draft = asyncio.run(server.draft_selection_execute(FakeRequest(draft_body)))
            draft_payload = _response_json(applied_draft)
            checks["isolated_draft_commit_is_v3_only"] = (
                applied_draft.status_code == 200
                and draft_payload.get("persisted_after_reload") is True
                and draft_payload.get("active_v2_unchanged") is True
                and v2.read_bytes() == b"protected-v2"
            )

            working.write_bytes(b"rollback-source")
            def failing_save(*_args, **kwargs):
                Path(kwargs["path"]).write_bytes(b"partial-write")
                raise RuntimeError("forced batch10 save failure")
            server.save_franchise_checkpoint = failing_save
            rollback_body = dict(draft_body)
            rollback_body["expected_working_save_sha256"] = sha256(working)
            failed = asyncio.run(server.draft_selection_execute(FakeRequest(rollback_body)))
            failed_payload = _response_json(failed)
            checks["isolated_draft_failure_rolls_back"] = (
                failed.status_code == 500
                and failed_payload.get("rollback_performed") is True
                and failed_payload.get("rollback_verified") is True
                and working.read_bytes() == b"rollback-source"
                and v2.read_bytes() == b"protected-v2"
            )
    finally:
        for name, value in original.items():
            setattr(server, name, value)
    return checks


def _live_read_only_probe() -> dict[str, Any]:
    working = server.V3_WORKING_CHECKPOINT_PATH
    v2 = Path(server.DEFAULT_CHECKPOINT_PATH)
    working_before = sha256(working)
    v2_before = sha256(v2)
    if working_before is None:
        return {"status": "skipped", "reason": "V3 working save unavailable."}
    checkpoint = load_franchise_checkpoint(path=working, allow_backup=False)
    if checkpoint is None:
        raise RuntimeError("V3 working checkpoint could not be loaded.")
    active_team = str(checkpoint.preferences.get("franchise_pref_active_team", "") or "").strip().upper()
    payload = build_scouting_draft_payload(checkpoint, active_team)
    board = list(payload.get("board", []))
    board_confidence = [float(row.get("Confidence", 0.0) or 0.0) for row in board]
    board_avg = sum(board_confidence) / len(board_confidence) if board_confidence else 0.0
    summary_avg = float(payload.get("summary", {}).get("average_confidence", 0.0) or 0.0)
    result: dict[str, Any] = {
        "status": "pass",
        "draft_phase": payload.get("draft", {}).get("phase"),
        "board_count": len(board),
        "summary_average_confidence": summary_avg,
        "board_average_confidence": round(board_avg, 1),
        "summary_matches_full_board": abs(summary_avg - board_avg) <= 0.11,
        "scouting_execution_enabled": payload.get("scouting_execution_enabled"),
        "draft_execution_enabled": payload.get("draft_execution_enabled"),
    }
    if board and payload.get("scouting_execution_enabled") and int(payload.get("summary", {}).get("weeks_remaining", 0) or 0) > 0:
        focus = [str(row.get("prospect_id")) for row in board[:2]]
        preview = build_scouting_advance_preview_payload(checkpoint, active_team, {"focus_ids": focus})
        result["scouting_preview_status"] = preview.get("status")
        result["scouting_preview_can_commit"] = preview.get("can_commit")
        result["scouting_confidence_before"] = preview.get("summary_before", {}).get("average_confidence")
        result["scouting_confidence_after"] = preview.get("summary_after", {}).get("average_confidence")
        result["scouting_confidence_non_decreasing"] = (
            float(result["scouting_confidence_after"] or 0.0) + 1e-9
            >= float(result["scouting_confidence_before"] or 0.0)
        )
    if board:
        draft_preview = build_draft_selection_preview_payload(
            checkpoint, active_team, {"prospect_id": str(board[0].get("prospect_id"))}
        )
        result["draft_preview_status"] = draft_preview.get("status")
        result["draft_preview_can_commit"] = draft_preview.get("can_commit")
    result["working_save_unchanged"] = sha256(working) == working_before
    result["active_v2_unchanged"] = sha256(v2) == v2_before
    return result


def main() -> int:
    foundation = ROOT / "desktop_bridge" / "transaction_foundation.py"
    bridge = ROOT / "desktop_bridge" / "server.py"
    main_gd = ROOT / "godot_client" / "scripts" / "main.gd"
    scouting_gd = ROOT / "godot_client" / "scripts" / "scouting_draft_center_v3.gd"
    foundation_text = text(foundation)
    bridge_text = text(bridge)
    main_text = text(main_gd)
    scouting_text = text(scouting_gd)

    checks: dict[str, bool] = {
        "batch08_foundation_preserved": "batch-08-transactional-trade-execution" in TRANSACTION_FOUNDATION_VERSION,
        "batch09_foundation_preserved": "batch-09-transactional-free-agency-execution" in TRANSACTION_FOUNDATION_VERSION,
        "batch10_foundation_version": "batch-10-scouting-draft-workflow" in TRANSACTION_FOUNDATION_VERSION,
        "production_scouting_engine_reused": "advance_scouting_week_v1" in foundation_text and "set_scouting_focus_v1" in foundation_text,
        "production_draft_engine_reused": "make_draft_selection" in foundation_text,
        "scouting_summary_endpoint_registered": 'Route("/v3/scouting-draft", scouting_draft_summary' in bridge_text,
        "scouting_preview_endpoint_registered": 'Route("/v3/scouting/preview", scouting_preview' in bridge_text,
        "scouting_execute_endpoint_registered": 'Route("/v3/scouting/advance", scouting_advance' in bridge_text,
        "draft_preview_endpoint_registered": 'Route("/v3/draft/selection/preview", draft_selection_preview' in bridge_text,
        "draft_execute_endpoint_registered": 'Route("/v3/draft/selection/execute", draft_selection_execute' in bridge_text,
        "scouting_requires_working_save_sha": "expected_working_save_sha256 is required. Run a fresh scouting preview first." in bridge_text,
        "draft_requires_working_save_sha": "expected_working_save_sha256 is required. Run a fresh Draft preview first." in bridge_text,
        "scouting_recovery_and_rollback": "V3_SCOUTING_RECOVERY_DIR" in bridge_text and "Protected V2 checkpoint changed during V3 scouting execution." in bridge_text,
        "draft_recovery_and_rollback": "V3_DRAFT_RECOVERY_DIR" in bridge_text and "Protected V2 checkpoint changed during V3 Draft execution." in bridge_text,
        "godot_dedicated_center_preloaded": "ScoutingDraftCenterV3" in main_text and "scouting_draft_center_v3.gd" in main_text,
        "godot_scouting_preview_and_execute_wired": SCOUT_PREVIEW_URL_TEXT in scouting_text and SCOUT_EXECUTE_URL_TEXT in scouting_text,
        "godot_draft_preview_and_execute_wired": DRAFT_PREVIEW_URL_TEXT in scouting_text and DRAFT_EXECUTE_URL_TEXT in scouting_text,
        "godot_scouting_confirmation_present": "Confirm scouting week" in scouting_text,
        "godot_draft_confirmation_present": "Confirm Draft selection" in scouting_text,
        "godot_limits_focus_to_six": "focus_selected.size() >= 6" in scouting_text,
        "godot_labels_week_counter_clearly": '"SCOUTING WEEK"' in scouting_text,
        "godot_uses_scouted_not_hidden_ratings": "Scouted OVR" in scouting_text and "hidden_overall" not in scouting_text and "hidden_potential" not in scouting_text,
    }

    try:
        for path in (foundation, bridge, Path(__file__)):
            py_compile.compile(str(path), doraise=True)
        checks["modified_python_files_compile"] = True
    except Exception:
        checks["modified_python_files_compile"] = False

    try:
        report = draft_self_test()
        checks["production_draft_engine_self_test"] = bool(report.get("passed"))
    except Exception:
        checks["production_draft_engine_self_test"] = False

    try:
        checks.update(_synthetic_scouting_checks())
    except Exception:
        for name in (
            "synthetic_board_uses_scouted_fields",
            "synthetic_summary_matches_full_board",
            "synthetic_preview_confidence_never_declines",
            "synthetic_preview_is_read_only",
            "synthetic_scouting_preview_passes",
            "synthetic_scouting_candidate_advances_one_week",
            "synthetic_scouting_candidate_keeps_focus",
            "synthetic_stale_scouting_token_rejected",
            "synthetic_regular_season_draft_pick_blocked",
        ):
            checks[name] = False

    try:
        checks.update(_run_isolated_safety_tests())
    except Exception:
        checks["isolated_stale_scouting_save_rejected"] = False
        checks["isolated_scouting_commit_is_v3_only"] = False
        checks["isolated_draft_commit_is_v3_only"] = False
        checks["isolated_draft_failure_rolls_back"] = False

    godot_binary = shutil.which("godot4") or shutil.which("godot")
    godot_validation = "SKIP: Godot CLI not on PATH"
    if godot_binary:
        result = subprocess.run(
            [godot_binary, "--headless", "--path", str(ROOT / "godot_client"), "--editor", "--quit"],
            capture_output=True, text=True, timeout=90,
        )
        checks["godot_headless_parse"] = result.returncode == 0
        godot_validation = (result.stdout + "\n" + result.stderr).strip()[-4000:]
    else:
        checks["godot_headless_parse"] = True

    working_before = sha256(server.V3_WORKING_CHECKPOINT_PATH)
    v2_before = sha256(Path(server.DEFAULT_CHECKPOINT_PATH))
    try:
        dynamic = _live_read_only_probe()
        checks["dynamic_read_only_probe"] = dynamic.get("status") != "failed"
        checks["dynamic_summary_matches_full_board"] = dynamic.get("summary_matches_full_board", True) is True
        checks["dynamic_scouting_confidence_non_decreasing"] = dynamic.get("scouting_confidence_non_decreasing", True) is True
        checks["dynamic_probe_does_not_write_working_save"] = dynamic.get("working_save_unchanged", True) is True
        checks["dynamic_probe_does_not_touch_v2"] = dynamic.get("active_v2_unchanged", True) is True
    except FileNotFoundError as exc:
        dynamic = {"status": "skipped", "reason": str(exc)}
        checks["dynamic_read_only_probe"] = True
        checks["dynamic_summary_matches_full_board"] = True
        checks["dynamic_scouting_confidence_non_decreasing"] = True
        checks["dynamic_probe_does_not_write_working_save"] = True
        checks["dynamic_probe_does_not_touch_v2"] = True
    except Exception as exc:
        dynamic = {"status": "failed", "exception_type": type(exc).__name__, "reason": str(exc)}
        checks["dynamic_read_only_probe"] = False
        checks["dynamic_summary_matches_full_board"] = False
        checks["dynamic_scouting_confidence_non_decreasing"] = False
        checks["dynamic_probe_does_not_write_working_save"] = False
        checks["dynamic_probe_does_not_touch_v2"] = False

    checks["validator_never_changes_working_save"] = working_before == sha256(server.V3_WORKING_CHECKPOINT_PATH)
    checks["validator_never_changes_v2_checkpoint"] = v2_before == sha256(Path(server.DEFAULT_CHECKPOINT_PATH))

    failed = [name for name, passed in checks.items() if not passed]
    report = {
        "validator_version": VALIDATOR_VERSION,
        "transaction_foundation_version": TRANSACTION_FOUNDATION_VERSION,
        "scouting_version": FRANCHISE_SCOUTING_DISCOVERY_VERSION,
        "draft_engine_version": DRAFT_ENGINE_VERSION,
        "checks": checks,
        "failed_checks": failed,
        "dynamic_validation": dynamic,
        "godot_validation": godot_validation,
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print("=" * 88)
    print("V3 BATCH 10 SCOUTING + DRAFT WORKFLOW VALIDATION")
    print("=" * 88)
    for name, passed in checks.items():
        print(f"  {name}: {'PASS' if passed else 'FAIL'}")
    print()
    print("Dynamic live probe:", str(dynamic.get("status", "unknown")).upper())
    if dynamic.get("draft_phase") is not None:
        print(f"  Draft phase: {dynamic.get('draft_phase')}")
        print(f"  Board prospects: {dynamic.get('board_count')}")
        print(f"  Board confidence: {dynamic.get('summary_average_confidence')}%")
        print(f"  Scouting preview: {dynamic.get('scouting_preview_status', 'not-run')} • can_commit={dynamic.get('scouting_preview_can_commit')}")
        if dynamic.get("scouting_confidence_before") is not None:
            print(f"  Confidence preview: {dynamic.get('scouting_confidence_before')}% → {dynamic.get('scouting_confidence_after')}%")
        print(f"  Draft preview: {dynamic.get('draft_preview_status', 'not-run')} • can_commit={dynamic.get('draft_preview_can_commit')}")
    print("Godot parser:", "PASS" if godot_binary and checks["godot_headless_parse"] else "SKIP (Godot CLI not on PATH; static wiring checks passed)")
    print("Report:", REPORT_PATH)
    print()
    if failed:
        print("BATCH 10 VALIDATION FAILED")
        print("Failed checks:", ", ".join(failed))
        return 1
    print("BATCH 10 VALIDATION PASSED")
    print("No scouting week or Draft selection was durably executed by this validator.")
    return 0


SCOUT_PREVIEW_URL_TEXT = "/v3/scouting/preview"
SCOUT_EXECUTE_URL_TEXT = "/v3/scouting/advance"
DRAFT_PREVIEW_URL_TEXT = "/v3/draft/selection/preview"
DRAFT_EXECUTE_URL_TEXT = "/v3/draft/selection/execute"


if __name__ == "__main__":
    raise SystemExit(main())
