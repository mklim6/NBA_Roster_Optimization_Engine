from __future__ import annotations

import dataclasses
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

import simulation_player_stat_fingerprints_v3 as fp  # noqa: E402

EXPECTED = "player-fingerprint-runtime-cache-v1-2026-08-13"
EXPECTED_V3 = "player-statistical-fingerprint-v3-empirical-2026-08-10"


@dataclasses.dataclass(frozen=True)
class _FrozenSample:
    player_id: str
    rating: float
    tags: tuple[str, ...]


def main() -> int:
    checks: dict[str, bool] = {}
    details: dict[str, str] = {}
    checks["cache_version_is_current"] = (
        getattr(fp, "PLAYER_FINGERPRINT_RUNTIME_CACHE_VERSION", "") == EXPECTED
    )
    checks["fingerprint_v3_version_is_preserved"] = (
        EXPECTED_V3 in Path(fp.__file__).read_text(encoding="utf-8")
    )
    checks["uncached_reference_builder_is_preserved"] = hasattr(
        fp, "_build_player_stat_fingerprint_uncached_v3"
    )
    checks["public_builder_is_wrapped_reference"] = (
        getattr(fp.build_player_stat_fingerprint, "__wrapped__", None)
        is fp._build_player_stat_fingerprint_uncached_v3
    )
    checks["cache_maxsize_is_bounded"] = (
        int(getattr(fp, "PLAYER_FINGERPRINT_RUNTIME_CACHE_MAXSIZE_V1", 0)) == 8192
    )

    sample = _FrozenSample("201939", 91.0, ("PG", "SG"))
    key1 = fp._fingerprint_cache_key_v1((sample, 32.5), {"phase": "regular"})
    key2 = fp._fingerprint_cache_key_v1((sample, 32.5), {"phase": "regular"})
    changed = _FrozenSample("201939", 92.0, ("PG", "SG"))
    key3 = fp._fingerprint_cache_key_v1((changed, 32.5), {"phase": "regular"})
    checks["value_equal_inputs_have_equal_keys"] = key1 == key2
    checks["mutated_semantic_inputs_change_key"] = key1 != key3

    class _Unsafe:
        pass
    unsafe_key = fp._fingerprint_cache_key_v1((_Unsafe(),), {})
    checks["unknown_mutable_objects_bypass_cache"] = (
        unsafe_key is fp._PLAYER_FINGERPRINT_CACHE_UNCACHEABLE_SENTINEL_V1
    )

    original = fp._build_player_stat_fingerprint_uncached_v3
    calls = {"count": 0}
    def fake_builder(*args, **kwargs):
        calls["count"] += 1
        return (args, tuple(kwargs.items()))
    try:
        fp._build_player_stat_fingerprint_uncached_v3 = fake_builder
        fp.player_fingerprint_runtime_cache_clear_v1()
        first = fp.build_player_stat_fingerprint("201939", rating=91.0)
        second = fp.build_player_stat_fingerprint("201939", rating=91.0)
        info = fp.player_fingerprint_runtime_cache_info_v1()
    finally:
        fp._build_player_stat_fingerprint_uncached_v3 = original
        fp.player_fingerprint_runtime_cache_clear_v1()
    checks["cache_hit_returns_exact_same_value"] = first == second
    checks["cache_hit_avoids_rebuilding"] = calls["count"] == 1
    checks["cache_info_records_hit_and_miss"] = (
        int(info["hits"]) == 1 and int(info["misses"]) == 1
    )
    details["cache_info_records_hit_and_miss"] = str(info)

    print("=" * 104)
    print("PLAYER FINGERPRINT RUNTIME CACHE V1 VALIDATION")
    print("=" * 104)
    for name, passed in checks.items():
        suffix = f" | {details[name]}" if name in details else ""
        print(f"  {name}: {'PASS' if passed else 'FAIL'}{suffix}")
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise AssertionError(
            "Player Fingerprint Runtime Cache V1 validation failed: " + ", ".join(failed)
        )
    print()
    print("PLAYER FINGERPRINT RUNTIME CACHE V1 VALIDATION PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
