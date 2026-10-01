from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import re
import shutil
import tempfile
from dataclasses import asdict, dataclass
from functools import lru_cache
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from franchise_free_agency_contract_salary_legality_v1_3 import resolve_years_of_service

FREE_AGENCY_RIGHTS_POPULATION_VERSION = "franchise-free-agency-verified-bird-rights-population-v1-2026-08-14"
FREE_AGENCY_RIGHTS_POPULATION_SCHEMA_VERSION = "free-agency-rights-population-schema-v1"
FREE_AGENCY_RIGHTS_POPULATION_SCOPE = "verified_history_only_no_inference"
FREE_AGENCY_RIGHTS_OVERLAY_ENV = "FA_RIGHTS_POPULATION_PATH"
FREE_AGENCY_RIGHTS_OVERLAY_FILENAME = "free_agency_rights_population_v1.json"
FREE_AGENCY_RIGHTS_REGISTRY_ATTRIBUTE = "free_agency_rights_registry_v1"
FREE_AGENCY_RIGHTS_EVIDENCE_VERSION = "free-agency-rights-evidence-v1"

NBA_TEAMS = {
    "ATL","BOS","BKN","CHA","CHI","CLE","DAL","DEN","DET","GSW","HOU","IND","LAC","LAL",
    "MEM","MIA","MIL","MIN","NOP","NYK","OKC","ORL","PHI","PHX","POR","SAC","SAS","TOR","UTA","WAS"
}

PLAYER_ID_ALIASES = {
    "player_id","nba_player_id","person_id","personid","playerid","id"
}
PLAYER_NAME_ALIASES = {
    "player_name","player","player_display_name","player_name_full","display_name","name"
}
SEASON_ALIASES = {
    "season","season_label","season_year","season_id","year"
}
TEAM_ALIASES = {
    "team_abbreviation","team_abbr","team","team_code","team_tricode","current_team"
}
SALARY_ALIASES = {
    "salary","annual_salary","base_salary","player_salary","salary_amount","trade_salary"
}

SOURCE_NAME_TOKENS = (
    "history","season","roster","player_stats","player-stat","player_team","player-team","career"
)


@dataclass(frozen=True)
class RightsHistorySource:
    path: str
    source_type: str
    player_id_column: str
    player_name_column: str
    season_column: str
    team_column: str
    salary_column: str
    row_count: int
    qualifying_row_count: int
    source_fingerprint: str


@dataclass(frozen=True)
class RightsPopulationCandidate:
    player_id: str
    player_name: str
    season_label: str
    status: str
    rights_classification: str
    prior_team: str
    continuous_qualifying_seasons: int | None
    continuity_verified: bool
    prior_regular_salary: float | None
    years_of_service: int | None
    service_source: str
    evidence_source: str
    evidence_detail: str
    observed_seasons: tuple[str, ...]
    observed_teams: tuple[str, ...]
    source_files: tuple[str, ...]
    evidence_fingerprint: str


@dataclass(frozen=True)
class RightsPopulationPreview:
    version: str
    schema_version: str
    season_label: str
    free_agent_count: int
    proven_count: int
    bird_count: int
    early_bird_count: int
    non_bird_count: int
    unresolved_count: int
    source_count: int
    candidates: tuple[RightsPopulationCandidate, ...]
    sources: tuple[RightsHistorySource, ...]
    preview_fingerprint: str


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _pid(value: Any) -> str:
    text = _clean(value)
    if text.endswith(".0") and text[:-2].isdigit():
        return text[:-2]
    return text


def _team(value: Any) -> str:
    return _clean(value).upper()


def _finite_positive(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number <= 0:
        return None
    return number


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_path(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def default_overlay_path() -> Path:
    override = _clean(os.environ.get(FREE_AGENCY_RIGHTS_OVERLAY_ENV))
    if override:
        return Path(override).expanduser().resolve()
    return project_root() / "outputs" / "runtime" / FREE_AGENCY_RIGHTS_OVERLAY_FILENAME


def _season_start(value: Any) -> int | None:
    text = _clean(value)
    if not text:
        return None
    # NBA stats often uses SEASON_ID like 22025 for 2025-26.
    if re.fullmatch(r"2\d{4}", text):
        return int(text[-4:])
    match = re.search(r"(19|20)\d{2}", text)
    if match:
        return int(match.group(0))
    try:
        number = int(float(text))
    except (TypeError, ValueError):
        return None
    if 1900 <= number <= 2100:
        return number
    return None


def _season_label_from_start(start: int) -> str:
    return f"{start}-{str((start + 1) % 100).zfill(2)}"


def _target_previous_season_start(state: Any) -> int | None:
    settings = getattr(state, "settings", None)
    current = _season_start(getattr(settings, "season_label", ""))
    return (current - 1) if current is not None else None


def _column_map(columns: Sequence[Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw in columns:
        text = _clean(raw)
        if text:
            result[text.strip().lower()] = text
    return result


def _first_alias(mapping: Mapping[str, str], aliases: set[str]) -> str:
    for alias in aliases:
        if alias in mapping:
            return mapping[alias]
    return ""


def _candidate_source_paths(root: Path) -> list[Path]:
    bases = [root / "data", root / "outputs", root / "evidence"]
    result: list[Path] = []
    for base in bases:
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            lower_parts = {part.lower() for part in path.parts}
            if "backups" in lower_parts or "audits" in lower_parts or "runtime" in lower_parts:
                continue
            if path.suffix.lower() not in {".csv", ".parquet"}:
                continue
            name = path.name.lower()
            if not any(token in name for token in SOURCE_NAME_TOKENS):
                continue
            try:
                if path.stat().st_size > 125 * 1024 * 1024:
                    continue
            except OSError:
                continue
            result.append(path)
    return sorted(set(result), key=lambda p: str(p).lower())


def _read_tabular(path: Path) -> tuple[list[str], list[dict[str, Any]]]:
    if path.suffix.lower() == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            columns = list(reader.fieldnames or [])
            rows = [dict(row) for row in reader]
        return columns, rows

    try:
        import pandas as pd  # lazy because the core resolver does not need pandas
    except Exception as exc:
        raise RuntimeError(f"Parquet history source requires pandas/pyarrow: {exc}") from exc
    frame = pd.read_parquet(path)
    return [str(c) for c in frame.columns], frame.to_dict(orient="records")


def discover_player_team_history_sources(
    root: Path | None = None,
    *,
    explicit_paths: Iterable[str | Path] = (),
) -> tuple[RightsHistorySource, ...]:
    root = (root or project_root()).resolve()
    paths = [Path(value).expanduser().resolve() for value in explicit_paths]
    paths.extend(_candidate_source_paths(root))
    seen: set[str] = set()
    sources: list[RightsHistorySource] = []

    for path in paths:
        key = str(path).lower()
        if key in seen or not path.exists() or not path.is_file():
            continue
        seen.add(key)
        try:
            columns, rows = _read_tabular(path)
        except Exception:
            continue
        mapping = _column_map(columns)
        pid_col = _first_alias(mapping, PLAYER_ID_ALIASES)
        season_col = _first_alias(mapping, SEASON_ALIASES)
        team_col = _first_alias(mapping, TEAM_ALIASES)
        if not pid_col or not season_col or not team_col:
            continue
        name_col = _first_alias(mapping, PLAYER_NAME_ALIASES)
        salary_col = _first_alias(mapping, SALARY_ALIASES)
        qualifying = 0
        for row in rows:
            if _pid(row.get(pid_col)) and _season_start(row.get(season_col)) is not None and _team(row.get(team_col)) in NBA_TEAMS:
                qualifying += 1
        if qualifying <= 0:
            continue
        try:
            fingerprint = _sha256_path(path)
        except OSError:
            fingerprint = ""
        sources.append(RightsHistorySource(
            path=str(path),
            source_type=path.suffix.lower().lstrip("."),
            player_id_column=pid_col,
            player_name_column=name_col,
            season_column=season_col,
            team_column=team_col,
            salary_column=salary_col,
            row_count=len(rows),
            qualifying_row_count=qualifying,
            source_fingerprint=fingerprint,
        ))
    return tuple(sources)


def _history_rows_from_sources(sources: Sequence[RightsHistorySource]) -> dict[str, list[dict[str, Any]]]:
    by_player: dict[str, list[dict[str, Any]]] = {}
    for source in sources:
        path = Path(source.path)
        try:
            _, rows = _read_tabular(path)
        except Exception:
            continue
        for row in rows:
            pid = _pid(row.get(source.player_id_column))
            season_start = _season_start(row.get(source.season_column))
            team = _team(row.get(source.team_column))
            if not pid or season_start is None or team not in NBA_TEAMS:
                continue
            by_player.setdefault(pid, []).append({
                "player_id": pid,
                "player_name": _clean(row.get(source.player_name_column)) if source.player_name_column else "",
                "season_start": season_start,
                "season_label": _season_label_from_start(season_start),
                "team": team,
                "salary": _finite_positive(row.get(source.salary_column)) if source.salary_column else None,
                "source_file": source.path,
                "source_fingerprint": source.source_fingerprint,
            })
    return by_player


def _archive_player_team_rows(state: Any) -> dict[str, list[dict[str, Any]]]:
    by_player: dict[str, list[dict[str, Any]]] = {}
    for archive in list(getattr(state, "season_history", []) or []):
        season_label = _clean(getattr(archive, "season_label", ""))
        season_start = _season_start(season_label)
        if season_start is None:
            continue
        schedule = getattr(archive, "schedule", {})
        completed = getattr(archive, "completed_games", {})
        if not isinstance(completed, Mapping):
            continue
        per_player: dict[str, list[tuple[int, str]]] = {}
        for game_id, game in completed.items():
            scheduled = schedule.get(game_id) if isinstance(schedule, Mapping) else None
            day = int(getattr(scheduled, "day_index", -1) or -1)
            for line in tuple(getattr(game, "player_box_scores", ()) or ()):
                pid = _pid(getattr(line, "player_id", ""))
                team = _team(getattr(line, "team_abbreviation", ""))
                if pid and team in NBA_TEAMS:
                    per_player.setdefault(pid, []).append((day, team))
        for pid, appearances in per_player.items():
            appearances.sort(key=lambda item: (item[0], item[1]))
            teams = {team for _, team in appearances}
            # Multiple teams in one season are not auto-resolved without transaction provenance.
            if len(teams) != 1:
                by_player.setdefault(pid, []).append({
                    "player_id": pid,
                    "player_name": "",
                    "season_start": season_start,
                    "season_label": _season_label_from_start(season_start),
                    "team": "",
                    "salary": None,
                    "source_file": "simulation_state.season_history",
                    "source_fingerprint": "",
                    "ambiguous_teams": tuple(sorted(teams)),
                })
                continue
            by_player.setdefault(pid, []).append({
                "player_id": pid,
                "player_name": "",
                "season_start": season_start,
                "season_label": _season_label_from_start(season_start),
                "team": next(iter(teams)),
                "salary": None,
                "source_file": "simulation_state.season_history",
                "source_fingerprint": "",
            })
    return by_player


def _merge_history_rows(*parts: Mapping[str, list[dict[str, Any]]]) -> dict[str, list[dict[str, Any]]]:
    merged: dict[str, list[dict[str, Any]]] = {}
    for part in parts:
        for pid, rows in part.items():
            merged.setdefault(pid, []).extend(rows)
    return merged


def _season_team_consensus(rows: Sequence[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    grouped: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        season_start = row.get("season_start")
        if isinstance(season_start, int):
            grouped.setdefault(season_start, []).append(row)
    result: dict[int, dict[str, Any]] = {}
    for season_start, items in grouped.items():
        teams = {_team(item.get("team")) for item in items if _team(item.get("team")) in NBA_TEAMS}
        ambiguous = any(item.get("ambiguous_teams") for item in items)
        if ambiguous or len(teams) != 1:
            result[season_start] = {
                "team": "",
                "salary": None,
                "sources": tuple(sorted({_clean(item.get("source_file")) for item in items if _clean(item.get("source_file"))})),
                "ambiguous": True,
            }
            continue
        salary_values = [
            _finite_positive(item.get("salary"))
            for item in items
            if _finite_positive(item.get("salary")) is not None
        ]
        result[season_start] = {
            "team": next(iter(teams)),
            "salary": salary_values[-1] if salary_values else None,
            "sources": tuple(sorted({_clean(item.get("source_file")) for item in items if _clean(item.get("source_file"))})),
            "ambiguous": False,
        }
    return result


def _existing_registry(state: Any) -> dict[str, dict[str, Any]]:
    raw = getattr(state, FREE_AGENCY_RIGHTS_REGISTRY_ATTRIBUTE, None)
    if not isinstance(raw, Mapping):
        return {}
    result: dict[str, dict[str, Any]] = {}
    for raw_id, raw_row in raw.items():
        pid = _pid(raw_id)
        if pid and isinstance(raw_row, Mapping):
            result[pid] = dict(raw_row)
    return result


def _classification_from_exact_history(
    *,
    season_rows: Mapping[int, dict[str, Any]],
    target_previous_season: int | None,
    years_of_service: int | None,
) -> tuple[str, str, int | None, tuple[str, ...], tuple[str, ...]]:
    if target_previous_season is None:
        return "unknown", "current season label cannot be resolved", None, (), ()
    latest = season_rows.get(target_previous_season)
    if latest is None or latest.get("ambiguous") or _team(latest.get("team")) not in NBA_TEAMS:
        return "unknown", "no unambiguous team evidence for the immediately prior season", None, (), ()
    prior_team = _team(latest.get("team"))
    observed_labels: list[str] = []
    source_files: set[str] = set()
    streak = 0
    for season in range(target_previous_season, target_previous_season - 6, -1):
        row = season_rows.get(season)
        if row is None or row.get("ambiguous") or _team(row.get("team")) != prior_team:
            break
        streak += 1
        observed_labels.append(_season_label_from_start(season))
        source_files.update(row.get("sources", ()) or ())

    # Bird is exact once three consecutive qualifying same-team seasons are explicitly observed.
    if streak >= 3:
        return "bird", "three or more consecutive prior seasons are explicitly observed with the same rights-holder team", streak, tuple(observed_labels), tuple(sorted(source_files))

    # Early Bird is exact only when the player's total service cannot hide an unseen third qualifying season.
    if streak >= 2 and years_of_service is not None and years_of_service <= 2:
        return "early_bird", "two consecutive prior seasons are explicitly observed and total NBA service is two seasons", streak, tuple(observed_labels), tuple(sorted(source_files))

    # We intentionally do not auto-classify one-season Non-Bird from team-history alone because waiver/free-agent path evidence is absent.
    return "unknown", (
        "history proves the immediately prior team but not the exact Bird clock; V1 will not downgrade a possibly stronger right or infer a waiver/free-agent path"
    ), streak if streak else None, tuple(observed_labels), tuple(sorted(source_files))


def build_rights_population_preview(
    state: Any,
    *,
    root: Path | None = None,
    explicit_history_paths: Iterable[str | Path] = (),
) -> RightsPopulationPreview:
    root = (root or project_root()).resolve()
    season_label = _clean(getattr(getattr(state, "settings", None), "season_label", ""))
    free_ids = tuple(sorted({_pid(value) for value in getattr(state, "free_agent_player_ids", ()) or () if _pid(value)}))
    players = getattr(state, "players", {})
    existing = _existing_registry(state)
    sources = discover_player_team_history_sources(root, explicit_paths=explicit_history_paths)
    history = _merge_history_rows(_history_rows_from_sources(sources), _archive_player_team_rows(state))
    target_previous_season = _target_previous_season_start(state)

    candidates: list[RightsPopulationCandidate] = []
    for pid in free_ids:
        player = players.get(pid) if isinstance(players, Mapping) else None
        player_name = _clean(getattr(player, "player_name", pid)) or pid
        service, service_source = resolve_years_of_service(player) if player is not None else (None, "missing_player")
        contract = getattr(player, "contract", None) if player is not None else None
        state_salary = _finite_positive(getattr(contract, "salary", None))

        row = existing.get(pid)
        if row and bool(row.get("continuity_verified", False)) and _team(row.get("prior_team")) in NBA_TEAMS:
            raw_seasons = row.get("continuous_prior_seasons")
            try:
                seasons = int(raw_seasons)
            except (TypeError, ValueError):
                seasons = -1
            classification = "bird" if seasons >= 3 else "early_bird" if seasons >= 2 else "non_bird" if seasons >= 0 else "unknown"
            status = "proven_existing_registry" if classification != "unknown" else "unresolved"
            source = _clean(row.get("source")) or "simulation_state.free_agency_rights_registry_v1"
            detail = "Existing explicit verified rights registry row remains authoritative."
            prior_team = _team(row.get("prior_team"))
            prior_salary = _finite_positive(row.get("prior_regular_salary")) or state_salary
            obs = ()
            src_files = (source,)
            continuity = classification != "unknown"
            clock = seasons if seasons >= 0 else None
        else:
            consensus = _season_team_consensus(history.get(pid, []))
            classification, detail, clock, obs, src_files = _classification_from_exact_history(
                season_rows=consensus,
                target_previous_season=target_previous_season,
                years_of_service=service,
            )
            latest = consensus.get(target_previous_season) if target_previous_season is not None else None
            prior_team = _team(latest.get("team")) if isinstance(latest, Mapping) else ""
            prior_salary = (_finite_positive(latest.get("salary")) if isinstance(latest, Mapping) else None) or state_salary
            source = "verified_player_team_history" if classification != "unknown" else "insufficient_verified_history"
            status = "proven" if classification != "unknown" else "unresolved"
            continuity = classification != "unknown"

        payload = {
            "player_id": pid,
            "player_name": player_name,
            "season_label": season_label,
            "status": status,
            "rights_classification": classification,
            "prior_team": prior_team,
            "continuous_qualifying_seasons": clock,
            "continuity_verified": continuity,
            "prior_regular_salary": prior_salary,
            "years_of_service": service,
            "service_source": service_source,
            "evidence_source": source,
            "evidence_detail": detail,
            "observed_seasons": list(obs),
            "observed_teams": [prior_team] if prior_team else [],
            "source_files": list(src_files),
        }
        evidence_fp = _sha256_bytes(json.dumps(payload, sort_keys=True, default=str, separators=(",", ":")).encode("utf-8"))
        candidates.append(RightsPopulationCandidate(
            player_id=pid,
            player_name=player_name,
            season_label=season_label,
            status=status,
            rights_classification=classification,
            prior_team=prior_team,
            continuous_qualifying_seasons=clock,
            continuity_verified=continuity,
            prior_regular_salary=prior_salary,
            years_of_service=service,
            service_source=service_source,
            evidence_source=source,
            evidence_detail=detail,
            observed_seasons=tuple(obs),
            observed_teams=(prior_team,) if prior_team else (),
            source_files=tuple(src_files),
            evidence_fingerprint=evidence_fp,
        ))

    candidates.sort(key=lambda row: (row.status != "proven", row.status != "proven_existing_registry", row.player_name.lower(), row.player_id))
    proven = [row for row in candidates if row.status in {"proven", "proven_existing_registry"}]
    preview_payload = {
        "version": FREE_AGENCY_RIGHTS_POPULATION_VERSION,
        "schema_version": FREE_AGENCY_RIGHTS_POPULATION_SCHEMA_VERSION,
        "season_label": season_label,
        "candidates": [asdict(row) for row in candidates],
        "sources": [asdict(row) for row in sources],
    }
    preview_fp = _sha256_bytes(json.dumps(preview_payload, sort_keys=True, default=str, separators=(",", ":")).encode("utf-8"))
    return RightsPopulationPreview(
        version=FREE_AGENCY_RIGHTS_POPULATION_VERSION,
        schema_version=FREE_AGENCY_RIGHTS_POPULATION_SCHEMA_VERSION,
        season_label=season_label,
        free_agent_count=len(free_ids),
        proven_count=len(proven),
        bird_count=sum(row.rights_classification == "bird" for row in proven),
        early_bird_count=sum(row.rights_classification == "early_bird" for row in proven),
        non_bird_count=sum(row.rights_classification == "non_bird" for row in proven),
        unresolved_count=len(candidates) - len(proven),
        source_count=len(sources),
        candidates=tuple(candidates),
        sources=tuple(sources),
        preview_fingerprint=preview_fp,
    )


def overlay_registry_from_preview(preview: RightsPopulationPreview) -> dict[str, dict[str, Any]]:
    registry: dict[str, dict[str, Any]] = {}
    for row in preview.candidates:
        if row.status not in {"proven", "proven_existing_registry"}:
            continue
        if row.rights_classification not in {"bird", "early_bird", "non_bird"}:
            continue
        seasons = row.continuous_qualifying_seasons
        if seasons is None or not row.continuity_verified or not row.prior_team:
            continue
        registry[row.player_id] = {
            "version": FREE_AGENCY_RIGHTS_EVIDENCE_VERSION,
            "player_id": row.player_id,
            "prior_team": row.prior_team,
            "continuous_prior_seasons": int(seasons),
            "continuity_verified": True,
            "prior_regular_salary": row.prior_regular_salary,
            "prior_average_player_salary": None,
            "restricted_free_agent": False,
            "qualifying_offer_amount": None,
            "source": f"{FREE_AGENCY_RIGHTS_POPULATION_VERSION}:{row.evidence_source}",
            "population_evidence_fingerprint": row.evidence_fingerprint,
            "population_observed_seasons": list(row.observed_seasons),
            "population_source_files": list(row.source_files),
        }
    return registry


def build_overlay_payload(preview: RightsPopulationPreview, *, checkpoint_sha256: str = "") -> dict[str, Any]:
    registry = overlay_registry_from_preview(preview)
    return {
        "version": FREE_AGENCY_RIGHTS_POPULATION_VERSION,
        "schema_version": FREE_AGENCY_RIGHTS_POPULATION_SCHEMA_VERSION,
        "scope": FREE_AGENCY_RIGHTS_POPULATION_SCOPE,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "season_label": preview.season_label,
        "checkpoint_sha256_at_generation": checkpoint_sha256,
        "preview_fingerprint": preview.preview_fingerprint,
        "registry": registry,
        "summary": {
            "free_agent_count": preview.free_agent_count,
            "proven_count": preview.proven_count,
            "bird_count": preview.bird_count,
            "early_bird_count": preview.early_bird_count,
            "non_bird_count": preview.non_bird_count,
            "unresolved_count": preview.unresolved_count,
            "source_count": preview.source_count,
        },
    }


def write_overlay_atomic(payload: Mapping[str, Any], *, path: Path | None = None) -> tuple[Path, Path | None]:
    path = (path or default_overlay_path()).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    recovery: Path | None = None
    if path.exists():
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        recovery_dir = path.parent / "free_agency_rights_population_recovery"
        recovery_dir.mkdir(parents=True, exist_ok=True)
        recovery = recovery_dir / f"pre_rights_population_{stamp}_{path.name}"
        shutil.copy2(path, recovery)
    encoded = json.dumps(dict(payload), indent=2, sort_keys=True, default=str).encode("utf-8")
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    os.close(fd)
    tmp_path = Path(tmp_name)
    try:
        tmp_path.write_bytes(encoded)
        os.replace(tmp_path, path)
    finally:
        tmp_path.unlink(missing_ok=True)
    return path, recovery


@lru_cache(maxsize=8)
def _cached_overlay_payload(
    path_text: str,
    mtime_ns: int,
    size_bytes: int,
) -> dict[str, Any]:
    # File metadata is part of the key so atomic overlay replacement
    # invalidates the cached read without returning mutable data to callers.
    del mtime_ns, size_bytes
    path = Path(path_text)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def load_overlay_for_state(state: Any, *, path: Path | None = None) -> dict[str, dict[str, Any]]:
    path = (path or default_overlay_path()).resolve()
    if not path.exists():
        return {}
    try:
        stat = path.stat()
        payload = _cached_overlay_payload(
            str(path),
            int(stat.st_mtime_ns),
            int(stat.st_size),
        )
    except Exception:
        return {}
    if _clean(payload.get("version")) != FREE_AGENCY_RIGHTS_POPULATION_VERSION:
        return {}
    state_season = _clean(getattr(getattr(state, "settings", None), "season_label", ""))
    if _clean(payload.get("season_label")) != state_season:
        return {}
    raw_registry = payload.get("registry")
    if not isinstance(raw_registry, Mapping):
        return {}
    free_ids = {_pid(value) for value in getattr(state, "free_agent_player_ids", ()) or ()}
    players = getattr(state, "players", {})
    result: dict[str, dict[str, Any]] = {}
    for raw_id, raw_row in raw_registry.items():
        pid = _pid(raw_id)
        if not pid or pid not in free_ids or not isinstance(raw_row, Mapping):
            continue
        if isinstance(players, Mapping) and pid not in players:
            continue
        if not bool(raw_row.get("continuity_verified", False)):
            continue
        prior_team = _team(raw_row.get("prior_team"))
        try:
            seasons = int(raw_row.get("continuous_prior_seasons"))
        except (TypeError, ValueError):
            continue
        if prior_team not in NBA_TEAMS or seasons < 0:
            continue
        result[pid] = dict(raw_row)
    return result


def overlay_status_for_state(state: Any, *, path: Path | None = None) -> dict[str, Any]:
    path = (path or default_overlay_path()).resolve()
    exists = path.exists()
    active = load_overlay_for_state(state, path=path)
    return {
        "version": FREE_AGENCY_RIGHTS_POPULATION_VERSION,
        "path": str(path),
        "exists": exists,
        "active_rows": len(active),
        "season_label": _clean(getattr(getattr(state, "settings", None), "season_label", "")),
    }


def preview_rows(preview: RightsPopulationPreview) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in preview.candidates:
        payload = asdict(row)
        payload["observed_seasons"] = "|".join(row.observed_seasons)
        payload["observed_teams"] = "|".join(row.observed_teams)
        payload["source_files"] = "|".join(row.source_files)
        rows.append(payload)
    return rows


def source_rows(preview: RightsPopulationPreview) -> list[dict[str, Any]]:
    return [asdict(row) for row in preview.sources]


def strict_preview_checks(preview: RightsPopulationPreview) -> list[dict[str, str]]:
    checks: list[dict[str, str]] = []
    def add(check_id: str, passed: bool, detail: str) -> None:
        checks.append({"check_id": check_id, "status": "PASS" if passed else "FAIL", "severity": "strict", "detail": detail})
    proven = [row for row in preview.candidates if row.status in {"proven", "proven_existing_registry"}]
    add("population_version_is_current", preview.version == FREE_AGENCY_RIGHTS_POPULATION_VERSION, "Population version must match V1.")
    add("population_schema_is_current", preview.schema_version == FREE_AGENCY_RIGHTS_POPULATION_SCHEMA_VERSION, "Population schema must match V1.")
    add("candidate_count_matches_free_agent_count", len(preview.candidates) == preview.free_agent_count, "Every current free agent must receive one population result.")
    add("proven_rows_have_verified_continuity", all(row.continuity_verified for row in proven), "No rights row may be populated without explicit continuity proof.")
    add("proven_rows_have_prior_team", all(row.prior_team in NBA_TEAMS for row in proven), "Every populated rights row must identify a valid prior team.")
    add("bird_rows_have_three_observed_qualifying_seasons", all((row.continuous_qualifying_seasons or 0) >= 3 for row in proven if row.rights_classification == "bird"), "Bird rows require three or more explicitly proven qualifying seasons.")
    add("early_bird_rows_have_exact_two_season_service_ceiling", all((row.continuous_qualifying_seasons or 0) >= 2 and (row.years_of_service is not None and row.years_of_service <= 2) for row in proven if row.rights_classification == "early_bird" and row.status == "proven"), "History-derived Early Bird rows require two observed seasons and no hidden third service season.")
    add("history_only_population_never_infers_non_bird", all(not (row.status == "proven" and row.rights_classification == "non_bird") for row in preview.candidates), "V1 never infers one-season Non-Bird from team-history alone.")
    add("unresolved_rows_are_not_marked_verified", all(not row.continuity_verified for row in preview.candidates if row.status == "unresolved"), "Unresolved evidence may never be consumed by the rights engine.")
    return checks
