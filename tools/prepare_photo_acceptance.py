"""Prepare a fresh, private photo workspace without network calls or memory claims.

The manifest is an enrollment/input contract, never a scene-label file. All
inputs are validated before the output directory is created. Actual local ORB
results are diagnostic appearance candidates, not physical-instance FOUND.
"""
import argparse
import base64
from contextlib import closing
import hashlib
import importlib.metadata
import json
from pathlib import Path, PureWindowsPath
import platform
import re
import sqlite3
import subprocess

from hometrace.household_memory import _identifier, _normalized, _text
from hometrace.household_service import HouseholdService, LOCATIONS
from hometrace.models import validate_reference_roi
from hometrace.photo_engine import PhotoSearchEngine
from hometrace.photo_flow_service import MAX_BYTES, PhotoFlowService, _dimensions
from hometrace.visual_advisor_client import _derivative


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _keys(value, expected, label):
    if not isinstance(value, dict) or set(value) != set(expected):
        raise ValueError(f'{label}: unexpected or missing fields')


def _input(root, row):
    value = row['path']
    if (not isinstance(value, str) or not value or Path(value).is_absolute()
            or PureWindowsPath(value).is_absolute() or PureWindowsPath(value).drive
            or '..' in value.replace('\\', '/').split('/')):
        raise ValueError('Image path must be relative and remain inside image-root')
    path = (root / value).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError('Image is missing or outside image-root')
    expected = row['sha256']
    if not isinstance(expected, str) or not re.fullmatch('[0-9a-f]{64}', expected):
        raise ValueError('sha256 must be a lowercase SHA256 digest')
    if not 0 < path.stat().st_size <= MAX_BYTES:
        raise ValueError('Image is empty or exceeds the unchanged 8 MB upload limit')
    raw = path.read_bytes()
    if _sha(raw) != expected:
        raise ValueError('Image SHA256 mismatch')
    width, height, extension = _dimensions(raw)
    if min(width, height) < 32 or width * height > 24_000_000:
        raise ValueError('Image dimensions exceed photo-workspace limits')
    import cv2
    import numpy as np
    buffer = np.frombuffer(raw, np.uint8)
    decoded = cv2.imdecode(buffer, cv2.IMREAD_COLOR | cv2.IMREAD_IGNORE_ORIENTATION)
    normal = cv2.imdecode(buffer, cv2.IMREAD_COLOR)
    if decoded is None or decoded.shape[:2] != (height, width):
        raise ValueError('Image decode failed or header dimensions differ')
    if normal is None or normal.shape != decoded.shape or not np.array_equal(normal, decoded):
        raise ValueError('EXIF orientation must be normalized before enrollment; original is unchanged')
    return {'path': path.relative_to(root).as_posix(), 'sha256': expected,
            'width': width, 'height': height, 'extension': extension}, raw


def _private_output(output):
    original = Path(output).absolute()
    if original.exists() or original.is_symlink():
        raise ValueError('Output must be new; existing results are never overwritten')
    if any(parent.is_symlink() for parent in original.parents):
        raise ValueError('Output parents must not be symbolic links')
    output = original.resolve()
    ancestor = output.parent
    while not ancestor.exists():
        ancestor = ancestor.parent
    found = subprocess.run(['git', '-C', str(ancestor), 'rev-parse', '--show-toplevel'],
                           text=True, capture_output=True, check=False, timeout=10)
    if found.returncode:
        raise ValueError('Output must be inside a Git repository and ignored')
    repo = Path(found.stdout.strip()).resolve()
    for probe in ('prepared.private.json', 'workspace/photos/probe.jpg', 'workspace/photo-flow.sqlite3'):
        relative = output.relative_to(repo) / probe
        ignored = subprocess.run(['git', '-C', str(repo), 'check-ignore', '--no-index', '-q', '--', relative.as_posix()],
                                 capture_output=True, check=False, timeout=10)
        if ignored.returncode:
            raise ValueError('Output and all private workspace assets must be Git ignored before preparation')
    return output


def preflight(manifest, image_root, output_dir):
    """Read-only validation; no files, databases, or network clients are created."""
    output = _private_output(output_dir)
    root = Path(image_root).resolve()
    if not root.is_dir():
        raise ValueError('image-root must be an existing directory')
    raw_manifest = Path(manifest).read_bytes()
    spec = json.loads(raw_manifest.decode('utf-8-sig'))
    _keys(spec, ('schema_version', 'source_kind', 'scope', 'object', 'reference', 'scenes'), 'manifest')
    if type(spec['schema_version']) is not int or spec['schema_version'] != 1:
        raise ValueError('Unsupported manifest schema_version')
    if spec['source_kind'] not in ('real_upload', 'synthetic') or spec['scope'] != 'diagnostic_reused':
        raise ValueError('Declare source_kind and diagnostic_reused scope')
    obj = spec['object']
    _keys(obj, ('object_id', 'name', 'aliases'), 'object')
    _identifier(obj['object_id'], 'object_id')
    _text(obj['name'], 'name')
    if not isinstance(obj['aliases'], list) or len(obj['aliases']) > 20:
        raise ValueError('aliases must be a list of at most 20 entries')
    names = [_text(value, 'alias') for value in [obj['name'], *obj['aliases']]]
    if len(set(map(_normalized, names))) != len(names):
        raise ValueError('Object name and aliases must not duplicate')
    reference = spec['reference']
    _keys(reference, ('path', 'sha256', 'roi', 'roi_reviewed', 'identity_reviewed', 'review_source'), 'reference')
    if reference['roi_reviewed'] is not True or reference['identity_reviewed'] is not True:
        raise ValueError('Reference ROI and identity need explicit review')
    _text(reference['review_source'], 'review_source', 2000)
    reference_input, reference_raw = _input(root, reference)
    roi = validate_reference_roi(reference['roi'], (reference_input['width'], reference_input['height']))
    if roi is None:
        raise ValueError('A fixed reviewed reference ROI is required')
    reference_meta = {**reference_input, 'roi': list(roi), 'source_kind': spec['source_kind']}
    # This executes the production quality gates, not a more permissive substitute.
    quality = PhotoSearchEngine(root, reference_meta, {}, obj['object_id']).quality()
    reference_input['derivative_sha256'] = _sha(_derivative(reference_raw, list(roi)))
    scenes = spec['scenes']
    if not isinstance(scenes, list) or not scenes:
        raise ValueError('scenes must be a nonempty list')
    sample_ids, mappings, scene_hashes, rows = set(), set(), set(), []
    locations = {row['location_id'] for row in LOCATIONS}
    for scene in scenes:
        _keys(scene, ('sample_id', 'path', 'sha256', 'location_id'), 'scene')
        sample_id = _identifier(scene['sample_id'], 'sample_id')
        if sample_id in sample_ids:
            raise ValueError('Duplicate sample_id')
        sample_ids.add(sample_id)
        location = scene['location_id']
        if location is not None:
            if not isinstance(location, str) or location not in locations:
                raise ValueError('Unknown location_id')
            if location in mappings:
                raise ValueError('Duplicate location mapping would overwrite a scene')
            mappings.add(location)
        metadata, raw = _input(root, scene)
        if metadata['sha256'] in scene_hashes:
            raise ValueError('Duplicate scene image SHA256; renamed copies are not additional samples')
        scene_hashes.add(metadata['sha256'])
        metadata['derivative_sha256'] = _sha(_derivative(raw))
        rows.append((scene, metadata, raw))
    return {'spec': spec, 'output': output, 'root': root, 'manifest_sha256': _sha(raw_manifest),
            'reference_input': reference_input, 'reference_raw': reference_raw,
            'quality': quality, 'scenes': rows}


def _execution():
    repo = Path(__file__).resolve().parents[1]
    files = [Path(__file__).resolve(), *sorted((repo / 'src/hometrace').glob('*.py'))]
    versions = {'python': platform.python_version()}
    for package in ('hometrace', 'opencv-python-headless', 'numpy', 'Pillow'):
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            versions[package] = 'not_installed'
    return {'base_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=repo, text=True).strip(),
            'working_tree_dirty': bool(subprocess.check_output(['git', 'status', '--porcelain'], cwd=repo)),
            'source_sha256': {path.relative_to(repo).as_posix(): _sha(path.read_bytes()) for path in files},
            'versions': versions}


def prepare(manifest, image_root, output_dir):
    checked = preflight(manifest, image_root, output_dir)
    spec, output = checked['spec'], checked['output']
    execution = _execution()
    output.mkdir(parents=True, exist_ok=False)
    household = HouseholdService(output / 'workspace')
    flow = PhotoFlowService(household, use_graph=False)
    household.enroll(**spec['object'])
    upload = lambda raw: flow.upload(base64.b64encode(raw).decode('ascii'), spec['source_kind'])
    ref_asset = upload(checked['reference_raw'])
    reference = flow.reference(spec['object']['object_id'], ref_asset['asset_id'], spec['reference']['roi'], True)
    with closing(flow._connect()) as db:
        stored_reference = json.loads(db.execute('SELECT payload FROM refs').fetchone()[0])
    reference.update(path=stored_reference['path'], identity_reviewed=True,
                     review_source=spec['reference']['review_source'],
                     derivative_sha256=checked['reference_input']['derivative_sha256'],
                     input_path=checked['reference_input']['path'])
    scenes, engine_scenes = [], {}
    for scene, metadata, raw in checked['scenes']:
        asset = upload(raw)
        with closing(flow._connect()) as db:
            stored = flow._asset_row(db, asset['asset_id'])
        asset.update(path=stored['path'], derivative_sha256=metadata['derivative_sha256'])
        if scene['location_id'] is not None:
            flow.scene(scene['location_id'], asset['asset_id'])
        scenes.append({'sample_id': scene['sample_id'], 'asset': asset,
                       'input_path': metadata['path'], 'location_id': scene['location_id']})
        engine_scenes[scene['sample_id']] = stored
    engine = PhotoSearchEngine(household.workspace, stored_reference, engine_scenes, spec['object']['object_id'])
    results = []
    for scene in scenes:
        row = engine.observe(scene['sample_id'])
        row.update(sample_id=scene['sample_id'], location_id=scene['location_id'])
        if row['status'] == 'FOUND' or row['identity_confirmed']:
            raise ValueError('Local appearance diagnostics must not claim physical identity')
        results.append(row)
    with closing(flow._connect()) as db:
        counts = {table: db.execute(f'SELECT count(*) FROM {table}').fetchone()[0] for table in ('runs', 'evidence')}
    with closing(sqlite3.connect(household.memory_path)) as db:
        counts['owner_history'] = db.execute('SELECT count(*) FROM hm_owner_events').fetchone()[0]
    if any(counts.values()):
        raise ValueError('Preparation must not create runs, evidence or owner history')
    result = {'schema_version': 1, 'scope': spec['scope'], 'source_kind': spec['source_kind'],
              'object': spec['object'], 'object_id': spec['object']['object_id'],
              'workspace': str(household.workspace), 'image_root': str(checked['root']),
              'reference': reference, 'scenes': scenes, 'local_results': results,
              'manifest_sha256': checked['manifest_sha256'],
              'input_sha256': {spec['reference']['path']: spec['reference']['sha256'],
                               **{row['path']: row['sha256'] for row in spec['scenes']}},
              'no_history': True, 'cloud_calls': 0, 'workspace_counts': counts,
              'automatic_found': False, 'location_mapping_basis': 'explicit_demo_mapping_not_verified_physical_location',
              'independent_test': False, 'metadata_is_owner_declared': True, **execution}
    with (output / 'prepared.private.json').open('x', encoding='utf-8') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--image-root', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    try:
        result = prepare(args.manifest, args.image_root, args.output_dir)
    except (ValueError, OSError, json.JSONDecodeError) as error:
        parser.error(str(error))
    print(json.dumps({'prepared': str(args.output_dir.resolve() / 'prepared.private.json'),
                      'scenes': len(result['scenes']), 'cloud_calls': 0, 'no_history': True}))


if __name__ == '__main__':
    main()
