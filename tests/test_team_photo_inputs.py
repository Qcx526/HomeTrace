"""Synthetic input-boundary tests; these bytes are not photo recognition evidence."""

import importlib.util
import json
from pathlib import Path

import pytest


spec = importlib.util.spec_from_file_location("evaluate_team_photos", Path(__file__).resolve().parents[1] / "tools/evaluate_team_photos.py")
evaluation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evaluation)


def write_pack(tmp_path):
    image = tmp_path / "test.jpg"
    image.write_bytes(b"synthetic input validation bytes; not an actual photograph")
    mapping = dict(scope="PRIVATE_LOCAL_EVALUATION_ONLY", source="Synthetic unit test",
                   capture_times="unknown; demo sequence only", files=[dict(english_path="test.jpg",
                   sha256=evaluation.sha256(image), bytes=image.stat().st_size)])
    write_mapping(tmp_path, mapping)
    return mapping


def write_mapping(root, mapping):
    (root / "PHOTO_MAPPING.json").write_text(json.dumps(mapping), encoding="utf-8")
    (root / "SHA256SUMS.txt").write_text("\n".join(
        f"{evaluation.sha256(root / name)}  {name}" for name in ("PHOTO_MAPPING.json", "test.jpg")), encoding="utf-8")


def write_scene(root, name, hour, **changes):
    content = dict(schema_version=1, data_source="recorded_image", navigation_mode="simulated_navigation",
                   timestamp_basis="demo_sequence", capture_source="Synthetic input test, no actual capture",
                   viewpoints=[dict(viewpoint_id="A", name="Synthetic A")],
                   observations=[dict(evidence_id=name, viewpoint_id="A", captured_at=f"2000-01-01T{hour:02}:00:00+00:00",
                                      image_path="test.jpg", visibility_status="clear")])
    content.update(changes)
    (root / f"{name}.json").write_text(json.dumps(content), encoding="utf-8")


def test_validates_inventory_hashes_and_never_modifies_inputs(tmp_path):
    write_pack(tmp_path)
    before = {p.name: evaluation.sha256(p) for p in tmp_path.iterdir()}
    assert len(evaluation.validate_pack(tmp_path, "PHOTO_MAPPING.json")["files"]) == 1
    assert before == {p.name: evaluation.sha256(p) for p in tmp_path.iterdir()}


def test_changed_photo_bytes_fail_inventory_validation(tmp_path):
    write_pack(tmp_path)
    (tmp_path / "test.jpg").write_bytes(b"changed")
    with pytest.raises(ValueError, match="mismatch"):
        evaluation.validate_pack(tmp_path, "PHOTO_MAPPING.json")


def test_changed_mapping_fails_supplied_checksum(tmp_path):
    write_pack(tmp_path)
    with (tmp_path / "PHOTO_MAPPING.json").open("a") as stream:
        stream.write(" ")
    with pytest.raises(ValueError, match="SHA256SUMS mismatch"):
        evaluation.validate_pack(tmp_path, "PHOTO_MAPPING.json")


@pytest.mark.parametrize("relative", ["../test.jpg", "C:/test.jpg", "/test.jpg", "images\\test.jpg", "./test.jpg"])
def test_inventory_paths_cannot_escape_root(tmp_path, relative):
    mapping = write_pack(tmp_path)
    mapping["files"][0]["english_path"] = relative
    write_mapping(tmp_path, mapping)
    with pytest.raises(ValueError, match="image_path"):
        evaluation.validate_pack(tmp_path, "PHOTO_MAPPING.json")


@pytest.mark.parametrize("changes", [dict(scope="PUBLIC"), dict(source=""), dict(capture_times="authenticated")])
def test_source_and_private_scope_are_required(tmp_path, changes):
    mapping = write_pack(tmp_path)
    mapping.update(changes)
    write_mapping(tmp_path, mapping)
    with pytest.raises(ValueError):
        evaluation.validate_pack(tmp_path, "PHOTO_MAPPING.json")


def test_current_observations_must_follow_history(tmp_path):
    mapping = write_pack(tmp_path)
    write_scene(tmp_path, "history", 2)
    write_scene(tmp_path, "moved", 1)
    write_scene(tmp_path, "missing", 3)
    with pytest.raises(ValueError, match="follow history"):
        evaluation.validate_tissue_scenes(tmp_path, mapping)


def test_demo_timestamps_cannot_be_relabelled_authentic_capture(tmp_path):
    mapping = write_pack(tmp_path)
    write_scene(tmp_path, "history", 1)
    write_scene(tmp_path, "moved", 2, timestamp_basis="declared_capture")
    write_scene(tmp_path, "missing", 3)
    with pytest.raises(ValueError, match="demo_sequence"):
        evaluation.validate_tissue_scenes(tmp_path, mapping)


def test_known_inputs_use_existing_strict_manifest_parser(tmp_path):
    mapping = write_pack(tmp_path)
    write_scene(tmp_path, "history", 1)
    write_scene(tmp_path, "moved", 2, detections=[dict(status="FOUND")])
    write_scene(tmp_path, "missing", 3)
    with pytest.raises(ValueError, match="unknown fields"):
        evaluation.validate_tissue_scenes(tmp_path, mapping)


def test_public_summary_excludes_raw_observations_and_private_strings():
    report = dict(generated_at="2000-01-01T00:00:00+00:00", private_path="PRIVATE_SECRET",
                  validation=dict(private_path="PRIVATE_SECRET", hashes="passed"),
                  detections=[dict(object_id="tissue-pack", case="current_B", method="ORB", expected_presence=True,
                                   result=dict(status="SUSPECTED", image_path="PRIVATE_SECRET", bbox=[1, 2, 3, 4],
                                               diagnostics=dict(good_matches=12, inliers=4, private_note="PRIVATE_SECRET")))],
                  cli_runs=[dict(scenario="moved", stage="hash_replay", returncode=0, command=["PRIVATE_SECRET"],
                                 report=dict(result_status="UNKNOWN", events=[dict(action="view_result",
                                             result=dict(reason="replayed_image_content"))], historical_evidence=["PRIVATE_SECRET"]))])
    summary = evaluation.public_summary(report)
    assert "PRIVATE_SECRET" not in json.dumps(summary)
    assert "bbox" not in summary["detections"][0]
    assert summary["cli_runs"][0]["replay_rejections"] == 1
    assert summary["cli_runs"][0]["replay_reasons"] == ["replayed_image_content"]


def test_missing_private_data_is_an_error_not_fabricated_results(tmp_path, capsys):
    assert evaluation.main(["--data-root", str(tmp_path / "absent"), "--output-dir", str(Path("artifacts") / "unused-photo-audit-test")]) == 2
    assert "Missing team photo directory" in capsys.readouterr().err


def test_refuses_existing_output_without_overwriting_evidence(tmp_path, capsys):
    preserved = tmp_path / "report.json"
    preserved.write_text("existing evidence", encoding="utf-8")
    assert evaluation.main(["--data-root", str(tmp_path), "--output-dir", str(tmp_path)]) == 2
    assert preserved.read_text() == "existing evidence"
    assert "already exists" in capsys.readouterr().err


def test_sift_and_akaze_geometry_keeps_coverage_gate_and_coordinates():
    cv = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    # Known synthetic transform tests geometry, not recognition accuracy.
    source = np.float32([[x, y] for x in (5, 30, 60, 90) for y in (5, 30, 60, 90)]).reshape(-1, 1, 2)
    target = source * 2 + np.float32([30, 40])
    metrics = {}
    status, reason, bbox = evaluation._geometry(cv, np, source, target, (100, 100), (300, 300), metrics)
    assert status == "FOUND"
    assert bbox == [30.0, 40.0, 228.0, 238.0]
    local_source = source / 10
    status, reason, bbox = evaluation._geometry(cv, np, local_source, local_source * 2 + 50, (100, 100), (300, 300), {})
    assert status == "SUSPECTED"
    assert reason == "reference_support_too_local"
    assert bbox is None
