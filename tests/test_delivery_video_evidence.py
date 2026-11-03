"""Media safeguards use software inputs; they do not validate household vision."""
import copy
import importlib.util
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
try:
    spec = importlib.util.spec_from_file_location('delivery_appendix', ROOT / 'tools/append_delivery_evidence.py')
    video = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(video)
finally:
    sys.path.pop(0)


@pytest.fixture
def inputs(tmp_path):
    source = tmp_path / 'TEST_ONLY.mp4'
    source.write_bytes(b'TEST_ONLY: validation does not decode media')
    metadata = dict(output_sha256=video.digest(source), browser_evidence_passed=True,
                    automatic_FOUND=False, scripted_owner_actions=True, real_household_validation=False)
    evidence = json.loads((ROOT / 'docs/evidence/issue-46-new-photos/workflow.json').read_text(encoding='utf-8'))
    return source, metadata, evidence


def test_current_frozen_report_supports_labelled_appendix(inputs):
    video.validate(*inputs)


@pytest.mark.parametrize('bad', ['hash', 'automatic_found', 'failed_check', 'negative_candidate', 'hidden_first_failure'])
def test_video_refuses_unsupported_claims(inputs, bad):
    source, metadata, original = inputs
    evidence = copy.deepcopy(original)
    if bad == 'hash':
        source.write_bytes(b'changed source')
    elif bad == 'automatic_found':
        evidence['second']['runs']['main']['automatic_found'] = True
    elif bad == 'failed_check':
        evidence['second']['checks'][0]['passed'] = False
    elif bad == 'negative_candidate':
        evidence['first']['runs']['control-scene-04']['state'] = 'AWAITING_REVIEW'
    elif bad == 'hidden_first_failure':
        evidence['first']['runs']['main']['state'] = 'USER_CONFIRMED'
    with pytest.raises(ValueError):
        video.validate(source, metadata, evidence)
