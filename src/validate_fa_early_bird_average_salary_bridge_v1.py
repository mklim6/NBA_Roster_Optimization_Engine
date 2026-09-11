from __future__ import annotations

import hashlib
import math
from pathlib import Path

from franchise_free_agency_cba_financial_constants_v1 import (
    CBA_AVERAGE_PLAYER_SALARY_DENOMINATOR,
    CBA_FINANCIAL_CONSTANTS_VERSION,
    SOURCE_FINAL_AUDIT_AVERAGE,
    SOURCE_FINAL_AUDIT_TOTAL,
    SOURCE_INTERIM_AUDIT_ESTIMATED_TOTAL,
    resolve_prior_average_player_salary,
)


def _sha256(path: Path) -> str:
    if not path.exists() or not path.is_file():
        return ""
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _checkpoint_path(root: Path) -> Path:
    try:
        from simulation_franchise_checkpoint_v1 import DEFAULT_CHECKPOINT_PATH
        return Path(DEFAULT_CHECKPOINT_PATH)
    except Exception:
        return root / "outputs" / "runtime" / "franchise_mode_checkpoint_v1.pkl.gz"


def main() -> int:
    root = Path.cwd().resolve()
    checkpoint = _checkpoint_path(root)
    overlay = root / "outputs" / "runtime" / "free_agency_rights_population_v1.json"
    checkpoint_before = _sha256(checkpoint)
    overlay_before = _sha256(overlay)

    print("=" * 118)
    print("EARLY BIRD AVERAGE PLAYER SALARY BRIDGE V1 VALIDATION")
    print("=" * 118)

    checks = []

    def check(name: str, passed: bool, detail: str) -> None:
        checks.append((name, bool(passed), detail))
        print(f"  {name}: {'PASS' if passed else 'FAIL'}")

    unresolved = resolve_prior_average_player_salary(
        "2026-27",
        payload={"values": {"2025-26": {"verified": False, "source_kind": ""}}},
    )
    check(
        "missing_authoritative_value_fails_closed",
        unresolved.status == "unresolved"
        and unresolved.average_player_salary is None,
        unresolved.reason,
    )

    total = 5_940_000_000.0
    final_total = resolve_prior_average_player_salary(
        "2026-27",
        payload={
            "values": {
                "2025-26": {
                    "verified": True,
                    "source_kind": SOURCE_FINAL_AUDIT_TOTAL,
                    "total_salaries": total,
                    "source_url": "https://example.invalid/final-audit",
                    "source_sha256": "a" * 64,
                }
            }
        },
    )
    check(
        "final_audit_total_uses_cba_396_denominator",
        final_total.status == "pass"
        and math.isclose(
            final_total.average_player_salary or 0.0,
            total / 396.0,
            rel_tol=0,
            abs_tol=1e-9,
        ),
        str(final_total.average_player_salary),
    )

    interim_total = 5_742_000_000.0
    interim = resolve_prior_average_player_salary(
        "2026-27",
        payload={
            "values": {
                "2025-26": {
                    "verified": True,
                    "source_kind": SOURCE_INTERIM_AUDIT_ESTIMATED_TOTAL,
                    "estimated_total_salaries": interim_total,
                    "source_url": "https://example.invalid/interim-audit",
                    "source_sha256": "b" * 64,
                }
            }
        },
    )
    check(
        "interim_audit_estimated_total_uses_same_cba_denominator",
        interim.status == "pass"
        and math.isclose(
            interim.average_player_salary or 0.0,
            interim_total / 396.0,
            rel_tol=0,
            abs_tol=1e-9,
        ),
        str(interim.average_player_salary),
    )

    direct_value = 14_750_123.45
    direct = resolve_prior_average_player_salary(
        "2026-27",
        payload={
            "values": {
                "2025-26": {
                    "verified": True,
                    "source_kind": SOURCE_FINAL_AUDIT_AVERAGE,
                    "average_player_salary": direct_value,
                    "source_url": "https://example.invalid/final-audit",
                    "source_sha256": "c" * 64,
                }
            }
        },
    )
    check(
        "explicit_final_audit_average_is_supported",
        direct.status == "pass"
        and math.isclose(
            direct.average_player_salary or 0.0,
            direct_value,
            rel_tol=0,
            abs_tol=1e-9,
        ),
        str(direct.average_player_salary),
    )

    wrong_term = resolve_prior_average_player_salary(
        "2026-27",
        payload={
            "values": {
                "2025-26": {
                    "verified": True,
                    "source_kind": "estimated_average_player_salary",
                    "average_player_salary": direct_value,
                    "source_url": "https://example.invalid/wrong-term",
                    "source_sha256": "d" * 64,
                }
            }
        },
    )
    check(
        "estimated_average_player_salary_term_is_rejected",
        wrong_term.status == "manual_review"
        and wrong_term.average_player_salary is None,
        wrong_term.reason,
    )

    no_provenance = resolve_prior_average_player_salary(
        "2026-27",
        payload={
            "values": {
                "2025-26": {
                    "verified": True,
                    "source_kind": SOURCE_FINAL_AUDIT_AVERAGE,
                    "average_player_salary": direct_value,
                    "source_url": "",
                    "source_sha256": "",
                }
            }
        },
    )
    check(
        "verified_value_requires_source_provenance",
        no_provenance.status == "manual_review"
        and no_provenance.average_player_salary is None,
        no_provenance.reason,
    )

    from franchise_free_agency_rights_exceptions_v1 import (
        FREE_AGENCY_RIGHTS_EXCEPTIONS_VERSION,
        rights_exceptions_contract_report,
    )

    report = rights_exceptions_contract_report()
    check(
        "rights_engine_reports_average_salary_bridge",
        report.get("early_bird_average_salary_resolution")
        == "season_scoped_cba_financial_constants_v1",
        str(report.get("early_bird_average_salary_resolution")),
    )
    check(
        "rights_engine_reports_cba_denominator",
        math.isclose(
            float(report.get("average_player_salary_denominator", 0.0)),
            CBA_AVERAGE_PLAYER_SALARY_DENOMINATOR,
        ),
        str(report.get("average_player_salary_denominator")),
    )
    check(
        "rights_engine_preserves_existing_version_family",
        "rights-exceptions" in FREE_AGENCY_RIGHTS_EXCEPTIONS_VERSION,
        FREE_AGENCY_RIGHTS_EXCEPTIONS_VERSION,
    )

    checkpoint_after = _sha256(checkpoint)
    overlay_after = _sha256(overlay)
    check(
        "validator_did_not_write_checkpoint",
        checkpoint_before == checkpoint_after,
        checkpoint_after,
    )
    check(
        "validator_did_not_write_rights_overlay",
        overlay_before == overlay_after,
        overlay_after or "<absent>",
    )

    failed = [name for name, passed, _ in checks if not passed]
    if failed:
        raise RuntimeError(
            "Early Bird Average Salary Bridge validation failed: "
            + ", ".join(failed)
        )

    print("")
    print("=" * 118)
    print("EARLY BIRD AVERAGE PLAYER SALARY BRIDGE V1 VALIDATION PASSED")
    print("=" * 118)
    print(f"Constants version: {CBA_FINANCIAL_CONSTANTS_VERSION}")
    print("Live 2025-26 authoritative APS value installed: NO")
    print("Fail-closed behavior preserved until authoritative input exists.")
    print("Checkpoint write: NOT PERFORMED")
    print("Rights overlay write: NOT PERFORMED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
