"""Isolated multi-reference ORB experiment. No production state or model writes.

Registration metadata is checked before inference; evaluation labels are not
accepted by this module. EXPERIMENTAL_ACCEPTED is geometric support, not FOUND.
"""

from dataclasses import asdict
import hashlib
from itertools import combinations
import json
import math
from pathlib import Path
import re
from time import perf_counter

from hometrace.image_matcher import ImageMatcher
from hometrace.models import DataSource, Observation, TimestampBasis, validate_reference_roi

VERSION = "multireference-orb-consensus/1"
PARAMETERS = {"max_references": 6, "quorum": 2, "box_iou": .5, "min_dhash_distance": 5,
              "seed": 0, "threads": 1, "feature_backend": "unchanged_production_ImageMatcher"}
SOURCES = {"real", "synthetic", "augmented"}
REF_FIELDS = {"reference_id", "object_instance_id", "path", "sha256", "roi", "view_id",
              "visible_surface", "surface_extent_id", "capture_id", "background_id", "source_type",
              "identity_reviewed", "roi_reviewed", "background_review"}
SCENE_FIELDS = {"sample_id", "object_instance_id", "path", "sha256", "source_type"}


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def exact_fields(value, fields):
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError("Missing or unexpected manifest fields")


def nonempty(value):
    return isinstance(value, str) and bool(value.strip()) and len(value) <= 200


def path_inside(root, value):
    if not isinstance(value, str) or not value or Path(value).is_absolute() or ".." in Path(value).parts:
        raise ValueError("Image path must be relative and inside data root")
    path = (root / value).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError("Image path escaped root")
    return path


def validate_manifest(manifest, root):
    exact_fields(manifest, {"schema_version", "objects", "scenes"})
    if type(manifest["schema_version"]) is not int or manifest["schema_version"] != 1:
        raise ValueError("Unsupported schema")
    if not isinstance(manifest["objects"], list) or not manifest["objects"] or not isinstance(manifest["scenes"], list):
        raise ValueError("Objects and scenes must be lists")
    object_ids, reference_ids, sample_ids, bindings = set(), set(), set(), {}
    by_object = {}
    for obj in manifest["objects"]:
        exact_fields(obj, {"object_instance_id", "baseline_reference_id", "references"})
        oid = obj["object_instance_id"]
        if not nonempty(oid) or oid in object_ids:
            raise ValueError("Invalid or duplicate instance ID")
        object_ids.add(oid)
        refs = obj["references"]
        if not isinstance(refs, list) or not 1 <= len(refs) <= PARAMETERS["max_references"]:
            raise ValueError("Each object requires 1..6 references")
        for ref in refs:
            exact_fields(ref, REF_FIELDS)
            if ref["object_instance_id"] != oid or not nonempty(ref["reference_id"]) or ref["reference_id"] in reference_ids:
                raise ValueError("Reference identity mismatch or duplicate ID")
            reference_ids.add(ref["reference_id"])
            for field in ("view_id", "visible_surface", "surface_extent_id", "capture_id", "background_id"):
                if not nonempty(ref[field]):
                    raise ValueError("Registration metadata must be text; use unknown when unknown")
            if any(type(ref[k]) is not bool for k in ("identity_reviewed", "roi_reviewed")):
                raise ValueError("Review flags must be bool")
            if ref["background_review"] not in {"pending", "object_dominant", "background_risk"}:
                raise ValueError("Unknown background review")
            roi = ref["roi"]
            if (not isinstance(roi, list) or len(roi) != 4 or any(type(x) is not int for x in roi)
                    or not 0 <= roi[0] < roi[2] or not 0 <= roi[1] < roi[3]):
                raise ValueError("ROI must be fixed integer xyxy")
        if obj["baseline_reference_id"] not in {r["reference_id"] for r in refs}:
            raise ValueError("Baseline reference must be chosen before evaluation")
        if len({r["source_type"] for r in refs}) != 1:
            raise ValueError("Do not mix real, augmented and synthetic reference votes")
        by_object[oid] = obj
    scene_images = set()
    for scene in manifest["scenes"]:
        exact_fields(scene, SCENE_FIELDS)
        if not nonempty(scene["sample_id"]) or scene["sample_id"] in sample_ids or scene["object_instance_id"] not in by_object:
            raise ValueError("Invalid scene or unknown target instance")
        sample_ids.add(scene["sample_id"])
        pair = (scene["object_instance_id"], scene["sha256"])
        if pair in scene_images:
            raise ValueError("Duplicate scene bytes for the same instance")
        scene_images.add(pair)
        if scene["source_type"] != by_object[scene["object_instance_id"]]["references"][0]["source_type"]:
            raise ValueError("Scene and reference source types differ")
    for item in [r for o in manifest["objects"] for r in o["references"]] + manifest["scenes"]:
        if item["source_type"] not in SOURCES or not isinstance(item["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", item["sha256"]):
            raise ValueError("Invalid source or SHA256")
        path = path_inside(root, item["path"])
        actual = sha256(path)
        if actual != item["sha256"]:
            raise ValueError("Input SHA256 mismatch")
        bindings[item["path"]] = actual
    # Exact duplicate references are diagnosed during registration, not votes.
    return bindings


def dhash(gray):
    import cv2
    small = cv2.resize(gray, (9, 8), interpolation=cv2.INTER_AREA)
    return sum(int(bit) << i for i, bit in enumerate((small[:, 1:] > small[:, :-1]).ravel()))


def pixel_hash(gray):
    return hashlib.sha256(str(gray.shape).encode("ascii") + gray.tobytes()).hexdigest()


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def box_iou(a, b):
    def valid(box):
        return (isinstance(box, (list, tuple)) and len(box) == 4 and
                all(type(v) in (int, float) and math.isfinite(v) for v in box) and
                0 <= box[0] < box[2] and 0 <= box[1] < box[3])
    if not valid(a) or not valid(b):
        return 0.0
    intersection = max(0, min(a[2], b[2])-max(a[0], b[0])) * max(0, min(a[3], b[3])-max(a[1], b[1]))
    return intersection / ((a[2]-a[0])*(a[3]-a[1]) + (b[2]-b[0])*(b[3]-b[1])-intersection)


def enroll(ref, root):
    import cv2 as cv
    import numpy as np
    started = perf_counter()
    record = {**ref, "sharpness": None, "keypoints": 0, "quality_pass": False, "dhash": None,
              "eligibility_reasons": [], "quality_reason": None}
    matcher = None
    # Also retain measured quality on rejected registrations; no invented score.
    try:
        path = path_inside(root, ref["path"])
        if sha256(path) != ref["sha256"]:
            raise ValueError("hash_changed")
        if path.stat().st_size > ImageMatcher.MAX_IMAGE_BYTES:
            raise ValueError("image_file_too_large")
        pixels = cv.imdecode(np.frombuffer(path.read_bytes(), np.uint8), cv.IMREAD_GRAYSCALE)
        if pixels is None or pixels.size > ImageMatcher.MAX_IMAGE_PIXELS or min(pixels.shape) < 32:
            raise ValueError("image_decode_or_dimensions")
        record["original_size"] = [int(pixels.shape[1]), int(pixels.shape[0])]
        record["pixels_sha256"] = pixel_hash(pixels)
        x1, y1, x2, y2 = validate_reference_roi(ref["roi"], record["original_size"])
        crop = pixels[y1:y2, x1:x2]
        cv.setNumThreads(1)
        cv.setRNGSeed(0)
        record["sharpness"] = round(float(cv.Laplacian(crop, cv.CV_64F).var()), 3)
        record["keypoints"] = len(cv.ORB_create(nfeatures=2000).detect(crop, None))
        record["dhash"] = dhash(crop)
        matcher = ImageMatcher(path, ref["sha256"], ref["object_instance_id"], root,
                               reference_roi=ref["roi"], seed=0, threads=1)
        record["quality_pass"] = True
        record["quality_reason"] = "production_reference_quality_pass"
    except (ValueError, OSError, cv.error):
        record["quality_reason"] = "reference_unusable_or_insufficient_quality"
        record["eligibility_reasons"].append(record["quality_reason"])
    for flag in ("identity_reviewed", "roi_reviewed"):
        if not ref[flag]:
            record["eligibility_reasons"].append(flag + "_missing")
    if ref["background_review"] != "object_dominant":
        record["eligibility_reasons"].append("background_review_incomplete_or_risk")
    for field in ("view_id", "visible_surface", "surface_extent_id", "capture_id", "background_id"):
        if ref[field].strip().lower() in {"unknown", "unverified", "pending"}:
            record["eligibility_reasons"].append(field + "_unknown")
    record["elapsed_ms"] = round((perf_counter()-started)*1000, 3)
    return record, matcher


def independent_pair(a, b):
    return (not a["eligibility_reasons"] and not b["eligibility_reasons"] and
            a["sha256"] != b["sha256"] and a["capture_id"] != b["capture_id"] and
            a["background_id"] != b["background_id"] and a["view_id"] != b["view_id"] and
            a["visible_surface"] == b["visible_surface"] and a["surface_extent_id"] == b["surface_extent_id"] and
            a["source_type"] == b["source_type"] and
            (a["dhash"] ^ b["dhash"]).bit_count() >= PARAMETERS["min_dhash_distance"])


def decision(status="UNKNOWN", reason="unverified", executed=True, bbox=None, **extra):
    return {"status": status, "reason": reason, "executed": executed, "bbox": bbox,
            "identity_confirmed": False, "production_integration": False, **extra}


def aggregate(registrations, attempts, target_id, replay=False):
    """Reject conflicting support and overlapping rival instances; no label input."""
    target = [r for r in registrations if r["object_instance_id"] == target_id]
    if replay:
        return decision(reason="reference_image_replay", executed=False)
    pairs = [(a, b) for a, b in combinations(target, 2) if independent_pair(a, b)]
    if not pairs:
        return decision(reason="insufficient_independent_references", executed=False)
    eligible = {r["reference_id"]: r for r in registrations if not r["eligibility_reasons"]}
    # Configured rival identities must each have at least one usable review.
    rival_ids = {r["object_instance_id"] for r in registrations} - {target_id}
    if any(not any(r["object_instance_id"] == oid for r in eligible.values()) for oid in rival_ids):
        return decision(reason="rival_control_unavailable", executed=False)
    by_ref = {a["reference_id"]: a for a in attempts}
    needed = {r["reference_id"] for r in eligible.values()}
    if any(rid not in by_ref or not by_ref[rid]["executed"] for rid in needed):
        return decision(reason="reference_attempt_unavailable", executed=False)
    accepted = [a for a in attempts if a["reference_id"] in eligible and a["raw_status"] == "FOUND"]
    supports = [a for a in accepted if eligible[a["reference_id"]]["object_instance_id"] == target_id]
    if any(box_iou(a["bbox"], a["bbox"]) != 1 for a in accepted):
        return decision(reason="invalid_support_box")
    if any(box_iou(a["bbox"], b["bbox"]) < PARAMETERS["box_iou"] for a, b in combinations(supports, 2)):
        return decision(reason="conflicting_reference_locations")
    ids = {s["reference_id"] for s in supports}
    if not any(a["reference_id"] in ids and b["reference_id"] in ids for a, b in pairs):
        return decision(reason="insufficient_consistent_support", supporting_reference_ids=sorted(ids))
    rivals = [a for a in accepted if eligible[a["reference_id"]]["object_instance_id"] != target_id]
    if any(box_iou(a["bbox"], b["bbox"]) >= PARAMETERS["box_iou"] for a in supports for b in rivals):
        return decision(reason="ambiguous_instance")
    chosen = min(supports, key=lambda a: a["reference_id"])
    return decision("EXPERIMENTAL_ACCEPTED", "cross_reference_geometric_support", bbox=chosen["bbox"],
                    supporting_reference_ids=sorted(ids), rival_coverage="configured" if rival_ids else "not_configured")


class MultiReferenceExperiment:
    def __init__(self, manifest, root):
        self.root = Path(root).resolve()
        self.manifest = manifest
        self.bindings = validate_manifest(manifest, self.root)
        import inspect
        self.frozen_signature = fingerprint({"manifest": manifest, "version": VERSION, "parameters": PARAMETERS,
            "matcher_source": sha256(Path(inspect.getfile(ImageMatcher))), "experiment_source": sha256(Path(__file__))})
        self.registrations, self.matchers = [], {}
        for obj in manifest["objects"]:
            for ref in obj["references"]:
                record, matcher = enroll(ref, self.root)
                self.registrations.append(record)
                self.matchers[ref["reference_id"]] = matcher
        hashes = [r["sha256"] for r in self.registrations]
        for record in self.registrations:
            if hashes.count(record["sha256"]) > 1:
                record["eligibility_reasons"].append("duplicate_reference_bytes")

    def infer(self, scene):
        started = perf_counter()
        oid = scene["object_instance_id"]
        obj = next(o for o in self.manifest["objects"] if o["object_instance_id"] == oid)
        replay = scene["sha256"] in {r["sha256"] for r in self.registrations}
        # Lossless re-encoding of a registered image is still a replay.
        import cv2
        import numpy as np
        contents = path_inside(self.root, scene["path"]).read_bytes()
        if hashlib.sha256(contents).hexdigest() != scene["sha256"]:
            raise ValueError("Scene changed after manifest validation")
        if len(contents) <= ImageMatcher.MAX_IMAGE_BYTES:
            try:
                pixels = cv2.imdecode(np.frombuffer(contents, np.uint8), cv2.IMREAD_GRAYSCALE)
            except cv2.error:
                pixels = None
            if pixels is not None and pixels.size <= ImageMatcher.MAX_IMAGE_PIXELS:
                replay = replay or pixel_hash(pixels) in {r.get("pixels_sha256") for r in self.registrations}
        attempts = []
        for ref in self.registrations:
            matcher = self.matchers[ref["reference_id"]]
            attempt = {"reference_id": ref["reference_id"], "executed": False, "raw_status": None,
                       "bbox": None, "diagnostics": {"reason": "reference_quality_rejected"}}
            if matcher is not None and not replay:
                obs = Observation(evidence_id=scene["sample_id"], viewpoint_id="experimental-static-photo",
                    captured_at="2000-01-01T00:00:00+00:00", data_source=DataSource.RECORDED_IMAGE,
                    image_path=scene["path"], image_hash=scene["sha256"],
                    capture_source="Offline diagnostic photo; no robot movement; capture time unknown",
                    timestamp_basis=TimestampBasis.DEMO_SEQUENCE)
                result = asdict(matcher.detect_target(obs, ref["object_instance_id"]))
                attempt.update(executed=bool(result["diagnostics"].get("image_decoded")),
                               raw_status=result["status"], bbox=result["bbox"], diagnostics=result["diagnostics"])
            attempts.append(attempt)
        baseline = next(a for a in attempts if a["reference_id"] == obj["baseline_reference_id"])
        single = decision("EXPERIMENTAL_ACCEPTED" if baseline["raw_status"] == "FOUND" else "UNKNOWN",
                          baseline["diagnostics"]["reason"], baseline["executed"], baseline["bbox"])
        if replay:
            single = decision(reason="reference_image_replay", executed=False)
        multi = aggregate(self.registrations, attempts, oid, replay)
        common = {"sample_id": scene["sample_id"], "source_type": scene["source_type"],
                  "object_instance_id": oid, "image_sha256": scene["sha256"], "attempts": attempts,
                  "total_elapsed_ms": round((perf_counter()-started)*1000, 3)}
        rows = [{**common, **single, "method": "SINGLE_ORB_ROI"},
                {**common, **multi, "method": "MULTI_ORB_CONSENSUS"}]
        for row in rows:
            row["prediction_fingerprint"] = fingerprint({"frozen_signature": self.frozen_signature,
                "scene": scene, **{k: row[k] for k in ("method", "status", "reason", "executed", "bbox")}})
        return rows
