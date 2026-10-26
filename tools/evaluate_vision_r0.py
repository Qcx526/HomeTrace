"""Private same-data diagnostic comparison, never a production detector.

Preserves the existing matchers and thresholds. Registration crops are fixed;
scene crops come ONLY from actual, hash-bound YOLOE predictions. Labels are
attached after matching. No SearchCore, memory, network or Agent writes.
"""

import argparse
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import platform
import subprocess
from time import perf_counter

from hometrace.image_matcher import ImageMatcher
from hometrace.models import DataSource, Observation, TimestampBasis
from evaluate_registration_roi import GROUPS, label_category, validate_assets
from evaluate_team_photos import experimental_match
from neural_contract import validate_candidates
from vision_r0_metrics import summarize


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def require_private(path, repo):
    path = path.resolve()
    if not path.is_relative_to(repo) or subprocess.run(
        ["git", "-C", str(repo), "check-ignore", "--quiet", str(path)], capture_output=True
    ).returncode:
        raise ValueError("Inputs and outputs must remain in ignored repository directories")
    return path


def crop_bounds(bbox, width, height):
    """Only neural proposals reach here; exclusive crop, full-image coordinates."""
    if len(bbox) != 4 or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in bbox):
        raise ValueError("Invalid candidate bounds")
    x1, y1, x2, y2 = bbox
    if not (0 <= x1 < x2 <= width and 0 <= y1 < y2 <= height):
        raise ValueError("Out-of-frame candidate")
    return math.floor(x1), math.floor(y1), math.ceil(x2), math.ceil(y2)


def map_box(bbox, origin):
    if bbox is None:
        return None
    x, y = origin
    return [round(bbox[0]+x, 2), round(bbox[1]+y, 2), round(bbox[2]+x, 2), round(bbox[3]+y, 2)]


def bind_neural(rows, root, manifest, suggestions, protocol):
    """Do not trust labels, order or a scene name to bind prior real inference."""
    by_path = {r["path"]: r for r in manifest["files"]}
    expected = {r["path"] for r in manifest["files"] if r["path"] != suggestions[r["group"]]["file"]}
    indexed = {}
    for row in rows:
        request = row["request"]
        scene = Path(request["scene"]["path"]).resolve()
        if not scene.is_relative_to(root):
            raise ValueError("Neural scene outside verified input root")
        relative = scene.relative_to(root).as_posix()
        if relative not in expected or relative in indexed:
            raise ValueError("Missing, duplicate or unexpected neural scene")
        item = by_path[relative]
        suggestion = suggestions[item["group"]]
        reference = root / suggestion["file"]
        if (request["scene"]["sha256"] != item["sha256"]
            or request["scene"]["size"] != [item["width"], item["height"]]
            or Path(request["reference"]["path"]).resolve() != reference.resolve()
            or request["reference"]["sha256"] != digest(reference)
            or request["reference_roi"] != suggestion["xyxy_original_pixels"]
            or request["parameters"] != protocol["parameters"]
            or request["weights"]["sha256"] != protocol["weight_sha256"]):
            raise ValueError("Neural input/prompt/protocol binding mismatch")
        result = row["result"]
        if result["reason"] not in {"no_candidates", "candidate_requires_instance_verification"}:
            raise ValueError("Neural inference failed; do not treat as negative")
        candidates = validate_candidates(result["candidates"], item["width"], item["height"])
        details = row["private_details"]
        if details.get("returncode") != 0 or details.get("network_disabled") is not True:
            raise ValueError("Require successful local neural inference provenance")
        indexed[relative] = {"candidates": candidates, "runtime": {k: details[k] for k in
            ("predict_ms", "process_wall_ms", "device", "versions")}}
    if set(indexed) != expected:
        raise ValueError("Neural evaluation must cover all 20 scenes")
    return indexed


def production(reference, scene, root, target, roi):
    started = perf_counter()
    try:
        matcher = ImageMatcher(reference, digest(reference), target, root, reference_roi=roi)
    except ValueError:
        return {"status": None, "bbox": None, "executed": False,
            "diagnostics": {"reason": "reference_quality_gate_rejected", "elapsed_ms": round((perf_counter()-started)*1000, 3)}}
    obs = Observation("diagnosis", "offline", "2000-01-01T00:00:00+00:00", DataSource.RECORDED_IMAGE,
        image_path=scene.relative_to(root).as_posix(), image_hash=digest(scene),
        capture_source="Private static photo diagnosis; capture time unknown", timestamp_basis=TimestampBasis.DEMO_SEQUENCE)
    result = asdict(matcher.detect_target(obs, target))
    result["executed"] = True
    result["diagnostics"]["total_elapsed_ms"] = round((perf_counter()-started)*1000, 3)
    result["diagnostics"]["timing_scope"] = "elapsed_ms is detection; total_elapsed_ms includes registration"
    return result


def pair(reference, scene, method):
    result = experimental_match(reference, scene, method)
    result["executed"] = result["diagnostics"]["reason"] not in {
        "reference_low_sharpness_or_texture", "insufficient_reference_features"}
    return result


def save_pixels(path, pixels):
    import cv2
    ok, encoded = cv2.imencode(".png", pixels)
    if not ok:
        raise ValueError("Cannot save diagnostic crop")
    path.write_bytes(encoded.tobytes())


def composite(reference, scene_pixels, proposals, output):
    """All predicted crops, fixed SIFT; no human scene regions or labels."""
    started = perf_counter()
    attempts = []
    for index, proposal in enumerate(proposals):
        x1, y1, x2, y2 = crop_bounds(proposal["bbox"], scene_pixels.shape[1], scene_pixels.shape[0])
        crop = output / f"proposal-{index}.png"
        save_pixels(crop, scene_pixels[y1:y2, x1:x2])
        result = pair(reference, crop, "SIFT")
        result["bbox"] = map_box(result["bbox"], (x1, y1))
        attempts.append({"proposal": proposal, "crop_origin": [x1, y1], "result": result})
    accepted = [a for a in attempts if a["result"]["status"] == "FOUND"]
    result = accepted[0]["result"] if accepted else {
        "status": "SUSPECTED" if attempts else "UNKNOWN", "bbox": None,
        "diagnostics": {"reason": "instance_geometry_unverified" if attempts else "no_localization_candidates"}}
    return {**result, "executed": True, "proposal_count": len(proposals), "attempts": attempts,
        "verification_elapsed_ms": round((perf_counter()-started)*1000, 3),
        "identity_confirmed": False, "production_integration": False}


def public_row(row):
    metrics = row["result"].get("diagnostics", {})
    return {k: row[k] for k in ("method", "sample_id", "group", "label", "split", "status", "reason",
        "executed", "signal_kind", "candidate_count", "localized_target_verified")} | {
        "metrics": {k: metrics[k] for k in ("reference_keypoints", "scene_keypoints", "good_matches", "inliers",
            "inlier_ratio", "reference_coverage", "reference_sharpness", "sharpness", "elapsed_ms", "total_elapsed_ms",
            "timing_scope", "projected_area_fraction", "projected_visible_fraction") if k in metrics},
        "runtime": row.get("runtime"),
        "proposal_verifications": [{"status": a["result"]["status"], "reason": a["result"]["diagnostics"]["reason"],
            "metrics": {k: a["result"]["diagnostics"][k] for k in ("good_matches", "inliers", "inlier_ratio", "reference_coverage")
                if k in a["result"]["diagnostics"]}} for a in row["result"].get("attempts", [])]}


def run(root, output, neural_dir, repo):
    import cv2 as cv
    import numpy as np
    root, output, neural_dir = [require_private(p, repo) for p in (root, output, neural_dir)]
    if output.exists():
        raise ValueError("Output already exists; never overwrite evidence")
    manifest, suggestions, before = validate_assets(root, repo)
    protocol = read(neural_dir/"protocol.json")
    from evaluate_yoloe import validate_protocol
    validate_protocol(protocol)
    neural_path = neural_dir/"results.private.json"
    neural = bind_neural(read(neural_path), root, manifest, suggestions, protocol)
    source_paths = [Path(__file__), repo/"tools/evaluate_team_photos.py", repo/"tools/vision_r0_metrics.py", repo/"src/hometrace/image_matcher.py"]
    code_hashes = {p.relative_to(repo).as_posix(): digest(p) for p in source_paths}
    output.mkdir(parents=True)
    rows, registry = [], []
    for group in GROUPS:
        suggestion = suggestions[group]
        reference = root/suggestion["file"]
        ref_pixels = cv.imdecode(np.frombuffer(reference.read_bytes(), np.uint8), cv.IMREAD_GRAYSCALE)
        roi = suggestion["xyxy_original_pixels"]
        x1, y1, x2, y2 = roi
        ref_crop = output/f"{group}-reference.png"
        save_pixels(ref_crop, ref_pixels[y1:y2, x1:x2])
        registry.append({"sample_id": group+"/reference", "object_instance_id": group+"-registered-instance",
            "source_type": "real", "split": "registration_only", "image_path": suggestion["file"],
            "sha256": digest(reference), "target_box": roi, "target_box_review": "original fixed team registration ROI",
            "label": "reference", "expected_output": "registration quality check, not evaluation positive",
            "capture_batch": "unverified; reused collection", "viewpoint": "unknown", "lighting": "unmeasured",
            "occlusion": "unquantified", "similar_distractor": "unverified"})
        scenes = [r for r in manifest["files"] if r["group"] == group and r["path"] != suggestion["file"]]
        for index, item in enumerate(scenes, 1):
            sample_id = f"{group}/scene_{index:02}"
            scene = root/item["path"]
            folder = output/f"{group}-scene_{index:02}"
            folder.mkdir()
            pixels = cv.imdecode(np.frombuffer(scene.read_bytes(), np.uint8), cv.IMREAD_GRAYSCALE)
            predicted = neural[item["path"]]
            results = {
                "ORB_FULL": production(reference, scene, root, group, None),
                "ORB_ROI": production(reference, scene, root, group, roi),
                "SIFT_FULL": pair(reference, scene, "SIFT"),
                "SIFT_ROI": pair(ref_crop, scene, "SIFT"),
                "AKAZE_FULL": pair(reference, scene, "AKAZE"),
                "AKAZE_ROI": pair(ref_crop, scene, "AKAZE"),
                "YOLOE_CANDIDATE": {"status": "SUSPECTED" if predicted["candidates"] else "UNKNOWN", "executed": True,
                    "bbox": None, "diagnostics": {"reason": "candidate_requires_instance_verification" if predicted["candidates"] else "no_candidates"}},
                "YOLOE_SIFT_ROI": composite(ref_crop, pixels, predicted["candidates"], folder),
            }
            # Ground-truth metadata is used only after ALL detector calls returned.
            label = label_category(item["role_hint"])
            for method, result in results.items():
                row = {"method": method, "sample_id": sample_id, "group": group, "label": label,
                    "split": "diagnostic_reused", "status": result["status"], "reason": result["diagnostics"]["reason"],
                    "executed": result["executed"], "signal_kind": "neural_candidate" if method == "YOLOE_CANDIDATE" else "geometric_acceptance",
                    "candidate_count": len(predicted["candidates"]) if method.startswith("YOLOE") else 0,
                    "localized_target_verified": None, "result": result, "image_path": item["path"], "image_sha256": item["sha256"],
                    "reference_path": suggestion["file"], "reference_sha256": digest(reference), "reference_roi": roi}
                if method.startswith("YOLOE"):
                    row["runtime"] = predicted["runtime"]
                rows.append(row)
            registry.append({"sample_id": sample_id, "object_instance_id": group+"-registered-instance", "label": label,
                "source_type": "real", "split": "diagnostic_reused", "image_path": item["path"], "sha256": item["sha256"],
                "label_source": "original team human role_hint; unchanged", "target_box": None,
                "target_box_review": "PENDING_OWNER_ANNOTATION", "capture_batch": "unverified; entire reused collection kept together",
                "occlusion": "partial per existing label" if item["role_hint"] == "positive_observed_occluded" else "unquantified",
                "viewpoint": "unknown", "lighting": "unmeasured", "similar_distractor": "unverified", "original_visual_note": item.get("visual_note"),
                "expected_output": "target instance with valid localization" if label == "positive" else "no confirmed target" if label == "negative" else "unscored",
                "actual_outputs": {m: r["status"] for m,r in results.items()}})
            write(output/"results.private.json", rows)
            print(sample_id, " ".join(f"{m}={r['status']}" for m,r in results.items()), flush=True)
    _, after_roi, after = validate_assets(root, repo)
    if before != after or suggestions != after_roi or any(digest(repo/p) != h for p,h in code_hashes.items()):
        raise ValueError("Inputs, ROI or executed sources changed during run")
    public = [public_row(r) for r in rows]
    summary = {"schema_version": 1, "scope": "same-data diagnosis only; no independent test set", "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"],cwd=repo,text=True).strip(), "source_sha256": code_hashes,
        "environment": {"python": platform.python_version(), "opencv": cv.__version__, "numpy": np.__version__, "traditional_device": "cpu", "seed": 0, "threads": 1},
        "images": {"real": 24, "registered_references": 4, "scene_cases": 20, "augmented": 0, "synthetic": 0, "independent_test": 0},
        "planned_evaluations": len(rows), "originals_unchanged": True, "thresholds_unchanged": True,
        "neural_parameters": protocol["parameters"], "neural_model": protocol["model"], "weight_sha256": protocol["weight_sha256"],
        "metrics": summarize(public), "evaluations": public, "gate": "BLOCKED_NO_INDEPENDENT_DATA", "production_integration": False,
        "neural_inputs_sha256_private": "Recorded only in private binding.json", "localization_truth": "No owner-verified boxes; instance metrics unavailable"}
    write(output/"summary.public.json", summary)
    write(output/"registry.private.json", registry)
    write(output/"binding.private.json", {"manifest_sha256": digest(root/"asset_manifest.json"), "roi_sha256": digest(root/"REGISTRATION_ROI_SUGGESTIONS.json"),
        "neural_results_sha256": digest(neural_path), "neural_protocol_sha256": digest(neural_dir/"protocol.json"), "image_hashes": before})
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--neural-dir", type=Path, required=True, help="Fresh actual evaluate_yoloe output, not offline precheck")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = run(args.data_root, args.output_dir, args.neural_dir, Path(__file__).resolve().parents[1])
        print(json.dumps({"evaluations": result["planned_evaluations"], "gate": result["gate"]}))
        return 0  # experiment completed; the recognition gate is separately BLOCKED
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as exc:
        print("Vision R0 experiment failed: " + type(exc).__name__ + "; inspect private inputs locally")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
