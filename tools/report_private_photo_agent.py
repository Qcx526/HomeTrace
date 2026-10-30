"""Build an offline, Git-ignored review page; no model calls or identity approval."""
import argparse
import hashlib
import html
import io
import json
import math
from pathlib import Path
import subprocess

from PIL import Image


def require(condition, code):
    if not condition:
        raise ValueError(code)


def private_path(path, repo):
    path, repo = Path(path).resolve(), Path(repo).resolve()
    require(path.is_relative_to(repo), 'PATH_OUTSIDE_REPOSITORY')
    result = subprocess.run(['git', 'check-ignore', '--quiet', '--', path.relative_to(repo).as_posix()],
                            cwd=repo, capture_output=True, check=False)
    require(result.returncode == 0, 'PATH_NOT_GIT_IGNORED')
    return path


def escaped(value):
    return html.escape(str(value), quote=True)


def details(title, value):
    return f'<details><summary>{escaped(title)}</summary><pre>{escaped(json.dumps(value, ensure_ascii=False, indent=2))}</pre></details>'


def checked_image(workspace, asset, roi=None):
    relative = Path(asset['path'])
    require(not relative.is_absolute() and '..' not in relative.parts, 'ASSET_PATH_INVALID')
    path = workspace / relative
    require(not path.is_symlink() and path.resolve().is_relative_to(workspace / 'photos'), 'ASSET_PATH_INVALID')
    raw = path.read_bytes()
    require(asset.get('source_kind') == 'real_upload'
            and hashlib.sha256(raw).hexdigest() == asset.get('sha256'), 'ASSET_HASH_OR_SOURCE_MISMATCH')
    with Image.open(io.BytesIO(raw)) as original:
        require(original.size == (asset['width'], asset['height']), 'ASSET_DIMENSIONS_MISMATCH')
        # Preserve decoded coordinates (as in ImageMatcher); do not rotate by EXIF.
        picture = original.convert('RGB')
        if roi is not None:
            require(valid_box(roi, *picture.size), 'REFERENCE_ROI_INVALID')
            picture = picture.crop(tuple(roi))
        picture.thumbnail((1280, 1280), Image.Resampling.LANCZOS)
        clean = Image.new('RGB', picture.size)
        clean.paste(picture)
        return clean


def valid_box(box, width, height):
    return (isinstance(box, (list, tuple)) and len(box) == 4
            and all(type(v) in (int, float) and math.isfinite(v) for v in box)
            and 0 <= box[0] < box[2] <= width and 0 <= box[1] < box[3] <= height)


def scene_svg(filename, asset, box):
    width, height = asset['width'], asset['height']
    rect = ''
    if valid_box(box, width, height):
        x1, y1, x2, y2 = box
        rect = (f'<rect x="{x1}" y="{y1}" width="{x2-x1}" height="{y2-y1}" '
                f'fill="none" stroke="#ef963c" stroke-width="{max(2, width/250)}"/>')
    return (f'<svg role="img" aria-label="完整场景及本地检测框" viewBox="0 0 {width} {height}">'
            f'<image href="previews/{escaped(filename)}" width="{width}" height="{height}"/>{rect}</svg>')


def build_report(prepared_path, summary_path, output, repo):
    prepared_path, summary_path, output = [private_path(p, repo) for p in (prepared_path, summary_path, output)]
    require(not output.exists(), 'OUTPUT_MUST_BE_NEW')
    for path in (output / 'index.html', output / 'previews' / '0.jpg'):
        private_path(path, repo)
    prepared_raw = prepared_path.read_bytes()
    prepared, summary = json.loads(prepared_raw), json.loads(summary_path.read_bytes())
    require(summary.get('prepared_sha256') == hashlib.sha256(prepared_raw).hexdigest(), 'PREPARED_HASH_MISMATCH')
    require(all(data.get('source_kind') == 'real_upload' and data.get('scope') == 'diagnostic_reused'
                for data in (prepared, summary)), 'SOURCE_OR_SCOPE_MISMATCH')
    workspace = private_path(prepared['workspace'], repo)
    reference = prepared['reference']
    require(reference.get('roi_reviewed') is True and reference.get('identity_reviewed') is True, 'REFERENCE_NOT_REVIEWED')
    previews = [checked_image(workspace, reference, reference['roi'])]
    scenes = prepared['scenes']
    require(len({s['sample_id'] for s in scenes}) == len(scenes), 'DUPLICATE_SAMPLE')
    previews.extend(checked_image(workspace, s['asset']) for s in scenes)
    output.mkdir(parents=True)
    (output / 'previews').mkdir()
    for index, picture in enumerate(previews):
        picture.save(output / 'previews' / f'{index}.jpg', quality=85)
    parts = ['<!doctype html><html lang="zh-CN"><meta charset="utf-8">',
             '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; img-src \'self\'; style-src \'unsafe-inline\'; base-uri \'none\'; form-action \'none\'">',
             '<meta name="viewport" content="width=device-width,initial-scale=1"><title>HomeTrace 私有实拍验收</title>',
             '<style>body{font:16px/1.6 system-ui;margin:24px auto;padding:0 20px;max-width:1100px;background:#f5f7fa;color:#19283a}article,header{background:white;padding:24px;margin:18px 0;border-radius:16px}svg{display:block;max-width:560px;max-height:650px;width:100%}img{max-width:100%;max-height:400px}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#eef1f5;padding:12px}summary{cursor:pointer}nav a{display:inline-block;margin:5px}strong{color:#9e4a00}</style>',
             '<header><h1>HomeTrace 实拍 Agent 结果审查</h1><p>真实上传 real_upload · 已复用开发图 diagnostic_reused · 非独立测试。模拟导航和演示地点映射，不证明实际拍摄位置。</p>',
             '<p>仅查看既有执行记录：本页不调用模型、不上传图片、不确认身份、不写入记忆。云端意见是 ADVISORY_ONLY；相似不等于生产 FOUND。</p>',
             f'<p>执行完成：{escaped(summary.get("execution_finished", False))}；自动身份确认：未执行。待主人核对的图片可按“图号：正确 / 错误 / 不确定 + 原因”回复。</p>',
             details('执行概况、失败及未执行', {k: summary.get(k) for k in ('transport', 'location_mapping', 'usage', 'reserved_vision_calls', 'failed_attempts', 'unexecuted', 'owner_history_rows_after')}),
             '<h2>固定登记参考 ROI</h2><img src="previews/0.jpg" alt="已批准参考区域">',
             details('参考来源与 ROI', {k: reference.get(k) for k in ('sha256', 'roi', 'roi_reviewed', 'identity_reviewed', 'review_source')}), '</header><nav>',
             *[f'<a href="#s{i}">{escaped(s["sample_id"])}</a>' for i, s in enumerate(scenes)], '</nav>']
    for index, scene in enumerate(scenes):
        asset, sample = scene['asset'], scene['sample_id']
        runs = [r for r in summary.get('runs', []) if sample in r.get('samples', [])]
        local, advice = [], []
        for run in runs:
            final = run.get('final', {})
            for obs_index, observation in enumerate(final.get('observations', [])):
                if observation.get('asset_id') == asset['asset_id'] and observation.get('image_sha256') == asset['sha256']:
                    local.append(observation)
                    advice.extend(a for a in final.get('visual_advice', []) if a.get('observation_index') == obs_index)
        box = local[-1].get('bbox') if local else None
        parts.extend([f'<article id="s{index}"><h2>{escaped(sample)}</h2>', scene_svg(f'{index+1}.jpg', asset, box),
                      '<p><strong>' + ('橙框为实际本地候选，不代表身份确认。' if valid_box(box, asset['width'], asset['height']) else '无有效本地检测框；未使用 LLM 文字生成框。') + '</strong></p>',
                      details('原图 SHA256', asset['sha256']), details('本轮 Agent 本地观察 / 匹配诊断', local or '未执行或无对应记录'),
                      details('准备阶段本地诊断（不代表 Agent 已执行）', [r for r in prepared.get('local_results', []) if r.get('sample_id') == sample]),
                      '<h3>实际云端意见</h3>'])
        appearance_names = {'similar': '外观相似，需主人核对', 'different': '外观不同',
                            'not_visible': '本图未见目标外观', 'uncertain': '无法确定'}
        for row in advice:
            model_advice = row.get('advice', {}).get('model_advice', {})
            appearance = model_advice.get('appearance')
            parts.extend([f'<p><strong>{escaped(appearance_names.get(appearance, row.get("execution_status", "未执行")))}</strong></p>',
                          f'<p>{escaped(model_advice.get("reason", row.get("error_code", "")))}</p>',
                          details('云端结果 / 耗时 / token', row)])
        if not advice:
            parts.append('<p>未执行、未返回或失败；不能算作通过。</p>')
        for run in runs:
            final = run.get('final', {})
            parts.extend([f'<h3>所在会话最终状态：{escaped(final.get("state", "未完成"))}</h3><p>{escaped(final.get("reply", ""))}</p>',
                          f'<p>该会话包含：{escaped(" → ".join(run.get("samples", [])))}。以上云端意见仅对应本张图；最终状态可能来自后续补图。</p>',
                          details('状态、用量、失败与人工操作', {k: final.get(k) for k in ('run_id', 'model_calls', 'total_tokens', 'vision_calls', 'vision_actual_tokens', 'photo_request', 'llm_explanation')} | {k: run.get(k) for k in ('pending_reason', 'failure_type', 'operator_actions')}),
                          details('真实工具轨迹（同一 run 的完整轨迹）', final.get('trace', []))])
        if not runs:
            parts.append('<p>Agent 未执行本场景。</p>')
        parts.append('</article>')
    parts.append('</html>')
    (output / 'index.html').write_text('\n'.join(parts), encoding='utf-8')
    return output / 'index.html'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('prepared', 'summary', 'output-dir'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args(argv)
    print(build_report(args.prepared, args.summary, args.output_dir, Path(__file__).resolve().parents[1]))


if __name__ == '__main__':
    main()
