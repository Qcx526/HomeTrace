"""Load and validate the synthetic Issue #1 scenario format."""

import json
import math
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from hometrace.models import (
    DetectionResult,
    MemoryRecord,
    Observation,
    RegisteredObject,
    Status,
    Viewpoint,
)


@dataclass(frozen=True)
class Scenario:
    object: RegisteredObject
    viewpoints: list[Viewpoint]
    memory_records: list[MemoryRecord]
    observations: dict[str, Observation]
    detections: dict[str, DetectionResult]
    unreachable_viewpoints: set[str]


def _fields(value: Any, required: set[str], optional: set[str], location: str) -> dict:
    if not isinstance(value, dict):
        raise ValueError(f"{location}: expected a JSON object")
    missing = required - value.keys()
    extra = value.keys() - required - optional
    if missing or extra:
        raise ValueError(f"{location}: missing fields {sorted(missing)}, unknown fields {sorted(extra)}")
    return value


def _text(value: Any, location: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{location}: expected nonempty text")
    return value


def _array(value: Any, location: str) -> list:
    if not isinstance(value, list):
        raise ValueError(f"{location}: expected a JSON array")
    return value


def load_fixture(path: Path) -> Scenario:
    """Reject ambiguous provenance and inconsistent evidence before any search."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Cannot read fixture {path}: {exc}") from exc
    root = _fields(
        data,
        {
            "schema_version", "name", "data_source", "navigation", "object",
            "viewpoints", "memory_records", "observations", "detections",
        },
        set(),
        "fixture",
    )
    if type(root["schema_version"]) is not int or root["schema_version"] != 1:
        raise ValueError("fixture.schema_version: expected 1")
    _text(root["name"], "fixture.name")
    if root["data_source"] != "fixture":
        raise ValueError("fixture.data_source: only synthetic 'fixture' data is supported")
    navigation = _fields(
        root["navigation"], {"adapter_kind", "simulated", "unreachable_viewpoints"}, set(), "navigation"
    )
    if navigation["adapter_kind"] != "mock" or navigation["simulated"] is not True:
        raise ValueError("navigation: this stage requires mock, simulated navigation")
    item = _fields(root["object"], {"object_id", "description"}, {"sample_image_path"}, "object")
    if item.get("sample_image_path") is not None:
        raise ValueError("object.sample_image_path: fixtures must not claim a sample image")
    registered = RegisteredObject(
        _text(item["object_id"], "object.object_id"),
        _text(item["description"], "object.description"),
    )
    viewpoints = []
    known: set[str] = set()
    for index, raw in enumerate(_array(root["viewpoints"], "viewpoints")):
        label = f"viewpoints[{index}]"
        point = _fields(raw, {"viewpoint_id", "name"}, set(), label)
        point_id = _text(point["viewpoint_id"], f"{label}.viewpoint_id")
        if point_id in known:
            raise ValueError(f"{label}: duplicate viewpoint ID {point_id!r}")
        known.add(point_id)
        viewpoints.append(Viewpoint(point_id, _text(point["name"], f"{label}.name")))
    if not viewpoints:
        raise ValueError("viewpoints: at least one viewpoint is required")
    unreachable_list = _array(navigation["unreachable_viewpoints"], "navigation.unreachable_viewpoints")
    unreachable = {
        _text(value, "navigation.unreachable_viewpoints[]") for value in unreachable_list
    }
    if len(unreachable) != len(unreachable_list) or not unreachable <= known:
        raise ValueError("navigation.unreachable_viewpoints: require unique known viewpoint IDs")

    evidence_ids: set[str] = set()

    def observation(raw: Any, label: str) -> Observation:
        row = _fields(
            raw, {"evidence_id", "viewpoint_id", "captured_at", "data_source", "visibility_status"},
            {"image_path", "image_hash"}, label,
        )
        evidence_id = _text(row["evidence_id"], f"{label}.evidence_id")
        if evidence_id in evidence_ids:
            raise ValueError(f"{label}: duplicate evidence ID {evidence_id!r}")
        evidence_ids.add(evidence_id)
        viewpoint_id = _text(row["viewpoint_id"], f"{label}.viewpoint_id")
        if viewpoint_id not in known:
            raise ValueError(f"{label}: unknown viewpoint {viewpoint_id!r}")
        timestamp = _text(row["captured_at"], f"{label}.captured_at")
        try:
            parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{label}.captured_at: expected ISO timestamp with timezone") from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError(f"{label}.captured_at: timezone is required")
        if row["data_source"] != "fixture":
            raise ValueError(f"{label}.data_source: expected 'fixture'")
        if row.get("image_path") is not None or row.get("image_hash") is not None:
            raise ValueError(f"{label}: synthetic fixtures must not claim image paths or hashes")
        if row["visibility_status"] not in ("clear", "occluded", "unobservable"):
            raise ValueError(f"{label}.visibility_status: expected clear, occluded or unobservable")
        return Observation(evidence_id, viewpoint_id, timestamp, "fixture", row["visibility_status"])

    def detection(raw: Any, label: str, expected_ids: set[str]) -> DetectionResult:
        row = _fields(
            raw, {"target_id", "evidence_id", "status", "matcher"}, {"score"}, label
        )
        if row["target_id"] != registered.object_id:
            raise ValueError(f"{label}.target_id: must match the registered object")
        evidence_id = _text(row["evidence_id"], f"{label}.evidence_id")
        if evidence_id not in expected_ids:
            raise ValueError(f"{label}.evidence_id: no matching observation")
        try:
            status = Status(row["status"])
        except (ValueError, TypeError) as exc:
            raise ValueError(f"{label}.status: invalid detection status") from exc
        if status == Status.UNREACHABLE:
            raise ValueError(f"{label}.status: UNREACHABLE is a navigation result")
        if row["matcher"] != "fixture_annotation":
            raise ValueError(f"{label}.matcher: expected 'fixture_annotation'")
        score = row.get("score")
        if score is not None and (
            isinstance(score, bool) or not isinstance(score, (int, float))
            or not math.isfinite(score) or not 0 <= score <= 1
        ):
            raise ValueError(f"{label}.score: expected null or a number from 0 to 1")
        return DetectionResult(registered.object_id, evidence_id, status, "fixture_annotation", score)

    memory = []
    for index, raw in enumerate(_array(root["memory_records"], "memory_records")):
        label = f"memory_records[{index}]"
        row = _fields(raw, {"observation", "detection"}, set(), label)
        observed = observation(row["observation"], f"{label}.observation")
        detected = detection(row["detection"], f"{label}.detection", {observed.evidence_id})
        if observed.visibility_status != "clear" and detected.status != Status.UNKNOWN:
            raise ValueError(f"{label}: obscured history must have UNKNOWN status")
        memory.append(MemoryRecord(observed, detected))

    observations = {}
    for index, raw in enumerate(_array(root["observations"], "observations")):
        observed = observation(raw, f"observations[{index}]")
        if observed.viewpoint_id in observations:
            raise ValueError(f"observations[{index}]: only one current observation per viewpoint")
        observations[observed.viewpoint_id] = observed
    current = {value.evidence_id: value for value in observations.values()}
    detections = {}
    for index, raw in enumerate(_array(root["detections"], "detections")):
        detected = detection(raw, f"detections[{index}]", set(current))
        if detected.evidence_id in detections:
            raise ValueError(f"detections[{index}]: duplicate annotation for evidence")
        if current[detected.evidence_id].visibility_status != "clear" and detected.status != Status.UNKNOWN:
            raise ValueError(f"detections[{index}]: obscured observation must have UNKNOWN status")
        detections[detected.evidence_id] = detected
    return Scenario(registered, viewpoints, memory, observations, detections, unreachable)
