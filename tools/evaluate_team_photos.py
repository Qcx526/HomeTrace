"""Private, reproducible photo audit; labels score results and never drive detection.

Run after installing .[vision]. Original images are neither rewritten nor copied.
Outputs (including CLI logs/databases) must remain in a Git-ignored local folder.
SIFT/AKAZE are bounded experiments, not production Search Core implementations.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from time import perf_counter

from hometrace.image_matcher import ImageMatcher
from hometrace.models import DataSource, Observation, TimestampBasis
from hometrace.recorded import load_recorded_scene, resolve_image_path


METHODS = ("ORB", "SIFT", "AKAZE")
SOURCES = [
    "https://docs.opencv.org/4.13.0/d1/de0/tutorial_py_feature_homography.html",
    "https://docs.opencv.org/4.13.0/dc/dc3/tutorial_py_matcher.html",
    "https://docs.opencv.org/4.13.0/db/d70/tutorial_akaze_matching.html",
]


def read_json(path: Path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate JSON field")
            result[key] = value
        return result
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def confined_file(root: Path, relative: str) -> Path:
    """Generic audit path; image paths additionally use production validation."""
    if (not isinstance(relative, str) or not relative or "\\" in relative
            or ":" in relative or "\x00" in relative or PurePosixPath(relative).is_absolute()
            or any(part in ("", ".", "..") for part in relative.split("/"))):
        raise ValueError("Require a confined relative path")
    result = (root / relative).resolve()
    if not result.is_relative_to(root.resolve()) or not result.is_file():
        raise ValueError("Expected an existing file inside the data root")
    return result


def validate_pack(root: Path, mapping_name: str) -> dict:
    """Verify manifest provenance, all mapping bytes, and the supplied SHA list."""
    mapping = read_json(confined_file(root, mapping_name))
    if mapping.get("scope", mapping.get("usage")) != "PRIVATE_LOCAL_EVALUATION_ONLY":
        raise ValueError("Dataset must explicitly declare private local evaluation")
    if not isinstance(mapping.get("source"), str) or not mapping["source"].strip():
        raise ValueError("Dataset must declare its source")
    timing = mapping.get("capture_times", mapping.get("timestamps"))
    if not isinstance(timing, str) or "unknown" not in timing.lower():
        raise ValueError("Team inputs must disclose unknown capture times")
    entries = mapping.get("files")
    if not isinstance(entries, list) or not entries:
        raise ValueError("Dataset requires a nonempty file inventory")
    verified = set()
    for entry in entries:
        relative = entry["english_path"]
        path = resolve_image_path(root, relative)
        confined_file(root, relative)
        if relative in verified:
            raise ValueError("Duplicate inventory image")
        if path.stat().st_size != entry["bytes"] or sha256(path) != entry["sha256"]:
            raise ValueError("Inventory image size or SHA256 mismatch")
        verified.add(relative)
    checksum_entries = set()
    for line in confined_file(root, "SHA256SUMS.txt").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        expected, relative = line.split(None, 1)
        relative = relative.strip().lstrip("*")
        if relative in checksum_entries or len(expected) != 64:
            raise ValueError("Invalid or duplicate checksum entry")
        if sha256(confined_file(root, relative)) != expected:
            raise ValueError("SHA256SUMS mismatch")
        checksum_entries.add(relative)
    if not verified <= checksum_entries:
        raise ValueError("SHA256SUMS must cover every inventory image")
    return mapping


def validate_tissue_scenes(root: Path, mapping: dict) -> dict:
    known = {entry["english_path"] for entry in mapping["files"]}
    scenes = {name: load_recorded_scene(root / f"{name}.json", root)
              for name in ("history", "moved", "missing")}
    histories = list(scenes["history"].observations.values())
    if not histories:
        raise ValueError("History requires at least one observation")
    history_end = max(datetime.fromisoformat(o.captured_at) for o in histories)
    for name, scene in scenes.items():
        ordered = list(scene.observations.values())
        if not ordered:
            raise ValueError("Scene requires observations")
        times = [datetime.fromisoformat(o.captured_at) for o in ordered]
        if any(later <= earlier for earlier, later in zip(times, times[1:])):
            raise ValueError("Scene times must follow the declared demo sequence")
        for observed in ordered:
            if observed.image_path not in known:
                raise ValueError("Manifest image missing from verified inventory")
            if observed.timestamp_basis != TimestampBasis.DEMO_SEQUENCE:
                raise ValueError("Unauthenticated team times must use demo_sequence")
            if name != "history" and datetime.fromisoformat(observed.captured_at) <= history_end:
                raise ValueError("Current observations must follow history")
    return scenes


def _geometry(cv, np, source, destination, reference_shape, scene_shape, metrics):
    """Same geometry/quality gates as ImageMatcher; never tune on sample labels."""
    cv.setRNGSeed(0)
    homography, mask = cv.findHomography(source, destination, cv.RANSAC, 3.0,
                                       maxIters=2000, confidence=0.995)
    if homography is None or mask is None or not np.isfinite(homography).all():
        return "SUSPECTED", "geometry_not_established", None
    inliers = mask.ravel().astype(bool)
    metrics["inliers"] = int(inliers.sum())
    metrics["inlier_ratio"] = round(float(inliers.mean()), 4)
    height, width = reference_shape
    points = source[inliers].reshape(-1, 2)
    if len(points) >= 3:
        metrics["reference_coverage"] = round(float(cv.contourArea(cv.convexHull(points))) / (width * height), 4)
    if metrics["inliers"] < ImageMatcher.MIN_INLIERS or metrics["inlier_ratio"] < ImageMatcher.MIN_INLIER_RATIO:
        return "SUSPECTED", "insufficient_geometric_inliers", None
    if metrics["reference_coverage"] < ImageMatcher.MIN_REFERENCE_COVERAGE:
        return "SUSPECTED", "reference_support_too_local", None
    corners = np.float32([[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]]).reshape(-1, 1, 2)
    projected = cv.perspectiveTransform(corners, homography).reshape(4, 2)
    if not np.isfinite(projected).all() or not cv.isContourConvex(projected):
        return "SUSPECTED", "invalid_projected_geometry", None
    scene_height, scene_width = scene_shape
    area = float(cv.contourArea(projected))
    fraction = area / (scene_width * scene_height)
    edges = np.linalg.norm(projected - np.roll(projected, 1, axis=0), axis=1)
    frame = np.float32([[0, 0], [scene_width - 1, 0], [scene_width - 1, scene_height - 1], [0, scene_height - 1]])
    intersection, _ = cv.intersectConvexConvex(projected, frame)
    visible = float(intersection) / area if area > 0 else 0.0
    metrics.update(projected_area_fraction=round(fraction, 4), projected_visible_fraction=round(visible, 4))
    if fraction < 0.002 or fraction > 1.2 or min(edges) < 12 or max(edges) / min(edges) > 10 or visible < 0.90:
        return "SUSPECTED", "projected_target_not_well_supported", None
    metrics["projected_corners"] = [[round(float(x), 2), round(float(y), 2)] for x, y in projected]
    bbox = [round(max(0.0, float(projected[:, 0].min())), 2),
            round(max(0.0, float(projected[:, 1].min())), 2),
            round(min(float(scene_width - 1), float(projected[:, 0].max())), 2),
            round(min(float(scene_height - 1), float(projected[:, 1].max())), 2)]
    return "FOUND", "verified_planar_reference_match", bbox


def experimental_match(reference: Path, scene: Path, method: str) -> dict:
    """Fixed SIFT/AKAZE ablation. No labels, source IDs or target location inputs.

    Both use ratio .75, unique scene descriptors and unchanged geometry gates.
    SIFT uses L2 (no Hamming cap; distance units differ), AKAZE Hamming <=64.
    Time includes reference extraction, unlike the production detect-only timer.
    """
    import cv2 as cv
    import numpy as np
    if method not in ("SIFT", "AKAZE"):
        raise ValueError("Experimental method must be SIFT or AKAZE")
    started = perf_counter()
    cv.setNumThreads(1)
    cv.setRNGSeed(0)
    metrics = dict(good_matches=0, inliers=0, inlier_ratio=0.0, reference_coverage=0.0,
                   reference_keypoints=0, scene_keypoints=0, opencv_version=cv.__version__, seed=0, threads=1,
                   timing_scope="reference_and_scene_processing")

    def finish(status, reason, bbox=None):
        metrics.update(reason=reason, elapsed_ms=round((perf_counter() - started) * 1000, 3))
        return dict(status=status, bbox=bbox, diagnostics=metrics)

    try:
        images = []
        for path in (reference, scene):
            if path.stat().st_size > ImageMatcher.MAX_IMAGE_BYTES:
                return finish("UNKNOWN", "image_file_too_large")
            image = cv.imdecode(np.frombuffer(path.read_bytes(), dtype=np.uint8), cv.IMREAD_GRAYSCALE)
            if image is None or image.size > ImageMatcher.MAX_IMAGE_PIXELS or min(image.shape) < 32:
                return finish("UNKNOWN", "unsupported_image_dimensions")
            images.append(image)
        ref, image = images
        metrics["reference_sharpness"] = round(float(cv.Laplacian(ref, cv.CV_64F).var()), 3)
        metrics["sharpness"] = round(float(cv.Laplacian(image, cv.CV_64F).var()), 3)
        metrics["scene_dimensions"] = [int(image.shape[1]), int(image.shape[0])]
        if metrics["reference_sharpness"] < ImageMatcher.MIN_SHARPNESS:
            return finish("UNKNOWN", "reference_low_sharpness_or_texture")
        if metrics["sharpness"] < ImageMatcher.MIN_SHARPNESS:
            return finish("UNKNOWN", "low_sharpness_or_texture")
        feature = cv.SIFT_create(nfeatures=2000) if method == "SIFT" else cv.AKAZE_create()
        kp1, des1 = feature.detectAndCompute(ref, None)
        kp2, des2 = feature.detectAndCompute(image, None)
        metrics.update(reference_keypoints=len(kp1), scene_keypoints=len(kp2))
        if des1 is None or len(kp1) < ImageMatcher.MIN_REFERENCE_KEYPOINTS:
            return finish("UNKNOWN", "insufficient_reference_features")
        if des2 is None or len(kp2) < ImageMatcher.MIN_SCENE_KEYPOINTS:
            return finish("UNKNOWN", "insufficient_scene_features")
        norm = cv.NORM_L2 if method == "SIFT" else cv.NORM_HAMMING
        candidates = cv.BFMatcher(norm).knnMatch(des1, des2, k=2)
        distinct = {}
        for neighbors in candidates:
            if len(neighbors) != 2:
                continue
            first, second = neighbors
            if first.distance < ImageMatcher.RATIO_THRESHOLD * second.distance and (method == "SIFT" or first.distance <= 64):
                previous = distinct.get(first.trainIdx)
                if previous is None or first.distance < previous.distance:
                    distinct[first.trainIdx] = first
        matches = sorted(distinct.values(), key=lambda match: (match.queryIdx, match.trainIdx))
        metrics["good_matches"] = len(matches)
        if len(matches) < 4:
            return finish("UNKNOWN", "no_verified_match")
        if len(matches) < ImageMatcher.MIN_GOOD_MATCHES:
            return finish("SUSPECTED", "insufficient_distinct_matches")
        src = np.float32([kp1[m.queryIdx].pt for m in matches]).reshape(-1, 1, 2)
        dst = np.float32([kp2[m.trainIdx].pt for m in matches]).reshape(-1, 1, 2)
        return finish(*_geometry(cv, np, src, dst, ref.shape, image.shape, metrics))
    except (cv.error, OSError):
        return finish("UNKNOWN", "image_processing_error")


def evaluate_pair(root: Path, reference: str, scene: str, object_id: str, method: str) -> dict:
    """All methods receive the same original image bytes; no annotations are inputs."""
    ref_path = resolve_image_path(root, reference)
    scene_path = resolve_image_path(root, scene)
    if method != "ORB":
        return experimental_match(ref_path, scene_path, method)
    started = perf_counter()
    try:
        matcher = ImageMatcher(ref_path, sha256(ref_path), object_id, root)
        observed = Observation("evaluation-only", "evaluation-only", "2000-01-01T01:00:00+00:00",
                               DataSource.RECORDED_IMAGE, image_path=scene,
                               image_hash=sha256(scene_path), capture_source="Private team photo evaluation",
                               timestamp_basis=TimestampBasis.DEMO_SEQUENCE)
        result = asdict(matcher.detect_target(observed, object_id))
        result["diagnostics"]["reference_sharpness"] = round(float(matcher.cv.Laplacian(matcher.reference_image, matcher.cv.CV_64F).var()), 3)
        result["diagnostics"]["timing_scope"] = "scene_processing_only"
        result["diagnostics"]["total_elapsed_ms"] = round((perf_counter() - started) * 1000, 3)
        return result
    except ValueError:
        return dict(status="UNKNOWN", bbox=None, diagnostics=dict(reason="reference_rejected",
                    good_matches=0, inliers=0, inlier_ratio=0.0, reference_coverage=0.0,
                    elapsed_ms=round((perf_counter() - started) * 1000, 3), timing_scope="reference_validation"))


def run_cli(tissue: Path, output: Path) -> list[dict]:
    results = []
    output.mkdir(parents=True, exist_ok=True)
    for scenario in ("moved", "missing"):
        database = output / f"{scenario}.sqlite3"
        # New IDs and later *demo-sequence* times cannot make old image bytes new.
        replay = read_json(tissue / f"{scenario}.json")
        for index, observation in enumerate(replay["observations"], 1):
            observation["evidence_id"] = f"hash-replay-{scenario}-{index}"
            observation["captured_at"] = f"2000-01-02T0{index}:00:00+00:00"
        hash_manifest = output / f"{scenario}-hash-replay.json"
        hash_manifest.write_text(json.dumps(replay, ensure_ascii=False, indent=2), encoding="utf-8")
        for stage, command, manifest in (("register", "register", tissue / "history.json"),
                                         ("search", "search", tissue / f"{scenario}.json"),
                                         ("replay", "search", tissue / f"{scenario}.json"),
                                         ("hash_replay", "search", hash_manifest)):
            directory = output / scenario / stage
            argv = [sys.executable, "-X", "utf8", "-m", "hometrace", command, "--db", str(database),
                    "--object-id", "tissue-pack", "--scene", str(manifest),
                    "--image-root", str(tissue), "--output-dir", str(directory)]
            if command == "register":
                argv += ["--reference", "images/ref_tissue.jpg", "--description", "Private team tissue package"]
            process = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace")
            directory.mkdir(parents=True, exist_ok=True)
            (directory / "cli.log").write_text(process.stdout + process.stderr, encoding="utf-8")
            result = dict(scenario=scenario, stage=stage, returncode=process.returncode, command=argv)
            if (directory / "report.json").is_file():
                result["report"] = read_json(directory / "report.json")
            results.append(result)
    return results


def public_summary(report: dict) -> dict:
    """Allowlist-only numerical/status summary; no raw paths, source text or images."""
    metrics = ("good_matches", "inliers", "inlier_ratio", "reference_coverage", "elapsed_ms", "total_elapsed_ms",
               "reason", "reference_keypoints", "scene_keypoints", "reference_sharpness", "sharpness",
               "projected_area_fraction", "projected_visible_fraction", "timing_scope")
    rows = []
    known_objects = {"tissue-pack", "dino-earbud-case", "keys", "pen", "ginkgo-thermos", "green-sleeve-glass"}
    for row in report["detections"]:
        result = row["result"]
        rows.append(dict(object_id=row["object_id"] if row["object_id"] in known_objects else "other-registered-object",
                         case=row["case"], method=row["method"],
                         expected_presence=row["expected_presence"], status=result["status"],
                         diagnostics={key: result["diagnostics"][key] for key in metrics if key in result["diagnostics"]}))
    cli = []
    for run in report.get("cli_runs", []):
        result = run.get("report", {})
        cli.append(dict(scenario=run["scenario"], stage=run["stage"], returncode=run["returncode"],
                        result_status=result.get("result_status"), location=result.get("location"),
                        confirmed_evidence_count=len(result.get("confirmed_evidence_ids", [])),
                        historical_evidence_count=len(result.get("historical_evidence", [])),
                        replay_rejections=sum(1 for event in result.get("events", [])
                                              if event["action"] == "view_result" and event["result"].get("reason") in ("replayed_image_content", "replayed_evidence")),
                        replay_reasons=sorted({event["result"]["reason"] for event in result.get("events", [])
                                              if event["action"] == "view_result" and event["result"].get("reason") in ("replayed_image_content", "replayed_evidence")})))
    return dict(schema_version=1, generated_at=report["generated_at"], data_source="private_team_photographs",
                navigation_mode="simulated_navigation", timestamp_basis="demo_sequence",
                capture_dates_authenticated=False, detections=rows, cli_runs=cli,
                validation={key: report.get("validation", {})[key]
                            for key in ("tissue_images", "other_images", "hashes", "paths", "demo_sequence_order", "originals_unchanged_after_run")
                            if key in report.get("validation", {})},
                configuration=dict(opencv_version=next((row["result"]["diagnostics"].get("opencv_version")
                                                        for row in report["detections"]
                                                        if row["result"]["diagnostics"].get("opencv_version")), None),
                                   seed=0, threads=1, ratio_threshold=ImageMatcher.RATIO_THRESHOLD,
                                   min_good_matches=ImageMatcher.MIN_GOOD_MATCHES,
                                   min_inliers=ImageMatcher.MIN_INLIERS,
                                   min_inlier_ratio=ImageMatcher.MIN_INLIER_RATIO,
                                   min_reference_coverage=ImageMatcher.MIN_REFERENCE_COVERAGE,
                                   min_sharpness=ImageMatcher.MIN_SHARPNESS,
                                   orb="Production implementation, Hamming <=64, up to 2000 features",
                                   sift="Experimental, L2 ratio only, up to 2000 features; distance units are not Hamming",
                                   akaze="Experimental, default extractor, Hamming <=64",
                                   geometry="RANSAC 3px, 2000 iterations, confidence .995; unchanged area/convexity/visibility gates"),
                bbox_coordinate_check="NOT_APPLICABLE_NO_FOUND" if all(row["status"] != "FOUND" for row in rows) else "REQUIRES_LOCAL_VISUAL_REVIEW",
                note="A bounded private sample evaluation, not accuracy or latency benchmark; no robot runs. Labels only score outcomes.",
                sources=SOURCES)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=Path("local_data"))
    parser.add_argument("--output-dir", type=Path, required=True, help="New, Git-ignored local output directory")
    args = parser.parse_args(argv)
    try:
        output = args.output_dir.resolve()
        if output.exists():
            raise ValueError("Output directory already exists; choose a fresh directory to avoid reusing evidence")
        repo = Path(__file__).resolve().parents[1]
        ignored = subprocess.run(["git", "check-ignore", "--quiet", str(output)], cwd=repo).returncode == 0
        if not ignored:
            raise ValueError("Output must be a Git-ignored local directory")
        tissue = (args.data_root / "team_tissue").resolve()
        others = (args.data_root / "team_other_objects").resolve()
        if not tissue.is_dir():
            raise ValueError(f"Missing team photo directory: {tissue}")
        tissue_mapping = validate_pack(tissue, "PHOTO_MAPPING.json")
        scenes = validate_tissue_scenes(tissue, tissue_mapping)
        other_mapping = validate_pack(others, "OBJECT_MAPPING.json") if others.is_dir() else None
        output.mkdir(parents=True)
        report = dict(generated_at=datetime.now(timezone.utc).isoformat(), detections=[], cli_runs=[],
                      validation=dict(tissue_images=len(tissue_mapping["files"]),
                                      other_images=len(other_mapping["files"]) if other_mapping else 0,
                                      hashes="passed", paths="passed", demo_sequence_order="passed"))
        cases = [("history_A", scenes["history"].observations["A"].image_path, True),
                 ("current_A", scenes["moved"].observations["A"].image_path, False),
                 ("current_B", scenes["moved"].observations["B"].image_path, True),
                 ("missing_B", scenes["missing"].observations["B"].image_path, False),
                 ("current_C", scenes["moved"].observations["C"].image_path, False)]
        for case, scene, expected in cases:
            for method in METHODS:
                result = evaluate_pair(tissue, "images/ref_tissue.jpg", scene, "tissue-pack", method)
                report["detections"].append(dict(object_id="tissue-pack", case=case, method=method, expected_presence=expected, result=result))
                print(f"tissue-pack {case} {method} {result['status']} {result['diagnostics']}", flush=True)
        report["cli_runs"] = run_cli(tissue, output / "cli")
        if other_mapping:
            scene_names = [entry["english_path"] for entry in other_mapping["files"] if entry.get("role") == "scene"]
            labels = other_mapping["manual_labels_external_only"]
            for object_id, reference in other_mapping["object_references"].items():
                for index, scene in enumerate(scene_names, 1):
                    for method in METHODS:
                        result = evaluate_pair(others, "images/" + reference, scene, object_id, method)
                        # External labels enter only after the detector returned.
                        expected = object_id in labels[PurePosixPath(scene).name]
                        report["detections"].append(dict(object_id=object_id, case=f"independent_scene_{index}", method=method, expected_presence=expected, result=result))
                        print(f"{object_id} scene_{index} {method} {result['status']} {result['diagnostics']}", flush=True)
        # A final hash check confirms that experiments did not mutate the originals.
        validate_pack(tissue, "PHOTO_MAPPING.json")
        if other_mapping:
            validate_pack(others, "OBJECT_MAPPING.json")
        report["validation"]["originals_unchanged_after_run"] = True
        (output / "evaluation.private.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (output / "summary.public.json").write_text(json.dumps(public_summary(report), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"Evaluation saved to {output}; originals unchanged; no real robot data.")
        return 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"Photo audit failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
