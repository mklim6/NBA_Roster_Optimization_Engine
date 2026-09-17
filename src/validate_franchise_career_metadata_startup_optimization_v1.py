from __future__ import annotations

import ast
import importlib.util
import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace


def _load(path: Path):
    spec = importlib.util.spec_from_file_location("career_metadata_perf_v1", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load career module.")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    path = root / "src" / "simulation_career_awards_v2.py"
    source = path.read_text(encoding="utf-8")
    module = _load(path)

    checks = {}
    try:
        ast.parse(source)
        checks["career_module_compiles"] = True
    except Exception:
        checks["career_module_compiles"] = False

    checks["compact_cache_version_present"] = hasattr(
        module, "CAREER_METADATA_LOOKUP_CACHE_VERSION"
    )
    checks["compact_cache_path_present"] = hasattr(
        module, "CAREER_METADATA_LOOKUP_CACHE_PATH"
    )
    checks["source_signature_validation_present"] = (
        "def _career_metadata_source_signature(" in source
        and "def _compact_cache_payload_is_current(" in source
    )
    checks["atomic_cache_write_present"] = (
        'with_suffix(".json.tmp")' in source
        and ".replace(CAREER_METADATA_LOOKUP_CACHE_PATH)" in source
    )
    checks["runtime_cache_still_preserved"] = (
        "CAREER_METADATA_RUNTIME_CACHE_VERSION" in source
        and "career_metadata_runtime_signature_v1" in source
    )
    checks["old_dataframe_group_copy_removed"] = (
        'for key, group in frame.groupby("player_id_key")' not in source
        and 'for key, group in frame.groupby("player_name_key")' not in source
    )
    checks["history_lookup_now_uses_compact_payload"] = (
        'payload.get("history_by_id"' in source
        and 'payload.get("history_by_name"' in source
    )
    checks["draft_lookup_now_uses_compact_payload"] = (
        'payload.get("draft_by_id"' in source
    )

    # Ensure the existing runtime signature behavior still works with monkeypatched
    # lookup functions, matching the old regression validator contract.
    calls = {"history": 0, "draft": 0}

    def fake_history():
        calls["history"] += 1
        return {}, {}

    def fake_draft():
        calls["draft"] += 1
        return {}

    module._history_lookup = fake_history
    module._draft_row_lookup = fake_draft

    player = SimpleNamespace(
        player_id="fixture-1",
        player_name="Fixture Rookie",
        team_abbreviation="CHI",
        age=22.0,
        synthetic=False,
    )
    state = SimpleNamespace(
        settings=SimpleNamespace(season_label="2026-27"),
        players={"fixture-1": player},
    )
    first = module.ensure_career_metadata(state)
    second = module.ensure_career_metadata(state)
    checks["existing_runtime_cache_contract_preserved"] = (
        first == second and calls == {"history": 1, "draft": 1}
    )

    state.players["fixture-2"] = SimpleNamespace(
        player_id="fixture-2",
        player_name="Fixture Two",
        team_abbreviation="CHI",
        age=23.0,
        synthetic=False,
    )
    module.ensure_career_metadata(state)
    checks["registry_change_still_invalidates_runtime_cache"] = (
        calls == {"history": 2, "draft": 2}
    )

    failed = [name for name, ok in checks.items() if not ok]
    print(json.dumps({
        "checks": checks,
        "failed_checks": failed,
        "passed": not failed,
    }, indent=2))

    if failed:
        print("FRANCHISE CAREER METADATA STARTUP OPTIMIZATION V1 VALIDATOR FAILED")
        return 1

    print("FRANCHISE CAREER METADATA STARTUP OPTIMIZATION V1 VALIDATOR PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
