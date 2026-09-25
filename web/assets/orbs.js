/* 光球渲染与引用定位（orbs.js）
   每个球同时有图形、中文标签和数量；颜色只辅助区分。
   首次最多展示 3—5 个主球，其余收入“更多依据”展开。
   点击球 → 打开对应依据抽屉；点击球也能高亮其支持的回答段落。 */
window.DSHOrbs = (() => {
  const KIND_CN = {
    evidence: "原文依据", product: "产品依据", analysis: "AI方案",
    compare: "对比详情", company: "企业", profile: "画像依据",
    checklist: "待核实事项", regional: "地区资料",
  };

  function esc(s) {
    return String(s ?? "").replace(/[&<>"]/g,
      (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  }

  const tip = {
    el: null,
    show(text, anchor) {
      this.hide();
      this.el = document.createElement("div");
      this.el.className = "orb-tip";
      this.el.textContent = text;
      document.body.appendChild(this.el);
      const r = anchor.getBoundingClientRect();
      this.el.style.left = Math.max(8, r.left) + "px";
      this.el.style.top = (r.top - 34) + "px";
    },
    hide() { if (this.el) { this.el.remove(); this.el = null; } },
  };

  function orbBtn(o, count, bubbleEl) {
    const b = document.createElement("button");
    b.type = "button";
    b.className = `orb kind-${o.kind} lit`;
    b.dataset.ref = o.ref_id || "";
    b.setAttribute("aria-label", `${o.label}：${o.summary || ""}`);
    b.innerHTML = `<i></i><span>${esc(o.label || KIND_CN[o.kind] || o.kind)}</span>` +
      (count > 1 ? `<span class="orb-count">${count}</span>` : "");
    if (o.summary) {
      b.addEventListener("mouseenter", () => tip.show(o.summary, b));
      b.addEventListener("mouseleave", tip.hide);
      b.addEventListener("focus", () => tip.show(o.summary, b));
      b.addEventListener("blur", tip.hide);
    }
    b.addEventListener("click", () => {
      b.classList.add("viewed");
      if (o.ref_id) window.DSHDrawer.open(o.ref_id, `${o.label} · ${o.summary || ""}`);
      else window.DSHDrawer.openList(o, `${o.label}`);
      highlightBlocks(bubbleEl, o.ref_id);
    });
    return b;
  }

  function highlightBlocks(bubbleEl, refId) {
    if (!bubbleEl || !refId) return;
    bubbleEl.querySelectorAll(".blk").forEach((blk) => {
      if ((blk.dataset.refs || "").split("|").includes(refId)) {
        blk.classList.add("hl-ref");
        setTimeout(() => blk.classList.remove("hl-ref"), 1600);
      }
    });
  }

  function render(container, orbs, bubbleEl) {
    const box = document.createElement("div");
    box.className = "orb-bar";
    const list = orbs || [];
    const main = list.filter((o) => o.main !== false);
    const more = list.filter((o) => o.main === false);
    // 同标签合并计数（图形+中文标签+数量）
    const groups = new Map();
    for (const o of main) {
      const key = o.kind + "|" + (o.label || "");
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(o);
    }
    // 依次点亮（固定位置，轻微呼吸，不持续漂移）
    const entries = [...groups.values()];
    let i = 0;
    const timer = setInterval(() => {
      const grp = entries[i];
      if (!grp) { clearInterval(timer); maybeAddMore(); return; }
      box.appendChild(orbBtn(grp[0], grp.length, bubbleEl));
      i++;
    }, 140);

    function maybeAddMore() {
      if (!more.length) return;
      const b = document.createElement("button");
      b.type = "button";
      b.className = "orb";
      b.innerHTML = `<i></i><span>更多依据（${more.length}）</span>`;
      const extra = document.createElement("div");
      extra.className = "orb-bar";
      extra.style.display = "none";
      more.forEach((o, idx) => {
        setTimeout(() => extra.appendChild(orbBtn(o, 1, bubbleEl)), idx * 100);
      });
      b.onclick = () => {
        extra.style.display = extra.style.display === "none" ? "flex" : "none";
        b.textContent = extra.style.display === "none"
          ? `更多依据（${more.length}）` : "收起更多依据";
      };
      box.appendChild(b);
      box.appendChild(extra);
    }

    container.appendChild(box);
    return box;
  }

  return { render, KIND_CN };
})();
