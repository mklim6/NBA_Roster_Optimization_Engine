from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIRECTORY = PROJECT_ROOT / "src"
DATA_DIRECTORY = PROJECT_ROOT / "data" / "processed"
MODELS_DIRECTORY = PROJECT_ROOT / "models"
OUTPUTS_DIRECTORY = PROJECT_ROOT / "outputs"

UNIFIED_PLAYER_SEASONS_PATH = (
    DATA_DIRECTORY
    / "unified_player_seasons_2014_15_2025_26.parquet"
)
SKILL_PROFILES_PATH = (
    DATA_DIRECTORY
    / "player_skill_profiles_2025_26.parquet"
)

EXPECTED_CONTRIBUTION_MODEL_PATH = (
    MODELS_DIRECTORY
    / "final_expected_contribution_model.joblib"
)
EXPECTED_CONTRIBUTION_METADATA_PATH = (
    MODELS_DIRECTORY
    / "final_expected_contribution_metadata.json"
)
CALIBRATOR_PATH = (
    MODELS_DIRECTORY
    / "expected_contribution_calibrator.joblib"
)
CALIBRATOR_METADATA_PATH = (
    MODELS_DIRECTORY
    / "expected_contribution_calibrator_metadata.json"
)
AVAILABILITY_RISK_MODEL_PATH = (
    MODELS_DIRECTORY
    / "availability_risk_adjusted_contribution_model.joblib"
)
AVAILABILITY_RISK_METADATA_PATH = (
    MODELS_DIRECTORY
    / "availability_risk_adjusted_contribution_metadata.json"
)
UNCERTAINTY_MODEL_PATH = (
    MODELS_DIRECTORY
    / "contribution_uncertainty_model.joblib"
)
ACTIVE_UNCERTAINTY_MODEL_PATH = (
    MODELS_DIRECTORY
    / "active_contribution_uncertainty_model.joblib"
)
SURVIVAL_MODEL_PATH = (
    MODELS_DIRECTORY
    / "next_season_survival_probability.joblib"
)
ROTATION_MODEL_PATH = (
    MODELS_DIRECTORY
    / "multiyear_next_rotation_probability.joblib"
)

OUTPUT_PARQUET_PATH = (
    DATA_DIRECTORY
    / "current_player_projection_board_2025_26_to_2026_27.parquet"
)
OUTPUT_CSV_PATH = OUTPUT_PARQUET_PATH.with_suffix(".csv")
TEAM_SUMMARY_PATH = (
    OUTPUTS_DIRECTORY
    / "current_player_projection_board_team_summary.csv"
)
MODEL_SELECTION_PATH = (
    OUTPUTS_DIRECTORY
    / "current_player_projection_board_model_selection.json"
)

DEFAULT_TARGET_SCHEDULE_GAMES = 82.0
SCRIPT_VERSION = "active-uncertainty-v2-2026-08-03"

PROFILE_COLUMNS = [
    "player_id",
    "player_name",
    "team_abbreviation",
    "primary_skill",
    "secondary_skill",
    "value_tier",
    "confidence_tier",
    "main_pool_eligible",
    "roster_value_score",
    "roster_value_percentile",
    "raw_overall_score",
    "reliability_weight",
    "reliability_adjusted_score",
    "scoring_score",
    "shooting_score",
    "playmaking_score",
    "rebounding_score",
    "defense_score",
]

CURRENT_COLUMNS = [
    "player_id",
    "player_name",
    "season",
    "team_id",
    "team_abbreviation",
    "age",
    "games_played",
    "total_minutes",
    "minutes_per_game",
    "points_per_game",
    "assists_per_game",
    "rebounds_per_game",
    "base_fg_pct",
    "base_fg3_pct",
    "base_ft_pct",
    "advanced_off_rating",
    "advanced_def_rating",
    "advanced_net_rating",
    "advanced_efg_pct",
    "advanced_ts_pct",
    "advanced_usg_pct",
    "advanced_pie",
    "availability_rate",
    "rotation_player_flag",
    "high_minutes_flag",
    "sample_reliability",
]


def require_file(path: Path) -> None:
    if not path.exists():
        raise FileNotFoundError(
            f"Required file was not found:\n{path}"
        )


def read_json(path: Path) -> dict[str, Any]:
    require_file(path)
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def next_season_label(season: str) -> str:
    start = int(str(season)[:4]) + 1
    return f"{start}-{str(start + 1)[-2:]}"


def numeric_array(
    frame: pd.DataFrame,
    column: str,
    fill_value: float = 0.0,
) -> np.ndarray:
    return (
        pd.to_numeric(
            frame[column],
            errors="coerce",
        )
        .fillna(fill_value)
        .to_numpy(dtype=float)
    )


def require_features(
    frame: pd.DataFrame,
    features: list[str],
    model_name: str,
) -> None:
    missing = [
        feature
        for feature in features
        if feature not in frame.columns
    ]
    if missing:
        raise ValueError(
            f"{model_name} requires missing current-season features:\n"
            + "\n".join(missing)
        )


def register_expected_model_classes() -> None:
    """Make the custom minutes-model class available to joblib."""
    if str(SRC_DIRECTORY) not in sys.path:
        sys.path.insert(0, str(SRC_DIRECTORY))

    try:
        from train_expected_contribution_model import (  # type: ignore
            TwoStageConditionalMinutesModel,
        )
    except ImportError as error:
        raise ImportError(
            "Could not import TwoStageConditionalMinutesModel from "
            "src/train_expected_contribution_model.py."
        ) from error

    # Models trained by running the training file directly can be pickled
    # under the __main__ module. Exposing the class here supports both that
    # form and the normal imported-module form.
    import __main__

    setattr(
        __main__,
        "TwoStageConditionalMinutesModel",
        TwoStageConditionalMinutesModel,
    )


def load_current_players() -> tuple[pd.DataFrame, str, str]:
    require_file(UNIFIED_PLAYER_SEASONS_PATH)
    frame = pd.read_parquet(
        UNIFIED_PLAYER_SEASONS_PATH
    )

    if frame.empty:
        raise ValueError(
            "The unified player-season dataset is empty."
        )

    required = {
        "player_id",
        "player_name",
        "season",
        "season_start",
        "team_abbreviation",
        "minutes_per_game",
        "total_minutes",
        "advanced_pie",
        "weighted3_availability_rate",
        "weighted3_advanced_pie",
    }
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise ValueError(
            "The unified dataset is missing required columns:\n"
            + "\n".join(missing)
        )

    latest_start = int(
        pd.to_numeric(
            frame["season_start"],
            errors="raise",
        ).max()
    )

    current = frame.loc[
        pd.to_numeric(
            frame["season_start"],
            errors="coerce",
        ).eq(latest_start)
    ].copy()

    if current.empty:
        raise ValueError(
            "No rows were found for the latest season."
        )

    duplicate_mask = current.duplicated(
        subset=["player_id"],
        keep=False,
    )
    if duplicate_mask.any():
        duplicates = current.loc[
            duplicate_mask,
            [
                "player_id",
                "player_name",
                "team_abbreviation",
            ],
        ]
        raise ValueError(
            "Duplicate current-season player rows were found:\n"
            f"{duplicates.to_string(index=False)}"
        )

    current_season = str(
        current["season"].mode().iloc[0]
    )
    target_season = next_season_label(
        current_season
    )

    current["target_season"] = target_season
    current["target_season_start"] = latest_start + 1
    current["target_schedule_games"] = (
        DEFAULT_TARGET_SCHEDULE_GAMES
    )

    reliability = pd.to_numeric(
        current["sample_reliability"],
        errors="coerce",
    ).fillna(0.0).clip(
        lower=0.0,
        upper=1.0,
    )

    current["training_sample_weight"] = (
        0.25 + 0.75 * reliability
    ).clip(
        lower=0.25,
        upper=1.0,
    )

    return (
        current.sort_values("player_name")
        .reset_index(drop=True),
        current_season,
        target_season,
    )


def predict_expected_contribution(
    bundle: dict[str, Any],
    frame: pd.DataFrame,
) -> tuple[
    np.ndarray,
    np.ndarray,
    np.ndarray,
    dict[str, np.ndarray],
]:
    features = list(bundle["features"])
    require_features(
        frame,
        features,
        "Final expected-contribution model",
    )
    X = frame[features]

    staged_models = bundle["staged_models"]
    survival_model = staged_models["survival"]
    minutes_model = staged_models["minutes"]
    availability_model = staged_models[
        "availability"
    ]
    pie_model = staged_models["pie"]

    survival_probability = np.clip(
        survival_model.predict_proba(X)[:, 1],
        0.001,
        0.999,
    )

    conditional_minutes = np.clip(
        minutes_model.predict(X),
        0.0,
        40.0,
    )
    conditional_minutes = (
        0.75 * conditional_minutes
        + 0.25
        * numeric_array(
            frame,
            "minutes_per_game",
        )
    )

    conditional_availability = np.clip(
        availability_model.predict(X),
        0.0,
        1.0,
    )
    history_availability = (
        pd.to_numeric(
            frame["weighted3_availability_rate"],
            errors="coerce",
        )
        .fillna(
            pd.to_numeric(
                frame["availability_rate"],
                errors="coerce",
            )
        )
        .fillna(0.0)
        .to_numpy(dtype=float)
    )
    conditional_availability = np.clip(
        0.75 * conditional_availability
        + 0.25 * history_availability,
        0.0,
        1.0,
    )

    conditional_pie = np.clip(
        pie_model.predict(X),
        -0.05,
        0.30,
    )
    history_pie = (
        pd.to_numeric(
            frame["weighted3_advanced_pie"],
            errors="coerce",
        )
        .fillna(
            pd.to_numeric(
                frame["advanced_pie"],
                errors="coerce",
            )
        )
        .fillna(0.0)
        .to_numpy(dtype=float)
    )
    conditional_pie = np.clip(
        0.75 * conditional_pie
        + 0.25 * history_pie,
        -0.05,
        0.30,
    )

    schedule_games = numeric_array(
        frame,
        "target_schedule_games",
        DEFAULT_TARGET_SCHEDULE_GAMES,
    )

    staged = (
        survival_probability
        * conditional_minutes
        * conditional_availability
        * schedule_games
        * conditional_pie
    )

    direct = np.asarray(
        bundle["direct_model"].predict(X),
        dtype=float,
    )

    persistence = (
        numeric_array(frame, "advanced_pie")
        * numeric_array(frame, "total_minutes")
    )

    direct_weight = float(bundle["direct_weight"])
    staged_weight = float(
        bundle.get(
            "staged_weight",
            1.0 - direct_weight,
        )
    )
    baseline_weight = float(
        bundle["baseline_weight"]
    )

    staged_direct = (
        direct_weight * direct
        + staged_weight * staged
    )
    final = (
        (1.0 - baseline_weight)
        * staged_direct
        + baseline_weight * persistence
    )

    components = {
        "survival_probability": survival_probability,
        "conditional_minutes_per_game": (
            conditional_minutes
        ),
        "conditional_availability_rate": (
            conditional_availability
        ),
        "conditional_pie": conditional_pie,
        "target_schedule_games": schedule_games,
    }

    return final, staged, direct, {
        **components,
        "persistence": persistence,
    }


def apply_expected_calibrator(
    bundle: dict[str, Any],
    frame: pd.DataFrame,
    base_prediction: np.ndarray,
    persistence: np.ndarray,
) -> np.ndarray:
    parameters = dict(bundle["parameters"])
    bins = list(bundle["workload_bins"])
    labels = list(bundle["workload_labels"])

    workload_group = pd.cut(
        pd.to_numeric(
            frame["minutes_per_game"],
            errors="coerce",
        ),
        bins=bins,
        labels=labels,
        right=False,
        include_lowest=True,
    ).astype(str)

    global_weight = float(
        parameters["global_base_weight"]
    )
    global_correction = float(
        parameters["global_correction"]
    )
    group_weights = {
        str(key): float(value)
        for key, value in dict(
            parameters.get(
                "group_base_weights",
                {},
            )
        ).items()
    }
    group_corrections = {
        str(key): float(value)
        for key, value in dict(
            parameters.get(
                "group_corrections",
                {},
            )
        ).items()
    }

    result = np.empty(len(frame), dtype=float)
    for index, group in enumerate(
        workload_group.astype(str)
    ):
        weight = group_weights.get(
            group,
            global_weight,
        )
        correction = group_corrections.get(
            group,
            global_correction,
        )
        result[index] = (
            weight * base_prediction[index]
            + (1.0 - weight) * persistence[index]
            + correction
        )

    return result


def predict_availability_candidate(
    candidate: dict[str, Any],
    frame: pd.DataFrame,
    features: list[str],
) -> np.ndarray:
    require_features(
        frame,
        features,
        "Availability-risk model",
    )
    X = frame[features]
    kind = str(candidate["kind"])

    if kind == "native_regressor":
        prediction = candidate["model"].predict(X)
    elif kind == "survival_conditional":
        active_probability = candidate[
            "survival_model"
        ].predict_proba(X)[:, 1]
        conditional = candidate[
            "conditional_model"
        ].predict(X)
        prediction = active_probability * conditional
    elif kind == "regime_model":
        high_probability = candidate[
            "classifier"
        ].predict_proba(X)[:, 1]
        low_prediction = candidate[
            "low_model"
        ].predict(X)
        high_prediction = candidate[
            "high_model"
        ].predict(X)
        prediction = (
            high_probability * high_prediction
            + (1.0 - high_probability)
            * low_prediction
        )
    else:
        raise ValueError(
            f"Unknown availability bundle kind: {kind}"
        )

    return np.clip(
        np.asarray(prediction, dtype=float),
        0.0,
        1.0,
    )


def predict_risk_adjusted_contribution(
    bundle: dict[str, Any],
    frame: pd.DataFrame,
    staged: np.ndarray,
    direct: np.ndarray,
    conditional_minutes: np.ndarray,
    conditional_pie: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    features = list(bundle["features"])
    availability = predict_availability_candidate(
        candidate=bundle["availability_model"],
        frame=frame,
        features=features,
    )

    schedule_games = numeric_array(
        frame,
        "target_schedule_games",
        DEFAULT_TARGET_SCHEDULE_GAMES,
    )
    risk_staged = (
        availability
        * conditional_minutes
        * conditional_pie
        * schedule_games
    )

    risk_final = (
        float(
            bundle[
                "new_risk_adjusted_staged_weight"
            ]
        )
        * risk_staged
        + float(bundle["original_staged_weight"])
        * staged
        + float(bundle["direct_contribution_weight"])
        * direct
    )

    return risk_final, risk_staged, availability


def logit(probabilities: np.ndarray) -> np.ndarray:
    clipped = np.clip(
        probabilities,
        1e-6,
        1.0 - 1e-6,
    )
    return np.log(clipped / (1.0 - clipped))


def predict_survival_probability(
    bundle: dict[str, Any],
    frame: pd.DataFrame,
) -> np.ndarray:
    features = list(bundle["features"])
    require_features(
        frame,
        features,
        "Standalone survival model",
    )

    model_name = str(bundle["model_name"])
    baseline = float(bundle["baseline_probability"])

    if model_name == "baseline_only" or bundle["model"] is None:
        calibrated = np.full(
            len(frame),
            baseline,
            dtype=float,
        )
    else:
        raw = bundle["model"].predict_proba(
            frame[features]
        )[:, 1]
        method = str(bundle["calibration_method"])
        calibrator = bundle["calibrator"]

        if method == "none":
            calibrated = raw
        elif method == "platt":
            calibrated = calibrator.predict_proba(
                logit(raw).reshape(-1, 1)
            )[:, 1]
        elif method == "isotonic":
            calibrated = calibrator.predict(raw)
        else:
            raise ValueError(
                f"Unknown survival calibration: {method}"
            )

    blended = (
        float(bundle["model_weight"])
        * calibrated
        + (1.0 - float(bundle["model_weight"]))
        * baseline
    )

    return np.clip(
        blended,
        float(bundle.get("probability_lower", 0.001)),
        float(bundle.get("probability_upper", 0.999)),
    )


def predict_rotation_probability(
    bundle: dict[str, Any],
    frame: pd.DataFrame,
) -> np.ndarray:
    features = list(bundle["features"])
    require_features(
        frame,
        features,
        "Rotation-probability model",
    )
    model = bundle["model"]
    probabilities = model.predict_proba(
        frame[features]
    )[:, 1]
    return np.clip(
        probabilities,
        float(bundle.get("probability_lower", 0.01)),
        float(bundle.get("probability_upper", 0.99)),
    )


def predict_uncertainty(
    bundle: dict[str, Any],
    frame: pd.DataFrame,
) -> pd.DataFrame:
    features = list(bundle["features"])
    require_features(
        frame,
        features,
        "Contribution-uncertainty model",
    )

    quantiles = [
        float(value)
        for value in bundle["quantiles"]
    ]
    models = bundle["quantile_models"]

    raw = np.column_stack(
        [
            models[quantile].predict(
                frame[features]
            )
            for quantile in quantiles
        ]
    )
    ordered = np.sort(raw, axis=1)

    columns = [
        f"q{int(quantile * 100):02d}"
        for quantile in quantiles
    ]
    output = pd.DataFrame(
        ordered,
        columns=columns,
        index=frame.index,
    )

    required_columns = {
        "q05",
        "q10",
        "q50",
        "q90",
        "q95",
    }
    missing = sorted(
        required_columns.difference(output.columns)
    )
    if missing:
        raise ValueError(
            "The uncertainty bundle does not contain expected quantiles:\n"
            + "\n".join(missing)
        )

    adjustment_80 = float(
        bundle["conformal_adjustment_80"]
    )
    adjustment_90 = float(
        bundle["conformal_adjustment_90"]
    )

    output["lower_80"] = (
        output["q10"] - adjustment_80
    )
    output["upper_80"] = (
        output["q90"] + adjustment_80
    )
    output["lower_90"] = (
        output["q05"] - adjustment_90
    )
    output["upper_90"] = (
        output["q95"] + adjustment_90
    )
    output["interval_width_80"] = (
        output["upper_80"] - output["lower_80"]
    )
    output["interval_width_90"] = (
        output["upper_90"] - output["lower_90"]
    )

    return output


def metric_from_metadata(
    metadata: dict[str, Any],
    path: tuple[str, ...],
) -> float | None:
    value: Any = metadata
    try:
        for key in path:
            value = value[key]
        return float(value)
    except (KeyError, TypeError, ValueError):
        return None


def select_point_projection(
    raw: np.ndarray,
    calibrated: np.ndarray,
    risk_adjusted: np.ndarray,
) -> tuple[str, np.ndarray, dict[str, float | None]]:
    calibration_metadata = read_json(
        CALIBRATOR_METADATA_PATH
    )
    risk_metadata = read_json(
        AVAILABILITY_RISK_METADATA_PATH
    )

    metrics: dict[str, float | None] = {
        "raw_expected_contribution": metric_from_metadata(
            calibration_metadata,
            ("confirmation_metrics", "raw", "weighted_mae"),
        ),
        "calibrated_expected_contribution": metric_from_metadata(
            calibration_metadata,
            (
                "confirmation_metrics",
                "calibrated",
                "weighted_mae",
            ),
        ),
        "availability_risk_adjusted": metric_from_metadata(
            risk_metadata,
            (
                "confirmation_metrics",
                "risk_adjusted",
                "weighted_mae",
            ),
        ),
    }

    predictions = {
        "raw_expected_contribution": raw,
        "calibrated_expected_contribution": calibrated,
        "availability_risk_adjusted": risk_adjusted,
    }

    valid = {
        name: score
        for name, score in metrics.items()
        if score is not None and np.isfinite(score)
    }

    if valid:
        selected_name = min(
            valid,
            key=valid.get,  # type: ignore[arg-type]
        )
    else:
        selected_name = "availability_risk_adjusted"

    return (
        selected_name,
        predictions[selected_name],
        metrics,
    )


def merge_skill_profiles(
    board: pd.DataFrame,
) -> pd.DataFrame:
    if not SKILL_PROFILES_PATH.exists():
        print(
            "Skill-profile file was not found. "
            "Continuing without profile columns."
        )
        return board

    profiles = pd.read_parquet(
        SKILL_PROFILES_PATH
    )
    if profiles.empty:
        return board

    merge_keys = ["player_id"]
    available = [
        column
        for column in PROFILE_COLUMNS
        if column in profiles.columns
        and column not in merge_keys
        and column not in board.columns
    ]

    return board.merge(
        profiles[
            [*merge_keys, *available]
        ],
        how="left",
        on=merge_keys,
        validate="one_to_one",
    )


def build_team_summary(
    board: pd.DataFrame,
) -> pd.DataFrame:
    summary = (
        board.groupby(
            "team_abbreviation",
            as_index=False,
        )
        .agg(
            players=("player_id", "size"),
            optimizer_pool_players=(
                "main_pool_eligible",
                "sum",
            ),
            expected_contribution=(
                "projected_expected_contribution",
                "sum",
            ),
            downside_contribution_80=(
                "projected_downside_contribution_80",
                "sum",
            ),
            upside_contribution_80=(
                "projected_upside_contribution_80",
                "sum",
            ),
            average_survival_probability=(
                "projected_survival_probability",
                "mean",
            ),
            average_rotation_probability=(
                "projected_rotation_probability",
                "mean",
            ),
            average_uncertainty_percentile=(
                "projection_uncertainty_percentile",
                "mean",
            ),
        )
    )

    numeric_columns = summary.select_dtypes(
        include="number"
    ).columns
    summary[numeric_columns] = summary[
        numeric_columns
    ].round(4)

    return summary.sort_values(
        "expected_contribution",
        ascending=False,
    ).reset_index(drop=True)


def main() -> None:
    DATA_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )
    OUTPUTS_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    required_paths = [
        EXPECTED_CONTRIBUTION_MODEL_PATH,
        EXPECTED_CONTRIBUTION_METADATA_PATH,
        CALIBRATOR_PATH,
        CALIBRATOR_METADATA_PATH,
        AVAILABILITY_RISK_MODEL_PATH,
        AVAILABILITY_RISK_METADATA_PATH,
        UNCERTAINTY_MODEL_PATH,
        ACTIVE_UNCERTAINTY_MODEL_PATH,
        SURVIVAL_MODEL_PATH,
        ROTATION_MODEL_PATH,
    ]
    for path in required_paths:
        require_file(path)

    register_expected_model_classes()

    current, current_season, target_season = (
        load_current_players()
    )

    print("=" * 80)
    print("CURRENT PLAYER PROJECTION BOARD")
    print("=" * 80)
    print(f"Script version: {SCRIPT_VERSION}")
    print(f"Current season: {current_season}")
    print(f"Projection season: {target_season}")
    print(f"Players: {len(current):,}")
    print(
        f"Teams: {current['team_abbreviation'].nunique():,}"
    )
    print()

    expected_bundle = joblib.load(
        EXPECTED_CONTRIBUTION_MODEL_PATH
    )
    calibrator_bundle = joblib.load(
        CALIBRATOR_PATH
    )
    risk_bundle = joblib.load(
        AVAILABILITY_RISK_MODEL_PATH
    )
    uncertainty_bundle = joblib.load(
        UNCERTAINTY_MODEL_PATH
    )
    active_uncertainty_bundle = joblib.load(
        ACTIVE_UNCERTAINTY_MODEL_PATH
    )
    survival_bundle = joblib.load(
        SURVIVAL_MODEL_PATH
    )
    rotation_bundle = joblib.load(
        ROTATION_MODEL_PATH
    )

    (
        raw_expected,
        staged_expected,
        direct_expected,
        components,
    ) = predict_expected_contribution(
        expected_bundle,
        current,
    )

    calibrated_expected = apply_expected_calibrator(
        bundle=calibrator_bundle,
        frame=current,
        base_prediction=raw_expected,
        persistence=components["persistence"],
    )

    (
        risk_expected,
        risk_staged,
        unconditional_availability,
    ) = predict_risk_adjusted_contribution(
        bundle=risk_bundle,
        frame=current,
        staged=staged_expected,
        direct=direct_expected,
        conditional_minutes=components[
            "conditional_minutes_per_game"
        ],
        conditional_pie=components[
            "conditional_pie"
        ],
    )

    (
        selected_point_model,
        selected_expected,
        selection_metrics,
    ) = select_point_projection(
        raw=raw_expected,
        calibrated=calibrated_expected,
        risk_adjusted=risk_expected,
    )

    survival_probability = (
        predict_survival_probability(
            survival_bundle,
            current,
        )
    )
    rotation_probability = (
        predict_rotation_probability(
            rotation_bundle,
            current,
        )
    )
    uncertainty = predict_uncertainty(
        uncertainty_bundle,
        current,
    )
    active_uncertainty = predict_uncertainty(
        active_uncertainty_bundle,
        current,
    )

    available_current_columns = [
        column
        for column in CURRENT_COLUMNS
        if column in current.columns
    ]
    board = current[
        available_current_columns
    ].copy()
    board["projection_season"] = target_season
    board["selected_point_model"] = (
        selected_point_model
    )

    board["projected_expected_contribution"] = (
        selected_expected
    )
    board["projected_raw_expected_contribution"] = (
        raw_expected
    )
    board[
        "projected_calibrated_expected_contribution"
    ] = calibrated_expected
    board[
        "projected_availability_risk_adjusted_contribution"
    ] = risk_expected
    board["projected_staged_contribution"] = (
        staged_expected
    )
    board["projected_risk_adjusted_staged_contribution"] = (
        risk_staged
    )
    board["projected_direct_contribution"] = (
        direct_expected
    )
    board["current_persistence_contribution"] = (
        components["persistence"]
    )

    board["projected_survival_probability"] = (
        survival_probability
    )
    board[
        "projected_internal_survival_probability"
    ] = components["survival_probability"]
    board["projected_rotation_probability"] = (
        rotation_probability
    )
    board["projected_minutes_per_game_if_active"] = (
        components["conditional_minutes_per_game"]
    )
    board["projected_availability_rate_if_active"] = (
        components["conditional_availability_rate"]
    )
    board[
        "projected_unconditional_availability_rate"
    ] = unconditional_availability
    board["projected_pie_if_active"] = components[
        "conditional_pie"
    ]
    board["projected_expected_total_minutes"] = (
        unconditional_availability
        * components["conditional_minutes_per_game"]
        * components["target_schedule_games"]
    )

    unconditional_uncertainty_rename = {
        "q05": "projected_unconditional_contribution_q05",
        "q10": "projected_unconditional_contribution_q10",
        "q50": "projected_unconditional_contribution_q50",
        "q90": "projected_unconditional_contribution_q90",
        "q95": "projected_unconditional_contribution_q95",
        "lower_80": (
            "projected_unconditional_lower_80"
        ),
        "upper_80": (
            "projected_unconditional_upper_80"
        ),
        "lower_90": (
            "projected_unconditional_lower_90"
        ),
        "upper_90": (
            "projected_unconditional_upper_90"
        ),
        "interval_width_80": (
            "projected_unconditional_interval_width_80"
        ),
        "interval_width_90": (
            "projected_unconditional_interval_width_90"
        ),
    }

    for (
        source,
        target,
    ) in unconditional_uncertainty_rename.items():
        board[target] = uncertainty[
            source
        ].to_numpy(dtype=float)

    active_uncertainty_rename = {
        "q05": "projected_active_contribution_q05",
        "q10": "projected_active_contribution_q10",
        "q50": "projected_active_contribution_q50",
        "q90": "projected_active_contribution_q90",
        "q95": "projected_active_contribution_q95",
        "lower_80": (
            "projected_active_downside_contribution_80"
        ),
        "upper_80": (
            "projected_active_upside_contribution_80"
        ),
        "lower_90": (
            "projected_active_downside_contribution_90"
        ),
        "upper_90": (
            "projected_active_upside_contribution_90"
        ),
        "interval_width_80": (
            "projected_active_interval_width_80"
        ),
        "interval_width_90": (
            "projected_active_interval_width_90"
        ),
    }

    for (
        source,
        target,
    ) in active_uncertainty_rename.items():
        board[target] = active_uncertainty[
            source
        ].to_numpy(dtype=float)

    # Compatibility aliases for the trade engine. These now refer to the
    # player-specific interval conditional on appearing next season.
    board["projected_contribution_q05"] = board[
        "projected_active_contribution_q05"
    ]
    board["projected_contribution_q10"] = board[
        "projected_active_contribution_q10"
    ]
    board["projected_contribution_q50"] = board[
        "projected_active_contribution_q50"
    ]
    board["projected_contribution_q90"] = board[
        "projected_active_contribution_q90"
    ]
    board["projected_contribution_q95"] = board[
        "projected_active_contribution_q95"
    ]
    board["projected_downside_contribution_80"] = board[
        "projected_active_downside_contribution_80"
    ]
    board["projected_upside_contribution_80"] = board[
        "projected_active_upside_contribution_80"
    ]
    board["projected_downside_contribution_90"] = board[
        "projected_active_downside_contribution_90"
    ]
    board["projected_upside_contribution_90"] = board[
        "projected_active_upside_contribution_90"
    ]
    board["projection_interval_width_80"] = board[
        "projected_active_interval_width_80"
    ]
    board["projection_interval_width_90"] = board[
        "projected_active_interval_width_90"
    ]

    board["projection_downside_gap_80"] = (
        board["projected_expected_contribution"]
        - board[
            "projected_active_downside_contribution_80"
        ]
    )
    board["projection_upside_gap_80"] = (
        board[
            "projected_active_upside_contribution_80"
        ]
        - board["projected_expected_contribution"]
    )

    board[
        "expected_point_outside_unconditional_80_flag"
    ] = (
        (
            board["projected_expected_contribution"]
            < board[
                "projected_unconditional_lower_80"
            ]
        )
        | (
            board["projected_expected_contribution"]
            > board[
                "projected_unconditional_upper_80"
            ]
        )
    ).astype(int)

    board[
        "active_median_outside_active_80_flag"
    ] = (
        (
            board["projected_active_contribution_q50"]
            < board[
                "projected_active_downside_contribution_80"
            ]
        )
        | (
            board["projected_active_contribution_q50"]
            > board[
                "projected_active_upside_contribution_80"
            ]
        )
    ).astype(int)

    # Preserve the original column name for downstream compatibility.
    board["point_outside_80_interval_flag"] = board[
        "expected_point_outside_unconditional_80_flag"
    ]

    board["expected_contribution_percentile"] = (
        board["projected_expected_contribution"]
        .rank(method="average", pct=True)
        * 100.0
    )
    board["downside_contribution_percentile"] = (
        board[
            "projected_active_downside_contribution_80"
        ]
        .rank(method="average", pct=True)
        * 100.0
    )
    board["projection_uncertainty_percentile"] = (
        board["projected_active_interval_width_80"]
        .rank(method="average", pct=True)
        * 100.0
    )
    board[
        "unconditional_uncertainty_percentile"
    ] = (
        board[
            "projected_unconditional_interval_width_80"
        ]
        .rank(method="average", pct=True)
        * 100.0
    )

    # This is a decision score, not a calibrated prediction interval. The
    # point estimate already contains survival risk, while the active lower
    # bound supplies player-specific performance downside.
    board[
        "conservative_contribution_score_25pct_downside"
    ] = (
        0.75
        * board["projected_expected_contribution"]
        + 0.25
        * board[
            "projected_active_downside_contribution_80"
        ]
    )

    board[
        "survival_weighted_active_downside_score"
    ] = (
        board["projected_survival_probability"]
        * board[
            "projected_active_downside_contribution_80"
        ]
    )

    board = merge_skill_profiles(board)

    if "main_pool_eligible" not in board.columns:
        board["main_pool_eligible"] = True
    board["main_pool_eligible"] = (
        board["main_pool_eligible"]
        .fillna(False)
        .astype(bool)
    )

    board = board.sort_values(
        [
            "main_pool_eligible",
            "projected_expected_contribution",
            "projected_downside_contribution_80",
        ],
        ascending=[False, False, False],
    ).reset_index(drop=True)
    board.insert(
        0,
        "projection_board_rank",
        np.arange(1, len(board) + 1),
    )

    numeric_columns = board.select_dtypes(
        include="number"
    ).columns
    board[numeric_columns] = board[
        numeric_columns
    ].round(6)

    team_summary = build_team_summary(board)

    board.to_parquet(
        OUTPUT_PARQUET_PATH,
        index=False,
    )
    board.to_csv(
        OUTPUT_CSV_PATH,
        index=False,
    )
    team_summary.to_csv(
        TEAM_SUMMARY_PATH,
        index=False,
    )

    model_selection_output = {
        "current_season": current_season,
        "projection_season": target_season,
        "selected_point_model": selected_point_model,
        "confirmation_weighted_mae_candidates": (
            selection_metrics
        ),
        "player_rows": len(board),
        "team_count": int(
            board["team_abbreviation"].nunique()
        ),
        "unconditional_uncertainty_model": str(
            UNCERTAINTY_MODEL_PATH
        ),
        "active_uncertainty_model": str(
            ACTIVE_UNCERTAINTY_MODEL_PATH
        ),
        "trade_downside_definition": (
            "80% conformal lower bound conditional on "
            "appearing next season"
        ),
        "output_parquet": str(OUTPUT_PARQUET_PATH),
        "output_csv": str(OUTPUT_CSV_PATH),
        "team_summary": str(TEAM_SUMMARY_PATH),
    }
    with MODEL_SELECTION_PATH.open(
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            model_selection_output,
            file,
            indent=2,
            default=float,
        )

    print("=" * 80)
    print("PROJECTION BOARD CREATED")
    print("=" * 80)
    print(
        f"Selected point model: {selected_point_model}"
    )
    print("Confirmation weighted-MAE candidates:")
    for model_name, score in selection_metrics.items():
        score_text = (
            "unavailable"
            if score is None
            else f"{score:.5f}"
        )
        print(f"  {model_name}: {score_text}")
    print()
    print(
        "Trade downside: active-season 80% conformal lower bound"
    )
    print(
        "Full absence risk: represented separately by survival probability "
        "and unconditional intervals"
    )
    print()
    print("TOP 20 MAIN-POOL PROJECTIONS")

    preview_columns = [
        "projection_board_rank",
        "player_name",
        "team_abbreviation",
        "projected_expected_contribution",
        "projected_active_downside_contribution_80",
        "projected_active_upside_contribution_80",
        "projected_survival_probability",
        "survival_weighted_active_downside_score",
        "projected_rotation_probability",
        "projection_uncertainty_percentile",
        "primary_skill",
        "secondary_skill",
    ]
    preview_columns = [
        column
        for column in preview_columns
        if column in board.columns
    ]
    print(
        board.loc[
            board["main_pool_eligible"]
        ]
        .head(20)[preview_columns]
        .to_string(index=False)
    )
    print()
    print("SAVED FILES")
    print(OUTPUT_PARQUET_PATH)
    print(OUTPUT_CSV_PATH)
    print(TEAM_SUMMARY_PATH)
    print(MODEL_SELECTION_PATH)


if __name__ == "__main__":
    main()