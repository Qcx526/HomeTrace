"""Join two actual browser recordings at original speed with Chinese captions.

Keys: an existing executed software example. Cup: read-only inspection of a
previously completed real-photo task in the unchanged production HTML interface.
No slide frames, manufactured clicks, inference or new detection boxes are used.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

from create_delivery_video import probe, stamp


KEY_CAPTIONS = {
    'empty-workspace': '先从空工作区开始，登记物品并记住位置。',
    'reference-ROI': '这是我的钥匙：登记名称，并框选参考外观。',
    'memory-confirmation': '“钥匙我放在这里了。”系统理解请求，先请主人核对位置。',
    'memory-saved': '点击确认后，位置才写入记忆；以后可以再次查询。',
    'changed-scenes': '现在把场景换成：旧处没有钥匙，新地点出现候选。',
    'search-in-progress': '“帮我找一下钥匙。”系统先查最近记忆，再按观察反馈继续寻找。',
    'actual-candidate': '界面显示实际匹配框，并把候选交给主人核对。',
    'search-order': '先查上次记录的位置，再去其他地点，搜索顺序有据可查。',
    'current-image-evidence': '每一步都保留当前图像；历史位置不能替代这次观察。',
    'real-tool-trace': '展开执行轨迹，可以看到实际工具调用和下一步决定。',
    'user-confirmed': '主人核对后保存新位置；外观相似不会自动变成身份确认。',
    'history-query': '再问一次位置，系统读回刚刚保存的记忆。',
    'model-call-metrics': '下面切换到真实水杯，在同一 HTML 界面查看已完成任务。',
}
CUP_CAPTIONS = {
    'cup-overview': '真实水杯案例：打开已完成任务，下面直接操作实际 HTML 页面。',
    'registered-cup': '先选择登记的水杯，查看主人批准的参考外观。',
    'saved-search-order': '这次任务从原位置查起，随后转查另一处桌面。',
    'original-place-not-visible': '第一张照片没有看到目标，系统没有把旧记忆当作现在的位置。',
    'wide-view-uncertain': '新地点远景中有疑似水杯，但细节不够，判断仍不确定。',
    'close-view-advice': '补充近景后，外观建议更明确，接下来请主人核对。',
    'scene-wide-photo': '在实际观察区查看原始远景，照片中的水杯由主人提供。',
    'scene-close-photo': '继续查看近景。这里没有可靠检测框，保留完整照片供核对。',
    'feedback-decisions': '滚动到工具轨迹，检查系统依据什么反馈选择下一步。',
    'feedback-next-action': '换地点、请求近景、请主人核对，都有对应的执行记录。',
    'saved-owner-confirmation': '主人已确认是同一只水杯，授权保存这条照片位置历史。',
    'restart-history': '打开重启后查询的已存记录，位置记忆依然可以读回。',
    'history-still-saved': '展开历史查看来源；照片中的位置不保证物品此刻仍在那里。',
    'old-photo-not-new-evidence': '旧图再次使用时不当作新证据，也不重复生成已找到的结论。',
    'future-voice-and-robot': '后续加入语音输入；接入机器人建图、定位、导航和相机后，再验证全屋搜索。',
}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def create(keys, cup, output, work):
    keys, cup, output, work = map(lambda x: Path(x).resolve(), (keys, cup, output, work))
    if output.exists() or output.with_suffix('.metadata.json').exists() or work.exists():
        raise ValueError('Use fresh output paths; prior media remains unchanged')
    for p in (output, work/'timing.json'):
        rel=p.relative_to(Path.cwd().resolve())
        if subprocess.run(['git','check-ignore','--quiet','--',rel.as_posix()],capture_output=True).returncode:
            raise ValueError('Private media outputs must be Git ignored')
    a=json.loads((keys/'browser-checks.json').read_text(encoding='utf8'))
    b=json.loads((cup/'recording.private.json').read_text(encoding='utf8'))
    if (a.get('passed') is not True or a.get('errors') or a.get('automatic_FOUND') is not False
            or a.get('source')!='hash_locked_AI_synthetic_software_fixture'
            or b.get('passed') is not True or b.get('errors')
            or b.get('kind')!='production_html_saved_task_inspection'
            or b.get('new_model_calls')!=0 or b.get('image_uploads')!=0
            or not all(x['local'] and x['method']=='GET' for x in b['network'])):
        raise ValueError('Both browser recordings must have passing provenance checks')
    sources=[keys/Path(a['video']).name,cup/Path(b['video']).name]
    if sha(sources[1])!=b['video_sha256']:
        raise ValueError('Cup recording changed after validation')
    durations=[float(probe(p)['format']['duration']) for p in sources]
    output.parent.mkdir(parents=True,exist_ok=True);work.mkdir(parents=True)
    lines=['[Script Info]','ScriptType: v4.00+','PlayResX: 1440','PlayResY: 1200','WrapStyle: 0','',
      '[V4+ Styles]','Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding',
      'Style: Body,Microsoft YaHei,28,&H00FFFFFF,&H00FFFFFF,&H00283B30,&H00283B30,0,0,0,0,100,100,0,0,1,1,0,2,35,35,18,1',
      'Style: Header,Microsoft YaHei,23,&H00FFFFFF,&H00FFFFFF,&H00283B30,&H00283B30,0,0,0,0,100,100,0,0,1,1,0,8,25,25,9,1','',
      '[Events]','Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text']
    def cap(start,end,text,style='Body'):
        lines.append(f'Dialogue: 0,{stamp(start)},{stamp(end)},{style},,0,0,0,,{text}')
    offset=0; timeline=[]
    headers=['钥匙软件案例 · 完整操作录像 · 合成示例 · 模拟导航',
             '实拍水杯 · 已完成任务的实际网页回看 · 本轮不重新执行 · 模拟导航']
    for number,(record,duration,captions) in enumerate(zip((a,b),durations,(KEY_CAPTIONS,CUP_CAPTIONS))):
        cap(offset,offset+duration,headers[number],'Header')
        chapters=record['chapters']
        cap(offset,offset+chapters[0]['seconds'],list(captions.values())[0])
        for i,c in enumerate(chapters):
            stop=chapters[i+1]['seconds'] if i+1<len(chapters) else duration
            cap(offset+c['seconds'],offset+stop,captions[c['name']])
        timeline.append({'kind':'actual_browser_recording' if number==0 else 'production_html_saved_task_inspection',
                         'source_sha256':sha(sources[number]),'source_start':0,'source_end':duration,
                         'output_start':offset,'output_end':offset+duration,'speed':1,'cuts':[],
                         'chapters':chapters})
        offset+=duration
    (work/'captions.ass').write_text('\n'.join(lines)+'\n',encoding='utf8')
    filters=';'.join(f'[{i}:v]fps=25,scale=1440:1080,pad=1440:1200:0:50:color=0x173c36,setsar=1[v{i}]' for i in range(2))
    filters+=';[v0][v1]concat=n=2:v=1:a=0,ass=captions.ass[out]'
    subprocess.run(['ffmpeg','-n','-v','warning','-i',str(sources[0]),'-i',str(sources[1]),
                    '-filter_complex',filters,'-map','[out]','-c:v','libx264','-crf','20','-preset','medium',
                    '-pix_fmt','yuv420p','-movflags','+faststart',str(output)],cwd=work,check=True)
    subprocess.run(['ffmpeg','-v','error','-xerror','-i',str(output),'-f','null','-'],check=True)
    data={'kind':'two_actual_html_recordings','source_bytes_unchanged':True,'new_model_calls':0,'image_uploads':0,
          'navigation':'simulated','cup_new_inference':False,'automatic_instance_recognition_passed':False,
          'privacy':b['privacy'],'audio':'none; Chinese subtitles burned in','timeline':timeline,
          'browser_footage_fraction':1.0,'full_decode_passed':True,'output_sha256':sha(output),**probe(output)}
    output.with_suffix('.metadata.json').write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    return data


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('keys','cup','output','work'):p.add_argument('--'+name,type=Path,required=True)
    args=p.parse_args();result=create(args.keys,args.cup,args.output,args.work)
    print(json.dumps({k:result[k] for k in ('output_sha256','full_decode_passed','format')},indent=2))
