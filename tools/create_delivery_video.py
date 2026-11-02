"""Caption the actual current browser recording; never reconstruct screen frames.

The full browser video is preserved at original speed. Added title/end cards and
Chinese subtitles explicitly describe software fixtures and scripted owner clicks.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess


CAPTIONS = {
    'empty-workspace': '从空工作区开始：没有预装物品、历史或搜索结果。',
    'reference-ROI': '登记名称与固定参考区域；素材是 AI 合成软件样例，不训练专用网络。',
    'memory-confirmation': '实际文本 LLM 理解“放在这里”；先等待主人确认，不提前写位置。',
    'memory-saved': '脚本模拟主人点击后，SQLite 保存 owner_reported 历史记忆。',
    'changed-scenes': '软件场景发生变化：旧处为空、新处有候选；这不是机器人实拍。',
    'search-in-progress': '真实文本 LLM 选择工具；依据历史与实际本地图像反馈继续寻找。',
    'actual-candidate': '检测框来自本地 ORB 实际匹配；只是外观候选，等待主人核对。',
    'search-order': '先检查配置及字母序末尾的历史地点，再检查新地点。',
    'current-image-evidence': '实际观察区保留空场景和候选图；历史记忆不替代当前观察。',
    'real-tool-trace': '可追溯工具链：真实模型决策、模拟导航、本地匹配及返回结果。',
    'user-confirmed': '脚本模拟主人确认：状态 USER_CONFIRMED，不是自动视觉 FOUND。',
    'history-query': '再次由真实文本 LLM 查询持久记忆，读回最新主人确认的位置。',
    'model-call-metrics': '界面显示本次实际模型调用与 Token；本轮没有图片外发。',
}


def stamp(value):
    return f'{int(value // 3600)}:{int(value // 60) % 60:02d}:{value % 60:05.2f}'


def probe(path):
    return json.loads(subprocess.check_output([
        'ffprobe', '-v', 'error', '-show_entries',
        'format=duration,size:stream=codec_name,width,height', '-of', 'json', str(path)]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--recording-dir', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    directory, output = args.recording_dir.resolve(), args.output.resolve()
    checks = json.loads((directory / 'browser-checks.json').read_text(encoding='utf-8'))
    if not checks.get('passed') or checks.get('errors') or checks.get('private_photographs') is not False:
        raise ValueError('Successful synthetic-only browser verification is required')
    if output.exists():
        raise ValueError('Never overwrite an existing video')
    source = directory / Path(checks['video']).name
    duration = float(probe(source)['format']['duration'])
    output.parent.mkdir(parents=True, exist_ok=True)
    lines = ['[Script Info]', 'ScriptType: v4.00+', 'PlayResX: 1440', 'PlayResY: 1080', 'WrapStyle: 0', '',
             '[V4+ Styles]', 'Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding',
             'Style: Body,Microsoft YaHei,26,&H00F1F6F7,&H00FFFFFF,&H001E3039,&H001E3039,0,0,0,0,100,100,0,0,1,1,0,2,40,40,14,1',
             'Style: Title,Microsoft YaHei,54,&H00F1F6F7,&H00FFFFFF,&H001E3039,&H001E3039,1,0,0,0,100,100,0,0,1,0,0,5,80,80,0,1', '',
             '[Events]', 'Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text']
    def caption(start, stop, text, style='Body'):
        lines.append(f'Dialogue: 0,{stamp(start)},{stamp(stop)},{style},,0,0,0,,{text}')
    end = duration + 6
    caption(0, 6, r'HomeTrace\N记住物品，循着证据寻找', 'Title')
    caption(0, 6, r'当前版本真实浏览器录屏 · 中文字幕版\N合成素材验证软件流程，不证明真实家庭通用识别')
    caption(6, end, r'{\an8\pos(720,10)}AI 合成软件素材  |  真实文本 LLM  |  本地 ORB  |  模拟导航')
    chapters = checks['chapters']
    for index, chapter in enumerate(chapters):
        stop = min(duration, chapters[index + 1]['seconds'] if index + 1 < len(chapters) else duration)
        if stop > chapter['seconds']:
            caption(6 + chapter['seconds'], 6 + stop, CAPTIONS[chapter['name']])
    caption(end, end + 8, r'有记忆、有行动、有证据、有边界', 'Title')
    caption(end, end + 8,
            f"本次 {checks['usage']['model_calls']} 次真实文本调用；图片外发 0 次；无自动 FOUND。"
            r'\N真实水杯自动定位与独立实例识别仍未通过；主人确认动作由脚本模拟。')
    (directory / 'delivery-narration.ass').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    edit = {'source': source.name, 'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
            'source_seconds': duration, 'original_speed': True, 'cuts': [],
            'timeline': [{'kind': 'title_card', 'output_start': 0, 'output_end': 6},
                         {'kind': 'unaltered_browser_frames_scaled_and_captioned', 'source_start': 0,
                          'source_end': duration, 'output_start': 6, 'output_end': end},
                         {'kind': 'end_card', 'output_start': end, 'output_end': end + 8}],
            'chapters': chapters, 'audio': 'No audio; Chinese subtitles'}
    (directory / 'editing-timeline.json').write_text(json.dumps(edit, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    filters = ('color=c=0x142c35:s=1440x1080:r=25:d=6[intro];'
               '[0:v]fps=25,scale=1280:960,pad=1440:1080:80:55:color=0x142c35,setsar=1[screen];'
               'color=c=0x142c35:s=1440x1080:r=25:d=8[outro];'
               '[intro][screen][outro]concat=n=3:v=1:a=0,ass=delivery-narration.ass[out]')
    subprocess.run(['ffmpeg', '-n', '-v', 'warning', '-i', str(source), '-filter_complex', filters,
                    '-map', '[out]', '-c:v', 'libx264', '-preset', 'medium', '-crf', '20', '-pix_fmt', 'yuv420p',
                    '-movflags', '+faststart', str(output)], cwd=directory, check=True)
    subprocess.run(['ffmpeg', '-v', 'error', '-xerror', '-i', str(output), '-f', 'null', '-'], check=True)
    metadata = {**probe(output), 'full_decode_passed': True, 'source_sha256': edit['source_sha256'],
                'output_sha256': hashlib.sha256(output.read_bytes()).hexdigest(), 'browser_evidence_passed': True,
                'frame_origin': 'Actual browser recording at original speed; title/end cards and subtitles added',
                'real_household_validation': False, 'image_calls': 0, 'usage': checks['usage'],
                'scripted_owner_actions': True, 'automatic_FOUND': False}
    output.with_suffix('.metadata.json').write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(metadata, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
