"""Synthetic protocol tests only; no real photos or neural inference claims."""

from dataclasses import replace

import pytest

from hometrace.memory import SQLiteMemory
from hometrace.models import (
    DataSource, DetectionResult, NavigationMode, NavigationResult, Observation,
    Status, TimestampBasis, Viewpoint,
)
from hometrace.search_core import SearchCore


SOURCES = [DataSource.SYNTHETIC_IMAGE, DataSource.USER_IMAGE]


class PhotoEnvironment:
    def __init__(self, source, observation=None):
        self.source = source
        self.observation = observation or Observation(
            "scene-1", "desk", "2026-10-27T10:00:00+08:00", source,
            image_path="scene.png", image_hash="a" * 64,
            capture_source="Software protocol test input",
            timestamp_basis=TimestampBasis.DEMO_SEQUENCE,
        )

    def list_viewpoints(self):
        return [Viewpoint("desk", "Desk")]

    def navigate_to(self, viewpoint_id):
        return NavigationResult(viewpoint_id, "ARRIVED", self.source.value, True,
                                NavigationMode.SIMULATED)

    def observe(self, viewpoint_id):
        return self.observation


class PhotoDetector:
    def __init__(self, source, **changes):
        self.source, self.changes, self.calls = source, changes, 0

    def detect_target(self, observation, object_id):
        self.calls += 1
        result = DetectionResult(
            object_id, observation.evidence_id, Status.SUSPECTED,
            matcher="test_candidate_detector", score=.84, data_source=self.source,
            verification_kind="appearance_candidate",
            diagnostics={"image_decoded": True, "reason": "appearance_support", "elapsed_ms": 1.2},
            bbox=[10, 20, 90, 100],
        )
        return replace(result, **self.changes)


def setup_core(memory, source, *, observation=None, **detection_changes):
    memory.register_object("target", "reference.png", "Test object", "b" * 64, source)
    detector = PhotoDetector(source, **detection_changes)
    core = SearchCore(memory, PhotoEnvironment(source, observation), detector,
                      data_source=source, navigation_mode=NavigationMode.SIMULATED)
    return core, detector


@pytest.mark.parametrize("source", SOURCES)
def test_new_image_sources_require_simulated_navigation(source):
    with SQLiteMemory() as memory:
        with pytest.raises(ValueError, match="evidence/navigation"):
            SearchCore(memory, PhotoEnvironment(source), PhotoDetector(source),
                       data_source=source, navigation_mode=NavigationMode.MOCK)


@pytest.mark.parametrize("source", SOURCES)
def test_found_candidate_is_downgraded_with_evidence_preserved(source):
    with SQLiteMemory() as memory:
        core, detector = setup_core(memory, source, status=Status.FOUND)
        core.start_search("target")
        core.navigate_viewpoint("desk", reason="owner_reported_history")
        assert core.observe_current()["status"] == "PENDING_VERIFICATION"
        result = core.verify_current()
        assert detector.calls == 1
        assert result["status"] == result["result_status"] == Status.SUSPECTED
        assert result["location"] is None and result["bbox"] is None
        assert result["candidate_bbox"] == [10, 20, 90, 100]
        assert result["identity_confirmed"] is False
        result["candidate_bbox"][0] = 999
        detection = core.state.evidence[0].detection
        assert detection.bbox == [10, 20, 90, 100] and detection.score == .84
        assert detection.diagnostics["reason"] == "appearance_support"
        assert detection.diagnostics["automatic_confirmation_blocked"] is True
        assert detection.diagnostics["detector_status"] == "FOUND"
        assert detection.diagnostics["rejection"] == "appearance_candidate_cannot_confirm_identity"
        report = core.finish_search()
        assert not report.confirmed_evidence_ids and report.location is None
        assert report.data_source == source
        assert all(event.provenance["data_source"] == source for event in report.events)
        assert memory.query_memory("target")[0].detection == detection
        text = " ".join(report.limitations)
        assert "Appearance candidates" in text and "Navigation is simulated" in text
        assert "images are recorded photographs" not in text
        assert ("synthetic images" if source == DataSource.SYNTHETIC_IMAGE else "user-supplied images") in text


@pytest.mark.parametrize("source", SOURCES)
@pytest.mark.parametrize("changes", [
    {"verification_kind": "reference_instance_match"},
    {"data_source": DataSource.RECORDED_IMAGE},
    {"data_source": None},
    {"matcher": "fixture_annotation"},
    {"status": Status.NOT_FOUND_IN_VIEW},
    {"score": float("nan")},
    {"score": True},
    {"bbox": None},
    {"bbox": [-1, 2, 3, 4]},
    {"bbox": [1, 2, float("inf"), 4]},
    {"bbox": [True, 2, 3, 4]},
    {"bbox": [10, 20, 5, 100]},
    {"diagnostics": {"image_decoded": False}},
])
def test_invalid_photo_candidates_are_unknown_and_have_no_candidate_box(source, changes):
    with SQLiteMemory() as memory:
        core, _ = setup_core(memory, source, **changes)
        report = core.run("target")
        detection = report.evidence[0].detection
        assert report.result_status == Status.UNKNOWN and report.location is None
        assert detection.status == Status.UNKNOWN and detection.bbox is None
        assert detection.diagnostics["rejection"] == "unusable_detection"
        assert not report.confirmed_evidence_ids


@pytest.mark.parametrize("source", SOURCES)
def test_reference_hash_replay_is_rejected_before_detector(source):
    observation = replace(PhotoEnvironment(source).observation, image_hash="b" * 64)
    with SQLiteMemory() as memory:
        core, detector = setup_core(memory, source, observation=observation)
        report = core.run("target")
        assert detector.calls == 0 and not memory.query_memory("target")
        assert any(e.result.get("reason") == "replayed_image_content" for e in report.events)


@pytest.mark.parametrize("source", SOURCES)
@pytest.mark.parametrize("status", [Status.UNKNOWN, Status.SUSPECTED])
def test_all_verified_evidence_blocks_hash_replay_after_database_reopen(tmp_path, source, status):
    path = tmp_path / "candidate-memory.sqlite3"
    with SQLiteMemory(path) as memory:
        core, detector = setup_core(memory, source, status=status,
                                    bbox=None if status == Status.UNKNOWN else [10, 20, 90, 100])
        core.run("target")
        assert detector.calls == 1 and len(memory.query_memory("target")) == 1
    with SQLiteMemory(path) as memory:
        observation = replace(PhotoEnvironment(source).observation, evidence_id="scene-2",
                              captured_at="2026-10-27T11:00:00+08:00")
        core, detector = setup_core(memory, source, observation=observation)
        report = core.run("target")
        assert detector.calls == 0 and not report.evidence
        assert len(report.historical_evidence) == len(memory.query_memory("target")) == 1
        assert any(e.result.get("reason") == "replayed_image_content" for e in report.events)


@pytest.mark.parametrize("source", SOURCES)
def test_same_evidence_id_is_not_fresh_even_with_a_different_hash(source):
    with SQLiteMemory() as memory:
        core, _ = setup_core(memory, source)
        core.run("target")
        observation = replace(PhotoEnvironment(source).observation, image_hash="c" * 64,
                              captured_at="2026-10-27T11:00:00+08:00")
        core, detector = setup_core(memory, source, observation=observation)
        report = core.run("target")
        assert detector.calls == 0
        assert any(e.result.get("reason") == "replayed_evidence" for e in report.events)


@pytest.mark.parametrize("source", SOURCES)
@pytest.mark.parametrize("changes", [
    {"image_path": None}, {"image_hash": None}, {"image_hash": "not-sha256"},
    {"capture_source": None}, {"timestamp_basis": TimestampBasis.FIXTURE},
])
def test_image_provenance_is_required_before_detection(source, changes):
    observation = replace(PhotoEnvironment(source).observation, **changes)
    with SQLiteMemory() as memory:
        core, detector = setup_core(memory, source, observation=observation)
        report = core.run("target")
        assert detector.calls == 0
        assert any(e.result.get("reason") == "incomplete_image_provenance" for e in report.events)


@pytest.mark.parametrize("source", SOURCES)
def test_sources_cannot_mix_in_one_search(source):
    other = DataSource.USER_IMAGE if source == DataSource.SYNTHETIC_IMAGE else DataSource.SYNTHETIC_IMAGE
    observation = replace(PhotoEnvironment(source).observation, data_source=other)
    with SQLiteMemory() as memory:
        core, detector = setup_core(memory, source, observation=observation)
        report = core.run("target")
        assert detector.calls == 0
        assert any(e.result.get("reason") == "unsupported_evidence_source" for e in report.events)


@pytest.mark.parametrize("source", SOURCES)
def test_declared_capture_is_not_allowed_for_synthetic_images(source):
    observation = replace(PhotoEnvironment(source).observation, timestamp_basis=TimestampBasis.DECLARED_CAPTURE)
    with SQLiteMemory() as memory:
        core, detector = setup_core(memory, source, observation=observation)
        report = core.run("target")
        if source == DataSource.SYNTHETIC_IMAGE:
            assert detector.calls == 0
            assert any(e.result.get("reason") == "synthetic_image_requires_demo_sequence" for e in report.events)
        else:
            assert detector.calls == 1 and report.result_status == Status.SUSPECTED
