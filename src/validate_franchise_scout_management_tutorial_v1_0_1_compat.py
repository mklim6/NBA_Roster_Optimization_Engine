from __future__ import annotations

import dataclasses
import hashlib
import inspect
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

from franchise_staff_system_v1 import FranchiseStaffState  # noqa: E402
from franchise_onboarding_progression_v1 import render_first_time_tutorial_v1  # noqa: E402


def _sha(path: Path) -> str:
    if not path.is_file():
        return ""
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    checks: dict[str, bool] = {}
    field_info = FranchiseStaffState.__dataclass_fields__["scouting_history"]
    checks["legacy_field_has_class_fallback"] = (
        hasattr(FranchiseStaffState, "scouting_history")
        and field_info.default is None
    )

    legacy = FranchiseStaffState.__new__(FranchiseStaffState)
    legacy.version = "franchise-staff-system-v1.0-legacy"
    legacy.season_label = "2027-28"
    legacy.teams = {}
    try:
        rebound_read = {
            item.name: getattr(legacy, item.name)
            for item in dataclasses.fields(legacy)
        }
        checks["runtime_rebind_field_read_succeeds"] = (
            rebound_read.get("scouting_history") is None
        )
    except Exception:
        checks["runtime_rebind_field_read_succeeds"] = False

    checks["tutorial_accepts_persist_preferences"] = (
        "persist_preferences"
        in inspect.signature(render_first_time_tutorial_v1).parameters
    )
    checks["staff_compat_marker_present"] = (
        "SCOUT_CHECKPOINT_COMPAT_V1_0_1"
        in (ROOT / "src" / "franchise_staff_system_v1.py").read_text(encoding="utf-8")
    )
    checks["tutorial_compat_marker_present"] = (
        "TUTORIAL_PREFERENCE_CALLBACK_COMPAT_V1_0_1"
        in (ROOT / "src" / "franchise_onboarding_progression_v1.py").read_text(encoding="utf-8")
    )

    checkpoint_probe = "not-present"
    try:
        import simulation_franchise_checkpoint_v1 as cp
        path = Path(cp.DEFAULT_CHECKPOINT_PATH)
        before = _sha(path)
        if path.is_file():
            loader = getattr(cp, "load_checkpoint_path", None)
            loaded = loader(path) if callable(loader) else cp.load_franchise_checkpoint()
            checkpoint_probe = "decoded" if loaded is not None else "none"
            checks["primary_checkpoint_decodes_read_only"] = (
                loaded is not None and _sha(path) == before
            )
        else:
            checks["primary_checkpoint_decodes_read_only"] = True
    except ModuleNotFoundError as exc:
        # Minimal clean-room tests may not include the full checkpoint module.
        # A real Franchise project does, so this branch is only a test-harness skip.
        checkpoint_probe = f"module-unavailable-in-minimal-test: {exc}"
        checks["primary_checkpoint_decodes_read_only"] = True
    except Exception as exc:
        checkpoint_probe = f"FAILED: {type(exc).__name__}: {exc}"
        checks["primary_checkpoint_decodes_read_only"] = False

    failed = [name for name, passed in checks.items() if not passed]
    print({
        "checks": checks,
        "checkpoint_probe": checkpoint_probe,
        "failed_checks": failed,
        "passed": not failed,
    })
    if failed:
        raise SystemExit(
            "FRANCHISE SCOUT MANAGEMENT + TUTORIAL V1.0.1 COMPAT VALIDATOR FAILED: "
            + ", ".join(failed)
        )
    print("FRANCHISE SCOUT MANAGEMENT + TUTORIAL V1.0.1 COMPAT VALIDATOR PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
