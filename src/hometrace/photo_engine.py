"""Photo-flow appearance candidates using the unchanged optional ORB matcher.

An accepted homography is useful evidence for a person to review, not proof of
physical instance identity. This boundary therefore never emits FOUND. It does
not train a model, read scene labels, infer a location from a filename, or relax
the separate experimental multi-reference gallery's requirements.
"""

from collections.abc import Mapping
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import math
from pathlib import Path
import re
from threading import RLock
from time import perf_counter

from .image_matcher import ImageMatcher
from .models import DataSource, Observation, Status, TimestampBasis


_VISION_LOCK = RLock()
_SOURCE_KINDS = {"synthetic", "real_upload"}


def _identifier(value, field):
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValueError(f"{field} must be a nonempty trimmed string")
    return value


def _digest(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", value):
        raise ValueError("sha256 must contain 64 hexadecimal characters")
    return value.lower()


def _source_kind(value):
    if not isinstance(value, str) or value not in _SOURCE_KINDS:
        raise ValueError("source_kind must be synthetic or real_upload")
    return value


class PhotoSearchEngine:
    """One registered reference and full-frame uploaded scenes.

    Paths are relative to ``image_root``. The constructor checks the reference
    immediately; a poor or altered reference raises ValueError so the UI can ask
    for a clearer registration photo. Scene errors instead return UNKNOWN from
    ``observe``. Uploaded source kind is preserved, rather than mislabelling AI
    images as real photographs. Source kind itself is a caller declaration.

    ``quality()`` returns the actual constructor diagnostics. ``observe`` returns
    at most a SUSPECTED appearance candidate whose box passed the existing
    ImageMatcher geometry checks. The caller must keep subsequent human review
    separate from any autonomous production FOUND decision.
    """

    def __init__(self, image_root: Path, reference: dict, scenes: dict, object_id: str):
        self.image_root = Path(image_root).resolve()
        if not self.image_root.is_dir():
            raise ValueError("image_root must be an existing directory")
        self.object_id = _identifier(object_id, "object_id")
        if not isinstance(reference, Mapping):
            raise ValueError("reference must be an object")
        if not isinstance(scenes, Mapping):
            raise ValueError("scenes must map locations to image metadata")
        self.reference = deepcopy(dict(reference))
        self.scenes = deepcopy(dict(scenes))
        self.reference_hash = _digest(self.reference.get("sha256"))
        self.reference_source_kind = _source_kind(self.reference.get("source_kind"))
        path = self._path(self.reference.get("path"))
        with _VISION_LOCK:
            self.matcher = ImageMatcher(
                path, self.reference_hash, self.object_id, self.image_root,
                reference_roi=self.reference.get("roi"),
            )

    def _path(self, value):
        if not isinstance(value, str) or not value or Path(value).is_absolute():
            raise ValueError("Image path must be relative to image_root")
        path = (self.image_root / value).resolve()
        if not path.is_relative_to(self.image_root):
            raise ValueError("Image path escapes image_root")
        return path

    def quality(self) -> dict:
        """Actual reference quality; no physical identity assurance is implied."""
        matcher = self.matcher
        return {
            "reference_accepted": True,
            "object_id": self.object_id,
            "source_kind": self.reference_source_kind,
            "image_sha256": self.reference_hash,
            "reference_roi": list(matcher.reference_roi) if matcher.reference_roi else None,
            "original_size": list(matcher.reference_original_size),
            "reference_size": [int(matcher.reference_image.shape[1]), int(matcher.reference_image.shape[0])],
            "reference_keypoints": len(matcher.reference_keypoints),
            "reference_sharpness": round(matcher.reference_sharpness, 3),
            "matcher": "opencv_orb_homography",
            "training_steps": 0,
            "identity_confirmed": False,
        }

    def observe(self, location_id: str) -> dict:
        started = perf_counter()
        row = {
            "object_id": self.object_id,
            "location_id": location_id,
            "asset_id": None,
            "status": Status.UNKNOWN.value,
            "appearance_candidate": False,
            "identity_confirmed": False,
            "bbox": None,
            "diagnostic_bbox": None,
            "raw_match_status": None,
            "matcher": "opencv_orb_homography",
            "source_kind": None,
            "image_sha256": None,
            "reference_sha256": self.reference_hash,
            "diagnostics": {},
        }

        def finish(reason=None):
            if reason:
                row["diagnostics"]["reason"] = reason
            row["reason"] = row["diagnostics"].get("reason", "unverified")
            row["duration_ms"] = round((perf_counter() - started) * 1000, 3)
            return row

        if not isinstance(location_id, str) or location_id not in self.scenes:
            return finish("scene_not_available")
        scene = self.scenes[location_id]
        if not isinstance(scene, Mapping):
            return finish("invalid_scene_metadata")
        try:
            row["asset_id"] = _identifier(scene.get("asset_id"), "asset_id")
            row["source_kind"] = _source_kind(scene.get("source_kind"))
            row["image_sha256"] = _digest(scene.get("sha256"))
            dimensions = [scene.get("width"), scene.get("height")]
            if any(type(value) is not int or value < 32 for value in dimensions):
                raise ValueError("Invalid decoded image dimensions")
        except (TypeError, ValueError):
            return finish("invalid_scene_metadata")
        try:
            path = self._path(scene.get("path"))
        except (OSError, ValueError):
            return finish("image_outside_root")
        try:
            if path.stat().st_size > self.matcher.MAX_IMAGE_BYTES:
                return finish("image_file_too_large")
            contents = path.read_bytes()
        except OSError:
            return finish("image_unreadable")
        if hashlib.sha256(contents).hexdigest() != row["image_sha256"]:
            return finish("image_hash_mismatch")
        if row["image_sha256"] == self.reference_hash:
            return finish("reference_replay")

        # This timestamp is processing time in a demonstration sequence. It is
        # never presented as a verified photograph-capture time.
        observation = Observation(
            evidence_id="photo-" + row["asset_id"], viewpoint_id=location_id,
            captured_at=datetime.now(timezone.utc).isoformat(),
            data_source=DataSource.RECORDED_IMAGE,
            image_path=scene["path"], image_hash=row["image_sha256"],
            capture_source="uploaded_for_processing:" + row["source_kind"],
            timestamp_basis=TimestampBasis.DEMO_SEQUENCE,
        )
        with _VISION_LOCK:
            result = self.matcher.detect_target(observation, self.object_id)
        row["raw_match_status"] = result.status.value
        row["diagnostics"] = deepcopy(result.diagnostics)
        if result.diagnostics.get("image_decoded") and result.diagnostics.get("scene_size") != dimensions:
            return finish("scene_dimensions_mismatch")
        if result.status == Status.FOUND:
            box = result.bbox
            if (not isinstance(box, list) or len(box) != 4
                    or any(type(value) not in (int, float) or not math.isfinite(value) for value in box)
                    or not 0 <= box[0] < box[2] <= dimensions[0]
                    or not 0 <= box[1] < box[3] <= dimensions[1]):
                return finish("invalid_candidate_geometry")
            row["status"] = Status.SUSPECTED.value
            row["appearance_candidate"] = True
            row["bbox"] = list(box)
            row["diagnostics"]["raw_match_reason"] = row["diagnostics"].get("reason")
            return finish("appearance_candidate_requires_review")
        if result.status == Status.SUSPECTED:
            row["status"] = Status.SUSPECTED.value
        # The base matcher does not emit a usable box for rejected geometry.
        # Keep diagnostic_bbox empty rather than fabricating a target region.
        return finish()
