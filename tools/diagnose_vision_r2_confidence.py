"""Full-frame confidence diagnostics; no annotation input and no production FOUND."""
import argparse
import importlib.metadata
import json
import os
from pathlib import Path
import socket
import subprocess
import time

from vision_r2_data import Blocked, require_private, sha256
from train_vision_r2 import deny_network

THRESHOLDS = (0.001, 0.01, 0.05, 0.10, 0.25)
SIZES = (640, 960)
OLD_WEIGHTS = {
    'pretrained': '0ebbc80d4a7680d14987a577cd21342b65ecfd94632bd9a8da63ae6417644ee1',
    'freeze-backbone': '300df186b6fab35d5dee40f8ad7c48b06614f110cf1a04071389611fa3bc3bce',
    'low-lr-finetune': '75b390f89068a9815c765fcf04566944c0ffb3cdcd53f48f77d2c52faa836591',
}


def score_distribution(values):
    import numpy as np
    v = np.asarray(values, dtype=float).reshape(-1)
    if not np.isfinite(v).all() or (v < 0).any() or (v > 1).any():
        raise Blocked('Invalid model class scores')
    return {'count': int(v.size), 'max': float(v.max()) if v.size else None,
            'quantiles': {str(q): float(np.quantile(v, q)) if v.size else None for q in (0,.5,.9,.99,1)},
            'above_threshold': {str(t): int((v > t).sum()) for t in THRESHOLDS}}


def expected_keys():
    return {(f'{n}.jpg', s, t) for n in range(1,19) for s in SIZES for t in THRESHOLDS}


def validate_rows(rows, hashes):
    keys = [(r['path'],r['imgsz'],r['threshold']) for r in rows]
    if len(keys) != len(set(keys)) or set(keys) != expected_keys():
        raise Blocked('Incomplete or duplicate diagnostic grid')
    for r in rows:
        if r['sha256'] != hashes[r['path']] or r.get('executed') is not True:
            raise Blocked('Unexecuted image or source hash mismatch')


def run(weights, model_id, data_root, output, repo):
    weights, data_root, output = [require_private(repo,p) for p in (weights,data_root,output)]
    if output.exists(): raise Blocked('Never overwrite diagnostic output')
    if model_id not in (*OLD_WEIGHTS,'no-warmup'): raise Blocked('Unknown experiment model')
    weight_hash = sha256(weights)
    if model_id in OLD_WEIGHTS and weight_hash != OLD_WEIGHTS[model_id]:
        raise Blocked('Frozen old checkpoint hash mismatch')
    if model_id == 'no-warmup':
        training=json.loads((repo/'artifacts/vision-r2-followup/nowarmup/training-evidence.private.json').read_text(encoding='utf-8'))
        if training.get('status') != 'COMPLETED' or weight_hash != training['best_weight_sha256']:
            raise Blocked('Controlled training checkpoint not bound to completed run')
    files=[data_root/f'{n}.jpg' for n in range(1,19)]
    if set(data_root.glob('*.jpg')) != set(files) or not all(p.is_file() for p in files):
        raise Blocked('Exactly 18 original photographs required')
    hashes={p.name:sha256(p) for p in files}
    output.mkdir(parents=True,exist_ok=False)
    (output/'settings').mkdir()
    os.environ.update(YOLO_CONFIG_DIR=str(output/'settings'),YOLO_OFFLINE='true',YOLO_AUTOINSTALL='false',WANDB_MODE='disabled')
    socket.socket.connect=deny_network
    socket.socket.connect_ex=deny_network
    socket.create_connection=deny_network
    socket.getaddrinfo=deny_network
    import cv2
    import numpy as np
    import torch
    from ultralytics import YOLO, settings
    from ultralytics.models.yolo.detect.predict import DetectionPredictor
    from ultralytics.utils import ops
    if importlib.metadata.version('ultralytics') != '8.3.221' or not torch.cuda.is_available():
        raise Blocked('Pinned Ultralytics and CUDA required')
    settings.update({k:False for k in ('sync','hub','clearml','comet','dvc','mlflow','neptune','raytune','tensorboard','wandb')})
    settings.update({'api_key':'','openai_api_key':''})
    torch.manual_seed(0)
    class ObservedPredictor(DetectionPredictor):
        def postprocess(self,preds,img,orig_imgs,**kwargs):
            raw=preds[0] if isinstance(preds,(tuple,list)) else preds
            # Copy before NMS mutates tensors; never replace network outputs.
            self.raw = raw.detach().clone()
            self.input_shape = tuple(img.shape[2:])
            return super().postprocess(preds,img,orig_imgs,**kwargs)
    model=YOLO(str(weights),task='detect')
    names=model.names
    expected='cup' if model_id=='pretrained' else 'sony_mug'
    target=[k for k,v in names.items() if v==expected]
    if len(target)!=1: raise Blocked('Expected class missing or ambiguous')
    metadata={'model_id':model_id,'weight_sha256':weight_hash,'torch':torch.__version__,
        'ultralytics':importlib.metadata.version('ultralytics'),'cuda':torch.version.cuda,'gpu':torch.cuda.get_device_name(0),
        'source_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip(),
        'script_sha256':sha256(Path(__file__)),'thresholds':THRESHOLDS,'sizes':SIZES,'business_confidence':.25,
        'nms_iou':.7,'max_det':100,'all_classes':True,'full_frame':True,'label_input':None,
        'identity_confirmed':False,'raw_coordinate_system':'xyxy original pixels clipped; source xywh in resized padded tensor also retained',
        'raw_score_semantics':'YOLO11 decoded sigmoid class scores, not calibrated identity probabilities',
        'timing':'CUDA synchronized predict with raw GPU clone, excludes disk/CPU raw serialization; not historical timing benchmark'}
    (output/'environment.public.json').write_text(json.dumps(metadata,indent=2)+'\n',encoding='utf-8')
    rows=[]
    for size in SIZES:
        for threshold in THRESHOLDS:
            for file in files:
                prefix=f'photo-{int(file.stem):02}-{size}-{threshold:g}'
                row={'path':file.name,'sha256':hashes[file.name],'imgsz':size,'threshold':threshold,'model_id':model_id,'executed':False}
                try:
                    image=cv2.imdecode(np.frombuffer(file.read_bytes(),np.uint8),cv2.IMREAD_COLOR)
                    if image is None: raise Blocked('Image decode failed')
                    torch.cuda.synchronize(); torch.cuda.reset_peak_memory_stats()
                    start=time.perf_counter()
                    result=model.predict(image,predictor=ObservedPredictor,imgsz=size,conf=threshold,iou=.7,
                        device=0,half=False,augment=False,max_det=100,batch=1,verbose=False,save=False)[0]
                    torch.cuda.synchronize()
                    elapsed=(time.perf_counter()-start)*1000
                    raw=model.predictor.raw[0].cpu()
                    if raw.shape[0] != 4+len(names): raise Blocked('Unexpected decoded output layout')
                    boxes=ops.xywh2xyxy(raw[:4].T.clone())
                    boxes=ops.scale_boxes(model.predictor.input_shape,boxes,image.shape).numpy()
                    scores=raw[4:].numpy()
                    rawfile=output/(prefix+'.raw.private.npz')
                    np.savez_compressed(rawfile,boxes_xyxy_original=boxes,scores=scores,
                        xywh_input=raw[:4].T.numpy(),input_shape=np.array(model.predictor.input_shape))
                    detections=[{'class_id':int(c),'class_name':names[int(c)],'confidence':float(s),'bbox_xyxy':list(map(float,b))}
                        for b,s,c in zip(result.boxes.xyxy.cpu().tolist(),result.boxes.conf.cpu().tolist(),result.boxes.cls.cpu().tolist())]
                    row.update(executed=True,original_size=[image.shape[1],image.shape[0]],detections=detections,
                        target_class_candidates=[d for d in detections if d['class_id'] in target],
                        raw_file=rawfile.name,raw_sha256=sha256(rawfile),raw_target_score_distribution=score_distribution(scores[target[0]]),
                        raw_target_class_index=target[0],class_names=names,post_nms_cap_reached=len(detections)==100,
                        elapsed_ms=round(elapsed,3),peak_allocated_bytes=torch.cuda.max_memory_allocated(),
                        status='DIAGNOSTIC_ONLY_NOT_FOUND',reason='post_nms_candidates_or_empty; score_after_inference',
                        cold_call=len(rows)==0)
                    if threshold in (.001,.25):
                        ok,buf=cv2.imencode('.jpg',result.plot())
                        if not ok: raise Blocked('Overlay encoding failed')
                        (output/(prefix+'.private.jpg')).write_bytes(buf.tobytes())
                except Exception as exc:
                    row.update(executed=False,status='ERROR',reason=type(exc).__name__+': '+str(exc))
                rows.append(row)
                (output/'predictions.private.json').write_text(json.dumps(rows,indent=2)+'\n',encoding='utf-8')
            print(f'{model_id} size={size} conf={threshold:g} executed={sum(r["executed"] for r in rows)}/{len(rows)}',flush=True)
    validate_rows(rows,hashes)
    if hashes!={p.name:sha256(p) for p in files} or sha256(weights)!=weight_hash:
        raise Blocked('Originals or model changed during diagnosis')
    completion={'status':'COMPLETED','model_id':model_id,'weight_sha256':weight_hash,'rows':len(rows),
        'input_hashes':hashes,'predictions_sha256':sha256(output/'predictions.private.json'),
        'environment_sha256':sha256(output/'environment.public.json'),'labels_read':False,'originals_unchanged':True}
    (output/'completion.private.json').write_text(json.dumps(completion,indent=2)+'\n',encoding='utf-8')
    return completion


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for key in ('weights','data-root','output-dir'): p.add_argument('--'+key,type=Path,required=True)
    p.add_argument('--model-id',choices=(*OLD_WEIGHTS,'no-warmup'),required=True)
    a=p.parse_args()
    result=run(a.weights,a.model_id,a.data_root,a.output_dir,Path(__file__).resolve().parents[1])
    print(json.dumps({k:result[k] for k in ('status','model_id','rows')}))
