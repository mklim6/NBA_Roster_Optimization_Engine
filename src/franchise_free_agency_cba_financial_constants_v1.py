from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

CBA_FINANCIAL_CONSTANTS_VERSION = (
    "franchise-free-agency-cba-financial-constants-v1-2026-08-14"
)
CBA_FINANCIAL_CONSTANTS_SCHEMA = "free-agency-cba-financial-constants-schema-v1"
DEFAULT_CONSTANTS_PATH = (
    Path("data") / "processed" / "free_agency_cba_financial_constants_v1.json"
)

NBA_NON_EXPANSION_TEAM_COUNT = 30
CBA_AVERAGE_ROSTER_FACTOR = 13.2
CBA_AVERAGE_PLAYER_SALARY_DENOMINATOR = (
    NBA_NON_EXPANSION_TEAM_COUNT * CBA_AVERAGE_ROSTER_FACTOR
)

SOURCE_FINAL_AUDIT_TOTAL = "nba_nbpa_final_audit_total_salaries"
SOURCE_FINAL_AUDIT_AVERAGE = "nba_nbpa_final_audit_average_player_salary"
SOURCE_INTERIM_AUDIT_ESTIMATED_TOTAL = (
    "nba_nbpa_interim_audit_estimated_total_salaries"
)

SUPPORTED_SOURCE_KINDS = {
    SOURCE_FINAL_AUDIT_TOTAL,
    SOURCE_FINAL_AUDIT_AVERAGE,
    SOURCE_INTERIM_AUDIT_ESTIMATED_TOTAL,
}


@dataclass(frozen=True)
class AveragePlayerSalaryResolution:
    version: str
    status: str
    target_prior_season: str
    average_player_salary: float | None
    source_kind: str
    source_url: str
    source_sha256: str
    basis_value: float | None
    denominator: float
    reason: str


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _finite_positive(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number <= 0:
        return None
    return number


def prior_season_label(current_season: str) -> str:
    text = _clean(current_season)
    if not text or "-" not in text:
        raise ValueError(f"Unsupported current season label: {current_season!r}")
    start = int(text.split("-", 1)[0])
    return f"{start - 1}-{str(start)[-2:]}"


def empty_constants_payload() -> dict[str, Any]:
    return {
        "version": CBA_FINANCIAL_CONSTANTS_VERSION,
        "schema_version": CBA_FINANCIAL_CONSTANTS_SCHEMA,
        "values": {
            "2025-26": {
                "status": "pending_authoritative_input",
                "verified": False,
                "source_kind": "",
                "total_salaries": None,
                "estimated_total_salaries": None,
                "average_player_salary": None,
                "source_url": "",
                "source_sha256": "",
                "notes": (
                    "Populate only from an authoritative NBA/NBPA final Audit "
                    "Report or Interim Audit Report. Do not use a rounded public "
                    "salary estimate or the distinct CBA Estimated Average Player Salary."
                ),
            }
        },
    }


def load_constants_payload(path: str | Path | None = None) -> dict[str, Any]:
    target = Path(path) if path is not None else DEFAULT_CONSTANTS_PATH
    if not target.exists():
        return empty_constants_payload()
    try:
        payload = json.loads(target.read_text(encoding="utf-8-sig"))
    except Exception:
        return empty_constants_payload()
    if not isinstance(payload, Mapping):
        return empty_constants_payload()
    return dict(payload)


def resolve_prior_average_player_salary(
    current_season: str,
    *,
    constants_path: str | Path | None = None,
    payload: Mapping[str, Any] | None = None,
) -> AveragePlayerSalaryResolution:
    prior = prior_season_label(current_season)
    source_payload = (
        dict(payload)
        if isinstance(payload, Mapping)
        else load_constants_payload(constants_path)
    )

    values = source_payload.get("values")
    if not isinstance(values, Mapping):
        values = {}

    row = values.get(prior)
    if not isinstance(row, Mapping):
        return AveragePlayerSalaryResolution(
            version=CBA_FINANCIAL_CONSTANTS_VERSION,
            status="unresolved",
            target_prior_season=prior,
            average_player_salary=None,
            source_kind="",
            source_url="",
            source_sha256="",
            basis_value=None,
            denominator=CBA_AVERAGE_PLAYER_SALARY_DENOMINATOR,
            reason=f"No authoritative Average Player Salary evidence is stored for {prior}.",
        )

    verified = bool(row.get("verified", False))
    source_kind = _clean(row.get("source_kind"))
    source_url = _clean(row.get("source_url"))
    source_sha256 = _clean(row.get("source_sha256"))

    if not verified:
        return AveragePlayerSalaryResolution(
            version=CBA_FINANCIAL_CONSTANTS_VERSION,
            status="unresolved",
            target_prior_season=prior,
            average_player_salary=None,
            source_kind=source_kind,
            source_url=source_url,
            source_sha256=source_sha256,
            basis_value=None,
            denominator=CBA_AVERAGE_PLAYER_SALARY_DENOMINATOR,
            reason=f"{prior} financial constant is not explicitly verified.",
        )

    if source_kind not in SUPPORTED_SOURCE_KINDS:
        return AveragePlayerSalaryResolution(
            version=CBA_FINANCIAL_CONSTANTS_VERSION,
            status="manual_review",
            target_prior_season=prior,
            average_player_salary=None,
            source_kind=source_kind,
            source_url=source_url,
            source_sha256=source_sha256,
            basis_value=None,
            denominator=CBA_AVERAGE_PLAYER_SALARY_DENOMINATOR,
            reason="Verified row uses an unsupported CBA evidence source kind.",
        )

    if not source_url or not source_sha256:
        return AveragePlayerSalaryResolution(
            version=CBA_FINANCIAL_CONSTANTS_VERSION,
            status="manual_review",
            target_prior_season=prior,
            average_player_salary=None,
            source_kind=source_kind,
            source_url=source_url,
            source_sha256=source_sha256,
            basis_value=None,
            denominator=CBA_AVERAGE_PLAYER_SALARY_DENOMINATOR,
            reason="Verified CBA financial constant requires source URL and SHA256 provenance.",
        )

    total_salaries = _finite_positive(row.get("total_salaries"))
    estimated_total = _finite_positive(row.get("estimated_total_salaries"))
    direct_average = _finite_positive(row.get("average_player_salary"))

    if source_kind == SOURCE_FINAL_AUDIT_TOTAL:
        if total_salaries is None:
            return AveragePlayerSalaryResolution(
                version=CBA_FINANCIAL_CONSTANTS_VERSION,
                status="manual_review",
                target_prior_season=prior,
                average_player_salary=None,
                source_kind=source_kind,
                source_url=source_url,
                source_sha256=source_sha256,
                basis_value=None,
                denominator=CBA_AVERAGE_PLAYER_SALARY_DENOMINATOR,
                reason="Final-audit total-salaries source is missing total_salaries.",
            )
        average = total_salaries / CBA_AVERAGE_PLAYER_SALARY_DENOMINATOR
        basis = total_salaries

    elif source_kind == SOURCE_INTERIM_AUDIT_ESTIMATED_TOTAL:
        if estimated_total is None:
            return AveragePlayerSalaryResolution(
                version=CBA_FINANCIAL_CONSTANTS_VERSION,
                status="manual_review",
                target_prior_season=prior,
                average_player_salary=None,
                source_kind=source_kind,
                source_url=source_url,
                source_sha256=source_sha256,
                basis_value=None,
                denominator=CBA_AVERAGE_PLAYER_SALARY_DENOMINATOR,
                reason="Interim-audit source is missing estimated_total_salaries.",
            )
        average = estimated_total / CBA_AVERAGE_PLAYER_SALARY_DENOMINATOR
        basis = estimated_total

    else:
        if direct_average is None:
            return AveragePlayerSalaryResolution(
                version=CBA_FINANCIAL_CONSTANTS_VERSION,
                status="manual_review",
                target_prior_season=prior,
                average_player_salary=None,
                source_kind=source_kind,
                source_url=source_url,
                source_sha256=source_sha256,
                basis_value=None,
                denominator=CBA_AVERAGE_PLAYER_SALARY_DENOMINATOR,
                reason="Final-audit average-salary source is missing average_player_salary.",
            )
        average = direct_average
        basis = direct_average

    if not math.isfinite(average) or average <= 0:
        return AveragePlayerSalaryResolution(
            version=CBA_FINANCIAL_CONSTANTS_VERSION,
            status="manual_review",
            target_prior_season=prior,
            average_player_salary=None,
            source_kind=source_kind,
            source_url=source_url,
            source_sha256=source_sha256,
            basis_value=basis,
            denominator=CBA_AVERAGE_PLAYER_SALARY_DENOMINATOR,
            reason="Derived Average Player Salary is not a finite positive number.",
        )

    return AveragePlayerSalaryResolution(
        version=CBA_FINANCIAL_CONSTANTS_VERSION,
        status="pass",
        target_prior_season=prior,
        average_player_salary=float(average),
        source_kind=source_kind,
        source_url=source_url,
        source_sha256=source_sha256,
        basis_value=float(basis),
        denominator=CBA_AVERAGE_PLAYER_SALARY_DENOMINATOR,
        reason=(
            f"Resolved {prior} Average Player Salary from authoritative "
            f"{source_kind} evidence."
        ),
    )
