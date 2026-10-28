"""Appearance boundary tests, using public OpenCV regression photos only."""

import hashlib
from pathlib import Path
import shutil

import pytest

pytest.importorskip("cv2")
pytest.importorskip("numpy")

from hometrace.image_matcher import ImageMatcher
from hometrace.photo_engine import PhotoSearchEngine


SAMPLES = Path(__file__).resolve().parents[1] / "examples" / "recorded_images"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def photos(tmp_path):
    import cv2
    import numpy as np

    for name in ("box.png", "box_in_scene.png", "apple.jpg"):
        shutil.copyfile(SAMPLES / name, tmp_path / name)
    reference = {"path": "box.png", "sha256": sha(tmp_path / "box.png"),
                 "roi": None, "source_kind": "real_upload"}
    scenes = {}
    for location, name in (("desk", "box_in_scene.png"), ("tray", "apple.jpg"), ("replay", "box.png")):
        im = cv2.imdecode(np.frombuffer((tmp_path / name).read_bytes(), np.uint8), cv2.IMREAD_COLOR)
        scenes[location] = {"asset_id": location, "path": name, "sha256": sha(tmp_path / name),
                            "source_kind": "real_upload", "width": im.shape[1], "height": im.shape[0]}
    return tmp_path, reference, scenes


def test_actual_geometry_acceptance_is_only_a_reviewable_candidate(photos):
    root, reference, scenes = photos
    engine = PhotoSearchEngine(root, reference, scenes, "arbitrary-instance")
    result = engine.observe("desk")
    assert result["raw_match_status"] == "FOUND"
    assert result["status"] == "SUSPECTED"
    assert result["appearance_candidate"] is True
    assert result["identity_confirmed"] is False
    assert len(result["bbox"]) == 4
    assert result["reason"] == "appearance_candidate_requires_review"
    assert result["diagnostics"]["raw_match_reason"] == "verified_planar_reference_match"
    assert result["diagnostics"]["inliers"] >= ImageMatcher.MIN_INLIERS
    assert result["diagnostics"]["reference_coverage"] >= ImageMatcher.MIN_REFERENCE_COVERAGE
    assert result["diagnostics"]["scene_preprocessing"] == "full_image"
    assert result["duration_ms"] >= 0
    assert result["image_sha256"] == scenes["desk"]["sha256"]


def test_quality_uses_actual_reference_features(photos):
    root, reference, scenes = photos
    quality = PhotoSearchEngine(root, reference, scenes, "target").quality()
    assert quality["reference_keypoints"] >= ImageMatcher.MIN_REFERENCE_KEYPOINTS
    assert quality["reference_sharpness"] >= ImageMatcher.MIN_SHARPNESS
    assert quality["training_steps"] == 0
    assert quality["identity_confirmed"] is False
    assert quality["image_sha256"] == reference["sha256"]


def test_negative_and_unavailable_scene_do_not_claim_absence_or_found(photos):
    root, reference, scenes = photos
    engine = PhotoSearchEngine(root, reference, scenes, "target")
    for location in ("tray", "missing"):
        result = engine.observe(location)
        assert result["status"] in {"UNKNOWN", "SUSPECTED"}
        assert result["appearance_candidate"] is False
        assert result["bbox"] is None
        assert result["diagnostic_bbox"] is None


def test_reference_replay_is_blocked_before_matcher(photos, monkeypatch):
    root, reference, scenes = photos
    engine = PhotoSearchEngine(root, reference, scenes, "target")

    def forbidden(*args):
        raise AssertionError("Reference replay must not invoke matcher")

    monkeypatch.setattr(engine.matcher, "detect_target", forbidden)
    result = engine.observe("replay")
    assert result["status"] == "UNKNOWN"
    assert result["raw_match_status"] is None
    assert result["reason"] == "reference_replay"


def test_hash_replay_remains_blocked_after_renaming(photos):
    root, reference, scenes = photos
    shutil.copyfile(root / "box.png", root / "seemingly-new-photo.png")
    scenes["replay"]["path"] = "seemingly-new-photo.png"
    assert PhotoSearchEngine(root, reference, scenes, "target").observe("replay")["reason"] == "reference_replay"


@pytest.mark.parametrize("source_kind", ["synthetic", "real_upload"])
def test_source_kind_survives_internal_legacy_image_contract(photos, source_kind):
    root, reference, scenes = photos
    reference["source_kind"] = source_kind
    scenes["desk"]["source_kind"] = source_kind
    engine = PhotoSearchEngine(root, reference, scenes, "target")
    assert engine.quality()["source_kind"] == source_kind
    assert engine.observe("desk")["source_kind"] == source_kind


@pytest.mark.parametrize(("condition", "reason"), [
    ("altered_bytes", "image_hash_mismatch"), ("missing", "image_unreadable"),
    ("corrupt", "image_decode_failed"), ("outside", "image_outside_root"),
    ("absolute", "image_outside_root"), ("dimensions", "scene_dimensions_mismatch"),
    ("hash", "invalid_scene_metadata"), ("source", "invalid_scene_metadata"),
    ("asset", "invalid_scene_metadata"), ("boolean_dimension", "invalid_scene_metadata"),
])
def test_scene_errors_return_unknown_without_a_candidate(photos, condition, reason):
    root, reference, scenes = photos
    scene = scenes["desk"]
    if condition in {"altered_bytes", "corrupt"}:
        (root / scene["path"]).write_bytes(b"corrupt image")
        if condition == "corrupt":
            scene["sha256"] = sha(root / scene["path"])
    elif condition == "missing":
        (root / scene["path"]).unlink()
    elif condition == "outside":
        scene["path"] = "../outside.png"
    elif condition == "absolute":
        scene["path"] = str(root / scene["path"])
    elif condition == "dimensions":
        scene["width"] += 1
    elif condition == "hash":
        scene["sha256"] = "invalid"
    elif condition == "source":
        scene["source_kind"] = "camera_verified"
    elif condition == "asset":
        scene["asset_id"] = ""
    elif condition == "boolean_dimension":
        scene["height"] = True
    result = PhotoSearchEngine(root, reference, scenes, "target").observe("desk")
    assert result["status"] == "UNKNOWN"
    assert result["reason"] == reason
    assert result["appearance_candidate"] is False
    assert result["bbox"] is None


def test_reference_changed_after_registration_cannot_use_cached_features(photos):
    root, reference, scenes = photos
    engine = PhotoSearchEngine(root, reference, scenes, "target")
    (root / reference["path"]).write_bytes(b"new bytes")
    result = engine.observe("desk")
    assert result["status"] == "UNKNOWN"
    assert result["reason"] == "reference_image_changed"


def test_bad_reference_cannot_be_registered(photos):
    root, reference, scenes = photos
    (root / reference["path"]).write_bytes(b"not an image")
    reference["sha256"] = sha(root / reference["path"])
    with pytest.raises(ValueError, match="unusable"):
        PhotoSearchEngine(root, reference, scenes, "target")


def test_scene_metadata_and_filename_do_not_supply_detector_answers(photos):
    root, reference, scenes = photos
    negative = scenes["tray"]
    shutil.copyfile(root / negative["path"], root / "TARGET_FOUND.png")
    negative.update(path="TARGET_FOUND.png", expected_status="FOUND", bbox=[0, 0, 100, 100])
    result = PhotoSearchEngine(root, reference, scenes, "target").observe("tray")
    assert result["appearance_candidate"] is False
    assert result["bbox"] is None
    assert result["status"] != "FOUND"


def test_input_dictionary_mutation_cannot_rebind_registered_scene(photos):
    root, reference, scenes = photos
    engine = PhotoSearchEngine(root, reference, scenes, "target")
    scenes["desk"]["sha256"] = "0" * 64
    reference["sha256"] = "0" * 64
    assert engine.observe("desk")["appearance_candidate"] is True
