"""Deterministic matching tests; fixtures are not real photo evidence."""
import sys
import json
import subprocess
from pathlib import Path

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from score_vision_r2 import iou, score_boxes, summarize, run
from vision_r2_data import Blocked, sha256


def pred(box, confidence=.9):
    return {'bbox_xyxy':box,'confidence':confidence}


def test_duplicate_predictions_do_not_count_as_two_true_positives():
    result=score_boxes([pred([0,0,10,10]),pred([0,0,10,10],.8)],[[0,0,10,10]])
    assert (result['tp'],result['fp'],result['fn'])==(1,1,0)


def test_rival_or_background_candidate_is_target_false_proposal():
    result=score_boxes([pred([0,0,10,10])],[])
    assert result['fp']==1 and result['tp']==0


def test_mislocalized_box_is_false_proposal_and_missed_truth():
    result=score_boxes([pred([20,20,30,30])],[[0,0,10,10]])
    assert (result['tp'],result['fp'],result['fn'])==(0,1,1)


def test_zero_accepts_precision_undefined_not_pass():
    result=summarize([{'tp':0,'fp':0,'fn':1,'candidate_count':0,'label':'present'},
                      {'tp':0,'fp':0,'fn':0,'candidate_count':0,'label':'absent'}])
    assert result['precision'] is None and result['recall']==0
    assert result['negative_image_false_acceptance_rate']==0


@pytest.mark.parametrize('box', [[0,0,0,2],[-1,0,2,2],[0,0,float('nan'),2]])
def test_malformed_boxes_rejected_even_for_empty_truth(box):
    with pytest.raises(Blocked): score_boxes([pred(box)],[])


def test_iou_threshold_exact_boundary():
    assert iou([0,0,10,10],[0,0,20,10])==.5
    assert score_boxes([pred([0,0,10,10])],[[0,0,20,10]])['tp']==1


@pytest.fixture
def scoring_inputs(tmp_path):
    Image = pytest.importorskip("PIL.Image")
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / ".gitignore").write_text("private/\n", encoding="utf-8")
    root = tmp_path / "private/originals"
    root.mkdir(parents=True)
    review = {"confirmed": True, "reviewer": "software fixture author", "source": "generated fixture only"}
    rows = []
    for index, split in enumerate(("train", "val")):
        image = root / f"sample_{index}.png"
        Image.new("RGB", (100, 100), (index * 50, 20, 30)).save(image)
        rows.append({"sample_id": f"sample_{index}", "path": image.name, "sha256": sha256(image),
                     "split": split, "label": "present", "group_id": f"group_{index}", "label_review": review,
                     "boxes": [{"xyxy": [10, 10, 90, 90], "bbox_scope": "full_visible_object", "review": review}]})
    annotation = tmp_path / "private/annotation.json"
    annotation.write_text(json.dumps({"schema_version": 1, "class_name": "sony_mug", "purpose": "exploratory_fit",
                                      "source_type": "synthetic_software_fixture", "split_review": review, "images": rows}), encoding="utf-8")
    return tmp_path, root, annotation, rows


@pytest.mark.parametrize("source", [[], {}, None])
def test_missing_prediction_evaluations_are_blocked(scoring_inputs, source):
    repo, root, annotation, _ = scoring_inputs
    predictions = repo / "private/predictions.json"
    predictions.write_text(json.dumps(source), encoding="utf-8")
    output = repo / "private/scores"
    with pytest.raises(Blocked, match="non-empty list"):
        run(predictions, annotation, root, output, repo)
    assert not output.exists()


def test_executed_rows_with_zero_candidates_still_count_as_misses(scoring_inputs):
    repo, root, annotation, images = scoring_inputs
    predictions = repo / "private/predictions.json"
    predictions.write_text(json.dumps([{"path": row["path"], "sha256": row["sha256"], "imgsz": 640,
                                        "executed": True, "target_class_candidates": [], "elapsed_ms": 1.0}
                                       for row in images]), encoding="utf-8")
    summary = run(predictions, annotation, root, repo / "private/scores", repo)
    metrics = summary["group_metrics"]["640"]["all"]
    assert metrics["images"] == 2 and metrics["fn"] == 2 and metrics["tp"] == 0
    assert metrics["precision"] is None and metrics["recall"] == 0
