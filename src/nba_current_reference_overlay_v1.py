from __future__ import annotations

import csv
import hashlib
import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

VERSION = "nba-current-reference-overlay-loader-v2-2026-09-07"
DEFAULT_MANIFEST_PATH = (
    Path(__file__).resolve().parents[1]
    / "app_data"
    / "nba_current_reference_manifest.json"
)
LEGACY_JSON_PATH = (
    Path(__file__).resolve().parents[1]
    / "app_data"
    / "nba_current_reference_overlay_2026_08_14.json"
)
LEGACY_CSV_PATH = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "reference"
    / "nba_current_reference_overlay_2026_08_14.csv"
)
DEFAULT_JSON_PATH = (
    Path(__file__).resolve().parents[1]
    / "app_data"
    / "nba_current_reference_overlay_2026_09_07.json"
)
DEFAULT_CSV_PATH = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "reference"
    / "nba_current_reference_overlay_2026_09_07.csv"
)

ALLOWED_STATUSES = {
    "under_contract",
    "two_way",
    "exhibit_10",
    "free_agent",
    "reference_review",
}


class CurrentReferenceOverlayError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _active_path() -> tuple[Path, dict[str, Any] | None]:
    if not DEFAULT_MANIFEST_PATH.exists():
        return LEGACY_JSON_PATH, None
    try:
        manifest = json.loads(DEFAULT_MANIFEST_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        raise CurrentReferenceOverlayError(
            f"Current-reference manifest is unreadable: {DEFAULT_MANIFEST_PATH}"
        ) from exc
    filename = str(manifest.get("active_overlay", "")).strip()
    if not filename or Path(filename).name != filename:
        raise CurrentReferenceOverlayError("Current-reference manifest has an unsafe active_overlay value.")
    return DEFAULT_MANIFEST_PATH.parent / filename, manifest


@lru_cache(maxsize=8)
def _read_payload_cached(
    resolved_path: str,
    modified_ns: int,
    size: int,
) -> dict[str, Any]:
    del modified_ns, size
    source = Path(resolved_path)
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except Exception as exc:
        raise CurrentReferenceOverlayError(
            f"Current-reference overlay is unreadable: {source}"
        ) from exc
    if not isinstance(payload, dict):
        raise CurrentReferenceOverlayError("Current-reference overlay root must be an object.")
    return payload


def _validate_payload(
    payload: Mapping[str, Any],
    source: Path,
    manifest: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    rows = payload.get("players")
    if not isinstance(rows, list):
        raise CurrentReferenceOverlayError("Current-reference overlay is missing a players list.")
    declared_count = payload.get("player_count")
    if declared_count != len(rows):
        raise CurrentReferenceOverlayError(
            f"Current-reference player count mismatch: declared={declared_count}; actual={len(rows)}"
        )
    if payload.get("reference_layer_only") is not True:
        raise CurrentReferenceOverlayError("Overlay is not marked reference_layer_only.")
    if payload.get("simulation_branch_eligible") is not False:
        raise CurrentReferenceOverlayError("Overlay must not be simulation-branch eligible.")

    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw in enumerate(rows):
        if not isinstance(raw, Mapping):
            raise CurrentReferenceOverlayError(f"Player row {index} is not an object.")
        row = dict(raw)
        player_id = str(row.get("player_id", "")).strip()
        if not player_id or player_id in seen:
            raise CurrentReferenceOverlayError(
                f"Player row {index} has a missing or duplicate player_id: {player_id!r}"
            )
        seen.add(player_id)
        status = str(row.get("current_reference_status", "")).strip()
        if status not in ALLOWED_STATUSES:
            raise CurrentReferenceOverlayError(
                f"Player {player_id} has unsupported current_reference_status={status!r}."
            )
        if row.get("reference_layer_only") is not True:
            raise CurrentReferenceOverlayError(f"Player {player_id} is not reference-layer only.")
        if row.get("simulation_branch_eligible") is not False:
            raise CurrentReferenceOverlayError(f"Player {player_id} is simulation-branch eligible.")
        normalized.append(row)

    if manifest is not None:
        expected_count = manifest.get("active_overlay_player_count")
        if expected_count != len(normalized):
            raise CurrentReferenceOverlayError(
                f"Manifest count mismatch: declared={expected_count}; actual={len(normalized)}"
            )
        expected_hash = str(manifest.get("active_overlay_sha256", "")).strip().lower()
        actual_hash = _sha256(source)
        if not expected_hash or expected_hash != actual_hash:
            raise CurrentReferenceOverlayError(
                f"Manifest hash mismatch for {source.name}: expected={expected_hash}; actual={actual_hash}"
            )
        cutoff = str(payload.get("reference_window_end_inclusive", ""))
        if cutoff != str(manifest.get("active_cutoff_date", "")):
            raise CurrentReferenceOverlayError(
                f"Manifest cutoff mismatch: manifest={manifest.get('active_cutoff_date')}; payload={cutoff}"
            )
    return normalized


def load_current_reference_overlay(
    path: str | Path | None = None,
) -> dict[str, dict[str, Any]]:
    if path is None:
        source, manifest = _active_path()
    else:
        source, manifest = Path(path), None
    if not source.exists():
        raise CurrentReferenceOverlayError(f"Current-reference overlay is missing: {source}")

    stat = source.stat()
    payload = _read_payload_cached(str(source.resolve()), stat.st_mtime_ns, stat.st_size)
    rows = _validate_payload(payload, source, manifest)
    return {
        str(row["player_id"]): dict(row)
        for row in rows
    }


def get_current_player_reference(
    player_id: str | int,
    path: str | Path | None = None,
) -> dict[str, Any] | None:
    return load_current_reference_overlay(path).get(str(player_id))


def overlay_current_reference(
    base: Mapping[str, Any],
    player_id: str | int,
    path: str | Path | None = None,
) -> dict[str, Any]:
    """
    Overlay CURRENT real-world reference fields only.

    This must never be used to mutate or seed the April-12 counterfactual
    franchise simulation branch.
    """
    result = dict(base)
    current = get_current_player_reference(player_id, path)
    if not current:
        return result

    result.update({
        "current_reference_team": current.get("current_reference_team", ""),
        "current_reference_status": current.get("current_reference_status", ""),
        "current_reference_two_way": current.get("current_reference_two_way", False),
        "current_reference_event_date": current.get("latest_event_date", ""),
        "current_reference_event_type": current.get("latest_event_type", ""),
        "current_reference_description": current.get("latest_description", ""),
        "current_reference_source": current.get("source_name", ""),
        "current_reference_source_url": current.get("source_url", ""),
        "current_reference_source_sha256": current.get("source_sha256", ""),
        "current_reference_roster_action": current.get("roster_reference_action", ""),
        "current_reference_contract_action": current.get("contract_reference_action", ""),
        "current_reference_supplemental_event": current.get("supplemental_event", False),
    })
    return result


__all__ = [
    "VERSION",
    "DEFAULT_MANIFEST_PATH",
    "DEFAULT_JSON_PATH",
    "DEFAULT_CSV_PATH",
    "LEGACY_JSON_PATH",
    "LEGACY_CSV_PATH",
    "CurrentReferenceOverlayError",
    "load_current_reference_overlay",
    "get_current_player_reference",
    "overlay_current_reference",
]
