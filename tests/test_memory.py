from dataclasses import replace

import pytest

from hometrace.memory import SQLiteMemory
from hometrace.models import DetectionResult, Observation, Status


def test_sqlite_persistence_and_evidence_immutability(tmp_path):
    path = tmp_path / "memory.sqlite3"
    observation = Observation("obs-1", "A", "2026-10-14T08:00:00+00:00")
    detection = DetectionResult("remote-control", "obs-1", Status.FOUND)
    with SQLiteMemory(path) as memory:
        memory.register_object("remote-control", None, "Remote control fixture")
        assert memory.update_memory(observation, detection)
        assert not memory.update_memory(observation, detection)
        with pytest.raises(ValueError, match="rewritten"):
            memory.update_memory(observation, replace(detection, status=Status.UNKNOWN))
        with pytest.raises(ValueError, match="supplied observation"):
            memory.update_memory(observation, replace(detection, evidence_id="wrong"))
        with pytest.raises(ValueError, match="Unregistered"):
            memory.update_memory(observation, replace(detection, target_id="wrong"))
    with SQLiteMemory(path) as reopened:
        assert reopened.get_object("remote-control").description == "Remote control fixture"
        records = reopened.query_memory("remote-control")
        assert len(records) == 1
        assert records[0].observation == observation
        assert records[0].detection == detection
        assert reopened.query_memory("other") == []


def test_memory_orders_timestamps_by_instant_not_timezone_text():
    with SQLiteMemory() as memory:
        memory.register_object("target", None, "Fixture")
        for evidence_id, timestamp in [
            ("later", "2026-10-14T08:00:00+00:00"),
            ("earlier", "2026-10-14T12:00:00+08:00"),
        ]:
            memory.update_memory(
                Observation(evidence_id, "A", timestamp),
                DetectionResult("target", evidence_id, Status.FOUND),
            )
        assert [r.observation.evidence_id for r in memory.query_memory("target")] == ["earlier", "later"]
