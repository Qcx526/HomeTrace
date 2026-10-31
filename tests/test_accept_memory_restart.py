"""Offline acceptance-runner safeguards; no provider call or private photograph."""
import importlib.util
import json
from pathlib import Path
import subprocess
from threading import Thread

import pytest


spec = importlib.util.spec_from_file_location('accept_memory_restart', Path(__file__).parents[1] / 'tools/accept_memory_restart.py')
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def repository(tmp_path):
    repo = tmp_path / 'repo'
    repo.mkdir()
    subprocess.run(['git', 'init', '--quiet', str(repo)], check=True)
    (repo / '.gitignore').write_text('artifacts/\n', encoding='utf-8')
    return repo


def test_output_requires_new_ignored_directory_in_repository(tmp_path):
    repo = repository(tmp_path)
    with pytest.raises(ValueError, match='inside'):
        runner.new_output(tmp_path / 'elsewhere', repo)
    with pytest.raises(ValueError, match='ignored'):
        runner.new_output(repo / 'public', repo)
    output = runner.new_output(repo / 'artifacts' / 'new', repo)
    marker = output / 'immutable.txt'
    marker.write_text('previous evidence', encoding='utf-8')
    with pytest.raises(ValueError, match='new'):
        runner.new_output(output, repo)
    assert marker.read_text(encoding='utf-8') == 'previous evidence'


def test_bounded_config_has_no_key_and_explicit_no_retry_limits(tmp_path, monkeypatch):
    yaml = pytest.importorskip('yaml')
    from hometrace import agent_config
    from test_photo_agent_service import config
    original = config(tmp_path)
    monkeypatch.setattr(agent_config, 'load_agent_config', lambda path: original)
    path, document = runner.bounded_config(tmp_path)
    data = path.read_text(encoding='utf-8')
    assert original.api_key not in data
    assert yaml.safe_load(data) == document
    assert document['llm']['max_retries'] == 0
    assert document['llm']['timeout_seconds'] == 45
    assert document['agent']['max_model_calls'] == 2
    assert document['privacy'] == {'send_raw_images_to_llm': False, 'external_tracing_enabled': False}


@pytest.mark.parametrize('path,value', [
    ('/api/home-flow/act', {'action': 'approve_vision'}),
    ('/api/home-flow/act', {'action': 'retry'}),
    ('/api/home-flow/scene', {'asset_id': 'forbidden'}),
    ('/api/home-flow/new-photo', {'asset_id': 'forbidden'}),
])
def test_runner_never_allows_image_consent_retry_or_search_images(tmp_path, monkeypatch, path, value):
    monkeypatch.setattr(runner, 'urlopen', lambda *a, **kw: pytest.fail('No network permitted'))
    acceptance = runner.Acceptance(tmp_path, None)
    with pytest.raises(ValueError):
        acceptance.call(path, value)
    assert acceptance.summary['http'] == []


def test_fixture_is_deterministic_pixels_not_external_input(tmp_path):
    from PIL import Image
    first = runner.fixture_png(tmp_path / 'a.png')
    second = runner.fixture_png(tmp_path / 'b.png')
    assert first.read_bytes() == second.read_bytes()
    with Image.open(first) as image:
        assert image.size == (256, 256)
        assert not image.getexif()
    with pytest.raises(FileExistsError):
        runner.fixture_png(first)


def test_failure_retains_summary_and_closes_child_without_exception_body(tmp_path, monkeypatch):
    acceptance = runner.Acceptance(tmp_path, None)
    stopped = []
    def fail(index):
        raise RuntimeError('private provider response must not be copied')
    monkeypatch.setattr(acceptance, 'start', fail)
    monkeypatch.setattr(acceptance, 'stop', lambda: stopped.append(True))
    with pytest.raises(RuntimeError):
        acceptance.execute()
    saved = (tmp_path / 'summary.json').read_text(encoding='utf-8')
    assert json.loads(saved)['failure_type'] == 'RuntimeError'
    assert json.loads(saved)['checks_passed'] is False
    assert 'private provider response' not in saved
    assert stopped == [True]


def test_fourth_text_phase_is_blocked_before_network(tmp_path, monkeypatch):
    acceptance = runner.Acceptance(tmp_path, None)
    acceptance.summary['text_phases_started'] = 3
    monkeypatch.setattr(runner, 'urlopen', lambda *a, **kw: pytest.fail('No fourth request'))
    with pytest.raises(AssertionError, match='three text phases'):
        acceptance.call('/api/home-flow/start', {'message': 'not permitted'})


def test_read_only_snapshot_cannot_create_missing_database(tmp_path):
    acceptance = runner.Acceptance(tmp_path, None)
    with pytest.raises(runner.sqlite3.OperationalError):
        acceptance.events('missing')
    assert not acceptance.workspace.exists()


def test_offline_http_flow_preserves_pending_event_and_rejects_stale_confirm(tmp_path):
    pytest.importorskip('langgraph')
    from hometrace.demo_server import make_server
    from hometrace.household_service import HouseholdService
    from hometrace.visual_photo_agent_service import VisualPhotoAgentService
    from test_photo_agent_service import ScriptedModel, config, resolve

    class OfflineHTTP(runner.Acceptance):
        """Real HTTP/database, reconstructed services; not actual child-process evidence."""
        server = thread = None

        def start(self, index):
            self.stop()
            household = HouseholdService(self.workspace)
            responses = ([resolve('remember', runner.OBJECT_ID), resolve('remember', runner.OBJECT_ID)]
                         if index == 1 else [resolve('history', runner.OBJECT_ID)] if index == 3 else [])
            model = ScriptedModel(responses)
            service = VisualPhotoAgentService(household, model=model, agent_config=config(tmp_path, max_model_calls=2))
            self.server = make_server(None, 0, household_service=household, photo_flow_service=service)
            self.thread = Thread(target=self.server.serve_forever, daemon=True)
            self.thread.start()
            self.base = f'http://127.0.0.1:{self.server.server_port}'

        def stop(self):
            if self.server is not None:
                self.server.shutdown()
                self.server.server_close()
                self.thread.join(timeout=3)
                self.server = None

    acceptance = OfflineHTTP(tmp_path, None)
    acceptance.summary.update(requested_real_text_llm=False,
                              transport='offline test: real HTTP and SQLite, recreated services, no subprocess')
    summary = acceptance.execute()
    assert summary['checks_passed'] is True
    assert summary['actual_model_calls'] == 3
    assert summary['image_consent_grants'] == 0
    assert [item['status'] for item in summary['http']].count(409) == 1
    final = summary['database_snapshots'][-1]
    assert len(final['events']) == 1 and final['evidence_count'] == 0
    assert summary['runs']['history']['history'][0]['event_id'] == final['events'][0]['event_id']
    assert all(row['inspection_mode'] == 'read_only_sqlite' for row in summary['database_snapshots'])


def test_startup_failure_records_real_process_exit_and_closes_log(tmp_path, monkeypatch):
    class FailedProcess:
        pid, returncode = 1234, 9
        def poll(self):
            return self.returncode

    commands = []
    def popen(command, **kwargs):
        commands.append((command, kwargs))
        return FailedProcess()
    monkeypatch.setattr(runner.subprocess, 'Popen', popen)
    acceptance = runner.Acceptance(tmp_path, tmp_path / 'bounded.yaml')
    with pytest.raises(RuntimeError, match='startup'):
        acceptance.execute()
    assert '--photo-vision-agent' in commands[0][0]
    assert commands[0][0][commands[0][0].index('--port') + 1] == '0'
    assert acceptance.summary['processes'][0] == {'boot': 1, 'pid': 1234, 'stopped': True, 'exit_code': 9}
    assert acceptance.logfile is None
