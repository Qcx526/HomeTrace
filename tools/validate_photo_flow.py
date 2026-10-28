"""Run real HTTP/photo processing against a NEW private synthetic demo workspace.

This opt-in check uses the generated five-image demo pack, not real household
validation. Explicit accept/reject requests simulate operator button presses;
they never provide detector output. Inputs and output directory remain private.
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

from hometrace.household_service import HouseholdService


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--images', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    output, inputs = args.output_dir.resolve(), args.images.resolve()
    if output.exists():
        parser.error('Use a new output directory; existing evidence is never overwritten')
    manifest = json.loads((inputs/'manifest.json').read_text(encoding='utf-8'))
    if manifest.get('not_real_household_data') is not True:
        parser.error('This demonstration script only accepts the explicitly synthetic pack')
    for row in manifest['files']:
        file = (inputs/row['file']).resolve()
        if not file.is_relative_to(inputs) or hashlib.sha256(file.read_bytes()).hexdigest() != row['sha256']:
            parser.error('Input path or hash does not match the synthetic manifest')
    output.mkdir(parents=True)
    HouseholdService(output/'home-accept')
    process, log, base = None, None, None
    requests, summary = [], {'data_source':'synthetic_image', 'physical_robot':False, 'training_steps':0,
                             'independent_real_test':False, 'input_files':manifest['files']}

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
        path = output/f'server-{index}.log'
        log = path.open('wb')
        process = subprocess.Popen([sys.executable, '-X', 'utf8', '-m', 'hometrace', 'demo', '--port', '0',
                                    '--household-dir', str(output/home), '--output-dir', str(output/'classic')],
                                   stdout=log, stderr=subprocess.STDOUT)
        for _ in range(200):
            match = re.search(r'HomeTrace demo: (http://127\.0\.0\.1:\d+)', path.read_text(encoding='utf-8'))
            if match:
                base = match.group(1); return
            if process.poll() is not None:
                raise RuntimeError('Server failed; inspect local log')
            time.sleep(.1)
        raise RuntimeError('Server startup timed out')

    def call(path, value=None, expected=200):
        body = None if value is None else json.dumps(value, ensure_ascii=False).encode('utf-8')
        req = Request(base+path, data=body, headers={'Content-Type':'application/json','Origin':base})
        try:
            with urlopen(req, timeout=30) as response:
                status, raw = response.status, response.read()
        except HTTPError as exc:
            status, raw = exc.code, exc.read()
        result = json.loads(raw)
        # Uploaded image bytes never enter the execution log.
        redacted = {k:v for k,v in value.items() if k != 'data_base64'} if value else value
        requests.append({'path':path,'input':redacted,'status':status,'output':result})
        assert status == expected, (path, status, result)
        return result

    def act(run, action, **kwargs):
        return call('/api/home-flow/act', {'run_id':run['run_id'],'version':run['version'],'action':action,**kwargs})

    def wait(run):
        for _ in range(100):
            run = call('/api/home-flow/runs/'+run['run_id'])
            if run['state'] != 'RUNNING':
                return run
            time.sleep(.1)
        raise RuntimeError('Search timed out')

    def seed():
        call('/api/household/enroll', {'object_id':'blue-keys','name':'蓝色钥匙','aliases':['钥匙']})
        assets = {}
        for row in manifest['files']:
            assets[row['file']] = call('/api/home-flow/assets', {
                'data_base64':base64.b64encode((inputs/row['file']).read_bytes()).decode('ascii'), 'source_kind':'synthetic'})
        # Fixed registration ROI reviewed on the synthetic reference. It is not
        # a scene ground truth and is never changed between scene observations.
        call('/api/home-flow/reference', {'object_id':'blue-keys','asset_id':assets['01_reference_keys.png']['asset_id'],
                                          'roi':[110,120,1390,950],'roi_reviewed':True})
        for loc, name in [('entry-tray','05_empty_entry_tray.png'), ('study-desk','03_keys_study_desk.png'),
                          ('living-table','04_rival_red_keys.png')]:
            call('/api/home-flow/scene', {'location_id':loc,'asset_id':assets[name]['asset_id']})
        # Two explicit fictional owner statements: older study, latest entry.
        # This tests long-term fallback without reading the scene answers.
        for place in ('study-desk', 'entry-tray'):
            memory = call('/api/home-flow/start', {'message':'记住蓝色钥匙放在这里','current_location_id':place})
            assert memory['state'] == 'CONFIRM_MEMORY'
            remembered = act(memory, 'confirm_memory')
            assert remembered['state'] == 'COMPLETED'
        assert len(remembered['history']) == 2
        return assets

    try:
        start(1, 'home-accept')
        assets = seed()
        run = wait(call('/api/home-flow/start', {'message':'我找不到蓝色钥匙了，帮我找一下'}))
        summary['initial_search'] = run
        assert run['state'] == 'AWAITING_REVIEW', run['state']
        assert run['visited'] == ['entry-tray','study-desk']
        assert run['candidate']['bbox'] and run['visual_confirmed'] is False
        stop(); start(2, 'home-accept')
        restored = call('/api/home-flow/runs/'+run['run_id'])
        assert restored == run
        saved = act(restored, 'accept_candidate')
        assert saved['state'] == 'USER_CONFIRMED' and len(saved['history']) == 3
        assert saved['owner_event']['visual_confirmed'] is False
        call('/api/home-flow/act', {'run_id':run['run_id'],'version':run['version'],'action':'accept_candidate'}, expected=409)
        summary['accepted_after_process_restart'] = saved
        replay = wait(call('/api/home-flow/start', {'message':'帮我找蓝色钥匙'}))
        assert replay['state'] == 'UNKNOWN'
        assert replay['planned_locations'][0]['location_id'] == 'study-desk'
        assert any(x['reason']=='replayed_image_content' for x in replay['observations'])
        summary['replay_and_history_reorder'] = replay
        stop(); start(3, 'home-reject')
        seed()
        run = wait(call('/api/home-flow/start', {'message':'帮我找蓝色钥匙'}))
        assert run['state'] == 'AWAITING_REVIEW'
        rejected = wait(act(run, 'reject_candidate'))
        assert rejected['state'] == 'UNKNOWN' and rejected['visited'] == ['entry-tray','study-desk','living-table']
        assert len(rejected['history']) == 2
        summary['rejected_then_replanned'] = rejected
        summary['checks_passed'] = True
        summary['browser_test'] = 'not executed by this HTTP script'
    finally:
        stop()
        (output/'requests.json').write_text(json.dumps(requests, ensure_ascii=False, indent=2), encoding='utf-8')
        (output/'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'checks_passed':True,'processes':3,'requests':len(requests),
                      'visual_found':False,'data_source':'synthetic_image'}, ensure_ascii=False))


if __name__ == '__main__':
    main()
