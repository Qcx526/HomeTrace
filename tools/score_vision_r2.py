"""Score saved predictions after inference against owner-reviewed boxes."""
import argparse
from collections import Counter
import json
import math
from pathlib import Path

from vision_r2_data import Blocked, require_private, sha256, validate_manifest


def iou(a, b):
    for box in (a, b):
        if (not isinstance(box, list) or len(box) != 4 or
                any(type(v) not in (int, float) or not math.isfinite(v) for v in box) or
                not 0 <= box[0] < box[2] or not 0 <= box[1] < box[3]):
            raise Blocked("Invalid box in prediction or reviewed annotation")
    area = max(0, min(a[2], b[2])-max(a[0], b[0])) * max(0, min(a[3], b[3])-max(a[1], b[1]))
    return area/((a[2]-a[0])*(a[3]-a[1])+(b[2]-b[0])*(b[3]-b[1])-area)


def score_boxes(predictions, truth):
    used = set()
    matches = []
    for index, pred in sorted(enumerate(predictions), key=lambda x: (-x[1]["confidence"], x[0])):
        confidence = pred.get("confidence")
        if type(confidence) not in (float, int) or not math.isfinite(confidence) or not 0 <= confidence <= 1:
            raise Blocked("Invalid prediction confidence")
        # Validate even when truth is empty.
        iou(pred["bbox_xyxy"], pred["bbox_xyxy"])
        options = [(iou(pred["bbox_xyxy"], box), j) for j, box in enumerate(truth) if j not in used]
        best = max(options, default=(0.0, -1))
        correct = best[0] >= .5
        if correct: used.add(best[1])
        matches.append({"prediction_index":index,"matched_truth":best[1] if correct else None,
                        "best_remaining_iou":best[0],"correct_localization":correct})
    return {"tp":len(used),"fp":len(predictions)-len(used),"fn":len(truth)-len(used),"matches":matches}


def summarize(rows):
    totals = {key:sum(r[key] for r in rows) for key in ("tp","fp","fn")}
    positives = [r for r in rows if r['label']=='present']
    negatives = [r for r in rows if r['label']=='absent']
    return {**totals, "images":len(rows),"positive_images":len(positives),"negative_images":len(negatives),
            "correctly_localized_positive_images":sum(r['tp']>0 for r in positives),
            "negative_images_with_candidates":sum(r['candidate_count']>0 for r in negatives),
            "precision":totals['tp']/(totals['tp']+totals['fp']) if totals['tp']+totals['fp'] else None,
            "recall":totals['tp']/(totals['tp']+totals['fn']) if totals['tp']+totals['fn'] else None,
            "negative_image_false_acceptance_rate":sum(r['candidate_count']>0 for r in negatives)/len(negatives) if negatives else None}


def run(predictions, annotations, data_root, output, repo):
    predictions, annotations, data_root, output = [require_private(repo,p) for p in (predictions,annotations,data_root,output)]
    if output.exists(): raise Blocked("Never overwrite scoring evidence")
    before = {"predictions":sha256(predictions),"annotations":sha256(annotations)}
    manifest = json.loads(annotations.read_text(encoding='utf-8'))
    samples = validate_manifest(manifest, data_root)
    by_path = {r['path']:r for r in manifest['images']}
    source = json.loads(predictions.read_text(encoding='utf-8'))
    seen = set()
    rows=[]
    for p in source:
        key=(p['path'],p['imgsz'])
        if key in seen or p['path'] not in by_path:
            raise Blocked("Duplicate or unknown prediction image")
        seen.add(key)
        record=by_path[p['path']]
        if p['sha256'] != record['sha256'] or not p['executed']:
            raise Blocked("Prediction image hash mismatch or unexecuted row")
        if record['split']=='excluded': continue
        result=score_boxes(p['target_class_candidates'],[b['xyxy'] for b in record['boxes']])
        rows.append({"sample_id":record['sample_id'],"imgsz":p['imgsz'],"split":record['split'],"label":record['label'],
            "candidate_count":len(p['target_class_candidates']),"elapsed_ms":p['elapsed_ms'],**result})
    for size in {r['imgsz'] for r in source}:
        if {p['path'] for p in source if p['imgsz']==size} != set(by_path):
            raise Blocked("Every input including failures must be evaluated at each size")
    groups={}
    for size in sorted({r['imgsz'] for r in rows}):
        groups[str(size)]={split:summarize([r for r in rows if r['imgsz']==size and (split=='all' or r['split']==split)])
                           for split in ('train','val','all')}
    assert before == {"predictions":sha256(predictions),"annotations":sha256(annotations)}
    output.mkdir(parents=True)
    (output/'scores.private.json').write_text(json.dumps({'bindings':before,'rows':rows},indent=2)+'\n',encoding='utf-8')
    summary={"iou_threshold":.5,"scope":"exploratory_fit; target appearance proxy, not physical instance identity",
        "independent_test":False,"threshold_tuned":False,"group_metrics":groups,
        "caution":"For COCO cup, non-target cups are correct category candidates but false target proposals; this is not COCO category precision."}
    (output/'metrics.public.json').write_text(json.dumps(summary,indent=2)+'\n',encoding='utf-8')
    return summary


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for arg in ('predictions','annotations','data-root','output-dir'): parser.add_argument('--'+arg,type=Path,required=True)
    args=parser.parse_args()
    print(json.dumps(run(args.predictions,args.annotations,args.data_root,args.output_dir,Path(__file__).resolve().parents[1])))
