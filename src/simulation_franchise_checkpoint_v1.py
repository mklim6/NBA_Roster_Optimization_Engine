from __future__ import annotations

import argparse
import copy
import gzip
import hashlib
import importlib
import json
import os
import pickle
import shutil
import sys
import tempfile
import time
from dataclasses import dataclass, fields, is_dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping

import cloudpickle


ROOT = Path(__file__).resolve().parents[1]
OUTPUTS = ROOT / "outputs"
RUNTIME_DIR = OUTPUTS / "runtime"

CHECKPOINT_VERSION = (
    "simulation-franchise-checkpoint-v1-2026-08-08"
)
CHECKPOINT_IMPLEMENTATION_VERSION = (
    "simulation-franchise-checkpoint-v1.2-2026-08-08"
)
DEFAULT_CHECKPOINT_PATH = (
    RUNTIME_DIR
    / "franchise_mode_checkpoint_v1.pkl.gz"
)
DEFAULT_BACKUP_PATH = (
    RUNTIME_DIR
    / "franchise_mode_checkpoint_v1.backup.pkl.gz"
)
SELF_TEST_REPORT = (
    OUTPUTS
    / "simulation_franchise_checkpoint_v1_self_test.json"
)

IO_RETRY_DELAYS = (
    0.05,
    0.10,
    0.20,
    0.40,
    0.80,
)


class FranchiseCheckpointError(RuntimeError):
    """Raised when a durable franchise checkpoint cannot be used."""

    def __init__(
        self,
        message: str,
        *,
        stage: str = "",
        cause: BaseException | None = None,
    ) -> None:
        self.stage = str(stage)
        self.cause_type = (
            type(cause).__name__
            if cause is not None
            else ""
        )
        self.cause_message = (
            str(cause)
            if cause is not None
            else ""
        )
        detail = str(message)

        if self.stage:
            detail += f" [stage={self.stage}]"

        if self.cause_type:
            detail += f" {self.cause_type}"

            if self.cause_message:
                detail += f": {self.cause_message}"

        super().__init__(detail)


@dataclass(frozen=True)
class FranchiseCheckpoint:
    version: str
    saved_at_utc: str
    simulation_state: Any
    trade_state: Any
    preferences: dict[str, Any]
    reason: str


def utc_timestamp() -> str:
    return datetime.now(
        timezone.utc
    ).isoformat()


def checkpoint_backup_path(
    path: Path,
) -> Path:
    if path == DEFAULT_CHECKPOINT_PATH:
        return DEFAULT_BACKUP_PATH

    return path.with_name(
        path.name + ".backup"
    )


def resolve_current_type(
    source_type: type[Any],
) -> type[Any] | None:
    module_name = getattr(
        source_type,
        "__module__",
        "",
    )
    qualname = getattr(
        source_type,
        "__qualname__",
        "",
    )

    if (
        not module_name
        or not qualname
        or "<locals>" in qualname
        or module_name == "builtins"
    ):
        return None

    try:
        current: Any = importlib.import_module(
            module_name
        )

        for part in qualname.split("."):
            current = getattr(
                current,
                part,
            )
    except (
        AttributeError,
        ImportError,
        ModuleNotFoundError,
    ):
        return None

    return (
        current
        if isinstance(current, type)
        else None
    )


def set_runtime_attribute(
    target: Any,
    name: str,
    value: Any,
) -> None:
    try:
        object.__setattr__(
            target,
            name,
            value,
        )
    except Exception:
        setattr(
            target,
            name,
            value,
        )


def rebind_runtime_graph(
    value: Any,
    *,
    memo: dict[int, Any] | None = None,
) -> Any:
    """Rebind stale hot-reloaded classes to their current module classes.

    Streamlit can keep objects created by an earlier module generation in
    session state after a hot reload. Standard pickle rejects those objects
    because their class identity no longer matches the class currently
    exported by the module. This routine rebuilds dataclasses, enums, and
    ordinary state objects against the current imported class definitions
    before the checkpoint is serialized.
    """

    if memo is None:
        memo = {}

    value_id = id(value)

    if value_id in memo:
        return memo[value_id]

    # String-backed enums must be rebound before the primitive string check.
    if isinstance(value, Enum):
        current_type = resolve_current_type(
            type(value)
        )

        if (
            current_type is not None
            and issubclass(
                current_type,
                Enum,
            )
        ):
            rebound = current_type(
                value.value
            )
            memo[value_id] = rebound
            return rebound

        return value

    if value is None or isinstance(
        value,
        (
            bool,
            int,
            float,
            complex,
            str,
            bytes,
            bytearray,
            Path,
            datetime,
        ),
    ):
        return value

    if isinstance(value, dict):
        rebound_dict: dict[Any, Any] = {}
        memo[value_id] = rebound_dict

        for key, item in value.items():
            rebound_dict[
                rebind_runtime_graph(
                    key,
                    memo=memo,
                )
            ] = rebind_runtime_graph(
                item,
                memo=memo,
            )

        return rebound_dict

    if isinstance(value, list):
        rebound_list: list[Any] = []
        memo[value_id] = rebound_list
        rebound_list.extend(
            rebind_runtime_graph(
                item,
                memo=memo,
            )
            for item in value
        )
        return rebound_list

    if isinstance(value, tuple):
        rebound_tuple = tuple(
            rebind_runtime_graph(
                item,
                memo=memo,
            )
            for item in value
        )
        memo[value_id] = rebound_tuple
        return rebound_tuple

    if isinstance(value, set):
        rebound_set: set[Any] = set()
        memo[value_id] = rebound_set
        rebound_set.update(
            rebind_runtime_graph(
                item,
                memo=memo,
            )
            for item in value
        )
        return rebound_set

    if isinstance(value, frozenset):
        rebound_frozenset = frozenset(
            rebind_runtime_graph(
                item,
                memo=memo,
            )
            for item in value
        )
        memo[value_id] = rebound_frozenset
        return rebound_frozenset

    source_type = type(value)
    current_type = resolve_current_type(
        source_type
    )
    target_type = (
        current_type
        if current_type is not None
        else source_type
    )

    if is_dataclass(value):
        try:
            rebound_object = target_type.__new__(
                target_type
            )
        except Exception as exc:
            raise FranchiseCheckpointError(
                "A runtime dataclass could not be rebound.",
                stage="normalize-dataclass",
                cause=exc,
            ) from exc

        memo[value_id] = rebound_object
        field_names: set[str] = set()

        for field_info in fields(value):
            field_names.add(
                field_info.name
            )
            set_runtime_attribute(
                rebound_object,
                field_info.name,
                rebind_runtime_graph(
                    getattr(
                        value,
                        field_info.name,
                    ),
                    memo=memo,
                ),
            )

        source_attributes = getattr(
            value,
            "__dict__",
            {},
        )

        for name, item in source_attributes.items():
            if name in field_names:
                continue

            set_runtime_attribute(
                rebound_object,
                name,
                rebind_runtime_graph(
                    item,
                    memo=memo,
                ),
            )

        return rebound_object

    if hasattr(value, "__dict__"):
        try:
            rebound_object = target_type.__new__(
                target_type
            )
        except Exception:
            return value

        memo[value_id] = rebound_object

        for name, item in value.__dict__.items():
            set_runtime_attribute(
                rebound_object,
                name,
                rebind_runtime_graph(
                    item,
                    memo=memo,
                ),
            )

        return rebound_object

    return value


def portable_checkpoint(
    checkpoint: FranchiseCheckpoint,
) -> FranchiseCheckpoint:
    try:
        memo: dict[int, Any] = {}
        return FranchiseCheckpoint(
            version=checkpoint.version,
            saved_at_utc=(
                checkpoint.saved_at_utc
            ),
            simulation_state=(
                rebind_runtime_graph(
                    checkpoint.simulation_state,
                    memo=memo,
                )
            ),
            trade_state=(
                rebind_runtime_graph(
                    checkpoint.trade_state,
                    memo=memo,
                )
            ),
            preferences=(
                rebind_runtime_graph(
                    checkpoint.preferences,
                    memo=memo,
                )
            ),
            reason=checkpoint.reason,
        )
    except FranchiseCheckpointError:
        raise
    except Exception as exc:
        raise FranchiseCheckpointError(
            "Checkpoint state normalization failed.",
            stage="normalize-runtime-graph",
            cause=exc,
        ) from exc


def checkpoint_from_payload(
    payload_object: Any,
) -> FranchiseCheckpoint:
    if isinstance(
        payload_object,
        FranchiseCheckpoint,
    ):
        checkpoint = payload_object
    else:
        required = (
            "version",
            "saved_at_utc",
            "simulation_state",
            "trade_state",
            "preferences",
            "reason",
        )

        if not all(
            hasattr(
                payload_object,
                name,
            )
            for name in required
        ):
            raise FranchiseCheckpointError(
                "Checkpoint payload has an invalid structure.",
                stage="validate-checkpoint-structure",
            )

        checkpoint = FranchiseCheckpoint(
            version=str(
                payload_object.version
            ),
            saved_at_utc=str(
                payload_object.saved_at_utc
            ),
            simulation_state=(
                payload_object.simulation_state
            ),
            trade_state=(
                payload_object.trade_state
            ),
            preferences=dict(
                payload_object.preferences
            ),
            reason=str(
                payload_object.reason
            ),
        )

    if (
        checkpoint.version
        != CHECKPOINT_VERSION
    ):
        raise FranchiseCheckpointError(
            "Checkpoint payload version is not current.",
            stage="validate-checkpoint-version",
        )

    return checkpoint


def encode_checkpoint(
    checkpoint: FranchiseCheckpoint,
) -> bytes:
    # cloudpickle is intentionally used for the payload. Streamlit hot
    # reloads can leave dataclass and Enum instances whose class identity
    # no longer matches the latest imported module object. Standard pickle
    # rejects those live objects; cloudpickle serializes their definitions
    # and allows the checkpoint to be normalized on load.
    try:
        payload = cloudpickle.dumps(
            checkpoint,
            protocol=pickle.HIGHEST_PROTOCOL,
        )
        serializer = "cloudpickle-v1"
    except Exception as cloudpickle_error:
        # Preserve the prior rebinding implementation as a conservative
        # fallback for objects cloudpickle cannot traverse directly.
        try:
            normalized = portable_checkpoint(
                checkpoint
            )
            payload = cloudpickle.dumps(
                normalized,
                protocol=pickle.HIGHEST_PROTOCOL,
            )
            serializer = (
                "cloudpickle-rebound-v1"
            )
        except Exception as rebound_error:
            raise FranchiseCheckpointError(
                "Checkpoint serialization failed.",
                stage="cloudpickle-payload",
                cause=rebound_error,
            ) from cloudpickle_error

    envelope = {
        "version": CHECKPOINT_VERSION,
        "implementation": (
            CHECKPOINT_IMPLEMENTATION_VERSION
        ),
        "serializer": serializer,
        "sha256": hashlib.sha256(
            payload
        ).hexdigest(),
        "payload": payload,
    }

    try:
        return pickle.dumps(
            envelope,
            protocol=pickle.HIGHEST_PROTOCOL,
        )
    except Exception as exc:
        raise FranchiseCheckpointError(
            "Checkpoint envelope serialization failed.",
            stage="pickle-envelope",
            cause=exc,
        ) from exc


def decode_checkpoint(
    encoded: bytes,
) -> FranchiseCheckpoint:
    try:
        envelope = pickle.loads(
            encoded
        )
    except Exception as exc:
        raise FranchiseCheckpointError(
            "Checkpoint envelope could not be decoded.",
            stage="decode-envelope",
            cause=exc,
        ) from exc

    if not isinstance(
        envelope,
        dict,
    ):
        raise FranchiseCheckpointError(
            "Checkpoint envelope has an invalid type.",
            stage="validate-envelope",
        )

    if (
        envelope.get("version")
        != CHECKPOINT_VERSION
    ):
        raise FranchiseCheckpointError(
            "Checkpoint envelope version is not current.",
            stage="validate-envelope-version",
        )

    payload = envelope.get(
        "payload"
    )
    expected_digest = envelope.get(
        "sha256"
    )
    serializer = str(
        envelope.get(
            "serializer",
            "pickle-rebound-v1",
        )
    )

    if not isinstance(
        payload,
        bytes,
    ):
        raise FranchiseCheckpointError(
            "Checkpoint payload is missing.",
            stage="validate-payload",
        )

    actual_digest = hashlib.sha256(
        payload
    ).hexdigest()

    if actual_digest != expected_digest:
        raise FranchiseCheckpointError(
            "Checkpoint integrity verification failed.",
            stage="verify-sha256",
        )

    try:
        if serializer.startswith(
            "cloudpickle"
        ):
            payload_object = (
                cloudpickle.loads(
                    payload
                )
            )
            payload_object = (
                rebind_runtime_graph(
                    payload_object
                )
            )
        else:
            # Backward compatibility with every checkpoint written by the
            # V1 and V1.1 writers.
            payload_object = pickle.loads(
                payload
            )
    except Exception as exc:
        raise FranchiseCheckpointError(
            "Checkpoint payload could not be decoded.",
            stage=(
                f"decode-payload-{serializer}"
            ),
            cause=exc,
        ) from exc

    return checkpoint_from_payload(
        payload_object
    )


def enum_text(value: Any) -> str:
    return str(
        getattr(
            value,
            "value",
            value,
        )
        or ""
    )


def checkpoint_progress_key(
    simulation_state: Any,
) -> tuple[int, int, int, int, int]:
    transition_count = int(
        getattr(
            simulation_state,
            "season_transition_count",
            0,
        )
        or 0
    )
    phase_rank = {
        "preseason": 0,
        "regular_season": 1,
        "play_in": 2,
        "playoffs": 3,
        "offseason": 4,
    }.get(
        enum_text(
            getattr(
                simulation_state,
                "phase",
                "",
            )
        ),
        -1,
    )
    completed_regular = len(
        getattr(
            simulation_state,
            "completed_games",
            {},
        )
        or {}
    )
    postseason = getattr(
        simulation_state,
        "postseason_state",
        None,
    )
    postseason_stage_rank = {
        "not_started": 0,
        "play_in_opening": 1,
        "play_in_final": 2,
        "first_round": 3,
        "conference_semifinals": 4,
        "conference_finals": 5,
        "nba_finals": 6,
        "complete": 7,
    }.get(
        enum_text(
            getattr(
                postseason,
                "stage",
                "",
            )
        ),
        0,
    )
    completed_postseason = len(
        getattr(
            postseason,
            "completed_games",
            {},
        )
        or {}
    )

    return (
        transition_count,
        phase_rank,
        completed_regular,
        postseason_stage_rank,
        completed_postseason,
    )


def checkpoint_season_label(
    simulation_state: Any,
) -> str:
    settings = getattr(
        simulation_state,
        "settings",
        None,
    )
    return str(
        getattr(
            settings,
            "season_label",
            "",
        )
        or ""
    )


def retry_io_operation(
    operation: Any,
    *,
    stage: str,
) -> Any:
    last_error: BaseException | None = None

    for attempt, delay in enumerate(
        (*IO_RETRY_DELAYS, None),
        start=1,
    ):
        try:
            return operation()
        except (
            PermissionError,
            OSError,
        ) as exc:
            last_error = exc

            if delay is None:
                break

            time.sleep(delay)

    raise FranchiseCheckpointError(
        "Checkpoint file I/O failed after retries.",
        stage=(
            f"{stage}-attempt-{attempt}"
        ),
        cause=last_error,
    )


def write_encoded_checkpoint(
    path: Path,
    encoded: bytes,
) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    descriptor, temporary_name = (
        tempfile.mkstemp(
            prefix=(
                path.name + "."
            ),
            suffix=".tmp",
            dir=str(path.parent),
        )
    )
    temporary_path = Path(
        temporary_name
    )

    try:
        with os.fdopen(
            descriptor,
            "wb",
        ) as raw:
            with gzip.GzipFile(
                fileobj=raw,
                mode="wb",
                compresslevel=1,
            ) as compressed:
                compressed.write(
                    encoded
                )
            raw.flush()
            os.fsync(
                raw.fileno()
            )

        retry_io_operation(
            lambda: os.replace(
                temporary_path,
                path,
            ),
            stage="replace-primary",
        )
    except FranchiseCheckpointError:
        raise
    except Exception as exc:
        raise FranchiseCheckpointError(
            "Checkpoint temporary file could not be written.",
            stage="write-temporary",
            cause=exc,
        ) from exc
    finally:
        if temporary_path.exists():
            try:
                temporary_path.unlink()
            except OSError:
                pass


def copy_valid_primary_to_backup(
    primary: Path,
    backup: Path,
) -> None:
    if not primary.exists():
        return

    try:
        load_checkpoint_path(
            primary
        )
    except FranchiseCheckpointError:
        return

    backup.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    retry_io_operation(
        lambda: shutil.copy2(
            primary,
            backup,
        ),
        stage="copy-backup",
    )


def save_franchise_checkpoint(
    simulation_state: Any,
    trade_state: Any,
    *,
    preferences: Mapping[
        str,
        Any,
    ] | None = None,
    reason: str = "",
    path: Path = (
        DEFAULT_CHECKPOINT_PATH
    ),
    copy_payload: bool = True,
) -> FranchiseCheckpoint:
    checkpoint = FranchiseCheckpoint(
        version=CHECKPOINT_VERSION,
        saved_at_utc=utc_timestamp(),
        simulation_state=(
            copy.deepcopy(
                simulation_state
            )
            if copy_payload
            else simulation_state
        ),
        trade_state=(
            copy.deepcopy(
                trade_state
            )
            if copy_payload
            else trade_state
        ),
        preferences=(
            copy.deepcopy(
                dict(
                    preferences or {}
                )
            )
            if copy_payload
            else dict(
                preferences or {}
            )
        ),
        reason=str(reason),
    )
    resolved_path = Path(path)
    backup_path = (
        checkpoint_backup_path(
            resolved_path
        )
    )

    try:
        existing = (
            load_franchise_checkpoint(
                path=resolved_path,
                allow_backup=False,
            )
            if resolved_path.exists()
            else None
        )

        if (
            existing is not None
            and checkpoint_season_label(
                existing.simulation_state
            )
            == checkpoint_season_label(
                checkpoint.simulation_state
            )
            and checkpoint_progress_key(
                checkpoint.simulation_state
            )
            < checkpoint_progress_key(
                existing.simulation_state
            )
        ):
            # Multiple Streamlit tabs can rerun independently. A stale tab
            # must never overwrite a more advanced playoff checkpoint.
            return existing

        encoded = encode_checkpoint(
            checkpoint
        )
        copy_valid_primary_to_backup(
            resolved_path,
            backup_path,
        )
        write_encoded_checkpoint(
            resolved_path,
            encoded,
        )
        verified = load_checkpoint_path(
            resolved_path
        )

        if (
            verified.saved_at_utc
            != checkpoint.saved_at_utc
            or verified.reason
            != checkpoint.reason
        ):
            raise FranchiseCheckpointError(
                "Checkpoint verification returned the wrong revision.",
                stage="verify-written-revision",
            )
    except FranchiseCheckpointError:
        raise
    except Exception as exc:
        raise FranchiseCheckpointError(
            "The durable franchise checkpoint could not be written.",
            stage="save-checkpoint",
            cause=exc,
        ) from exc

    return checkpoint


def load_checkpoint_path(
    path: Path,
) -> FranchiseCheckpoint:
    try:
        with gzip.open(
            path,
            "rb",
        ) as handle:
            encoded = handle.read()
    except Exception as exc:
        raise FranchiseCheckpointError(
            f"Checkpoint file could not be read: {path}.",
            stage="read-checkpoint-file",
            cause=exc,
        ) from exc

    return decode_checkpoint(
        encoded
    )


def load_franchise_checkpoint(
    *,
    path: Path = (
        DEFAULT_CHECKPOINT_PATH
    ),
    allow_backup: bool = True,
) -> FranchiseCheckpoint | None:
    resolved_path = Path(path)
    backup_path = (
        checkpoint_backup_path(
            resolved_path
        )
    )

    if not resolved_path.exists():
        if (
            allow_backup
            and backup_path.exists()
        ):
            return load_checkpoint_path(
                backup_path
            )

        return None

    try:
        return load_checkpoint_path(
            resolved_path
        )
    except FranchiseCheckpointError:
        if (
            allow_backup
            and backup_path.exists()
        ):
            return load_checkpoint_path(
                backup_path
            )

        raise


def clear_franchise_checkpoint(
    *,
    path: Path = (
        DEFAULT_CHECKPOINT_PATH
    ),
) -> None:
    resolved_path = Path(path)
    backup_path = (
        checkpoint_backup_path(
            resolved_path
        )
    )

    for candidate in (
        resolved_path,
        backup_path,
    ):
        if candidate.exists():
            retry_io_operation(
                candidate.unlink,
                stage="clear-checkpoint",
            )


def checkpoint_metadata(
    checkpoint: FranchiseCheckpoint,
) -> dict[str, Any]:
    return {
        "version": checkpoint.version,
        "implementation": (
            CHECKPOINT_IMPLEMENTATION_VERSION
        ),
        "saved_at_utc": (
            checkpoint.saved_at_utc
        ),
        "reason": checkpoint.reason,
        "preference_keys": sorted(
            checkpoint.preferences
        ),
    }


def create_stale_reload_fixture(
    directory: Path,
) -> tuple[
    Any,
    Any,
    str,
]:
    module_name = (
        "checkpoint_reload_fixture_v1"
    )
    module_path = (
        directory
        / f"{module_name}.py"
    )
    source = (
        "from dataclasses import dataclass\n"
        "from enum import Enum\n"
        "class Phase(str, Enum):\n"
        "    PLAYOFFS = 'playoffs'\n"
        "@dataclass\n"
        "class State:\n"
        "    games: int\n"
        "    phase: Phase\n"
    )
    module_path.write_text(
        source,
        encoding="utf-8",
    )
    sys.path.insert(
        0,
        str(directory),
    )
    importlib.invalidate_caches()
    module = importlib.import_module(
        module_name
    )
    stale_state = module.State(
        games=88,
        phase=module.Phase.PLAYOFFS,
    )
    module_path.write_text(
        source + "\nRELOADED = True\n",
        encoding="utf-8",
    )
    importlib.invalidate_caches()
    current_module = importlib.reload(
        module
    )
    return (
        stale_state,
        current_module,
        module_name,
    )


def run_self_test() -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as directory:
        directory_path = Path(
            directory
        )
        path = (
            directory_path
            / "checkpoint.pkl.gz"
        )
        backup = (
            checkpoint_backup_path(
                path
            )
        )
        first = save_franchise_checkpoint(
            {
                "season": "2026-27",
                "games": 82,
            },
            {
                "revision": 3,
            },
            preferences={
                "controlled": ["CHI"],
            },
            reason="first",
            path=path,
        )
        loaded_first = (
            load_franchise_checkpoint(
                path=path
            )
        )
        second = save_franchise_checkpoint(
            {
                "season": "2026-27",
                "games": 90,
            },
            {
                "revision": 4,
            },
            preferences={
                "controlled": ["CHI"],
                "active": "CHI",
            },
            reason="second",
            path=path,
        )
        loaded_second = (
            load_franchise_checkpoint(
                path=path
            )
        )
        backup_existed = backup.exists()

        stale_state, current_module, module_name = (
            create_stale_reload_fixture(
                directory_path
            )
        )
        stale_path = (
            directory_path
            / "stale.pkl.gz"
        )
        stale_saved = save_franchise_checkpoint(
            stale_state,
            {"revision": 5},
            reason="stale-class",
            path=stale_path,
            copy_payload=False,
        )
        stale_loaded = (
            load_franchise_checkpoint(
                path=stale_path
            )
        )
        stale_rebound = (
            type(
                stale_loaded.simulation_state
            )
            is current_module.State
            and stale_loaded
            .simulation_state.phase
            is current_module.Phase.PLAYOFFS
        )

        with path.open(
            "wb",
        ) as handle:
            handle.write(
                b"corrupted"
            )

        recovered = (
            load_franchise_checkpoint(
                path=path,
                allow_backup=True,
            )
        )
        clear_franchise_checkpoint(
            path=path
        )
        clear_franchise_checkpoint(
            path=stale_path
        )

        regression_path = (
            directory_path
            / "regression.pkl.gz"
        )
        advanced_state = SimpleNamespace(
            settings=SimpleNamespace(
                season_label="2026-27"
            ),
            season_transition_count=0,
            phase="offseason",
            completed_games={
                index: True
                for index in range(1230)
            },
            postseason_state=SimpleNamespace(
                stage="complete",
                completed_games={
                    index: True
                    for index in range(88)
                },
                champion="CHI",
            ),
        )
        stale_progress_state = SimpleNamespace(
            settings=SimpleNamespace(
                season_label="2026-27"
            ),
            season_transition_count=0,
            phase="play_in",
            completed_games={
                index: True
                for index in range(1230)
            },
            postseason_state=SimpleNamespace(
                stage="play_in_opening",
                completed_games={},
                champion="",
            ),
        )
        save_franchise_checkpoint(
            advanced_state,
            {"revision": 9},
            reason="advanced-state",
            path=regression_path,
            copy_payload=False,
        )
        regression_result = (
            save_franchise_checkpoint(
                stale_progress_state,
                {"revision": 10},
                reason="stale-tab",
                path=regression_path,
                copy_payload=False,
            )
        )
        regression_loaded = (
            load_franchise_checkpoint(
                path=regression_path
            )
        )
        clear_franchise_checkpoint(
            path=regression_path
        )
        sys.modules.pop(
            module_name,
            None,
        )

        try:
            sys.path.remove(
                str(directory_path)
            )
        except ValueError:
            pass

        checks = {
            "checkpoint_version_is_current": (
                first.version
                == CHECKPOINT_VERSION
            ),
            "cloudpickle_runtime_is_available": (
                bool(cloudpickle.__version__)
            ),
            "implementation_version_is_current": (
                CHECKPOINT_IMPLEMENTATION_VERSION
                == (
                    "simulation-franchise-checkpoint-v1.2-2026-08-08"
                )
            ),
            "checkpoint_round_trip_preserves_state": (
                loaded_first is not None
                and loaded_first
                .simulation_state[
                    "games"
                ]
                == 82
                and loaded_first.trade_state[
                    "revision"
                ]
                == 3
            ),
            "new_checkpoint_replaces_primary": (
                loaded_second is not None
                and loaded_second
                .simulation_state[
                    "games"
                ]
                == 90
                and loaded_second.reason
                == "second"
            ),
            "previous_checkpoint_becomes_backup": (
                backup_existed
            ),
            "stale_hot_reload_class_is_rebound": (
                stale_saved.reason
                == "stale-class"
                and stale_rebound
            ),
            "stale_tab_cannot_overwrite_advanced_state": (
                regression_result.reason
                == "advanced-state"
                and regression_loaded.reason
                == "advanced-state"
                and getattr(
                    regression_loaded.simulation_state
                    .postseason_state,
                    "champion",
                    "",
                )
                == "CHI"
            ),
            "corrupted_primary_recovers_backup": (
                recovered is not None
                and recovered
                .simulation_state[
                    "games"
                ]
                == 82
            ),
            "clear_removes_primary_and_backup": (
                not path.exists()
                and not backup.exists()
            ),
            "metadata_is_json_safe": bool(
                json.dumps(
                    checkpoint_metadata(
                        second
                    )
                )
            ),
        }

    failed = [
        name
        for name, passed
        in checks.items()
        if not passed
    ]
    report = {
        "script": (
            CHECKPOINT_IMPLEMENTATION_VERSION
        ),
        "state_contract": CHECKPOINT_VERSION,
        "checks": checks,
        "failed_checks": failed,
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

    if failed:
        raise AssertionError(
            "Franchise checkpoint self-test failed: "
            + ", ".join(failed)
        )

    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--self-test",
        action="store_true",
    )
    args = parser.parse_args()

    if args.self_test:
        report = run_self_test()
        print(
            json.dumps(
                report,
                indent=2,
            )
        )
        print(
            "\nSIMULATION FRANCHISE "
            "CHECKPOINT V1.2 SELF-TEST PASSED"
        )
        return 0

    checkpoint = (
        load_franchise_checkpoint()
    )
    print(
        json.dumps(
            (
                {
                    "script": (
                        CHECKPOINT_IMPLEMENTATION_VERSION
                    ),
                    "checkpoint": None,
                }
                if checkpoint is None
                else {
                    "script": (
                        CHECKPOINT_IMPLEMENTATION_VERSION
                    ),
                    "checkpoint": (
                        checkpoint_metadata(
                            checkpoint
                        )
                    ),
                }
            ),
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
