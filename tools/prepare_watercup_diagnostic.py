"""Prepare a new, private WaterCup snapshot without editing R1 matchers.

Candidate ROIs and metadata come from a separate reviewed input file, never
from detection output. Unconfirmed labels stay uncertain. No auto-approval.
"""

import argparse
from pathlib import Path

from evaluate_vision_r0 import require_private
from evaluate_vision_r1 import read, write
from vision_r1 import sha256, enroll, independent_pair, validate_manifest


EXPECTED_FILES = {f"{i}.jpg" for i in range(1, 19)}
REFERENCE_FILES = ("1.jpg", "6.jpg", "10.jpg")
SCENE_FILES = ("8.jpg", "9.jpg", "11.jpg", "12.jpg", "13.jpg", "14.jpg", "15.jpg", "16.jpg", "17.jpg", "18.jpg")


def prepare(root, review_path, output, repo):
    import cv2 as cv
    import numpy as np
    root, review_path, output = [require_private(p, repo) for p in (root, review_path, output)]
    if not root.is_dir():
        raise ValueError("WaterCup data directory missing; no fallback allowed")
    if output.exists():
        raise ValueError("Output exists; never overwrite a review or experiment")
    paths = {p.name: p for p in root.iterdir() if p.is_file() and p.suffix.lower() in {".jpg", ".jpeg", ".png"}}
    if set(paths) != EXPECTED_FILES:
        raise ValueError("Require exactly the specified 18 original photographs")
    review_hash = sha256(review_path)
    review = read(review_path)
    if review["schema_version"] != 1 or set(review["photos"]) != EXPECTED_FILES:
        raise ValueError("Review draft must cover all 18 photos")
    before = {name: sha256(path) for name, path in paths.items()}
    inventory = []
    cv.setNumThreads(1)
    cv.setRNGSeed(0)
    for name in sorted(paths, key=lambda s: int(Path(s).stem)):
        record = review["photos"][name]
        if record["sha256"] != before[name]:
            raise ValueError("Review is bound to different input bytes")
        pixels = cv.imdecode(np.frombuffer(paths[name].read_bytes(), np.uint8), cv.IMREAD_GRAYSCALE)
        if pixels is None:
            raise ValueError("Cannot decode original photo")
        roi = record["candidate_roi"]
        if roi is not None:
            from hometrace.models import validate_reference_roi
            validate_reference_roi(roi, (pixels.shape[1], pixels.shape[0]))
        inventory.append({"path": name, "sha256": before[name], "width": int(pixels.shape[1]),
            "height": int(pixels.shape[0]), "sharpness": round(float(cv.Laplacian(pixels, cv.CV_64F).var()), 4),
            "orb_keypoints": len(cv.ORB_create(nfeatures=2000).detect(pixels, None)),
            "candidate_roi": roi, "roi_is_ground_truth": False,
            "capture_batch": record["capture_batch"], "source_type": "real", "split": "diagnostic_reused"})
    refs, registrations = [], []
    for name in REFERENCE_FILES:
        item = review["photos"][name]
        ref = dict(item["reference"])
        if ref["path"] != name or ref["sha256"] != before[name] or ref["roi"] != item["candidate_roi"]:
            raise ValueError("Reference must bind to the fixed reviewed ROI and input bytes")
        refs.append(ref)
        registration, _ = enroll(ref, root)
        registrations.append(registration)
    target = refs[0]["object_instance_id"]
    if refs[1]["object_instance_id"] != target or refs[2]["object_instance_id"] == target:
        raise ValueError("Require two target references and a distinct rival instance")
    scenes, labels = [], []
    for index, name in enumerate(SCENE_FILES, 1):
        item = review["photos"][name]
        if type(item["label_confirmed_by_owner"]) is not bool:
            raise ValueError("Label confirmation must be an explicit boolean")
        if item["label_confirmed_by_owner"] and not item.get("label_confirmation_source"):
            raise ValueError("Confirmed label requires provenance")
        label = item["proposed_label"] if item["label_confirmed_by_owner"] else "uncertain"
        if label not in {"positive", "negative", "uncertain"}:
            raise ValueError("Invalid label")
        sid = f"watercup_scene_{index:02}"
        scenes.append({"sample_id": sid, "object_instance_id": target, "path": name, "sha256": before[name], "source_type": "real"})
        # Candidate scene regions are never promoted to human truth boxes.
        labels.append({"sample_id": sid, "object_instance_id": target, "label": label, "source_type": "real",
            "split": "diagnostic_reused", "capture_batch": item["capture_batch"], "target_box": None,
            "box_source": "none", "instance_reviews": {}})
    manifest = {"schema_version": 1, "objects": [
        {"object_instance_id": target, "baseline_reference_id": refs[0]["reference_id"], "references": refs[:2]},
        {"object_instance_id": refs[2]["object_instance_id"], "baseline_reference_id": refs[2]["reference_id"], "references": refs[2:]}], "scenes": scenes}
    validate_manifest(manifest, root)
    if before != {name: sha256(path) for name, path in paths.items()} or sha256(review_path) != review_hash:
        raise ValueError("Input or review changed during preparation")
    pair = independent_pair(registrations[0], registrations[1])
    rival = not registrations[2]["eligibility_reasons"]
    output.mkdir(parents=True)
    write(output/"manifest.draft.private.json", manifest)
    write(output/"labels.private.json", labels)
    write(output/"inventory.private.json", inventory)
    write(output/"registration.private.json", registrations)
    write(output/"binding.private.json", {"review_sha256": review_hash, "inputs_sha256": before,
        "note": "Fixed diagnostic snapshot; not approved enrollment or independent validation", "originals_unchanged": True})
    quality = [{"alias": f"reference_{i:02}", **{k: r[k] for k in
        ("sharpness", "keypoints", "quality_pass", "quality_reason", "eligibility_reasons")}} for i, r in enumerate(registrations, 1)]
    result = {"images": 18, "scene_count": 10, "independent_test_images": 0,
        "target_reference_pair_eligible": pair, "rival_eligible": rival,
        "target_roi_dhash_distance": ((registrations[0]["dhash"] ^ registrations[1]["dhash"]).bit_count()
            if all(r["dhash"] is not None for r in registrations[:2]) else None),
        "registration": quality, "qualification_gate": "ELIGIBLE_FOR_DIAGNOSTIC_ONLY" if pair and rival else "BLOCKED",
        "unconfirmed_scene_labels": sum(not review["photos"][name]["label_confirmed_by_owner"] for name in SCENE_FILES),
        "originals_unchanged": True, "ground_truth_boxes_generated": 0}
    write(output/"qualification.public.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ("data-root", "review", "output-dir"):
        parser.add_argument("--"+option, type=Path, required=True)
    args = parser.parse_args()
    try:
        result = prepare(args.data_root, args.review, args.output_dir, Path(__file__).resolve().parents[1])
        print(result)
        return 0
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print("WaterCup preparation stopped: " + type(exc).__name__ + "; inspect private review locally")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
