from __future__ import annotations

import copy
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from franchise_generated_player_portraits_v1 import (  # noqa: E402
    GENERATED_PORTRAIT_VERSION,
    player_image_url,
)
from simulation_career_awards_v2 import (  # noqa: E402
    CAREER_AWARDS_VERSION,
    ALL_ROOKIE_MIN_GAMES,
    MIP_PRIOR_MIN_GAMES,
    MIP_PRIOR_MIN_MPG,
    _mip_breakout_metrics_v3,
    _mip_prior_baseline_eligible,
    build_playoff_honors_v2,
    build_regular_awards_v2,
    ensure_career_metadata,
    player_headshot_url,
    season_label_from_start,
    season_start_from_label,
)
from simulation_franchise_checkpoint_v1 import (  # noqa: E402
    DEFAULT_CHECKPOINT_PATH,
    load_franchise_checkpoint,
)


VALIDATOR_VERSION = "awards-generated-presentation-validator-v3.1-2026-08-11"
OUTPUT = ROOT / "outputs" / "awards_generated_presentation_validation_v3_1.json"


def main() -> int:
    tiny_prior = {
        "GP": 78,
        "MIN": 36.0,
        "PTS": 28.6,
        "AST": 7.4,
        "REB": 7.0,
        "STL": 1.1,
        "BLK": 0.5,
        "TO": 3.5,
        "TS%": 61.0,
    }
    tiny_current = {
        "GP": 78,
        "MIN": 36.1,
        "PTS": 29.0,
        "AST": 7.6,
        "REB": 7.1,
        "STL": 1.1,
        "BLK": 0.5,
        "TO": 3.5,
        "TS%": 61.2,
    }
    breakout_prior = {
        "GP": 67,
        "MIN": 27.0,
        "PTS": 16.8,
        "AST": 3.8,
        "REB": 4.9,
        "STL": 0.9,
        "BLK": 0.4,
        "TO": 1.8,
        "TS%": 56.2,
    }
    breakout_current = {
        "GP": 75,
        "MIN": 34.0,
        "PTS": 24.5,
        "AST": 6.1,
        "REB": 6.2,
        "STL": 1.3,
        "BLK": 0.7,
        "TO": 2.4,
        "TS%": 60.4,
    }

    tiny = _mip_breakout_metrics_v3(tiny_current, tiny_prior)
    breakout = _mip_breakout_metrics_v3(breakout_current, breakout_prior)

    generated_a = player_image_url(
        "GEN-2030-041",
        team="IND",
        player_name="Jaylen Wright",
    )
    generated_b = player_image_url(
        "GEN-2030-041",
        team="IND",
        player_name="Jaylen Wright",
    )
    generated_other = player_image_url(
        "GEN-2030-042",
        team="IND",
        player_name="Another Rookie",
    )
    nba_url = player_image_url("203999", team="DEN", player_name="Nikola Jokic")

    checks: dict[str, bool] = {
        "career_awards_version_is_v31": (
            CAREER_AWARDS_VERSION == "simulation-career-awards-v3.1-2026-08-11"
        ),
        "portrait_version_is_current": (
            GENERATED_PORTRAIT_VERSION
            == "franchise-generated-player-portraits-v1.1-2026-08-11"
        ),
        "season_parser": (
            season_start_from_label("2030-31") == 2030
            and season_label_from_start(2030) == "2030-31"
        ),
        "mip_prior_workload_threshold": (
            MIP_PRIOR_MIN_GAMES == 41
            and MIP_PRIOR_MIN_MPG == 15.0
        ),
        "injury_limited_prior_is_ineligible": (
            not _mip_prior_baseline_eligible({"GP": 20, "MIN": 29.0})
        ),
        "reasonable_prior_baseline_is_eligible": (
            _mip_prior_baseline_eligible({"GP": 50, "MIN": 20.0})
        ),
        "real_breakout_dominates_tiny_superstar_change": (
            breakout["breakout_score"] > tiny["breakout_score"] + 15.0
        ),
        "tiny_change_stays_small": (
            tiny["breakout_score"] < 6.0
        ),
        "generated_portrait_is_data_svg": (
            generated_a.startswith("data:image/svg+xml")
        ),
        "generated_portrait_is_deterministic": generated_a == generated_b,
        "generated_players_get_distinct_portraits": generated_a != generated_other,
        "real_nba_players_keep_official_headshots": (
            nba_url.startswith("https://cdn.nba.com/headshots/nba/latest/")
        ),
        "explicit_generated_numeric_id_uses_portrait": (
            player_image_url(
                "999999999",
                team="IND",
                player_name="Future Rookie",
                generated=True,
            ).startswith("data:image/svg+xml")
        ),
        "all_rookie_primary_floor_is_broader_than_roy": (
            1 <= ALL_ROOKIE_MIN_GAMES < 41
        ),
        "page_wires_exact_src_awards_runtime": (
            "# AWARDS V3.1 EXACT-SRC RUNTIME WIRING"
            in (
                ROOT / "pages" / "5_Franchise_Mode.py"
            ).read_text(encoding="utf-8")
        ),
        "checkpoint_optional": True,
    }
    summary: dict[str, object] = {
        "synthetic_mip_test": {
            "tiny_change_score": round(tiny["breakout_score"], 2),
            "breakout_score": round(breakout["breakout_score"], 2),
        }
    }

    if DEFAULT_CHECKPOINT_PATH.exists():
        checkpoint = load_franchise_checkpoint()
        state = copy.deepcopy(checkpoint.simulation_state)
        metadata_counts = ensure_career_metadata(state)
        regular = build_regular_awards_v2(state)
        playoff = build_playoff_honors_v2(state)

        checks["career_metadata_applied"] = bool(
            getattr(state, "career_metadata_version", "") == CAREER_AWARDS_VERSION
        )
        checks["regular_awards_build"] = bool(regular.get("ready"))

        all_rookie = (
            regular.get("all_rookie", {})
            if regular.get("ready")
            else {}
        )
        rookie_first = all_rookie.get(
            "All-Rookie First Team",
            [],
        )
        rookie_second = all_rookie.get(
            "All-Rookie Second Team",
            [],
        )
        all_rookie_pool = int(
            regular.get(
                "all_rookie_eligible_count",
                0,
            )
            or 0
        )
        checks["all_rookie_first_team_fills_when_possible"] = bool(
            all_rookie_pool < 5
            or len(rookie_first) == 5
        )
        checks["all_rookie_second_team_fills_when_possible"] = bool(
            all_rookie_pool < 10
            or len(rookie_second) == 5
        )
        checks["all_rookie_teams_are_unique"] = (
            len(
                {
                    str(item.get("player_id", ""))
                    for item in (
                        list(rookie_first)
                        + list(rookie_second)
                    )
                }
            )
            == len(rookie_first) + len(rookie_second)
        )

        mip = regular.get("awards", {}).get("mip", []) if regular.get("ready") else []
        checks["mip_candidates_have_breakout_metrics"] = all(
            "mip_metrics" in item and "mip_prior" in item
            for item in mip
        )
        checks["mip_candidates_have_prior_baseline"] = all(
            float(item.get("mip_prior", {}).get("GP", 0) or 0) >= MIP_PRIOR_MIN_GAMES
            and float(item.get("mip_prior", {}).get("MIN", 0) or 0) >= MIP_PRIOR_MIN_MPG
            for item in mip
        )
        checks["mip_candidates_show_positive_growth"] = all(
            float(item.get("mip_metrics", {}).get("impact_gain", 0) or 0) > 0.25
            for item in mip
        )

        generated = [
            player
            for player in state.players.values()
            if bool(getattr(player, "generated_prospect", False))
        ]
        checks["generated_player_portraits_work_in_live_state"] = all(
            player_headshot_url(
                player.player_id,
                player.team_abbreviation,
                player.player_name,
                generated=True,
            ).startswith("data:image/svg+xml")
            for player in generated[:20]
        )

        roy = regular.get("awards", {}).get("roy", []) if regular.get("ready") else []
        checks["generated_roy_has_portrait_when_applicable"] = all(
            (
                not bool(getattr(state.players[item["player_id"]], "generated_prospect", False))
                or str(item.get("image_url", "")).startswith("data:image/svg+xml")
            )
            for item in roy
        )

        postseason = getattr(state, "postseason_state", None)
        checks["playoff_honors_build"] = bool(
            playoff.get("ready") or postseason is None
        )

        summary.update(
            {
                "season": state.settings.season_label,
                "metadata_counts": metadata_counts,
                "generated_players": len(generated),
                "mip_top_five": [
                    {
                        "player": item["subject_name"],
                        "team": item["subject_team"],
                        "score": round(float(item["award_score"]), 2),
                        "detail": item.get("detail", ""),
                    }
                    for item in mip[:5]
                ],
                "roy_winner": (
                    roy[0]["subject_name"] if roy else None
                ),
                "rookie_participants": regular.get(
                    "rookie_count",
                    0,
                ),
                "roy_workload_eligible": regular.get(
                    "rookie_award_eligible_count",
                    0,
                ),
                "all_rookie_pool": all_rookie_pool,
                "all_rookie_first_team": [
                    item["subject_name"]
                    for item in rookie_first
                ],
                "all_rookie_second_team": [
                    item["subject_name"]
                    for item in rookie_second
                ],
            }
        )

    failed = [name for name, passed in checks.items() if not passed]
    report = {
        "script": VALIDATOR_VERSION,
        "checks": checks,
        "failed_checks": failed,
        "summary": summary,
        "passed": not failed,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))

    if failed:
        raise AssertionError(
            "Awards & Generated Player Presentation V3 validation failed: "
            + ", ".join(failed)
        )

    print()
    print("AWARDS & GENERATED PLAYER PRESENTATION V3.1 VALIDATION PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
