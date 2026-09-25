/* 详情抽屉（drawer.js）
   桌面右侧抽屉 / 窄屏全屏面板；Esc 关闭；返回保留滚动位置。
   引用详情失败：显示可重试状态，不让整个对话消失。 */
window.DSHDrawer = (() => {
  let savedScrollY = 0;
  let lastRef = null;
  let revision = 0;

  function authHeaders() {
    const token = (window.DSH_AUTH && window.DSH_AUTH.token()) || "";
    return { "Authorization": "Bearer " + token };
  }

  function open(refId, title) {
    savedScrollY = window.scrollY;
    lastRef = refId;
    const d = document.getElementById("drawer");
    d.querySelector("#drawer-title").textContent = title || "依据详情";
    const body = d.querySelector("#drawer-body");
    body.innerHTML = '<div class="d-meta">加载依据详情…</div>';
    d.classList.add("on");
    load(refId, body);
  }

  function openList(orb, title) {
    revision++;
    savedScrollY = window.scrollY;
    lastRef = null;
    const d = document.getElementById("drawer");
    d.querySelector("#drawer-title").textContent = title || "待核实事项";
    const body = d.querySelector("#drawer-body");
    const last = (window.DSH_CHAT && window.DSH_CHAT.lastAnalysis) || {};
    const recs = last.recommendations || [];
    const lines = [];
    for (const r of recs) {
      const miss = r.missing_conditions || [];
      if (miss.length) lines.push(`<li>${esc(r.id)}：${esc(miss.join("、"))}</li>`);
    }
    body.innerHTML = lines.length
      ? '<div class="d-sec"><b>以下候选服务存在待确认条件（不冒充适配）：</b><ul>' +
        lines.join("") + "</ul></div>"
      : '<p class="muted">当前分析没有待确认事项。</p>';
    d.classList.add("on");
  }

  async function load(refId, body) {
    const current = ++revision;
    try {
      const r = await fetch(API + "/api/v1/references/" + encodeURIComponent(refId),
                            { headers: authHeaders() });
      if (!r.ok) {
        const txt = await r.text();
        if (current === revision) renderError(body, refId, r.status, txt);
        return;
      }
      const data = await r.json();
      if (current === revision) render(body, data);
    } catch (e) {
      if (current === revision) renderError(body, refId, 0, String(e));
    }
  }

  function renderError(body, refId, status, message) {
    body.innerHTML = `<div class="d-err">引用详情加载失败（${status || "网络错误"}）。<br>
      <span class="muted">${esc(message)}</span></div>
      <div style="text-align:center"><button class="d-btn" id="drawer-retry">↻ 重试</button></div>`;
    const btn = body.querySelector("#drawer-retry");
    if (btn) btn.onclick = () => { body.innerHTML = '<div class="d-meta">重新加载…</div>'; load(refId, body); };
  }

  function render(body, data) {
    const k = data.kind;
    const d = data.detail || {};
    if (k === "evidence") return renderEvidence(body, d);
    if (k === "product") return renderProduct(body, d);
    if (k === "metric") return renderMetric(body, d);
    if (k === "compare") return renderCompare(body, d);
    if (k === "analysis") return renderAnalysis(body, d);
    if (k === "regional") return renderRegional(body, d);
    if (k === "company") return renderCompany(body, d);
    body.innerHTML = `<p class="muted">暂不支持该引用类型的展示。</p>`;
  }

  function renderEvidence(body, d) {
    const spans = (d.spans || []).map((s) => ({ start: s.start, end: s.end }));
    const focusStart = spans.length ? spans[0].start : null;
    const hl = window.highlight ? window.highlight(d.text, spans, focusStart, null) : esc(d.text);
    body.innerHTML = `
      <div class="d-meta">${esc(d.coname)}（${esc(d.scode)}）· ${d.year} 年度 · ${esc(d.section)}<br>
        ${esc(d.program_label)} · 证据块 ${esc(d.chunk_id)} · 文本版本 ${esc(d.text_version)}
        ${d.warning ? '<br><span style="color:var(--coral)">⚠ ' + esc(d.warning) + "</span>" : ""}</div>
      <div class="d-text">${hl}</div>
      <div class="d-note">来源：${esc((d.source || {}).snapshot_id || "")}（${esc((d.source || {}).kb_version || "")}）。
        “确定性证据”指数据库中稳定的原文记录，不表示上游抽取标签和 AI 推断绝不会出错。</div>`;
  }

  function renderProduct(body, d) {
    const badge = d.status === "verified"
      ? '<span class="state-badge verified">已核实演示卡</span>'
      : "";
    body.innerHTML = `
      <div class="d-meta">产品ID ${esc(d.product_id)} · 版本 ${esc(d.product_version)} · 类别 ${esc(d.category)} ${badge}</div>
      <h4 style="color:var(--head)">${esc(d.name)}</h4>
      <div class="d-sec"><b>定义</b><p style="margin-top:3px">${esc(d.summary)}</p></div>
      <div class="d-sec"><b>适用场景</b><ul>${(d.scenarios || []).map((s) => `<li>${esc(s)}</li>`).join("")}</ul></div>
      <div class="d-sec"><b>必要条件</b><ul>${(d.conditions || []).map((s) => `<li>${esc(s)}</li>`).join("") || "<li>无</li>"}</ul></div>
      ${(d.exclusions || []).length ? `<div class="d-sec"><b>排除条件</b><ul>${d.exclusions.map((s) => `<li>${esc(s)}</li>`).join("")}</ul></div>` : ""}
      <div class="d-sec"><b>需核实信息</b><ul>${(d.need_verify || []).map((s) => `<li>${esc(s)}</li>`).join("") || "<li>—</li>"}</ul></div>
      <div class="d-sec"><b>来源</b><p class="muted" style="margin-top:3px">${esc(d.source)}</p>
        <p class="muted">${esc(d.source_locator || "")} · ${esc(d.source_date)} · 维护 ${esc(d.maintainer || "产品资料维护组")}</p></div>
      <div class="d-note">结构化产品卡：条件/名称/ID 由程序检查；长说明由检索返回片段。具体产品名称、条件与收费以行内最新产品手册为准。</div>`;
  }

  function renderMetric(body, d) {
    body.innerHTML = `
      <div class="d-meta">指标引用 · ${esc(d.table)} 表 · ${esc(d.scode)} · ${d.year}</div>
      <p style="font-size:15px;color:var(--head)">${esc(d.label)}：
        <b style="color:var(--gold)">${d.value}${esc(d.unit)}</b></p>
      <div class="d-sec"><b>参考范围</b><p class="muted" style="margin-top:3px">
        样本中位数 ${d.sample_median}${esc(d.unit)}（n=${d.sample_n}）</p></div>
      <div class="d-note">${esc(d.note)}</div>`;
  }

  function renderCompare(body, d) {
    const rows = (d.companies || []).map((c) => {
      const w = c.window || {};
      const cap = c.capability || {};
      return `<tr>
        <td><b style="color:var(--head)">${esc(c.coname)}</b><br><span class="muted">${esc(c.scode)} · ${esc(c.province)}</span></td>
        <td>${esc(w.window_label || "—")}<br><span class="muted">${esc(w.stage_label || "")} · 强度分 ${w.score ?? "—"}</span></td>
        <td>${c.customer_concentration != null ? c.customer_concentration + "%" : '<span class="muted">待核实</span>'}<br>
            <span class="muted">供应商 ${c.supplier_concentration != null ? c.supplier_concentration + "%" : "待核实"}</span></td>
        <td>${esc(cap.grade || "待核实")}${cap.score != null ? "<br><span class=\"muted\">评分 " + cap.score.toFixed(2) + "</span>" : ""}</td>
      </tr>`;
    }).join("");
    const miss = (d.missing || []).map((m) =>
      `<li>${esc(m.scode)}：${esc((m.missing || []).join("、"))}（待核实，不补 0、不取其他年度）</li>`).join("");
    body.innerHTML = `
      <div class="d-meta">确定性对比表 · 同一年度 ${d.year} · 比较ID ${esc(d.comparison_id)}</div>
      <table><thead><tr><th>企业</th><th>窗口</th><th>客户/供应商集中度</th><th>能力</th></tr></thead>
        <tbody>${rows}</tbody></table>
      ${miss ? `<div class="d-sec"><b>缺失标识</b><ul>${miss}</ul></div>` : ""}
      <div class="d-sec"><b>参考范围（样本中位数/四分位，${d.year}）</b>
        <ul>${Object.entries(d.reference || {}).map(([k, v]) =>
          `<li>${esc(k)}：中位 ${v.median}（Q1 ${v.q1} / Q3 ${v.q3}，n=${v.n}）</li>`).join("")}</ul></div>
      <div class="d-note">${esc(d.note || "")}</div>`;
  }

  function renderAnalysis(body, d) {
    const r = d.recommendation || {};
    const state = { eligible: "条件已满足", not_eligible: "不适用", unknown: "待确认" }[r.eligibility] || "待确认";
    body.innerHTML = `
      <div class="d-meta">AI 方案引用 · analysis_id ${esc(d.analysis_id)} · 推荐 ${esc(r.id)}<br>
        <span style="color:var(--coral)">标注为分析结果（引擎：${esc(d.engine || "—")}），不冒充原文事实。</span></div>
      ${r.product_ref ? `<p>产品依据：<a class="d-link" data-ref="${esc(r.product_ref)}"
         style="color:var(--gold);cursor:pointer">${esc(r.product_ref)}</a></p>` : ""}
      <div class="d-sec"><b>理由</b><p style="margin-top:3px">${esc(r.reason || "—")}</p></div>
      <div class="d-sec"><b>资格</b> <span class="state-badge ${r.eligibility === "eligible" ? "verified" : "placeholder"}">${esc(state)}</span>
        ${(r.missing_conditions || []).length ? `<ul style="margin-top:6px">${r.missing_conditions.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>` : ""}</div>
      ${(r.evidence_refs || []).length ? `<div class="d-sec"><b>证据引用</b><ul>${r.evidence_refs.map((x) =>
        `<li><a class="d-link" data-ref="${esc(x)}" style="color:var(--gold);cursor:pointer">${esc(x)}</a></li>`).join("")}</ul></div>` : ""}
      <div class="d-note">${esc(d.note || "")}</div>`;
    body.querySelectorAll("[data-ref]").forEach((a) =>
      a.onclick = () => open(a.dataset.ref, "依据详情"));
  }

  function renderRegional(body, d) {
    body.innerHTML = `
      <div class="d-meta">地区资料 · ${esc(d.source_name)}（${esc(d.source_id)}）· ${esc(d.version)} · scope=${esc(d.scope)}</div>
      <h4 style="color:var(--head)">${esc(d.title)}</h4>
      <p class="muted" style="margin:4px 0 10px">资料日期 ${esc(d.effective_from || "—")} · 定位 ${esc(d.locator || "—")}</p>
      <div class="d-text">${esc(d.body)}</div>
      <div class="d-note">${esc(d.note || "")} 地区资料引用：带 source_id、scope、版本；读取已再次检查权限。资料冲突时保留两个来源及差异，经理文件不无声覆盖公共事实。</div>`;
  }

  function renderCompany(body, d) {
    body.innerHTML = `
      <div class="d-meta">企业引用 · 稳定ID ${esc(d.scode)}${d.year ? " · 数据年度 " + d.year : ""}</div>
      <p style="font-size:15px;color:var(--head)">${esc(d.coname)}</p>
      <button class="d-btn" id="drawer-open-co">打开企业确定性详情 →</button>
      <div class="d-note">点击后打开网页确定性内容（同一年度上下文），不依赖全局可变年份猜测。</div>`;
    const btn = body.querySelector("#drawer-open-co");
    if (btn) btn.onclick = () => {
      close();
      if (window.DSHOpenCompany) window.DSHOpenCompany(d.scode, d.year);
      else if (window.openCompany) window.openCompany(d.scode, d.year);
    };
  }

  function close() {
    revision++;
    const d = document.getElementById("drawer");
    d.classList.remove("on");
    if (savedScrollY) window.scrollTo(0, savedScrollY);
    savedScrollY = 0;
  }

  function esc(s) {
    return String(s ?? "").replace(/[&<>"]/g,
      (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  }

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") close();
  });
  const closeBtn = document.getElementById("drawer-close");
  if (closeBtn) closeBtn.onclick = close;

  return { open, openList, close };
})();
