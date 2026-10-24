"use strict";

(() => {
  const el = (id) => document.getElementById(id);
  const terminal = new Set(["COMPLETED", "MODEL_UNAVAILABLE", "AGENT_FAILED", "BUDGET_EXCEEDED", "CLARIFY", "UNKNOWN_OBJECT"]);
  const labels = {RUNNING: "正在执行", COMPLETED: "本轮执行结束", MODEL_UNAVAILABLE: "模型服务不可用", AGENT_FAILED: "Agent 执行失败", BUDGET_EXCEEDED: "已达到调用预算", CLARIFY: "需要明确目标", UNKNOWN_OBJECT: "目标尚未登记"};
  let enabled = false;
  let generation = 0;
  let currentBox = null;
  let lastTrace = "";
  let pollTimer = null;
  let pollingInterrupted = false;

  const text = (id, value) => { el(id).textContent = value == null ? "—" : String(value); };
  const count = (value) => Number.isFinite(value) && value >= 0 ? String(value) : "未报告";
  const asJson = (value) => JSON.stringify(value, null, 2);

  async function api(url, options = {}) {
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 15000);
    try {
      const response = await fetch(url, {cache: "no-store", signal: controller.signal, ...options});
      let result;
      try { result = await response.json(); } catch (_) { throw new Error("服务未返回可读取的 JSON，请检查本地服务日志。"); }
      if (!response.ok) throw new Error(typeof result.error === "string" ? result.error : `请求失败（HTTP ${response.status}）。`);
      return result;
    } finally {
      window.clearTimeout(timeout);
    }
  }

  function error(message) {
    el("error").hidden = !message;
    text("error", message || "");
  }

  function imageUrl(value) {
    if (typeof value !== "string" || !value) return null;
    try {
      const url = new URL(value, window.location.origin);
      return url.origin === window.location.origin && ["http:", "https:"].includes(url.protocol) ? url.href : null;
    } catch (_) { return null; }
  }

  function drawBox() {
    const image = el("current");
    const canvas = el("bbox");
    if (!image.complete || !image.naturalWidth) return;
    canvas.width = image.naturalWidth;
    canvas.height = image.naturalHeight;
    const context = canvas.getContext("2d");
    context.clearRect(0, 0, canvas.width, canvas.height);
    if (!Array.isArray(currentBox) || currentBox.length !== 4 || !currentBox.every(Number.isFinite)) return;
    const [x1, y1, x2, y2] = currentBox;
    if (x1 < 0 || y1 < 0 || x2 <= x1 || y2 <= y1 || x2 > canvas.width || y2 > canvas.height) return;
    context.strokeStyle = "#20e39d";
    context.lineWidth = Math.max(2, canvas.width / 180);
    context.strokeRect(x1, y1, x2 - x1, y2 - y1);
  }

  function renderImages(data) {
    const images = data.images || {};
    const reference = imageUrl(images.reference);
    if (reference && el("reference").src !== reference) el("reference").src = reference;
    el("reference").hidden = !reference;
    const current = imageUrl(images.current);
    currentBox = data.bbox || null;
    el("image-frame").hidden = !current;
    el("image-placeholder").hidden = Boolean(current);
    if (current) {
      if (el("current").src !== current) {
        const canvas = el("bbox");
        canvas.getContext("2d").clearRect(0, 0, canvas.width, canvas.height);
        el("current").src = current;
      } else drawBox();
    }
  }

  function renderHistory(records) {
    const list = el("history");
    list.replaceChildren();
    for (const record of Array.isArray(records) ? records : []) {
      const item = document.createElement("li");
      item.textContent = `历史位置 ${record.viewpoint_id ?? "未提供"} · ${record.status ?? "未提供状态"} · 仅作历史参考`;
      list.append(item);
    }
    if (!list.children.length) {
      const item = document.createElement("li");
      item.textContent = "暂无工具返回的历史记忆。";
      list.append(item);
    }
  }

  function renderTrace(records) {
    const values = Array.isArray(records) ? records : [];
    const encoded = asJson(values);
    if (encoded === lastTrace) return;
    lastTrace = encoded;
    const panel = el("trace").parentElement;
    const following = panel.scrollTop + panel.clientHeight >= panel.scrollHeight - 90;
    el("trace").replaceChildren();
    el("trace-empty").hidden = values.length > 0;
    for (const record of values) {
      const item = document.createElement("li");
      const kind = ["model", "tool", "state"].includes(record.kind) ? record.kind : "state";
      item.className = kind;
      const heading = document.createElement("div");
      heading.className = "trace-heading";
      const title = document.createElement("span");
      title.textContent = `${record.seq ?? "·"} · ${{model: "模型调用 / 决策摘要", tool: "实际工具调用", state: "Agent 状态"}[kind]}`;
      const timing = document.createElement("small");
      const milliseconds = record.elapsed_ms ?? record.latency_ms;
      timing.textContent = Number.isFinite(milliseconds) ? `${Math.round(milliseconds)} ms` : "";
      heading.append(title, timing);
      const body = document.createElement("pre");
      body.textContent = asJson(record);
      item.append(heading, body);
      el("trace").append(item);
    }
    if (following) panel.scrollTop = panel.scrollHeight;
  }

  function render(data) {
    const verified = data.verified_result || {};
    const state = data.status || "RUNNING";
    text("run-status", labels[state] || state);
    el("run-status").className = `status ${state === "RUNNING" ? "running" : verified.result_status === "FOUND" ? "found" : "warning"}`;
    text("run-id", data.run_id || "");
    text("model-count", count(data.model_calls));
    text("tool-count", count(data.tool_calls));
    text("token-count", count(data.total_tokens));
    text("live-label", state === "RUNNING" ? "实时更新" : "本轮已停止");
    text("visual-status", verified.result_status || "等待观察");
    text("result-status", verified.result_status || "尚无搜索结果");
    text("result-location", verified.result_status === "FOUND" && verified.location ? verified.location : "未确认");
    text("result-route", Array.isArray(verified.attempted_viewpoints) && verified.attempted_viewpoints.length ? verified.attempted_viewpoints.join(" → ") : "尚无尝试");
    text("result-evidence", Array.isArray(verified.confirmed_evidence_ids) && verified.confirmed_evidence_ids.length ? verified.confirmed_evidence_ids.join("\n") : "无当前确认证据");
    text("explanation", data.explanation || "尚无模型说明。位置、到达与检测事实以工具验证结果为准。");
    text("core-events", Array.isArray(data.core_events) && data.core_events.length ? asJson(data.core_events) : "尚无事件。");
    renderHistory(data.history);
    renderImages(data);
    renderTrace(data.trace);
    if (data.error) error(typeof data.error === "string" ? data.error : "本轮执行报告了错误，请查看实际轨迹。");
  }

  async function poll(runId, runGeneration) {
    if (runGeneration !== generation) return;
    try {
      const data = await api(`/api/agent/runs/${encodeURIComponent(runId)}`);
      if (runGeneration !== generation) return;
      if (pollingInterrupted) {
        pollingInterrupted = false;
        error("");
      }
      render(data);
      if (terminal.has(data.status)) {
        el("run").disabled = !enabled;
        el("run").textContent = "开始新一轮 Agent ↗";
        return;
      }
      pollTimer = window.setTimeout(() => poll(runId, runGeneration), 1000);
    } catch (exception) {
      if (runGeneration !== generation) return;
      pollingInterrupted = true;
      error(`状态读取中断：${exception.message} 本轮后台执行状态未知；请勿据此认为已完成。`);
      text("live-label", "连接中断，正在重试");
      pollTimer = window.setTimeout(() => poll(runId, runGeneration), 3000);
    }
  }

  el("current").addEventListener("load", drawBox);
  el("current").addEventListener("error", () => {
    el("image-frame").hidden = true;
    el("image-placeholder").hidden = false;
    error("当前照片无法读取。仍可查看实际工具轨迹；图片缺失不能作为确认结果。");
  });
  el("example").addEventListener("click", () => {
    el("goal").value = "请帮我找到已登记的公开样例盒子。";
    el("goal").focus();
  });
  el("request-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const goal = el("goal").value.trim();
    if (!enabled || !goal || el("run").disabled) return;
    const runGeneration = ++generation;
    if (pollTimer) window.clearTimeout(pollTimer);
    error("");
    pollingInterrupted = false;
    el("run").disabled = true;
    el("run").textContent = "正在执行…";
    lastTrace = "";
    render({status: "RUNNING", model_calls: 0, tool_calls: 0, total_tokens: 0});
    text("run-status", "正在创建运行");
    try {
      const data = await api("/api/agent/run", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({goal, scenario: el("scenario").value})});
      if (typeof data.run_id !== "string" || !data.run_id) throw new Error("服务未返回运行编号。");
      await poll(data.run_id, runGeneration);
    } catch (exception) {
      error(exception.message);
      text("run-status", "启动失败");
      text("live-label", "未启动");
      el("run").disabled = !enabled;
      el("run").textContent = "重试启动 Agent ↗";
    }
  });

  async function configure() {
    try {
      const config = await api("/api/agent/config");
      el("scenario").replaceChildren();
      for (const scenario of Array.isArray(config.scenarios) ? config.scenarios : []) {
        if (!["moved", "missing", "replay", "fair"].includes(scenario.id)) continue;
        const option = document.createElement("option");
        option.value = scenario.id;
        option.textContent = scenario.label || scenario.id;
        el("scenario").append(option);
      }
      enabled = config.enabled === true && el("scenario").options.length > 0;
      el("scenario").disabled = !enabled;
      el("run").disabled = !enabled;
      text("config-notice", config.notice || (enabled ? "模型通过真实 API 调用；照片仅在本机处理。" : "Agent 暂不可用，请检查本地配置。"));
      if (!enabled) text("run-status", "Agent 暂不可用");
    } catch (exception) {
      text("config-notice", "无法读取 Agent 配置。经典 Demo 仍可通过顶部入口访问。");
      error(exception.message);
    }
  }
  configure();
})();
