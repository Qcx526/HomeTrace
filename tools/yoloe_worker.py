"""One local, fixed-version Visual Prompt inference; never confirms identity.

Called in an isolated process by evaluate_yoloe.py. Private paths, pixels and
boxes stay in the ignored request/output directories. No HomeTrace state writes.
"""

import argparse
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import socket
from time import perf_counter


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("request", type=Path)
    args = parser.parse_args()
    request = json.loads(args.request.read_text(encoding="utf-8"))
    output = Path(request["output"])
    output.mkdir(parents=True, exist_ok=False)
    os.environ.update(YOLO_OFFLINE="true", YOLO_AUTOINSTALL="false",
                      YOLO_CONFIG_DIR=str(output / "settings"), MPLCONFIGDIR=str(output / "mpl"))
    # Defense in depth: no sockets during imports or inference. This is a local
    # experiment, not an upload API. All model files must already be downloaded.
    def denied(*args, **kwargs):
        raise RuntimeError("Network is disabled in the private inference worker")
    socket.socket.connect = denied
    socket.socket.connect_ex = denied
    socket.create_connection = denied
    socket.getaddrinfo = denied
    started = perf_counter()
    try:
        import cv2
        import numpy as np
        import torch
        from ultralytics import YOLOE, settings
        from ultralytics.models.yolo.yoloe import YOLOEVPSegPredictor
        from neural_contract import validate_candidates
        if importlib.metadata.version("ultralytics") != "8.3.221":
            raise ValueError("This experiment requires ultralytics 8.3.221")
        settings.update({key: False for key in ("sync", "hub", "clearml", "comet", "dvc", "mlflow",
            "neptune", "raytune", "tensorboard", "wandb")})
        settings.update({"api_key": "", "openai_api_key": ""})
        torch.manual_seed(0)
        np.random.seed(0)
        torch.set_num_threads(4)
        cv2.setNumThreads(1)
        torch.backends.cudnn.benchmark = False
        torch.backends.cudnn.deterministic = True
        images = {}
        for role in ("reference", "scene", "weights"):
            path = Path(request[role]["path"])
            content = path.read_bytes()
            if hashlib.sha256(content).hexdigest() != request[role]["sha256"]:
                raise ValueError("Input content does not match fixed SHA256")
            if role != "weights":
                image = cv2.imdecode(np.frombuffer(content, np.uint8), cv2.IMREAD_COLOR | cv2.IMREAD_IGNORE_ORIENTATION)
                if image is None or list(image.shape[:2][::-1]) != request[role]["size"]:
                    raise ValueError("Image decode or dimensions mismatch")
                images[role] = image
        roi = request["reference_roi"]
        width, height = request["reference"]["size"]
        if not (len(roi) == 4 and all(type(v) is int for v in roi)
                and 0 <= roi[0] < roi[2] <= width and 0 <= roi[1] < roi[3] <= height):
            raise ValueError("Invalid original-reference ROI")
        device = request["parameters"]["device"]
        if device.startswith("cuda") and not torch.cuda.is_available():
            raise RuntimeError("Configured CUDA device unavailable; no silent device fallback")
        if device.startswith("cuda"):
            torch.cuda.reset_peak_memory_stats()
            torch.cuda.synchronize()
        load_start = perf_counter()
        model = YOLOE(request["weights"]["path"])
        load_ms = (perf_counter() - load_start) * 1000
        # Each process starts with untouched weights: no prompt state can leak
        # from another object or a previous scene into this inference.
        predict_start = perf_counter()
        parameters = {k: v for k, v in request["parameters"].items() if k != "seed"}
        results = model.predict(source=images["scene"], refer_image=images["reference"],
            visual_prompts={"bboxes": np.array([roi], dtype=np.float32), "cls": np.array([0], dtype=np.int64)},
            predictor=YOLOEVPSegPredictor, save=False, verbose=False, **parameters)
        if device.startswith("cuda"):
            torch.cuda.synchronize()
        predict_ms = (perf_counter() - predict_start) * 1000
        if len(results) != 1 or list(results[0].orig_shape[::-1]) != request["scene"]["size"]:
            raise ValueError("Output must retain the full scene coordinate system")
        boxes = results[0].boxes
        classes = boxes.cls.cpu().tolist()
        if any(not math.isfinite(value) or value != 0 for value in classes):
            raise ValueError("Unexpected visual prompt class")
        raw = [{"bbox": box, "score": score, "class_id": int(class_id)} for box, score, class_id
               in zip(boxes.xyxy.cpu().tolist(), boxes.conf.cpu().tolist(), classes)]
        candidates = validate_candidates(raw, *request["scene"]["size"])
        overlay = images["scene"].copy()
        for candidate in candidates:
            x1, y1, x2, y2 = map(round, candidate["bbox"])
            cv2.rectangle(overlay, (x1, y1), (x2, y2), (0, 160, 255), 4)
            cv2.putText(overlay, f"object0 candidate {candidate['score']:.3f}", (x1, max(24, y1 - 8)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 160, 255), 2)
        ok, encoded = cv2.imencode(".jpg", overlay)
        if not ok:
            raise ValueError("Private overlay encoding failed")
        (output / "candidates.private.jpg").write_bytes(encoded.tobytes())
        for role in ("reference", "scene", "weights"):
            if hashlib.sha256(Path(request[role]["path"]).read_bytes()).hexdigest() != request[role]["sha256"]:
                raise ValueError("Input changed during inference")
        record = {"status": "SUSPECTED" if candidates else "UNKNOWN", "confirmed_identity": False,
            "candidates": candidates, "model_classes": results[0].names, "predict_ms": round(predict_ms, 3),
            "model_load_ms": round(load_ms, 3), "process_work_ms": round((perf_counter() - started) * 1000, 3),
            "speed_ms": results[0].speed, "device": device,
            "gpu_name": torch.cuda.get_device_name(0) if device.startswith("cuda") else None,
            "cuda_runtime": torch.version.cuda, "cuda_available": torch.cuda.is_available(),
            "compute_capability": list(torch.cuda.get_device_capability(0)) if device.startswith("cuda") else None,
            "peak_allocated_bytes": torch.cuda.max_memory_allocated() if device.startswith("cuda") else 0,
            "peak_reserved_bytes": torch.cuda.max_memory_reserved() if device.startswith("cuda") else 0,
            "versions": {name: importlib.metadata.version(name) for name in ("ultralytics", "torch", "torchvision", "numpy", "opencv-python")},
            "network_disabled": True, "scene_preprocessing": "full image; model letterbox only",
            "reference_prompt": "full registration image and fixed original-coordinate ROI"}
        (output / "result.private.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"success": True, "candidate_count": len(candidates), "device": device}))
        return 0
    except Exception as exc:
        # Detailed private diagnostics, no keys are read by this worker.
        import traceback
        (output / "failure.private.txt").write_text(traceback.format_exc(), encoding="utf-8")
        print(json.dumps({"success": False, "error_type": type(exc).__name__}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
