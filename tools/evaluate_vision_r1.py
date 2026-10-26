"""Run isolated multi-reference experiments; read scoring labels after inference."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import platform
import subprocess

from evaluate_vision_r0 import require_private
from vision_r1 import MultiReferenceExperiment, VERSION, PARAMETERS, sha256
from vision_r1_metrics import summarize
from hometrace.image_matcher import ImageMatcher


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def public_results(rows, registrations):
    # No manifest IDs, input hashes, image paths, boxes, ROI, or free-form metadata.
    objects = {s: f"object_{i:02}" for i, s in enumerate(dict.fromkeys(r["object_instance_id"] for r in registrations), 1)}
    refs = {r["reference_id"]: f"reference_{i:02}" for i, r in enumerate(registrations, 1)}
    samples = {s: f"scene_{i:02}" for i, s in enumerate(dict.fromkeys(r["sample_id"] for r in rows), 1)}
    metric_keys = ("good_matches", "inliers", "inlier_ratio", "reference_coverage", "elapsed_ms", "scene_keypoints", "sharpness")
    public = [{"method": r["method"], "sample_id": samples[r["sample_id"]], "source_type": r["source_type"],
               "object_id": objects[r["object_instance_id"]], "status": r["status"], "reason": r["reason"],
               "executed": r["executed"], "total_elapsed_ms": r["total_elapsed_ms"],
               "attempts": [{"reference_id": refs[a["reference_id"]], "executed": a["executed"],
                   "geometric_signal": {"FOUND": "accepted_geometry", "SUSPECTED": "unconfirmed", "UNKNOWN": "rejected", None: "not_executed"}[a["raw_status"]],
                   "reason": a["diagnostics"]["reason"],
                   "metrics": {k: a["diagnostics"][k] for k in metric_keys if k in a["diagnostics"]}} for a in r["attempts"]]} for r in rows]
    quality = [{"reference_id": refs[r["reference_id"]], "object_id": objects[r["object_instance_id"]],
                **{k: r[k] for k in ("sharpness", "keypoints", "quality_pass", "quality_reason", "eligibility_reasons", "elapsed_ms")}}
               for r in registrations]
    return public, quality, samples


def run(data_root, manifest_path, labels_path, output, repo):
    import cv2
    import numpy
    data_root, manifest_path, labels_path, output = [require_private(p, repo) for p in (data_root, manifest_path, labels_path, output)]
    if output.exists():
        raise ValueError("Output already exists; never overwrite evidence")
    input_hashes = {"manifest": sha256(manifest_path), "labels": sha256(labels_path)}
    source_files = ["tools/vision_r1.py", "tools/vision_r1_metrics.py", "tools/evaluate_vision_r1.py",
                    "tools/evaluate_vision_r0.py", "src/hometrace/image_matcher.py", "src/hometrace/models.py"]
    code_hashes = {f: sha256(repo/f) for f in source_files}
    experiment = MultiReferenceExperiment(read(manifest_path), data_root)
    output.mkdir(parents=True)
    write(output/"registration.private.json", experiment.registrations)
    rows = []
    for index, scene in enumerate(experiment.manifest["scenes"], 1):
        results = experiment.infer(scene)
        rows.extend(results)
        print(f"scene_{index:02}: " + ", ".join(f"{r['method']}={r['status']} ({r['reason']})" for r in results), flush=True)
    # Predictions written before reading any labels. Re-score without re-detecting.
    write(output/"predictions.private.json", rows)
    prediction_hash = sha256(output/"predictions.private.json")
    labels = read(labels_path)
    if {l["sample_id"] for l in labels} != {s["sample_id"] for s in experiment.manifest["scenes"]}:
        raise ValueError("Labels must cover exactly the manifest scenes")
    metrics = summarize(rows, labels)
    if (sha256(manifest_path) != input_hashes["manifest"] or sha256(labels_path) != input_hashes["labels"] or
            any(sha256(data_root/p) != h for p, h in experiment.bindings.items()) or
            any(sha256(repo/p) != h for p, h in code_hashes.items())):
        raise ValueError("Inputs or code changed during experiment")
    public, quality, aliases = public_results(rows, experiment.registrations)
    object_aliases = {s: f"object_{i:02}" for i, s in enumerate(dict.fromkeys(r["object_instance_id"] for r in experiment.registrations), 1)}
    for groups in metrics["methods"].values():
        for group in groups.values():
            for scored in [group, *group["per_instance"].values()]:
                for sample in scored["samples"]:
                    sample["sample_id"] = aliases[sample["sample_id"]]
            group["per_instance"] = {object_aliases[k]: v for k, v in group["per_instance"].items()}
    info = {"generated_at": datetime.now(timezone.utc).isoformat(), "method_version": VERSION,
            "parameters": PARAMETERS, "production_thresholds": {k: getattr(ImageMatcher, k) for k in vars(ImageMatcher) if k.isupper()},
            "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip(),
            "source_sha256": code_hashes, "environment": {"python": platform.python_version(), "opencv": cv2.__version__,
                "numpy": numpy.__version__, "device": "cpu", "seed": 0, "threads": 1},
            "source_counts": {source: sum(s["source_type"] == source for s in experiment.manifest["scenes"])
                for source in ("real", "synthetic", "augmented")},
            "timing_scope": "registration separately; per-scene total includes all target and rival detections, shared by both method rows",
            "originals_unchanged": True, "production_integration": False, "identity_confirmed": False,
            "registration": quality, "evaluations": public, "metrics": metrics}
    write(output/"binding.private.json", {"inputs_sha256": input_hashes, "images_sha256": experiment.bindings,
        "prediction_sha256": prediction_hash, "public_sample_aliases": aliases})
    write(output/"summary.public.json", info)
    return info


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("data-root", "manifest", "labels", "output-dir"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    try:
        result = run(args.data_root, args.manifest, args.labels, args.output_dir, Path(__file__).resolve().parents[1])
        print(json.dumps({"evaluations": len(result["evaluations"]), "production_integration": False}))
        return 0
    except (ValueError, OSError, KeyError, TypeError, subprocess.SubprocessError) as exc:
        print("Vision R1 stopped: " + type(exc).__name__ + "; inspect private input locally")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
