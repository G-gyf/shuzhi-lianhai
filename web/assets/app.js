/* 数智链海 · 最小闭环前端（零外部依赖：SVG 手绘雷达图与关系图） */
const API = window.DSH_API_BASE || "";
let CUR = null; // 当前企业 scode

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
    const p = $("f-province"), y = $("f-year");
    m.provinces.forEach((v) => p.add(new Option(v, v)));
    m.years.forEach((v) => y.add(new Option(String(v), String(v))));
    $("health").textContent = "● 知识库 kb-2023 在线（" + m.provinces.length + " 省份）";
    await loadRadar();
  } catch (e) {
    $("health").textContent = "● 服务连接失败";
    console.error(e);
  }
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
  const d = await jget("/api/radar?" + q.toString() + "&limit=200");
  const body = $("radar-body");
  body.innerHTML = "";
  d.items.forEach((it, i) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td class="muted">${i + 1}</td>
      <td><b style="color:var(--head)">${esc(it.coname)}</b><br><span class="muted">${esc(it.scode)}</span></td>
      <td>${esc(it.province)}</td>
      <td class="muted">${it.year}</td>
      <td><span class="tag w-${it.window_type}">${esc(it.window_label)}</span></td>
      <td><span class="tag st-${it.stage_layer}">${esc(it.stage_label)}</span></td>
      <td>${it.directions.map((x) => `<span class="dirchip">${DIR_CN[x] || x}</span>`).join("")}</td>
      <td>${it.countries.slice(0, 4).map((c) => `<span class="dirchip">${esc(c)}</span>`).join("") || '<span class="muted">—</span>'}</td>
      <td class="muted">${it.n_deploy} / ${it.n_intent}</td>
      <td class="score">${it.score}</td>`;
    tr.onclick = () => openCompany(it.scode);
    body.appendChild(tr);
  });
  $("radar-note").textContent =
    `共 ${d.items.length} 个出海需求企业-年（电气设备 2018-2023 全量样本）。排序：窗口期优先 → 落地层 > 筹备层 → 强度分。`;
}

/* ---------------- 企业详情 ---------------- */
async function openCompany(scode) {
  CUR = scode;
  const [d, ch, sc, g] = await Promise.all([
    jget("/api/company/" + scode),
    jget("/api/company/" + scode + "/chain"),
    jget("/api/company/" + scode + "/supply-chain"),
    jget("/api/company/" + scode + "/graph"),
  ]);
  $("co-name").textContent = d.coname;
  $("co-sub").textContent = `${d.province} · ${d.industry} · 数据年度 ${d.year}`;
  $("co-tags").innerHTML =
    (d.window ? `<span class="tag w-${d.window.window_type}">${esc(d.window.window_label)}</span>` +
                `<span class="tag st-${d.window.stage_layer}">${esc(d.window.stage_label)}</span>` +
                `<span class="tag">强度分 ${d.window.score}</span>` : "") +
    `<span class="tag">能力「${esc(d.capability.grade)}」</span>`;
  renderCapability(d);
  renderChain(ch);
  renderSignals(d);
  renderSupplyChain(sc, scode);
  renderCountries(ch.countries || []);
  switchView("view-company");
}

function renderCapability(d) {
  const dims = d.capability.dims;
  $("radar-svg").innerHTML = radarSVG(dims);
  $("cap-grade").textContent = d.capability.grade;
  $("cap-desc").textContent = `评分 ${d.capability.score} · ${d.capability.desc}`;
  $("cap-kpi").innerHTML = `
    <div class="k">总资产（元）</div><div class="v">${fmt(d.assets)}</div>
    <div class="k">ROA</div><div class="v">${pct(d.roa)}</div>
    <div class="k">杠杆率</div><div class="v">${pct(d.leverage)}</div>
    <div class="k">研发强度</div><div class="v">${pct(d.rd_intensity)}</div>
    <div class="k">海外子公司</div><div class="v">${d.overseas_sub_count} 家</div>
    <div class="k">海外收入占比</div><div class="v">${pct(d.overseas_rev_share)}</div>`;
}

function fmt(x) { return x == null ? "—" : (x / 1e8).toFixed(1) + " 亿"; }
function pct(x) { return x == null ? "—" : (x * 100).toFixed(1) + "%"; }

function renderChain(ch) {
  $("chain-steps").innerHTML = ch.steps.map((s) => `
    <div class="step">
      <div class="sl">${esc(s.label)}</div>
      <div class="st">${esc(s.title)}</div>
      <div class="sd">${esc(s.detail)}</div>
      ${s.evidence ? `<div class="se">证据：「${esc(s.evidence)}」</div>` : ""}
    </div>`).join("");
}

function renderSignals(d) {
  const list = $("sig-list");
  list.innerHTML = d.claims.map((c) => `
    <div class="sig">
      <div class="row1">
        <span class="tag">${c.year}</span>
        <span class="tag">${esc(c.program_label)}</span>
        <span class="dirchip">${DIR_CN[c.direction] || c.direction || "—"}</span>
        ${c.anchor ? `<span class="dirchip">锚点：${esc(c.anchor).slice(0, 26)}</span>` : ""}
      </div>
      <div class="quote">「${esc(c.evidence_quote)}」</div>
      <div class="ev" onclick="showEvidence('${c.chunk_id}', ${c.evidence_start}, ${c.evidence_end})">↗ 查看原文证据</div>
    </div>`).join("") || '<p class="muted">无需求类信号</p>';
}

function renderSupplyChain(sc, scode) {
  if (sc.nodes.length <= 1) {
    $("sc-svg").innerHTML = `<p class="muted">该企业未披露具名客户（named_customer 锚点缺失）。<br>
      供应链演示样例请查看示例企业：<a class="ev" onclick="openCompany('002860')">002860（浙江 · 客户含美的/LG 等）</a></p>`;
    $("sc-note").textContent = sc.note;
    return;
  }
  $("sc-svg").innerHTML = graphSVG(sc.nodes, sc.edges, 340);
  $("sc-note").textContent = sc.note;
}

function renderCountries(countries) {
  const card = $("country-card");
  if (!countries.length) { card.style.display = "none"; return; }
  card.style.display = "block";
  $("country-body").innerHTML = countries.slice(0, 4).map((c) => `
    <div style="border:1px solid var(--line);border-radius:8px;padding:9px 11px;margin-bottom:8px">
      <b style="color:var(--gold-soft)">${esc(c)}</b>
      <div class="muted" style="margin-top:3px" id="cc-${esc(c)}">加载中…</div>
    </div>`).join("");
  countries.slice(0, 4).forEach(async (c) => {
    try {
      const info = await jget("/api/country/" + encodeURIComponent(c));
      const el = $("cc-" + esc(c));
      if (el) el.textContent = `${info.region} · 清算：${info.clearing} · 避险：${info.hedging}`;
    } catch (e) { /* 忽略 */ }
  });
}

/* ---------------- 证据弹窗 ---------------- */
async function showEvidence(chunkId, start, end) {
  const e = await jget("/api/evidence/" + chunkId);
  $("modal-title").textContent = `原文证据 · ${e.coname} ${e.year} · ${e.section}`;
  $("modal-meta").textContent = e.program_label + " · 共 " + e.spans.length + " 条标注";
  $("modal-text").innerHTML = highlight(e.text, e.spans, start, end);
  $("modal-bg").classList.add("on");
}

function highlight(text, spans, focusStart, focusEnd) {
  const marks = spans.map((s) => ({ start: s.start, end: s.end, main: s.start === focusStart }));
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
  const b = await jget("/api/company/" + CUR + "/briefing");
  $("brief-title").textContent = b.title;
  $("brief-sections").innerHTML = b.sections.map((s) => `
    <div class="sec"><h4>${esc(s.heading)}</h4><p>${esc(s.body)}</p></div>`).join("");
  switchView("view-briefing");
}

/* ---------------- SVG：雷达图 ---------------- */
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
  const dataPts = dims.map((d, i) => pt(i, Math.max(0.05, d.value) * R).map((v) => v.toFixed(1)).join(",")).join(" ");
  svg += `<polygon points="${dataPts}" fill="rgba(212,175,106,.25)" stroke="#d4af6a" stroke-width="1.5"/>`;
  dims.forEach((d, i) => {
    const [x, y] = pt(i, R + 18);
    const anchor = Math.abs(x - cx) < 8 ? "middle" : x < cx ? "end" : "start";
    svg += `<text x="${x.toFixed(1)}" y="${(y + 4).toFixed(1)}" fill="#c9d4e2" font-size="11" text-anchor="${anchor}">${esc(d.label)}</text>`;
    const [px, py] = pt(i, Math.max(0.05, d.value) * R);
    svg += `<text x="${px.toFixed(1)}" y="${(py - 6).toFixed(1)}" fill="#d4af6a" font-size="10" text-anchor="middle">${(d.value * 100).toFixed(0)}</text>`;
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
  const color = { "企业": "#d4af6a", "客户": "#8fc4dd", "国家": "#7fae8e", "信号": "#c9d4e2", "方向": "#c98a7a" };
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
$("modal-close").onclick = () => $("modal-bg").classList.remove("on");
$("modal-bg").onclick = (e) => { if (e.target === $("modal-bg")) $("modal-bg").classList.remove("on"); };

init();
