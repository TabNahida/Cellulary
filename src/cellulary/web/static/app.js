"use strict";

(() => {
  const $ = (id) => document.getElementById(id);
  const pages = {
    overview: ["设备总览", "查看连接的模块、SIM 卡和蜂窝网络状态。"],
    sms: ["短信", "读取模块中的消息，或通过选中的 SIM 卡发送短信。"],
    data: ["数据连接", "配置模块数据业务，管理主机移动宽带连接。"],
    calls: ["通话", "查看来电与活动通话，通过模块发起语音呼叫。"],
    events: ["事件与诊断", "查看设备状态变化、操作结果和连接问题。"],
  };
  const state = {
    token: null, devices: [], events: [], selected: null, page: "overview",
    network: null, usb: null, usbRequest: 0, scanning: false, polling: false, pageRequest: 0,
    pendingActions: new Set(), cachedLoaded: false,
  };

  // All module, SMS, and diagnostic strings are inserted as text, never HTML.
  function node(tag, className, text) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (text !== undefined && text !== null) element.textContent = String(text);
    return element;
  }
  function show(element, visible = true) { element.hidden = !visible; }
  function display(value, fallback = "未提供") {
    if (value === undefined || value === null || value === "") return fallback;
    if (typeof value === "object") return JSON.stringify(value);
    return String(value);
  }
  function textAt(id, value) { $(id).textContent = display(value, ""); }
  function selectedDevice() { return state.devices.find((device) => String(device.id) === state.selected); }
  function deviceLabel(device) { return display(device?.model, display(device?.description, "未识别模块")); }
  function isEc801e(device) { return /EC801E/i.test(deviceLabel(device)); }
  function endpoint(id, suffix) { return `/api/devices/${encodeURIComponent(id)}/${suffix}`; }
  function simInfo(device) {
    const raw = display(device?.sim_status, "未知");
    const status = raw.toUpperCase();
    if (["READY", "SIM READY", "+CPIN: READY"].includes(status)) return ["已就绪", "ready"];
    if (/NOT INSERTED|ABSENT|NO SIM|NOT PRESENT|未插|无卡/.test(status)) return ["未插卡", ""];
    if (/PIN|PUK|LOCK/.test(status)) return [status.includes("PUK") ? "需要 PUK" : status.includes("PIN") ? "需要 PIN" : "SIM 已锁定", "warning"];
    if (/ERROR|FAIL/.test(status)) return ["读取异常", "error"];
    return [raw, ""];
  }
  function registrationInfo(device) {
    const registration = device?.registration;
    let value = registration;
    if (registration && typeof registration === "object") {
      value = registration.stat ?? registration.status ?? registration.state ?? registration.registration;
      if (registration.registered === true && value === undefined) value = 1;
    }
    const raw = display(value, "未知");
    const normalized = raw.toLowerCase();
    if (["1", "registered", "home", "registered_home", "registered (home)", "已注册"].includes(normalized)) return ["已注册", "ready"];
    if (["5", "roaming", "registered_roaming", "registered (roaming)"].includes(normalized)) return ["漫游已注册", "ready"];
    if (["0", "not registered", "not_registered", "unregistered"].includes(normalized)) return ["未注册", ""];
    if (["2", "searching"].includes(normalized)) return ["正在搜网", "warning"];
    if (["3", "denied", "registration denied"].includes(normalized)) return ["注册被拒绝", "error"];
    if (["4", "unknown"].includes(normalized)) return ["未知", ""];
    return [raw, ""];
  }
  function badge(label, className = "") { return node("span", `badge ${className}`.trim(), label); }
  function signalView(device) {
    const signal = device?.signal ?? {};
    const rssi = Number(signal.rssi);
    const hasRssi = signal.rssi !== null && signal.rssi !== undefined && rssi >= 0 && rssi <= 31;
    let dbm = signal.dbm;
    if ((dbm === null || dbm === undefined) && hasRssi) dbm = -113 + rssi * 2;
    const valid = dbm !== null && dbm !== undefined && Number.isFinite(Number(dbm));
    const bars = valid ? (Number(dbm) >= -73 ? 4 : Number(dbm) >= -85 ? 3 : Number(dbm) >= -97 ? 2 : 1) : 0;
    const wrapper = node("span", "signal-value");
    const graph = node("span", "signal-bars");
    graph.setAttribute("aria-hidden", "true");
    for (let i = 1; i <= 4; i++) graph.append(node("i", i <= bars ? "filled" : ""));
    wrapper.append(graph, node("span", "", valid ? `${dbm} dBm` : "未知"));
    return wrapper;
  }
  function errorText(data, fallback) {
    if (typeof data?.detail === "string") return data.detail;
    if (Array.isArray(data?.detail)) return data.detail.map((item) => item.msg || display(item)).join("；");
    return display(data?.message || data?.error, fallback);
  }
  async function api(path, options = {}) {
    const method = options.method || "GET";
    const headers = { Accept: "application/json" };
    if (method !== "GET") {
      if (!state.token) throw new Error("会话尚未建立，请刷新页面后重试。");
      headers["X-Cellulary-Token"] = state.token;
      if (options.body !== undefined) headers["Content-Type"] = "application/json";
    }
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 90000);
    try {
      const response = await fetch(path, {
        method, headers, credentials: "same-origin", cache: "no-store",
        signal: controller.signal,
        ...(options.body !== undefined ? { body: JSON.stringify(options.body) } : {}),
      });
      const contentType = response.headers.get("content-type") || "";
      const data = contentType.includes("application/json") ? await response.json() : {};
      if (!response.ok) throw new Error(errorText(data, `请求失败（HTTP ${response.status}）`));
      return data;
    } catch (error) {
      if (error.name === "AbortError") throw new Error("请求超时。操作可能仍在模块上执行，请先刷新状态，避免重复提交。");
      if (error instanceof TypeError) throw new Error("无法连接本地服务，请确认 Cellulary 服务仍在运行。");
      throw error;
    } finally { clearTimeout(timeout); }
  }
  function globalError(message) {
    textAt("global-error", message);
    show($("global-error"), Boolean(message));
  }
  function announce(message) {
    textAt("operation-status", message);
    show($("operation-status"), Boolean(message));
  }
  function serviceState(online) {
    $("service-indicator").className = `connection-indicator ${online ? "online" : "offline"}`;
    textAt("service-state", online ? "本地服务已连接" : "本地服务连接中断");
  }
  function busy(button, active, label) {
    if (active) {
      if (!button.dataset.originalText) button.dataset.originalText = button.textContent;
      if (label) button.textContent = label;
      button.classList.add("loading");
      button.disabled = true;
      button.setAttribute("aria-busy", "true");
    } else {
      button.textContent = button.dataset.originalText || button.textContent;
      delete button.dataset.originalText;
      button.classList.remove("loading");
      button.disabled = false;
      button.removeAttribute("aria-busy");
    }
  }
  async function action(button, key, resultId, callback) {
    if (state.pendingActions.has(key)) return;
    state.pendingActions.add(key);
    const result = resultId ? $(resultId) : null;
    if (result) { result.textContent = ""; result.classList.remove("error"); }
    busy(button, true, "正在执行…");
    try {
      const message = await callback();
      if (result && message) result.textContent = message;
      else if (message) announce(message);
      await refreshCached(true);
    } catch (error) {
      if (result) { result.textContent = error.message; result.classList.add("error"); }
      else globalError(error.message);
    } finally {
      state.pendingActions.delete(key);
      busy(button, false);
    }
  }
  function resultMessage(result, fallback) {
    return display(result?.message ?? result?.detail, fallback);
  }
  function requireDevice() {
    const device = selectedDevice();
    if (!device) throw new Error("请先扫描并选择一个模块。");
    return device;
  }
  function setDevices(response) {
    const previousDevices = JSON.stringify(state.devices);
    const previousScanning = state.scanning;
    state.devices = Array.isArray(response.devices) ? response.devices : [];
    state.scanning = Boolean(response.scanning);
    state.cachedLoaded = true;
    const previousId = state.selected;
    if (!state.devices.some((device) => String(device.id) === state.selected)) {
      const first = state.devices.find((device) => simInfo(device)[1] === "ready") || state.devices[0];
      state.selected = first ? String(first.id) : null;
    }
    if (previousDevices !== JSON.stringify(state.devices) || previousScanning !== state.scanning || previousId !== state.selected) renderDevices();
    if (previousId !== state.selected) updatePage(true);
  }
  function renderDevices() {
    const devices = state.devices;
    const count = devices.length;
    ["nav-device-count", "sidebar-device-count", "table-count", "metric-total"].forEach((id) => textAt(id, count));
    textAt("metric-sim", devices.filter((device) => simInfo(device)[1] === "ready").length);
    textAt("metric-registered", devices.filter((device) => registrationInfo(device)[1] === "ready").length);
    textAt("metric-attention", devices.filter((device) => device.error || simInfo(device)[1] === "error" || registrationInfo(device)[1] === "error").length);
    const picker = $("device-picker");
    const tbody = $("device-table-body");
    const select = $("device-select");
    picker.replaceChildren(); tbody.replaceChildren(); select.replaceChildren();
    if (!count) {
      picker.append(node("p", "sidebar-empty", "尚未发现设备"));
      const option = node("option", "", "请选择模块"); option.value = ""; select.append(option);
    }
    for (const device of devices) {
      const id = String(device.id);
      const isSelected = id === state.selected;
      const [simLabel, simClass] = simInfo(device);
      const [registration, registrationClass] = registrationInfo(device);
      const option = node("button", `device-option${isSelected ? " selected" : ""}`);
      option.type = "button";
      option.setAttribute("aria-pressed", String(isSelected));
      const indicator = node("span", `status-dot ${device.error ? "error" : simClass}`);
      indicator.setAttribute("aria-hidden", "true");
      const optionLabel = node("span", "device-option-label");
      optionLabel.append(node("strong", "", deviceLabel(device)), node("small", "", display(device.port, id)));
      option.append(indicator, optionLabel);
      option.addEventListener("click", () => selectDevice(id));
      picker.append(option);
      const selectOption = node("option", "", `${deviceLabel(device)} · ${display(device.port, id)}`);
      selectOption.value = id; selectOption.selected = isSelected; select.append(selectOption);

      const row = node("tr", isSelected ? "selected" : "");
      const identity = node("td");
      identity.append(node("span", "device-name", deviceLabel(device)), node("span", "device-port", display(device.port, id)));
      if (device.error) identity.append(node("span", "device-error", display(device.error)));
      const sim = node("td"); sim.append(badge(simLabel, simClass));
      const operator = node("td", "", display(device.operator?.name ?? device.operator, "未获取"));
      const network = node("td"); network.append(badge(registration, registrationClass));
      const signal = node("td"); signal.append(signalView(device));
      const selection = node("td");
      const choose = node("button", "row-select", isSelected ? "✓" : "→");
      choose.type = "button";
      choose.setAttribute("aria-label", `选择 ${deviceLabel(device)} ${display(device.port, id)}`);
      choose.setAttribute("aria-pressed", String(isSelected));
      choose.addEventListener("click", () => selectDevice(id));
      selection.append(choose); row.append(identity, sim, operator, network, signal, selection); tbody.append(row);
    }
    show($("devices-empty"), !count);
    $("status-button").disabled = !state.selected || state.pendingActions.has("status");
    textAt("scan-status", state.scanning ? "正在扫描设备…" : count ? `${count} 个模块已识别` : "等待扫描");
    renderDetail(); renderDeviceContext();
  }
  function renderDetail() {
    const device = selectedDevice();
    const container = $("device-detail");
    container.replaceChildren();
    show($("quick-actions"), Boolean(device));
    if (!device) {
      textAt("detail-subtitle", "选择模块后显示设备信息。");
      container.append(node("p", "muted", "暂无选中的模块。")); return;
    }
    textAt("detail-subtitle", `${deviceLabel(device)} · ${display(device.port, device.id)}`);
    const list = node("dl", "detail-list");
    const fields = [
      ["制造商", device.manufacturer], ["模块型号", device.model],
      ["IMEI", device.imei], ["AT 接口", device.port],
      ["SIM 卡状态", simInfo(device)[0]], ["网络注册", registrationInfo(device)[0]],
      ["固件版本", device.firmware, true],
    ];
    for (const [label, value, full] of fields) {
      const group = node("div", full ? "full-span" : "");
      group.append(node("dt", "", label), node("dd", label === "IMEI" || label === "AT 接口" || label === "固件版本" ? "mono" : "", display(value)));
      list.append(group);
    }
    container.append(list);
    if (device.error) container.append(node("p", "form-result error", display(device.error)));
  }
  function renderDeviceContext() {
    const device = selectedDevice();
    show($("ec801e-voice-note"), Boolean(device && isEc801e(device)));
    if (!device) return;
    textAt("context-model", deviceLabel(device));
    textAt("context-port", device.port || device.id);
    const [label, status] = simInfo(device);
    textAt("context-sim", label); $("context-sim").className = `badge ${status}`;
    $("device-select").value = state.selected;
  }
  function selectDevice(id) {
    if (state.selected === id) return;
    state.selected = id;
    renderDevices();
    ["sms-result", "data-result", "usb-result", "call-result"].forEach((result) => textAt(result, ""));
    updatePage(true);
  }
  function setPage(page, updateHash = true) {
    if (!pages[page]) page = "overview";
    const changed = state.page !== page;
    state.page = page;
    if (updateHash) history.replaceState(null, "", `#${page}`);
    updatePage(changed);
  }
  function updatePage(load) {
    const page = state.page;
    const needsDevice = ["sms", "data", "calls"].includes(page);
    const available = Boolean(selectedDevice());
    textAt("page-title", pages[page][0]);
    textAt("breadcrumb-page", pages[page][0]);
    textAt("page-description", pages[page][1]);
    document.title = `${pages[page][0]} · Cellulary`;
    for (const name of Object.keys(pages)) show($(`page-${name}`), name === page && (!needsDevice || available));
    document.querySelectorAll(".navigation [data-page]").forEach((button) => {
      const active = button.dataset.page === page;
      button.classList.toggle("active", active);
      if (active) button.setAttribute("aria-current", "page");
      else button.removeAttribute("aria-current");
    });
    show($("device-context"), needsDevice && available);
    show($("selection-empty"), needsDevice && !available);
    if (load) {
      state.pageRequest++;
      if (needsDevice && available) loadPageData();
      if (page === "events") renderEvents();
    }
  }
  async function refreshCached(silent = false) {
    const results = await Promise.allSettled([api("/api/devices"), api("/api/events")]);
    if (results[0].status === "fulfilled") {
      setDevices(results[0].value); serviceState(true);
      textAt("last-updated", `更新于 ${new Date().toLocaleTimeString("zh-CN", { hour12: false })}`);
      if (!silent) globalError("");
    } else {
      serviceState(false);
      if (!silent) globalError(results[0].reason.message);
    }
    if (results[1].status === "fulfilled") {
      state.events = Array.isArray(results[1].value.events) ? results[1].value.events : [];
      renderEvents();
    } else if (!silent && state.page === "events") globalError(results[1].reason.message);
  }
  async function discover() {
    if (state.pendingActions.has("discover")) return;
    state.pendingActions.add("discover");
    globalError("");
    busy($("discover-button"), true, "扫描中…");
    busy($("empty-discover-button"), true, "扫描中…");
    textAt("scan-status", "正在扫描设备，可能需要一些时间…");
    announce("正在检查可用的模块 AT 接口，请稍候。");
    try {
      const result = await api("/api/discover", { method: "POST" });
      setDevices(result);
      announce(result.scanning ? "设备扫描已开始，结果将自动更新。" : `扫描完成，发现 ${state.devices.length} 个模块。`);
      await refreshCached(true);
    } catch (error) { globalError(error.message); announce(""); }
    finally {
      state.pendingActions.delete("discover");
      busy($("discover-button"), false); busy($("empty-discover-button"), false);
    }
  }
  async function refreshStatus() {
    await action($("status-button"), "status", null, async () => {
      const device = requireDevice();
      const result = await api(endpoint(device.id, "status"));
      const fresh = result.device ?? result;
      state.devices = state.devices.map((item) => String(item.id) === String(device.id) ? { ...item, ...fresh, id: item.id } : item);
      renderDevices();
      return `${deviceLabel(device)} ${display(device.port, "")} 的状态已更新。`;
    });
  }
  function inlineMessage(containerId, text, isError = false) {
    $(containerId).replaceChildren(node("p", isError ? "empty-inline form-result error" : "empty-inline", text));
  }
  async function readDeviceData(kind, explicit = false) {
    const device = selectedDevice();
    if (!device) return;
    const id = String(device.id);
    const version = state.pageRequest;
    const config = {
      sms: ["sms-inbox", "sms-refresh", "正在读取短信…", renderSms],
      data: ["data-contexts", "data-refresh", "正在读取数据上下文…", renderData],
      calls: ["call-list", "calls-refresh", "正在读取通话状态…", renderCalls],
    }[kind];
    const [containerId, buttonId, loading, render] = config;
    const requestKey = `read-${kind}-${id}-${version}`;
    if (state.pendingActions.has(requestKey)) return;
    state.pendingActions.add(requestKey);
    const button = $(buttonId);
    busy(button, true, "读取中…");
    inlineMessage(containerId, loading);
    const isCurrent = () => state.selected === id && state.page === kind && version === state.pageRequest;
    try {
      const result = await api(endpoint(id, kind));
      if (isCurrent()) render(result);
    } catch (error) { if (isCurrent()) inlineMessage(containerId, error.message, true); }
    finally {
      state.pendingActions.delete(requestKey);
      // A request for another selected device may now own this button.
      if (!Array.from(state.pendingActions).some((key) => key.startsWith(`read-${kind}-`))) busy(button, false);
    }
  }
  async function loadPageData() {
    const page = state.page;
    if (page === "sms") {
      textAt("sms-count", 0);
      inlineMessage("sms-inbox", "点击“读取短信”查看当前模块中的消息。");
    } else if (["data", "calls"].includes(page)) {
      const requests = [readDeviceData(page)];
      if (page === "data") requests.push(readHostNetwork(), readUsbData());
      await Promise.allSettled(requests);
    }
  }
  function formatTime(value, date = false) {
    if (!value) return "时间未知";
    const parsed = new Date(value);
    if (!Number.isFinite(parsed.getTime())) return String(value);
    return date ? parsed.toLocaleString("zh-CN", { hour12: false }) : parsed.toLocaleTimeString("zh-CN", { hour12: false });
  }
  function renderSms(data) {
    const messages = Array.isArray(data.messages) ? data.messages : [];
    textAt("sms-count", messages.length);
    const inbox = $("sms-inbox"); inbox.replaceChildren();
    if (!messages.length) { inlineMessage("sms-inbox", "模块中暂无短信。"); return; }
    for (const message of messages) {
      const article = node("article", "sms-message");
      const header = node("div", "sms-message-header");
      header.append(node("strong", "", display(message.number ?? message.sender ?? message.address, "未知号码")), node("time", "", formatTime(message.timestamp, true)));
      const statuses = { 0: "未读", 1: "已读", 2: "待发送", 3: "已发送", "REC UNREAD": "未读", "REC READ": "已读", "STO UNSENT": "待发送", "STO SENT": "已发送" };
      const status = statuses[message.status] || display(message.status, "");
      article.append(header, node("p", "", display(message.text ?? message.body, "空消息")), node("small", "", `${status}${message.index !== undefined ? ` · 存储索引 ${message.index}` : ""}`));
      if (message.complete === false) article.append(node("p", "form-result error", Array.isArray(message.missing_parts) && message.missing_parts.length ? `长短信尚不完整，缺少第 ${message.missing_parts.join("、")} 段。` : "长短信分段无法可靠合并，当前显示单个分段。"));
      if (message.error || message.decode_error) article.append(node("p", "form-result error", `短信解析失败：${display(message.error ?? message.decode_error)}`));
      inbox.append(article);
    }
  }
  async function sendSms(event) {
    event.preventDefault();
    if (!event.currentTarget.reportValidity()) return;
    const button = event.currentTarget.querySelector('[type="submit"]');
    const number = $("sms-number").value.trim();
    const text = $("sms-text").value;
    if (!text.trim()) { $("sms-text").setCustomValidity("请输入短信内容。"); $("sms-text").reportValidity(); return; }
    await action(button, "send-sms", "sms-result", async () => {
      const device = requireDevice();
      const result = await api(endpoint(device.id, "sms"), { method: "POST", body: { number, text } });
      if (state.selected === String(device.id) && $("sms-text").value === text) { $("sms-text").value = ""; updateCharacterCount(); }
      return resultMessage(result, `短信已由 ${display(device.port, deviceLabel(device))} 提交至 ${number}。`);
    });
  }
  function updateCharacterCount() {
    $("sms-text").setCustomValidity("");
    textAt("sms-character-count", `${Array.from($("sms-text").value).length} 个字符`);
  }
  function renderData(data) {
    const contexts = Array.isArray(data.contexts) ? data.contexts : [];
    const container = $("data-contexts"); container.replaceChildren();
    const list = node("div", "context-list");
    if (data.attached !== undefined && data.attached !== null) list.append(node("p", "field-note", `分组数据附着：${data.attached ? "已附着" : "未附着"}`));
    if (!contexts.length) list.append(node("p", "field-note", "模块未返回已配置的数据上下文。"));
    for (const context of contexts) {
      const row = node("div", "data-context-row");
      const main = node("div");
      main.append(node("strong", "", `CID ${display(context.cid ?? context.context_id ?? context.id, "?")} · ${display(context.apn, "未提供 APN")}`));
      main.append(node("small", "", [display(context.pdp_type ?? context.type, ""), display(context.address ?? context.ip, "")].filter(Boolean).join(" · ") || "暂无地址信息"));
      const active = context.active === true || context.active === 1 || context.active === "1";
      const known = context.active !== undefined && context.active !== null;
      row.append(main, badge(known ? (active ? "已激活" : "未激活") : "状态未知", active ? "ready" : ""));
      list.append(row);
    }
    for (const error of Array.isArray(data.errors) ? data.errors : []) list.append(node("p", "form-result error", typeof error === "string" ? error : `${display(error.command, "数据查询")}：${display(error.error, "查询失败")}`));
    container.append(list);
  }
  function cidValue() {
    const input = $("data-cid");
    if (!input.reportValidity()) throw new Error("CID 应为 1 至 16 之间的整数。");
    return Number(input.value);
  }
  async function configureApn(event) {
    event.preventDefault();
    if (!event.currentTarget.reportValidity()) return;
    const button = event.currentTarget.querySelector('[type="submit"]');
    await action(button, "apn", "data-result", async () => {
      const device = requireDevice();
      const body = { apn: $("data-apn").value.trim(), cid: cidValue() };
      const result = await api(endpoint(device.id, "data/configure"), { method: "POST", body });
      if (state.selected === String(device.id) && state.page === "data") await readDeviceData("data");
      return resultMessage(result, `CID ${body.cid} 的 APN 已保存为 ${body.apn}。`);
    });
  }
  async function dataAction(active) {
    const button = $(active ? "data-activate" : "data-deactivate");
    await action(button, "data-operation", "data-result", async () => {
      const device = requireDevice();
      const cid = cidValue();
      const result = await api(endpoint(device.id, active ? "data/activate" : "data/deactivate"), { method: "POST", body: { cid } });
      if (state.selected === String(device.id) && state.page === "data") await readDeviceData("data");
      return resultMessage(result, `CID ${cid} ${active ? "已激活" : "已停用"}。`);
    });
  }
  function renderUsbControls() {
    const device = selectedDevice();
    const supported = Boolean(device && isEc801e(device) && state.usb?.deviceId === String(device.id) && state.usb?.supported === true);
    const pending = state.pendingActions.has("usb-operation") || state.pendingActions.has("read-usb");
    $("usb-connect").disabled = !supported || pending;
    $("usb-disconnect").disabled = !supported || pending;
    $("usb-refresh").disabled = !device || !isEc801e(device) || pending;
  }
  function renderUsbData(data) {
    const container = $("usb-status");
    container.replaceChildren();
    if (!data.supported) {
      container.append(badge("当前固件不支持", "warning"));
      if (data.reason) container.append(node("p", "form-result error", display(data.reason)));
      return;
    }
    const known = typeof data.connected === "boolean";
    container.append(badge(known ? (data.connected ? "模块报告已连接" : "模块报告未连接") : "连接状态未知", data.connected === true ? "ready" : ""));
    const cid = data.context_id ?? data.cid;
    if (cid !== undefined && cid !== null) container.append(node("span", "mono", `当前 CID ${cid}`));
  }
  async function readUsbData() {
    const device = selectedDevice();
    const sequence = ++state.usbRequest;
    const version = state.pageRequest;
    state.usb = null;
    textAt("usb-result", "");
    if (!device || !isEc801e(device)) {
      state.pendingActions.delete("read-usb");
      if ($("usb-refresh").getAttribute("aria-busy") === "true") busy($("usb-refresh"), false);
      $("usb-status").replaceChildren(badge("此模块使用系统移动宽带", ""));
      textAt("usb-note", "USB RNDIS / ECM 拨号接口当前仅支持 EC801E。EC200A 请使用“主机移动宽带”中的 Windows 接口与配置文件。");
      renderUsbControls();
      return;
    }
    const id = String(device.id);
    textAt("usb-note", "通过 EC801E 现有 RNDIS / ECM USB 网卡拨号，使用上方 CID。Windows 网卡需通过 DHCP 获取地址；此操作不修改模块 USB 模式。");
    state.pendingActions.add("read-usb");
    busy($("usb-refresh"), true, "读取中…");
    $("usb-status").replaceChildren(badge("正在查询…", ""));
    renderUsbControls();
    const isCurrent = () => state.selected === id && state.page === "data" && version === state.pageRequest && sequence === state.usbRequest;
    try {
      const result = await api(endpoint(id, "data/usb"));
      if (isCurrent()) {
        state.usb = { ...result, deviceId: id };
        renderUsbData(result);
      }
    } catch (error) {
      if (isCurrent()) {
        $("usb-status").replaceChildren(badge("无法确认拨号能力", "error"));
        const detail = node("p", "form-result error", error.message);
        $("usb-status").append(detail);
      }
    } finally {
      if (sequence === state.usbRequest) {
        state.pendingActions.delete("read-usb");
        busy($("usb-refresh"), false);
        renderUsbControls();
      }
    }
  }
  async function usbAction(connect) {
    const button = $(connect ? "usb-connect" : "usb-disconnect");
    await action(button, "usb-operation", "usb-result", async () => {
      const device = requireDevice();
      if (!isEc801e(device) || state.usb?.deviceId !== String(device.id) || state.usb?.supported !== true) throw new Error("请先成功查询该 EC801E 的 USB 拨号状态，确认固件支持后再操作。");
      renderUsbControls();
      const cid = cidValue();
      if (cid > 15) throw new Error("EC801E USB 拨号仅支持 CID 1 至 15，请修改上方的上下文 CID。");
      const result = await api(endpoint(device.id, `data/usb/${connect ? "connect" : "disconnect"}`), { method: "POST", body: { cid } });
      if (state.selected === String(device.id) && state.page === "data") await readUsbData();
      return resultMessage(result, `${display(device.port, deviceLabel(device))}：已提交 USB ${connect ? "启动" : "停止"}拨号请求${connect ? "，请确认 Windows 网卡已通过 DHCP 获取地址" : ""}。`);
    });
    renderUsbControls();
  }
  function interfaceName(item) { return typeof item === "string" ? item : display(item.name ?? item.interface ?? item.id, ""); }
  function profileName(item) { return typeof item === "string" ? item : display(item.name ?? item.profile ?? item.id, ""); }
  function renderHostProfiles() {
    const profile = $("host-profile");
    const previous = profile.value;
    profile.replaceChildren();
    const defaultOption = node("option", "", "请选择连接配置文件"); defaultOption.value = ""; profile.append(defaultOption);
    const network = state.network || {};
    const selectedInterface = $("host-interface").value;
    const interfaceObject = (network.interfaces || []).find((item) => interfaceName(item) === selectedInterface);
    const profiles = Array.isArray(interfaceObject?.profiles) ? interfaceObject.profiles : Array.isArray(network.profiles) ? network.profiles : [];
    for (const item of profiles) {
      if (item.interface && item.interface !== selectedInterface) continue;
      const name = profileName(item);
      if (!name) continue;
      const option = node("option", "", name); option.value = name; profile.append(option);
    }
    if (previous && Array.from(profile.options).some((item) => item.value === previous)) profile.value = previous;
    else if (profile.options.length === 2) profile.selectedIndex = 1;
    $("host-connect").disabled = profile.options.length < 2 || !selectedInterface;
    if (profile.options.length < 2) defaultOption.textContent = "无可用配置，请先在系统中配置";
  }
  function renderHostNetwork(data) {
    state.network = data;
    const interfaces = Array.isArray(data.interfaces) ? data.interfaces : [];
    const summary = $("host-network-summary"); summary.replaceChildren();
    const platform = display(data.platform, "当前系统");
    const reported = data.message ?? data.note ?? data.error;
    summary.append(node("p", "", reported ? display(reported) : `${platform} · ${interfaces.length} 个移动宽带接口`));
    for (const error of Array.isArray(data.errors) ? data.errors : []) summary.append(node("p", "form-result error", display(error)));
    const selector = $("host-interface");
    const previous = selector.value;
    selector.replaceChildren();
    const placeholder = node("option", "", interfaces.length ? "请选择系统接口" : "未发现移动宽带接口");
    placeholder.value = ""; selector.append(placeholder);
    for (const item of interfaces) {
      const name = interfaceName(item);
      if (!name) continue;
      const option = node("option", "", name); option.value = name; selector.append(option);
      const row = node("div", "host-interface-item");
      const label = node("span", "", name);
      if (item.description) label.append(node("small", "", ` · ${display(item.description)}`));
      const rawState = display(item.state ?? item.status, "状态未知");
      const connected = /^(connected|已连接|已连接。)$/i.test(rawState);
      row.append(label, badge(rawState, connected ? "ready" : "")); summary.append(row);
    }
    if (interfaces.some((item) => interfaceName(item) === previous)) selector.value = previous;
    else if (interfaces.length === 1) selector.value = interfaceName(interfaces[0]);
    $("host-connect").disabled = !interfaces.length;
    $("host-disconnect").disabled = !interfaces.length;
    if (!interfaces.length) summary.append(node("p", "", "请确认模块以系统支持的移动宽带模式枚举。AT 数据上下文状态与主机联网状态分别显示。"));
    renderHostProfiles();
  }
  async function readHostNetwork() {
    if (state.pendingActions.has("read-host")) return;
    state.pendingActions.add("read-host");
    busy($("host-refresh"), true, "读取中…");
    try { renderHostNetwork(await api("/api/host/network")); }
    catch (error) {
      inlineMessage("host-network-summary", error.message, true);
      $("host-connect").disabled = true; $("host-disconnect").disabled = true;
    } finally {
      state.pendingActions.delete("read-host"); busy($("host-refresh"), false);
    }
  }
  async function hostAction(connect, event) {
    if (event) event.preventDefault();
    if (!$("host-interface").reportValidity()) return;
    if (connect && !$("host-profile").reportValidity()) return;
    const button = $(connect ? "host-connect" : "host-disconnect");
    await action(button, "host-operation", "host-result", async () => {
      const body = { interface: $("host-interface").value };
      if (connect && $("host-profile").value) body.profile = $("host-profile").value;
      const result = await api(`/api/host/network/${connect ? "connect" : "disconnect"}`, { method: "POST", body });
      await readHostNetwork();
      return resultMessage(result, `${body.interface} 的${connect ? "连接" : "断开"}请求已完成。`);
    });
  }
  function renderCalls(data) {
    const calls = Array.isArray(data.calls) ? data.calls : [];
    const list = $("call-list"); list.replaceChildren();
    if (!calls.length) { inlineMessage("call-list", "当前没有活动通话。"); return; }
    const states = { 0: "通话中", 1: "保持中", 2: "拨号中", 3: "对方振铃", 4: "来电", 5: "等待中", active: "通话中", held: "保持中", dialing: "拨号中", alerting: "对方振铃", incoming: "来电", waiting: "等待中" };
    for (const call of calls) {
      const row = node("div", "call-item");
      const main = node("div");
      main.append(node("strong", "", display(call.number, "未知号码")));
      const direction = call.direction ?? call.dir;
      main.append(node("small", "", `${direction === 1 || direction === "incoming" ? "呼入" : direction === 0 || direction === "outgoing" ? "呼出" : "通话"} · ${display(call.id ?? call.index, "无索引")}`));
      const status = call.status ?? call.state ?? call.stat;
      row.append(main, badge(states[status] ?? display(status, "状态未知"), "ready"));
      list.append(row);
    }
  }
  async function callAction(operation, event) {
    if (event) {
      event.preventDefault();
      if (!event.currentTarget.reportValidity()) return;
    }
    const button = operation === "dial" ? $("dial-form").querySelector('[type="submit"]') : $(`call-${operation}`);
    await action(button, "call-operation", "call-result", async () => {
      const device = requireDevice();
      const options = { method: "POST" };
      if (operation === "dial") options.body = { number: $("call-number").value.trim() };
      const result = await api(endpoint(device.id, `calls/${operation}`), options);
      if (state.selected === String(device.id) && state.page === "calls") await readDeviceData("calls");
      const messages = { dial: "拨号请求已提交。", answer: "接听请求已提交。", hangup: "挂断请求已提交。" };
      return resultMessage(result, `${display(device.port, deviceLabel(device))}：${messages[operation]}`);
    });
  }
  function eventLevel(event) {
    const raw = display(event.level, "info").toLowerCase();
    return raw === "warn" ? "warning" : raw === "critical" ? "error" : raw;
  }
  function sortedEvents() {
    return [...state.events].sort((a, b) => (Date.parse(b.time ?? b.timestamp) || 0) - (Date.parse(a.time ?? a.timestamp) || 0));
  }
  function eventDevice(id) {
    if (id === undefined || id === null || id === "") return "系统";
    const device = state.devices.find((item) => String(item.id) === String(id));
    return device ? display(device.port, deviceLabel(device)) : String(id);
  }
  function renderEvents() {
    const events = sortedEvents();
    const recent = $("recent-events"); recent.replaceChildren();
    if (!events.length) recent.append(node("p", "empty-inline", "暂无事件。扫描设备后将显示运行记录。"));
    for (const event of events.slice(0, 4)) {
      const row = node("div", "event-item");
      const dot = node("span", `status-dot ${eventLevel(event) === "error" ? "error" : "ready"}`); dot.setAttribute("aria-hidden", "true");
      const content = node("div");
      content.append(node("p", "", display(event.message, "无事件说明")), node("small", "", eventDevice(event.device_id)));
      row.append(dot, content, node("time", "", formatTime(event.time ?? event.timestamp))); recent.append(row);
    }
    const filter = $("event-filter").value;
    const filtered = events.filter((event) => filter === "all" || eventLevel(event) === filter);
    const table = $("events-body"); table.replaceChildren();
    for (const event of filtered) {
      const row = node("tr");
      const level = eventLevel(event);
      const severity = node("td"); severity.append(badge({ info: "信息", warning: "警告", error: "错误", debug: "调试" }[level] || level, level === "error" || level === "warning" ? level : ""));
      row.append(node("td", "", formatTime(event.time ?? event.timestamp, true)), severity, node("td", "", eventDevice(event.device_id)), node("td", "", display(event.message, "无事件说明"))); table.append(row);
    }
    show($("events-empty"), !filtered.length);
    textAt("events-empty", filter === "all" ? "暂无事件。扫描设备后，运行记录将显示在这里。" : "当前等级没有事件。");
  }
  async function refreshEvents() {
    busy($("events-refresh"), true, "刷新中…");
    try {
      const result = await api("/api/events"); state.events = Array.isArray(result.events) ? result.events : []; renderEvents();
    } catch (error) { globalError(error.message); }
    finally { busy($("events-refresh"), false); }
  }
  async function poll() {
    if (document.hidden || state.polling || state.pendingActions.has("discover")) return;
    state.polling = true;
    try { await refreshCached(true); }
    finally { state.polling = false; }
  }
  function bindEvents() {
    document.querySelectorAll("[data-page]").forEach((button) => button.addEventListener("click", () => setPage(button.dataset.page)));
    window.addEventListener("hashchange", () => setPage(location.hash.slice(1), false));
    $("discover-button").addEventListener("click", discover);
    $("empty-discover-button").addEventListener("click", discover);
    $("status-button").addEventListener("click", refreshStatus);
    $("device-select").addEventListener("change", (event) => selectDevice(event.target.value));
    $("sms-form").addEventListener("submit", sendSms);
    $("sms-text").addEventListener("input", updateCharacterCount);
    $("sms-refresh").addEventListener("click", () => readDeviceData("sms", true));
    $("data-refresh").addEventListener("click", () => Promise.allSettled([readDeviceData("data", true), readUsbData()]));
    $("calls-refresh").addEventListener("click", () => readDeviceData("calls", true));
    $("apn-form").addEventListener("submit", configureApn);
    $("data-activate").addEventListener("click", () => dataAction(true));
    $("data-deactivate").addEventListener("click", () => dataAction(false));
    $("usb-refresh").addEventListener("click", readUsbData);
    $("usb-connect").addEventListener("click", () => usbAction(true));
    $("usb-disconnect").addEventListener("click", () => usbAction(false));
    $("host-refresh").addEventListener("click", readHostNetwork);
    $("host-interface").addEventListener("change", renderHostProfiles);
    $("host-connect-form").addEventListener("submit", (event) => hostAction(true, event));
    $("host-disconnect").addEventListener("click", () => hostAction(false));
    $("dial-form").addEventListener("submit", (event) => callAction("dial", event));
    $("call-answer").addEventListener("click", () => callAction("answer"));
    $("call-hangup").addEventListener("click", () => callAction("hangup"));
    $("events-refresh").addEventListener("click", refreshEvents);
    $("event-filter").addEventListener("change", renderEvents);
  }
  async function start() {
    bindEvents();
    setPage(location.hash.slice(1) || "overview", false);
    busy($("discover-button"), true, "连接中…");
    $("empty-discover-button").disabled = true;
    try {
      const session = await api("/api/session");
      state.token = session.token;
      textAt("app-version", `本地运行${session.version ? ` · ${session.version}` : ""}`);
      show($("demo-banner"), session.mode === "demo");
      textAt("footer-mode", session.mode === "demo" ? "演示模式 · 模拟设备与操作" : "所有操作由本机服务执行");
      serviceState(true);
      await refreshCached();
    } catch (error) { serviceState(false); globalError(error.message); }
    finally {
      busy($("discover-button"), false);
      $("discover-button").disabled = !state.token;
      $("empty-discover-button").disabled = !state.token;
    }
    setInterval(poll, 8000);
    document.addEventListener("visibilitychange", () => { if (!document.hidden) poll(); });
  }
  start();
})();
