from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import tempfile
import zipfile
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterable, Mapping

VERSION = "fa-rights-registry-v2-preview-2026-08-14"
SCHEMA_VERSION = "free-agency-rights-registry-preview-schema-v2"
SEASON_LABEL = "2026-27"
SIMULATION_SPLIT_DATE = date(2026, 4, 12)

EXPECTED_TOTAL = 187
EXPECTED_BIRD = 25
EXPECTED_EARLY_BIRD = 16
EXPECTED_NON_BIRD = 90
EXPECTED_NON_VFA = 54
EXPECTED_UNKNOWN = 2
EXPECTED_OVERLAY_CANDIDATES = 131
EXPECTED_SALARY_DEPENDENT = 106

RIGHTS_CLASSES = {"bird", "early_bird", "non_bird"}
NON_VFA_CATEGORIES = {
    "waiver_terminated_free_agent",
    "ten_day_free_agent",
}

class ContractTableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[list[list[str]]] = []
        self.depth = 0
        self.table: list[list[str]] | None = None
        self.row: list[str] | None = None
        self.cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.lower()
        if tag == "table":
            self.depth += 1
            if self.depth == 1:
                self.table = []
        elif self.depth == 1 and tag == "tr":
            self.row = []
        elif self.depth == 1 and self.row is not None and tag in {"td", "th"}:
            self.cell = []
        elif self.cell is not None and tag == "br":
            self.cell.append(" ")

    def handle_data(self, data: str) -> None:
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if self.depth == 1 and self.cell is not None and tag in {"td", "th"}:
            assert self.row is not None
            self.row.append(" ".join("".join(self.cell).split()))
            self.cell = None
        elif self.depth == 1 and self.row is not None and tag == "tr":
            if self.table is not None and any(self.row):
                self.table.append(self.row)
            self.row = None
        elif tag == "table" and self.depth:
            if self.depth == 1 and self.table is not None:
                self.tables.append(self.table)
                self.table = None
            self.depth -= 1

def clean(value: Any) -> str:
    return str(value or "").strip()

def pid(value: Any) -> str:
    text = clean(value)
    if text.endswith(".0") and text[:-2].isdigit():
        return text[:-2]
    return text

def as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return clean(value).lower() in {"1", "true", "yes", "y"}

def positive_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number > 0 and number == number and number != float("inf"):
        return number
    return None

def sha256_file(path: Path) -> str:
    if not path.exists() or not path.is_file():
        return ""
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()

def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def read_csv_member(archive: zipfile.ZipFile, suffix: str) -> list[dict[str, str]]:
    member = next((name for name in archive.namelist() if name.endswith(suffix)), "")
    if not member:
        raise RuntimeError(f"ZIP missing required member: {suffix}")
    return list(
        csv.DictReader(
            io.StringIO(archive.read(member).decode("utf-8-sig"))
        )
    )

def read_json_member(archive: zipfile.ZipFile, suffix: str) -> dict[str, Any]:
    member = next((name for name in archive.namelist() if name.endswith(suffix)), "")
    if not member:
        raise RuntimeError(f"ZIP missing required member: {suffix}")
    return json.loads(archive.read(member).decode("utf-8-sig"))

def find_latest(root: Path, pattern: str, excludes: tuple[str, ...] = ()) -> Path:
    candidates = [
        path for path in root.rglob(pattern)
        if path.is_file()
        and not any(token in path.name.lower() for token in excludes)
    ]
    if not candidates:
        raise RuntimeError(f"Could not locate required audit: {pattern}")
    return max(candidates, key=lambda path: path.stat().st_mtime)

def checkpoint_path(root: Path) -> Path:
    try:
        from simulation_franchise_checkpoint_v1 import DEFAULT_CHECKPOINT_PATH
        return Path(DEFAULT_CHECKPOINT_PATH)
    except Exception:
        return (
            root
            / "outputs"
            / "runtime"
            / "franchise_mode_checkpoint_v1.pkl.gz"
        )

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

def strip_html(value: str) -> str:
    return " ".join(re.sub(r"<[^>]+>", " ", value).split())

def parse_money(value: Any) -> float | None:
    match = re.search(r"\$([\d,]+(?:\.\d+)?)", clean(value))
    if not match:
        return None
    try:
        return float(match.group(1).replace(",", ""))
    except ValueError:
        return None

def normalize_header(row: list[str]) -> list[str]:
    return [
        re.sub(r"[^a-z0-9]+", "_", clean(cell).lower()).strip("_")
        for cell in row
    ]

def parse_contract_blocks(html_text: str) -> list[dict[str, Any]]:
    """
    Parse SalarySwish contract wrappers with stdlib only.

    Each returned block includes:
      contract_type
      signing_team
      signing_method
      signing_date
      2025-26 base salary, when present
    """
    parts = html_text.split('<div class="sw_playerContract__wrapper">')[1:]
    blocks: list[dict[str, Any]] = []

    for part in parts:
        title_match = re.search(
            r"sw_playerContract__title[^>]*>(.*?)</h6>",
            part,
            flags=re.IGNORECASE | re.DOTALL,
        )
        contract_type = (
            strip_html(title_match.group(1))
            if title_match
            else ""
        )

        page_text = strip_html(part[:70000])

        date_match = re.search(
            r"Signing Date\s*:\s*([A-Za-z]+\s+\d{1,2},\s+\d{4})",
            page_text,
        )
        signing_date: date | None = None
        if date_match:
            try:
                signing_date = datetime.strptime(
                    date_match.group(1),
                    "%B %d, %Y",
                ).date()
            except ValueError:
                signing_date = None

        team_match = re.search(
            r"Signing Team\s*:\s*([A-Z]{3})(?:\s|$)",
            page_text,
        )
        method_match = re.search(
            r"Signing Method\s*:\s*(.*?)\s+Signing Date\s*:",
            page_text,
        )

        parser = ContractTableParser()
        parser.feed(part)

        salary = None
        salary_text = ""
        salary_row: list[str] | None = None

        for table in parser.tables:
            if not table:
                continue
            header = normalize_header(table[0])
            if "season" not in header or "base_salary" not in header:
                continue
            season_index = header.index("season")
            base_index = header.index("base_salary")

            for row in table[1:]:
                if (
                    season_index < len(row)
                    and clean(row[season_index]).startswith("2025-26")
                    and base_index < len(row)
                ):
                    salary_text = clean(row[base_index])
                    salary = parse_money(salary_text)
                    salary_row = row
                    break
            if salary is not None:
                break

        blocks.append({
            "contract_type": contract_type,
            "signing_team": clean(team_match.group(1)) if team_match else "",
            "signing_method": clean(method_match.group(1)) if method_match else "",
            "signing_date": signing_date,
            "base_salary_2025_26": salary,
            "base_salary_2025_26_text": salary_text,
            "salary_row": salary_row or [],
        })

    return blocks

def latest_pre_split_contract_salary(
    html_text: str,
) -> dict[str, Any] | None:
    candidates = [
        block for block in parse_contract_blocks(html_text)
        if block["signing_date"] is not None
        and block["signing_date"] <= SIMULATION_SPLIT_DATE
        and positive_float(block["base_salary_2025_26"]) is not None
    ]
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda block: block["signing_date"],
    )

def archive_snapshot_map(
    archive: zipfile.ZipFile,
    *,
    contract_only: bool = False,
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for member in archive.namelist():
        if "/snapshots/" not in member or not member.endswith(".html"):
            continue
        if contract_only and not member.endswith("_contract.html"):
            continue
        match = re.search(r"/snapshots/(\d+)_", member)
        if not match:
            continue
        player_id = match.group(1)
        body = archive.read(member)
        result[player_id] = {
            "member": member,
            "html": body.decode("utf-8", errors="ignore"),
            "sha256": sha256_bytes(body),
        }
    return result

def salary_rows_by_player(
    rows: Iterable[Mapping[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for raw in rows:
        player_id = pid(raw.get("player_id"))
        if not player_id:
            continue
        result[player_id].append(dict(raw))
    return result

def numeric_salary_set(rows: Iterable[Mapping[str, Any]]) -> set[float]:
    values: set[float] = set()
    for row in rows:
        value = positive_float(row.get("base_salary_numeric"))
        if value is not None:
            values.add(value)
    return values

def v1_continuity_seasons(rights_classification: str) -> int:
    if rights_classification == "bird":
        return 3
    if rights_classification == "early_bird":
        return 2
    if rights_classification == "non_bird":
        return 1
    raise ValueError(f"Unsupported Veteran-FA rights class: {rights_classification}")

def assemble_from_archives(
    *,
    population_zip: Path,
    continuity_zip: Path,
    external_zip: Path,
    financial_zip: Path,
    reconciliation_zip: Path,
) -> dict[str, Any]:
    """
    Pure archive assembly. No checkpoint or overlay access occurs here.
    Used by main() and by package self-validation.
    """
    with zipfile.ZipFile(population_zip) as archive:
        population_summary = read_json_member(
            archive, "rights_population_summary.json"
        )
        population_candidates = read_csv_member(
            archive, "rights_population_candidates.csv"
        )

    with zipfile.ZipFile(continuity_zip) as archive:
        continuity_summary = read_json_member(
            archive, "continuity_preview_summary.json"
        )
        continuity_rows = read_csv_member(
            archive, "continuity_preview_resolved.csv"
        )

    with zipfile.ZipFile(external_zip) as archive:
        external_summary = read_json_member(
            archive, "rights_external_evidence_summary.json"
        )
        external_salary_rows = read_csv_member(
            archive, "rights_external_prior_salary_rows.csv"
        )

    with zipfile.ZipFile(financial_zip) as archive:
        financial_summary = read_json_member(
            archive, "financial_contract_summary.json"
        )
        financial_manifest = read_csv_member(
            archive, "financial_contract_manifest.csv"
        )
        financial_snapshots = archive_snapshot_map(archive)

    with zipfile.ZipFile(reconciliation_zip) as archive:
        reconciliation_summary = read_json_member(
            archive, "v1_proven_reconciliation_summary.json"
        )
        reconciliation_rows = read_csv_member(
            archive, "v1_proven_reconciliation.csv"
        )
        reconciliation_manifest = read_csv_member(
            archive, "v1_proven_source_manifest.csv"
        )
        reconciliation_contract_snapshots = archive_snapshot_map(
            archive,
            contract_only=True,
        )

    population_by_id = {
        pid(row.get("player_id")): row
        for row in population_candidates
    }
    continuity_by_id = {
        pid(row.get("player_id")): row
        for row in continuity_rows
    }
    reconciliation_by_id = {
        pid(row.get("player_id")): row
        for row in reconciliation_rows
    }
    salary_by_id = salary_rows_by_player(external_salary_rows)

    financial_manifest_by_id = {
        pid(row.get("player_id")): row
        for row in financial_manifest
    }
    reconciliation_contract_manifest_by_id = {
        pid(row.get("player_id")): row
        for row in reconciliation_manifest
        if clean(row.get("source_kind")) == "contract"
    }

    final_rows: list[dict[str, Any]] = []

    # 161 rows resolved by Continuity V2.
    for player_id, row in continuity_by_id.items():
        rights_class = clean(row.get("preview_rights_classification"))
        preview_status = clean(row.get("preview_status"))

        if rights_class in RIGHTS_CLASSES and preview_status == "proven":
            final_status = "verified_veteran_fa"
            final_class = rights_class
            category = "veteran_free_agent"
            overlay_eligible = True
            continuity_verified = True
        elif rights_class == "not_applicable":
            final_status = "verified_non_vfa"
            final_class = "not_applicable"
            category = clean(row.get("free_agent_category"))
            overlay_eligible = False
            continuity_verified = True
        else:
            final_status = "manual_review"
            final_class = "unknown"
            category = clean(row.get("free_agent_category"))
            overlay_eligible = False
            continuity_verified = False

        final_rows.append({
            "player_id": player_id,
            "player_name": clean(row.get("player_name")),
            "season_label": SEASON_LABEL,
            "final_status": final_status,
            "rights_classification": final_class,
            "free_agent_category": category,
            "prior_team": clean(row.get("preview_prior_team")),
            "continuity_verified": continuity_verified,
            "continuous_prior_seasons": (
                v1_continuity_seasons(final_class)
                if final_class in RIGHTS_CLASSES
                else None
            ),
            "years_of_service": clean(row.get("years_of_service")),
            "prior_regular_salary": None,
            "prior_regular_salary_status": "not_required",
            "prior_regular_salary_basis": "",
            "prior_regular_salary_source": "",
            "prior_regular_salary_source_fingerprint": "",
            "prior_average_player_salary": None,
            "early_bird_average_salary_branch_required": (
                final_class == "early_bird"
            ),
            "early_bird_exact_ceiling_ready": (
                final_class != "early_bird"
            ),
            "overlay_candidate": overlay_eligible,
            "classification_source": "continuity_v2",
            "classification_reason": clean(row.get("classification_reason")),
            "classification_fingerprint": clean(row.get("timeline_fingerprint")),
            "qualifying_seasons": clean(row.get("qualifying_seasons")),
            "original_population_evidence_fingerprint": clean(
                population_by_id.get(player_id, {}).get("evidence_fingerprint")
            ),
        })

    # Reconciled original 26 rows replace the Continuity V2 preserved placeholders.
    for player_id, row in reconciliation_by_id.items():
        final_class = clean(row.get("reconciled_rights_classification"))
        status = clean(row.get("reconciled_status"))
        category = clean(row.get("free_agent_category"))

        if final_class in RIGHTS_CLASSES and status in {"confirmed", "reclassified"}:
            final_status = "verified_veteran_fa"
            overlay_eligible = True
            continuity_verified = True
        elif final_class == "not_applicable":
            final_status = "verified_non_vfa"
            overlay_eligible = False
            continuity_verified = True
        else:
            final_status = "manual_review"
            final_class = "unknown"
            overlay_eligible = False
            continuity_verified = False

        pop = population_by_id.get(player_id, {})
        final_rows.append({
            "player_id": player_id,
            "player_name": clean(row.get("player_name")),
            "season_label": SEASON_LABEL,
            "final_status": final_status,
            "rights_classification": final_class,
            "free_agent_category": category,
            "prior_team": clean(row.get("v1_prior_team")),
            "continuity_verified": continuity_verified,
            "continuous_prior_seasons": (
                v1_continuity_seasons(final_class)
                if final_class in RIGHTS_CLASSES
                else None
            ),
            "years_of_service": clean(pop.get("years_of_service")),
            "prior_regular_salary": None,
            "prior_regular_salary_status": "not_required",
            "prior_regular_salary_basis": "",
            "prior_regular_salary_source": "",
            "prior_regular_salary_source_fingerprint": "",
            "prior_average_player_salary": None,
            "early_bird_average_salary_branch_required": (
                final_class == "early_bird"
            ),
            "early_bird_exact_ceiling_ready": (
                final_class != "early_bird"
            ),
            "overlay_candidate": overlay_eligible,
            "classification_source": "v1_reconciliation_v1_0_1",
            "classification_reason": clean(row.get("classification_reason")),
            "classification_fingerprint": clean(row.get("timeline_fingerprint")),
            "qualifying_seasons": clean(row.get("observed_qualifying_seasons")),
            "original_population_evidence_fingerprint": clean(
                pop.get("evidence_fingerprint")
            ),
        })

    final_by_id = {
        row["player_id"]: row
        for row in final_rows
    }

    # Resolve salary-dependent Early Bird + Non-Bird rows.
    salary_resolution_rows: list[dict[str, Any]] = []
    salary_crosscheck_failures: list[str] = []

    for player_id, final in sorted(final_by_id.items()):
        rights_class = final["rights_classification"]
        if rights_class not in {"early_bird", "non_bird"}:
            continue

        source_kind = ""
        source_ref = ""
        source_fp = ""
        contract_type = ""
        signing_team = ""
        signing_method = ""
        signing_date = ""
        selected_salary: float | None = None
        crosscheck_status = ""

        continuity = continuity_by_id.get(player_id)
        external_rows = salary_by_id.get(player_id, [])
        external_values = numeric_salary_set(external_rows)

        # Original V1 reconciled Early Bird rows are not part of the 161-player
        # external salary harvest, so use the verified contract snapshots.
        if player_id in reconciliation_by_id:
            snapshot = financial_snapshots.get(player_id)
            manifest = financial_manifest_by_id.get(player_id)

            if snapshot is None:
                snapshot = reconciliation_contract_snapshots.get(player_id)
                manifest = reconciliation_contract_manifest_by_id.get(player_id)

            selected = (
                latest_pre_split_contract_salary(snapshot["html"])
                if snapshot is not None
                else None
            )
            if selected is not None:
                selected_salary = positive_float(
                    selected["base_salary_2025_26"]
                )
                source_kind = "verified_contract_snapshot"
                source_ref = clean(
                    (
                        manifest.get("source_url")
                        or manifest.get("url")
                    )
                    if manifest
                    else snapshot.get("member")
                )
                source_fp = clean(
                    manifest.get("snapshot_sha256")
                    if manifest and manifest.get("snapshot_sha256")
                    else manifest.get("body_sha256")
                    if manifest
                    else snapshot.get("sha256")
                )
                contract_type = clean(selected["contract_type"])
                signing_team = clean(selected["signing_team"])
                signing_method = clean(selected["signing_method"])
                signing_date = (
                    selected["signing_date"].isoformat()
                    if selected["signing_date"]
                    else ""
                )
                crosscheck_status = "snapshot_identity_verified"
            else:
                crosscheck_status = "missing_verified_contract_salary"

        elif continuity is not None:
            salary_status = clean(
                continuity.get("salary_evidence_status")
            )

            if salary_status == "single_standard_salary_ready":
                selected_salary = positive_float(
                    continuity.get("proposed_prior_regular_salary")
                )
                source_kind = "external_salary_single_standard"
                source_ref = (
                    clean(external_rows[0].get("source_url"))
                    if external_rows
                    else ""
                )
                source_fp = (
                    clean(external_rows[0].get("source_sha256"))
                    if external_rows
                    else ""
                )
                contract_type = clean(continuity.get("final_contract_type"))
                crosscheck_status = (
                    "matched_external_salary"
                    if selected_salary in external_values
                    else "external_salary_mismatch"
                )

            elif salary_status == "two_way_salary_requires_financial_rule_review":
                if len(external_values) == 1:
                    selected_salary = next(iter(external_values))
                source_kind = "external_salary_two_way"
                source_ref = (
                    clean(external_rows[0].get("source_url"))
                    if external_rows
                    else ""
                )
                source_fp = (
                    clean(external_rows[0].get("source_sha256"))
                    if external_rows
                    else ""
                )
                contract_type = clean(continuity.get("final_contract_type"))
                crosscheck_status = (
                    "two_way_salary_unique"
                    if selected_salary is not None
                    else "two_way_salary_ambiguous"
                )

            elif salary_status == "multiple_rows_require_contract_sequence":
                snapshot = financial_snapshots.get(player_id)
                manifest = financial_manifest_by_id.get(player_id)
                selected = (
                    latest_pre_split_contract_salary(snapshot["html"])
                    if snapshot is not None
                    else None
                )
                if selected is not None:
                    selected_salary = positive_float(
                        selected["base_salary_2025_26"]
                    )
                    source_kind = "financial_contract_sequence"
                    source_ref = clean(
                        manifest.get("source_url")
                        if manifest
                        else snapshot.get("member")
                    )
                    source_fp = clean(
                        manifest.get("snapshot_sha256")
                        if manifest and manifest.get("snapshot_sha256")
                        else snapshot.get("sha256")
                    )
                    contract_type = clean(selected["contract_type"])
                    signing_team = clean(selected["signing_team"])
                    signing_method = clean(selected["signing_method"])
                    signing_date = (
                        selected["signing_date"].isoformat()
                        if selected["signing_date"]
                        else ""
                    )
                    crosscheck_status = (
                        "selected_salary_matches_external_row"
                        if selected_salary in external_values
                        else "selected_salary_not_in_external_rows"
                    )
                else:
                    crosscheck_status = "contract_sequence_unresolved"
            else:
                crosscheck_status = f"unsupported_salary_status:{salary_status}"

        if selected_salary is None:
            final["prior_regular_salary_status"] = "unresolved"
        else:
            final["prior_regular_salary"] = selected_salary
            final["prior_regular_salary_status"] = "verified"
            final["prior_regular_salary_basis"] = (
                "2025-26 Two-Way Base Compensation; Two-Way contracts "
                "contain no bonuses or incentive compensation"
                if "Two-Way" in contract_type
                or source_kind == "external_salary_two_way"
                else "latest applicable pre-split 2025-26 contract Base Salary"
            )
            final["prior_regular_salary_source"] = source_ref
            final["prior_regular_salary_source_fingerprint"] = source_fp

        if crosscheck_status in {
            "external_salary_mismatch",
            "two_way_salary_ambiguous",
            "selected_salary_not_in_external_rows",
            "contract_sequence_unresolved",
            "missing_verified_contract_salary",
        }:
            salary_crosscheck_failures.append(
                f"{player_id}:{final['player_name']}:{crosscheck_status}"
            )

        salary_resolution_rows.append({
            "player_id": player_id,
            "player_name": final["player_name"],
            "rights_classification": rights_class,
            "prior_regular_salary": selected_salary,
            "salary_resolution_status": final["prior_regular_salary_status"],
            "salary_source_kind": source_kind,
            "salary_source": source_ref,
            "salary_source_fingerprint": source_fp,
            "contract_type": contract_type,
            "signing_team": signing_team,
            "signing_method": signing_method,
            "signing_date": signing_date,
            "external_salary_values": "|".join(
                str(int(value) if value.is_integer() else value)
                for value in sorted(external_values)
            ),
            "crosscheck_status": crosscheck_status,
            "simulation_split_date": SIMULATION_SPLIT_DATE.isoformat(),
        })

    # Any Bird row may carry no prior salary. That is acceptable for the
    # current Bird classification route, which is max-salary based.
    final_rows = sorted(
        final_by_id.values(),
        key=lambda row: (row["player_name"].lower(), row["player_id"]),
    )

    overlay_candidates = [
        row for row in final_rows
        if row["overlay_candidate"]
    ]
    non_vfa_rows = [
        row for row in final_rows
        if row["final_status"] == "verified_non_vfa"
    ]
    manual_rows = [
        row for row in final_rows
        if row["final_status"] == "manual_review"
    ]

    candidate_registry: dict[str, dict[str, Any]] = {}
    for row in overlay_candidates:
        rights_class = row["rights_classification"]
        candidate_registry[row["player_id"]] = {
            # Fields below are deliberately compatible with the existing
            # evidence row contract, but this JSON itself is preview-only.
            "version": "free-agency-rights-evidence-v2-preview",
            "player_id": row["player_id"],
            "prior_team": row["prior_team"],
            "continuous_prior_seasons": int(
                row["continuous_prior_seasons"]
            ),
            "continuity_verified": True,
            "prior_regular_salary": row["prior_regular_salary"],
            "prior_average_player_salary": None,
            "restricted_free_agent": False,
            "qualifying_offer_amount": None,
            "source": (
                f"{VERSION}:{row['classification_source']}"
            ),
            "rights_classification_preview": rights_class,
            "classification_fingerprint": row["classification_fingerprint"],
            "original_population_evidence_fingerprint": (
                row["original_population_evidence_fingerprint"]
            ),
            "prior_regular_salary_status": (
                row["prior_regular_salary_status"]
            ),
            "prior_regular_salary_source": (
                row["prior_regular_salary_source"]
            ),
            "prior_regular_salary_source_fingerprint": (
                row["prior_regular_salary_source_fingerprint"]
            ),
            "early_bird_average_salary_branch_required": (
                rights_class == "early_bird"
            ),
            "early_bird_exact_ceiling_ready": False
            if rights_class == "early_bird"
            else True,
            "preview_only": True,
        }

    candidate_payload = {
        "version": VERSION,
        "schema_version": SCHEMA_VERSION,
        "preview_only": True,
        "live_apply_ready": False,
        "season_label": SEASON_LABEL,
        "simulation_split_date": SIMULATION_SPLIT_DATE.isoformat(),
        "registry": candidate_registry,
        "financial_boundary": {
            "early_bird_average_salary_branch_status": (
                "requires canonical engine constant before live overlay"
            ),
            "prior_average_player_salary_written": False,
            "reason": (
                "The current exception engine requires the 105% prior Average "
                "Player Salary branch to mark an Early Bird ceiling exact. "
                "This preview resolves every prior Regular Salary but does not "
                "invent an exact Average Player Salary from rounded publications."
            ),
        },
    }

    return {
        "population_summary": population_summary,
        "continuity_summary": continuity_summary,
        "external_summary": external_summary,
        "financial_summary": financial_summary,
        "reconciliation_summary": reconciliation_summary,
        "population_candidates": population_candidates,
        "final_rows": final_rows,
        "overlay_candidates": overlay_candidates,
        "non_vfa_rows": non_vfa_rows,
        "manual_rows": manual_rows,
        "salary_resolution_rows": salary_resolution_rows,
        "salary_crosscheck_failures": salary_crosscheck_failures,
        "candidate_payload": candidate_payload,
        "financial_manifest": financial_manifest,
        "reconciliation_contract_manifest": reconciliation_contract_manifest_by_id,
    }

def main() -> int:
    root = Path.cwd().resolve()

    population_zip = find_latest(
        root,
        "franchise_free_agency_rights_population_2026-27_*.zip",
        excludes=("provenance", "external", "continuity"),
    )
    continuity_zip = find_latest(
        root,
        "fa_rights_continuity_v2_preview_2026-27_*.zip",
    )
    external_zip = find_latest(
        root,
        "franchise_free_agency_rights_external_evidence_v1_0_1_2026-27_*.zip",
    )
    financial_zip = find_latest(
        root,
        "fa_financial_contract_evidence_v1_2026-27_*.zip",
    )
    reconciliation_zip = find_latest(
        root,
        "fa_v1_proven_reconciliation_v1_0_1_2026-27_*.zip",
    )

    checkpoint = checkpoint_path(root)
    overlay = (
        root
        / "outputs"
        / "runtime"
        / "free_agency_rights_population_v1.json"
    )

    checkpoint_before = sha256_file(checkpoint)
    overlay_before = sha256_file(overlay)

    print("=" * 120, flush=True)
    print("FINAL 187-PLAYER FREE AGENCY RIGHTS REGISTRY V2 PREVIEW", flush=True)
    print("=" * 120, flush=True)
    print(f"Population:     {population_zip}", flush=True)
    print(f"Continuity V2: {continuity_zip}", flush=True)
    print(f"External V1.0.1: {external_zip}", flush=True)
    print(f"Financial V1:  {financial_zip}", flush=True)
    print(f"V1 reconciliation: {reconciliation_zip}", flush=True)
    print("", flush=True)
    print("READ-ONLY PREVIEW. NO RIGHTS OVERLAY WILL BE WRITTEN.", flush=True)
    print("", flush=True)

    assembled = assemble_from_archives(
        population_zip=population_zip,
        continuity_zip=continuity_zip,
        external_zip=external_zip,
        financial_zip=financial_zip,
        reconciliation_zip=reconciliation_zip,
    )

    final_rows = assembled["final_rows"]
    overlay_candidates = assembled["overlay_candidates"]
    non_vfa_rows = assembled["non_vfa_rows"]
    manual_rows = assembled["manual_rows"]
    salary_resolution = assembled["salary_resolution_rows"]

    counts = Counter(row["rights_classification"] for row in final_rows)
    status_counts = Counter(row["final_status"] for row in final_rows)

    input_summaries = [
        assembled["population_summary"],
        assembled["continuity_summary"],
        assembled["external_summary"],
        assembled["financial_summary"],
        assembled["reconciliation_summary"],
    ]

    expected_checkpoint_hashes = {
        clean(summary.get("checkpoint_sha256"))
        or clean(summary.get("checkpoint_sha256_after"))
        for summary in input_summaries
        if (
            clean(summary.get("checkpoint_sha256"))
            or clean(summary.get("checkpoint_sha256_after"))
        )
    }

    expected_overlay_hashes = {
        clean(summary.get("rights_overlay_sha256_after"))
        for summary in input_summaries
        if "rights_overlay_sha256_after" in summary
    }

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
        print(
            f"  {check_id}: {'PASS' if passed else 'FAIL'}",
            flush=True,
        )

    print("[1/4] Validating input audit lineage...", flush=True)
    check(
        "all_upstream_previews_passed",
        all(
            bool(summary.get("passed", True))
            for summary in (
                assembled["continuity_summary"],
                assembled["external_summary"],
                assembled["financial_summary"],
                assembled["reconciliation_summary"],
            )
        ),
        "Continuity, external evidence, focused financial evidence, and V1 reconciliation all passed.",
    )
    check(
        "input_population_count_is_187",
        len(assembled["population_candidates"]) == EXPECTED_TOTAL,
        "Original free-agent universe remains exactly 187 players.",
    )
    check(
        "checkpoint_anchors_are_consistent",
        len(expected_checkpoint_hashes) == 1
        and checkpoint_before in expected_checkpoint_hashes,
        (
            f"upstream={sorted(expected_checkpoint_hashes)} "
            f"current={checkpoint_before}"
        ),
    )
    check(
        "overlay_anchors_are_consistent",
        len(expected_overlay_hashes) <= 1
        and (
            not expected_overlay_hashes
            or overlay_before in expected_overlay_hashes
        ),
        (
            f"upstream={sorted(expected_overlay_hashes)} "
            f"current={overlay_before or '<absent>'}"
        ),
    )

    print("[2/4] Validating final 187-player rights partition...", flush=True)
    final_ids = {row["player_id"] for row in final_rows}
    population_ids = {
        pid(row.get("player_id"))
        for row in assembled["population_candidates"]
    }

    check(
        "final_registry_preview_has_exactly_187_unique_players",
        len(final_rows) == EXPECTED_TOTAL
        and len(final_ids) == EXPECTED_TOTAL
        and final_ids == population_ids,
        "Exactly one final disposition exists for every original free agent.",
    )
    check(
        "final_rights_counts_match_reconciled_expectation",
        counts.get("bird", 0) == EXPECTED_BIRD
        and counts.get("early_bird", 0) == EXPECTED_EARLY_BIRD
        and counts.get("non_bird", 0) == EXPECTED_NON_BIRD
        and counts.get("not_applicable", 0) == EXPECTED_NON_VFA
        and counts.get("unknown", 0) == EXPECTED_UNKNOWN,
        f"counts={dict(sorted(counts.items()))}",
    )
    check(
        "overlay_candidate_count_is_131",
        len(overlay_candidates) == EXPECTED_OVERLAY_CANDIDATES
        and all(
            row["rights_classification"] in RIGHTS_CLASSES
            and row["continuity_verified"]
            for row in overlay_candidates
        ),
        "Only verified Veteran-FA Bird/Early Bird/Non-Bird rows enter the candidate registry.",
    )
    check(
        "non_vfa_count_is_54",
        len(non_vfa_rows) == EXPECTED_NON_VFA
        and all(
            row["rights_classification"] == "not_applicable"
            for row in non_vfa_rows
        ),
        "Waiver-terminated / last-10-day categories remain outside the Veteran-FA registry.",
    )
    check(
        "manual_queue_is_exactly_two",
        len(manual_rows) == EXPECTED_UNKNOWN,
        "Only the genuinely unresolved rights cases remain manual.",
    )

    print("[3/4] Validating prior-Regular-Salary resolution...", flush=True)
    salary_dependent = [
        row for row in overlay_candidates
        if row["rights_classification"] in {"early_bird", "non_bird"}
    ]
    salary_resolved = [
        row for row in salary_dependent
        if positive_float(row["prior_regular_salary"]) is not None
        and row["prior_regular_salary_status"] == "verified"
    ]

    check(
        "salary_dependent_candidate_count_is_106",
        len(salary_dependent) == EXPECTED_SALARY_DEPENDENT,
        "16 Early Bird + 90 Non-Bird rows require a prior Regular Salary basis.",
    )
    check(
        "all_106_salary_dependent_rows_are_resolved",
        len(salary_resolved) == EXPECTED_SALARY_DEPENDENT,
        f"resolved={len(salary_resolved)}/{EXPECTED_SALARY_DEPENDENT}",
    )
    check(
        "multi_contract_salary_selection_crosschecks_pass",
        not assembled["salary_crosscheck_failures"],
        (
            "All selected multi-contract salaries match the harvested 2025-26 salary evidence. "
            f"failures={assembled['salary_crosscheck_failures']}"
        ),
    )
    check(
        "all_106_resolved_salaries_have_source_provenance",
        all(
            clean(row["prior_regular_salary_source"])
            and clean(row["prior_regular_salary_source_fingerprint"])
            for row in salary_resolved
        ),
        "Every salary-dependent registry row retains a source URL/member and source-page fingerprint.",
    )
    check(
        "early_bird_rows_have_prior_salary_but_do_not_fake_average_salary",
        all(
            positive_float(row["prior_regular_salary"]) is not None
            and row["prior_average_player_salary"] is None
            and not row["early_bird_exact_ceiling_ready"]
            for row in overlay_candidates
            if row["rights_classification"] == "early_bird"
        ),
        "All 16 Early Bird prior salaries are resolved while the exact 105% Average Player Salary branch remains explicitly pending.",
    )

    print("[4/4] Verifying read-only durable-state safety...", flush=True)
    checkpoint_after = sha256_file(checkpoint)
    overlay_after = sha256_file(overlay)

    check(
        "canonical_checkpoint_unchanged",
        checkpoint_before == checkpoint_after,
        f"checkpoint={checkpoint_after}",
    )
    check(
        "rights_overlay_unchanged",
        overlay_before == overlay_after,
        f"overlay={overlay_after or '<absent>'}",
    )
    check(
        "candidate_payload_is_preview_only",
        assembled["candidate_payload"].get("preview_only") is True
        and assembled["candidate_payload"].get("live_apply_ready") is False,
        "Candidate JSON cannot be mistaken for an approved live overlay.",
    )

    failed_strict = [
        row["check_id"]
        for row in checks
        if row["severity"] == "strict"
        and row["status"] == "FAIL"
    ]
    if failed_strict:
        raise RuntimeError(
            "Final Rights Registry V2 Preview failed strict checks: "
            + ", ".join(failed_strict)
        )

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    export_id = f"fa_rights_registry_v2_preview_{SEASON_LABEL}_{stamp}"
    out_dir = root / "outputs" / "audits"
    out_dir.mkdir(parents=True, exist_ok=True)
    zip_out = out_dir / f"{export_id}.zip"

    input_manifest = [
        {
            "input_kind": "population_v1",
            "path": str(population_zip),
            "sha256": sha256_file(population_zip),
        },
        {
            "input_kind": "continuity_v2",
            "path": str(continuity_zip),
            "sha256": sha256_file(continuity_zip),
        },
        {
            "input_kind": "external_evidence_v1_0_1",
            "path": str(external_zip),
            "sha256": sha256_file(external_zip),
        },
        {
            "input_kind": "financial_contract_evidence_v1",
            "path": str(financial_zip),
            "sha256": sha256_file(financial_zip),
        },
        {
            "input_kind": "v1_proven_reconciliation_v1_0_1",
            "path": str(reconciliation_zip),
            "sha256": sha256_file(reconciliation_zip),
        },
    ]

    with tempfile.TemporaryDirectory(prefix="farrv2_") as tmpdir:
        export = Path(tmpdir) / export_id
        export.mkdir(parents=True)

        write_csv(export / "final_rights_registry_preview.csv", final_rows)
        write_csv(
            export / "final_rights_overlay_candidates.csv",
            overlay_candidates,
        )
        write_csv(export / "final_rights_non_vfa.csv", non_vfa_rows)
        write_csv(export / "final_rights_manual_queue.csv", manual_rows)
        write_csv(
            export / "final_rights_salary_resolution.csv",
            salary_resolution,
        )
        write_csv(export / "final_rights_input_manifest.csv", input_manifest)
        write_csv(export / "final_rights_checks.csv", checks)

        candidate_payload = dict(assembled["candidate_payload"])
        candidate_payload.update({
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "checkpoint_sha256_at_generation": checkpoint_before,
            "existing_rights_overlay_sha256_at_generation": overlay_before,
            "input_fingerprints": {
                row["input_kind"]: row["sha256"]
                for row in input_manifest
            },
            "summary": {
                "total_free_agents": EXPECTED_TOTAL,
                "bird": counts.get("bird", 0),
                "early_bird": counts.get("early_bird", 0),
                "non_bird": counts.get("non_bird", 0),
                "not_applicable": counts.get("not_applicable", 0),
                "unknown": counts.get("unknown", 0),
                "overlay_candidates": len(overlay_candidates),
                "salary_dependent_candidates": len(salary_dependent),
                "salary_resolved_candidates": len(salary_resolved),
            },
        })
        (export / "final_rights_registry_candidate.json").write_text(
            json.dumps(
                candidate_payload,
                indent=2,
                sort_keys=True,
                default=str,
            ),
            encoding="utf-8",
        )

        summary = {
            "version": VERSION,
            "schema_version": SCHEMA_VERSION,
            "season_label": SEASON_LABEL,
            "simulation_split_date": SIMULATION_SPLIT_DATE.isoformat(),
            "passed": True,
            "failed_strict_checks": [],
            "total_free_agents": len(final_rows),
            "rights_classification_counts": dict(sorted(counts.items())),
            "status_counts": dict(sorted(status_counts.items())),
            "overlay_candidate_count": len(overlay_candidates),
            "non_vfa_count": len(non_vfa_rows),
            "manual_review_count": len(manual_rows),
            "manual_review_players": [
                {
                    "player_id": row["player_id"],
                    "player_name": row["player_name"],
                }
                for row in manual_rows
            ],
            "salary_dependent_candidate_count": len(salary_dependent),
            "salary_resolved_candidate_count": len(salary_resolved),
            "salary_crosscheck_failures": assembled["salary_crosscheck_failures"],
            "early_bird_exact_ceiling_ready_count": sum(
                bool(row["early_bird_exact_ceiling_ready"])
                for row in overlay_candidates
                if row["rights_classification"] == "early_bird"
            ),
            "early_bird_exact_ceiling_pending_count": sum(
                not bool(row["early_bird_exact_ceiling_ready"])
                for row in overlay_candidates
                if row["rights_classification"] == "early_bird"
            ),
            "live_apply_ready": False,
            "blocking_live_apply_item": (
                "Install a canonical 2026-27 Early Bird 105%-of-prior-Average-"
                "Player-Salary branch in the exception engine before applying "
                "this registry. Prior Regular Salary is already resolved for "
                "all 16 Early Bird rows."
            ),
            "checkpoint_sha256_before": checkpoint_before,
            "checkpoint_sha256_after": checkpoint_after,
            "rights_overlay_sha256_before": overlay_before,
            "rights_overlay_sha256_after": overlay_after,
            "checkpoint_write_performed": False,
            "rights_overlay_write_performed": False,
            "input_fingerprints": {
                row["input_kind"]: row["sha256"]
                for row in input_manifest
            },
        }
        (export / "final_rights_summary.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True),
            encoding="utf-8",
        )

        readme = f"""FINAL 187-PLAYER FREE AGENCY RIGHTS REGISTRY V2 PREVIEW
========================================================

Version: {VERSION}

FINAL PREVIEW COUNTS
--------------------
Bird:           {counts.get('bird', 0)}
Early Bird:     {counts.get('early_bird', 0)}
Non-Bird:       {counts.get('non_bird', 0)}
Not applicable: {counts.get('not_applicable', 0)}
Unknown:        {counts.get('unknown', 0)}

Verified Veteran-FA registry candidates: {len(overlay_candidates)}
Special non-VFA rows:                    {len(non_vfa_rows)}
Manual rights rows:                      {len(manual_rows)}

PRIOR REGULAR SALARY
--------------------
Every salary-dependent Veteran-FA row is resolved:
- 16 / 16 Early Bird
- 90 / 90 Non-Bird
- 106 / 106 total

For Two-Way contracts, the harvested 2025-26 Base Compensation is retained as
the prior Regular Salary basis because Two-Way contracts cannot contain signing
bonuses or incentive compensation.

For players with multiple 2025-26 contracts, the preview selects the latest
applicable contract signed on or before {SIMULATION_SPLIT_DATE.isoformat()} and
cross-checks its salary against the harvested salary rows.

IMPORTANT LIVE-APPLY BOUNDARY
-----------------------------
THIS PACKAGE IS NOT A LIVE OVERLAY.

The existing exception engine's Early Bird financial ceiling requires both:
- 175% of prior Regular Salary, and
- 105% of prior Average Player Salary.

All 16 prior Regular Salaries are now proven. This package intentionally leaves
prior_average_player_salary unset because it will not manufacture an exact
Average Player Salary from rounded published figures.

Before a live rights overlay is applied, the next patch should install one
canonical, independently validated 2026-27 Early Bird average-salary branch in
the exception engine and test it against all 16 Early Bird rows.

FILES
-----
final_rights_registry_preview.csv
final_rights_overlay_candidates.csv
final_rights_non_vfa.csv
final_rights_manual_queue.csv
final_rights_salary_resolution.csv
final_rights_input_manifest.csv
final_rights_checks.csv
final_rights_registry_candidate.json
final_rights_summary.json

SAFETY
------
- no rights overlay write
- no checkpoint write
- no roster mutation
- no signing
- no trade
- no contract mutation
"""
        (export / "README.txt").write_text(readme, encoding="utf-8")

        with zipfile.ZipFile(zip_out, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(export.iterdir()):
                archive.write(path, arcname=f"{export_id}/{path.name}")

    if sha256_file(checkpoint) != checkpoint_before:
        raise RuntimeError("Checkpoint changed after preview export.")
    if sha256_file(overlay) != overlay_before:
        raise RuntimeError("Rights overlay changed after preview export.")

    print("", flush=True)
    print("=" * 120, flush=True)
    print("FINAL 187-PLAYER RIGHTS REGISTRY V2 PREVIEW PASSED", flush=True)
    print("=" * 120, flush=True)
    print(f"Bird:               {counts.get('bird', 0)}", flush=True)
    print(f"Early Bird:         {counts.get('early_bird', 0)}", flush=True)
    print(f"Non-Bird:           {counts.get('non_bird', 0)}", flush=True)
    print(f"Not applicable:     {counts.get('not_applicable', 0)}", flush=True)
    print(f"Unknown/manual:     {counts.get('unknown', 0)}", flush=True)
    print(f"Overlay candidates: {len(overlay_candidates)}", flush=True)
    print(
        f"Prior salaries:     {len(salary_resolved)}/{len(salary_dependent)} salary-dependent rows",
        flush=True,
    )
    print("Live apply ready:    NO", flush=True)
    print(
        "Remaining live blocker: canonical Early Bird 105% Average Player Salary branch.",
        flush=True,
    )
    print(f"Audit ZIP: {zip_out}", flush=True)
    print("Checkpoint write: NOT PERFORMED", flush=True)
    print("Rights overlay write: NOT PERFORMED", flush=True)

    return 0

if __name__ == "__main__":
    raise SystemExit(main())
