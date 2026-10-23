"""Local identities, independent history and optional-case failure isolation.

Tests use copied public OpenCV photos; they are not team-photo experiments.
"""

import json
from pathlib import Path
import shutil
import subprocess

import pytest

from hometrace.demo_cases import load_case
from hometrace.demo_service import DemoService

SAMPLES = Path(__file__).resolve().parents[1] / "examples/recorded_images"


@pytest.fixture
def case_config(tmp_path):
    root = tmp_path / "private-case"
    shutil.copytree(SAMPLES, root)
    (root / "reference.png").write_bytes((root / "box.png").read_bytes())
    history = json.loads((root / "history.json").read_text(encoding="utf-8"))
    history["observations"][0]["image_path"] = "box_in_scene.png"
    (root / "history.json").write_text(json.dumps(history), encoding="utf-8")
    config = {
        "schema_version": 1, "case_id": "different-object", "label": "Public-photo integration fixture",
        "object_id": "test-textured-object", "reference": "reference.png", "image_root": ".",
        "source_notice": "Public OpenCV photos, test fixture, simulated navigation",
        "history_note": "Independent photo, results determined by actual detector",
    }
    path = root / "case.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    return path


def test_local_identity_and_reference_are_used_by_real_cli(case_config, tmp_path):
    pytest.importorskip("cv2")
    service = DemoService(SAMPLES, tmp_path / "runs", case_configs=[case_config])
    run = service.run("moved", "memory_first", "different-object")
    assert run["report"]["object_id"] == "test-textured-object"
    assert run["case"]["reference"] == "reference.png"
    assert run["case"]["private"] is True
    assert "root" not in run["case"]
    assert "reference.png" in run["images"]
    # The current B photo equals historical evidence: cannot claim a new finding.
    assert run["report"]["result_status"] != "FOUND"
    assert any(e["result"].get("reason") == "replayed_image_content" for e in run["report"]["events"])


@pytest.mark.parametrize("field,value", [
    ("case_id", "public"), ("case_id", "../escape"), ("schema_version", True),
    ("object_id", "sample-box"), ("image_root", ".."), ("reference", "../secret.png"),
    ("reference", "missing.png"), ("source_notice", ""), ("label", []),
])
def test_bad_local_config_is_rejected(case_config, field, value):
    raw = json.loads(case_config.read_text(encoding="utf-8"))
    raw[field] = value
    case_config.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError):
        load_case(case_config)


@pytest.mark.parametrize("change", ["reference_history", "older_search", "mixed_basis", "missing_image", "answer_label"])
def test_input_validation_protects_history_and_provenance(case_config, change):
    path = case_config.parent / ("history.json" if change == "reference_history" else "moved.json")
    raw = json.loads(path.read_text(encoding="utf-8"))
    if change == "reference_history":
        raw["observations"][0]["image_path"] = "box.png"
    elif change == "older_search":
        raw["observations"][0]["captured_at"] = "2000-01-01T00:00:00+00:00"
    elif change == "mixed_basis":
        raw["timestamp_basis"] = "declared_capture"
    elif change == "missing_image":
        raw["observations"][0]["image_path"] = "missing.png"
    else:
        raw["observations"][0]["target_present"] = True
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError):
        load_case(case_config)


def test_invalid_optional_case_does_not_disable_public_cases(tmp_path):
    service = DemoService(SAMPLES, tmp_path / "runs", case_configs=[tmp_path / "absent.json"])
    assert [c["case_id"] for c in service.config()["cases"]] == ["public"]
    assert service.config()["unavailable_cases"]
    with pytest.raises(ValueError, match="unavailable"):
        service.run("moved", "memory_first", "absent")


def test_duplicate_case_is_reported_without_replacing_first(case_config, tmp_path):
    service = DemoService(SAMPLES, tmp_path / "runs", case_configs=[case_config, case_config])
    assert len(service.cases) == 2
    assert service.unavailable_cases[0]["error"] == "Duplicate case_id"


def test_private_snapshots_cannot_enter_unignored_git_directory(case_config, tmp_path):
    repository = tmp_path / "repository"
    repository.mkdir()
    subprocess.run(["git", "init", str(repository)], check=True, capture_output=True)
    service = DemoService(SAMPLES, repository / "public-preview", case_configs=[case_config])
    with pytest.raises(ValueError, match="ignored directory"):
        service.run("moved", "memory_first", "different-object")
    assert list(service.output_dir.iterdir()) == []
    (repository / ".gitignore").write_text("artifacts/\n", encoding="utf-8")
    safe = DemoService(SAMPLES, repository / "artifacts/private", case_configs=[case_config])
    safe._check_private_output()


def test_startup_validation_cannot_be_bypassed_by_later_image_change(case_config, tmp_path):
    service = DemoService(SAMPLES, tmp_path / "runs", case_configs=[case_config])
    # A later same-byte replacement with a different filename is still not independent.
    (case_config.parent / "box_in_scene.png").write_bytes((case_config.parent / "reference.png").read_bytes())
    with pytest.raises(ValueError, match="independent"):
        service.run("moved", "memory_first", "different-object")
    assert not list(service.output_dir.rglob("memory.sqlite3"))
