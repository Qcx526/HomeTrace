"""Deterministic search decisions using memory and observations already acquired."""

from copy import deepcopy
from dataclasses import asdict, replace
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
            (DataSource.SYNTHETIC_IMAGE, NavigationMode.SIMULATED),
            (DataSource.USER_IMAGE, NavigationMode.SIMULATED),
        ):
            raise ValueError("Unsupported evidence/navigation combination")
        if operation not in ("search", "register"):
            raise ValueError("Unsupported operation")
        self.operation = operation
        self.strategy = SearchStrategy(strategy)
        self.adapter_kind = "mock" if self.data_source == DataSource.FIXTURE else self.data_source.value
        self._candidate_images = self.data_source in (DataSource.SYNTHETIC_IMAGE, DataSource.USER_IMAGE)
        self._state: TaskState | None = None
        self._phase = "idle"
        self._current_viewpoint: str | None = None
        self._observation = None

    @property
    def current_phase(self) -> str:
        return self._phase

    @property
    def state(self) -> TaskState | None:
        """A snapshot for controllers; mutation cannot change trusted state."""
        return deepcopy(self._state)

    def _require_phase(self, phase: str) -> TaskState:
        if self._state is None or self._phase != phase:
            raise ValueError(f"Search operation requires phase {phase}; current phase is {self._phase}")
        if self._state.result_status == Status.FOUND:
            raise ValueError("Search already confirmed a finding; finish the search")
        return self._state

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

    def start_search(self, object_id: str, task_id: str | None = None) -> TaskState:
        """Initialize one session without navigating or reading future images."""
        if self._phase not in ("idle", "finished"):
            raise ValueError("A search session is already active; finish it before starting another")
        registered = self.memory.get_object(object_id)
        if registered is None:
            raise ValueError(f"Unregistered object: {object_id}")
        if registered.data_source != self.data_source:
            raise ValueError("Registered object and search evidence sources differ")
        state = TaskState(task_id or str(uuid4()), object_id)
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
        self._state = state
        self._seen_ids, self._seen_hashes = seen_ids, seen_hashes
        self._bases, self._latest_time = bases, latest_time
        self._current_viewpoint, self._observation = None, None
        self._phase = "ready"
        self._event(
            state, "query_memory", [object_id],
            {"records": [asdict(record) for record in history], "historical_only": True},
        )
        return self.state

    def navigate_viewpoint(self, viewpoint_id: str, reason: str = "agent_tool_choice", *, score: int = 0) -> dict:
        """Attempt one legal viewpoint; reason/score describe a plan, never facts."""
        state = self._require_phase("ready")
        known = {view.viewpoint_id for view in self.environment.list_viewpoints()}
        if not isinstance(viewpoint_id, str) or viewpoint_id not in known:
            raise ValueError("Unknown viewpoint")
        if viewpoint_id in state.visited_viewpoints:
            raise ValueError("Viewpoint was already attempted in this search")
        if not isinstance(reason, str) or not reason.strip() or len(reason) > 500 or type(score) is not int:
            raise ValueError("Invalid plan metadata")
        self._current_viewpoint, self._observation = viewpoint_id, None
        self._event(state, "plan_next", [state.object_id], asdict(PlanDecision(viewpoint_id, reason, score)))
        state.visited_viewpoints.append(viewpoint_id)
        navigation = self.environment.navigate_to(viewpoint_id)
        self._event(state, "navigate", [viewpoint_id], asdict(navigation))
        if (
            navigation.status != "ARRIVED"
            or navigation.viewpoint_id != viewpoint_id
            or navigation.adapter_kind != self.adapter_kind
            or navigation.simulated is not True
            or navigation.navigation_mode != self.navigation_mode
        ):
            self._event(state, "view_result", [viewpoint_id], {"status": Status.UNREACHABLE})
            return {"viewpoint_id": viewpoint_id, "status": Status.UNREACHABLE,
                    "phase": self._phase, "navigation_mode": self.navigation_mode, "simulated": True}
        state.arrived_viewpoints.append(viewpoint_id)
        self._phase = "arrived"
        return {"viewpoint_id": viewpoint_id, "status": "ARRIVED",
                "phase": self._phase, "navigation_mode": self.navigation_mode, "simulated": True}

    def observe_current(self) -> dict:
        """Acquire one observation and apply the shared provenance/replay guards."""
        state = self._require_phase("arrived")
        view_id = self._current_viewpoint
        observation = self.environment.observe(view_id)
        self._event(
            state, "observe", [view_id],
            {"observation": asdict(observation) if observation else None},
        )
        if observation is None:
            self._event(state, "view_result", [view_id], {"status": Status.UNKNOWN, "reason": "no_observation"})
            self._phase = "ready"
            return {"viewpoint_id": view_id, "status": Status.UNKNOWN, "reason": "no_observation", "phase": self._phase}
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
        elif source in (DataSource.RECORDED_IMAGE, DataSource.SYNTHETIC_IMAGE, DataSource.USER_IMAGE) and (
            not observation.image_path or not observation.capture_source
            or basis not in (TimestampBasis.DECLARED_CAPTURE, TimestampBasis.DEMO_SEQUENCE)
            or (not observation.error and not re.fullmatch(r"[0-9a-f]{64}", observation.image_hash or ""))
        ):
            rejection = "incomplete_image_provenance"
        elif source == DataSource.SYNTHETIC_IMAGE and basis != TimestampBasis.DEMO_SEQUENCE:
            rejection = "synthetic_image_requires_demo_sequence"
        elif self._bases and basis not in self._bases:
            rejection = "timestamp_basis_changed"
        elif observation.evidence_id in self._seen_ids:
            rejection = "replayed_evidence"
        elif observation.image_hash and observation.image_hash in self._seen_hashes:
            rejection = "replayed_image_content"
        elif self._latest_time is not None and observed_time <= self._latest_time:
            rejection = "observation_not_newer_than_memory"
        if rejection:
            self._event(
                state, "view_result", [view_id, observation.evidence_id],
                {"status": Status.UNKNOWN, "reason": rejection},
            )
            self._phase = "ready"
            return {"viewpoint_id": view_id, "evidence_id": observation.evidence_id,
                    "status": Status.UNKNOWN, "reason": rejection, "phase": self._phase}
        self._seen_ids.add(observation.evidence_id)
        if observation.image_hash:
            self._seen_hashes.add(observation.image_hash)
        self._bases.add(basis)
        self._latest_time = observed_time
        self._observation = observation
        self._phase = "observed"
        # Paths, hashes, capture-source text and image bytes stay in local evidence.
        return {"viewpoint_id": view_id, "evidence_id": observation.evidence_id,
                "status": "PENDING_VERIFICATION", "data_source": self.data_source,
                "phase": self._phase}

    def verify_current(self) -> dict:
        """Run the detector and the single authoritative FOUND/memory-write path."""
        state = self._require_phase("observed")
        view_id, observation, object_id = self._current_viewpoint, self._observation, state.object_id
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
            or (self._candidate_images and (
                detection.data_source != self.data_source
                or not detection.matcher or detection.matcher == "fixture_annotation"
                or detection.verification_kind != "appearance_candidate"
                or detection.status == Status.NOT_FOUND_IN_VIEW
                or (detection.score is not None and (
                    type(detection.score) not in (int, float) or not math.isfinite(detection.score)
                ))
                or (detection.bbox is not None and (
                    not self._valid_candidate_bbox(detection.bbox)
                    or detection.diagnostics.get("image_decoded") is not True
                ))
                or (detection.status in (Status.FOUND, Status.SUSPECTED) and (
                    detection.diagnostics.get("image_decoded") is not True
                    or not self._valid_candidate_bbox(detection.bbox)
                ))
            ))
        ):
            detection = DetectionResult(
                object_id, observation.evidence_id, Status.UNKNOWN,
                matcher=detection.matcher, data_source=self.data_source,
                verification_kind=detection.verification_kind,
                diagnostics={**detection.diagnostics, "rejection": observation.error or "unusable_detection"},
            )
        elif self._candidate_images and detection.status == Status.FOUND:
            # A model/appearance candidate cannot assert physical instance identity.
            # Keep the actual candidate evidence, but never enter the FOUND path.
            detection = replace(detection, status=Status.SUSPECTED, diagnostics={
                **detection.diagnostics, "detector_status": Status.FOUND.value,
                "automatic_confirmation_blocked": True,
                "rejection": "appearance_candidate_cannot_confirm_identity",
            })
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
        elif detection.status == Status.SUSPECTED:
            state.result_status = Status.SUSPECTED
        self._phase, self._observation = "ready", None
        diagnostics = {}
        for key in ("good_matches", "inliers", "inlier_ratio", "reference_coverage", "elapsed_ms", "image_decoded"):
            value = detection.diagnostics.get(key)
            if isinstance(value, (int, float)) and math.isfinite(value):
                diagnostics[key] = value
        for key in ("reason", "rejection"):
            value = detection.diagnostics.get(key)
            if isinstance(value, str) and re.fullmatch(r"[a-z][a-z0-9_]{0,100}", value):
                diagnostics[key] = value
        result = {"object_id": object_id, "viewpoint_id": view_id, "evidence_id": observation.evidence_id,
                "status": detection.status, "result_status": state.result_status, "location": state.location,
                "bbox": deepcopy(detection.bbox) if detection.status == Status.FOUND else None,
                "diagnostics": diagnostics, "memory_inserted": inserted, "phase": self._phase}
        if self._candidate_images:
            result["candidate_bbox"] = deepcopy(detection.bbox)
            result["identity_confirmed"] = False
        return result

    @staticmethod
    def _valid_candidate_bbox(bbox) -> bool:
        return (isinstance(bbox, (list, tuple)) and len(bbox) == 4
                and all(type(value) in (int, float) and math.isfinite(value) for value in bbox)
                and 0 <= bbox[0] < bbox[2] and 0 <= bbox[1] < bbox[3])

    def finish_search(self) -> SearchReport:
        """End explicitly, without silently observing or verifying pending work."""
        state = self._state
        if state is None or self._phase == "idle":
            raise ValueError("No active search session")
        if self._phase == "finished":
            return self.build_report(state.task_id)
        if self._phase in ("arrived", "observed"):
            self._event(state, "view_result", [self._current_viewpoint],
                        {"status": Status.UNKNOWN, "reason": "incomplete_viewpoint"})
        self._phase, self._observation = "finished", None
        self._event(
            state, "complete", [state.object_id],
            {"result_status": state.result_status, "location": state.location},
        )
        return self.build_report(state.task_id)

    def run(self, object_id: str, task_id: str | None = None) -> SearchReport:
        """The original deterministic controller over the same trusted session."""
        self.start_search(object_id, task_id)
        while self._state.result_status != Status.FOUND and (decision := self.plan_next(self._state)):
            self.navigate_viewpoint(decision.viewpoint_id, decision.reason, score=decision.score)
            if self._phase == "arrived":
                self.observe_current()
            if self._phase == "observed":
                self.verify_current()
        return self.finish_search()

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
        elif self.data_source == DataSource.RECORDED_IMAGE:
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
        else:
            origin = ("Inputs are AI-generated or otherwise synthetic images, not real household photographs."
                      if self.data_source == DataSource.SYNTHETIC_IMAGE else
                      "Inputs are user-supplied images; their physical origin and capture time are not authenticated.")
            limitations = [
                "Navigation is simulated; no physical robot or live camera was run.",
                origin,
                "Appearance candidates and model scores cannot establish physical instance identity or automatic FOUND.",
                "User confirmation is recorded separately and does not replace the automatic visual conclusion.",
                "UNKNOWN/SUSPECTED does not establish that the object is absent.",
                "demo_sequence timestamps order processing only, not authenticated photo capture.",
                "SHA256 blocks byte-identical reference/previous-evidence replay, not every edited copy.",
                "Synthetic-image results are software demonstrations, not independent real-household validation.",
            ]
        limitations.extend([
            "History guides planning but cannot confirm the current location.",
            "visited_viewpoints is a legacy alias for attempted_viewpoints, including failed navigation.",
            "The Search Core itself does not call cloud APIs; navigation remains simulated with no physical robot or ROS integration.",
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
