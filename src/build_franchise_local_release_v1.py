from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
RELEASE_VERSION = "nba-franchise-simulator-local-v1-2026-09-17"

ROOT_FILES = (
    ".gitignore",
    "Home.py",
    "LICENSE.md",
    "README.md",
    "requirements.txt",
)

RUNTIME_DATA_FILES = (
    "data/processed/trade_eligible_player_pool_2026_27.parquet",
    "data/processed/player_financial_layer_2026_27_v2.parquet",
    "data/processed/player_trade_market_value_layer_2026_27_v3.parquet",
    "data/processed/team_trade_salary_profiles_2026_27.csv",
    "data/processed/future_pick_optimizer_inventory_2027_2029_final.parquet",
    "data/processed/future_first_round_legality_calendar_2027_2034_v5_evidence_ingested.parquet",
    "data/reference/nba_current_reference_overlay_2026_09_07.csv",
    "data/reference/nba_player_movement_delta_2026_08_04_to_2026_09_07.csv",
)

RUNTIME_OUTPUT_FILES = (
    "outputs/mixed_player_pick_team_cba_decision_release_v1.csv",
    "outputs/mixed_player_pick_player_cba_decision_release_v1.csv",
    "outputs/mixed_player_pick_right_legality_decision_release_v1.csv",
    "outputs/mixed_player_pick_final_full_cba_rules_v1.json",
)

RELEASE_DOCS = (
    "docs/FRANCHISE_MODE_CURRENT_STATUS.md",
    "docs/FRANCHISE_MODE_MASTER_ROADMAP.md",
    "docs/FRANCHISE_MODE_RELEASE_CHECKLIST_V1.md",
    "docs/FRANCHISE_V2_ROADMAP.md",
    "docs/FRANCHISE_GAME_DAY_BROADCAST_V1.md",
    "docs/FRANCHISE_ONBOARDING_PROGRESSION_V1.md",
    "docs/FRANCHISE_RETENTION_EXPERIENCE_V1.md",
    "docs/NBA_REAL_STAFF_REFERENCE_V1.md",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _safe_relative(path: Path) -> str:
    resolved = path.resolve()
    try:
        relative = resolved.relative_to(ROOT.resolve())
    except ValueError as exc:
        raise RuntimeError(f"Release input is outside the project root: {path}") from exc
    return relative.as_posix()


def _production_python(directory: str) -> Iterable[Path]:
    root = ROOT / directory
    for path in sorted(root.glob("*.py")):
        name = path.name.lower()
        if "_backup_" not in name and not name.endswith("~"):
            yield path


def _app_data_files() -> Iterable[Path]:
    for path in sorted((ROOT / "app_data").iterdir()):
        if not path.is_file():
            continue
        name = path.name.lower()
        if "_backup_" in name or name.endswith(".tmp"):
            continue
        yield path


def _asset_files() -> Iterable[Path]:
    asset_root = ROOT / "assets"
    if not asset_root.is_dir():
        return
    for path in sorted(asset_root.rglob("*")):
        if path.is_file() and "__pycache__" not in path.parts:
            yield path


def release_files() -> list[Path]:
    candidates: list[Path] = []
    candidates.extend(ROOT / value for value in ROOT_FILES)
    candidates.extend(_production_python("pages"))
    candidates.extend(_production_python("src"))
    candidates.extend(_app_data_files())
    candidates.extend(_asset_files())
    candidates.extend(ROOT / value for value in RUNTIME_DATA_FILES)
    candidates.extend(ROOT / value for value in RUNTIME_OUTPUT_FILES)
    candidates.extend(ROOT / value for value in RELEASE_DOCS)

    missing = [str(path) for path in candidates if not path.is_file()]
    if missing:
        raise FileNotFoundError(
            "Required local-release inputs are missing:\n" + "\n".join(missing)
        )

    by_relative = {_safe_relative(path): path for path in candidates}
    files = [by_relative[key] for key in sorted(by_relative)]
    if not files:
        raise RuntimeError("The local-release allowlist resolved to no files.")
    return files


def build_release(output_dir: Path) -> tuple[Path, Path, dict[str, object]]:
    files = release_files()
    output_dir.mkdir(parents=True, exist_ok=True)
    archive = output_dir / "NBA_Franchise_Simulator_V1_2026-09-17.zip"

    entries = [
        {
            "path": _safe_relative(path),
            "size_bytes": path.stat().st_size,
            "sha256": _sha256(path),
        }
        for path in files
    ]
    manifest: dict[str, object] = {
        "release_version": RELEASE_VERSION,
        "built_at_utc": datetime.now(timezone.utc).isoformat(),
        "entry_point": "Home.py",
        "file_count": len(entries),
        "total_uncompressed_bytes": sum(int(row["size_bytes"]) for row in entries),
        "files": entries,
        "excluded_local_state": [
            "outputs/runtime",
            "outputs/franchise_*",
            "app_data/league_scenarios",
            "backups",
            "historical ZIPs and staging directories",
            "development-only data and model artifacts",
        ],
    }

    with zipfile.ZipFile(
        archive,
        mode="w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
    ) as bundle:
        for path in files:
            bundle.write(path, arcname=_safe_relative(path))
        bundle.writestr(
            "RELEASE_MANIFEST.json",
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        )

    with zipfile.ZipFile(archive, mode="r") as bundle:
        corrupt = bundle.testzip()
        if corrupt is not None:
            raise RuntimeError(f"Release archive integrity failed at {corrupt}.")
        names = set(bundle.namelist())
        for required in ("Home.py", "requirements.txt", "RELEASE_MANIFEST.json"):
            if required not in names:
                raise RuntimeError(f"Release archive is missing {required}.")

    sha_path = archive.with_suffix(archive.suffix + ".sha256")
    sha_path.write_text(f"{_sha256(archive)}  {archive.name}\n", encoding="utf-8")
    return archive, sha_path, manifest


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build the clean, save-free local NBA Franchise Simulator release."
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "outputs" / "releases",
    )
    args = parser.parse_args()

    archive, sha_path, manifest = build_release(args.output_dir.resolve())
    print("NBA FRANCHISE SIMULATOR LOCAL RELEASE V1")
    print(f"Archive: {archive}")
    print(f"SHA-256: {_sha256(archive)}")
    print(f"Sidecar: {sha_path}")
    print(f"Files: {manifest['file_count']}")
    print(
        "Uncompressed: "
        f"{int(manifest['total_uncompressed_bytes']) / (1024 * 1024):.2f} MB"
    )
    print("Active franchise save included: NO")
    print("LOCAL RELEASE BUILD: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
