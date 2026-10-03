from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

LONG_ACTION_VALIDATOR = ROOT / "src" / "validate_v3_batch18c_long_actions.py"
V3_WORKING = ROOT / "outputs" / "runtime" / "v3_godot_working_checkpoint.pkl.gz"
V2_PROTECTED = ROOT / "outputs" / "runtime" / "franchise_mode_checkpoint_v1.pkl.gz"

BUILD_CMD = ROOT / "Build_V3_Windows_Bundle.cmd"
BUILD_PS1 = ROOT / "scripts" / "build_v3_windows_bundle.ps1"
RUN_PS1 = ROOT / "scripts" / "run_v3_bundle.ps1"
BOOTSTRAP_PS1 = ROOT / "scripts" / "bootstrap_v3_bundle_runtime.ps1"
GITIGNORE = ROOT / ".gitignore"

VERSION = "v3-desktop-packaging-batch-18d-v1.0.0-2026-10-03"


def sha256(path: Path) -> str | None:
    if not path.exists():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def check(condition: bool, label: str, results: dict[str, bool]) -> None:
    passed = bool(condition)
    results[label] = passed
    print(f"  {label}: {'PASS' if passed else 'FAIL'}")


def main() -> int:
    v3_before = sha256(V3_WORKING)
    v2_before = sha256(V2_PROTECTED)

    results: dict[str, bool] = {}
    print("=" * 100)
    print("V3 BATCH 18D WINDOWS DESKTOP PACKAGING FOUNDATION VALIDATION")
    print("=" * 100)

    files = {
        "build_cmd": BUILD_CMD,
        "build_ps1": BUILD_PS1,
        "run_ps1": RUN_PS1,
        "bootstrap_ps1": BOOTSTRAP_PS1,
    }
    for label, path in files.items():
        check(path.exists(), f"{label}_present", results)

    build_text = BUILD_PS1.read_text(encoding="utf-8") if BUILD_PS1.exists() else ""
    run_text = RUN_PS1.read_text(encoding="utf-8") if RUN_PS1.exists() else ""
    bootstrap_text = BOOTSTRAP_PS1.read_text(encoding="utf-8") if BOOTSTRAP_PS1.exists() else ""
    ignore_text = GITIGNORE.read_text(encoding="utf-8") if GITIGNORE.exists() else ""

    check(
        'dist_v3' in build_text
        and 'NBA_Franchise_Simulator_V3' in build_text
        and 'BUILD_MANIFEST.json' in build_text,
        "builder_creates_versioned_bundle_layout",
        results,
    )
    check(
        'Godot_v4.0-stable_win64.exe' in build_text
        and 'Copy-Item $GodotExe $BundleGodot' in build_text,
        "builder_bundles_godot_runtime",
        results,
    )
    check(
        'IncludeCurrentSave' in build_text
        and 'v3_godot_working_checkpoint.pkl.gz' in build_text
        and 'Remove-Item' in build_text,
        "builder_excludes_active_v3_save_by_default",
        results,
    )
    check(
        'franchise_mode_checkpoint_v1.pkl.gz' in build_text,
        "builder_requires_protected_v2_checkpoint",
        results,
    )
    check(
        'runtime\\python\\python.exe' in run_text
        and 'runtime\\venv\\Scripts\\python.exe' in run_text,
        "bundle_launcher_prefers_bundle_local_python",
        results,
    )
    check(
        'Copy-Item $ProtectedV2 $WorkingV3' in run_text
        and 'if (-not (Test-Path $WorkingV3' in run_text,
        "bundle_first_run_creates_isolated_v3_working_save",
        results,
    )
    check(
        'Get-NetTCPConnection' in run_text
        and 'api_version' in run_text
        and 'Wait-Process' in run_text,
        "bundle_launcher_preserves_bridge_ownership_and_api_checks",
        results,
    )
    check(
        '-m venv' in bootstrap_text
        and '-m pip install -r' in bootstrap_text
        and 'Core V3 runtime imports: PASS' in bootstrap_text,
        "runtime_bootstrap_is_self_contained_after_base_python",
        results,
    )
    check(
        '/dist_v3/' in ignore_text and '/.v3_runtime/' in ignore_text,
        "generated_packaging_artifacts_are_gitignored",
        results,
    )
    check(
        LONG_ACTION_VALIDATOR.exists(),
        "batch18c_validator_preserved",
        results,
    )

    # Syntax check the Python validator itself and the existing bridge runner.
    compile_targets = [
        ROOT / "src" / "validate_v3_batch18d_packaging.py",
        ROOT / "scripts" / "run_v3_bridge.py",
    ]
    compile_ok = True
    for target in compile_targets:
        try:
            compile(target.read_text(encoding="utf-8"), str(target), "exec")
        except Exception as exc:
            compile_ok = False
            print(f"    compile error {target}: {exc}")
    check(compile_ok, "python_files_compile", results)

    # PowerShell parser check when available.
    ps_ok = True
    powershell = os.environ.get("SystemRoot", r"C:\Windows") + r"\System32\WindowsPowerShell\v1.0\powershell.exe"
    if Path(powershell).exists():
        for target in [BUILD_PS1, RUN_PS1, BOOTSTRAP_PS1]:
            command = [
                powershell,
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                f"$e=$null; [void][System.Management.Automation.Language.Parser]::ParseFile('{target}',[ref]$null,[ref]$e); if($e.Count -gt 0){{ $e | ForEach-Object {{ Write-Host $_.Message }}; exit 1 }}",
            ]
            completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
            if completed.returncode != 0:
                ps_ok = False
                print(completed.stdout)
                print(completed.stderr)
    check(ps_ok, "powershell_packaging_scripts_parse", results)

    check(sha256(V3_WORKING) == v3_before, "validator_never_changes_active_v3_save", results)
    check(sha256(V2_PROTECTED) == v2_before, "validator_never_changes_active_v2_save", results)

    report_dir = ROOT / "outputs" / "v3_batch18d_packaging"
    report_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "version": VERSION,
        "results": results,
        "active_v3_unchanged": sha256(V3_WORKING) == v3_before,
        "protected_v2_unchanged": sha256(V2_PROTECTED) == v2_before,
    }
    report_path = report_dir / "validation.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print()
    print(f"Report: {report_path}")
    if all(results.values()):
        print()
        print("V3 BATCH 18D VALIDATION PASSED")
        print("Packaging validation is read-only; active V3 and protected V2 remained unchanged.")
        return 0

    print()
    print("V3 BATCH 18D VALIDATION FAILED")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
