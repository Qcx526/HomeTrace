"""Trusted photo service boundaries used by model-selected tools (offline)."""
from contextlib import closing

import pytest

from test_photo_flow_service import create_service, register, upload, evidence_count


def pending(tmp_path):
    home, flow, engine = create_service(tmp_path)
    register(home, flow)
    for index, location in enumerate(('entry-tray','living-table','study-desk'), 2):
        flow.scene(location, upload(flow, index)['asset_id'])
    flow._launch = lambda run_id: None
    run = flow.start('帮我找蓝钥匙')
    return flow, engine, run


def test_explicit_model_choice_is_executed_instead_of_first_suggestion(tmp_path):
    flow, engine, run = pending(tmp_path)
    assert run['planned_locations'][0]['location_id']=='entry-tray'
    flow._step(run['run_id'], location_id='study-desk', reason='先检查书房', expected_version=run['version'])
    saved = flow.get(run['run_id'])
    assert saved['visited']==['study-desk']
    assert engine.calls[0][0]=='study-desk'
    assert saved['observations'][0]['identity_confirmed'] is False


def test_stale_model_decision_cannot_consume_evidence(tmp_path):
    flow, engine, run = pending(tmp_path)
    assert not flow._step(run['run_id'], location_id='study-desk', reason='旧请求', expected_version=run['version']-1)
    assert flow.get(run['run_id'])==run and evidence_count(flow)==0 and not engine.calls


def test_invalid_or_already_visited_model_choice_cannot_fall_through(tmp_path):
    flow, engine, run = pending(tmp_path)
    with pytest.raises(ValueError, match='尚未访问'):
        flow._step(run['run_id'], location_id='invented', reason='无效')
    assert not engine.calls
    flow._step(run['run_id'], location_id='study-desk', reason='检查')
    with pytest.raises(ValueError, match='尚未访问'):
        flow._step(run['run_id'], location_id='study-desk', reason='重复')
    assert len(engine.calls)==1


def test_rule_service_cannot_resume_llm_record_or_expose_private_agent_context(tmp_path):
    flow, _, run = pending(tmp_path)
    with closing(flow._connect()) as db, db:
        private = flow._load(db, run['run_id'])
        private['mode']='llm_langgraph'
        private['agent_internal']={'private_context':'test-only'}
        flow._save(db, private)
    public = flow.get(run['run_id'])
    assert 'agent_internal' not in public and 'snapshot' not in public
    with pytest.raises(ValueError, match='--photo-agent'):
        flow.act(run['run_id'], public['version'], 'retry')
    assert flow.get(run['run_id'])==public
