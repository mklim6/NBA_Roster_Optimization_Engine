from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import tempfile
import time
import unicodedata
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

VERSION = "fa-financial-contract-evidence-v1-2026-08-14"
SEASON_LABEL = "2026-27"
BASE = "https://www.salaryswish.com"
PLAYER_URL = BASE + "/players/{slug}"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/151.0.0.0 Safari/537.36"
)

SLUG_OVERRIDES = {
    "Cameron Payne": ["cam-payne"],
    "Bruce Brown": ["bruce-brown-jr"],
    "Xavier Tillman": ["xavier-tillman-sr"],
    "KJ Simpson": ["k-j-simpson"],
    "Darius Brown II": ["darius-brown"],
    "Trey Jemison III": ["trey-jemison"],
}

NAME_EQUIVALENTS = {
    "cameron payne": {"cam payne"},
    "bruce brown": {"bruce brown jr"},
    "xavier tillman": {"xavier tillman sr"},
    "kj simpson": {"k j simpson"},
    "darius brown ii": {"darius brown"},
    "trey jemison iii": {"trey jemison"},
}

class IdentityParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.in_title = False
        self.in_h1 = False
        self.title_parts: list[str] = []
        self.h1_parts: list[str] = []
        self.all_text: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.lower()
        if tag == "title":
            self.in_title = True
        elif tag == "h1":
            self.in_h1 = True

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "title":
            self.in_title = False
        elif tag == "h1":
            self.in_h1 = False

    def handle_data(self, data: str) -> None:
        text = " ".join(data.split())
        if not text:
            return
        self.all_text.append(text)
        if self.in_title:
            self.title_parts.append(text)
        if self.in_h1:
            self.h1_parts.append(text)

    @property
    def title(self) -> str:
        return " ".join(self.title_parts)

    @property
    def h1(self) -> str:
        return " ".join(self.h1_parts)

    @property
    def page_text(self) -> str:
        return "\n".join(self.all_text)

def clean(value: Any) -> str:
    return str(value or "").strip()

def pid(value: Any) -> str:
    text = clean(value)
    if text.endswith(".0") and text[:-2].isdigit():
        return text[:-2]
    return text

def norm_name(value: Any) -> str:
    text = unicodedata.normalize("NFKD", clean(value))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower()
    text = re.sub(r"\(two-way\)", "", text)
    text = re.sub(r"[.'’]", "", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())

def names_equivalent(a: str, b: str) -> bool:
    na = norm_name(a)
    nb = norm_name(b)
    if na == nb:
        return True
    if nb in NAME_EQUIVALENTS.get(na, set()):
        return True
    if na in NAME_EQUIVALENTS.get(nb, set()):
        return True
    return False

def slugify(name: str) -> str:
    text = unicodedata.normalize("NFKD", name)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower()
    text = re.sub(r"[.'’]", "", text)
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text

def slug_candidates(name: str) -> list[str]:
    result: list[str] = []
    for slug in SLUG_OVERRIDES.get(name, []):
        if slug not in result:
            result.append(slug)
    base = slugify(name)
    for slug in [
        base,
        re.sub(r"-(jr|sr|ii|iii|iv|v)$", "", base),
        base.replace("kj-", "k-j-"),
        base.replace("aj-", "a-j-"),
        base.replace("dj-", "d-j-"),
    ]:
        slug = slug.strip("-")
        if slug and slug not in result:
            result.append(slug)
    return result

def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def sha256_file(path: Path) -> str:
    if not path.exists() or not path.is_file():
        return ""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()

def fetch(url: str, timeout: int = 30) -> tuple[int, bytes, str]:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Cache-Control": "no-cache",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return int(getattr(response, "status", 200)), response.read(), ""
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read()
        except Exception:
            body = b""
        return int(exc.code), body, f"HTTPError: {exc}"
    except Exception as exc:
        return 0, b"", f"{type(exc).__name__}: {exc}"

def page_identity(body: bytes, player_name: str) -> tuple[bool, str, str, str]:
    if not body:
        return False, "", "", ""
    parser = IdentityParser()
    parser.feed(body.decode("utf-8", errors="ignore"))
    target = norm_name(player_name)
    title = norm_name(parser.title)
    h1 = norm_name(parser.h1)
    text = norm_name(parser.page_text[:200000])

    equivalents = {target} | NAME_EQUIVALENTS.get(target, set())
    identity = any(
        token and (token in title or token in h1)
        for token in equivalents
    )
    if not identity:
        identity = any(token and token in text for token in equivalents)

    bird_match = re.search(
        r"Bird Rights:\s*([^\n\r]{1,80})",
        parser.page_text,
        flags=re.IGNORECASE,
    )
    bird_text = clean(bird_match.group(1)) if bird_match else ""
    return identity, parser.title, parser.h1, bird_text

def fetch_verified(player_name: str, sleep_seconds: float) -> tuple[str, str, int, bytes, str, bool, str, str, str]:
    last = ("", "", 0, b"", "", False, "", "", "")
    for slug in slug_candidates(player_name):
        url = PLAYER_URL.format(slug=slug)
        status, body, error = fetch(url)
        identity, title, h1, bird_text = page_identity(body, player_name)
        last = (slug, url, status, body, error, identity, title, h1, bird_text)
        if status == 200 and body and identity:
            return last
        time.sleep(sleep_seconds)
    return last

def find_latest(root: Path, pattern: str, excludes: tuple[str, ...] = ()) -> Path:
    candidates = [
        p for p in root.rglob(pattern)
        if p.is_file()
        and not any(token in p.name.lower() for token in excludes)
    ]
    if not candidates:
        raise RuntimeError(f"Could not locate {pattern}")
    return max(candidates, key=lambda p: p.stat().st_mtime)

def read_csv_member(archive: zipfile.ZipFile, suffix: str) -> list[dict[str, str]]:
    name = next((n for n in archive.namelist() if n.endswith(suffix)), "")
    if not name:
        raise RuntimeError(f"ZIP missing {suffix}")
    return list(csv.DictReader(io.StringIO(archive.read(name).decode("utf-8-sig"))))

def read_json_member(archive: zipfile.ZipFile, suffix: str) -> dict[str, Any]:
    name = next((n for n in archive.namelist() if n.endswith(suffix)), "")
    if not name:
        raise RuntimeError(f"ZIP missing {suffix}")
    return json.loads(archive.read(name).decode("utf-8-sig"))

def checkpoint_path(root: Path) -> Path:
    try:
        from simulation_franchise_checkpoint_v1 import DEFAULT_CHECKPOINT_PATH
        return Path(DEFAULT_CHECKPOINT_PATH)
    except Exception:
        return root / "outputs" / "runtime" / "franchise_mode_checkpoint_v1.pkl.gz"

def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row:
            if key not in seen:
                seen.add(key)
                fields.append(key)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

def main() -> int:
    root = Path.cwd().resolve()

    continuity_zip = find_latest(
        root,
        "fa_rights_continuity_v2_preview_2026-27_*.zip",
    )
    population_zip = find_latest(
        root,
        "franchise_free_agency_rights_population_2026-27_*.zip",
        excludes=("provenance", "external", "continuity"),
    )
    evidence_zip = find_latest(
        root,
        "franchise_free_agency_rights_external_evidence_v1_0_1_2026-27_*.zip",
    )

    with zipfile.ZipFile(continuity_zip) as archive:
        continuity_summary = read_json_member(
            archive, "continuity_preview_summary.json"
        )
        resolved = read_csv_member(
            archive, "continuity_preview_resolved.csv"
        )
        preserved = read_csv_member(
            archive, "continuity_preview_preserved_v1.csv"
        )

    with zipfile.ZipFile(population_zip) as archive:
        population_proven = read_csv_member(
            archive, "rights_population_proven.csv"
        )

    with zipfile.ZipFile(evidence_zip) as archive:
        salary_rows = read_csv_member(
            archive, "rights_external_prior_salary_rows.csv"
        )
        tx_rows = read_csv_member(
            archive, "rights_external_transaction_rows.csv"
        )

    checkpoint = checkpoint_path(root)
    overlay = root / "outputs" / "runtime" / "free_agency_rights_population_v1.json"
    checkpoint_before = sha256_file(checkpoint)
    overlay_before = sha256_file(overlay)

    targets: dict[str, dict[str, Any]] = {}

    # All new Early Bird cases need direct contract-history support.
    for row in resolved:
        if clean(row.get("preview_rights_classification")) == "early_bird":
            player = pid(row.get("player_id"))
            targets[player] = {
                "player_id": player,
                "player_name": clean(row.get("player_name")),
                "rights_classification": "early_bird",
                "target_reason": "v2_early_bird_financial_basis",
                "current_salary_status": clean(row.get("salary_evidence_status")),
                "v1_or_v2": "v2",
            }

    # Multi-contract Non-Bird rows need the final applicable prior contract.
    for row in resolved:
        if (
            clean(row.get("preview_rights_classification")) == "non_bird"
            and clean(row.get("salary_evidence_status"))
            == "multiple_rows_require_contract_sequence"
        ):
            player = pid(row.get("player_id"))
            targets[player] = {
                "player_id": player,
                "player_name": clean(row.get("player_name")),
                "rights_classification": "non_bird",
                "target_reason": "v2_non_bird_multiple_2025_26_contracts",
                "current_salary_status": clean(row.get("salary_evidence_status")),
                "v1_or_v2": "v2",
            }

    # The 8 V1 Early Bird rows were proven before the 161-player salary harvest.
    # Add them so their financial basis can finally be populated.
    for row in population_proven:
        if clean(row.get("rights_classification")) == "early_bird":
            player = pid(row.get("player_id"))
            targets[player] = {
                "player_id": player,
                "player_name": clean(row.get("player_name")),
                "rights_classification": "early_bird",
                "target_reason": "v1_early_bird_missing_financial_basis",
                "current_salary_status": "not_harvested_in_161_unresolved_pass",
                "v1_or_v2": "v1",
            }

    target_rows = sorted(
        targets.values(),
        key=lambda r: (
            r["rights_classification"],
            r["player_name"].lower(),
        ),
    )
    target_ids = {row["player_id"] for row in target_rows}

    print("=" * 112, flush=True)
    print("FREE AGENCY FINANCIAL CONTRACT EVIDENCE V1", flush=True)
    print("=" * 112, flush=True)
    print(f"Continuity input: {continuity_zip}", flush=True)
    print(f"Target players:   {len(target_rows)}", flush=True)
    print(
        "Targets = all Early Bird cases + V2 Non-Bird rows with multiple 2025-26 salary rows.",
        flush=True,
    )
    print("", flush=True)

    existing_salary = [
        row for row in salary_rows
        if pid(row.get("player_id")) in target_ids
    ]
    existing_tx = [
        row for row in tx_rows
        if pid(row.get("player_id")) in target_ids
    ]

    manifest: list[dict[str, Any]] = []
    snapshot_payloads: dict[str, bytes] = {}
    sleep_seconds = 0.55

    for index, target in enumerate(target_rows, start=1):
        player_id = target["player_id"]
        player_name = target["player_name"]
        print(
            f"[{index:02d}/{len(target_rows):02d}] {player_name} ({player_id})",
            flush=True,
        )

        (
            slug,
            url,
            status,
            body,
            error,
            identity,
            title,
            h1,
            bird_text,
        ) = fetch_verified(player_name, sleep_seconds)

        body_sha = sha256_bytes(body) if body else ""
        if status == 200 and body and identity:
            snapshot_name = f"snapshots/{player_id}_{slug}.html"
            snapshot_payloads[snapshot_name] = body
            fetch_state = "verified_snapshot"
        else:
            snapshot_name = ""
            fetch_state = "manual_research_required"

        prior_salary_rows = [
            row for row in existing_salary
            if pid(row.get("player_id")) == player_id
        ]
        prior_tx_rows = [
            row for row in existing_tx
            if pid(row.get("player_id")) == player_id
        ]

        manifest.append({
            **target,
            "slug_used": slug,
            "source_url": url,
            "http_status": status,
            "page_identity_verified": identity,
            "page_title": title,
            "page_h1": h1,
            "page_bird_rights_text": bird_text,
            "snapshot_member": snapshot_name,
            "snapshot_sha256": body_sha,
            "snapshot_bytes": len(body),
            "fetch_error": error,
            "fetch_state": fetch_state,
            "existing_2025_26_salary_row_count": len(prior_salary_rows),
            "existing_transaction_row_count": len(prior_tx_rows),
            "classification_changed": False,
        })

        time.sleep(sleep_seconds)

    checkpoint_after = sha256_file(checkpoint)
    overlay_after = sha256_file(overlay)

    checks: list[dict[str, Any]] = []
    def check(
        check_id: str,
        passed: bool,
        detail: str,
        severity: str = "strict",
    ) -> None:
        checks.append({
            "check_id": check_id,
            "status": "PASS" if passed else "FAIL",
            "severity": severity,
            "detail": detail,
        })

    check(
        "continuity_preview_passed",
        bool(continuity_summary.get("passed")),
        "Financial evidence is built only from the passed V2 continuity preview.",
    )
    check(
        "all_target_ids_unique",
        len(target_ids) == len(target_rows),
        "Each target player appears exactly once.",
    )
    check(
        "target_scope_is_early_bird_or_multi_non_bird_only",
        all(
            row["rights_classification"] == "early_bird"
            or (
                row["rights_classification"] == "non_bird"
                and "multiple" in row["target_reason"]
            )
            for row in target_rows
        ),
        "No unrelated free agents are fetched.",
    )
    check(
        "successful_snapshots_have_identity",
        all(
            row["fetch_state"] != "verified_snapshot"
            or row["page_identity_verified"]
            for row in manifest
        ),
        "A page can only count if target-player identity is verified.",
    )
    check(
        "successful_snapshots_have_sha256",
        all(
            row["fetch_state"] != "verified_snapshot"
            or bool(row["snapshot_sha256"])
            for row in manifest
        ),
        "Every accepted source snapshot is fingerprinted.",
    )
    check(
        "no_rights_classification_changes",
        all(not row["classification_changed"] for row in manifest),
        "This is evidence collection only.",
    )
    check(
        "canonical_checkpoint_unchanged",
        checkpoint_before == checkpoint_after,
        "No durable franchise state is mutated.",
    )
    check(
        "rights_overlay_unchanged",
        overlay_before == overlay_after,
        "No rights registry is applied.",
    )
    check(
        "snapshot_coverage",
        sum(row["fetch_state"] == "verified_snapshot" for row in manifest)
        == len(manifest),
        (
            f"Verified snapshots: "
            f"{sum(row['fetch_state'] == 'verified_snapshot' for row in manifest)}"
            f"/{len(manifest)}"
        ),
        severity="coverage",
    )

    failed_strict = [
        row["check_id"]
        for row in checks
        if row["severity"] == "strict" and row["status"] == "FAIL"
    ]
    if failed_strict:
        raise RuntimeError(
            "Financial contract evidence V1 failed strict checks: "
            + ", ".join(failed_strict)
        )

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    export_id = f"fa_financial_contract_evidence_v1_{SEASON_LABEL}_{stamp}"
    out_dir = root / "outputs" / "audits"
    out_dir.mkdir(parents=True, exist_ok=True)
    zip_out = out_dir / f"{export_id}.zip"

    with tempfile.TemporaryDirectory(prefix="fafce1_") as tmpdir:
        export = Path(tmpdir) / export_id
        export.mkdir(parents=True)

        write_csv(export / "financial_contract_targets.csv", target_rows)
        write_csv(export / "financial_contract_manifest.csv", manifest)
        write_csv(export / "financial_existing_salary_rows.csv", existing_salary)
        write_csv(export / "financial_existing_transaction_rows.csv", existing_tx)
        write_csv(export / "financial_contract_checks.csv", checks)

        summary = {
            "version": VERSION,
            "season_label": SEASON_LABEL,
            "target_count": len(target_rows),
            "early_bird_target_count": sum(
                row["rights_classification"] == "early_bird"
                for row in target_rows
            ),
            "multi_non_bird_target_count": sum(
                row["rights_classification"] == "non_bird"
                for row in target_rows
            ),
            "verified_snapshot_count": sum(
                row["fetch_state"] == "verified_snapshot"
                for row in manifest
            ),
            "manual_snapshot_queue_count": sum(
                row["fetch_state"] != "verified_snapshot"
                for row in manifest
            ),
            "continuity_zip": str(continuity_zip),
            "continuity_zip_sha256": sha256_file(continuity_zip),
            "population_zip": str(population_zip),
            "population_zip_sha256": sha256_file(population_zip),
            "evidence_zip": str(evidence_zip),
            "evidence_zip_sha256": sha256_file(evidence_zip),
            "checkpoint_sha256_before": checkpoint_before,
            "checkpoint_sha256_after": checkpoint_after,
            "rights_overlay_sha256_before": overlay_before,
            "rights_overlay_sha256_after": overlay_after,
            "checkpoint_write_performed": False,
            "rights_overlay_write_performed": False,
            "classification_changes_performed": 0,
            "passed": not failed_strict,
            "failed_strict_checks": failed_strict,
            "purpose": (
                "Capture source-complete SalarySwish contract pages for every "
                "Early Bird case and every multi-contract Non-Bird case so the "
                "next resolver can associate each 2025-26 salary row with its "
                "actual contract, signing team, signing date, and contract type."
            ),
        }
        (export / "financial_contract_summary.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True),
            encoding="utf-8",
        )

        with zipfile.ZipFile(zip_out, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(export.iterdir()):
                archive.write(path, arcname=f"{export_id}/{path.name}")
            for member_name, body in sorted(snapshot_payloads.items()):
                archive.writestr(
                    f"{export_id}/{member_name}",
                    body,
                    compress_type=zipfile.ZIP_DEFLATED,
                )

    if sha256_file(checkpoint) != checkpoint_before:
        raise RuntimeError("Checkpoint changed after evidence export.")
    if sha256_file(overlay) != overlay_before:
        raise RuntimeError("Rights overlay changed after evidence export.")

    print("", flush=True)
    print("=" * 112, flush=True)
    print("FREE AGENCY FINANCIAL CONTRACT EVIDENCE V1 PASSED", flush=True)
    print("=" * 112, flush=True)
    print(
        f"Verified snapshots: "
        f"{sum(row['fetch_state'] == 'verified_snapshot' for row in manifest)}"
        f"/{len(manifest)}",
        flush=True,
    )
    print(f"Audit ZIP: {zip_out}", flush=True)
    print("Rights classifications changed: 0", flush=True)
    print("Checkpoint write: NOT PERFORMED", flush=True)
    print("Rights overlay write: NOT PERFORMED", flush=True)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
