"""Offline batch consent/control tests; no real photos, model or network."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path

import pytest


SPEC = importlib.util.spec_from_file_location('private_photo_acceptance',
    Path(__file__).resolve().parents[1] / 'tools/accept_private_photo_agent.py')
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


def consent():
    return {'schema_version': 1, 'approved': True, 'review_source': 'explicit test-only review',
            'endpoint': 'https://example.invalid/v1', 'model': 'test-only', 'max_calls': 2,
            'reference_sha256': 'a' * 64, 'reference_derivative_sha256': 'b' * 64,
            'scenes': [{'sample_id': 'one', 'sha256': 'c' * 64, 'derivative_sha256': 'd' * 64},
                       {'sample_id': 'two', 'sha256': 'e' * 64, 'derivative_sha256': 'f' * 64}]}


def request(value, index=0):
    scene = value['scenes'][index]
    return {'request_id': 'request-' + scene['sample_id'], 'endpoint': value['endpoint'], 'model': value['model'],
            'reference_sha256': value['reference_sha256'],
            'reference_derivative_sha256': value['reference_derivative_sha256'],
            'scene_sha256': scene['sha256'], 'scene_derivative_sha256': scene['derivative_sha256'],
            'reference': {'source_kind': 'real_upload'}, 'scene': {'source_kind': 'real_upload'}}


def ledger_inputs(tmp_path, value=None):
    value = value or consent()
    path = tmp_path / 'consent.json'
    path.write_text(json.dumps(value), encoding='utf-8')
    return path, value


@pytest.mark.parametrize('key', ['endpoint', 'model', 'reference_sha256', 'reference_derivative_sha256',
                                'scene_sha256', 'scene_derivative_sha256'])
def test_mismatched_request_never_reserves(tmp_path, key):
    path, value = ledger_inputs(tmp_path)
    with runner.ConsentLedger(path, value, tmp_path / 'output') as ledger:
        wrong = request(value)
        wrong[key] = 'wrong'
        with pytest.raises(ValueError, match='REQUEST_CONSENT_MISMATCH'):
            ledger.reserve('one', wrong)
        assert ledger.value['attempts'] == []


def test_one_scene_once_including_failed_request(tmp_path):
    path, value = ledger_inputs(tmp_path)
    with runner.ConsentLedger(path, value, tmp_path / 'output') as ledger:
        ledger.reserve('one', request(value))
        with pytest.raises(ValueError, match='SCENE_ALREADY_RESERVED'):
            ledger.reserve('one', request(value))
        persisted = runner.read_json(ledger.path)
        assert persisted['attempts'][0]['reservation_consumed_even_on_failure'] is True
        assert persisted['attempts'][0]['status'] == 'reserved_before_send'


def test_consent_cannot_restart_in_new_output(tmp_path):
    path, value = ledger_inputs(tmp_path)
    with runner.ConsentLedger(path, value, tmp_path / 'first') as ledger:
        ledger.reserve('one', request(value))
    with pytest.raises(ValueError, match='CONSENT_ALREADY_BOUND_TO_EXECUTION'):
        with runner.ConsentLedger(path, value, tmp_path / 'different'):
            pytest.fail('Cannot execute under reused consent')


def test_exclusive_lock_and_call_budget(tmp_path):
    value = consent()
    value['max_calls'] = 1
    path, value = ledger_inputs(tmp_path, value)
    with runner.ConsentLedger(path, value, tmp_path / 'first') as ledger:
        with pytest.raises(FileExistsError):
            with runner.ConsentLedger(path, value, tmp_path / 'other'):
                pytest.fail('Concurrent consent accepted')
        ledger.reserve('one', request(value))
        with pytest.raises(ValueError, match='BUDGET_EXHAUSTED'):
            ledger.reserve('two', request(value, 1))


@pytest.mark.parametrize('key', ['sample_id', 'sha256', 'derivative_sha256'])
def test_duplicate_consent_samples_rejected(key):
    value = consent()
    value['scenes'][1][key] = value['scenes'][0][key]
    with pytest.raises(ValueError, match='DUPLICATE'):
        runner.validate_consent(value)


def test_consent_edit_after_claim_is_rejected(tmp_path):
    path, value = ledger_inputs(tmp_path)
    with runner.ConsentLedger(path, value, tmp_path / 'output') as ledger:
        path.write_text('{}', encoding='utf-8')
        with pytest.raises(ValueError, match='CONSENT_CHANGED'):
            ledger.reserve('one', request(value))


class Service:
    def __init__(self, value, end_state='AWAITING_REVIEW', *, ask_followup=False):
        self.value, self.end_state, self.ask_followup = value, end_state, ask_followup
        self.actions, self.starts, self.followups = [], [], []
        self.run = None

    def scene(self, location, asset_id):
        self.current_asset = asset_id

    def start(self, message, current_location_id):
        self.starts.append(self.current_asset)
        index = 0 if self.current_asset == 'asset-one' else 1
        self.run = {'run_id': 'run-' + self.current_asset, 'version': 1,
                    'state': 'AWAITING_IMAGE_CONSENT', 'vision_request': request(self.value, index),
                    'vision_calls': 0, 'visual_advice': [], 'history': []}
        return deepcopy(self.run)

    def act(self, run_id, version, action, **kwargs):
        assert action == 'approve_vision', 'No owner acceptance, memory confirmation, or retries'
        self.actions.append(action)
        self.run['vision_calls'] += 1
        self.run['visual_advice'].append({'execution_status': 'completed'})
        self.run['version'] += 1
        self.run['state'] = 'AWAITING_NEW_PHOTO' if self.ask_followup and self.run['vision_calls'] == 1 else self.end_state
        self.run['photo_request'] = {'location_id': 'study-desk'}
        return deepcopy(self.run)

    def submit_new_photo(self, run_id, version, asset_id):
        self.followups.append(asset_id)
        self.run['state'] = 'AWAITING_IMAGE_CONSENT'
        self.run['vision_request'] = request(self.value, 1)
        self.run['version'] += 1
        return deepcopy(self.run)

    def get(self, run_id):
        return deepcopy(self.run)


def prepared():
    return {'object': {'name': '测试物品'}, 'scenes': [
        {'sample_id': 'one', 'asset': {'asset_id': 'asset-one'}},
        {'sample_id': 'two', 'asset': {'asset_id': 'asset-two'}}]}


@pytest.mark.parametrize('state', ['AWAITING_REVIEW', 'CONFIRM_MEMORY', 'UNKNOWN', 'ERROR'])
def test_real_workflow_results_never_trigger_owner_acceptance(tmp_path, state):
    path, value = ledger_inputs(tmp_path)
    service = Service(value, state)
    summary = {'runs': [], 'failed_attempts': [], 'unexecuted': []}
    with runner.ConsentLedger(path, value, tmp_path / 'output') as ledger:
        runner.run_cases(service, prepared(), value, ledger, summary, lambda: None)
        assert len(ledger.value['attempts']) == 2
    assert service.actions == ['approve_vision', 'approve_vision']
    assert all(row['final']['state'] == state and row['final']['history'] == [] for row in summary['runs'])
    assert 'sample_id' not in summary['prompt']


def test_followup_only_after_actual_model_request_and_no_second_run(tmp_path):
    value = consent()
    value['followups'] = {'one': 'two'}
    path, value = ledger_inputs(tmp_path, value)
    service = Service(value, ask_followup=True)
    summary = {'runs': [], 'failed_attempts': [], 'unexecuted': []}
    with runner.ConsentLedger(path, value, tmp_path / 'output') as ledger:
        runner.run_cases(service, prepared(), value, ledger, summary, lambda: None)
    assert service.starts == ['asset-one']
    assert service.followups == ['asset-two']
    assert summary['runs'][0]['samples'] == ['one', 'two']
    assert summary['runs'][0]['final']['state'] == 'AWAITING_REVIEW'


def test_followup_missing_preserves_waiting_state(tmp_path):
    path, value = ledger_inputs(tmp_path)
    service = Service(value, ask_followup=True)
    summary = {'runs': [], 'failed_attempts': [], 'unexecuted': []}
    with runner.ConsentLedger(path, value, tmp_path / 'output') as ledger:
        runner.run_cases(service, prepared(), value, ledger, summary, lambda: None)
    assert not service.followups
    assert all(row['final']['state'] == 'AWAITING_NEW_PHOTO' for row in summary['runs'])
    assert all(row['pending_reason'] == 'NO_UNUSED_AUTHORIZED_FOLLOWUP_FOR_REQUEST' for row in summary['runs'])


class RunningService(Service):
    """Local worker double: cancel retries never issue another model request."""
    def __init__(self, value, *, starts_running=False, conflict_once=False, fail_first_get=False):
        super().__init__(value, end_state='RUNNING')
        self.starts_running = starts_running
        self.conflict_once = conflict_once
        self.fail_first_get = fail_first_get
        self.get_calls = 0
        self.cancel_versions = []
        self.waits = []

    def start(self, message, current_location_id):
        result = super().start(message, current_location_id)
        if self.starts_running:
            self.run['state'] = result['state'] = 'RUNNING'
        return result

    def get(self, run_id):
        self.get_calls += 1
        if self.fail_first_get and self.get_calls == 1:
            raise OSError('test-only state read failed')
        return super().get(run_id)

    def act(self, run_id, version, action, **kwargs):
        if action != 'cancel':
            return super().act(run_id, version, action, **kwargs)
        self.actions.append(action)
        self.cancel_versions.append(version)
        assert version == self.run['version']
        if self.conflict_once and len(self.cancel_versions) == 1:
            from hometrace.household_service import HouseholdConflict
            self.run['version'] += 1
            raise HouseholdConflict('test-only worker advanced version')
        self.run['state'] = 'CANCELLED'
        self.run['version'] += 1
        return deepcopy(self.run)

    def wait(self, run_id, timeout):
        self.waits.append((run_id, timeout))
        assert self.run['state'] == 'CANCELLED'
        # Represent usage settling after cancellation, without sending anything.
        self.run['vision_actual_tokens'] = 17 if self.run['vision_calls'] else 0
        return deepcopy(self.run)


def test_timeout_cancellation_refreshes_conflicted_version_without_resending(tmp_path):
    path, value = ledger_inputs(tmp_path)
    service = RunningService(value, conflict_once=True)
    summary = {'runs': [], 'failed_attempts': [], 'unexecuted': []}
    snapshots = []
    now = [0.0]

    def advance(_seconds):
        now[0] += runner.RUN_SECONDS + 1

    single = prepared()
    single['scenes'] = single['scenes'][:1]
    with runner.ConsentLedger(path, value, tmp_path / 'output') as ledger:
        runner.run_cases(service, single, value, ledger, summary,
                         lambda: snapshots.append(deepcopy(summary)),
                         clock=lambda: now[0], sleeper=advance)
        assert len(ledger.value['attempts']) == 1
        assert ledger.value['attempts'][0]['reservation_consumed_even_on_failure'] is True
    assert service.actions == ['approve_vision', 'cancel', 'cancel']
    assert service.cancel_versions == [2, 3]
    assert service.starts == ['asset-one']
    assert service.followups == []
    assert service.waits == [('run-asset-one', 50)]
    final = snapshots[-1]['runs'][0]['final']
    assert final['state'] == 'CANCELLED'
    assert final['vision_calls'] == 1
    assert final['vision_actual_tokens'] == 17
    assert final['history'] == []
    assert any(row.get('reason') == 'EXECUTION_DEADLINE' for row in summary['failed_attempts'])


def test_first_state_read_failure_cancels_and_saves_the_started_run(tmp_path):
    path, value = ledger_inputs(tmp_path)
    service = RunningService(value, starts_running=True, fail_first_get=True)
    summary = {'runs': [], 'failed_attempts': [], 'unexecuted': []}
    snapshots = []
    with runner.ConsentLedger(path, value, tmp_path / 'output') as ledger:
        with pytest.raises(OSError, match='test-only state read failed'):
            runner.run_cases(service, prepared(), value, ledger, summary,
                             lambda: snapshots.append(deepcopy(summary)),
                             clock=lambda: 0.0, sleeper=lambda _seconds: None)
        assert ledger.value['attempts'] == []
    assert service.get_calls == 2
    assert service.actions == ['cancel']
    assert service.starts == ['asset-one']
    assert service.followups == []
    assert service.waits == [('run-asset-one', 50)]
    record = snapshots[-1]['runs'][0]
    assert record['failure_type'] == 'OSError'
    assert record['stopped_without_retry'] is True
    assert record['final']['state'] == 'CANCELLED'
    assert record['final']['vision_calls'] == 0
    assert record['final']['history'] == []
    assert len(snapshots[-1]['runs']) == 1
