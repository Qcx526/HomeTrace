'use strict';

// Full production client with explicit DOM and HTTP doubles. These are UI state
// tests, not real LLM calls, browser rendering or household recognition evidence.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../src/hometrace/web/home-flow.js'), 'utf8');
const html = fs.readFileSync(path.join(__dirname, '../src/hometrace/web/home-flow.html'), 'utf8');
const ids = new Set([...html.matchAll(/\bid="([^"]+)"/g)].map(match => match[1]));
const settle = () => new Promise(resolve => setImmediate(resolve));

class ElementDouble {
  constructor(tagName = 'div') {
    Object.assign(this, {tagName, children: [], options: [], listeners: {}, value: '', style: {}, dataset: {}, files: []});
  }
  append(...children) { this.children.push(...children); this.options = this.children; }
  replaceChildren(...children) { this.children = children; this.options = this.children; }
  addEventListener(type, callback) { this.listeners[type] = callback; }
  setAttribute(name, value) { this[name] = value; }
  querySelector() { return null; }
}

function allText(element) {
  return [element.textContent || '', ...element.children.map(allText)].join('\n');
}

async function client(mode = 'llm_langgraph') {
  const elements = new Map();
  const element = id => {
    assert.ok(ids.has(id), 'The production HTML must contain #' + id);
    if (!elements.has(id)) elements.set(id, new ElementDouble());
    return elements.get(id);
  };
  const config = {mode, notice: 'Software fixture', catalog: [], scenes: [], locations: [], model: 'test-model'};
  const context = vm.createContext({
    console, Number,
    fetch: async url => {
      assert.equal(url, '/api/home-flow/config');
      return {ok: true, json: async () => config};
    },
    Option: class { constructor(text, value) { this.text = text; this.value = value; } },
    document: {getElementById: element, querySelectorAll: () => [], createElement: tag => new ElementDouble(tag), createElementNS: (_, tag) => new ElementDouble(tag)},
    localStorage: {getItem: () => null, setItem() {}},
    setTimeout: () => 1, clearTimeout() {},
  });
  vm.runInContext(source, context);
  await settle();
  return {element, show: run => vm.runInContext('run=' + JSON.stringify(run) + ';renderRun();', context)};
}

function runFixture(extra = {}) {
  return {
    run_id: 'a'.repeat(32), version: 1, state: 'RUNNING', mode: 'llm_langgraph',
    model: 'test-model', model_calls: 3, tool_calls: 2, total_tokens: 902,
    selected_object: null, matches: [], history: [], planned_locations: [], visited: [],
    observations: [], trace: [], reply: '程序尚未确认目标。', candidate: null,
    ...extra,
  };
}

test('LLM metrics and choice are visible without turning a model rationale into a tool fact', async () => {
  const page = await client();
  const reason = '刚才玄关没有候选；查看有较早位置记录的书房。';
  page.show(runFixture({
    planned_locations: [{location_id: 'study', location_name: '书房', reason: 'llm_choice'}],
    visited: ['study'],
    trace: [
      {seq: 1, tool: 'llm_decision', at: '2026-10-28T00:00:00Z', input: {}, result: {selected_tool: 'navigate_simulated', decision_reason: reason, latency_ms: 121.5, usage: {total_tokens: 300}}},
      {seq: 2, tool: 'navigate_simulated', at: '2026-10-28T00:00:01Z', input: {location_id: 'study'}, result: {status: 'UNKNOWN', reason: 'simulation_only'}},
    ],
  }));
  assert.equal(page.element('model-mode').textContent, '真实 LLM 决策');
  assert.equal(page.element('model-metrics').hidden, false);
  assert.equal(page.element('model-name').textContent, 'test-model');
  assert.equal(page.element('model-calls').textContent, '3');
  assert.equal(page.element('tool-calls').textContent, '2');
  assert.equal(page.element('model-tokens').textContent, '902');
  assert.equal(page.element('model-reason').textContent, reason);
  assert.match(page.element('model-next-tool').textContent, /是否实际执行请查看/);
  assert.match(allText(page.element('plan')), /LLM 选择并已执行/);
  assert.doesNotMatch(allText(page.element('plan')), /规则：历史优先/);
  assert.match(allText(page.element('trace').children[0]), /模型选择 · 非观察证据/);
  assert.match(allText(page.element('trace').children[0]), /121.5 ms · 300 Token/);
  assert.match(allText(page.element('trace').children[1]), /实际工具执行 · 模拟导航/);
  assert.equal(page.element('reply').textContent, '程序尚未确认目标。');
  assert.match(page.element('model-privacy').textContent, /原始图片留在本地/);
  assert.match(page.element('model-privacy').textContent, /发送给已配置的模型 API/);
});

test('offline and restored offline runs do not claim LLM execution', async () => {
  for (const serviceMode of ['deterministic_rules', 'llm_langgraph']) {
    const page = await client(serviceMode);
    page.show(runFixture({mode: 'deterministic_langgraph', llm_explanation: 'Must not be presented as a model result'}));
    assert.equal(page.element('model-mode').textContent, '离线规则 + LangGraph');
    assert.equal(page.element('model-metrics').hidden, true);
    assert.equal(page.element('model-decision').hidden, true);
    assert.equal(page.element('model-name').textContent, '未调用');
    assert.match(page.element('model-description').textContent, /不产生真实 LLM 调用/);
  }
});

test('model outages, budget exhaustion and protocol failure stay explicit and do not offer false fallback', async () => {
  const page = await client();
  for (const [state, label, canRetry] of [
    ['MODEL_UNAVAILABLE', '模型服务不可用', true],
    ['BUDGET_EXCEEDED', '本次调用预算已用尽', false],
    ['AGENT_FAILED', 'Agent 执行失败', false],
  ]) {
    page.show(runFixture({state}));
    assert.equal(page.element('session-state').textContent, label);
    assert.equal(page.element('model-error').hidden, false);
    assert.match(page.element('model-error').textContent, /已停止/);
    assert.equal(page.element('session-actions').children.some(x => x.textContent === '重新查询 / 重试'), canRetry);
    assert.doesNotMatch(allText(page.element('session-actions')), /切换.*规则/);
  }
});

test('unknown model usage stays unknown and model text is rendered as literal non-authoritative text', async () => {
  const page = await client();
  const untrusted = '<img src=x onerror="pretendFound()">';
  page.show(runFixture({total_tokens: null, model_calls: undefined, llm_explanation: untrusted}));
  assert.equal(page.element('model-tokens').textContent, '待返回');
  assert.equal(page.element('model-calls').textContent, '待返回');
  assert.equal(page.element('model-reason').textContent, untrusted);
  assert.equal(page.element('model-reason').children.length, 0);
  assert.equal(page.element('reply').textContent, '程序尚未确认目标。');
  assert.equal(page.element('model-next-tool').textContent, '模型提供的文字说明，不替代工具证据。');
});
