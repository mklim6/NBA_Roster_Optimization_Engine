from __future__ import annotations

import importlib.util
import inspect
import sys
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
PAGE = ROOT / "pages" / "5_Franchise_Mode.py"
BRIDGE = SRC / "franchise_game_flow_runtime_bridge_v1.py"
TARGET = SRC / "franchise_game_flow_v1.py"

checks: dict[str, bool] = {}
page_text = PAGE.read_text(encoding="utf-8")
bridge_text = BRIDGE.read_text(encoding="utf-8") if BRIDGE.exists() else ""
checks["page_uses_runtime_bridge"] = "from franchise_game_flow_runtime_bridge_v1 import" in page_text
checks["bridge_loads_exact_src_path"] = '"franchise_game_flow_v1.py"' in bridge_text and "spec_from_file_location" in bridge_text
checks["bridge_has_sys_modules_collision_guard"] = "unique_name" in bridge_text and "sys.modules[unique_name]" in bridge_text
checks["bridge_has_compat_signature_filter"] = '"state" not in params' in bridge_text
checks["target_exists"] = TARGET.exists()

# Load the target directly from its file path and verify the expected signature.
spec = importlib.util.spec_from_file_location("_validator_exact_game_flow", TARGET)
module = importlib.util.module_from_spec(spec)
assert spec is not None and spec.loader is not None
sys.modules[spec.name] = module
spec.loader.exec_module(module)
sig = inspect.signature(module.render_franchise_game_flow_v1)
checks["target_accepts_state"] = "state" in sig.parameters
checks["target_accepts_headshot_resolver"] = "player_headshot_resolver" in sig.parameters

# Prove the bridge ignores a poisoned/colliding module already sitting in sys.modules.
poison = ModuleType("franchise_game_flow_v1")
def old_render(*, snapshot, active_team, team_name_resolver, team_logo_resolver, policy_label, blocking_count, trade_sync_required, full_schedule_active):
    return None
poison.render_franchise_game_flow_v1 = old_render
sys.modules["franchise_game_flow_v1"] = poison
sys.path.insert(0, str(SRC))
import franchise_game_flow_runtime_bridge_v1 as bridge
bridge_sig = bridge.runtime_render_signature_v1()
checks["bridge_ignores_poisoned_module"] = "state:" in bridge_sig and "player_headshot_resolver" in bridge_sig
checks["bridge_points_to_project_src"] = Path(bridge.runtime_target_path_v1()).resolve() == TARGET.resolve()

failed = [name for name, ok in checks.items() if not ok]
print({"checks": checks, "failed_checks": failed, "passed": not failed})
if failed:
    raise SystemExit(1)
print("FRANCHISE GAME FLOW IMPORT BRIDGE HOTFIX V1 VALIDATOR PASSED")
