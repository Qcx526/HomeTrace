"""Append labelled, photo-free real-workflow evidence to an existing demo video.

The original browser recording section is retained in full at original speed.
The appendix is a report, not a reconstruction of UI actions or private photos.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

from create_delivery_video import probe, stamp


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def validate(source, metadata, evidence):
    if metadata.get('output_sha256') != digest(source):
        raise ValueError('Source video SHA256 mismatch')
    if (metadata.get('browser_evidence_passed') is not True
            or metadata.get('automatic_FOUND') is not False
            or metadata.get('scripted_owner_actions') is not True
            or metadata.get('real_household_validation') is not False):
        raise ValueError('Expected the documented synthetic browser demo')
    if (evidence.get('navigation') != 'simulated'
            or evidence.get('automatic_instance_validation') != 'BLOCKED'
            or evidence.get('truth_boxes') is not None
            or evidence['first']['runs']['main']['state'] != 'BUDGET_EXCEEDED'
            or evidence['second']['runs']['main']['state'] != 'USER_CONFIRMED'
            or evidence['second']['new_owner_events'] != 1
            or not evidence['second']['checks']
            or any(c.get('passed') is not True for c in evidence['second']['checks'])):
        raise ValueError('Evidence does not support this dated report appendix')
    main = evidence['second']['runs']['main']
    if main.get('automatic_found') is not False:
        raise ValueError('Owner confirmation must not be described as automatic FOUND')
    for sample in ('04', '05'):
        if evidence['first']['runs'][f'control-scene-{sample}']['state'] != 'UNKNOWN':
            raise ValueError('Negative controls must retain their actual UNKNOWN status')


def build(source, metadata_path, evidence_path, output):
    source, metadata_path, evidence_path, output = map(Path, (source, metadata_path, evidence_path, output))
    metadata = json.loads(metadata_path.read_text(encoding='utf-8'))
    evidence = json.loads(evidence_path.read_text(encoding='utf-8'))
    validate(source, metadata, evidence)
    audit_path = output.with_suffix('.metadata.json')
    if output.exists() or audit_path.exists():
        raise ValueError('Never overwrite an existing video or audit')
    output.parent.mkdir(parents=True, exist_ok=True)
    duration = float(probe(source)['format']['duration'])
    main = evidence['second']['runs']['main']
    cards = [
        ('真实水杯：从记忆到反馈寻找',
         r'第二部分是 2026-11-02 实际执行记录摘要，不是实时录屏。\N私人照片不展示；使用脱敏场景 S1–S5。\N真实 HTTP 服务与第三方模型调用；导航仍为模拟。'),
        ('不确定时，主动要求更好的证据',
         r'先查历史地点 H：S1 未见目标 → 转向地点 B。\NS2 全景不确定 → LLM 调用 request_new_photo。\N主人提供 S3 近景 → 相似建议 → 请求主人核对。'),
        ('主人确认之后，才更新历史',
         r'依据负责人明确授权，通过 HTTP 保存照片位置历史。\NUSER_CONFIRMED / owner_reported；不是自动 FOUND。\N新进程恢复同一记录；真实 LLM 查询成功；旧图重放拒绝。'),
        ('真实结果，同时保留失败',
         f"成功主流程：{main['model_calls']} 次文本调用 / {main['decision_tokens']} Token；"
         rf"\N{main['vision_calls']} 次视觉调用 / {main['vision_tokens']} Token；新增 1 条主人历史。"
         r'\N相似杯和空场景控制均 UNKNOWN，无新增记忆。'),
        ('预算失败与能力边界',
         r'首次 24,000 Token 预算停止、没有保存；失败记录保留。\N调整至 32,000 后完成；模型、识别阈值和零重试规则不变。\N实拍 ORB 均无可靠框；独立实例识别尚未通过。'),
        ('可演示的创新：有依据地寻找',
         r'记住来源 → 根据反馈选工具 → 请求补拍 → 主人核对 → 持久记忆。\N当前是一件水杯的受限人机协作 Demo；不是通用自动识别。\N官方个人信息待填写，代码待审查，平台要求待核验。'),
    ]
    card_seconds = 12
    appendix_seconds = len(cards) * card_seconds
    header = [
        '[Script Info]', 'ScriptType: v4.00+', 'PlayResX: 1440', 'PlayResY: 1080', 'WrapStyle: 0',
        '', '[V4+ Styles]',
        'Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding',
        'Style: Title,Microsoft YaHei,52,&H00EFF4F2,&H00FFFFFF,&H001E3039,&H001E3039,1,0,0,0,100,100,0,0,1,0,0,5,90,90,0,1',
        'Style: Body,Microsoft YaHei,34,&H00EFF4F2,&H00FFFFFF,&H001E3039,&H001E3039,0,0,0,0,100,100,0,0,1,0,0,5,80,80,0,1',
        'Style: Label,Microsoft YaHei,24,&H00B8CFBF,&H00FFFFFF,&H001E3039,&H001E3039,0,0,0,0,100,100,0,0,1,0,0,5,80,80,0,1',
        '', '[Events]', 'Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text',
    ]
    for i, (title, body) in enumerate(cards):
        start, end = i * card_seconds, (i + 1) * card_seconds
        for style, y, text in [('Title', 320, title), ('Body', 560, body),
                               ('Label', 900, '实拍执行记录摘要 · 非实时录屏 · 私人照片未展示')]:
            header.append(f'Dialogue: 0,{stamp(start)},{stamp(end)},{style},,0,0,0,,{{\\pos(720,{y})}}{text}')
    with tempfile.TemporaryDirectory(prefix='video-appendix-', dir=output.parent) as temp:
        directory = Path(temp)
        (directory / 'appendix.ass').write_text('\n'.join(header) + '\n', encoding='utf-8')
        filters = (f'color=c=0x142c35:s=1440x1080:r=25:d={appendix_seconds},ass=appendix.ass[appendix];'
                   '[0:v]fps=25,setsar=1[source];[source][appendix]concat=n=2:v=1:a=0[out]')
        subprocess.run(['ffmpeg', '-n', '-v', 'warning', '-i', str(source.resolve()),
                        '-filter_complex', filters, '-map', '[out]', '-c:v', 'libx264',
                        '-preset', 'medium', '-crf', '20', '-pix_fmt', 'yuv420p',
                        '-movflags', '+faststart', str(output.resolve())], cwd=directory, check=True)
    subprocess.run(['ffmpeg', '-v', 'error', '-xerror', '-i', str(output), '-f', 'null', '-'], check=True)
    result = {**probe(output), 'output_sha256': digest(output), 'full_decode_passed': True,
              'source_video_sha256': digest(source), 'source_metadata_sha256': digest(metadata_path),
              'public_evidence_sha256': digest(evidence_path), 'source_commit': evidence['source_commit'],
              'new_model_calls': 0, 'new_image_sends': 0, 'private_photos_in_video': False,
              'automatic_FOUND': False, 'independent_instance_benchmark_passed': False,
              'audio': 'No audio; Chinese subtitles and evidence cards',
              'timeline': [{'start': 0, 'end': duration, 'kind': 'existing synthetic demo video: title, original-speed browser recording, end card'},
                           *[{'start': duration+i*card_seconds, 'end': duration+(i+1)*card_seconds,
                              'kind': 'real workflow report card, NOT browser footage', 'title': card[0]}
                             for i, card in enumerate(cards)]]}
    with audit_path.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--source-metadata', type=Path, required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = build(args.source, args.source_metadata, args.evidence, args.output)
    print(json.dumps(result, ensure_ascii=True, indent=2))
