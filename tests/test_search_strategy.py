"""Fair strategy controls: acquired memory and public viewpoints, never future truth."""

import json
import subprocess
import sys
from dataclasses import replace
from importlib.resources import files
from pathlib import Path

import pytest

from hometrace.environment import MockAdapter
from hometrace.fixtures import load_fixture
from hometrace.memory import SQLiteMemory
from hometrace.models import DetectionResult, SearchStrategy, Status, TaskState, Viewpoint
from hometrace.perception import FixtureDetector
from hometrace.search_core import SearchCore


SAMPLES = Path(__file__).resolve().parents[1] / "examples/recorded_images"


class MetadataOnlyEnvironment:
    def list_viewpoints(self):
        return [Viewpoint("C", "Third"), Viewpoint("A", "First"), Viewpoint("B", "Second")]

    def navigate_to(self, _):
        raise AssertionError("Planning must not navigate")

    def observe(self, _):
        raise AssertionError("Planning must not inspect future photographs")


class NoDetector:
    def detect_target(self, *_):
        raise AssertionError("Planning must not ask a detector for future answers")


def seed_fixture(memory):
    scenario = load_fixture(files("hometrace").joinpath("fixture_data", "moved.json"))
    obj = scenario.object
    memory.register_object(obj.object_id, obj.sample_image_path, obj.description)
    for record in scenario.memory_records:
        memory.update_memory(record.observation, record.detection)
    return scenario


def test_fixed_order_ignores_memory_and_input_enumeration_order():
    class UnreadableMemory:
        def query_memory(self, _):
            raise AssertionError("Fixed-order planning must not rank by memory")

    core = SearchCore(
        UnreadableMemory(), MetadataOnlyEnvironment(), NoDetector(),
        strategy=SearchStrategy.FIXED_ORDER,
    )
    state = TaskState("planning-only", "target")
    for expected in ("A", "B", "C"):
        decision = core.plan_next(state)
        assert (decision.viewpoint_id, decision.reason, decision.score) == (expected, "fixed_order", 0)
        state.visited_viewpoints.append(expected)
    assert core.plan_next(state) is None


def test_memory_first_responds_to_acquired_memory_while_fixed_order_does_not():
    with SQLiteMemory() as memory:
        scenario = seed_fixture(memory)
        state = TaskState("planning-only", scenario.object.object_id)
        memory_first = SearchCore(memory, MetadataOnlyEnvironment(), NoDetector())
        fixed = SearchCore(memory, MetadataOnlyEnvironment(), NoDetector(), strategy="fixed_order")
        assert memory_first.plan_next(state).viewpoint_id == fixed.plan_next(state).viewpoint_id == "A"
        observation = replace(
            scenario.observations["C"], evidence_id="acquired-history-C",
            captured_at="2026-10-01T18:00:00+08:00",
        )
        memory.update_memory(
            observation,
            DetectionResult(scenario.object.object_id, observation.evidence_id, Status.FOUND),
        )
        assert memory_first.plan_next(state).viewpoint_id == "C"
        assert fixed.plan_next(state).viewpoint_id == "A"
        assert memory_first.strategy is SearchStrategy.MEMORY_FIRST


def test_unknown_strategy_is_rejected_before_search():
    with pytest.raises(ValueError):
        SearchCore(None, None, None, strategy="future_truth")


@pytest.mark.parametrize("strategy", list(SearchStrategy))
def test_fixture_results_and_report_strategy_remain_auditable(strategy):
    with SQLiteMemory() as memory:
        scenario = seed_fixture(memory)
        report = SearchCore(
            memory, MockAdapter(scenario.viewpoints, scenario.observations),
            FixtureDetector(scenario.detections), strategy=strategy,
        ).run(scenario.object.object_id)
    assert report.result_status == Status.FOUND
    assert report.location == "B"
    assert report.attempted_viewpoints == ["A", "B"]
    assert report.to_dict()["strategy"] == strategy.value
    assert report.historical_evidence == scenario.memory_records
    assert report.confirmed_evidence_ids == [scenario.observations["B"].evidence_id]


@pytest.mark.parametrize("scene", ["moved", "missing"])
def test_cli_strategies_use_identical_public_photos_and_separate_memory(tmp_path, scene):
    pytest.importorskip("cv2")
    reports = []
    for strategy in SearchStrategy:
        directory = tmp_path / strategy.value
        common = [
            "--db", str(directory / "memory.sqlite3"), "--object-id", "sample-box",
            "--image-root", str(SAMPLES),
        ]
        commands = [
            ["register", *common, "--reference", "box.png", "--scene", str(SAMPLES / "history.json"),
             "--output-dir", str(directory / "register")],
            ["search", *common, "--scene", str(SAMPLES / f"{scene}.json"),
             "--strategy", strategy.value, "--output-dir", str(directory / "search")],
        ]
        for arguments in commands:
            result = subprocess.run(
                [sys.executable, "-m", "hometrace", *arguments],
                cwd=tmp_path, capture_output=True, text=True,
            )
            assert result.returncode == 0, result.stderr
        report = json.loads((directory / "search/report.json").read_text(encoding="utf-8"))
        assert report["strategy"] == strategy.value
        assert f"STRATEGY {strategy.value}" in result.stdout
        assert report["data_source"] == "recorded_image"
        assert report["navigation_mode"] == "simulated_navigation"
        reports.append(report)
    memory_report, fixed_report = reports
    # Both strategies have the same candidates/history/images; this sample is a tie.
    # Detector elapsed times differ, so compare the acquired image identities and states.
    assert [r["observation"] for r in memory_report["historical_evidence"]] == [
        r["observation"] for r in fixed_report["historical_evidence"]
    ]
    assert [r["observation"] for r in memory_report["evidence"]] == [
        r["observation"] for r in fixed_report["evidence"]
    ]
    assert memory_report["attempted_viewpoints"] == fixed_report["attempted_viewpoints"]
    assert memory_report["observed_viewpoints"] == fixed_report["observed_viewpoints"]
    assert memory_report["result_status"] == fixed_report["result_status"]
    if scene == "moved":
        assert memory_report["result_status"] == "FOUND"
        assert memory_report["location"] == fixed_report["location"] == "B"
        assert len(memory_report["attempted_viewpoints"]) == 2
    else:
        assert memory_report["result_status"] in ("SUSPECTED", "UNKNOWN")
        assert memory_report["location"] is fixed_report["location"] is None
        assert not memory_report["confirmed_evidence_ids"]
        assert not fixed_report["confirmed_evidence_ids"]
        assert len(memory_report["attempted_viewpoints"]) == 3
