"""Synthetic scalar/box tests only; not real recognition evidence."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from diagnose_vision_r2_confidence import expected_keys, score_distribution, validate_rows
from score_vision_r2_confidence import raw_localization
from vision_r2_data import Blocked


def grid():
    hashes={f'{n}.jpg':str(n) for n in range(1,19)}
    return [dict(path=p,imgsz=s,threshold=t,sha256=hashes[p],executed=True) for p,s,t in expected_keys()],hashes


def test_all_five_actual_execution_slots_required():
    rows,hashes=grid()
    assert len(rows)==180
    validate_rows(rows,hashes)


@pytest.mark.parametrize('problem',['missing','duplicate','unexecuted','hash'])
def test_grid_rejects_incomplete_evidence(problem):
    rows,hashes=grid()
    if problem=='missing': rows.pop()
    if problem=='duplicate': rows[-1]=rows[0]
    if problem=='unexecuted': rows[0]['executed']=False
    if problem=='hash': rows[0]['sha256']='changed'
    with pytest.raises(Blocked): validate_rows(rows,hashes)


def test_low_confidence_localization_does_not_pass_business_gate():
    result=raw_localization([[0,0,10,10],[20,20,30,30]],[.04,.2],[[0,0,10,10]])
    assert result['highest_score_iou']==0
    assert result['highest_correct_score']==.04
    assert result['correct_raw_boxes_above']['0.01']==1
    assert result['correct_raw_boxes_above']['0.25']==0


def test_raw_zero_area_boxes_are_not_ground_truth_matches():
    result=raw_localization([[0,0,0,0]],[.9],[[0,0,10,10]])
    assert result['highest_correct_score'] is None
    assert result['best_iou']==0


def test_negative_has_score_distribution_without_iou_claim():
    result=raw_localization([[0,0,5,5]],[.8],[])
    assert result['highest_score']==.8 and result['highest_score_iou'] is None
    assert result['highest_correct_score'] is None


@pytest.mark.parametrize('bad',[[float('nan')],[-.1],[1.1]])
def test_invalid_score_distribution_rejected(bad):
    with pytest.raises(Blocked): score_distribution(bad)


def test_empty_distribution_is_undefined_not_zero_confidence():
    assert score_distribution([])['max'] is None
    assert score_distribution([.01,.25,.9])['above_threshold']['0.25']==1
