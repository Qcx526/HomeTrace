"use strict";

// Render only the prefix of acquired core events selected by the viewer.
// The page never supplies detections, navigation outcomes, or plan decisions.
const $ = (id) => document.getElementById(id);
const state = {scenario: "moved", data: null, cursor: -1, timer: null, busy: false};
const strategies = {memory_first: "记忆优先", fixed_order: "固定顺序"};
const statusNames = {FOUND: "已确认参考外观", SUSPECTED: "疑似 · 尚未确认", UNKNOWN: "未知 · 尚未确认", UNREACHABLE: "未能到达", NOT_FOUND_IN_VIEW: "本视野未发现"};
const reasons = {
  latest_memory_found: "优先核验最近的历史确认位置",
  latest_memory_suspected: "优先核验历史疑似位置",
  latest_memory_negative: "历史视野负证据降低优先级",
  unvisited_fallback: "继续检查尚未尝试的观察点",
  fixed_order: "按预先固定的观察点顺序访问",
  fixed_viewpoint_order: "按预先固定的观察点顺序访问",
  insufficient_distinct_matches: "特征支持不足，当前图片不能确认目标",
  verified_planar_reference_match: "特征匹配与几何验证支持参考外观确认",
  no_verified_match: "没有得到可靠的参考外观匹配",
  replayed_evidence: "证据 ID 已在历史中，拒绝作为当前新确认",
  replayed_image_content: "图片字节与历史重复，拒绝作为当前新确认",
  observation_not_newer_than_memory: "图片记录不晚于已有记忆，不能作为新观察",
  timestamp_basis_changed: "时间依据不同，不能混为连续观测",
  no_observation: "没有可用的图像观察",
  unusable_detection: "检测未通过核心校验，不能确认",
};

function text(id, value) { $(id).textContent = value == null ? "—" : String(value); }
function element(tag, className, content) {
  const item = document.createElement(tag);
  if (className) item.className = className;
  if (content != null) item.textContent = String(content);
  return item;
}
function statusBadge(node, value, fallback = "等待观察") {
  node.textContent = value || fallback;
  node.className = "badge " + (Object.hasOwn(statusNames, value) ? value : "neutral");
}
function explain(reason) { return reasons[reason] || reason || "等待本轮证据"; }
function imageURL(path) {
  const value = state.data?.images?.[path];
  // Only the local server's run-scoped image routes may be shown.
  return typeof value === "string" && /^\/api\/runs\/[a-zA-Z0-9_-]+\/images\/[a-zA-Z0-9_.-]+$/.test(value) ? value : null;
}
function stop() {
  if (state.timer !== null) window.clearInterval(state.timer);
  state.timer = null;
  text("play", "播放过程");
  $("play").classList.remove("playing");
}
function startPlayback() {
  if (!state.data || state.timer !== null) return;
  if (state.cursor >= state.data.report.events.length - 1) setCursor(-1);
  state.timer = window.setInterval(() => setCursor(state.cursor + 1), 1100);
  text("play", "暂停回放");
  $("play").classList.add("playing");
}
function setCursor(cursor) {
  const events = state.data?.report?.events || [];
  state.cursor = Math.max(-1, Math.min(cursor, events.length - 1));
  if (state.cursor >= events.length - 1) stop();
  render();
}
function selectScenario(value) {
  if (state.busy) return;
  state.scenario = value;
  document.querySelectorAll("[data-scenario]").forEach((button) => {
    const selected = button.dataset.scenario === value;
    button.classList.toggle("selected", selected);
    button.setAttribute("aria-pressed", String(selected));
  });
}
function setBusy(busy) {
  state.busy = busy;
  $("run").disabled = busy;
  $("strategy").disabled = busy;
  document.querySelectorAll("[data-scenario]").forEach((button) => {button.disabled = busy;});
  text("run", busy ? "正在实际计算…" : "运行并回放 ↗");
}

async function run() {
  if (state.busy) return;
  stop();
  setBusy(true);
  $("error").hidden = true;
  state.data = null;
  state.cursor = -1;
  render();
  text("session-status", "正在独立数据库中登记、搜索并运行公平对照；真正读取照片执行 OpenCV 匹配…");
  try {
    const response = await fetch("/api/run", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({scenario: state.scenario, strategy: $("strategy").value})});
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "运行失败，请检查本地服务日志。");
    if (!Array.isArray(data.report?.events) || !data.report.events.length) throw new Error("服务未返回有效的搜索事件。");
    state.data = data;
    state.cursor = 0;
    text("session-status", "计算已完成 · 下方按真实事件顺序回放；可暂停、逐步查看或跳至结果。");
    text("session-id", "RUN " + String(data.run_id).slice(0, 12));
    render();
  } catch (error) {
    text("error", error.message || String(error));
    $("error").hidden = false;
    text("session-status", "本次运行未完成。修复错误后可重新运行；没有生成成功结论。");
  } finally {
    setBusy(false);
    renderControls();
    if (state.data) startPlayback();
  }
}

function prefixState() {
  const view = {history: [], attempted: [], arrived: [], observed: [], statuses: {}, current: null, observation: null, detection: null, rejection: null, finished: false, event: null};
  const events = state.data?.report?.events || [];
  for (const event of events.slice(0, state.cursor + 1)) {
    view.event = event;
    const result = event.result || {};
    if (event.action === "query_memory") view.history = result.records || [];
    if (event.action === "plan_next") {
      view.current = result.viewpoint_id;
      view.attempted.push(result.viewpoint_id);
      view.observation = null;
      view.detection = null;
      view.rejection = null;
    }
    if (event.action === "navigate" && result.status === "ARRIVED") view.arrived.push(result.viewpoint_id);
    if (event.action === "observe") {
      view.observation = result.observation;
      view.detection = null;
      view.rejection = null;
    }
    if (event.action === "detect_target") {
      view.detection = result;
      if (result.diagnostics?.image_decoded === true && view.current) view.observed.push(view.current);
    }
    if (event.action === "view_result") {
      view.statuses[event.input_ids[0]] = result.status;
      if (result.reason) view.rejection = result.reason;
    }
    if (event.action === "complete") view.finished = true;
  }
  return view;
}

function renderHistory(view) {
  const root = $("history-records");
  root.replaceChildren();
  text("object-name", state.data?.report?.object_id || "待登记目标");
  text("history-count", view.history.length + " 条历史");
  const confirmed = view.history.filter((record) => record.detection?.status === "FOUND");
  const latest = confirmed[confirmed.length - 1];
  text("history-location", latest ? "历史确认位置 " + latest.observation.viewpoint_id + " · 非当前确认" : "等待读取 SQLite 记忆");
  const reference = state.data?.registration?.evidence?.[0]?.observation;
  const url = reference && imageURL(reference.image_path);
  const image = $("reference-image");
  image.hidden = !url || !view.history.length;
  if (url && image.getAttribute("src") !== url) image.src = url;
  for (const record of view.history) {
    const row = element("div", "history-record");
    row.append(element("strong", null, "位置 " + record.observation.viewpoint_id + " · " + record.detection.status));
    row.append(element("span", null, record.observation.evidence_id));
    row.append(element("span", null, record.observation.captured_at + " / " + record.observation.timestamp_basis));
    root.append(row);
  }
}

function renderMap(view) {
  const views = state.data?.viewpoints || [{viewpoint_id: "A", name: "观察点 A"}, {viewpoint_id: "B", name: "观察点 B"}, {viewpoint_id: "C", name: "观察点 C"}];
  const map = $("map");
  map.replaceChildren();
  for (const point of views) {
    const id = point.viewpoint_id;
    const node = element("div", "map-node");
    node.classList.toggle("current", view.current === id);
    node.classList.toggle("done", Object.hasOwn(view.statuses, id));
    node.append(element("span", "node-circle", id));
    const info = element("div", "node-info");
    info.append(element("strong", null, point.name));
    info.append(element("small", null, view.observed.includes(id) ? "已成功解码图像" : view.arrived.includes(id) ? "已模拟到达" : view.attempted.includes(id) ? "已规划访问" : "候选观察点"));
    node.append(info);
    node.append(element("span", "node-state", view.statuses[id] || (view.current === id ? "处理中" : "待核验")));
    map.append(node);
  }
  text("attempted-count", view.attempted.length);
  text("arrived-count", view.arrived.length);
  text("observed-count", view.observed.length);
}

function renderBox() {
  const view = prefixState();
  const image = $("observation-image");
  const overlay = $("box-overlay");
  const box = view.detection?.bbox;
  overlay.replaceChildren();
  overlay.setAttribute("hidden", "");
  if (view.rejection || view.detection?.status !== "FOUND" || !Array.isArray(box) || box.length !== 4 || !box.every(Number.isFinite) || !image.complete || !image.naturalWidth || !image.naturalHeight) return;
  if (box[2] <= box[0] || box[3] <= box[1]) return;
  overlay.setAttribute("viewBox", `0 0 ${image.naturalWidth} ${image.naturalHeight}`);
  const rect = document.createElementNS("http://www.w3.org/2000/svg", "rect");
  for (const [key, value] of Object.entries({x: box[0], y: box[1], width: box[2] - box[0], height: box[3] - box[1], fill: "none", stroke: "#37e4b0", "stroke-width": 2.5, "vector-effect": "non-scaling-stroke"})) rect.setAttribute(key, value);
  overlay.append(rect);
  overlay.removeAttribute("hidden");
}

function renderObservation(view) {
  const observation = view.observation;
  const detection = view.detection;
  const url = observation && imageURL(observation.image_path);
  const image = $("observation-image");
  $("image-frame").hidden = !url;
  $("image-placeholder").hidden = !!url;
  $("image-label").hidden = !url;
  $("box-overlay").setAttribute("hidden", "");
  if (url && image.getAttribute("src") !== url) image.src = url;
  if (url) text("image-label", "记录图片 · 观察点 " + observation.viewpoint_id + (view.rejection ? " · 未接纳为新证据" : ""));
  let badge = detection?.status;
  let title = state.data ? "历史记忆已读取，等待开始核验" : "尚未开始搜索";
  let explanation = "历史记录用于选择地点，只有本轮通过校验的图像才能支持当前确认。";
  if (view.current) {
    title = "观察点 " + view.current + " · 等待当前图像";
    explanation = view.event?.action === "plan_next" ? explain(view.event.result.reason) : "此处导航为模拟操作，不代表机器人真实到达。";
  }
  if (observation) {
    title = "观察点 " + observation.viewpoint_id + " · 图像已读取";
    explanation = "图片预览不等于识别成功；等待核心解码与证据校验。";
  }
  if (detection) {
    title = "观察点 " + view.current + " · " + (statusNames[detection.status] || detection.status);
    explanation = explain(detection.diagnostics?.rejection || detection.diagnostics?.reason);
    if (detection.status === "SUSPECTED" || detection.status === "UNKNOWN") explanation += "；这不能证明物品不存在。";
  }
  if (view.rejection) {
    badge = "UNKNOWN";
    title = "观察点 " + view.current + " · 当前证据未获确认";
    explanation = explain(view.rejection);
  }
  statusBadge($("observation-status"), badge, state.data ? "核验中" : "待运行");
  text("observation-title", title);
  text("observation-explanation", explanation);
  const diagnostics = $("diagnostics");
  diagnostics.replaceChildren();
  diagnostics.hidden = !detection;
  if (detection) {
    const data = detection.diagnostics || {};
    for (const [label, value] of [["匹配点", data.good_matches], ["几何内点", data.inliers], ["PC 匹配", data.elapsed_ms == null ? null : data.elapsed_ms + " ms"]]) {
      if (value == null) continue;
      const chip = element("span", "diagnostic", label);
      chip.append(element("strong", null, value));
      diagnostics.append(chip);
    }
  }
  const fields = $("evidence-fields");
  fields.replaceChildren();
  text("evidence-short", observation?.evidence_id || "等待观测");
  if (observation) {
    const rows = [
      ["证据 ID", observation.evidence_id], ["图片路径", observation.image_path], ["SHA256", observation.image_hash],
      ["数据来源", observation.data_source], ["导航模式", state.data.report.navigation_mode], ["时间标签", observation.captured_at],
      ["时间依据", observation.timestamp_basis + (observation.timestamp_basis === "demo_sequence" ? "（演示顺序不代表原拍摄日期）" : "（操作者声明，未经硬件认证）")],
      ["匹配方法", detection?.matcher || "本步未执行 / 未接纳"], ["确认类型", detection?.verification_kind || "无当前确认"],
      ["检测框", detection?.bbox ? JSON.stringify(detection.bbox) + "（原图像素）" : "无可靠检测框"],
      ["采集说明", observation.capture_source], ["当前原因", view.rejection || detection?.diagnostics?.rejection || detection?.diagnostics?.reason || observation.error || "等待核验"],
    ];
    for (const [label, value] of rows) {fields.append(element("dt", null, label), element("dd", null, value ?? "—"));}
  }
  renderBox();
}

function eventDescription(event) {
  const result = event.result || {};
  switch (event.action) {
    case "query_memory": return ["读取持久记忆", (result.records || []).length + " 条历史；不是当前确认"];
    case "plan_next": return ["选择观察点 " + result.viewpoint_id, explain(result.reason)];
    case "navigate": return ["模拟导航 → " + result.viewpoint_id, result.status === "ARRIVED" ? "模拟到达 · 无真实机器人移动" : "模拟导航未到达"];
    case "observe": return ["读取当前照片", result.observation?.image_path || "无可用观察"];
    case "detect_target": return ["实际图像匹配 · " + result.status, explain(result.diagnostics?.rejection || result.diagnostics?.reason)];
    case "update_memory": return ["保存本轮证据", result.inserted ? "已写入 SQLite" : "未新增重复记录"];
    case "view_result": return ["本点结果 · " + result.status, result.reason ? explain(result.reason) : statusNames[result.status] || result.status];
    case "complete": return ["搜索完成 · " + result.result_status, result.location ? "确认位置 " + result.location : "位置未确认，不报告物品不存在"];
    default: return [event.action, "核心事件记录"];
  }
}

function renderTimeline(view) {
  const timeline = $("timeline");
  timeline.replaceChildren();
  const events = state.data?.report?.events || [];
  $("timeline-empty").hidden = events.length > 0 && state.cursor >= 0;
  text("strategy-label", strategies[state.data?.strategy || $("strategy").value] || "搜索策略");
  events.slice(0, state.cursor + 1).forEach((event, index) => {
    const row = element("li", index === state.cursor ? "current" : "");
    const button = element("button");
    const [title, detail] = eventDescription(event);
    const strong = element("strong");
    strong.append(element("span", "sequence", String(event.seq).padStart(2, "0")), document.createTextNode(title));
    button.append(strong, element("small", null, detail));
    button.addEventListener("click", () => {stop(); setCursor(index);});
    row.append(button);
    timeline.append(row);
  });
  timeline.scrollTop = timeline.scrollHeight;
}

function renderResult(view) {
  $("result-panel").hidden = !view.finished;
  $("comparison-panel").hidden = !view.finished;
  if (!view.finished) return;
  const report = state.data.report;
  const found = report.result_status === "FOUND";
  text("final-title", found ? "在 " + report.location + " 的照片中确认参考外观" : "本轮未能确认目标位置");
  text("final-description", found ? "确认来自本轮独立图像及几何匹配。它不证明实时在场，也不能区分完全相同外观的实体。" : "保留 " + report.result_status + "；当前证据不足以确认。这不意味着物品不存在。" );
  statusBadge($("final-status"), report.result_status);
  text("final-location", report.location || "未确认（null）");
  text("confirmed-evidence", (report.confirmed_evidence_ids || []).join(" · ") || "无");
  const downloads = $("downloads");
  downloads.replaceChildren();
  for (const [key, label] of [["report", "下载本轮报告 JSON"], ["events", "下载事件 JSONL"], ["comparison", "下载公平对照 JSON"]]) {
    const url = state.data.downloads?.[key];
    if (typeof url !== "string" || !url.startsWith("/api/runs/") || url.includes("..")) continue;
    const link = element("a", null, label + " ↓");
    link.href = url;
    link.setAttribute("download", "");
    downloads.append(link);
  }
  const table = $("comparison-body");
  table.replaceChildren();
  const rows = state.data.comparison?.rows || [];
  for (const result of rows) {
    const row = element("tr");
    const values = [strategies[result.strategy] || result.strategy, (result.attempted_viewpoints || []).join(" → "), result.attempted, result.arrived, result.observed, result.result_status + (result.location ? " / " + result.location : " / 未确认")];
    values.forEach((value) => row.append(element("td", null, value ?? "—")));
    table.append(row);
  }
  const equal = rows.length === 2 && rows[0].attempted === rows[1].attempted && rows[0].observed === rows[1].observed;
  text("comparison-note", equal ? "本例两种策略的尝试步数和有效解码次数相同，不据此宣称记忆策略更快或最优。导航耗时未测量。" : "以上为该组输入的实际计数，不代表一般场景性能优势。导航耗时未测量，不能推断机器人移动时间。");
  text("fairness", JSON.stringify(state.data.comparison?.fairness || {}, null, 2));
}

function renderControls() {
  const count = state.data?.report?.events?.length || 0;
  $("previous").disabled = !count || state.cursor < 0 || state.busy;
  $("next").disabled = !count || state.cursor >= count - 1 || state.busy;
  $("play").disabled = !count || state.busy;
  $("finish").disabled = !count || state.cursor >= count - 1 || state.busy;
  $("progress").disabled = !count || state.busy;
  $("progress").max = count;
  $("progress").value = state.cursor + 1;
  text("step-count", (state.cursor + 1) + " / " + count);
}
function render() {
  const view = prefixState();
  renderHistory(view);
  renderMap(view);
  renderObservation(view);
  renderTimeline(view);
  renderResult(view);
  renderControls();
  if (!state.data) text("session-id", "");
}

$("run").addEventListener("click", run);
document.querySelectorAll("[data-scenario]").forEach((button) => button.addEventListener("click", () => selectScenario(button.dataset.scenario)));
$("strategy").addEventListener("change", () => {if (!state.data) text("strategy-label", strategies[$("strategy").value]);});
$("previous").addEventListener("click", () => {stop(); setCursor(state.cursor - 1);});
$("next").addEventListener("click", () => {stop(); setCursor(state.cursor + 1);});
$("finish").addEventListener("click", () => {stop(); setCursor(state.data.report.events.length - 1);});
$("progress").addEventListener("input", () => {stop(); setCursor(Number($("progress").value) - 1);});
$("play").addEventListener("click", () => {
  if (state.timer !== null) {stop(); return;}
  startPlayback();
});
$("observation-image").addEventListener("load", renderBox);
$("observation-image").addEventListener("error", () => {
  $("image-frame").hidden = true;
  $("image-placeholder").hidden = false;
  $("image-label").hidden = true;
  text("observation-explanation", "证据图片暂时无法预览；请下载报告核对图像路径和原始状态。预览失败不改写核心报告。");
});
window.addEventListener("pagehide", stop);
render();
fetch("/api/config").then(async (response) => {
  if (!response.ok) throw new Error("本地服务配置读取失败。");
  const config = await response.json();
  if (config.source_notice) text("source-notice", config.source_notice);
}).catch((error) => {
  text("error", error.message + " 请确认通过 HomeTrace 本地服务打开页面。");
  $("error").hidden = false;
});
