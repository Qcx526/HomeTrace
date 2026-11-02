"""No network: HTTP provider doubles and image metadata/privacy boundaries."""
from io import BytesIO
import json
from types import SimpleNamespace as NS

import pytest

Image = pytest.importorskip('PIL.Image')
pytest.importorskip('openai')
from hometrace.visual_advisor import PARAMETERS
from hometrace.visual_advisor_client import (
    AdvisorResponseError, LIVE_MAX_OUTPUT_TOKENS, _derivative, call_advisor,
)


REQUEST_LIMITS = {'max_output_tokens': 4096, 'timeout_seconds': 45, 'max_retries': 0}


def valid_content():
    return json.dumps({'appearance': 'similar', 'quality_flags': [], 'next_action': 'ask_owner_review',
                       'visible_features': ['蓝色挂件'], 'reason': '外观相近，需人工核对'})


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
    captured = {'calls': 0}
    class Client:
        def __init__(self, **kwargs):
            captured['config'] = kwargs
            self.chat = NS(completions=NS(create=self.create))
        def __enter__(self): return self
        def __exit__(self, *args): captured['config']['http_client'].close()
        def create(self, **kwargs):
            captured['calls'] += 1
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
    assert exc.value.code == ('OUTPUT_TRUNCATED' if finish == 'length' else 'INVALID_CONTENT')
    assert exc.value.finish_reason == finish
    assert exc.value.request_limits == REQUEST_LIMITS
    assert captured['calls'] == 1
    assert captured['request']['max_tokens'] == 4096
    assert captured['config']['max_retries'] == 0
    assert captured['config']['http_client'].follow_redirects is False


def test_missing_usage_never_creates_valid_advice(monkeypatch):
    config, packet, _ = invoke(monkeypatch, response(usage=False))
    with pytest.raises(AdvisorResponseError) as exc:
        call_advisor(config, packet)
    assert exc.value.usage is None
    assert exc.value.request_limits == REQUEST_LIMITS


def test_valid_advice_is_not_instance_confirmation(monkeypatch):
    config, packet, captured = invoke(monkeypatch, response(content=valid_content()))
    result = call_advisor(config, packet)
    assert result['advice']['production_status'] == 'UNKNOWN'
    assert result['advice']['identity_confirmed'] is False
    request = captured['request']
    assert request['max_tokens'] == LIVE_MAX_OUTPUT_TOKENS == 4096
    assert PARAMETERS['max_tokens'] == 2048
    assert result['request_limits'] == REQUEST_LIMITS
    assert result['usage'] == {'input_tokens': 11000, 'output_tokens': 1000, 'total_tokens': 12000}
    assert captured['config']['timeout'] == 45
    assert captured['config']['max_retries'] == 0
    assert captured['config']['http_client'].follow_redirects is False
    assert captured['calls'] == 1
    wire = json.dumps(request)
    assert 'software-test-secret' not in wire and 'location_id' not in wire


@pytest.mark.parametrize('reasoning_tokens', [0, 250, 1000])
def test_reasoning_count_is_optional_output_subset_without_retaining_text(monkeypatch, reasoning_tokens):
    reply = response(content=valid_content())
    reply.usage.completion_tokens_details = NS(reasoning_tokens=reasoning_tokens)
    reply.choices[0].message.reasoning_content = 'PRIVATE model reasoning must never be stored'
    config, packet, _ = invoke(monkeypatch, reply)
    result = call_advisor(config, packet)
    assert result['usage'] == {'input_tokens': 11000, 'output_tokens': 1000,
                               'total_tokens': 12000, 'reasoning_tokens': reasoning_tokens}
    assert 'PRIVATE model reasoning' not in json.dumps(result)


@pytest.mark.parametrize('details', [None, NS(), NS(reasoning_tokens=None), NS(reasoning_tokens=-1),
                                    NS(reasoning_tokens=True), NS(reasoning_tokens='250'),
                                    NS(reasoning_tokens=250.0), NS(reasoning_tokens=1001)])
def test_invalid_reasoning_detail_is_unknown_without_losing_base_usage(monkeypatch, details):
    reply = response(content=valid_content())
    reply.usage.completion_tokens_details = details
    config, packet, _ = invoke(monkeypatch, reply)
    result = call_advisor(config, packet)
    assert result['usage'] == {'input_tokens': 11000, 'output_tokens': 1000, 'total_tokens': 12000}


@pytest.mark.parametrize('content', ['', valid_content()])
def test_length_rejects_even_valid_json_and_keeps_safe_accounting(monkeypatch, content):
    reply = response(content=content, finish='length')
    reply.usage.completion_tokens_details = NS(reasoning_tokens=1000)
    reply.choices[0].message.reasoning_content = 'PRIVATE discarded reasoning'
    config, packet, captured = invoke(monkeypatch, reply)
    with pytest.raises(AdvisorResponseError) as exc:
        call_advisor(config, packet)
    assert exc.value.code == 'OUTPUT_TRUNCATED'
    assert exc.value.finish_reason == 'length'
    assert exc.value.usage == {'input_tokens': 11000, 'output_tokens': 1000,
                               'total_tokens': 12000, 'reasoning_tokens': 1000}
    assert exc.value.request_limits == REQUEST_LIMITS
    assert 'PRIVATE discarded reasoning' not in json.dumps(vars(exc.value))
    assert captured['calls'] == 1 and captured['config']['max_retries'] == 0


@pytest.mark.parametrize('finish', ['content_filter', None, 'tool_calls'])
def test_other_incomplete_finish_reasons_remain_invalid_content(monkeypatch, finish):
    config, packet, captured = invoke(monkeypatch, response(content=valid_content(), finish=finish))
    with pytest.raises(AdvisorResponseError) as exc:
        call_advisor(config, packet)
    assert exc.value.code == 'INVALID_CONTENT'
    assert exc.value.request_limits == REQUEST_LIMITS
    assert captured['calls'] == 1


def test_bad_total_accounting_preserves_request_limits(monkeypatch):
    reply = response(content=valid_content())
    reply.usage.total_tokens = 12001
    config, packet, _ = invoke(monkeypatch, reply)
    with pytest.raises(AdvisorResponseError) as exc:
        call_advisor(config, packet)
    assert exc.value.code == 'INVALID_USAGE' and exc.value.usage is None
    assert exc.value.request_limits == REQUEST_LIMITS


def test_error_constructor_remains_compatible_with_existing_callers():
    error = AdvisorResponseError('Known invalid response', {'total_tokens': 25})
    assert error.request_limits is None
    assert error.usage == {'total_tokens': 25}
