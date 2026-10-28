"""Local demo integration: real CLI processes, images and independent SQLite stores."""

import hashlib
import http.client
import json
from pathlib import Path
import shutil
import threading

import pytest

from hometrace.demo_service import DemoBusyError, DemoService
from hometrace.demo_server import make_server


SAMPLES = Path(__file__).resolve().parents[1] / "examples" / "recorded_images"


@pytest.fixture(scope="module")
def demo(tmp_path_factory):
    pytest.importorskip("cv2")
    root = tmp_path_factory.mktemp("visual-demo") / "中文目录"
    root.mkdir()
    samples = root / "samples"
    shutil.copytree(SAMPLES, samples)
    service = DemoService(samples, root / "runs")
    runs = {name: service.run(name, "memory_first") for name in ("moved", "missing", "replay")}
    return service, runs


def test_three_demos_execute_and_preserve_report_semantics(demo):
    service, runs = demo
    moved, missing, replay = (runs[k]["report"] for k in ("moved", "missing", "replay"))
    assert moved["result_status"] == "FOUND" and moved["location"] == "B"
    assert moved["attempted_viewpoints"] == ["A", "B"]
    assert moved["evidence"][0]["detection"]["status"] == "SUSPECTED"
    assert moved["evidence"][1]["detection"]["bbox"]
    assert missing["result_status"] in {"UNKNOWN", "SUSPECTED"}
    assert missing["location"] is None and not missing["confirmed_evidence_ids"]
    assert replay["result_status"] == "UNKNOWN" and replay["location"] is None
    assert replay["observed_viewpoints"] == ["C"]
    assert sum(e["result"].get("reason") == "replayed_evidence" for e in replay["events"]) == 2
    for name, run in runs.items():
        assert run["report"]["data_source"] == "recorded_image"
        assert run["report"]["navigation_mode"] == "simulated_navigation"
        assert run["registration"]["operation"] == "register"
        assert bool(run["prior_search"]) == (name == "replay")
        assert json.loads(service.download(run["run_id"], "report").read_text(encoding="utf-8")) == run["report"]


def test_fair_comparison_uses_frozen_identical_inputs_and_history(demo):
    service, runs = demo
    for name, run in runs.items():
        directory = service.output_dir / run["run_id"]
        rows = run["comparison"]["rows"]
        assert {r["strategy"] for r in rows} == {"memory_first", "fixed_order"}
        assert rows[0]["result_status"] == rows[1]["result_status"]
        assert rows[0]["attempted"] == rows[1]["attempted"] == (2 if name == "moved" else 3)
        assert rows[0]["observed"] == rows[1]["observed"] == (1 if name == "replay" else rows[0]["attempted"])
        histories = []
        for strategy in ("memory_first", "fixed_order"):
            report = json.loads((directory / strategy / "search/report.json").read_text(encoding="utf-8"))
            histories.append([(r["observation"], r["detection"]["status"], r["detection"]["bbox"]) for r in report["historical_evidence"]])
            assert (directory / strategy / "memory.sqlite3").is_file()
        assert histories[0] == histories[1]
        for path, digest in run["comparison"]["fairness"]["input_sha256"].items():
            assert hashlib.sha256((directory / "inputs" / path).read_bytes()).hexdigest() == digest


def test_registered_images_are_hash_bound_and_no_arbitrary_paths(demo):
    service, runs = demo
    run = runs["moved"]
    key = run["images"]["box_in_scene.png"].rsplit("/", 1)[1]
    path = service.asset(run["run_id"], key)
    original = path.read_bytes()
    try:
        path.write_bytes(b"changed after matching")
        with pytest.raises(ValueError, match="changed"):
            service.asset(run["run_id"], key)
    finally:
        path.write_bytes(original)
    with pytest.raises(KeyError):
        service.asset(run["run_id"], "../../README.md")


def test_runner_validates_choices_and_busy_state_before_work(demo):
    service, _ = demo
    with pytest.raises(ValueError, match="Unknown"):
        service.run("../../secret", "memory_first")
    with service._lock:
        with pytest.raises(DemoBusyError):
            service.run("moved", "memory_first")


@pytest.fixture
def server(demo):
    service, _ = demo
    server = make_server(service, 0, legacy_web_dir=Path(__file__).parent / "fixtures" / "legacy_web")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)


def request(server, method, path, body=None, headers=None):
    connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=10)
    connection.request(method, path, body=body, headers=headers or {})
    response = connection.getresponse()
    result = response.status, dict(response.getheaders()), response.read()
    connection.close()
    return result


def test_http_reports_images_and_downloads_match_real_execution(server, demo):
    _, runs = demo
    run = runs["moved"]
    status, headers, body = request(server, "GET", "/api/config")
    assert status == 200 and len(json.loads(body)["scenarios"]) == 3
    status, headers, body = request(server, "GET", run["downloads"]["report"])
    assert status == 200 and json.loads(body) == run["report"]
    assert "attachment" in headers["Content-Disposition"]
    status, headers, body = request(server, "GET", run["images"]["box_in_scene.png"])
    assert status == 200 and headers["Content-Type"] == "image/png"
    assert hashlib.sha256(body).hexdigest() == run["report"]["evidence"][1]["observation"]["image_hash"]


@pytest.mark.parametrize("path,marker", [("/", b"HomeTrace"), ("/app.js", b"prefixState"), ("/style.css", b".workspace")])
def test_static_assets_available_from_installed_package(server, path, marker):
    status, headers, body = request(server, "GET", path)
    assert status == 200 and marker in body
    assert "script-src 'self'" in headers["Content-Security-Policy"]


@pytest.mark.parametrize("path", ["/../pyproject.toml", "/.git/config", "/api/runs/abc/downloads/report", "/api/runs/" + "0" * 32 + "/images/unknown"])
def test_http_only_serves_explicit_artifacts(server, path):
    assert request(server, "GET", path)[0] == 404


@pytest.mark.parametrize("headers,status", [
    ({"Host": "evil.example"}, 403),
    ({"Origin": "https://evil.example", "Content-Type": "application/json"}, 403),
    ({"Content-Type": "text/plain"}, 415),
])
def test_http_rejects_external_hosts_origins_and_form_posts(server, headers, status):
    assert request(server, "POST", "/api/run", '{"scenario":"moved","strategy":"memory_first"}', headers)[0] == status


@pytest.mark.parametrize("body", ['{}', '{"scenario":[],"strategy":"memory_first"}', 'not json', '{"scenario":"fake","strategy":"memory_first"}'])
def test_http_rejects_invalid_run_requests(server, body):
    assert request(server, "POST", "/api/run", body, {"Content-Type": "application/json"})[0] == 400
