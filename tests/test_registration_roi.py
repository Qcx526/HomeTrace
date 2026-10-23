"""Registration-only ROI contracts; only public OpenCV images and test canvases.

No private family photos, scene answers or hand-selected scene rectangles are
used by these automated tests.
"""

import hashlib
import json
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from hometrace.memory import SQLiteMemory
from hometrace.models import DataSource, Observation, Status, TimestampBasis

cv = pytest.importorskip("cv2")
np = pytest.importorskip("numpy")

from hometrace.image_matcher import ImageMatcher

SAMPLES = Path(__file__).resolve().parents[1] / "examples/recorded_images"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def observation(path, root):
    return Observation(
        "roi-observation", "B", "2026-10-23T10:00:00+08:00",
        data_source=DataSource.RECORDED_IMAGE,
        image_path=path.relative_to(root).as_posix(), image_hash=sha(path),
        capture_source="public OpenCV sample", timestamp_basis=TimestampBasis.DEMO_SEQUENCE,
    )


@pytest.fixture
def padded_reference(tmp_path):
    original = cv.imdecode(np.frombuffer((SAMPLES / "box.png").read_bytes(), np.uint8), cv.IMREAD_GRAYSCALE)
    height, width = original.shape
    canvas = np.full((height + 160, width + 200), 127, dtype=np.uint8)
    canvas[80:80 + height, 100:100 + width] = original
    path = tmp_path / "padded.png"
    path.write_bytes(cv.imencode(".png", canvas)[1].tobytes())
    scene = tmp_path / "scene.png"
    shutil.copyfile(SAMPLES / "box_in_scene.png", scene)
    return path, scene, (100, 80, 100 + width, 80 + height)


def test_registration_roi_matches_object_and_preserves_full_scene_coordinates(padded_reference, tmp_path):
    reference, scene, roi = padded_reference
    matcher = ImageMatcher(reference, sha(reference), "box", tmp_path, reference_roi=roi)
    result = matcher.detect_target(observation(scene, tmp_path), "box")
    baseline = ImageMatcher(SAMPLES / "box.png", sha(SAMPLES / "box.png"), "box", SAMPLES)
    expected = baseline.detect_target(observation(SAMPLES / "box_in_scene.png", SAMPLES), "box")
    assert result.status == expected.status == Status.FOUND
    assert result.bbox == expected.bbox
    assert result.diagnostics["projected_corners"] == expected.diagnostics["projected_corners"]
    assert result.diagnostics["scene_keypoints"] == expected.diagnostics["scene_keypoints"]
    assert result.diagnostics["reference_roi"] == list(roi)
    assert result.diagnostics["reference_preprocessing"] == "registration_roi"
    assert result.diagnostics["scene_preprocessing"] == "full_image"
    assert result.diagnostics["reference_size"] == [roi[2] - roi[0], roi[3] - roi[1]]
    assert result.diagnostics["reference_original_size"] == [roi[2] + 100, roi[3] + 80]
    height, width = cv.imdecode(np.frombuffer(scene.read_bytes(), np.uint8), 0).shape
    assert result.diagnostics["scene_size"] == [width, height]
    assert result.diagnostics["reference_image_hash"] == sha(reference)
    x1, y1, x2, y2 = result.bbox
    assert 0 <= x1 < x2 < width and 0 <= y1 < y2 < height


def test_roi_still_checks_original_image_hash_outside_crop(padded_reference, tmp_path):
    reference, scene, roi = padded_reference
    matcher = ImageMatcher(reference, sha(reference), "box", tmp_path, reference_roi=roi)
    changed = cv.imdecode(np.frombuffer(reference.read_bytes(), np.uint8), 0)
    changed[0, 0] = 0  # Outside ROI, but original-file integrity must still hold.
    reference.write_bytes(cv.imencode(".png", changed)[1].tobytes())
    result = matcher.detect_target(observation(scene, tmp_path), "box")
    assert result.status == Status.UNKNOWN
    assert result.diagnostics["reason"] == "reference_image_changed"
    with pytest.raises(ValueError, match="hash_mismatch"):
        ImageMatcher(reference, matcher.reference_hash, "box", tmp_path, reference_roi=roi)


@pytest.mark.parametrize("filename", ["apple.jpg", "orange.jpg", "fruits.jpg"])
def test_registration_roi_preserves_negative_rejection(padded_reference, tmp_path, filename):
    reference, _, roi = padded_reference
    scene = tmp_path / filename
    shutil.copyfile(SAMPLES / filename, scene)
    result = ImageMatcher(reference, sha(reference), "box", tmp_path, reference_roi=roi).detect_target(
        observation(scene, tmp_path), "box"
    )
    assert result.status in (Status.UNKNOWN, Status.SUSPECTED)
    assert result.bbox is None


def test_features_outside_roi_cannot_rescue_blank_object(padded_reference, tmp_path):
    reference, _, _ = padded_reference
    with pytest.raises(ValueError, match="sharp, textured"):
        ImageMatcher(reference, sha(reference), "box", tmp_path, reference_roi=[0, 0, 80, 60])


@pytest.mark.parametrize("roi", [
    [0, 0, 31, 80], [0, 0, 80, 31], [-1, 0, 80, 80], [0, -1, 80, 80],
    [80, 0, 0, 80], [0, 80, 80, 0], [0, 0, 9999, 80], [0, 0, 80, 9999],
    [False, 0, 80, 80], [0, 0, 80.0, 80], [0, 0, 80], "0,0,80,80", {"x1": 0},
])
def test_invalid_reference_roi_rejected(padded_reference, tmp_path, roi):
    reference, _, _ = padded_reference
    with pytest.raises(ValueError, match="reference_roi"):
        ImageMatcher(reference, sha(reference), "box", tmp_path, reference_roi=roi)


def test_roi_persists_and_is_immutable_in_sqlite(tmp_path):
    path = tmp_path / "roi.sqlite3"
    with SQLiteMemory(path) as memory:
        memory.register_object("box", "box.png", "first", "a" * 64, DataSource.RECORDED_IMAGE, reference_roi=[0, 0, 120, 100])
    with SQLiteMemory(path) as memory:
        assert memory.get_object("box").reference_roi == (0, 0, 120, 100)
        memory.register_object("box", "box.png", "description may change", "a" * 64, DataSource.RECORDED_IMAGE, reference_roi=(0, 0, 120, 100))
        for replacement in (None, [1, 1, 120, 100]):
            with pytest.raises(ValueError, match="immutable"):
                memory.register_object("box", "box.png", "changed", "a" * 64, DataSource.RECORDED_IMAGE, reference_roi=replacement)
        assert memory.get_object("box").reference_roi == (0, 0, 120, 100)
        with pytest.raises(ValueError, match="recorded-image"):
            memory.register_object("fixture", None, "fixture", reference_roi=[0, 0, 120, 100])


def test_pre_roi_sqlite_migration_preserves_objects(tmp_path):
    path = tmp_path / "old.sqlite3"
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE objects(object_id TEXT PRIMARY KEY, description TEXT NOT NULL, sample_image_path TEXT, sample_image_hash TEXT, data_source TEXT NOT NULL)")
    connection.execute("INSERT INTO objects VALUES ('box','legacy','box.png',?,'recorded_image')", ("a" * 64,))
    connection.commit()
    connection.close()
    with SQLiteMemory(path) as memory:
        registered = memory.get_object("box")
        assert registered.reference_roi is None
        assert registered.sample_image_hash == "a" * 64
        assert registered.data_source == DataSource.RECORDED_IMAGE


def command(tmp_path, operation, extra=()):
    args = [
        sys.executable, "-m", "hometrace", operation,
        "--db", str(tmp_path / "memory.sqlite3"), "--object-id", "roi-box",
        "--scene", str(SAMPLES / ("history.json" if operation == "register" else "moved.json")),
        "--image-root", str(SAMPLES), "--output-dir", str(tmp_path / operation),
    ]
    if operation == "register":
        args += ["--reference", "box.png"]
    return subprocess.run(args + list(extra), capture_output=True, text=True)


def test_separate_cli_processes_load_registration_roi_and_disallow_search_override(tmp_path):
    ref = cv.imdecode(np.frombuffer((SAMPLES / "box.png").read_bytes(), np.uint8), 0)
    height, width = ref.shape
    roi = [0, 0, width, height]
    registration = command(tmp_path, "register", ["--reference-roi", *map(str, roi)])
    assert registration.returncode == 0, registration.stderr
    searched = command(tmp_path, "search")
    assert searched.returncode == 0, searched.stderr
    report = json.loads((tmp_path / "search/report.json").read_text(encoding="utf-8"))
    assert report["result_status"] == "FOUND"
    assert report["location"] == "B"
    assert all(row["detection"]["diagnostics"]["reference_roi"] == roi for row in report["evidence"])
    assert report["evidence"][-1]["detection"]["diagnostics"]["scene_preprocessing"] == "full_image"
    with SQLiteMemory(tmp_path / "memory.sqlite3") as memory:
        assert memory.get_object("roi-box").sample_image_hash == sha(SAMPLES / "box.png")
        assert memory.get_object("roi-box").reference_roi == tuple(roi)
    overwritten = command(tmp_path, "search", ["--reference-roi", *map(str, roi)])
    assert overwritten.returncode == 2
    assert "unrecognized arguments" in overwritten.stderr


def test_invalid_roi_enrollment_does_not_create_database(tmp_path):
    result = command(tmp_path, "register", ["--reference-roi", "0", "0", "99999", "100"])
    assert result.returncode == 2
    assert "reference_roi" in result.stderr
    assert not (tmp_path / "memory.sqlite3").exists()
