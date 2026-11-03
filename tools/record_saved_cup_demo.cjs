/* Record actual production HTML while inspecting completed, saved tasks.
 * No response interception, inference, confirmation clicks or synthetic states.
 * The server is read-only; original scene images remain fully visible.
 */
const {chromium}=require('playwright');
const fs=require('node:fs/promises'), fss=require('node:fs');
const path=require('node:path'), crypto=require('node:crypto');
const {spawn,spawnSync}=require('node:child_process');
const assert=require('node:assert/strict');
const {isDeepStrictEqual}=require('node:util');
const digest=b=>crypto.createHash('sha256').update(b).digest('hex');
const pause=ms=>new Promise(r=>setTimeout(r,ms));

(async()=>{
 const [planArg,summaryArg,outArg,pythonArg]=process.argv.slice(2);
 assert.ok(planArg&&summaryArg&&outArg&&pythonArg,'plan summary output python are required');
 const root=path.resolve(__dirname,'..'),output=path.resolve(outArg);
 assert.ok(output.startsWith(root+path.sep));assert.ok(!fss.existsSync(output));
 assert.equal(spawnSync('git',['check-ignore','--quiet',path.relative(root,path.join(output,'recording.json'))],{cwd:root,windowsHide:true}).status,0);
 const plan=JSON.parse(await fs.readFile(planArg,'utf8')),saved=JSON.parse(await fs.readFile(summaryArg,'utf8'));
 assert.equal(saved.runs.main.final.state,'USER_CONFIRMED');
 assert.equal(saved.runs.history.final.state,'COMPLETED');assert.equal(saved.runs.replay.final.state,'UNKNOWN');
 assert.equal(saved.runs.main.final.visual_confirmed,false);
 await fs.mkdir(output,{recursive:false});
 const workspace=path.resolve(plan.workspace);
 const dbs=(await fs.readdir(workspace)).filter(x=>/\.(sqlite|sqlite3|db)$/.test(x));
 const before=Object.fromEntries(await Promise.all(dbs.map(async x=>[x,digest(await fs.readFile(path.join(workspace,x)))])));
 const log=fss.openSync(path.join(output,'readonly-server.log'),'wx');
 const server=spawn(path.resolve(pythonArg),['-X','utf8','tools/serve_saved_demo.py','--workspace',workspace,'--summary',path.resolve(summaryArg),'--port','0'],{cwd:root,windowsHide:true,stdio:['ignore',log,log]});
 const audit={kind:'production_html_saved_task_inspection',new_model_calls:0,image_uploads:0,
   continuous_new_execution:false,navigation:'simulated',owner_confirmation:'previous_explicit_authorization',
   private_photographs:true,errors:[],network:[],chapters:[],checks:[],
   input_sha256:{plan:digest(await fs.readFile(planArg)),summary:digest(await fs.readFile(summaryArg))},
   ui_sha256:Object.fromEntries(await Promise.all(['home-flow.html','home-flow.js','home-flow.css'].map(async n=>[n,digest(await fs.readFile(path.join(root,'src/hometrace/web',n)))]))),
   privacy:'No masking; owner explicitly requested original workstation appearance for local submission media',passed:false};
 let context,browser,page,start;
 const check=(name,yes)=>{audit.checks.push({name,passed:!!yes});assert.ok(yes,name)};
 try{
  let url;
  for(let i=0;i<200;i++){const t=await fs.readFile(path.join(output,'readonly-server.log'),'utf8');const m=t.match(/HomeTrace demo: (http:\/\/127\.0\.0\.1:\d+)/);if(m){url=m[1];break;}assert.equal(server.exitCode,null);await pause(100)}
  assert.ok(url,'server readiness');
  browser=await chromium.launch({channel:'msedge',headless:true});
  context=await browser.newContext({viewport:{width:1440,height:1080},recordVideo:{dir:output,size:{width:1440,height:1080}}});
  await context.route('**/*',route=>{const r=route.request(),u=new URL(r.url());
   if(u.origin===url&&r.method()==='GET')return route.continue();
   audit.errors.push('BLOCKED_NONLOCAL_OR_WRITE_REQUEST');return route.abort();});
  page=await context.newPage();start=Date.now();
  page.on('pageerror',e=>audit.errors.push(e.name));
  page.on('request',r=>audit.network.push({method:r.method(),pathname:new URL(r.url()).pathname,local:new URL(r.url()).origin===url}));
  async function chapter(name,locator,seconds=5){
   if(locator)await locator.scrollIntoViewIfNeeded();await pause(450);
   audit.chapters.push({name,seconds:(Date.now()-start)/1000});
   await page.screenshot({path:path.join(output,String(audit.chapters.length).padStart(2,'0')+'-'+name+'.png')});await pause(seconds*1000);
  }
  async function load(which){
   const r=saved.runs[which].final;await page.goto(url+'/?run='+r.run_id);
   await page.waitForFunction(()=>document.querySelector('#reply').textContent.length>0);
   const actual=await (await page.request.get(url+'/api/home-flow/runs/'+r.run_id)).json();
   check(which+' state equals frozen record',actual.state===r.state&&actual.version===r.version);
   check(which+' tool trace equals frozen record',isDeepStrictEqual(actual.trace,r.trace));
  }
  await load('main');await chapter('cup-overview',null,5);
  await page.getByRole('button',{name:'选择这件物品',exact:true}).first().click();
  await chapter('registered-cup',page.locator('#registered-reference'),6);
  await chapter('saved-search-order',page.locator('#memory-panel'),6);
  const opinions=page.locator('#visual-advice .visual-advice-card');
  check('three saved image comparisons',await opinions.count()===3);
  await chapter('original-place-not-visible',opinions.nth(0),6);
  await chapter('wide-view-uncertain',opinions.nth(1),6);
  await chapter('close-view-advice',opinions.nth(2),6);
  const images=page.locator('#observations .observation-card');
  await chapter('scene-wide-photo',images.nth(1),6);
  await chapter('scene-close-photo',images.nth(2),6);
  const decisions=page.locator('#trace .model-trace');
  await chapter('feedback-decisions',decisions.first(),5);
  await chapter('feedback-next-action',decisions.nth(Math.min(3,(await decisions.count())-1)),5);
  await chapter('saved-owner-confirmation',page.locator('#session-title'),5);
  await load('history');await chapter('restart-history',page.locator('#memory-panel'),7);
  const history=page.locator('.history-details summary');await history.click();await pause(650);await history.click();
  await chapter('history-still-saved',page.locator('#memory-panel'),5);
  await load('replay');await chapter('old-photo-not-new-evidence',page.locator('#session-title'),7);
  await chapter('future-voice-and-robot',page.locator('#session-title'),9);
  check('only local GET requests',audit.network.every(r=>r.local&&r.method==='GET'));
  check('no browser errors',audit.errors.length===0);
  check('original databases unchanged',(await Promise.all(dbs.map(async n=>digest(await fs.readFile(path.join(workspace,n)))===before[n]))).every(Boolean));
  audit.database_sha256=before;audit.passed=true;
 }finally{
  if(context){audit.video=path.basename(await page.video().path());await context.close();}
  if(browser){audit.browser=browser.version();await browser.close();}
  server.kill();fss.closeSync(log);
  if(audit.video&&fss.existsSync(path.join(output,audit.video)))audit.video_sha256=digest(await fs.readFile(path.join(output,audit.video)));
  await fs.writeFile(path.join(output,'recording.private.json'),JSON.stringify(audit,null,2));
 }
 console.log(JSON.stringify({passed:audit.passed,checks:audit.checks.length,chapters:audit.chapters.length,new_model_calls:0}));
})().catch(e=>{console.error(e.name+': '+e.message);process.exitCode=1});
