"""Software fixtures only: no real-photo performance claims or network calls."""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess

from PIL import Image
import pytest


SPEC = importlib.util.spec_from_file_location('private_photo_report',
    Path(__file__).resolve().parents[1] / 'tools/report_private_photo_agent.py')
report = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(report)


@pytest.fixture
def inputs(tmp_path):
    subprocess.run(['git', 'init', '--quiet', str(tmp_path)], check=True)
    (tmp_path / '.gitignore').write_text('artifacts/\n')
    root = tmp_path / 'artifacts'
    workspace = root / 'workspace'
    photos = workspace / 'photos'
    photos.mkdir(parents=True)
    image = Image.new('RGB', (1800, 900), 'white')
    exif = Image.Exif()
    exif[270] = 'fixture private metadata'
    image.save(photos / 'fixture.jpg', exif=exif)
    asset = {'path': 'photos/fixture.jpg', 'asset_id': 'fixture', 'source_kind': 'real_upload',
             'width': 1800, 'height': 900, 'sha256': hashlib.sha256((photos / 'fixture.jpg').read_bytes()).hexdigest()}
    prepared = {'source_kind': 'real_upload', 'scope': 'diagnostic_reused', 'workspace': str(workspace),
                'reference': asset | {'roi': [20, 10, 800, 890], 'roi_reviewed': True, 'identity_reviewed': True},
                'scenes': [{'sample_id': '<script>alert(1)</script>', 'asset': asset}, {'sample_id': 'not-run', 'asset': asset}]}
    summary = {'source_kind': 'real_upload', 'scope': 'diagnostic_reused', 'runs': [
        {'samples': ['<script>alert(1)</script>'], 'final': {'state': 'AWAITING_REVIEW',
         'observations': [{'asset_id': 'fixture', 'image_sha256': asset['sha256'], 'bbox': [100, 200, 500, 600]}],
         'visual_advice': [{'observation_index': 0, 'advice': {'reason': '<img src=x onerror=alert(1)>'}, 'elapsed_ms': 5}],
         'trace': [{'tool': 'inspect_location'}]}}]}
    return tmp_path, root, prepared, summary


def save(inputs):
    repo, root, prepared, summary = inputs
    prepared_path, summary_path = root / 'prepared.json', root / 'summary.json'
    prepared_path.write_text(json.dumps(prepared), encoding='utf-8')
    summary['prepared_sha256'] = hashlib.sha256(prepared_path.read_bytes()).hexdigest()
    summary_path.write_text(json.dumps(summary), encoding='utf-8')
    return prepared_path, summary_path, root / 'report', repo


def test_offline_page_escapes_text_preserves_geometry_and_strips_metadata(inputs):
    page = report.build_report(*save(inputs))
    content = page.read_text(encoding='utf-8')
    assert '<script>' not in content and '&lt;script&gt;' in content
    assert '<img src=x' not in content and '&lt;img src=x' in content
    assert 'viewBox="0 0 1800 900"' in content
    assert '<rect x="100" y="200" width="400" height="400"' in content
    assert 'AWAITING_REVIEW' in content and 'Agent 未执行本场景' in content
    assert 'diagnostic_reused' in content and '非独立测试' in content and 'inspect_location' in content
    for path in (page.parent / 'previews').glob('*.jpg'):
        with Image.open(path) as image:
            assert max(image.size) <= 1280
            assert not image.getexif()


@pytest.mark.parametrize('bad_path', ['../private.jpg', '/private.jpg', 'photos/../../private.jpg'])
def test_prepared_asset_escape_rejected_before_output(inputs, bad_path):
    inputs[2]['scenes'][0]['asset']['path'] = bad_path
    args = save(inputs)
    with pytest.raises(ValueError, match='ASSET_PATH_INVALID'):
        report.build_report(*args)
    assert not args[2].exists()


def test_summary_cannot_supply_images_or_model_boxes(inputs):
    summary = inputs[3]
    observation = summary['runs'][0]['final']['observations'][0]
    observation['bbox'] = None
    observation['path'] = 'outside.jpg'
    observation['url'] = 'https://example.invalid/private.jpg'
    summary['runs'][0]['final']['visual_advice'][0]['bbox'] = [1, 2, 30, 40]
    page = report.build_report(*save(inputs))
    content = page.read_text(encoding='utf-8')
    assert '<rect ' not in content
    assert '<image href="previews/1.jpg"' in content
    assert '无有效本地检测框' in content
    assert 'href="https://' not in content


def test_asset_and_summary_hashes_are_enforced(inputs):
    args = save(inputs)
    inputs[3]['prepared_sha256'] = '0' * 64
    args[1].write_text(json.dumps(inputs[3]), encoding='utf-8')
    with pytest.raises(ValueError, match='PREPARED_HASH_MISMATCH'):
        report.build_report(*args)
    inputs[2]['scenes'][0]['asset']['sha256'] = '1' * 64
    with pytest.raises(ValueError, match='ASSET_HASH_OR_SOURCE_MISMATCH'):
        report.build_report(*save(inputs))


def test_existing_or_public_output_rejected(inputs):
    args = save(inputs)
    report.build_report(*args)
    with pytest.raises(ValueError, match='OUTPUT_MUST_BE_NEW'):
        report.build_report(*args)
    with pytest.raises(ValueError, match='PATH_NOT_GIT_IGNORED'):
        report.build_report(args[0], args[1], inputs[0] / 'public', inputs[0])


@pytest.mark.parametrize('box', [[0, 0, float('nan'), 4], [-1, 0, 8, 9], [0, 0, 1900, 900], '<script>'])
def test_invalid_boxes_never_render(box):
    assert '<rect ' not in report.scene_svg('1.jpg', {'width': 1800, 'height': 900}, box)
