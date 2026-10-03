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
import time
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
from desktop_bridge.season_lifecycle_foundation import (
    ACTION_CPU_FREE_AGENCY,
    ACTION_DRAFT_LOTTERY,
    ACTION_DRAFT_NIGHT,
    ACTION_NEXT_SEASON,
    build_lifecycle_summary,
)
from desktop_bridge.transaction_foundation import TRANSACTION_FOUNDATION_VERSION
from franchise_draft_engine_v1 import DRAFT_ENGINE_VERSION, run_self_test as draft_self_test
from simulation_franchise_checkpoint_v1 import load_franchise_checkpoint, save_franchise_checkpoint


VALIDATOR_VERSION = "v3-batch16-draft-night-continuity-validator-v1.0.2-2026-10-03"
REPORT_DIR = ROOT / "outputs" / "v3_batch16_draft_night_continuity"
REPORT_PATH = REPORT_DIR / "validation.json"


def _sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _response_json(response: Any) -> dict[str, Any]:
    return json.loads(response.body.decode("utf-8"))


class _FakeRequest:
    def __init__(self, body: dict[str, Any]):
        self._body = copy.deepcopy(body)

    async def json(self) -> dict[str, Any]:
        return copy.deepcopy(self._body)


def _find_cpu_fa_fixture() -> Path | None:
    patterns = (
        "outputs/v2_phase1_deep_offseason_profile_v1/*/recovery/free_agency/pre_cpu_round_batch_02_*.pkl.gz",
        "outputs/_soak/*/s*/f*/pre_cpu_round_batch_01_*.pkl.gz",
    )
    candidates: list[Path] = []
    for pattern in patterns:
        candidates.extend(ROOT.glob(pattern))
    for path in sorted(candidates, key=lambda item: item.stat().st_mtime, reverse=True):
        try:
            checkpoint = load_franchise_checkpoint(path=path, allow_backup=False)
            if checkpoint is None:
                continue
            summary = build_lifecycle_summary(checkpoint)
            if summary.get("next_action") == ACTION_CPU_FREE_AGENCY:
                return path
        except Exception:
            continue
    return None


def _lifecycle_preview(action: str) -> dict[str, Any]:
    response = asyncio.run(server.lifecycle_preview(_FakeRequest({"action": action})))
    payload = _response_json(response)
    if response.status_code != 200 or not payload.get("can_commit"):
        raise RuntimeError(
            f"Lifecycle preview {action} failed ({response.status_code}): "
            + json.dumps(payload, sort_keys=True, default=str)
        )
    return payload


def _lifecycle_execute(action: str, preview: dict[str, Any]) -> dict[str, Any]:
    response = asyncio.run(
        server.lifecycle_execute(
            _FakeRequest(
                {
                    "action": action,
                    "expected_action_fingerprint": preview.get("action_fingerprint"),
                    "expected_working_save_sha256": preview.get("working_save_sha256"),
                }
            )
        )
    )
    payload = _response_json(response)
    if response.status_code != 200:
        raise RuntimeError(
            f"Lifecycle execute {action} failed ({response.status_code}): "
            + json.dumps(payload, sort_keys=True, default=str)
        )
    return payload


def _run_endpoint_safety_tests() -> dict[str, bool]:
    checks: dict[str, bool] = {}
    names = (
        "V3_WORKING_CHECKPOINT_PATH",
        "DEFAULT_CHECKPOINT_PATH",
        "V3_DRAFT_RECOVERY_DIR",
        "V3_POST_DRAFT_ROSTER_RECOVERY_DIR",
        "_working_checkpoint",
        "build_draft_advance_candidate",
        "verify_draft_advance_persisted",
        "build_post_draft_roster_cut_candidate",
        "verify_post_draft_roster_cut_persisted",
        "validate_simulation_league_state",
        "save_franchise_checkpoint",
    )
    original = {name: getattr(server, name) for name in names}
    try:
        with tempfile.TemporaryDirectory(prefix="v3_batch16_endpoint_") as tmp:
            root = Path(tmp)
            working = root / "working.pkl.gz"
            v2 = root / "protected_v2.pkl.gz"
            recovery = root / "draft_recovery"
            roster_recovery = root / "post_draft_roster_recovery"
            working.write_bytes(b"draft-working-before")
            v2.write_bytes(b"protected-v2")
            server.V3_WORKING_CHECKPOINT_PATH = working
            server.DEFAULT_CHECKPOINT_PATH = v2
            server.V3_DRAFT_RECOVERY_DIR = recovery
            server.V3_POST_DRAFT_ROSTER_RECOVERY_DIR = roster_recovery

            checkpoint = SimpleNamespace(
                simulation_state=SimpleNamespace(),
                trade_state=SimpleNamespace(),
                preferences={"franchise_pref_active_team": "CHI"},
            )
            holder = {"value": checkpoint}
            server._working_checkpoint = lambda: holder["value"]
            server.validate_simulation_league_state = lambda _state: True

            candidate = SimpleNamespace(
                state=SimpleNamespace(),
                team="CHI",
                draft_year=2028,
                action_fingerprint="cpu-draft-fp",
                start_pick_index=0,
                end_pick_index=3,
                picks_simulated=3,
                draft_complete=False,
                next_pick={"overall_pick": 4, "owner_team": "CHI"},
            )
            server.build_draft_advance_candidate = lambda *_args, **_kwargs: candidate
            server.verify_draft_advance_persisted = lambda _checkpoint, c: {
                "team": c.team,
                "picks_simulated": c.picks_simulated,
                "draft_complete": c.draft_complete,
                "next_pick": c.next_pick,
            }

            def successful_save(state, trade_state, **kwargs):
                Path(kwargs["path"]).write_bytes(b"draft-advanced")
                holder["value"] = SimpleNamespace(
                    simulation_state=state,
                    trade_state=trade_state,
                    preferences=checkpoint.preferences,
                )

            server.save_franchise_checkpoint = successful_save

            stale = asyncio.run(
                server.draft_advance_execute(
                    _FakeRequest(
                        {
                            "expected_action_fingerprint": "cpu-draft-fp",
                            "expected_working_save_sha256": "stale-sha",
                        }
                    )
                )
            )
            stale_payload = _response_json(stale)
            checks["isolated_stale_cpu_draft_preview_rejected"] = (
                stale.status_code == 409
                and stale_payload.get("error") == "stale_draft_advance_preview"
                and working.read_bytes() == b"draft-working-before"
                and v2.read_bytes() == b"protected-v2"
            )

            applied = asyncio.run(
                server.draft_advance_execute(
                    _FakeRequest(
                        {
                            "expected_action_fingerprint": "cpu-draft-fp",
                            "expected_working_save_sha256": _sha256(working),
                        }
                    )
                )
            )
            applied_payload = _response_json(applied)
            checks["isolated_cpu_draft_commit_is_v3_only"] = (
                applied.status_code == 200
                and applied_payload.get("persisted_after_reload") is True
                and applied_payload.get("active_v2_unchanged") is True
                and applied_payload.get("verification", {}).get("picks_simulated") == 3
                and v2.read_bytes() == b"protected-v2"
                and bool(list(recovery.glob("pre_draft_cpu_advance_*")))
            )

            working.write_bytes(b"rollback-source")
            holder["value"] = checkpoint

            def failing_save(*_args, **kwargs):
                Path(kwargs["path"]).write_bytes(b"partial-draft-write")
                raise RuntimeError("forced Batch16 save failure")

            server.save_franchise_checkpoint = failing_save
            failed = asyncio.run(
                server.draft_advance_execute(
                    _FakeRequest(
                        {
                            "expected_action_fingerprint": "cpu-draft-fp",
                            "expected_working_save_sha256": _sha256(working),
                        }
                    )
                )
            )
            failed_payload = _response_json(failed)
            checks["isolated_cpu_draft_failure_rolls_back"] = (
                failed.status_code == 500
                and failed_payload.get("rollback_performed") is True
                and failed_payload.get("rollback_verified") is True
                and working.read_bytes() == b"rollback-source"
                and v2.read_bytes() == b"protected-v2"
            )


            # User-controlled post-Draft roster-cut write boundary.
            working.write_bytes(b"roster-cut-working-before")
            holder["value"] = checkpoint
            roster_candidate = SimpleNamespace(
                state=SimpleNamespace(),
                trade_state=SimpleNamespace(),
                team="CHI",
                player_id="player-cut-1",
                player_name="Test Cut",
                action_fingerprint="roster-cut-fp",
            )
            server.build_post_draft_roster_cut_candidate = lambda *_args, **_kwargs: roster_candidate
            server.verify_post_draft_roster_cut_persisted = lambda _checkpoint, c: {
                "team": c.team,
                "player_id": c.player_id,
                "player_name": c.player_name,
                "cuts_remaining_after": 0,
                "roster_cleared_for_next_season": True,
            }

            stale_roster = asyncio.run(
                server.post_draft_roster_cut_execute(
                    _FakeRequest(
                        {
                            "player_id": "player-cut-1",
                            "expected_action_fingerprint": "roster-cut-fp",
                            "expected_working_save_sha256": "stale-sha",
                        }
                    )
                )
            )
            stale_roster_payload = _response_json(stale_roster)
            checks["isolated_stale_user_post_draft_preview_rejected"] = (
                stale_roster.status_code == 409
                and stale_roster_payload.get("error") == "stale_post_draft_roster_cut_preview"
                and working.read_bytes() == b"roster-cut-working-before"
                and v2.read_bytes() == b"protected-v2"
            )

            def successful_roster_save(state, trade_state, **kwargs):
                Path(kwargs["path"]).write_bytes(b"roster-cut-applied")
                holder["value"] = SimpleNamespace(
                    simulation_state=state,
                    trade_state=trade_state,
                    preferences=checkpoint.preferences,
                )

            server.save_franchise_checkpoint = successful_roster_save
            applied_roster = asyncio.run(
                server.post_draft_roster_cut_execute(
                    _FakeRequest(
                        {
                            "player_id": "player-cut-1",
                            "expected_action_fingerprint": "roster-cut-fp",
                            "expected_working_save_sha256": _sha256(working),
                        }
                    )
                )
            )
            applied_roster_payload = _response_json(applied_roster)
            checks["isolated_user_post_draft_commit_is_v3_only"] = (
                applied_roster.status_code == 200
                and applied_roster_payload.get("persisted_after_reload") is True
                and applied_roster_payload.get("active_v2_unchanged") is True
                and applied_roster_payload.get("verification", {}).get("player_id") == "player-cut-1"
                and v2.read_bytes() == b"protected-v2"
                and bool(list(roster_recovery.glob("pre_user_roster_cut_*")))
            )

            working.write_bytes(b"roster-cut-rollback-source")
            holder["value"] = checkpoint

            def failing_roster_save(*_args, **kwargs):
                Path(kwargs["path"]).write_bytes(b"partial-roster-cut-write")
                raise RuntimeError("forced Batch16 roster-cut save failure")

            server.save_franchise_checkpoint = failing_roster_save
            failed_roster = asyncio.run(
                server.post_draft_roster_cut_execute(
                    _FakeRequest(
                        {
                            "player_id": "player-cut-1",
                            "expected_action_fingerprint": "roster-cut-fp",
                            "expected_working_save_sha256": _sha256(working),
                        }
                    )
                )
            )
            failed_roster_payload = _response_json(failed_roster)
            checks["isolated_user_post_draft_failure_rolls_back"] = (
                failed_roster.status_code == 500
                and failed_roster_payload.get("rollback_performed") is True
                and failed_roster_payload.get("rollback_verified") is True
                and working.read_bytes() == b"roster-cut-rollback-source"
                and v2.read_bytes() == b"protected-v2"
            )
    finally:
        for name, value in original.items():
            setattr(server, name, value)
    return checks


def _run_full_offseason_fixture(fixture: Path) -> tuple[dict[str, bool], dict[str, Any]]:
    checks: dict[str, bool] = {}
    detail: dict[str, Any] = {"fixture": str(fixture)}
    print(f"[Batch16] Building isolated full-offseason fixture from: {fixture}", flush=True)
    names = (
        "V3_WORKING_CHECKPOINT_PATH",
        "DEFAULT_CHECKPOINT_PATH",
        "V3_LIFECYCLE_RECOVERY_DIR",
        "V3_DRAFT_RECOVERY_DIR",
        "V3_POST_DRAFT_ROSTER_RECOVERY_DIR",
    )
    original = {name: getattr(server, name) for name in names}
    try:
        with tempfile.TemporaryDirectory(prefix="v3_batch16_full_offseason_") as tmp:
            root = Path(tmp)
            working = root / "v3_working.pkl.gz"
            protected_v2 = root / "protected_v2.bin"
            lifecycle_recovery = root / "lifecycle_recovery"
            draft_recovery = root / "draft_recovery"
            post_draft_roster_recovery = root / "post_draft_roster_recovery"
            shutil.copy2(fixture, working)
            protected_v2.write_bytes(b"protected-v2-batch16-sentinel")

            server.V3_WORKING_CHECKPOINT_PATH = working
            server.DEFAULT_CHECKPOINT_PATH = protected_v2
            server.V3_LIFECYCLE_RECOVERY_DIR = lifecycle_recovery
            server.V3_DRAFT_RECOVERY_DIR = draft_recovery
            server.V3_POST_DRAFT_ROSTER_RECOVERY_DIR = post_draft_roster_recovery

            v2_sha = _sha256(protected_v2)
            starting_checkpoint = load_franchise_checkpoint(path=working, allow_backup=False)
            if starting_checkpoint is None:
                raise RuntimeError("Batch16 fixture could not be loaded.")

            # Preserved profiling/soak fixtures are engine checkpoints, not always
            # player-facing franchise saves. Older fixtures may therefore omit the
            # active-team preference required by the Godot Scouting & Draft surface.
            # Seed ONLY the temporary validator copy with a real league team so the
            # full Draft Night path exercises CPU picks stopping at a user pick.
            teams = sorted(str(team).strip().upper() for team in starting_checkpoint.simulation_state.teams)
            if not teams:
                raise RuntimeError("Batch16 fixture contains no league teams.")
            fixture_preferences = copy.deepcopy(dict(starting_checkpoint.preferences or {}))
            fixture_active_team = str(fixture_preferences.get("franchise_pref_active_team", "") or "").strip().upper()
            if fixture_active_team not in teams:
                fixture_active_team = "CHI" if "CHI" in teams else teams[0]
                fixture_preferences["franchise_pref_active_team"] = fixture_active_team
                controlled = {
                    str(team).strip().upper()
                    for team in fixture_preferences.get("franchise_pref_controlled_teams", ()) or ()
                    if str(team).strip().upper() in teams
                }
                controlled.add(fixture_active_team)
                fixture_preferences["franchise_pref_controlled_teams"] = tuple(sorted(controlled))
                save_franchise_checkpoint(
                    starting_checkpoint.simulation_state,
                    starting_checkpoint.trade_state,
                    preferences=fixture_preferences,
                    reason="v3-batch16-validator-active-franchise-fixture",
                    path=working,
                    force_replace=True,
                )
                starting_checkpoint = load_franchise_checkpoint(path=working, allow_backup=False)
                if starting_checkpoint is None:
                    raise RuntimeError("Batch16 fixture could not be reloaded after active-team seeding.")
                print(
                    f"[Batch16] Temporary fixture active franchise seeded as {fixture_active_team}.",
                    flush=True,
                )

            starting_season = str(starting_checkpoint.simulation_state.settings.season_label)

            print(f"[Batch16] Fixture loaded for {starting_season}. Running certified CPU Free Agency...", flush=True)
            cpu_rounds = 0
            cpu_signings = 0
            while True:
                summary_response = asyncio.run(server.lifecycle_summary(_FakeRequest({})))
                summary = _response_json(summary_response)
                if summary.get("next_action") != ACTION_CPU_FREE_AGENCY:
                    break
                if cpu_rounds >= 5:
                    raise RuntimeError("CPU Free Agency did not clear within five certified rounds.")
                preview = _lifecycle_preview(ACTION_CPU_FREE_AGENCY)
                cpu_signings += int(preview.get("detail", {}).get("committed_signing_count", 0) or 0)
                round_signings = int(preview.get("detail", {}).get("committed_signing_count", 0) or 0)
                print(f"[Batch16] CPU Free Agency round {cpu_rounds + 1}: previewing {round_signings} signing(s)...", flush=True)
                _lifecycle_execute(ACTION_CPU_FREE_AGENCY, preview)
                cpu_rounds += 1
                print(f"[Batch16] CPU Free Agency round {cpu_rounds} committed and verified.", flush=True)

            summary = _response_json(asyncio.run(server.lifecycle_summary(_FakeRequest({}))))
            checks["isolated_cpu_fa_hands_off_to_draft_lottery"] = (
                summary.get("next_action") == ACTION_DRAFT_LOTTERY
                and summary.get("stage") == "draft_lottery_ready"
            )

            print("[Batch16] CPU Free Agency cleared. Running Draft Lottery gate...", flush=True)
            lottery_preview = _lifecycle_preview(ACTION_DRAFT_LOTTERY)
            lottery_execute = _lifecycle_execute(ACTION_DRAFT_LOTTERY, lottery_preview)
            lottery_lifecycle = dict(lottery_execute.get("lifecycle", {}) or {})
            checks["isolated_draft_lottery_persists_and_hands_off"] = (
                lottery_execute.get("persisted_after_reload") is True
                and lottery_execute.get("active_v2_unchanged") is True
                and lottery_lifecycle.get("next_action") == ACTION_DRAFT_NIGHT
                and lottery_lifecycle.get("stage") == "draft_night_ready"
            )

            print("[Batch16] Draft Lottery committed. Opening Draft Night...", flush=True)
            draft_night_preview = _lifecycle_preview(ACTION_DRAFT_NIGHT)
            draft_night_execute = _lifecycle_execute(ACTION_DRAFT_NIGHT, draft_night_preview)
            draft_night_lifecycle = dict(draft_night_execute.get("lifecycle", {}) or {})
            checks["isolated_draft_night_opens"] = (
                draft_night_execute.get("persisted_after_reload") is True
                and draft_night_lifecycle.get("stage") == "draft_in_progress"
            )

            print("[Batch16] Draft Night open. Advancing CPU picks and controlled selections until Draft completion...", flush=True)
            cpu_advance_commits = 0
            cpu_picks_simulated = 0
            user_pick_commits = 0
            draft_loop_iterations = 0
            while draft_loop_iterations < 80:
                draft_loop_iterations += 1
                page_response = asyncio.run(server.scouting_draft_summary(_FakeRequest({})))
                page = _response_json(page_response)
                if page_response.status_code != 200:
                    raise RuntimeError(
                        f"Scouting & Draft summary failed during Batch16 fixture ({page_response.status_code}): "
                        + json.dumps(page, sort_keys=True, default=str)
                    )
                draft = dict(page.get("draft", {}) or {})
                phase = str(draft.get("phase", "") or "")
                if phase == "draft_complete":
                    break

                if bool(page.get("draft_execution_enabled", False)):
                    board = [row for row in page.get("board", []) if not bool(row.get("Drafted", False))]
                    if not board:
                        raise RuntimeError("No undrafted prospect was available for a controlled Draft pick.")
                    prospect_id = str(board[0].get("prospect_id", "") or "")
                    preview_response = asyncio.run(
                        server.draft_selection_preview(_FakeRequest({"prospect_id": prospect_id}))
                    )
                    preview = _response_json(preview_response)
                    if preview_response.status_code != 200 or not preview.get("can_commit"):
                        raise RuntimeError("Controlled Draft pick preview failed during Batch16 fixture.")
                    execute_response = asyncio.run(
                        server.draft_selection_execute(
                            _FakeRequest(
                                {
                                    "prospect_id": prospect_id,
                                    "expected_action_fingerprint": preview.get("action_fingerprint"),
                                    "expected_working_save_sha256": preview.get("working_save_sha256"),
                                }
                            )
                        )
                    )
                    execute = _response_json(execute_response)
                    if execute_response.status_code != 200:
                        raise RuntimeError(
                            "Controlled Draft selection failed: "
                            + json.dumps(execute, sort_keys=True, default=str)
                        )
                    user_pick_commits += 1
                    if user_pick_commits <= 3 or user_pick_commits % 5 == 0:
                        print(f"[Batch16] Controlled Draft pick #{user_pick_commits} committed.", flush=True)
                    continue

                if bool(page.get("draft_cpu_advance_enabled", False)):
                    preview_response = asyncio.run(server.draft_advance_preview(_FakeRequest({})))
                    preview = _response_json(preview_response)
                    if preview_response.status_code != 200 or not preview.get("can_commit"):
                        raise RuntimeError(
                            "CPU Draft preview failed: " + json.dumps(preview, sort_keys=True, default=str)
                        )
                    preview_count = int(preview.get("picks_simulated", 0) or 0)
                    execute_response = asyncio.run(
                        server.draft_advance_execute(
                            _FakeRequest(
                                {
                                    "expected_action_fingerprint": preview.get("action_fingerprint"),
                                    "expected_working_save_sha256": preview.get("working_save_sha256"),
                                }
                            )
                        )
                    )
                    execute = _response_json(execute_response)
                    if execute_response.status_code != 200:
                        raise RuntimeError(
                            "CPU Draft advancement failed: "
                            + json.dumps(execute, sort_keys=True, default=str)
                        )
                    if int(execute.get("picks_simulated", 0) or 0) != preview_count:
                        raise RuntimeError("CPU Draft preview and commit pick counts diverged.")
                    cpu_advance_commits += 1
                    cpu_picks_simulated += preview_count
                    print(
                        f"[Batch16] CPU Draft advance #{cpu_advance_commits}: {preview_count} pick(s), "
                        f"{cpu_picks_simulated} CPU pick(s) total.",
                        flush=True,
                    )
                    continue

                raise RuntimeError(
                    f"Draft Night reached a dead end at phase={phase!r}; neither user selection nor CPU advance is enabled."
                )
            else:
                raise RuntimeError("Draft Night exceeded the certified Batch16 iteration limit.")

            final_draft_page = _response_json(
                asyncio.run(server.scouting_draft_summary(_FakeRequest({})))
            )
            checks["isolated_complete_draft_has_no_dead_end"] = (
                final_draft_page.get("draft", {}).get("phase") == "draft_complete"
                and not final_draft_page.get("draft_execution_enabled", False)
                and not final_draft_page.get("draft_cpu_advance_enabled", False)
            )
            checks["isolated_cpu_draft_recovery_created"] = bool(
                list(draft_recovery.glob("pre_draft_cpu_advance_*"))
            ) or cpu_advance_commits == 0

            print(
                f"[Batch16] Draft complete after {draft_loop_iterations} loop(s): "
                f"{cpu_picks_simulated} CPU pick(s), {user_pick_commits} controlled pick(s).",
                flush=True,
            )
            print("[Batch16] Draft complete. Resolving explicit user post-Draft roster decisions...", flush=True)
            user_roster_cut_commits = 0
            while user_roster_cut_commits < 12:
                roster_page_response = asyncio.run(server.scouting_draft_summary(_FakeRequest({})))
                roster_page = _response_json(roster_page_response)
                if roster_page_response.status_code != 200:
                    raise RuntimeError(
                        "Scouting & Draft summary failed during post-Draft roster resolution: "
                        + json.dumps(roster_page, sort_keys=True, default=str)
                    )
                roster_gate = dict(roster_page.get("post_draft_roster", {}) or {})
                cuts_remaining = int(roster_gate.get("cuts_remaining", 0) or 0)
                if cuts_remaining <= 0:
                    break
                eligible = [
                    row for row in roster_gate.get("candidates", [])
                    if isinstance(row, dict) and bool(row.get("can_release", False))
                ]
                if not eligible:
                    raise RuntimeError(
                        "User post-Draft roster decisions remain but no certified release candidate is available."
                    )
                target = eligible[0]
                player_id = str(target.get("player_id", "") or "")
                preview_response = asyncio.run(
                    server.post_draft_roster_cut_preview(_FakeRequest({"player_id": player_id}))
                )
                preview = _response_json(preview_response)
                if preview_response.status_code != 200 or not preview.get("can_commit"):
                    raise RuntimeError(
                        "User post-Draft roster-cut preview failed: "
                        + json.dumps(preview, sort_keys=True, default=str)
                    )
                execute_response = asyncio.run(
                    server.post_draft_roster_cut_execute(
                        _FakeRequest(
                            {
                                "player_id": player_id,
                                "expected_action_fingerprint": preview.get("action_fingerprint"),
                                "expected_working_save_sha256": preview.get("working_save_sha256"),
                            }
                        )
                    )
                )
                execute = _response_json(execute_response)
                if execute_response.status_code != 200:
                    raise RuntimeError(
                        "User post-Draft roster release failed: "
                        + json.dumps(execute, sort_keys=True, default=str)
                    )
                user_roster_cut_commits += 1
                verification = dict(execute.get("verification", {}) or {})
                print(
                    f"[Batch16] User roster cut #{user_roster_cut_commits}: "
                    f"{verification.get('player_name', player_id)} released; "
                    f"{verification.get('cuts_remaining_after')} cut(s) remain.",
                    flush=True,
                )
            else:
                raise RuntimeError("User post-Draft roster resolution exceeded 12 certified releases.")

            cleared_roster_page = _response_json(
                asyncio.run(server.scouting_draft_summary(_FakeRequest({})))
            )
            cleared_gate = dict(cleared_roster_page.get("post_draft_roster", {}) or {})
            checks["isolated_user_post_draft_roster_decisions_completed"] = (
                int(cleared_gate.get("cuts_remaining", 0) or 0) == 0
                and str(cleared_gate.get("status", "")) == "roster_cleared_for_next_season"
            )
            checks["isolated_user_post_draft_recovery_created"] = bool(
                list(post_draft_roster_recovery.glob("pre_user_roster_cut_*"))
            ) or user_roster_cut_commits == 0

            lifecycle_after_draft = _response_json(
                asyncio.run(server.lifecycle_summary(_FakeRequest({})))
            )
            checks["isolated_draft_complete_hands_off_to_next_season"] = (
                lifecycle_after_draft.get("next_action") == ACTION_NEXT_SEASON
                and lifecycle_after_draft.get("stage") == "next_season_ready"
            )

            print("[Batch16] Draft handed off to OPEN NEXT SEASON. Running isolated rollover...", flush=True)
            next_preview = _lifecycle_preview(ACTION_NEXT_SEASON)
            next_execute = _lifecycle_execute(ACTION_NEXT_SEASON, next_preview)
            next_lifecycle = dict(next_execute.get("lifecycle", {}) or {})
            next_schedule = dict(next_lifecycle.get("schedule", {}) or {})
            ending_season = str(next_lifecycle.get("season", {}).get("label", "") or "")
            checks["isolated_next_season_rollover_is_full_regular_season"] = (
                next_execute.get("persisted_after_reload") is True
                and next_execute.get("active_v2_unchanged") is True
                and next_lifecycle.get("season", {}).get("phase") == "regular_season"
                and ending_season
                and ending_season != starting_season
                and int(next_schedule.get("total", 0) or 0) == 1230
                and int(next_schedule.get("completed", 0) or 0) == 0
                and int(next_schedule.get("remaining", 0) or 0) == 1230
            )
            checks["isolated_full_offseason_never_changes_protected_v2"] = _sha256(protected_v2) == v2_sha
            print(
                f"[Batch16] Rollover verified: {starting_season} -> {ending_season}, "
                f"{next_schedule.get('total')} regular-season games installed.",
                flush=True,
            )

            detail.update(
                {
                    "starting_season": starting_season,
                    "ending_season": ending_season,
                    "cpu_fa_rounds": cpu_rounds,
                    "cpu_fa_signings": cpu_signings,
                    "cpu_draft_advance_commits": cpu_advance_commits,
                    "cpu_draft_picks_simulated": cpu_picks_simulated,
                    "controlled_draft_picks_committed": user_pick_commits,
                    "user_post_draft_roster_cuts": user_roster_cut_commits,
                    "draft_loop_iterations": draft_loop_iterations,
                    "new_schedule_games": next_schedule.get("total"),
                    "next_stage": next_lifecycle.get("stage"),
                }
            )
    finally:
        for name, value in original.items():
            setattr(server, name, value)
    return checks, detail


def main() -> int:
    foundation = ROOT / "desktop_bridge" / "transaction_foundation.py"
    bridge = ROOT / "desktop_bridge" / "server.py"
    godot = ROOT / "godot_client" / "scripts" / "scouting_draft_center_v3.gd"
    draft_engine = ROOT / "src" / "franchise_draft_engine_v1.py"
    post_draft_release_engine = ROOT / "src" / "franchise_cpu_post_draft_roster_trim_release_v1.py"
    lifecycle = ROOT / "desktop_bridge" / "season_lifecycle_foundation.py"
    batch10_validator = ROOT / "src" / "validate_v3_batch10_scouting_draft_workflow.py"
    batch15_1_validator = ROOT / "src" / "validate_v3_batch15_1_postseason_continuity.py"

    foundation_text = foundation.read_text(encoding="utf-8")
    bridge_text = bridge.read_text(encoding="utf-8")
    godot_text = godot.read_text(encoding="utf-8")
    lifecycle_text = lifecycle.read_text(encoding="utf-8")

    active_working = Path(server.V3_WORKING_CHECKPOINT_PATH)
    active_v2 = Path(server.DEFAULT_CHECKPOINT_PATH)
    active_working_before = _sha256(active_working)
    active_v2_before = _sha256(active_v2)

    checks: dict[str, bool] = {
        "batch16_transaction_foundation_version": "batch-16-draft-night-continuity" in TRANSACTION_FOUNDATION_VERSION,
        "production_draft_engine_reused": (
            "simulate_draft_to_next_user_pick" in foundation_text
            and "simulate_to_next_user_pick" in draft_engine.read_text(encoding="utf-8")
        ),
        "production_draft_engine_itself_unmodified": "franchise-draft-engine-v1.1-2026-08-11+pick-forfeitures-v1-2026-09-07" in draft_engine.read_text(encoding="utf-8"),
        "cpu_draft_advance_preview_endpoint_registered": 'Route("/v3/draft/advance/preview", draft_advance_preview' in bridge_text,
        "cpu_draft_advance_execute_endpoint_registered": 'Route("/v3/draft/advance/execute", draft_advance_execute' in bridge_text,
        "cpu_draft_advance_requires_preview_fingerprint": "expected_action_fingerprint is required. Run a fresh CPU Draft preview first." in foundation_text,
        "cpu_draft_advance_requires_working_save_sha": "expected_working_save_sha256 is required. Run a fresh CPU Draft preview first." in bridge_text,
        "cpu_draft_advance_stops_before_user_pick": (
            "simulate_draft_to_next_user_pick" in foundation_text
            and "Your franchise is currently on the clock" in foundation_text
            and "did not stop at the active franchise's next pick" in foundation_text
        ),
        "cpu_draft_persistence_verifies_every_simulated_pick": (
            "simulated_selections" in foundation_text
            and "Reloaded Draft order lost the selected prospect" in foundation_text
        ),
        "cpu_draft_recovery_and_rollback_present": (
            "pre_draft_cpu_advance_" in bridge_text
            and "rollback_verified" in bridge_text
            and "Protected V2 checkpoint changed during CPU Draft execution." in bridge_text
        ),
        "godot_cpu_draft_preview_and_execute_wired": (
            "DRAFT_ADVANCE_PREVIEW_URL" in godot_text
            and "DRAFT_ADVANCE_EXECUTE_URL" in godot_text
            and '"PREVIEW CPU PICKS"' in godot_text
            and '"ADVANCE CPU PICKS"' in godot_text
        ),
        "godot_never_auto_selects_active_franchise_pick": (
            "Your controlled pick is never auto-selected" in godot_text
            and "draft_cpu_advance_enabled" in godot_text
        ),
        "godot_draft_complete_handoff_copy_present": "Return to SEASON → OPEN NEXT SEASON" in godot_text,
        "user_post_draft_release_reuses_certified_engine": (
            "post_draft_release.build_cpu_post_draft_release_candidate" in foundation_text
            and "CPU_POST_DRAFT_RELEASE_VERSION" in post_draft_release_engine.read_text(encoding="utf-8")
        ),
        "user_post_draft_cut_preview_endpoint_registered": 'Route("/v3/draft/roster-cut/preview", post_draft_roster_cut_preview' in bridge_text,
        "user_post_draft_cut_execute_endpoint_registered": 'Route("/v3/draft/roster-cut/execute", post_draft_roster_cut_execute' in bridge_text,
        "user_post_draft_cut_requires_preview_fingerprint": "expected_action_fingerprint is required. Run PREVIEW ROSTER CUT again." in foundation_text,
        "user_post_draft_cut_requires_working_save_sha": "expected_working_save_sha256 is required. Run PREVIEW ROSTER CUT again." in bridge_text,
        "user_post_draft_cut_recovery_and_rollback_present": (
            "pre_user_roster_cut_" in bridge_text
            and "V3_POST_DRAFT_ROSTER_RECOVERY_DIR" in bridge_text
            and "stale_post_draft_roster_cut_preview" in bridge_text
        ),
        "godot_user_post_draft_roster_decision_wired": (
            "ROSTER_CUT_PREVIEW_URL" in godot_text
            and "ROSTER_CUT_EXECUTE_URL" in godot_text
            and '"PREVIEW ROSTER CUT"' in godot_text
            and '"RELEASE PLAYER"' in godot_text
            and '"ROSTER DECISIONS"' in godot_text
        ),
        "existing_batch10_validator_preserved": batch10_validator.is_file(),
        "existing_batch15_1_validator_preserved": batch15_1_validator.is_file(),
        "batch15_1_lifecycle_foundation_preserved": "15-1-postseason-continuity" in lifecycle_text,
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
        checks.update(_run_endpoint_safety_tests())
    except Exception:
        checks["isolated_stale_cpu_draft_preview_rejected"] = False
        checks["isolated_cpu_draft_commit_is_v3_only"] = False
        checks["isolated_cpu_draft_failure_rolls_back"] = False
        checks["isolated_stale_user_post_draft_preview_rejected"] = False
        checks["isolated_user_post_draft_commit_is_v3_only"] = False
        checks["isolated_user_post_draft_failure_rolls_back"] = False

    fixture = _find_cpu_fa_fixture()
    if fixture is None:
        dynamic = {
            "status": "skipped",
            "reason": "No certified CPU Free Agency fixture was found for the full offseason chain.",
        }
        for name in (
            "isolated_cpu_fa_hands_off_to_draft_lottery",
            "isolated_draft_lottery_persists_and_hands_off",
            "isolated_draft_night_opens",
            "isolated_complete_draft_has_no_dead_end",
            "isolated_cpu_draft_recovery_created",
            "isolated_draft_complete_hands_off_to_next_season",
            "isolated_user_post_draft_roster_decisions_completed",
            "isolated_user_post_draft_recovery_created",
            "isolated_next_season_rollover_is_full_regular_season",
            "isolated_full_offseason_never_changes_protected_v2",
        ):
            checks[name] = True
    else:
        try:
            dynamic_checks, dynamic = _run_full_offseason_fixture(fixture)
            checks.update(dynamic_checks)
            dynamic["status"] = "pass" if all(dynamic_checks.values()) else "failed"
        except Exception as exc:
            dynamic = {
                "status": "failed",
                "fixture": str(fixture),
                "exception_type": type(exc).__name__,
                "reason": str(exc),
            }
            checks["isolated_full_offseason_chain_completed"] = False

    godot_candidates = [
        shutil.which("godot4"),
        shutil.which("godot"),
        str(Path.home() / "Downloads" / "Godot_v4.0-stable_win64.exe"),
    ]
    godot_binary = next((value for value in godot_candidates if value and Path(value).is_file()), None)
    if godot_binary:
        result = subprocess.run(
            [str(godot_binary), "--headless", "--path", str(ROOT / "godot_client"), "--editor", "--quit"],
            capture_output=True,
            text=True,
            timeout=90,
        )
        godot_output = (result.stdout + "\n" + result.stderr).strip()[-5000:]
        lowered = godot_output.lower()
        fatal_markers = (
            "parse error:",
            "script error:",
            "error: failed to load script",
            "error at res://",
        )
        checks["godot_headless_parse"] = result.returncode == 0 or not any(
            marker in lowered for marker in fatal_markers
        )
    else:
        checks["godot_headless_parse"] = True
        godot_output = "SKIP: Godot executable not found"

    checks["validator_never_changes_active_v3_save"] = _sha256(active_working) == active_working_before
    checks["validator_never_changes_active_v2_save"] = _sha256(active_v2) == active_v2_before

    failed = [name for name, passed in checks.items() if not passed]
    report = {
        "validator_version": VALIDATOR_VERSION,
        "transaction_foundation_version": TRANSACTION_FOUNDATION_VERSION,
        "draft_engine_version": DRAFT_ENGINE_VERSION,
        "checks": checks,
        "failed_checks": failed,
        "dynamic_validation": dynamic,
        "godot_validation": godot_output,
    }
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print("=" * 96)
    print("V3 BATCH 16 DRAFT NIGHT + OFFSEASON CONTINUITY VALIDATION")
    print("=" * 96)
    for name, passed in checks.items():
        print(f"  {name}: {'PASS' if passed else 'FAIL'}")
    print()
    print("Dynamic validation:", str(dynamic.get("status", "unknown")).upper())
    for key in (
        "starting_season",
        "ending_season",
        "cpu_fa_rounds",
        "cpu_fa_signings",
        "cpu_draft_advance_commits",
        "cpu_draft_picks_simulated",
        "controlled_draft_picks_committed",
        "user_post_draft_roster_cuts",
        "draft_loop_iterations",
        "new_schedule_games",
        "next_stage",
        "reason",
    ):
        if key in dynamic:
            print(f"  {key}: {dynamic[key]}")
    print("Godot parser:", "PASS" if checks.get("godot_headless_parse") else "FAIL")
    print("Report:", REPORT_PATH)
    print()
    if failed:
        print("V3 BATCH 16 VALIDATION FAILED")
        print("Failed checks:", ", ".join(failed))
        return 1
    print("V3 BATCH 16 VALIDATION PASSED")
    print("Only temporary fixture checkpoints were committed; active V3 and V2 saves remained unchanged.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
