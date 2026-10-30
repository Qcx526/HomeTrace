"""Run a bounded, explicitly authorized real-photo Agent diagnostic.

This calls the production service directly, not HTTP or a browser. It never
confirms identity or writes owner memory. All photos and evidence stay ignored.
Each approved scene can be sent once; failures consume the durable reservation.
"""
from contextlib import closing
from dataclasses import replace
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import time


MAX_CALLS = 10
RUN_SECONDS = 300
TOTAL_SECONDS = 1800
LOCATION = 'study-desk'


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write_json(path, value):
    """Atomic durable update; never replace any frozen input or old output."""
    path = Path(path)
    temporary = path.with_name(path.name + '.pending')
    with temporary.open('x', encoding='utf-8', newline='\n') as output:
        json.dump(value, output, ensure_ascii=False, indent=2)
        output.write('\n')
        output.flush()
        os.fsync(output.fileno())
    os.replace(temporary, path)


def require(condition, code):
    if not condition:
        raise ValueError(code)


def private_path(path, repo):
    path = Path(path).resolve()
    require(path.is_relative_to(repo.resolve()), 'PATH_OUTSIDE_REPOSITORY')
    result = subprocess.run(['git', 'check-ignore', '--quiet', '--',
                             path.relative_to(repo).as_posix()], cwd=repo,
                            capture_output=True, check=False)
    require(result.returncode == 0, 'PATH_NOT_GIT_IGNORED')
    return path


def validate_consent(consent):
    require(consent.get('schema_version') == 1 and consent.get('approved') is True,
            'EXPLICIT_CONSENT_REQUIRED')
    require(isinstance(consent.get('review_source'), str) and bool(consent['review_source'].strip()),
            'CONSENT_REVIEW_SOURCE_REQUIRED')
    require(type(consent.get('max_calls')) is int and 0 < consent['max_calls'] <= MAX_CALLS,
            'CONSENT_CALL_LIMIT_INVALID')
    require(isinstance(consent.get('endpoint'), str) and consent['endpoint'].startswith('https://')
            and isinstance(consent.get('model'), str) and bool(consent['model']),
            'CONSENT_DESTINATION_REQUIRED')
    rows = consent.get('scenes')
    require(isinstance(rows, list) and 0 < len(rows) <= MAX_CALLS, 'CONSENT_SCENES_INVALID')
    for key in ('sample_id', 'sha256', 'derivative_sha256'):
        values = [row.get(key) for row in rows]
        require(all(isinstance(value, str) and value for value in values)
                and len(values) == len(set(values)), 'CONSENT_DUPLICATE_OR_INVALID_' + key.upper())
    for row in [*rows, {'sha256': consent.get('reference_sha256'),
                       'derivative_sha256': consent.get('reference_derivative_sha256')}]:
        require(all(isinstance(row[k], str) and re.fullmatch('[0-9a-f]{64}', row[k])
                    for k in ('sha256', 'derivative_sha256')), 'CONSENT_HASH_INVALID')
    require(consent['reference_sha256'] not in {row['sha256'] for row in rows}, 'REFERENCE_REPLAY')
    sample_ids = {row['sample_id'] for row in rows}
    followups = consent.get('followups', {})
    require(type(followups) is dict and all(a in sample_ids and b in sample_ids and a != b
            for a, b in followups.items()), 'FOLLOWUP_MAPPING_INVALID')
    require(len(set(followups.values())) == len(followups)
            and not set(followups).intersection(followups.values()), 'FOLLOWUP_MAPPING_AMBIGUOUS')


class ConsentLedger:
    """One consent file belongs to exactly one execution, even across outputs.

    A crash leaves a lock and/or ledger. Neither is auto-cleared or resumed. This
    deliberately loses unused quota rather than risking a duplicate private send.
    """
    def __init__(self, consent_path, consent, output):
        validate_consent(consent)
        self.consent_path = Path(consent_path).resolve()
        self.consent = consent
        self.output = Path(output).resolve()
        self.path = self.consent_path.with_name(self.consent_path.name + '.ledger.json')
        self.lock_path = self.consent_path.with_name(self.consent_path.name + '.lock')
        self.claimed = False
        self.value = None

    def __enter__(self):
        self.lock = self.lock_path.open('x', encoding='utf-8')
        self.claimed = True
        try:
            self.lock.write(str(os.getpid()))
            self.lock.flush()
            os.fsync(self.lock.fileno())
            require(not self.path.exists(), 'CONSENT_ALREADY_BOUND_TO_EXECUTION')
            self.value = {'schema_version': 1, 'consent_sha256': digest(self.consent_path.read_bytes()),
                          'output_dir': str(self.output), 'max_calls': self.consent['max_calls'],
                          'attempts': [], 'state': 'claimed', 'automatic_retry': False}
            write_json(self.path, self.value)
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def reserve(self, sample_id, request):
        require(self.claimed and self.value is not None, 'CONSENT_NOT_CLAIMED')
        require(digest(self.consent_path.read_bytes()) == self.value['consent_sha256'], 'CONSENT_CHANGED')
        attempts = self.value['attempts']
        require(len(attempts) < self.consent['max_calls'], 'CONSENT_BUDGET_EXHAUSTED')
        require(not any(row['sample_id'] == sample_id for row in attempts), 'SCENE_ALREADY_RESERVED')
        expected = next((row for row in self.consent['scenes'] if row['sample_id'] == sample_id), None)
        require(expected is not None, 'SCENE_NOT_AUTHORIZED')
        bindings = {'endpoint': self.consent['endpoint'], 'model': self.consent['model'],
                    'reference_sha256': self.consent['reference_sha256'],
                    'reference_derivative_sha256': self.consent['reference_derivative_sha256'],
                    'scene_sha256': expected['sha256'],
                    'scene_derivative_sha256': expected['derivative_sha256']}
        require(all(request.get(key) == value for key, value in bindings.items()), 'REQUEST_CONSENT_MISMATCH')
        require(request.get('reference', {}).get('source_kind') == 'real_upload'
                and request.get('scene', {}).get('source_kind') == 'real_upload', 'REQUEST_PROVENANCE_MISMATCH')
        request_id = request.get('request_id')
        require(isinstance(request_id, str) and request_id
                and not any(row['request_id'] == request_id for row in attempts), 'REQUEST_ID_INVALID')
        entry = {'sample_id': sample_id, 'request_id': request_id, **bindings,
                 'status': 'reserved_before_send', 'reservation_consumed_even_on_failure': True}
        attempts.append(entry)
        self.value['state'] = 'running'
        write_json(self.path, self.value)
        return entry

    def __exit__(self, *_):
        if self.claimed:
            self.lock.close()
            self.lock_path.unlink()
            self.claimed = False


def validate_prepared(prepared, consent):
    """Read-only local validation before constructing any network-capable model."""
    from hometrace.visual_advisor_client import _derivative
    validate_consent(consent)
    require(prepared.get('schema_version') == 1 and prepared.get('source_kind') == 'real_upload'
            and prepared.get('scope') == 'diagnostic_reused', 'PREPARED_SOURCE_INVALID')
    require(prepared.get('cloud_calls') == 0 and prepared.get('no_history') is True,
            'PREPARED_NOT_EMPTY_DIAGNOSTIC')
    workspace = Path(prepared['workspace']).resolve()
    require(workspace.is_dir(), 'PREPARED_WORKSPACE_MISSING')
    with closing(sqlite3.connect((workspace / 'photo-flow.sqlite3').as_uri() + '?mode=ro', uri=True)) as db:
        require(db.execute('SELECT count(*) FROM runs').fetchone()[0] == 0
                and db.execute('SELECT count(*) FROM evidence').fetchone()[0] == 0,
                'PREPARED_HAS_PREVIOUS_RUNS')
        assets = {key: json.loads(value) for key, value in db.execute('SELECT asset_id,payload FROM assets')}
        refs = {key: json.loads(value) for key, value in db.execute('SELECT object_id,payload FROM refs')}
    with closing(sqlite3.connect((workspace / 'owner-memory.sqlite3').as_uri() + '?mode=ro', uri=True)) as db:
        require(db.execute('SELECT count(*) FROM hm_owner_events').fetchone()[0] == 0, 'PREPARED_HAS_OWNER_HISTORY')
    reference = prepared['reference']
    stored = refs.get(prepared['object_id'])
    require(stored is not None and all(stored.get(key) == reference.get(key)
            for key in ('asset_id', 'sha256', 'roi', 'roi_reviewed')), 'REFERENCE_REGISTRATION_MISMATCH')
    require(reference.get('roi_reviewed') is True and reference.get('identity_reviewed') is True,
            'REFERENCE_REVIEW_REQUIRED')

    def check_asset(row, expected_sha, expected_derivative, roi=None):
        asset = assets.get(row['asset_id'])
        require(asset is not None and asset['sha256'] == row['sha256'] == expected_sha
                and asset['source_kind'] == row.get('source_kind') == 'real_upload', 'ASSET_BINDING_INVALID')
        path = workspace / asset['path']
        require(not path.is_symlink() and path.resolve().is_relative_to(workspace / 'photos'), 'ASSET_PATH_INVALID')
        raw = path.read_bytes()
        require(digest(raw) == expected_sha and digest(_derivative(raw, roi)) == expected_derivative,
                'ASSET_OR_DERIVATIVE_HASH_MISMATCH')

    check_asset(reference, consent['reference_sha256'], consent['reference_derivative_sha256'], reference['roi'])
    rows = prepared['scenes']
    by_id = {row['sample_id']: row for row in rows}
    require(len(by_id) == len(rows) and set(by_id) == {row['sample_id'] for row in consent['scenes']},
            'PREPARED_SCENE_SET_MISMATCH')
    for expected in consent['scenes']:
        check_asset(by_id[expected['sample_id']]['asset'], expected['sha256'], expected['derivative_sha256'])
    return workspace


def prompt_for(object_name):
    return (f'请寻找已登记的{object_name}。本轮只检查书房桌面；这是照片演示地点映射，'
            '不证明实际拍摄地点，也没有主人放置历史。先调用本地观察工具，再请求一次视觉顾问比较'
            '登记参考与当前完整场景。读取实际反馈后由你决定：请求补充新视角、请求主人核对或结束。'
            '如果收到了新照片，请重新执行本地观察并请求它的单次视觉比较。'
            '不检查其他地点，不重复比较任何照片；证据不足应说明未确认，不能自动确认身份或写入记忆。')


def run_cases(service, prepared, consent, ledger, summary, save, *, clock=time.monotonic, sleeper=time.sleep):
    """Only transport approvals/new approved views; all tools are chosen by LLM."""
    samples = {row['sample_id']: row for row in prepared['scenes']}
    used = set()
    deadline = clock() + TOTAL_SECONDS
    summary['prompt'] = prompt_for(prepared['object']['name'])
    summary['prompt_limitations'] = 'Local observation and one comparison are explicitly requested; subsequent decisions are real model choices.'

    def cancel_active(run):
        # Optimistic versions can change while a call is returning. These are
        # bounded state-read retries, never model/network retries.
        for _ in range(3):
            current = service.get(run['run_id'])
            if current['state'] != 'RUNNING':
                return current
            try:
                return service.act(current['run_id'], current['version'], 'cancel')
            except Exception as error:
                if type(error).__name__ != 'HouseholdConflict':
                    raise
        raise RuntimeError('ACTIVE_RUN_CANCELLATION_CONFLICT')

    def wait(run, run_deadline):
        while run['state'] == 'RUNNING' and clock() < min(deadline, run_deadline):
            sleeper(.2)
            run = service.get(run['run_id'])
        if run['state'] == 'RUNNING':
            summary['failed_attempts'].append({'run_id': run['run_id'], 'reason': 'EXECUTION_DEADLINE'})
            # Never retry any model call. Cancel blocks later decisions; in-flight
            # calls cannot be retracted and keep their consumed reservation.
            run = cancel_active(run)
        return run

    for scene in prepared['scenes']:
        sample = scene['sample_id']
        if sample in used:
            continue
        if clock() >= deadline:
            summary['unexecuted'].append({'sample_id': sample, 'reason': 'TOTAL_DEADLINE'})
            continue
        used.add(sample)
        run_deadline = min(deadline, clock() + RUN_SECONDS)
        record = {'initial_sample_id': sample, 'samples': [sample], 'snapshots': [], 'operator_actions': []}
        summary['runs'].append(record)
        save()
        run = None
        active = sample
        try:
            service.scene(LOCATION, scene['asset']['asset_id'])
            run = service.start(summary['prompt'], current_location_id=LOCATION)
            run = wait(run, run_deadline)
            while True:
                record['snapshots'].append(run)
                record['final'] = run
                save()
                if clock() >= min(deadline, run_deadline):
                    break
                if run['state'] == 'AWAITING_IMAGE_CONSENT':
                    request = run['vision_request']
                    # The durable reservation always precedes the only send trigger.
                    reservation = ledger.reserve(active, request)
                    record['operator_actions'].append({'action': 'approve_vision',
                                                       'authorization': 'explicit_owner_batch_consent',
                                                       'reservation': reservation})
                    save()
                    run = service.act(run['run_id'], run['version'], 'approve_vision',
                                      request_id=request['request_id'])
                    run = wait(run, run_deadline)
                elif run['state'] == 'AWAITING_NEW_PHOTO':
                    followup = consent.get('followups', {}).get(active)
                    if not followup or followup in used or run['photo_request']['location_id'] != LOCATION:
                        record['pending_reason'] = 'NO_UNUSED_AUTHORIZED_FOLLOWUP_FOR_REQUEST'
                        break
                    used.add(followup)
                    active = followup
                    record['samples'].append(followup)
                    record['operator_actions'].append({'action': 'submit_new_photo', 'sample_id': followup,
                                                       'source': 'existing_user_supplied_followup_not_new_live_capture'})
                    save()
                    run = service.submit_new_photo(run['run_id'], run['version'],
                               samples[followup]['asset']['asset_id'])
                    run = wait(run, run_deadline)
                else:
                    # AWAITING_REVIEW and CONFIRM_MEMORY are intentionally left
                    # untouched. No fixture labels or model scores authorize them.
                    break
            record['final'] = run
            if run['state'] in ('ERROR', 'BUDGET_EXCEEDED', 'CANCELLED', 'MODEL_UNAVAILABLE'):
                summary['failed_attempts'].append({'sample_id': sample, 'run_id': run['run_id'], 'state': run['state']})
        except Exception as error:
            record['failure_type'] = type(error).__name__
            summary['failed_attempts'].append({'sample_id': sample, 'failure_type': type(error).__name__})
            if run is not None:
                record['final'] = cancel_active(run)
            # Binding/budget errors must not be worked around using another run.
            record['stopped_without_retry'] = True
            save()
            raise
        finally:
            if run is not None and record.get('final', {}).get('state') == 'CANCELLED':
                # Join the bounded production worker so late paid usage is
                # recorded before final evidence is frozen or scenes change.
                record['final'] = service.wait(run['run_id'], timeout=50)
            save()
            print(json.dumps({'sample': sample, 'state': record.get('final', {}).get('state', 'FAILED'),
                              'vision_calls': record.get('final', {}).get('vision_calls', 0),
                              'advice_results': len(record.get('final', {}).get('visual_advice', []))}), flush=True)
    summary['used_sample_ids'] = sorted(used)


def execution_metadata(repo):
    source = [*sorted((repo / 'src/hometrace').glob('*.py')), Path(__file__).resolve()]
    versions = {}
    for name in ('hometrace', 'openai', 'Pillow', 'langgraph', 'langchain-core', 'langchain-openai'):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = 'not-installed'
    return {'commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=repo, text=True).strip(),
            'working_tree_dirty': bool(subprocess.check_output(['git', 'status', '--porcelain'], cwd=repo)),
            'source_sha256': {path.relative_to(repo).as_posix(): digest(path.read_bytes()) for path in source},
            'versions': versions}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepared', type=Path, required=True)
    parser.add_argument('--consent', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args(argv)
    repo = Path(__file__).resolve().parents[1]
    prepared_path, consent_path, output = (private_path(path, repo)
                                           for path in (args.prepared, args.consent, args.output_dir))
    require(not output.exists(), 'OUTPUT_MUST_BE_NEW')
    prepared, consent = read_json(prepared_path), read_json(consent_path)
    workspace = validate_prepared(prepared, consent)
    private_path(workspace, repo)
    # Load config only after validating every authorized image. No client exists yet.
    from hometrace.agent_config import load_agent_config
    config = load_agent_config(project_root=repo)
    require(config.llm.base_url == consent['endpoint'] and config.llm.model == consent['model'],
            'CONFIG_DESTINATION_DIFFERS_FROM_CONSENT')
    configured_retries = config.llm.max_retries
    # This diagnostic never retries a failed model request. Preserve the
    # production YAML; the explicit runtime override is retained in evidence.
    config = replace(config, llm=replace(config.llm, max_retries=0))
    with ConsentLedger(consent_path, consent, output) as ledger:
        output.mkdir(parents=True)
        shutil.copytree(workspace, output / 'workspace')
        summary = {'schema_version': 1, 'source_kind': 'real_upload', 'scope': 'diagnostic_reused',
                   'transport': 'direct production service invocation, not HTTP/browser',
                   'navigation': 'simulated', 'location_mapping': 'study-desk is an explicit demo mapping',
                   'owner_confirmation_performed': False, 'history_seeded': False,
                   'independent_test': False, 'production_FOUND': False,
                   'prepared_sha256': digest(prepared_path.read_bytes()),
                   'consent_sha256': digest(consent_path.read_bytes()),
                   'execution': execution_metadata(repo), 'runs': [], 'failed_attempts': [], 'unexecuted': [],
                   'runtime_overrides': {'decision_max_retries': 0, 'configured_max_retries': configured_retries,
                                         'production_config_modified': False, 'advisor_max_retries': 0},
                   'limits': {'max_vision_calls': consent['max_calls'], 'per_scene_calls': 1,
                              'run_seconds': RUN_SECONDS, 'total_seconds': TOTAL_SECONDS, 'retries': 0}}
        save = lambda: write_json(output / 'summary.private.json', summary)
        save()
        try:
            from hometrace.household_service import HouseholdService
            from hometrace.visual_photo_agent_service import VisualPhotoAgentService
            service = VisualPhotoAgentService(HouseholdService(output / 'workspace'), agent_config=config)
            require(service.config()['model_available'], 'REAL_MODEL_UNAVAILABLE')
            run_cases(service, prepared, consent, ledger, summary, save)
            with closing(sqlite3.connect(service.household.memory_path)) as db:
                summary['owner_history_rows_after'] = db.execute('SELECT count(*) FROM hm_owner_events').fetchone()[0]
            require(summary['owner_history_rows_after'] == 0, 'UNEXPECTED_OWNER_MEMORY_WRITE')
            summary['execution_finished'] = True
        except Exception as error:
            summary['failure_type'] = type(error).__name__
            summary['execution_finished'] = False
            raise
        finally:
            summary['reserved_vision_calls'] = len(ledger.value['attempts'])
            summary['usage'] = {key: sum(row.get('final', {}).get(key, 0) for row in summary['runs'])
                                for key in ('model_calls', 'total_tokens', 'vision_calls',
                                            'vision_actual_tokens', 'vision_tokens_used')}
            ledger.value['state'] = 'finished' if summary.get('execution_finished') else 'stopped'
            write_json(ledger.path, ledger.value)
            save()


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        # Never echo provider exception bodies, private paths, or configured keys.
        print(json.dumps({'execution': 'stopped', 'error_type': type(error).__name__}), flush=True)
        raise SystemExit(1) from None
