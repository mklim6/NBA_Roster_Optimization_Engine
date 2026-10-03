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
SETUP = ROOT / "scripts" / "bootstrap_v3_bundle_runtime.ps1"

REQUIRED_CBA_OUTPUTS = (
    "mixed_player_pick_team_cba_decision_release_v1.csv",
    "mixed_player_pick_player_cba_decision_release_v1.csv",
    "mixed_player_pick_right_legality_decision_release_v1.csv",
    "mixed_player_pick_final_full_cba_rules_v1.json",
)

VERSION = "v3-packaging-runtime-dependencies-batch-18d2-v1.2.0-2026-10-03"


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
    setup = SETUP.read_text(encoding="utf-8")
    results: dict[str, bool] = {}

    print("=" * 100)
    print("V3 BATCH 18D.2 PACKAGING RUNTIME DEPENDENCIES VALIDATION")
    print("=" * 100)

    check(
        'Copy-Tree -Source $outputsSource' not in build,
        "full_development_outputs_copy_still_absent",
        results,
    )

    for name in REQUIRED_CBA_OUTPUTS:
        check(
            name in build,
            f"builder_packages_{name}",
            results,
        )

    check(
        'Required packaged CBA runtime artifact is missing' in build,
        "builder_fails_closed_if_cba_dependency_missing",
        results,
    )
    check(
        'minimal-runtime-plus-cba-release-seed' in build,
        "manifest_declares_explicit_cba_seed_policy",
        results,
    )
    check(
        'packaged_cba_outputs' in build,
        "manifest_records_packaged_cba_dependencies",
        results,
    )
    check(
        'from freeform_trade_machine_engine_v3 import load_runtime_data' in setup
        and 'runtime=load_runtime_data()' in setup
        and 'Bundle-local V3 transaction runtime-data smoke: PASS' in setup,
        "runtime_setup_smokes_transaction_runtime_data",
        results,
    )
    check(
        'Bundle-local V3 server/checkpoint smoke: PASS' in setup,
        "legacy_runtime_smoke_marker_preserved",
        results,
    )

    # The source artifacts must exist before a distributable bundle can be built.
    for name in REQUIRED_CBA_OUTPUTS:
        check(
            (ROOT / "outputs" / name).is_file(),
            f"source_artifact_present_{name}",
            results,
        )

    powershell = (
        Path(os.environ.get("SystemRoot", r"C:\Windows"))
        / "System32/WindowsPowerShell/v1.0/powershell.exe"
    )
    ps_ok = True
    if powershell.exists():
        for target in (BUILD, SETUP):
            command = [
                str(powershell),
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                f"$e=$null; [void][System.Management.Automation.Language.Parser]::ParseFile('{target}',[ref]$null,[ref]$e); if($e.Count -gt 0){{ $e | ForEach-Object {{ Write-Host $_.Message }}; exit 1 }}",
            ]
            completed = subprocess.run(
                command,
                cwd=ROOT,
                capture_output=True,
                text=True,
            )
            if completed.returncode != 0:
                ps_ok = False
                print(completed.stdout)
                print(completed.stderr)
    check(ps_ok, "packaging_powershell_scripts_parse", results)

    check(
        sha256(V3_WORKING) == v3_before,
        "validator_never_changes_active_v3_save",
        results,
    )
    check(
        sha256(V2_PROTECTED) == v2_before,
        "validator_never_changes_active_v2_save",
        results,
    )

    report_dir = ROOT / "outputs" / "v3_batch18d2_packaging_runtime_dependencies"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / "validation.json"
    report_path.write_text(
        json.dumps(
            {
                "version": VERSION,
                "required_cba_outputs": list(REQUIRED_CBA_OUTPUTS),
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
        print("V3 BATCH 18D.2 VALIDATION PASSED")
        print("Packaging dependency validation is read-only; development V3/V2 saves remained unchanged.")
        return 0

    print()
    print("V3 BATCH 18D.2 VALIDATION FAILED")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
