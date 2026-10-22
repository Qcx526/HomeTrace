"""Protocol fault injection; these observations are synthetic, not real photo tests."""

from dataclasses import replace

import pytest

from hometrace.memory import SQLiteMemory
from hometrace.models import DataSource, DetectionResult, NavigationMode, NavigationResult, Observation, Status, TimestampBasis, Viewpoint
from hometrace.search_core import SearchCore


@pytest.mark.parametrize("fault", ["not_decoded", "no_bbox", "invalid_bbox", "wrong_source"])
def test_recorded_found_requires_usable_decoded_evidence(fault):
    class Environment:
        def list_viewpoints(self):
            return [Viewpoint("A", "Protocol test point")]

        def navigate_to(self, viewpoint_id):
            return NavigationResult(viewpoint_id, "ARRIVED", "recorded_image", True, NavigationMode.SIMULATED)

        def observe(self, viewpoint_id):
            return Observation(
                "new-evidence", viewpoint_id, "2026-10-21T10:00:00+08:00", DataSource.RECORDED_IMAGE,
                image_path="synthetic.png", image_hash="a" * 64, capture_source="Synthetic fault injection",
                timestamp_basis=TimestampBasis.DEMO_SEQUENCE,
            )

    class FaultyDetector:
        def detect_target(self, observation, object_id):
            result = DetectionResult(
                object_id, observation.evidence_id, Status.FOUND, matcher="opencv_orb_homography",
                data_source=DataSource.RECORDED_IMAGE, verification_kind="reference_instance_match",
                diagnostics={"image_decoded": True}, bbox=[0, 0, 10, 10],
            )
            if fault == "not_decoded":
                return replace(result, diagnostics={"image_decoded": False})
            if fault == "no_bbox":
                return replace(result, bbox=None)
            if fault == "invalid_bbox":
                return replace(result, bbox=[0, 0, float("nan"), 10])
            return replace(result, data_source=DataSource.FIXTURE)

    with SQLiteMemory() as memory:
        memory.register_object("target", "reference.png", "Protocol test", "b" * 64, DataSource.RECORDED_IMAGE)
        report = SearchCore(
            memory, Environment(), FaultyDetector(),
            data_source=DataSource.RECORDED_IMAGE, navigation_mode=NavigationMode.SIMULATED,
        ).run("target")
        assert report.result_status == Status.UNKNOWN
        assert not report.confirmed_evidence_ids
        assert memory.query_memory("target")[0].detection.status == Status.UNKNOWN


def test_outer_transaction_rolls_back_objects_and_evidence():
    with SQLiteMemory() as memory:
        with pytest.raises(OSError):
            with memory.transaction():
                memory.register_object("target", None, "Fixture")
                memory.update_memory(
                    Observation("obs", "A", "2026-10-21T08:00:00+08:00"),
                    DetectionResult("target", "obs", Status.FOUND),
                )
                raise OSError("Report write failed")
        assert memory.get_object("target") is None
        assert not memory.query_memory("target")
