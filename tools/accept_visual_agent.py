"""One opt-in real-API visual Agent acceptance from a fresh private workspace.

Only the hash-locked synthetic keys pack is allowed. Operator actions use HTTP,
not a browser, and are scripted software-test actions, not human identity labels.
The real configured LLM must choose every tool; no tool trace is manufactured.
Run explicitly: python tools/accept_visual_agent.py --output-dir artifacts/issue-34/live-01
"""
import argparse
import base64
import hashlib
import importlib.metadata
import json
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen


EXPECTED = {
    '01_reference_keys.png': '3cc149287c013dd6b9ff8f4ff9f54a4d32d9dfeb5b4200612ec2ea0d40e94fe8',
    '03_keys_study_desk.png': 'ac06b717b7171daa0b4b26c6adcbb1556938717929b7a68d53ba785494239502',
    '04_rival_red_keys.png': '5646c45ed7f793136e85ce9183a96d6ef9055af428d47a35ce4215fa447d3b50',
    '05_empty_entry_tray.png': '0b66fbf63b2255ecd3d2535974e0a730403e88c35c9038a67663006a879ae307',
}
REFERENCE_ROI = [110, 120, 1390, 950]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--images', type=Path, default=Path('local_data/ai_html_test_20261027'))
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--case', choices=('positive', 'rival'), default='positive')
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    images, output = args.images.resolve(), args.output_dir.resolve()
    if output.exists():
        parser.error('Output must be new; frozen evidence is never overwritten')
    try:
        relative = output.relative_to(repo)
    except ValueError:
        parser.error('Output must be inside this repository and Git ignored')
    ignored = subprocess.run(['git', 'check-ignore', '--quiet', str(relative / 'acceptance-probe.json')],
                             cwd=repo, check=False, capture_output=True)
    if ignored.returncode != 0:
        parser.error('Output must be Git ignored before execution')
    manifest = json.loads((images / 'manifest.json').read_text(encoding='utf-8'))
    if manifest.get('not_real_household_data') is not True:
        parser.error('Only the explicitly synthetic pack is authorized for this script')
    for name, digest in EXPECTED.items():
        if hashlib.sha256((images / name).read_bytes()).hexdigest() != digest:
            parser.error(f'Synthetic input hash mismatch: {name}')

    output.mkdir(parents=True)
    source_files = [*sorted((repo / 'src/hometrace').glob('*.py')), Path(__file__).resolve()]
    execution = {'base_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=repo, text=True).strip(),
                 'working_tree_dirty': bool(subprocess.check_output(['git', 'status', '--porcelain'], cwd=repo)),
                 'source_sha256': {str(p.relative_to(repo)).replace('\\', '/'): hashlib.sha256(p.read_bytes()).hexdigest()
                                  for p in source_files},
                 'versions': {name: importlib.metadata.version(name) for name in
                              ('hometrace', 'openai', 'Pillow', 'langgraph', 'langchain-core', 'langchain-openai')}}
    (output / 'execution.json').write_text(json.dumps(execution, indent=2) + '\n', encoding='utf-8')
    process = logfile = base = None
    deadline = time.monotonic() + 300
    summary = {
        'case': args.case,
        'source': 'synthetic', 'transport': 'scripted HTTP, not browser',
        'navigation': 'simulated', 'real_household_validation': False,
        'requested_real_llm': True, 'requested_real_advisor': True,
        'scripted_owner_actions': True, 'input_sha256': EXPECTED,
        'reference_roi': REFERENCE_ROI, 'checks_passed': False,
        'limits': {'total_seconds': 300, 'find_runs': 1,
                   'advisor_calls': 3 if args.case == 'positive' else 1,
                   'new_photos': 1 if args.case == 'positive' else 0,
                   'explicit_protocol_retries': 1},
        'runs': {}, 'checks': [], 'http': [], 'consents': [],
        'limitations': [
            'This is software integration acceptance with synthetic inputs, not physical instance recognition.',
            'A blurred full frame followed by its sharp source is a software fixture, not a new camera capture.',
            'The user scenario explicitly requests another photo; this does not prove spontaneous recovery planning.',
            'Owner approval is scripted; model advice and owner memory never become automatic FOUND.',
            'At most one explicit operator retry is allowed for a rejected tool protocol; its failure remains in the trace.',
        ],
    }
    if args.case == 'rival':
        summary['limitations'] = [
            'This is software integration acceptance with synthetic inputs, not physical instance recognition.',
            'The scenario requests one full-frame comparison; its outcome is produced by the actual advisor.',
            'No new photo or owner identity confirmation is permitted in this negative-case run.',
            'At most one explicit operator retry is allowed for a rejected tool protocol; its failure remains in the trace.',
        ]

    def save():
        (output / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    def check(name, condition):
        summary['checks'].append({'name': name, 'passed': bool(condition)})
        save()
        if not condition:
            raise AssertionError(name)

    def remaining():
        seconds = deadline - time.monotonic()
        if seconds <= 0:
            raise TimeoutError('Overall 300-second acceptance deadline')
        return seconds

    def call(path, value=None):
        clean_input = {key: item for key, item in value.items() if key != 'data_base64'} if value is not None else None
        request = Request(base + path,
                          data=json.dumps(value, ensure_ascii=False).encode() if value is not None else None,
                          headers={'Content-Type': 'application/json', 'Origin': base})
        try:
            with urlopen(request, timeout=min(30, remaining())) as response:
                result = json.load(response)
        except HTTPError as error:
            summary['http'].append({'path': path, 'input': clean_input, 'status': error.code})
            save()
            raise
        # Keep each distinct poll version, rather than hundreds of duplicate runs.
        record = {'path': path, 'input': clean_input, 'output': result}
        if not summary['http'] or summary['http'][-1] != record:
            summary['http'].append(record)
            save()
        return result

    def stop():
        nonlocal process, logfile
        if process:
            process.terminate()
            try:
                process.wait(5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(5)
            process = None
        if logfile:
            logfile.close()
            logfile = None

    def start(index, *, fresh=False):
        nonlocal process, logfile, base
        stop()
        workspace = output / 'workspace'
        if fresh:
            check('workspace absent before first boot', not workspace.exists())
        path = output / f'server-{index}.log'
        logfile = path.open('xb')
        process = subprocess.Popen(
            [sys.executable, '-X', 'utf8', '-m', 'hometrace', 'demo', '--photo-vision-agent', '--port', '0',
             '--household-dir', str(workspace), '--output-dir', str(output / 'classic')],
            cwd=repo, stdout=logfile, stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        while remaining():
            match = re.search(r'HomeTrace demo: (http://127\.0\.0\.1:\d+)', path.read_text(encoding='utf-8'))
            if match:
                base = match.group(1)
                config = call('/api/home-flow/config')
                check(f'boot {index}: real visual Agent available', config['mode'] == 'llm_langgraph'
                      and config['model_available'] and config.get('visual_advisor_enabled') is True)
                if fresh:
                    with sqlite3.connect((workspace / 'photo-flow.sqlite3').as_uri() + '?mode=ro', uri=True) as db:
                        count = db.execute('SELECT count(*) FROM evidence').fetchone()[0]
                    check('empty initial catalog, scenes and evidence', not config['catalog'] and not config['scenes'] and count == 0)
                return
            if process.poll() is not None:
                raise RuntimeError('Server startup failed; inspect retained private server log')
            time.sleep(min(.1, remaining()))

    def wait(name, run):
        while run['state'] == 'RUNNING':
            time.sleep(min(.4, remaining()))
            run = call('/api/home-flow/runs/' + run['run_id'])
        summary['runs'][name] = run
        save()
        print(json.dumps({'stage': name, 'state': run['state'], 'model_calls': run.get('model_calls'),
                          'vision_calls': run.get('vision_calls'), 'observations': len(run.get('observations', []))},
                         ensure_ascii=False), flush=True)
        check(name + ': actual model executed', run.get('model_calls', 0) > 0)
        return run

    def action(name, run, choice, **extra):
        return wait(name, call('/api/home-flow/act', {'run_id': run['run_id'], 'version': run['version'],
                                                    'action': choice, **extra}))

    def upload(path):
        return call('/api/home-flow/assets', {'data_base64': base64.b64encode(path.read_bytes()).decode(),
                                             'source_kind': 'synthetic'})

    try:
        degraded_hash = None
        if args.case == 'positive':
            # Full-frame deterministic degradation. No boxes or target coordinates are read.
            from PIL import Image, ImageFilter
            degraded = output / 'software-fixture-blurred-full-frame.png'
            with Image.open(images / '03_keys_study_desk.png') as picture:
                size = picture.size
                low = picture.convert('RGB')
                low.thumbnail((160, 160), Image.Resampling.BILINEAR)
                low.resize(size, Image.Resampling.BILINEAR).filter(ImageFilter.GaussianBlur(3)).save(degraded)
            degraded_hash = hashlib.sha256(degraded.read_bytes()).hexdigest()
            summary['software_fixture'] = {'name': degraded.name, 'sha256': degraded_hash,
                                           'source_sha256': EXPECTED['03_keys_study_desk.png'],
                                           'method': 'full frame RGB -> thumbnail max 160 -> original dimensions bilinear -> Gaussian radius 3',
                                           'target_crop': False, 'new_camera_capture': False}
        save()
        start(1, fresh=True)
        call('/api/household/enroll', {'object_id': 'blue-keys', 'name': '蓝色钥匙', 'aliases': ['蓝挂件钥匙']})
        assets = {name: upload(images / name) for name in EXPECTED}
        first_scene = upload(degraded) if args.case == 'positive' else assets['04_rival_red_keys.png']
        call('/api/home-flow/reference', {'object_id': 'blue-keys',
                                         'asset_id': assets['01_reference_keys.png']['asset_id'],
                                         'roi': REFERENCE_ROI, 'roi_reviewed': True})
        memory = wait('remember', call('/api/home-flow/start', {'message': '请记住，蓝色钥匙我放在书桌这里了。',
                                                                'current_location_id': 'study-desk'}))
        check('empty history requires owner confirmation', memory['state'] == 'CONFIRM_MEMORY' and not memory['history'])
        saved = action('remember-confirmed', memory, 'confirm_memory')
        check('one owner-reported memory saved', saved['state'] == 'COMPLETED'
              and len(saved['history']) == 1 and not saved['visual_confirmed'])
        for location, asset in [('study-desk', first_scene), ('entry-tray', assets['05_empty_entry_tray.png']),
                                ('living-table', assets['04_rival_red_keys.png'])]:
            call('/api/home-flow/scene', {'location_id': location, 'asset_id': asset['asset_id']})
        prompt = ('请寻找蓝色钥匙，先按最近记忆检查书桌。请调用视觉顾问比较第一张照片；'
                  '无论首张比较结果如何，都请我补充一张书桌的新照片，然后再次观察并调用视觉顾问比较。'
                  '两张照片都比较完成后，只有最新证据支持外观相似时才请我核对，否则如实说明未确认。')
        if args.case == 'rival':
            prompt = ('请寻找蓝色钥匙，本轮只检查书桌：先调用本地观察工具，再请求视觉顾问比较参考图与当前整张照片。'
                      '本轮最多进行一次视觉比较，不补拍，也不检查其他地点。'
                      '请根据实际视觉结果判断；如果外观不同或没有看到目标，请结束搜索并保留 UNKNOWN，'
                      '不要请求主人确认或更新记忆。证据不足也应如实结束，不能声称找到了目标。')
        run = wait('find-initial', call('/api/home-flow/start', {'message': prompt}))
        approved = set()
        new_photo_sent = False
        protocol_retry = False
        while True:
            remaining()
            check('advisor call limit preserved', run['vision_calls'] <= summary['limits']['advisor_calls'])
            if run['state'] == 'AWAITING_IMAGE_CONSENT':
                request = run['vision_request']
                allowed_scenes = ((degraded_hash, EXPECTED['03_keys_study_desk.png'])
                                  if args.case == 'positive' else (EXPECTED['04_rival_red_keys.png'],))
                check('consent bound to authorized synthetic inputs',
                      request['reference_sha256'] == EXPECTED['01_reference_keys.png']
                      and request['scene_sha256'] in allowed_scenes
                      and request['reference']['source_kind'] == request['scene']['source_kind'] == 'synthetic')
                check('fresh consent request and call budget', request['request_id'] not in approved
                      and len(approved) < summary['limits']['advisor_calls'])
                approved.add(request['request_id'])
                summary['consents'].append({'request_id': request['request_id'],
                                            'scene_sha256': request['scene_sha256'],
                                            'reference_sha256': request['reference_sha256'],
                                            'operator': 'scripted synthetic-fixture approval',
                                            'scene_derivative_sha256': request['scene_derivative_sha256'],
                                            'reference_derivative_sha256': request['reference_derivative_sha256']})
                run = action(f'after-consent-{len(approved)}', run, 'approve_vision', request_id=request['request_id'])
            elif run['state'] == 'AWAITING_NEW_PHOTO':
                check('new photo permitted only for positive case', args.case == 'positive')
                check('LLM requested one follow-up at same location', not new_photo_sent
                      and run['photo_request']['location_id'] == 'study-desk'
                      and any(item['execution_status'] == 'completed' for item in run['visual_advice']))
                new_photo_sent = True
                run = wait('new-photo-observed', call('/api/home-flow/new-photo', {
                    'run_id': run['run_id'], 'version': run['version'],
                    'asset_id': assets['03_keys_study_desk.png']['asset_id']}))
            elif (run['state'] == 'ERROR' and not protocol_retry
                  and run['trace'][-1]['result'].get('code') == 'EXACTLY_ONE_TOOL_REQUIRED'):
                protocol_retry = True
                summary['explicit_protocol_retry'] = {'operator': 'scripted operator retry',
                                                      'failed_run_preserved': run}
                run = action('after-explicit-protocol-retry', run, 'retry')
            else:
                break

        if args.case == 'rival':
            advice = run['visual_advice']
            observations = run['observations']
            tools = [row['input']['name'] for row in run['trace'] if row['tool'] == 'llm_tool']
            check('one actual rival comparison completed', len(advice) == 1
                  and advice[0]['execution_status'] == 'completed'
                  and run['vision_calls'] == 1 and len(approved) == 1)
            check('actual advisor rejected rival appearance',
                  advice[0]['advice']['model_advice']['appearance'] in ('different', 'not_visible'))
            check('negative search ends UNKNOWN without candidate or confirmation',
                  run['state'] == 'UNKNOWN' and run['candidate'] is None and not run['visual_confirmed']
                  and len(run['history']) == 1 and run['new_photo_count'] == 0)
            check('only rival full frame was observed and consented', len(observations) == 1
                  and observations[0]['location_id'] == 'study-desk'
                  and observations[0]['image_sha256'] == EXPECTED['04_rival_red_keys.png']
                  and {row['scene_sha256'] for row in summary['consents']}
                  == {EXPECTED['04_rival_red_keys.png']})
            check('negative tool trace contains real observation comparison and finish',
                  sum(row['tool'] == 'observe_uploaded_image' for row in run['trace']) == 1
                  and tools.count('visual_advice') == 1
                  and 'finish_search' in tools and 'request_new_photo' not in tools
                  and 'request_owner_review' not in tools)
            check('negative Core and advisor never auto-confirm identity',
                  bool(run['core_reports'])
                  and all(report['result_status'] in ('UNKNOWN', 'SUSPECTED') for report in run['core_reports'])
                  and all(not row['identity_confirmed'] for row in observations)
                  and advice[0]['advice']['production_status'] == 'UNKNOWN'
                  and advice[0]['advice']['identity_confirmed'] is False
                  and 'bbox' not in advice[0]['advice'])
            check('negative actual model and advisor usage recorded', run['total_tokens'] > 0
                  and run['vision_actual_tokens'] > 0
                  and advice[0]['request_id'] in approved)
            start(2)
            restored = call('/api/home-flow/runs/' + run['run_id'])
            check('restart preserves complete negative result and trace', restored == run)
            history = wait('history-after-restart', call('/api/home-flow/start', {'message': '蓝色钥匙最近记在哪里？'}))
            check('negative run left original owner history unchanged', history['state'] == 'COMPLETED'
                  and len(history['history']) == 1 and history['history'][0]['location_id'] == 'study-desk')
            summary['checks_passed'] = True
            return

        check('LLM reached owner review after both actual image comparisons', run['state'] == 'AWAITING_REVIEW'
              and new_photo_sent and len(run['visual_advice']) >= 2
              and all(item['execution_status'] == 'completed' for item in run['visual_advice']))
        observations = [row for row in run['observations'] if row['location_id'] == 'study-desk']
        check('same place has two preserved and different image hashes', len(observations) == 2
              and [row['image_sha256'] for row in observations] == [degraded_hash, EXPECTED['03_keys_study_desk.png']])
        evidence_ids = [event['result']['observation']['evidence_id']
                        for report in run['core_reports'] for event in report['events']
                        if event['action'] == 'observe' and event['result'].get('observation', {}).get('viewpoint_id') == 'study-desk']
        check('same-place reobservation has unique Core evidence IDs', len(evidence_ids) == 2 and len(set(evidence_ids)) == 2)
        check('each returned advice has its own approved request', len({row['request_id'] for row in run['visual_advice']}) == len(approved)
              and {row['request_id'] for row in run['visual_advice']} == approved)
        check('both images were individually consented', {row['scene_sha256'] for row in summary['consents']}
              == {degraded_hash, EXPECTED['03_keys_study_desk.png']})
        tools = [row['input']['name'] for row in run['trace'] if row['tool'] == 'llm_tool']
        check('actual LLM tool trace includes feedback decisions', tools.count('visual_advice') >= 2
              and 'request_new_photo' in tools and 'request_owner_review' in tools)
        check('Core never auto-confirms identity', not run['visual_confirmed']
              and all(report['result_status'] in ('UNKNOWN', 'SUSPECTED') for report in run['core_reports'])
              and all(not row['identity_confirmed'] for row in observations))
        check('advisor never invents bbox or FOUND', all(row['advice']['production_status'] == 'UNKNOWN'
              and row['advice']['identity_confirmed'] is False and 'bbox' not in row['advice'] for row in run['visual_advice'])
              and (run['candidate']['kind'] != 'visual_advisor' or run['candidate']['bbox'] is None))
        check('actual model and advisor usage recorded', run['total_tokens'] > 0
              and run['vision_actual_tokens'] > 0 and run['vision_calls'] == len(approved))
        summary['evidence_ids'] = evidence_ids
        start(2)
        restored = call('/api/home-flow/runs/' + run['run_id'])
        check('restart retains complete pending review and tool trace', restored == run)
        accepted = action('scripted-owner-confirmed', restored, 'accept_candidate')
        check('scripted owner confirmation only writes reported memory', accepted['state'] == 'USER_CONFIRMED'
              and len(accepted['history']) == 2 and not accepted['visual_confirmed'])
        start(3)
        persisted = call('/api/home-flow/runs/' + accepted['run_id'])
        check('restart preserves owner-confirmed record', persisted == accepted)
        history = wait('history-after-restart', call('/api/home-flow/start', {'message': '蓝色钥匙最近记在哪里？'}))
        check('fresh LLM query reads persisted history', history['state'] == 'COMPLETED'
              and len(history['history']) == 2 and history['history'][0]['location_id'] == 'study-desk')
        summary['checks_passed'] = True
    except Exception as exc:
        summary['failure_type'] = type(exc).__name__
        # Do not echo arbitrary provider exception bodies or configured credentials.
        print('Acceptance failed; all completed HTTP stages and server logs retained.', flush=True)
        raise
    finally:
        stop()
        save()


if __name__ == '__main__':
    main()
