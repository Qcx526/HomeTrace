/* Optional development tool: npm install playwright, npx playwright install msedge ffmpeg.
 * Records an actual browser session; no detection or report data is fabricated.
 * Usage: node tools/validate_p2_browser.cjs http://127.0.0.1:8765 artifacts/p2-browser-check
 */
const {chromium} = require('playwright');
const fs = require('node:fs/promises');
const path = require('node:path');
const assert = require('node:assert/strict');

async function main() {
  const url = process.argv[2] || 'http://127.0.0.1:8765';
  const output = path.resolve(process.argv[3] || 'artifacts/p2-browser-check');
  await fs.mkdir(output, {recursive: false});
  const browser = await chromium.launch({channel: process.env.HOMETRACE_BROWSER_CHANNEL || 'msedge', headless: true});
  const context = await browser.newContext({viewport: {width: 1440, height: 1080}, recordVideo: {dir: output, size: {width: 1440, height: 1080}}});
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const checks = {browser: browser.version(), viewport: {width: 1440, height: 1080}, scenarios: [], errors};
  try {
    await page.goto(url);
    await page.locator('#run').waitFor();
    assert.match(await page.title(), /HomeTrace/);
    await page.screenshot({path: path.join(output, 'home.png'), fullPage: true});
    for (const scenario of ['moved', 'missing', 'replay']) {
      await page.locator(`[data-scenario="${scenario}"]`).click();
      const response = page.waitForResponse(r => r.url().endsWith('/api/run') && r.request().method() === 'POST', {timeout: 90000});
      await page.locator('#run').click();
      const result = await response;
      assert.equal(result.status(), 200);
      const data = await result.json();
      await page.waitForFunction(() => !document.getElementById('run').disabled);
      if ((await page.locator('#play').innerText()).includes('暂停')) await page.locator('#play').click();
      await fs.writeFile(path.join(output, `${scenario}-session.json`), JSON.stringify(data, null, 2));
      let attempted = 0, arrived = 0, observed = 0;
      const steps = [];
      for (let i = 0; i < data.report.events.length; i++) {
        const event = data.report.events[i];
        await page.locator('#progress').evaluate((input, value) => {
          input.value = String(value);
          input.dispatchEvent(new Event('input', {bubbles: true}));
        }, i + 1);
        if (event.action === 'plan_next') attempted++;
        if (event.action === 'navigate' && event.result.status === 'ARRIVED') arrived++;
        if (event.action === 'detect_target' && event.result.diagnostics.image_decoded === true) observed++;
        assert.equal(Number(await page.locator('#attempted-count').innerText()), attempted);
        assert.equal(Number(await page.locator('#arrived-count').innerText()), arrived);
        assert.equal(Number(await page.locator('#observed-count').innerText()), observed);
        assert.equal(await page.locator('#result-panel').isVisible(), event.action === 'complete');
        if (event.action === 'plan_next') assert.equal(await page.locator('#image-frame').isVisible(), false);
        if (event.action === 'detect_target' && event.result.status === 'FOUND') {
          await page.locator('#box-overlay rect').waitFor({state: 'visible'});
          const box = await page.locator('#box-overlay rect').evaluate(rect => ['x', 'y', 'width', 'height'].map(k => Number(rect.getAttribute(k))));
          const expected = event.result.bbox;
          [expected[0], expected[1], expected[2] - expected[0], expected[3] - expected[1]].forEach((v, k) => assert.ok(Math.abs(v - box[k]) < 0.001));
          await page.screenshot({path: path.join(output, `${scenario}-matched.png`), fullPage: true});
        }
        if (scenario === 'moved' && event.action === 'view_result' && event.input_ids[0] === 'A') {
          assert.match(await page.locator('#observation-explanation').innerText(), /不能证明物品不存在/);
          await page.screenshot({path: path.join(output, 'moved-unconfirmed-A.png'), fullPage: true});
        }
        if (scenario === 'replay' && event.result.reason === 'replayed_evidence') {
          assert.equal(await page.locator('#box-overlay').isVisible(), false);
          assert.equal(observed, 0);
          await page.screenshot({path: path.join(output, `replay-rejected-${event.input_ids[0]}.png`), fullPage: true});
        }
        steps.push({seq: event.seq, action: event.action, attempted, arrived, observed});
        // Short pauses expose the real application frames in the continuous recording.
        await page.waitForTimeout(event.action === 'view_result' || event.action === 'detect_target' ? 1000 : 450);
      }
      assert.equal(await page.locator('#final-status').innerText(), data.report.result_status);
      assert.equal(await page.locator('#comparison-body tr').count(), 2);
      await page.locator('#result-panel').scrollIntoViewIfNeeded();
      await page.screenshot({path: path.join(output, `${scenario}-final.png`), fullPage: true});
      const download = page.waitForEvent('download');
      await page.getByText('下载本轮报告 JSON').click();
      const downloaded = await download;
      const saved = path.join(output, `${scenario}-download.json`);
      await downloaded.saveAs(saved);
      assert.deepEqual(JSON.parse(await fs.readFile(saved, 'utf8')), data.report);
      checks.scenarios.push({scenario, run_id: data.run_id, result_status: data.report.result_status, location: data.report.location, steps, comparison: data.comparison.rows, downloaded_report_matches: true});
      await page.waitForTimeout(1500);
      await page.evaluate(() => window.scrollTo(0, 0));
    }
    await page.setViewportSize({width: 390, height: 844});
    await page.screenshot({path: path.join(output, 'mobile.png'), fullPage: true});
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true);
    checks.mobile_no_horizontal_overflow = true;
    assert.deepEqual(errors, []);
    checks.passed = true;
  } finally {
    await context.close();
    checks.video = path.basename(await page.video().path());
    await fs.writeFile(path.join(output, 'browser-checks.json'), JSON.stringify(checks, null, 2));
    await browser.close();
  }
  console.log(JSON.stringify(checks, null, 2));
}

main().catch(error => {console.error(error); process.exitCode = 1;});
