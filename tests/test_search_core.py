from dataclasses import replace
from importlib.resources import files

import pytest

from hometrace.environment import MockAdapter
from hometrace.fixtures import load_fixture
from hometrace.memory import SQLiteMemory
from hometrace.models import DetectionResult, Status, TaskState
from hometrace.perception import FixtureDetector
from hometrace.search_core import SearchCore


@pytest.fixture
def memory():
    with SQLiteMemory() as store:
        yield store


def make_core(memory, scenario_name="moved"):
    scenario = load_fixture(files("hometrace").joinpath("fixture_data", f"{scenario_name}.json"))
    obj = scenario.object
    memory.register_object(obj.object_id, obj.sample_image_path, obj.description)
    for record in scenario.memory_records:
        memory.update_memory(record.observation, record.detection)
    return (
        SearchCore(
            memory,
            MockAdapter(scenario.viewpoints, scenario.observations, scenario.unreachable_viewpoints),
            FixtureDetector(scenario.detections),
        ),
        scenario,
    )


def test_moved_target_replans_after_negative_observation(memory):
    core, scenario = make_core(memory)
    report = core.run(scenario.object.object_id, "test-moved")
    assert report.result_status == Status.FOUND
    assert report.location == "B"
    assert report.visited_viewpoints == ["A", "B"]
    plans = [e for e in report.events if e.action == "plan_next"]
    assert plans[0].result["reason"] == "latest_memory_found"
    assert plans[1].result["reason"] == "unvisited_fallback"
    updates = [e for e in report.events if e.action == "update_memory"]
    assert updates[0].result["status"] == Status.NOT_FOUND_IN_VIEW
    assert updates[0].seq < plans[1].seq
    assert report.evidence[-1].detection.status == Status.FOUND
    assert report.evidence[-1].observation.viewpoint_id == report.location
    assert len(memory.query_memory(scenario.object.object_id)) == 3
    assert all(e.provenance["data_source"] == "fixture" for e in report.events)
    assert [e.seq for e in report.events] == list(range(1, len(report.events) + 1))


def test_missing_target_cannot_reuse_historical_found(memory):
    core, scenario = make_core(memory, "missing")
    report = core.run(scenario.object.object_id)
    assert report.result_status == Status.UNKNOWN
    assert report.location is None
    assert report.visited_viewpoints == ["A", "B", "C"]
    assert all(r.detection.status != Status.FOUND for r in report.evidence)
    assert any(r.detection.status == Status.UNKNOWN for r in report.evidence)
    assert any(r.detection.status == Status.NOT_FOUND_IN_VIEW for r in report.evidence)
    assert scenario.memory_records[0].observation.evidence_id not in report.evidence_ids


def test_planner_uses_memory_not_future_truth(memory):
    core, scenario = make_core(memory)
    # This adapter deliberately offers no way to inspect observations.
    class MetadataOnlyEnvironment:
        def list_viewpoints(self):
            return list(reversed(scenario.viewpoints))

        def observe(self, view_id):
            raise AssertionError("Planner must not observe ahead of navigation")

        def navigate_to(self, view_id):
            raise AssertionError("Planning must not navigate")

    core.environment = MetadataOnlyEnvironment()
    state = TaskState("plan-test", scenario.object.object_id)
    assert core.plan_next(state).viewpoint_id == "A"
    state.visited_viewpoints.append("A")
    assert core.plan_next(state).viewpoint_id == "B"


def test_latest_negative_memory_invalidates_old_positive(memory):
    core, scenario = make_core(memory)
    observation = scenario.observations["A"]
    memory.update_memory(observation, scenario.detections[observation.evidence_id])
    decision = core.plan_next(TaskState("plan-test", scenario.object.object_id))
    assert decision.viewpoint_id == "B"


def test_recent_memory_changes_first_choice_from_default_order(memory):
    core, scenario = make_core(memory)
    observed = replace(
        scenario.observations["C"],
        evidence_id="new-history-C",
        captured_at="2026-10-01T18:00:00+08:00",
    )
    memory.update_memory(
        observed,
        DetectionResult(scenario.object.object_id, observed.evidence_id, Status.FOUND),
    )
    assert core.plan_next(TaskState("plan-test", scenario.object.object_id)).viewpoint_id == "C"


def test_unreachable_views_do_not_produce_observations(memory):
    core, scenario = make_core(memory)
    core.environment = MockAdapter(scenario.viewpoints, scenario.observations, {"A", "B", "C"})
    report = core.run(scenario.object.object_id)
    assert report.result_status == Status.UNKNOWN
    assert not report.evidence_ids
    assert not [e for e in report.events if e.action == "observe"]
    assert [e.result["status"] for e in report.events if e.action == "view_result"] == [Status.UNREACHABLE] * 3


@pytest.mark.parametrize("case", ["historical_id", "wrong_target", "wrong_evidence", "occluded", "no_observation"])
def test_untrusted_positive_cannot_become_found(memory, case):
    core, scenario = make_core(memory)
    observation = scenario.observations["B"]
    if case == "historical_id":
        observation = replace(observation, evidence_id=scenario.memory_records[0].observation.evidence_id)
    elif case == "occluded":
        observation = replace(observation, visibility_status="occluded")

    class FaultyEnvironment:
        def list_viewpoints(self):
            return [v for v in scenario.viewpoints if v.viewpoint_id == "B"]

        def navigate_to(self, view_id):
            from hometrace.models import NavigationResult
            return NavigationResult(view_id, "ARRIVED")

        def observe(self, view_id):
            return None if case == "no_observation" else observation

    class FaultyDetector:
        def detect_target(self, obs, object_id):
            return DetectionResult(
                "different-object" if case == "wrong_target" else object_id,
                "different-evidence" if case == "wrong_evidence" else obs.evidence_id,
                Status.FOUND,
            )

    core.environment, core.detector = FaultyEnvironment(), FaultyDetector()
    report = core.run(scenario.object.object_id)
    assert report.result_status == Status.UNKNOWN
    assert report.location is None
    assert not any(r.detection.status == Status.FOUND for r in report.evidence)


def test_suspected_annotation_is_not_promoted_to_found(memory):
    core, scenario = make_core(memory)
    detections = dict(scenario.detections)
    evidence_id = scenario.observations["B"].evidence_id
    detections[evidence_id] = replace(detections[evidence_id], status=Status.SUSPECTED)
    core.detector = FixtureDetector(detections)
    report = core.run(scenario.object.object_id)
    assert report.result_status == Status.SUSPECTED
    assert report.location is None
    assert report.visited_viewpoints == ["A", "B", "C"]


def test_unregistered_target_fails_before_navigation(memory):
    core, _ = make_core(memory)
    with pytest.raises(ValueError, match="Unregistered"):
        core.run("another-target")
