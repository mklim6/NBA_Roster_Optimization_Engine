from __future__ import annotations

import hashlib
import importlib.util
import inspect
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

FRANCHISE_GAME_FLOW_RUNTIME_BRIDGE_V1_VERSION = (
    "franchise-game-flow-runtime-bridge-v1.0-2026-09-11"
)

_SRC_DIR = Path(__file__).resolve().parent
_TARGET = _SRC_DIR / "franchise_game_flow_v1.py"
_CACHE_KEY: tuple[int, int, str] | None = None
_CACHE_MODULE: ModuleType | None = None


def _target_fingerprint() -> tuple[int, int, str]:
    stat = _TARGET.stat()
    digest = hashlib.sha256(_TARGET.read_bytes()).hexdigest()[:16]
    return (stat.st_mtime_ns, stat.st_size, digest)


def _load_exact_game_flow_module() -> ModuleType:
    """Load the exact src/franchise_game_flow_v1.py file, ignoring sys.modules collisions."""
    global _CACHE_KEY, _CACHE_MODULE
    key = _target_fingerprint()
    if _CACHE_MODULE is not None and _CACHE_KEY == key:
        return _CACHE_MODULE

    unique_name = f"_franchise_game_flow_exact_{key[2]}"
    spec = importlib.util.spec_from_file_location(unique_name, _TARGET)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not create import spec for {_TARGET}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[unique_name] = module
    spec.loader.exec_module(module)
    _CACHE_KEY = key
    _CACHE_MODULE = module
    return module


def runtime_target_path_v1() -> str:
    return str(_TARGET)


def runtime_render_signature_v1() -> str:
    module = _load_exact_game_flow_module()
    return str(inspect.signature(module.render_franchise_game_flow_v1))


def inject_franchise_game_flow_visuals_runtime_bridge_v1(*args: Any, **kwargs: Any) -> Any:
    module = _load_exact_game_flow_module()
    return module.inject_franchise_game_flow_visuals_v1(*args, **kwargs)


def render_franchise_game_flow_runtime_bridge_v1(*args: Any, **kwargs: Any) -> Any:
    module = _load_exact_game_flow_module()
    render = module.render_franchise_game_flow_v1
    signature = inspect.signature(render)
    params = signature.parameters

    # The current Season Flow V2 implementation accepts both `state` and
    # `player_headshot_resolver`. Keep a compatibility fallback so a stale
    # V1 source file can render rather than crash, while exact-path loading
    # guarantees that an unrelated sys.modules entry can never win.
    if "state" not in params:
        kwargs.pop("state", None)
    if "player_headshot_resolver" not in params:
        kwargs.pop("player_headshot_resolver", None)
    return render(*args, **kwargs)
