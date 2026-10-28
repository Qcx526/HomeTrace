'use strict';
// Server-owned state and evidence only. No client-side detector or pretend trace.
const $ = id => document.getElementById(id);
let config = null, run = null, referenceAsset = null, busy = false, timer = null;
const storageKey = 'hometrace.photo-flow.run.v1';
const sourceText = s => s === 'synthetic' ? 'AI 合成图' : s === 'real_upload' ? '用户声明实拍图' : '无图片';
const labels = {CONFIRM_MEMORY:'等待确认位置', RUNNING:'正在搜索', AWAITING_REVIEW:'等待核对候选',
  USER_CONFIRMED:'主人已确认', UNKNOWN:'未确认 UNKNOWN', COMPLETED:'已完成', CLARIFY:'需要选择物品',
  UNKNOWN_OBJECT:'物品尚未登记', NEEDS_REFERENCE:'需要登记参考', ERROR:'执行遇到问题', CANCELLED:'已取消'};
function node(tag, text, cls) { const n=document.createElement(tag); if(text!==undefined)n.textContent=text; if(cls)n.className=cls; return n; }
function error(e) { $('error').textContent=e?.message || String(e); $('error').hidden=false; }
function rememberRun(id) { try {localStorage.setItem(storageKey,id);} catch { $('storage-notice').textContent='浏览器存储不可用，刷新后请保留报告中的执行编号。服务端记录仍保留。'; $('storage-notice').hidden=false; } }
async function api(path, value) {
  const response=await fetch(path,value===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(value)});
  const data=await response.json();
  if(!response.ok) {const e=new Error(data.error || '本地请求失败'); e.status=response.status; throw e;}
  return data;
}
function controls() {
  document.querySelectorAll('input,select,textarea,button').forEach(el=>{el.disabled=busy || !config;});
  $('save-reference').disabled=busy || !config || !referenceAsset || !$('reference-object').value || !$('roi-reviewed').checked;
  $('start').disabled=busy || !config || run?.state==='RUNNING';
}
async function perform(fn) {
  if(busy)return; busy=true; $('error').hidden=true; controls();
  try {await fn();} catch(e) {
    error(e);
    if(e.status===409 && run) {try{run=await api('/api/home-flow/runs/'+run.run_id); renderRun();}catch{}}
  } finally {busy=false; controls();}
}
function options(select, rows, blank) {
  const previous=select.value; select.replaceChildren();
  if(blank)select.append(new Option(blank,''));
  rows.forEach(x=>select.append(new Option(x.name,x.id)));
  if([...select.options].some(x=>x.value===previous)) select.value=previous;
}
function imageFrame(asset,bbox,caption) {
  const box=node('div',undefined,'image-frame');
  if(!asset?.url || !/^\/api\/home-flow\/assets\/[0-9a-f]{32}$/.test(asset.url))return box;
  if(!asset.width || !asset.height) {const img=node('img');img.src=asset.url;img.alt=caption;box.append(img);return box;}
  const ns='http://www.w3.org/2000/svg';
  const svg=document.createElementNS(ns,'svg');svg.setAttribute('viewBox',`0 0 ${asset.width} ${asset.height}`);svg.setAttribute('role','img');svg.setAttribute('aria-label',caption);
  const img=document.createElementNS(ns,'image');img.setAttribute('href',asset.url);img.setAttribute('width',asset.width);img.setAttribute('height',asset.height);svg.append(img);
  if(Array.isArray(bbox)&&bbox.length===4&&bbox.every(Number.isFinite)) {
    const rect=document.createElementNS(ns,'rect');rect.setAttribute('x',bbox[0]);rect.setAttribute('y',bbox[1]);rect.setAttribute('width',bbox[2]-bbox[0]);rect.setAttribute('height',bbox[3]-bbox[1]);rect.setAttribute('fill','none');rect.setAttribute('stroke','#e44b30');rect.setAttribute('stroke-width',Math.max(2,asset.width/250));rect.dataset.roi='true';svg.append(rect);
  }
  box.append(svg);return box;
}
function details(title,value) {const d=node('details',undefined,'diagnostics');d.append(node('summary',title),node('pre',JSON.stringify(value,null,2)));return d;}
async function reloadConfig() {config=await api('/api/home-flow/config');renderConfig();}
function renderConfig() {
  $('service-notice').textContent=config.notice+' · '+config.mode;
  $('catalog-count').textContent=config.catalog.length+' 件';
  $('catalog').replaceChildren();
  for(const obj of config.catalog) {
    const li=node('li',undefined,'object-card');li.append(node('strong',obj.name),node('code',obj.object_id),node('p',obj.reference?'外观参考已固定 · '+sourceText(obj.reference.source_kind):'尚未登记外观'));
    const select=node('button','选择这件物品');select.type='button';select.onclick=()=>{$('reference-object').value=obj.object_id;referenceAsset=null;renderReference();controls();};li.append(select);$('catalog').append(li);
  }
  if(!config.catalog.length)$('catalog').append(node('li','先登记一件物品的名称。','empty'));
  options($('reference-object'),config.catalog.map(x=>({id:x.object_id,name:x.name})),'请选择已登记物品');
  const places=config.locations.map(x=>({id:x.location_id,name:x.location_name}));
  options($('scene-location'),places,'请选择地点');options($('current-location'),places,'暂不指定');
  $('scenes').replaceChildren();
  for(const loc of config.locations) {
    const scene=config.scenes.find(x=>x.location_id===loc.location_id), li=node('li',undefined,'scene-card');
    if(scene){const img=node('img');img.src=scene.url;img.alt=loc.location_name+'当前配置';li.append(img);}
    const text=node('div');text.append(node('strong',loc.location_name),node('p',scene?sourceText(scene.source_kind)+' · '+scene.width+'×'+scene.height:'未配置，搜索时会报告无法观察'));li.append(text);$('scenes').append(li);
  }
  renderReference();controls();
}
function renderReference() {
  const ref=config?.catalog.find(x=>x.object_id===$('reference-object').value)?.reference;
  $('registered-reference').replaceChildren();$('registered-reference').hidden=!ref;$('reference-edit-fields').hidden=!!ref;
  if(ref) {$('registered-reference').append(imageFrame(ref,ref.roi,'已登记参考与固定 ROI'),node('p',sourceText(ref.source_kind)+' · 已人工确认区域，未确认物理身份','note'),details('实际登记质量',ref.quality));}
  $('roi-editor').hidden=!referenceAsset;
}
function roi() {return ['x1','y1','x2','y2'].map(k=>Number($('roi-'+k).value));}
function changeRoi(values) {
  ['x1','y1','x2','y2'].forEach((k,i)=>{$('roi-'+k).value=values[i];});
  const rect=$('roi-image').querySelector('rect');
  if(rect) {rect.setAttribute('x',values[0]);rect.setAttribute('y',values[1]);rect.setAttribute('width',Math.max(0,values[2]-values[0]));rect.setAttribute('height',Math.max(0,values[3]-values[1]));}
  $('roi-size').textContent=`原图 ${referenceAsset.width} × ${referenceAsset.height}；区域 ${values[2]-values[0]} × ${values[3]-values[1]} 像素`;
  $('roi-reviewed').checked=false;controls();
}
function editRoi() {
  $('roi-image').replaceChildren(imageFrame(referenceAsset,[0,0,referenceAsset.width,referenceAsset.height],'拖动框选物品'));
  changeRoi([0,0,referenceAsset.width,referenceAsset.height]);$('roi-editor').hidden=false;
  const svg=$('roi-image').querySelector('svg');let start=null;
  function point(e) {const b=svg.getBoundingClientRect();return [Math.max(0,Math.min(referenceAsset.width,Math.round((e.clientX-b.left)/b.width*referenceAsset.width))),Math.max(0,Math.min(referenceAsset.height,Math.round((e.clientY-b.top)/b.height*referenceAsset.height)))];}
  svg.addEventListener('pointerdown',e=>{if(busy)return;start=point(e);svg.setPointerCapture(e.pointerId);e.preventDefault();});
  svg.addEventListener('pointermove',e=>{if(!start)return;const p=point(e);changeRoi([Math.min(start[0],p[0]),Math.min(start[1],p[1]),Math.max(start[0],p[0]),Math.max(start[1],p[1])]);});
  svg.addEventListener('pointerup',()=>{start=null;});svg.addEventListener('pointercancel',()=>{start=null;});
}
async function upload(file,source) {
  if(!file || !['image/jpeg','image/png'].includes(file.type) || file.size>8*1024*1024)throw new Error('请选择不超过 8 MB 的 JPEG/PNG 图片');
  const data=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(String(reader.result).split(',')[1]);reader.onerror=()=>reject(new Error('图片读取失败'));reader.readAsDataURL(file);});
  return api('/api/home-flow/assets',{data_base64:data,source_kind:source});
}
function actionButton(container,text,action,objectId,cls='secondary') {
  const b=node('button',text,cls);b.type='button';b.onclick=()=>perform(async()=>{
    const args={run_id:run.run_id,version:run.version,action};if(objectId)args.object_id=objectId;
    run=await api('/api/home-flow/act',args);renderRun();await reloadConfig();
  });container.append(b);
}
function renderRun() {
  if(!run)return;
  clearTimeout(timer); rememberRun(run.run_id);
  $('session-state').textContent=labels[run.state] || run.state;
  $('session-meta').textContent=`${run.selected_object?.name || '待解析物品'} · 版本 ${run.version} · ${run.mode}`;
  $('reply').textContent=run.reply;$('mode-badge').textContent=run.mode;
  const actions=$('session-actions');actions.replaceChildren();
  if(run.state==='CLARIFY')run.matches.forEach(obj=>actionButton(actions,obj.name+' · '+obj.object_id,'select',obj.object_id));
  if(run.state==='CONFIRM_MEMORY')actionButton(actions,'确认记住这个位置','confirm_memory',null,'primary');
  if(['UNKNOWN_OBJECT','NEEDS_REFERENCE','ERROR','RUNNING'].includes(run.state))actionButton(actions,run.state==='RUNNING'?'服务重启后继续执行':'重新查询 / 重试','retry');
  if(!['COMPLETED','USER_CONFIRMED','UNKNOWN','CANCELLED'].includes(run.state))actionButton(actions,'取消后续操作','cancel');
  const report=node('a','下载本次真实执行 JSON');report.href='/api/home-flow/runs/'+run.run_id+'/report';report.className='small-link';report.style.marginLeft='12px';actions.append(report);
  $('candidate-panel').hidden=run.state!=='AWAITING_REVIEW';$('candidate-content').replaceChildren();$('candidate-actions').replaceChildren();
  if(run.state==='AWAITING_REVIEW'&&run.candidate) {
    const grid=node('div',undefined,'compare-grid');
    const ref=config?.catalog.find(x=>x.object_id===run.selected_object.object_id)?.reference;
    for(const [asset,box,title] of [[ref,ref?.roi,'登记参考与人工固定区域'],[run.candidate,run.candidate.bbox,run.candidate.location_name+' · 实际匹配框']]) {
      const f=node('figure');f.append(imageFrame(asset,box,title),node('figcaption',title+' · '+sourceText(asset?.source_kind)));grid.append(f);
    }
    $('candidate-content').append(grid);
    actionButton($('candidate-actions'),'是我要找的物品，记录此位置','accept_candidate',null,'primary');
    actionButton($('candidate-actions'),'不是它，继续寻找','reject_candidate');
  }
  $('memory-panel').hidden=!run.selected_object;
  $('plan').replaceChildren();run.planned_locations.forEach((loc,i)=>$('plan').append(node('li',`${i+1}. ${loc.location_name} · ${loc.reason==='recent_owner_memory'?'历史优先':'剩余地点'}`,run.visited.includes(loc.location_id)?'visited':'')));
  $('history-count').textContent=`${run.history.length} 条`;$('history').replaceChildren();
  run.history.forEach(x=>{const li=node('li');li.append(node('strong',x.location_name),node('p',new Date(x.reported_at).toLocaleString()+' · 主人陈述 / 非视觉确认'),node('p','来源：'+x.source));$('history').append(li);});
  if(!run.history.length)$('history').append(node('li','尚无位置记录','empty'));
  $('observations-panel').hidden=!run.observations.length;$('observation-count').textContent=run.observations.length+' 次';$('observations').replaceChildren();
  for(const obs of run.observations) {
    const card=node('article',undefined,'observation-card');card.append(node('h3',obs.location_name),node('span',obs.status,'badge amber'),imageFrame(obs,obs.bbox,obs.location_name+'观察证据'),node('p',sourceText(obs.source_kind)+' · '+obs.reason,'note'),details('实际匹配诊断与坐标',{bbox:obs.bbox,raw_match_status:obs.raw_match_status,duration_ms:obs.duration_ms,...obs.diagnostics}));$('observations').append(card);
  }
  $('trace-panel').hidden=!run.trace.length;$('trace').replaceChildren();
  run.trace.forEach(t=>{const li=node('li'),head=node('div',undefined,'trace-header');head.append(node('strong',`${t.seq}. ${t.tool}`),node('time',new Date(t.at).toLocaleTimeString()));li.append(head,details('输入与真实返回',{input:t.input,result:t.result}));$('trace').append(li);});
  if(run.state==='RUNNING')timer=setTimeout(poll,700);
  controls();
}
async function poll() {
  if(busy){timer=setTimeout(poll,700);return;}
  try {run=await api('/api/home-flow/runs/'+run.run_id);renderRun();}
  catch(e) {error(e);timer=setTimeout(poll,3000);}
}
$('enroll-form').addEventListener('submit',e=>{e.preventDefault();perform(async()=>{
  const id=$('object-id').value.trim();await api('/api/household/enroll',{object_id:id,name:$('object-name').value.trim(),aliases:$('object-aliases').value.split(/[,，]/).map(x=>x.trim()).filter(Boolean)});
  await reloadConfig();$('reference-object').value=id;referenceAsset=null;renderReference();$('enroll-status').textContent='名称已保存；接下来上传参考图。';
});});
$('reference-object').addEventListener('change',()=>{referenceAsset=null;$('reference-file').value='';renderReference();controls();});
$('reference-file').addEventListener('change',()=>perform(async()=>{referenceAsset=await upload($('reference-file').files[0],$('reference-source').value);editRoi();$('reference-upload-status').textContent='图片已保存。请框选目标并确认区域。';}));
$('reference-source').addEventListener('change',()=>{referenceAsset=null;$('reference-file').value='';$('roi-editor').hidden=true;$('reference-upload-status').textContent='来源已改变，请重新选择照片。';controls();});
['x1','y1','x2','y2'].forEach(k=>$('roi-'+k).addEventListener('input',()=>{if(referenceAsset)changeRoi(roi());}));
$('roi-reviewed').addEventListener('change',controls);
$('reference-form').addEventListener('submit',e=>{e.preventDefault();perform(async()=>{
  if(!referenceAsset || !$('roi-reviewed').checked)throw new Error('请上传并确认目标区域');
  await api('/api/home-flow/reference',{object_id:$('reference-object').value,asset_id:referenceAsset.asset_id,roi:roi(),roi_reviewed:true});referenceAsset=null;await reloadConfig();$('reference-status').textContent='参考已固定，未训练新模型。';
});});
$('scene-form').addEventListener('submit',e=>{e.preventDefault();perform(async()=>{
  const asset=await upload($('scene-file').files[0],$('scene-source').value);await api('/api/home-flow/scene',{location_id:$('scene-location').value,asset_id:asset.asset_id});await reloadConfig();$('scene-status').textContent='场景已保存，下一次搜索使用新配置；进行中的搜索保持原始输入。';
});});
document.querySelectorAll('[data-template]').forEach(b=>b.addEventListener('click',()=>{
  const name=config?.catalog.find(x=>x.object_id===$('reference-object').value)?.name || '钥匙';
  $('message').value={remember:`记住${name}放在这里了`,find:`帮我找${name}`,history:`查看${name}历史`}[b.dataset.template];$('message').focus();
}));
$('request-form').addEventListener('submit',e=>{e.preventDefault();perform(async()=>{
  run=await api('/api/home-flow/start',{message:$('message').value,current_location_id:$('current-location').value || null});renderRun();
});});
perform(async()=>{
  await reloadConfig();let id=null;try{id=localStorage.getItem(storageKey);}catch{rememberRun('');}
  if(id&&/^[0-9a-f]{32}$/.test(id)) {try{run=await api('/api/home-flow/runs/'+id);renderRun();}catch(e){error(e);}}
});
