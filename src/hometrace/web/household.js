"use strict";

(() => {
  const byId = (id) => document.getElementById(id);
  const storageKey = "hometrace.household.session_id";
  const pendingStates = new Set(["CLARIFY", "CONFIRM", "UNKNOWN_OBJECT"]);
  const stateNames = {CLARIFY: "请选择物品", CONFIRM: "等待确认保存", UNKNOWN_OBJECT: "物品尚未登记", COMPLETED: "操作完成", CANCELLED: "已取消"};
  let enabled = false;
  let busy = false;
  let session = null;

  function node(tag, text, className) {
    const element = document.createElement(tag);
    if (text !== undefined) element.textContent = String(text);
    if (className) element.className = className;
    return element;
  }

  function showError(message) {
    byId("error").textContent = message || "";
    byId("error").hidden = !message;
  }

  function rememberSession(id) {
    try {
      if (id) localStorage.setItem(storageKey, id);
      else localStorage.removeItem(storageKey);
    } catch (_) {
      byId("storage-notice").textContent = "浏览器未允许保存会话编号，刷新后可能无法自动恢复本次交互；已保存的服务器记忆不受影响。";
      byId("storage-notice").hidden = false;
    }
  }

  function storedSession() {
    try {
      const id = localStorage.getItem(storageKey);
      if (!id) return null;
      if (/^[0-9a-f]{32}$/.test(id)) return id;
      rememberSession(null);
    } catch (_) { rememberSession(null); }
    return null;
  }

  async function request(path, body) {
    let response;
    try {
      response = await fetch(path, {method: body === undefined ? "GET" : "POST", cache: "no-store", headers: body === undefined ? {} : {"Content-Type": "application/json"}, body: body === undefined ? undefined : JSON.stringify(body)});
    } catch (_) { throw new Error("无法连接本地服务。请确认服务仍在运行，再重新操作。"); }
    let data;
    try { data = await response.json(); }
    catch (_) { throw new Error("服务未返回有效结果，请检查服务状态。操作是否保存，请恢复会话后核实。"); }
    if (!response.ok) {
      const error = new Error(typeof data.error === "string" ? data.error : "操作未完成，请检查输入后重试。");
      error.status = response.status;
      throw error;
    }
    return data;
  }

  function selectedIntent() { return document.querySelector('input[name="intent"]:checked').value; }

  function updateControls() {
    const pending = session && pendingStates.has(session.state);
    document.querySelectorAll("#enroll-form input, #enroll-form button, #session-actions button, #catalog button").forEach((element) => { element.disabled = busy || !enabled; });
    document.querySelectorAll("#request-form input, #request-form select, #request-form button").forEach((element) => { element.disabled = busy || !enabled || Boolean(pending); });
    const remembering = selectedIntent() === "remember";
    byId("remember-fields").hidden = !remembering;
    byId("location").required = remembering;
    byId("start").textContent = busy ? "正在处理…" : remembering ? "继续确认" : "查询历史";
    byId("pending-notice").textContent = pending ? "请先处理或取消下方待完成交互，再开始新操作。" : remembering ? "记住位置前，还会请你确认一次。" : "返回历史线索，不会据此确认物品的当前位置。";
    document.body.setAttribute("aria-busy", String(busy));
  }

  async function operation(callback) {
    if (busy) return;
    busy = true;
    showError("");
    updateControls();
    try { await callback(); }
    catch (error) {
      if (error.status === 409 && session) {
        try {
          renderSession(await request(`/api/household/sessions/${session.session_id}`));
          showError("会话已在其他页面更新，已载入最新状态。请核对下方内容后再操作。");
        } catch (restoreError) { showError(restoreError.message); }
      } else { showError(error.message); }
    } finally { busy = false; updateControls(); }
  }

  function timeText(value) {
    if (!value) return "时间未提供";
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString("zh-CN", {year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit", timeZoneName: "short"});
  }

  function timeBasis(value) {
    return value === "session_creation_time" ? "服务接收请求时的本机时间" : value === "owner_supplied_timestamp" ? "主人填写的时间" : "主人陈述的时间";
  }

  function button(text, callback, className) {
    const result = node("button", text, className);
    result.type = "button";
    result.addEventListener("click", callback);
    return result;
  }

  async function loadCatalog() {
    const config = await request("/api/household");
    enabled = config.enabled === true;
    byId("service-notice").textContent = config.notice || "家庭工作区尚未启用。";
    const previousLocation = byId("location").value;
    byId("location").replaceChildren(node("option", "请选择地点"));
    byId("location").firstChild.value = "";
    (config.locations || []).forEach((location) => {
      const option = node("option", location.location_name);
      option.value = location.location_id;
      byId("location").append(option);
    });
    byId("location").value = previousLocation;
    const objects = config.catalog || [];
    byId("catalog-count").textContent = `${objects.length} 件`;
    byId("catalog").replaceChildren();
    if (!objects.length) byId("catalog").append(node("li", "还没有登记物品。先添加一个名称档案，再记住你说的位置。", "empty"));
    objects.forEach((object) => {
      const item = node("li", undefined, "object-card");
      item.append(node("strong", object.name), node("code", object.object_id), node("p", object.aliases.length ? `别名：${object.aliases.join("、")}` : "暂无别名"), node("p", "外观未登记 · 未视觉确认"));
      item.append(button("使用此物品", () => {
        if (session && pendingStates.has(session.state)) {
          showError("请先处理或取消待完成交互。目录选择不会改变正在确认的物品。");
          return;
        }
        byId("query").value = object.object_id;
        byId("query").focus();
      }));
      byId("catalog").append(item);
    });
    updateControls();
  }

  function act(action, objectId) {
    return operation(async () => {
      const payload = {session_id: session.session_id, version: session.version, action};
      if (objectId !== undefined) payload.object_id = objectId;
      renderSession(await request("/api/household/act", payload));
    });
  }

  function renderHistory(data) {
    byId("memory-panel").hidden = !data.selected_object || data.state !== "COMPLETED";
    const histories = data.history || [];
    const candidates = data.candidates || [];
    byId("history-count").textContent = `${histories.length} 条`;
    byId("candidates").replaceChildren();
    byId("history").replaceChildren();
    if (!candidates.length) byId("candidates").append(node("li", "尚无位置陈述，无法生成有来源的候选地点。", "empty"));
    candidates.forEach((candidate) => {
      const item = node("li", undefined, "candidate");
      const body = node("div");
      body.append(node("strong", candidate.location_name), node("p", `最近陈述：${timeText(candidate.latest_reported_at)}`), node("p", `共 ${candidate.report_count} 条主人陈述 · 按最近陈述排序 · 未视觉确认`));
      item.append(node("span", candidate.rank, "rank"), body);
      byId("candidates").append(item);
    });
    if (!histories.length) byId("history").append(node("li", "没有已保存的位置记录。", "empty"));
    histories.forEach((record) => {
      const item = node("li");
      const details = node("details");
      details.append(node("summary", "来源与原始时间"), node("p", `来源类型：主人陈述（${record.source_kind}）`), node("p", `来源记录：${record.source}`), node("p", `陈述时间：${record.reported_at}`), node("p", `时间来源：${timeBasis(record.reported_at_basis)}`), node("p", `保存时间：${record.recorded_at}`), node("p", `记录编号：${record.event_id}`));
      item.append(node("strong", record.location_name), node("p", `陈述时间：${timeText(record.reported_at)}`), node("p", "主人陈述 · 未视觉确认"), details);
      byId("history").append(item);
    });
  }

  function renderSession(data) {
    session = data;
    rememberSession(data.session_id);
    byId("session-state").textContent = stateNames[data.state] || "未知状态";
    byId("session-meta").textContent = `会话 ${data.session_id.slice(0, 8)} · 版本 ${data.version} · ${data.intent === "remember" ? "记住位置" : "查找历史"} · 未视觉确认`;
    byId("messages").replaceChildren();
    (data.messages || []).forEach((message) => {
      const item = node("li", undefined, message.role === "user" ? "message user" : "message");
      item.append(node("span", message.role === "user" ? "你的实际操作" : "本地程序回复", "speaker"), node("p", message.text));
      byId("messages").append(item);
    });
    const actions = byId("session-actions");
    actions.replaceChildren();
    if (data.state === "CLARIFY") {
      actions.append(node("p", "同名或别名对应多件物品，请按独立编号选择。"));
      const choices = node("div", undefined, "action-buttons");
      data.matches.forEach((object) => {
        const choice = button("", () => act("select", object.object_id), "choice");
        choice.append(node("span", object.name), node("small", object.object_id), node("small", object.aliases.length ? `别名：${object.aliases.join("、")}` : "暂无别名"));
        choices.append(choice);
      });
      actions.append(choices);
    } else if (data.state === "CONFIRM") {
      const card = node("div", undefined, "confirm-card");
      card.append(node("strong", `${data.selected_object.name} → ${data.location.location_name}`), node("p", `物品编号：${data.selected_object.object_id}`), node("p", `陈述时间：${timeText(data.reported_at)}（${timeBasis(data.reported_at_basis)}）`), node("p", "确认后只保存你陈述的位置，不表示系统已经看到该物品。"));
      actions.append(card);
    } else if (data.state === "UNKNOWN_OBJECT") {
      actions.append(node("p", `先在左侧登记“${data.query}”作为名称或别名，再重新查询；不会自动替换成其他物品。`));
      actions.append(button("填写登记名称", () => {
        byId("object-name").value = data.query;
        byId("object-id").focus();
        byId("enroll-form").scrollIntoView({behavior: "smooth", block: "center"});
      }, "secondary"));
    }
    if (pendingStates.has(data.state)) {
      const controls = node("div", undefined, "action-buttons");
      controls.style.marginTop = "14px";
      if (data.state === "CONFIRM") controls.append(button("确认保存位置", () => act("confirm"), "primary"));
      if (data.state === "UNKNOWN_OBJECT") controls.append(button("重新查询", () => act("retry"), "primary"));
      controls.append(button("取消本次操作", () => act("cancel")));
      actions.append(controls);
    }
    renderHistory(data);
    updateControls();
  }

  byId("enroll-form").addEventListener("submit", (event) => {
    event.preventDefault();
    operation(async () => {
      byId("enroll-status").textContent = "";
      const aliases = byId("object-aliases").value.split(/[,，]/).map((value) => value.trim()).filter(Boolean);
      const result = await request("/api/household/enroll", {object_id: byId("object-id").value.trim(), name: byId("object-name").value.trim(), aliases});
      byId("enroll-status").textContent = result.message;
      await loadCatalog();
    });
  });

  byId("request-form").addEventListener("submit", (event) => {
    event.preventDefault();
    operation(async () => {
      const intent = selectedIntent();
      const payload = {intent, query: byId("query").value.trim()};
      if (intent === "remember") {
        payload.location_id = byId("location").value;
        if (byId("reported-at").value.trim()) payload.reported_at = byId("reported-at").value.trim();
      }
      renderSession(await request("/api/household/start", payload));
    });
  });
  document.querySelectorAll('input[name="intent"]').forEach((element) => element.addEventListener("change", updateControls));

  operation(async () => {
    await loadCatalog();
    if (!enabled) return;
    const id = storedSession();
    if (!id) return;
    try { renderSession(await request(`/api/household/sessions/${id}`)); }
    catch (error) {
      if (error.status === 404) rememberSession(null);
      showError(`上次交互未能恢复：${error.message}`);
    }
  });
})();
