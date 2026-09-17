"use strict";
(() => {
  const $ = (id) => document.getElementById(id);
  const staticEnglish = {};
  document.querySelectorAll("[data-i18n]").forEach((e) => { staticEnglish[e.dataset.i18n] = e.textContent; });
  document.querySelectorAll("[data-i18n-placeholder]").forEach((e) => { staticEnglish[e.dataset.i18nPlaceholder] = e.placeholder; });
  document.querySelectorAll("[data-i18n-aria]").forEach((e) => { staticEnglish[e.dataset.i18nAria] = e.getAttribute("aria-label"); });
  const translations = window.CellularyText;
  const pageKeys = {overview:"overview",sms:"sms",data:"network",calls:"calls",gnss:"gnss",events:"events"};
  const state = {language:document.documentElement.lang === "zh-CN" ? "zh" : "en",theme:document.documentElement.dataset.theme || "system",token:null,version:"",online:null,devices:[],selected:null,events:[],page:"overview",caches:new Map(),host:null,mutating:false,scanning:false,polling:false,notice:null,serviceError:null,updated:null,selectionSignature:""};
  function t(key,args={}) {
    const value = translations.dynamic[key]?.[state.language === "zh" ? 1 : 0] ?? (state.language === "zh" ? translations.zh[key] : null) ?? staticEnglish[key] ?? key;
    return value.replace(/\{(\w+)\}/g, (_, name) => String(args[name] ?? ""));
  }
  const locale = () => state.language === "zh" ? "zh-CN" : "en-GB";
  const show = (element,value=true) => { element.hidden = !value; };
  const text = (id,value) => { $(id).textContent = value ?? ""; };
  const display = (value,fallback=t("notReported")) => value == null || value === "" ? fallback : typeof value === "object" ? JSON.stringify(value) : String(value);
  // Untrusted SMS, modem and network strings are always rendered with textContent.
  function el(tag,className="",value) { const element=document.createElement(tag);if(className)element.className=className;if(value!==undefined)element.textContent=String(value);return element; }
  const badge = (value,kind="") => el("span",`badge ${kind}`,value);
  const current = () => state.devices.find((device) => String(device.id) === state.selected);
  const name = (device) => display(device?.model,display(device?.description,t("device")));
  const port = (device) => display(device?.port,display(device?.id,""));
  const route = (id,path) => `/api/devices/${encodeURIComponent(id)}/${path}`;
  function cache(id=state.selected) { if(!state.caches.has(id))state.caches.set(id,{});return state.caches.get(id); }
  const resource = (kind) => cache()[kind];
  function persist(key,value) { try { localStorage.setItem(`cellulary.${key}`,value); } catch { /* Optional storage. */ } }
  function sim(device) {
    const raw=String(device?.sim_status ?? "").toUpperCase();
    if(["READY","SIM READY","+CPIN: READY"].includes(raw))return {key:"ready",kind:"ready"};
    if(/ABSENT|NOT INSERTED|NOT PRESENT|NO SIM|未插|无卡/.test(raw))return {key:"absent",kind:""};
    if(/PUK/.test(raw))return {key:"puk",kind:"warning"};
    if(/PIN/.test(raw))return {key:"pin",kind:"warning"};
    if(/LOCK/.test(raw))return {key:"locked",kind:"warning"};
    if(/FAIL|ERROR/.test(raw))return {key:"simError",kind:"error"};
    return {key:"unknown",kind:""};
  }
  function registration(device) {
    const input=device?.registration;
    const raw=String(typeof input === "object" && input ? input.status ?? input.stat ?? (input.registered ? input.roaming ? 5 : 1 : "") : input ?? "").toLowerCase();
    if(["1","registered","home","registered_home"].includes(raw))return {key:"registered",kind:"ready"};
    if(["5","roaming","registered_roaming"].includes(raw))return {key:"roaming",kind:"ready"};
    if(["0","not_registered","not registered","unregistered"].includes(raw))return {key:"notRegistered",kind:""};
    if(["2","searching"].includes(raw))return {key:"searching",kind:"warning"};
    if(["3","denied"].includes(raw))return {key:"denied",kind:"error"};
    return {key:"unknown",kind:""};
  }
  function phone(device) {
    const status=sim(device),numbers=Array.isArray(device?.numbers)?device.numbers:[];
    const value=device?.phone_number || numbers.map((item)=>typeof item === "string"?item:item.number).filter(Boolean).join(" / ");
    if(status.key === "absent")return {value:t("absent"),help:t("numberAbsentHelp"),present:false};
    if(value)return {value:String(value),help:t("numberFromSim",{source:device.number_source || "CNUM"}),present:true};
    const reason=device?.number_reason_code;
    if(reason === "number_not_stored")return {value:t("numberNotStored"),help:t("numberMissingHelp"),present:false};
    if(reason === "sim_not_ready" || ["pin","puk","locked"].includes(status.key))return {value:t("numberUnavailable"),help:t("numberLockedHelp"),present:false};
    return {value:t("numberUnavailable"),help:t(reason === "number_query_failed"?"numberQueryHelp":"numberRefreshHelp"),present:false};
  }
  function signal(device) { let dbm=device?.signal?.dbm;const rssi=device?.signal?.rssi;if(dbm==null && rssi!=null && Number(rssi)>=0 && Number(rssi)<=31)dbm=-113+Number(rssi)*2;return dbm!=null && Number.isFinite(Number(dbm))?`${dbm} dBm`:t("unknown"); }
  function time(value,full=false) { if(!value)return t("timeUnknown");const date=new Date(value);return Number.isFinite(date.getTime()) ? full ? date.toLocaleString(locale(),{hour12:false}) : date.toLocaleTimeString(locale(),{hour12:false}) : String(value); }
  class UIError extends Error { constructor(key,detail="",args={}) { super(key);this.key=key;this.detail=detail;this.args=args; } }
  const normalizeError = (error) => error instanceof UIError ? error : new UIError("requestFailed",error?.message || String(error));
  function errorNode(error) { const issue=normalizeError(error),box=el("div","inline-error",t(issue.key,issue.args));if(issue.detail)box.append(el("span","error-detail",issue.detail));return box; }
  async function api(path,{method="GET",body}={}) {
    if(method!=="GET" && !state.token)throw new UIError("sessionExpired");
    const headers={Accept:"application/json"};if(method!=="GET")headers["X-Cellulary-Token"]=state.token;if(body!==undefined)headers["Content-Type"]="application/json";
    const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),180000);
    try {
      const response=await fetch(path,{method,headers,credentials:"same-origin",cache:"no-store",signal:controller.signal,...(body!==undefined?{body:JSON.stringify(body)}:{})});
      const data=(response.headers.get("content-type")||"").includes("application/json")?await response.json():{};
      if(!response.ok) {
        const code=data.code || data.error_code || data.detail?.code;
        const detail=typeof data.detail === "string"?data.detail:typeof data.message === "string"?data.message:Array.isArray(data.detail)?data.detail.map((item)=>item.msg).join("; "):"";
        const key=translations.dynamic[code]?code:response.status===403?"sessionExpired":response.status===404?"deviceMissing":response.status===422?"validationFailed":"requestFailed";
        throw new UIError(key,detail);
      }
      return data;
    } catch(error) { if(error.name === "AbortError")throw new UIError("requestTimeout");if(error instanceof TypeError)throw new UIError("connectionFailed");throw error; }
    finally { clearTimeout(timeout); }
  }
  function busy(button,value) { button.classList.toggle("loading",value);button.setAttribute("aria-busy",String(value));button.disabled=value; }
  function notice(key,args={},kind="",detail="",device="") { state.notice={key,args,kind,detail,device};renderNotice(); }
  function renderNotice() { const message=state.notice;show($("operation-notice"),Boolean(message));if(!message)return;$("operation-notice").className=`notice operation-notice ${message.kind}`;const span=$("operation-message");span.replaceChildren(document.createTextNode(`${message.device?`${message.device} · `:""}${t(message.key,message.args)}`));if(message.detail)span.append(el("span","error-detail",message.detail)); }
  function renderService() { text("service-status",t(state.online===true?"online":state.online===false?"offline":"connecting"));$("service-status").className=`service-status ${state.online===true?"online":state.online===false?"offline":""}`;show($("service-error"),Boolean(state.serviceError));if(state.serviceError){const issue=normalizeError(state.serviceError);text("service-error",t(issue.key,issue.args));}text("last-updated",state.updated?t("updated",{time:time(state.updated)}):"");text("footer-info",`Cellulary${state.version?` · ${state.version}`:""}`); }
  function translate() {
    document.documentElement.lang=state.language === "zh"?"zh-CN":"en";$("language").value=state.language;$("theme").value=state.theme;
    document.querySelectorAll("[data-i18n]").forEach((e)=>{e.textContent=t(e.dataset.i18n);});
    document.querySelectorAll("[data-i18n-placeholder]").forEach((e)=>{e.placeholder=t(e.dataset.i18nPlaceholder);});
    document.querySelectorAll("[data-i18n-aria]").forEach((e)=>{e.setAttribute("aria-label",t(e.dataset.i18nAria));});
    document.querySelectorAll("input,textarea,select").forEach((input)=>input.setCustomValidity(""));
    renderService();renderNotice();renderDevices();renderPage();renderHost();updateCount();
  }
  function setDevices(data) {
    const oldDevices=new Map(state.devices.map(device=>[String(device.id),device]));
    state.devices=Array.isArray(data.devices)?data.devices:[];const previous=state.selected;let invalidatedCurrent=false;
    for(const device of state.devices){const old=oldDevices.get(String(device.id));if(old && ["imei","firmware","sim_status","connected"].some(key=>old[key]!==device[key])){state.caches.delete(String(device.id));if(String(device.id)===state.selected)invalidatedCurrent=true;}}
    for(const id of state.caches.keys())if(id && !state.devices.some(device=>String(device.id)===id))state.caches.delete(id);
    if(!state.devices.some((device)=>String(device.id)===state.selected)) {
      const ready=state.devices.filter((device)=>sim(device).key === "ready");
      const first=ready.find((device)=>phone(device).present && device.connected!==false) || ready.find((device)=>device.connected!==false) || ready[0] || state.devices[0];
      state.selected=first?String(first.id):null;
    }
    renderDevices();if(previous!==state.selected || invalidatedCurrent){renderPage();loadPage();}else if(state.page === "overview")renderOverview();renderControls();
  }
  function renderDevices() {
    const items=state.devices.map((device)=>({id:String(device.id),label:`${name(device)} · ${port(device)}`}));const signature=JSON.stringify([state.language,items]);const selector=$("device-select");
    if(signature!==state.selectionSignature){state.selectionSignature=signature;selector.replaceChildren();if(!items.length){const option=el("option","",t("noDevices"));option.value="";selector.append(option);}for(const item of items){const option=el("option","",item.label);option.value=item.id;selector.append(option);}}
    selector.value=state.selected||"";selector.disabled=!items.length;
    text("device-count",t("deviceCount",{count:items.length,ready:state.devices.filter((device)=>sim(device).key === "ready").length}));
    const device=current(),facts=$("context-facts");facts.replaceChildren();
    if(device){const s=sim(device),r=registration(device),p=phone(device);for(const [key,value,kind]of [["sim",t(s.key),s.kind],["registration",t(r.key),r.kind],["phoneNumber",p.value,""]]){const fact=el("div","context-fact");fact.append(el("small","",t(key)),el("span",kind,value));facts.append(fact);}}
  }
  function definitionList(fields,className="detail-list") { const list=el("dl",className);for(const [key,value,kind]of fields){const group=el("div",kind||"");group.append(el("dt","",t(key)),el("dd",["firmware","atPort"].includes(key)?"mono":"",display(value)));list.append(group);}return list; }
  function renderOverview() {
    const device=current();if(!device)return;const p=phone(device),s=sim(device),r=registration(device);
    $("overview-sim").replaceChildren(badge(t(s.key),s.kind));text("phone-number",p.value);$("phone-number").classList.toggle("unavailable",!p.present);text("phone-reason",p.help);
    const fields=[["operator",device.operator?.name ?? device.operator ?? device.radio?.operator_plmn],["registration",t(r.key)],["signal",signal(device)],["sim",t(s.key)]];
    if(device.radio?.technology)fields.push(["radio",device.radio.technology],["band",device.radio.band]);
    $("overview-network").replaceChildren(...Array.from(definitionList(fields).children));
    $("device-detail").replaceChildren(definitionList([["manufacturer",device.manufacturer],["model",device.model],["IMEI",device.imei],["atPort",device.port],["firmware",device.firmware,"full-span"]]));
    if(device.error)$("device-detail").append(errorNode(new UIError("readFailed",String(device.error))));renderEvents();
  }
  function setPage(page,updateHash=true) { state.page=Object.hasOwn(pageKeys,page)?page:"overview";if(updateHash)history.replaceState(null,"",`#${state.page}`);renderPage();loadPage(); }
  function renderPage() {
    const page=state.page,available=Boolean(current());document.title=`${t(pageKeys[page])} · Cellulary`;text("page-title",t(pageKeys[page]));text("page-description",t(`${pageKeys[page]}Description`));
    show($("empty-device"),!available && page!=="events");Object.keys(pageKeys).forEach((key)=>show($(`page-${key}`),key===page && (available || key === "events")));
    document.querySelectorAll("[data-page]").forEach((button)=>{const active=button.dataset.page===page;button.classList.toggle("active",active);if(active)button.setAttribute("aria-current","page");else button.removeAttribute("aria-current");});
    if(page === "overview")renderOverview();else if(page === "sms")renderSms();else if(page === "data"){renderData();renderUsb();renderAdapter();}else if(page === "calls")renderCalls();else if(page === "gnss"){renderGnss();renderLocation();}else renderEvents();renderControls();
  }
  function resourceState(kind,containerId,emptyKey="notRequested") { const entry=resource(kind),container=$(containerId);container.replaceChildren();if(entry?.loading){container.append(el("p","empty-inline loading-text",t("loading")));return null;}if(entry?.error){container.append(errorNode(entry.error));return null;}if(!entry?.data){container.append(el("p","empty-inline",t(emptyKey)));return null;}return entry.data; }
  const resources={network:["network","network-refresh"],sms:["sms","sms-refresh"],data:["data","data-refresh"],usb:["data/usb","usb-refresh"],calls:["calls","calls-refresh"],gnss:["gnss","gnss-refresh"],location:["gnss/location","gnss-location"]};
  async function loadResource(kind,force=false,id=state.selected) {
    if(!id)return;const storage=cache(id);if(storage[kind]?.loading || (!force && storage[kind]))return;
    const entry={loading:true,data:null,error:null};storage[kind]=entry;if(id===state.selected){renderResource(kind);renderControls();}
    try{entry.data=await api(route(id,resources[kind][0]));}catch(error){entry.error=normalizeError(error);}finally{entry.loading=false;if(id===state.selected){renderResource(kind);renderControls();}}
  }
  function renderResource(kind) { ({network:renderAdapter,sms:renderSms,data:renderData,usb:renderUsb,calls:renderCalls,gnss:renderGnss,location:renderLocation})[kind](); }
  function loadPage() { if(!current())return;if(state.page === "data")Promise.allSettled([loadResource("data"),loadResource("usb"),loadResource("network")]);if(state.page === "calls" && current()?.voice_support!=="unsupported")loadResource("calls");if(state.page === "gnss")loadResource("gnss"); }
  function renderControls() {
    const device=current();document.querySelectorAll("[data-mutation]").forEach((button)=>{button.disabled=!device || device.connected===false || !state.token || state.mutating;});
    for(const [kind,[,buttonId]]of Object.entries(resources)){const loading=Boolean(resource(kind)?.loading);busy($(buttonId),loading);$(buttonId).disabled=!device || loading;}
    const usb=resource("usb"),gnss=resource("gnss");
    const usbReady=Boolean(device && device.connected!==false && usb?.data?.supported===true && !usb.loading && !usb.error && state.token && !state.mutating);$("usb-connect").disabled=!usbReady;$("usb-disconnect").disabled=!usbReady;
    const gnssReady=Boolean(device && device.connected!==false && gnss?.data?.supported===true && !gnss.loading && !gnss.error);$("gnss-start").disabled=!gnssReady || !state.token || state.mutating || gnss.data.enabled===true;$("gnss-stop").disabled=!gnssReady || !state.token || state.mutating || gnss.data.enabled===false;$("gnss-location").disabled=!gnssReady || gnss.data.enabled!==true || Boolean(resource("location")?.loading);
    const smsUnavailable=!device || device.sms_support === "unsupported";
    $("sms-number").disabled=smsUnavailable || state.mutating;$("sms-text").disabled=smsUnavailable || state.mutating;
    if(device?.sms_support === "unsupported"){$("sms-form").querySelector("button").disabled=true;$("sms-refresh").disabled=true;}
    $("call-number").disabled=!device || device.voice_support === "unsupported" || state.mutating;
    if(device?.voice_support === "unsupported"){for(const id of ["call-answer","call-hangup","calls-refresh"])$(id).disabled=true;$("dial-form").querySelector("button").disabled=true;}
    if(!device || device.connected===false || sim(device).key!=="ready") {
      for(const id of ["sms-refresh","call-answer","calls-refresh","data-activate","usb-connect"])$(id).disabled=true;
      $("sms-form").querySelector("button").disabled=true;$("dial-form").querySelector("button").disabled=true;
    }
    $("status-refresh").disabled=!device || state.mutating;$("discover-button").disabled=!state.token || state.scanning;
    const iface=$("host-interface").value;$("host-connect").disabled=!state.token || state.mutating || !iface || !$("host-profile").value;$("host-disconnect").disabled=!state.token || state.mutating || !iface;
  }
  function renderSms() {
    text("sms-count","");if(current()?.sms_support === "unsupported"){$("sms-inbox").replaceChildren(el("p","empty-inline",t("smsUnsupported")));return;}
    const data=resourceState("sms","sms-inbox","smsOnDemand");if(!data)return;const messages=Array.isArray(data.messages)?data.messages:[];text("sms-count",t("messageCount",{count:messages.length}));const inbox=$("sms-inbox");if(!messages.length){inbox.append(el("p","empty-inline",t("noMessages")));return;}
    const statuses={0:"unread",1:"read",2:"unsent",3:"sent","REC UNREAD":"unread","REC READ":"read","STO UNSENT":"unsent","STO SENT":"sent"};
    for(const message of messages){const article=el("article","message-item"),header=el("header");header.append(el("strong","",display(message.number ?? message.sender ?? message.address,t("unknownNumber"))),el("time","",time(message.timestamp,true)));article.append(header,el("p","",display(message.text ?? message.body,t("emptyMessage"))),el("small","",[t(statuses[message.status]||"unknown"),message.index!=null?t("storageIndex",{index:message.index}):""].filter(Boolean).join(" · ")));if(message.complete===false)article.append(el("p","inline-error",t("smsIncomplete")));if(message.decode_error)article.append(errorNode(new UIError("smsDecodeError",message.decode_error)));inbox.append(article);}
  }
  function updateCount() { text("sms-character-count",t("characters",{count:Array.from($("sms-text").value).length})); }
  function renderData() {
    const data=resourceState("data","data-contexts");if(!data)return;const container=$("data-contexts");if(data.attached!=null)container.append(el("p","field-note",t(data.attached?"attached":"detached")));
    const list=el("div","data-context-list"),contexts=Array.isArray(data.contexts)?data.contexts:[];
    for(const item of contexts){const row=el("div","data-context-row"),detail=el("div");detail.append(el("strong","",`CID ${display(item.context_id ?? item.cid,"?")} · ${display(item.apn)}`),el("small","",[display(item.pdp_type ?? item.type,""),display(item.address ?? item.ip,"")].filter(Boolean).join(" · ")||t("noAddress")));row.append(detail,badge(t(item.active==null?"unknown":item.active?"active":"inactive"),item.active?"ready":""));list.append(row);}
    if(!contexts.length)list.append(el("p","field-note",t("noContexts")));container.append(list);for(const error of data.errors||[])container.append(errorNode(new UIError("readFailed",typeof error === "string"?error:`${error.command}: ${error.error}`)));
  }
  function renderUsb() { text("usb-help",t("usbHelp"));const data=resourceState("usb","usb-status");if(!data)return;const container=$("usb-status"),status=el("div","status-summary");status.append(badge(t(!data.supported?"unsupported":data.connected===true?"usbConnected":data.connected===false?"usbDisconnected":"unknown"),data.connected===true?"ready":!data.supported?"warning":""));const cid=data.context_id ?? data.cid;if(cid!=null)status.append(el("span","mono",t("currentCid",{cid})));container.append(status);if(!data.supported)text("usb-help",t("usbUnsupportedHelp")); }
  function renderAdapter() {
    const data=resourceState("network","device-network");if(!data)return;
    const container=$("device-network");
    if(!(data.adapters||[]).length)container.append(el("p","field-note",t("adapterMissing")));
    for(const adapter of data.adapters||[]) {
      const row=el("div","data-context-row"),detail=el("div");
      detail.append(el("strong","",adapter.Name),el("small","",`${(adapter.ipv4||[]).map(item=>item.address).join(", ")||t("noAddress")} · ${t("gateway")}: ${(adapter.gateways||[]).join(", ")||t("notReported")}`));
      row.append(detail,badge(t(adapter.host_configured?"hostConfigured":"hostNotConfigured"),adapter.host_configured?"ready":"warning"));container.append(row);
      if(adapter.duplicate_mac)container.append(el("p","notice warning",t("duplicateMac",{names:(adapter.conflicts||[]).join(", ")})));
      if(adapter.query_error)container.append(errorNode(new UIError("readFailed",adapter.query_error)));
    }
    container.append(el("p","field-note",t("hostNotVerified")));
    for(const error of data.errors||[])container.append(errorNode(new UIError("readFailed",String(error))));
  }
  function renderCalls() {
    const device=current(),unsupported=device?.voice_support === "unsupported";show($("voice-note"),unsupported || /EC801E/i.test(name(device)));text("voice-note",t(unsupported?"voiceUnsupported":"voiceUnverified"));if(unsupported){$("call-list").replaceChildren(el("p","empty-inline",t("voiceUnsupported")));return;}
    const data=resourceState("calls","call-list");if(!data)return;const calls=Array.isArray(data.calls)?data.calls:[],list=$("call-list");if(!calls.length){list.append(el("p","empty-inline",t("noCalls")));return;}
    const states={0:"callActive",1:"held",2:"dialing",3:"alerting",4:"incomingCall",5:"waiting",active:"callActive",held:"held",dialing:"dialing",alerting:"alerting",incoming:"incomingCall",waiting:"waiting"};
    for(const call of calls){const row=el("div","call-item"),detail=el("div"),direction=call.direction ?? call.dir;detail.append(el("strong","",display(call.number,t("unknownNumber"))),el("small","",t(direction===1 || direction === "incoming"?"incoming":"outgoing")));row.append(detail,badge(t(states[call.state ?? call.status ?? call.stat]||"unknown"),"ready"));list.append(row);}
  }
  function gnssReason(data) { return translations.dynamic[data?.reason_code]?t(data.reason_code):data?.supported===false?t("gnss_not_supported"):data?.enabled===false?t("gnss_disabled"):""; }
  function renderGnss() { const data=resourceState("gnss","gnss-status");if(!data)return;const container=$("gnss-status"),summary=el("div","status-summary");summary.append(badge(t(data.supported===false?"unsupported":data.enabled===true?"enabled":data.enabled===false?"disabled":"supportedUnknown"),data.supported===false?"warning":data.enabled?"ready":""));container.append(summary);const reason=gnssReason(data);if(reason)container.append(el("p","field-note",reason)); }
  function renderLocation() { const data=resourceState("location","gnss-location-result","locationOnDemand");if(!data)return;const container=$("gnss-location-result");if(!data.fix){container.append(el("h3","",t("noFix")),el("p","field-note",gnssReason(data)||t("fixHelp")));return;}container.append(definitionList([["latitude",data.latitude,"coordinate"],["longitude",data.longitude,"coordinate"],["altitude",data.altitude_m!=null?`${data.altitude_m} m`:undefined],["satellites",data.satellites],["fixType",data.fix_type!=null?`${data.fix_type}D`:undefined],["speed",data.speed_kph!=null?`${data.speed_kph} km/h`:undefined],["timestamp",time(data.timestamp || data.utc,true),"full-span"]],"location-values")); }
  async function refreshCached() { const results=await Promise.allSettled([api("/api/devices"),api("/api/events")]);if(results[0].status === "fulfilled"){state.online=true;state.serviceError=null;state.updated=new Date().toISOString();setDevices(results[0].value);}else{state.online=false;state.serviceError=results[0].reason;}if(results[1].status === "fulfilled"){state.events=results[1].value.events||[];renderEvents();}renderService(); }
  async function scan() { if(state.scanning)return;state.scanning=true;busy($("discover-button"),true);notice("scanStarted");try{const data=await api("/api/discover",{method:"POST"});setDevices(data);notice(data.scanning?"scanStarted":"scanComplete",{count:state.devices.length});await refreshCached();}catch(error){const issue=normalizeError(error);notice(issue.key,issue.args,"error",issue.detail);}finally{state.scanning=false;busy($("discover-button"),false);renderControls();} }
  function requireDevice() { const device=current();if(!device)throw new UIError("selectDevice");return device; }
  async function action(button,callback,scope) { if(state.mutating)return;state.mutating=true;const label=scope ?? (current()?port(current()):"");busy(button,true);renderControls();notice("working",{},"","",label);try{const result=await callback();notice(result.key,result.args||{},"","",result.device??label);await refreshCached();}catch(error){const issue=normalizeError(error);notice(issue.key,issue.args,"error",issue.detail,label);}finally{state.mutating=false;busy(button,false);renderControls();} }
  function valid(input,key,condition,args={}) { input.setCustomValidity(condition?"":t(key,args));if(!condition){input.reportValidity();input.focus();}return condition; }
  function numberValue(id) { const input=$(id),value=input.value.trim();return valid(input,"validNumber",/^\+?[0-9]{1,20}$/.test(value))?value:null; }
  function cidValue(id,max) { const input=$(id),value=Number(input.value);return valid(input,"validCid",input.value!=="" && Number.isInteger(value) && value>=1 && value<=max,{max})?value:null; }
  async function refreshStatus() { await action($("status-refresh"),async()=>{const device=requireDevice(),value=await api(route(device.id,"status")),status=value.device??value;state.devices=state.devices.map((item)=>String(item.id)===String(device.id)?{...item,...status,id:item.id}:item);renderDevices();renderOverview();return {key:"statusUpdated"};}); }
  async function sendSms(event) { event.preventDefault();const number=numberValue("sms-number"),value=$("sms-text").value;if(!number || !valid($("sms-text"),"requiredMessage",Boolean(value.trim())))return;await action(event.currentTarget.querySelector("button"),async()=>{const device=requireDevice();await api(route(device.id,"sms"),{method:"POST",body:{number,text:value}});if(state.selected===String(device.id) && $("sms-text").value===value){$("sms-text").value="";updateCount();}return {key:"smsSubmitted",args:{number}};}); }
  async function configureApn(event) { event.preventDefault();const cid=cidValue("data-cid",16),input=$("data-apn"),apn=input.value.trim();if(cid===null || !valid(input,"validApn",/^[A-Za-z0-9.-]{1,100}$/.test(apn)))return;await action(event.currentTarget.querySelector("button"),async()=>{const device=requireDevice();await api(route(device.id,"data/configure"),{method:"POST",body:{cid,apn}});await loadResource("data",true,String(device.id));return {key:"apnSaved",args:{cid}};}); }
  async function dataAction(active) { const cid=cidValue("data-cid",16);if(cid===null)return;await action($(active?"data-activate":"data-deactivate"),async()=>{const device=requireDevice();await api(route(device.id,`data/${active?"activate":"deactivate"}`),{method:"POST",body:{cid}});await loadResource("data",true,String(device.id));return {key:active?"contextActivated":"contextDeactivated"};}); }
  async function usbAction(connect) { const cid=cidValue("usb-cid",15);if(cid===null)return;await action($(connect?"usb-connect":"usb-disconnect"),async()=>{const device=requireDevice();if(resource("usb")?.data?.supported!==true)throw new UIError("capabilityRequired");await api(route(device.id,`data/usb/${connect?"connect":"disconnect"}`),{method:"POST",body:{cid}});await loadResource("usb",true,String(device.id));return {key:connect?"usbStarted":"usbStopped"};}); }
  async function callAction(operation,event) { if(event)event.preventDefault();const number=operation === "dial"?numberValue("call-number"):null;if(operation === "dial"&&!number)return;const button=operation === "dial"?$("dial-form").querySelector("button"):$(`call-${operation}`);await action(button,async()=>{const device=requireDevice();await api(route(device.id,`calls/${operation}`),{method:"POST",...(operation === "dial"?{body:{number}}:{})});await loadResource("calls",true,String(device.id));return {key:{dial:"callRequested",answer:"answerRequested",hangup:"hangupRequested"}[operation]};}); }
  async function gnssAction(start) { await action($(start?"gnss-start":"gnss-stop"),async()=>{const device=requireDevice();if(resource("gnss")?.data?.supported!==true)throw new UIError("capabilityRequired");const result=await api(route(device.id,`gnss/${start?"start":"stop"}`),{method:"POST"});await loadResource("gnss",true,String(device.id));if(!start){delete cache(String(device.id)).location;if(state.selected===String(device.id))renderLocation();}return {key:result.status === "already_enabled"?"alreadyEnabled":result.status === "already_disabled"?"alreadyDisabled":start?"gnssStarted":"gnssStopped"};}); }
  const interfaceName=(item)=>typeof item === "string"?item:display(item.name??item.interface??item.id,"");
  const profileName=(item)=>typeof item === "string"?item:display(item.name??item.profile??item.id,"");
  function renderHostProfiles() { const selector=$("host-profile"),previous=selector.value;selector.replaceChildren();const placeholder=el("option","",t("chooseProfile"));placeholder.value="";selector.append(placeholder);const data=state.host?.data||{},selected=$("host-interface").value,entry=(data.interfaces||[]).find((item)=>interfaceName(item)===selected),profiles=Array.isArray(entry?.profiles)?entry.profiles:data.profiles||[];for(const item of profiles){if(item.interface && item.interface!==selected)continue;const value=profileName(item);if(!value)continue;const option=el("option","",value);option.value=value;selector.append(option);}if(previous && [...selector.options].some((item)=>item.value===previous))selector.value=previous;else if(selector.options.length===2)selector.selectedIndex=1;if(selector.options.length===1)placeholder.textContent=t("noProfiles");renderControls(); }
  function hostStatus(raw) { const value=String(raw??"").toLowerCase();if(["connected","已连接","up"].includes(value))return [t("connected"),"ready"];if(["disconnected","已断开连接","断开连接","down"].includes(value))return [t("disconnected"),""];return [t("unknown"),""]; }
  function renderHost() {
    const host=state.host,container=$("host-network-summary");container.replaceChildren();if(host?.loading){container.append(el("p","empty-inline loading-text",t("loading")));return;}if(host?.error){container.append(errorNode(host.error));return;}if(!host?.data){container.append(el("p","empty-inline",t("hostOnDemand")));return;}
    const interfaces=host.data.interfaces||[];if(!interfaces.length)container.append(el("p","field-note",t("noInterfaces")));
    for(const item of interfaces){const row=el("div","host-interface-item"),detail=el("span","",interfaceName(item));if(item.description)detail.append(el("small","",item.description));const [label,kind]=hostStatus(item.state??item.status);row.append(detail,badge(label,kind));container.append(row);}
    for(const issue of host.data.errors||[])container.append(errorNode(new UIError("readFailed",display(issue))));
    const selector=$("host-interface"),previous=selector.value;selector.replaceChildren();const placeholder=el("option","",t("chooseInterface"));placeholder.value="";selector.append(placeholder);for(const item of interfaces){const value=interfaceName(item),option=el("option","",value);option.value=value;selector.append(option);}if(interfaces.some((item)=>interfaceName(item)===previous))selector.value=previous;else if(interfaces.length===1)selector.selectedIndex=1;renderHostProfiles();
  }
  async function loadHost(force=false) { if(state.host?.loading || (state.host&&!force))return;state.host={loading:true,data:null,error:null};busy($("host-refresh"),true);renderHost();try{state.host.data=await api("/api/host/network");}catch(error){state.host.error=normalizeError(error);}finally{state.host.loading=false;busy($("host-refresh"),false);renderHost();renderControls();} }
  async function hostAction(connect,event) { if(event)event.preventDefault();const input=$("host-interface"),profile=$("host-profile");if(!valid(input,"interfaceRequired",Boolean(input.value)) || (connect&&!valid(profile,"profileRequired",Boolean(profile.value))))return;const body={interface:input.value,...(connect?{profile:profile.value}:{})};await action($(connect?"host-connect":"host-disconnect"),async()=>{await api(`/api/host/network/${connect?"connect":"disconnect"}`,{method:"POST",body});await loadHost(true);return {key:connect?"hostConnected":"hostDisconnected",device:body.interface};},body.interface); }
  function eventLevel(event) { const raw=String(event.level||"info").toLowerCase();return raw === "warn"?"warning":raw === "critical"?"error":raw; }
  function eventMessage(event) { if(event.code && translations.dynamic[event.code])return t(event.code,event.params||{});const raw=display(event.message,""),known={"模块已连接":"deviceConnectedEvent","Device connected":"deviceConnectedEvent","模块已移除":"deviceRemovedEvent","Device disconnected":"deviceRemovedEvent","Device removed":"deviceRemovedEvent"};if(known[raw])return t(known[raw]);if(raw.startsWith("Scan failed:"))return `${t("scanFailedEvent")}: ${raw.slice(12)}`;if(raw.startsWith("扫描失败"))return `${t("scanFailedEvent")}: ${raw.slice(5)}`;return raw; }
  function renderEvents() {
    const events=[...state.events].sort((a,b)=>(Date.parse(b.time??b.timestamp)||0)-(Date.parse(a.time??a.timestamp)||0));const selected=events.filter((item)=>!item.device_id || String(item.device_id)===state.selected).slice(0,4),recent=$("recent-events");recent.replaceChildren();if(!selected.length)recent.append(el("p","empty-inline",t("noEvents")));
    for(const event of selected){const row=el("div",`event-item ${eventLevel(event)}`),body=el("div");body.append(el("p","",eventMessage(event)),el("small","",event.device_id||t("system")));row.append(body,el("time","",time(event.time??event.timestamp)));recent.append(row);}
    const filter=$("event-filter").value,filtered=events.filter((item)=>filter === "all" || eventLevel(item)===filter),table=$("events-body");table.replaceChildren();
    for(const event of filtered){const row=el("tr"),level=eventLevel(event),cell=el("td");cell.append(badge(t(level),["error","warning"].includes(level)?level:""));row.append(el("td","",time(event.time??event.timestamp,true)),cell,el("td","",event.device_id||t("system")),el("td","",eventMessage(event)));table.append(row);}show($("events-empty"),!filtered.length);text("events-empty",t(filter === "all"?"noEvents":"noFilteredEvents"));
  }
  async function refreshEvents() { busy($("events-refresh"),true);try{const data=await api("/api/events");state.events=data.events||[];renderEvents();}catch(error){const issue=normalizeError(error);notice(issue.key,issue.args,"error",issue.detail);}finally{busy($("events-refresh"),false);} }
  function bind() {
    document.querySelectorAll("[data-page]").forEach((button)=>button.addEventListener("click",()=>setPage(button.dataset.page)));
    window.addEventListener("hashchange",()=>{if(location.hash!=="#main")setPage(location.hash.slice(1),false);});
    $("device-select").addEventListener("change",(event)=>{state.selected=event.target.value;persist("device",state.selected);renderDevices();renderPage();loadPage();});
    $("language").addEventListener("change",(event)=>{state.language=event.target.value;persist("language",state.language);translate();});
    $("theme").addEventListener("change",(event)=>{state.theme=event.target.value;document.documentElement.dataset.theme=state.theme;persist("theme",state.theme);});
    $("discover-button").addEventListener("click",scan);$("dismiss-notice").addEventListener("click",()=>{state.notice=null;renderNotice();});$("status-refresh").addEventListener("click",refreshStatus);
    $("sms-form").addEventListener("submit",sendSms);$("sms-text").addEventListener("input",updateCount);$("sms-refresh").addEventListener("click",()=>loadResource("sms",true));
    for(const kind of ["data","usb","calls","gnss","network"])$(resources[kind][1]).addEventListener("click",()=>loadResource(kind,true));
    $("gnss-location").addEventListener("click",()=>loadResource("location",true));$("apn-form").addEventListener("submit",configureApn);$("data-activate").addEventListener("click",()=>dataAction(true));$("data-deactivate").addEventListener("click",()=>dataAction(false));$("usb-connect").addEventListener("click",()=>usbAction(true));$("usb-disconnect").addEventListener("click",()=>usbAction(false));
    $("dial-form").addEventListener("submit",(event)=>callAction("dial",event));$("call-answer").addEventListener("click",()=>callAction("answer"));$("call-hangup").addEventListener("click",()=>callAction("hangup"));$("gnss-start").addEventListener("click",()=>gnssAction(true));$("gnss-stop").addEventListener("click",()=>gnssAction(false));
    $("host-section").addEventListener("toggle",()=>{if($("host-section").open)loadHost();});$("host-refresh").addEventListener("click",()=>loadHost(true));$("host-interface").addEventListener("change",renderHostProfiles);$("host-profile").addEventListener("change",renderControls);$("host-connect-form").addEventListener("submit",(event)=>hostAction(true,event));$("host-disconnect").addEventListener("click",()=>hostAction(false));$("event-filter").addEventListener("change",renderEvents);$("events-refresh").addEventListener("click",refreshEvents);
    document.querySelectorAll("input,textarea,select").forEach((input)=>input.addEventListener("input",()=>input.setCustomValidity("")));
  }
  async function poll() { if(document.hidden || state.polling || state.scanning)return;state.polling=true;try{await refreshCached();}finally{state.polling=false;} }
  async function start() { try{state.selected=localStorage.getItem("cellulary.device");}catch{/* Optional storage. */}bind();translate();setPage(location.hash.slice(1)||"overview",false);busy($("discover-button"),true);try{const session=await api("/api/session");state.token=session.token;state.version=session.version||"";show($("demo-banner"),session.mode === "demo");await refreshCached();}catch(error){state.online=false;state.serviceError=normalizeError(error);renderService();}finally{busy($("discover-button"),false);renderControls();}setInterval(poll,8000);document.addEventListener("visibilitychange",()=>{if(!document.hidden)poll();}); }
  start();
})();
