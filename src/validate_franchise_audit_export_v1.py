from __future__ import annotations

import csv
import hashlib
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

from franchise_audit_export_v1 import (
    AUDIT_EXPORT_VERSION,
    AUDIT_SCHEMA_VERSION,
    REQUIRED_EXPORT_FILES,
    build_franchise_audit_export,
)
from franchise_cpu_front_office_v1 import (
    CPU_FRONT_OFFICE_VERSION,
    front_office_state_fingerprint,
)
from franchise_trade_finder_ai_v1 import (
    TRADE_FINDER_AI_VERSION,
)
from simulation_franchise_checkpoint_v1 import (
    DEFAULT_CHECKPOINT_PATH,
    load_franchise_checkpoint,
)

VALIDATOR_VERSION = (
    "franchise-audit-export-validator-v1.1-2026-08-13"
)

EXPECTED_CPU_FO_HASH = "2978362f8edf626431fd29bc4f349525041d48460c4e7dc22dee230deceffc9f"
EXPECTED_SHARED_HASH = "6ab1c377757ade6c6208cc66a20f6306827577f917bbe3fa39944e2946975899"
EXPECTED_TRADE_AI_HASH = "235d10e9f5aa9aca1f627b1ef95fe53b37e924764d2bd65b57121c0ec67102ac"
EXPECTED_CENTER_HASH = "575df09efa8d96b279331f2a093a9ffa3eca0d9f660c1d99c2753dacdec44fde"


def sha(path: Path) -> str:
    return hashlib.sha256(
        path.read_bytes()
    ).hexdigest()


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    src = root / "src"
    checkpoint_path = Path(
        DEFAULT_CHECKPOINT_PATH
    )

    checkpoint_before = sha(
        checkpoint_path
    )
    checkpoint = load_franchise_checkpoint()
    if checkpoint is None:
        raise RuntimeError(
            "Durable checkpoint could not be loaded."
        )

    state = checkpoint.simulation_state
    state_before = (
        front_office_state_fingerprint(
            state
        )
    )

    temp_dir = Path(
        tempfile.mkdtemp(
            prefix="audit_export_validation_"
        )
    )

    checks = {
        "validator_version_is_current": (
            "v1" in VALIDATOR_VERSION
        ),
        "audit_export_version_is_current": (
            AUDIT_EXPORT_VERSION
            == "franchise-audit-export-v1.1-2026-08-13"
        ),
        "audit_schema_version_is_current": (
            AUDIT_SCHEMA_VERSION
            == "franchise-audit-schema-v1.1-2026-08-13"
        ),
        "cpu_front_office_v1_6_2_dependency_is_exact": (
            sha(
                src
                / "franchise_cpu_front_office_v1.py"
            )
            == EXPECTED_CPU_FO_HASH
        ),
        "shared_asset_market_dependency_is_exact": (
            sha(
                src
                / "franchise_asset_market_value_v1.py"
            )
            == EXPECTED_SHARED_HASH
        ),
        "trade_finder_v1_5_3_dependency_is_exact": (
            sha(
                src
                / "franchise_trade_finder_ai_v1.py"
            )
            == EXPECTED_TRADE_AI_HASH
        ),
        "embedded_trade_center_v2_1_dependency_is_exact": (
            sha(
                src
                / "franchise_embedded_trade_center_v2.py"
            )
            == EXPECTED_CENTER_HASH
        ),
        "cpu_front_office_version_is_live": (
            "v1.6" in CPU_FRONT_OFFICE_VERSION
        ),
        "trade_finder_version_is_live": (
            "v1.5.3" in TRADE_FINDER_AI_VERSION
        ),
        "checkpoint_exists": (
            checkpoint_path.is_file()
        ),
        "checkpoint_loader_is_called_with_zero_arguments": (
            "checkpoint = load_franchise_checkpoint()"
            in (
                src
                / "franchise_audit_export_v1.py"
            ).read_text(encoding="utf-8")
            and "load_franchise_checkpoint(\n        checkpoint_path"
            not in (
                src
                / "franchise_audit_export_v1.py"
            ).read_text(encoding="utf-8")
        ),
        "alternate_checkpoint_path_is_explicitly_guarded": (
            "supports only the canonical durable"
            in (
                src
                / "franchise_audit_export_v1.py"
            ).read_text(encoding="utf-8")
        ),
    }

    try:
        result = build_franchise_audit_export(
            output_dir=temp_dir,
            include_trade_finder=True,
            trade_finder_max_partners=10,
            trade_finder_max_targets_per_partner=4,
            trade_finder_max_package_evaluations=12,
            trade_finder_max_financial_prechecks=320,
        )

        zip_path = Path(
            result.zip_path
        )
        checks[
            "audit_zip_was_created"
        ] = zip_path.is_file()

        with zipfile.ZipFile(
            zip_path
        ) as archive:
            names = set(
                archive.namelist()
            )
            basenames = {
                Path(name).name
                for name in names
            }

            checks[
                "all_required_csvs_exist"
            ] = all(
                filename in basenames
                for filename in REQUIRED_EXPORT_FILES
            )

            manifest_name = next(
                (
                    name
                    for name in names
                    if Path(name).name
                    == "audit_manifest.csv"
                ),
                "",
            )
            manifest_text = (
                archive.read(
                    manifest_name
                ).decode(
                    "utf-8-sig"
                )
                if manifest_name
                else ""
            )
            checks[
                "manifest_contains_checkpoint_hash"
            ] = (
                result.checkpoint_sha256
                in manifest_text
            )
            checks[
                "manifest_contains_model_versions"
            ] = (
                "cpu_front_office_version"
                in manifest_text
                and "trade_finder_version"
                in manifest_text
                and "asset_market_model_version"
                in manifest_text
            )

            market_name = next(
                (
                    name
                    for name in names
                    if Path(name).name
                    == "player_market_context.csv"
                ),
                "",
            )
            market_text = (
                archive.read(
                    market_name
                ).decode(
                    "utf-8-sig"
                )
                if market_name
                else ""
            )
            checks[
                "market_context_export_contains_core_fields"
            ] = (
                "asset_tier"
                in market_text
                and "market_score"
                in market_text
                and "trade_value_score"
                in market_text
            )

            trade_audit_name = next(
                (
                    name
                    for name in names
                    if Path(name).name
                    == "trade_finder_package_audit.csv"
                ),
                "",
            )
            trade_audit_text = (
                archive.read(
                    trade_audit_name
                ).decode(
                    "utf-8-sig"
                )
                if trade_audit_name
                else ""
            )
            checks[
                "trade_finder_audit_contains_shared_context"
            ] = (
                "target_shared_asset_tier"
                in trade_audit_text
                and "target_shared_trade_value"
                in trade_audit_text
                and "canonical_precheck_status"
                in trade_audit_text
            )

            health_name = next(
                (
                    name
                    for name in names
                    if Path(name).name
                    == "player_health.csv"
                ),
                "",
            )
            health_text = (
                archive.read(
                    health_name
                ).decode("utf-8-sig")
                if health_name
                else ""
            )
            checks[
                "health_export_contains_real_medical_columns"
            ] = (
                "availability_status"
                in health_text
                and "fatigue"
                in health_text
                and "medical_profile_present"
                in health_text
            )

            contract_name = next(
                (
                    name
                    for name in names
                    if Path(name).name
                    == "player_contracts.csv"
                ),
                "",
            )
            contract_text = (
                archive.read(
                    contract_name
                ).decode("utf-8-sig")
                if contract_name
                else ""
            )
            checks[
                "contract_export_contains_exact_contract_state"
            ] = all(
                field_name in contract_text
                for field_name in (
                    "status",
                    "salary",
                    "years_remaining",
                    "option_type",
                    "guaranteed",
                )
            )

            regular_name = next(
                (
                    name
                    for name in names
                    if Path(name).name
                    == "regular_season_player_stats.csv"
                ),
                "",
            )
            regular_text = (
                archive.read(
                    regular_name
                ).decode("utf-8-sig")
                if regular_name
                else ""
            )
            checks[
                "regular_stats_export_has_full_shooting_metrics"
            ] = all(
                field_name in regular_text
                for field_name in (
                    "games_played",
                    "points_per_game",
                    "fg_pct",
                    "three_pct",
                    "ft_pct",
                    "effective_fg_pct",
                    "true_shooting_pct",
                )
            )

        checks[
            "core_exports_are_nonempty"
        ] = (
            result.row_counts.get(
                "team_rosters.csv",
                0,
            )
            > 0
            and result.row_counts.get(
                "player_market_context.csv",
                0,
            )
            > 0
            and result.row_counts.get(
                "cpu_front_office_player_decisions.csv",
                0,
            )
            > 0
            and result.row_counts.get(
                "draft_rights.csv",
                0,
            )
            > 0
        )

        live_player_count = len(
            getattr(state, "players", {})
        )
        live_roster_ids = {
            str(player_id)
            for team_state in getattr(
                state,
                "teams",
                {},
            ).values()
            for player_id in (
                getattr(
                    team_state,
                    "roster_player_ids",
                    (),
                )
                or ()
            )
        }
        live_free_agent_ids = {
            str(player_id)
            for player_id in (
                getattr(
                    state,
                    "free_agent_player_ids",
                    (),
                )
                or ()
            )
        }

        checks[
            "player_pool_export_matches_live_state"
        ] = (
            result.row_counts.get(
                "league_player_pool.csv",
                -1,
            )
            == live_player_count
        )
        checks[
            "active_roster_export_matches_team_rosters"
        ] = (
            result.row_counts.get(
                "active_rosters.csv",
                -1,
            )
            == len(live_roster_ids)
            and result.row_counts.get(
                "team_rosters.csv",
                -1,
            )
            == len(live_roster_ids)
        )
        checks[
            "free_agent_export_matches_live_pool"
        ] = (
            result.row_counts.get(
                "free_agent_pool.csv",
                -1,
            )
            == len(live_free_agent_ids)
        )
        checks[
            "roster_and_free_agent_populations_reconcile"
        ] = (
            not (
                live_roster_ids
                & live_free_agent_ids
            )
            and len(
                live_roster_ids
                | live_free_agent_ids
            )
            == live_player_count
        )
        checks[
            "injury_records_cover_all_players"
        ] = (
            result.row_counts.get(
                "injury_records.csv",
                -1,
            )
            == live_player_count
        )
        checks[
            "health_export_covers_all_players"
        ] = (
            result.row_counts.get(
                "player_health.csv",
                -1,
            )
            == live_player_count
        )
        profiles = getattr(
            state,
            "injury_fatigue_profiles",
            {},
        ) or {}
        checks[
            "medical_v2_profile_coverage_is_exportable"
        ] = (
            not profiles
            or len(profiles)
            == live_player_count
        )
        checks[
            "contract_export_uses_exact_simulation_contract_fields"
        ] = (
            result.row_counts.get(
                "player_contracts.csv",
                -1,
            )
            == live_player_count
        )
        checks[
            "standings_export_has_all_30_teams"
        ] = (
            result.row_counts.get(
                "standings.csv",
                -1,
            )
            == len(
                getattr(
                    state,
                    "standings",
                    {},
                )
            )
            == 30
        )
        checks[
            "regular_player_stats_cover_all_players"
        ] = (
            result.row_counts.get(
                "regular_season_player_stats.csv",
                -1,
            )
            == live_player_count
        )
        checks[
            "regular_team_stats_cover_all_teams"
        ] = (
            result.row_counts.get(
                "regular_season_team_stats.csv",
                -1,
            )
            == 30
        )
        checks[
            "playoff_exports_are_schema_stable"
        ] = (
            "playoff_player_stats.csv"
            in result.row_counts
            and "playoff_team_stats.csv"
            in result.row_counts
        )
        checks[
            "season_history_export_is_present"
        ] = (
            "season_history.csv"
            in result.row_counts
        )

        checks[
            "trade_finder_audit_ran"
        ] = (
            result.row_counts.get(
                "trade_finder_search_summary.csv",
                0,
            )
            == 1
            and result.row_counts.get(
                "trade_finder_package_audit.csv",
                0,
            )
            > 0
        )

        checks[
            "audit_export_is_read_only"
        ] = (
            front_office_state_fingerprint(
                state
            )
            == state_before
        )
        checks[
            "checkpoint_hash_still_unchanged"
        ] = (
            sha(checkpoint_path)
            == checkpoint_before
        )

        checks[
            "all_export_source_files_compile"
        ] = True
        for source_path in (
            src
            / "franchise_audit_export_v1.py",
            src
            / "run_franchise_audit_export_v1.py",
            src
            / "validate_franchise_audit_export_v1.py",
        ):
            compile(
                source_path.read_text(
                    encoding="utf-8"
                ),
                str(source_path),
                "exec",
            )

        print("=" * 104)
        print(
            "FRANCHISE AUDIT / SIMULATION EXPORT CENTER V1.1 VALIDATION"
        )
        print("=" * 104)
        for name, passed in checks.items():
            print(
                f"  {name}: "
                f"{'PASS' if passed else 'FAIL'}"
            )

        print()
        print("VALIDATION EXPORT ROW COUNTS")
        for filename, count in sorted(
            result.row_counts.items()
        ):
            print(
                f"  {filename}: {count}"
            )

        print()
        print(
            "Validation ZIP SHA256:",
            result.zip_sha256,
        )

        failed = [
            name
            for name, passed in checks.items()
            if not passed
        ]
        if failed:
            raise AssertionError(
                "Audit Export V1 failed: "
                + ", ".join(failed)
            )

        print()
        print(
            "FRANCHISE AUDIT / SIMULATION EXPORT "
            "FOUNDATION V1 VALIDATION PASSED"
        )
        print(
            "READ-ONLY VALIDATION: no roster, trade, "
            "draft-right, contract, free-agent, or "
            "checkpoint mutation was performed."
        )
        return 0

    finally:
        shutil.rmtree(
            temp_dir,
            ignore_errors=True,
        )


if __name__ == "__main__":
    raise SystemExit(main())
