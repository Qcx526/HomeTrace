/* Actual UI/API run; never intercept requests or supply model/tool results. */
const {chromium} = require('playwright');
const fs = require('node:fs/promises');
const path = require('node:path');
const assert = require('node:assert/strict');

(async () => {
  const url = process.argv[2] || 'http://127.0.0.1:8766';
  const output = path.resolve(process.argv[3] || 'artifacts/issue-11/browser-01');
  await fs.mkdir(output,{recursive:false});
  const browser = await chromium.launch({channel:'msedge',headless:true});
  const context = await browser.newContext({viewport:{width:1440,height:1080},recordVideo:{dir:output,size:{width:1440,height:1080}}});
  const page = await context.newPage();
  const errors = [], polls = [];
  page.on('pageerror',e => errors.push(e.message));
  page.on('response',async r => {
    if (/\/api\/agent\/runs\/[a-f0-9]{32}$/.test(r.url())) {
      try { polls.push(await r.json()); } catch (_) {}
    }
  });
  try {
    await page.goto(url+'/agent.html');
    await page.locator('#scenario').selectOption('moved');
    await page.locator('#goal').fill('请帮我找到已登记的公开样例盒子。');
    await page.screenshot({path:path.join(output,'input.png'),fullPage:true});
    await page.locator('#run').click();
    await page.waitForFunction(() => document.querySelector('#trace li.tool'),{},{timeout:120000});
    await page.screenshot({path:path.join(output,'live-tools.png'),fullPage:true});
    await page.waitForFunction(() => !document.querySelector('#run').disabled,{},{timeout:600000});
    const result = polls.at(-1);
    assert.equal(result.status,'COMPLETED');
    assert.equal(result.verified_result.result_status,'FOUND');
    assert.equal(await page.locator('#result-location').innerText(),result.verified_result.location);
    assert.ok(polls.some(p => p.status==='RUNNING' && p.trace.length>0));
    await page.locator('#current').waitFor({state:'visible'});
    const image = await page.locator('#current').evaluate(img => ({width:img.naturalWidth,height:img.naturalHeight,url:img.getAttribute('src')}));
    const canvas = await page.locator('#bbox').evaluate(c => ({width:c.width,height:c.height,nonzero:Array.from(c.getContext('2d').getImageData(0,0,c.width,c.height).data).some(v=>v!==0)}));
    assert.equal(canvas.width,image.width); assert.equal(canvas.height,image.height); assert.ok(canvas.nonzero);
    assert.ok(image.url.endsWith('/images/current-2'));
    await page.screenshot({path:path.join(output,'found.png'),fullPage:true});
    await page.setViewportSize({width:390,height:844});
    await page.screenshot({path:path.join(output,'mobile.png'),fullPage:true});
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth<=window.innerWidth),true);
    assert.deepEqual(errors,[]);
    await fs.writeFile(path.join(output,'result.json'),JSON.stringify({browser:browser.version(),status:'PASSED',poll_count:polls.length,live_poll_count:polls.filter(p=>p.status==='RUNNING').length,image,canvas,errors,run_id:result.run_id,model_calls:result.model_calls,tool_calls:result.tool_calls,tokens:result.total_tokens,result:result.verified_result},null,2));
    await fs.writeFile(path.join(output,'session.private.json'),JSON.stringify(result,null,2));
  } finally {await context.close();await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
