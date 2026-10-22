"""Deterministic search decisions using memory and observations already acquired."""

from dataclasses import asdict
from datetime import datetime
import math
import re
from uuid import uuid4

from .environment import EnvironmentAdapter
from .memory import MemoryStore
from .perception import Detector
from .models import (
    DataSource,
    DetectionResult,
    MemoryRecord,
    NavigationMode,
    PlanDecision,
    SearchReport,
    SearchStrategy,
    Status,
    TaskEvent,
    TaskState,
    TimestampBasis,
)


class SearchCore:
    def __init__(
        self, memory: MemoryStore, environment: EnvironmentAdapter, detector: Detector,
        *, data_source: DataSource = DataSource.FIXTURE,
        navigation_mode: NavigationMode = NavigationMode.MOCK,
        operation: str = "search",
        strategy: SearchStrategy = SearchStrategy.MEMORY_FIRST,
    ):
        self.memory = memory
        self.environment = environment
        self.detector = detector
        self.data_source = DataSource(data_source)
        self.navigation_mode = NavigationMode(navigation_mode)
        if (self.data_source, self.navigation_mode) not in (
            (DataSource.FIXTURE, NavigationMode.MOCK),
            (DataSource.RECORDED_IMAGE, NavigationMode.SIMULATED),
        ):
            raise ValueError("Unsupported evidence/navigation combination")
        if operation not in ("search", "register"):
            raise ValueError("Unsupported operation")
        self.operation = operation
        self.strategy = SearchStrategy(strategy)
        self.adapter_kind = "mock" if self.data_source == DataSource.FIXTURE else "recorded_image"
        self._state: TaskState | None = None

    def plan_next(self, task_state: TaskState) -> PlanDecision | None:
        # This method sees only public viewpoint metadata and acquired memory.
        # It never reads observations/annotations from the fixture adapter.
        if self.strategy == SearchStrategy.FIXED_ORDER:
            remaining = sorted(
                view.viewpoint_id for view in self.environment.list_viewpoints()
                if view.viewpoint_id not in task_state.visited_viewpoints
            )
            return PlanDecision(remaining[0], "fixed_order", 0) if remaining else None
        latest = {}
        for record in self.memory.query_memory(task_state.object_id):
            latest[record.observation.viewpoint_id] = record
        ranked = []
        for view in self.environment.list_viewpoints():
            if view.viewpoint_id in task_state.visited_viewpoints:
                continue
            record = latest.get(view.viewpoint_id)
            score, recency, reason = 0, 0.0, "unvisited_fallback"
            if record:
                status = record.detection.status
                if status in (Status.FOUND, Status.SUSPECTED):
                    score = 100 if status == Status.FOUND else 50
                    recency = datetime.fromisoformat(
                        record.observation.captured_at
                    ).timestamp()
                    reason = f"latest_memory_{status.value.lower()}"
                elif status == Status.NOT_FOUND_IN_VIEW:
                    score, reason = -10, "latest_memory_negative"
            ranked.append(
                (-score, -recency, view.viewpoint_id, PlanDecision(view.viewpoint_id, reason, score))
            )
        return min(ranked, key=lambda item: item[:3])[3] if ranked else None

    def _event(
        self, state: TaskState, action: str, input_ids: list[str], result: dict
    ) -> None:
        state.events.append(
            TaskEvent(
                seq=len(state.events) + 1,
                action=action,
                input_ids=input_ids,
                result=result,
                provenance={"adapter_kind": self.adapter_kind, "simulated": True,
                            "navigation_mode": self.navigation_mode, "data_source": self.data_source},
            )
        )

    def run(self, object_id: str, task_id: str | None = None) -> SearchReport:
        registered = self.memory.get_object(object_id)
        if registered is None:
            raise ValueError(f"Unregistered object: {object_id}")
        if registered.data_source != self.data_source:
            raise ValueError("Registered object and search evidence sources differ")
        state = TaskState(task_id or str(uuid4()), object_id)
        self._state = state
        history = self.memory.query_memory(object_id)
        state.history = history
        seen_ids = {record.observation.evidence_id for record in history}
        seen_hashes = {record.observation.image_hash for record in history if record.observation.image_hash}
        if registered.sample_image_hash and self.operation != "register":
            seen_hashes.add(registered.sample_image_hash)
        bases = {record.observation.timestamp_basis for record in history}
        if len(bases) > 1:
            raise ValueError("Historical evidence mixes incompatible timestamp bases")
        latest_time = max((datetime.fromisoformat(r.observation.captured_at) for r in history), default=None)
        self._event(
            state, "query_memory", [object_id],
            {"records": [asdict(record) for record in history], "historical_only": True},
        )
        while decision := self.plan_next(state):
            view_id = decision.viewpoint_id
            self._event(state, "plan_next", [object_id], asdict(decision))
            state.visited_viewpoints.append(view_id)
            navigation = self.environment.navigate_to(view_id)
            self._event(state, "navigate", [view_id], asdict(navigation))
            if (
                navigation.status != "ARRIVED"
                or navigation.viewpoint_id != view_id
                or navigation.adapter_kind != self.adapter_kind
                or navigation.simulated is not True
                or navigation.navigation_mode != self.navigation_mode
            ):
                self._event(state, "view_result", [view_id], {"status": Status.UNREACHABLE})
                continue
            state.arrived_viewpoints.append(view_id)
            observation = self.environment.observe(view_id)
            self._event(
                state, "observe", [view_id],
                {"observation": asdict(observation) if observation else None},
            )
            if observation is None:
                self._event(state, "view_result", [view_id], {"status": Status.UNKNOWN, "reason": "no_observation"})
                continue
            rejection = None
            observed_time = None
            try:
                observed_time = datetime.fromisoformat(observation.captured_at)
                if observed_time.utcoffset() is None:
                    raise ValueError("Missing timezone")
                source = DataSource(observation.data_source)
                basis = TimestampBasis(observation.timestamp_basis)
            except (ValueError, TypeError):
                rejection = "invalid_source_or_timestamp"
            if observation.viewpoint_id != view_id:
                rejection = "wrong_viewpoint"
            elif rejection:
                pass
            elif source != self.data_source:
                rejection = "unsupported_evidence_source"
            elif source == DataSource.FIXTURE and (
                observation.image_path is not None or observation.image_hash is not None
                or basis != TimestampBasis.FIXTURE
            ):
                rejection = "unsupported_evidence_source"
            elif source == DataSource.RECORDED_IMAGE and (
                not observation.image_path or not observation.capture_source
                or basis not in (TimestampBasis.DECLARED_CAPTURE, TimestampBasis.DEMO_SEQUENCE)
                or (not observation.error and not re.fullmatch(r"[0-9a-f]{64}", observation.image_hash or ""))
            ):
                rejection = "incomplete_image_provenance"
            elif bases and basis not in bases:
                rejection = "timestamp_basis_changed"
            elif observation.evidence_id in seen_ids:
                rejection = "replayed_evidence"
            elif observation.image_hash and observation.image_hash in seen_hashes:
                rejection = "replayed_image_content"
            elif latest_time is not None and observed_time <= latest_time:
                rejection = "observation_not_newer_than_memory"
            if rejection:
                self._event(
                    state, "view_result", [view_id, observation.evidence_id],
                    {"status": Status.UNKNOWN, "reason": rejection},
                )
                continue
            seen_ids.add(observation.evidence_id)
            if observation.image_hash:
                seen_hashes.add(observation.image_hash)
            bases.add(basis)
            latest_time = observed_time
            detection = self.detector.detect_target(observation, object_id)
            if self.data_source == DataSource.FIXTURE or detection.diagnostics.get("image_decoded") is True:
                state.observed_viewpoints.append(view_id)
            if (
                detection.target_id != object_id
                or detection.evidence_id != observation.evidence_id
                or observation.visibility_status != "clear"
                or detection.status not in (Status.FOUND, Status.SUSPECTED, Status.NOT_FOUND_IN_VIEW, Status.UNKNOWN)
                or observation.error
                or (detection.data_source is not None and detection.data_source != self.data_source)
                or (self.data_source == DataSource.RECORDED_IMAGE and (
                    detection.data_source != DataSource.RECORDED_IMAGE
                    or not detection.matcher or detection.matcher == "fixture_annotation"
                    or detection.verification_kind != "reference_instance_match"
                    or detection.status == Status.NOT_FOUND_IN_VIEW
                    or (detection.status == Status.FOUND and (
                        detection.diagnostics.get("image_decoded") is not True
                        or not detection.bbox or len(detection.bbox) != 4
                        or not all(isinstance(x, (int, float)) and math.isfinite(x) for x in detection.bbox)
                        or detection.bbox[0] >= detection.bbox[2]
                        or detection.bbox[1] >= detection.bbox[3]
                    ))
                ))
            ):
                detection = DetectionResult(
                    object_id, observation.evidence_id, Status.UNKNOWN,
                    matcher=detection.matcher, data_source=self.data_source,
                    verification_kind=detection.verification_kind,
                    diagnostics={**detection.diagnostics, "rejection": observation.error or "unusable_detection"},
                )
            state.evidence.append(MemoryRecord(observation, detection))
            self._event(state, "detect_target", [observation.evidence_id, object_id], asdict(detection))
            inserted = self.memory.update_memory(observation, detection)
            self._event(
                state, "update_memory", [observation.evidence_id],
                {"inserted": inserted, "status": detection.status},
            )
            self._event(state, "view_result", [view_id], {"status": detection.status})
            if detection.status == Status.FOUND:
                state.result_status, state.location = Status.FOUND, view_id
                break
            if detection.status == Status.SUSPECTED:
                state.result_status = Status.SUSPECTED
        self._event(
            state, "complete", [object_id],
            {"result_status": state.result_status, "location": state.location},
        )
        return self.build_report(state.task_id)

    def build_report(self, task_id: str) -> SearchReport:
        state = self._state
        if state is None or state.task_id != task_id:
            raise ValueError("No matching search task")
        if self.data_source == DataSource.FIXTURE:
            limitations = [
                "Mock navigation only; no physical robot was run.",
                "All observations, annotations and timestamps are synthetic fixtures; no images were captured or analyzed.",
                "FOUND confirms a fixture annotation only, not a real-world object.",
            ]
        else:
            limitations = [
                "Navigation is simulated; images are recorded photographs, never real_robot observations.",
                "FOUND is a geometric reference-appearance match in a recorded image, not live presence or category recognition.",
                "Similar copies, low texture, severe occlusion, lighting and viewpoint changes can defeat this matcher.",
                "No reliable match is UNKNOWN/SUSPECTED, not evidence that an object is absent.",
                "declared_capture timestamps are supplied by the operator, not authenticated camera metadata.",
                "demo_sequence timestamps order a replay only; original photo capture dates may be unknown.",
                "SHA256 blocks byte-identical replay, but cannot prove capture time or detect every edited copy.",
                "Reference-image enrollment is not independent confirmation; search must use different image content.",
            ]
        limitations.extend([
            "History guides planning but cannot confirm the current location.",
            "visited_viewpoints is a legacy alias for attempted_viewpoints, including failed navigation.",
            "No physical robot, ROS, cloud API or learned visual model is integrated.",
        ])
        return SearchReport(
            task_id=task_id,
            object_id=state.object_id,
            result_status=state.result_status,
            location=state.location,
            evidence_ids=[r.observation.evidence_id for r in state.evidence],
            visited_viewpoints=list(state.visited_viewpoints),
            evidence=list(state.evidence),
            events=list(state.events),
            limitations=limitations,
            navigation_mode=self.navigation_mode,
            data_source=self.data_source,
            schema_version=2,
            attempted_viewpoints=list(state.visited_viewpoints),
            arrived_viewpoints=list(state.arrived_viewpoints),
            observed_viewpoints=list(state.observed_viewpoints),
            historical_evidence=list(state.history),
            confirmed_evidence_ids=[r.observation.evidence_id for r in state.evidence if r.detection.status == Status.FOUND],
            operation=self.operation,
            strategy=self.strategy,
        )
