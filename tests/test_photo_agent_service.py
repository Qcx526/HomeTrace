"""Offline protocol regressions, not evidence of LLM or household recognition.

The model returns scripted AIMessage tool calls. PhotoFlow's upload, database,
SearchCore and LangChain tool execution are real; the detector is an explicitly
injected software double. No test loads .env or sends a provider request.
"""
from contextlib import closing
from dataclasses import replace
import json
from threading import Event

import pytest

pytest.importorskip('langgraph')
pytest.importorskip('langchain_core')
from langchain_core.messages import AIMessage

from hometrace.agent_config import AgentConfig, AgentConfigError, BudgetConfig, LLMConfig
from hometrace.household_service import HouseholdService
from hometrace.photo_agent_service import PhotoAgentService
from hometrace.photo_flow_service import PhotoFlowService
import hometrace.photo_agent_service as agent_module
from test_photo_flow_service import ScriptedEngine, evidence_count, history, register, remember, upload


class ScriptedModel:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.contexts = []
        self.bindings = []
        self.invocation_options = []

    def bind_tools(self, tools):
        self.bindings.append([tool.name for tool in tools])
        return self

    def invoke(self, messages, **kwargs):
        context = json.loads(messages[-1].content)
        self.contexts.append(context)
        self.invocation_options.append(kwargs)
        result = next(self.responses)
        if callable(result):
            result = result(context)
        if isinstance(result, Exception):
            raise result
        return result


def call(name=None, args=None, *, content='', usage=True):
    fields = {'content': content,
              'tool_calls': [{'name': name, 'args': args or {}, 'id': 'scripted-call'}] if name else []}
    if usage:
        fields['usage_metadata'] = {'input_tokens': 90, 'output_tokens': 10, 'total_tokens': 100}
    return AIMessage(**fields)


def resolve(intent='find', object_id='keys-a'):
    return call('resolve_request', {'object_id': object_id, 'intent': intent, 'reason': '按已登记目录解析'})


def inspect(location):
    return call('inspect_location', {'location_id': location, 'reason': '根据实际历史与观察选择'})


def stop():
    return call('finish_search', {'reason': '现有证据不足，停止查找'})


def config(tmp_path, **limits):
    budget = BudgetConfig(12, 12, 3, 32000, True)
    return AgentConfig(LLMConfig('openai_compatible', 'scripted-offline-test',
        'https://provider.invalid/v1', 1, 0, False), replace(budget, **limits),
        'unit-test-secret-not-a-real-key', tmp_path, tmp_path / 'unused-config.yaml')


def create(tmp_path, responses, outcomes=None, **limits):
    household = HouseholdService(tmp_path / 'home')
    engine = ScriptedEngine(outcomes)
    model = ScriptedModel(responses)
    service = PhotoAgentService(household, agent_config=config(tmp_path, **limits),
                                model=model, engine_factory=engine)
    assert service.config()['model_available'] is True
    return household, service, engine, model


def complete(service, message='请帮忙寻找出门用的那串蓝色钥匙', location=None):
    return service.wait(service.start(message, location)['run_id'])


def guards(run):
    return [row['result']['code'] for row in run['trace'] if row['tool'] == 'llm_guard']


def test_model_selects_nonfirst_location_and_receives_each_actual_feedback(tmp_path):
    def after_unknown(context):
        assert context['visited'] == ['study-desk']
        assert context['observations'][0]['status'] == 'UNKNOWN'
        assert context['observations'][0]['identity_confirmed'] is False
        return inspect('living-table')

    home, service, engine, model = create(tmp_path,
        [resolve(), inspect('study-desk'), after_unknown], {'living-table': 'candidate'})
    register(home, service)
    remember(home, 'entry-tray', '2026-10-27T09:00:00+08:00', 'owner')
    for seed, place in enumerate(('study-desk', 'living-table'), 2):
        service.scene(place, upload(service, seed)['asset_id'])
    run = complete(service)
    assert run['state'] == 'AWAITING_REVIEW'
    assert run['planned_locations'][0]['location_id'] == 'entry-tray'
    assert run['visited'] == ['study-desk', 'living-table']
    assert [row[0] for row in engine.calls] == run['visited']
    assert run['candidate']['bbox'] == [8, 8, 48, 48]
    assert run['visual_confirmed'] is False
    assert run['core_reports'][-1]['result_status'] == 'SUSPECTED'
    assert run['core_reports'][-1]['confirmed_evidence_ids'] == []
    assert run['model_calls'] == run['tool_calls'] == len(model.contexts) == 3
    assert model.contexts[1]['history'][0]['location_id'] == 'entry-tray'
    assert model.contexts[1]['history'][0]['historical_only'] is True
    assert evidence_count(service) == 2 and len(history(home)) == 1
    assert all(0 < options['max_tokens'] <= 512 for options in model.invocation_options)
    assert model.contexts[0]['phase'] == 'resolve_request'
    assert model.contexts[1]['phase'] == 'searching_bound_object'
    assert 'resolve_request' not in model.bindings[-1]
    assert 'inspect_location' in model.bindings[-1]
    assert model.contexts[-1]['last_tool_result']['tool'] == 'inspect_location'


def test_remember_and_history_are_model_resolved_but_require_owner_write(tmp_path):
    home, service, engine, model = create(tmp_path, [resolve('remember'), resolve('history')])
    register(home, service)
    pending = complete(service, '这串出门带的东西就先搁这里，你记一下', 'study-desk')
    assert pending['state'] == 'CONFIRM_MEMORY' and history(home) == []
    assert not engine.calls and evidence_count(service) == 0
    confirmed = service.act(pending['run_id'], pending['version'], 'confirm_memory')
    assert confirmed['state'] == 'COMPLETED' and confirmed['visual_confirmed'] is False
    recalled = complete(service, '我上次跟你说搁在哪儿来着')
    assert recalled['state'] == 'COMPLETED'
    assert recalled['history'][0]['location_id'] == 'study-desk'
    assert recalled['history'][0]['source_kind'] == 'owner_reported'
    assert len(model.contexts) == 2 and not engine.calls


@pytest.mark.parametrize('tool,state', [('unknown_object', 'UNKNOWN_OBJECT'), ('decline_request', 'CANCELLED')])
def test_model_unknown_or_decline_never_navigates_or_writes(tmp_path, tool, state):
    home, service, engine, _ = create(tmp_path, [call(tool, {'reason': '不执行此请求'})])
    register(home, service)
    run = complete(service, '不用找了，只是随口一说')
    assert run['state'] == state and run['visited'] == []
    assert not engine.calls and not history(home) and evidence_count(service) == 0


def test_model_clarification_requires_existing_unique_choices_then_resumes_model(tmp_path):
    home, service, engine, model = create(tmp_path, [
        call('clarify_request', {'intent': 'find', 'candidate_ids': ['keys-a', 'keys-b'],
                                 'question': '是蓝钥匙还是红钥匙？'}), stop()])
    register(home, service)
    register(home, service, object_id='keys-b', name='红钥匙', seed=2)
    pending = complete(service)
    assert pending['state'] == 'CLARIFY' and len(pending['matches']) == 2
    with pytest.raises(ValueError):
        service.act(pending['run_id'], pending['version'], 'select', 'made-up')
    service.act(pending['run_id'], pending['version'], 'select', 'keys-b')
    run = service.wait(pending['run_id'])
    assert run['state'] == 'UNKNOWN' and run['selected_object']['object_id'] == 'keys-b'
    assert model.contexts[-1]['selected_object_id'] == 'keys-b'
    assert not engine.calls and not history(home)


def test_owner_rejection_causes_new_model_decision_not_fixed_next_location(tmp_path):
    def after_reject(context):
        assert context['owner_rejected_locations'] == ['entry-tray']
        assert context['observations'][0]['status'] == 'SUSPECTED'
        assert context['observations'][0]['identity_confirmed'] is False
        return inspect('study-desk')

    home, service, engine, model = create(tmp_path, [resolve(), inspect('entry-tray'), after_reject],
        {'entry-tray': 'candidate', 'study-desk': 'candidate'})
    register(home, service)
    for seed, place in enumerate(('entry-tray', 'study-desk'), 2):
        service.scene(place, upload(service, seed)['asset_id'])
    first = complete(service)
    assert first['state'] == 'AWAITING_REVIEW' and len(model.contexts) == 2
    service.act(first['run_id'], first['version'], 'reject_candidate')
    second = service.wait(first['run_id'])
    assert second['state'] == 'AWAITING_REVIEW' and second['candidate']['location_id'] == 'study-desk'
    assert len(model.contexts) == 3 and second['visited'] == ['entry-tray', 'study-desk']
    accepted = service.act(second['run_id'], second['version'], 'accept_candidate')
    assert accepted['state'] == 'USER_CONFIRMED' and accepted['visual_confirmed'] is False
    assert history(home)[0]['source_kind'] == 'owner_reported'
    assert all(row['result_status'] == 'SUSPECTED' for row in accepted['core_reports'])


@pytest.mark.parametrize('response,code', [
    (call('resolve_request', {'object_id': 'keys-a', 'intent': 'find', 'reason': 'x'}, usage=False), 'TOKEN_USAGE_UNAVAILABLE'),
    (call(content='FOUND，已经在书房找到了'), 'EXACTLY_ONE_TOOL_REQUIRED'),
    (call('FOUND', {'location_id': 'study-desk'}), 'INVALID_TOOL_ARGUMENTS'),
    (call('resolve_request', {'object_id': 'keys-a', 'intent': 'find', 'reason': 'x', 'found': True}), 'INVALID_TOOL_ARGUMENTS'),
    (call('resolve_request', {'object_id': 42, 'intent': 'find', 'reason': 'x'}), 'INVALID_TOOL_ARGUMENTS'),
    (call('resolve_request', {'object_id': 'keys-a', 'intent': 'delete', 'reason': 'x'}), 'INVALID_TOOL_ARGUMENTS'),
    (call('resolve_request', {'object_id': 'invented', 'intent': 'find', 'reason': 'x'}), 'TOOL_STATE_OR_ARGUMENT_REJECTED'),
    (call('inspect_location', {'location_id': 'entry-tray', 'reason': '还未解析'}), 'INVALID_TOOL_ARGUMENTS'),
    (call('finish_search', {'reason': '还未解析'}), 'INVALID_TOOL_ARGUMENTS'),
    (call('clarify_request', {'intent': 'find', 'candidate_ids': ['keys-a', 'keys-a'], 'question': '重复'}), 'TOOL_STATE_OR_ARGUMENT_REJECTED'),
    (call('clarify_request', {'intent': 'find', 'candidate_ids': ['keys-a', 'invented'], 'question': '虚构'}), 'TOOL_STATE_OR_ARGUMENT_REJECTED'),
])
def test_invalid_model_protocol_cannot_observe_or_write(tmp_path, response, code):
    home, service, engine, _ = create(tmp_path, [response])
    register(home, service)
    run = complete(service)
    assert run['state'] == 'ERROR' and guards(run) == [code]
    assert run['observations'] == [] and run['candidate'] is None
    assert not engine.calls and not history(home) and evidence_count(service) == 0


def test_multiple_tool_calls_are_rejected_together(tmp_path):
    response = call('unknown_object', {'reason': 'x'})
    response.tool_calls.append({'name': 'decline_request', 'args': {'reason': 'y'}, 'id': 'second'})
    home, service, engine, _ = create(tmp_path, [response])
    register(home, service)
    run = complete(service)
    assert guards(run) == ['EXACTLY_ONE_TOOL_REQUIRED'] and run['tool_calls'] == 0
    assert not history(home) and not engine.calls


def test_model_prose_cannot_override_tool_or_core_result(tmp_path):
    final = call('finish_search', {'reason': '证据不足'}, content='FOUND! 在书房，框是 [1,2,3,4]')
    home, service, engine, _ = create(tmp_path, [resolve(), final])
    register(home, service)
    run = complete(service)
    assert run['state'] == 'UNKNOWN' and run['candidate'] is None
    assert run['visited'] == [] and 'FOUND!' not in json.dumps(run, ensure_ascii=False)
    assert not history(home) and not engine.calls


@pytest.mark.parametrize('location,repeat', [('made-up', False), ('entry-tray', True)])
def test_illegal_and_repeated_locations_never_bypass_guard(tmp_path, location, repeat):
    responses = [resolve()] + ([inspect('entry-tray')] if repeat else []) + [inspect(location)]
    home, service, engine, _ = create(tmp_path, responses)
    register(home, service)
    service.scene('entry-tray', upload(service, 2)['asset_id'])
    run = complete(service)
    assert run['state'] == 'ERROR' and guards(run) == ['TOOL_STATE_OR_ARGUMENT_REJECTED']
    assert len(engine.calls) == int(repeat) and evidence_count(service) == int(repeat)
    assert not history(home)


def test_api_failure_is_visible_and_retry_keeps_budget_without_rules_fallback(tmp_path):
    secret = 'unit-test-secret-not-a-real-key'
    home, service, engine, model = create(tmp_path, [RuntimeError('provider ' + secret), resolve('history')])
    register(home, service)
    first = complete(service)
    assert first['state'] == 'MODEL_UNAVAILABLE' and first['model_calls'] == 1
    assert first['budget_tokens_used'] > 0 and first['visited'] == []
    assert secret not in json.dumps(first)
    service.act(first['run_id'], first['version'], 'retry')
    second = service.wait(first['run_id'])
    assert second['state'] == 'COMPLETED' and second['model_calls'] == 2
    assert second['budget_tokens_used'] >= first['budget_tokens_used']
    assert len(model.contexts) == 2 and not engine.calls


def test_cancellation_discards_inflight_model_response(tmp_path):
    started, release = Event(), Event()

    def blocked(context):
        started.set()
        assert release.wait(5)
        return resolve()

    home, service, engine, _ = create(tmp_path, [blocked])
    register(home, service)
    first = service.start('请找蓝钥匙')
    try:
        assert started.wait(5)
        current = service.get(first['run_id'])
        cancelled = service.act(current['run_id'], current['version'], 'cancel')
        assert cancelled['state'] == 'CANCELLED'
    finally:
        release.set()
    for worker in list(service._workers.values()):
        worker.join(5)
    result = service.get(first['run_id'])
    assert result == cancelled and result['selected_object'] is None
    assert result['tool_calls'] == 0 and not engine.calls and not history(home)


@pytest.mark.parametrize('limits,expected_calls,expected_observations', [
    ({'max_model_calls': 1}, 1, 0), ({'max_tool_calls': 1}, 1, 0),
    ({'max_viewpoints': 1}, 3, 1), ({'max_total_tokens': 256}, 0, 0),
])
def test_durable_model_tool_viewpoint_token_budgets(tmp_path, limits, expected_calls, expected_observations):
    home, service, engine, model = create(tmp_path,
        [resolve(), inspect('entry-tray'), inspect('study-desk')], **limits)
    register(home, service)
    service.scene('entry-tray', upload(service, 2)['asset_id'])
    run = complete(service)
    assert run['state'] == 'BUDGET_EXCEEDED'
    assert len(model.contexts) == expected_calls and len(run['observations']) == expected_observations
    assert not history(home)


def test_restart_retains_reserved_interrupted_call_and_cannot_reset_budget(tmp_path, monkeypatch):
    home, first, engine, _ = create(tmp_path, [], max_model_calls=1)
    register(home, first)
    monkeypatch.setattr(first, '_launch', lambda run_id: None)
    run = first.start('请找钥匙')
    with closing(first._connect()) as db, db:
        private = first._load(db, run['run_id'])
        private['model_calls'] = 1
        private['budget_tokens_used'] = 9000
        private['agent_internal']['active_seconds'] = 3
        private['agent_internal']['pending_call'] = {'id': 'interrupted', 'reserved_tokens': 9000, 'reserved_seconds': 3}
        first._save(db, private)
    model = ScriptedModel([resolve()])
    restarted = PhotoAgentService(HouseholdService(home.workspace), agent_config=first.agent_config,
                                 model=model, engine_factory=engine)
    pending = restarted.get(run['run_id'])
    restarted.act(run['run_id'], pending['version'], 'retry')
    result = restarted.wait(run['run_id'])
    assert result['state'] == 'BUDGET_EXCEEDED' and result['model_calls'] == 1
    assert result['budget_tokens_used'] == 9000 and not model.contexts and not engine.calls
    assert any(row['tool'] == 'interrupted_model_call' for row in result['trace'])


def test_rule_and_llm_runs_cannot_resume_in_wrong_mode(tmp_path):
    home, llm, engine, _ = create(tmp_path, [resolve('remember')])
    register(home, llm)
    rules = PhotoFlowService(home, engine_factory=engine, use_graph=False)
    model_run = complete(llm, '记一下这串钥匙', 'entry-tray')
    rule_run = rules.start('记住蓝钥匙', 'entry-tray')
    with pytest.raises(ValueError, match='LLM'):
        rules.act(model_run['run_id'], model_run['version'], 'confirm_memory')
    with pytest.raises(ValueError, match='规则'):
        llm.act(rule_run['run_id'], rule_run['version'], 'confirm_memory')
    assert not history(home)


def test_unavailable_configuration_never_executes_rule_search(tmp_path, monkeypatch):
    def unavailable(_):
        raise AgentConfigError('MODEL_UNAVAILABLE', 'offline injected failure')
    monkeypatch.setattr(agent_module, 'load_agent_config', unavailable)
    household = HouseholdService(tmp_path / 'home')
    engine = ScriptedEngine({'entry-tray': 'candidate'})
    service = PhotoAgentService(household, model=ScriptedModel([]), engine_factory=engine)
    register(household, service)
    run = service.start('帮我找蓝钥匙')
    assert run['state'] == 'MODEL_UNAVAILABLE' and run['mode'] == 'llm_langgraph'
    assert run['visited'] == [] and not engine.calls and not history(household)


def test_llm_context_excludes_raw_images_paths_hashes_and_secrets(tmp_path):
    secret = 'unit-test-secret-not-a-real-key'
    reason = secret + ' C:\\private\\image.png https://private.invalid/path ' + 'a' * 64
    home, service, _, model = create(tmp_path, [resolve(), inspect('study-desk'),
        call('finish_search', {'reason': reason})])
    reference = register(home, service)
    scene = upload(service, 2)
    service.scene('study-desk', scene['asset_id'])
    remember(home, 'study-desk', '2026-10-27T09:00:00+08:00', 'private-owner-event')
    run = complete(service, '请找钥匙 ' + reason)
    assert run['state'] == 'UNKNOWN'
    serialized = json.dumps(model.contexts, ensure_ascii=False)
    for forbidden in (secret, 'C:\\private', 'private.invalid', 'a' * 64, reference['sha256'],
                      scene['sha256'], 'image_path', 'image_sha256', 'base64', str(tmp_path)):
        assert forbidden not in serialized
    assert 'source' not in model.contexts[1]['history'][0]
    assert '[redacted]' in model.contexts[0]['user_request']
    assert secret not in run['llm_explanation'] and 'private.invalid' not in run['llm_explanation']
    assert 'agent_internal' not in run and 'snapshot' not in run
