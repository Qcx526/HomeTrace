"""Offline visual-loop regressions; fixtures are not household vision evidence.

The model, advisor and detector are explicit doubles. LangGraph tool calls,
image decoding, hashing, SearchCore, consent transactions and SQLite are real.
These checks neither read .env nor contact any model provider.
"""
from contextlib import closing
from copy import deepcopy
from dataclasses import replace
from io import BytesIO
import json
from threading import Event

import pytest

pytest.importorskip('langgraph')
pytest.importorskip('langchain_core')
Image = pytest.importorskip('PIL.Image')

from hometrace.household_service import HouseholdConflict, HouseholdService
from hometrace.photo_agent_service import PhotoAgentService
from hometrace.photo_flow_service import PhotoFlowService
from hometrace.visual_advisor import validate_advice
from hometrace.visual_photo_agent_service import VisualPhotoAgentService, VISION_RESERVATION
from test_photo_agent_service import ScriptedModel, call, config, guards, inspect, resolve, stop
from test_photo_flow_service import ScriptedEngine, evidence_count, fixture_bytes, history, register, upload


@pytest.fixture(autouse=True)
def no_real_advisor(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('Offline test attempted a real advisor request')
    monkeypatch.setattr('hometrace.visual_advisor_client.call_advisor', forbidden)


def advice(appearance='similar', *, total_tokens=300, reason='测试外观描述，不确认身份'):
    action = 'ask_owner_review' if appearance == 'similar' else 'request_side_view'
    value = {'appearance': appearance, 'quality_flags': [], 'next_action': action,
             'visible_features': ['测试图案'], 'reason': reason}
    return {'advice': validate_advice(json.dumps(value)),
            'usage': {'input_tokens': total_tokens - 10, 'output_tokens': 10, 'total_tokens': total_tokens},
            'elapsed_ms': 1.25, 'model': 'explicit-offline-advisor-double'}


class Advisor:
    def __init__(self, *responses):
        self.responses = iter(responses or [advice()])
        self.calls = []

    def __call__(self, agent_config, packet):
        self.calls.append(deepcopy(packet))
        response = next(self.responses)
        if callable(response):
            response = response(packet)
        if isinstance(response, Exception):
            raise response
        return response


def tool(name, reason='依据实际反馈选择下一步'):
    return call(name, {'reason': reason})


def create(tmp_path, responses, advisor=None, outcomes=None):
    home = HouseholdService(tmp_path / 'home')
    engine, model = ScriptedEngine(outcomes), ScriptedModel(responses)
    advisor = advisor or Advisor()
    service = VisualPhotoAgentService(home, agent_config=config(tmp_path), model=model,
                                      engine_factory=engine, advisor_client=advisor)
    assert service.config()['model_available'] is True
    return home, service, engine, model, advisor


def initial(tmp_path, after=(), *, advisor=None, outcomes=None):
    values = create(tmp_path, [resolve(), inspect('study-desk'), tool('visual_advice'), *after],
                    advisor, outcomes)
    home, service, _, _, _ = values
    reference = register(home, service)
    scene = upload(service, 2)
    service.scene('study-desk', scene['asset_id'])
    run = service.wait(service.start('请找蓝钥匙')['run_id'])
    assert run['state'] == 'AWAITING_IMAGE_CONSENT'
    return (*values, run, reference, scene)


def consent(service, run, action='approve_vision'):
    return service.act(run['run_id'], run['version'], action,
                       request_id=run['vision_request']['request_id'])


def mutate(service, run_id, change):
    """Create precise crash/budget conditions without calling any model."""
    with closing(service._connect()) as db, db:
        run = service._load(db, run_id)
        change(run)
        service._save(db, run)
    return service.get(run_id)


def restart(home, service, engine, responses, advisor):
    return VisualPhotoAgentService(HouseholdService(home.workspace), agent_config=service.agent_config,
                                  model=ScriptedModel(responses), engine_factory=engine, advisor_client=advisor)


def test_without_current_approval_no_images_leave_and_request_binds_content(tmp_path):
    home, service, _, model, advisor, run, reference, scene = initial(tmp_path)
    assert not advisor.calls and run['images_sent_to_advisor'] is False
    assert run['vision_calls'] == run['vision_tokens_used'] == 0
    request = run['vision_request']
    assert request['status'] == 'awaiting_consent'
    assert request['reference_sha256'] == reference['sha256']
    assert request['scene_sha256'] == scene['sha256']
    assert request['endpoint'] == 'https://provider.invalid/v1'
    assert request['reference']['roi'] == [0, 0, 64, 64]
    assert run['observations'][0]['bbox'] is None and not history(home)
    assert 'visual_advice' in model.contexts[-1]['allowed_tools']
    assert evidence_count(service) == 1


def test_approval_requires_current_request_id_and_version(tmp_path):
    _, service, _, _, advisor, run, _, _ = initial(tmp_path)
    with pytest.raises(HouseholdConflict):
        service.act(run['run_id'], run['version'] - 1, 'approve_vision', request_id=run['vision_request']['request_id'])
    with pytest.raises(ValueError):
        service.act(run['run_id'], run['version'], 'approve_vision', request_id='unrelated-request')
    with pytest.raises(ValueError):
        service.act(run['run_id'], run['version'], 'approve_vision')
    with pytest.raises(ValueError):
        service.act(run['run_id'], run['version'], 'approve_vision', object_id='keys-a', request_id=run['vision_request']['request_id'])
    assert service.get(run['run_id']) == run and not advisor.calls


def test_denial_returns_feedback_to_llm_without_sending_or_retrying(tmp_path):
    def after_denied(context):
        assert context['last_tool_result']['outcome'] == 'denied'
        assert 'visual_advice' not in context['allowed_tools']
        return stop()
    home, service, _, model, advisor, run, _, _ = initial(tmp_path, [after_denied])
    consent(service, run, 'deny_vision')
    final = service.wait(run['run_id'])
    assert final['state'] == 'UNKNOWN' and not advisor.calls and not history(home)
    assert final['vision_request']['status'] == 'denied' and final['vision_calls'] == 0
    assert len(model.contexts) == 4


def test_similar_without_bbox_requires_llm_review_then_explicit_owner_memory(tmp_path):
    def after_advice(context):
        result = context['last_tool_result']
        assert result['tool'] == 'visual_advice'
        assert result['advice']['model_advice']['appearance'] == 'similar'
        assert result['advice']['production_status'] == 'UNKNOWN'
        return tool('request_owner_review')
    home, service, _, model, advisor, run, _, scene = initial(tmp_path, [after_advice])
    consent(service, run)
    review = service.wait(run['run_id'])
    assert review['state'] == 'AWAITING_REVIEW' and review['candidate']['bbox'] is None
    assert review['candidate']['kind'] == 'visual_advisor' and review['candidate']['status'] == 'UNKNOWN'
    assert not history(home) and len(advisor.calls) == 1 and len(model.contexts) == 4
    assert review['vision_tokens_used'] == review['vision_actual_tokens'] == 300
    for key in ('reference_jpeg', 'scene_jpeg'):
        with Image.open(BytesIO(advisor.calls[0][key])) as image:
            assert image.format == 'JPEG' and max(image.size) <= 1280 and not image.getexif()
    confirmed = service.act(review['run_id'], review['version'], 'accept_candidate')
    assert confirmed['state'] == 'USER_CONFIRMED' and confirmed['visual_confirmed'] is False
    assert history(home)[0]['source_kind'] == 'owner_reported'
    assert history(home)[0]['source'].startswith('visual_advisor_owner_review:')
    assert history(home)[0]['source'].endswith(scene['sha256'])
    assert all(not report['confirmed_evidence_ids'] for report in confirmed['core_reports'])


def test_similar_advice_does_not_automatically_request_review(tmp_path):
    home, service, _, _, _, run, _, _ = initial(tmp_path, [stop()])
    consent(service, run)
    final = service.wait(run['run_id'])
    assert final['state'] == 'UNKNOWN' and final['candidate'] is None and not history(home)


def test_uncertain_reobserve_same_run_requires_fresh_consent_then_owner_confirmation(tmp_path):
    advisor = Advisor(advice('uncertain'), advice())
    def after_uncertain(context):
        assert context['visual_advice'][-1]['advice']['model_advice']['appearance'] == 'uncertain'
        assert 'request_owner_review' not in context['allowed_tools']
        return tool('request_new_photo', '请换角度补拍')
    def after_new_observation(context):
        assert len(context['observations']) == 2 and context['visited'] == ['study-desk']
        assert context['last_tool_result']['tool'] == 'inspect_location'
        assert context['last_tool_result']['observation_index'] == 1
        return tool('visual_advice')
    home, service, engine, model, _, run, _, old_scene = initial(tmp_path,
        [after_uncertain, after_new_observation, tool('request_owner_review')], advisor=advisor)
    consent(service, run)
    waiting = service.wait(run['run_id'])
    assert waiting['state'] == 'AWAITING_NEW_PHOTO' and len(advisor.calls) == 1
    new_scene = upload(service, 3)
    service.submit_new_photo(run['run_id'], waiting['version'], new_scene['asset_id'])
    second = service.wait(run['run_id'])
    assert second['state'] == 'AWAITING_IMAGE_CONSENT' and len(advisor.calls) == 1
    assert second['run_id'] == run['run_id'] and second['new_photo_count'] == 1
    assert second['vision_request']['request_id'] != run['vision_request']['request_id']
    assert second['vision_request']['scene_sha256'] == new_scene['sha256']
    assert [row['asset_id'] for row in second['observations']] == [old_scene['asset_id'], new_scene['asset_id']]
    assert [x[0] for x in engine.calls] == ['study-desk', 'study-desk'] and evidence_count(service) == 2
    assert second['core_reports'][1]['result_status'] == 'UNKNOWN'
    with pytest.raises(ValueError):
        service.act(run['run_id'], second['version'], 'approve_vision', request_id=run['vision_request']['request_id'])
    consent(service, second)
    review = service.wait(run['run_id'])
    assert review['state'] == 'AWAITING_REVIEW' and len(advisor.calls) == 2 and len(model.contexts) == 6
    assert review['candidate']['asset_id'] == new_scene['asset_id']
    assert not history(home)


@pytest.mark.parametrize('invalid', ['reference', 'old_scene', 'wrong_source'])
def test_new_photo_rejects_replay_and_mixed_provenance(tmp_path, invalid):
    home, service, _, _, advisor, run, reference, scene = initial(tmp_path, [tool('request_new_photo')],
                                                                advisor=Advisor(advice('uncertain')))
    consent(service, run)
    waiting = service.wait(run['run_id'])
    bad = {'reference': reference, 'old_scene': scene}.get(invalid)
    if bad is None:
        bad = upload(service, 3, 'real_upload')
    with pytest.raises(ValueError, match='新图|来源一致'):
        service.submit_new_photo(run['run_id'], waiting['version'], bad['asset_id'])
    assert service.get(run['run_id']) == waiting and len(advisor.calls) == 1 and not history(home)


@pytest.mark.parametrize('issue', ['reference_replay', 'wrong_source', 'missing_scene'])
def test_invalid_observations_cannot_be_sent_to_advisor(tmp_path, issue):
    home, service, engine, _, advisor = create(tmp_path, [resolve(), inspect('study-desk'), tool('visual_advice')])
    reference = register(home, service)
    if issue != 'missing_scene':
        scene = reference if issue == 'reference_replay' else upload(service, 2, 'real_upload')
        service.scene('study-desk', scene['asset_id'])
    run = service.wait(service.start('找钥匙')['run_id'])
    assert run['state'] == 'ERROR' and guards(run) == ['INVALID_TOOL_ARGUMENTS']
    assert not advisor.calls and not engine.calls and not history(home)


@pytest.mark.parametrize('change', ['scene_bytes', 'destination', 'derivative_hash'])
def test_approved_packet_rechecks_hashes_and_destination_before_send(tmp_path, monkeypatch, change):
    home, service, _, _, advisor, run, _, scene = initial(tmp_path, [stop()])
    monkeypatch.setattr(service, '_launch', lambda _: None)
    consent(service, run)
    if change == 'scene_bytes':
        (service.assets_dir / f"{scene['asset_id']}.png").write_bytes(fixture_bytes(99))
    elif change == 'destination':
        service.agent_config = replace(service.agent_config, llm=replace(service.agent_config.llm, base_url='https://other.invalid/v1'))
    else:
        mutate(service, run['run_id'], lambda r: r['vision_request'].update(scene_derivative_sha256='changed'))
    assert service._consume_advisor(run['run_id']) is True
    result = service.get(run['run_id'])
    assert result['visual_advice'][-1]['error_code'] == 'CONSENT_BINDING_INVALID'
    assert result['vision_tokens_used'] == VISION_RESERVATION and not advisor.calls and not history(home)


def test_restart_preserves_waiting_consent_and_only_owner_can_resume(tmp_path):
    home, first, engine, _, advisor, waiting, _, _ = initial(tmp_path)
    second = restart(home, first, engine, [stop()], advisor)
    assert second.get(waiting['run_id']) == waiting and not advisor.calls
    consent(second, waiting)
    final = second.wait(waiting['run_id'])
    assert final['state'] == 'UNKNOWN' and len(advisor.calls) == 1


def test_restart_does_not_retry_already_sending_request_or_reset_reservation(tmp_path, monkeypatch):
    home, first, engine, _, advisor, waiting, _, _ = initial(tmp_path)
    monkeypatch.setattr(first, '_launch', lambda _: None)
    consent(first, waiting)
    def interrupted(run):
        run['agent_internal']['vision_pending']['stage'] = 'sending'
        run['vision_request']['status'] = 'sending'
        run['images_sent_to_advisor'] = True
    persisted = mutate(first, waiting['run_id'], interrupted)
    second = restart(home, first, engine, [stop()], advisor)
    second.act(persisted['run_id'], persisted['version'], 'retry')
    final = second.wait(persisted['run_id'])
    assert final['state'] == 'UNKNOWN' and not advisor.calls
    assert final['vision_calls'] == 1 and final['vision_tokens_used'] == VISION_RESERVATION
    assert final['visual_advice'][0]['error_code'] == 'INTERRUPTED_REQUEST_NOT_RETRIED'


def test_cancel_discards_late_visual_response_and_never_writes_memory(tmp_path):
    started, release = Event(), Event()
    def blocked(packet):
        started.set()
        assert release.wait(5)
        return advice(total_tokens=12000)
    home, service, _, _, advisor, waiting, _, _ = initial(tmp_path, advisor=Advisor(blocked))
    consent(service, waiting)
    try:
        assert started.wait(5)
        current = service.get(waiting['run_id'])
        cancelled = service.act(current['run_id'], current['version'], 'cancel')
        assert cancelled['state'] == 'CANCELLED'
    finally:
        release.set()
    for worker in list(service._workers.values()):
        worker.join(5)
    final = service.get(waiting['run_id'])
    assert final['state'] == cancelled['state'] == 'CANCELLED' and final['candidate'] is None
    assert final['reply'] == cancelled['reply'] and not history(home)
    assert final['visual_advice'][0]['execution_status'] == 'discarded'
    assert 'advice' not in final['visual_advice'][0]
    assert final['vision_request']['status'] == 'discarded'
    assert len(advisor.calls) == 1 and final['vision_tokens_used'] == final['vision_actual_tokens'] == 12000
    with closing(service._connect()) as db:
        private = service._load(db, final['run_id'])
    assert 'vision_pending' not in private['agent_internal']
    before = private['vision_tokens_used']
    assert service._settle_advisor_usage(private, waiting['vision_request']['request_id'], 12000, failed=True) is False
    assert private['vision_tokens_used'] == before


@pytest.mark.parametrize('budget', ['calls', 'tokens'])
def test_approval_checks_durable_visual_budget(tmp_path, budget):
    _, service, _, _, advisor, run, _, _ = initial(tmp_path)
    field, value = ('vision_calls', 3) if budget == 'calls' else ('vision_tokens_used', 24000 - VISION_RESERVATION + 1)
    pending = mutate(service, run['run_id'], lambda r: r.update({field: value}))
    with pytest.raises(ValueError, match='预算不足'):
        consent(service, pending)
    assert service.get(run['run_id']) == pending and not advisor.calls


def test_actual_usage_overflow_stops_before_another_model_decision(tmp_path):
    home, service, _, model, advisor, run, _, _ = initial(tmp_path, advisor=Advisor(advice(total_tokens=24001)))
    consent(service, run)
    final = service.wait(run['run_id'])
    assert final['state'] == 'BUDGET_EXCEEDED' and final['vision_tokens_used'] == 24001
    assert len(model.contexts) == 3 and len(advisor.calls) == 1 and not history(home)
    row = final['visual_advice'][0]
    assert row['requested_model'] == 'scripted-offline-test'
    assert row['returned_model'] == 'explicit-offline-advisor-double'


@pytest.mark.parametrize('invalid', ['extra_found', 'invalid_usage', 'bad_elapsed', 'exception', 'contradiction'])
def test_advisor_errors_are_safe_feedback_not_confirmation_or_silent_retry(tmp_path, invalid):
    response = advice()
    if invalid == 'extra_found':
        response['advice']['model_advice']['FOUND'] = True
    elif invalid == 'invalid_usage':
        response['usage']['total_tokens'] = True
    elif invalid == 'bad_elapsed':
        response['elapsed_ms'] = float('nan')
    elif invalid == 'contradiction':
        response['advice']['model_advice']['appearance'] = 'not_visible'
    else:
        response = RuntimeError('unit-test-secret-not-a-real-key https://private.invalid/error')
    def after_error(context):
        assert context['last_tool_result']['execution_status'] == 'failed'
        assert 'request_owner_review' not in context['allowed_tools']
        return stop()
    home, service, _, _, advisor, run, _, _ = initial(tmp_path, [after_error], advisor=Advisor(response))
    consent(service, run)
    final = service.wait(run['run_id'])
    assert final['state'] == 'UNKNOWN' and final['candidate'] is None and not history(home)
    assert final['visual_advice'][0]['error_code'] == 'ADVISOR_CALL_OR_RESPONSE_INVALID'
    assert len(advisor.calls) == 1 and final['vision_tokens_used'] == VISION_RESERVATION
    assert 'unit-test-secret-not-a-real-key' not in json.dumps(final)


def test_advisor_text_is_redacted_and_does_not_override_authoritative_state(tmp_path):
    secret = 'unit-test-secret-not-a-real-key'
    text = secret + ' https://private.invalid/path C:\\private\\image.png ' + 'a' * 64
    response = advice(reason=text)
    response['advice']['model_advice']['visible_features'] = [secret + ' https://private.invalid/']
    home, service, _, model, _, run, reference, scene = initial(tmp_path, [stop()], advisor=Advisor(response))
    consent(service, run)
    final = service.wait(run['run_id'])
    assert final['state'] == 'UNKNOWN' and not history(home)
    context = json.dumps(model.contexts, ensure_ascii=False)
    for forbidden in (secret, 'private.invalid', 'C:\\private', 'a' * 64, reference['sha256'],
                      scene['sha256'], 'data:image', 'base64', str(tmp_path)):
        assert forbidden not in context
    assert secret not in json.dumps(final) and '[redacted]' in context


@pytest.mark.parametrize('known_tokens,via_exception', [(300, False), (12000, False), (24001, False), (12000, True)])
def test_invalid_advice_still_charges_known_usage_without_releasing_failure_reservation(tmp_path, known_tokens, via_exception):
    if via_exception:
        class KnownUsageError(ValueError):
            usage = {'input_tokens': known_tokens - 10, 'output_tokens': 10, 'total_tokens': known_tokens}
        response = KnownUsageError('Malformed JSON; explicit offline double')
    else:
        response = advice(total_tokens=known_tokens)
        response['advice']['model_advice']['appearance'] = 'FOUND'
    home, service, _, model, advisor, run, _, _ = initial(tmp_path, [stop()], advisor=Advisor(response))
    consent(service, run)
    final = service.wait(run['run_id'])
    assert final['vision_tokens_used'] == max(known_tokens, VISION_RESERVATION)
    assert final['vision_actual_tokens'] == known_tokens
    assert final['visual_advice'][0]['known_total_tokens'] == known_tokens
    assert final['visual_advice'][0]['execution_status'] == 'failed'
    assert final['state'] == ('BUDGET_EXCEEDED' if known_tokens > 24000 else 'UNKNOWN')
    assert len(model.contexts) == (3 if known_tokens > 24000 else 4)
    assert len(advisor.calls) == 1 and not history(home)


def test_owner_rejection_returns_to_llm_and_same_evidence_cannot_be_reviewed_twice(tmp_path):
    def rejected(context):
        assert context['last_tool_result']['tool'] == 'owner_reject_candidate'
        assert 'request_owner_review' not in context['allowed_tools']
        return stop()
    home, service, _, _, _, run, _, _ = initial(tmp_path, [tool('request_owner_review'), rejected])
    consent(service, run)
    review = service.wait(run['run_id'])
    service.act(review['run_id'], review['version'], 'reject_candidate')
    final = service.wait(run['run_id'])
    assert final['state'] == 'UNKNOWN' and final['candidate'] is None and not history(home)


def test_local_candidate_requires_model_decision_but_no_cloud_call(tmp_path):
    home, service, _, model, advisor = create(tmp_path,
        [resolve(), inspect('study-desk'), tool('request_owner_review')], outcomes={'study-desk': 'candidate'})
    register(home, service)
    service.scene('study-desk', upload(service, 2)['asset_id'])
    run = service.wait(service.start('请找钥匙')['run_id'])
    assert run['state'] == 'AWAITING_REVIEW' and run['candidate']['kind'] == 'local_matcher'
    assert run['candidate']['bbox'] == [8, 8, 48, 48] and len(model.contexts) == 3
    assert not advisor.calls and not history(home)
    assert all(x['max_tokens'] == 1024 for x in model.invocation_options)


def test_ordinary_services_cannot_resume_visual_runs(tmp_path):
    home, service, engine, _, advisor, waiting, _, _ = initial(tmp_path)
    ordinary = PhotoAgentService(home, agent_config=service.agent_config, model=ScriptedModel([]), engine_factory=engine)
    rules = PhotoFlowService(home, engine_factory=engine, use_graph=False)
    for wrong in (ordinary, rules):
        with pytest.raises(ValueError, match='模式|LLM'):
            wrong.act(waiting['run_id'], waiting['version'], 'cancel')
    assert service.get(waiting['run_id']) == waiting and not advisor.calls


def test_new_photo_limit_is_durable_and_not_a_model_suggestion(tmp_path):
    home, service, _, model, advisor, run, _, _ = initial(tmp_path, [tool('request_new_photo')],
                                                      advisor=Advisor(advice('uncertain')))
    consent(service, run)
    waiting = service.wait(run['run_id'])
    waiting = mutate(service, run['run_id'], lambda r: r.update(new_photo_count=2))
    fresh = upload(service, 4)
    with pytest.raises(ValueError, match='次数已耗尽'):
        service.submit_new_photo(run['run_id'], waiting['version'], fresh['asset_id'])
    assert service.get(run['run_id']) == waiting and len(advisor.calls) == 1 and not history(home)
