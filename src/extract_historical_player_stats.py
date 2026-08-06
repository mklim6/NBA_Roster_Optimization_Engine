from __future__ import annotations

import argparse
import random
import time
from importlib.metadata import version
from pathlib import Path

import pandas as pd
from nba_api.stats.endpoints import leaguedashplayerstats


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIRECTORY = (
    PROJECT_ROOT
    / "data"
    / "raw"
    / "historical_player_stats"
)

SEASONS = [
    "2014-15",
    "2015-16",
    "2016-17",
    "2017-18",
    "2018-19",
    "2019-20",
    "2020-21",
    "2021-22",
]

MEASURE_TYPES = ("Base", "Advanced")
SEASON_TYPE = "Regular Season"

MAX_ATTEMPTS = 5
REQUEST_TIMEOUT_SECONDS = 60
MIN_PAUSE_SECONDS = 2.5
MAX_PAUSE_SECONDS = 4.5


def season_slug(season: str) -> str:
    """Convert an NBA season label into a filename-safe value."""

    return season.replace("-", "_")


def output_path(
    season: str,
    measure_type: str,
) -> Path:
    """Return the Parquet path for one season and measure type."""

    return (
        OUTPUT_DIRECTORY
        / (
            f"player_stats_{season_slug(season)}_"
            f"{measure_type.lower()}.parquet"
        )
    )


def download_player_stats(
    season: str,
    measure_type: str,
) -> pd.DataFrame:
    """Download one NBA player-stat dataset with retries."""

    last_error: Exception | None = None

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            print(
                f"Requesting {season} {measure_type} "
                f"(attempt {attempt}/{MAX_ATTEMPTS})..."
            )

            endpoint = (
                leaguedashplayerstats.LeagueDashPlayerStats(
                    season=season,
                    season_type_all_star=SEASON_TYPE,
                    measure_type_detailed_defense=measure_type,
                    per_mode_detailed="Totals",
                    league_id_nullable="00",
                    pace_adjust="N",
                    plus_minus="N",
                    rank="N",
                    timeout=REQUEST_TIMEOUT_SECONDS,
                )
            )

            frames = endpoint.get_data_frames()

            if not frames:
                raise ValueError(
                    "The NBA endpoint returned no data frames."
                )

            frame = frames[0].copy()

            if frame.empty:
                raise ValueError(
                    "The NBA endpoint returned an empty table."
                )

            frame.columns = [
                str(column).strip().lower()
                for column in frame.columns
            ]

            required_columns = {
                "player_id",
                "player_name",
                "team_id",
                "team_abbreviation",
                "age",
                "gp",
                "min",
            }

            missing_columns = sorted(
                required_columns.difference(frame.columns)
            )

            if missing_columns:
                raise ValueError(
                    "The downloaded table is missing required columns: "
                    + ", ".join(missing_columns)
                )

            frame.insert(0, "season", season)
            frame.insert(1, "season_type", SEASON_TYPE)
            frame.insert(2, "measure_type", measure_type)

            frame["player_id"] = pd.to_numeric(
                frame["player_id"],
                errors="raise",
            ).astype("int64")

            duplicate_mask = frame.duplicated(
                subset=["season", "player_id"],
                keep=False,
            )

            if duplicate_mask.any():
                duplicates = frame.loc[
                    duplicate_mask,
                    [
                        "season",
                        "player_id",
                        "player_name",
                        "team_abbreviation",
                    ],
                ]

                raise ValueError(
                    "Duplicate player-season rows were returned:\n"
                    f"{duplicates.to_string(index=False)}"
                )

            return frame

        except Exception as error:
            last_error = error

            if attempt == MAX_ATTEMPTS:
                break

            wait_seconds = min(
                15.0 * (2 ** (attempt - 1)),
                120.0,
            )

            wait_seconds += random.uniform(0.0, 3.0)

            print(
                f"Request failed: {type(error).__name__}: "
                f"{error}"
            )

            print(
                f"Waiting {wait_seconds:.1f} seconds "
                "before retrying..."
            )

            time.sleep(wait_seconds)

    raise RuntimeError(
        f"Unable to download {season} {measure_type} "
        f"after {MAX_ATTEMPTS} attempts."
    ) from last_error


def load_or_download(
    season: str,
    measure_type: str,
    force: bool,
) -> pd.DataFrame:
    """Load an existing file or download and save a new one."""

    path = output_path(
        season=season,
        measure_type=measure_type,
    )

    if path.exists() and not force:
        print(f"Loading existing file: {path}")

        frame = pd.read_parquet(path)

        if frame.empty:
            raise ValueError(
                f"Existing file is empty: {path}"
            )

        return frame

    frame = download_player_stats(
        season=season,
        measure_type=measure_type,
    )

    frame.to_parquet(
        path,
        index=False,
    )

    print(
        f"Saved {len(frame):,} rows to: {path}"
    )

    pause_seconds = random.uniform(
        MIN_PAUSE_SECONDS,
        MAX_PAUSE_SECONDS,
    )

    print(
        f"Pausing {pause_seconds:.1f} seconds..."
    )

    time.sleep(pause_seconds)

    return frame


def validate_measure_overlap(
    base_frame: pd.DataFrame,
    advanced_frame: pd.DataFrame,
    season: str,
) -> None:
    """Confirm that Base and Advanced contain the same players."""

    base_ids = set(
        base_frame["player_id"].astype("int64")
    )

    advanced_ids = set(
        advanced_frame["player_id"].astype("int64")
    )

    base_only = sorted(
        base_ids.difference(advanced_ids)
    )

    advanced_only = sorted(
        advanced_ids.difference(base_ids)
    )

    print(
        f"{season}: Base={len(base_ids):,}, "
        f"Advanced={len(advanced_ids):,}, "
        f"matched={len(base_ids & advanced_ids):,}, "
        f"base_only={len(base_only):,}, "
        f"advanced_only={len(advanced_only):,}"
    )

    if base_only or advanced_only:
        raise ValueError(
            f"Base and Advanced player IDs do not match "
            f"for {season}."
        )


def save_combined_files(
    frames_by_measure: dict[str, list[pd.DataFrame]],
) -> None:
    """Combine all downloaded seasons by measure type."""

    for measure_type, frames in frames_by_measure.items():
        combined = pd.concat(
            frames,
            ignore_index=True,
            sort=False,
        )

        combined = combined.sort_values(
            ["season", "player_name"],
            kind="stable",
        ).reset_index(drop=True)

        duplicate_mask = combined.duplicated(
            subset=["season", "player_id"],
            keep=False,
        )

        if duplicate_mask.any():
            duplicates = combined.loc[
                duplicate_mask,
                [
                    "season",
                    "player_id",
                    "player_name",
                    "team_abbreviation",
                ],
            ]

            raise ValueError(
                "Duplicate rows were found in the combined "
                f"{measure_type} data:\n"
                f"{duplicates.to_string(index=False)}"
            )

        parquet_path = (
            OUTPUT_DIRECTORY
            / (
                "historical_player_stats_"
                f"{measure_type.lower()}_2014_15_2021_22"
                ".parquet"
            )
        )

        csv_path = parquet_path.with_suffix(".csv")

        combined.to_parquet(
            parquet_path,
            index=False,
        )

        combined.to_csv(
            csv_path,
            index=False,
        )

        print()
        print(
            f"COMBINED {measure_type.upper()} DATA"
        )
        print(
            f"Rows: {len(combined):,}"
        )
        print(
            f"Seasons: {combined['season'].nunique()}"
        )
        print(
            f"Unique players: "
            f"{combined['player_id'].nunique():,}"
        )
        print(parquet_path)
        print(csv_path)


def parse_args() -> argparse.Namespace:
    """Parse command-line options."""

    parser = argparse.ArgumentParser(
        description=(
            "Download historical NBA Base and Advanced "
            "player-season totals."
        )
    )

    parser.add_argument(
        "--force",
        action="store_true",
        help=(
            "Download every season again even when a "
            "saved Parquet file already exists."
        ),
    )

    return parser.parse_args()


def main() -> None:
    """Download and validate historical NBA player statistics."""

    args = parse_args()

    OUTPUT_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    print("HISTORICAL NBA PLAYER EXTRACTION")
    print(f"nba_api version: {version('nba_api')}")
    print(f"Output directory: {OUTPUT_DIRECTORY}")
    print(
        f"Seasons: {SEASONS[0]} through {SEASONS[-1]}"
    )
    print()

    frames_by_measure: dict[
        str,
        list[pd.DataFrame],
    ] = {
        measure_type: []
        for measure_type in MEASURE_TYPES
    }

    for season in SEASONS:
        print("=" * 72)
        print(season)
        print("=" * 72)

        season_frames: dict[str, pd.DataFrame] = {}

        for measure_type in MEASURE_TYPES:
            frame = load_or_download(
                season=season,
                measure_type=measure_type,
                force=args.force,
            )

            season_frames[measure_type] = frame
            frames_by_measure[measure_type].append(
                frame
            )

        validate_measure_overlap(
            base_frame=season_frames["Base"],
            advanced_frame=season_frames["Advanced"],
            season=season,
        )

        print()

    save_combined_files(
        frames_by_measure=frames_by_measure
    )

    print()
    print("=" * 72)
    print("HISTORICAL EXTRACTION COMPLETED")
    print("=" * 72)
    print(
        "The existing 2022-23 through 2025-26 source "
        "database was not modified."
    )


if __name__ == "__main__":
    main()