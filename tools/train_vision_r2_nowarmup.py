"""One separately authorized controlled run. Historical two-trial runner is unchanged."""
import argparse
import csv
import importlib.metadata
import inspect
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import time

from diagnose_vision_r2_confidence import OLD_WEIGHTS, THRESHOLDS, SIZES, validate_rows
from train_vision_r2 import build_train_args, deny_network, stage_dataset, validate_inputs
from vision_r2_data import Blocked, require_private, sha256


def controlled_arguments(baseline, staged, destination):
    expected=build_train_args(staged,destination,'low-lr-finetune',50)
    ignored={'data','project'}
    if {k:v for k,v in baseline.items() if k not in ignored}!={k:v for k,v in expected.items() if k not in ignored}:
        raise Blocked('Frozen baseline configuration differs from reviewed low-lr configuration')
    result=dict(baseline,data=str(staged/'data.yaml'),project=str(destination),warmup_epochs=0.0)
    changes={k:(baseline[k],result[k]) for k in baseline if baseline[k]!=result[k] and k not in ignored}
    if changes!={'warmup_epochs':(1.0,0.0)}: raise Blocked('Only warmup_epochs may change')
    return result


def claim_attempt(ledger, details):
    ledger.parent.mkdir(parents=True,exist_ok=True)
    try:
        with ledger.open('x',encoding='utf-8') as stream:
            json.dump(details,stream,indent=2); stream.write('\n')
    except FileExistsError as exc:
        raise Blocked('The one authorized controlled attempt is already reserved; no retry or alternate output') from exc


def verify_gate(path, expected_sha, repo, annotations_sha):
    path=require_private(repo,path)
    if sha256(path)!=expected_sha: raise Blocked('Phase A gate hash mismatch')
    gate=json.loads(path.read_text(encoding='utf-8'))
    if (gate.get('schema_version')!=1 or gate.get('status')!='COMPLETED' or gate.get('phase')!='A_before_training'
            or gate.get('total_executed_rows')!=540 or gate.get('thresholds')!=list(THRESHOLDS)
            or gate.get('sizes')!=list(SIZES) or gate.get('business_confidence')!=.25
            or gate.get('annotations_sha256')!=annotations_sha or set(gate.get('models',{}))!=set(OLD_WEIGHTS)):
        raise Blocked('Incomplete pre-training diagnosis gate')
    same_inputs=None
    for model,binding in gate['models'].items():
        directory=require_private(repo,Path(binding['directory']))
        scores=require_private(repo,Path(binding['score_directory']))
        for file,digest in ((directory/'completion.private.json',binding['completion_sha256']),
                            (directory/'predictions.private.json',binding['predictions_sha256']),
                            (scores/'scores.private.json',binding['scores_sha256']),
                            (scores/'metrics.public.json',binding['metrics_sha256'])):
            if sha256(file)!=digest: raise Blocked('Diagnostic or post-hoc scoring evidence changed')
        completion=json.loads((directory/'completion.private.json').read_text(encoding='utf-8'))
        predictions=json.loads((directory/'predictions.private.json').read_text(encoding='utf-8'))
        score_data=json.loads((scores/'scores.private.json').read_text(encoding='utf-8'))
        if (completion.get('status')!='COMPLETED' or completion.get('labels_read') is not False
                or completion.get('model_id')!=model or completion.get('weight_sha256')!=OLD_WEIGHTS[model]
                or binding['weight_sha256']!=OLD_WEIGHTS[model]
                or completion['predictions_sha256']!=binding['predictions_sha256']
                or score_data['bindings']['predictions_sha256']!=binding['predictions_sha256']
                or score_data['bindings']['annotations_sha256']!=annotations_sha):
            raise Blocked('Phase A checkpoint or scoring binding inconsistent')
        validate_rows(predictions,completion['input_hashes'])
        if len(score_data['rows'])!=180 or any(not r.get('executed') for r in score_data['rows']):
            raise Blocked('Post-hoc scoring has unexecuted items')
        # Preserve raw score evidence too, not just a summary declaring success.
        for row in predictions:
            raw=(directory/row['raw_file']).resolve()
            if not raw.is_relative_to(directory) or sha256(raw)!=row['raw_sha256']:
                raise Blocked('Raw diagnostic artifact changed')
        if same_inputs is not None and completion['input_hashes']!=same_inputs:
            raise Blocked('Models were evaluated on different originals')
        same_inputs=completion['input_hashes']
    return gate,same_inputs


def run(repo, gate_path, gate_sha):
    old=repo/'artifacts/vision-r2-issue19'
    root=require_private(repo,repo/'artifacts/vision-r2-followup')
    destination=root/'nowarmup'
    ledger=root/'controlled-training-attempt.json'
    if ledger.exists() or destination.exists(): raise Blocked('Controlled attempt/output already exists; stopped before training')
    baseline_path=old/'trials-02/low-lr-finetune/training-evidence.private.json'
    baseline=json.loads(baseline_path.read_text(encoding='utf-8'))
    if baseline.get('status')!='TRAINING_COMPLETED_EVALUATION_REQUIRED' or baseline.get('trial')!='low-lr-finetune':
        raise Blocked('Completed historical baseline required')
    dataset,weights,_,record=validate_inputs(old/'dataset-02',old/'weights/yolo11n.pt',OLD_WEIGHTS['pretrained'],
        root/'validation-only-no-training','low-lr-finetune',repo)
    if (sha256(dataset/'prepared.private.json')!=baseline['dataset_binding_sha256']
            or record['manifest_sha256']!=baseline['dataset_manifest_sha256']):
        raise Blocked('Dataset differs from frozen low-lr baseline')
    gate,input_hashes=verify_gate(gate_path,gate_sha,repo,record['manifest_sha256'])
    if {Path(r['path']).name:r['sha256'] for r in record['samples']}!=input_hashes:
        raise Blocked('Training and diagnosed originals differ')
    args=controlled_arguments(baseline['arguments'],destination/'working-dataset',destination)
    for package,version in baseline['versions'].items():
        if importlib.metadata.version(package)!=version: raise Blocked('Version differs from baseline: '+package)
    if importlib.metadata.version('ultralytics')!='8.3.221': raise Blocked('Pinned trainer required')
    config=root/'training-preflight-settings'
    (config/'Ultralytics').mkdir(parents=True,exist_ok=True)
    font=Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts/arial.ttf'
    if font.is_file(): shutil.copyfile(font,config/'Ultralytics/Arial.ttf')
    os.environ.update(YOLO_CONFIG_DIR=str(config),YOLO_OFFLINE='true',YOLO_AUTOINSTALL='false',WANDB_MODE='disabled',COMET_MODE='DISABLED',MPLCONFIGDIR=str(root/'training-mpl'))
    socket.socket.connect=deny_network; socket.socket.connect_ex=deny_network
    socket.create_connection=deny_network; socket.getaddrinfo=deny_network
    import torch
    import yaml
    from ultralytics import YOLO,settings
    from ultralytics.engine.trainer import BaseTrainer
    if not torch.cuda.is_available() or torch.cuda.get_device_name(0)!=baseline['gpu_name']:
        raise Blocked('Same CUDA GPU required')
    trainer_source=inspect.getsource(BaseTrainer._do_train)
    required='nw = max(round(self.args.warmup_epochs * nb), 100) if self.args.warmup_epochs > 0 else -1'
    if required not in trainer_source or 'if ni <= nw:' not in trainer_source:
        raise Blocked('Installed warmup logic differs from inspected version')
    settings.update({k:False for k in ('sync','hub','clearml','comet','dvc','mlflow','neptune','raytune','tensorboard','wandb')})
    settings.update({'api_key':'','openai_api_key':''})
    torch.cuda.init(); torch.cuda.synchronize(0); torch.cuda.reset_peak_memory_stats(0); torch.set_num_threads(4)
    model=YOLO(str(weights))
    if not model.ckpt or model.task!='detect' or len(model.names)!=80 or model.names.get(41)!='cup':
        raise Blocked('Same COCO pretrained detector required')
    baseline_resolved=yaml.safe_load((old/'trials-02/low-lr-finetune/training/args.yaml').read_text(encoding='utf-8'))
    original_bindings={str(baseline_path):sha256(baseline_path),str(weights):sha256(weights)}
    for model_id,relative in [('freeze-backbone','freeze-backbone'),('low-lr-finetune','low-lr-finetune')]:
        p=old/'trials-02'/relative/'training/weights/best.pt'
        if sha256(p)!=OLD_WEIGHTS[model_id]: raise Blocked('Old model changed')
        original_bindings[str(p)]=sha256(p)
    evidence={'status':'RESERVED','authorization':'User follow-up: exactly one warmup_epochs=0 controlled trial; original two-trial quota unchanged',
        'source_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip(),
        'driver_sha256':sha256(Path(__file__)),'phase_a_gate_sha256':gate_sha,'baseline_evidence_sha256':sha256(baseline_path),
        'arguments':args,'changed_training_factors':{'warmup_epochs':{'before':1.0,'after':0.0}},
        'versions':baseline['versions'],'pretrained_sha256':OLD_WEIGHTS['pretrained'],
        'dataset_binding_sha256':baseline['dataset_binding_sha256'],'independent_test':False,
        'warmup_logic_verified':True,'effective_warmup_iterations':-1,
        'trainer_source_sha256':sha256(Path(inspect.getfile(BaseTrainer))),
        'optimizer_steps':0,'batch_callbacks':0,'gpu':torch.cuda.get_device_name(0),'cuda':torch.version.cuda}
    claim_attempt(ledger,{'status':'RESERVED_ONCE','gate_sha256':gate_sha,'destination':str(destination),'source_commit':evidence['source_commit']})
    destination.mkdir(parents=True,exist_ok=False)
    started=time.perf_counter()
    path=destination/'training-evidence.private.json'
    def save():
        evidence['wall_seconds']=time.perf_counter()-started
        path.write_text(json.dumps(evidence,indent=2)+'\n',encoding='utf-8')
    try:
        staged=stage_dataset(dataset,destination)
        def on_start(trainer):
            resolved=vars(trainer.args)
            ignored={'model','data','project','save_dir'}
            differences={k:{'before':baseline_resolved.get(k),'after':resolved.get(k)} for k in set(baseline_resolved)|set(resolved)
                if k not in ignored and baseline_resolved.get(k)!=resolved.get(k)}
            if differences!={'warmup_epochs':{'before':1.0,'after':0.0}}:
                raise Blocked('Resolved framework configuration has additional differences: '+str(differences))
            evidence['resolved_parameter_differences']=differences
            evidence['batches_per_epoch']=len(trainer.train_loader)
            def step_done(optimizer,unused_args,unused_kwargs):
                evidence['optimizer_steps']+=1
                item={'step':evidence['optimizer_steps'],'epoch':int(trainer.epoch)+1,'batch_seen':evidence['batch_callbacks'],
                    'learning_rates':[float(g['lr']) for g in optimizer.param_groups],
                    'weight_decays':[float(g['weight_decay']) for g in optimizer.param_groups],
                    'optimizer':'AdamW','hook':'actual optimizer.register_step_post_hook',
                    'wall_seconds':time.perf_counter()-started}
                with (destination/'optimizer-steps.private.jsonl').open('a',encoding='utf-8') as stream: stream.write(json.dumps(item)+'\n')
            trainer.optimizer.register_step_post_hook(step_done)
        def batch_start(trainer): evidence['batch_callbacks']+=1
        def epoch_end(trainer):
            item={'epoch':int(trainer.epoch)+1,'losses':trainer.tloss.detach().cpu().tolist(),'optimizer_steps':evidence['optimizer_steps'],
                'learning_rates':[float(g['lr']) for g in trainer.optimizer.param_groups],
                'peak_allocated_bytes':torch.cuda.max_memory_allocated(0)}
            with (destination/'epochs.private.jsonl').open('a',encoding='utf-8') as stream: stream.write(json.dumps(item)+'\n')
            save()
        model.add_callback('on_train_start',on_start)
        model.add_callback('on_train_batch_start',batch_start)
        model.add_callback('on_train_epoch_end',epoch_end)
        evidence['status']='TRAINING';save()
        model.train(**args)
        torch.cuda.synchronize(0)
        if any(sha256(dataset/n)!=h for n,h in record['files'].items()) or any(sha256(Path(s['path']))!=s['sha256'] for s in record['samples']):
            raise Blocked('Reviewed export or originals changed')
        if any(sha256(Path(p))!=h for p,h in original_bindings.items()): raise Blocked('Historical model/evidence changed')
        working_same=all(sha256(staged/change['path'])==change['working_sha256'] for change in baseline['training_working_image_changes'])
        labels_same=all(sha256(staged/n)==h for n,h in record['files'].items() if n.startswith('labels/'))
        if not working_same or not labels_same: raise Blocked('Training working images or labels differ from prior baseline')
        artifacts={}
        for name in ('weights/best.pt','weights/last.pt','results.csv','results.png','args.yaml'):
            file=destination/'training'/name
            if not file.is_file() or not file.stat().st_size: raise Blocked('Required output missing: '+name)
            artifacts[name]={'sha256':sha256(file),'bytes':file.stat().st_size}
        epochs=list(csv.DictReader((destination/'training/results.csv').open(encoding='utf-8')))
        evidence.update(status='COMPLETED',epochs_completed=len(epochs),artifacts=artifacts,
            best_weight_sha256=artifacts['weights/best.pt']['sha256'],last_weight_sha256=artifacts['weights/last.pt']['sha256'],
            peak_allocated_bytes=torch.cuda.max_memory_allocated(0),peak_reserved_bytes=torch.cuda.max_memory_reserved(0),
            originals_unchanged=True,old_models_unchanged=True,working_images_equal_to_baseline=True,labels_unchanged=True)
        save();return evidence
    except Exception as exc:
        import traceback
        (destination/'failure.private.log').write_text(traceback.format_exc(),encoding='utf-8')
        evidence.update(status='BLOCKED',reason=type(exc).__name__+': '+str(exc));save();raise


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--diagnostic-gate',type=Path,required=True)
    parser.add_argument('--gate-sha256',required=True)
    args=parser.parse_args()
    result=run(Path(__file__).resolve().parents[1],args.diagnostic_gate,args.gate_sha256)
    print(json.dumps({k:result[k] for k in ('status','epochs_completed','optimizer_steps','best_weight_sha256')}))
