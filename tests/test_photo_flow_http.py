"""HTTP boundaries for private photo uploads and durable workflow actions."""
from contextlib import contextmanager
import json
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from hometrace.demo_server import make_server
from hometrace.household_service import HouseholdService
from hometrace.photo_flow_service import PhotoFlowService


class ClassicStub:
    def config(self):
        return {'test_only': True}


@contextmanager
def running(tmp_path):
    home = HouseholdService(tmp_path/'home')
    flow = PhotoFlowService(home, use_graph=False)
    server = make_server(ClassicStub(), 0, household_service=home, photo_flow_service=flow)
    worker = Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}', flow
    finally:
        server.shutdown(); server.server_close(); worker.join(5)


def request(base, path, data=None, headers=None):
    body = None if data is None else json.dumps(data).encode()
    req = Request(base+path, data=body, headers={'Content-Type':'application/json', **(headers or {})})
    try:
        response = urlopen(req, timeout=5)
    except HTTPError as exc:
        response = exc
    with response:
        return response.status, response.read(), response.headers


def test_page_assets_security_headers_and_private_paths(tmp_path):
    with running(tmp_path) as (base, _):
        for suffix in ('html', 'js', 'css'):
            status, raw, headers = request(base, '/home-flow.'+suffix)
            assert status == 200 and len(raw) > 100
            assert headers['Cache-Control'] == 'no-store'
            assert "script-src 'self'" in headers['Content-Security-Policy']
        for path in ('/api/home-flow/assets/../../owner-memory.sqlite3', '/api/home-flow/nope'):
            assert request(base, path)[0] == 404
        assert request(base, '/api/home-flow/config', headers={'Origin':'https://attacker.invalid'})[0] == 403
        assert request(base, '/api/home-flow/config', headers={'Host':'attacker.invalid'})[0] == 403


@pytest.mark.parametrize('path,value', [
    ('assets', {'data_base64':'','source_kind':'synthetic','path':'arbitrary'}),
    ('reference', {'object_id':'x','asset_id':'0'*32,'roi':[0,0,40,40]}),
    ('scene', {'location_id':'entry-tray','asset_id':'../private'}),
    ('start', {'message':'找钥匙','location':'invented'}),
    ('act', {'run_id':'0'*32,'version':1,'action':'accept_candidate','bbox':[0,0,50,50]}),
])
def test_injected_fields_cannot_supply_locations_or_detection_evidence(tmp_path, path, value):
    with running(tmp_path) as (base, _):
        assert request(base, '/api/home-flow/'+path, value)[0] == 400


def test_version_conflict_and_download_return_actual_saved_state(tmp_path):
    with running(tmp_path) as (base, _):
        status, raw, _ = request(base, '/api/home-flow/start', {'message':'帮我找钥匙'})
        assert status == 200
        run = json.loads(raw)
        assert run['state'] == 'UNKNOWN_OBJECT'
        value = {'run_id':run['run_id'],'version':run['version'],'action':'cancel'}
        assert request(base, '/api/home-flow/act', value)[0] == 200
        assert request(base, '/api/home-flow/act', value)[0] == 409
        status, raw, headers = request(base, '/api/home-flow/runs/'+run['run_id']+'/report')
        assert status == 200 and json.loads(raw)['state'] == 'CANCELLED'
        assert 'attachment;' in headers['Content-Disposition']


def test_core_only_install_can_open_page_but_reports_missing_vision(tmp_path, monkeypatch):
    with running(tmp_path) as (base, flow):
        def unavailable(*args, **kwargs):
            raise ImportError('test missing dependency')
        monkeypatch.setattr(flow, 'upload', unavailable)
        status, raw, _ = request(base, '/api/home-flow/assets', {'data_base64':'a','source_kind':'synthetic'})
        assert status == 503 and 'vision' in json.loads(raw)['error']
