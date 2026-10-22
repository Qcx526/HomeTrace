"""Image algorithm tests; generated patterns below are synthetic, not photos."""

import hashlib
from dataclasses import replace
from pathlib import Path

import pytest

cv = pytest.importorskip("cv2")
np = pytest.importorskip("numpy")

from hometrace.image_matcher import ImageMatcher
from hometrace.models import DataSource, Observation, Status, TimestampBasis


PUBLIC_SAMPLES = Path(__file__).resolve().parents[1] / "examples" / "recorded_images"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def observation(path, root, **changes):
    base = Observation(
        evidence_id="image-test", viewpoint_id="B", captured_at="2026-10-21T10:00:00+08:00",
        data_source=DataSource.RECORDED_IMAGE, image_path=path.relative_to(root).as_posix(),
        image_hash=sha(path), capture_source="synthetic algorithm-test image",
        timestamp_basis=TimestampBasis.DEMO_SEQUENCE,
    )
    return replace(base, **changes)


def save_image(path, image):
    success, contents = cv.imencode(path.suffix, image)
    assert success
    path.write_bytes(contents.tobytes())


@pytest.fixture
def synthetic_images(tmp_path):
    # Seeded drawings exercise geometric matching, not real-world recognition.
    rng = np.random.default_rng(4729)
    reference = np.full((280, 400), 245, dtype=np.uint8)
    for index in range(130):
        point = tuple(int(x) for x in rng.integers([12, 12], [388, 268]))
        radius = int(rng.integers(2, 9))
        cv.circle(reference, point, radius, int(rng.integers(0, 180)), -1)
    cv.putText(reference, "SYNTHETIC TEST 4729", (30, 135), cv.FONT_HERSHEY_SIMPLEX, 0.65, 0, 2)
    cv.rectangle(reference, (18, 18), (382, 262), 0, 3)
    source = np.float32([[0, 0], [399, 0], [399, 279], [0, 279]])
    destination = np.float32([[100, 85], [550, 100], [535, 425], [85, 400]])
    homography = cv.getPerspectiveTransform(source, destination)
    scene = cv.warpPerspective(reference, homography, (720, 510), borderValue=70)
    reference_path, scene_path = tmp_path / "参考图.png", tmp_path / "观察图.png"
    save_image(reference_path, reference)
    save_image(scene_path, scene)
    return reference_path, scene_path


def test_synthetic_perspective_match_has_geometric_evidence(synthetic_images, tmp_path):
    reference, scene = synthetic_images
    matcher = ImageMatcher(reference, sha(reference), "target", tmp_path)
    result = matcher.detect_target(observation(scene, tmp_path), "target")
    assert result.status == Status.FOUND
    assert result.verification_kind == "reference_instance_match"
    assert result.data_source == DataSource.RECORDED_IMAGE
    assert result.matcher == "opencv_orb_homography"
    assert result.diagnostics["image_decoded"] is True
    assert result.diagnostics["inliers"] >= matcher.MIN_INLIERS
    assert result.diagnostics["reference_coverage"] >= matcher.MIN_REFERENCE_COVERAGE
    assert result.diagnostics["elapsed_ms"] >= 0
    assert len(result.bbox) == 4


@pytest.mark.parametrize("condition", ["occluded", "wrong_hash", "missing", "corrupt", "outside_root", "wrong_target", "wrong_source"])
def test_unusable_images_never_become_found_or_negative(synthetic_images, tmp_path, condition):
    reference, scene = synthetic_images
    matcher = ImageMatcher(reference, sha(reference), "target", tmp_path)
    observed = observation(scene, tmp_path)
    target = "target"
    if condition == "occluded":
        observed = replace(observed, visibility_status="occluded")
    elif condition == "wrong_hash":
        observed = replace(observed, image_hash="0" * 64)
    elif condition == "missing":
        scene.unlink()
    elif condition == "corrupt":
        scene.write_bytes(b"not an image")
        observed = replace(observed, image_hash=sha(scene))
    elif condition == "outside_root":
        observed = replace(observed, image_path="../outside.png")
    elif condition == "wrong_target":
        target = "different-target"
    elif condition == "wrong_source":
        observed = replace(observed, data_source=DataSource.FIXTURE)
    result = matcher.detect_target(observed, target)
    assert result.status == Status.UNKNOWN
    assert result.bbox is None
    assert result.diagnostics["image_decoded"] is (condition == "occluded")


def test_blank_and_blurred_images_do_not_support_absence(synthetic_images, tmp_path):
    reference, scene = synthetic_images
    matcher = ImageMatcher(reference, sha(reference), "target", tmp_path)
    for name, image in [
        ("blank.png", np.full((400, 600), 128, dtype=np.uint8)),
        ("blurred.png", cv.GaussianBlur(cv.imdecode(np.frombuffer(scene.read_bytes(), np.uint8), cv.IMREAD_GRAYSCALE), (61, 61), 20)),
    ]:
        path = tmp_path / name
        save_image(path, image)
        result = matcher.detect_target(observation(path, tmp_path), "target")
        assert result.status == Status.UNKNOWN
        assert result.diagnostics["image_decoded"] is True


def test_registration_rejects_blank_reference(tmp_path):
    path = tmp_path / "blank.png"
    save_image(path, np.zeros((200, 300), dtype=np.uint8))
    with pytest.raises(ValueError, match="sharp, textured"):
        ImageMatcher(path, sha(path), "target", tmp_path)


def test_reference_cannot_change_after_registration(synthetic_images, tmp_path):
    reference, scene = synthetic_images
    matcher = ImageMatcher(reference, sha(reference), "target", tmp_path)
    reference.write_bytes(b"replaced reference")
    result = matcher.detect_target(observation(scene, tmp_path), "target")
    assert result.status == Status.UNKNOWN
    assert result.diagnostics["reason"] == "reference_image_changed"


def test_incomplete_reference_patch_is_not_confirmed(synthetic_images, tmp_path):
    reference, _ = synthetic_images
    matcher = ImageMatcher(reference, sha(reference), "target", tmp_path)
    image = cv.imdecode(np.frombuffer(reference.read_bytes(), np.uint8), cv.IMREAD_GRAYSCALE)
    partial = np.full((450, 650), 70, dtype=np.uint8)
    partial[120:185, 130:225] = image[90:155, 80:175]
    path = tmp_path / "small_patch.png"
    save_image(path, partial)
    result = matcher.detect_target(observation(path, tmp_path), "target")
    assert result.status in (Status.SUSPECTED, Status.UNKNOWN)


def test_public_reference_photo_matches_distinct_scene_photo():
    # Unmodified upstream OpenCV photographs; provenance is in SOURCES.json.
    reference = PUBLIC_SAMPLES / "box.png"
    scene = PUBLIC_SAMPLES / "box_in_scene.png"
    matcher = ImageMatcher(reference, sha(reference), "sample-box", PUBLIC_SAMPLES)
    observed = observation(scene, PUBLIC_SAMPLES, capture_source="OpenCV public sample photograph")
    assert observed.image_hash != sha(reference)
    result = matcher.detect_target(observed, "sample-box")
    assert result.status == Status.FOUND
    assert result.bbox is not None


@pytest.mark.parametrize("filename", ["apple.jpg", "orange.jpg", "fruits.jpg"])
def test_public_negative_photographs_do_not_confirm_registered_box(filename):
    reference = PUBLIC_SAMPLES / "box.png"
    scene = PUBLIC_SAMPLES / filename
    matcher = ImageMatcher(reference, sha(reference), "sample-box", PUBLIC_SAMPLES)
    result = matcher.detect_target(
        observation(scene, PUBLIC_SAMPLES, capture_source="OpenCV public sample photograph"), "sample-box"
    )
    assert result.status in (Status.UNKNOWN, Status.SUSPECTED)
    assert result.status != Status.NOT_FOUND_IN_VIEW
    assert result.bbox is None
