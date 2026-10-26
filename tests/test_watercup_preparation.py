"""Preparation contract tests use generated textures, never household evidence."""

import copy
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"tools"))
import prepare_watercup_diagnostic as watercup
from vision_r1 import sha256


@pytest.fixture
def inputs(tmp_path, monkeypatch):
    cv = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    root = tmp_path/"images"
    root.mkdir()
    review = {"schema_version": 1, "photos": {}}
    for i in range(1, 19):
        name = f"{i}.jpg"
        rng = np.random.default_rng(i)
        pixels = rng.integers(0, 256, (200, 200), dtype=np.uint8)
        ok, encoded = cv.imencode(".jpg", pixels)
        assert ok
        (root/name).write_bytes(encoded.tobytes())
        item = {"sha256": sha256(root/name), "candidate_roi": [10, 10, 190, 190],
            "capture_batch": "unknown", "label_confirmed_by_owner": False,
            "proposed_label": "positive" if i in (8, 12, 13, 14) else "negative"}
        if i in (1, 6, 10):
            oid = "fixture-rival" if i == 10 else "fixture-target"
            item["reference"] = {"reference_id": f"r{i}", "object_instance_id": oid, "path": name,
                "sha256": item["sha256"], "roi": item["candidate_roi"], "view_id": "front",
                "visible_surface": "front", "surface_extent_id": "unknown", "capture_id": "unknown",
                "background_id": "unknown", "source_type": "real", "identity_reviewed": i in (1, 6),
                "roi_reviewed": False, "background_review": "pending"}
        review["photos"][name] = item
    path = tmp_path/"review.json"
    path.write_text(json.dumps(review), encoding="utf-8")
    # Temporary software fixture directories only. CLI never bypasses privacy.
    monkeypatch.setattr(watercup, "require_private", lambda p, repo: p)
    return root, path, tmp_path/"output", tmp_path, review


def save(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")


def test_draft_is_blocked_and_never_promotes_candidates_to_truth(inputs):
    root, path, output, repo, review = inputs
    before = {p.name: sha256(p) for p in root.iterdir()}
    result = watercup.prepare(root, path, output, repo)
    labels = watercup.read(output/"labels.private.json")
    manifest = watercup.read(output/"manifest.draft.private.json")
    assert result["qualification_gate"] == "BLOCKED"
    assert result["unconfirmed_scene_labels"] == 10
    assert all(l["label"] == "uncertain" and l["target_box"] is None and l["box_source"] == "none" for l in labels)
    assert all(s["path"] != "10.jpg" for s in manifest["scenes"])
    assert all(l["split"] == "diagnostic_reused" for l in labels)
    assert all(r["capture_id"] == "unknown" for o in manifest["objects"] for r in o["references"])
    assert before == {p.name: sha256(p) for p in root.iterdir()}


def test_confirmed_labels_do_not_create_localization_truth(inputs):
    root, path, output, repo, review = inputs
    for name in watercup.SCENE_FILES:
        review["photos"][name].update(label_confirmed_by_owner=True, label_confirmation_source="TEST ONLY owner statement")
    save(path, review)
    watercup.prepare(root, path, output, repo)
    labels = watercup.read(output/"labels.private.json")
    assert sum(l["label"] == "positive" for l in labels) == 4
    assert all(l["target_box"] is None and not l["instance_reviews"] for l in labels)


def test_owner_roi_approval_cannot_invent_independent_captures(inputs):
    root, path, output, repo, review = inputs
    for name in watercup.REFERENCE_FILES:
        ref = review["photos"][name]["reference"]
        ref.update(identity_reviewed=True, roi_reviewed=True,
                   background_review="object_dominant", surface_extent_id="front-body",
                   view_id="front-" + name, background_id="background-" + name)
    save(path, review)
    result = watercup.prepare(root, path, output, repo)
    assert result["qualification_gate"] == "BLOCKED"
    assert not result["target_reference_pair_eligible"] and not result["rival_eligible"]
    assert all(r["eligibility_reasons"] == ["capture_id_unknown"] for r in result["registration"])
    assert result["unconfirmed_scene_labels"] == 10


@pytest.mark.parametrize("mutation", ["missing_image", "unexpected_image", "hash", "roi", "bad_roi", "same_rival", "label_without_source", "confirmation_string", "review_missing_photo", "blank_source", "number_source", "blank_batch"])
def test_invalid_inputs_do_not_fall_back_or_publish_outputs(inputs, mutation):
    root, path, output, repo, review = inputs
    if mutation == "missing_image": (root/"18.jpg").unlink()
    elif mutation == "unexpected_image": (root/"19.jpg").write_bytes((root/"18.jpg").read_bytes())
    elif mutation == "hash": review["photos"]["1.jpg"]["sha256"] = "0"*64
    elif mutation == "roi": review["photos"]["1.jpg"]["reference"]["roi"] = [0, 0, 100, 100]
    elif mutation == "bad_roi": review["photos"]["18.jpg"]["candidate_roi"] = [0, 0, 1000, 1000]
    elif mutation == "same_rival": review["photos"]["10.jpg"]["reference"]["object_instance_id"] = "fixture-target"
    elif mutation == "label_without_source": review["photos"]["8.jpg"]["label_confirmed_by_owner"] = True
    elif mutation == "confirmation_string": review["photos"]["8.jpg"]["label_confirmed_by_owner"] = "true"
    elif mutation == "review_missing_photo": del review["photos"]["18.jpg"]
    elif mutation == "blank_source": review["photos"]["8.jpg"].update(label_confirmed_by_owner=True, label_confirmation_source=" ")
    elif mutation == "number_source": review["photos"]["8.jpg"].update(label_confirmed_by_owner=True, label_confirmation_source=123)
    elif mutation == "blank_batch": review["photos"]["8.jpg"]["capture_batch"] = " "
    save(path, review)
    with pytest.raises(ValueError): watercup.prepare(root, path, output, repo)
    assert not output.exists()


def test_preserves_existing_output(inputs):
    root, path, output, repo, _ = inputs
    output.mkdir()
    sentinel = output/"sentinel.txt"
    sentinel.write_text("existing evidence")
    with pytest.raises(ValueError, match="never overwrite"):
        watercup.prepare(root, path, output, repo)
    assert sentinel.read_text() == "existing evidence"


def test_no_missing_directory_fallback(inputs):
    root, path, output, repo, _ = inputs
    with pytest.raises(ValueError, match="no fallback"):
        watercup.prepare(root/"missing", path, output, repo)
