"""Exercise two real CLI server processes; synthetic statements, no browser/vision.

Use a NEW ignored output directory. All requests use the production HTTP routes.
No private input, API key or language model is used. Does not assert browser QA.
"""
import argparse
from datetime import datetime, timezone
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
    parser.add_argument('--output-dir', required=True, type=Path)
    parser.add_argument('--samples-dir', type=Path, default=Path('examples/recorded_images'))
    args = parser.parse_args()
    output = args.output_dir.resolve()
    if output.exists():
        parser.error('Output directory already exists; use a new directory')
    output.mkdir(parents=True)
    HouseholdService(output / 'home')  # Enforce the ignored-workspace boundary.
    results = []
    logs = []
    process = None
    stream = None
    base = None

    def start(index):
        nonlocal process, stream, base
        log = output / f'server-{index}.log'
        logs.append(log.name)
        stream = log.open('wb')
        process = subprocess.Popen([sys.executable, '-X', 'utf8', '-m', 'hometrace', 'demo',
            '--port', '0', '--samples-dir', str(args.samples_dir.resolve()),
            '--output-dir', str(output / 'photos'), '--household-dir', str(output / 'home')],
            stdout=stream, stderr=subprocess.STDOUT)
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            text = log.read_text(encoding='utf-8')
            match = re.search(r'HomeTrace demo: (http://127\.0\.0\.1:\d+)', text)
            if match:
                base = match.group(1)
                return
            if process.poll() is not None:
                raise RuntimeError('Server exited; inspect the local log')
            time.sleep(.1)
        raise RuntimeError('Server did not become ready')

    def stop():
        nonlocal process, stream
        if process is not None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            process = None
        if stream is not None:
            stream.close()
            stream = None

    def call(path, payload=None, expected=200):
        body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode('utf-8')
        req = Request(base+path, data=body, headers={'Content-Type': 'application/json', 'Origin': base})
        try:
            with urlopen(req, timeout=10) as response:
                status, raw = response.status, response.read()
        except HTTPError as error:
            status, raw = error.code, error.read()
        assert status == expected, (path, status, expected)
        result = json.loads(raw)
        results.append({'path': path, 'input': payload, 'http_status': status, 'output': result})
        return result

    def act(session, action, **fields):
        return call('/api/household/act', {'session_id': session['session_id'],
                    'version': session['version'], 'action': action, **fields})

    try:
        start(1)
        for oid, name in [('blue-keys', '蓝色钥匙'), ('red-keys', '红色钥匙')]:
            call('/api/household/enroll', {'object_id': oid, 'name': name, 'aliases': ['我的钥匙']})
        pending = call('/api/household/start', {'intent': 'remember', 'query': '我的钥匙',
                       'location_id': 'entry-tray', 'reported_at': '2026-10-27T10:00:00+08:00'})
        assert pending['state'] == 'CLARIFY'
        pending = act(pending, 'select', object_id='blue-keys')
        assert pending['state'] == 'CONFIRM'
        assert call('/api/household/start', {'intent': 'recall', 'query': 'blue-keys'})['history'] == []
        first_pid = process.pid
        stop()
        start(2)
        assert process.pid != first_pid
        assert call('/api/household/sessions/'+pending['session_id']) == pending
        saved = act(pending, 'confirm')
        assert len(saved['history']) == 1 and saved['visual_confirmed'] is False
        call('/api/household/act', {'session_id': pending['session_id'], 'version': pending['version'],
                                  'action': 'confirm'}, expected=409)
        assert act(saved, 'confirm') == saved
        moved = call('/api/household/start', {'intent': 'remember', 'query': 'blue-keys',
                     'location_id': 'study-desk', 'reported_at': '2026-10-27T11:00:00+08:00'})
        act(moved, 'confirm')
        cancelled = call('/api/household/start', {'intent': 'remember', 'query': 'blue-keys',
                         'location_id': 'living-table'})
        assert act(cancelled, 'cancel')['state'] == 'CANCELLED'
        unknown = call('/api/household/start', {'intent': 'remember', 'query': '我的水杯',
                       'location_id': 'living-table'})
        assert unknown['state'] == 'UNKNOWN_OBJECT'
        call('/api/household/enroll', {'object_id': 'demo-cup', 'name': '我的水杯', 'aliases': []})
        retried = act(unknown, 'retry')
        assert retried['state'] == 'CONFIRM'
        act(retried, 'cancel')
        assert call('/api/household/start', {'intent': 'recall', 'query': 'demo-cup'})['history'] == []
        final = call('/api/household/start', {'intent': 'recall', 'query': 'blue-keys'})
        assert [x['location_id'] for x in final['candidates']] == ['study-desk', 'entry-tray']
        assert len(final['history']) == 2
        assert all(x['source_kind'] == 'owner_reported' and not x['visual_confirmed'] for x in final['history'])
        assert call('/api/household/start', {'intent': 'recall', 'query': 'red-keys'})['history'] == []
        assets = {}
        for name in ['household.html', 'household.js', 'household.css']:
            with urlopen(base+'/'+name, timeout=10) as response:
                content = response.read()
                assert response.status == 200 and len(content) > 100
                assets[name] = {'bytes': len(content), 'sha256': hashlib.sha256(content).hexdigest()}
        summary = {'status': 'PASS', 'evidence_kind': 'actual_http_processes_with_software_fixture_statements',
                   'timestamp': datetime.now(timezone.utc).isoformat(), 'server_processes': 2,
                   'api_requests': len(results), 'visual_confirmed': False, 'browser_ui_executed': False,
                   'persisted_blue_key_events': 2, 'cancelled_cup_events': 0,
                   'candidate_order': [x['location_id'] for x in final['candidates']],
                   'assets': assets, 'local_logs': logs}
        (output/'requests.json').write_text(json.dumps(results, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        (output/'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    finally:
        stop()


if __name__ == '__main__':
    main()
