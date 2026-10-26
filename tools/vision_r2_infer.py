"""Local, full-frame YOLO proposals; never physical instance confirmation."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
from time import perf_counter


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def private_path(path, repo):
    path = Path(path).resolve()
    if not path.is_relative_to(repo.resolve()):
        raise ValueError("Input/output must remain in the local repository")
    if subprocess.run(["git", "check-ignore", "--quiet", str(path)], cwd=repo).returncode:
        raise ValueError("Image, weight and output paths must be Git ignored")
    return path


def run(weights, data_root, output, sizes, repo):
    weights, data_root, output = [private_path(p, repo) for p in (weights, data_root, output)]
    if output.exists():
        raise ValueError("Output exists; never overwrite an experiment")
    if not weights.is_file() or weights.suffix != ".pt":
        raise ValueError("A local, downloaded pretrained .pt checkpoint is required")
    if not data_root.is_dir():
        raise ValueError("Data missing; no fallback")
    if not sizes or any(s not in (640, 960) for s in sizes) or len(set(sizes)) != len(sizes):
        raise ValueError("Use the fixed 640/960 full-frame comparisons")
    files = sorted(data_root.glob("*.jpg"), key=lambda p: int(p.stem))
    if [p.name for p in files] != [f"{n}.jpg" for n in range(1, 19)]:
        raise ValueError("Expected all 18 WaterCup originals")
    before = {p.name: sha256(p) for p in files}
    config = repo / "artifacts/vision-r2-issue19/ultralytics-settings"
    config.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("YOLO_CONFIG_DIR", str(config))
    os.environ.setdefault("YOLO_OFFLINE", "true")
    os.environ.setdefault("YOLO_AUTOINSTALL", "false")
    os.environ.setdefault("WANDB_MODE", "disabled")
    import cv2
    import numpy as np
    import torch
    import ultralytics
    from ultralytics import YOLO
    if not torch.cuda.is_available():
        raise ValueError("CUDA unavailable; report the block, do not silently switch device")
    torch.manual_seed(0)
    model = YOLO(str(weights), task="detect")
    if model.task != "detect":
        raise ValueError("Detection checkpoint required")
    names = model.names
    target_names = {"cup", "sony_mug"}
    target_classes = [int(k) for k,v in names.items() if v in target_names]
    if not target_classes:
        raise ValueError("No expected cup/sony_mug class in model")
    output.mkdir(parents=True)
    rows = []
    params = {"imgsz":list(sizes), "conf":.25, "iou":.7, "device":0, "half":False,
              "augment":False, "max_det":100, "batch":1, "seed":0, "crop":"none_full_frame", "classes":"all"}
    weight_hash = sha256(weights)
    metadata = {"python":platform.python_version(), "torch":torch.__version__, "torchvision":__import__('torchvision').__version__,
        "torch_cuda":torch.version.cuda, "cuda_available":True, "ultralytics":ultralytics.__version__, "opencv":cv2.__version__,
        "gpu":torch.cuda.get_device_name(0), "gpu_memory_bytes":torch.cuda.get_device_properties(0).total_memory,
        "model":weights.name, "weight_sha256":weight_hash, "parameters":params,
        "source_commit":subprocess.check_output(["git","rev-parse","HEAD"],cwd=repo,text=True).strip(),
        "script_sha256":sha256(Path(__file__)), "source_worktree_dirty":bool(subprocess.check_output(["git","status","--porcelain"],cwd=repo,text=True).strip()),
        "label_input":None, "production_integration":False, "identity_confirmed":False,
        "timing":"CUDA synchronized wall time including predict preprocessing/postprocessing; excludes decode and visualization; first call includes cold setup",
        "gpu_memory_scope":"PyTorch peak allocated/reserved bytes; not total display-driver GPU memory"}
    (output/"environment.public.json").write_text(json.dumps(metadata,indent=2)+'\n',encoding="utf-8")
    for size in sizes:
        for index,path in enumerate(files,1):
            alias = f"photo_{index:02}"
            image = cv2.imdecode(np.frombuffer(path.read_bytes(),np.uint8),cv2.IMREAD_COLOR)
            if image is None:
                raise ValueError("Image cannot decode")
            torch.cuda.synchronize()
            torch.cuda.reset_peak_memory_stats()
            started = perf_counter()
            result = model.predict(source=image, imgsz=size, conf=.25, iou=.7, device=0,
                half=False, augment=False, max_det=100, batch=1, verbose=False, save=False)[0]
            torch.cuda.synchronize()
            elapsed = (perf_counter()-started)*1000
            detections = [{"class_id":int(cls), "class_name":names[int(cls)], "confidence":float(conf),
                "bbox_xyxy":[float(v) for v in box]} for box,conf,cls in zip(result.boxes.xyxy.cpu().tolist(),result.boxes.conf.cpu().tolist(),result.boxes.cls.cpu().tolist())]
            candidates = [d for d in detections if d['class_id'] in target_classes]
            row = {"sample_id":alias, "path":path.name, "sha256":before[path.name], "source_type":"real", "split":"diagnostic_reused",
                "original_size":[image.shape[1],image.shape[0]], "imgsz":size, "executed":True,
                "detections":detections, "target_class_candidates":candidates, "bbox_source":"predicted",
                "status":"CATEGORY_CANDIDATES" if candidates else "NO_CATEGORY_CANDIDATE",
                "reason":"instance_not_verified" if candidates else "no_target_class_above_fixed_threshold",
                "elapsed_ms":round(elapsed,3), "internal_speed_ms":result.speed,
                "peak_allocated_bytes":torch.cuda.max_memory_allocated(), "peak_reserved_bytes":torch.cuda.max_memory_reserved(),
                "human_localization_review":"pending", "cold_call":len(rows)==0}
            rows.append(row)
            ok, encoded = cv2.imencode('.jpg', result.plot())
            if not ok: raise ValueError("Cannot encode private prediction overlay")
            (output/f"{alias}-{size}.private.jpg").write_bytes(encoded.tobytes())
            (output/"predictions.private.json").write_text(json.dumps(rows,indent=2)+'\n',encoding="utf-8")
            print(f"{alias} size={size} candidates={len(candidates)} elapsed_ms={elapsed:.1f} peak_MiB={row['peak_allocated_bytes']/2**20:.1f}",flush=True)
    assert before == {p.name:sha256(p) for p in files} and weight_hash == sha256(weights)
    summary = {"images":18, "evaluations":len(rows), "originals_unchanged":True, "method":"full_frame",
        "ground_truth_used":False, "identity_confirmed":False, "production_integration":False,
        "gate":"PENDING_VISUAL_REVIEW_NOT_INSTANCE_VALIDATION", "environment":metadata,
        "methods":[{"imgsz":size,"images":18,"images_with_candidates":sum(bool(r['target_class_candidates']) for r in rows if r['imgsz']==size),
            "candidate_boxes":sum(len(r['target_class_candidates']) for r in rows if r['imgsz']==size),
            "total_wall_ms":round(sum(r['elapsed_ms'] for r in rows if r['imgsz']==size),3),
            "max_peak_allocated_bytes":max(r['peak_allocated_bytes'] for r in rows if r['imgsz']==size)} for size in sizes]}
    (output/"summary.public.json").write_text(json.dumps(summary,indent=2)+'\n',encoding="utf-8")
    return summary


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    for arg in ("weights","data-root","output-dir"): parser.add_argument("--"+arg, type=Path, required=True)
    parser.add_argument("--imgsz", nargs="+", type=int, default=[640,960])
    args=parser.parse_args()
    run(args.weights,args.data_root,args.output_dir,args.imgsz,Path(__file__).resolve().parents[1])
