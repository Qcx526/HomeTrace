"""Local recorded-image inputs with explicit simulated navigation and provenance."""

import hashlib
import json
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from .models import DataSource, NavigationMode, NavigationResult, Observation, TimestampBasis, Viewpoint


MAX_IMAGE_BYTES = 25 * 1024 * 1024
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tif", ".tiff"}


@dataclass(frozen=True)
class RecordedScene:
    image_root: Path
    viewpoints: list[Viewpoint]
    observations: dict[str, Observation]
    unreachable_viewpoints: set[str]


def _fields(value: Any, required: set[str], optional: set[str], label: str) -> dict:
    if not isinstance(value, dict):
        raise ValueError(f"{label}: expected a JSON object")
    missing = required - value.keys()
    extra = value.keys() - required - optional
    if missing or extra:
        raise ValueError(f"{label}: missing fields {sorted(missing)}, unknown fields {sorted(extra)}")
    return value


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label}: expected nonempty text")
    return value


def _array(value: Any, label: str) -> list:
    if not isinstance(value, list):
        raise ValueError(f"{label}: expected a JSON array")
    return value


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON field: {key}")
        result[key] = value
    return result


def resolve_image_path(image_root: Path, image_path: str) -> Path:
    """Confine a portable relative image path to its configured root, including links."""
    name = _text(image_path, "image_path")
    parts = name.split("/")
    if (
        "\\" in name or ":" in name or "\x00" in name
        or PurePosixPath(name).is_absolute() or PureWindowsPath(name).drive
        or any(part in ("", ".", "..") for part in parts)
    ):
        raise ValueError("image_path: require a relative POSIX path without traversal")
    if PurePosixPath(name).suffix.lower() not in IMAGE_SUFFIXES:
        raise ValueError("image_path: unsupported image extension")
    root = Path(image_root).resolve()
    try:
        path = root.joinpath(*parts).resolve()
    except (OSError, RuntimeError) as exc:
        raise ValueError("image_path: cannot resolve path") from exc
    if not path.is_relative_to(root):
        raise ValueError("image_path: resolved path escapes image_root")
    return path


def load_recorded_scene(manifest_path: Path, image_root: Path | None = None) -> RecordedScene:
    """Read metadata only; never accept target labels or caller-supplied image hashes."""
    manifest_path = Path(manifest_path)
    try:
        data = json.loads(
            manifest_path.read_text(encoding="utf-8"), object_pairs_hook=_unique_json_object
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Cannot read recorded-image manifest {manifest_path}: {exc}") from exc
    root = _fields(
        data,
        {"schema_version", "data_source", "navigation_mode", "timestamp_basis", "capture_source", "viewpoints", "observations"},
        {"unreachable_viewpoints"},
        "recorded_scene",
    )
    if type(root["schema_version"]) is not int or root["schema_version"] != 1:
        raise ValueError("schema_version: expected 1")
    if root["data_source"] != DataSource.RECORDED_IMAGE:
        raise ValueError("data_source: expected recorded_image, never real_robot")
    if root["navigation_mode"] != NavigationMode.SIMULATED:
        raise ValueError("navigation_mode: expected simulated_navigation")
    try:
        basis = TimestampBasis(_text(root["timestamp_basis"], "timestamp_basis"))
    except ValueError as exc:
        raise ValueError("timestamp_basis: require declared_capture or demo_sequence") from exc
    if basis == TimestampBasis.FIXTURE:
        raise ValueError("timestamp_basis: require declared_capture or demo_sequence")
    source = _text(root["capture_source"], "capture_source")
    directory = Path(image_root if image_root is not None else manifest_path.parent).resolve()
    if not directory.is_dir():
        raise ValueError("image_root: expected an existing directory")

    viewpoints = []
    known = set()
    for index, raw in enumerate(_array(root["viewpoints"], "viewpoints")):
        label = f"viewpoints[{index}]"
        row = _fields(raw, {"viewpoint_id", "name"}, set(), label)
        view_id = _text(row["viewpoint_id"], f"{label}.viewpoint_id")
        if view_id in known:
            raise ValueError(f"{label}: duplicate viewpoint")
        known.add(view_id)
        viewpoints.append(Viewpoint(view_id, _text(row["name"], f"{label}.name")))
    if not viewpoints:
        raise ValueError("viewpoints: at least one viewpoint is required")
    unreachable_values = _array(root.get("unreachable_viewpoints", []), "unreachable_viewpoints")
    unreachable = {_text(value, "unreachable_viewpoints[]") for value in unreachable_values}
    if len(unreachable) != len(unreachable_values) or not unreachable <= known:
        raise ValueError("unreachable_viewpoints: require unique known viewpoints")

    observations = {}
    evidence_ids = set()
    for index, raw in enumerate(_array(root["observations"], "observations")):
        label = f"observations[{index}]"
        row = _fields(
            raw, {"evidence_id", "viewpoint_id", "captured_at", "image_path", "visibility_status"}, set(), label
        )
        evidence_id = _text(row["evidence_id"], f"{label}.evidence_id")
        view_id = _text(row["viewpoint_id"], f"{label}.viewpoint_id")
        if evidence_id in evidence_ids:
            raise ValueError(f"{label}: duplicate evidence ID")
        if view_id not in known:
            raise ValueError(f"{label}: unknown viewpoint")
        if view_id in observations:
            raise ValueError(f"{label}: only one observation per viewpoint is supported")
        timestamp = _text(row["captured_at"], f"{label}.captured_at")
        try:
            captured = datetime.fromisoformat(timestamp)
        except ValueError as exc:
            raise ValueError(f"{label}.captured_at: require ISO timestamp with timezone") from exc
        if captured.utcoffset() is None:
            raise ValueError(f"{label}.captured_at: timezone required")
        visibility = row["visibility_status"]
        if visibility not in ("clear", "occluded", "unobservable"):
            raise ValueError(f"{label}.visibility_status: require clear, occluded or unobservable")
        path = _text(row["image_path"], f"{label}.image_path")
        resolve_image_path(directory, path)
        evidence_ids.add(evidence_id)
        observations[view_id] = Observation(
            evidence_id, view_id, timestamp, DataSource.RECORDED_IMAGE, visibility,
            image_path=path, capture_source=source, timestamp_basis=basis,
        )
    return RecordedScene(directory, viewpoints, observations, unreachable)


class RecordedImageAdapter:
    """Simulate arrival, then read a local image; this adapter cannot represent a robot."""

    data_source = DataSource.RECORDED_IMAGE
    navigation_mode = NavigationMode.SIMULATED

    def __init__(self, scene: RecordedScene):
        self._root = scene.image_root
        self._viewpoints = list(scene.viewpoints)
        self._observations = dict(scene.observations)
        self._known = {view.viewpoint_id for view in self._viewpoints}
        self._unreachable = set(scene.unreachable_viewpoints)
        if len(self._known) != len(self._viewpoints) or not self._unreachable <= self._known:
            raise ValueError("RecordedImageAdapter requires unique known viewpoints")
        for view_id, observed in self._observations.items():
            if view_id not in self._known or observed.viewpoint_id != view_id:
                raise ValueError("RecordedImageAdapter observation must match a known viewpoint")
            if observed.data_source != DataSource.RECORDED_IMAGE:
                raise ValueError("RecordedImageAdapter accepts recorded_image observations only")
            if observed.image_path is None:
                raise ValueError("RecordedImageAdapter requires an image path")
            resolve_image_path(self._root, observed.image_path)
        self._arrived_at: str | None = None

    def list_viewpoints(self) -> list[Viewpoint]:
        return list(self._viewpoints)

    def navigate_to(self, viewpoint_id: str) -> NavigationResult:
        self._arrived_at = None
        status = "UNREACHABLE"
        if viewpoint_id in self._known and viewpoint_id not in self._unreachable:
            self._arrived_at = viewpoint_id
            status = "ARRIVED"
        return NavigationResult(viewpoint_id, status, "recorded_image", True, NavigationMode.SIMULATED)

    def observe(self, viewpoint_id: str) -> Observation | None:
        if self._arrived_at != viewpoint_id:
            return None
        observation = self._observations.get(viewpoint_id)
        if observation is None:
            return None
        try:
            path = resolve_image_path(self._root, observation.image_path)
            if not path.is_file():
                error = "image_not_file" if path.exists() else "image_missing"
                return replace(observation, image_hash=None, error=error)
            if path.stat().st_size > MAX_IMAGE_BYTES:
                return replace(observation, image_hash=None, error="image_too_large")
            with path.open("rb") as stream:
                content = stream.read(MAX_IMAGE_BYTES + 1)
            if len(content) > MAX_IMAGE_BYTES:
                return replace(observation, image_hash=None, error="image_too_large")
        except ValueError:
            return replace(observation, image_hash=None, error="invalid_image_path")
        except FileNotFoundError:
            return replace(observation, image_hash=None, error="image_missing")
        except OSError:
            return replace(observation, image_hash=None, error="image_unreadable")
        return replace(
            observation, image_hash=hashlib.sha256(content).hexdigest(),
            error=None if content else "image_empty",
        )
