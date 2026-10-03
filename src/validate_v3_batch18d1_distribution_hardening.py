from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

V3_WORKING = ROOT / "outputs" / "runtime" / "v3_godot_working_checkpoint.pkl.gz"
V2_PROTECTED = ROOT / "outputs" / "runtime" / "franchise_mode_checkpoint_v1.pkl.gz"

BUILD = ROOT / "scripts" / "build_v3_windows_bundle.ps1"
RUN = ROOT / "scripts" / "run_v3_bundle.ps1"
SETUP = ROOT / "scripts" / "bootstrap_v3_bundle_runtime.ps1"
B18D = ROOT / "src" / "validate_v3_batch18d_packaging.py"
B18C = ROOT / "src" / "validate_v3_batch18c_long_actions.py"

VERSION = "v3-distribution-hardening-batch-18d1-v1.1.0-2026-10-03"


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

    build = BUILD.read_text(encoding="utf-8")
    run = RUN.read_text(encoding="utf-8")
    setup = SETUP.read_text(encoding="utf-8")

    results: dict[str, bool] = {}

    print("=" * 100)
    print("V3 BATCH 18D.1 DISTRIBUTION HARDENING VALIDATION")
    print("=" * 100)

    check(
        '$outputsSource = Join-Path $RepoRoot "outputs"' not in build
        and 'Copy-Tree -Source $outputsSource' not in build,
        "full_development_outputs_copy_removed",
        results,
    )
    check(
        'franchise_mode_checkpoint_v1.pkl.gz' in build
        and 'Minimal runtime seed' in build,
        "protected_v2_is_explicit_runtime_seed",
        results,
    )
    check(
        'if ($IncludeCurrentSave)' in build
        and 'v3_godot_working_checkpoint.pkl.gz' in build
        and 'v3_save_manager' in build,
        "creator_v3_save_remains_explicit_opt_in",
        results,
    )
    check(
        '[double]$MaxBundleGB = 4.0' in build
        and 'exceeds the safety ceiling' in build,
        "builder_has_distribution_size_ceiling",
        results,
    )
    check(
        'bundle_bytes' in build
        and 'bundle_mb' in build
        and 'bundle_gb' in build,
        "build_manifest_records_bundle_size",
        results,
    )
    check(
        'if ($listener)' in run
        and 'Close any development V3 bridge' in run
        and '[OK] Existing bridge detected' not in run,
        "packaged_launcher_refuses_existing_bridge",
        results,
    )
    check(
        'Bundle-owned bridge healthy' in run
        and 'Shutting down bundle-owned bridge' in run,
        "packaged_launcher_owns_bridge_lifecycle",
        results,
    )
    check(
        'winget install' in setup
        and 'Python.Python.3.12' in setup,
        "runtime_setup_has_clean_machine_python_fallback",
        results,
    )
    check(
        'Bundle-local V3 server/checkpoint smoke: PASS' in setup
        and 'from desktop_bridge import server' in setup
        and 'load_franchise_checkpoint' in setup,
        "runtime_setup_smokes_full_server_and_checkpoint",
        results,
    )
    check(B18D.exists(), "batch18d_validator_preserved", results)
    check(B18C.exists(), "batch18c_validator_preserved", results)

    powershell = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    ps_ok = True
    if powershell.exists():
        for target in [BUILD, RUN, SETUP]:
            command = [
                str(powershell),
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
    check(ps_ok, "distribution_powershell_scripts_parse", results)

    check(sha256(V3_WORKING) == v3_before, "validator_never_changes_active_v3_save", results)
    check(sha256(V2_PROTECTED) == v2_before, "validator_never_changes_active_v2_save", results)

    report_dir = ROOT / "outputs" / "v3_batch18d1_distribution_hardening"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / "validation.json"
    report_path.write_text(
        json.dumps(
            {
                "version": VERSION,
                "results": results,
                "active_v3_unchanged": sha256(V3_WORKING) == v3_before,
                "protected_v2_unchanged": sha256(V2_PROTECTED) == v2_before,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    print()
    print(f"Report: {report_path}")
    if all(results.values()):
        print()
        print("V3 BATCH 18D.1 VALIDATION PASSED")
        print("Distribution hardening validation is read-only; development V3/V2 saves remained unchanged.")
        return 0

    print()
    print("V3 BATCH 18D.1 VALIDATION FAILED")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
