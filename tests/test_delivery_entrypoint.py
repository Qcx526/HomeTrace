"""The shipped photo entry point is independent of historical demo assets."""

from contextlib import contextmanager
import http.client
from importlib.resources import files
import json
from pathlib import Path
import threading

import pytest

from hometrace import demo_server


@contextmanager
def running(**kwargs):
    with demo_server.make_server(port=0, **kwargs) as server:
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            yield server
        finally:
            server.shutdown()
            worker.join(timeout=5)


def request(server, path, data=None):
    connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
    try:
        connection.request("GET" if data is None else "POST", path,
                           body=None if data is None else json.dumps(data),
                           headers={"Content-Type": "application/json"})
        response = connection.getresponse()
        return response.status, response.read(), dict(response.getheaders())
    finally:
        connection.close()


def test_default_root_is_current_photo_page_and_no_historical_resources_are_exposed():
    with running() as server:
        status, page, headers = request(server, "/")
        assert status == 200
        assert page == request(server, "/home-flow.html")[1]
        assert b'/home-flow.js' in page and b'/home-flow.css' in page
        assert b'/agent.html' not in page and b'/household.html' not in page
        assert b'8786' not in page
        assert headers["Cache-Control"] == "no-store"
        for name in demo_server.LEGACY_WEB_FILES:
            assert request(server, "/" + name)[0] == 404
        assert request(server, "/tests/fixtures/legacy_web/index.html")[0] == 404


def test_installed_web_resources_only_contain_current_photo_entrypoint():
    web = files("hometrace").joinpath("web")
    assert {path.name for path in web.iterdir() if path.is_file()} == {
        "home-flow.html", "home-flow.js", "home-flow.css",
    }


def test_disabled_historical_api_reports_unavailable_instead_of_crashing():
    with running() as server:
        for path in ("/api/config", "/api/runs/" + "0" * 32 + "/images/reference"):
            status, body, _ = request(server, path)
            assert status == 503 and "disabled" in json.loads(body)["error"]
        status, body, _ = request(server, "/api/run", {"scenario": "moved", "strategy": "memory_first"})
        assert status == 503 and "disabled" in json.loads(body)["error"]


def test_explicit_legacy_directory_preserves_pages_without_exposing_arbitrary_files():
    legacy = Path(__file__).parent / "fixtures" / "legacy_web"
    with running(legacy_web_dir=legacy) as server:
        assert request(server, "/")[1] == (legacy / "index.html").read_bytes()
        for name in demo_server.LEGACY_WEB_FILES:
            assert request(server, "/" + name)[1] == (legacy / name).read_bytes()
        assert request(server, "/home-flow.html")[0] == 200
        for path in ("/../test_demo.py", "/%2e%2e/test_demo.py", "/legacy_web/index.html"):
            assert request(server, path)[0] == 404


def test_missing_legacy_directory_is_not_silently_replaced_by_shipped_assets(tmp_path):
    with pytest.raises(ValueError, match="historical test fixtures"):
        demo_server.make_server(port=0, legacy_web_dir=tmp_path / "missing")


def test_default_cli_starts_without_public_samples_or_classic_service(tmp_path, monkeypatch, capsys):
    def forbidden(*args, **kwargs):
        pytest.fail("The photo workspace must not read historical scenarios")

    def stop(server, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(demo_server, "DemoService", forbidden)
    monkeypatch.setattr(demo_server, "load_recorded_scene", forbidden)
    monkeypatch.setattr(demo_server.ThreadingHTTPServer, "serve_forever", stop)
    assert demo_server.main([
        "--port", "0", "--samples-dir", str(tmp_path / "absent-samples"),
        "--household-dir", str(tmp_path / "empty-household"),
    ]) == 0
    output = capsys.readouterr().out
    assert "HomeTrace demo: http://127.0.0.1:" in output
    assert "/household.html" not in output and "Historical run evidence" not in output
    assert not (tmp_path / "absent-samples").exists()
