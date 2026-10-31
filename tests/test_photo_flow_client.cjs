'use strict';

// Client state regression tests using the complete production JavaScript.
// DOM, timers, file reads and HTTP responses are explicit software doubles.
// These tests do not claim browser rendering or actual image recognition.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../src/hometrace/web/home-flow.js'), 'utf8');
const OLD_ID = 'a'.repeat(32);
const NEW_ID = 'b'.repeat(32);
const config = {
  catalog: [], locations: [], scenes: [],
  notice: 'Software test fixture', mode: 'deterministic_rules',
};

function runFixture(runId, overrides = {}) {
  return {
    run_id: runId, version: 1, state: 'RUNNING', mode: 'deterministic_rules',
    selected_object: null, matches: [], history: [], planned_locations: [],
    visited: [], observations: [], trace: [], reply: 'Searching', candidate: null,
    ...overrides,
  };
}

function response(value, status = 200) {
  return {
    ok: status >= 200 && status < 300, status,
    json: async () => JSON.parse(JSON.stringify(value)),
  };
}

function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

// Drain promise continuations without real polling delays or network access.
const settle = () => new Promise(resolve => setImmediate(resolve));

class ElementDouble {
  constructor(tagName = 'div') {
    Object.assign(this, {
      tagName, children: [], options: [], listeners: {}, value: '',
      style: {}, dataset: {}, files: [], checked: false,
    });
  }

  append(...children) { this.children.push(...children); this.options = this.children; }
  replaceChildren(...children) { this.children = children; this.options = this.children; }
  addEventListener(type, handler) { this.listeners[type] = handler; }
  setAttribute(name, value) { this[name] = value; }
  focus() {}

  querySelector(tagName) {
    for (const child of this.children) {
      if (child.tagName === tagName) return child;
      const nested = child.querySelector?.(tagName);
      if (nested) return nested;
    }
    return null;
  }
}

function createClient(fetch, initialStored = '') {
  const elements = new Map();
  const timers = new Map();
  let stored = initialStored, timerId = 0;
  const element = id => {
    if (!elements.has(id)) elements.set(id, new ElementDouble());
    return elements.get(id);
  };
  const context = vm.createContext({
    console, Number, fetch,
    Option: class {
      constructor(text, value) { this.text = text; this.value = value; }
    },
    FileReader: class {
      readAsDataURL() {
        this.result = 'data:image/png;base64,c29mdHdhcmUgdGVzdCBkb3VibGU=';
        this.onload();
      }
    },
    document: {
      getElementById: element,
      querySelectorAll: () => [],
      createElement: tag => new ElementDouble(tag),
      createElementNS: (_, tag) => new ElementDouble(tag),
    },
    localStorage: { getItem: () => stored, setItem: (_, value) => { stored = value; } },
    setTimeout: (callback, delay) => { timers.set(++timerId, { callback, delay }); return timerId; },
    clearTimeout: id => timers.delete(id),
  });
  vm.runInContext(source, context);
  return {
    element,
    evaluate: code => vm.runInContext(code, context),
    stored: () => stored,
    pendingTimers: () => [...timers].map(([id, value]) => [id, value.delay]),
  };
}

async function startNewRunWhileOldPollIsPending() {
  const oldRequest = deferred();
  let oldReads = 0;
  const client = createClient(async (url, options) => {
    if (url === '/api/home-flow/config') return response(config);
    if (url === '/api/home-flow/runs/' + OLD_ID) {
      return oldReads++ === 0 ? response(runFixture(OLD_ID)) : oldRequest.promise;
    }
    if (url === '/api/home-flow/act') {
      const action = JSON.parse(options.body);
      assert.equal(action.run_id, OLD_ID);
      assert.equal(action.action, 'cancel');
      return response(runFixture(OLD_ID, { version: 2, state: 'CANCELLED' }));
    }
    if (url === '/api/home-flow/start') return response(runFixture(NEW_ID));
    throw new Error('Unexpected request: ' + url);
  }, OLD_ID);
  await settle();
  assert.equal(client.evaluate('run.run_id'), OLD_ID);
  const poll = client.evaluate('poll()');
  assert.equal(oldReads, 2);

  const cancel = client.element('session-actions').children.find(button => button.textContent === '取消后续操作');
  assert.ok(cancel);
  await cancel.onclick();
  assert.equal(client.evaluate('run.state'), 'CANCELLED');
  client.element('message').value = '帮我找新物品';
  client.element('request-form').listeners.submit({ preventDefault() {} });
  await settle();
  assert.equal(client.evaluate('run.run_id'), NEW_ID);
  assert.equal(client.stored(), NEW_ID);
  return { client, oldRequest, poll };
}

test('workspace places appear as literal names and submit their actual IDs', async () => {
  const places = [{location_id: 'fixture-shelf', location_name: '样例架'},
    {location_id: 'fixture-table', location_name: '<b>样例桌</b>'}];
  let submitted;
  const client = createClient(async (url, options) => {
    if (url === '/api/home-flow/config') return response({...config, locations: places});
    if (url === '/api/home-flow/start') {
      submitted = JSON.parse(options.body);
      return response(runFixture(NEW_ID, {state: 'CONFIRM_MEMORY'}));
    }
    throw new Error('Unexpected request: ' + url);
  });
  await settle();
  for (const id of ['current-location', 'scene-location']) {
    assert.deepEqual(client.element(id).options.slice(1).map(x => [x.value, x.text]),
      places.map(x => [x.location_id, x.location_name]));
  }
  assert.equal(client.element('scenes').children.length, 2);
  client.element('message').value = '请记住测试物品';
  client.element('current-location').value = 'fixture-table';
  client.element('request-form').listeners.submit({preventDefault() {}});
  await settle();
  assert.equal(submitted.current_location_id, 'fixture-table');
  assert.equal(client.evaluate('run.state'), 'CONFIRM_MEMORY');
});

test('an old poll cannot replace a newly started run or its recovery ID', async () => {
  const { client, oldRequest, poll } = await startNewRunWhileOldPollIsPending();
  oldRequest.resolve(response(runFixture(OLD_ID)));
  await poll;

  assert.equal(client.evaluate('run.run_id'), NEW_ID);
  assert.equal(client.stored(), NEW_ID);
  assert.equal(client.element('session-state').textContent, '正在搜索');
});

test('a lower version response cannot roll back the same run', async () => {
  const older = deferred(), newer = deferred();
  let reads = 0;
  const client = createClient(async url => {
    if (url === '/api/home-flow/config') return response(config);
    if (url === '/api/home-flow/runs/' + OLD_ID) {
      return [response(runFixture(OLD_ID)), older.promise, newer.promise][reads++];
    }
    throw new Error('Unexpected request: ' + url);
  }, OLD_ID);
  await settle();
  const olderPoll = client.evaluate('poll()');
  const newerPoll = client.evaluate('poll()');
  assert.equal(reads, 3);
  newer.resolve(response(runFixture(OLD_ID, { version: 3, reply: 'Newer progress' })));
  await newerPoll;
  older.resolve(response(runFixture(OLD_ID, { version: 2, reply: 'Older progress' })));
  await olderPoll;

  assert.equal(client.evaluate('run.version'), 3);
  assert.equal(client.element('reply').textContent, 'Newer progress');
  assert.equal(client.stored(), OLD_ID);
});

test('an invalidated request error cannot disturb the new run or its polling timer', async () => {
  const { client, oldRequest, poll } = await startNewRunWhileOldPollIsPending();
  const timersBefore = client.pendingTimers();
  assert.equal(client.element('error').hidden, true);
  oldRequest.reject(new Error('Old request failed after a new run started'));
  await poll;

  assert.equal(client.evaluate('run.run_id'), NEW_ID);
  assert.equal(client.stored(), NEW_ID);
  assert.equal(client.element('error').hidden, true);
  assert.deepEqual(client.pendingTimers(), timersBefore);
});

test('a failed replacement upload cannot submit the previously reviewed reference', async () => {
  let uploads = 0;
  const submissions = [];
  const asset = {
    asset_id: OLD_ID, url: '/api/home-flow/assets/' + OLD_ID,
    width: 64, height: 64, source_kind: 'synthetic',
  };
  const client = createClient(async (url, options) => {
    if (url === '/api/home-flow/config') return response(config);
    if (url === '/api/home-flow/assets') {
      return ++uploads === 1 ? response(asset) : response({ error: 'Replacement image rejected' }, 400);
    }
    if (url === '/api/home-flow/reference') {
      submissions.push(JSON.parse(options.body));
      return response({});
    }
    throw new Error('Unexpected request: ' + url);
  });
  await settle();
  client.element('reference-object').value = 'keys-a';
  client.element('reference-source').value = 'synthetic';
  const input = client.element('reference-file');
  input.files = [{ name: 'first.png', type: 'image/png', size: 64 }];
  await input.listeners.change();
  client.element('roi-reviewed').checked = true;
  client.element('roi-reviewed').listeners.change();
  assert.equal(client.element('save-reference').disabled, false);

  input.files = [{ name: 'replacement.png', type: 'image/png', size: 64 }];
  await input.listeners.change();
  assert.equal(uploads, 2);
  assert.equal(client.element('error').textContent, 'Replacement image rejected');
  assert.equal(client.element('reference-upload-status').textContent, '图片未保存，请重新选择。');
  assert.equal(client.element('save-reference').disabled, true);
  assert.equal(client.element('roi-reviewed').checked, false);
  assert.equal(client.element('roi-editor').hidden, true);

  // The submit handler must also refuse the stale asset if invoked directly.
  client.element('reference-form').listeners.submit({ preventDefault() {} });
  await settle();
  assert.deepEqual(submissions, []);
});
