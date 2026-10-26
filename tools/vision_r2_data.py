"""Prepare a private, human-reviewed YOLO dataset; never infer labels or splits."""

import argparse
import hashlib
import json
import math
import re
import shutil
import subprocess
from pathlib import Path


class Blocked(ValueError):
    """Required evidence is absent or inconsistent."""


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def require_private(repo, path):
    repo, path = Path(repo).resolve(), Path(path).resolve()
    try:
        relative = path.relative_to(repo)
    except ValueError as exc:
        raise Blocked("Private input/output must be inside an ignored repository directory") from exc
    result = subprocess.run(["git", "check-ignore", "--no-index", "-q", "--", str(relative)], cwd=repo, capture_output=True)
    if result.returncode != 0:
        raise Blocked("Private input/output is not Git ignored")
    return path


def reviewed(value, field):
    if not isinstance(value, dict) or value.get("confirmed") is not True:
        raise Blocked(f"{field}: human confirmation pending")
    if any(not isinstance(value.get(key), str) or not value[key].strip() for key in ("reviewer", "source")):
        raise Blocked(f"{field}: human review provenance missing")


def read_image(path):
    from PIL import Image

    try:
        with Image.open(path) as image:
            image.load()
            width, height = image.size
            orientation = image.getexif().get(274, 1)
            if orientation not in (0, 1, None):
                raise Blocked("Rotated EXIF image needs explicit coordinate-normalization review")
            return width, height
    except Blocked:
        raise
    except Exception as exc:
        raise Blocked("Image cannot be decoded") from exc


def validate_manifest(manifest, data_root):
    if not isinstance(manifest, dict) or type(manifest.get("schema_version")) is not int or manifest.get("schema_version") != 1:
        raise Blocked("Unsupported annotation schema")
    if manifest.get("class_name") != "sony_mug" or manifest.get("purpose") != "exploratory_fit":
        raise Blocked("Only sony_mug exploratory_fit is supported; no independent-test claim")
    if manifest.get("source_type") not in ("real_team_photo", "synthetic_software_fixture"):
        raise Blocked("Explicit image source_type required")
    reviewed(manifest.get("split_review"), "split/group allocation")
    rows = manifest.get("images")
    if not isinstance(rows, list) or not rows:
        raise Blocked("Image inventory is empty")
    root = Path(data_root).resolve()
    samples, ids, paths, groups, hashes = [], set(), set(), {}, {}
    for row in rows:
        if not isinstance(row, dict):
            raise Blocked("Image record must be an object")
        sample_id = row.get("sample_id")
        if not isinstance(sample_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", sample_id) or sample_id in ids:
            raise Blocked("Invalid or duplicate sample_id")
        ids.add(sample_id)
        relative = row.get("path")
        if not isinstance(relative, str) or Path(relative).is_absolute():
            raise Blocked("Image path must be relative")
        path = (root / relative).resolve()
        if not path.is_relative_to(root) or not path.is_file() or path in paths:
            raise Blocked("Missing, duplicate or escaping image path")
        if path.suffix.lower() not in (".jpg", ".jpeg", ".png", ".bmp", ".webp"):
            raise Blocked("Unsupported YOLO image extension")
        paths.add(path)
        digest = sha256(path)
        if row.get("sha256") != digest:
            raise Blocked("Original image SHA256 mismatch")
        width, height = read_image(path)
        split, label = row.get("split"), row.get("label")
        if split not in ("train", "val", "excluded") or label not in ("present", "absent", "uncertain"):
            raise Blocked("Missing explicit split or label")
        boxes = row.get("boxes")
        if not isinstance(boxes, list):
            raise Blocked("boxes must be a list")
        lines = []
        if split != "excluded":
            if label == "uncertain":
                raise Blocked("Uncertain samples must be excluded")
            reviewed(row.get("label_review"), f"{sample_id} label")
            group = row.get("group_id")
            if not isinstance(group, str) or group != group.strip() or group.lower() in ("", "unknown", "pending"):
                raise Blocked("Reviewed scene/near-duplicate group_id is required; capture_id may stay unknown")
            if group in groups and groups[group] != split:
                raise Blocked("Scene/near-duplicate group crosses train/val")
            groups[group] = split
            if digest in hashes and hashes[digest] != split:
                raise Blocked("Byte-identical image crosses train/val")
            hashes[digest] = split
            if (label == "present" and not boxes) or (label == "absent" and boxes):
                raise Blocked("Label and bounding boxes disagree")
            for box in boxes:
                if not isinstance(box, dict) or box.get("bbox_scope") != "full_visible_object":
                    raise Blocked("Human-reviewed full visible object box, including handle, required")
                reviewed(box.get("review"), f"{sample_id} box")
                coordinates = box.get("xyxy")
                if (not isinstance(coordinates, list) or len(coordinates) != 4
                        or any(type(v) not in (int, float) or not math.isfinite(v) for v in coordinates)):
                    raise Blocked("Invalid original-pixel box")
                x1, y1, x2, y2 = coordinates
                if not (0 <= x1 < x2 <= width and 0 <= y1 < y2 <= height):
                    raise Blocked("Bounding box outside decoded image")
                lines.append("0 " + " ".join(f"{v:.10f}" for v in ((x1 + x2) / (2 * width), (y1 + y2) / (2 * height), (x2 - x1) / width, (y2 - y1) / height)))
        samples.append({"sample_id": sample_id, "path": str(path), "sha256": digest,
                        "size": [width, height], "split": split, "label": label,
                        "group_id": row.get("group_id"), "yolo_lines": lines})
    if not all(any(s["split"] == split and s["label"] == "present" for s in samples) for split in ("train", "val")):
        raise Blocked("Reviewed train and development-val each require at least one positive; never random-split")
    return samples


def prepare_dataset(manifest_path, data_root, output, repo):
    manifest_path = require_private(repo, manifest_path)
    data_root = require_private(repo, data_root)
    output = require_private(repo, output)
    if output.exists():
        raise Blocked("Refusing to overwrite dataset output")
    manifest_digest = sha256(manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    samples = validate_manifest(manifest, data_root)
    output.mkdir(parents=True)
    for split in ("train", "val"):
        (output / "images" / split).mkdir(parents=True)
        (output / "labels" / split).mkdir(parents=True)
    files = {}
    for sample in samples:
        if sample["split"] == "excluded":
            continue
        source = Path(sample["path"])
        image_path = output / "images" / sample["split"] / (sample["sample_id"] + source.suffix.lower())
        label_path = output / "labels" / sample["split"] / (sample["sample_id"] + ".txt")
        shutil.copyfile(source, image_path)
        label_path.write_text("\n".join(sample["yolo_lines"]) + ("\n" if sample["yolo_lines"] else ""), encoding="utf-8")
        if sha256(image_path) != sample["sha256"]:
            raise Blocked("Copied image bytes changed")
        files[str(image_path.relative_to(output)).replace("\\", "/")] = sha256(image_path)
        files[str(label_path.relative_to(output)).replace("\\", "/")] = sha256(label_path)
    yaml_path = output / "data.yaml"
    yaml_path.write_text("path: " + json.dumps(str(output).replace("\\", "/")) + "\ntrain: images/train\nval: images/val\nnames:\n  0: sony_mug\n", encoding="utf-8")
    files["data.yaml"] = sha256(yaml_path)
    annotation_path = output / "annotation.private.json"
    shutil.copyfile(manifest_path, annotation_path)
    files["annotation.private.json"] = sha256(annotation_path)
    if sha256(manifest_path) != manifest_digest or any(sha256(s["path"]) != s["sha256"] for s in samples):
        raise Blocked("Source changed during preparation")
    record = {"schema_version": 1, "purpose": "exploratory_fit", "source_type": manifest["source_type"],
              "independent_test": False, "manifest_sha256": manifest_digest, "files": files,
              "original_data_root": str(data_root), "samples": samples,
              "counts": {split: sum(s["split"] == split for s in samples) for split in ("train", "val", "excluded")}}
    (output / "prepared.private.json").write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = prepare_dataset(args.manifest, args.data_root, args.output_dir, Path(__file__).resolve().parents[1])
        print(json.dumps({"status": "READY_FOR_EXPLORATORY_FIT", "counts": result["counts"], "independent_test": False}))
    except (Blocked, OSError, ValueError) as exc:
        print(json.dumps({"status": "BLOCKED", "reason": str(exc)}))
        raise SystemExit(2)


if __name__ == "__main__":
    main()
