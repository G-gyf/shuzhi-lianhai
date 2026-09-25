/* 对话工作台（chat.js）
   职责：面板开关、会话状态、SSE 消费、请求取消、上下文跟随、历史恢复。
   事件（项目自定义协议）：request_started / status / clarification /
   answer_delta / orbs_ready / analysis_ready / error / done
   切换企业后旧请求不得覆盖新企业面板（request_id + 上下文代际双重防护）。 */

window.DSH_AUTH = {
  token: () => localStorage.getItem("dsh_token") || "demo-token-region-a",
};

window.DSH_CHAT = (() => {
  const PHASE_CN = { querying: "查询中", analyzing: "分析中", validating: "校验中",
                     answered: "已呈现", failed: "失败", cancelled: "已取消" };
  let sessionId = null;
  let activeRequestId = null;
  let activeBubble = null;
  let activeStatus = null;
  let controller = null;
  let contextGen = 0;
  let lastAnalysis = null;
  let open = false;

  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? "").replace(/[&<>"]/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

  function authHeaders(extra) {
    return Object.assign({ "Authorization": "Bearer " + window.DSH_AUTH.token() }, extra || {});
  }
  function sessionKey() { return "dsh_session_" + window.DSH_AUTH.token(); }

  function pageContext() {
    const c = window.DSH_CHAT_CONTEXT || {};
    const ctx = {};
    if (c.scode) ctx.scode = c.scode;
    if (c.year) ctx.year = c.year;
    if (c.view) ctx.view = c.view;
    return ctx;
  }

  /* ---------- UI 骨架 ---------- */
  function addMsg(role, contentHtml, extraClass) {
    const body = $("chat-body");
    const m = document.createElement("div");
    m.className = "chat-msg " + role + (extraClass ? " " + extraClass : "");
    m.innerHTML = `<div class="who">${role === "user" ? "经理" : "数智链海助手"}</div>
      <div class="bubble">${contentHtml}</div>`;
    body.appendChild(m);
    body.scrollTop = body.scrollHeight;
    return m;
  }

  function newAssistantBubble() {
    activeBubble = addMsg("assistant", "");
    activeStatus = document.createElement("div");
    activeStatus.className = "chat-status";
    activeStatus.innerHTML = '<span class="s-dot"></span><span class="s-text">查询中…</span>';
    activeBubble.querySelector(".bubble").appendChild(activeStatus);
    return activeBubble;
  }

  function setStatus(text, phase) {
    if (!activeStatus) return;
    activeStatus.querySelector(".s-text").textContent = text;
    activeStatus.className = "chat-status" +
      (phase === "done" ? " done" : phase === "err" ? " err" : "");
  }

  function appendBlock(kind, text, refs) {
    if (!activeBubble) return;
    const bubble = activeBubble.querySelector(".bubble");
    if (activeStatus) { activeStatus.remove(); activeStatus = null; }
    const blk = document.createElement("div");
    blk.className = "blk " + kind;
    blk.dataset.refs = (refs || []).join("|");
    let html = esc(text);
    (refs || []).forEach((r, i) => {
      html += `<sup class="refmark" data-ref="${esc(r)}" title="查看依据">[${i + 1}]</sup>`;
    });
    blk.innerHTML = html;
    bubble.appendChild(blk);
    bubble.querySelectorAll(".refmark").forEach((m) =>
      m.onclick = () => window.DSHDrawer.open(m.dataset.ref, "依据详情"));
    $("chat-body").scrollTop = $("chat-body").scrollHeight;
  }

  function renderOrbs(orbs) {
    if (!activeBubble) return;
    const bubble = activeBubble.querySelector(".bubble");
    const box = window.DSHOrbs.render(bubble, orbs, activeBubble);
    $("chat-body").scrollTop = $("chat-body").scrollHeight;
    return box;
  }

  function renderAnalysis(payload) {
    if (!activeBubble) return;
    lastAnalysis = payload;
    const bubble = activeBubble.querySelector(".bubble");
    const card = document.createElement("div");
    card.className = "analysis-card";
    let html = "";
    const recs = payload.recommendations || [];
    if (recs.length) {
      html += "<h5>候选服务（讨论顺序）</h5>" + recs.map((r, i) => {
        const state = { eligible: "条件已满足", not_eligible: "不适用",
                        unknown: "待确认" }[r.eligibility] || "待确认";
        const pid = (r.product_ref || "").split(":").pop();
        return `<div class="rec"><b>${i + 1}. ${esc(pid || r.id)}</b>
          <span class="state ${esc(r.eligibility || "unknown")}">${esc(state)}</span>
          <br><span class="muted">${esc(r.reason || "")}</span>
          ${(r.missing_conditions || []).length ? `<br><span class="warn">待核实：${esc(r.missing_conditions.join("、"))}</span>` : ""}
          ${r.product_ref ? ` <a class="refmark" data-ref="${esc(r.product_ref)}" style="cursor:pointer">产品卡</a>` : ""}</div>`;
      }).join("");
    }
    const qs = payload.questions || [];
    if (qs.length) {
      html += "<h5>拜访问题清单</h5><ul>" + qs.map((q, i) =>
        `<li>${i + 1}. ${esc(q.text)}</li>`).join("") + "</ul>";
    }
    const warns = payload.warnings || [];
    if (warns.length) {
      html += `<h5>口径与演示说明</h5>` + warns.map((w) =>
        `<div class="warn">· ${esc(w)}</div>`).join("");
    }
    html += `<div style="margin-top:8px;display:flex;gap:8px;flex-wrap:wrap">
      <button class="brief-btn" id="chat-brief">生成一页访前简报</button>
      ${payload.context && payload.context.scode
        ? `<button class="brief-btn" id="chat-open-co">打开企业详情</button>` : ""}
    </div>`;
    card.innerHTML = html;
    bubble.appendChild(card);
    card.querySelectorAll(".refmark").forEach((m) =>
      m.onclick = () => window.DSHDrawer.open(m.dataset.ref, "产品依据"));
    const bb = card.querySelector("#chat-brief");
    if (bb) bb.onclick = async () => {
      bb.disabled = true; bb.textContent = "生成中…";
      try {
        const r = await fetch(API + "/api/v1/briefings", {
          method: "POST", headers: authHeaders({ "Content-Type": "application/json" }),
          body: JSON.stringify({ analysis_id: payload.analysis_id }),
        });
        if (!r.ok) throw new Error("briefing " + r.status);
        const b = await r.json();
        if (window.DSHShowBriefing) window.DSHShowBriefing(b);
      } catch (e) {
        bb.textContent = "简报生成失败，点击重试";
      } finally { bb.disabled = false; }
    };
    const oc = card.querySelector("#chat-open-co");
    if (oc) oc.onclick = () => {
      const c = payload.context;
      if (window.DSHOpenCompany) window.DSHOpenCompany(c.scode, c.year);
    };
    $("chat-body").scrollTop = $("chat-body").scrollHeight;
  }

  function renderClarify(payload) {
    if (!activeBubble) return;
    const bubble = activeBubble.querySelector(".bubble");
    if (activeStatus) { activeStatus.remove(); activeStatus = null; }
    const div = document.createElement("div");
    div.className = "blk note";
    div.textContent = payload.message || "请补充信息。";
    bubble.appendChild(div);
    if (payload.options && payload.options.length) {
      const box = document.createElement("div");
      box.className = "clarify-options";
      payload.options.forEach((o) => {
        const b = document.createElement("button");
        b.textContent = o.label || o.scode;
        b.onclick = () => {
          if (o.scode && window.DSHOpenCompany) window.DSHOpenCompany(o.scode, o.year);
          send("分析这家企业（" + (o.scode || o.label) + "）为何入选？", true);
        };
        box.appendChild(b);
      });
      bubble.appendChild(box);
    }
    $("chat-body").scrollTop = $("chat-body").scrollHeight;
  }

  function renderError(code, message, retryable) {
    setStatus("出错：" + (message || code), "err");
    if (retryable && activeBubble) {
      const bubble = activeBubble.querySelector(".bubble");
      const b = document.createElement("button");
      b.className = "brief-btn"; b.textContent = "↻ 重试";
      b.onclick = () => retryLast();
      bubble.appendChild(b);
    }
  }

  let lastMessage = "";
  function retryLast() {
    if (lastMessage) send(lastMessage, false);
  }

  /* ---------- 发送与 SSE ---------- */
  async function send(message, fromOption) {
    if (controller) return; // 已有请求进行中（可先点“停止”）
    const msg = (message || $("chat-input").value || "").trim();
    if (!msg) return;
    if (!fromOption) { $("chat-input").value = ""; }
    lastMessage = msg;
    addMsg("user", esc(msg));
    newAssistantBubble();
    contextGen++;
    const myGen = contextGen;
    const clientRequestId = "crid_" + Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
    const body = {
      session_id: sessionId,
      client_request_id: clientRequestId,
      message: msg,
      page_context: pageContext(),
    };
    controller = new AbortController();
    $("chat-cancel").style.display = "inline-block";
    try {
      const resp = await fetch(API + "/api/v1/chat/stream", {
        method: "POST",
        headers: authHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify(body),
        signal: controller.signal,
      });
      if (!resp.ok || !resp.body) {
        const txt = await resp.text().catch(() => "");
        throw new Error("HTTP " + resp.status + " " + txt.slice(0, 160));
      }
      await consumeStream(resp.body, myGen);
    } catch (e) {
      if (e.name === "AbortError") {
        setStatus("已停止（上游可能仍计费）", "err");
      } else if (contextGen === myGen) {
        renderError("stream", String(e), true);
      }
    } finally {
      controller = null;
      $("chat-cancel").style.display = "none";
      setBusy(false);
    }
  }

  async function consumeStream(stream, myGen) {
    const reader = stream.getReader();
    const decoder = new TextDecoder("utf-8");
    let buf = "";
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      let idx;
      while ((idx = buf.indexOf("\n\n")) >= 0) {
        const chunk = buf.slice(0, idx);
        buf = buf.slice(idx + 2);
        handleEvent(parseSSE(chunk), myGen);
      }
    }
  }

  function parseSSE(chunk) {
    let event = "message", data = "";
    for (const line of chunk.split("\n")) {
      if (line.startsWith("event:")) event = line.slice(6).trim();
      else if (line.startsWith("data:")) data += line.slice(5).trim();
    }
    try { return { event, data: data ? JSON.parse(data) : {} }; }
    catch (e) { return { event, data: {} }; }
  }

  function handleEvent(ev, myGen) {
    if (ev.data.request_id && ev.data.request_id !== activeRequestId && ev.event !== "request_started") {
      // 旧请求事件：不覆盖当前面板（切换企业/新请求后丢弃）
      return;
    }
    if (contextGen !== myGen) return; // 页面上下文已切换：旧响应丢弃
    switch (ev.event) {
      case "request_started":
        activeRequestId = ev.data.request_id;
        if (ev.data.session_id) {
          sessionId = ev.data.session_id;
          localStorage.setItem(sessionKey(), sessionId);
        }
        const c = ev.data.context || {};
        $("chat-meta").textContent = c.scode
          ? `上下文：${esc(c.scode)}${c.year ? " · " + c.year : ""}`
          : "上下文：未绑定企业";
        setStatus("查询中：受控工具检索事实与证据");
        break;
      case "status":
        setStatus(ev.data.text || PHASE_CN[ev.data.phase] || "处理中");
        break;
      case "clarification":
        renderClarify(ev.data);
        setStatus("需要澄清", "done");
        break;
      case "answer_delta":
        appendBlock(ev.data.kind || "fact", ev.data.text || "", ev.data.refs || []);
        break;
      case "orbs_ready":
        renderOrbs(ev.data.orbs || []);
        break;
      case "analysis_ready":
        renderAnalysis(ev.data);
        setStatus("校验完成 · 依据可核查", "done");
        break;
      case "error":
        renderError(ev.data.code, ev.data.message, ev.data.retryable);
        break;
      case "done":
        setStatus("完成", "done");
        break;
    }
  }

  function setBusy(busy) {
    const dot = document.querySelector("#chat-toggle .dot");
    if (dot) dot.className = "dot" + (busy ? " busy" : "");
  }

  function cancel() {
    if (!controller) return;
    if (activeRequestId) {
      fetch(API + "/api/v1/chat/requests/" + activeRequestId + "/cancel",
            { method: "POST", headers: authHeaders() }).catch(() => {});
    }
    controller.abort();
  }

  function contextChanged() {
    // 企业切换：旧响应不覆盖新面板
    contextGen++;
    if (activeBubble && controller) {
      activeBubble.classList.add("stale");
    }
  }

  /* ---------- 会话恢复 ---------- */
  async function restore() {
    const sid = localStorage.getItem(sessionKey());
    if (!sid) return;
    try {
      const r = await fetch(API + "/api/v1/chat/sessions/" + sid, { headers: authHeaders() });
      if (!r.ok) return;
      const s = await r.json();
      sessionId = s.session_id;
      const bodyEl = $("chat-body");
      bodyEl.innerHTML = "";
      for (const m of s.messages || []) {
        addMsg(m.role === "user" ? "user" : "assistant", esc(m.content));
      }
      const c = s.context || {};
      $("chat-meta").textContent = c.scode
        ? `会话上下文：${esc(c.scode)}${c.year ? " · " + c.year : ""}`
        : "已恢复会话";
    } catch (e) { /* 恢复失败不阻塞 */ }
  }

  /* ---------- 初始化 ---------- */
  function init() {
    const toggle = $("chat-toggle"), panel = $("chat-panel");
    toggle.onclick = () => {
      open = !open;
      panel.classList.toggle("on", open);
      if (open) $("chat-input").focus();
    };
    $("chat-close").onclick = () => { open = false; panel.classList.remove("on"); };
    $("chat-send").onclick = () => send();
    $("chat-cancel").onclick = cancel;
    $("chat-input").addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
    });
    $("chat-identity").value = window.DSH_AUTH.token();
    $("chat-identity").onchange = (e) => {
      localStorage.setItem("dsh_token", e.target.value);
      sessionId = null;
      $("chat-body").innerHTML = "";
      $("chat-meta").textContent = "";
      restore();
    };
    restore();
  }

  document.addEventListener("DOMContentLoaded", init);
  return { send, contextChanged, restore,
           get lastAnalysis() { return lastAnalysis; } };
})();
