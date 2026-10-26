"""Generated images test software contracts only; these are not household results."""

import copy
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

Image = pytest.importorskip("PIL.Image")
TOOLS = Path(__file__).resolve().parents[1] / "tools"
spec = importlib.util.spec_from_file_location("vision_r2_data", TOOLS / "vision_r2_data.py")
data = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = data
spec.loader.exec_module(data)
spec = importlib.util.spec_from_file_location("train_vision_r2", TOOLS / "train_vision_r2.py")
driver = importlib.util.module_from_spec(spec)
spec.loader.exec_module(driver)


def review():
    return {"confirmed": True, "reviewer": "synthetic fixture author", "source": "software test only"}


@pytest.fixture
def inputs(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / ".gitignore").write_text("private/\n", encoding="utf-8")
    root = tmp_path / "private" / "originals"
    root.mkdir(parents=True)
    rows = []
    for index, (label, split) in enumerate((("present", "train"), ("absent", "train"), ("present", "val"), ("uncertain", "excluded"))):
        path = root / f"sample-{index}.png"
        Image.new("RGB", (100, 80), (index * 40, 30, 20)).save(path)
        rows.append({"sample_id": f"sample_{index}", "path": path.name, "sha256": data.sha256(path),
                     "group_id": f"scene_{index}", "capture_id": "unknown", "split": split,
                     "label": label, "label_review": review(),
                     "boxes": [{"xyxy": [10, 20, 70, 60], "bbox_scope": "full_visible_object", "review": review()}] if label == "present" else []})
    manifest = {"schema_version": 1, "class_name": "sony_mug", "purpose": "exploratory_fit",
                "source_type": "synthetic_software_fixture", "split_review": review(), "images": rows}
    path = tmp_path / "private" / "annotations.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return tmp_path, root, path, manifest


def write_manifest(inputs, manifest):
    inputs[2].write_text(json.dumps(manifest), encoding="utf-8")


def test_reviewed_dataset_preserves_originals_and_excludes_uncertain(inputs):
    repo, root, manifest_path, manifest = inputs
    before = {p.name: data.sha256(p) for p in root.iterdir()}
    output = repo / "private" / "dataset"
    result = data.prepare_dataset(manifest_path, root, output, repo)
    assert result["counts"] == {"train": 2, "val": 1, "excluded": 1}
    assert result["independent_test"] is False
    assert (output / "labels/train/sample_0.txt").read_text().strip() == "0 0.4000000000 0.5000000000 0.6000000000 0.5000000000"
    assert (output / "labels/train/sample_1.txt").read_text() == ""
    assert not (output / "images/excluded").exists()
    assert all("capture_id" not in sample for sample in result["samples"])
    assert {p.name: data.sha256(p) for p in root.iterdir()} == before
    assert data.sha256(output / "annotation.private.json") == data.sha256(manifest_path)


@pytest.mark.parametrize("change,match", [
    (lambda m: m["split_review"].update(confirmed=False), "split/group"),
    (lambda m: m["images"][0]["label_review"].update(confirmed=False), "label"),
    (lambda m: m["images"][0]["boxes"][0]["review"].update(confirmed=False), "box"),
    (lambda m: m["images"][0]["label_review"].update(source=" "), "provenance"),
    (lambda m: m["images"][0].update(group_id="unknown"), "group_id"),
    (lambda m: m["images"][2].update(group_id=m["images"][0]["group_id"]), "crosses"),
    (lambda m: m["images"][0].update(split="unknown"), "split"),
    (lambda m: m["images"][3].update(split="train"), "Uncertain"),
    (lambda m: m["images"][0].update(sha256="0" * 64), "SHA256"),
    (lambda m: m["images"][0]["boxes"][0].update(xyxy=[0, 0, 101, 50]), "outside"),
    (lambda m: m["images"][0]["boxes"][0].update(xyxy=[0, 0, float("nan"), 50]), "Invalid"),
    (lambda m: m["images"][0]["boxes"][0].update(bbox_scope="reference_logo_roi"), "full visible"),
    (lambda m: m["images"][0].update(boxes=[]), "disagree"),
    (lambda m: m["images"][1].update(boxes=copy.deepcopy(m["images"][0]["boxes"])), "disagree"),
    (lambda m: m["images"][2].update(split="excluded"), "train and development-val"),
    (lambda m: m["images"][0].update(path="../escape.png"), "escaping"),
])
def test_invalid_review_or_leakage_blocks_before_any_copy(inputs, change, match):
    repo, root, manifest_path, manifest = inputs
    change(manifest)
    write_manifest(inputs, manifest)
    output = repo / "private" / "dataset"
    with pytest.raises(data.Blocked, match=match):
        data.prepare_dataset(manifest_path, root, output, repo)
    assert not output.exists()


def test_same_bytes_cannot_cross_split_even_with_different_names(inputs):
    repo, root, path, manifest = inputs
    (root / "sample-2.png").write_bytes((root / "sample-0.png").read_bytes())
    manifest["images"][2]["sha256"] = data.sha256(root / "sample-2.png")
    with pytest.raises(data.Blocked, match="Byte-identical"):
        data.validate_manifest(manifest, root)


def test_public_output_and_overwrite_rejected(inputs):
    repo, root, path, _ = inputs
    with pytest.raises(data.Blocked, match="ignored"):
        data.prepare_dataset(path, root, repo / "public", repo)
    output = repo / "private" / "dataset"
    data.prepare_dataset(path, root, output, repo)
    with pytest.raises(data.Blocked, match="overwrite"):
        data.prepare_dataset(path, root, output, repo)


@pytest.mark.parametrize("trial,freeze,lr", [("freeze-backbone", 10, 0.01), ("low-lr-finetune", 0, 0.001)])
def test_fixed_training_contract(trial, freeze, lr):
    arguments = driver.build_train_args(Path("dataset"), Path("trial"), trial)
    assert arguments["freeze"] == freeze and arguments["lr0"] == lr
    assert arguments["epochs"] == 50 and arguments["batch"] == 2 and arguments["imgsz"] == 640
    assert arguments["seed"] == 19 and arguments["patience"] == 10 and arguments["workers"] == 0
    assert arguments["device"] == 0 and arguments["amp"] is False
    assert arguments["fliplr"] == 0 and arguments["mosaic"] == 0


@pytest.mark.parametrize("trial,epochs", [("third-experiment", 50), ("freeze-backbone", 51), ("freeze-backbone", 0), ("freeze-backbone", True)])
def test_unbounded_or_extra_trials_rejected(trial, epochs):
    with pytest.raises(data.Blocked):
        driver.build_train_args(Path("dataset"), Path("trial"), trial, epochs)


def test_synthetic_fixture_cannot_be_passed_off_as_real_training(inputs):
    repo, root, path, _ = inputs
    dataset = repo / "private" / "dataset"
    data.prepare_dataset(path, root, dataset, repo)
    weights = repo / "private" / "yolo11n.pt"
    weights.write_bytes(b"synthetic checkpoint bytes only")
    with pytest.raises(data.Blocked, match="real-photo"):
        driver.validate_inputs(dataset, weights, data.sha256(weights), repo / "private" / "trials", "freeze-backbone", repo)


def test_training_preflight_checks_weights_and_does_not_import_gpu(inputs):
    repo, root, path, _ = inputs
    weights = repo / "private" / "yolo11n.pt"
    weights.write_bytes(b"synthetic checkpoint bytes only")
    with pytest.raises(data.Blocked, match="SHA256"):
        driver.validate_inputs(repo / "private/dataset", weights, "wrong", repo / "private/trials", "freeze-backbone", repo)
    trial = repo / "private/trials/freeze-backbone"
    trial.mkdir(parents=True)
    with pytest.raises(data.Blocked, match="already exists"):
        driver.validate_inputs(repo / "private/dataset", weights, data.sha256(weights), trial.parent, "freeze-backbone", repo)
