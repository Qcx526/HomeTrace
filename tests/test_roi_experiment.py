"""Experiment bookkeeping tests use synthetic bytes, not recognition evidence."""

from dataclasses import asdict
import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

from hometrace.models import DetectionResult, Status


spec = importlib.util.spec_from_file_location("evaluate_registration_roi", Path(__file__).resolve().parents[1] / "tools/evaluate_registration_roi.py")
evaluation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evaluation)


@pytest.fixture
def pack(tmp_path):
    cv = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    root = tmp_path / "local_data/synthetic"
    root.mkdir(parents=True)
    files, suggestions = [], {}
    for group in evaluation.GROUPS:
        directory = root / group / "images"
        directory.mkdir(parents=True)
        for index in range(6):
            path = directory / f"image_{index}.jpg"
            ok, encoded = cv.imencode(".jpg", np.full((64, 96), index * 20, dtype=np.uint8))
            assert ok
            path.write_bytes(encoded.tobytes())
            files.append({"group": group, "path": path.relative_to(root).as_posix(), "width": 96, "height": 64,
                          "size_bytes": path.stat().st_size, "sha256": evaluation.sha256(path),
                          "role_hint": "reference_candidate" if index == 0 else "uncertain"})
        suggestions[group] = {"file": f"{group}/images/image_0.jpg", "xyxy_original_pixels": [0, 0, 64, 64]}
    manifest = {"privacy": "local_only_not_for_public_git", "capture_time_verification": "unknown",
                "source": "user_uploaded_private_photos", "navigation": "none",
                "all_labels": "human_visual_review_only_not_detection_answers", "files": files}
    evaluation.write_json(root / "asset_manifest.json", manifest)
    evaluation.write_json(root / "REGISTRATION_ROI_SUGGESTIONS.json", suggestions)
    (root / "SHA256SUMS.txt").write_text("".join(f"{row['sha256']}  local_data/synthetic/{row['path']}\n" for row in files), encoding="utf-8")
    return root, tmp_path, manifest, suggestions


def test_verifies_all_assets_and_keeps_original_bytes(pack):
    root, repo, _, _ = pack
    before = {p.relative_to(root).as_posix(): evaluation.sha256(p) for p in root.rglob("*.jpg")}
    _, _, verified = evaluation.validate_assets(root, repo)
    assert len(verified) == 24 and before == verified


@pytest.mark.parametrize("damage", ["hash", "bytes", "dimensions", "traversal", "duplicate"])
def test_bad_inventory_blocks_experiment(pack, damage):
    root, repo, manifest, _ = pack
    row = manifest["files"][0]
    if damage == "hash":
        row["sha256"] = "0" * 64
    elif damage == "bytes":
        row["size_bytes"] += 1
    elif damage == "dimensions":
        row["width"] += 1
    elif damage == "traversal":
        row["path"] = "../private.jpg"
    else:
        manifest["files"][1] = dict(row)
    evaluation.write_json(root / "asset_manifest.json", manifest)
    with pytest.raises(ValueError):
        evaluation.validate_assets(root, repo)


def test_checksum_inventory_must_cover_all_24_images(pack):
    root, repo, _, _ = pack
    lines = (root / "SHA256SUMS.txt").read_text().splitlines()
    (root / "SHA256SUMS.txt").write_text("\n".join(lines[:-1]))
    with pytest.raises(ValueError, match="exactly"):
        evaluation.validate_assets(root, repo)


def test_fixed_roi_cannot_exceed_reference_dimensions(pack):
    root, repo, _, suggestions = pack
    suggestions["earbud"]["xyxy_original_pixels"] = [0, 0, 1000, 1000]
    evaluation.write_json(root / "REGISTRATION_ROI_SUGGESTIONS.json", suggestions)
    with pytest.raises(ValueError, match="outside"):
        evaluation.validate_assets(root, repo)


def test_constructor_rejection_is_not_a_detector_unknown(pack):
    root, _, manifest, suggestions = pack
    class Reject:
        def __init__(self, *args, **kwargs):
            raise ValueError("Synthetic enrollment rejection")
    rows = evaluation.evaluate_group(root, "earbud", "baseline_full_image", manifest["files"], suggestions["earbud"], Reject)
    assert len(rows) == 5
    assert all(row["result"] is None and not row["detect_called"] and row["outcome"] == "enrollment_rejected" for row in rows)


def test_detector_receives_original_scene_and_reference_only_roi(pack):
    root, _, manifest, suggestions = pack
    seen = []
    class Spy:
        def __init__(self, path, digest, object_id, image_root, **options):
            assert path == root / suggestions["earbud"]["file"]
            assert options == {"seed": 0, "threads": 1, "reference_roi": (0, 0, 64, 64)}
        def detect_target(self, observation, object_id):
            fields = asdict(observation)
            assert "evaluation_label" not in fields and "role_hint" not in fields
            assert evaluation.sha256(root / observation.image_path) == observation.image_hash
            seen.append(observation.image_path)
            return DetectionResult(object_id, observation.evidence_id, Status.UNKNOWN, diagnostics={"reason": "no_verified_match"})
    rows = evaluation.evaluate_group(root, "earbud", "registration_roi", manifest["files"], suggestions["earbud"], Spy)
    assert len(seen) == 5 and all(row["evaluation_label"] == "uncertain" for row in rows)


@pytest.mark.parametrize("role,category", [("uncertain", "uncertain"), ("uncertain_or_negative", "uncertain"),
    ("alternative_reference", "auxiliary"), ("positive_observed_occluded", "positive"), ("negative_small_panda", "negative")])
def test_uncertain_and_auxiliary_are_separate_categories(role, category):
    assert evaluation.label_category(role) == category


def test_public_summary_removes_private_paths_hashes_rectangles(pack):
    root, _, manifest, suggestions = pack
    class Reject:
        def __init__(self, *args, **kwargs):
            raise ValueError("PRIVATE_SECRET")
    rows = evaluation.evaluate_group(root, "earbud", "baseline_full_image", manifest["files"], suggestions["earbud"], Reject)
    rows[0]["result"] = {"status": "FOUND", "bbox": [1, 2, 3, 4], "image_hash": "PRIVATE_SECRET",
                         "diagnostics": {"reason": "verified_planar_reference_match", "good_matches": 55,
                                         "reference_roi": [1, 2, 3, 4], "projected_corners": "PRIVATE_SECRET"}}
    rows[0].update(detect_called=True, outcome="detected", evaluation_label="uncertain")
    result = evaluation.public_summary({"generated_at": "synthetic", "environment": {}, "evaluations": rows, "baseline": {"commit": "synthetic-code-commit"},
                                        "originals_unchanged": True, "private_path": "PRIVATE_SECRET"})
    encoded = json.dumps(result)
    assert "PRIVATE_SECRET" not in encoded and "image_hash" not in encoded and "bbox" not in encoded
    assert "reference_roi" not in encoded and "projected_corners" not in encoded
    counts = result["counts"]["baseline_full_image"]
    assert counts["detect_calls"] == 1 and counts["enrollment_rejected_cases"] == 4
    assert counts["labels"]["negative"]["found"] == 0 and counts["labels"]["uncertain"]["found"] == 1


def test_public_report_uses_actual_baseline_commit():
    actual_commit = "b" * 40
    report = evaluation.public_summary({"generated_at": "synthetic", "environment": {},
        "evaluations": [], "baseline": {"commit": actual_commit}, "originals_unchanged": True})
    assert report["baseline_code_commit"] == actual_commit
    assert "e3adca7" not in json.dumps(report)


def test_wrong_installed_matcher_rejected_before_experiment(pack):
    root, repo, _, _ = pack
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
    (repo / ".gitignore").write_text("local_data/\nartifacts/\n", encoding="utf-8")
    source = repo / "src/hometrace/image_matcher.py"
    source.parent.mkdir(parents=True)
    source.write_text("# Different synthetic checkout, never a matcher result.\n", encoding="utf-8")
    output = repo / "artifacts/experiment"
    with pytest.raises(ValueError, match="Imported matcher differs"):
        evaluation.run_experiment(root, output, repo)
    assert not output.exists()
