"""Export an offline, read-only review of frozen household workflow snapshots.

This is an edited presentation of existing execution, never a new Agent run.
Inputs and output contain private photos and must remain local / Git ignored.
Only selected fields are exported; no model client, key, DB or write API is used.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def validate(summary):
    main = summary['runs']['main']['final']
    history = summary['runs']['history']['final']
    replay = summary['runs']['replay']['final']
    if (main['state'] != 'USER_CONFIRMED' or main['visual_confirmed'] is not False
            or main['owner_event']['source_kind'] != 'owner_reported'
            or main['owner_event']['visual_confirmed'] is not False):
        raise ValueError('Expected owner-confirmed history, not automatic identification')
    saved = main['owner_event']
    restored = [e for e in history['history'] if e['event_id'] == saved['event_id']]
    # `created` is a response-only insertion flag, not a persisted event field.
    # The same ID with changed location, source or timestamps is not restoration.
    if (history['state'] != 'COMPLETED' or len(restored) != 1
            or any(restored[0].get(k) != v for k, v in saved.items() if k != 'created')):
        raise ValueError('Restart query does not contain the saved event')
    if replay['state'] != 'UNKNOWN' or replay.get('vision_calls') != 0:
        raise ValueError('Replay must remain UNKNOWN with no new image calls')
    if not summary['checks'] or any(c['passed'] is not True for c in summary['checks']):
        raise ValueError('Original workflow acceptance has a failed check')
    return main


def build(summary_path, plan_path, story_path, output, repo):
    summary_path, plan_path, story_path, output, repo = map(
        lambda p: Path(p).resolve(), (summary_path, plan_path, story_path, output, repo))
    if output.exists():
        raise ValueError('Never overwrite a review or frozen evidence')
    relative = output.relative_to(repo)
    if subprocess.run(['git', '-C', str(repo), 'check-ignore', '--quiet', '--',
                       relative.as_posix() + '/index.html'], capture_output=True).returncode:
        raise ValueError('Private review output must be Git ignored')
    summary, plan, story = read(summary_path), read(plan_path), read(story_path)
    main = validate(summary)
    ref = plan['reference']
    if ref['roi_reviewed'] is not True or ref['source_kind'] != 'real_upload':
        raise ValueError('A reviewed real reference is required')
    workspace = Path(plan['workspace']).resolve()
    ref_path = (workspace / ref['path']).resolve()
    ref_path.relative_to(workspace)
    sources = {'reference': (ref_path, ref['sha256'])}
    scene_assets = {}
    for s in plan['scenes']:
        if (not isinstance(s['sample_id'], str)
                or not re.fullmatch(r'[A-Za-z0-9_-]+', s['sample_id'])
                or s['sample_id'] in sources):
            raise ValueError('Scene IDs must be unique safe file names')
        sources[s['sample_id']] = (Path(s['local_path']), s['sha256'])
        scene_assets[s['sample_id']] = s['asset_id']
    for path, expected in sources.values():
        if digest(path) != expected:
            raise ValueError('Original photo SHA256 mismatch')
    stages = []
    for chapter in story['chapters']:
        run = summary['runs'][chapter['run']]
        if chapter['version'] == 'final':
            snapshot = run['final']
        else:
            snapshot = next(s for s in run['snapshots'] if s['version'] == chapter['version'])
        if snapshot['state'] != chapter['expected_state']:
            raise ValueError('Chapter state differs from its frozen snapshot')
        scene = chapter['scene']
        if scene not in sources:
            raise ValueError('Chapter uses an unknown photo')
        if scene != 'reference':
            if chapter['run'] == 'history':
                # History queries have no new observation. They may display only
                # the already saved candidate, clearly presented as a past photo.
                if scene_assets[scene] != main['candidate']['asset_id']:
                    raise ValueError('History photo is not the saved candidate')
                saved = main['owner_event']
                if (snapshot['state'] != 'COMPLETED'
                        or not any(all(e.get(k) == v for k, v in saved.items() if k != 'created')
                                   for e in snapshot['history'])):
                    raise ValueError('History chapter has not restored the saved event')
            elif scene_assets[scene] not in {o['asset_id'] for o in snapshot['observations']}:
                raise ValueError('Photo was not yet observed in this snapshot')
        trace = [{'tool': e['tool'], 'seq': e['seq']} for e in snapshot['trace']]
        stages.append({**chapter, 'state': snapshot['state'], 'trace': trace,
                       'actual_version': snapshot['version'],
                       'model_calls': snapshot['model_calls'],
                       'vision_calls': snapshot.get('vision_calls', 0),
                       'image': scene + '.jpg'})
    payload = {'date': story['date'], 'object': main['selected_object']['name'],
               'reference': {'width': ref['width'], 'height': ref['height'], 'roi': ref['roi']},
               'chapters': stages}
    output.mkdir(parents=True)
    for name, (path, _) in sources.items():
        shutil.copyfile(path, output / (name + '.jpg'))
    # Escape script terminators and U+2028 so private labels cannot inject markup.
    encoded = json.dumps(payload, ensure_ascii=False).replace('<', '\\u003c').replace('\u2028', '\\u2028')
    (output / 'index.html').write_text(HTML.replace('__DATA__', encoded), encoding='utf-8')
    audit = {'kind': 'frozen_execution_review', 'new_model_calls': 0,
             'continuous_live_recording': False, 'automatic_FOUND': False,
             'photo_bytes_unchanged': True, 'masking': 'presentation overlays only',
             'input_sha256': {p.name: digest(p) for p in (summary_path, plan_path, story_path)},
             'images': {name: expected for name, (_, expected) in sources.items()},
             'chapters': [{'run': c['run'], 'version': c['actual_version'],
                           'state': c['state'], 'scene': c['scene']} for c in stages]}
    (output / 'review.private.json').write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding='utf-8')
    return audit


HTML = r'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'none'">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>HomeTrace · 水杯寻物回看</title>
<style>
*{box-sizing:border-box}body{margin:0;background:#f5f5ee;color:#173c36;font-family:'Microsoft YaHei',sans-serif}
header{height:90px;padding:22px 46px;display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid #d9e2d8}
.brand{font-size:28px;font-weight:700;letter-spacing:-1px}.brand span{font-size:15px;font-weight:400;margin-left:22px;letter-spacing:1px;color:#677d74}.stamp{font-size:15px;color:#61796e}
main{padding:26px 46px 15px}nav{display:flex;gap:8px;margin-bottom:24px}button{border:1px solid #d1ddd1;border-radius:30px;background:transparent;padding:10px 20px;color:#647a70;font:inherit;font-size:15px;cursor:pointer}button.active{color:white;background:#1f574c;border-color:#1f574c}
.layout{display:grid;grid-template-columns:minmax(0,1fr) 350px;gap:28px}.scene{background:#e2e7dc;border-radius:16px;padding:16px;box-shadow:0 4px 18px #29423708}.photo{position:relative;aspect-ratio:1706/1279;overflow:hidden;border-radius:9px;background:#e1e7df}.photo>img{width:100%;height:100%;object-fit:contain}.mask{position:absolute;background:#33453e;border:1px solid #718078;border-radius:5px;display:flex;align-items:center;justify-content:center;color:#e5ece7;font-size:14px;letter-spacing:2px}.mask span{max-width:80%}
.scene-label{display:flex;justify-content:space-between;padding:13px 3px 0;font-size:15px;color:#60766b}.caption{font-size:23px;line-height:1.6;margin:18px 2px 0;min-height:74px;color:#193f35}
aside{padding:3px 0}.overline{font-size:13px;letter-spacing:2px;color:#7b8e81}h1{font-size:33px;line-height:1.35;margin:13px 0 17px;font-weight:650}p{font-size:18px;line-height:1.8;margin:0 0 20px;color:#567165}.chip{display:inline-block;background:#e0ebd7;border-radius:5px;padding:7px 11px;font-size:14px;margin-bottom:24px}.steps{border-top:1px solid #d9e2d8;padding-top:20px}.step{font-size:16px;padding:10px 0;line-height:1.7}.step::before{content:'·';color:#a4ad6b;padding-right:12px;font-weight:bold}.reference{display:flex;gap:20px;align-items:center;margin-top:22px;padding:17px;background:#e9ede2;border-radius:12px}.reference .crop{width:65px;flex-shrink:0}.crop{position:relative;overflow:hidden;border-radius:6px;background:#d9e0d5}.crop img{position:absolute;max-width:none}.reference b{font-size:17px}.reference small{display:block;line-height:1.8;color:#678071;margin-top:5px}footer{display:flex;justify-content:space-between;font-size:13px;color:#718477;padding:12px 46px;border-top:1px solid #dde4d7}details{font-size:12px;color:#718477}details pre{white-space:pre-wrap;max-height:150px;overflow:auto}.hero-ref{height:100%;display:flex;justify-content:center;background:#dce3d9}.hero-ref .crop{height:96%;margin:1%}
.photo{width:min(100%,calc((100vh - 420px)*1.33385));margin:auto}.hero-ref .crop{height:96%;width:auto}
@media(max-width:1100px){header{padding:18px}main{padding:20px}.layout{grid-template-columns:minmax(0,1fr) 300px;gap:20px}h1{font-size:27px}p{font-size:16px}nav button{padding:8px 13px}.caption{font-size:20px}footer{padding:12px 20px}}
</style></head><body><header><div class="brand">HomeTrace<span>把物品的位置记下来</span></div><div class="stamp" id="stamp"></div></header>
<main><nav id="nav" aria-label="回看章节"></nav><div class="layout"><section><div class="scene"><div class="photo" id="photo"></div><div class="scene-label"><span id="place"></span><span id="view"></span></div></div><div class="caption" id="caption"></div></section><aside><div class="overline" id="number"></div><h1 id="title"></h1><p id="body"></p><div class="chip" id="status"></div><div class="steps" id="steps"></div><div class="reference"><div class="crop" id="ref"></div><div><b id="object"></b><small>登记参考<br>主人已核对</small></div></div></aside></div></main>
<footer><span>真实照片 · 模拟导航 · 主人确认</span><details><summary>查看执行记录</summary><pre id="trace"></pre></details><span>只读回看，无新增模型请求</span></footer>
<script>const data=__DATA__;const el=id=>document.getElementById(id);el('stamp').textContent=data.date+' · 真实任务回看';el('object').textContent=data.object;
function crop(target){const r=data.reference,[x,y,x2,y2]=r.roi;target.style.aspectRatio=(x2-x)+' / '+(y2-y);const i=document.createElement('img');i.src='reference.jpg';i.alt='已批准的水杯参考区域';i.style.cssText=`width:${r.width/(x2-x)*100}%;left:${-x/(x2-x)*100}%;top:${-y/(y2-y)*100}%`;target.append(i)}crop(el('ref'));
data.chapters.forEach((c,n)=>{const b=document.createElement('button');b.textContent=c.label;b.onclick=()=>show(n);el('nav').append(b)});
function show(n){const c=data.chapters[n];[...el('nav').children].forEach((b,i)=>{b.className=i===n?'active':'';b.setAttribute('aria-current',i===n?'step':'false')});for(const k of ['title','body','caption','place','view','status'])el(k).textContent=c[k];el('number').textContent=String(n+1).padStart(2,'0')+' / '+String(data.chapters.length).padStart(2,'0');el('steps').replaceChildren();for(const t of c.points){let d=document.createElement('div');d.className='step';d.textContent=t;el('steps').append(d)}el('photo').replaceChildren();if(c.scene==='reference'){const h=document.createElement('div');h.className='hero-ref';const d=document.createElement('div');d.className='crop';crop(d);h.append(d);el('photo').append(h)}else{const i=document.createElement('img');i.src=c.image;i.alt=c.place+' · '+c.view;el('photo').append(i);for(const m of c.masks||[]){const d=document.createElement('div');d.className='mask';d.style.cssText=`left:${m[0]}%;top:${m[1]}%;width:${m[2]}%;height:${m[3]}%`;d.textContent='隐私遮挡';el('photo').append(d)}}el('trace').textContent=JSON.stringify({state:c.state,version:c.actual_version,text_calls:c.model_calls,vision_calls:c.vision_calls,tools:c.trace},null,2);location.hash='s'+n;}show(Math.min(Math.max(Number(location.hash.slice(2))||0,0),data.chapters.length-1));
</script></body></html>'''


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('summary', 'plan', 'story', 'output'):
        p.add_argument('--' + name, required=True, type=Path)
    p.add_argument('--repo', type=Path, default=Path(__file__).resolve().parents[1])
    a = p.parse_args()
    build(a.summary, a.plan, a.story, a.output, a.repo)
    print('Created private read-only review; no inference or database changes.')
