"""Opt-in empty-workspace acceptance via the same HTTP endpoints as the UI.

Real configured LLM and ORB, explicitly synthetic images, simulated navigation.
Operator actions are scripted HTTP requests, NOT browser interaction evidence.
No prepared workspace or preloaded owner history is used. Never overwrites runs.
"""
import argparse
import base64
from dataclasses import asdict
import hashlib
import importlib.metadata
import json
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import time
from urllib.request import Request, urlopen


CUSTOM_LOCATIONS = [
    {'location_id': 'a-new-table', 'location_name': '软件样例新桌'},
    {'location_id': 'm-rival-shelf', 'location_name': '软件样例干扰架'},
    {'location_id': 'z-history-tray', 'location_name': '软件样例历史托盘'},
]


def prepare_custom_locations(workspace):
    """Only place configuration precedes boot; no objects, history or evidence."""
    workspace.mkdir(exist_ok=False)
    (workspace / 'locations.json').write_text(
        json.dumps({'version': 1, 'locations': CUSTOM_LOCATIONS}, ensure_ascii=False) + '\n', encoding='utf-8')


def bounded_config(output):
    """Keep production settings unchanged; no retries or image-network mode."""
    from hometrace.agent_config import load_agent_config
    import yaml
    config = load_agent_config()
    document = {'llm': {**asdict(config.llm), 'max_retries': 0, 'timeout_seconds': 45},
                'agent': {**asdict(config.agent), 'max_model_calls': min(config.agent.max_model_calls, 10)},
                'vision': {'backend': 'orb'},
                'privacy': {'send_raw_images_to_llm': False, 'external_tracing_enabled': False}}
    path = output / 'bounded-config.private.yaml'
    with path.open('x', encoding='utf-8') as file:
        yaml.safe_dump(document, file, sort_keys=False)
    return path, document


def usage_totals(runs):
    """State snapshots repeat cumulative counters: count each run only once."""
    unique = {}
    for run in runs.values():
        previous = unique.get(run['run_id'], {})
        unique[run['run_id']] = {key: max(previous.get(key, 0), run.get(key, 0))
                                 for key in ('model_calls', 'total_tokens')}
    return {'unique_runs': len(unique), **{key: sum(run[key] for run in unique.values())
                                          for key in ('model_calls', 'total_tokens')}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--images', type=Path, default=Path('local_data/ai_html_test_20261027'))
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--custom-locations', action='store_true',
                        help='Exercise custom places with history last in alphabetical/config order')
    args = parser.parse_args()
    output, images = args.output_dir.resolve(), args.images.resolve()
    if output.exists():
        parser.error('Output must be new; previous evidence is never overwritten')
    repo = Path(__file__).resolve().parents[1]
    try:
        relative = output.relative_to(repo)
    except ValueError:
        parser.error('Output must be inside the repository and Git ignored')
    if subprocess.run(['git', 'check-ignore', '--quiet', str(relative / 'summary.json')],
                      cwd=repo, capture_output=True, check=False).returncode:
        parser.error('Output must be Git ignored')
    expected = {
        '01_reference_keys.png':'3cc149287c013dd6b9ff8f4ff9f54a4d32d9dfeb5b4200612ec2ea0d40e94fe8',
        '03_keys_study_desk.png':'ac06b717b7171daa0b4b26c6adcbb1556938717929b7a68d53ba785494239502',
        '04_rival_red_keys.png':'5646c45ed7f793136e85ce9183a96d6ef9055af428d47a35ce4215fa447d3b50',
        '05_empty_entry_tray.png':'0b66fbf63b2255ecd3d2535974e0a730403e88c35c9038a67663006a879ae307',
    }
    manifest = json.loads((images/'manifest.json').read_text(encoding='utf-8'))
    assert manifest.get('not_real_household_data') is True
    for name, digest in expected.items():
        assert hashlib.sha256((images/name).read_bytes()).hexdigest() == digest
    output.mkdir(parents=True)
    config_path, runtime_config = bounded_config(output)
    old_place, new_place, rival_place = (('z-history-tray', 'a-new-table', 'm-rival-shelf')
                                        if args.custom_locations else ('entry-tray', 'study-desk', 'living-table'))
    overall_deadline = time.monotonic() + 900
    process = log = base = None
    summary = {'source':'synthetic', 'transport':'HTTP, not browser', 'navigation':'simulated',
               'requested_real_llm':True, 'checks_passed':False, 'input_sha256':expected,
               'initial_workspaces':[], 'runs':{}, 'checks':[], 'http':[], 'processes':[],
               'custom_locations': CUSTOM_LOCATIONS if args.custom_locations else None,
               'scripted_owner_actions': True, 'independent_household_validation': False,
               'image_calls': 0, 'limits': {'max_new_runs': 6, 'max_calls_per_run': runtime_config['agent']['max_model_calls'],
                                         'max_provider_retries': 0, 'overall_seconds': 900, 'per_run_seconds': 240},
               'execution': {'head': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=repo, text=True).strip(),
                             'source_sha256': {p.relative_to(repo).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                                               for p in [*sorted((repo/'src/hometrace').glob('*.py')), Path(__file__).resolve()]},
                             'versions': {name: importlib.metadata.version(name) for name in
                                          ('hometrace', 'openai', 'Pillow', 'langgraph', 'langchain-core', 'langchain-openai')}}}
    new_runs = 0

    def save():
        (output/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

    def check(name, condition):
        summary['checks'].append({'name':name,'passed':bool(condition)})
        save()
        assert condition, name

    def call(path, value=None):
        nonlocal new_runs
        if time.monotonic() > overall_deadline:
            raise TimeoutError('Overall acceptance deadline')
        if path == '/api/home-flow/start':
            if new_runs >= 6:
                raise ValueError('New-run budget exhausted')
            new_runs += 1
        if path == '/api/home-flow/act' and value.get('action') in ('retry', 'approve_vision'):
            raise ValueError('Provider retry and image-network actions are prohibited')
        req = Request(base+path,data=json.dumps(value,ensure_ascii=False).encode() if value is not None else None,
                      headers={'Content-Type':'application/json','Origin':base})
        with urlopen(req,timeout=30) as r:
            result=json.load(r)
        summary['http'].append({'path':path,'input':{k:v for k,v in value.items() if k!='data_base64'} if value else None,'output':result})
        return result

    def stop():
        nonlocal process, log
        if process:
            process.terminate()
            try: process.wait(10)
            except subprocess.TimeoutExpired: process.kill(); process.wait(5)
            process=None
        if log: log.close(); log=None

    def start(index, home, fresh=False):
        nonlocal process, log, base
        stop()
        workspace=output/home
        if fresh:
            check(f'{home}: directory absent before first boot',not workspace.exists())
            if args.custom_locations:
                prepare_custom_locations(workspace)
        logfile=output/f'server-{index}.log'
        log=logfile.open('xb')
        process=subprocess.Popen([sys.executable,'-X','utf8','-m','hometrace','demo','--photo-agent','--port','0',
                                  '--config',str(config_path),'--household-dir',str(workspace),
                                  '--output-dir',str(output/'classic')],stdout=log,stderr=subprocess.STDOUT)
        summary['processes'].append({'stage': index, 'pid': process.pid})
        for _ in range(600):
            match=re.search(r'HomeTrace demo: (http://127\.0\.0\.1:\d+)',logfile.read_text(encoding='utf-8'))
            if match:
                base=match.group(1)
                config=call('/api/home-flow/config')
                check(f'{index}: real model available',config['mode']=='llm_langgraph' and config['model_available'])
                check(f'{index}: image advisor disabled',not config.get('visual_advisor_enabled', False))
                if args.custom_locations:
                    check(f'{index}: custom places preserved',config['locations'] == CUSTOM_LOCATIONS)
                if fresh:
                    with sqlite3.connect((workspace/'photo-flow.sqlite3').as_uri()+'?mode=ro',uri=True) as db:
                        evidence=db.execute('SELECT count(*) FROM evidence').fetchone()[0]
                    summary['initial_workspaces'].append({'name':home,'catalog':config['catalog'],'scenes':config['scenes'],'evidence_count':evidence})
                    check(f'{home}: empty catalog/scenes/evidence',not config['catalog'] and not config['scenes'] and evidence==0)
                return
            if process.poll() is not None: raise RuntimeError('Server failed; inspect private log')
            time.sleep(.1)
        raise TimeoutError('Server startup')

    def wait(name, run):
        deadline=time.monotonic()+240
        while run['state']=='RUNNING' and time.monotonic()<deadline:
            time.sleep(.5)
            run=call('/api/home-flow/runs/'+run['run_id'])
        summary['runs'][name]=run
        save()
        print(json.dumps({'case':name,'state':run['state'],'calls':run.get('model_calls'),'visited':run['visited']},ensure_ascii=False),flush=True)
        check(name+': completed model step',run['state']!='RUNNING' and run['model_calls']>0)
        return run

    def request(name,message,location=None):
        return wait(name,call('/api/home-flow/start',{'message':message,'current_location_id':location}))

    def act(name,run,action):
        return wait(name,call('/api/home-flow/act',{'run_id':run['run_id'],'version':run['version'],'action':action}))

    def register():
        call('/api/household/enroll',{'object_id':'blue-keys','name':'蓝色钥匙','aliases':['蓝挂件钥匙']})
        assets={}
        for name in expected:
            assets[name]=call('/api/home-flow/assets',{'data_base64':base64.b64encode((images/name).read_bytes()).decode(),'source_kind':'synthetic'})
        call('/api/home-flow/reference',{'object_id':'blue-keys','asset_id':assets['01_reference_keys.png']['asset_id'],
                                        'roi':[110,120,1390,950],'roi_reviewed':True})
        check('reference saved from reviewed synthetic ROI',call('/api/home-flow/config')['catalog'][0]['reference']['roi']==[110,120,1390,950])
        return assets

    def remember(prefix):
        pending=request(prefix+'-remember-entry','请记住，蓝色钥匙我放在这里了。',old_place)
        check('remember waits for owner',pending['state']=='CONFIRM_MEMORY' and not pending['history'])
        saved=act(prefix+'-memory-confirmed',pending,'confirm_memory')
        check('one owner statement saved',saved['state']=='COMPLETED' and len(saved['history'])==1 and not saved['visual_confirmed'])

    def scene(assets,location,name):
        call('/api/home-flow/scene',{'location_id':location,'asset_id':assets[name]['asset_id']})

    try:
        start(1,'accept',fresh=True)
        assets=register()
        # Explicitly demonstrate replacement, not a preconfigured final scenario.
        scene(assets,old_place,'03_keys_study_desk.png')
        remember('accept')
        scene(assets,old_place,'05_empty_entry_tray.png')
        scene(assets,new_place,'03_keys_study_desk.png')
        scene(assets,rival_place,'04_rival_red_keys.png')
        candidate=request('find','蓝色钥匙找不到了，请先检查最近记录的位置，没找到再继续寻找。')
        check('old location checked then new candidate',candidate['state']=='AWAITING_REVIEW' and candidate['visited'][0]==old_place
              and candidate['visited'][-1]==new_place and len(set(candidate['visited']))==len(candidate['visited'])
              and candidate['candidate']['location_id']==new_place and not candidate['visual_confirmed'])
        check('refresh preserves candidate',call('/api/home-flow/runs/'+candidate['run_id'])==candidate)
        start(2,'accept')
        restored=call('/api/home-flow/runs/'+candidate['run_id'])
        check('process restart preserves candidate',restored==candidate)
        accepted=act('candidate-confirmed',restored,'accept_candidate')
        check('owner confirmation is not visual FOUND',accepted['state']=='USER_CONFIRMED' and not accepted['visual_confirmed'] and len(accepted['history'])==2)
        start(3,'accept')
        history=request('history-after-restart','蓝色钥匙最近一次记在哪里？')
        check('new process reads updated memory',history['state']=='COMPLETED' and len(history['history'])==2 and history['history'][0]['location_id']==new_place)
        replay=request('replay','请再帮我寻找蓝色钥匙。')
        check('used photos cannot confirm again',replay['state']=='UNKNOWN' and not replay['candidate'])
        start(4,'reject',fresh=True)
        assets=register();remember('reject')
        for location,name in [(old_place,'05_empty_entry_tray.png'),(new_place,'03_keys_study_desk.png'),(rival_place,'04_rival_red_keys.png')]:
            scene(assets,location,name)
        candidate=request('reject-find','蓝色钥匙找不到了，请先检查最近记录的位置，没找到再继续寻找。')
        check('reject branch has actual candidate',candidate['state']=='AWAITING_REVIEW')
        rejected=act('reject-continue',candidate,'reject_candidate')
        check('rejection triggers model and no new memory',rejected['state']=='UNKNOWN' and rejected['model_calls']>candidate['model_calls'] and len(rejected['history'])==1 and not rejected['candidate'])
        summary['checks_passed']=True
    except Exception as exc:
        summary['failure_type']=type(exc).__name__
        print('Acceptance failed; partial evidence retained.',flush=True)
        raise
    finally:
        stop()
        summary['usage'] = usage_totals(summary['runs'])
        save()


if __name__=='__main__':
    main()
