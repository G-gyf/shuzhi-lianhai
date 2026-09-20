/* 数智链海 · 最小闭环前端（零外部依赖：SVG 手绘雷达图与关系图） */
const API = window.DSH_API_BASE || "";
let CUR = null;       // 当前企业 scode
let CUR_YEAR = null;  // 当前企业选定年度（年份上下文贯穿详情/推理链/简报/子图）
let CUR_SEGMENT = null; // 当前产业链环节筛选

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

async function jget(url) {
  const r = await fetch(API + url);
  if (!r.ok) throw new Error(url + " -> " + r.status);
  return r.json();
}

/* ---------------- 初始化 ---------------- */
async function init() {
  try {
    const m = await jget("/api/meta");
    const p = $("f-province"), y = $("f-year"), ind = $("f-industry");
    m.provinces.forEach((v) => p.add(new Option(v, v)));
    m.years.forEach((v) => y.add(new Option(String(v), String(v))));
    ind.innerHTML = "";
    m.industries.forEach((v) => ind.add(new Option(v, v)));
    $("health").textContent = "● 知识库 kb-2023 在线（" + m.provinces.length + " 省份 · 光伏成分 " + m.pv_overlap + "/" + m.pv_full + "）";
    await loadSegments();
    await loadRadar();
  } catch (e) {
    $("health").textContent = "● 服务连接失败";
    console.error(e);
  }
}

/* ---------------- 产业链出海 ---------------- */
async function loadSegments() {
  const d = await jget("/api/segments");
  $("chain-strip").innerHTML = d.items.map((s) => `
    <div class="chainbar ${CUR_SEGMENT === s.segment ? "on" : ""}" onclick="pickSegment('${esc(s.segment)}')"
         title="${esc(s.desc)}">
      <span class="cn">${esc(s.segment)}</span>
      <span class="cbar"><i style="width:${(s.ratio * 100).toFixed(1)}%"></i></span>
      <span class="cv">${(s.ratio * 100).toFixed(0)}% · ${s.demand_firms}/${s.firms}家 · ${s.deploy + s.intent}信号</span>
    </div>`).join("");
  $("chain-active").innerHTML = CUR_SEGMENT
    ? `当前环节：<b style="color:var(--gold)">${esc(CUR_SEGMENT)}</b>
       <a class="ev" onclick="pickSegment('')">✕ 清除筛选</a>`
    : "";
}

function pickSegment(seg) {
  CUR_SEGMENT = seg || null;
  loadSegments();
  loadRadar();
}

/* ---------------- 名单 ---------------- */
const DIR_CN = {
  market_expansion: "市场开拓", capacity_production: "产能出海",
  channel_supply_chain: "渠道供应链", local_organization_readiness: "本地准备",
  rd_localization: "研发本地化", investment_ma: "投资并购",
};

async function loadRadar() {
  const q = new URLSearchParams();
  if ($("f-province").value) q.set("province", $("f-province").value);
  if ($("f-year").value) q.set("year", $("f-year").value);
  if ($("f-industry").value && $("f-industry").value !== "全部") q.set("industry", $("f-industry").value);
  if (CUR_SEGMENT) q.set("segment", CUR_SEGMENT);
  q.set("sort", $("f-sort").value || "window");
  const d = await jget("/api/radar?" + q.toString() + "&limit=200");
  const body = $("radar-body");
  body.innerHTML = "";
  d.items.forEach((it, i) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td class="muted">${i + 1}</td>
      <td><b style="color:var(--head)">${esc(it.coname)}</b>
          ${it.industry_tags && it.industry_tags.includes("光伏") ? '<span class="tag" style="margin-left:6px">光伏</span>' : ""}
          <br><span class="muted">${esc(it.scode)}</span></td>
      <td>${esc(it.province)}</td>
      <td class="muted">${it.year}</td>
      <td><span class="tag w-${it.window_type}">${esc(it.window_label)}</span></td>
      <td><span class="tag st-${it.stage_layer}">${esc(it.stage_label)}</span></td>
      <td>${it.directions.map((x) => `<span class="dirchip">${DIR_CN[x] || x}</span>`).join("")}</td>
      <td>${it.countries.slice(0, 4).map((c) => `<span class="dirchip">${esc(c)}</span>`).join("")}
          ${it.regions.slice(0, 2).map((r) => `<span class="dirchip rc">区域·${esc(r)}</span>`).join("")}
          ${(!it.countries.length && !it.regions.length) ? '<span class="muted">—</span>' : ""}</td>
      <td>${it.overseas_cust_share != null ? `<span class="dirchip ov">${it.overseas_cust_share}%</span>` : '<span class="muted">—</span>'}</td>
      <td class="muted">${it.n_deploy} / ${it.n_intent}</td>
      <td class="score">${it.score}</td>`;
    tr.onclick = () => openCompany(it.scode, it.year);
    body.appendChild(tr);
  });
  $("radar-note").textContent =
    `共 ${d.items.length} 个出海需求企业-年（电气设备 2018-2023 全量样本）。排序：窗口期优先 → 落地层 > 筹备层 → 强度分。点击企业即按该行年度打开详情（年份上下文贯穿推理链与简报）。`;
}

/* ---------------- 企业详情 ---------------- */
function yearQs() { return CUR_YEAR ? `?year=${CUR_YEAR}` : ""; }

async function openCompany(scode, year = null) {
  CUR = scode;
  CUR_YEAR = year;
  const qs = yearQs();
  const [d, ch, sc, g] = await Promise.all([
    jget("/api/company/" + scode + qs),
    jget("/api/company/" + scode + "/chain" + qs),
    jget("/api/company/" + scode + "/supply-chain" + qs),
    jget("/api/company/" + scode + "/graph" + qs),
  ]);
  $("co-name").textContent = d.coname;
  $("co-sub").textContent = `${d.province} · ${d.industry} · 数据年度 ${d.year ?? "—"}`;
  $("co-tags").innerHTML =
    (d.window ? `<span class="tag w-${d.window.window_type}">${esc(d.window.window_label)}</span>` +
                `<span class="tag st-${d.window.stage_layer}">${esc(d.window.stage_label)}</span>` +
                `<span class="tag">强度分 ${d.window.score}</span>` : "") +
    `<span class="tag">能力「${esc(d.capability.grade)}」</span>`;
  renderCapability(d);
  renderChain(ch);
  renderSignals(d);
  renderSupplyChain(sc, scode);
  renderCountries(ch.countries || [], ch.regions || []);
  switchView("view-company");
}

function renderCapability(d) {
  const dims = d.capability.dims;
  $("radar-svg").innerHTML = radarSVG(dims);
  $("cap-grade").textContent = d.capability.grade;
  const comp = d.capability.completeness || {};
  $("cap-desc").textContent =
    (d.capability.score == null ? "评分 待核实" : "评分 " + d.capability.score.toFixed(2)) +
    " · " + d.capability.desc +
    (comp.total ? ` · 数据完整度 ${comp.available}/${comp.total}` : "");
  const v = (x, f) => x == null ? '<span class="muted">待核实</span>' : f(x);
  let kpi = `
    <div class="k">总资产（元）</div><div class="v">${v(d.assets, fmt)}</div>
    <div class="k">ROA</div><div class="v">${v(d.roa, pct)}</div>
    <div class="k">杠杆率</div><div class="v">${v(d.leverage, pct)}</div>
    <div class="k">研发强度</div><div class="v">${v(d.rd_intensity, pct)}</div>
    <div class="k">海外子公司</div><div class="v">${v(d.overseas_sub_count, (x) => x + " 家")}</div>
    <div class="k">海外收入占比</div><div class="v">${v(d.overseas_rev_share, pct)}</div>
    <div class="k">前五大客户集中度</div><div class="v">${v(d.customer_concentration, (x) => x.toFixed(1) + "%")}</div>
    <div class="k">前五大供应商集中度</div><div class="v">${v(d.supplier_concentration, (x) => x.toFixed(1) + "%")}</div>
    <div class="k">海外客户收入占比</div><div class="v">${v(d.overseas_customer_share, (x) => x.toFixed(1) + "%")}</div>`;
  if (d.data_completeness && d.data_completeness.missing.length) {
    kpi += `<div class="k" style="grid-column:1/-1;color:var(--gold-soft)">缺失待核实</div>
            <div class="v muted" style="grid-column:1/-1">${esc(d.data_completeness.missing.join("、"))}</div>`;
  }
  $("cap-kpi").innerHTML = kpi;
}

function fmt(x) { return x == null ? "—" : (x / 1e8).toFixed(1) + " 亿"; }
function pct(x) { return x == null ? "—" : (x * 100).toFixed(1) + "%"; }

function renderChain(ch) {
  const stepHtml = (s) => {
    let body = "";
    if (s.products && s.products.length) {
      body += '<div class="prods">' + s.products.map((p) => `
        <details class="prod">
          <summary><b style="color:var(--gold-soft)">${esc(p.name)}</b><span class="muted">（${esc(p.category)}）</span>
          ${p.n_signals > 1 ? `<span class="muted tiny"> · 命中 ${p.n_signals} 条信号</span>` : ""}</summary>
          <div class="prod-body">
            <div class="sd">${esc(p.reason)}</div>
            <div class="muted tiny">${esc(p.rule_id)} · 信号ID ${esc(p.signal_id || "—")}</div>
            ${p.evidence_id ? `<button type="button" class="evlink" data-ev="${esc(p.evidence_id)}">↗ 查看原文证据</button>` : ""}
          </div>
        </details>`).join("") + "</div>";
    }
    if (s.items && s.items.length) {
      body += '<ul class="prereq-list">' + s.items.map((x) => `<li><b>${esc(x)}</b></li>`).join("") + "</ul>";
    }
    const ev = s.evidence && s.evidence.evidence_id
      ? `<div class="se">证据：「${esc(s.evidence.quote || "")}」
           <button type="button" class="evlink" data-ev="${esc(s.evidence.evidence_id)}">↗ 查看原文</button></div>`
      : "";
    const meta = s.rule_id
      ? `<div class="muted tiny">${esc(s.rule_id)}${s.evidence && s.evidence.signal_id ? " · 信号ID " + esc(s.evidence.signal_id) : ""}</div>`
      : "";
    return `<div class="step">
      <div class="sl">${esc(s.label)}</div>
      <div class="st">${esc(s.title)}</div>
      <div class="sd">${esc(s.detail)}</div>${ev}${meta}${body}
    </div>`;
  };
  // 双栏布局：左窄（窗口期判定 / 出海方向与模式），右宽（产品匹配 / 前置条件）
  const win = ch.steps.find((s) => s.key === "window");
  const dir = ch.steps.find((s) => s.key === "direction");
  const prod = ch.steps.find((s) => s.key === "product");
  const pre = ch.steps.find((s) => s.key === "prereq");
  $("chain-steps").innerHTML =
    '<div class="chain-cols">' +
      `<div class="chain-col chain-left">${win ? stepHtml(win) : ""}${dir ? stepHtml(dir) : ""}</div>` +
      `<div class="chain-col chain-right">${prod ? stepHtml(prod) : ""}${pre ? stepHtml(pre) : ""}</div>` +
    "</div>" +
    (ch.as_of ? `<p class="muted tiny">口径：${esc(ch.as_of)}</p>` : "");
}

function renderSignals(d) {
  const sigHtml = d.signals.map(renderSig).join("") ||
    '<p class="muted">所选年度无需求类信号</p>';
  const hist = d.history || {};
  const histHtml = (hist.items && hist.items.length)
    ? `<div class="hist-note muted">历史信号 ${hist.count} 条（所选年度以前：${esc((hist.years || []).join("、"))}）——仅存档展示，不参与本年度产品推荐：</div>` +
      hist.items.map(renderSig).join("")
    : "";
  $("sig-list").innerHTML = sigHtml + histHtml;
}

function renderSig(c) {
  const geo = [
    ...(c.countries || []).map((x) => `<span class="dirchip">${esc(x)}</span>`),
    ...(c.regions || []).map((x) => `<span class="dirchip rc">区域·${esc(x)}</span>`),
  ].join("");
  return `
    <div class="sig">
      <div class="row1">
        <span class="tag">${c.year}</span>
        <span class="tag">${esc(c.program_label)}</span>
        <span class="dirchip">${DIR_CN[c.direction] || c.direction || "—"}</span>
        ${c.anchor ? `<span class="dirchip">锚点：${esc(c.anchor).slice(0, 26)}</span>` : ""}
        ${geo}
      </div>
      <div class="quote">「${esc(c.evidence_quote)}」</div>
      <button type="button" class="evlink" data-ev="${c.chunk_id}" data-start="${c.evidence_start}" data-end="${c.evidence_end}">↗ 查看原文证据 · ${esc(c.signal_id)}</button>
    </div>`;
}

function renderSupplyChain(sc, scode) {
  if (sc.nodes.length <= 1) {
    $("sc-svg").innerHTML = `<p class="muted">该企业未披露供应链明细。<br>
      供应链演示样例请查看示例企业：<a class="ev" onclick="openCompany('002860')">002860</a></p>`;
    $("sc-detail").innerHTML = "";
    $("sc-note").textContent = sc.note;
    return;
  }
  $("sc-svg").innerHTML = graphSVG(sc.nodes, sc.edges, 340);
  const dt = sc.detail || {};
  const row = (label, items) => items && items.length
    ? `<div class="sc-sec"><b>${label}</b>` + items.map((x) => `
        <div class="sc-row">
          <span class="sc-nm">${esc(x.name)}${x.overseas ? ' <span class="dirchip ov">境外</span>' : ""}${x.source === "text" ? ' <span class="dirchip rc">文本</span>' : ""}</span>
          <span class="sc-val muted">${x.proportion != null ? "占比 " + x.proportion + "%" : ""}</span>
        </div>`).join("") + "</div>" : "";
  let html = "";
  html += row("前五大客户（CSMAR 结构化）", (dt.customers || []).slice(0, 5));
  html += row("前五大供应商（CSMAR 结构化）", (dt.suppliers || []).slice(0, 5));
  if (dt.concentration) {
    html += `<div class="sc-sec"><b>集中度（${dt.concentration.year}）</b>
      <div class="sc-row"><span class="sc-nm">客户集中度</span><span class="sc-val muted">${dt.concentration.customer}%</span></div>
      <div class="sc-row"><span class="sc-nm">供应商集中度</span><span class="sc-val muted">${dt.concentration.purchase}%</span></div></div>`;
  }
  if (dt.two_hop && dt.two_hop.length) {
    html += `<div class="sc-sec"><b>二跳传导链</b>` + dt.two_hop.map((t) => `
      <div class="sc-row"><span class="sc-nm">${esc(t.b)} → ${esc(t.c)}</span>
      <span class="sc-val muted">我方${t.rel1} · 其${t.rel2} · ${t.year}</span></div>`).join("") + "</div>";
  }
  $("sc-detail").innerHTML = html;
  $("sc-note").textContent = sc.note;
}

function renderCountries(countries, regions = []) {
  const card = $("country-card");
  const items = [...countries, ...regions];
  if (!items.length) { card.style.display = "none"; return; }
  card.style.display = "block";
  $("country-body").innerHTML = items.slice(0, 4).map((c) => `
    <div style="border:1px solid var(--line);border-radius:8px;padding:9px 11px;margin-bottom:8px">
      <b style="color:var(--gold-soft)">${esc(c)}${regions.includes(c) ? ' <span class="tag rc">区域</span>' : ""}</b>
      <div class="muted" style="margin-top:3px" id="cc-${esc(c)}">加载中…</div>
    </div>`).join("");
  items.slice(0, 4).forEach(async (c) => {
    try {
      const info = await jget("/api/country/" + encodeURIComponent(c));
      const el = $("cc-" + esc(c));
      if (el) el.textContent = info.type === "country"
        ? `${info.region} · 清算：${info.clearing} · 避险：${info.hedging}`
        : `清算：${info.clearing}`;
    } catch (e) { /* 忽略 */ }
  });
}

/* ---------------- 证据弹窗 ---------------- */
async function showEvidence(chunkId, start = null, end = null) {
  let e;
  try {
    e = await jget("/api/evidence/" + chunkId);
  } catch (err) {
    console.error("evidence load failed", chunkId, err);
    alert("证据加载失败：" + chunkId);
    return;
  }
  $("modal-title").textContent = `原文证据 · ${e.coname} ${e.year} · ${e.section}`;
  $("modal-meta").textContent = e.program_label + " · 共 " + e.spans.length + " 条标注";
  $("modal-text").innerHTML = highlight(e.text, e.spans, start, end);
  $("modal-bg").classList.add("on");
}

function highlight(text, spans, focusStart, focusEnd) {
  const marks = spans.map((s) => ({ start: s.start, end: s.end, main: focusStart != null && s.start === focusStart }));
  marks.sort((a, b) => a.start - b.start);
  let html = "", pos = 0;
  for (const m of marks) {
    if (m.start < pos || m.end > text.length) continue;
    html += esc(text.slice(pos, m.start));
    html += `<mark${m.main ? ' style="outline:1px solid #d4af6a"' : ""}>${esc(text.slice(m.start, m.end))}</mark>`;
    pos = m.end;
  }
  html += esc(text.slice(pos));
  return html;
}

/* ---------------- 简报 ---------------- */
async function showBriefing() {
  const b = await jget("/api/company/" + CUR + "/briefing" + yearQs());
  $("brief-title").textContent = b.title;
  $("brief-sections").innerHTML = b.sections.map((s) => `
    <div class="sec"><h4>${esc(s.heading)}</h4><p>${esc(s.body)}</p>
    ${s.rule_ids && s.rule_ids.length ? `<div class="muted tiny">规则：${esc([...new Set(s.rule_ids)].join(" · "))}</div>` : ""}
    ${s.evidence_ids && s.evidence_ids.length ? `<div class="muted tiny">证据ID：${esc([...new Set(s.evidence_ids)].join(" · "))}</div>` : ""}
    </div>`).join("");
  switchView("view-briefing");
}

/* ---------------- SVG：雷达图（缺失维度显示待核实，不画顶点） ---------------- */
function radarSVG(dims, size = 320) {
  const cx = size / 2, cy = size / 2, R = size / 2 - 52, N = dims.length;
  const ang = (i) => -Math.PI / 2 + (i * 2 * Math.PI) / N;
  const pt = (i, r) => [cx + r * Math.cos(ang(i)), cy + r * Math.sin(ang(i))];
  const poly = (r) => Array.from({ length: N }, (_, i) => pt(i, r).map((v) => v.toFixed(1)).join(",")).join(" ");
  let svg = `<svg width="${size}" height="${size}" viewBox="0 0 ${size} ${size}">`;
  for (const g of [0.33, 0.66, 1]) {
    svg += `<polygon points="${poly(R * g)}" fill="none" stroke="rgba(255,255,255,.12)"/>`;
  }
  for (let i = 0; i < N; i++) {
    const [x, y] = pt(i, R);
    svg += `<line x1="${cx}" y1="${cy}" x2="${x.toFixed(1)}" y2="${y.toFixed(1)}" stroke="rgba(255,255,255,.10)"/>`;
  }
  const idxs = dims.map((d, i) => d.value == null ? null : i).filter((i) => i != null);
  if (idxs.length >= 3) {
    const dataPts = idxs.map((i) => pt(i, Math.max(0.05, dims[i].value) * R).map((v) => v.toFixed(1)).join(",")).join(" ");
    svg += `<polygon points="${dataPts}" fill="rgba(212,175,106,.25)" stroke="#d4af6a" stroke-width="1.5"/>`;
  }
  dims.forEach((d, i) => {
    const [x, y] = pt(i, R + 18);
    const anchor = Math.abs(x - cx) < 8 ? "middle" : x < cx ? "end" : "start";
    svg += `<text x="${x.toFixed(1)}" y="${(y + 4).toFixed(1)}" fill="#c9d4e2" font-size="11" text-anchor="${anchor}">${esc(d.label)}</text>`;
    if (d.value == null) {
      const [nx, ny] = pt(i, R - 10);
      svg += `<text x="${nx.toFixed(1)}" y="${ny.toFixed(1)}" fill="#8b9bb0" font-size="9" text-anchor="middle">待核实</text>`;
    } else {
      const [px, py] = pt(i, Math.max(0.05, d.value) * R);
      svg += `<text x="${px.toFixed(1)}" y="${(py - 6).toFixed(1)}" fill="#d4af6a" font-size="10" text-anchor="middle">${(d.value * 100).toFixed(0)}</text>`;
    }
  });
  return svg + "</svg>";
}

/* ---------------- SVG：关系图（圆形布局） ---------------- */
function graphSVG(nodes, edges, size = 340) {
  const cx = size / 2, cy = size / 2;
  const self = nodes.find((n) => n.type === "企业") || nodes[0];
  const others = nodes.filter((n) => n !== self);
  const R = size / 2 - 46;
  const pos = { [self.id]: [cx, cy] };
  others.forEach((n, i) => {
    const a = -Math.PI / 2 + (i * 2 * Math.PI) / Math.max(others.length, 1);
    pos[n.id] = [cx + R * Math.cos(a), cy + R * Math.sin(a)];
  });
  const color = { "企业": "#d4af6a", "客户": "#8fc4dd", "供应商": "#8fbfa8", "国家": "#7fae8e", "信号": "#c9d4e2", "方向": "#c98a7a" };
  let svg = `<svg width="${size}" height="${size}" viewBox="0 0 ${size} ${size}">`;
  for (const e of edges) {
    const [x1, y1] = pos[e.source], [x2, y2] = pos[e.target];
    svg += `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="rgba(212,175,106,.30)" stroke-width="1"/>`;
  }
  for (const n of nodes) {
    const [x, y] = pos[n.id];
    const c = color[n.type] || "#8b9bb0";
    svg += `<circle cx="${x}" cy="${y}" r="${n.type === "企业" ? 13 : 8}" fill="rgba(10,18,32,.9)" stroke="${c}" stroke-width="1.5"/>`;
    svg += `<text x="${x}" y="${y - (n.type === "企业" ? 20 : 14)}" fill="${c}" font-size="10.5" text-anchor="middle">${esc(n.label.length > 12 ? n.label.slice(0, 11) + "…" : n.label)}</text>`;
  }
  return svg + "</svg>";
}

/* ---------------- 视图切换 ---------------- */
function switchView(id) {
  document.querySelectorAll(".view").forEach((v) => v.classList.remove("on"));
  $(id).classList.add("on");
  window.scrollTo(0, 0);
}

$("btn-radar").onclick = () => { loadRadar(); switchView("view-radar"); };
$("back-radar").onclick = () => switchView("view-radar");
$("back-company").onclick = () => switchView("view-company");
$("btn-briefing").onclick = showBriefing;
$("f-province").onchange = loadRadar;
$("f-year").onchange = loadRadar;
$("f-sort").onchange = loadRadar;
$("f-industry").onchange = loadRadar;
$("modal-close").onclick = () => $("modal-bg").classList.remove("on");
$("modal-bg").onclick = (e) => { if (e.target === $("modal-bg")) $("modal-bg").classList.remove("on"); };
// 证据跳转：事件委托（data-ev → showEvidence），推理链与信号列表统一走此通道
function bindEvidence(containerId) {
  $(containerId).addEventListener("click", (e) => {
    const t = e.target && e.target.closest ? e.target.closest("[data-ev]") : null;
    if (!t || !t.dataset.ev) return;
    const start = t.dataset.start ? +t.dataset.start : null;
    const end = t.dataset.end ? +t.dataset.end : null;
    showEvidence(t.dataset.ev, start, end);
  });
}
bindEvidence("chain-steps");
bindEvidence("sig-list");

init();
