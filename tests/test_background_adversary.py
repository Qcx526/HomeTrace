"""Synthetic infrastructure tests for reference-background confusion.

Every pixel is generated from fixed seeds. These are deliberately controllable
planar patterns, not private photographs or evidence of household recognition
accuracy. Presence/absence is asserted by the test only after the production
ImageMatcher has processed pixels; no labels enter the detector.
"""

import hashlib

import pytest

cv = pytest.importorskip("cv2")
np = pytest.importorskip("numpy")

from hometrace.image_matcher import ImageMatcher
from hometrace.models import DataSource, Observation, Status, TimestampBasis


def _texture(seed, width, height, count):
    """Distinct textured planes with spatially distributed ORB features."""
    rng = np.random.default_rng(seed)
    image = np.full((height, width), 225, dtype=np.uint8)
    for _ in range(count):
        x, y = (int(value) for value in rng.integers([8, 8], [width - 8, height - 8]))
        radius = int(rng.integers(2, 7))
        value = int(rng.integers(0, 180))
        cv.circle(image, (x, y), radius, value, -1)
    return image


def _write_image(path, image):
    success, encoded = cv.imencode(".png", image)
    assert success
    path.write_bytes(encoded.tobytes())
    return path


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _observe(path):
    return Observation(
        evidence_id="synthetic-infrastructure-observation",
        viewpoint_id="test-view",
        captured_at="2026-10-23T10:00:00+08:00",
        data_source=DataSource.RECORDED_IMAGE,
        image_path=path.name,
        image_hash=_sha(path),
        capture_source="fixed-seed synthetic planar test; not a photograph",
        timestamp_basis=TimestampBasis.DEMO_SEQUENCE,
    )


@pytest.fixture(params=[4729, 8633], ids=["seed-4729", "seed-8633"])
def adversarial_scene(request, tmp_path):
    seed = request.param
    background = _texture(seed, 640, 480, 1000)
    target = _texture(seed + 100, 260, 220, 210)
    roi = (210, 140, 470, 360)  # Original-reference xyxy, right/bottom exclusive.
    reference = background.copy()
    reference[roi[1]:roi[3], roi[0]:roi[2]] = target

    # The background occupies most of the registration photograph. A legacy
    # full-image registration can confirm that background after target removal.
    background_share = 1 - target.size / reference.size
    assert background_share > 0.80
    reference_path = _write_image(tmp_path / "reference.png", reference)
    empty_path = _write_image(tmp_path / "empty-shared-background.png", background)

    other_object = background.copy()
    other_object[roi[1]:roi[3], roi[0]:roi[2]] = _texture(seed + 200, 260, 220, 210)
    other_path = _write_image(tmp_path / "different-object-same-background.png", other_object)

    # A mild perspective transform retains the shared background but not the
    # object. This prevents relying only on exact pixel identity for a negative.
    background_corners = np.float32([[0, 0], [639, 0], [639, 479], [0, 479]])
    background_warp = cv.getPerspectiveTransform(
        background_corners, np.float32([[22, 17], [655, 24], [644, 496], [12, 483]])
    )
    warped_background = cv.warpPerspective(background, background_warp, (690, 520), borderValue=110)
    warped_path = _write_image(tmp_path / "changed-view-shared-background.png", warped_background)

    # The same object appears on an independently generated, larger full scene
    # under mild perspective. No scene ROI or expected location enters matcher.
    positive = _texture(seed + 300, 780, 580, 700)
    source_corners = np.float32([[0, 0], [259, 0], [259, 219], [0, 219]])
    destination_corners = np.float32([[365, 180], [628, 197], [610, 425], [348, 409]])
    transform = cv.getPerspectiveTransform(source_corners, destination_corners)
    warped_target = cv.warpPerspective(target, transform, (780, 580))
    mask = cv.warpPerspective(np.full(target.shape, 255, np.uint8), transform, (780, 580), flags=cv.INTER_NEAREST)
    positive[mask > 0] = warped_target[mask > 0]
    positive_path = _write_image(tmp_path / "object-on-independent-background.png", positive)
    expected_bbox = [348.0, 180.0, 628.0, 425.0]
    return reference_path, roi, empty_path, other_path, warped_path, positive_path, expected_bbox


def _matcher(reference, *, roi=None):
    return ImageMatcher(reference, _sha(reference), "synthetic-target", reference.parent, reference_roi=roi)


def test_full_reference_exposes_shared_background_false_confirmation(adversarial_scene):
    reference, _, empty, _, _, _, _ = adversarial_scene
    result = _matcher(reference).detect_target(_observe(empty), "synthetic-target")
    # An explicit counterexample, not an endorsed success: the object pixels
    # were removed, but whole-reference geometry is dominated by the background.
    assert result.status == Status.FOUND
    assert result.diagnostics["reference_preprocessing"] == "full_image"
    assert result.diagnostics["reference_coverage"] >= ImageMatcher.MIN_REFERENCE_COVERAGE
    assert result.diagnostics["inliers"] >= ImageMatcher.MIN_INLIERS
    assert result.bbox is not None


@pytest.mark.parametrize("negative_index", [2, 3, 4], ids=["empty-background", "different-object", "changed-background-view"])
def test_registration_roi_rejects_target_absent_backgrounds(adversarial_scene, negative_index):
    reference, roi, *_ = adversarial_scene
    negative = adversarial_scene[negative_index]
    result = _matcher(reference, roi=roi).detect_target(_observe(negative), "synthetic-target")
    assert result.diagnostics["image_decoded"] is True
    assert result.diagnostics["scene_keypoints"] >= ImageMatcher.MIN_SCENE_KEYPOINTS
    assert result.diagnostics["scene_preprocessing"] == "full_image"
    assert result.diagnostics["reference_roi"] == list(roi)
    assert result.status in (Status.SUSPECTED, Status.UNKNOWN)
    assert result.bbox is None


def test_registration_roi_finds_object_on_new_background_in_scene_coordinates(adversarial_scene):
    reference, roi, _, _, _, positive, expected_bbox = adversarial_scene
    matcher = _matcher(reference, roi=roi)
    result = matcher.detect_target(_observe(positive), "synthetic-target")
    assert result.status == Status.FOUND
    assert result.verification_kind == "reference_instance_match"
    assert result.diagnostics["reference_preprocessing"] == "registration_roi"
    assert result.diagnostics["reference_original_size"] == [640, 480]
    assert result.diagnostics["reference_size"] == [260, 220]
    assert result.diagnostics["scene_preprocessing"] == "full_image"
    assert result.diagnostics["inliers"] >= ImageMatcher.MIN_INLIERS
    assert result.diagnostics["inlier_ratio"] >= ImageMatcher.MIN_INLIER_RATIO
    assert result.diagnostics["reference_coverage"] >= ImageMatcher.MIN_REFERENCE_COVERAGE
    # Rasterization/feature localization permits a few pixels of estimation
    # error. The bounds must refer to the larger scene, never crop coordinates
    # or coordinates shifted by the registration ROI origin.
    assert result.bbox == pytest.approx(expected_bbox, abs=5.0)
    assert np.asarray(result.diagnostics["projected_corners"]) == pytest.approx(
        np.asarray([[365, 180], [628, 197], [610, 425], [348, 409]]), abs=5.0
    )
    x1, y1, x2, y2 = result.bbox
    assert 0 <= x1 < x2 < 780 and 0 <= y1 < y2 < 580
