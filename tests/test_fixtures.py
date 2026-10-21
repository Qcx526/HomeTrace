import json
from dataclasses import replace
from importlib.resources import files

import pytest

from hometrace.environment import MockAdapter
from hometrace.fixtures import load_fixture
from hometrace.models import DetectionResult, Observation, Status, Viewpoint
from hometrace.perception import FixtureDetector


def fixture_path(name="moved"):
    return files("hometrace").joinpath("fixture_data", f"{name}.json")


@pytest.mark.parametrize("name", ["moved", "missing"])
def test_bundled_fixtures_have_distinct_synthetic_history_and_current_evidence(name):
    scenario = load_fixture(fixture_path(name))
    assert scenario.object.object_id == "remote-control"
    assert len(scenario.viewpoints) == 3
    historic_ids = {record.observation.evidence_id for record in scenario.memory_records}
    current_ids = {observation.evidence_id for observation in scenario.observations.values()}
    assert historic_ids.isdisjoint(current_ids)
    assert all(observation.data_source == "fixture" for observation in scenario.observations.values())
    assert all(observation.image_path is None for observation in scenario.observations.values())


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda d: d.update(data_source="recorded_image"), "data_source"),
        (lambda d: d["navigation"].update(simulated=False), "simulated"),
        (lambda d: d["navigation"].update(adapter_kind="real_robot"), "navigation"),
        (lambda d: d["navigation"].update(unreachable_viewpoints=["D"]), "known viewpoint"),
        (lambda d: d["object"].update(sample_image_path="photo.jpg"), "sample_image_path"),
        (lambda d: d["viewpoints"].append(d["viewpoints"][0]), "duplicate viewpoint"),
        (lambda d: d["observations"][0].update(viewpoint_id="D"), "unknown viewpoint"),
        (lambda d: d["observations"][0].update(evidence_id="moved-history-A"), "duplicate evidence"),
        (lambda d: d["observations"][0].update(captured_at="2026-10-02T09:00:00"), "timezone"),
        (lambda d: d["observations"][0].update(captured_at="not-a-date"), "ISO timestamp"),
        (lambda d: d["observations"][0].update(image_path="photo.jpg"), "image paths"),
        (lambda d: d["observations"][0].update(image_hash="abc"), "image paths"),
        (lambda d: d["observations"][0].update(data_source="real_robot"), "data_source"),
        (lambda d: d["observations"][0].update(visibility_status="invisible"), "visibility_status"),
        (lambda d: d["observations"][1].update(visibility_status="occluded"), "UNKNOWN"),
        (lambda d: d["detections"][0].update(target_id="wrong-object"), "target_id"),
        (lambda d: d["detections"][0].update(evidence_id="missing-evidence"), "matching observation"),
        (lambda d: d["detections"][0].update(matcher="visual_model"), "matcher"),
        (lambda d: d["detections"][0].update(status="UNREACHABLE"), "navigation result"),
        (lambda d: d["detections"][0].update(score=1.01), "score"),
        (lambda d: d.update(robot_position=[0, 0]), "unknown fields"),
    ],
)
def test_loader_rejects_invalid_or_misleading_fixture_data(tmp_path, mutate, message):
    data = json.loads(fixture_path().read_text(encoding="utf-8"))
    mutate(data)
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        load_fixture(path)


def test_fixture_with_no_annotation_stays_unknown(tmp_path):
    data = json.loads(fixture_path().read_text(encoding="utf-8"))
    data["detections"] = []
    path = tmp_path / "unannotated.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    scenario = load_fixture(path)
    result = FixtureDetector(scenario.detections).detect_target(scenario.observations["B"], "remote-control")
    assert result.status == Status.UNKNOWN


def test_mock_requires_simulated_arrival_before_observation():
    scenario = load_fixture(fixture_path())
    adapter = MockAdapter(scenario.viewpoints, scenario.observations, {"C"})
    assert adapter.observe("A") is None
    arrived = adapter.navigate_to("A")
    assert (arrived.status, arrived.adapter_kind, arrived.simulated) == ("ARRIVED", "mock", True)
    assert adapter.observe("A") == scenario.observations["A"]
    assert adapter.observe("B") is None
    blocked = adapter.navigate_to("C")
    assert (blocked.status, blocked.adapter_kind, blocked.simulated) == ("UNREACHABLE", "mock", True)
    assert adapter.observe("C") is None
    assert adapter.observe("A") is None
    assert adapter.navigate_to("no-such-point").status == "UNREACHABLE"


@pytest.mark.parametrize(
    "change",
    [{"data_source": "recorded_image"}, {"data_source": "real_robot"}, {"image_path": "photo.jpg"}],
)
def test_mock_cannot_accept_nonfixture_observations(change):
    observed = replace(Observation("evidence", "A", "2026-10-01T09:00:00+08:00"), **change)
    with pytest.raises(ValueError, match="synthetic fixtures"):
        MockAdapter([Viewpoint("A", "Test point")], {"A": observed})


@pytest.mark.parametrize(
    "status", [Status.FOUND, Status.SUSPECTED, Status.NOT_FOUND_IN_VIEW, Status.UNKNOWN]
)
def test_detector_preserves_annotation_status_without_upgrading_suspected(status):
    observation = Observation("evidence", "A", "2026-10-01T09:00:00+08:00")
    detection = DetectionResult("target", "evidence", status)
    assert FixtureDetector({"evidence": detection}).detect_target(observation, "target") == detection


@pytest.mark.parametrize(
    "change",
    [{"visibility_status": "occluded"}, {"visibility_status": "unobservable"}, {"data_source": "real_robot"}],
)
def test_detector_does_not_claim_found_from_unusable_observation(change):
    observation = replace(Observation("evidence", "A", "2026-10-01T09:00:00+08:00"), **change)
    detector = FixtureDetector({"evidence": DetectionResult("target", "evidence", Status.FOUND)})
    assert detector.detect_target(observation, "target").status == Status.UNKNOWN


def test_detector_wrong_target_or_missing_evidence_is_unknown():
    observation = Observation("evidence", "A", "2026-10-01T09:00:00+08:00")
    detector = FixtureDetector({"evidence": DetectionResult("target", "evidence", Status.FOUND)})
    assert detector.detect_target(observation, "another-target").status == Status.UNKNOWN
    assert detector.detect_target(replace(observation, evidence_id="absent"), "target").status == Status.UNKNOWN
