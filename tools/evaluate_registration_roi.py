"""Run the production matcher on private images; publish only allowlisted statistics.

The archived baseline is loaded from Git, never from the supplied precheck JSON.
Only the reference is cropped. Human labels are attached after detection returns.
"""

import argparse
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import importlib.util
import inspect
import json
from pathlib import Path
import platform
import subprocess
import sys
from time import perf_counter

from hometrace.image_matcher import ImageMatcher
from hometrace.models import DataSource, Observation, TimestampBasis, validate_reference_roi
from hometrace.recorded import resolve_image_path


GROUPS = ("earbud", "panda", "keys", "tissue")
MODES = ("baseline_full_image", "registration_roi")
METRICS = ("reference_keypoints", "scene_keypoints", "good_matches", "inliers", "inlier_ratio",
           "reference_coverage", "projected_area_fraction", "projected_visible_fraction", "elapsed_ms")
CAPTURE_SOURCE = "Private team static photos; actual capture times unknown. Offline experiment sequence only; no robot observations."


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def label_category(role):
    if role in {"positive_observed", "positive_observed_occluded"}:
        return "positive"
    if role in {"negative", "negative_small_panda"}:
        return "negative"
    if role in {"uncertain", "uncertain_or_negative"}:
        return "uncertain"
    return "auxiliary"


def validate_assets(root, repo):
    import cv2
    import numpy as np
    manifest = read_json(root / "asset_manifest.json")
    if (manifest.get("privacy") != "local_only_not_for_public_git"
            or manifest.get("capture_time_verification") != "unknown"
            or manifest.get("source") != "user_uploaded_private_photos"
            or manifest.get("navigation") != "none"
            or manifest.get("all_labels") != "human_visual_review_only_not_detection_answers"):
        raise ValueError("Require the private static-photo provenance contract")
    files = manifest["files"]
    if len(files) != 24 or Counter(row["group"] for row in files) != Counter({group: 6 for group in GROUPS}):
        raise ValueError("Expected exactly four groups of six images")
    actual = {}
    for row in files:
        name = row["path"]
        path = resolve_image_path(root, name)
        if name in actual or row["group"] != name.split("/")[0]:
            raise ValueError("Duplicate image or inconsistent group")
        contents = path.read_bytes()
        digest = hashlib.sha256(contents).hexdigest()
        if digest != row["sha256"] or len(contents) != row["size_bytes"]:
            raise ValueError("Image SHA256 or byte count mismatch")
        image = cv2.imdecode(np.frombuffer(contents, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
        if image is None or (image.shape[1], image.shape[0]) != (row["width"], row["height"]):
            raise ValueError("Image decoded dimensions mismatch")
        actual[name] = digest
    checksums = {}
    prefix = root.relative_to(repo).as_posix() + "/"
    for line in (root / "SHA256SUMS.txt").read_text(encoding="utf-8").splitlines():
        if line.strip():
            digest, name = line.split(None, 1)
            name = name.strip().removeprefix("*")
            if not name.startswith(prefix) or name[len(prefix):] in checksums:
                raise ValueError("Checksum inventory path or duplicate mismatch")
            checksums[name[len(prefix):]] = digest
    if checksums != actual:
        raise ValueError("Checksum inventory must exactly match all 24 images")
    suggestions = read_json(root / "REGISTRATION_ROI_SUGGESTIONS.json")
    if set(suggestions) != set(GROUPS):
        raise ValueError("Expected one fixed ROI per group")
    for group, suggestion in suggestions.items():
        reference = next((r for r in files if r["path"] == suggestion["file"] and r["group"] == group), None)
        if reference is None or reference["role_hint"] != "reference_candidate":
            raise ValueError("ROI must name the declared registration reference")
        validate_reference_roi(suggestion["xyxy_original_pixels"], (reference["width"], reference["height"]))
    return manifest, suggestions, actual


def load_baseline(repo, output, ref):
    resolved = subprocess.run(["git", "-C", str(repo), "rev-parse", "--verify", ref + "^{commit}"], check=True, capture_output=True).stdout.decode().strip()
    source = subprocess.run(["git", "-C", str(repo), "show", resolved + ":src/hometrace/image_matcher.py"], check=True, capture_output=True).stdout
    saved = output / "baseline_image_matcher.py"
    saved.write_bytes(source)
    spec = importlib.util.spec_from_file_location("hometrace._archived_roi_baseline", saved)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.ImageMatcher, {"commit": resolved, "matcher_source_sha256": sha256(saved)}


def evaluate_group(root, group, mode, files, suggestion, matcher_class):
    reference = suggestion["file"]
    object_id = "registration-experiment-" + group
    options = {"reference_roi": tuple(suggestion["xyxy_original_pixels"])} if mode == "registration_roi" else {}
    started = perf_counter()
    try:
        matcher = matcher_class(root / reference, sha256(root / reference), object_id, root,
                                seed=0, threads=1, **options)
        enrollment = {"outcome": "accepted", "reason": None}
    except ValueError as exc:
        matcher = None
        enrollment = {"outcome": "enrollment_rejected", "reason": str(exc)}
    enrollment["elapsed_ms"] = round((perf_counter() - started) * 1000, 3)
    rows = []
    for index, row in enumerate((r for r in files if r["group"] == group and r["path"] != reference), 1):
        observation = Observation(
            evidence_id=f"{mode}-{group}-{index}", viewpoint_id=f"V{index}",
            captured_at=f"2000-01-01T00:00:{index:02}+00:00", data_source=DataSource.RECORDED_IMAGE,
            image_path=row["path"], image_hash=sha256(root / row["path"]),
            capture_source=CAPTURE_SOURCE, timestamp_basis=TimestampBasis.DEMO_SEQUENCE,
        )
        result = asdict(matcher.detect_target(observation, object_id)) if matcher else None
        # Evaluation labels enter only after the detector has finished. Filenames are
        # locator metadata; ImageMatcher has no access to the inventory or role hints.
        rows.append({"group": group, "mode": mode, "case": f"scene_{index:02}",
                     "evaluation_label": label_category(row["role_hint"]),
                     "detect_called": matcher is not None, "outcome": "detected" if matcher else "enrollment_rejected",
                     "enrollment": enrollment, "reference_path": reference,
                     "reference_hash": sha256(root / reference), "observation": asdict(observation),
                     "result": result})
    return rows


def public_summary(private):
    rows = []
    for row in private["evaluations"]:
        result = row["result"] or {}
        diagnostics = result.get("diagnostics", {})
        rows.append({"group": row["group"], "mode": row["mode"], "case": row["case"],
                     "evaluation_label": row["evaluation_label"], "detect_called": row["detect_called"],
                     "outcome": row["outcome"], "status": result.get("status"),
                     "reason": diagnostics.get("reason") if row["detect_called"] else "reference_quality_gate_rejected",
                     "metrics": {key: diagnostics[key] for key in METRICS if key in diagnostics}})
    counts = {}
    for mode in MODES:
        selected = [r for r in rows if r["mode"] == mode]
        counts[mode] = {
            "planned_evaluations": len(selected),
            "detect_calls": sum(r["detect_called"] for r in selected),
            "enrollment_rejected_cases": sum(r["outcome"] == "enrollment_rejected" for r in selected),
            "statuses": dict(Counter(r["status"] for r in selected if r["detect_called"])),
            "labels": {label: {"planned": sum(r["evaluation_label"] == label for r in selected),
                               "detect_calls": sum(r["evaluation_label"] == label and r["detect_called"] for r in selected),
                               "found": sum(r["evaluation_label"] == label and r["status"] == "FOUND" for r in selected)}
                       for label in ("positive", "negative", "uncertain", "auxiliary")},
        }
    return {"schema_version": 1, "experiment": "fixed_registration_roi_production_matcher",
            "generated_at": private["generated_at"], "environment": private["environment"],
            "baseline": "Archived production ImageMatcher from Git; original source retained privately",
            "baseline_code_commit": private["baseline"]["commit"],
            "input_images_validated": 24, "originals_unchanged": private["originals_unchanged"],
            "thresholds_unchanged": True, "scene_preprocessing": "full_image",
            "roi_selection": "Provided registration suggestions fixed before evaluation; no per-scene tuning",
            "capture_times": "unknown; no historical location claims",
            "navigation": "none in pair experiment; any separate CLI navigation is simulated",
            "evaluation_labels": "Human review only; uncertain and auxiliary excluded from positive/negative counts",
            "precheck_results_used_as_detections": False, "counts": counts, "evaluations": rows}


def run_cli_smoke(root, output, suggestion):
    """Empty history plus one staged view: no invented A-to-B capture history."""
    output.mkdir()
    base = {"schema_version": 1, "data_source": "recorded_image", "navigation_mode": "simulated_navigation",
            "timestamp_basis": "demo_sequence", "capture_source": CAPTURE_SOURCE,
            "viewpoints": [{"viewpoint_id": "V1", "name": "Offline experiment view"}], "observations": []}
    write_json(output / "empty-history.json", base)
    current = dict(base, observations=[{"evidence_id": "independent-empty-background", "viewpoint_id": "V1",
        "captured_at": "2000-01-01T00:01:00+00:00", "image_path": "earbud/images/scene_empty_wood.jpg",
        "visibility_status": "clear"}])
    write_json(output / "current.json", current)
    results = []
    for mode in ("full_image_current_api", "registration_roi"):
        database = output / f"{mode}.sqlite3"
        for stage in ("register", "search"):
            directory = output / mode / stage
            command = [sys.executable, "-m", "hometrace", stage, "--db", str(database), "--object-id", "earbud-roi-experiment",
                       "--scene", str(output / ("empty-history.json" if stage == "register" else "current.json")),
                       "--image-root", str(root), "--output-dir", str(directory)]
            if stage == "register":
                command.extend(["--reference", suggestion["file"]])
                if mode == "registration_roi":
                    command.extend(["--reference-roi", *map(str, suggestion["xyxy_original_pixels"])])
            process = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
            directory.mkdir(parents=True, exist_ok=True)
            (directory / "stdout.txt").write_text(process.stdout, encoding="utf-8")
            (directory / "stderr.txt").write_text(process.stderr, encoding="utf-8")
            report_path = directory / "report.json"
            results.append({"mode": mode, "stage": stage, "returncode": process.returncode,
                            "command": command, "report": read_json(report_path) if report_path.exists() else None})
    write_json(output / "cli.private.json", results)
    public = [{"mode": item["mode"], "stage": item["stage"], "returncode": item["returncode"],
               "result_status": item["report"].get("result_status") if item["report"] else None}
              for item in results]
    return public


def run_experiment(root, output, repo, baseline_ref="e3adca7"):
    import cv2
    import numpy as np
    root, output, repo = root.resolve(), output.resolve(), repo.resolve()
    if output.exists():
        raise ValueError("Output already exists; preserve the prior experiment")
    for path in (root, output):
        if not path.is_relative_to(repo) or subprocess.run(["git", "-C", str(repo), "check-ignore", "--quiet", str(path)], capture_output=True).returncode != 0:
            raise ValueError("Private input and output must be inside Git-ignored repository directories")
    manifest, suggestions, before = validate_assets(root, repo)
    executed_source = Path(inspect.getsourcefile(ImageMatcher)).resolve()
    if sha256(executed_source) != sha256(repo / "src/hometrace/image_matcher.py"):
        raise ValueError("Imported matcher differs from repository source; install the checkout in editable mode")
    output.mkdir(parents=True)
    (output / "current_image_matcher.py").write_bytes(executed_source.read_bytes())
    baseline, baseline_info = load_baseline(repo, output, baseline_ref)
    thresholds = {name: getattr(ImageMatcher, name) for name in dir(ImageMatcher) if name.isupper()}
    if any(getattr(baseline, name, None) != value for name, value in thresholds.items()):
        raise ValueError("Production matcher thresholds differ from the baseline")
    private = {"generated_at": datetime.now(timezone.utc).isoformat(), "environment": {
        "python": platform.python_version(), "os": platform.system(), "machine": platform.machine(),
        "opencv": cv2.__version__, "numpy": np.__version__, "seed": 0, "threads": 1},
        "baseline": baseline_info, "current_matcher_source_sha256": sha256(executed_source),
        "executed_matcher_source_path": str(executed_source),
        "thresholds": thresholds, "inventory": manifest, "fixed_roi_suggestions": suggestions,
        "original_hashes": before, "evaluations": [], "originals_unchanged": False}
    for mode, matcher in ((MODES[0], baseline), (MODES[1], ImageMatcher)):
        for group in GROUPS:
            rows = evaluate_group(root, group, mode, manifest["files"], suggestions[group], matcher)
            private["evaluations"].extend(rows)
            write_json(output / "evaluation.private.json", private)
            for row in rows:
                result = row["result"] or {}
                metrics = result.get("diagnostics", {})
                print(f"{mode} {group} {row['case']} {result.get('status', row['outcome'])} matches={metrics.get('good_matches')} inliers={metrics.get('inliers')} coverage={metrics.get('reference_coverage')}", flush=True)
    _, after_suggestions, after = validate_assets(root, repo)
    if before != after or suggestions != after_suggestions:
        raise ValueError("Original assets or fixed ROI definitions changed during evaluation")
    private["originals_unchanged"] = True
    write_json(output / "evaluation.private.json", private)
    summary = public_summary(private)
    summary["cli_smoke"] = run_cli_smoke(root, output / "cli", suggestions["earbud"])
    summary["cli_history"] = "Empty; staged demo_sequence timestamps, never asserted as actual capture times"
    _, final_suggestions, final_hashes = validate_assets(root, repo)
    if before != final_hashes or suggestions != final_suggestions or sha256(executed_source) != private["current_matcher_source_sha256"]:
        raise ValueError("Assets, ROI definitions or executed matcher changed during CLI validation")
    write_json(output / "summary.public.json", summary)
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--baseline-ref", default="e3adca7")
    args = parser.parse_args(argv)
    try:
        summary = run_experiment(args.data_root, args.output_dir, Path(__file__).resolve().parents[1], args.baseline_ref)
        print(json.dumps(summary["counts"], ensure_ascii=False))
        return 0
    except (OSError, ValueError, KeyError, TypeError, subprocess.CalledProcessError) as exc:
        print(f"Experiment failed: {type(exc).__name__}; inspect private inputs locally", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
