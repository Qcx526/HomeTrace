/* Actual UI recording: no intercepted requests, canned tools or DOM result edits.
 * Uses only the fixed synthetic pack; real text LLM, local ORB, simulated owner.
 * NODE_PATH may point to an isolated Playwright installation. */
const {chromium} = require('playwright');
const fs = require('node:fs/promises');
const fsSync = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const {spawn, spawnSync} = require('node:child_process');
const assert = require('node:assert/strict');

(async () => {
  const root = path.resolve(__dirname, '..');
  const output = path.resolve(process.argv[2] || 'artifacts/issue-44/browser-01');
  const python = path.resolve(process.argv[3] || 'artifacts/issue-11/agent-env/Scripts/python.exe');
  assert.ok(output.startsWith(root + path.sep));
  assert.ok(!fsSync.existsSync(output), 'Output must be new');
  assert.equal(spawnSync('git', ['check-ignore','--quiet',path.relative(root,path.join(output,'summary.json'))], {cwd:root,windowsHide:true}).status, 0);
  const images = path.join(root,'local_data/ai_html_test_20261027');
  const expected = {'01_reference_keys.png':'3cc149287c013dd6b9ff8f4ff9f54a4d32d9dfeb5b4200612ec2ea0d40e94fe8',
    '03_keys_study_desk.png':'ac06b717b7171daa0b4b26c6adcbb1556938717929b7a68d53ba785494239502',
    '04_rival_red_keys.png':'5646c45ed7f793136e85ce9183a96d6ef9055af428d47a35ce4215fa447d3b50',
    '05_empty_entry_tray.png':'0b66fbf63b2255ecd3d2535974e0a730403e88c35c9038a67663006a879ae307'};
  assert.equal(JSON.parse(await fs.readFile(path.join(images,'manifest.json'),'utf8')).not_real_household_data,true);
  for(const [name,sha] of Object.entries(expected)) assert.equal(crypto.createHash('sha256').update(await fs.readFile(path.join(images,name))).digest('hex'),sha);
  await fs.mkdir(output);
  const workspace = path.join(output,'workspace');
  const prep = spawnSync(python,['-X','utf8','-c',
    'import sys; from pathlib import Path; sys.path.insert(0,"tools"); from accept_photo_workflow import bounded_config,prepare_custom_locations; p=Path(sys.argv[1]); bounded_config(p); prepare_custom_locations(p/"workspace")',output],
    {cwd:root,encoding:'utf8',windowsHide:true});
  assert.equal(prep.status,0,'Runtime configuration preparation failed');
  const log = fsSync.openSync(path.join(output,'server.log'),'wx');
  const server = spawn(python,['-X','utf8','-m','hometrace','demo','--photo-agent','--port','0','--config',path.join(output,'bounded-config.private.yaml'),
    '--household-dir',workspace,'--output-dir',path.join(output,'classic')],{cwd:root,stdio:['ignore',log,log],windowsHide:true});
  const summary={source:'hash_locked_AI_synthetic_software_fixture',navigation:'simulated',owner_actions:'scripted_browser_clicks',
    real_text_llm:true,local_ORB:true,image_calls:0,private_photographs:false,automatic_FOUND:false,passed:false,
    checkpoints:[],runs:{},errors:[],network:[],input_sha256:expected,process_id:server.pid,
    limits:{max_new_runs:3,max_provider_retries:0,max_model_calls_per_run:10,overall_seconds:600},
    head:spawnSync('git',['rev-parse','HEAD'],{cwd:root,encoding:'utf8',windowsHide:true}).stdout.trim(),
    script_sha256:crypto.createHash('sha256').update(await fs.readFile(__filename)).digest('hex')};
  let browser,context,page,recordingStart=0;
  const deadline=Date.now()+600000;
  const pause=ms=>new Promise(resolve=>setTimeout(resolve,ms));
  const save=()=>fs.writeFile(path.join(output,'browser-checks.json'),JSON.stringify(summary,null,2));
  const check=(name,ok)=>{summary.checkpoints.push({name,passed:!!ok,seconds:recordingStart?(Date.now()-recordingStart)/1000:0});assert.ok(ok,name);};
  const chapter=async(name,selector,seconds=3)=>{
    if(selector) await page.locator(selector).scrollIntoViewIfNeeded();
    summary.chapters.push({name,seconds:(Date.now()-recordingStart)/1000});
    await page.screenshot({path:path.join(output,`${String(summary.chapters.length).padStart(2,'0')}-${name}.png`)});
    await pause(seconds*1000);
  };
  try {
    let url;
    for(let i=0;i<300;i++){
      const match=(await fs.readFile(path.join(output,'server.log'),'utf8')).match(/HomeTrace demo: (http:\/\/127\.0\.0\.1:\d+)/);
      if(match){url=match[1];break;}
      if(server.exitCode!==null)throw new Error('Server exited before startup');
      await pause(100);
    }
    assert.ok(url,'Server did not publish localhost endpoint');
    summary.endpoint=url;
    browser=await chromium.launch({channel:'msedge',headless:true});
    context=await browser.newContext({viewport:{width:1440,height:1080},recordVideo:{dir:output,size:{width:1440,height:1080}}});
    page=await context.newPage(); recordingStart=Date.now(); summary.chapters=[];
    const pending=[]; let latest=null,starts=0;
    page.on('pageerror',e=>summary.errors.push(e.name));
    page.on('request',req=>{
      const target=new URL(req.url());
      if(target.protocol==='http:'||target.protocol==='https:') summary.network.push({method:req.method(),pathname:target.pathname,local:target.hostname==='127.0.0.1'});
      if(target.pathname==='/api/home-flow/start'&&++starts>3) summary.errors.push('NEW_RUN_LIMIT_EXCEEDED');
    });
    page.on('response',response=>{
      if(/\/api\/home-flow\/(start|act|runs\/[a-f0-9]{32})$/.test(new URL(response.url()).pathname)){
        const task=response.json().then(run=>{if(run.run_id){latest=run;summary.runs[run.run_id]=run;}}).catch(()=>summary.errors.push('RUN_RESPONSE_DECODE'));
        pending.push(task);
      }
    });
    async function waitState(state){
      for(let i=0;i<480;i++){
        if(Date.now()>deadline)throw new Error('Overall video deadline');
        if(latest?.state===state){await pause(900);return latest;}
        if(latest&&['ERROR','MODEL_UNAVAILABLE','BUDGET_EXCEEDED'].includes(latest.state))throw new Error('Agent '+latest.state);
        await pause(250);
      }
      throw new Error('Expected state not reached: '+state);
    }
    async function send(message,place=''){
      await page.locator('#current-location').selectOption(place);
      await page.locator('#message').fill(message);
      latest=null;await page.locator('#start').click();
    }
    async function scene(place,file){
      await page.locator('#scene-location').selectOption(place);
      await page.locator('#scene-file').setInputFiles(path.join(images,file));
      const response=page.waitForResponse(r=>new URL(r.url()).pathname==='/api/home-flow/scene'&&r.request().method()==='POST');
      await page.locator('#scene-form button[type=submit]').click();
      assert.equal((await response).status(),200);await pause(1000);
    }
    await page.goto(url);
    await page.locator('#object-id').waitFor({state:'attached'});
    await page.waitForFunction(()=>!document.querySelector('#object-id').disabled);
    check('empty catalog visible',(await page.locator('#catalog-count').innerText())==='0 件');
    await chapter('empty-workspace',null);
    await page.locator('#enroll-details summary').click();
    await page.locator('#object-id').fill('blue-keys');await page.locator('#object-name').fill('蓝色钥匙');
    await page.locator('#object-aliases').fill('蓝挂件钥匙');await page.locator('#enroll-form button').click();
    await page.waitForFunction(()=>document.querySelector('#reference-object option[value="blue-keys"]'));
    await page.locator('#reference-object').selectOption('blue-keys');
    await page.locator('#reference-file').setInputFiles(path.join(images,'01_reference_keys.png'));
    await page.locator('#roi-editor').waitFor({state:'visible'});
    for(const [id,value] of Object.entries({'roi-x1':110,'roi-y1':120,'roi-x2':1390,'roi-y2':950}))await page.locator('#'+id).fill(String(value));
    await page.locator('#roi-reviewed').check();await chapter('reference-ROI','#roi-editor');
    await page.locator('#save-reference').click();
    await page.waitForFunction(()=>document.querySelector('#reference-edit-fields').hidden);
    await scene('z-history-tray','03_keys_study_desk.png');
    await send('请记住，蓝色钥匙我放在这里了。','z-history-tray');
    await waitState('CONFIRM_MEMORY');await chapter('memory-confirmation','#session-title');
    await page.getByRole('button',{name:'确认记住这个位置',exact:true}).click();
    const remembered=await waitState('COMPLETED');check('owner memory saved after click',remembered.history.length===1&&!remembered.visual_confirmed);
    await chapter('memory-saved','#memory-panel');
    await scene('z-history-tray','05_empty_entry_tray.png');
    await scene('a-new-table','03_keys_study_desk.png');
    await scene('m-rival-shelf','04_rival_red_keys.png');
    await chapter('changed-scenes','#scene-title');
    await send('蓝色钥匙找不到了，请先检查最近记录的位置，没找到再继续寻找。');
    await chapter('search-in-progress','#session-title',2);
    const candidate=await waitState('AWAITING_REVIEW');
    check('real LLM follows last history then actual candidate',candidate.visited[0]==='z-history-tray'&&candidate.candidate.location_id==='a-new-table'&&candidate.candidate.bbox?.length===4&&candidate.model_calls>0);
    await chapter('actual-candidate','#candidate-panel',5);
    await chapter('search-order','#memory-panel',4);
    await chapter('current-image-evidence','#observations-panel',4);
    await chapter('real-tool-trace','#trace-panel',6);
    await page.locator('#trace li').last().scrollIntoViewIfNeeded();await pause(4);
    await page.getByRole('button',{name:'是我要找的物品，记录此位置',exact:true}).click();
    const accepted=await waitState('USER_CONFIRMED');check('scripted owner confirmation is not automatic FOUND',accepted.history.length===2&&!accepted.visual_confirmed);
    await chapter('user-confirmed','#session-title',4);
    await send('蓝色钥匙最近一次记在哪里？');
    const history=await waitState('COMPLETED');check('history query reads changed location',history.history.length===2&&history.history[0].location_id==='a-new-table');
    await chapter('history-query','#memory-panel',5);
    await chapter('model-call-metrics','#model-title',4);
    await Promise.all(pending);
    check('all browser network local',summary.network.every(x=>x.local));
    check('no image network approval',!summary.network.some(x=>x.pathname.includes('vision')));
    check('no page errors',summary.errors.length===0);
    summary.passed=true;
  } catch(error){summary.failure_type=error.name;summary.failure_message=error.message;throw error;}
  finally {
    if(context){summary.video=path.basename(await page.video().path());await context.close();}
    if(browser){summary.browser=browser.version();await browser.close();}
    server.kill();fsSync.closeSync(log);
    summary.usage={model_calls:Object.values(summary.runs).reduce((s,r)=>s+(r.model_calls||0),0),total_tokens:Object.values(summary.runs).reduce((s,r)=>s+(r.total_tokens||0),0)};
    await save();
  }
  console.log(JSON.stringify({passed:summary.passed,checks:summary.checkpoints.length,usage:summary.usage,video:summary.video}));
})().catch(e=>{console.error(e.name+': '+e.message);process.exitCode=1;});
