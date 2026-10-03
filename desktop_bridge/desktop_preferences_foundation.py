from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
import json
import os
import tempfile


PREFERENCES_VERSION = "v3-desktop-preferences-batch-17c-v1.0.0-2026-10-03"

DEFAULT_PREFERENCES: dict[str, bool] = {
    "show_tutorial_on_startup": True,
    "tutorial_completed": False,
    "confirm_load": True,
    "confirm_delete": True,
    "confirm_new_franchise": True,
    "return_home_after_save_switch": True,
}

EDITABLE_KEYS = {
    "show_tutorial_on_startup",
    "confirm_load",
    "confirm_delete",
    "confirm_new_franchise",
    "return_home_after_save_switch",
}


class V3DesktopPreferencesError(RuntimeError):
    """Raised when a desktop-preferences request is invalid or unsafe."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_json_write(path: Path, payload: Mapping[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(dict(payload), handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)


def _coerce_preferences(raw: Any) -> dict[str, bool]:
    resolved = dict(DEFAULT_PREFERENCES)
    if not isinstance(raw, Mapping):
        return resolved
    for key in DEFAULT_PREFERENCES:
        value = raw.get(key)
        if isinstance(value, bool):
            resolved[key] = value
    return resolved


def _read_document(path: Path) -> tuple[bool, dict[str, Any]]:
    path = Path(path)
    if not path.is_file():
        return False, {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise V3DesktopPreferencesError(
            f"Desktop preferences could not be read: {type(exc).__name__}: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise V3DesktopPreferencesError("Desktop preferences must be a JSON object.")
    return True, payload


def build_desktop_preferences_summary(path: Path) -> dict[str, Any]:
    path = Path(path)
    initialized, document = _read_document(path)
    preferences = _coerce_preferences(document.get("preferences", {}))
    return {
        "version": PREFERENCES_VERSION,
        "initialized": initialized,
        "preferences": preferences,
        "updated_at_utc": str(document.get("updated_at_utc", "") or ""),
        "settings_path": str(path),
        "franchise_save_write_performed": False,
        "active_v2_read_only": True,
    }


def _write_preferences(path: Path, preferences: Mapping[str, bool]) -> dict[str, Any]:
    normalized = _coerce_preferences(preferences)
    document = {
        "version": PREFERENCES_VERSION,
        "updated_at_utc": _utc_now(),
        "preferences": normalized,
    }
    _atomic_json_write(path, document)
    summary = build_desktop_preferences_summary(path)
    summary["preferences_write_performed"] = True
    return summary


def update_desktop_preferences(
    path: Path,
    updates: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(updates, Mapping):
        raise V3DesktopPreferencesError("Preference updates must be a JSON object.")

    unknown = sorted(set(str(key) for key in updates) - EDITABLE_KEYS)
    if unknown:
        raise V3DesktopPreferencesError(
            "Unsupported desktop preference(s): " + ", ".join(unknown)
        )

    current = build_desktop_preferences_summary(path)["preferences"]
    next_preferences = dict(current)
    for key, value in updates.items():
        if not isinstance(value, bool):
            raise V3DesktopPreferencesError(
                f"Desktop preference '{key}' must be true or false."
            )
        next_preferences[str(key)] = value

    return _write_preferences(path, next_preferences)


def complete_tutorial(path: Path) -> dict[str, Any]:
    current = build_desktop_preferences_summary(path)["preferences"]
    next_preferences = dict(current)
    next_preferences["tutorial_completed"] = True
    next_preferences["show_tutorial_on_startup"] = False
    result = _write_preferences(path, next_preferences)
    result["tutorial_status"] = "completed"
    return result


def reset_desktop_preferences(path: Path) -> dict[str, Any]:
    result = _write_preferences(path, DEFAULT_PREFERENCES)
    result["reset_to_safe_defaults"] = True
    return result
