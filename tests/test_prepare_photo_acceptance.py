"""Generated software fixtures only; these tests are not real-photo validation."""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import socket
import subprocess

import pytest

cv2 = pytest.importorskip('cv2')
np = pytest.importorskip('numpy')
pytest.importorskip('PIL')

spec = importlib.util.spec_from_file_location('prepare_photo_acceptance',
                                            Path(__file__).resolve().parents[1] / 'tools/prepare_photo_acceptance.py')
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)


@pytest.fixture
def case(tmp_path, monkeypatch):
    subprocess.run(['git', 'init', '-q', str(tmp_path)], check=True, capture_output=True)
    (tmp_path / '.gitignore').write_text('artifacts/\n', encoding='utf-8')
    images = tmp_path / 'inputs'
    images.mkdir()
    # The target is a deterministic generated texture, not a photograph of a cup.
    reference = np.random.default_rng(36).integers(0, 256, (320, 400, 3), dtype=np.uint8)
    samples = {'reference.png': reference,
               'scene.png': cv2.warpAffine(reference, np.float32([[1, 0, 5], [0, 1, 5]]), (400, 320)),
               'empty.png': np.full_like(reference, 128)}
    hashes = {}
    for name, pixels in samples.items():
        ok, data = cv2.imencode('.png', pixels)
        assert ok
        (images / name).write_bytes(data.tobytes())
        hashes[name] = hashlib.sha256(data).hexdigest()
    manifest = {'schema_version': 1, 'source_kind': 'synthetic', 'scope': 'diagnostic_reused',
                'object': {'object_id': 'fixture-object', 'name': '软件测试纹理', 'aliases': ['纹理']},
                'reference': {'path': 'reference.png', 'sha256': hashes['reference.png'],
                              'roi': [0, 0, 400, 320], 'roi_reviewed': True,
                              'identity_reviewed': True, 'review_source': 'software fixture, not human photo approval'},
                'scenes': [{'sample_id': 'dev3_close', 'path': 'scene.png', 'sha256': hashes['scene.png'],
                            'location_id': 'study-desk'},
                           {'sample_id': 'empty', 'path': 'empty.png', 'sha256': hashes['empty.png'],
                            'location_id': None}]}
    manifest_path = tmp_path / 'manifest.json'
    def save(value=manifest):
        manifest_path.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
    save()
    def forbidden(*args, **kwargs):
        raise AssertionError('Local preparation must not connect to a network')
    monkeypatch.setattr(socket, 'create_connection', forbidden)
    monkeypatch.setattr(socket.socket, 'connect', forbidden)
    return manifest, manifest_path, images, tmp_path / 'artifacts' / 'new', save


def test_actual_local_prepare_preserves_bytes_and_creates_no_history(case):
    manifest, path, images, output, _ = case
    originals = {p.name: p.read_bytes() for p in images.iterdir()}
    result = tool.prepare(path, images, output)
    assert result == json.loads((output / 'prepared.private.json').read_text(encoding='utf-8'))
    assert result['workspace_counts'] == {'runs': 0, 'evidence': 0, 'owner_history': 0}
    assert result['cloud_calls'] == 0 and result['no_history'] is True
    assert not result['independent_test'] and not result['automatic_found']
    assert result['source_kind'] == 'synthetic'
    assert result['reference']['quality']['reference_keypoints'] >= 32
    assert result['reference']['review_source'] == manifest['reference']['review_source']
    assert result['reference']['identity_reviewed'] is True
    assert len(result['reference']['derivative_sha256']) == 64
    workspace = Path(result['workspace'])
    for scene in result['scenes']:
        assert (workspace / scene['asset']['path']).read_bytes() == originals[scene['input_path']]
        assert scene['asset']['capture_time'] == 'unknown'
        assert len(scene['asset']['derivative_sha256']) == 64
    assert result['local_results'][0]['sample_id'] == 'dev3_close'
    assert result['local_results'][1]['location_id'] is None
    assert all(row['status'] != 'FOUND' and not row['identity_confirmed'] for row in result['local_results'])
    assert {p.name: p.read_bytes() for p in images.iterdir()} == originals
    assert result['source_sha256']['tools/prepare_photo_acceptance.py']
    assert result['versions']['Pillow'] != 'not_installed'


@pytest.mark.parametrize('change', [
    lambda m: m.update(schema_version=True),
    lambda m: m.update(scope='independent_test'),
    lambda m: m.update(source_kind='camera_verified'),
    lambda m: m['object'].update(object_id='Bad ID'),
    lambda m: m['object'].update(name=''),
    lambda m: m['object'].update(aliases=['纹理', '纹理']),
    lambda m: m['reference'].update(roi_reviewed=False),
    lambda m: m['reference'].update(identity_reviewed='true'),
    lambda m: m['reference'].update(review_source=''),
    lambda m: m['reference'].update(roi=[0, 0, 401, 320]),
    lambda m: m['reference'].update(roi=None),
    lambda m: m['scenes'][1].update(sha256='0' * 64),
    lambda m: m['scenes'][1].update(path='../reference.png'),
    lambda m: m['scenes'][1].update(path='C:\\private\\photo.png'),
    lambda m: m['scenes'][1].update(path='missing.png'),
    lambda m: m['scenes'][1].update(location_id='kitchen'),
    lambda m: m['scenes'][1].update(location_id='study-desk'),
    lambda m: m['scenes'][1].update(sample_id='dev3_close'),
    lambda m: m['scenes'][1].update(ground_truth='positive'),
    lambda m: m.update(scenes=[]),
])
def test_preflight_rejects_bad_contract_without_creating_output(case, change):
    manifest, path, images, output, save = case
    invalid = deepcopy(manifest)
    change(invalid)
    save(invalid)
    with pytest.raises(ValueError):
        tool.prepare(path, images, output)
    assert not output.exists()


def test_bad_decode_does_not_create_partial_workspace(case):
    manifest, path, images, output, save = case
    damaged = b'not a decodable image'
    (images / 'empty.png').write_bytes(damaged)
    manifest['scenes'][1]['sha256'] = hashlib.sha256(damaged).hexdigest()
    save()
    with pytest.raises(ValueError):
        tool.prepare(path, images, output)
    assert not output.exists()


def test_poor_reference_uses_unchanged_quality_gate(case):
    manifest, path, images, output, save = case
    manifest['reference'].update(path='empty.png', sha256=manifest['scenes'][1]['sha256'])
    save()
    with pytest.raises(ValueError):
        tool.prepare(path, images, output)
    assert not output.exists()


def test_existing_output_is_never_overwritten(case):
    _, path, images, output, _ = case
    output.mkdir(parents=True)
    sentinel = output / 'previous.json'
    sentinel.write_text('frozen')
    with pytest.raises(ValueError, match='never overwritten'):
        tool.prepare(path, images, output)
    assert sentinel.read_text() == 'frozen'
    assert list(output.iterdir()) == [sentinel]


def test_unignored_output_rejected_before_creation(case):
    _, path, images, output, _ = case
    unsafe = output.parents[1] / 'public-output'
    with pytest.raises(ValueError, match='Git ignored'):
        tool.prepare(path, images, unsafe)
    assert not unsafe.exists()


def test_ignoring_only_json_does_not_protect_photo_workspace(case):
    _, path, images, output, _ = case
    (output.parents[1] / '.gitignore').write_text('*.json\n*.sqlite3\n', encoding='utf-8')
    with pytest.raises(ValueError, match='Git ignored'):
        tool.prepare(path, images, output)
    assert not output.exists()


def test_duplicate_scene_bytes_are_not_counted_as_extra_samples(case):
    manifest, path, images, output, save = case
    manifest['scenes'][1].update(path=manifest['scenes'][0]['path'], sha256=manifest['scenes'][0]['sha256'])
    save()
    with pytest.raises(ValueError, match='Duplicate scene image'):
        tool.prepare(path, images, output)
    assert not output.exists()


def test_reference_replay_is_recorded_as_rejected_diagnostic(case):
    manifest, path, images, output, save = case
    manifest['scenes'][0].update(path=manifest['reference']['path'], sha256=manifest['reference']['sha256'])
    save()
    result = tool.prepare(path, images, output)
    assert result['local_results'][0]['reason'] == 'reference_replay'
    assert result['local_results'][0]['status'] == 'UNKNOWN'
    assert result['workspace_counts']['evidence'] == 0
