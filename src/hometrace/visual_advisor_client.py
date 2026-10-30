"""Explicitly authorized image advice. No tools, arbitrary URLs or location writes."""
import hashlib
from io import BytesIO
from time import perf_counter

from .agent_config import disable_external_tracing
from .visual_advisor import PARAMETERS, build_messages, validate_advice


class AdvisorResponseError(ValueError):
    """Invalid content can still have incurred a known provider token charge."""

    def __init__(self, message, usage=None, *, code='INVALID_RESPONSE', finish_reason=None):
        super().__init__(message)
        self.usage = usage
        self.code = code
        self.finish_reason = finish_reason


def _derivative(raw, roi=None):
    from PIL import Image
    with Image.open(BytesIO(raw)) as original:
        if original.width * original.height > 24_000_000:
            raise ValueError('Image exceeds workspace pixel limit')
        image = original.convert('RGB')
        if roi is not None:
            if (type(roi) is not list or len(roi) != 4 or
                    any(type(v) is not int for v in roi) or
                    not 0 <= roi[0] < roi[2] <= image.width or
                    not 0 <= roi[1] < roi[3] <= image.height):
                raise ValueError('Invalid fixed reference ROI')
            image = image.crop(roi)
        image.thumbnail((1280, 1280), Image.Resampling.LANCZOS)
        clean = Image.new('RGB', image.size)
        clean.paste(image)
        output = BytesIO()
        clean.save(output, format='JPEG', quality=90)
        return output.getvalue()


def prepare_packet(service, run, observation):
    reference = run['snapshot']['reference']
    scene = run['snapshot']['scenes'].get(observation['location_id'])
    if not scene or scene['asset_id'] != observation.get('asset_id'):
        raise ValueError('Observation is not bound to this snapshot')
    ref_bytes, _ = service.asset(reference['asset_id'])
    scene_bytes, _ = service.asset(scene['asset_id'])
    sha = lambda raw: hashlib.sha256(raw).hexdigest()
    if (sha(ref_bytes) != reference['sha256'] or sha(scene_bytes) != scene['sha256']
            or scene['sha256'] != observation.get('image_sha256')
            or scene['sha256'] == reference['sha256'] or not reference.get('roi_reviewed')):
        raise ValueError('Image or reference binding differs from reviewed evidence')
    if reference['source_kind'] != scene['source_kind']:
        raise ValueError('Reference and scene provenance differ')
    ref_jpeg = _derivative(ref_bytes, reference['roi'])
    scene_jpeg = _derivative(scene_bytes)
    build_messages([ref_jpeg], scene_jpeg)
    public = lambda row: {k:row[k] for k in ('asset_id','url','width','height','source_kind','roi') if k in row}
    return {'reference':public(reference),'scene':public(scene),
            'reference_sha256':sha(ref_bytes),'scene_sha256':sha(scene_bytes),
            'reference_derivative_sha256':sha(ref_jpeg),'scene_derivative_sha256':sha(scene_jpeg),
            'reference_jpeg':ref_jpeg,'scene_jpeg':scene_jpeg}


def call_advisor(config, packet):
    """One request, no retries/redirects; caller owns durable authorization/budget."""
    disable_external_tracing()
    from openai import OpenAI
    import httpx
    messages = build_messages([packet['reference_jpeg']], packet['scene_jpeg'])
    started = perf_counter()
    with OpenAI(api_key=config.api_key, base_url=config.llm.base_url,
                timeout=PARAMETERS['timeout_seconds'], max_retries=0,
                http_client=httpx.Client(follow_redirects=False, timeout=PARAMETERS['timeout_seconds'])) as client:
        response = client.chat.completions.create(model=config.llm.model, messages=messages,
            temperature=PARAMETERS['temperature'], max_tokens=PARAMETERS['max_tokens'],
            response_format={'type':'json_object'})
    usage = response.usage
    if usage is None:
        raise AdvisorResponseError('Missing token accounting', code='MISSING_USAGE')
    values = [usage.prompt_tokens, usage.completion_tokens, usage.total_tokens]
    if (any(type(v) is not int or v < 0 for v in values) or values[2] < 1
            or values[2] != values[0] + values[1]):
        raise AdvisorResponseError('Invalid token accounting', code='INVALID_USAGE')
    accounting = dict(zip(('input_tokens','output_tokens','total_tokens'),values))
    finish_reason = None
    try:
        choice = response.choices[0]
        finish_reason = choice.finish_reason
        if choice.finish_reason != 'stop':
            raise ValueError('Incomplete visual advice')
        advice = validate_advice(choice.message.content)
    except (ValueError, IndexError, TypeError, AttributeError) as exc:
        raise AdvisorResponseError('Invalid or incomplete visual advice', accounting,
                                   code='INVALID_CONTENT', finish_reason=finish_reason) from exc
    return {'advice':advice,
            'usage':accounting,
            'elapsed_ms':round((perf_counter()-started)*1000,3), 'model':response.model}
