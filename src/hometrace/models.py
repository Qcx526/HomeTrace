"""Shared, model-independent contracts for the offline search loop."""

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class Status(str, Enum):
    FOUND = "FOUND"
    SUSPECTED = "SUSPECTED"
    NOT_FOUND_IN_VIEW = "NOT_FOUND_IN_VIEW"
    UNKNOWN = "UNKNOWN"
    UNREACHABLE = "UNREACHABLE"


@dataclass(frozen=True)
class RegisteredObject:
    object_id: str
    description: str
    sample_image_path: str | None = None


@dataclass(frozen=True)
class Viewpoint:
    viewpoint_id: str
    name: str


@dataclass(frozen=True)
class Observation:
    evidence_id: str
    viewpoint_id: str
    captured_at: str
    data_source: str = "fixture"
    visibility_status: str = "clear"
    image_path: str | None = None
    image_hash: str | None = None


@dataclass(frozen=True)
class DetectionResult:
    target_id: str
    evidence_id: str
    status: Status
    matcher: str = "fixture_annotation"
    score: float | None = None


@dataclass(frozen=True)
class MemoryRecord:
    observation: Observation
    detection: DetectionResult


@dataclass(frozen=True)
class NavigationResult:
    viewpoint_id: str
    status: str
    adapter_kind: str = "mock"
    simulated: bool = True


@dataclass(frozen=True)
class PlanDecision:
    viewpoint_id: str
    reason: str
    score: int


@dataclass(frozen=True)
class TaskEvent:
    seq: int
    action: str
    input_ids: list[str]
    result: dict[str, Any]
    provenance: dict[str, Any]


@dataclass
class TaskState:
    task_id: str
    object_id: str
    visited_viewpoints: list[str] = field(default_factory=list)
    evidence: list[MemoryRecord] = field(default_factory=list)
    events: list[TaskEvent] = field(default_factory=list)
    result_status: Status = Status.UNKNOWN
    location: str | None = None


@dataclass(frozen=True)
class SearchReport:
    task_id: str
    object_id: str
    result_status: Status
    location: str | None
    evidence_ids: list[str]
    visited_viewpoints: list[str]
    evidence: list[MemoryRecord]
    events: list[TaskEvent]
    limitations: list[str]
    navigation_mode: str = "mock"
    data_source: str = "fixture"
    schema_version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
