'use strict';

// Execute the real client against explicit DOM/HTTP doubles. These tests make
// no model requests and do not constitute browser or photo recognition evidence.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../src/hometrace/web/home-flow.js'), 'utf8');
const html = fs.readFileSync(path.join(__dirname, '../src/hometrace/web/home-flow.html'), 'utf8');
const ids = new Set([...html.matchAll(/\bid="([^"]+)"/g)].map(x => x[1]));
const ID = 'a'.repeat(32), NEXT_ID = 'b'.repeat(32), REQUEST = 'c'.repeat(32), ASSET = 'd'.repeat(32);
const settle = () => new Promise(resolve => setImmediate(resolve));
const response = (data, status = 200) => ({ok: status < 400, status, json: async () => data});
function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => {resolve = yes; reject = no;});
  return {promise, resolve, reject};
}
class Element {
  constructor(tagName = 'div') {Object.assign(this, {tagName, children: [], options: [], listeners: {}, value: '', style: {}, dataset: {}, files: [], checked: false});}
  append(...children) {this.children.push(...children);this.options=this.children;}
  replaceChildren(...children) {this.children=children;this.options=children;}
  addEventListener(type, fn) {this.listeners[type]=fn;}
  setAttribute(name, value) {this[name]=value;}
  querySelector(tag) {for (const child of this.children) {if(child.tagName===tag)return child;const found=child.querySelector?.(tag);if(found)return found;}return null;}
}
const text = el => [el.textContent || '', ...el.children.map(text)].join('\n');
const asset = {asset_id: ASSET, url: '/api/home-flow/assets/'+ASSET, width: 64, height: 128, source_kind: 'real_upload'};
function runFixture(extra = {}) {
  return {run_id: ID, version: 1, state: 'RUNNING', mode: 'llm_langgraph', visual_advisor_enabled: true,
    selected_object: null, matches: [], history: [], planned_locations: [], visited: [], observations: [], trace: [],
    reply: '尚未确认目标', candidate: null, visual_advice: [], vision_calls: 0, vision_tokens_used: 0, ...extra};
}
function consentFixture(extra = {}) {
  return runFixture({state: 'AWAITING_IMAGE_CONSENT', vision_request: {request_id: REQUEST, endpoint: 'https://example.invalid/v1',
    model: 'fixture-model', observation_index: 0, reference: {...asset, roi: [1,2,60,120]}, scene: asset}, ...extra});
}
async function client(handler = () => {throw new Error('Unexpected HTTP call');}) {
  const elements = new Map(), calls = [], timers = new Map();let nextTimer = 0;
  const element = id => {assert.ok(ids.has(id), 'Missing production HTML #'+id);if(!elements.has(id))elements.set(id,new Element());return elements.get(id);};
  const config = {mode: 'llm_langgraph', visual_advisor_enabled: true, vision_model: 'fixture-model', notice: 'Software fixture', catalog: [], locations: [], scenes: []};
  const context=vm.createContext({console, Number,
    fetch: async (url, options) => {const body=options?.body?JSON.parse(options.body):undefined;calls.push({url,body});return url==='/api/home-flow/config'?response(config):handler(url,body);},
    Option: class {constructor(label,value){this.text=label;this.value=value;}},
    FileReader: class {readAsDataURL(){this.result='data:image/jpeg;base64,dGVzdA==';this.onload();}},
    document: {getElementById: element, querySelectorAll: () => [], createElement: tag => new Element(tag), createElementNS: (_,tag) => new Element(tag)},
    localStorage: {getItem: () => null, setItem(){}},
    setTimeout: (fn,delay) => {timers.set(++nextTimer,{fn,delay});return nextTimer;},clearTimeout: id => timers.delete(id),
  });
  vm.runInContext(source,context);await settle();
  return {element,calls,evaluate: code => vm.runInContext(code,context),
    show: run => vm.runInContext('run='+JSON.stringify(run)+';renderRun();',context),
    submit: id => element(id).listeners.submit({preventDefault(){}})};
}

test('consent is unchecked, bound to one request, and not inherited by a later request', async () => {
  const page=await client((url,body) => {assert.equal(url,'/api/home-flow/act');assert.deepEqual(body,{run_id:ID,version:1,action:'approve_vision',request_id:REQUEST});return response(runFixture({version:2}));});
  page.show(consentFixture());
  assert.equal(page.element('vision-consent').checked,false);
  assert.equal(page.element('approve-vision').disabled,true);
  await page.element('approve-vision').listeners.click();
  assert.equal(page.calls.filter(x=>x.url.endsWith('/act')).length,0);
  page.element('vision-consent').checked=true;page.element('vision-consent').listeners.change();
  assert.equal(page.element('approve-vision').disabled,false);
  await page.element('approve-vision').listeners.click();
  assert.equal(page.evaluate('run.state'),'RUNNING');
  page.show(consentFixture({version:3,vision_request:{...consentFixture().vision_request,request_id:'e'.repeat(32)}}));
  assert.equal(page.element('vision-consent').checked,false);
  assert.equal(page.element('approve-vision').disabled,true);
});

test('declining sends only the bound denial and never requires approval checkbox', async () => {
  const page=await client((url,body) => {assert.deepEqual(body,{run_id:ID,version:1,action:'deny_vision',request_id:REQUEST});return response(runFixture({version:2}));});
  page.show(consentFixture());
  await page.element('deny-vision').listeners.click();
  assert.equal(page.calls.filter(x=>x.url.endsWith('/act')).length,1);
  assert.equal(page.element('vision-consent-panel').hidden,true);
});

test('visual token reservations and all actual advice enum values have honest labels', async () => {
  const page=await client();
  for(const [appearance, action, appearanceText, actionText] of [
    ['similar','ask_owner_review','外观相似建议','建议主人核对'],
    ['different','continue_search','外观不同建议','建议继续寻找'],
    ['uncertain','request_side_view','无法判定','建议换角度补拍'],
    ['not_visible','request_closeup','未看到目标外观','建议靠近补拍'],
  ]) {
    page.show(runFixture({vision_calls:1,vision_tokens_used:8192,visual_advice:[{observation_index:0,execution_status:'completed',
      advice:{model_advice:{appearance,next_action:action,reason:'<img src=x onerror=bad()>',visible_features:['叶片'],quality_flags:['occluded']}},elapsed_ms:123,usage:{total_tokens:100}}]}));
    assert.equal(page.element('vision-tokens').textContent,'8192');
    const card=page.element('visual-advice').children[0];
    assert.match(text(card),new RegExp(appearanceText));assert.match(text(card),new RegExp(actionText));
    assert.match(text(card),/实例仍未确认/);assert.match(text(card),/目标被遮挡/);
    assert.equal(card.children[2].textContent,'<img src=x onerror=bad()>');
    assert.equal(card.children[2].children.length,0);
  }
});

test('a failed advisor call has an explicit unavailable record, not empty success advice', async () => {
  const page=await client();page.show(runFixture({visual_advice:[{observation_index:1,execution_status:'failed',error_code:'CALL_FAILED',reserved_budget_retained:true}]}));
  assert.match(text(page.element('visual-advice')),/视觉调用未完成/);
  assert.match(text(page.element('visual-advice')),/预算预留仍保留/);
  assert.match(text(page.element('visual-advice')),/CALL_FAILED/);
  assert.doesNotMatch(text(page.element('visual-advice')),/外观相似建议/);
});

test('new photo uses local upload then the run-scoped endpoint without granting image consent', async () => {
  const page=await client((url,body) => {
    if(url.endsWith('/assets')){assert.equal(body.source_kind,'real_upload');return response(asset);}
    assert.equal(url,'/api/home-flow/new-photo');assert.deepEqual(body,{run_id:ID,version:5,asset_id:ASSET});
    return response(runFixture({version:6}));
  });
  page.show(runFixture({version:5,state:'AWAITING_NEW_PHOTO',photo_request:{location_id:'study',location_name:'书房',reason:'请换角度'}}));
  assert.match(page.element('new-photo-reason').textContent,/书房.*请换角度/);
  page.element('new-photo-file').files=[{type:'image/jpeg',size:128}];page.element('new-photo-source').value='real_upload';
  page.submit('new-photo-form');await settle();
  assert.equal(page.evaluate('run.version'),6);
  assert.deepEqual(page.calls.map(x=>x.url),['/api/home-flow/config','/api/home-flow/assets','/api/home-flow/new-photo']);
  assert.match(page.element('new-photo-status').textContent,/尚未因此授权图片外发/);
});

test('cancelling while a new image upload is pending cannot submit that image afterward', async () => {
  const upload=deferred();
  const page=await client((url,body) => {
    if(url.endsWith('/assets'))return upload.promise;
    assert.equal(url,'/api/home-flow/act');assert.equal(body.action,'cancel');return response(runFixture({version:2,state:'CANCELLED'}));
  });
  page.show(runFixture({state:'AWAITING_NEW_PHOTO',photo_request:{location_id:'study',reason:'补拍'}}));
  page.element('new-photo-file').files=[{type:'image/jpeg',size:128}];page.element('new-photo-source').value='real_upload';
  page.submit('new-photo-form');await settle();
  await page.evaluate('cancelRun()');upload.resolve(response(asset));await settle();
  assert.equal(page.evaluate('run.state'),'CANCELLED');assert.equal(page.evaluate('busy'),false);
  assert.equal(page.calls.filter(x=>x.url.endsWith('/new-photo')).length,0);
});

test('an approval response arriving after cancellation cannot restore the old run', async () => {
  const approval=deferred();
  const page=await client((url,body) => body.action==='approve_vision'?approval.promise:response(runFixture({version:3,state:'CANCELLED'})));
  page.show(consentFixture());page.element('vision-consent').checked=true;
  const pending=page.element('approve-vision').listeners.click();await settle();await page.evaluate('cancelRun()');
  approval.resolve(response(runFixture({version:2})));await pending;
  assert.equal(page.evaluate('run.state'),'CANCELLED');assert.equal(page.evaluate('run.version'),3);
  assert.equal(page.element('vision-consent').checked,false);
});

test('an outdated conflict-refresh response cannot undo cancellation', async () => {
  const refresh=deferred();
  const page=await client((url,body) => {
    if(url.startsWith('/api/home-flow/runs/'))return refresh.promise;
    return body.action==='approve_vision'?response({error:'Version changed'},409):response(runFixture({version:4,state:'CANCELLED'}));
  });
  page.show(consentFixture());page.element('vision-consent').checked=true;
  const pending=page.element('approve-vision').listeners.click();await settle();await page.evaluate('cancelRun()');
  refresh.resolve(response(runFixture({version:3})));await pending;
  assert.equal(page.evaluate('run.state'),'CANCELLED');assert.equal(page.evaluate('run.version'),4);
  assert.equal(page.element('error').hidden,true);
});

test('cancel retries its intent after a concurrently committed approval causes a version conflict', async () => {
  const approval=deferred();let cancels=0;
  const page=await client((url,body) => {
    if(url.startsWith('/api/home-flow/runs/'))return response(runFixture({version:2}));
    if(body.action==='approve_vision')return approval.promise;
    assert.equal(body.action,'cancel');
    if(++cancels===1){assert.equal(body.version,1);return response({error:'Version changed'},409);}
    assert.equal(body.version,2);return response(runFixture({version:3,state:'CANCELLED'}));
  });
  page.show(consentFixture());page.element('vision-consent').checked=true;
  const pending=page.element('approve-vision').listeners.click();await settle();await page.evaluate('cancelRun()');
  approval.resolve(response(runFixture({version:2})));await pending;
  assert.equal(cancels,2);assert.equal(page.evaluate('run.state'),'CANCELLED');assert.equal(page.evaluate('run.version'),3);
});

test('cancel retry is bounded and does not claim success when the server keeps advancing', async () => {
  let cancels=0,reads=0;
  const page=await client((url,body) => {
    if(url.startsWith('/api/home-flow/runs/'))return response(runFixture({version:2+(reads++)}));
    assert.equal(body.action,'cancel');cancels++;return response({error:'Version changed'},409);
  });
  page.show(runFixture());await page.evaluate('cancelRun()');
  assert.equal(cancels,2);assert.equal(reads,2);assert.equal(page.evaluate('run.state'),'RUNNING');
  assert.match(page.element('error').textContent,/尚未确认取消成功/);
});

test('cancelled scene uploads cannot mutate global scene configuration', async () => {
  const upload=deferred();
  const page=await client((url,body) => url.endsWith('/assets')?upload.promise:response(runFixture({version:2,state:'CANCELLED'})));
  page.show(runFixture());page.element('scene-file').files=[{type:'image/png',size:32}];page.element('scene-source').value='real_upload';page.element('scene-location').value='study';
  page.submit('scene-form');await settle();await page.evaluate('cancelRun()');upload.resolve(response(asset));await settle();
  assert.equal(page.calls.filter(x=>x.url.endsWith('/scene')).length,0);
});

test('a visual-only candidate displays the complete image without inventing a detection rectangle', async () => {
  const page=await client();
  page.show(runFixture({state:'AWAITING_REVIEW',selected_object:{object_id:'cup',name:'水杯'},candidate:{...asset,location_name:'书房',kind:'visual_advisor',bbox:[1,1,60,120]}}));
  assert.match(page.element('candidate-notice').textContent,/无检测框/);
  assert.equal(page.element('candidate-content').querySelector('rect'),null);
  assert.ok(page.element('candidate-content').querySelector('image'));
  assert.match(text(page.element('candidate-actions')),/记录此位置/);
});

test('a late cancelled response is explicitly discarded rather than rendered as model advice', async () => {
  const page=await client();
  page.show(runFixture({state:'CANCELLED',visual_advice:[{observation_index:0,execution_status:'discarded',known_total_tokens:12000}]}));
  assert.match(text(page.element('visual-advice')),/返回已丢弃/);
  assert.match(text(page.element('visual-advice')),/未用于判断或写入记忆/);
});
