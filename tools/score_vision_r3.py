"""Post-inference scoring only; reads reviewed labels after proposals are saved."""
import argparse
from collections import Counter
import html
import json
from pathlib import Path
from statistics import median

from score_vision_r2 import score_boxes, summarize
from vision_r2_data import validate_manifest
from vision_r3_retrieve import private_path, sha256, write_json, PARAMETERS


def evaluate_rows(predictions, annotations, reference_hashes):
    """Require a complete grid, including reference exclusions and missed scenes."""
    by_path = {r['path']: r for r in annotations['images']}
    if len(by_path) != len(annotations['images']):
        raise ValueError('Duplicate annotated input')
    expected = {(p, s) for p in by_path for s in PARAMETERS['detector_sizes']}
    seen, rows = set(), []
    for p in predictions:
        key = p['path'], p['imgsz']
        if key not in expected or key in seen:
            raise ValueError('Unexpected or duplicate evaluation')
        seen.add(key)
        a = by_path[p['path']]
        if p['sha256'] != a['sha256'] or p['executed'] is not True or p['identity_confirmed'] is not False:
            raise ValueError('Hash, execution or identity mismatch')
        excluded = p['sha256'] in reference_hashes
        if p['reference_replay'] != excluded or (p['status'] == 'REFERENCE_EXCLUDED') != excluded:
            raise ValueError('Reference exclusion mismatch')
        accepted = []
        for candidate in p['candidates']:
            retrieval = candidate['retrieval']
            if retrieval['status'] not in ('UNKNOWN', 'APPEARANCE_SUPPORTED') or retrieval['identity_confirmed'] is not False:
                raise ValueError('Invalid experimental retrieval status')
            if excluded and retrieval['status'] != 'UNKNOWN':
                raise ValueError('Reference replay was accepted')
            if retrieval['status'] == 'APPEARANCE_SUPPORTED':
                accepted.append(candidate)
        if a['label'] not in ('present', 'absent'):
            raise ValueError('Unreviewed label cannot be scored')
        truth = [b['xyxy'] for b in a['boxes']]
        metrics = {name: score_boxes(boxes, truth) for name, boxes in
                   [('detector_only', p['candidates']), ('retrieval', accepted)]}
        rows.append({'sample_id': p['sample_id'], 'path': p['path'], 'imgsz': p['imgsz'],
                     'split': a['split'], 'label': a['label'], 'reference_excluded': excluded,
                     'candidate_count': len(p['candidates']), 'supported_count': len(accepted),
                     'elapsed_ms': p['elapsed_ms'], 'cold_call': p.get('cold_call', False),
                     'peak_allocated_bytes': p['peak_allocated_bytes'], 'reason': p['reason'],
                     'rejection_reasons': [c['retrieval']['reason'] for c in p['candidates'] if c['retrieval']['status'] == 'UNKNOWN'],
                     **metrics})
    if seen != expected:
        raise ValueError('Missing evaluations; failures must not be silently omitted')
    groups = {}
    for size in PARAMETERS['detector_sizes']:
        group = [r for r in rows if r['imgsz'] == size and not r['reference_excluded']]
        groups[str(size)] = {}
        for method in ('detector_only', 'retrieval'):
            groups[str(size)][method] = {}
            for split in ('train', 'val', 'all'):
                chosen = [r for r in group if split == 'all' or r['split'] == split]
                chosen = [{**r, **r[method], 'candidate_count': r['candidate_count'] if method == 'detector_only' else r['supported_count']} for r in chosen]
                groups[str(size)][method][split] = summarize(chosen)
        groups[str(size)]['rejection_reasons'] = dict(Counter(reason for r in group for reason in r['rejection_reasons']))
        groups[str(size)]['no_detector_candidate_images'] = sum(r['candidate_count'] == 0 for r in group)
        timings = [r['elapsed_ms'] for r in rows if r['imgsz'] == size and not r['cold_call']]
        groups[str(size)]['warm_median_ms'] = median(timings)
        groups[str(size)]['max_peak_allocated_bytes'] = max(r['peak_allocated_bytes'] for r in rows if r['imgsz'] == size)
    return rows, {'groups': groups, 'physical_images': len(by_path),
                  'reference_images_excluded': len(reference_hashes), 'independent_test_images': 0,
                  'production_found': False, 'thresholds_calibrated': False,
                  'scope': 'reused-development appearance retrieval; not physical identity',
                  'rival_control': 'one reviewed cartoon reference, limited',
                  'evaluation_rule': 'one-to-one IoU >= .5; duplicate supported boxes count FP'}


def run(inference, annotations, data_root, output, repo):
    inference, annotations, data_root, output = [private_path(repo, p) for p in (inference, annotations, data_root, output)]
    if output.exists():
        raise ValueError('Never overwrite scores')
    manifest = json.loads(annotations.read_text(encoding='utf-8'))
    validate_manifest(manifest, data_root)
    env = json.loads((inference / 'environment.public.json').read_text(encoding='utf-8'))
    if env['parameters'] != PARAMETERS or env['scene_ground_truth_input'] is not False:
        raise ValueError('Inference method mismatch')
    binding = json.loads((inference / 'binding.private.json').read_text(encoding='utf-8'))
    predictions = json.loads((inference / 'predictions.private.json').read_text(encoding='utf-8'))
    rows, metrics = evaluate_rows(predictions, manifest, set(binding['reference_hashes']))
    output.mkdir(parents=True)
    write_json(output / 'scores.private.json', {'rows': rows, 'annotation_sha256': sha256(annotations),
               'prediction_sha256': sha256(inference/'predictions.private.json')})
    write_json(output / 'metrics.public.json', metrics)
    cards = []
    for p, r in zip(predictions, rows):
        details = [{k: c['retrieval'][k] for k in ('status', 'reason', 'target_score', 'best_rival_score', 'margin')} | {'bbox': c['bbox_xyxy']} for c in p['candidates']]
        image = (inference / f"{p['sample_id']}-{p['imgsz']}.private.jpg").relative_to(output.parent).as_posix()
        cards.append(f"<article><h2>{html.escape(p['sample_id'])} / {p['imgsz']}</h2><p>{html.escape(p['status'])} | {html.escape(r['label'])} | reference excluded: {r['reference_excluded']}</p>"
                     f"<img src='../{html.escape(image, quote=True)}'><pre>{html.escape(json.dumps({'score': r['retrieval'], 'candidates': details}, ensure_ascii=False, indent=2))}</pre></article>")
    (output/'review.private.html').write_text('<!doctype html><meta charset="utf-8"><title>R3 private review</title><style>body{font:16px sans-serif;max-width:1200px;margin:auto}article{border-bottom:2px solid #ccc;padding:16px}img{max-width:700px;max-height:550px}pre{white-space:pre-wrap}</style><h1>真实照片开发诊断；无独立测试；非生产 FOUND</h1>'+''.join(cards), encoding='utf-8')
    return metrics


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ('inference', 'annotations', 'data-root', 'output-dir'):
        parser.add_argument('--'+arg, type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.inference, args.annotations, args.data_root, args.output_dir, Path(__file__).resolve().parents[1]), indent=2))
