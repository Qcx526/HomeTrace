/* Local-only UI validation. Does not record, screenshot or export private photos. */
const {chromium} = require('playwright');
const fs = require('node:fs/promises');
const path = require('node:path');
const assert = require('node:assert/strict');

async function main() {
  const output = path.resolve(process.argv[3] || 'artifacts/p3-private-ui-check.json');
  const browser = await chromium.launch({channel: process.env.HOMETRACE_BROWSER_CHANNEL || 'msedge', headless: true});
  const page = await browser.newPage({viewport: {width: 1440, height: 1080}});
  const checks = {data: 'team photographs; local only', navigation: 'simulated_navigation', results: [], errors: []};
  page.on('pageerror', e => checks.errors.push(e.message));
  try {
    await page.goto(process.argv[2] || 'http://127.0.0.1:8767');
    await page.locator('#case-select option[value="team-tissue"]').waitFor({state: 'attached'});
    await page.locator('#case-select').selectOption('team-tissue');
    assert.match(await page.locator('#case-privacy').innerText(), /私有/);
    for (const scenario of ['moved', 'missing', 'replay']) {
      await page.locator(`[data-scenario="${scenario}"]`).click();
      const promise = page.waitForResponse(r => r.url().endsWith('/api/run') && r.request().method() === 'POST', {timeout: 180000});
      await page.locator('#run').click();
      const response = await promise;
      assert.equal(response.status(), 200);
      const result = await response.json();
      await page.waitForFunction(() => !document.getElementById('run').disabled);
      await page.locator('#finish').click();
      assert.equal(result.report.object_id, 'tissue-pack');
      assert.equal(result.case.reference, 'images/ref_tissue.jpg');
      assert.notEqual(result.report.result_status, 'FOUND');
      assert.equal(result.report.location, null);
      assert.equal(await page.locator('#final-status').innerText(), result.report.result_status);
      assert.equal(await page.locator('#box-overlay').isVisible(), false);
      assert.match(await page.locator('#history-location').innerText(), /尚未确认/);
      assert.match(await page.locator('#source-notice').innerText(), /模拟/);
      checks.results.push({scenario, status: result.report.result_status, location: result.report.location,
        object_id: result.report.object_id, historical_evidence: result.report.historical_evidence.length,
        observed: result.report.observed_viewpoints.length, image_box_hidden: true});
    }
    await page.locator('#case-select').selectOption('public');
    assert.match(await page.locator('#case-privacy').innerText(), /公开/);
    assert.equal(await page.locator('#result-panel').isVisible(), false);
    assert.deepEqual(checks.errors, []);
    checks.passed = true;
  } finally {
    await browser.close();
    await fs.mkdir(path.dirname(output), {recursive: true});
    await fs.writeFile(output, JSON.stringify(checks, null, 2));
  }
  console.log(JSON.stringify(checks, null, 2));
}
main().catch(error => {console.error(error); process.exitCode = 1;});
