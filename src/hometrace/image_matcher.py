"""Local planar-reference matching using OpenCV, without label lookup or models.

This verifies a sufficiently supported visual appearance match. It does not
recognize a semantic category or distinguish physically identical copies.
"""

import hashlib
from pathlib import Path
from time import perf_counter

from .models import DataSource, DetectionResult, Observation, Status, validate_reference_roi


class ImageMatcher:
    """ORB + Hamming ratio test + geometric verification of one reference."""

    MIN_REFERENCE_KEYPOINTS = 32
    MIN_SCENE_KEYPOINTS = 20
    MIN_GOOD_MATCHES = 12
    MIN_INLIERS = 10
    MIN_INLIER_RATIO = 0.55
    MIN_REFERENCE_COVERAGE = 0.10
    RATIO_THRESHOLD = 0.75
    MAX_HAMMING_DISTANCE = 64
    MIN_SHARPNESS = 30.0
    MAX_IMAGE_PIXELS = 24_000_000
    MAX_IMAGE_BYTES = 25 * 1024 * 1024

    def __init__(
        self,
        reference_path: Path,
        reference_hash: str,
        object_id: str,
        image_root: Path,
        *,
        reference_roi: tuple[int, int, int, int] | list[int] | None = None,
        seed: int = 0,
        threads: int = 1,
    ) -> None:
        # Vision is optional: importing HomeTrace's P0 path requires no cv2/numpy.
        try:
            import cv2
            import numpy as np
        except ImportError as exc:
            raise ValueError('Image matching requires: pip install ".[vision]"') from exc
        if threads < 1:
            raise ValueError("threads must be at least 1")
        self.cv, self.np = cv2, np
        self.image_root = Path(image_root).resolve()
        self.object_id = object_id
        self.reference_hash = reference_hash
        self.seed, self.threads = seed, threads
        cv2.setNumThreads(threads)
        cv2.setRNGSeed(seed)
        self.reference_path = self._resolve(reference_path)
        if self.reference_path is None:
            raise ValueError("Reference image must be inside image_root")
        self.orb = cv2.ORB_create(nfeatures=2000)
        image, error = self._read_image(self.reference_path, reference_hash)
        if error:
            raise ValueError(f"Reference image is unusable: {error}")
        self.reference_original_size = (int(image.shape[1]), int(image.shape[0]))
        self.reference_roi = validate_reference_roi(reference_roi, self.reference_original_size)
        if self.reference_roi is not None:
            x1, y1, x2, y2 = self.reference_roi
            image = image[y1:y2, x1:x2].copy()
        self.reference_image = image
        sharpness = float(cv2.Laplacian(image, cv2.CV_64F).var())
        self.reference_sharpness = sharpness
        self.reference_keypoints, self.reference_descriptors = self.orb.detectAndCompute(image, None)
        if (
            sharpness < self.MIN_SHARPNESS
            or self.reference_descriptors is None
            or len(self.reference_keypoints) < self.MIN_REFERENCE_KEYPOINTS
        ):
            raise ValueError("Reference image needs a sharp, textured planar target")

    def _resolve(self, value: str | Path) -> Path | None:
        path = Path(value)
        path = path.resolve() if path.is_absolute() else (self.image_root / path).resolve()
        return path if path.is_relative_to(self.image_root) else None

    def _read_image(self, path: Path, expected_hash: str | None):
        """Decode the exact hashed bytes, including Unicode filenames on Windows."""
        if not expected_hash:
            return None, "missing_image_hash"
        try:
            if path.stat().st_size > self.MAX_IMAGE_BYTES:
                return None, "image_file_too_large"
            contents = path.read_bytes()
        except OSError:
            return None, "image_unreadable"
        if hashlib.sha256(contents).hexdigest() != expected_hash:
            return None, "image_hash_mismatch"
        try:
            image = self.cv.imdecode(self.np.frombuffer(contents, dtype=self.np.uint8), self.cv.IMREAD_GRAYSCALE)
        except self.cv.error:
            return None, "image_decode_failed"
        if image is None or image.size == 0:
            return None, "image_decode_failed"
        if image.size > self.MAX_IMAGE_PIXELS or min(image.shape) < 32:
            return None, "unsupported_image_dimensions"
        return image, None

    def detect_target(self, observation: Observation, object_id: str) -> DetectionResult:
        started = perf_counter()
        metrics = {
            "image_decoded": False,
            "reference_keypoints": len(self.reference_keypoints),
            "reference_sharpness": round(self.reference_sharpness, 3),
            "reference_image_hash": self.reference_hash,
            "reference_preprocessing": "registration_roi" if self.reference_roi else "full_image",
            "reference_roi": list(self.reference_roi) if self.reference_roi else None,
            "reference_original_size": list(self.reference_original_size),
            "reference_size": [int(self.reference_image.shape[1]), int(self.reference_image.shape[0])],
            "scene_preprocessing": "full_image",
            "scene_keypoints": 0,
            "good_matches": 0,
            "inliers": 0,
            "inlier_ratio": 0.0,
            "reference_coverage": 0.0,
            "opencv_version": self.cv.__version__,
            "seed": self.seed,
            "threads": self.threads,
        }

        def finish(status: Status, reason: str, bbox=None) -> DetectionResult:
            metrics["reason"] = reason
            metrics["elapsed_ms"] = round((perf_counter() - started) * 1000, 3)
            return DetectionResult(
                target_id=object_id,
                evidence_id=observation.evidence_id,
                status=status,
                matcher="opencv_orb_homography",
                score=metrics["inlier_ratio"] if metrics["good_matches"] else None,
                data_source=DataSource.RECORDED_IMAGE,
                verification_kind="reference_instance_match",
                diagnostics=metrics,
                bbox=bbox,
            )

        if object_id != self.object_id:
            return finish(Status.UNKNOWN, "wrong_registered_object")
        if observation.data_source != DataSource.RECORDED_IMAGE:
            return finish(Status.UNKNOWN, "unsupported_data_source")
        if observation.error:
            return finish(Status.UNKNOWN, observation.error)
        if not observation.image_path:
            return finish(Status.UNKNOWN, "missing_image_path")
        from .recorded import resolve_image_path

        try:
            path = resolve_image_path(self.image_root, observation.image_path)
        except ValueError:
            return finish(Status.UNKNOWN, "image_outside_root")
        # Cached reference features are valid only while its original bytes remain.
        try:
            if hashlib.sha256(self.reference_path.read_bytes()).hexdigest() != self.reference_hash:
                return finish(Status.UNKNOWN, "reference_image_changed")
        except OSError:
            return finish(Status.UNKNOWN, "reference_image_unreadable")
        image, error = self._read_image(path, observation.image_hash)
        if error:
            return finish(Status.UNKNOWN, error)
        metrics["image_decoded"] = True
        metrics["scene_size"] = [int(image.shape[1]), int(image.shape[0])]
        if observation.visibility_status != "clear":
            return finish(Status.UNKNOWN, "visibility_not_clear")
        try:
            cv, np = self.cv, self.np
            sharpness = float(cv.Laplacian(image, cv.CV_64F).var())
            metrics["sharpness"] = round(sharpness, 3)
            if sharpness < self.MIN_SHARPNESS:
                return finish(Status.UNKNOWN, "low_sharpness_or_texture")
            scene_keypoints, descriptors = self.orb.detectAndCompute(image, None)
            metrics["scene_keypoints"] = len(scene_keypoints)
            if descriptors is None or len(scene_keypoints) < self.MIN_SCENE_KEYPOINTS:
                return finish(Status.UNKNOWN, "insufficient_scene_features")
            matcher = cv.BFMatcher(cv.NORM_HAMMING)
            candidates = matcher.knnMatch(self.reference_descriptors, descriptors, k=2)
            # Different reference keypoints must not all vote for one scene point.
            distinct = {}
            for neighbors in candidates:
                if len(neighbors) != 2:
                    continue
                first, second = neighbors
                if first.distance < self.RATIO_THRESHOLD * second.distance and first.distance <= self.MAX_HAMMING_DISTANCE:
                    previous = distinct.get(first.trainIdx)
                    if previous is None or first.distance < previous.distance:
                        distinct[first.trainIdx] = first
            matches = sorted(distinct.values(), key=lambda match: (match.queryIdx, match.trainIdx))
            metrics["good_matches"] = len(matches)
            if len(matches) < 4:
                return finish(Status.UNKNOWN, "no_verified_match")
            if len(matches) < self.MIN_GOOD_MATCHES:
                return finish(Status.SUSPECTED, "insufficient_distinct_matches")
            source = np.float32([self.reference_keypoints[m.queryIdx].pt for m in matches]).reshape(-1, 1, 2)
            destination = np.float32([scene_keypoints[m.trainIdx].pt for m in matches]).reshape(-1, 1, 2)
            cv.setRNGSeed(self.seed)
            homography, mask = cv.findHomography(source, destination, cv.RANSAC, 3.0, maxIters=2000, confidence=0.995)
            if homography is None or mask is None or not np.isfinite(homography).all():
                return finish(Status.SUSPECTED, "geometry_not_established")
            inliers = mask.ravel().astype(bool)
            metrics["inliers"] = int(inliers.sum())
            metrics["inlier_ratio"] = round(float(inliers.mean()), 4)
            height, width = self.reference_image.shape
            reference_points = source[inliers].reshape(-1, 2)
            if len(reference_points) >= 3:
                metrics["reference_coverage"] = round(float(cv.contourArea(cv.convexHull(reference_points))) / (width * height), 4)
            if metrics["inliers"] < self.MIN_INLIERS or metrics["inlier_ratio"] < self.MIN_INLIER_RATIO:
                return finish(Status.SUSPECTED, "insufficient_geometric_inliers")
            if metrics["reference_coverage"] < self.MIN_REFERENCE_COVERAGE:
                return finish(Status.SUSPECTED, "reference_support_too_local")
            corners = np.float32([[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]]).reshape(-1, 1, 2)
            projected = cv.perspectiveTransform(corners, homography).reshape(4, 2)
            if not np.isfinite(projected).all() or not cv.isContourConvex(projected):
                return finish(Status.SUSPECTED, "invalid_projected_geometry")
            scene_height, scene_width = image.shape
            area = float(cv.contourArea(projected))
            area_fraction = area / (scene_width * scene_height)
            edges = np.linalg.norm(projected - np.roll(projected, 1, axis=0), axis=1)
            frame = np.float32([[0, 0], [scene_width - 1, 0], [scene_width - 1, scene_height - 1], [0, scene_height - 1]])
            intersection_area, _ = cv.intersectConvexConvex(projected, frame)
            visible_fraction = float(intersection_area) / area if area > 0 else 0.0
            metrics["projected_area_fraction"] = round(area_fraction, 4)
            metrics["projected_visible_fraction"] = round(visible_fraction, 4)
            if area_fraction < 0.002 or area_fraction > 1.2 or min(edges) < 12 or max(edges) / min(edges) > 10 or visible_fraction < 0.90:
                return finish(Status.SUSPECTED, "projected_target_not_well_supported")
            metrics["projected_corners"] = [[round(float(x), 2), round(float(y), 2)] for x, y in projected]
            bbox = [
                round(max(0.0, float(projected[:, 0].min())), 2),
                round(max(0.0, float(projected[:, 1].min())), 2),
                round(min(float(scene_width - 1), float(projected[:, 0].max())), 2),
                round(min(float(scene_height - 1), float(projected[:, 1].max())), 2),
            ]
            return finish(Status.FOUND, "verified_planar_reference_match", bbox)
        except cv.error:
            return finish(Status.UNKNOWN, "opencv_processing_error")
