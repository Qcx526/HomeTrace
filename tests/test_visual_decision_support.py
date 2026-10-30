"""Offline decision-feedback checks, not real LLM or household-vision evidence.

All images are generated software fixtures. Model and visual-advisor outputs are
explicit doubles; the tool loop, evidence transactions and memory guard are real.
No test reads private photographs, labels, credentials or contacts an API.
"""
from contextlib import closing
from copy import deepcopy
import json

import pytest

pytest.importorskip('langgraph')
pytest.importorskip('langchain_core')
pytest.importorskip('PIL.Image')

from hometrace.visual_photo_agent_service import VisualPhotoAgentService
from test_photo_agent_service import inspect, resolve, stop
from test_photo_flow_service import evidence_count, history, register, upload
from test_visual_photo_agent_service import Advisor, advice, consent, create, initial, tool


@pytest.fixture(autouse=True)
def prohibit_real_visual_api(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('Decision regression attempted an external image request')
    monkeypatch.setattr('hometrace.visual_advisor_client.call_advisor', forbidden)


def observed_run():
    return {
        'observations': [{'status': 'UNKNOWN', 'bbox': None}],
        'visual_advice': [],
        'visited': ['study-desk'],
        'snapshot': {'scenes': {'study-desk': {'asset_id': 'fixture-asset'}}},
        'agent_internal': {'review_rejected': []},
    }


def completed_advice(index=0, appearance='similar'):
    return {'observation_index': index, 'execution_status': 'completed',
            'advice': advice(appearance)['advice']}


def test_new_observation_does_not_inherit_previous_similar_feedback():
    run = observed_run()
    run['visual_advice'].append(completed_advice())
    assert VisualPhotoAgentService._decision_support(run)['owner_review_available'] is True
    run['observations'].append({'status': 'UNKNOWN', 'bbox': None})
    actual = VisualPhotoAgentService._decision_support(run)
    assert actual['observation_ref'] == 'E2'
    assert actual['latest_advisor_status'] == 'not_requested_or_pending'
    assert actual['appearance'] is actual['advisor_next_action'] is None
    assert actual['quality_flags'] == []
    assert actual['owner_review_available'] is False


@pytest.mark.parametrize('status', ['failed', 'discarded'])
def test_latest_failed_or_discarded_feedback_does_not_reuse_old_advice(status):
    run = observed_run()
    run['visual_advice'] = [completed_advice(),
                            {'observation_index': 0, 'execution_status': status}]
    actual = VisualPhotoAgentService._decision_support(run)
    assert actual['latest_advisor_status'] == status
    assert actual['appearance'] is actual['advisor_next_action'] is None
    assert actual['quality_flags'] == []
    # Earlier valid evidence remains separate from the latest feedback status.
    # This fixture is a resilience check, not permission to resend an image.


def test_similar_without_local_box_supports_review_but_owner_rejection_revokes_it():
    run = observed_run()
    run['visual_advice'] = [completed_advice()]
    actual = VisualPhotoAgentService._decision_support(run)
    assert actual['appearance'] == 'similar'
    assert actual['advisor_next_action'] == 'ask_owner_review'
    assert actual['local_bbox_available'] is False
    assert actual['owner_review_available'] is True
    run['agent_internal']['review_rejected'].append(0)
    rejected = VisualPhotoAgentService._decision_support(run)
    assert rejected['appearance'] == 'similar'
    assert rejected['owner_review_available'] is False


def test_only_known_unvisited_locations_in_run_snapshot_are_listed():
    run = observed_run()
    run['snapshot']['scenes'].update({
        'living-table': {'asset_id': 'fixture-second'},
        'not-a-registered-location': {'asset_id': 'fixture-invalid'},
    })
    run['planned_locations'] = [{'location_id': 'entry-tray'}]
    actual = VisualPhotoAgentService._decision_support(run)
    assert actual['unvisited_uploaded_locations'] == ['living-table']
    run['visited'].append('living-table')
    assert VisualPhotoAgentService._decision_support(run)['unvisited_uploaded_locations'] == []


def test_before_observation_feedback_has_no_false_review_or_appearance():
    run = observed_run()
    run['observations'] = []
    run['visited'] = []
    actual = VisualPhotoAgentService._decision_support(run)
    assert actual['observation_ref'] is actual['appearance'] is None
    assert actual['owner_review_available'] is False
    assert actual['local_bbox_available'] is False
    assert actual['unvisited_uploaded_locations'] == ['study-desk']


def test_context_uses_snapshot_and_excludes_private_asset_metadata(tmp_path):
    _, service, _, _, _, run, reference, scene = initial(tmp_path)
    # A later workspace upload is not part of this run's frozen scene snapshot.
    service.scene('living-table', upload(service, 3)['asset_id'])
    with closing(service._connect()) as db:
        internal = service._load(db, run['run_id'])
    private_path = 'C:/private-test-only/household-secret-photo.png'
    ground_truth = 'private-ground-truth-fixture-never-for-model'
    internal['observations'][0].update(source_path=private_path, ground_truth=ground_truth)
    internal['snapshot']['reference']['source_path'] = private_path
    internal['snapshot']['scenes']['study-desk']['ground_truth'] = ground_truth
    before = deepcopy(internal)
    context = service._context(internal)
    assert internal == before
    assert context['decision_support']['unvisited_uploaded_locations'] == []
    assert not next(row for row in context['locations']
                    if row['location_id'] == 'living-table')['has_uploaded_image']
    serialized = json.dumps(context, ensure_ascii=False)
    for confidential in (private_path, ground_truth, reference['sha256'], scene['sha256'],
                         reference['asset_id'], scene['asset_id'],
                         run['vision_request']['request_id']):
        assert confidential not in serialized
    support = json.dumps(context['decision_support'])
    assert 'ground_truth' not in support and 'sha256' not in support and 'source_path' not in support
    assert context['automatic_found_enabled'] is False


@pytest.mark.parametrize('appearance', ['not_visible', 'different'])
@pytest.mark.parametrize('next_choice', ['finish', 'other_location'])
def test_negative_feedback_allows_model_to_choose_finish_or_next_location(tmp_path, appearance, next_choice):
    def after_advice(context):
        support = context['decision_support']
        assert support['appearance'] == appearance
        assert support['owner_review_available'] is False
        assert 'request_owner_review' not in context['allowed_tools']
        # Guidance does not remove the model's ability to request a useful view.
        assert 'request_new_photo' in context['allowed_tools']
        assert 'finish_search' in context['allowed_tools']
        expected = ['living-table'] if next_choice == 'other_location' else []
        assert support['unvisited_uploaded_locations'] == expected
        return inspect('living-table') if expected else stop()

    def after_second_observation(context):
        assert context['decision_support']['observation_ref'] == 'E2'
        assert context['decision_support']['appearance'] is None
        assert context['decision_support']['unvisited_uploaded_locations'] == []
        return stop()

    responses = [resolve(), inspect('study-desk'), tool('visual_advice'), after_advice]
    if next_choice == 'other_location':
        responses.append(after_second_observation)
    home, service, engine, model, advisor = create(tmp_path, responses, Advisor(advice(appearance)))
    register(home, service)
    service.scene('study-desk', upload(service, 2)['asset_id'])
    if next_choice == 'other_location':
        service.scene('living-table', upload(service, 3)['asset_id'])
    pending = service.wait(service.start('请找蓝钥匙')['run_id'])
    assert pending['state'] == 'AWAITING_IMAGE_CONSENT' and not advisor.calls
    consent(service, pending)
    final = service.wait(pending['run_id'])
    expected_locations = ['study-desk', 'living-table'] if next_choice == 'other_location' else ['study-desk']
    assert final['state'] == 'UNKNOWN' and final['candidate'] is None
    assert final['visited'] == [row[0] for row in engine.calls] == expected_locations
    assert evidence_count(service) == len(expected_locations)
    assert len(model.contexts) == len(responses) and len(advisor.calls) == 1
    assert final['new_photo_count'] == 0 and not history(home)
    assert all(not report['confirmed_evidence_ids'] for report in final['core_reports'])


def test_model_can_still_request_informative_photo_after_negative_advice(tmp_path):
    def choose_new_photo(context):
        assert context['decision_support']['appearance'] == 'not_visible'
        assert context['decision_support']['unvisited_uploaded_locations'] == []
        return tool('request_new_photo', '主人明确要求检查被遮挡区域的新视角')

    home, service, _, model, advisor, pending, _, _ = initial(
        tmp_path, [choose_new_photo], advisor=Advisor(advice('not_visible')))
    consent(service, pending)
    final = service.wait(pending['run_id'])
    assert final['state'] == 'AWAITING_NEW_PHOTO'
    assert final['photo_request']['location_id'] == 'study-desk'
    assert len(model.contexts) == 4 and len(advisor.calls) == 1
    assert not history(home) and final['candidate'] is None


def test_model_selects_owner_review_for_similar_full_frame_without_box(tmp_path):
    def choose_review(context):
        support = context['decision_support']
        assert support['appearance'] == 'similar'
        assert support['owner_review_available'] is True
        assert support['local_bbox_available'] is False
        assert 'request_new_photo' in context['allowed_tools']
        return tool('request_owner_review')

    home, service, _, model, advisor, pending, _, _ = initial(tmp_path, [choose_review])
    consent(service, pending)
    review = service.wait(pending['run_id'])
    assert review['state'] == 'AWAITING_REVIEW'
    assert review['candidate']['bbox'] is None
    assert review['candidate']['kind'] == 'visual_advisor'
    assert review['candidate']['identity_confirmed'] is False
    assert review['new_photo_count'] == 0 and not history(home)
    assert len(model.contexts) == 4 and len(advisor.calls) == 1
    assert all(not report['confirmed_evidence_ids'] for report in review['core_reports'])
