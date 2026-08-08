from __future__ import annotations

import argparse
import json
import math
from functools import lru_cache
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
APP_DATA = ROOT / "app_data"
OUTPUTS = ROOT / "outputs"

PROFILE_DATA_PATH = (
    APP_DATA
    / "simulation_player_stat_profiles_2026_27_v1.json"
)
PROFILE_LOADER_VERSION = (
    "simulation-player-stat-profile-loader-v1-2026-08-08"
)
SELF_TEST_REPORT = (
    OUTPUTS
    / "simulation_player_stat_profiles_v1_self_test.json"
)

REQUIRED_PROFILE_FIELDS = {
    "player_id",
    "player_name",
    "position",
    "points_per_game",
    "rebounds_per_game",
    "assists_per_game",
    "steals_per_game",
    "blocks_per_game",
    "turnovers_per_game",
    "overall_rating",
    "scoring_rating",
    "shooting_rating",
    "playmaking_rating",
    "rebounding_rating",
    "defense_rating",
    "profile_reliability",
    "stat_factors",
}

SUPPORTED_FACTORS = {
    "points",
    "rebounds",
    "assists",
    "steals",
    "blocks",
    "turnovers",
    "fouls",
    "three_attempts",
    "free_throw_attempts",
}


class SimulationPlayerStatProfileError(RuntimeError):
    """Raised when the permanent player-stat layer is invalid."""


def normalize_player_id(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""

    try:
        number = float(text)
    except (TypeError, ValueError):
        return text

    if math.isfinite(number) and number.is_integer():
        return str(int(number))

    return text


def finite_float(
    value: Any,
    *,
    default: float | None = None,
) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default

    return number if math.isfinite(number) else default


def validate_profile_record(
    player_id: str,
    record: Any,
) -> dict[str, Any]:
    if not isinstance(record, dict):
        raise SimulationPlayerStatProfileError(
            f"Profile {player_id!r} is not a mapping."
        )

    missing = sorted(
        REQUIRED_PROFILE_FIELDS.difference(record)
    )
    if missing:
        raise SimulationPlayerStatProfileError(
            f"Profile {player_id} is missing: "
            + ", ".join(missing)
        )

    record_player_id = normalize_player_id(
        record.get("player_id")
    )
    if record_player_id != player_id:
        raise SimulationPlayerStatProfileError(
            f"Profile key {player_id} does not match "
            f"record player_id {record_player_id!r}."
        )

    position = str(
        record.get("position") or ""
    ).strip().upper()
    if not position or position == "UNK":
        raise SimulationPlayerStatProfileError(
            f"Profile {player_id} has no resolved position."
        )

    factors = record.get("stat_factors")
    if not isinstance(factors, dict):
        raise SimulationPlayerStatProfileError(
            f"Profile {player_id} has invalid stat_factors."
        )

    missing_factors = sorted(
        SUPPORTED_FACTORS.difference(factors)
    )
    if missing_factors:
        raise SimulationPlayerStatProfileError(
            f"Profile {player_id} is missing factors: "
            + ", ".join(missing_factors)
        )

    for factor_name in SUPPORTED_FACTORS:
        factor = finite_float(
            factors.get(factor_name)
        )
        if factor is None or factor <= 0:
            raise SimulationPlayerStatProfileError(
                f"Profile {player_id} has invalid "
                f"{factor_name} factor."
            )

    reliability = finite_float(
        record.get("profile_reliability")
    )
    if (
        reliability is None
        or reliability < 0
        or reliability > 1
    ):
        raise SimulationPlayerStatProfileError(
            f"Profile {player_id} has invalid reliability."
        )

    return record


@lru_cache(maxsize=1)
def load_profile_payload() -> dict[str, Any]:
    if not PROFILE_DATA_PATH.exists():
        raise FileNotFoundError(
            "Simulation player-stat profile layer was not found:\n"
            f"{PROFILE_DATA_PATH}"
        )

    payload = json.loads(
        PROFILE_DATA_PATH.read_text(
            encoding="utf-8"
        )
    )
    if not isinstance(payload, dict):
        raise SimulationPlayerStatProfileError(
            "Player-stat profile payload is not a mapping."
        )

    players = payload.get("players")
    if not isinstance(players, dict):
        raise SimulationPlayerStatProfileError(
            "Player-stat profile payload is missing players."
        )

    if len(players) != 582:
        raise SimulationPlayerStatProfileError(
            "Expected 582 player-stat profiles, found "
            f"{len(players)}."
        )

    normalized_players: dict[
        str,
        dict[str, Any],
    ] = {}

    for raw_player_id, raw_record in players.items():
        player_id = normalize_player_id(
            raw_player_id
        )
        if not player_id:
            raise SimulationPlayerStatProfileError(
                "Player-stat profile contains a blank ID."
            )
        if player_id in normalized_players:
            raise SimulationPlayerStatProfileError(
                "Player-stat profile contains duplicate ID "
                f"{player_id}."
            )

        normalized_players[player_id] = (
            validate_profile_record(
                player_id,
                raw_record,
            )
        )

    return {
        **payload,
        "players": normalized_players,
    }


def load_player_stat_profiles() -> dict[
    str,
    dict[str, Any],
]:
    return load_profile_payload()["players"]


def player_stat_profile(
    player_id: Any,
) -> dict[str, Any] | None:
    return load_player_stat_profiles().get(
        normalize_player_id(player_id)
    )


def player_stat_factor(
    player_id: Any,
    stat_name: str,
    *,
    default: float = 1.0,
) -> float:
    profile = player_stat_profile(player_id)
    if profile is None:
        return float(default)

    factor = finite_float(
        profile["stat_factors"].get(stat_name),
        default=default,
    )
    return float(
        factor
        if factor is not None
        else default
    )


def player_stat_value(
    player_id: Any,
    field_name: str,
    *,
    default: float | None = None,
) -> float | None:
    profile = player_stat_profile(player_id)
    if profile is None:
        return default

    return finite_float(
        profile.get(field_name),
        default=default,
    )


def player_profile_name(
    player_id: Any,
) -> str:
    profile = player_stat_profile(player_id)
    if profile is None:
        return ""
    return str(profile.get("player_name") or "").strip()


def player_id_by_name(
    player_name: str,
) -> str:
    target = " ".join(
        str(player_name).lower().split()
    )

    for player_id, profile in (
        load_player_stat_profiles().items()
    ):
        name = " ".join(
            str(
                profile.get("player_name") or ""
            ).lower().split()
        )
        if name == target:
            return player_id

    return ""


def run_self_test() -> dict[str, Any]:
    profiles = load_player_stat_profiles()

    jokic_id = player_id_by_name(
        "Nikola Jokić"
    ) or player_id_by_name("Nikola Jokic")
    curry_id = player_id_by_name(
        "Stephen Curry"
    )
    wemby_id = player_id_by_name(
        "Victor Wembanyama"
    )
    trae_id = player_id_by_name(
        "Trae Young"
    )
    duren_id = player_id_by_name(
        "Jalen Duren"
    )

    checks = {
        "profile_file_exists": (
            PROFILE_DATA_PATH.exists()
        ),
        "profile_count_is_582": (
            len(profiles) == 582
        ),
        "all_positions_resolved": all(
            str(profile["position"]).upper()
            != "UNK"
            for profile in profiles.values()
        ),
        "all_supported_factors_present": all(
            SUPPORTED_FACTORS.issubset(
                profile["stat_factors"]
            )
            for profile in profiles.values()
        ),
        "jokic_found": bool(jokic_id),
        "jokic_exceptional_assist_factor": (
            bool(jokic_id)
            and player_stat_factor(
                jokic_id,
                "assists",
            )
            >= 2.50
        ),
        "jokic_strong_rebound_factor": (
            bool(jokic_id)
            and player_stat_factor(
                jokic_id,
                "rebounds",
            )
            >= 1.05
        ),
        "curry_found": bool(curry_id),
        "curry_elite_shooting_rating": (
            bool(curry_id)
            and (
                player_stat_value(
                    curry_id,
                    "shooting_rating",
                    default=0.0,
                )
                or 0.0
            )
            >= 90.0
        ),
        "wembanyama_found": bool(wemby_id),
        "wembanyama_exceptional_block_factor": (
            bool(wemby_id)
            and player_stat_factor(
                wemby_id,
                "blocks",
            )
            >= 2.00
        ),
        "trae_found": bool(trae_id),
        "trae_exceptional_assist_factor": (
            bool(trae_id)
            and player_stat_factor(
                trae_id,
                "assists",
            )
            >= 1.40
        ),
        "duren_found": bool(duren_id),
        "duren_strong_rebound_factor": (
            bool(duren_id)
            and player_stat_factor(
                duren_id,
                "rebounds",
            )
            >= 1.05
        ),
    }

    failed = [
        name
        for name, passed in checks.items()
        if not passed
    ]
    sample_ids = {
        "Nikola Jokic": jokic_id,
        "Stephen Curry": curry_id,
        "Victor Wembanyama": wemby_id,
        "Trae Young": trae_id,
        "Jalen Duren": duren_id,
    }
    samples = {
        name: {
            "player_id": player_id,
            "position": (
                profiles[player_id]["position"]
            ),
            "points_factor": (
                player_stat_factor(
                    player_id,
                    "points",
                )
            ),
            "rebounds_factor": (
                player_stat_factor(
                    player_id,
                    "rebounds",
                )
            ),
            "assists_factor": (
                player_stat_factor(
                    player_id,
                    "assists",
                )
            ),
            "blocks_factor": (
                player_stat_factor(
                    player_id,
                    "blocks",
                )
            ),
        }
        for name, player_id in sample_ids.items()
        if player_id
    }

    report = {
        "script": PROFILE_LOADER_VERSION,
        "profile_path": str(PROFILE_DATA_PATH),
        "profile_count": len(profiles),
        "checks": checks,
        "failed_checks": failed,
        "samples": samples,
        "passed": not failed,
    }

    OUTPUTS.mkdir(
        parents=True,
        exist_ok=True,
    )
    SELF_TEST_REPORT.write_text(
        json.dumps(
            report,
            indent=2,
        ),
        encoding="utf-8",
    )

    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--self-test",
        action="store_true",
    )
    args = parser.parse_args()

    if not args.self_test:
        payload = load_profile_payload()
        print(
            json.dumps(
                {
                    "script": (
                        PROFILE_LOADER_VERSION
                    ),
                    "profile_path": str(
                        PROFILE_DATA_PATH
                    ),
                    "profile_count": len(
                        payload["players"]
                    ),
                },
                indent=2,
            )
        )
        return 0

    report = run_self_test()
    print(json.dumps(report, indent=2))

    if not report["passed"]:
        print(
            "\nSIMULATION PLAYER STAT PROFILE "
            "SELF-TEST FAILED"
        )
        return 1

    print(
        "\nSIMULATION PLAYER STAT PROFILE "
        "SELF-TEST PASSED"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())