"""Deterministic search decisions using memory and observations already acquired."""

from dataclasses import asdict
from datetime import datetime
from uuid import uuid4

from .environment import EnvironmentAdapter
from .memory import MemoryStore
from .perception import Detector
from .models import (
    DetectionResult,
    MemoryRecord,
    PlanDecision,
    SearchReport,
    Status,
    TaskEvent,
    TaskState,
)


class SearchCore:
    def __init__(
        self, memory: MemoryStore, environment: EnvironmentAdapter, detector: Detector
    ):
        self.memory = memory
        self.environment = environment
        self.detector = detector
        self._state: TaskState | None = None

    def plan_next(self, task_state: TaskState) -> PlanDecision | None:
        # This method sees only public viewpoint metadata and acquired memory.
        # It never reads observations/annotations from the fixture adapter.
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

    @staticmethod
    def _event(
        state: TaskState, action: str, input_ids: list[str], result: dict
    ) -> None:
        state.events.append(
            TaskEvent(
                seq=len(state.events) + 1,
                action=action,
                input_ids=input_ids,
                result=result,
                provenance={"adapter_kind": "mock", "simulated": True, "data_source": "fixture"},
            )
        )

    def run(self, object_id: str, task_id: str | None = None) -> SearchReport:
        if self.memory.get_object(object_id) is None:
            raise ValueError(f"Unregistered object: {object_id}")
        state = TaskState(task_id or str(uuid4()), object_id)
        self._state = state
        history = self.memory.query_memory(object_id)
        seen_ids = {record.observation.evidence_id for record in history}
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
                or navigation.adapter_kind != "mock"
                or navigation.simulated is not True
            ):
                self._event(state, "view_result", [view_id], {"status": Status.UNREACHABLE})
                continue
            observation = self.environment.observe(view_id)
            self._event(
                state, "observe", [view_id],
                {"observation": asdict(observation) if observation else None},
            )
            if observation is None:
                self._event(state, "view_result", [view_id], {"status": Status.UNKNOWN, "reason": "no_observation"})
                continue
            rejection = None
            if observation.viewpoint_id != view_id:
                rejection = "wrong_viewpoint"
            elif (
                observation.data_source != "fixture"
                or observation.image_path is not None
                or observation.image_hash is not None
            ):
                rejection = "unsupported_evidence_source"
            elif observation.evidence_id in seen_ids:
                rejection = "replayed_evidence"
            elif history and datetime.fromisoformat(observation.captured_at) <= max(
                datetime.fromisoformat(record.observation.captured_at) for record in history
            ):
                rejection = "observation_not_newer_than_memory"
            if rejection:
                self._event(
                    state, "view_result", [view_id, observation.evidence_id],
                    {"status": Status.UNKNOWN, "reason": rejection},
                )
                continue
            seen_ids.add(observation.evidence_id)
            detection = self.detector.detect_target(observation, object_id)
            if (
                detection.target_id != object_id
                or detection.evidence_id != observation.evidence_id
                or observation.visibility_status != "clear"
                or detection.status == Status.UNREACHABLE
            ):
                detection = DetectionResult(object_id, observation.evidence_id, Status.UNKNOWN)
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
        return SearchReport(
            task_id=task_id,
            object_id=state.object_id,
            result_status=state.result_status,
            location=state.location,
            evidence_ids=[r.observation.evidence_id for r in state.evidence],
            visited_viewpoints=list(state.visited_viewpoints),
            evidence=list(state.evidence),
            events=list(state.events),
            limitations=[
                "Mock navigation only; no physical robot was run.",
                "All observations, annotations and timestamps are synthetic fixtures; no images were captured or analyzed.",
                "FOUND confirms a fixture annotation only, not a real-world object.",
                "History guides planning but cannot confirm the current location.",
                "A negative view is not proof of global absence; unconfirmed search ends UNKNOWN or SUSPECTED.",
                "No visual model, robot SDK, ROS, SLAM or cloud API is integrated.",
            ],
        )
