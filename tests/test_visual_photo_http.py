"""HTTP consent/new-photo routing, no external provider."""
from contextlib import contextmanager
from threading import Thread

from hometrace.demo_server import make_server
from test_photo_flow_http import ClassicStub, request, running


class VisualStub:
    visual_advisor_enabled = True
    def upload(self, **kwargs): return kwargs
    reference = scene = start = upload
    def act(self, **kwargs): return kwargs
    def submit_new_photo(self, **kwargs): return kwargs


@contextmanager
def visual_server():
    server = make_server(ClassicStub(), 0, photo_flow_service=VisualStub())
    worker = Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try: yield f'http://127.0.0.1:{server.server_port}'
    finally: server.shutdown(); server.server_close(); worker.join(5)


def test_visual_routes_accept_only_bounded_action_contract():
    with visual_server() as base:
        value = {'run_id':'0'*32, 'version':1, 'action':'approve_vision', 'request_id':'request'}
        assert request(base, '/api/home-flow/act', value)[0] == 200
        assert request(base, '/api/home-flow/act', {**value, 'endpoint':'https://evil.invalid'})[0] == 400
        photo = {'run_id':'0'*32, 'version':1, 'asset_id':'1'*32}
        assert request(base, '/api/home-flow/new-photo', photo)[0] == 200
        assert request(base, '/api/home-flow/new-photo', {**photo, 'bbox':[1, 2, 3, 4]})[0] == 400
        assert request(base, '/api/home-flow/new-photo', photo, {'Origin':'https://evil.invalid'})[0] == 403


def test_default_mode_cannot_accept_visual_consent_or_new_photo(tmp_path):
    with running(tmp_path) as (base, _):
        assert request(base, '/api/home-flow/new-photo', {'run_id':'0'*32, 'version':1, 'asset_id':'1'*32})[0] == 409
        assert request(base, '/api/home-flow/act', {'run_id':'0'*32, 'version':1,
                    'action':'approve_vision', 'request_id':'request'})[0] == 400
