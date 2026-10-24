"""Offline runner tests: synthetic pixels and mocked workers are not model evidence."""

import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.fixture
def runner(monkeypatch):
    tools = Path(__file__).resolve().parents[1] / "tools"
    monkeypatch.syspath_prepend(str(tools))
    spec = importlib.util.spec_from_file_location("evaluate_yoloe_under_test", tools / "evaluate_yoloe.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def experiment(tmp_path, runner):
    cv = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
    (repo / ".gitignore").write_text("local_data/\nartifacts/\n", encoding="utf-8")
    root = repo / "local_data/private-synthetic-fixture"
    root.mkdir(parents=True)
    files, prompts = [], {}
    roles = ("reference_candidate", "positive_observed", "negative", "uncertain",
             "alternative_reference", "negative")
    for group in ("earbud", "panda", "keys", "tissue"):
        directory = root / group / "images"
        directory.mkdir(parents=True)
        for index, role in enumerate(roles):
            name = "scene_empty_wood.jpg" if index == 5 else f"PRIVATE_image_{index}.jpg"
            image = directory / name
            ok, encoded = cv.imencode(".jpg", np.full((64, 96), index * 30, dtype=np.uint8))
            assert ok
            image.write_bytes(encoded.tobytes())
            files.append({"group": group, "path": image.relative_to(root).as_posix(),
                          "width": 96, "height": 64, "size_bytes": image.stat().st_size,
                          "sha256": runner.digest(image), "role_hint": role})
        prompts[group] = {"file": f"{group}/images/PRIVATE_image_0.jpg",
                          "xyxy_original_pixels": [10, 8, 80, 60]}
    manifest = {"privacy": "local_only_not_for_public_git", "capture_time_verification": "unknown",
                "source": "user_uploaded_private_photos", "navigation": "none",
                "all_labels": "human_visual_review_only_not_detection_answers", "files": files}
    runner.write_json(root / "asset_manifest.json", manifest)
    runner.write_json(root / "REGISTRATION_ROI_SUGGESTIONS.json", prompts)
    (root / "SHA256SUMS.txt").write_text("".join(
        f"{row['sha256']}  {root.relative_to(repo).as_posix()}/{row['path']}\n" for row in files), encoding="utf-8")
    weights = repo / "artifacts/model/yoloe-11s-seg.pt"
    weights.parent.mkdir(parents=True)
    weights.write_bytes(b"Synthetic test weight binding, not an executable model")
    protocol = {"model": weights.name, "ultralytics": "8.3.221", "weight_sha256": runner.digest(weights),
                "weight_url": "https://github.com/ultralytics/assets/releases/download/v8.3.0/yoloe-11s-seg.pt",
                "base_commit": "e5732b4024d90cc190aedb77f98f626b11e982cd", "timeout_seconds_per_scene": 1,
                "parameters": {"conf": 0.25, "iou": 0.7, "imgsz": 640, "max_det": 100,
                               "half": False, "seed": 0, "device": "cpu"}}
    protocol_path = repo / "artifacts/protocol.json"
    runner.write_json(protocol_path, protocol)
    return {"root": root, "output": repo / "artifacts/test-output", "repo": repo,
            "python": Path(sys.executable), "weights": weights, "protocol_path": protocol_path,
            "protocol": protocol, "manifest": manifest, "prompts": prompts}


def execute(runner, experiment, **options):
    args = {name: experiment[name] for name in ("root", "output", "repo", "python", "weights", "protocol_path")}
    return runner.run(**args, **options)


def mock_worker(monkeypatch, runner, behavior):
    real_run = subprocess.run
    calls = []

    def run(command, **kwargs):
        if command[0] == "git":
            return real_run(command, **kwargs)
        request = json.loads(Path(command[-1]).read_text(encoding="utf-8"))
        calls.append(request)
        return behavior(command, request, kwargs)

    monkeypatch.setattr(runner.subprocess, "run", run)
    return calls


def success_worker(command, request, kwargs):
    output = Path(request["output"])
    output.mkdir()
    output.joinpath("result.private.json").write_text(json.dumps({
        "candidates": [{"bbox": [4, 6, 50, 60], "score": 0.91, "class_id": 0}],
        "predict_ms": 12.5, "device": "cpu", "network_disabled": True,
        "private_path": "PRIVATE_WORKER_METADATA", "reference_roi": request["reference_roi"]}), encoding="utf-8")
    return subprocess.CompletedProcess(command, 0, "synthetic worker only", "")


def test_private_inputs_and_outputs_must_be_inside_ignored_repository_paths(runner, tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
    (repo / ".gitignore").write_text("artifacts/\n", encoding="utf-8")
    runner.require_ignored(repo / "artifacts/new-output", repo)
    for path in (repo / "public-output", tmp_path / "artifacts/outside-repo"):
        with pytest.raises(ValueError, match="Git-ignored"):
            runner.require_ignored(path, repo)


def test_wrong_weight_hash_stops_before_worker_or_output_creation(runner, experiment, monkeypatch):
    experiment["weights"].write_bytes(b"Changed synthetic weights")
    calls = mock_worker(monkeypatch, runner, success_worker)
    with pytest.raises(ValueError, match="Weights"):
        execute(runner, experiment)
    assert not calls and not experiment["output"].exists()


def test_existing_experiment_output_is_preserved_and_never_reused(runner, experiment, monkeypatch):
    experiment["output"].mkdir()
    sentinel = experiment["output"] / "prior-evidence.txt"
    sentinel.write_text("Frozen synthetic evidence", encoding="utf-8")
    calls = mock_worker(monkeypatch, runner, success_worker)
    with pytest.raises(ValueError, match="already exists"):
        execute(runner, experiment)
    assert not calls and sentinel.read_text(encoding="utf-8") == "Frozen synthetic evidence"


def test_protocol_rejects_threshold_changes_and_unapproved_prediction_options(runner, experiment, monkeypatch):
    calls = mock_worker(monkeypatch, runner, success_worker)
    fixed = experiment["protocol"]["parameters"].copy()
    for changes in ({"conf": 0.01}, {"iou": 0.1}, {"imgsz": 1280}, {"max_det": 999},
                    {"half": True}, {"seed": 7}, {"device": "cuda:1"}, {"save": True}):
        protocol = dict(experiment["protocol"], parameters=dict(fixed, **changes))
        runner.write_json(experiment["protocol_path"], protocol)
        with pytest.raises(ValueError):
            execute(runner, experiment)
        assert not experiment["output"].exists()
    assert not calls


def test_labels_never_enter_worker_and_public_summary_excludes_private_evidence(runner, experiment, monkeypatch):
    calls = mock_worker(monkeypatch, runner, success_worker)
    summary = execute(runner, experiment)
    assert len(calls) == 20 and summary["gate"] == "NO_GO"
    for request in calls:
        assert set(request) == {"reference", "scene", "reference_roi", "weights", "parameters", "output"}
        assert set(request["scene"]) == {"path", "sha256", "size"}
        assert set(request["reference"]) == {"path", "sha256", "size"}
        assert request["scene"]["size"] == [96, 64]
        assert request["reference_roi"] == [10, 8, 80, 60]
        assert "role_hint" not in json.dumps(request) and "evaluation_label" not in json.dumps(request)
    encoded = json.dumps(summary)
    for forbidden in ("PRIVATE", str(experiment["root"]), "bbox", "reference_roi",
                      experiment["manifest"]["files"][1]["sha256"]):
        assert forbidden not in encoded
    assert summary["counts"]["positive"]["candidate_cases"] == 4
    assert summary["counts"]["negative"]["candidate_cases"] == 8
    assert summary["confirmed_instances"] == 0 and summary["integration_enabled"] is False


def test_timeout_preserves_private_diagnostics_and_publishes_blocked_smoke(runner, experiment, monkeypatch):
    def timeout(command, request, kwargs):
        assert kwargs["timeout"] == experiment["protocol"]["timeout_seconds_per_scene"]
        raise subprocess.TimeoutExpired(command, 1, output=b"PRIVATE partial stdout", stderr=b"PRIVATE partial stderr")
    calls = mock_worker(monkeypatch, runner, timeout)
    summary = execute(runner, experiment, smoke=True)
    assert len(calls) == 1 and summary["gate"] == "BLOCKED"
    assert summary["evaluations"][0]["reason"] == "provider_timeout"
    private = json.loads((experiment["output"] / "results.private.json").read_text(encoding="utf-8"))[0]
    case = experiment["output"] / "earbud-scene_05"
    assert "partial stdout" in (case / "stdout.private.txt").read_text(encoding="utf-8")
    assert "partial stderr" in (case / "stderr.private.txt").read_text(encoding="utf-8")
    assert private["private_details"]["process_wall_ms"] >= 0
    assert (experiment["output"] / "summary.public.json").is_file()
    assert "PRIVATE" not in json.dumps(summary)


def test_worker_exit_failure_is_unknown_and_cannot_pass_smoke_gate(runner, experiment, monkeypatch):
    def failed(command, request, kwargs):
        return subprocess.CompletedProcess(command, 2, "PRIVATE worker stdout", "PRIVATE worker exception")
    mock_worker(monkeypatch, runner, failed)
    summary = execute(runner, experiment, smoke=True)
    assert summary["gate"] == "BLOCKED" and summary["confirmed_instances"] == 0
    row = summary["evaluations"][0]
    assert row["status"] == "UNKNOWN" and row["reason"] == "provider_error"
    assert row["candidate_count"] == 0 and row["provider_called"] is True
    assert "PRIVATE" not in json.dumps(summary)


def test_zero_exit_without_result_file_is_not_success(runner, experiment, monkeypatch):
    mock_worker(monkeypatch, runner, lambda command, request, kwargs: subprocess.CompletedProcess(command, 0, "", ""))
    summary = execute(runner, experiment, smoke=True)
    assert summary["gate"] == "BLOCKED"
    assert summary["evaluations"][0]["reason"] == "provider_error"
    assert summary["evaluations"][0]["candidate_count"] == 0
