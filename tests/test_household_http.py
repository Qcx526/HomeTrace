"""Real local HTTP and SQLite integration; no camera, LLM, or visual success claims."""

from contextlib import contextmanager
import http.client
import json
import threading

import pytest

from hometrace.demo_server import make_server
from hometrace.household_service import HouseholdService


class Demo:
    def config(self):
        return {}


@contextmanager
def running_server(service=None):
    with make_server(Demo(), 0, household_service=service) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield server
        finally:
            server.shutdown()
            thread.join(timeout=5)


@pytest.fixture
def server(tmp_path):
    service = HouseholdService(tmp_path / "private-household")
    with running_server(service) as server:
        yield server


def request(server, path, data=None, *, method=None, headers=None, raw=None):
    method = method or ("POST" if data is not None or raw is not None else "GET")
    body = raw if raw is not None else json.dumps(data, ensure_ascii=False).encode("utf-8") if data is not None else None
    connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
    try:
        connection.request(method, path, body=body, headers={"Content-Type": "application/json", **(headers or {})})
        response = connection.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    finally:
        connection.close()


def post_json(server, endpoint, data):
    status, _, body = request(server, "/api/household/" + endpoint, data)
    return status, json.loads(body)


def enroll(server):
    status, body = post_json(server, "enroll", {"object_id": "blue-keys", "name": "蓝色钥匙", "aliases": ["我的钥匙"]})
    assert status == 200
    return body


def pending(server):
    enroll(server)
    status, body = post_json(server, "start", {"intent": "remember", "query": "我的钥匙", "location_id": "entry-tray"})
    assert status == 200 and body["state"] == "CONFIRM"
    return body


def test_http_registration_confirmation_recall_and_poll_use_real_persistence(server):
    status, headers, _ = request(server, "/api/household")
    assert status == 200 and headers["Cache-Control"] == "no-store"
    session = pending(server)
    assert json.loads(request(server, "/api/household/sessions/" + session["session_id"])[2]) == session
    status, complete = post_json(server, "act", {"session_id": session["session_id"], "version": session["version"], "action": "confirm"})
    assert status == 200 and complete["state"] == "COMPLETED"
    status, recalled = post_json(server, "start", {"intent": "recall", "query": "我的钥匙"})
    assert status == 200 and len(recalled["history"]) == 1
    assert recalled["history"][0]["visual_confirmed"] is False
    assert recalled["candidates"][0]["location_id"] == "entry-tray"
    assert "FOUND" not in json.dumps(recalled)


def test_http_stale_version_returns_conflict_without_duplicate_event(server):
    session = pending(server)
    arguments = {"session_id": session["session_id"], "version": session["version"], "action": "confirm"}
    assert post_json(server, "act", arguments)[0] == 200
    assert post_json(server, "act", arguments)[0] == 409
    status, recalled = post_json(server, "start", {"intent": "recall", "query": "我的钥匙"})
    assert status == 200 and len(recalled["history"]) == 1


@pytest.mark.parametrize("headers", [{"Host": "evil.example"}, {"Origin": "https://evil.example"}])
def test_http_external_origin_or_host_cannot_read_or_write_household_memory(server, headers):
    assert request(server, "/api/household", headers=headers)[0] == 403
    assert request(server, "/api/household/enroll", {"object_id": "keys", "name": "钥匙", "aliases": []}, headers=headers)[0] == 403


@pytest.mark.parametrize("endpoint,payload", [
    ("enroll", {"object_id": "keys", "name": "钥匙", "aliases": [], "api_key": "fake"}),
    ("enroll", {"object_id": "keys", "name": "钥匙", "aliases": "wrong-type"}),
    ("enroll", {"object_id": "keys", "name": 1, "aliases": []}),
    ("start", {"intent": "recall", "query": "钥匙", "db": "../../private.sqlite3"}),
    ("start", {"intent": "recall", "query": []}),
    ("start", {"intent": "remember", "query": "钥匙", "location_id": "unknown-room"}),
    ("start", {"intent": "remember", "query": "钥匙", "location_id": "entry-tray", "reported_at": "2026-10-27T10:00:00"}),
    ("start", []),
    ("act", {"session_id": "0" * 32, "version": True, "action": "confirm"}),
    ("act", {"session_id": "0" * 32, "version": "1", "action": "confirm"}),
    ("act", {"session_id": "0" * 32, "version": 1, "action": "confirm", "location_id": "study-desk"}),
])
def test_http_rejects_invalid_types_and_unexpected_fields(server, endpoint, payload):
    status, body = post_json(server, endpoint, payload)
    assert status == 400
    assert "error" in body


def test_http_unknown_sessions_are_404(server):
    assert request(server, "/api/household/sessions/" + "0" * 32)[0] == 404
    assert post_json(server, "act", {"session_id": "0" * 32, "version": 1, "action": "confirm"})[0] == 404


@pytest.mark.parametrize("path", ["/api/household/sessions/../../.env", "/api/household/sessions/%2e%2e%2f.env", "/api/household/.env", "/api/household/sessions/invalid"])
def test_http_paths_cannot_escape_explicit_session_routes(server, path):
    assert request(server, path)[0] == 404


def test_http_rejects_nonjson_malformed_json_and_oversized_requests(server):
    assert request(server, "/api/household/start", raw=b"{}", headers={"Content-Type": "text/plain"})[0] == 415
    assert request(server, "/api/household/start", raw=b"not json")[0] == 400
    assert request(server, "/api/household/start", raw=b"{" + b" " * 8192 + b"}")[0] == 400


def test_disabled_household_api_is_explicit_and_cannot_write():
    with running_server() as server:
        assert request(server, "/api/household")[0] == 503
        assert post_json(server, "start", {"intent": "recall", "query": "钥匙"})[0] == 503


def test_html_like_object_name_remains_json_data(server):
    name = '<img src=x onerror="alert(1)">'
    status, _ = post_json(server, "enroll", {"object_id": "markup", "name": name, "aliases": []})
    assert status == 200
    status, headers, body = request(server, "/api/household/start", {"intent": "recall", "query": name})
    assert status == 200 and headers["Content-Type"].startswith("application/json")
    assert json.loads(body)["selected_object"]["name"] == name
    assert headers["X-Content-Type-Options"] == "nosniff"


def test_public_api_errors_never_include_workspace_or_key(server, tmp_path):
    for endpoint, payload in [("start", {"intent": "recall", "query": "missing"}), ("enroll", {"object_id": "../private", "name": "bad", "aliases": []})]:
        _, body = post_json(server, endpoint, payload)
        serialized = json.dumps(body, ensure_ascii=False)
        assert str(tmp_path) not in serialized
        assert "HOMETRACE_LLM_API_KEY" not in serialized
