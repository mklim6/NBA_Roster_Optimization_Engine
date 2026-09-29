from __future__ import annotations

import ast
import hashlib
import json
import py_compile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
PACKAGE_DIR = ROOT / "franchise_checkpoint_fastpath_patch_v1"
MANIFEST = json.loads((PACKAGE_DIR / "PATCH_MANIFEST.json").read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    h = hashlib.sha256(path.read_bytes()).hexdigest()
    return h


def call_name(node: ast.Call) -> str:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return ""


def kw(call: ast.Call, name: str):
    for item in call.keywords:
        if item.arg == name:
            return item.value
    return None


def is_bool(node: ast.AST | None, value: bool) -> bool:
    return isinstance(node, ast.Constant) and node.value is value


def main() -> int:
    checks = []
    failed = []
    for name, hashes in MANIFEST.items():
        path = SRC / name
        py_compile.compile(str(path), doraise=True)
        hash_ok = sha256(path) == hashes["patched_sha256"]
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        save_calls = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.Call) and call_name(node) == "save_franchise_checkpoint"
        ]
        fastpath_ok = bool(save_calls)
        details = []
        for call in save_calls:
            call_ok = (
                is_bool(kw(call, "copy_payload"), False)
                and is_bool(kw(call, "_return_verified"), True)
                and kw(call, "_existing_checkpoint") is not None
                and kw(call, "_expected_existing_sha256") is not None
            )
            details.append({"line": call.lineno, "fastpath": call_ok})
            fastpath_ok = fastpath_ok and call_ok
        row = {"file": name, "hash_ok": hash_ok, "fastpath_ok": fastpath_ok, "calls": details}
        checks.append(row)
        if not hash_ok or not fastpath_ok:
            failed.append(row)

    print("FRANCHISE CHECKPOINT FASTPATH PATCH V1 VALIDATION")
    for row in checks:
        status = "PASS" if row["hash_ok"] and row["fastpath_ok"] else "FAIL"
        print(f"  {row['file']}: {status}")
    print("  active franchise checkpoint loaded/mutated: NO")
    if failed:
        print("VALIDATION FAILED")
        return 1
    print("VALIDATION PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
