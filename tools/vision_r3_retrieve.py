"""Isolated, frozen-model full-image retrieval experiment; never production FOUND.

Enrollment input contains only reviewed references and unlabelled scene identities.
Ground truth is deliberately absent from this process. See score_vision_r3.py.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
from time import perf_counter

from vision_gallery import rank_candidate

PARAMETERS = {"detector_sizes": [640, 960], "conf": .25, "nms_iou": .7,
              "max_det": 100, "encoder_size": 224, "min_similarity": .70,
              "min_margin": .05, "min_support": 2,
              "feature": "normalized_cls_token", "resize": "whole_crop_bicubic_224_square",
              "candidate_classes": ["cup"], "training": False}
MODEL_COMMIT = "7764ea0f912e53c92e82eb78a2a1631e92725fc8"
ENCODER_SHA256 = "b938bf1bc15cd2ec0feacfe3a1bb553fe8ea9ca46a7e1d8d00217f29aef60cd9"
DETECTOR_SHA256 = "0ebbc80d4a7680d14987a577cd21342b65ecfd94632bd9a8da63ae6417644ee1"


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def private_path(repo, path):
    path = Path(path).resolve()
    if not path.is_relative_to(repo.resolve()):
        raise ValueError("Private input/output must stay within the repository")
    if subprocess.run(["git", "check-ignore", "--quiet", str(path)], cwd=repo).returncode:
        raise ValueError("Private input/output must be Git ignored")
    return path


def source_path(root, name):
    if not isinstance(name, str) or not name:
        raise ValueError("Missing image path")
    path = (root / name).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError("Image outside data root or missing")
    return path


def checked_box(box, width, height):
    if (not isinstance(box, list) or len(box) != 4 or
            any(type(x) not in (int, float) or not math.isfinite(x) for x in box)):
        raise ValueError("Invalid bounding box")
    x1, y1, x2, y2 = box
    if not 0 <= x1 < x2 <= width or not 0 <= y1 < y2 <= height:
        raise ValueError("Bounding box outside decoded image")
    return [math.floor(x1), math.floor(y1), math.ceil(x2), math.ceil(y2)]


def validate_enrollment(manifest, root):
    if set(manifest) != {"schema_version", "target_instance_id", "references", "scenes", "scope"}:
        raise ValueError("Enrollment schema rejects extra fields, including scene labels")
    if manifest['schema_version'] != 1 or manifest['scope'] != 'diagnostic_reused':
        raise ValueError("Only development diagnostics are supported")
    scenes, refs = manifest['scenes'], manifest['references']
    if not scenes or not refs or not isinstance(manifest['target_instance_id'], str):
        raise ValueError("Missing target/reference/scenes")
    seen = set()
    for scene in scenes:
        if set(scene) != {'sample_id', 'path', 'sha256', 'source_type'} or scene['source_type'] != 'real':
            raise ValueError("Scenes must contain only unlabelled real input identities")
        if scene['sample_id'] in seen:
            raise ValueError("Duplicate scene")
        seen.add(scene['sample_id'])
        if sha256(source_path(root, scene['path'])) != scene['sha256']:
            raise ValueError("Scene image hash mismatch")
    ref_ids = set()
    for ref in refs:
        required = {'reference_id', 'object_instance_id', 'path', 'sha256', 'roi',
                    'identity_reviewed', 'roi_reviewed', 'review_source', 'source_type'}
        if set(ref) != required or ref['source_type'] != 'real':
            raise ValueError("Invalid reference schema")
        if ref['identity_reviewed'] is not True or ref['roi_reviewed'] is not True or not ref['review_source']:
            raise ValueError("Owner-reviewed identity and ROI are required")
        if ref['reference_id'] in ref_ids:
            raise ValueError("Duplicate reference ID")
        ref_ids.add(ref['reference_id'])
        if sha256(source_path(root, ref['path'])) != ref['sha256']:
            raise ValueError("Reference hash mismatch")
    if len({r['sha256'] for r in refs if r['object_instance_id'] == manifest['target_instance_id']}) < 2:
        raise ValueError("At least two distinct target reference images required")
    if not any(r['object_instance_id'] != manifest['target_instance_id'] for r in refs):
        raise ValueError("Rival reference required")
    return scenes, refs


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def run(enrollment, data_root, encoder_source, encoder_weights, detector_weights, output, repo):
    enrollment, data_root, encoder_source, encoder_weights, detector_weights, output = [
        private_path(repo, p) for p in (enrollment, data_root, encoder_source, encoder_weights, detector_weights, output)]
    if output.exists():
        raise ValueError("Never overwrite an experiment")
    manifest = json.loads(enrollment.read_text(encoding='utf-8'))
    scenes, references = validate_enrollment(manifest, data_root)
    source_commit = subprocess.check_output(['git', '-C', str(encoder_source), 'rev-parse', 'HEAD'], text=True).strip()
    if source_commit != MODEL_COMMIT or subprocess.check_output(['git', '-C', str(encoder_source), 'status', '--porcelain'], text=True).strip():
        raise ValueError("Encoder source must be the frozen clean upstream commit")
    if sha256(encoder_weights) != ENCODER_SHA256 or sha256(detector_weights) != DETECTOR_SHA256:
        raise ValueError("Frozen pretrained weight checksum mismatch")
    output.mkdir(parents=True, exist_ok=False)
    # Ultralytics checks the parent's writability before creating its subfolder.
    # Create it explicitly so framework settings cannot fall back to repo root.
    (output / 'settings').mkdir()
    os.environ['YOLO_CONFIG_DIR'] = str(output / 'settings')
    os.environ['YOLO_OFFLINE'] = 'true'
    os.environ['YOLO_AUTOINSTALL'] = 'false'
    import cv2
    import numpy as np
    from PIL import Image
    import torch
    from torchvision import transforms
    import ultralytics
    from ultralytics import YOLO
    if not torch.cuda.is_available():
        raise ValueError("CUDA unavailable; no unreported fallback")
    if ultralytics.__version__ != '8.3.221' or torch.__version__ != '2.6.0+cu124':
        raise ValueError("Use the recorded optional neural environment")
    torch.manual_seed(22)
    torch.backends.cudnn.benchmark = False
    encoder = torch.hub.load(str(encoder_source), 'dinov2_vits14', source='local', pretrained=False)
    encoder.load_state_dict(torch.load(encoder_weights, map_location='cpu', weights_only=True), strict=True)
    encoder.eval().to('cuda')
    for p in encoder.parameters():
        p.requires_grad_(False)
    detector = YOLO(str(detector_weights), task='detect')
    transform = transforms.Compose([
        transforms.Resize((224, 224), interpolation=transforms.InterpolationMode.BICUBIC),
        transforms.ToTensor(), transforms.Normalize([.485, .456, .406], [.229, .224, .225])])

    def decode(path):
        result = cv2.imdecode(np.frombuffer(path.read_bytes(), np.uint8), cv2.IMREAD_COLOR)
        if result is None:
            raise ValueError("Image cannot decode")
        return result

    def embed(image, box):
        x1, y1, x2, y2 = checked_box(box, image.shape[1], image.shape[0])
        crop = Image.fromarray(cv2.cvtColor(image[y1:y2, x1:x2], cv2.COLOR_BGR2RGB))
        tensor = transform(crop).unsqueeze(0).to('cuda')
        with torch.inference_mode():
            feature = torch.nn.functional.normalize(encoder(tensor), dim=-1)[0].cpu().tolist()
        return feature

    gallery = []
    for ref in references:
        image = decode(source_path(data_root, ref['path']))
        gallery.append({'object_instance_id': ref['object_instance_id'], 'reference_id': ref['reference_id'],
                        'image_sha256': ref['sha256'], 'embedding': embed(image, ref['roi'])})
    write_json(output / 'gallery.private.json', gallery)
    ref_hashes = {r['image_sha256'] for r in gallery}
    metadata = {'parameters': PARAMETERS, 'encoder': 'dinov2_vits14', 'encoder_source_commit': source_commit,
                'encoder_sha256': ENCODER_SHA256, 'detector_sha256': DETECTOR_SHA256,
                'encoder_license': 'Apache-2.0', 'detector_license': 'Ultralytics AGPL-3.0 or enterprise; no redistribution here',
                'torch': torch.__version__, 'ultralytics': ultralytics.__version__, 'cuda': torch.version.cuda,
                'device': torch.cuda.get_device_name(0), 'trainable_encoder_parameters': 0,
                'scene_ground_truth_input': False, 'independent_test': False, 'production_integration': False,
                'source_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=repo, text=True).strip(),
                'script_sha256': sha256(Path(__file__)), 'gallery_script_sha256': sha256(Path(__file__).with_name('vision_gallery.py')),
                'encoder_preprocessing': 'RGB candidate/reference crop resized entirely to square; ImageNet normalization',
                'timing': 'CUDA synchronized full candidate detection plus encoding/ranking, excludes decode and drawing; first call cold'}
    write_json(output / 'environment.public.json', metadata)
    write_json(output / 'binding.private.json', {'enrollment_sha256': sha256(enrollment), 'reference_hashes': sorted(ref_hashes)})
    rows = []
    for size in PARAMETERS['detector_sizes']:
        for scene in scenes:
            image = decode(source_path(data_root, scene['path']))
            torch.cuda.synchronize()
            torch.cuda.reset_peak_memory_stats()
            start = perf_counter()
            prediction = detector.predict(image, imgsz=size, conf=.25, iou=.7, device=0,
                                          max_det=100, half=False, augment=False, verbose=False, save=False)[0]
            all_boxes = [{'bbox_xyxy': [float(x) for x in box], 'class_name': detector.names[int(cls)],
                          'confidence': float(conf)} for box, cls, conf in zip(
                prediction.boxes.xyxy.cpu().tolist(), prediction.boxes.cls.cpu().tolist(), prediction.boxes.conf.cpu().tolist())]
            candidates = []
            for detection in all_boxes:
                if detection['class_name'] not in PARAMETERS['candidate_classes']:
                    continue
                feature = embed(image, detection['bbox_xyxy'])
                ranking = rank_candidate({'embedding': feature, 'image_sha256': scene['sha256']}, gallery,
                                         target_instance_id=manifest['target_instance_id'], min_similarity=.70,
                                         min_margin=.05, min_support=2)
                candidates.append({**detection, 'retrieval': ranking, 'feature': feature})
            torch.cuda.synchronize()
            replay = scene['sha256'] in ref_hashes
            supported = any(c['retrieval']['status'] == 'APPEARANCE_SUPPORTED' for c in candidates)
            row = {**scene, 'imgsz': size, 'executed': True, 'original_size': [image.shape[1], image.shape[0]],
                   'all_detections': all_boxes, 'candidates': candidates, 'reference_replay': replay,
                   'status': 'REFERENCE_EXCLUDED' if replay else ('APPEARANCE_SUPPORTED' if supported else 'UNKNOWN'),
                   'reason': 'reference_replay' if replay else ('appearance_only_not_identity' if supported else
                             ('no_cup_candidate' if not candidates else 'retrieval_rejected')),
                   'identity_confirmed': False, 'bbox_source': 'full_frame_detector',
                   'elapsed_ms': round((perf_counter()-start)*1000, 3),
                   'peak_allocated_bytes': torch.cuda.max_memory_allocated(), 'cold_call': not rows}
            rows.append(row)
            write_json(output / 'predictions.private.json', rows)
            overlay = image.copy()
            for c in candidates:
                x1, y1, x2, y2 = checked_box(c['bbox_xyxy'], image.shape[1], image.shape[0])
                color = (0, 180, 0) if c['retrieval']['status'] == 'APPEARANCE_SUPPORTED' else (0, 140, 255)
                cv2.rectangle(overlay, (x1, y1), (x2, y2), color, 6)
                cv2.putText(overlay, c['retrieval']['status'], (x1, max(35, y1-10)), cv2.FONT_HERSHEY_SIMPLEX, 1, color, 3)
            ok, buf = cv2.imencode('.jpg', overlay)
            if not ok:
                raise ValueError("Cannot save overlay")
            (output / f"{scene['sample_id']}-{size}.private.jpg").write_bytes(buf.tobytes())
            print(f"{scene['sample_id']} size={size} candidates={len(candidates)} status={row['status']} ms={row['elapsed_ms']}", flush=True)
    validate_enrollment(manifest, data_root)
    if sha256(encoder_weights) != ENCODER_SHA256 or sha256(detector_weights) != DETECTOR_SHA256:
        raise ValueError("Weights changed during inference")
    write_json(output / 'completion.public.json', {'actual_inference_calls': len(rows), 'physical_images': len(scenes),
               'training_steps': 0, 'originals_unchanged': True, 'weights_unchanged': True,
               'independent_test_images': 0, 'identity_confirmed': False})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ('enrollment', 'data-root', 'encoder-source', 'encoder-weights', 'detector-weights', 'output-dir'):
        parser.add_argument('--'+arg, type=Path, required=True)
    args = parser.parse_args()
    run(args.enrollment, args.data_root, args.encoder_source, args.encoder_weights,
        args.detector_weights, args.output_dir, Path(__file__).resolve().parents[1])
