from __future__ import annotations

import copy
import hashlib
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import franchise_free_agency_transaction_v1 as tx
import franchise_free_agency_transaction_v1_1 as tx11
import simulation_franchise_checkpoint_v1 as checkpoint
import franchise_free_agency_cpu_execution_v1 as execution


def _candidate_reuse_check() -> None:
    state = object()
    sentinel = object()
    offer = tx.FreeAgencyOffer(
        player_id="P1",
        team_abbreviation="CHI",
        annual_salary=1_000_000.0,
        years=1,
        offer_id="TEST-OFFER",
    )
    preview = tx.FreeAgencyTransactionPreview(
        transaction_version=tx.FREE_AGENCY_TRANSACTION_VERSION,
        offer_version=tx.FREE_AGENCY_OFFER_VERSION,
        offer=offer,
        player_name="Test Player",
        source_fingerprint="SRC",
        candidate_fingerprint="CAND",
        status="pass",
        can_commit=True,
        checks={},
        financial_gate=tx.FreeAgencyFinancialGateResult(status="pass"),
        roster_count_before=10,
        roster_count_after=11,
        message="",
    )

    original_build_preview = tx.build_free_agency_preview
    original_state_fp = tx.free_agency_state_fingerprint
    original_build_candidate = tx._build_candidate_state
    original_build_preview_candidate = tx._build_preview_candidate_state

    calls = {
        "build_preview": 0,
        "state_fp": 0,
        "legacy_builder": 0,
    }

    def fake_build_preview(*args, **kwargs):
        calls["build_preview"] += 1
        sink = kwargs.get("_candidate_sink")
        if sink is not None:
            sink.append(sentinel)
        return SimpleNamespace(
            can_commit=True,
            candidate_fingerprint="CAND",
        )

    def fake_state_fp(value):
        calls["state_fp"] += 1
        return "SRC" if value is state else "CAND"

    def fail_builder(*args, **kwargs):
        calls["legacy_builder"] += 1
        raise AssertionError(
            "The verified copy-on-write candidate was rebuilt unexpectedly."
        )

    try:
        tx.build_free_agency_preview = fake_build_preview
        tx.free_agency_state_fingerprint = fake_state_fp
        tx._build_candidate_state = fail_builder
        tx._build_preview_candidate_state = fail_builder

        candidate, result = tx.commit_free_agency_preview(
            state,
            preview,
            financial_gate=lambda _state, _offer: None,
            state_validator=lambda _state: None,
            _candidate_copy_on_write=True,
            _source_fingerprint="SRC",
        )
    finally:
        tx.build_free_agency_preview = original_build_preview
        tx.free_agency_state_fingerprint = original_state_fp
        tx._build_candidate_state = original_build_candidate
        tx._build_preview_candidate_state = original_build_preview_candidate

    assert candidate is sentinel
    assert result.committed_fingerprint == "CAND"
    assert calls["build_preview"] == 1, calls
    assert calls["legacy_builder"] == 0, calls
    assert calls["state_fp"] == 0, calls


def _durable_fingerprint_reuse_check() -> None:
    state = SimpleNamespace(
        state_version="test",
        settings=SimpleNamespace(season_label="2026-27"),
        phase="offseason",
        source_league_state_revision=1,
        source_transaction_count=2,
        transition_count=3,
        franchise_transaction_revision=4,
        free_agent_player_ids=(),
        players={},
        teams={},
        free_agency_transaction_revision=7,
        free_agency_transaction_history=[{"event": "test"}],
    )
    v1 = tx.free_agency_state_fingerprint(state)
    ordinary = tx11.free_agency_durable_state_fingerprint(state)
    reused = tx11.free_agency_durable_state_fingerprint(
        state,
        _v1_state_fingerprint=v1,
    )
    assert ordinary == reused


def _checkpoint_byte_hash_reuse_check() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "checkpoint.pkl.gz"
        sim = SimpleNamespace(
            settings=SimpleNamespace(season_label="2026-27"),
            phase="offseason",
            current_day_index=0,
        )
        trade = SimpleNamespace()

        first_hashes: list[str] = []
        first = checkpoint.save_franchise_checkpoint(
            sim,
            trade,
            path=path,
            reason="durable-integrity-reuse-test-1",
            copy_payload=False,
            force_replace=True,
            _return_verified=True,
            _verify_encoded_bytes_only=True,
            _verified_file_sha256_sink=first_hashes,
        )
        assert len(first_hashes) == 1
        assert first_hashes[0] == hashlib.sha256(path.read_bytes()).hexdigest()

        second_hashes: list[str] = []
        second = checkpoint.save_franchise_checkpoint(
            sim,
            trade,
            path=path,
            reason="durable-integrity-reuse-test-2",
            copy_payload=False,
            force_replace=True,
            _return_verified=True,
            _existing_checkpoint=first,
            _expected_existing_sha256=first_hashes[0],
            _verify_encoded_bytes_only=True,
            _verified_file_sha256_sink=second_hashes,
        )
        assert len(second_hashes) == 1
        assert second_hashes[0] == hashlib.sha256(path.read_bytes()).hexdigest()

        semantic = checkpoint.load_checkpoint_path(path)
        assert semantic.reason == second.reason
        assert semantic.saved_at_utc == second.saved_at_utc


def main() -> int:
    _candidate_reuse_check()
    _durable_fingerprint_reuse_check()
    _checkpoint_byte_hash_reuse_check()

    report = execution.cpu_execution_contract_report()
    required = {
        "round_reuses_verified_checkpoint_sha256": True,
        "byte_verified_commit_skips_same_object_postsave_fingerprints": True,
        "durable_commit_reuses_verified_preview_candidate": True,
        "durable_commit_reuses_precomputed_state_fingerprint": True,
        "round_final_semantic_reload_required": True,
    }
    for key, expected in required.items():
        assert report.get(key) is expected, (key, report.get(key), expected)

    print("FRANCHISE V2 PHASE 1 DURABLE INTEGRITY REUSE CHECK PASSED")
    print("Verified copy-on-write candidate reused without rebuild: PASS")
    print("Precomputed durable-state fingerprint equivalence: PASS")
    print("Byte-verified checkpoint raw SHA-256 sink: PASS")
    print("Ordinary semantic checkpoint reload after byte verification: PASS")
    print("Final round semantic reload requirement: PRESERVED")
    print("Checkpoint recovery behavior intentionally changed: NO")
    print("CBA / offer / player-decision behavior intentionally changed: NO")
    print("No active franchise checkpoint was loaded or mutated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
