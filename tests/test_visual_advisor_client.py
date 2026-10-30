"""No network: HTTP provider doubles and image metadata/privacy boundaries."""
from io import BytesIO
import json
from types import SimpleNamespace as NS

import pytest

Image = pytest.importorskip('PIL.Image')
pytest.importorskip('openai')
from hometrace.visual_advisor_client import AdvisorResponseError, _derivative, call_advisor


def jpeg():
    image = Image.new('RGB', (1800, 900), 'red')
    out = BytesIO()
    exif = Image.Exif()
    exif[0x010e] = 'PRIVATE metadata'
    image.save(out, format='JPEG', exif=exif)
    return out.getvalue()


def test_derivative_crops_only_reference_and_removes_metadata():
    raw = jpeg()
    scene = Image.open(BytesIO(_derivative(raw)))
    reference = Image.open(BytesIO(_derivative(raw, [0, 0, 600, 700])))
    assert scene.size == (1280, 640) and reference.size == (600, 700)
    assert not scene.getexif() and not reference.getexif()
    assert b'PRIVATE' not in _derivative(raw)


@pytest.mark.parametrize('roi', [[-1, 0, 1, 5], [0, 0, 1900, 900], [0., 0, 9, 9], [True, 0, 9, 9]])
def test_invalid_roi_rejected(roi):
    with pytest.raises(ValueError, match='ROI'):
        _derivative(jpeg(), roi)


def invoke(monkeypatch, response):
    captured = {}
    class Client:
        def __init__(self, **kwargs):
            captured['config'] = kwargs
            self.chat = NS(completions=NS(create=self.create))
        def __enter__(self): return self
        def __exit__(self, *args): captured['config']['http_client'].close()
        def create(self, **kwargs):
            captured['request'] = kwargs
            return response
    monkeypatch.setattr('openai.OpenAI', Client)
    config = NS(api_key='software-test-secret', llm=NS(base_url='https://provider.invalid/v1', model='test'))
    packet = {'reference_jpeg': _derivative(jpeg(), [0, 0, 600, 700]), 'scene_jpeg': _derivative(jpeg())}
    return config, packet, captured


def response(content='{}', finish='stop', usage=True):
    return NS(choices=[NS(finish_reason=finish, message=NS(content=content))], model='test',
              usage=NS(prompt_tokens=11000, completion_tokens=1000, total_tokens=12000) if usage else None)


@pytest.mark.parametrize('finish', ['stop', 'length'])
def test_bad_response_keeps_known_usage(monkeypatch, finish):
    config, packet, captured = invoke(monkeypatch, response(finish=finish))
    with pytest.raises(AdvisorResponseError) as exc:
        call_advisor(config, packet)
    assert exc.value.usage['total_tokens'] == 12000
    assert captured['config']['max_retries'] == 0
    assert captured['config']['http_client'].follow_redirects is False


def test_missing_usage_never_creates_valid_advice(monkeypatch):
    config, packet, _ = invoke(monkeypatch, response(usage=False))
    with pytest.raises(AdvisorResponseError) as exc:
        call_advisor(config, packet)
    assert exc.value.usage is None


def test_valid_advice_is_not_instance_confirmation(monkeypatch):
    text = json.dumps({'appearance': 'similar', 'quality_flags': [], 'next_action': 'ask_owner_review',
                       'visible_features': ['蓝色挂件'], 'reason': '外观相近，需人工核对'})
    config, packet, captured = invoke(monkeypatch, response(content=text))
    result = call_advisor(config, packet)
    assert result['advice']['production_status'] == 'UNKNOWN'
    assert result['advice']['identity_confirmed'] is False
    request = captured['request']
    assert request['max_tokens'] == 2048
    wire = json.dumps(request)
    assert 'software-test-secret' not in wire and 'location_id' not in wire
