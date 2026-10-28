"""Opt-in real API + real ORB HTTP demonstration on explicitly synthetic images.

Never used by pytest. Requires local API configuration and the reviewed image
pack. Saves private evidence to a new directory and never overwrites old runs.
Owner accept/reject HTTP actions represent scripted operator button presses.
"""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--images', type=Path, default=Path('local_data/ai_html_test_20261027'))
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--config', type=Path)
    args = parser.parse_args()
    images, output = args.images.resolve(), args.output_dir.resolve()
    if output.exists():
        parser.error('Use a new output directory; old evidence must remain unchanged')
    manifest = json.loads((images/'manifest.json').read_text(encoding='utf-8'))
    if manifest.get('not_real_household_data') is not True:
        parser.error('Only the explicitly synthetic pack is accepted by this demonstration')
    for item in manifest['files']:
        path = (images/item['file']).resolve()
        if not path.is_relative_to(images) or hashlib.sha256(path.read_bytes()).hexdigest() != item['sha256']:
            parser.error('Image manifest path/hash mismatch')
    output.mkdir(parents=True)
    process = log = base = None
    requests, runs = [], {}
    summary = {'source':'synthetic_image', 'requested_real_llm_api':True, 'physical_robot':False,
               'independent_household_validation':False, 'checks_passed':False,
               'input_files':manifest['files'], 'runs':runs}

    def save():
        (output/'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
        (output/'http.json').write_text(json.dumps(requests, ensure_ascii=False, indent=2), encoding='utf-8')

    def stop():
        nonlocal process, log
        if process:
            process.terminate()
            try:
                process.wait(10)
            except subprocess.TimeoutExpired:
                process.kill(); process.wait(5)
            process = None
        if log:
            log.close(); log = None

    def start(index, home):
        nonlocal process, log, base
        stop()
        path = output/f'server-{index}.log'
        log = path.open('xb')
        command = [sys.executable, '-X', 'utf8', '-m', 'hometrace', 'demo', '--photo-agent',
                   '--port', '0', '--household-dir', str(output/home), '--output-dir', str(output/'classic')]
        if args.config:
            command += ['--config', str(args.config.resolve())]
        process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
        for _ in range(200):
            match = re.search(r'HomeTrace demo: (http://127\.0\.0\.1:\d+)', path.read_text(encoding='utf-8'))
            if match:
                base = match.group(1)
                assert call('/api/home-flow/config')['mode'] == 'llm_langgraph'
                return
            if process.poll() is not None:
                raise RuntimeError('Server startup failed; inspect private log')
            time.sleep(.1)
        raise RuntimeError('Server startup timeout')

    def call(path, value=None):
        body = None if value is None else json.dumps(value, ensure_ascii=False).encode()
        request = Request(base+path, data=body, headers={'Content-Type':'application/json','Origin':base})
        try:
            response = urlopen(request, timeout=30)
        except HTTPError as exc:
            response = exc
        with response:
            status, data = response.status, json.load(response)
        # Uploaded bytes are never copied into the log.
        requests.append({'path':path,'input':{k:v for k,v in value.items() if k!='data_base64'} if value else None,
                         'status':status,'output':data})
        assert status == 200, (path, status)
        return data

    def wait(name, run):
        deadline = time.monotonic()+360
        while run['state']=='RUNNING' and time.monotonic()<deadline:
            time.sleep(.5)
            run = call('/api/home-flow/runs/'+run['run_id'])
        runs[name] = run
        save()
        print(json.dumps({'case':name,'state':run['state'],'model_calls':run.get('model_calls'),
                          'visited':run['visited']}, ensure_ascii=False), flush=True)
        assert run['state'] != 'RUNNING', 'Execution timeout; saved partial evidence'
        return run

    def act(run, action):
        return call('/api/home-flow/act', {'run_id':run['run_id'],'version':run['version'],'action':action})

    def seed(negative=False):
        call('/api/household/enroll', {'object_id':'blue-keys','name':'蓝色钥匙','aliases':['钥匙','蓝挂件钥匙']})
        assets = {}
        for name in ('01_reference_keys.png','03_keys_study_desk.png','04_rival_red_keys.png','05_empty_entry_tray.png'):
            assets[name] = call('/api/home-flow/assets', {'data_base64':base64.b64encode((images/name).read_bytes()).decode(),
                                                         'source_kind':'synthetic'})
        call('/api/home-flow/reference', {'object_id':'blue-keys','asset_id':assets['01_reference_keys.png']['asset_id'],
                                         'roi':[110,120,1390,950],'roi_reviewed':True})
        mapping = [('entry-tray','05_empty_entry_tray.png'),('living-table','04_rival_red_keys.png')]
        if not negative:
            mapping.append(('study-desk','03_keys_study_desk.png'))
        for location, name in mapping:
            call('/api/home-flow/scene', {'location_id':location,'asset_id':assets[name]['asset_id']})

    def memory(name, location):
        run = wait(name, call('/api/home-flow/start', {'message':'请记一下，蓝色钥匙我就放在这儿了。',
                                                       'current_location_id':location}))
        assert run['state']=='CONFIRM_MEMORY' and run['model_calls']>0
        runs[name+'-confirmed'] = act(run, 'confirm_memory')
        save()

    try:
        start(1, 'home-accept'); seed()
        memory('remember-study', 'study-desk')
        memory('remember-entry', 'entry-tray')
        history = wait('history', call('/api/home-flow/start', {'message':'我之前跟你说，蓝色钥匙放在哪儿？'}))
        assert history['state']=='COMPLETED' and len(history['history'])==2
        request = {'message':'出门要用的蓝色钥匙不见了，帮我看看哪里有。'}
        found = wait('candidate', call('/api/home-flow/start', request))
        assert found['state']=='AWAITING_REVIEW' and found['candidate']['location_id']=='study-desk'
        assert found['model_calls']>1 and not found['visual_confirmed']
        start(2, 'home-accept')
        restored = call('/api/home-flow/runs/'+found['run_id'])
        assert restored == found
        runs['owner-confirmed'] = act(restored, 'accept_candidate')
        assert runs['owner-confirmed']['state']=='USER_CONFIRMED'
        replay = wait('replay', call('/api/home-flow/start', request))
        assert replay['state']=='UNKNOWN' and not replay['candidate']
        start(3, 'home-reject'); seed()
        memory('reject-remember-study','study-desk')
        candidate = wait('reject-candidate', call('/api/home-flow/start', request))
        assert candidate['state']=='AWAITING_REVIEW'
        rejected = wait('reject-continued', act(candidate,'reject_candidate'))
        assert rejected['state']=='UNKNOWN' and rejected['model_calls']>candidate['model_calls']
        start(4, 'home-negative'); seed(negative=True)
        missing = wait('negative', call('/api/home-flow/start', request))
        assert missing['state']=='UNKNOWN' and not missing['candidate']
        summary['checks_passed'] = True
    except Exception as exc:
        summary['failure_type'] = type(exc).__name__
        print('Verification stopped; actual and partial results preserved.', flush=True)
        raise
    finally:
        stop(); save()


if __name__ == '__main__':
    main()
