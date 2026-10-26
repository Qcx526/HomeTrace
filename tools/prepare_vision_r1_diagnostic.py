"""Adapt the existing verified 24-image pack without inventing extra views."""

import argparse
from pathlib import Path

from evaluate_registration_roi import validate_assets, GROUPS, label_category
from evaluate_vision_r0 import require_private
from evaluate_vision_r1 import write
from vision_r1 import sha256


def prepare(root, output, repo):
    root, output = require_private(root, repo), require_private(output, repo)
    if output.exists():
        raise ValueError("Never overwrite an existing registration manifest")
    inventory, rois, hashes = validate_assets(root, repo)
    objects, scenes, labels = [], [], []
    for group in GROUPS:
        reference = rois[group]
        oid = group + "-registered-instance"
        rid = group + "-original-reference"
        objects.append({"object_instance_id": oid, "baseline_reference_id": rid, "references": [{
            "reference_id": rid, "object_instance_id": oid, "path": reference["file"],
            "sha256": hashes[reference["file"]], "roi": reference["xyxy_original_pixels"],
            "view_id": "unknown", "visible_surface": "unknown", "surface_extent_id": "unknown",
            "capture_id": "unknown", "background_id": "unknown", "source_type": "real",
            "identity_reviewed": True, "roi_reviewed": True, "background_review": "pending"}]})
        images = [r for r in inventory["files"] if r["group"] == group and r["path"] != reference["file"]]
        for index, image in enumerate(images, 1):
            sid = f"{group}/scene_{index:02}"
            scenes.append({"sample_id": sid, "object_instance_id": oid, "path": image["path"],
                           "sha256": image["sha256"], "source_type": "real"})
            labels.append({"sample_id": sid, "object_instance_id": oid, "label": label_category(image["role_hint"]), "source_type": "real",
                           "split": "diagnostic_reused", "capture_batch": "unknown", "target_box": None,
                           "box_source": "none", "instance_reviews": {}})
    output.mkdir(parents=True)
    write(output/"manifest.private.json", {"schema_version": 1, "objects": objects, "scenes": scenes})
    write(output/"labels.private.json", labels)
    write(output/"provenance.private.json", {"input_hashes": hashes,
        "inventory_sha256": sha256(root/"asset_manifest.json"), "roi_sha256": sha256(root/"REGISTRATION_ROI_SUGGESTIONS.json"),
        "note": "Only original approved reference and ROI reused. Capture/view/background metadata unknown. No new views created."})
    return {"references": len(objects), "scenes": len(scenes), "new_reference_photos": 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    print(prepare(args.data_root, args.output_dir, Path(__file__).resolve().parents[1]))


if __name__ == "__main__":
    main()
