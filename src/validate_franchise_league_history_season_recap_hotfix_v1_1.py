from __future__ import annotations

import ast
import importlib.util
import sys
import types
from pathlib import Path


def _install_streamlit_stub() -> None:
    if "streamlit" in sys.modules:
        return
    stub = types.SimpleNamespace(
        markdown=lambda *args, **kwargs: None,
        tabs=lambda labels: [types.SimpleNamespace(__enter__=lambda self: None, __exit__=lambda self, exc_type, exc, tb: False) for _ in labels],
        info=lambda *args, **kwargs: None,
        caption=lambda *args, **kwargs: None,
        columns=lambda n: [types.SimpleNamespace(__enter__=lambda self: None, __exit__=lambda self, exc_type, exc, tb: False) for _ in range(n)],
        divider=lambda *args, **kwargs: None,
    )
    # simple context manager class
    class _Ctx:
        def __enter__(self): return None
        def __exit__(self, exc_type, exc, tb): return False
    stub.tabs = lambda labels: [_Ctx() for _ in labels]
    stub.columns = lambda n: [_Ctx() for _ in range(n)]
    sys.modules["streamlit"] = stub


def _load(path: Path):
    _install_streamlit_stub()
    spec = importlib.util.spec_from_file_location("league_history_hotfix_test", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load League History hotfix module.")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    module_path = root / "src" / "franchise_league_history_season_recap_v1.py"
    source = module_path.read_text(encoding="utf-8")
    module = _load(module_path)

    checks = {}
    try:
        ast.parse(source)
        checks["module_compiles"] = True
    except Exception:
        checks["module_compiles"] = False

    checks["version_bumped"] = (
        "franchise-league-history-season-recap-v1.1-2026-09-16"
        in module.LEAGUE_HISTORY_SEASON_RECAP_VERSION
    )
    checks["uses_player_images"] = (
        "player_image_url" in source and "flh-leader-img" in source
    )
    checks["roy_fallback_present"] = (
        "_season_specific_roy_winner" in source
        and "season-specific rookie fallback" in source
    )
    checks["render_uses_roy_payload"] = (
        'winner=payload.get("roy_winner")' in source
    )
    checks["no_checkpoint_write"] = (
        "save_franchise_checkpoint" not in source
        and "commit_franchise_checkpoint" not in source
    )

    failed = [name for name, ok in checks.items() if not ok]
    print({"checks": checks, "failed_checks": failed, "passed": not failed})
    if failed:
        print("FRANCHISE LEAGUE HISTORY + SEASON RECAP HOTFIX V1.1 VALIDATOR FAILED")
        return 1
    print("FRANCHISE LEAGUE HISTORY + SEASON RECAP HOTFIX V1.1 VALIDATOR PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
