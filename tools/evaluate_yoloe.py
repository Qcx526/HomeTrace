"""Fixed exploratory YOLOE Visual Prompt experiment on private team photos.

Run with the normal HomeTrace [vision] environment. Heavy inference executes in
a separately installed Python and is killed on timeout. No production integration.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from time import perf_counter

from evaluate_registration_roi import validate_assets, label_category
from neural_contract import run_candidate_provider, public_summary


def validate_protocol(protocol):
    parameters = protocol.get("parameters")
    fixed = {"conf": 0.25, "iou": 0.7, "imgsz": 640, "max_det": 100, "half": False, "seed": 0}
    if not isinstance(parameters, dict) or set(parameters) != set(fixed) | {"device"}:
        raise ValueError("Unexpected inference parameters")
    if any(type(parameters[k]) is not type(v) or parameters[k] != v for k, v in fixed.items()):
        raise ValueError("This experiment uses fixed parameters; no per-sample tuning")
    if parameters["device"] not in ("cuda:0", "cpu"):
        raise ValueError("Explicit CPU or CUDA device required")
    if type(protocol.get("timeout_seconds_per_scene")) is not int or not 1 <= protocol["timeout_seconds_per_scene"] <= 300:
        raise ValueError("Inference timeout must be 1..300 seconds")
    if protocol.get("model") != "yoloe-11s-seg.pt" or protocol.get("ultralytics") != "8.3.221":
        raise ValueError("Unexpected model version")
    if protocol.get("base_commit") != "e5732b4024d90cc190aedb77f98f626b11e982cd" or protocol.get("weight_url") != "https://github.com/ultralytics/assets/releases/download/v8.3.0/yoloe-11s-seg.pt":
        raise ValueError("Unexpected experiment source")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def require_ignored(path, repo):
    if not path.is_relative_to(repo) or subprocess.run(
        ["git", "-C", str(repo), "check-ignore", "--quiet", str(path)], capture_output=True).returncode:
        raise ValueError("Private data, model and outputs must stay in Git-ignored repository paths")


def run(root, output, repo, python, weights, protocol_path, *, smoke=False):
    root, output, python, weights = (p.resolve() for p in (root, output, python, weights))
    for path in (root, output, weights, protocol_path.resolve()):
        require_ignored(path, repo)
    if output.exists():
        raise ValueError("Output already exists; use a new directory")
    protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
    validate_protocol(protocol)
    if weights.name != protocol["model"] or digest(weights) != protocol["weight_sha256"]:
        raise ValueError("Weights do not match the fixed experiment protocol")
    if not python.is_file():
        raise ValueError("Independent inference Python is missing")
    manifest, suggestions, hashes = validate_assets(root, repo)
    by_path = {r["path"]: r for r in manifest["files"]}
    output.mkdir(parents=True)
    write_json(output / "protocol.json", protocol)
    rows = []
    chosen = ("earbud",) if smoke else ("earbud", "panda", "keys", "tissue")
    for group in chosen:
        reference_name = suggestions[group]["file"]
        reference = by_path[reference_name]
        scenes = [r for r in manifest["files"] if r["group"] == group and r["path"] != reference_name]
        for index, scene in enumerate(scenes, 1):
            # Gate 0 chooses the known empty-wood challenge, fixed before output.
            if smoke and not scene["path"].endswith("scene_empty_wood.jpg"):
                continue
            case = f"scene_{index:02}"
            case_root = output / f"{group}-{case}"
            case_root.mkdir()
            request = {"reference": {"path": str(root / reference_name), "sha256": hashes[reference_name],
                "size": [reference["width"], reference["height"]]},
                "scene": {"path": str(root / scene["path"]), "sha256": hashes[scene["path"]],
                "size": [scene["width"], scene["height"]]},
                "reference_roi": suggestions[group]["xyxy_original_pixels"],
                "weights": {"path": str(weights), "sha256": protocol["weight_sha256"]},
                "parameters": protocol["parameters"], "output": str(case_root / "inference")}
            request_path = case_root / "request.private.json"
            write_json(request_path, request)
            details = {}
            def predict():
                started = perf_counter()
                try:
                    process = subprocess.run([str(python), "-X", "utf8", str(repo / "tools/yoloe_worker.py"), str(request_path)],
                        capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=case_root,
                        timeout=protocol["timeout_seconds_per_scene"], env=dict(os.environ, PYTHONUTF8="1"))
                except subprocess.TimeoutExpired as exc:
                    for name, content in (("stdout", exc.stdout), ("stderr", exc.stderr)):
                        text = content.decode("utf-8", errors="replace") if isinstance(content, bytes) else content or ""
                        (case_root / f"{name}.private.txt").write_text(text, encoding="utf-8")
                    details.update(timed_out=True, process_wall_ms=round((perf_counter() - started) * 1000, 3))
                    raise
                (case_root / "stdout.private.txt").write_text(process.stdout, encoding="utf-8")
                (case_root / "stderr.private.txt").write_text(process.stderr, encoding="utf-8")
                details.update(returncode=process.returncode, process_wall_ms=round((perf_counter() - started) * 1000, 3))
                if process.returncode:
                    raise RuntimeError("Inference worker failed; inspect private logs")
                details.update(json.loads((case_root / "inference/result.private.json").read_text(encoding="utf-8")))
                return details["candidates"]
            result = run_candidate_provider(predict, image_path=root / scene["path"], expected_sha256=hashes[scene["path"]],
                width=scene["width"], height=scene["height"])
            # Labels are attached only AFTER the label-free worker has exited.
            row = {"group": group, "case": case, "evaluation_label": label_category(scene["role_hint"]),
                   "result": result, "private_details": details, "request": request}
            rows.append(row)
            write_json(output / "results.private.json", rows)
            print(group, case, result["status"], result["reason"], len(result["candidates"]), flush=True)
    _, final_roi, after = validate_assets(root, repo)
    if hashes != after or suggestions != final_roi or digest(weights) != protocol["weight_sha256"]:
        raise ValueError("Images, prompts or weights changed during evaluation")
    summary = public_summary(rows)
    summary.update(generated_at_utc=datetime.now(timezone.utc).isoformat(), baseline_commit=protocol["base_commit"],
        original_images_verified=24, originals_unchanged=True, scope="gate_0_smoke" if smoke else "gate_1_full_dataset",
        parameters=protocol["parameters"], model=protocol["model"], weight_sha256=protocol["weight_sha256"],
        weight_url=protocol["weight_url"], protocol_sha256=digest(protocol_path),
        limitations=["Exploratory fixed-parameter evaluation on previously reviewed photos, no held-out set",
            "Candidate class object0 is bound to registration, not a semantic or instance identity claim",
            "No robot navigation or SearchCore/SQLite state writes in this experiment",
            "No candidate on an image does not prove absence", "Private original-coordinate boxes remain local"])
    for public, private in zip(summary["evaluations"], rows):
        details = private["private_details"]
        public["runtime"] = {k: details[k] for k in ("predict_ms", "model_load_ms", "process_wall_ms", "speed_ms",
            "device", "gpu_name", "cuda_runtime", "compute_capability", "peak_allocated_bytes", "peak_reserved_bytes",
            "versions", "network_disabled") if k in details}
        public["prompt_class"] = "object0"
    failures = sum(r["result"]["reason"] not in {"no_candidates", "candidate_requires_instance_verification"} for r in rows)
    negative_candidates = summary["counts"]["negative"]["candidate_cases"]
    positive_candidates = summary["counts"]["positive"]["candidate_cases"]
    summary["gate"] = "BLOCKED" if failures else "SMOKE_COMPLETED" if smoke else (
        "NO_GO" if negative_candidates or not positive_candidates else "REQUIRES_LOCALIZATION_REVIEW")
    summary["integration_enabled"] = False
    summary["gate_reason"] = ("Inference failures" if failures else
        "Definite negative scenes produce unconfirmed candidates" if negative_candidates else
        "Full evaluation and/or manual localization review required; not proof of instance identity")
    write_json(output / "summary.public.json", summary)
    return summary


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--data-root", required=True, type=Path)
    p.add_argument("--output-dir", required=True, type=Path)
    p.add_argument("--python", required=True, type=Path)
    p.add_argument("--weights", required=True, type=Path)
    p.add_argument("--protocol", required=True, type=Path)
    p.add_argument("--smoke", action="store_true")
    args = p.parse_args()
    try:
        result = run(args.data_root, args.output_dir, Path(__file__).resolve().parents[1], args.python,
                     args.weights, args.protocol, smoke=args.smoke)
        print(json.dumps({"gate": result["gate"], "counts": result["counts"]}))
        return 2 if result["gate"] == "BLOCKED" else 0
    except (ValueError, OSError, RuntimeError, subprocess.SubprocessError) as exc:
        print("Experiment failed: " + type(exc).__name__ + "; inspect local inputs/logs", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
