"""Two explicit local-only YOLO11n transfer-learning trials; no production writes."""

import argparse
import csv
import importlib.metadata
import json
import os
import socket
import time
from pathlib import Path

from vision_r2_data import Blocked, require_private, sha256, validate_manifest


TRIALS = {
    "freeze-backbone": {"freeze": 10, "lr0": 0.01},
    "low-lr-finetune": {"freeze": 0, "lr0": 0.001},
}
PRETRAINED_URL = "https://github.com/ultralytics/assets/releases/download/v8.3.0/yolo11n.pt"


def build_train_args(dataset, trial_dir, trial, epochs=50):
    if trial not in TRIALS or type(epochs) is not int or not 1 <= epochs <= 50:
        raise Blocked("Only the two declared trials and 1..50 epochs are allowed")
    return {"data": str(Path(dataset) / "data.yaml"), "project": str(trial_dir), "name": "training",
            "device": 0, "imgsz": 640, "batch": 2, "epochs": epochs, "patience": 10,
            "seed": 19, "deterministic": True, "workers": 0, "optimizer": "SGD",
            "freeze": TRIALS[trial]["freeze"], "lr0": TRIALS[trial]["lr0"],
            "amp": False, "cache": False, "save": True, "save_period": 1,
            "plots": True, "val": True, "exist_ok": False, "resume": False,
            "hsv_h": 0.0, "hsv_s": 0.15, "hsv_v": 0.2, "degrees": 5.0,
            "translate": 0.1, "scale": 0.3, "shear": 0.0, "perspective": 0.0,
            "flipud": 0.0, "fliplr": 0.0, "mosaic": 0.0, "mixup": 0.0, "copy_paste": 0.0}


def validate_inputs(dataset, weights, expected_sha256, output_root, trial, repo):
    dataset, weights = require_private(repo, dataset), require_private(repo, weights)
    output_root = require_private(repo, output_root)
    if trial not in TRIALS:
        raise Blocked("Undeclared training trial")
    if (output_root / trial).exists():
        raise Blocked("Trial already exists; refusing to overwrite or silently retrain")
    if weights.name != "yolo11n.pt" or not weights.is_file() or sha256(weights) != expected_sha256:
        raise Blocked("Verified local YOLO11n pretrained .pt and exact SHA256 required")
    record_path = dataset / "prepared.private.json"
    record = json.loads(record_path.read_text(encoding="utf-8"))
    if (record.get("schema_version") != 1 or record.get("purpose") != "exploratory_fit"
            or record.get("independent_test") is not False or record.get("source_type") != "real_team_photo"):
        raise Blocked("Only the reviewed real-photo exploratory dataset may enter actual training")
    if not isinstance(record.get("files"), dict) or "data.yaml" not in record["files"]:
        raise Blocked("Dataset integrity manifest missing")
    for name, expected in record["files"].items():
        path = (dataset / name).resolve()
        if not path.is_relative_to(dataset) or not path.is_file() or sha256(path) != expected:
            raise Blocked("Prepared dataset changed; repeat human-reviewed preparation")
    annotation = dataset / "annotation.private.json"
    if not annotation.is_file() or sha256(annotation) != record.get("manifest_sha256"):
        raise Blocked("Reviewed annotation binding missing")
    originals = require_private(repo, record["original_data_root"])
    expected_samples = validate_manifest(json.loads(annotation.read_text(encoding="utf-8-sig")), originals)
    if expected_samples != record.get("samples"):
        raise Blocked("Prepared dataset does not match reviewed annotation")
    return dataset, weights, output_root / trial, record


def deny_network(*args, **kwargs):
    raise RuntimeError("Network disabled for private local training")


def train(dataset, weights, expected_sha256, output_root, trial, repo, epochs=50):
    dataset, weights, trial_dir, record = validate_inputs(dataset, weights, expected_sha256, output_root, trial, repo)
    arguments = build_train_args(dataset, trial_dir, trial, epochs)
    trial_dir.mkdir(parents=True, exist_ok=False)
    (trial_dir / "settings").mkdir()
    (trial_dir / "mpl").mkdir()
    # Reuse the installed Windows font locally; do not download during training.
    system_font = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts/arial.ttf"
    if system_font.is_file():
        import shutil
        shutil.copyfile(system_font, trial_dir / "settings/Arial.ttf")
    os.environ.update(YOLO_OFFLINE="true", YOLO_AUTOINSTALL="false", WANDB_MODE="disabled",
                      COMET_MODE="DISABLED", YOLO_CONFIG_DIR=str(trial_dir / "settings"),
                      MPLCONFIGDIR=str(trial_dir / "mpl"))
    socket.socket.connect = deny_network
    socket.socket.connect_ex = deny_network
    socket.create_connection = deny_network
    socket.getaddrinfo = deny_network
    started = time.perf_counter()
    evidence = {"status": "STARTING", "trial": trial, "purpose": "exploratory_fit", "independent_test": False,
                "pretrained_source": PRETRAINED_URL, "pretrained_sha256": expected_sha256,
                "dataset_manifest_sha256": record["manifest_sha256"],
                "dataset_binding_sha256": sha256(dataset / "prepared.private.json"), "arguments": arguments}
    import subprocess
    evidence.update(source_commit=subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip(),
                    driver_sha256=sha256(Path(__file__)),
                    data_preparer_sha256=sha256(Path(__file__).with_name("vision_r2_data.py")))
    evidence_path = trial_dir / "training-evidence.private.json"

    def save():
        evidence["wall_seconds"] = round(time.perf_counter() - started, 6)
        evidence_path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    try:
        import torch
        from ultralytics import YOLO, settings

        if importlib.metadata.version("ultralytics") != "8.3.221":
            raise Blocked("This reproducible fallback experiment pins ultralytics==8.3.221")
        if not torch.cuda.is_available():
            raise Blocked("CUDA unavailable; no silent CPU training fallback")
        settings.update({key: False for key in ("sync", "hub", "clearml", "comet", "dvc", "mlflow", "neptune", "raytune", "tensorboard", "wandb")})
        settings.update({"api_key": "", "openai_api_key": ""})
        torch.cuda.reset_peak_memory_stats(0)
        torch.set_num_threads(4)
        evidence.update(versions={name: importlib.metadata.version(name) for name in ("torch", "torchvision", "ultralytics", "numpy", "opencv-python")},
                        gpu_name=torch.cuda.get_device_name(0), cuda_runtime=torch.version.cuda,
                        gpu_total_bytes=torch.cuda.get_device_properties(0).total_memory)
        model = YOLO(str(weights))
        if not model.ckpt or model.task != "detect" or len(model.names) != 80 or model.names.get(41) != "cup":
            raise Blocked("Expected pretrained COCO detector, not random initialization or a custom checkpoint")

        def on_epoch_end(trainer):
            losses = trainer.tloss.detach().cpu().tolist()
            row = {"epoch": int(trainer.epoch) + 1, "losses": losses,
                   "peak_allocated_bytes": torch.cuda.max_memory_allocated(0),
                   "peak_reserved_bytes": torch.cuda.max_memory_reserved(0),
                   "wall_seconds": time.perf_counter() - started}
            with (trial_dir / "epochs.private.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(row) + "\n")

        model.add_callback("on_train_epoch_end", on_epoch_end)
        evidence["status"] = "TRAINING"
        save()
        model.train(**arguments)
        torch.cuda.synchronize(0)
        generated = {}
        for name in ("training/weights/best.pt", "training/weights/last.pt", "training/args.yaml", "training/results.csv", "training/results.png"):
            path = trial_dir / name
            if not path.is_file() or path.stat().st_size == 0:
                raise Blocked("Training ended without required artifact: " + name)
            generated[name] = {"sha256": sha256(path), "bytes": path.stat().st_size}
        with (trial_dir / "training/results.csv").open(encoding="utf-8") as stream:
            evidence["epochs_completed"] = len(list(csv.DictReader(stream)))
        evidence.update(status="TRAINING_COMPLETED_EVALUATION_REQUIRED", artifacts=generated,
                        peak_allocated_bytes=torch.cuda.max_memory_allocated(0),
                        peak_reserved_bytes=torch.cuda.max_memory_reserved(0))
        save()
        return evidence
    except Exception as exc:
        evidence.update(status="BLOCKED", failure_type=type(exc).__name__, reason=str(exc))
        save()
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--weights", type=Path, required=True)
    parser.add_argument("--weights-sha256", required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--trial", choices=TRIALS, required=True)
    parser.add_argument("--epochs", type=int, default=50)
    args = parser.parse_args()
    try:
        result = train(args.dataset, args.weights, args.weights_sha256, args.output_root, args.trial,
                       Path(__file__).resolve().parents[1], args.epochs)
        print(json.dumps({"status": result["status"], "epochs_completed": result["epochs_completed"], "independent_test": False}))
    except Exception as exc:
        print(json.dumps({"status": "BLOCKED", "reason": str(exc)}))
        raise SystemExit(2)


if __name__ == "__main__":
    main()
