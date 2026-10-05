"""Build a self-contained Windows playtest snapshot without touching live saves."""
from __future__ import annotations
import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'src')]

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--destination', type=Path, required=True)
    parser.add_argument('--python-zip', type=Path, required=True)
    parser.add_argument('--wheels', type=Path, required=True)
    parser.add_argument('--godot', type=Path, required=True)
    args = parser.parse_args()
    dest = args.destination.resolve()
    if dest.exists():
        raise RuntimeError('Use a new destination; existing bundles are never overwritten.')
    protected = [ROOT / 'outputs/runtime/v3_godot_working_checkpoint.pkl.gz', ROOT / 'outputs/runtime/franchise_mode_checkpoint_v1.pkl.gz']
    before = [sha(p) for p in protected]
    app = dest / 'app'
    runtime = dest / 'runtime/python'
    runtime.mkdir(parents=True)
    for folder in ['src', 'desktop_bridge', 'app_data', 'assets', 'data', 'models', 'godot_client']:
        source = ROOT / folder
        if source.exists():
            shutil.copytree(source, app / folder, ignore=shutil.ignore_patterns('__pycache__', '.godot', '.git', '*.import', '*.backup', '*_backup_*'))
    (app / 'scripts').mkdir()
    for name in ['run_v3_bridge.py', 'run_v3_bundle.ps1']:
        shutil.copy2(ROOT / 'scripts' / name, app / 'scripts' / name)
    launcher_path = app / 'scripts/run_v3_bundle.ps1'
    launcher = launcher_path.read_text()
    start = launcher.index('    if ($env:CONDA_DEFAULT_ENV')
    end = launcher.index('\n}\n', start)
    launcher = launcher[:start] + '    throw "Bundled Python is missing. Extract the entire ZIP again."\n' + launcher[end:]
    launcher = launcher.replace('"/v3/franchise-summary",', '"/v3/franchise-summary",\n        "/v3/rebuild-hq",')
    launcher_path.write_text(launcher, encoding='utf-8')
    with zipfile.ZipFile(args.python_zip) as archive:
        archive.extractall(runtime)
    (runtime / 'python312._pth').write_text('python312.zip\n.\nLib/site-packages\n../../app\n../../app/src\nimport site\n')
    # Runtime uses modules directly, not pip-generated command entry points.
    vendor = runtime / 'Lib/site-packages'
    vendor.mkdir(parents=True)
    for wheel in sorted(args.wheels.glob('*.whl')):
        with zipfile.ZipFile(wheel) as archive:
            archive.extractall(vendor)
    for data_dir in vendor.glob('*.data'):
        for kind in ['purelib', 'platlib']:
            folder = data_dir / kind
            if folder.exists():
                for child in folder.iterdir():
                    shutil.move(str(child), str(vendor / child.name))
    godot_dest = dest / 'runtime/godot'
    godot_dest.mkdir()
    shutil.copy2(args.godot, godot_dest / 'Godot_v4.0-stable_win64.exe')
    outputs = app / 'outputs'
    (outputs / 'runtime').mkdir(parents=True)
    for name in ['mixed_player_pick_team_cba_decision_release_v1.csv', 'mixed_player_pick_player_cba_decision_release_v1.csv', 'mixed_player_pick_right_legality_decision_release_v1.csv', 'mixed_player_pick_final_full_cba_rules_v1.json']:
        shutil.copy2(ROOT / 'outputs' / name, outputs / name)
    from desktop_bridge.save_manager_foundation import _build_certified_fresh_franchise_checkpoint
    fresh = _build_certified_fresh_franchise_checkpoint(team='BOS', target_path=outputs / 'runtime/franchise_mode_checkpoint_v1.pkl.gz')
    shutil.copy2(outputs / 'runtime/franchise_mode_checkpoint_v1.pkl.gz', outputs / 'runtime/v3_godot_working_checkpoint.pkl.gz')
    project = app / 'godot_client/project.godot'
    project.write_text(project.read_text().replace('config/name="NBA Franchise Simulator V3"', 'config/name="NBA Franchise Simulator V3 Playtest"\nconfig/use_custom_user_dir=true\nconfig/custom_user_dir_name="NBA_Franchise_V3_Playtest"'))
    (dest / 'Play.cmd').write_text('@echo off\nsetlocal\ncd /d "%~dp0"\npowershell.exe -NoProfile -ExecutionPolicy Bypass -File ".\\app\\scripts\\run_v3_bundle.ps1"\nif errorlevel 1 pause\n', encoding='ascii')
    (dest / 'THIRD_PARTY_NOTICES.txt').write_text('Godot Engine 4.0: https://godotengine.org/license/\nCopyright Godot Engine contributors; Juan Linietsky and Ariel Manzur. Godot and its bundled third-party license notices are linked above.\nPython license: runtime/python/LICENSE.txt\nPython library licenses and attribution: runtime/python/Lib/site-packages/*.dist-info (including licenses subdirectories).\nNBA team branding and player portraits retain their respective ownership; this is a private evaluation build.\n', encoding='utf-8')
    (dest / 'README.txt').write_text('NBA FRANCHISE SIMULATOR V3 - PRIVATE WINDOWS PLAYTEST\n\n1. Extract the entire ZIP to a writable folder, such as Documents.\n2. Double-click Play.cmd. No Python, Conda, Godot installation or administrator access is required.\n3. Allow initial loading to finish. Follow Rebuild HQ onboarding, then Development.\n4. Close the game normally to stop its backend.\n\nWindows 10/11 x64 only. One simulator instance at a time (local port 8765).\nGame progress stays inside app/outputs/runtime in this extracted folder.\nDo not run from inside the ZIP. Keep this folder to preserve your save.\n\nStarts a fresh Boston Celtics 2026-27 franchise, with no creator gameplay/save slots included.\nUse FRANCHISES to create a different team. Player portraits may require internet; missing portraits have fallbacks. Core gameplay runs locally.\n\nThis internal playtest bundles the existing Godot 4.0 runtime and project, rather than a signed installer. Latest local Expansion 49 changes are included.\n\nIf launch fails, send the exact message plus app/outputs/runtime/v3_desktop_bridge_stderr.log.\nPlease report: team/season/day, steps taken, expected behavior, actual behavior and a screenshot.\nTest development discovery, roster/roles, games, scouting, transactions and save/relaunch. Do not email private machine information in logs.\n', encoding='utf-8')
    head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    status = subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT, text=True)
    manifest = {'build_id': 'v3-playtest-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'), 'source_head': head, 'includes_uncommitted_working_tree': bool(status.strip()), 'source_status': status.splitlines(), 'api_version': '0.26.0', 'starter_franchise': fresh, 'python_zip_sha256': sha(args.python_zip), 'godot_sha256': sha(args.godot), 'wheels': {p.name: sha(p) for p in args.wheels.glob('*.whl')}, 'files': {p.relative_to(dest).as_posix(): sha(p) for p in dest.rglob('*') if p.is_file()}}
    (dest / 'BUILD_MANIFEST.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    assert before == [sha(p) for p in protected], 'Live save changed during build'
    print('PLAYTEST_BUILD_COMPLETE', dest, flush=True)
    print('LIVE_SAVES_UNCHANGED', flush=True)

if __name__ == '__main__':
    main()
