"""Real text-LLM / HTTP / process-restart acceptance using software fixtures only.

No private photographs, image consent, search, provider retry, or automatic FOUND.
Run explicitly with --output-dir artifacts/issue-40/memory-restart-NEW.
The selected tools come from the configured real model, never a canned response.
"""
import argparse
import base64
from contextlib import closing
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
from urllib.error import HTTPError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
OBJECT_ID = 'memory-fixture'
TIMEOUT = 45
MAX_PHASES = 3
MAX_CALLS_PER_PHASE = 2


def new_output(path, repo=ROOT):
    original = Path(path).absolute()
    if original.is_symlink():
        raise ValueError('Output must not be a symbolic link')
    output = original.resolve()
    if output.exists():
        raise ValueError('Output must be new; previous evidence will not be overwritten')
    try:
        relative = output.relative_to(repo.resolve())
    except ValueError:
        raise ValueError('Output must be inside this repository') from None
    ignored = subprocess.run(['git', 'check-ignore', '--quiet', str(relative / 'summary.json')],
                             cwd=repo, capture_output=True, check=False)
    if ignored.returncode:
        raise ValueError('Output must be Git ignored before execution')
    output.mkdir(parents=True, exist_ok=False)
    return output


def bounded_config(output, config_path=None):
    """Validate configured provider; serialize only the whitelisted non-secret fields."""
    from hometrace.agent_config import load_agent_config
    import yaml
    config = load_agent_config(config_path)
    document = {
        'llm': {**asdict(config.llm), 'timeout_seconds': TIMEOUT, 'max_retries': 0},
        'agent': {**asdict(config.agent), 'max_model_calls': MAX_CALLS_PER_PHASE},
        'vision': {'backend': 'orb'},
        'privacy': {'send_raw_images_to_llm': False, 'external_tracing_enabled': False},
    }
    path = output / 'bounded-config.private.yaml'
    with path.open('x', encoding='utf-8') as file:
        yaml.safe_dump(document, file, sort_keys=False)
    return path, document


def fixture_png(path):
    """Fixed checker/line pattern: software pixels, not a generated household photo."""
    from PIL import Image, ImageDraw
    picture = Image.new('RGB', (256, 256), '#f0f0f0')
    draw = ImageDraw.Draw(picture)
    for y in range(16, 240, 16):
        for x in range(16, 240, 16):
            color = ((x * 13 + y * 3) % 256, (x * 7 + y * 11) % 256, (x + y * 17) % 256)
            draw.rectangle((x, y, x + 10, y + 10), fill=color)
    draw.line((25, 30, 220, 205), fill='black', width=3)
    with path.open('xb') as file:
        picture.save(file, format='PNG')
    return path


class Acceptance:
    def __init__(self, output, config_path, repo=ROOT):
        self.output, self.config_path, self.repo = output, config_path, repo
        self.workspace = output / 'workspace'
        self.process = self.logfile = self.base = None
        self.deadline = time.monotonic() + 360
        self.summary = {
            'checks_passed': False, 'source': 'deterministic_software_fixture',
            'transport': 'actual localhost HTTP; actual child-process restart',
            'real_household_validation': False, 'requested_real_text_llm': True,
            'scripted_owner_actions': True, 'image_consent_grants': 0,
            'limits': {'text_phases': MAX_PHASES, 'model_calls_per_phase': MAX_CALLS_PER_PHASE,
                       'total_model_calls': MAX_PHASES * MAX_CALLS_PER_PHASE,
                       'provider_retries': 0, 'model_timeout_seconds': TIMEOUT,
                       'overall_seconds': 360},
            'runs': {}, 'http': [], 'checks': [], 'processes': [], 'database_snapshots': [],
            'limitations': [
                'Scripted software owner confirmation is not a real person identity or location review.',
                'Only owner-reported historical memory is tested, not visual recognition or current position.',
                'No scene is registered, no search is requested, and no image consent is granted.',
                'A failed real model response ends acceptance without a retry or fixture substitution.',
            ],
        }

    def save(self):
        (self.output / 'summary.json').write_text(json.dumps(self.summary, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    def check(self, name, condition):
        self.summary['checks'].append({'name': name, 'passed': bool(condition)})
        self.save()
        if not condition:
            raise AssertionError(name)

    def remaining(self):
        seconds = self.deadline - time.monotonic()
        if seconds <= 0:
            raise TimeoutError('Acceptance deadline exceeded')
        return seconds

    def call(self, path, value=None, expected=200):
        # No arbitrary API actions may add a hidden photo grant or execute a search.
        if path == '/api/home-flow/act' and value.get('action') != 'confirm_memory':
            raise ValueError('Only scripted fixture memory confirmation is permitted')
        if path in ('/api/home-flow/scene', '/api/home-flow/new-photo'):
            raise ValueError('Search images are outside this memory-only acceptance')
        if path == '/api/home-flow/start':
            self.summary['text_phases_started'] = self.summary.get('text_phases_started', 0) + 1
            self.check('three text phases maximum', self.summary['text_phases_started'] <= MAX_PHASES)
        request = Request(self.base + path,
                          data=json.dumps(value, ensure_ascii=False).encode() if value is not None else None,
                          headers={'Content-Type': 'application/json', 'Origin': self.base})
        status = None
        try:
            with urlopen(request, timeout=min(10, self.remaining())) as response:
                status, result = response.status, json.load(response)
        except HTTPError as exc:
            status, result = exc.code, json.load(exc)
        record = {'path': path, 'input': ({k: v for k, v in value.items() if k != 'data_base64'}
                                        if value is not None else None),
                  'status': status, 'output': result}
        if not self.summary['http'] or self.summary['http'][-1] != record:
            self.summary['http'].append(record)
            self.save()
        self.check('HTTP status matches expected', status == expected)
        return result

    def stop(self):
        if self.process is not None:
            process = self.process
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            self.summary['processes'][-1]['exit_code'] = process.returncode
            self.summary['processes'][-1]['stopped'] = True
            self.process = None
        if self.logfile is not None:
            self.logfile.close()
            self.logfile = None

    def start(self, index):
        self.stop()
        log = self.output / f'server-{index}.log'
        self.logfile = log.open('xb')
        self.process = subprocess.Popen(
            [sys.executable, '-X', 'utf8', '-m', 'hometrace', 'demo', '--photo-vision-agent',
             '--port', '0', '--household-dir', str(self.workspace),
             '--output-dir', str(self.output / 'unused-classic'), '--config', str(self.config_path)],
            cwd=self.repo, stdout=self.logfile, stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        self.summary['processes'].append({'boot': index, 'pid': self.process.pid, 'stopped': False})
        self.save()
        while self.remaining():
            match = re.search(r'HomeTrace demo: (http://127\.0\.0\.1:\d+)', log.read_text(encoding='utf-8'))
            if match:
                self.base = match.group(1)
                self.summary['processes'][-1]['base_url'] = self.base
                config = self.call('/api/home-flow/config')
                self.check('real visual Agent available', config.get('mode') == 'llm_langgraph'
                           and config.get('model_available') is True and config.get('visual_advisor_enabled') is True)
                self.check('no scenes or automatic FOUND', not config['scenes'] and config['automatic_found_enabled'] is False)
                return
            if self.process.poll() is not None:
                raise RuntimeError('Server exited before startup; see retained private log')
            time.sleep(min(.1, self.remaining()))

    def events(self, label):
        with closing(sqlite3.connect((self.workspace / 'owner-memory.sqlite3').as_uri() + '?mode=ro', uri=True)) as db:
            db.row_factory = sqlite3.Row
            events = [dict(row) for row in db.execute('SELECT * FROM hm_owner_events ORDER BY recorded_at,event_id')]
        with closing(sqlite3.connect((self.workspace / 'photo-flow.sqlite3').as_uri() + '?mode=ro', uri=True)) as db:
            evidence = db.execute('SELECT count(*) FROM evidence').fetchone()[0]
        self.summary['database_snapshots'].append({'stage': label, 'events': events, 'evidence_count': evidence,
                                                  'inspection_mode': 'read_only_sqlite'})
        self.check('no visual evidence generated', evidence == 0)
        return events

    def wait(self, label, run):
        while run['state'] == 'RUNNING':
            time.sleep(min(.15, self.remaining()))
            run = self.call('/api/home-flow/runs/' + run['run_id'])
        self.summary['runs'][label] = run
        self.save()
        self.check('actual bounded model invocation', 0 < run.get('model_calls', 0) <= MAX_CALLS_PER_PHASE)
        self.check('no vision calls, observations, or consent', run.get('vision_calls') == 0
                   and run.get('images_sent_to_advisor') is False and run.get('raw_images_sent') is False
                   and not run.get('observations') and not run.get('vision_request') and not run.get('visual_confirmed'))
        return run

    def execute(self):
        try:
            self.check('fresh workspace', not self.workspace.exists())
            picture = fixture_png(self.output / 'software-memory-fixture.png')
            self.summary['fixture'] = {'sha256': hashlib.sha256(picture.read_bytes()).hexdigest(),
                                       'source': 'software_pattern', 'roi': [16, 16, 240, 240],
                                       'roi_review_source': 'scripted software fixture, not human photograph review'}
            self.start(1)
            self.check('initial memory empty', self.events('initial') == [])
            self.call('/api/household/enroll', {'object_id': OBJECT_ID, 'name': '测试物品', 'aliases': []})
            asset = self.call('/api/home-flow/assets', {'data_base64': base64.b64encode(picture.read_bytes()).decode(),
                                                        'source_kind': 'synthetic'})
            self.call('/api/home-flow/reference', {'object_id': OBJECT_ID, 'asset_id': asset['asset_id'],
                                                   'roi': [16, 16, 240, 240], 'roi_reviewed': True})
            missing = self.wait('missing-location', self.call('/api/home-flow/start', {'message': '请记住，测试物品我放在这里了。'}))
            self.check('missing location rejected without write', missing['state'] == 'ERROR' and missing['intent'] == 'remember'
                       and missing['current_location_id'] is None and self.events('missing-location') == [])
            pending = self.wait('pending', self.call('/api/home-flow/start', {'message': '请记住，测试物品我放在书房桌面了。',
                                                                            'current_location_id': 'study-desk'}))
            self.check('explicit location still needs confirmation', pending['state'] == 'CONFIRM_MEMORY' and not pending['history']
                       and self.events('pending') == [])
            self.start(2)
            restored = self.call('/api/home-flow/runs/' + pending['run_id'])
            self.check('pending state survives process restart exactly', restored == pending and self.events('restored-pending') == [])
            payload = {'run_id': pending['run_id'], 'version': pending['version'], 'action': 'confirm_memory'}
            confirmed = self.call('/api/home-flow/act', payload)
            self.summary['runs']['confirmed'] = confirmed
            events = self.events('confirmed')
            self.check('one owner-reported non-visual event', confirmed['state'] == 'COMPLETED' and not confirmed['visual_confirmed']
                       and len(events) == 1 and events[0]['source_kind'] == 'owner_reported' and events[0]['visual_confirmed'] == 0
                       and events[0]['object_id'] == OBJECT_ID and events[0]['location_id'] == 'study-desk')
            self.call('/api/home-flow/act', payload, expected=409)
            self.check('stale duplicate confirmation writes nothing', self.events('duplicate-rejected') == events)
            self.start(3)
            self.check('event survives second restart unchanged', self.events('restored-event') == events)
            recalled = self.wait('history', self.call('/api/home-flow/start', {'message': '测试物品上次记在哪里？请只查询历史，不寻找。'}))
            self.check('actual LLM queries exact saved history', recalled['intent'] == 'history' and recalled['state'] == 'COMPLETED'
                       and len(recalled['history']) == 1
                       and all(recalled['history'][0][key] == events[0][key]
                               for key in ('event_id', 'reported_at', 'location_id', 'location_name'))
                       and recalled['history'][0]['source_kind'] == 'owner_reported'
                       and recalled['history'][0]['visual_confirmed'] is False and self.events('final') == events)
            actual = [self.summary['runs'][name] for name in ('missing-location', 'pending', 'history')]
            self.summary['actual_model_calls'] = sum(row['model_calls'] for row in actual)
            self.summary['actual_total_tokens'] = sum(row['total_tokens'] for row in actual)
            self.check('total real text calls bounded', self.summary['actual_model_calls'] <= MAX_PHASES * MAX_CALLS_PER_PHASE)
            self.summary['checks_passed'] = True
        except Exception as exc:
            self.summary['failure_type'] = type(exc).__name__
            # Do not serialize exception/provider body, credentials, or environment.
            raise
        finally:
            try:
                self.stop()
            finally:
                self.save()
        return self.summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--config', type=Path)
    args = parser.parse_args(argv)
    try:
        output = new_output(args.output_dir)
    except ValueError as exc:
        parser.error(str(exc))
    acceptance = Acceptance(output, None)
    try:
        config, effective = bounded_config(output, args.config)
        acceptance.config_path = config
        sources = [Path(__file__).resolve(), *sorted((ROOT / 'src/hometrace').glob('*.py'))]
        execution = {
            'base_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
            'working_tree_dirty': bool(subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT)),
            'source_sha256': {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},
            'versions': {name: importlib.metadata.version(name) for name in ('hometrace', 'Pillow', 'langchain-openai', 'langgraph')},
            'effective_config': effective,
        }
        (output / 'execution.json').write_text(json.dumps(execution, indent=2) + '\n', encoding='utf-8')
        acceptance.execute()
    except Exception as exc:
        acceptance.summary['failure_type'] = type(exc).__name__
        acceptance.save()
        print('Memory acceptance failed; retained evidence: ' + str(output), flush=True)
        return 1
    print(json.dumps({'checks_passed': True, 'actual_model_calls': acceptance.summary['actual_model_calls'],
                      'image_calls': 0, 'output': str(output)}, ensure_ascii=False), flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
