"""Offline exporter safeguards using software data, never photographic evidence."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import subprocess

import pytest


spec = importlib.util.spec_from_file_location(
    'create_task_review', Path(__file__).parents[1] / 'tools/create_task_review.py')
review = importlib.util.module_from_spec(spec)
spec.loader.exec_module(review)


@pytest.fixture
def inputs(tmp_path):
    repo = tmp_path / 'repo'
    repo.mkdir()
    subprocess.run(['git', 'init', '--quiet', str(repo)], check=True)
    (repo / '.gitignore').write_text('artifacts/\n', encoding='utf-8')
    workspace = repo / 'artifacts' / 'workspace'
    workspace.mkdir(parents=True)
    # Intentional non-image bytes exercise file preservation, not visual quality.
    for name in ('reference', 'scene1', 'scene2'):
        (workspace / (name + '.jpg')).write_bytes(('SOFTWARE_FIXTURE_' + name).encode())
    event = {'event_id': 'event-1', 'object_id': 'fixture-object',
             'location_id': 'fixture-place', 'location_name': '样例地点',
             'source': 'owner_action:fixture', 'source_kind': 'owner_reported',
             'visual_confirmed': False, 'recorded_at': '2026-01-01T00:00:00Z',
             'reported_at': None, 'recorded_at_basis': 'local_confirmation',
             'reported_at_basis': 'unknown'}
    snapshot = {'state': 'AWAITING_REVIEW', 'visual_confirmed': False,
                'version': 3, 'model_calls': 2, 'vision_calls': 1,
                'observations': [{'asset_id': 'asset-1'}, {'asset_id': 'asset-2'}],
                'trace': [{'tool': 'request_owner_review', 'seq': 3}],
                'selected_object': {'name': '软件样例物品'}}
    main = deepcopy(snapshot)
    main.update(state='USER_CONFIRMED', version=4,
                owner_event={**event, 'created': True}, candidate={'asset_id': 'asset-2'})
    history = {'state': 'COMPLETED', 'version': 2, 'model_calls': 1,
               'vision_calls': 0, 'history': [event], 'observations': [],
               'trace': [{'tool': 'query_history', 'seq': 1}]}
    replay = {'state': 'UNKNOWN', 'version': 2, 'model_calls': 1,
              'vision_calls': 0, 'observations': [{'asset_id': 'asset-1'}],
              'trace': [{'tool': 'observe', 'seq': 1}]}
    summary = {'runs': {'main': {'snapshots': [snapshot], 'final': main},
                        'history': {'snapshots': [], 'final': history},
                        'replay': {'snapshots': [], 'final': replay}},
               'checks': [{'name': 'software fixture check', 'passed': True}],
               'not_for_export': 'PRIVATE_CONFIGURATION_MUST_STAY_OUT'}
    plan = {'workspace': str(workspace), 'reference': {
        'path': 'reference.jpg', 'sha256': review.digest(workspace / 'reference.jpg'),
        'roi_reviewed': True, 'source_kind': 'real_upload',
        'width': 100, 'height': 100, 'roi': [10, 10, 90, 90]}, 'scenes': [
            {'sample_id': name, 'local_path': str(workspace / (name + '.jpg')),
             'sha256': review.digest(workspace / (name + '.jpg')), 'asset_id': asset}
            for name, asset in [('scene1', 'asset-1'), ('scene2', 'asset-2')]]}
    def chapter(run, version, state, scene):
        return {'run': run, 'version': version, 'expected_state': state, 'scene': scene,
                'label': '样例章节', 'title': '软件样例', 'body': '编辑解说',
                'caption': '本测试不是实拍识别证据', 'place': '样例地点',
                'view': '软件数据', 'status': state, 'points': ['回看，不是新执行']}
    story = {'date': '2026-01-01', 'chapters': [
        chapter('main', 3, 'AWAITING_REVIEW', 'reference'),
        chapter('main', 3, 'AWAITING_REVIEW', 'scene1'),
        chapter('main', 'final', 'USER_CONFIRMED', 'scene2'),
        chapter('history', 'final', 'COMPLETED', 'scene2'),
        chapter('replay', 'final', 'UNKNOWN', 'scene1')]}
    paths = [workspace / (name + '.json') for name in ('summary', 'plan', 'story')]
    data = {'repo': repo, 'workspace': workspace, 'summary': summary,
            'plan': plan, 'story': story, 'paths': paths,
            'output': repo / 'artifacts' / 'review'}
    def build(output=None):
        for name, path in zip(('summary', 'plan', 'story'), paths):
            path.write_text(json.dumps(data[name], ensure_ascii=False), encoding='utf-8')
        return review.build(*paths, output or data['output'], repo)
    data['build'] = build
    return data


def test_build_preserves_inputs_exports_only_selected_fields_and_records_provenance(inputs):
    before = {p.name: p.read_bytes() for p in inputs['workspace'].glob('*.jpg')}
    audit = inputs['build']()
    output = inputs['output']
    for name, content in before.items():
        assert (output / name).read_bytes() == content
        assert (inputs['workspace'] / name).read_bytes() == content
    html = (output / 'index.html').read_text(encoding='utf-8')
    assert 'PRIVATE_CONFIGURATION_MUST_STAY_OUT' not in html
    assert str(inputs['workspace']) not in html
    assert audit['kind'] == 'frozen_execution_review'
    assert audit['new_model_calls'] == 0
    assert audit['continuous_live_recording'] is False
    assert audit['automatic_FOUND'] is False
    assert audit['photo_bytes_unchanged'] is True
    assert audit['input_sha256'] == {p.name: review.digest(p) for p in inputs['paths']}
    assert audit['images']['reference'] == review.digest(output / 'reference.jpg')
    assert json.loads((output / 'review.private.json').read_text(encoding='utf-8')) == audit


@pytest.mark.parametrize('field,value', [
    ('state', 'FOUND'), ('state', 'AWAITING_REVIEW'), ('visual_confirmed', True),
])
def test_requires_owner_confirmed_not_automatic_identification(inputs, field, value):
    inputs['summary']['runs']['main']['final'][field] = value
    with pytest.raises(ValueError, match='owner-confirmed'):
        inputs['build']()
    assert not inputs['output'].exists()


@pytest.mark.parametrize('field,value', [
    ('source_kind', 'visual_detection'), ('visual_confirmed', True),
])
def test_requires_owner_reported_event(inputs, field, value):
    inputs['summary']['runs']['main']['final']['owner_event'][field] = value
    with pytest.raises(ValueError, match='owner-confirmed'):
        inputs['build']()


@pytest.mark.parametrize('field,value', [
    ('event_id', 'other-event'), ('object_id', 'other-object'),
    ('location_id', 'other-place'), ('location_name', '另一个地方'),
    ('source', 'different-source'), ('source_kind', 'visual_detection'),
    ('visual_confirmed', True), ('recorded_at', '2026-01-02T00:00:00Z'),
    ('reported_at', 'invented capture time'), ('reported_at_basis', 'camera_time'),
])
def test_restart_event_must_preserve_values_not_only_id(inputs, field, value):
    inputs['summary']['runs']['history']['final']['history'][0][field] = value
    with pytest.raises(ValueError, match='Restart query'):
        inputs['build']()
    assert not inputs['output'].exists()


@pytest.mark.parametrize('mode', ['missing', 'duplicate', 'incomplete'])
def test_restart_requires_one_matching_event_and_completed_query(inputs, mode):
    history = inputs['summary']['runs']['history']['final']
    if mode == 'missing':
        history['history'] = []
    elif mode == 'duplicate':
        history['history'].append(deepcopy(history['history'][0]))
    else:
        history['state'] = 'UNKNOWN'
    with pytest.raises(ValueError, match='Restart query'):
        inputs['build']()


@pytest.mark.parametrize('mode', ['new_call', 'missing_count', 'accepted'])
def test_replay_needs_explicit_zero_vision_calls_and_unknown_state(inputs, mode):
    replay = inputs['summary']['runs']['replay']['final']
    if mode == 'new_call':
        replay['vision_calls'] = 1
    elif mode == 'missing_count':
        replay.pop('vision_calls')
    else:
        replay['state'] = 'USER_CONFIRMED'
    with pytest.raises(ValueError, match='Replay'):
        inputs['build']()


@pytest.mark.parametrize('checks', [[], [{'passed': False}], [{'passed': 1}]])
def test_all_original_acceptance_checks_must_have_passed(inputs, checks):
    inputs['summary']['checks'] = checks
    with pytest.raises(ValueError, match='failed check'):
        inputs['build']()


@pytest.mark.parametrize('name', ['reference', 'scene1'])
def test_rejects_changed_photo_bytes_before_output_creation(inputs, name):
    (inputs['workspace'] / (name + '.jpg')).write_bytes(b'changed fixture')
    with pytest.raises(ValueError, match='SHA256'):
        inputs['build']()
    assert not inputs['output'].exists()


@pytest.mark.parametrize('field,value', [('roi_reviewed', False), ('source_kind', 'generated')])
def test_requires_reviewed_real_reference_metadata(inputs, field, value):
    inputs['plan']['reference'][field] = value
    with pytest.raises(ValueError, match='reviewed real reference'):
        inputs['build']()


def test_reference_path_cannot_escape_workspace(inputs):
    inputs['plan']['reference']['path'] = '../outside.jpg'
    with pytest.raises(ValueError):
        inputs['build']()


@pytest.mark.parametrize('sample_id', ['../escape', 'a/b', 'a\\b', 'reference', 'scene2'])
def test_sample_ids_cannot_escape_output_or_overwrite_other_sources(inputs, sample_id):
    inputs['plan']['scenes'][0]['sample_id'] = sample_id
    with pytest.raises(ValueError, match='unique safe file names'):
        inputs['build']()
    assert not inputs['output'].exists()


def test_rejects_chapter_state_not_in_snapshot(inputs):
    inputs['story']['chapters'][1]['expected_state'] = 'FOUND'
    with pytest.raises(ValueError, match='state differs'):
        inputs['build']()


def test_rejects_unknown_chapter_photo(inputs):
    inputs['story']['chapters'][1]['scene'] = 'not-in-plan'
    with pytest.raises(ValueError, match='unknown photo'):
        inputs['build']()


@pytest.mark.parametrize('run,chapter_index', [('main', 1), ('replay', 4)])
def test_chapter_cannot_show_photo_not_observed_in_its_snapshot(inputs, run, chapter_index):
    if run == 'main':
        inputs['summary']['runs']['main']['snapshots'][0]['observations'] = []
    else:
        inputs['story']['chapters'][chapter_index]['scene'] = 'scene2'
    with pytest.raises(ValueError, match='not yet observed'):
        inputs['build']()


def test_history_only_displays_photo_of_saved_candidate(inputs):
    inputs['story']['chapters'][3]['scene'] = 'scene1'
    with pytest.raises(ValueError, match='saved candidate'):
        inputs['build']()


def test_history_chapter_cannot_show_event_before_it_was_restored(inputs):
    history = inputs['summary']['runs']['history']
    earlier = {**deepcopy(history['final']), 'version': 1, 'history': []}
    history['snapshots'] = [earlier]
    inputs['story']['chapters'][3]['version'] = 1
    with pytest.raises(ValueError, match='has not restored'):
        inputs['build']()


def test_refuses_to_overwrite_existing_evidence(inputs):
    inputs['output'].mkdir()
    marker = inputs['output'] / 'previous.txt'
    marker.write_bytes(b'previous evidence')
    with pytest.raises(ValueError, match='Never overwrite'):
        inputs['build']()
    assert marker.read_bytes() == b'previous evidence'


def test_requires_ignored_output_inside_repository(inputs, tmp_path):
    with pytest.raises(ValueError, match='Git ignored'):
        inputs['build'](inputs['repo'] / 'public-review')
    with pytest.raises(ValueError):
        inputs['build'](tmp_path / 'elsewhere')
    assert not (inputs['repo'] / 'public-review').exists()


def test_label_script_terminators_are_escaped_and_page_has_no_write_api(inputs):
    attack = '</script><script>window.pwned=true</script>\u2028'
    inputs['summary']['runs']['main']['final']['selected_object']['name'] = attack
    inputs['story']['chapters'][0]['body'] = attack
    inputs['build']()
    html = (inputs['output'] / 'index.html').read_text(encoding='utf-8')
    assert attack not in html
    assert r'\u003c/script>' in html
    assert '\u2028' not in html
    assert r'\u2028' in html
    assert "connect-src 'none'" in html
    assert 'fetch(' not in html
    assert 'XMLHttpRequest' not in html
    assert 'WebSocket' not in html
    assert 'innerHTML' not in html
    assert 'textContent=c[k]' in html
    assert '真实任务回看' in html
    assert '模拟导航' in html
    assert '主人确认' in html


@pytest.fixture
def encoder(monkeypatch):
    tools = Path(__file__).parents[1] / 'tools'
    monkeypatch.syspath_prepend(str(tools))
    spec = importlib.util.spec_from_file_location('encode_task_review', tools / 'encode_task_review.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module.subprocess, 'run', lambda *a, **kw: pytest.fail('No real encoding in boundary tests'))
    return module


@pytest.mark.parametrize('existing', ['video', 'metadata'])
def test_encoder_does_not_overwrite_outputs(encoder, tmp_path, existing):
    output = tmp_path / 'clip.mp4'
    protected = output if existing == 'video' else output.with_suffix('.metadata.json')
    protected.write_bytes(b'previous output')
    with pytest.raises(ValueError, match='Never overwrite'):
        encoder.encode(tmp_path, tmp_path / 'missing-review.json', output, [5])
    assert protected.read_bytes() == b'previous output'


@pytest.mark.parametrize('durations', [[], [5, 5], [0], [61]])
def test_encoder_requires_one_bounded_duration_per_chapter(encoder, tmp_path, durations):
    audit = tmp_path / 'review.json'
    audit.write_text(json.dumps({'kind': 'frozen_execution_review', 'new_model_calls': 0,
                                'automatic_FOUND': False, 'chapters': [{}]}), encoding='utf-8')
    with pytest.raises(ValueError, match='bounded duration'):
        encoder.encode(tmp_path, audit, tmp_path / 'clip.mp4', durations)
    assert not (tmp_path / 'clip.mp4').exists()


@pytest.mark.parametrize('field,value', [
    ('kind', 'invented_execution'), ('new_model_calls', 1), ('automatic_FOUND', True),
])
def test_encoder_requires_read_only_review_provenance(encoder, tmp_path, field, value):
    data = {'kind': 'frozen_execution_review', 'new_model_calls': 0,
            'automatic_FOUND': False, 'chapters': [{}]}
    data[field] = value
    audit = tmp_path / 'review.json'
    audit.write_text(json.dumps(data), encoding='utf-8')
    with pytest.raises(ValueError, match='read-only execution review'):
        encoder.encode(tmp_path, audit, tmp_path / 'clip.mp4', [5])
