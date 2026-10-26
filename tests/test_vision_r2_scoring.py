"""Deterministic matching tests; fixtures are not real photo evidence."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from score_vision_r2 import iou, score_boxes, summarize
from vision_r2_data import Blocked


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
