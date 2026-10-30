"""Twelve text-only tool-selection probes; no images, execution, or identity scoring.

Compare prompt + tool description + context-facts bundles, not a pure prompt A/B.
All observations are explicit public software fixtures. Never invoke selected tools.
"""
import argparse
import ast
from dataclasses import replace
import hashlib
import importlib.metadata
import json
from pathlib import Path
import subprocess
from time import perf_counter

from hometrace.agent_config import load_agent_config
from hometrace.agent_model import create_model, response_metrics, safe_model_error
from hometrace.household_service import LOCATIONS
from hometrace.photo_agent_service import _bounded_text
from hometrace.visual_photo_agent_service import VisualPhotoAgentService, VISUAL_SYSTEM

BASE = '66eae126aa775e76d58e5de06116f184d3ae7770'
ROOT = Path(__file__).resolve().parents[1]
SOURCES = ('src/hometrace/photo_agent_service.py', 'src/hometrace/visual_photo_agent_service.py')
MAX_CALLS = 12
SPECS = (('not_visible', 'continue_search', [], False),
         ('different', 'continue_search', [], True),
         ('similar', 'ask_owner_review', ['view_mismatch'], False),
         ('uncertain', 'request_closeup', ['small_target', 'occluded'], False),
         ('similar', 'request_closeup', ['small_target'], False),
         ('not_visible', 'continue_search', ['background_clutter'], True))


def digest(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def constant(node, names):
    """Only the existing string literals/addition/replace expression; no code exec."""
    if isinstance(node, ast.Constant) and type(node.value) is str:
        return node.value
    if isinstance(node, ast.Name) and node.id in names:
        return names[node.id]
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return constant(node.left, names) + constant(node.right, names)
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr == 'replace' and len(node.args) == 2 and not node.keywords):
        return constant(node.func.value, names).replace(*(constant(x, names) for x in node.args))
    raise ValueError('Unsupported prompt constant expression')


def baseline():
    sources = {p: subprocess.check_output(['git', 'show', f'{BASE}:{p}'], cwd=ROOT).decode('utf-8')
               for p in SOURCES}
    names = {}
    for source in sources.values():
        for node in ast.parse(source).body:
            if (isinstance(node, ast.Assign) and len(node.targets) == 1
                    and isinstance(node.targets[0], ast.Name) and node.targets[0].id in ('SYSTEM', 'VISUAL_SYSTEM')):
                names[node.targets[0].id] = constant(node.value, names)
    doc = next(ast.get_docstring(n) for n in ast.walk(ast.parse(sources[SOURCES[1]]))
               if isinstance(n, ast.FunctionDef) and n.name == 'request_new_photo')
    return names['VISUAL_SYSTEM'], doc, {p: digest(s) for p, s in sources.items()}


def context_for(index, mode):
    appearance, action, flags, alternative = SPECS[index]
    feedback = {'appearance': appearance, 'next_action': action, 'quality_flags': flags,
                'visible_features': ['测试物品外观'], 'reason': '纯软件观察 fixture，不是真实照片识别结果'}
    row = {'location_id': 'study-desk', 'status': 'UNKNOWN', 'bbox': None,
           'asset_id': 'software-scene', 'diagnostics': {'image_decoded': True}}
    advice = {'observation_index': 0, 'execution_status': 'completed',
              'advice': {'model_advice': feedback, 'identity_confirmed': False}}
    scenes = {'study-desk': 'software-scene', **({'living-table': 'software-other'} if alternative else {})}
    run = {'observations': [row], 'visual_advice': [advice], 'selected_object': {'object_id': 'fixture-object'},
           'intent': 'find', 'visited': ['study-desk'], 'snapshot': {'scenes': scenes},
           'vision_calls': 1, 'vision_tokens_used': 500, 'new_photo_count': 0,
           'agent_internal': {'vision_attempts': {'0': 'completed'}, 'review_rejected': [], 'photo_requested': []}}
    context = {
        'user_request': '请寻找测试物品，可以检查书房桌面和客厅茶几。' if alternative else '请只在书房桌面寻找测试物品。',
        'catalog': [{'object_id': 'fixture-object', 'name': '测试物品', 'aliases': []}],
        'phase': 'searching_bound_object', 'allowed_tools': VisualPhotoAgentService._allowed_tools(run),
        'intent': 'find', 'selected_object_id': 'fixture-object', 'current_location_id': 'study-desk',
        'history': [], 'locations': [{**x, 'has_uploaded_image': x['location_id'] in scenes} for x in LOCATIONS],
        'visited': ['study-desk'], 'observations': [{'ref': 'E1', 'location_id': 'study-desk', 'status': 'UNKNOWN',
          'reason': '软件 fixture：本地未形成候选框', 'bbox': None, 'identity_confirmed': False, 'diagnostics': {}}],
        'owner_rejected_locations': [], 'navigation_mode': 'simulated_navigation',
        'last_tool_result': {'tool': 'visual_advice', 'observation_index': 0, 'execution_status': 'completed'},
        'budgets_used': {'model_calls': 3, 'tool_calls': 3, 'total_tokens': 500}, 'automatic_found_enabled': False,
        'visual_advisor_enabled': True, 'vision_budget': {'calls': 1, 'max_calls': 3, 'tokens': 500, 'max_tokens': 24000},
        'new_photo_count': 0, 'max_new_photos': 2, 'visual_advice': [
            {'observation_ref': 'E1', 'execution_status': 'completed', 'advice': advice['advice'], 'identity_confirmed': False}]}
    if mode == 'new':
        context['decision_support'] = VisualPhotoAgentService._decision_support(run)
    return context


def score(index, context, response):
    calls = getattr(response, 'tool_calls', [])
    if getattr(response, 'invalid_tool_calls', []) or not isinstance(calls, list) or len(calls) != 1:
        return {'valid': False, 'pass': False, 'reason': 'EXACTLY_ONE_TOOL_REQUIRED'}
    name, args = calls[0].get('name'), calls[0].get('args')
    valid = name in context['allowed_tools'] and VisualPhotoAgentService._valid_args(name, args)
    if valid and name == 'inspect_location':
        valid = args['location_id'] in {x['location_id'] for x in context['locations']} - set(context['visited'])
    expected = ('finish_search', 'inspect_location', 'request_owner_review', 'request_new_photo',
                'request_new_photo', 'inspect_location')[index]
    passed = valid and name == expected and (name != 'inspect_location' or args['location_id'] == 'living-table')
    return {'valid': valid, 'pass': passed, 'expected_tool': expected,
            'reason': 'MATCH' if passed else 'UNEXPECTED_DECISION' if valid else 'INVALID_TOOL_OR_LOCATION'}


def run_probe(output, model, *, secret=''):
    from langchain_core.messages import HumanMessage, SystemMessage
    from langchain_core.utils.function_calling import convert_to_openai_tool
    old_prompt, old_doc, old_hashes = baseline()
    current_hashes = {p: digest((ROOT / p).read_text(encoding='utf-8')) for p in SOURCES}
    current_hashes['tools/probe_visual_decisions.py'] = digest(Path(__file__).read_text(encoding='utf-8'))
    tools = VisualPhotoAgentService._tools(object.__new__(VisualPhotoAgentService))
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)  # Never overwrite a previous or interrupted experiment.
    execution = {
        'head': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        'working_tree_dirty': bool(subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT)),
        'versions': {name: importlib.metadata.version(name) for name in
                     ('hometrace', 'langgraph', 'langchain-core', 'langchain-openai', 'openai')},
        'max_output_tokens': 1024, 'network_timeout_seconds': 45, 'max_retries': 0,
        'input_kind': 'public software fixtures; no images, private labels or household descriptions',
        'current_source_sha256': current_hashes, 'baseline_source_sha256': old_hashes,
    }
    (output / 'execution.json').write_text(json.dumps(execution, indent=2), encoding='utf-8')
    rows = []
    for index in range(len(SPECS)):
        for mode in ('baseline', 'new'):
            if len(rows) >= MAX_CALLS:
                raise RuntimeError('Call cap exceeded')
            context = context_for(index, mode)
            selected = [tools[name] for name in context['allowed_tools']]
            if mode == 'baseline':
                selected = [t.model_copy(update={'description': old_doc}) if t.name == 'request_new_photo' else t for t in selected]
            prompt = old_prompt if mode == 'baseline' else VISUAL_SYSTEM
            row = {'case': index + 1, 'mode': mode, 'context': context, 'system_prompt': prompt,
                   'prompt_sha256': digest(prompt), 'source_sha256': old_hashes if mode == 'baseline' else current_hashes,
                   'tool_schemas': [convert_to_openai_tool(t) for t in selected], 'max_tokens': 1024,
                   'execution_kind': 'text_tool_selection_only', 'images_sent': False, 'tools_executed': False}
            rows.append(row)  # An unsuccessful attempt consumes the same one-call allocation.
            (output / f'{index + 1}-{mode}.json').write_text(json.dumps(row, ensure_ascii=False, indent=2), encoding='utf-8')
            started = perf_counter()
            try:
                response = model.bind_tools(selected).invoke(
                    [SystemMessage(content=prompt), HumanMessage(content=json.dumps(context, ensure_ascii=False))], max_tokens=1024)
                row.update(execution_status='completed', tool_calls=response.tool_calls,
                           invalid_tool_calls=response.invalid_tool_calls, metrics=response_metrics(response, (perf_counter()-started)*1000),
                           score=score(index, context, response))
            except Exception as exc:
                row.update(execution_status='error', error=safe_model_error(exc), score={'pass': False, 'valid': False})
            row['latency_ms'] = round((perf_counter()-started)*1000, 3)
            def clean(value):
                if isinstance(value, str):
                    return value.replace(secret, '[redacted]') if secret else value
                if isinstance(value, dict):
                    return {k: clean(v) for k, v in value.items()}
                return [clean(v) for v in value] if isinstance(value, list) else value
            row.update(clean(row))
            (output / f'{index + 1}-{mode}.json').write_text(json.dumps(row, ensure_ascii=False, indent=2), encoding='utf-8')
            names = [c.get('name') for c in row.get('tool_calls', [])]
            print(index + 1, mode, _bounded_text(str(names), secret), row['score']['pass'], flush=True)
    result = {'baseline_commit': BASE, 'call_count': len(rows), 'max_calls': MAX_CALLS,
              'comparison': 'prompt + request_new_photo description + decision_support context bundle',
              'source_kind': 'public_software_fixtures', 'full_agent_acceptance': False,
              'summary': {mode: {'passed': sum(r['score']['pass'] for r in rows if r['mode'] == mode),
                                'errors': sum(r['execution_status'] == 'error' for r in rows if r['mode'] == mode)}
                          for mode in ('baseline', 'new')}}
    (output / 'summary.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    path = args.output.resolve()
    if (not path.is_relative_to(ROOT) or subprocess.run(['git', 'check-ignore', '-q', '--', str(path)], cwd=ROOT).returncode):
        parser.error('Output must be a new Git-ignored directory inside the repository')
    config = load_agent_config()
    config = replace(config, llm=replace(config.llm, max_retries=0, timeout_seconds=45))
    run_probe(path, create_model(config), secret=config.api_key)


if __name__ == '__main__':
    main()
