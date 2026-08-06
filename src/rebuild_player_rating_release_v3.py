"""Rebuild NBA player ratings with accomplishment-aware OVR and ceiling POT.

OVR = current demonstrated NBA value.
POT = plausible career ceiling and is never below OVR.
FUT = projected future standing and may be below OVR.

This is a presentation-layer rebuild. Projection, optimizer, legality, salary,
and simulation source values remain unchanged.
"""
from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

SCRIPT_VERSION = "player-rating-accomplishment-v3-2026-08-06"
RELEASE_NAME = "player_ratings_2026_27_v3"

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data" / "processed"
OUTPUT_DIR = PROJECT_ROOT / "outputs"
APP_DIR = PROJECT_ROOT / "app_data"

RATING_INPUTS = [
    DATA_DIR / "player_rating_release_2026_27_v2.parquet",
    DATA_DIR / "player_rating_release_2026_27_v2.csv",
    DATA_DIR / "player_rating_release_2026_27_v1.parquet",
    DATA_DIR / "player_rating_release_2026_27_v1.csv",
]
HISTORY_INPUTS = [
    DATA_DIR / "unified_player_seasons_2014_15_2025_26.parquet",
    DATA_DIR / "unified_player_seasons_2014_15_2025_26.csv",
]

OUT_PARQUET = DATA_DIR / "player_rating_release_2026_27_v3.parquet"
OUT_CSV = OUT_PARQUET.with_suffix(".csv")
OUT_JSON = APP_DIR / "player_ratings_2026_27_v3.json"
ACTIVE_ALIAS = APP_DIR / "player_ratings_2026_27_v2.json"
OUT_VALIDATION = OUTPUT_DIR / "player_rating_v3_validation.csv"
OUT_DISTRIBUTION = OUTPUT_DIR / "player_rating_v3_distribution.csv"
OUT_AUDIT = OUTPUT_DIR / "player_rating_v3_player_audit.csv"
OUT_TOP100 = OUTPUT_DIR / "player_rating_v3_top_100.csv"
OUT_METHOD = OUTPUT_DIR / "player_rating_v3_methodology.json"

# Conservative current-value scale. A perfect 99.9 OVR is intentionally not used.
OVR_PCT = np.array([0,5,10,20,30,40,50,60,70,80,85,90,92.5,95,97,98,99,99.5,100], dtype=float)
OVR_VAL = np.array([60,64,67,71,74,77,79.5,81.5,83.5,85.5,87,89,90.5,92.5,94.5,95.7,96.9,97.7,98.5], dtype=float)
POT_PCT = OVR_PCT.copy()
POT_VAL = np.array([60,64,67,71,74,77,80,82,84,86,87.5,89.5,91,93,95,96.5,97.8,98.7,99.5], dtype=float)

CURRENT_IMPACT_WEIGHTS = {
    "pie_rank_pct": .30,
    "net_rating_rank_pct": .15,
    "minutes_rank_pct": .20,
    "points_rank_pct": .15,
    "assists_rank_pct": .10,
    "rebounds_rank_pct": .10,
}
ROLE_WEIGHTS = {
    "points_rank_pct": .30,
    "assists_rank_pct": .18,
    "rebounds_rank_pct": .12,
    "usage_rank_pct": .22,
    "minutes_rank_pct": .18,
}
OVR_WEIGHTS = {
    "expected_contribution_rank_pct": .26,
    "current_impact_rank_pct": .18,
    "role_burden_rank_pct": .12,
    "downside_contribution_percentile_rating": .11,
    "roster_value_percentile_rating": .10,
    "skill_mean_percentile_rating": .10,
    "efficiency_percentile_rating": .07,
    "availability_percentile_rating": .04,
    "skill_peak_percentile_rating": .02,
}
FUT_WEIGHTS = {
    "future_peak_rank_pct": .55,
    "future_long_rank_pct": .25,
    "future_growth_rank_pct": .20,
}
POT_WEIGHTS = {
    "future_outlook_percentile_v3": .34,
    "upside_contribution_rank_pct": .22,
    "skill_peak_percentile_rating": .17,
    "age_runway_score": .15,
    "overall_league_percentile_v3": .12,
}

GRADE_THRESHOLDS = [(97,"A+"),(93,"A"),(90,"A-"),(87,"B+"),(83,"B"),(80,"B-"),(77,"C+"),(73,"C"),(70,"C-"),(67,"D+"),(63,"D"),(60,"D-")]
ROLE_THRESHOLDS = [(97,"MVP-level superstar"),(94,"Franchise superstar"),(90,"All-Star caliber"),(87,"High-end starter"),(83,"Quality starter"),(79,"Rotation player"),(75,"Bench contributor"),(70,"Depth player"),(60,"Developmental player")]

APP_COLUMNS = [
    "player_id","player_name","team_abbreviation","age","league_overall_rank","team_overall_rank",
    "overall_rating","overall_grade","role_label","archetype","primary_skill","secondary_skill",
    "primary_strength","secondary_strength","strengths","concerns","rating_confidence",
    "development_direction","development_arrow","future_peak_season",
    "games_played","minutes_per_game","points_per_game","rebounds_per_game","assists_per_game",
    "field_goal_pct","three_point_pct","true_shooting_pct","usage_pct",
    "scoring_rating","scoring_grade","shooting_rating","shooting_grade","playmaking_rating","playmaking_grade",
    "rebounding_rating","rebounding_grade","defense_rating","defense_grade","efficiency_rating","efficiency_grade",
    "availability_rating","availability_grade","potential_rating","potential_grade",
    "future_outlook_rating","future_outlook_grade","contract_value_rating","contract_value_grade","contract_value_source",
    "trade_value_rating","trade_value_grade","trade_value_source","market_asset_class","protected_player_flag",
    "salary_2026_27","future_salary_commitment","career_seasons","career_games","career_minutes","evidence_weight",
    "rating_scope_note","finishing_scope_note",
]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--self-test", action="store_true")
    return p.parse_args()


def locate(candidates: list[Path], label: str) -> Path:
    for path in candidates:
        if path.exists():
            return path
    raise FileNotFoundError(label + " not found:\n" + "\n".join(map(str, candidates)))


def read_frame(path: Path) -> pd.DataFrame:
    return pd.read_parquet(path) if path.suffix.lower() == ".parquet" else pd.read_csv(path, low_memory=False)


def player_id(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    try:
        x = float(value)
        if math.isfinite(x) and x.is_integer():
            return str(int(x))
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    return text[:-2] if text.endswith(".0") else text


def safe_float(value: Any, default: float = np.nan) -> float:
    try:
        x = float(value)
    except (TypeError, ValueError):
        return default
    return x if math.isfinite(x) else default


def num(frame: pd.DataFrame, column: str, default: float = np.nan) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(default, index=frame.index, dtype=float)
    return pd.to_numeric(frame[column], errors="coerce").astype(float)


def first_existing(frame: pd.DataFrame, names: Iterable[str]) -> str | None:
    columns = set(frame.columns)
    return next((name for name in names if name in columns), None)


def pct_rank(values: pd.Series, fill: float = 50.0) -> pd.Series:
    values = pd.to_numeric(values, errors="coerce")
    valid = values.notna()
    out = pd.Series(fill, index=values.index, dtype=float)
    if valid.any():
        out.loc[valid] = values.loc[valid].rank(method="average", pct=True) * 100.0
    return out.clip(0, 100)


def weighted(frame: pd.DataFrame, weights: dict[str, float]) -> pd.Series:
    if not math.isclose(sum(weights.values()), 1.0, abs_tol=1e-9):
        raise ValueError("Weights must sum to 1.0")
    missing = sorted(set(weights) - set(frame.columns))
    if missing:
        raise ValueError("Missing weighted columns:\n" + "\n".join(missing))
    out = pd.Series(0.0, index=frame.index, dtype=float)
    for column, weight in weights.items():
        out += num(frame, column, 50.0).fillna(50.0).clip(0, 100) * weight
    return out.clip(0, 100)


def map_rating(value: Any, pcts: np.ndarray, ratings: np.ndarray) -> float:
    return round(float(np.interp(np.clip(safe_float(value, 50.0), 0, 100), pcts, ratings)), 1)


def grade(value: Any) -> str:
    x = safe_float(value, 60.0)
    return next((label for threshold, label in GRADE_THRESHOLDS if x >= threshold), "D-")


def role(value: Any) -> str:
    x = safe_float(value, 60.0)
    return next((label for threshold, label in ROLE_THRESHOLDS if x >= threshold), "Developmental player")


def age_runway(age: Any) -> float:
    ages = np.array([18,20,22,24,26,28,30,33,36,40], dtype=float)
    scores = np.array([100,99,96,90,80,67,52,32,16,5], dtype=float)
    return round(float(np.interp(safe_float(age, 28.0), ages, scores)), 3)


def minimum_pot_gap(age: Any) -> float:
    x = safe_float(age, 28.0)
    if x <= 20: return 2.5
    if x <= 22: return 2.0
    if x <= 24: return 1.5
    if x <= 26: return .7
    if x <= 27: return .3
    return 0.0


def evidence(career_seasons: Any, career_minutes: Any, current_minutes: Any, reliability: Any) -> float:
    s = min(max(safe_float(career_seasons, 1.0), 0.0) / 4.0, 1.0)
    m = min(math.sqrt(max(safe_float(career_minutes, 0.0), 0.0) / 8000.0), 1.0)
    c = min(max(safe_float(current_minutes, 0.0), 0.0) / 2000.0, 1.0)
    r = float(np.clip(safe_float(reliability, .5), 0, 1))
    return round(float(np.clip(.35 + .20*s + .20*m + .15*c + .10*r, .45, 1.0)), 4)


def history_summary(history: pd.DataFrame) -> pd.DataFrame:
    if "player_id" not in history.columns:
        raise ValueError("Historical player seasons are missing player_id")
    h = history.copy()
    h["_id"] = h["player_id"].map(player_id)
    h = h.loc[h["_id"].ne("")].copy()
    season_col = first_existing(h, ["season","season_id","year"])
    games_col = first_existing(h, ["games_played","gp"])
    mins_col = first_existing(h, ["total_minutes","minutes","min"])
    mpg_col = first_existing(h, ["minutes_per_game","mpg"])
    h["_games"] = num(h, games_col, 0.0).fillna(0.0) if games_col else 0.0
    if mins_col:
        h["_minutes"] = num(h, mins_col, 0.0).fillna(0.0)
    elif mpg_col:
        h["_minutes"] = num(h, mpg_col, 0.0).fillna(0.0) * h["_games"]
    else:
        h["_minutes"] = 0.0
    if season_col:
        return h.groupby("_id", as_index=False).agg(career_seasons=(season_col,"nunique"), career_games=("_games","sum"), career_minutes=("_minutes","sum"))
    return h.groupby("_id", as_index=False).agg(career_seasons=("_id","size"), career_games=("_games","sum"), career_minutes=("_minutes","sum"))


def add_rank_inputs(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    mapping = {
        "pie_rank_pct":"pie",
        "net_rating_rank_pct":"net_rating",
        "minutes_rank_pct":"minutes_per_game",
        "points_rank_pct":"points_per_game",
        "assists_rank_pct":"assists_per_game",
        "rebounds_rank_pct":"rebounds_per_game",
        "usage_rank_pct":"usage_pct",
        "expected_contribution_rank_pct":"projected_expected_contribution",
        "upside_contribution_rank_pct":"projected_upside_contribution",
        "future_peak_rank_pct":"future_peak_contribution",
        "future_long_rank_pct":"future_long_horizon_contribution",
        "future_growth_rank_pct":"future_growth_to_peak",
    }
    for target, source in mapping.items():
        out[target] = pct_rank(num(out, source))
    return out


def completeness_penalty(frame: pd.DataFrame) -> pd.Series:
    raw = num(frame, "current_value_raw")
    role_pct = num(frame, "role_burden_rank_pct", 50)
    skill = num(frame, "skill_mean_percentile_rating", 50)
    downside = num(frame, "downside_contribution_percentile_rating", 50)
    high = ((raw - 75) / 25).clip(0, 1)
    return high * (.14*(82-role_pct).clip(lower=0) + .09*(70-skill).clip(lower=0) + .06*(55-downside).clip(lower=0))


def build_v3(base: pd.DataFrame, history: pd.DataFrame) -> pd.DataFrame:
    out = base.copy()
    out["player_id"] = out["player_id"].map(player_id)
    hist = history_summary(history)
    out = out.merge(hist, left_on="player_id", right_on="_id", how="left", validate="one_to_one").drop(columns=["_id"])

    current_minutes = num(out,"games_played",0).fillna(0) * num(out,"minutes_per_game",0).fillna(0)
    out["career_seasons"] = num(out,"career_seasons",1).fillna(1).clip(lower=1)
    out["career_games"] = np.maximum(num(out,"career_games",0).fillna(0), num(out,"games_played",0).fillna(0))
    out["career_minutes"] = np.maximum(num(out,"career_minutes",0).fillna(0), current_minutes)

    out = add_rank_inputs(out)
    out["current_impact_rank_pct"] = weighted(out, CURRENT_IMPACT_WEIGHTS)
    out["role_burden_rank_pct"] = weighted(out, ROLE_WEIGHTS)
    out["current_value_raw"] = weighted(out, OVR_WEIGHTS)
    out["evidence_weight"] = [
        evidence(
            getattr(r, "career_seasons", 1.0),
            getattr(r, "career_minutes", 0.0),
            safe_float(getattr(r, "games_played", 0.0), 0.0)
            * safe_float(getattr(r, "minutes_per_game", 0.0), 0.0),
            getattr(r, "reliability_weight", 0.5),
        )
        for r in out.itertuples()
    ]
    out["demonstrated_prior_pct"] = .62*out["current_impact_rank_pct"] + .38*out["role_burden_rank_pct"]
    out["current_value_evidence_adjusted"] = out["evidence_weight"]*out["current_value_raw"] + (1-out["evidence_weight"])*out["demonstrated_prior_pct"]
    out["accomplishment_penalty"] = completeness_penalty(out)
    out["current_value_final_score"] = out["current_value_evidence_adjusted"] - out["accomplishment_penalty"]
    out["overall_league_percentile_v3"] = pct_rank(out["current_value_final_score"])
    out["overall_rating"] = out["overall_league_percentile_v3"].map(lambda x: map_rating(x, OVR_PCT, OVR_VAL))
    out["overall_grade"] = out["overall_rating"].map(grade)
    out["role_label"] = out["overall_rating"].map(role)

    out["future_outlook_score"] = weighted(out, FUT_WEIGHTS)
    out["future_outlook_percentile_v3"] = pct_rank(out["future_outlook_score"])
    out["future_outlook_rating"] = out["future_outlook_percentile_v3"].map(lambda x: map_rating(x, OVR_PCT, OVR_VAL))
    out["future_outlook_grade"] = out["future_outlook_rating"].map(grade)

    out["age_runway_score"] = out["age"].map(age_runway)
    out["potential_score_raw"] = weighted(out, POT_WEIGHTS)
    out["potential_league_percentile_v3"] = pct_rank(out["potential_score_raw"])
    modeled = out["potential_league_percentile_v3"].map(lambda x: map_rating(x, POT_PCT, POT_VAL))
    young_floor = out["overall_rating"] + out["age"].map(minimum_pot_gap)
    out["potential_rating"] = np.maximum.reduce([modeled.to_numpy(float), out["overall_rating"].to_numpy(float), young_floor.to_numpy(float)])
    out["potential_rating"] = pd.Series(out["potential_rating"], index=out.index).clip(upper=99.5).round(1)
    out["potential_grade"] = out["potential_rating"].map(grade)

    pot_gap = out["potential_rating"] - out["overall_rating"]
    fut_gap = out["future_outlook_rating"] - out["overall_rating"]
    out["development_direction"] = np.select([
        out["age"].le(28) & pot_gap.ge(1.5) & fut_gap.ge(-2.5),
        out["age"].ge(29) & fut_gap.le(-2.0),
    ], ["Rising","Declining"], default="Stable")
    out["development_arrow"] = out["development_direction"].map({"Rising":"↑","Stable":"→","Declining":"↓"})

    out = out.sort_values(["overall_rating","current_value_final_score","player_name"], ascending=[False,False,True]).reset_index(drop=True)
    out["league_overall_rank"] = np.arange(1, len(out)+1)
    out["team_overall_rank"] = out.groupby("team_abbreviation")["overall_rating"].rank(method="first", ascending=False).astype("Int64")
    out["rating_scope_note"] = "V3 separates current demonstrated value (OVR), career ceiling (POT), and projected future standing (FUT). Source projections, optimizer inputs, legality checks, and simulation values retain original precision."
    return out


def find_player(frame: pd.DataFrame, name: str) -> pd.Series | None:
    matches = frame.loc[frame["player_name"].astype(str).str.casefold() == name.casefold()]
    return None if matches.empty else matches.iloc[0]


def validation_rows(base: pd.DataFrame, v3: pd.DataFrame) -> list[dict[str, Any]]:
    def row(name: str, passed: bool, observed: Any, expected: Any, severity: str="required") -> dict[str, Any]:
        return {"check_name":name,"passed":bool(passed),"severity":severity,"observed":observed,"expected":expected}
    kon = find_player(v3, "Kon Knueppel")
    moussa = find_player(v3, "Moussa Diabaté")
    if moussa is None:
        moussa = find_player(v3, "Moussa Diabate")
    elite = int(v3.overall_rating.ge(93).sum())
    allstar = int(v3.overall_rating.ge(90).sum())
    highstarter = int(v3.overall_rating.ge(87).sum())
    return [
        row("player_count_preserved", len(base)==len(v3)==582, len(v3), 582),
        row("player_ids_unique", v3.player_id.is_unique and v3.player_id.ne("").all(), int(v3.player_id.nunique()), len(v3)),
        row("overall_rank_complete", set(v3.league_overall_rank)==set(range(1,len(v3)+1)), int(v3.league_overall_rank.nunique()), len(v3)),
        row("overall_scale_reasonable", v3.overall_rating.between(60,98.5).all(), {"min":float(v3.overall_rating.min()),"max":float(v3.overall_rating.max())}, "60.0-98.5"),
        row("potential_scale_reasonable", v3.potential_rating.between(60,99.5).all(), {"min":float(v3.potential_rating.min()),"max":float(v3.potential_rating.max())}, "60.0-99.5"),
        row("potential_never_below_overall", v3.potential_rating.ge(v3.overall_rating).all(), int(v3.potential_rating.lt(v3.overall_rating).sum()), 0),
        row("young_players_have_ceiling_room", (v3.loc[v3.age.le(24),"potential_rating"]-v3.loc[v3.age.le(24),"overall_rating"]).ge(1.5-1e-9).all(), round(float((v3.loc[v3.age.le(24),"potential_rating"]-v3.loc[v3.age.le(24),"overall_rating"]).min()),3), ">=1.5"),
        row("future_outlook_can_be_below_overall", int(v3.future_outlook_rating.lt(v3.overall_rating).sum())>0, int(v3.future_outlook_rating.lt(v3.overall_rating).sum()), ">0"),
        row("elite_population_not_inflated", 8<=elite<=30, elite, "8-30 at 93+"),
        row("all_star_population_not_inflated", 20<=allstar<=65, allstar, "20-65 at 90+"),
        row("high_starter_population_reasonable", 55<=highstarter<=125, highstarter, "55-125 at 87+"),
        row("median_overall_reasonable", 78<=float(v3.overall_rating.median())<=81, round(float(v3.overall_rating.median()),3), "78-81"),
        row("top_overall_below_perfect", float(v3.overall_rating.max())<=98.5, float(v3.overall_rating.max()), "<=98.5"),
        row("kon_not_top_11", kon is None or int(kon.league_overall_rank)>11, None if kon is None else {"rank":int(kon.league_overall_rank),"ovr":float(kon.overall_rating)}, "rank > 11", "player_sanity"),
        row("moussa_potential_above_overall", moussa is None or float(moussa.potential_rating)>float(moussa.overall_rating), None if moussa is None else {"ovr":float(moussa.overall_rating),"pot":float(moussa.potential_rating),"fut":float(moussa.future_outlook_rating)}, "POT > OVR", "player_sanity"),
        row("development_labels_complete", v3.development_direction.isin(["Rising","Stable","Declining"]).all(), v3.development_direction.value_counts().to_dict(), "complete"),
        row("finishing_remains_unreleased", not v3.finishing_rating_released.any(), bool(v3.finishing_rating_released.any()), False),
    ]


def distribution(frame: pd.DataFrame) -> pd.DataFrame:
    cols = ["overall_rating","potential_rating","future_outlook_rating","scoring_rating","shooting_rating","playmaking_rating","rebounding_rating","defense_rating","efficiency_rating","availability_rating","contract_value_rating","trade_value_rating"]
    rows=[]
    for col in cols:
        s=num(frame,col)
        rows.append({"rating":col,"count":int(s.notna().sum()),"minimum":round(float(s.min()),3),"p10":round(float(s.quantile(.1)),3),"p25":round(float(s.quantile(.25)),3),"median":round(float(s.median()),3),"mean":round(float(s.mean()),3),"p75":round(float(s.quantile(.75)),3),"p90":round(float(s.quantile(.9)),3),"p95":round(float(s.quantile(.95)),3),"maximum":round(float(s.max()),3)})
    return pd.DataFrame(rows)


def json_safe(value: Any) -> Any:
    if isinstance(value, dict): return {str(k):json_safe(v) for k,v in value.items()}
    if isinstance(value, (list,tuple)): return [json_safe(v) for v in value]
    if isinstance(value, np.integer): return int(value)
    if isinstance(value, np.floating): return None if np.isnan(value) else float(value)
    if value is None: return None
    if isinstance(value,float) and math.isnan(value): return None
    try:
        if pd.isna(value): return None
    except (TypeError,ValueError): pass
    return value


def app_payload(frame: pd.DataFrame, methodology: dict[str, Any]) -> dict[str, Any]:
    cols=[c for c in APP_COLUMNS if c in frame.columns]
    records=frame[cols].where(pd.notna(frame[cols]),None).to_dict("records")
    by_id={str(r["player_id"]):json_safe(r) for r in records}
    by_team={}
    for r in records: by_team.setdefault(str(r.get("team_abbreviation","")),[]).append(str(r["player_id"]))
    return {"release_name":RELEASE_NAME,"script_version":SCRIPT_VERSION,"league_year":"2026-27","rating_scale":{"overall_minimum":60.0,"overall_maximum":98.5,"potential_maximum":99.5,"decimals":1},"player_count":len(records),"methodology":methodology,"players_by_id":by_id,"player_ids_by_team":by_team}


def self_test() -> int:
    tests={
        "impact_weights":math.isclose(sum(CURRENT_IMPACT_WEIGHTS.values()),1),
        "role_weights":math.isclose(sum(ROLE_WEIGHTS.values()),1),
        "ovr_weights":math.isclose(sum(OVR_WEIGHTS.values()),1),
        "future_weights":math.isclose(sum(FUT_WEIGHTS.values()),1),
        "potential_weights":math.isclose(sum(POT_WEIGHTS.values()),1),
        "ovr_ceiling":map_rating(100,OVR_PCT,OVR_VAL)==98.5,
        "pot_ceiling":map_rating(100,POT_PCT,POT_VAL)==99.5,
        "percentile_order":pct_rank(pd.Series([10,20,30,40])).round(1).tolist()==[25,50,75,100],
        "evidence_history":evidence(5,10000,2500,.9)>evidence(1,2500,2500,.9),
        "age24_gap":minimum_pot_gap(24)==1.5,
        "grade":grade(94)=="A",
    }
    tests={k:bool(v) for k,v in tests.items()}
    print(json.dumps(tests,indent=2))
    return 0 if all(tests.values()) else 1


def main() -> int:
    args=parse_args()
    if args.self_test: return self_test()
    rating_path=locate(RATING_INPUTS,"Rating release")
    history_path=locate(HISTORY_INPUTS,"Unified historical player seasons")
    print("="*88); print("PLAYER RATING RELEASE V3"); print("="*88); print(f"Script version: {SCRIPT_VERSION}\n")
    print("[1/7] Loading current ratings and historical evidence")
    base=read_frame(rating_path); hist=read_frame(history_path)
    print(f"  Rating source: {rating_path.name} | {len(base):,} players")
    print(f"  History source: {history_path.name} | {len(hist):,} player-seasons")
    print("[2/7] Building career evidence and role burden")
    print("[3/7] Rebuilding accomplishment-aware OVR")
    print("[4/7] Separating POT ceiling from FUT outlook")
    v3=build_v3(base,hist)
    print("[5/7] Validating distribution and player sanity")
    validation=pd.DataFrame(validation_rows(base,v3))
    valid=bool(validation.passed.all())
    print("[6/7] Building diagnostics")
    dist=distribution(v3)
    audit_cols=[c for c in ["league_overall_rank","player_id","player_name","team_abbreviation","age","career_seasons","career_games","career_minutes","evidence_weight","points_per_game","rebounds_per_game","assists_per_game","minutes_per_game","true_shooting_pct","overall_rating","potential_rating","future_outlook_rating","contract_value_rating","trade_value_rating","current_value_raw","demonstrated_prior_pct","current_value_evidence_adjusted","accomplishment_penalty","current_value_final_score","overall_league_percentile_v3","future_outlook_percentile_v3","potential_score_raw","potential_league_percentile_v3","development_direction","archetype"] if c in v3.columns]
    audit=v3[audit_cols].copy()
    kon=find_player(v3,"Kon Knueppel")
    moussa=find_player(v3,"Moussa Diabaté")
    if moussa is None:
        moussa=find_player(v3,"Moussa Diabate")
    methodology={
        "release_name":RELEASE_NAME,"script_version":SCRIPT_VERSION,"created_utc":datetime.now(timezone.utc).isoformat(),"release_valid":valid,
        "rating_source":str(rating_path),"history_source":str(history_path),
        "interpretation":{"overall":"Current demonstrated NBA value with evidence moderation.","potential":"Plausible career ceiling; never below OVR.","future_outlook":"Projected future standing; may be below OVR."},
        "current_impact_weights":CURRENT_IMPACT_WEIGHTS,"role_weights":ROLE_WEIGHTS,"overall_weights":OVR_WEIGHTS,"future_weights":FUT_WEIGHTS,"potential_weights":POT_WEIGHTS,
        "validation_passed":int(validation.passed.sum()),"validation_total":len(validation),
    }
    print("[7/7] Writing V3 release")
    DATA_DIR.mkdir(parents=True,exist_ok=True); OUTPUT_DIR.mkdir(parents=True,exist_ok=True); APP_DIR.mkdir(parents=True,exist_ok=True)
    v3.to_parquet(OUT_PARQUET,index=False); v3.to_csv(OUT_CSV,index=False)
    validation.to_csv(OUT_VALIDATION,index=False); dist.to_csv(OUT_DISTRIBUTION,index=False); audit.to_csv(OUT_AUDIT,index=False); audit.head(100).to_csv(OUT_TOP100,index=False)
    OUT_METHOD.write_text(json.dumps(json_safe(methodology),indent=2,ensure_ascii=False),encoding="utf-8")
    payload=json.dumps(json_safe(app_payload(v3,methodology)),indent=2,ensure_ascii=False)
    OUT_JSON.write_text(payload,encoding="utf-8"); ACTIVE_ALIAS.write_text(payload,encoding="utf-8")
    print("Complete")
    print(f"Validation: {int(validation.passed.sum())}/{len(validation)}")
    print(f"Release valid: {valid}")
    print(f"Players rated: {len(v3):,}")
    print(f"Overall distribution: {v3.overall_rating.min():.1f}-{v3.overall_rating.max():.1f} | median {v3.overall_rating.median():.1f} | std {v3.overall_rating.std():.1f}")
    print(f"OVR tiers: 93+ {v3.overall_rating.ge(93).sum()} | 90+ {v3.overall_rating.ge(90).sum()} | 87+ {v3.overall_rating.ge(87).sum()}")
    print("Development: " + " | ".join(f"{k} {v}" for k,v in v3.development_direction.value_counts().to_dict().items()))
    for name,r in [("Kon Knueppel",kon),("Moussa Diabaté",moussa)]:
        if r is not None: print(f"{name}: rank #{int(r.league_overall_rank)} | OVR {float(r.overall_rating):.1f} | POT {float(r.potential_rating):.1f} | FUT {float(r.future_outlook_rating):.1f} | evidence {float(r.evidence_weight):.3f}")
    print("\nTOP 20 V3 OVERALL RATINGS")
    print(v3[["league_overall_rank","player_name","team_abbreviation","overall_rating","potential_rating","future_outlook_rating","career_seasons","evidence_weight","archetype"]].head(20).to_string(index=False))
    if not valid:
        print("\nFAILED VALIDATION CHECKS")
        print(validation.loc[~validation.passed].to_string(index=False))
    return 0 if valid else 1

if __name__ == "__main__":
    raise SystemExit(main())