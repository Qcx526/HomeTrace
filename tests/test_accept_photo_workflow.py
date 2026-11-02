"""Offline acceptance-tool checks; no API or household photograph is read."""
import importlib.util
import json
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    'accept_photo_workflow', Path(__file__).parents[1] / 'tools/accept_photo_workflow.py')
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def test_custom_preboot_workspace_has_configuration_only_and_no_overwrite(tmp_path):
    from hometrace.household_locations import load_workspace_locations
    workspace = tmp_path / 'home'
    runner.prepare_custom_locations(workspace)
    assert [p.name for p in workspace.iterdir()] == ['locations.json']
    assert load_workspace_locations(workspace) == runner.CUSTOM_LOCATIONS
    ids = [row['location_id'] for row in runner.CUSTOM_LOCATIONS]
    assert ids[-1] == sorted(ids)[-1] == 'z-history-tray'
    original = (workspace / 'locations.json').read_bytes()
    with pytest.raises(FileExistsError):
        runner.prepare_custom_locations(workspace)
    assert (workspace / 'locations.json').read_bytes() == original


def test_usage_never_double_counts_pending_confirmed_or_out_of_order_snapshots():
    runs = {'pending': {'run_id': 'a', 'model_calls': 3, 'total_tokens': 200},
            'confirmed': {'run_id': 'a', 'model_calls': 3, 'total_tokens': 200},
            'continued': {'run_id': 'a', 'model_calls': 5, 'total_tokens': 300},
            'older': {'run_id': 'a', 'model_calls': 4, 'total_tokens': 250},
            'history': {'run_id': 'b', 'model_calls': 1, 'total_tokens': 50}}
    assert runner.usage_totals(runs) == {'unique_runs': 2, 'model_calls': 6, 'total_tokens': 350}


def test_bounded_runtime_config_preserves_key_and_image_privacy(tmp_path, monkeypatch):
    yaml = pytest.importorskip('yaml')
    from hometrace import agent_config
    from test_photo_agent_service import config
    original = config(tmp_path)
    monkeypatch.setattr(agent_config, 'load_agent_config', lambda: original)
    path, data = runner.bounded_config(tmp_path)
    text = path.read_text(encoding='utf-8')
    assert original.api_key not in text
    assert yaml.safe_load(text) == data
    assert data['llm']['max_retries'] == 0
    assert data['llm']['timeout_seconds'] == 45
    assert data['agent']['max_model_calls'] <= 10
    assert data['privacy'] == {'send_raw_images_to_llm': False, 'external_tracing_enabled': False}
