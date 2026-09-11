from __future__ import annotations

import argparse
import csv
import hashlib
import json
import tempfile
import zipfile
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from franchise_free_agency_rights_population_v1 import (
    FREE_AGENCY_RIGHTS_POPULATION_VERSION,
    build_overlay_payload,
    build_rights_population_preview,
    default_overlay_path,
    preview_rows,
    source_rows,
    strict_preview_checks,
    write_overlay_atomic,
)

CONFIRM_TOKEN = "POPULATE_BIRD_RIGHTS_V1"


def sha256(path: Path) -> str:
    if not path.exists():
        return ""
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row:
            if key not in seen:
                fields.append(key)
                seen.add(key)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="Preview or apply verified Bird-rights population evidence.")
    parser.add_argument("--history", action="append", default=[], help="Explicit CSV/parquet player-team season-history source. May be repeated.")
    parser.add_argument("--apply", action="store_true", help="Write the season-scoped rights overlay after preview validation.")
    parser.add_argument("--confirm", default="", help=f"Required with --apply: {CONFIRM_TOKEN}")
    args = parser.parse_args()

    from simulation_franchise_checkpoint_v1 import DEFAULT_CHECKPOINT_PATH, load_franchise_checkpoint

    checkpoint_path = Path(DEFAULT_CHECKPOINT_PATH)
    before_hash = sha256(checkpoint_path)

    print("=" * 124, flush=True)
    print("VERIFIED BIRD-RIGHTS POPULATION V1", flush=True)
    print("=" * 124, flush=True)
    print("[1/6] Loading canonical franchise checkpoint and free-agent pool...", flush=True)
    durable = load_franchise_checkpoint()
    state = getattr(durable, "simulation_state", None)
    if state is None:
        raise RuntimeError("Durable checkpoint does not expose simulation_state.")

    print("[2/6] Discovering explicit player-team season-history evidence...", flush=True)
    preview = build_rights_population_preview(
        state,
        root=Path.cwd(),
        explicit_history_paths=args.history,
    )
    print(f"      History sources accepted: {preview.source_count}", flush=True)
    print(f"      Current free agents: {preview.free_agent_count}", flush=True)

    print("[3/6] Resolving exact Bird clocks without guessing trade/free-agent history...", flush=True)
    print(
        f"      Proven: {preview.proven_count} · Bird {preview.bird_count} · Early Bird {preview.early_bird_count} · Non-Bird {preview.non_bird_count} · unresolved {preview.unresolved_count}",
        flush=True,
    )

    print("[4/6] Running strict evidence-population checks...", flush=True)
    checks = strict_preview_checks(preview)
    for row in checks:
        print(f"      {row['check_id']}: {row['status']}", flush=True)
    failed = [row["check_id"] for row in checks if row["status"] == "FAIL"]
    if failed:
        raise RuntimeError(f"Rights population preview failed strict checks: {failed}")

    print("[5/6] Packaging auditable preview exports...", flush=True)
    out_dir = Path.cwd() / "outputs" / "audits"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    season = preview.season_label or "unknown-season"
    export_id = f"franchise_free_agency_rights_population_{season}_{stamp}"
    zip_path = out_dir / f"{export_id}.zip"
    with tempfile.TemporaryDirectory(prefix="fa_rights_population_") as tmp:
        root = Path(tmp) / export_id
        root.mkdir(parents=True, exist_ok=True)
        candidates = preview_rows(preview)
        unresolved = [row for row in candidates if row.get("status") == "unresolved"]
        proven = [row for row in candidates if row.get("status") in {"proven", "proven_existing_registry"}]
        write_csv(root / "rights_population_candidates.csv", candidates)
        write_csv(root / "rights_population_proven.csv", proven)
        write_csv(root / "rights_population_unresolved.csv", unresolved)
        write_csv(root / "rights_population_sources.csv", source_rows(preview))
        write_csv(root / "rights_population_checks.csv", checks)
        summary = {
            "version": FREE_AGENCY_RIGHTS_POPULATION_VERSION,
            "season_label": preview.season_label,
            "checkpoint_sha256": before_hash,
            "free_agent_count": preview.free_agent_count,
            "proven_count": preview.proven_count,
            "bird_count": preview.bird_count,
            "early_bird_count": preview.early_bird_count,
            "non_bird_count": preview.non_bird_count,
            "unresolved_count": preview.unresolved_count,
            "source_count": preview.source_count,
            "preview_fingerprint": preview.preview_fingerprint,
            "apply_requested": bool(args.apply),
            "overlay_path": str(default_overlay_path()),
        }
        (root / "rights_population_summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(root.iterdir()):
                archive.write(path, arcname=f"{export_id}/{path.name}")

    overlay_written = False
    overlay_recovery = None
    if args.apply:
        if args.confirm != CONFIRM_TOKEN:
            raise RuntimeError(f"--apply requires --confirm {CONFIRM_TOKEN}")
        print("      Explicit apply confirmed. Writing season-scoped verified rights overlay...", flush=True)
        payload = build_overlay_payload(preview, checkpoint_sha256=before_hash)
        overlay_path, overlay_recovery = write_overlay_atomic(payload)
        overlay_written = True
        print(f"      Rights overlay: {overlay_path}", flush=True)
        if overlay_recovery is not None:
            print(f"      Previous overlay recovery copy: {overlay_recovery}", flush=True)
    else:
        print("      PREVIEW ONLY: no runtime rights overlay was written.", flush=True)

    print("[6/6] Verifying canonical checkpoint remained byte-for-byte unchanged...", flush=True)
    after_hash = sha256(checkpoint_path)
    if before_hash != after_hash:
        raise RuntimeError("Canonical checkpoint hash changed during rights population preview/apply.")

    print("", flush=True)
    print("=" * 124, flush=True)
    print("VERIFIED BIRD-RIGHTS POPULATION V1 PASSED", flush=True)
    print("=" * 124, flush=True)
    print(f"Season: {preview.season_label}", flush=True)
    print(f"Proven rights rows: {preview.proven_count}/{preview.free_agent_count}", flush=True)
    print(f"Bird: {preview.bird_count} · Early Bird: {preview.early_bird_count} · Non-Bird: {preview.non_bird_count}", flush=True)
    print(f"Unresolved: {preview.unresolved_count}", flush=True)
    print(f"Preview ZIP: {zip_path}", flush=True)
    print(f"Preview ZIP SHA256: {sha256(zip_path)}", flush=True)
    print(f"Runtime overlay written: {overlay_written}", flush=True)
    print(f"Checkpoint SHA256 unchanged: {after_hash}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
