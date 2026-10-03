from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from simulation_franchise_checkpoint_v1 import load_franchise_checkpoint


SAVE_MANAGER_VERSION = "v3-save-manager-foundation-batch-17a-v1.0.0-2026-10-03"
MANIFEST_FILENAME = "manifest.json"
SLOTS_DIRNAME = "slots"
RECOVERY_DIRNAME = "recovery"
MAX_SLOT_NAME_LENGTH = 48

TEAM_NAMES = {
    "ATL": "Atlanta Hawks",
    "BKN": "Brooklyn Nets",
    "BOS": "Boston Celtics",
    "CHA": "Charlotte Hornets",
    "CHI": "Chicago Bulls",
    "CLE": "Cleveland Cavaliers",
    "DAL": "Dallas Mavericks",
    "DEN": "Denver Nuggets",
    "DET": "Detroit Pistons",
    "GSW": "Golden State Warriors",
    "HOU": "Houston Rockets",
    "IND": "Indiana Pacers",
    "LAC": "LA Clippers",
    "LAL": "Los Angeles Lakers",
    "MEM": "Memphis Grizzlies",
    "MIA": "Miami Heat",
    "MIL": "Milwaukee Bucks",
    "MIN": "Minnesota Timberwolves",
    "NOP": "New Orleans Pelicans",
    "NYK": "New York Knicks",
    "OKC": "Oklahoma City Thunder",
    "ORL": "Orlando Magic",
    "PHI": "Philadelphia 76ers",
    "PHX": "Phoenix Suns",
    "POR": "Portland Trail Blazers",
    "SAC": "Sacramento Kings",
    "SAS": "San Antonio Spurs",
    "TOR": "Toronto Raptors",
    "UTA": "Utah Jazz",
    "WAS": "Washington Wizards",
}


class V3SaveManagerError(RuntimeError):
    pass


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _sha256(path: Path) -> str | None:
    path = Path(path)
    if not path.exists():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _manifest_path(root: Path) -> Path:
    return Path(root) / MANIFEST_FILENAME


def _slots_dir(root: Path) -> Path:
    return Path(root) / SLOTS_DIRNAME


def _recovery_dir(root: Path) -> Path:
    return Path(root) / RECOVERY_DIRNAME


def _slot_path(root: Path, slot_id: str) -> Path:
    return _slots_dir(root) / f"{slot_id}.pkl.gz"


def _clean_slot_name(value: Any) -> str:
    name = re.sub(r"\s+", " ", str(value or "").strip())
    if not name:
        raise V3SaveManagerError("Save name cannot be blank.")
    if len(name) > MAX_SLOT_NAME_LENGTH:
        raise V3SaveManagerError(
            f"Save name cannot exceed {MAX_SLOT_NAME_LENGTH} characters."
        )
    if any(ch in name for ch in "\\/:*?\"<>|"):
        raise V3SaveManagerError("Save name contains an unsupported filesystem character.")
    return name


def _phase_value(state: Any) -> str:
    raw = getattr(state, "phase", "")
    return str(getattr(raw, "value", raw) or "").strip().lower()


def _checkpoint_metadata(path: Path) -> dict[str, Any]:
    checkpoint = load_franchise_checkpoint(path=Path(path), allow_backup=False)
    if checkpoint is None:
        raise V3SaveManagerError(f"Checkpoint does not exist: {path}")
    state = checkpoint.simulation_state
    preferences = dict(getattr(checkpoint, "preferences", {}) or {})
    team = str(preferences.get("franchise_pref_active_team", "") or "").strip().upper()
    if not team:
        controlled = preferences.get("franchise_pref_controlled_teams", ()) or ()
        for value in controlled:
            candidate = str(value or "").strip().upper()
            if candidate:
                team = candidate
                break
    season = str(getattr(getattr(state, "settings", None), "season_label", "") or "")
    day_index = int(getattr(state, "current_day_index", 0) or 0)
    standing = (getattr(state, "standings", {}) or {}).get(team)
    wins = int(getattr(standing, "wins", 0) or 0) if standing is not None else 0
    losses = int(getattr(standing, "losses", 0) or 0) if standing is not None else 0
    games_played = int(getattr(standing, "games_played", wins + losses) or 0) if standing is not None else 0
    return {
        "team": team,
        "team_name": TEAM_NAMES.get(team, team or "Unknown Franchise"),
        "season": season,
        "phase": _phase_value(state),
        "day_index": day_index,
        "wins": wins,
        "losses": losses,
        "games_played": games_played,
        "record": f"{wins}-{losses}" if standing is not None else "--",
        "checkpoint_saved_at_utc": str(getattr(checkpoint, "saved_at_utc", "") or ""),
        "checkpoint_reason": str(getattr(checkpoint, "reason", "") or ""),
    }


def _atomic_copy_verified(source: Path, target: Path) -> str:
    source = Path(source)
    target = Path(target)
    if not source.exists():
        raise V3SaveManagerError(f"Source checkpoint does not exist: {source}")
    target.parent.mkdir(parents=True, exist_ok=True)
    source_sha = _sha256(source)
    if not source_sha:
        raise V3SaveManagerError("Could not hash the source checkpoint.")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=target.name + ".",
        suffix=".tmp",
        dir=str(target.parent),
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as out_handle, source.open("rb") as in_handle:
            shutil.copyfileobj(in_handle, out_handle, length=1024 * 1024)
            out_handle.flush()
            os.fsync(out_handle.fileno())
        if _sha256(temporary) != source_sha:
            raise V3SaveManagerError("Temporary checkpoint copy failed SHA-256 verification.")
        os.replace(temporary, target)
        if _sha256(target) != source_sha:
            raise V3SaveManagerError("Committed checkpoint copy failed SHA-256 verification.")
        load_franchise_checkpoint(path=target, allow_backup=False)
        return source_sha
    finally:
        if temporary.exists():
            try:
                temporary.unlink()
            except OSError:
                pass


def _atomic_json_write(path: Path, payload: Mapping[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=path.name + ".",
        suffix=".tmp",
        dir=str(path.parent),
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            try:
                temporary.unlink()
            except OSError:
                pass


def _load_manifest(root: Path, *, required: bool = False) -> dict[str, Any] | None:
    path = _manifest_path(root)
    if not path.exists():
        if required:
            raise V3SaveManagerError("V3 Save Manager is not initialized yet.")
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise V3SaveManagerError(f"Save Manager manifest could not be read: {exc}") from exc
    if not isinstance(payload, dict):
        raise V3SaveManagerError("Save Manager manifest has an invalid structure.")
    if str(payload.get("version", "")) != SAVE_MANAGER_VERSION:
        raise V3SaveManagerError("Save Manager manifest version is unsupported.")
    slots = payload.get("slots", [])
    if not isinstance(slots, list):
        raise V3SaveManagerError("Save Manager manifest slot list is invalid.")
    return payload


def _slot_rows(manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = manifest.get("slots", [])
    return [dict(row) for row in rows if isinstance(row, Mapping)]


def _find_slot(manifest: Mapping[str, Any], slot_id: str) -> dict[str, Any]:
    slot_id = str(slot_id or "").strip()
    for row in _slot_rows(manifest):
        if str(row.get("slot_id", "")) == slot_id:
            return row
    raise V3SaveManagerError(f"Unknown save slot: {slot_id or '<blank>'}.")


def _next_slot_id(manifest: Mapping[str, Any]) -> str:
    used = {str(row.get("slot_id", "")) for row in _slot_rows(manifest)}
    index = 1
    while True:
        candidate = f"slot-{index:03d}"
        if candidate not in used:
            return candidate
        index += 1


def _assert_unique_name(manifest: Mapping[str, Any], name: str, *, except_slot_id: str = "") -> None:
    lowered = name.casefold()
    for row in _slot_rows(manifest):
        if str(row.get("slot_id", "")) == except_slot_id:
            continue
        if str(row.get("name", "")).casefold() == lowered:
            raise V3SaveManagerError("A save with that name already exists.")


def _slot_row_from_checkpoint(
    *,
    root: Path,
    slot_id: str,
    name: str,
    created_at_utc: str,
    checkpoint_path: Path,
) -> dict[str, Any]:
    metadata = _checkpoint_metadata(checkpoint_path)
    return {
        "slot_id": slot_id,
        "name": name,
        "filename": _slot_path(root, slot_id).name,
        "created_at_utc": created_at_utc,
        "updated_at_utc": _utc(),
        "sha256": _sha256(checkpoint_path),
        **metadata,
    }


def _replace_slot(manifest: dict[str, Any], updated: Mapping[str, Any]) -> None:
    slot_id = str(updated.get("slot_id", ""))
    cooked: list[dict[str, Any]] = []
    replaced = False
    for row in _slot_rows(manifest):
        if str(row.get("slot_id", "")) == slot_id:
            cooked.append(dict(updated))
            replaced = True
        else:
            cooked.append(row)
    if not replaced:
        raise V3SaveManagerError(f"Could not update missing slot {slot_id}.")
    manifest["slots"] = cooked
    manifest["updated_at_utc"] = _utc()


def _safety_hashes(working_path: Path, v2_path: Path) -> tuple[str | None, str | None]:
    return _sha256(Path(working_path)), _sha256(Path(v2_path))


def build_save_manager_summary(
    *,
    working_path: Path,
    v2_path: Path,
    manager_root: Path,
) -> dict[str, Any]:
    working_path = Path(working_path)
    v2_path = Path(v2_path)
    manager_root = Path(manager_root)
    working_before, v2_before = _safety_hashes(working_path, v2_path)
    manifest = _load_manifest(manager_root, required=False)
    if manifest is None:
        return {
            "version": SAVE_MANAGER_VERSION,
            "initialized": False,
            "bootstrap_available": working_path.exists(),
            "working_save_exists": working_path.exists(),
            "working_save_sha256": working_before,
            "active_v2_read_only": True,
            "active_v2_sha256": v2_before,
            "working_save_unchanged": working_before == _sha256(working_path),
            "active_v2_unchanged": v2_before == _sha256(v2_path),
            "active_slot_id": "",
            "slot_count": 0,
            "slots": [],
        }

    active_slot_id = str(manifest.get("active_slot_id", "") or "")
    slots: list[dict[str, Any]] = []
    for row in _slot_rows(manifest):
        slot_id = str(row.get("slot_id", ""))
        path = _slot_path(manager_root, slot_id)
        observed_sha = _sha256(path)
        expected_sha = str(row.get("sha256", "") or "")
        rendered = dict(row)
        rendered.update(
            {
                "active": slot_id == active_slot_id,
                "exists": path.exists(),
                "healthy": bool(path.exists() and observed_sha and observed_sha == expected_sha),
                "observed_sha256": observed_sha,
            }
        )
        slots.append(rendered)

    active_row = next((row for row in slots if row.get("active")), None)
    active_snapshot_sha = str((active_row or {}).get("sha256", "") or "")
    working_now = _sha256(working_path)
    return {
        "version": SAVE_MANAGER_VERSION,
        "initialized": True,
        "bootstrap_available": False,
        "working_save_exists": working_path.exists(),
        "working_save_sha256": working_now,
        "active_v2_read_only": True,
        "active_v2_sha256": v2_before,
        "working_save_unchanged": working_before == working_now,
        "active_v2_unchanged": v2_before == _sha256(v2_path),
        "active_slot_id": active_slot_id,
        "active_slot_snapshot_sha256": active_snapshot_sha,
        "live_session_ahead_of_snapshot": bool(
            active_slot_id and working_now and active_snapshot_sha and working_now != active_snapshot_sha
        ),
        "slot_count": len(slots),
        "slots": slots,
        "manifest_updated_at_utc": str(manifest.get("updated_at_utc", "") or ""),
    }


def bootstrap_save_manager(
    *,
    working_path: Path,
    v2_path: Path,
    manager_root: Path,
    default_name: str = "",
) -> dict[str, Any]:
    working_path = Path(working_path)
    v2_path = Path(v2_path)
    manager_root = Path(manager_root)
    working_before, v2_before = _safety_hashes(working_path, v2_path)
    if not working_path.exists():
        raise V3SaveManagerError("V3 working save must exist before Save Manager initialization.")
    existing = _load_manifest(manager_root, required=False)
    if existing is not None:
        return build_save_manager_summary(
            working_path=working_path,
            v2_path=v2_path,
            manager_root=manager_root,
        )

    metadata = _checkpoint_metadata(working_path)
    slot_id = "slot-001"
    fallback_name = f"{metadata['team_name']} Franchise" if metadata.get("team_name") else "Current Franchise"
    name = _clean_slot_name(default_name or fallback_name)
    now = _utc()
    slot_path = _slot_path(manager_root, slot_id)
    slot_sha = _atomic_copy_verified(working_path, slot_path)
    row = _slot_row_from_checkpoint(
        root=manager_root,
        slot_id=slot_id,
        name=name,
        created_at_utc=now,
        checkpoint_path=slot_path,
    )
    row["sha256"] = slot_sha
    manifest = {
        "version": SAVE_MANAGER_VERSION,
        "created_at_utc": now,
        "updated_at_utc": now,
        "active_slot_id": slot_id,
        "slots": [row],
    }
    _atomic_json_write(_manifest_path(manager_root), manifest)
    if _sha256(working_path) != working_before:
        raise V3SaveManagerError("Save Manager bootstrap unexpectedly changed the V3 working save.")
    if _sha256(v2_path) != v2_before:
        raise V3SaveManagerError("Save Manager bootstrap unexpectedly changed protected V2.")
    return build_save_manager_summary(
        working_path=working_path,
        v2_path=v2_path,
        manager_root=manager_root,
    )


def save_current_slot(
    *,
    working_path: Path,
    v2_path: Path,
    manager_root: Path,
) -> dict[str, Any]:
    working_path = Path(working_path)
    v2_path = Path(v2_path)
    manager_root = Path(manager_root)
    if not working_path.exists():
        raise V3SaveManagerError("V3 working save does not exist.")
    manifest = _load_manifest(manager_root, required=True)
    assert manifest is not None
    slot_id = str(manifest.get("active_slot_id", "") or "")
    if not slot_id:
        raise V3SaveManagerError("Save Manager has no active slot.")
    row = _find_slot(manifest, slot_id)
    working_before, v2_before = _safety_hashes(working_path, v2_path)
    slot_path = _slot_path(manager_root, slot_id)
    recovery_path: Path | None = None
    if slot_path.exists():
        recovery_path = _recovery_dir(manager_root) / f"pre_save_{slot_id}_{_stamp()}.pkl.gz"
        _atomic_copy_verified(slot_path, recovery_path)
    try:
        new_sha = _atomic_copy_verified(working_path, slot_path)
        updated = _slot_row_from_checkpoint(
            root=manager_root,
            slot_id=slot_id,
            name=str(row.get("name", "") or "Current Franchise"),
            created_at_utc=str(row.get("created_at_utc", "") or _utc()),
            checkpoint_path=slot_path,
        )
        updated["sha256"] = new_sha
        _replace_slot(manifest, updated)
        _atomic_json_write(_manifest_path(manager_root), manifest)
    except Exception:
        if recovery_path is not None and recovery_path.exists():
            _atomic_copy_verified(recovery_path, slot_path)
        raise
    if _sha256(working_path) != working_before:
        raise V3SaveManagerError("Saving the active slot changed the V3 working save.")
    if _sha256(v2_path) != v2_before:
        raise V3SaveManagerError("Saving the active slot changed protected V2.")
    summary = build_save_manager_summary(
        working_path=working_path,
        v2_path=v2_path,
        manager_root=manager_root,
    )
    summary.update({"status": "saved", "saved_slot_id": slot_id, "recovery_path": str(recovery_path or "")})
    return summary


def create_slot_copy(
    *,
    working_path: Path,
    v2_path: Path,
    manager_root: Path,
    name: str,
) -> dict[str, Any]:
    working_path = Path(working_path)
    v2_path = Path(v2_path)
    manager_root = Path(manager_root)
    manifest = _load_manifest(manager_root, required=True)
    assert manifest is not None
    if not working_path.exists():
        raise V3SaveManagerError("V3 working save does not exist.")
    clean_name = _clean_slot_name(name)
    _assert_unique_name(manifest, clean_name)
    working_before, v2_before = _safety_hashes(working_path, v2_path)
    slot_id = _next_slot_id(manifest)
    now = _utc()
    slot_path = _slot_path(manager_root, slot_id)
    slot_sha = _atomic_copy_verified(working_path, slot_path)
    row = _slot_row_from_checkpoint(
        root=manager_root,
        slot_id=slot_id,
        name=clean_name,
        created_at_utc=now,
        checkpoint_path=slot_path,
    )
    row["sha256"] = slot_sha
    manifest["slots"] = [*_slot_rows(manifest), row]
    manifest["updated_at_utc"] = _utc()
    try:
        _atomic_json_write(_manifest_path(manager_root), manifest)
    except Exception:
        try:
            slot_path.unlink(missing_ok=True)
        except Exception:
            pass
        raise
    if _sha256(working_path) != working_before or _sha256(v2_path) != v2_before:
        raise V3SaveManagerError("Creating a save copy changed a protected checkpoint.")
    summary = build_save_manager_summary(
        working_path=working_path,
        v2_path=v2_path,
        manager_root=manager_root,
    )
    summary.update({"status": "created", "created_slot_id": slot_id})
    return summary


def rename_slot(
    *,
    working_path: Path,
    v2_path: Path,
    manager_root: Path,
    slot_id: str,
    name: str,
) -> dict[str, Any]:
    working_path = Path(working_path)
    v2_path = Path(v2_path)
    manager_root = Path(manager_root)
    manifest = _load_manifest(manager_root, required=True)
    assert manifest is not None
    row = _find_slot(manifest, slot_id)
    clean_name = _clean_slot_name(name)
    _assert_unique_name(manifest, clean_name, except_slot_id=slot_id)
    working_before, v2_before = _safety_hashes(working_path, v2_path)
    updated = dict(row)
    updated["name"] = clean_name
    updated["updated_at_utc"] = _utc()
    _replace_slot(manifest, updated)
    _atomic_json_write(_manifest_path(manager_root), manifest)
    if _sha256(working_path) != working_before or _sha256(v2_path) != v2_before:
        raise V3SaveManagerError("Renaming a save changed a protected checkpoint.")
    summary = build_save_manager_summary(
        working_path=working_path,
        v2_path=v2_path,
        manager_root=manager_root,
    )
    summary.update({"status": "renamed", "renamed_slot_id": str(slot_id)})
    return summary


def load_slot(
    *,
    working_path: Path,
    v2_path: Path,
    manager_root: Path,
    slot_id: str,
) -> dict[str, Any]:
    working_path = Path(working_path)
    v2_path = Path(v2_path)
    manager_root = Path(manager_root)
    manifest_path = _manifest_path(manager_root)
    manifest = _load_manifest(manager_root, required=True)
    assert manifest is not None
    target = _find_slot(manifest, slot_id)
    target_path = _slot_path(manager_root, str(target.get("slot_id", "")))
    target_expected_sha = str(target.get("sha256", "") or "")
    if not target_path.exists() or _sha256(target_path) != target_expected_sha:
        raise V3SaveManagerError("Selected save slot failed checkpoint integrity verification.")
    load_franchise_checkpoint(path=target_path, allow_backup=False)
    working_before, v2_before = _safety_hashes(working_path, v2_path)
    if not working_before:
        raise V3SaveManagerError("V3 working save does not exist.")
    original_manifest_bytes = manifest_path.read_bytes()
    current_slot_id = str(manifest.get("active_slot_id", "") or "")
    current_path: Path | None = None
    current_recovery: Path | None = None
    working_recovery = _recovery_dir(manager_root) / f"pre_load_working_{_stamp()}.pkl.gz"
    _atomic_copy_verified(working_path, working_recovery)
    try:
        if current_slot_id:
            current_row = _find_slot(manifest, current_slot_id)
            current_path = _slot_path(manager_root, current_slot_id)
            if current_path.exists():
                current_recovery = _recovery_dir(manager_root) / f"pre_switch_snapshot_{current_slot_id}_{_stamp()}.pkl.gz"
                _atomic_copy_verified(current_path, current_recovery)
            _atomic_copy_verified(working_path, current_path)
            current_updated = _slot_row_from_checkpoint(
                root=manager_root,
                slot_id=current_slot_id,
                name=str(current_row.get("name", "") or "Current Franchise"),
                created_at_utc=str(current_row.get("created_at_utc", "") or _utc()),
                checkpoint_path=current_path,
            )
            _replace_slot(manifest, current_updated)

        target_sha_now = _sha256(target_path)
        _atomic_copy_verified(target_path, working_path)
        if _sha256(working_path) != target_sha_now:
            raise V3SaveManagerError("Loaded working save did not match the selected slot.")
        loaded = load_franchise_checkpoint(path=working_path, allow_backup=False)
        if loaded is None:
            raise V3SaveManagerError("Loaded working save could not be reopened.")
        manifest["active_slot_id"] = str(slot_id)
        manifest["updated_at_utc"] = _utc()
        _atomic_json_write(manifest_path, manifest)
        if _sha256(v2_path) != v2_before:
            raise V3SaveManagerError("Loading a save changed protected V2.")
    except Exception:
        try:
            _atomic_copy_verified(working_recovery, working_path)
            if current_path is not None and current_recovery is not None and current_recovery.exists():
                _atomic_copy_verified(current_recovery, current_path)
        finally:
            try:
                descriptor, temporary_name = tempfile.mkstemp(
                    prefix=manifest_path.name + ".rollback.",
                    suffix=".tmp",
                    dir=str(manifest_path.parent),
                )
                temporary = Path(temporary_name)
                with os.fdopen(descriptor, "wb") as handle:
                    handle.write(original_manifest_bytes)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, manifest_path)
            except Exception:
                pass
        raise
    summary = build_save_manager_summary(
        working_path=working_path,
        v2_path=v2_path,
        manager_root=manager_root,
    )
    summary.update(
        {
            "status": "loaded",
            "loaded_slot_id": str(slot_id),
            "previous_working_sha256": working_before,
            "loaded_working_sha256": _sha256(working_path),
            "recovery_path": str(working_recovery),
        }
    )
    return summary


def delete_slot(
    *,
    working_path: Path,
    v2_path: Path,
    manager_root: Path,
    slot_id: str,
) -> dict[str, Any]:
    working_path = Path(working_path)
    v2_path = Path(v2_path)
    manager_root = Path(manager_root)
    manifest = _load_manifest(manager_root, required=True)
    assert manifest is not None
    slot_id = str(slot_id or "").strip()
    row = _find_slot(manifest, slot_id)
    if slot_id == str(manifest.get("active_slot_id", "") or ""):
        raise V3SaveManagerError("The active franchise cannot be deleted. Load another save first.")
    working_before, v2_before = _safety_hashes(working_path, v2_path)
    slot_path = _slot_path(manager_root, slot_id)
    if not slot_path.exists():
        raise V3SaveManagerError("Selected save file is missing.")
    recovery = _recovery_dir(manager_root) / f"deleted_{slot_id}_{_stamp()}.pkl.gz"
    _atomic_copy_verified(slot_path, recovery)
    old_manifest = copy.deepcopy(manifest)
    try:
        slot_path.unlink()
        manifest["slots"] = [
            item for item in _slot_rows(manifest) if str(item.get("slot_id", "")) != slot_id
        ]
        manifest["updated_at_utc"] = _utc()
        _atomic_json_write(_manifest_path(manager_root), manifest)
    except Exception:
        if not slot_path.exists() and recovery.exists():
            _atomic_copy_verified(recovery, slot_path)
        try:
            _atomic_json_write(_manifest_path(manager_root), old_manifest)
        except Exception:
            pass
        raise
    if _sha256(working_path) != working_before or _sha256(v2_path) != v2_before:
        raise V3SaveManagerError("Deleting a non-active save changed a protected checkpoint.")
    summary = build_save_manager_summary(
        working_path=working_path,
        v2_path=v2_path,
        manager_root=manager_root,
    )
    summary.update(
        {
            "status": "deleted",
            "deleted_slot_id": slot_id,
            "deleted_slot_name": str(row.get("name", "")),
            "recovery_path": str(recovery),
        }
    )
    return summary
