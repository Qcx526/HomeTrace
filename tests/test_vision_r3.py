"""Software contract fixtures; these are not household recognition evidence."""
import copy
import hashlib
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from vision_r3_retrieve import checked_box, validate_enrollment
from score_vision_r3 import evaluate_rows


def test_reference_and_unlabelled_scene_schema(tmp_path):
    refs, scenes = [], []
    for n, obj in enumerate(('target', 'target', 'rival'), 1):
        p = tmp_path/f'{n}.jpg'
        p.write_bytes(f'not-an-image-fixture-{n}'.encode())
        digest = hashlib.sha256(p.read_bytes()).hexdigest()
        refs.append({'reference_id': f'r{n}', 'object_instance_id': obj, 'path': p.name,
                     'sha256': digest, 'roi': [0, 0, 10, 10], 'identity_reviewed': True,
                     'roi_reviewed': True, 'review_source': 'software fixture', 'source_type': 'real'})
        scenes.append({'sample_id': f's{n}', 'path': p.name, 'sha256': digest, 'source_type': 'real'})
    manifest = {'schema_version': 1, 'target_instance_id': 'target', 'references': refs,
                'scenes': scenes, 'scope': 'diagnostic_reused'}
    assert validate_enrollment(manifest, tmp_path) == (scenes, refs)
    for field in ('label', 'boxes', 'ground_truth', 'split'):
        bad = copy.deepcopy(manifest)
        bad['scenes'][0][field] = 'answer'
        with pytest.raises(ValueError, match='unlabelled'):
            validate_enrollment(bad, tmp_path)
    bad = copy.deepcopy(manifest)
    bad['references'][0]['roi_reviewed'] = False
    with pytest.raises(ValueError, match='reviewed'):
        validate_enrollment(bad, tmp_path)
    (tmp_path/'1.jpg').write_bytes(b'changed')
    with pytest.raises(ValueError, match='hash mismatch'):
        validate_enrollment(manifest, tmp_path)


@pytest.mark.parametrize('box', [[-1, 0, 5, 5], [0, 0, 11, 5], [5, 5, 1, 1], [0, 0, float('nan'), 5], [True, 0, 5, 5]])
def test_bad_crop_rejected(box):
    with pytest.raises(ValueError):
        checked_box(box, 10, 10)


def test_subpixel_crop_encloses_original_box():
    assert checked_box([.5, 1.3, 8.2, 9.5], 10, 10) == [0, 1, 9, 10]


def fixtures():
    annotation = {'images': [
        {'path': 'positive.jpg', 'sha256': 'a'*64, 'split': 'val', 'label': 'present', 'boxes': [{'xyxy': [0, 0, 10, 10]}]},
        {'path': 'negative.jpg', 'sha256': 'b'*64, 'split': 'val', 'label': 'absent', 'boxes': []},
        {'path': 'reference.jpg', 'sha256': 'c'*64, 'split': 'train', 'label': 'present', 'boxes': [{'xyxy': [0, 0, 10, 10]}]}]}
    rows = []
    for size in (640, 960):
        for a in annotation['images']:
            is_positive = a['path'] == 'positive.jpg'
            replay = a['path'] == 'reference.jpg'
            c = {'bbox_xyxy': [0, 0, 10, 10], 'confidence': .8,
                 'retrieval': {'status': 'APPEARANCE_SUPPORTED' if is_positive else 'UNKNOWN',
                               'identity_confirmed': False, 'reason': 'appearance_support_and_margin' if is_positive else 'reference_replay' if replay else 'insufficient_rival_margin'}}
            rows.append({'path': a['path'], 'sample_id': a['path'], 'sha256': a['sha256'], 'imgsz': size,
                         'executed': True, 'identity_confirmed': False, 'reference_replay': replay,
                         'status': 'REFERENCE_EXCLUDED' if replay else 'APPEARANCE_SUPPORTED' if is_positive else 'UNKNOWN',
                         'candidates': [c], 'elapsed_ms': 1, 'peak_allocated_bytes': 10, 'reason': 'fixture'})
    return rows, annotation


def test_scores_exclude_reference_and_count_rejected_negative():
    rows, annotation = fixtures()
    _, metrics = evaluate_rows(rows, annotation, {'c'*64})
    for size in ('640', '960'):
        group = metrics['groups'][size]
        assert group['detector_only']['all']['fp'] == 1
        assert group['retrieval']['all']['tp'] == 1
        assert group['retrieval']['all']['fp'] == 0
        assert group['retrieval']['all']['fn'] == 0
        assert group['retrieval']['all']['images'] == 2


@pytest.mark.parametrize('problem', ['missing', 'duplicate', 'hash', 'unexecuted', 'identity', 'replay', 'found'])
def test_scoring_rejects_partial_or_invalid_evidence(problem):
    rows, annotation = fixtures()
    if problem == 'missing': rows.pop()
    elif problem == 'duplicate': rows.append(copy.deepcopy(rows[0]))
    elif problem == 'hash': rows[0]['sha256'] = 'd'*64
    elif problem == 'unexecuted': rows[0]['executed'] = False
    elif problem == 'identity': rows[0]['identity_confirmed'] = True
    elif problem == 'replay': rows[2]['reference_replay'] = False
    elif problem == 'found': rows[0]['candidates'][0]['retrieval']['status'] = 'FOUND'
    with pytest.raises(ValueError):
        evaluate_rows(rows, annotation, {'c'*64})


def test_duplicate_supported_box_is_false_positive():
    rows, annotation = fixtures()
    rows[0]['candidates'].append(copy.deepcopy(rows[0]['candidates'][0]))
    _, metrics = evaluate_rows(rows, annotation, {'c'*64})
    assert metrics['groups']['640']['retrieval']['all']['tp'] == 1
    assert metrics['groups']['640']['retrieval']['all']['fp'] == 1
