from __future__ import annotations

import copy
import hashlib
import py_compile
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from simulation_franchise_checkpoint_v1 import DEFAULT_CHECKPOINT_PATH
from franchise_trade_transaction_v1 import (
    FRANCHISE_TRADE_TRANSACTION_VERSION,
    FranchiseTradeTransactionError,
    select_commit_base_state,
)

VALIDATOR_VERSION = "franchise-trade-transaction-ui-hotfix-v1.0.1-validator-2026-08-12"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def fake_state(revision: int, ids: list[str]):
    return SimpleNamespace(
        franchise_trade_revision_v1=revision,
        franchise_transaction_history_v1=[
            {"transaction_id": txn_id} for txn_id in ids
        ],
    )


def main() -> int:
    checkpoint = Path(DEFAULT_CHECKPOINT_PATH)
    before = sha256(checkpoint)

    aligned_live = fake_state(1, ["FTX-0001"])
    aligned_durable = copy.deepcopy(aligned_live)
    aligned, aligned_mode = select_commit_base_state(aligned_live, aligned_durable)

    live_old = fake_state(0, [])
    durable_new = fake_state(1, ["FTX-0001"])
    selected_durable, durable_mode = select_commit_base_state(live_old, durable_new)

    live_new = fake_state(2, ["FTX-0001", "FTX-0002"])
    durable_old = fake_state(1, ["FTX-0001"])
    selected_live, live_mode = select_commit_base_state(live_new, durable_old)

    fork_rejected = False
    try:
        select_commit_base_state(
            fake_state(1, ["FTX-0001"]),
            fake_state(2, ["FTX-0099", "FTX-0100"]),
        )
    except FranchiseTradeTransactionError:
        fork_rejected = True

    ledger_ui = (SRC / "franchise_live_asset_ledger_ui_v1.py").read_text(encoding="utf-8")
    trade_ui = (SRC / "franchise_embedded_trade_center_ui_v2.py").read_text(encoding="utf-8")
    tx_text = (SRC / "franchise_trade_transaction_v1.py").read_text(encoding="utf-8")

    checks = {
        "validator_version_is_current": VALIDATOR_VERSION.endswith("2026-08-12"),
        "transaction_version_is_hotfix": "v1.0.1-auto-reconcile" in FRANCHISE_TRADE_TRANSACTION_VERSION,
        "aligned_revision_uses_live_state": aligned is aligned_live and aligned_mode == "aligned",
        "durable_newer_same_lineage_auto_reconciles": getattr(selected_durable, "franchise_trade_revision_v1", -1) == 1 and durable_mode == "durable_newer_same_lineage",
        "live_newer_same_lineage_auto_reconciles": selected_live is live_new and live_mode == "live_newer_same_lineage",
        "forked_transaction_lineage_is_rejected": fork_rejected,
        "durable_newer_package_is_re_evaluated": "reconciled_preview = build_franchise_trade_preview" in tx_text,
        "persistent_asset_router_replaces_st_tabs": "asset_tabs = st.tabs" not in ledger_ui and "franchise_live_asset_ledger_view_v1" in ledger_ui,
        "trade_builder_router_is_keyed": 'key=view_key' in ledger_ui,
        "successful_commit_stays_in_trade_builder": 'franchise_live_asset_ledger_view_v1"] = "Trade Builder"' in trade_ui,
        "confirmation_gate_is_preserved": "I understand this will change the live franchise" in trade_ui,
        "no_force_trade_path_added": "force trade" not in trade_ui.lower(),
        "all_modified_files_compile": True,
        "checkpoint_hash_still_unchanged": sha256(checkpoint) == before,
    }

    try:
        for name in [
            "franchise_trade_transaction_v1.py",
            "franchise_embedded_trade_center_ui_v2.py",
            "franchise_live_asset_ledger_ui_v1.py",
            "validate_franchise_trade_transaction_v1.py",
            "validate_franchise_trade_transaction_ui_hotfix_v1_0_1.py",
        ]:
            py_compile.compile(str(SRC / name), doraise=True)
    except Exception:
        checks["all_modified_files_compile"] = False

    print("=" * 92)
    print("FRANCHISE TRADE TRANSACTION UI HOTFIX V1.0.1 VALIDATION")
    print("=" * 92)
    for name, passed in checks.items():
        print(f"  {name}: {'PASS' if passed else 'FAIL'}")

    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise SystemExit("Hotfix validation failed: " + ", ".join(failed))

    print()
    print("HOTFIX VALIDATION PASSED")
    print("READ-ONLY VALIDATION: no live trade or durable checkpoint write was performed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
