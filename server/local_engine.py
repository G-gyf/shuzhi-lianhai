# -*- coding: utf-8 -*-
"""本地规则分析引擎（降级/演示路径，方案 12.3 节）。

当 Coze 未启用或调用失败时，由本引擎基于受控工具结果确定性组装分析草稿：
- 事实块引用企业披露与结构化数值；假设块使用条件性表述；
- 候选服务关联已核实产品卡；已知条件不满足时标“待确认”，不冒充适配；
- 输出符合 analysis_draft 协议，由 analysis_service 校验后发布。
引擎标注 engine=rules-demo，回答中明确“规则演示”，不冒充生成式 AI 输出。
"""
from __future__ import annotations

import re

from . import products, runtime, tools

NUM_CN = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6,
          "七": 7, "八": 8, "九": 9, "十": 10}
NUM_CHARS = "一二两三四五六七八九十"

FINANCING_CATEGORY = "出海金融"

# 产品资格判定：无额外前置条件的产品可标 eligible；其余一律待确认（不冒充适配）
NO_PREREQ_PRODUCTS = {"account_setup", "advance_bond"}

# 有“境外主体”锚点时可确认的条件（其余仍待确认）
ANCHOR_CONDITIONS = {
    "overseas_entity": ["offshore", "treasury"],
}


def _history_summary(history: list[dict]) -> str:
    lines = []
    for h in history[-6:]:
        role = "经理" if h.get("role") == "user" else "助手"
        lines.append(f"{role}：{h.get('content', '')[:200]}")
    return "\n".join(lines)


def detect_intent(message: str, page: dict, history: list[dict]) -> str:
    m = message or ""
    if re.search(r"比较|对比|哪个更|优先拜访谁|区别", m):
        return "compare"
    if re.search(r"找|名单|筛选|有哪些|搜", m) and re.search(
            r"企业|公司|光伏|江苏|浙江|广东|山东|省|地区|行业|方向", m):
        if not re.search(r"这家|该企业|当前|它", m):
            return "search"
    if re.search(r"方案|拜访|简报|准备|计划|问题清单|怎么谈|话术|重点谈", m):
        return "plan"
    if re.search(r"为什么|为何|怎么|如何|什么|解释|含义|分数|入选|值得关注|分析|看看", m):
        return "explain"
    if re.search(r"帮助|用法|能做什么|使用说明|你好|谢谢|功能", m):
        return "general"
    if page.get("scode"):
        return "explain"
    return "general"


def _parse_preferences(message: str, prefs: dict) -> dict:
    """本轮明确要求优先于页面上下文/偏好；冲突在回答中说明采用范围。"""
    p = dict(prefs or {})
    service_focus = list(p.get("service_focus") or [])
    exclude_financing = bool(p.get("exclude_financing"))
    conflicts = []
    exclude_pat = re.search(r"不考虑融资|不要融资|排除融资|融资先不谈", message)
    if exclude_pat:
        if not exclude_financing:
            conflicts.append("本轮要求排除融资（覆盖了偏好默认）")
        exclude_financing = True
    elif "融资" in message:
        # 明确提及融资且无排除表述 → 纳入融资
        if exclude_financing:
            conflicts.append("本轮明确提及融资（覆盖了偏好排除）")
        exclude_financing = False
    for key, word in [("settlement", "结算"), ("guarantee", "保函"),
                      ("hedging", "避险"), ("treasury", "司库"),
                      ("financing", "融资"), ("account", "账户")]:
        if word in message:
            if key not in service_focus:
                service_focus.append(key)
    return {"service_focus": service_focus, "exclude_financing": exclude_financing,
            "plan_length": p.get("plan_length", "brief"),
            "conflicts": conflicts}


def _resolve_mentions(message: str, ctx: dict, page: dict, state: dict) -> tuple[list[str], list[str]]:
    """解析企业指代：'第二家'绑定上一条结果集的稳定ID；不按当前名单猜测。"""
    scodes, unresolved = [], []
    last = (state or {}).get("last_search") or {}
    items = last.get("items") or []
    m = re.search(r"第\s*([" + NUM_CHARS + r"\d]+)\s*家", message)
    if m:
        idx = int(NUM_CN.get(m.group(1), m.group(1)))
        if 1 <= idx <= len(items):
            scodes.append(items[idx - 1]["scode"])
        else:
            unresolved.append(f"第{idx}家")
    m2 = re.search(r"前\s*([" + NUM_CHARS + r"\d]+)\s*家", message)
    if m2 and re.search(r"比较|对比", message):
        n = int(NUM_CN.get(m2.group(1), m2.group(1)))
        if 1 <= n <= len(items):
            scodes.extend(it["scode"] for it in items[:n])
        else:
            unresolved.append(f"前{n}家")
    if not scodes:
        from . import logic
        names = logic._coname_map()
        scodes.extend(dict.fromkeys(code for code in re.findall(r"(?<!\d)\d{6}(?!\d)", message) if code in names))
    if not scodes:
        # 消息中出现样本内企业名（长度≥3）→ 直接解析
        from . import logic
        for scode, coname in logic._coname_map().items():
            if len(coname) >= 3 and coname in message:
                scodes.append(scode)
                break
    if not scodes and page.get("scode"):
        scodes.append(page["scode"])
    return scodes, unresolved


def _fmt_pct(x) -> str:
    return "待核实" if x is None else f"{x:.1f}%"


def _fmt_assets(x) -> str:
    return "待核实" if x is None else f"{x / 1e8:.1f} 亿元"


def _directions_cn(dirs) -> str:
    return "、".join(products.DIRECTION_CN.get(d, d) for d in dirs) or "未分类"


def _blocks_facts(d, refs) -> list[dict]:
    """事实块：引用披露与结构化数值；不使用未来记录作为历史事实。"""
    w = d.get("window") or {}
    blocks = []
    sig_refs = refs or []
    top_ref = sig_refs[0]["evidence_ref"] if sig_refs else None
    dirs = [s["direction"] for s in d.get("signals", [])]
    countries = sorted({c for s in d.get("signals", []) for c in s.get("countries", [])})
    regions = sorted({c for s in d.get("signals", []) for c in s.get("regions", [])})
    if w:
        blocks.append({
            "kind": "fact",
            "text": (f"{d['coname']}（{d['scode']}）在 {d['year']} 年度处于「{w.get('window_label')}」窗口"
                     f"（{w.get('stage_label')}），强度分 {w.get('score')}。"
                     f"当年披露方向：{_directions_cn(sorted(set(dirs)))}；"
                     f"目标国别：{'、'.join(countries) if countries else '未披露明确国别'}"
                     + (f"；区域表述：{'、'.join(regions)}。" if regions else "。")),
            "refs": [top_ref] if top_ref else [],
        })
    sc = d.get("sc") or {}
    sc_parts = []
    if sc.get("customer_concentration") is not None:
        sc_parts.append(f"前五大客户集中度 {sc['customer_concentration']:.1f}%")
    if sc.get("overseas_customer_share") is not None:
        sc_parts.append(f"海外客户收入占比 {sc['overseas_customer_share']:.1f}%（前五大口径）")
    if sc.get("supplier_concentration") is not None:
        sc_parts.append(f"前五大供应商集中度 {sc['supplier_concentration']:.1f}%")
    if sc_parts:
        blocks.append({"kind": "fact", "text": "结构化供应链：" + "；".join(sc_parts) + "。",
                       "refs": list((d.get("metric_refs") or {}).values())[:2]})
    cap = d.get("capability") or {}
    comp = cap.get("completeness") or {}
    cap_txt = (f"能力评分 {cap['score']:.2f}（{cap['grade']}），数据完整度 "
               f"{comp.get('available', 0)}/{comp.get('total', 0)}"
               + (f"；缺失维度：{'、'.join(comp.get('missing', []))}" if comp.get("missing") else ""))
    blocks.append({"kind": "fact", "text": f"能力画像：{cap_txt}。本项为辅助判断，不替代人工尽调。",
                   "refs": []})
    missing = (d.get("panel") or {}).get("missing") or []
    if missing:
        blocks.append({"kind": "checklist",
                       "text": f"面板缺失字段（待核实）：{'、'.join(missing)}。缺失按“待核实”处理，不补 0、不取其他年度。",
                       "refs": []})
    return blocks


def _recs_for(d, prefs, ctx, top_ev_ref) -> tuple[list[dict], list[dict], list[str]]:
    """候选服务：关联已核实产品卡；条件不满足→待确认；偏好改变候选不改写事实。"""
    candidates = d.get("rule_candidates") or []
    focus = prefs.get("service_focus") or []
    exclude_fin = prefs.get("exclude_financing")
    recs, questions, warnings = [], [], []

    def focus_hit(name, category, keywords_text):
        if not focus:
            return True
        text = name + category + keywords_text
        for f in focus:
            for w in products.FOCUS_KEYWORDS.get(f, [f]):
                if w in text:
                    return True
        return False

    for i, c in enumerate(candidates):
        card = products.get_card(c["key"]) or {}
        text_scope = " ".join([c["name"], c["category"],
                               " ".join(card.get("keywords", []))])
        if not focus_hit(c["name"], c["category"], text_scope):
            continue
        if exclude_fin and c["category"] == FINANCING_CATEGORY:
            continue
        # 资格判定：无前置→eligible；有境外主体锚点且产品在其确认表→eligible；否则待确认
        eligibility, missing = "unknown", list(card.get("conditions") or [])
        if c["key"] in NO_PREREQ_PRODUCTS:
            eligibility, missing = "eligible", []
        anchors = {s.get("anchor_type") for s in d.get("signals", [])}
        if c["key"] in ANCHOR_CONDITIONS.get("overseas_entity", []) and \
                "overseas_entity" in anchors:
            eligibility = "eligible"
            missing = []
        missing = missing + list(card.get("need_verify") or [])
        recs.append({
            "id": f"rec_{c['key']}_{i}",
            "product_ref": c["product_ref"],
            "priority": "discussion_first" if i < 3 else "standard",
            "reason": f"规则命中：{c['reason']}。"
                      + (f"本轮偏好聚焦“{'、'.join(focus)}”，候选按此收窄。" if focus else "")
                      + (f"本轮排除融资类服务。" if exclude_fin and c["category"] == FINANCING_CATEGORY else ""),
            "evidence_refs": [top_ev_ref] if top_ev_ref else [],
            "product_source_refs": [c["product_ref"]],
            "eligibility": eligibility,
            "missing_conditions": missing,
            "_name": c["name"],
            "_category": c["category"],
            "_status": c["card_status"],
        })
        if c["card_status"] == "placeholder":
            warnings.append(f"{c['name']} 产品卡未经资料核实（placeholder），仅列讨论方向，不构成正式适配建议。")

    # 拜访问题（每个候选一条 + 企业通用待核实）
    for r in recs[:5]:
        name = r.get("_name", "")
        if r["missing_conditions"]:
            questions.append({"text": f"{name}：{'、'.join(r['missing_conditions'][:2])}是否已具备？",
                              "related_recommendation": r["id"]})
        else:
            questions.append({"text": f"{name}：贵司当前结算与担保安排如何，是否需要我行协助梳理？",
                              "related_recommendation": r["id"]})
    return recs, questions, warnings


def _build_orbs(d, recs, kind_extra=None) -> list[dict]:
    """后端根据合法引用构建光球；AI 方案球标注为分析结果，不冒充原文。"""
    orbs: list[dict] = []
    for ref in (d.get("signal_refs") or [])[:2]:
        orbs.append({"id": f"orb_ev_{ref['signal_id'].replace('#', '_')}",
                     "kind": "evidence", "label": "原文依据",
                     "summary": f"{ref['year']} · {products.DIRECTION_CN.get(ref['direction'], ref['direction'])}",
                     "ref_id": ref["evidence_ref"], "state": "ready"})
    for r in recs[:2]:
        orbs.append({"id": f"orb_pr_{r['id']}", "kind": "product",
                     "label": r.get("_name", "产品依据"),
                     "summary": f"{r.get('_category', '')} · {'待确认条件' if r['missing_conditions'] else '条件已满足'}",
                     "ref_id": r["product_ref"], "state": "ready"})
    pend = sorted({c for r in recs for c in r["missing_conditions"]})
    orbs.append({"id": "orb_checklist", "kind": "checklist", "label": "待核实事项",
                 "summary": f"{len(pend)} 项待确认" if pend else "无待确认事项",
                 "ref_id": None, "state": "ready"})
    return orbs


def _history_note(year) -> str | None:
    if year is None or int(year) >= 2023:
        return None
    return (f"提示：本分析基于 {year} 年度历史企业资料、采用当前服务资料的演示建议，"
            "不冒充当时可用方案（方案 1.1 节）。")


def run(message: str, ctx: dict, page: dict, prefs: dict, history: list[dict],
        state: dict, request_id: str = "") -> dict:
    """主入口：返回 analysis_draft 字典。"""
    intent = detect_intent(message, page, history)
    prefs = _parse_preferences(message, prefs)
    warnings: list[str] = []
    answer_blocks: list[dict] = []
    recommendations: list[dict] = []
    questions: list[dict] = []
    orbs: list[dict] = []
    context = {"scode": page.get("scode"), "year": page.get("year"),
               "snapshot_id": runtime.get_snapshot(),
               "product_version": products.product_version()}

    if intent == "general":
        answer_blocks.append({
            "kind": "note",
            "text": ("数智链海对话工作台（规则演示模式）：可执行 找企业（按地区/产业/方向筛选）、"
                     "解释企业（入选依据/画像/集中度）、数据分析、企业比较（同一年度）、"
                     "定制拜访方案（结合服务偏好与产品资料）与生成拜访清单。"
                     "当前 Coze 工作流未接入，回答由本地规则引擎按数据库事实确定性生成；"
                     "接入 Coze 后将支持自然语言连续追问与 AI 综合分析。"),
            "refs": [],
        })
    elif intent == "search":
        scodes, unresolved = _resolve_mentions(message, ctx, page, state)
        params = {}
        m = re.search(r"省", message)
        provinces = ["江苏省", "浙江省", "山东省", "广东省", "四川省", "安徽省",
                     "湖北省", "湖南省", "河南省", "河北省", "福建省", "江西省"]
        for pv in provinces:
            if pv in message:
                params["province"] = pv
                break
        if "光伏" in message:
            params["industry"] = "光伏"
        if "电气" in message and "光伏" not in message:
            params["industry"] = "电气设备"
        for word, segment in [("风电", "风电设备"), ("储能", "储能与电源"),
                              ("电网", "电网设备"), ("工业控制", "工业控制"),
                              ("家电", "家电消费")]:
            if word in message:
                params["industry"] = segment
                break
        if re.search(r"产能|建厂|绿地", message):
            params["direction"] = "capacity_production"
        elif re.search(r"投资并购|并购", message):
            params["direction"] = "investment_ma"
        elif re.search(r"市场开拓|开拓", message):
            params["direction"] = "market_expansion"
        if re.search(r"\b20(18|19|20|21|22|23)\b", message):
            params["year"] = int(re.search(r"\b20(18|19|20|21|22|23)\b", message).group(0))
        elif re.search(r"最近", message):
            params["year"] = max(logic_years())
        r = tools.search_companies(ctx, **params)
        items = r["items"]
        listing = "、".join(
            f"{it['coname']}（{it['scode']}，{it['province']}，{it['year']}，{it['window_label']}）"
            for it in items[:8])
        answer_blocks.append({
            "kind": "fact",
            "text": (f"共 {r['total']} 个企业-年符合条件" +
                     (f"（{params.get('province')}）" if params.get("province") else "") +
                     f"。前 {min(len(items), 8)} 家：{listing}。" +
                     (f" 可翻页；‘最近’按最新可用数据年度（{r['filter_explanation'].get('year', '最新年度')}）解释，不擅称实时。"
                      if re.search(r"最近", message) else "")),
            "refs": [],
        })
        for it in items[:5]:
            orbs.append({"id": f"orb_co_{it['scode']}_{it['year']}", "kind": "company",
                         "label": it["coname"], "summary": f"{it['province']} · {it['year']} · {it['window_label']}",
                         "ref_id": f"company:{it['scode']}:{it['year']}", "state": "ready"})
        answer_blocks.append({"kind": "note", "text": "点击企业光球打开该企业详情；追问“第二家”绑定本条结果集。", "refs": []})
        # 记录本结果集供指代解析
        state_last = {"items": items, "total": r["total"]}
        context["scode"] = None
        context["year"] = params.get("year")
        return _draft(context, answer_blocks, [], [], orbs, warnings, state_last,
                      request_id, intent)

    elif intent == "compare":
        scodes, unresolved = _resolve_mentions(message, ctx, page, state)
        if len(scodes) < 2:
            return {"clarify": True, "options": [],
                    "message": ("请指定要比较的企业：例如“比较前两家”绑定上一条名单结果，"
                                "或在消息中给出企业代码/名称（如“比较 002860 与 600388”）。")}
        year = page.get("year")
        r = tools.compare_companies(ctx, scodes, year)
        rows = r["companies"]
        lines = []
        for row in rows:
            w = row.get("window") or {}
            lines.append(
                f"{row['coname']}（{row['scode']}）：{w.get('window_label', '无窗口')}"
                f"（{w.get('stage_label', '—')}），强度分 {w.get('score', '—')}；"
                f"能力 {row['capability']['grade']}"
                + (f"（评分 {row['capability']['score']:.2f}）" if row['capability']['score'] is not None else "")
                + f"；客户集中度 {_fmt_pct(row['customer_concentration'])}；"
                f"海外客户占比 {_fmt_pct(row['overseas_customer_share'])}。")
        answer_blocks.append({"kind": "fact",
                              "text": f"同一年度（{r['year']}）对比：" + " ".join(lines),
                              "refs": [r["compare_ref"]]})
        for row in rows:
            miss = next((m for m in r["missing"] if m["scode"] == row["scode"]), None)
            if miss:
                answer_blocks.append({"kind": "checklist",
                                      "text": f"{row['coname']} 缺失：{'、'.join(miss['missing'])}（待核实，不补 0、不取其他年度）。",
                                      "refs": []})
        # 拜访优先级（确定性依据：窗口期+分层+强度分；不声称转化概率更高）
        order = sorted(rows, key=lambda x: (
            (x.get("window") or {}).get("window_type", "z"),
            (x.get("window") or {}).get("stage_layer", "z"),
            -((x.get("window") or {}).get("score") or 0)))
        first = order[0]
        answer_blocks.append({"kind": "hypothesis",
                              "text": (f"若以窗口期与强度分为优先依据，建议先拜访 {first['coname']}："
                                       f"其窗口类型排序更靠前、强度分更高。这是规则排序理由，"
                                       "不声称转化概率更高；建议结合客户关系与产能情况人工确认。"),
                              "refs": []})
        recommendations.append({
            "id": "rec_visit_priority", "product_ref": None,
            "priority": "discussion_first",
            "reason": "对比排序理由：窗口类型→分层→强度分（确定性规则），不声称转化概率更高。",
            "evidence_refs": [], "product_source_refs": [],
            "eligibility": "unknown",
            "missing_conditions": ["客户当前需求与业务背景（资料不足，列出缺项）"],
            "_name": "拜访优先级建议", "_category": "分析结论",
        })
        questions.append({"text": "两家企业当前出海项目进度与资金安排分别如何？",
                          "related_recommendation": "rec_visit_priority"})
        orbs.append({"id": "orb_cmp", "kind": "compare", "label": "对比详情",
                     "summary": f"{len(rows)} 家 · 同一年度 {r['year']}",
                     "ref_id": r["compare_ref"], "state": "ready"})
        for row in rows:
            orbs.append({"id": f"orb_cmp_co_{row['scode']}", "kind": "company",
                         "label": row["coname"],
                         "summary": f"{row['province']} · {row['year']}",
                         "ref_id": f"company:{row['scode']}:{row['year']}", "state": "ready"})
        return _draft(context, answer_blocks, recommendations, questions, orbs,
                      warnings, state, request_id, intent)

    elif intent in ("explain", "plan"):
        scodes, unresolved = _resolve_mentions(message, ctx, page, state)
        if not scodes:
            return {"clarify": True, "options": [],
                    "message": "请先指定企业：打开企业详情后直接提问，或输入企业名称/代码。"}
        scode = scodes[0]
        year = page.get("year") if page.get("scode") == scode else None
        explicit_year = re.search(r"(?<!\d)20\d{2}(?!\d)", message)
        if explicit_year:
            year = int(explicit_year.group(0))
        d = tools.get_company_context(ctx, scode, year)
        if not d.get("ok"):
            answer_blocks.append({"kind": "note", "text": d.get("error", "企业上下文获取失败"), "refs": []})
            return _draft(context, answer_blocks, [], [], [], warnings, state, request_id, intent)
        context["scode"], context["coname"], context["year"] = d["scode"], d["coname"], d["year"]
        top_ev = (d.get("signal_refs") or [{}])[0].get("evidence_ref")
        answer_blocks += _blocks_facts(d, d.get("signal_refs") or [])
        recs, questions, warnings = _recs_for(d, prefs, ctx, top_ev)
        recommendations = [{k: v for k, v in r.items() if not k.startswith("_")} for r in recs]

        if recs:
            names = "、".join(f"{r['_name']}（{r['_category']}）" for r in recs[:5])
            answer_blocks.append({
                "kind": "product",
                "text": (f"规则候选服务（{d['year']} 年度信号，历史信号不参与）：{names}。"
                         + (f"本轮聚焦“{'、'.join(prefs['service_focus'])}”，已收窄候选。" if prefs["service_focus"] else "")
                         + (" 已按本轮要求排除融资类服务。" if prefs["exclude_financing"] else "")),
                "refs": [r["product_ref"] for r in recs[:5] if r.get("product_ref")],
            })
        else:
            answer_blocks.append({"kind": "checklist",
                                  "text": "按当前偏好过滤后无规则候选（可能全部被排除），请调整服务偏好或确认需求。",
                                  "refs": []})
        # 假设块：需求假设（条件性表述）
        dirs = sorted({s["direction"] for s in d.get("signals", [])})
        if dirs:
            needs = "、".join(products.DIRECTION_CN.get(x, x) for x in dirs)
            answer_blocks.append({"kind": "hypothesis",
                                  "text": (f"需求假设：基于 {needs} 方向的披露，企业若推进落地，"
                                           "预计产生开户、结算与担保类需求；是否属实需与客户确认，"
                                           "本假设不改写企业事实。"),
                                  "refs": [top_ev] if top_ev else []})
        if intent == "plan":
            answer_blocks.append({"kind": "note",
                                  "text": ("访前方案（规则演示）：下列为建议讨论顺序与拜访问题。"
                                           "可继续要求“做一页简报”，将复用本分析，不重算事实。"),
                                  "refs": []})
        else:
            answer_blocks.append({"kind": "note",
                                  "text": ("以上依据可点击光球核查；AI 方案球标注为分析结果，"
                                           "不冒充原文事实。"), "refs": []})
        orbs = _build_orbs(d, recs)
        if recs:
            orbs.append({"id": "orb_analysis", "kind": "analysis", "label": "方案分析",
                         "summary": f"规则演示 · {len(recs)} 个候选 · 结合{('、'.join(prefs['service_focus']) if prefs['service_focus'] else '全量')}偏好",
                         "ref_id": None, "state": "ready"})
        note = _history_note(d["year"])
        if note:
            warnings.append(note)
        for c in prefs.get("conflicts", []):
            warnings.append(c)
        return _draft(context, answer_blocks, recommendations, questions, orbs,
                      warnings, state, request_id, intent)

    return _draft(context, answer_blocks, recommendations, questions, orbs,
                  warnings, state, request_id, intent)


def logic_years():
    from . import logic
    return logic.years()


def _draft(context, blocks, recs, questions, orbs, warnings, state, request_id, intent):
    import time
    now = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    warnings.append("当前为本地规则引擎演示输出（Coze 未接入或调用失败时的降级路径）；"
                    "事实引用来自确定性数据库，分析组合由规则生成，未经生成式模型加工。")
    # state 兼容两种形态：{"last_search": {...}}（会话状态）或直接为结果集 {"items": [...]}
    last_search = state.get("last_search") if isinstance(state, dict) and "last_search" in state \
        else (state if isinstance(state, dict) and "items" in state else None)
    return {
        "schema_version": "1.0",
        "context": context,
        "status": "draft",
        "answer_blocks": blocks,
        "recommendations": recs,
        "questions": questions,
        "orbs": orbs,
        "warnings": warnings,
        "provenance": {"engine": "rules-demo", "workflow_version": "local-rules-v1",
                       "generated_at": now, "request_id": request_id},
        "_state": {"last_search": last_search, "intent": intent},
    }
