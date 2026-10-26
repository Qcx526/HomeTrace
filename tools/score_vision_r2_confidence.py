"""Post-hoc reviewed-GT scoring, after complete label-free diagnostic inference."""
import argparse
import json
from pathlib import Path

from diagnose_vision_r2_confidence import OLD_WEIGHTS, THRESHOLDS, SIZES, score_distribution, validate_rows
from score_vision_r2 import iou, score_boxes, summarize
from vision_r2_data import Blocked, require_private, sha256, validate_manifest


def raw_localization(boxes, scores, truth):
    import numpy as np
    boxes=np.asarray(boxes,dtype=float); scores=np.asarray(scores,dtype=float)
    if boxes.ndim!=2 or boxes.shape[1]!=4 or len(boxes)!=len(scores) or not np.isfinite(boxes).all():
        raise Blocked('Invalid raw prediction array')
    overlaps=np.zeros(len(scores))
    for target in truth:
        b=np.asarray(target)
        intersection=np.maximum(0,np.minimum(boxes[:,2:],b[2:])-np.maximum(boxes[:,:2],b[:2])).prod(axis=1)
        area=np.maximum(0,boxes[:,2:]-boxes[:,:2]).prod(axis=1)
        union=area+(b[2]-b[0])*(b[3]-b[1])-intersection
        overlaps=np.maximum(overlaps,np.divide(intersection,union,out=np.zeros_like(intersection),where=union>0))
    correct=overlaps>=.5
    top=int(np.argmax(scores)) if len(scores) else None
    best_correct=int(np.argmax(np.where(correct,scores,-1))) if correct.any() else None
    return {'highest_score':float(scores[top]) if top is not None else None,
        'highest_score_iou':float(overlaps[top]) if top is not None and truth else None,
        'best_iou':float(overlaps.max()) if len(scores) and truth else None,
        'highest_correct_score':float(scores[best_correct]) if best_correct is not None else None,
        'highest_correct_iou':float(overlaps[best_correct]) if best_correct is not None else None,
        'correct_raw_boxes_above':{str(t):int((correct & (scores>t)).sum()) for t in THRESHOLDS}}


def score_model(directory, annotations, data_root, output, repo):
    import numpy as np
    directory,annotations,data_root,output=[require_private(repo,p) for p in (directory,annotations,data_root,output)]
    if output.exists(): raise Blocked('Scoring output already exists')
    # Require finished inference before loading any annotations.
    completion=json.loads((directory/'completion.private.json').read_text(encoding='utf-8'))
    if completion.get('status')!='COMPLETED' or completion.get('labels_read') is not False:
        raise Blocked('Inference has not completed without labels')
    if completion['predictions_sha256']!=sha256(directory/'predictions.private.json') or completion['environment_sha256']!=sha256(directory/'environment.public.json'):
        raise Blocked('Diagnostic output binding mismatch')
    source=json.loads((directory/'predictions.private.json').read_text(encoding='utf-8'))
    validate_rows(source,completion['input_hashes'])
    manifest=json.loads(annotations.read_text(encoding='utf-8-sig'))
    validate_manifest(manifest,data_root)
    by_path={r['path']:r for r in manifest['images']}
    if {r['path']:r['sha256'] for r in manifest['images']}!=completion['input_hashes']:
        raise Blocked('Reviewed GT does not bind exactly to diagnostic inputs')
    rows=[]
    for p in source:
        ann=by_path[p['path']]
        if ann['split']=='excluded': raise Blocked('This frozen experiment requires all 18 reviewed inputs')
        truth=[b['xyxy'] for b in ann['boxes']]
        pred=p['target_class_candidates']
        result=score_boxes(pred,truth)
        top=max(pred,key=lambda r:r['confidence'],default=None)
        rawfile=(directory/p['raw_file']).resolve()
        if not rawfile.is_relative_to(directory) or sha256(rawfile)!=p['raw_sha256']:
            raise Blocked('Raw score artifact mismatch')
        with np.load(rawfile,allow_pickle=False) as raw:
            scores=raw['scores'][p['raw_target_class_index']]
            rawdiag=raw_localization(raw['boxes_xyxy_original'],scores,truth)
            distribution=score_distribution(scores)
        if distribution!=p['raw_target_score_distribution']:
            raise Blocked('Raw score summary differs from saved tensor')
        rows.append({'sample_id':ann['sample_id'],'imgsz':p['imgsz'],'threshold':p['threshold'],
            'split':ann['split'],'label':ann['label'],'executed':True,'candidate_count':len(pred),
            'elapsed_ms':p['elapsed_ms'],'highest_candidate':top,
            'highest_candidate_iou':max((iou(top['bbox_xyxy'],b) for b in truth),default=None) if top else None,
            'highest_correct_post_nms_score':max((x['confidence'] for x in pred if any(iou(x['bbox_xyxy'],b)>=.5 for b in truth)),default=None),
            'negative_candidate_distribution':score_distribution([x['confidence'] for x in pred]) if not truth else None,
            'raw':rawdiag,'post_nms_cap_reached':p['post_nms_cap_reached'],**result})
    groups={}
    for size in SIZES:
        groups[str(size)]={}
        for t in THRESHOLDS:
            groups[str(size)][str(t)]={}
            for split in ('train','val','all'):
                subset=[r for r in rows if r['imgsz']==size and r['threshold']==t and (split=='all' or r['split']==split)]
                positive=[r for r in subset if r['label']=='present']
                negative=[r for r in subset if r['label']=='absent']
                groups[str(size)][str(t)][split]={**summarize(subset),
                    'post_nms_cap_images':sum(r['post_nms_cap_reached'] for r in subset),
                    'positive_images_with_correct_raw_box_above_threshold':sum(r['raw']['correct_raw_boxes_above'][str(t)]>0 for r in positive),
                    'positive_top_raw_scores':score_distribution([r['raw']['highest_score'] for r in positive]),
                    'negative_top_raw_scores':score_distribution([r['raw']['highest_score'] for r in negative]),
                    'positive_best_correct_raw_scores':score_distribution([r['raw']['highest_correct_score'] for r in positive if r['raw']['highest_correct_score'] is not None]),
                    'negative_post_nms_candidate_scores':score_distribution([x['confidence'] for p in source if p['imgsz']==size and p['threshold']==t and by_path[p['path']]['label']=='absent' and (split=='all' or by_path[p['path']]['split']==split) for x in p['target_class_candidates']])}
    summary={'status':'COMPLETED','model_id':completion['model_id'],'weight_sha256':completion['weight_sha256'],
        'business_confidence':.25,'diagnostic_thresholds':THRESHOLDS,'localization_iou':.5,
        'independent_test':False,'production_found':False,'group_metrics':groups,
        'note':'Raw geometry is pre-NMS target-class score, not an accepted prediction; max_det=100 can truncate low-threshold post-NMS rows. No threshold selection.'}
    output.mkdir(parents=True)
    private={'bindings':{'annotations_sha256':sha256(annotations),'predictions_sha256':completion['predictions_sha256'],
        'completion_sha256':sha256(directory/'completion.private.json')},'rows':rows}
    (output/'scores.private.json').write_text(json.dumps(private,indent=2)+'\n',encoding='utf-8')
    (output/'metrics.public.json').write_text(json.dumps(summary,indent=2)+'\n',encoding='utf-8')
    return summary


def build_gate(diagnostics, scoring_root, annotations, gate_path, repo):
    """Training gate binds all three completed old-model grids and post-hoc scores."""
    if gate_path.exists(): raise Blocked('Gate already exists')
    models={}
    for directory in diagnostics:
        d=json.loads((directory/'completion.private.json').read_text(encoding='utf-8'))
        model=d['model_id']
        if model in models or model not in OLD_WEIGHTS or d['weight_sha256']!=OLD_WEIGHTS[model]:
            raise Blocked('Expected three distinct frozen old models')
        score_dir=scoring_root/model
        summary=json.loads((score_dir/'metrics.public.json').read_text(encoding='utf-8'))
        if summary['status']!='COMPLETED': raise Blocked('Post-hoc scoring incomplete')
        models[model]={ 'directory':str(directory),'score_directory':str(score_dir),
            'weight_sha256':d['weight_sha256'],'completion_sha256':sha256(directory/'completion.private.json'),
            'predictions_sha256':sha256(directory/'predictions.private.json'),
            'scores_sha256':sha256(score_dir/'scores.private.json'),'metrics_sha256':sha256(score_dir/'metrics.public.json')}
    if set(models)!=set(OLD_WEIGHTS): raise Blocked('All three frozen-model diagnostics required')
    gate={'schema_version':1,'status':'COMPLETED','phase':'A_before_training','models':models,
        'annotations_sha256':sha256(annotations),'thresholds':THRESHOLDS,'sizes':SIZES,
        'total_executed_rows':540,'business_confidence':.25,'independent_test':False}
    gate_path.write_text(json.dumps(gate,indent=2)+'\n',encoding='utf-8')
    return gate


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--diagnostics',nargs='+',type=Path,required=True)
    for key in ('annotations','data-root','output-dir'): p.add_argument('--'+key,type=Path,required=True)
    p.add_argument('--phase-a-gate',action='store_true')
    a=p.parse_args(); repo=Path(__file__).resolve().parents[1]
    output=require_private(repo,a.output_dir)
    if output.exists(): raise Blocked('Never overwrite score root')
    output.mkdir(parents=True)
    dirs=[require_private(repo,d) for d in a.diagnostics]
    for directory in dirs:
        model=json.loads((directory/'completion.private.json').read_text(encoding='utf-8'))['model_id']
        score_model(directory,a.annotations,a.data_root,output/model,repo)
        print(model+': post-hoc scoring COMPLETED',flush=True)
    if a.phase_a_gate:
        build_gate(dirs,output,a.annotations,output/'phase-a-gate.private.json',repo)
        print('Phase A complete; gate SHA256 '+sha256(output/'phase-a-gate.private.json'))
