"""Software fixtures only; no fixture is evidence of household recognition."""

import copy
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"tools"))
import vision_r1 as r1
import evaluate_vision_r1 as runner


def record(rid="a", oid="target", **changes):
    return {"reference_id": rid, "object_instance_id": oid, "sha256": rid * 64,
            "view_id": rid, "capture_id": rid, "background_id": rid, "visible_surface": "front",
            "surface_extent_id": "front", "source_type": "synthetic", "dhash": 0 if rid == "a" else 255,
            "eligibility_reasons": [], **changes}


def attempt(rid="a", box=None, status="FOUND", **changes):
    return {"reference_id": rid, "raw_status": status, "bbox": [10, 20, 110, 120] if box is None else box,
            "executed": True, **changes}


def test_two_independent_consistent_views_return_experimental_only():
    out = r1.aggregate([record(), record("b")], [attempt(), attempt("b", [12, 21, 112, 121])], "target")
    assert out["status"] == "EXPERIMENTAL_ACCEPTED" and out["bbox"] == [10, 20, 110, 120]
    assert not out["identity_confirmed"] and not out["production_integration"]


@pytest.mark.parametrize("change", [{"sha256": "a"*64}, {"view_id": "a"}, {"capture_id": "a"},
    {"background_id": "a"}, {"visible_surface": "back"}, {"surface_extent_id": "smaller_patch"},
    {"dhash": 15}, {"eligibility_reasons": ["quality_rejected"]}, {"source_type": "real"}])
def test_redundant_or_incompatible_views_cannot_form_quorum(change):
    out = r1.aggregate([record(), record("b", **change)], [attempt(), attempt("b")], "target")
    assert out["reason"] == "insufficient_independent_references" and not out["executed"]


def test_one_success_is_not_any_reference_or():
    out = r1.aggregate([record(), record("b")], [attempt(), attempt("b", status="UNKNOWN")], "target")
    assert out["reason"] == "insufficient_consistent_support" and out["executed"]


def test_extra_conflict_cannot_be_cherry_picked_out():
    out = r1.aggregate([record(), record("b"), record("c")],
                       [attempt(), attempt("b"), attempt("c", [200, 200, 300, 300])], "target")
    assert out["reason"] == "conflicting_reference_locations"


def test_wrong_instance_at_same_location_rejected():
    out = r1.aggregate([record(), record("b"), record("c", "other-instance")],
                       [attempt(), attempt("b"), attempt("c")], "target")
    assert out["reason"] == "ambiguous_instance"


def test_rival_elsewhere_does_not_block_consistent_target():
    out = r1.aggregate([record(), record("b"), record("c", "other-instance")],
                       [attempt(), attempt("b"), attempt("c", [200, 200, 300, 300])], "target")
    assert out["status"] == "EXPERIMENTAL_ACCEPTED" and out["rival_coverage"] == "configured"


def test_unusable_rival_cannot_claim_completed_negative_control():
    out = r1.aggregate([record(), record("b"), record("c", "other", eligibility_reasons=["bad"])],
                       [attempt(), attempt("b")], "target")
    assert out["reason"] == "rival_control_unavailable" and not out["executed"]


def test_missing_attempt_is_not_success():
    out = r1.aggregate([record(), record("b")], [attempt()], "target")
    assert out["reason"] == "reference_attempt_unavailable" and not out["executed"]


def test_replay_returns_unknown():
    out = r1.aggregate([record(), record("b")], [attempt(), attempt("b")], "target", replay=True)
    assert out["reason"] == "reference_image_replay" and not out["executed"]


@pytest.mark.parametrize("box", [[1, 2, 1, 3], [0, 0, float("nan"), 4], [True, 0, 20, 40], [-1, 0, 20, 40]])
def test_invalid_support_box_rejected(box):
    assert r1.aggregate([record(), record("b")], [attempt(box=box), attempt("b")], "target")["reason"] == "invalid_support_box"


@pytest.fixture
def image_manifest(tmp_path):
    cv = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    rng = np.random.default_rng(816)
    texture = rng.integers(0, 256, (320, 320), dtype=np.uint8)
    # Generated pixel texture and two fixed projective views: software only.
    src = np.float32([[0, 0], [319, 0], [319, 319], [0, 319]])
    dst = np.float32([[16, 8], [305, 20], [312, 306], [8, 315]])
    warped = cv.warpPerspective(texture, cv.getPerspectiveTransform(src, dst), (320, 320))
    scene = np.zeros((500, 600), dtype=np.uint8)
    scene[80:400, 140:460] = texture
    wrong = rng.integers(0, 256, (500, 600), dtype=np.uint8)
    files = {"a.png": texture, "b.png": warped, "scene.png": scene, "blank.png": np.zeros_like(scene), "wrong.png": wrong}
    for name, pixels in files.items():
        ok, encoded = cv.imencode(".png", pixels)
        assert ok
        (tmp_path/name).write_bytes(encoded.tobytes())
    refs = [{"reference_id": rid, "object_instance_id": "fixture-target", "path": rid+".png",
             "sha256": r1.sha256(tmp_path/(rid+".png")), "roi": [0, 0, 320, 320],
             "view_id": rid, "capture_id": rid, "background_id": rid, "visible_surface": "front",
             "surface_extent_id": "front", "source_type": "synthetic", "identity_reviewed": True,
             "roi_reviewed": True, "background_review": "object_dominant"} for rid in ("a", "b")]
    scenes = [{"sample_id": name, "object_instance_id": "fixture-target", "path": name,
               "sha256": r1.sha256(tmp_path/name), "source_type": "synthetic"} for name in ("scene.png", "blank.png", "wrong.png")]
    return tmp_path, {"schema_version": 1, "objects": [{"object_instance_id": "fixture-target", "baseline_reference_id": "a", "references": refs}], "scenes": scenes}


def test_real_opencv_software_fixture_positive_empty_and_wrong_instance(image_manifest):
    root, manifest = image_manifest
    experiment = r1.MultiReferenceExperiment(manifest, root)
    positive = experiment.infer(manifest["scenes"][0])
    assert all(r["status"] == "EXPERIMENTAL_ACCEPTED" for r in positive)
    assert r1.box_iou(positive[1]["bbox"], [140, 80, 460, 400]) >= .5
    for scene in manifest["scenes"][1:]:
        assert all(r["status"] == "UNKNOWN" for r in experiment.infer(scene))


def test_no_metadata_or_label_can_bypass_quality_gate(image_manifest):
    root, manifest = image_manifest
    ref = manifest["objects"][0]["references"][0]
    ref.update(path="blank.png", sha256=r1.sha256(root/"blank.png"))
    experiment = r1.MultiReferenceExperiment(manifest, root)
    rec = experiment.registrations[0]
    assert not rec["quality_pass"] and rec["sharpness"] == 0 and rec["keypoints"] == 0
    assert experiment.infer(manifest["scenes"][0])[1]["executed"] is False


@pytest.mark.parametrize("mutation", ["hash", "outside", "label", "gt", "source", "baseline", "review", "roi", "duplicate_scene", "too_many", "unknown_object"])
def test_manifest_rejects_bad_or_leaking_contract(image_manifest, mutation):
    root, manifest = image_manifest
    ref = manifest["objects"][0]["references"][0]
    scene = manifest["scenes"][0]
    if mutation == "hash": ref["sha256"] = "0"*64
    elif mutation == "outside": ref["path"] = "../outside.png"
    elif mutation == "label": scene["label"] = "positive"
    elif mutation == "gt": scene["target_box"] = [1, 2, 3, 4]
    elif mutation == "source": scene["source_type"] = "real"
    elif mutation == "baseline": manifest["objects"][0]["baseline_reference_id"] = "unknown"
    elif mutation == "review": ref["identity_reviewed"] = "yes"
    elif mutation == "roi": ref["roi"] = [True, 0, 300, 300]
    elif mutation == "duplicate_scene": manifest["scenes"].append(copy.deepcopy(scene))
    elif mutation == "too_many": manifest["objects"][0]["references"] *= 4
    elif mutation == "unknown_object": scene["object_instance_id"] = "other"
    with pytest.raises(ValueError):
        r1.validate_manifest(manifest, root)


def test_duplicate_reference_bytes_are_not_extra_views(image_manifest):
    root, manifest = image_manifest
    a, b = manifest["objects"][0]["references"]
    b.update(path=a["path"], sha256=a["sha256"])
    experiment = r1.MultiReferenceExperiment(manifest, root)
    assert all("duplicate_reference_bytes" in r["eligibility_reasons"] for r in experiment.registrations)
    assert not experiment.infer(manifest["scenes"][0])[1]["executed"]


def test_public_output_omits_private_identifiers_boxes_and_hashes(image_manifest):
    root, manifest = image_manifest
    experiment = r1.MultiReferenceExperiment(manifest, root)
    rows = experiment.infer(manifest["scenes"][0])
    public, quality, _ = runner.public_results(rows, experiment.registrations)
    rendered = repr((public, quality))
    assert "fixture-target" not in rendered and "scene.png" not in rendered and "bbox" not in rendered
    assert manifest["objects"][0]["references"][0]["sha256"] not in rendered


def test_rerunning_fixture_is_deterministic_except_timing(image_manifest):
    root, manifest = image_manifest
    experiment = r1.MultiReferenceExperiment(manifest, root)
    first, second = experiment.infer(manifest["scenes"][0]), experiment.infer(manifest["scenes"][0])
    def semantic(rows):
        for row in rows:
            row.pop("total_elapsed_ms")
            for a in row["attempts"]:
                a["diagnostics"].pop("elapsed_ms", None)
        return rows
    assert semantic(first) == semantic(second)


def test_runner_writes_predictions_before_loading_labels_and_refuses_overwrite(image_manifest, monkeypatch):
    import json
    root, manifest = image_manifest
    manifest_path, labels_path = root/"manifest.json", root/"labels.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    labels = [{"sample_id": s["sample_id"], "object_instance_id": s["object_instance_id"], "label": "uncertain", "source_type": "synthetic",
               "split": "software_fixture", "capture_batch": "fixture", "target_box": None,
               "box_source": "none", "instance_reviews": {}} for s in manifest["scenes"]]
    labels_path.write_text(json.dumps(labels), encoding="utf-8")
    output = root/"run"
    original_read = runner.read
    def checked_read(path):
        if path == labels_path:
            assert (output/"predictions.private.json").is_file()
            assert len(original_read(output/"predictions.private.json")) == 6
        return original_read(path)
    # Only this software fixture bypasses ignored-directory policy, tested below.
    monkeypatch.setattr(runner, "require_private", lambda p, repo: p)
    monkeypatch.setattr(runner, "read", checked_read)
    result = runner.run(root, manifest_path, labels_path, output, Path(__file__).resolve().parents[1])
    assert result["source_counts"] == {"real": 0, "synthetic": 3, "augmented": 0}
    assert all(g["restricted_demo_gate"] == "BLOCKED" for groups in result["metrics"]["methods"].values() for g in groups.values())
    with pytest.raises(ValueError, match="never overwrite"):
        runner.run(root, manifest_path, labels_path, output, Path(__file__).resolve().parents[1])


def test_runner_rejects_output_outside_ignored_repo(tmp_path):
    with pytest.raises(ValueError, match="ignored"):
        runner.require_private(tmp_path, Path(__file__).resolve().parents[1])


def test_example_schema_includes_all_fields_but_cannot_masquerade_as_registration():
    import json
    repo = Path(__file__).resolve().parents[1]
    manifest = json.loads((repo/"examples/vision_r1/manifest.example.json").read_text(encoding="utf-8"))
    for ref in manifest["objects"][0]["references"]:
        assert set(ref) == r1.REF_FIELDS
        assert not ref["identity_reviewed"] and not ref["roi_reviewed"]
    with pytest.raises(ValueError):
        r1.validate_manifest(manifest, repo)


def test_exact_duplicate_scene_with_new_id_cannot_inflate_samples(image_manifest):
    root, manifest = image_manifest
    manifest["scenes"].append({**manifest["scenes"][0], "sample_id": "duplicate"})
    with pytest.raises(ValueError, match="Duplicate scene bytes"):
        r1.validate_manifest(manifest, root)


def test_lossless_reencoding_of_reference_is_unexecuted_replay(image_manifest):
    root, manifest = image_manifest
    import cv2 as cv
    import numpy as np
    pixels = cv.imdecode(np.frombuffer((root/"a.png").read_bytes(), np.uint8), cv.IMREAD_GRAYSCALE)
    ok, encoded = cv.imencode(".png", pixels, [cv.IMWRITE_PNG_COMPRESSION, 9])
    assert ok
    (root/"reencoded.png").write_bytes(encoded.tobytes())
    scene = {**manifest["scenes"][0], "path": "reencoded.png", "sha256": r1.sha256(root/"reencoded.png")}
    assert scene["sha256"] != manifest["objects"][0]["references"][0]["sha256"]
    manifest["scenes"] = [scene]
    out = r1.MultiReferenceExperiment(manifest, root).infer(scene)
    assert all(r["reason"] == "reference_image_replay" and not r["executed"] for r in out)


def test_fingerprint_changes_when_registration_contract_changes(image_manifest):
    root, manifest = image_manifest
    first = r1.MultiReferenceExperiment(manifest, root).infer(manifest["scenes"][0])
    manifest["objects"][0]["references"][1]["background_id"] = "changed-review"
    second = r1.MultiReferenceExperiment(manifest, root).infer(manifest["scenes"][0])
    assert first[0]["bbox"] == second[0]["bbox"]
    assert first[0]["prediction_fingerprint"] != second[0]["prediction_fingerprint"]
