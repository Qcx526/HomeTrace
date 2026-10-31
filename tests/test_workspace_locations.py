"""Offline workspace-place contracts; generated fixtures are not vision evidence.

These tests use temporary JSON/SQLite files and explicitly scripted model and
detector doubles. They never load private photos, .env or a remote model API.
"""
from contextlib import closing
from copy import deepcopy
import json

import pytest

from hometrace.household_locations import DEFAULT_LOCATIONS, load_workspace_locations, run_locations
from hometrace.household_memory import HouseholdMemory
from hometrace.household_service import HouseholdService


PLACES = [{'location_id': 'alpha-table', 'location_name': '软件样例桌'},
          {'location_id': 'zeta-shelf', 'location_name': '软件样例架'}]


def write_places(workspace, places=None, *, value=None):
    workspace.mkdir(parents=True, exist_ok=True)
    payload = value if value is not None else {'version': 1, 'locations': places or deepcopy(PLACES)}
    path = workspace / 'locations.json'
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
    return path


def flow(workspace, outcomes=None):
    from hometrace.photo_flow_service import PhotoFlowService
    from test_photo_flow_service import ScriptedEngine
    household = HouseholdService(workspace)
    engine = ScriptedEngine(outcomes)
    return household, PhotoFlowService(household, engine_factory=engine, use_graph=False), engine


def test_locations_are_workspace_local_restart_stable_and_defensive_copies(tmp_path):
    custom = tmp_path / 'custom'
    write_places(custom)
    home = HouseholdService(custom)
    assert home.locations == home.config()['locations'] == PLACES
    response = home.config()
    response['locations'][0]['location_name'] = 'client-only-edit'
    assert home.config()['locations'] == PLACES
    assert HouseholdService(custom).config()['locations'] == PLACES
    assert HouseholdService(tmp_path / 'default').config()['locations'] == list(DEFAULT_LOCATIONS)
    default_result = load_workspace_locations(tmp_path / 'default')
    default_result[0]['location_name'] = 'caller-only-edit'
    assert load_workspace_locations(tmp_path / 'default') == list(DEFAULT_LOCATIONS)


@pytest.mark.parametrize('payload', [
    {'version': True, 'locations': PLACES},
    {'version': 2, 'locations': PLACES},
    {'version': 1, 'locations': PLACES, 'api_key': 'unused-software-fixture'},
    {'version': 1, 'locations': []},
    {'version': 1, 'locations': [{'location_id': f'place-{i}', 'location_name': f'样例{i}'} for i in range(11)]},
    {'version': 1, 'locations': [PLACES[0], PLACES[0]]},
    {'version': 1, 'locations': [{'location_id': '../escape', 'location_name': '样例'}]},
    {'version': 1, 'locations': [{'location_id': 'place', 'location_name': '   '}]},
    {'version': 1, 'locations': [{'location_id': 'place', 'location_name': '样例\u202e位置'}]},
    {'version': 1, 'locations': [{'location_id': 'place', 'location_name': '样例', 'image': 'unknown.png'}]},
    {'version': 1, 'locations': [{'location_id': 'first', 'location_name': ' Ａ  Desk '},
                               {'location_id': 'second', 'location_name': 'a desk'}]},
])
def test_invalid_config_fails_before_initializing_databases(tmp_path, payload):
    write_places(tmp_path, value=payload)
    with pytest.raises(ValueError):
        HouseholdService(tmp_path)
    assert not (tmp_path / 'owner-memory.sqlite3').exists()
    assert not (tmp_path / 'sessions.sqlite3').exists()


@pytest.mark.parametrize('text', [
    '{"version":1,"version":1,"locations":[]}',
    '{"version":1,"locations":[{"location_id":"a","location_id":"b","location_name":"test"}]}',
    '{"version":',
    ' ' * (16 * 1024 + 1),
])
def test_unparseable_duplicate_or_oversized_configuration_is_not_defaulted(tmp_path, text):
    (tmp_path / 'locations.json').write_text(text, encoding='utf-8')
    with pytest.raises(ValueError):
        load_workspace_locations(tmp_path)


def test_symlink_config_cannot_read_an_external_file(tmp_path):
    target = write_places(tmp_path / 'outside')
    workspace = tmp_path / 'home'
    workspace.mkdir()
    try:
        (workspace / 'locations.json').symlink_to(target)
    except OSError:
        pytest.skip('This OS account cannot create symlinks')
    with pytest.raises(ValueError):
        load_workspace_locations(workspace)


def test_existing_run_without_snapshot_uses_only_original_defaults():
    assert run_locations({}) == list(DEFAULT_LOCATIONS)
    for corrupt in (None, [], {}, [{'location_id': 'x'}]):
        with pytest.raises(ValueError):
            run_locations({'location_snapshot': corrupt})
    snap = {'location_snapshot': deepcopy(PLACES)}
    result = run_locations(snap)
    result[0]['location_name'] = 'caller-only-edit'
    assert snap['location_snapshot'] == PLACES


def test_household_pending_statement_survives_config_change_without_renaming(tmp_path):
    write_places(tmp_path)
    home = HouseholdService(tmp_path)
    home.enroll('keys-a', '蓝钥匙', ['钥匙'])
    pending = home.start('remember', '蓝钥匙', 'zeta-shelf')
    write_places(tmp_path, [{'location_id': 'new-place', 'location_name': '新的样例地点'}])
    resumed = HouseholdService(tmp_path)
    confirmed = resumed.act(pending['session_id'], pending['version'], 'confirm')
    assert confirmed['history'][0]['location_id'] == 'zeta-shelf'
    assert confirmed['history'][0]['location_name'] == '软件样例架'
    with pytest.raises(ValueError):
        resumed.start('remember', '蓝钥匙', 'zeta-shelf')


def test_history_prioritizes_custom_place_and_confirm_uses_run_snapshot_after_restart(tmp_path):
    from test_photo_flow_service import history, register, upload
    write_places(tmp_path)
    home, service, engine = flow(tmp_path, {'zeta-shelf': 'candidate'})
    register(home, service)
    with HouseholdMemory(home.memory_path) as memory:
        memory.remember(event_id='fixture-history', object_id='keys-a', location_id='zeta-shelf',
                        location_name='软件样例架', reported_at='2026-10-01T12:00:00+08:00',
                        source='explicit_software_test_owner_statement')
    service.scene('zeta-shelf', upload(service, 2)['asset_id'])
    pending = service.wait(service.start('帮我找蓝钥匙')['run_id'])
    assert pending['state'] == 'AWAITING_REVIEW'
    assert pending['location_snapshot'] == PLACES
    assert pending['planned_locations'][0]['location_id'] == 'zeta-shelf'
    assert pending['planned_locations'][0]['reason'] == 'recent_owner_memory'
    assert pending['visited'] == ['zeta-shelf']
    assert engine.calls[0][0] == 'zeta-shelf'
    write_places(tmp_path, [{'location_id': 'zeta-shelf', 'location_name': '同ID的新名称'}])
    restarted_home, restarted, _ = flow(tmp_path)
    confirmed = restarted.act(pending['run_id'], pending['version'], 'accept_candidate')
    assert confirmed['owner_event']['location_name'] == '软件样例架'
    assert confirmed['state'] == 'USER_CONFIRMED' and not confirmed['visual_confirmed']
    assert len(history(restarted_home)) == 2
    assert restarted.config()['locations'][0]['location_name'] == '同ID的新名称'


def test_old_default_run_confirmation_cannot_be_relabelled_by_new_workspace_config(tmp_path):
    from test_photo_flow_service import register
    _, service, _ = flow(tmp_path)
    register(service.household, service)
    pending = service.start('记住蓝钥匙', 'study-desk')
    with closing(service._connect()) as db, db:
        private = service._load(db, pending['run_id'])
        private.pop('location_snapshot')
        service._save(db, private)
    write_places(tmp_path, [{'location_id': 'study-desk', 'location_name': '新配置不得改旧记录'}])
    _, restarted, _ = flow(tmp_path)
    resumed = restarted.get(pending['run_id'])
    confirmed = restarted.act(resumed['run_id'], resumed['version'], 'confirm_memory')
    assert confirmed['owner_event']['location_name'] == '书房桌面'


def test_retired_scenes_are_filtered_without_deleting_old_assets_or_runs(tmp_path):
    from test_photo_flow_service import register, upload
    _, old, _ = flow(tmp_path)
    register(old.household, old)
    asset = upload(old, 2)
    old.scene('study-desk', asset['asset_id'])
    write_places(tmp_path)
    _, current, engine = flow(tmp_path)
    assert current.config()['scenes'] == []
    assert current.asset(asset['asset_id'])[0] == old.asset(asset['asset_id'])[0]
    with pytest.raises(ValueError):
        current.scene('study-desk', asset['asset_id'])
    with pytest.raises(ValueError):
        current.start('帮我找蓝钥匙', 'study-desk')
    result = current.wait(current.start('帮我找蓝钥匙')['run_id'])
    assert result['state'] == 'UNKNOWN' and not engine.calls
    assert set(result['visited']) == {x['location_id'] for x in PLACES}
    with closing(current._connect()) as db:
        assert current._load(db, result['run_id'])['snapshot']['scenes'] == {}
        assert db.execute('SELECT count(*) FROM scenes').fetchone()[0] == 1


def test_llm_cannot_navigate_to_default_place_outside_custom_workspace(tmp_path):
    from hometrace.photo_agent_service import PhotoAgentService
    from test_photo_agent_service import ScriptedModel, config, guards, inspect, resolve
    from test_photo_flow_service import ScriptedEngine, history, register
    write_places(tmp_path)
    home, engine = HouseholdService(tmp_path), ScriptedEngine()
    model = ScriptedModel([resolve(), inspect('study-desk')])
    service = PhotoAgentService(home, agent_config=config(tmp_path), model=model, engine_factory=engine)
    register(home, service)
    result = service.wait(service.start('请找蓝钥匙')['run_id'])
    assert result['state'] == 'ERROR'
    assert guards(result) == ['TOOL_STATE_OR_ARGUMENT_REJECTED']
    assert not engine.calls and not history(home)
    assert [x['location_id'] for x in model.contexts[-1]['locations']] == ['alpha-table', 'zeta-shelf']


def test_llm_pending_search_keeps_original_locations_after_restart(tmp_path):
    from hometrace.photo_agent_service import PhotoAgentService
    from test_photo_agent_service import ScriptedModel, config, inspect, resolve, stop
    from test_photo_flow_service import ScriptedEngine, register, upload
    write_places(tmp_path)
    home, engine = HouseholdService(tmp_path), ScriptedEngine({'zeta-shelf': 'candidate'})
    service = PhotoAgentService(home, agent_config=config(tmp_path),
        model=ScriptedModel([resolve(), inspect('zeta-shelf')]), engine_factory=engine)
    register(home, service)
    for seed, place in enumerate(PLACES, 2):
        service.scene(place['location_id'], upload(service, seed)['asset_id'])
    pending = service.wait(service.start('请找蓝钥匙')['run_id'])
    assert pending['state'] == 'AWAITING_REVIEW'
    write_places(tmp_path, [{'location_id': 'new-place', 'location_name': '新的样例地点'}])
    model = ScriptedModel([inspect('alpha-table'), stop()])
    resumed = PhotoAgentService(HouseholdService(tmp_path), agent_config=service.agent_config,
                               model=model, engine_factory=engine)
    resumed.act(pending['run_id'], pending['version'], 'reject_candidate')
    result = resumed.wait(pending['run_id'])
    assert result['state'] == 'UNKNOWN' and result['visited'] == ['zeta-shelf', 'alpha-table']
    assert [x['location_name'] for x in model.contexts[0]['locations']] == [x['location_name'] for x in PLACES]
    assert 'inspect_location' not in model.contexts[-1]['allowed_tools']
    assert len(engine.calls) == 2


@pytest.mark.parametrize('max_viewpoints,expected_state,expected_visits', [
    (2, 'BUDGET_EXCEEDED', 2), (4, 'UNKNOWN', 4),
])
def test_four_custom_places_respect_real_visit_budget_not_old_three_place_limit(
        tmp_path, max_viewpoints, expected_state, expected_visits):
    from hometrace.photo_agent_service import PhotoAgentService
    from test_photo_agent_service import ScriptedModel, config, guards, inspect, resolve, stop
    from test_photo_flow_service import ScriptedEngine, register, upload
    places = [{'location_id': f'place-{i}', 'location_name': f'软件地点{i}'} for i in range(4)]
    write_places(tmp_path, places)
    home, engine = HouseholdService(tmp_path), ScriptedEngine()
    model = ScriptedModel([resolve(), *(inspect(x['location_id']) for x in places), stop()])
    service = PhotoAgentService(home, agent_config=config(tmp_path, max_viewpoints=max_viewpoints),
                               model=model, engine_factory=engine)
    register(home, service)
    for seed, place in enumerate(places, 2):
        service.scene(place['location_id'], upload(service, seed)['asset_id'])
    run = service.wait(service.start('请找蓝钥匙')['run_id'])
    assert run['state'] == expected_state and len(run['visited']) == expected_visits
    assert len(engine.calls) == expected_visits and not run['visual_confirmed']
    if expected_state == 'BUDGET_EXCEEDED':
        assert guards(run) == ['VIEWPOINT_BUDGET']
    else:
        assert 'inspect_location' not in model.contexts[-1]['allowed_tools']


def test_visual_feedback_lists_only_unvisited_uploaded_snapshot_places(tmp_path):
    from hometrace.visual_photo_agent_service import VisualPhotoAgentService
    run = {'location_snapshot': deepcopy(PLACES), 'visited': ['alpha-table'],
           'observations': [], 'visual_advice': [],
           'snapshot': {'scenes': {'alpha-table': {}, 'zeta-shelf': {}, 'study-desk': {}}}}
    assert VisualPhotoAgentService._decision_support(run)['unvisited_uploaded_locations'] == ['zeta-shelf']
