import json
import subprocess
import sys

import pytest

from hometrace.memory import SQLiteMemory


@pytest.mark.parametrize(("scenario", "status", "location", "visited"), [
    ("moved", "FOUND", "B", ["A", "B"]),
    ("missing", "UNKNOWN", None, ["A", "B", "C"]),
])
def test_cli_from_arbitrary_working_directory(tmp_path, scenario, status, location, visited):
    output = tmp_path / "outputs"
    result = subprocess.run(
        [sys.executable, "-m", "hometrace", "--scenario", scenario, "--output-dir", str(output)],
        cwd=tmp_path, capture_output=True, text=True, check=True,
    )
    assert "Mock navigation" in result.stdout
    assert "data_source=fixture" in result.stdout
    report = json.loads((output / "report.json").read_text(encoding="utf-8"))
    events = [json.loads(line) for line in (output / "events.jsonl").read_text(encoding="utf-8").splitlines()]
    assert report["result_status"] == status
    assert report["location"] == location
    assert report["visited_viewpoints"] == visited
    assert report["events"] == events
    assert report["data_source"] == "fixture"
    with SQLiteMemory(output / "memory.sqlite3") as memory:
        assert len(memory.query_memory("remote-control")) == len(report["evidence"]) + 1


def test_cli_unknown_object_returns_error_without_report(tmp_path):
    result = subprocess.run(
        [sys.executable, "-m", "hometrace", "--object-id", "unknown", "--output-dir", str(tmp_path / "bad")],
        cwd=tmp_path, capture_output=True, text=True,
    )
    assert result.returncode == 2
    assert "Unregistered" in result.stderr
    assert not (tmp_path / "bad" / "report.json").exists()
