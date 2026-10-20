"""A deterministic annotation adapter, not an image recognition algorithm."""

from typing import Protocol

from hometrace.models import DetectionResult, Observation, Status


class Detector(Protocol):
    def detect_target(self, observation: Observation, object_id: str) -> DetectionResult: ...


class FixtureDetector:
    """Read explicitly supplied test annotations; never infer a visual result."""

    def __init__(self, detections: dict[str, DetectionResult]) -> None:
        self._detections = dict(detections)

    def detect_target(self, observation: Observation, object_id: str) -> DetectionResult:
        detection = self._detections.get(observation.evidence_id)
        if (
            observation.data_source != "fixture"
            or observation.image_path is not None
            or observation.image_hash is not None
            or observation.visibility_status != "clear"
            or detection is None
            or detection.evidence_id != observation.evidence_id
            or detection.target_id != object_id
            or detection.matcher != "fixture_annotation"
            or detection.status not in (
                Status.FOUND,
                Status.SUSPECTED,
                Status.NOT_FOUND_IN_VIEW,
                Status.UNKNOWN,
            )
        ):
            return DetectionResult(object_id, observation.evidence_id, Status.UNKNOWN)
        return detection
