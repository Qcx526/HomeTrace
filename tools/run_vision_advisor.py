"""Bounded opt-in experiment; private bundle and endpoint-specific consent required."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
from time import perf_counter

from hometrace.agent_config import load_agent_config
from hometrace.agent_model import safe_model_error
from vision_advisor import METHOD, PARAMETERS, build_messages, strict_json, validate_advice
import hometrace.visual_advisor as advisor_contract


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def bundle_fingerprint(manifest, endpoint, model):
    """Approval scope is image content, independent of JSON formatting or names."""
    value = {'endpoint':endpoint, 'model':model,
             'references':sorted(item['sha256'] for item in manifest['references']),
             'scenes':sorted(item['sha256'] for item in manifest['scenes'])}
    return digest(json.dumps(value, sort_keys=True).encode('utf-8'))


def private_path(root, value):
    path = (root / value).resolve()
    if not path.is_relative_to(root) or subprocess.run(
        ['git', 'check-ignore', '--quiet', str(path)], cwd=root).returncode != 0:
        raise ValueError('Input and output paths must be inside Git ignored directories')
    return path


def prepare(root, manifest_path, consent_path, endpoint, model):
    raw = private_path(root, manifest_path).read_bytes()
    if len(raw) > 65536:
        raise ValueError('Oversized manifest')
    manifest = strict_json(raw.decode('utf-8'))
    consent = strict_json(private_path(root, consent_path).read_text(encoding='utf-8'))
    if type(manifest) is not dict or set(manifest) != {'schema_version', 'source_type', 'references', 'scenes'} or type(manifest['schema_version']) is not int or manifest['schema_version'] != 1:
        raise ValueError('Unexpected manifest fields, including labels')
    if manifest['source_type'] not in ('real', 'synthetic'):
        raise ValueError('Missing explicit image provenance')
    if type(consent) is not dict or set(consent) != {'schema_version','approved','endpoint','model','manifest_sha256','max_calls','approval_source'}:
        raise ValueError('Invalid consent document')
    if (type(consent['schema_version']) is not int or consent['schema_version'] != 1 or consent['approved'] is not True or
        consent['endpoint'] != endpoint or consent['model'] != model or
        consent['manifest_sha256'] != digest(raw) or type(consent['max_calls']) is not int or
        not 1 <= consent['max_calls'] <= PARAMETERS['max_calls'] or
        type(consent['approval_source']) is not str or not consent['approval_source'].strip()):
        raise ValueError('Consent is missing or does not match this bundle and provider')
    refs, scenes = manifest['references'], manifest['scenes']
    if type(refs) is not list or not 1 <= len(refs) <= 6 or type(scenes) is not list or not 1 <= len(scenes) <= consent['max_calls']:
        raise ValueError('Bundle exceeds call or reference budget')
    images, ids, hashes = [], set(), set()
    for item in refs + scenes:
        if type(item) is not dict or set(item) != {'id','path','sha256'}:
            raise ValueError('Only image identities allowed; no ground truth or annotations')
        if type(item['id']) is not str or not item['id'].isascii() or not 1 <= len(item['id']) <= 80 or not all(c.isalnum() or c in '_-' for c in item['id']) or item['id'] in ids:
            raise ValueError('Invalid or repeated image ID')
        ids.add(item['id'])
        path = private_path(root, item['path'])
        if path.stat().st_size > 4 * 1024 * 1024:
            raise ValueError('Oversized derivative')
        content = path.read_bytes()
        if digest(content) != item['sha256'] or item['sha256'] in hashes:
            raise ValueError('Image hash mismatch, duplicate, or reference replay')
        hashes.add(item['sha256'])
        images.append(content)
    refbytes, scenebytes = images[:len(refs)], images[len(refs):]
    # Validate every payload before the first network request; no labels or names transmitted.
    for content in scenebytes:
        build_messages(refbytes, content)
    return manifest, consent, refbytes, scenebytes


def run(root, manifest_path, consent_path, output, config):
    manifest, consent, refs, scenes = prepare(root, manifest_path, consent_path, config.llm.base_url, config.llm.model)
    output = private_path(root, output)
    output.mkdir(parents=True, exist_ok=False)
    # One approval document permits one bounded run, including failed/interrupted calls.
    # Changing output directories must not silently renew the ten-call allowance.
    ledger = private_path(root, Path('artifacts/vision-advisor-consent-ledger'))
    ledger.mkdir(parents=True, exist_ok=True)
    # Legacy records have no endpoint/model. Conservatively keep that bundle spent
    # even if the human-readable approval description has subsequently changed.
    for record_path in ledger.glob('*.json'):
        record = strict_json(record_path.read_text(encoding='utf-8'))
        if not isinstance(record, dict):
            raise ValueError('Unreadable consent ledger; manual review required')
        if (record.get('manifest_sha256') == consent['manifest_sha256']
                and 'endpoint' not in record):
            raise FileExistsError('This bundle already has a legacy budget reservation')
    legacy_id = digest(json.dumps(consent, sort_keys=True).encode('utf-8'))
    if (ledger / (legacy_id + '.json')).exists():
        raise FileExistsError('This approval has already reserved its call budget')
    scope = {key:consent[key] for key in ('manifest_sha256','endpoint','model')}
    consent_id = bundle_fingerprint(manifest, config.llm.base_url, config.llm.model)
    with (ledger / (consent_id + '.json')).open('x', encoding='utf-8') as handle:
        json.dump({'reserved_calls':len(scenes),**scope,'bundle_fingerprint':consent_id,
                   'output':str(output.relative_to(root))}, handle)
    def save(name, value):
        (output/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    binding = {'method':METHOD,'parameters':PARAMETERS,'endpoint':config.llm.base_url,
               'model':config.llm.model,'manifest_sha256':consent['manifest_sha256'],
               'source_type':manifest['source_type'],'training':False,'production_integration':False,
               'code':{p.name:digest(p.read_bytes()) for p in (Path(__file__),Path(advisor_contract.__file__))},
               'git_head':subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip()}
    save('protocol.private.json',binding)
    from openai import OpenAI
    import httpx
    client = OpenAI(api_key=config.api_key,base_url=config.llm.base_url,
                    timeout=PARAMETERS['timeout_seconds'],max_retries=0,
                    http_client=httpx.Client(follow_redirects=False,timeout=PARAMETERS['timeout_seconds']))
    rows=[]
    for item, content in zip(manifest['scenes'],scenes):
        row={'sample_id':item['id'],'scene_sha256':item['sha256'],'status':'REQUEST_RESERVED',
             'identity_confirmed':False,'production_status':'UNKNOWN'}
        rows.append(row)
        save('predictions.private.json',rows)
        start=perf_counter()
        try:
            response=client.chat.completions.create(model=config.llm.model,
                messages=build_messages(refs,content),temperature=PARAMETERS['temperature'],
                max_tokens=PARAMETERS['max_tokens'],response_format={'type':'json_object'})
            choice=response.choices[0]
            row.update(returned_model=response.model,finish_reason=choice.finish_reason,
                       response_content=choice.message.content,
                       usage=response.usage.model_dump() if response.usage else None)
            if choice.finish_reason != 'stop' or not response.usage:
                raise ValueError('Incomplete response or unavailable accounting')
            row.update(validate_advice(choice.message.content))
        except Exception as exc:
            row.update(status='ERROR',error=safe_model_error(exc))
        row['elapsed_ms']=round((perf_counter()-start)*1000,3)
        save('predictions.private.json',rows)
        advice = row.get('model_advice', {})
        print(json.dumps({'sample_id':item['id'],'status':row['status'],'elapsed_ms':row['elapsed_ms'],
                          'appearance':advice.get('appearance'),'next_action':advice.get('next_action'),
                          'error':row.get('error')},ensure_ascii=False),flush=True)
    save('completion.private.json',{'calls':len(rows),'valid_advice':sum(r['status']=='ADVISORY_ONLY' for r in rows),
         'identity_confirmed':False,'production_status':'UNKNOWN','independent_test':False,
         'response_total_tokens':sum((r.get('usage') or {}).get('total_tokens',0) for r in rows)})
    client.close()
    return rows


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest',type=Path,required=True)
    parser.add_argument('--consent',type=Path,required=True)
    parser.add_argument('--output-dir',type=Path,required=True)
    parser.add_argument('--config',type=Path)
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[1]
    config=load_agent_config(args.config,project_root=root)
    run(root,args.manifest,args.consent,args.output_dir,config)
