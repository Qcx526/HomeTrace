"""Edit existing keys recording then a real-cup task review, with Chinese captions.

No model client, new experiment or invented UI is used. Crops are editorial
focus areas, recorded in metadata. Source footage and frozen reports are never
changed. Run with Pillow and ffmpeg in the optional authoring environment.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

from PIL import Image, ImageDraw, ImageFont

from create_delivery_video import probe


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def fit(image, box):
    image = image.convert('RGB')
    ratio = min(box[2] / image.width, box[3] / image.height)
    image = image.resize((round(image.width * ratio), round(image.height * ratio)), Image.Resampling.LANCZOS)
    return image, (box[0] + (box[2] - image.width) // 2,
                   box[1] + (box[3] - image.height) // 2)


def text_lines(draw, text, font, width):
    lines, line = [], ''
    for char in text:
        if char == '\n' or draw.textlength(line + char, font=font) > width:
            lines.append(line)
            line = '' if char == '\n' else char
        else:
            line += char
    return lines + ([line] if line else [])


def card(title, subtitle, section, points, font_dir):
    canvas = Image.new('RGB', (1920, 1080), '#f4f7fb')
    d = ImageDraw.Draw(canvas)
    font = lambda size, bold=False: ImageFont.truetype(str(font_dir / ('msyhbd.ttc' if bold else 'msyh.ttc')), size)
    d.rectangle((0, 0, 1920, 10), fill='#1466ad')
    d.text((60, 38), 'HomeTrace', font=font(32, True), fill='#17456b')
    d.text((60, 100), title, font=font(56, True), fill='#17364e')
    d.text((60, 178), section, font=font(24), fill='#587186')
    d.rounded_rectangle((60, 245, 1295, 925), radius=22, fill='white')
    d.text((1360, 270), '记住 · 寻找 · 核对', font=font(30, True), fill='#1466ad')
    y = 355
    for index, point in enumerate(points):
        d.ellipse((1360, y+9, 1374, y+23), fill='#2f8d8a')
        for line in text_lines(d, point, font(32), 430):
            d.text((1395, y), line, font=font(32), fill='#274356')
            y += 50
        y += 38
    d.rectangle((0, 980, 1920, 1080), fill='#17364e')
    lines = text_lines(d, subtitle, font(34), 1800)
    if len(lines) > 2:
        raise ValueError('Caption exceeds two lines')
    for index, line in enumerate(lines):
        w = d.textlength(line, font=font(34))
        d.text(((1920-w)/2, 994 + index*43), line, font=font(34), fill='white')
    return canvas


def create(recording, frames, review, output, work, font_dir):
    recording, frames, review, output, work, font_dir = map(Path, (recording, frames, review, output, work, font_dir))
    if output.exists() or output.with_suffix('.metadata.json').exists() or work.exists():
        raise ValueError('Use new output and working directories; historical outputs are immutable')
    repo = Path.cwd().resolve()
    for target in (output, output.with_suffix('.metadata.json'), work/'01.png'):
        relative = target.resolve().relative_to(repo)
        if subprocess.run(['git','check-ignore','--quiet','--',relative.as_posix()],capture_output=True).returncode:
            raise ValueError('Media and intermediate outputs must remain Git ignored')
    checks = json.loads((recording/'browser-checks.json').read_text(encoding='utf-8'))
    audit = json.loads(review.read_text(encoding='utf-8'))
    if (checks.get('passed') is not True or checks.get('errors')
            or checks.get('source') != 'hash_locked_AI_synthetic_software_fixture'
            or checks.get('real_text_llm') is not True or checks.get('local_ORB') is not True
            or checks.get('automatic_FOUND') is not False
            or audit.get('kind') != 'frozen_execution_review'
            or audit.get('new_model_calls') != 0 or audit.get('automatic_FOUND') is not False):
        raise ValueError('Expected verified software recording and frozen real-cup review')
    source = recording / Path(checks['video']).name
    work.mkdir(parents=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    key_label = '钥匙软件演示 · 合成示例 · 操作录像节选 · 模拟移动'
    cup_label = '实拍水杯 · 2026-11-02 任务回看 · 照片由主人提供 · 模拟移动'
    # Source coordinates refer only to the original screen, not target truth boxes.
    stages = [
        dict(title='物品忘在哪里，让记忆带着找', seconds=5, section='HomeTrace · 家庭寻物助手',
             caption='先看钥匙的完整操作流程，再看一只真实水杯的协作寻物。',
             points=['说一句话，记下物品与位置', '找不到时，循着记忆继续寻找', '拿不准时，请主人一起核对'], image='key_ref'),
        dict(title='先登记：这是我的钥匙', seconds=4, section=key_label,
             caption='登记名称和参考外观，以后寻找时就知道在找哪一件物品。',
             points=['参考图与名称一起保存', '确认参考中的物品范围', '登记新物品无需重新训练网络'], start=6.6, source_seconds=1.5, crop=[94,182,308,230]),
        dict(title='“钥匙我放这里了”', seconds=8, section=key_label,
             caption='先请主人核对要记住的位置，确认后再保存。',
             points=['理解主人想记录位置', '显示待保存内容', '确认后成为一条历史记忆'], start=15.0, source_seconds=6.0, crop=[477,603,870,125], image='key_ref'),
        dict(title='原处没有，继续找下一处', seconds=8, section=key_label,
             caption='先查上次的位置；原处未见目标，再检查新的地点。',
             points=['旧地点：托盘', '下一地点：桌面', '每一处保留当次图片'], image='key_evidence'),
        dict(title='找到外观候选，交给主人核对', seconds=5, section=key_label,
             caption='右侧红框来自程序在示例图片上的实际匹配，仍需主人核对。',
             points=['左边：已登记的外观', '右边：桌面上的候选', '不把相似外观直接当成同一件'], start=39.0, source_seconds=2.0, crop=[477,648,870,322]),
        dict(title='确认之后，记住新的位置', seconds=5, section=key_label,
             caption='这段软件操作由脚本模拟主人确认；程序按确认保存位置。',
             points=['保存的是主人确认的位置', '保留先前的历史', '以后可以再次查询'], start=60.0, source_seconds=1.5, crop=[477,603,648,60], image='key_ref'),
        dict(title='再次询问，读回最新记忆', seconds=4, section=key_label,
             caption='系统返回最近记录的地点，同时说明历史不等于此刻的位置。',
             points=['读取已经保存的历史', '不凭空编造物品位置', '钥匙操作流程完成'], start=67.0, source_seconds=2.0, crop=[477,225,870,60], image='key_ref'),
    ]
    cup = [
        ('接下来，寻找一只真实水杯', '这次要找的是主人登记的水杯，上次记在历史地点。', ['真实家庭照片', '已有参考外观', '已有主人提供的位置记忆'], 8),
        ('先回到上次记住的位置', '先看历史地点；照片中没有看到目标外观。', ['先查询最近历史', '检查历史地点照片', '依据观察继续决定'], 8),
        ('原处没有，转查下一处', '原处未见目标，助手继续检查新地点。', ['没有在原处就结束', '选择下一处可检查地点', '读取这一次的场景照片'], 8),
        ('远景看不清，请拍近一点', '杂物多、目标小，助手请求同一位置的近景。', ['远景只能提供线索', '请主人补充细节', '保留先前的照片'], 10),
        ('看到细节，请主人核对', '近景中的花纹、杯盖和底圈与参考相似，交给主人核对。', ['依据新增照片继续比较', '相似只是建议', '主人确认具体物品身份'], 10),
        ('主人确认后，保存这条历史', '主人确认是同一只水杯，并授权保存新地点的照片位置。', ['明确授权后保存', '新增一条位置记忆', '不推断未知的拍摄时间'], 9),
        ('重新打开，记忆仍然在', '程序重启后，再次查询，读回刚才确认的同一条记录。', ['位置记录持久保存', '再次查询可读回', '历史位置不保证此刻仍在'], 9),
        ('旧照片不能变成新发现', '重复使用旧照片时，系统不会再写成一次新的发现。', ['旧图重复使用被拦截', '没有新增位置历史', '拿不准时保留未确认'], 8),
    ]
    for i, (title, caption, points, seconds) in enumerate(cup):
        stages.append(dict(title=title, caption=caption, points=points, seconds=seconds,
                           section=cup_label, image=f'cup_{i+1:02d}'))
    stages.append(dict(title='从“记在哪里”，到“帮我一起找”', seconds=7,
                       section='HomeTrace · 已完成单物品、主人参与确认的软件流程',
                       caption='把位置记下来，根据反馈继续寻找，确认后留下下一次可用的记忆。',
                       points=['已展示：记忆、决策与协作核对', '后续：接入真实移动与实时观察', '家庭通用自动识别仍需验证'], image='cup_05'))
    source_hashes = {'keys_video': sha(source), 'keys_checks': sha(recording/'browser-checks.json'), 'cup_review': sha(review),
                     'keys_reference_frame': sha(recording/'02-reference-ROI.png')}
    reference = Image.open(recording/'02-reference-ROI.png').crop((94,182,402,412))
    timeline, total = [], 0.0
    for index, stage in enumerate(stages):
        canvas = card(stage['title'], stage['caption'], stage['section'], stage['points'], font_dir)
        box = (80, 265, 1195, 640)
        image_name = stage.get('image')
        if image_name:
            if image_name == 'key_ref':
                picture = reference.copy()
                if 'start' in stage:
                    box = (300, 270, 740, 415)
            elif image_name == 'key_evidence':
                evidence = Image.open(recording/'09-current-image-evidence.png')
                picture = Image.new('RGB',(842,300),'white')
                picture.paste(evidence.crop((490,681,890,907)),(0,37))
                picture.paste(evidence.crop((935,681,1332,981)),(445,0))
                source_hashes['keys_evidence_frame'] = sha(recording/'09-current-image-evidence.png')
            else:
                path = frames/(image_name[4:] + '.png')
                picture = Image.open(path).crop((444,198,1090,683))
                source_hashes[image_name] = sha(path)
            picture, position = fit(picture, box)
            canvas.paste(picture, position)
        background = work/f'{index:02d}.png'
        canvas.save(background)
        segment = work/f'{index:02d}.mp4'
        command = ['ffmpeg','-n','-v','error','-loop','1','-framerate','25','-i',str(background.resolve())]
        if 'start' in stage:
            x,y,w,h = stage['crop']
            area = (95,740,1160,150) if image_name else (95,270,1160,630)
            sw = min(area[2], int(w*area[3]/h))//2*2
            sh = int(h*sw/w)//2*2
            ox,oy = area[0]+(area[2]-sw)//2, area[1]+(area[3]-sh)//2
            command += ['-ss',str(stage['start']),'-i',str(source.resolve()),'-filter_complex',
                        f"[1:v]trim=duration={stage['source_seconds']},crop={w}:{h}:{x}:{y},scale={sw}:{sh},setsar=1,setpts=PTS-STARTPTS,tpad=stop_mode=clone:stop_duration={stage['seconds']-stage['source_seconds']}[clip];[0:v][clip]overlay={ox}:{oy}:shortest=1[out]", '-map','[out]']
        command += ['-t',str(stage['seconds']),'-an','-r','25','-c:v','libx264','-preset','fast','-crf','20','-pix_fmt','yuv420p',str(segment.resolve())]
        subprocess.run(command,check=True)
        timeline.append({**stage,'output_start':total,'output_end':total+stage['seconds'],
                         'kind':'original_speed_crop_then_final_frame_hold' if 'start' in stage else 'edited_evidence_recap',
                         'card_sha256':sha(background)})
        total += stage['seconds']
    playlist = work/'segments.txt'
    playlist.write_text(''.join(f"file '{i:02d}.mp4'\n" for i in range(len(stages))),encoding='ascii')
    subprocess.run(['ffmpeg','-n','-v','error','-f','concat','-safe','1','-i',str(playlist.resolve()),'-c','copy','-movflags','+faststart',str(output.resolve())],check=True)
    subprocess.run(['ffmpeg','-v','error','-xerror','-i',str(output),'-f','null','-'],check=True)
    result = {'kind':'keys_recording_then_real_cup_review','source_hashes':source_hashes,
              'source_bytes_unchanged':True,'new_model_calls':0,'image_uploads':0,'navigation':'simulated',
              'keys_source':'synthetic_software_fixture','keys_owner_actions':'scripted_clicks',
              'cup_source':'real_owner_photos_frozen_execution_review','cup_owner_confirmation':'explicit_owner_authorization',
              'continuous_live_run':False,'automatic_instance_recognition_passed':False,
              'audio':'none; burned-in Chinese subtitles','full_decode_passed':True,
              'timeline':timeline,'duration_seconds':total,'output_sha256':sha(output),**probe(output)}
    output.with_suffix('.metadata.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return result


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('recording','frames','review','output','work'):
        parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--font-dir',type=Path,default=Path('C:/Windows/Fonts'))
    args=parser.parse_args()
    result=create(args.recording,args.frames,args.review,args.output,args.work,args.font_dir)
    print(json.dumps({k:result[k] for k in ('duration_seconds','full_decode_passed','output_sha256')},indent=2))
