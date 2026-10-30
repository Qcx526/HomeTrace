"""Offline software fixtures only; no API calls or visual accuracy claims."""
import ast
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip('langchain_core')
spec = importlib.util.spec_from_file_location('decision_probe', Path(__file__).parents[1] / 'tools/probe_visual_decisions.py')
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


def response(name='finish_search', **args):
    return SimpleNamespace(tool_calls=[{'name': name, 'args': {'reason': '软件测试', **args}}],
        invalid_tool_calls=[], response_metadata={'model_name': 'offline-double'},
        usage_metadata={'input_tokens': 10, 'output_tokens': 2, 'total_tokens': 12}, id='offline-response')


class Model:
    def __init__(self, error=False):
        self.calls, self.error = [], error

    def bind_tools(self, tools):
        self.tools = tools
        return self

    def invoke(self, messages, **kwargs):
        self.calls.append((messages, kwargs))
        assert kwargs == {'max_tokens': 1024}
        if self.error:
            raise ValueError('provider private body must not be saved')
        return response()


def test_expected_not_in_input_and_context_matches_available_tools():
    for index in range(6):
        old, new = (probe.context_for(index, mode) for mode in ('baseline', 'new'))
        assert 'decision_support' not in old
        assert {k: v for k, v in new.items() if k != 'decision_support'} == old
        assert 'expected' not in json.dumps(new)
        assert set(new['allowed_tools']) <= {'inspect_location', 'finish_search', 'decline_request',
                                            'request_new_photo', 'request_owner_review'}
        assert ('request_owner_review' in new['allowed_tools']) == (index in (2, 4))
        assert new['observations'][0]['bbox'] is None
        assert not new['automatic_found_enabled']


def test_twelve_attempts_including_errors_are_counted_and_never_retried(tmp_path):
    model = Model(error=True)
    result = probe.run_probe(tmp_path / 'probe', model)
    assert result['call_count'] == len(model.calls) == probe.MAX_CALLS == 12
    assert result['summary'] == {'baseline': {'passed': 0, 'errors': 6}, 'new': {'passed': 0, 'errors': 6}}
    for path in (tmp_path / 'probe').glob('*-*.json'):
        row = json.loads(path.read_text(encoding='utf-8'))
        assert row['execution_status'] == 'error'
        assert not row['tools_executed'] and not row['images_sent']
        assert 'provider private body' not in path.read_text(encoding='utf-8')
    with pytest.raises(FileExistsError):
        probe.run_probe(tmp_path / 'probe', model)
    assert len(model.calls) == 12


def test_returned_selection_not_executed_and_baseline_description_recorded(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('Probe must never execute a tool')
    monkeypatch.setattr(probe.VisualPhotoAgentService, '_execute', forbidden)
    model = Model()
    result = probe.run_probe(tmp_path / 'probe', model)
    assert result['summary']['baseline']['passed'] == result['summary']['new']['passed'] == 1
    old = json.loads((tmp_path / 'probe/1-baseline.json').read_text(encoding='utf-8'))
    new = json.loads((tmp_path / 'probe/1-new.json').read_text(encoding='utf-8'))
    assert old['prompt_sha256'] != new['prompt_sha256']
    descriptions = lambda row: {t['function']['name']: t['function']['description'] for t in row['tool_schemas']}
    assert descriptions(old)['request_new_photo'] != descriptions(new)['request_new_photo']
    assert old['metrics']['usage']['total_tokens'] == 12


@pytest.mark.parametrize('name,args', [('invented', {}), ('inspect_location', {'location_id': 'nonexistent'}),
    ('inspect_location', {'location_id': 'study-desk'}), ('request_owner_review', {}), ('finish_search', {'extra': True})])
def test_invalid_tool_or_location_never_scores(name, args):
    result = probe.score(1, probe.context_for(1, 'new'), response(name, **args))
    assert not result['valid'] and not result['pass']


def test_correct_and_wrong_inspection():
    context = probe.context_for(1, 'new')
    assert probe.score(1, context, response('inspect_location', location_id='living-table'))['pass']
    assert not probe.score(1, context, response('inspect_location', location_id='entry-tray'))['pass']
    value = response()
    value.invalid_tool_calls = [{'name': 'broken'}]
    assert not probe.score(0, context, value)['valid']


def test_constant_reader_rejects_execution():
    assert probe.constant(ast.parse("X.replace('a', 'c') + 'd'", mode='eval').body, {'X': 'ab'}) == 'cbd'
    with pytest.raises(ValueError):
        probe.constant(ast.parse("__import__('os').system('secret')", mode='eval').body, {})


def test_key_echo_is_redacted(tmp_path):
    class Echo(Model):
        def invoke(self, *args, **kwargs):
            value = response()
            value.tool_calls[0]['args']['reason'] = 'private-test-key'
            return value
    probe.run_probe(tmp_path / 'probe', Echo(), secret='private-test-key')
    assert all('private-test-key' not in p.read_text(encoding='utf-8') for p in (tmp_path / 'probe').glob('*.json'))
