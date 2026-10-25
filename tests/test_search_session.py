"""Incremental controller checks; fixture tests are not model/API evidence."""

from dataclasses import replace
from importlib.resources import files
import json

import pytest

from hometrace.environment import MockAdapter
from hometrace.fixtures import load_fixture
from hometrace.memory import SQLiteMemory
from hometrace.models import DataSource, DetectionResult, NavigationMode, NavigationResult, Observation, SearchStrategy, Status, TimestampBasis, Viewpoint
from hometrace.perception import FixtureDetector
from hometrace.search_core import SearchCore


def make_core(memory, scenario_name="moved", strategy=SearchStrategy.MEMORY_FIRST):
    scenario = load_fixture(files("hometrace").joinpath("fixture_data", f"{scenario_name}.json"))
    obj = scenario.object
    memory.register_object(obj.object_id, obj.sample_image_path, obj.description)
    for record in scenario.memory_records:
        memory.update_memory(record.observation, record.detection)
    core = SearchCore(memory, MockAdapter(scenario.viewpoints, scenario.observations, scenario.unreachable_viewpoints),
                      FixtureDetector(scenario.detections), strategy=strategy)
    return core, scenario


@pytest.mark.parametrize("scenario_name", ["moved", "missing"])
@pytest.mark.parametrize("strategy", list(SearchStrategy))
def test_steps_and_original_controller_have_identical_events_and_memory(scenario_name, strategy):
    with SQLiteMemory() as automatic_memory, SQLiteMemory() as step_memory:
        automatic, scenario = make_core(automatic_memory, scenario_name, strategy)
        stepped, _ = make_core(step_memory, scenario_name, strategy)
        expected = automatic.run(scenario.object.object_id, "same-task")
        stepped.start_search(scenario.object.object_id, "same-task")
        while stepped.state.result_status != Status.FOUND and (decision := stepped.plan_next(stepped.state)):
            stepped.navigate_viewpoint(decision.viewpoint_id, decision.reason, score=decision.score)
            if stepped.current_phase == "arrived":
                stepped.observe_current()
            if stepped.current_phase == "observed":
                stepped.verify_current()
        actual = stepped.finish_search()
        assert actual.to_dict() == expected.to_dict()
        assert step_memory.query_memory(scenario.object.object_id) == automatic_memory.query_memory(scenario.object.object_id)
        assert actual.events[1].result["score"] == (100 if strategy == SearchStrategy.MEMORY_FIRST else 0)


def test_start_only_reads_history_and_returns_isolated_state():
    with SQLiteMemory() as memory:
        core, scenario = make_core(memory)
        state = core.start_search(scenario.object.object_id, "task")
        assert core.current_phase == "ready"
        assert [event.action for event in state.events] == ["query_memory"]
        assert not state.visited_viewpoints and not state.evidence
        state.result_status, state.location = Status.FOUND, "invented-by-controller"
        state.history.clear()
        snapshot = core.state
        snapshot.events.clear()
        assert core.state.result_status == Status.UNKNOWN
        assert core.state.location is None and core.state.history and core.state.events
        with pytest.raises(ValueError, match="already active"):
            core.start_search(scenario.object.object_id)
        with pytest.raises(ValueError, match="already active"):
            core.run(scenario.object.object_id)


def test_operations_require_the_legal_phase_without_side_effects():
    with SQLiteMemory() as memory:
        core, scenario = make_core(memory)
        assert core.current_phase == "idle" and core.state is None
        for operation in (lambda: core.navigate_viewpoint("A"), core.observe_current, core.verify_current, core.finish_search):
            with pytest.raises(ValueError):
                operation()
        core.start_search(scenario.object.object_id)
        for operation in (core.observe_current, core.verify_current):
            with pytest.raises(ValueError, match="requires phase"):
                operation()
        core.navigate_viewpoint("A")
        for operation in (lambda: core.navigate_viewpoint("B"), core.verify_current):
            with pytest.raises(ValueError, match="requires phase"):
                operation()
        core.observe_current()
        for operation in (lambda: core.navigate_viewpoint("B"), core.observe_current):
            with pytest.raises(ValueError, match="requires phase"):
                operation()
        core.verify_current()
        before = core.state
        with pytest.raises(ValueError, match="requires phase"):
            core.verify_current()
        assert core.state == before
        core.finish_search()
        for operation in (lambda: core.navigate_viewpoint("B"), core.observe_current, core.verify_current):
            with pytest.raises(ValueError, match="requires phase"):
                operation()


def test_unknown_and_repeated_viewpoints_cannot_create_events_or_evidence():
    with SQLiteMemory() as memory:
        core, scenario = make_core(memory)
        core.start_search(scenario.object.object_id)
        before = core.state
        for bad_view in ("invented", None, ["A"]):
            with pytest.raises(ValueError, match="Unknown viewpoint"):
                core.navigate_viewpoint(bad_view)
        assert core.state == before
        core.navigate_viewpoint("A")
        core.observe_current()
        core.verify_current()
        before = core.state
        with pytest.raises(ValueError, match="already attempted"):
            core.navigate_viewpoint("A")
        assert core.state == before


def test_found_can_only_be_finished_and_finish_is_idempotent():
    with SQLiteMemory() as memory:
        core, scenario = make_core(memory)
        core.start_search(scenario.object.object_id, "first")
        core.navigate_viewpoint("B")
        core.observe_current()
        result = core.verify_current()
        assert result["status"] == Status.FOUND and result["location"] == "B"
        for operation in (lambda: core.navigate_viewpoint("C"), core.observe_current, core.verify_current):
            with pytest.raises(ValueError):
                operation()
        first = core.finish_search()
        assert core.finish_search() == first
        assert sum(e.action == "complete" for e in first.events) == 1
        core.start_search(scenario.object.object_id, "second")
        assert core.state.task_id == "second" and not core.state.evidence
        assert core.state.result_status == Status.UNKNOWN and core.state.location is None
        core.navigate_viewpoint("B")
        assert core.observe_current()["reason"] == "replayed_evidence"
        assert core.current_phase == "ready"


@pytest.mark.parametrize("observe", [False, True])
def test_finish_pending_work_marks_incomplete_and_never_calls_detector(observe):
    with SQLiteMemory() as memory:
        core, scenario = make_core(memory)
        before = memory.query_memory(scenario.object.object_id)

        class NeverDetect:
            def detect_target(self, *_):
                raise AssertionError("Ending a task must not execute pending vision")

        core.detector = NeverDetect()
        core.start_search(scenario.object.object_id)
        core.navigate_viewpoint("B")
        if observe:
            core.observe_current()
        report = core.finish_search()
        assert report.result_status == Status.UNKNOWN and report.location is None
        assert not report.evidence and not report.observed_viewpoints
        assert report.events[-2].result == {"status": Status.UNKNOWN, "reason": "incomplete_viewpoint"}
        assert memory.query_memory(scenario.object.object_id) == before


@pytest.mark.parametrize("fault", ["unreachable", "missing", "replayed_evidence", "old_timestamp"])
def test_failed_navigation_and_rejected_observations_return_to_ready(fault):
    with SQLiteMemory() as memory:
        core, scenario = make_core(memory)
        observations = dict(scenario.observations)
        if fault == "missing":
            observations.pop("A")
        elif fault == "replayed_evidence":
            observations["A"] = replace(observations["A"], evidence_id=scenario.memory_records[0].observation.evidence_id)
        elif fault == "old_timestamp":
            observations["A"] = replace(observations["A"], captured_at=scenario.memory_records[0].observation.captured_at)
        core.environment = MockAdapter(scenario.viewpoints, observations, {"A"} if fault == "unreachable" else set())
        core.start_search(scenario.object.object_id)
        core.navigate_viewpoint("A")
        if core.current_phase == "arrived":
            core.observe_current()
        assert core.current_phase == "ready"
        assert not core.state.evidence
        core.navigate_viewpoint("B")
        core.observe_current()
        assert core.verify_current()["status"] == Status.FOUND


def test_nonchronological_agent_choice_does_not_relax_watermark():
    with SQLiteMemory() as memory:
        core, scenario = make_core(memory)
        core.start_search(scenario.object.object_id)
        core.navigate_viewpoint("C")
        core.observe_current()
        core.verify_current()
        core.navigate_viewpoint("B")
        rejected = core.observe_current()
        assert rejected["status"] == Status.UNKNOWN
        assert rejected["reason"] == "observation_not_newer_than_memory"
        assert core.current_phase == "ready"
        assert core.finish_search().result_status != Status.FOUND


def test_step_summaries_do_not_export_private_paths_hashes_or_arbitrary_diagnostics():
    private_path, private_hash = "private/home/photo.jpg", "a" * 64

    class Environment:
        def list_viewpoints(self):
            return [Viewpoint("B", "View B")]

        def navigate_to(self, view_id):
            return NavigationResult(view_id, "ARRIVED", "recorded_image", True, NavigationMode.SIMULATED)

        def observe(self, view_id):
            return Observation("evidence", view_id, "2026-10-24T12:00:00+08:00", DataSource.RECORDED_IMAGE,
                               image_path=private_path, image_hash=private_hash, capture_source="private text",
                               timestamp_basis=TimestampBasis.DEMO_SEQUENCE)

    class Detector:
        def detect_target(self, observation, object_id):
            return DetectionResult(object_id, observation.evidence_id, Status.FOUND, matcher="opencv_orb_homography",
                                   data_source=DataSource.RECORDED_IMAGE, verification_kind="reference_instance_match",
                                   bbox=[1, 2, 20, 30], diagnostics={"image_decoded": True, "good_matches": 12,
                                   "inliers": 10, "reason": "reference_appearance_matched", "image_path": private_path,
                                   "image_hash": private_hash, "other": {"secret": "private text"}})

    with SQLiteMemory() as memory:
        memory.register_object("target", "private/reference.jpg", "object", "b" * 64, DataSource.RECORDED_IMAGE)
        core = SearchCore(memory, Environment(), Detector(), data_source=DataSource.RECORDED_IMAGE,
                          navigation_mode=NavigationMode.SIMULATED)
        core.start_search("target")
        navigation = core.navigate_viewpoint("B")
        observation = core.observe_current()
        detection = core.verify_current()
        payload = json.dumps([navigation, observation, detection])
        assert private_path not in payload and private_hash not in payload and "private text" not in payload
        assert detection["bbox"] == [1, 2, 20, 30]
        assert detection["diagnostics"]["inliers"] == 10
        detection["bbox"][0] = 999
        assert core.finish_search().evidence[0].detection.bbox == [1, 2, 20, 30]
