"""Synthetic inputs test diagnostic boundaries, not household recognition."""

import copy
import json
from pathlib import Path
import sys

import pytest

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))
import evaluate_vision_r0 as r0


@pytest.mark.parametrize("box", [[-1, 0, 10, 10], [0, 0, 51, 10], [0, 0, 0, 10],
    [True, 0, 10, 10], [float("nan"), 0, 10, 10], [0, 0, float("inf"), 10]])
def test_candidate_crop_rejects_invalid_coordinates(box):
    with pytest.raises(ValueError):
        r0.crop_bounds(box, 50, 40)


def test_crop_rounding_and_original_coordinate_mapping():
    assert r0.crop_bounds([1.8, 2.3, 20.1, 30.8], 50, 40) == (1, 2, 21, 31)
    assert r0.map_box([3, 4, 8, 9], (10, 20)) == [13, 24, 18, 29]
    assert r0.map_box(None, (10, 20)) is None


@pytest.fixture
def bound_rows(tmp_path):
    reference, scene = tmp_path/"reference.jpg", tmp_path/"scene.jpg"
    reference.write_bytes(b"TEST_ONLY-reference")
    scene.write_bytes(b"TEST_ONLY-scene")
    manifest = {"files": [
        {"path": "reference.jpg", "group": "fixture", "sha256": r0.digest(reference), "width": 100, "height": 100},
        {"path": "scene.jpg", "group": "fixture", "sha256": r0.digest(scene), "width": 100, "height": 100}]}
    suggestions = {"fixture": {"file": "reference.jpg", "xyxy_original_pixels": [0, 0, 50, 50]}}
    protocol = {"parameters": {"test_only": True}, "weight_sha256": "test-only-weight"}
    row = {"request": {"scene": {"path": str(scene), "sha256": r0.digest(scene), "size": [100, 100]},
        "reference": {"path": str(reference), "sha256": r0.digest(reference)},
        "reference_roi": [0, 0, 50, 50], "parameters": protocol["parameters"], "weights": {"sha256": "test-only-weight"},
        "output": str(tmp_path/"job/inference")},
        "result": {"reason": "no_candidates", "candidates": [], "status": "UNKNOWN", "confirmed_identity": False, "provider_called": True},
        "private_details": {"returncode": 0, "network_disabled": True, "predict_ms": 1,
            "process_wall_ms": 2, "device": "test_only", "versions": {"test": "0"},
            "candidates": [], "status": "UNKNOWN", "confirmed_identity": False}}
    (tmp_path/"job/inference").mkdir(parents=True)
    (tmp_path/"job/request.private.json").write_text(json.dumps(row["request"]), encoding="utf-8")
    (tmp_path/"job/inference/result.private.json").write_text(json.dumps(row["private_details"]), encoding="utf-8")
    return tmp_path, manifest, suggestions, protocol, row


def test_neural_binding_accepts_complete_fixture(bound_rows):
    root, manifest, suggestions, protocol, row = bound_rows
    result = r0.bind_neural([row], root, manifest, suggestions, protocol, root)
    assert result["scene.jpg"]["candidates"] == []


@pytest.mark.parametrize("mutation", ["duplicate", "missing", "sha", "roi", "parameters", "worker_failure", "candidate_outside", "wrong_scene",
    "injected_candidate", "status", "confirmed_identity", "provider_called", "raw_worker_changed", "raw_request_changed", "output_outside"])
def test_neural_binding_fails_closed(bound_rows, mutation):
    root, manifest, suggestions, protocol, row = bound_rows
    rows = [copy.deepcopy(row)]
    if mutation == "duplicate": rows.append(copy.deepcopy(row))
    elif mutation == "missing": rows = []
    elif mutation == "sha": rows[0]["request"]["scene"]["sha256"] = "wrong"
    elif mutation == "roi": rows[0]["request"]["reference_roi"] = [1, 0, 50, 50]
    elif mutation == "parameters": rows[0]["request"]["parameters"] = {"changed": True}
    elif mutation == "worker_failure": rows[0]["result"]["reason"] = "provider_error"
    elif mutation == "candidate_outside": rows[0]["result"]["candidates"] = [{"bbox": [0, 0, 101, 100], "score": .9, "class_id": 0}]
    elif mutation == "wrong_scene": rows[0]["request"]["scene"]["path"] = str(root/"other.jpg")
    elif mutation == "injected_candidate": rows[0]["result"]["candidates"] = [{"bbox": [1, 1, 20, 20], "score": .9, "class_id": 0}]
    elif mutation == "status": rows[0]["result"]["status"] = "FOUND"
    elif mutation == "confirmed_identity": rows[0]["result"]["confirmed_identity"] = True
    elif mutation == "provider_called": rows[0]["result"]["provider_called"] = False
    elif mutation == "raw_worker_changed":
        path=root/"job/inference/result.private.json"
        obj=json.loads(path.read_text()); obj["predict_ms"]=999; path.write_text(json.dumps(obj))
    elif mutation == "raw_request_changed":
        path=root/"job/request.private.json"
        obj=json.loads(path.read_text()); obj["reference_roi"]=[2,2,50,50]; path.write_text(json.dumps(obj))
    elif mutation == "output_outside": rows[0]["request"]["output"] = str(root.parent/"outside")
    with pytest.raises(ValueError):
        r0.bind_neural(rows, root, manifest, suggestions, protocol, root)


def test_composite_verifies_all_proposals_and_maps_to_scene(tmp_path, monkeypatch):
    np = pytest.importorskip("numpy")
    calls = []
    monkeypatch.setattr(r0, "save_pixels", lambda path, pixels: calls.append((path, pixels.shape)))
    monkeypatch.setattr(r0, "pair", lambda *args: {"status": "FOUND", "bbox": [1, 2, 8, 9],
        "diagnostics": {"reason": "TEST_ONLY_geometry"}})
    proposals = [{"bbox": [10, 20, 30, 40]}, {"bbox": [40, 50, 60, 70]}]
    result = r0.composite(tmp_path/"reference.png", np.zeros((100, 100), dtype=np.uint8), proposals, tmp_path)
    assert len(calls) == len(result["attempts"]) == 2
    assert result["bbox"] == [11, 22, 18, 29]
    assert result["attempts"][1]["result"]["bbox"] == [41, 52, 48, 59]
    assert result["identity_confirmed"] is False
    assert result["production_integration"] is False


def test_no_candidates_cannot_confirm_target(tmp_path):
    result = r0.composite(tmp_path/"unused.png", None, [], tmp_path)
    assert result["status"] == "UNKNOWN" and result["bbox"] is None
    assert result["proposal_count"] == 0 and result["attempts"] == []


def test_public_row_has_no_private_image_coordinates_or_paths():
    row = dict(method="SIFT_ROI", sample_id="fixture/scene_01", group="fixture", label="positive",
        split="diagnostic_reused", status="UNKNOWN", reason="no_verified_match", executed=True,
        signal_kind="geometric_acceptance", candidate_count=0, localized_target_verified=None,
        image_path="PRIVATE-PATH", image_sha256="PRIVATE-HASH", reference_roi=[1, 2, 3, 4],
        result={"bbox": [1, 2, 3, 4], "diagnostics": {"good_matches": 2, "reference_roi": [1, 2, 3, 4], "reference_image_hash": "PRIVATE-HASH"}})
    result = r0.public_row(row)
    assert "PRIVATE" not in repr(result)
    assert "bbox" not in repr(result) and "roi" not in repr(result)
    assert result["metrics"] == {"good_matches": 2}


def test_reference_rejection_not_scored_as_executed_negative(monkeypatch):
    monkeypatch.setattr(r0, "experimental_match", lambda *args: {"status": "UNKNOWN", "bbox": None,
        "diagnostics": {"reason": "reference_low_sharpness_or_texture"}})
    assert not r0.pair(Path("unused"), Path("unused"), "SIFT")["executed"]
