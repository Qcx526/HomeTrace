"""Separate-process and state-machine checks using documented public photographs."""

import hashlib
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from hometrace.memory import SQLiteMemory
from hometrace.models import DataSource, NavigationMode, Status
from hometrace.search_core import SearchCore

pytest.importorskip("cv2")
SAMPLES = Path(__file__).resolve().parents[1] / "examples/recorded_images"


def cli(tmp_path, operation, scene="history.json", *, db="memory.sqlite3", suffix="", extra=()):
    scene_path = SAMPLES / scene if isinstance(scene, str) else scene
    output = tmp_path / (operation + suffix)
    command = [
        sys.executable, "-m", "hometrace", operation, "--db", str(tmp_path / db),
        "--object-id", "sample-box", "--scene", str(scene_path),
        "--image-root", str(SAMPLES), "--output-dir", str(output),
    ]
    if operation == "register":
        command += ["--reference", "box.png"]
    result = subprocess.run(command + list(extra), cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return json.loads((output / "report.json").read_text(encoding="utf-8")), result.stdout


def manifest(tmp_path, modify):
    data = json.loads((SAMPLES / "moved.json").read_text(encoding="utf-8"))
    modify(data)
    path = tmp_path / "custom.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_real_photo_enrollment_and_search_are_separate_processes(tmp_path):
    registered, _ = cli(tmp_path, "register")
    assert registered["operation"] == "register"
    assert registered["result_status"] == "FOUND"
    assert not registered["historical_evidence"]
    with SQLiteMemory(tmp_path / "memory.sqlite3") as memory:
        assert len(memory.query_memory("sample-box")) == 1
        assert memory.get_object("sample-box").sample_image_hash == hashlib.sha256((SAMPLES / "box.png").read_bytes()).hexdigest()
    report, stdout = cli(tmp_path, "search", "moved.json")
    assert "simulated_navigation" in stdout
    assert report["result_status"] == "FOUND"
    assert report["location"] == "B"
    assert report["attempted_viewpoints"] == report["arrived_viewpoints"] == report["observed_viewpoints"] == ["A", "B"]
    assert report["historical_evidence"] == registered["evidence"]
    assert report["confirmed_evidence_ids"] == [report["evidence"][-1]["observation"]["evidence_id"]]
    assert report["evidence"][0]["detection"]["status"] != "FOUND"
    assert report["evidence"][-1]["detection"]["verification_kind"] == "reference_instance_match"
    assert report["evidence"][-1]["observation"]["image_hash"] != registered["evidence"][0]["observation"]["image_hash"]
    assert all(event["provenance"]["data_source"] == "recorded_image" for event in report["events"])
    with SQLiteMemory(tmp_path / "memory.sqlite3") as memory:
        assert len(memory.query_memory("sample-box")) == 3


def test_real_negative_photos_are_matched_without_false_found(tmp_path):
    cli(tmp_path, "register")
    report, _ = cli(tmp_path, "search", "missing.json")
    assert report["result_status"] in ("UNKNOWN", "SUSPECTED")
    assert report["location"] is None
    assert report["observed_viewpoints"] == ["A", "B", "C"]
    assert not report["confirmed_evidence_ids"]
    assert all(r["detection"]["status"] in ("UNKNOWN", "SUSPECTED") for r in report["evidence"])
    assert all(r["detection"]["diagnostics"]["image_decoded"] for r in report["evidence"])


def test_new_ids_and_dates_do_not_bypass_image_replay_guard(tmp_path):
    cli(tmp_path, "register")
    cli(tmp_path, "search", "moved.json")

    def modify(data):
        for row in data["observations"]:
            row["evidence_id"] += "-renamed"
            row["captured_at"] = row["captured_at"].replace("2026-10-21", "2026-10-22")

    report, _ = cli(tmp_path, "search", manifest(tmp_path, modify), suffix="-replay")
    assert report["result_status"] != "FOUND"
    rejected = [e for e in report["events"] if e["action"] == "view_result" and e["result"].get("reason") == "replayed_image_content"]
    assert {e["input_ids"][0] for e in rejected} == {"A", "B"}
    assert not report["confirmed_evidence_ids"]


def test_same_run_latest_accepted_frame_sets_time_watermark(tmp_path):
    cli(tmp_path, "register")

    def modify(data):
        data["observations"][0]["captured_at"] = "2026-10-21T11:00:00+08:00"
        data["observations"][1]["captured_at"] = "2026-10-21T10:00:00+08:00"
        data["observations"][2]["captured_at"] = "2026-10-21T11:02:00+08:00"

    report, _ = cli(tmp_path, "search", manifest(tmp_path, modify))
    assert report["result_status"] != "FOUND"
    assert "B" not in report["observed_viewpoints"]
    assert any(e["input_ids"][0] == "B" and e["result"].get("reason") == "observation_not_newer_than_memory" for e in report["events"] if e["action"] == "view_result")


def test_attempted_arrived_and_observed_are_distinct(tmp_path):
    cli(tmp_path, "register")

    def modify(data):
        data["unreachable_viewpoints"] = ["B"]
        data["observations"][2]["image_path"] = "not-provided.png"

    report, _ = cli(tmp_path, "search", manifest(tmp_path, modify))
    assert report["result_status"] in ("UNKNOWN", "SUSPECTED")
    assert report["attempted_viewpoints"] == ["A", "B", "C"]
    assert report["arrived_viewpoints"] == ["A", "C"]
    assert report["observed_viewpoints"] == ["A"]
    assert report["evidence"][-1]["observation"]["error"] == "image_missing"
    assert report["evidence"][-1]["detection"]["status"] == "UNKNOWN"


@pytest.mark.parametrize("change", ["occluded", "time_basis", "old_capture"])
def test_unusable_positive_photo_cannot_confirm(tmp_path, change):
    cli(tmp_path, "register")

    def modify(data):
        if change == "occluded":
            data["observations"][1]["visibility_status"] = "occluded"
        elif change == "time_basis":
            data["timestamp_basis"] = "declared_capture"
        else:
            data["observations"][1]["captured_at"] = "2026-10-20T08:00:00+08:00"

    report, _ = cli(tmp_path, "search", manifest(tmp_path, modify))
    assert report["result_status"] != "FOUND"
    assert report["location"] is None


def test_source_types_cannot_enable_real_robot():
    with pytest.raises(ValueError):
        SearchCore(None, None, None, data_source="real_robot")
    with pytest.raises(ValueError):
        SearchCore(None, None, None, data_source=DataSource.RECORDED_IMAGE, navigation_mode=NavigationMode.MOCK)


def test_registration_cannot_overwrite_existing_identity(tmp_path):
    cli(tmp_path, "register")
    with SQLiteMemory(tmp_path / "memory.sqlite3") as memory:
        old = memory.get_object("sample-box")
        with pytest.raises(ValueError, match="immutable"):
            memory.register_object("sample-box", "orange.jpg", "changed", "a" * 64, DataSource.RECORDED_IMAGE)
        assert memory.get_object("sample-box") == old


def test_p0_sqlite_schema_and_payloads_are_migrated_without_rewriting(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    record = json.loads((Path(__file__).resolve().parents[1] / "src/hometrace/fixture_data/moved.json").read_text(encoding="utf-8"))["memory_records"][0]
    payload = json.dumps(record, sort_keys=True)
    connection = sqlite3.connect(path)
    connection.executescript("CREATE TABLE objects(object_id TEXT PRIMARY KEY, description TEXT NOT NULL, sample_image_path TEXT); CREATE TABLE records(evidence_id TEXT, object_id TEXT, payload TEXT, PRIMARY KEY(evidence_id,object_id));")
    connection.execute("INSERT INTO objects VALUES ('remote-control','legacy',NULL)")
    connection.execute("INSERT INTO records VALUES (?,?,?)", (record["observation"]["evidence_id"], "remote-control", payload))
    connection.commit()
    connection.close()
    with SQLiteMemory(path) as memory:
        assert memory.get_object("remote-control").data_source == DataSource.FIXTURE
        history = memory.query_memory("remote-control")
        assert history[0].detection.status == Status.FOUND
        assert not memory.update_memory(history[0].observation, history[0].detection)
        assert memory.connection.execute("SELECT payload FROM records").fetchone()[0] == payload


def test_report_failure_does_not_consume_persistent_evidence(tmp_path, monkeypatch):
    from hometrace import recorded_cli

    def fail_report(*args):
        raise OSError("simulated output failure")

    monkeypatch.setattr(recorded_cli, "_write_report", fail_report)
    db = tmp_path / "rollback.sqlite3"
    code = recorded_cli.main([
        "register", "--db", str(db), "--object-id", "sample-box", "--reference", "box.png",
        "--scene", str(SAMPLES / "history.json"), "--output-dir", str(tmp_path / "output"),
    ])
    assert code == 2
    with SQLiteMemory(db) as memory:
        assert memory.get_object("sample-box") is None
        assert not memory.query_memory("sample-box")


def test_bad_output_path_is_rejected_before_creating_database(tmp_path):
    from hometrace import recorded_cli

    output = tmp_path / "already-a-file"
    output.write_text("Do not change", encoding="utf-8")
    db = tmp_path / "not-created.sqlite3"
    code = recorded_cli.main([
        "register", "--db", str(db), "--object-id", "sample-box", "--reference", "box.png",
        "--scene", str(SAMPLES / "history.json"), "--output-dir", str(output),
    ])
    assert code == 2
    assert not db.exists()
    assert output.read_text(encoding="utf-8") == "Do not change"
