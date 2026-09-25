# -*- coding: utf-8 -*-
"""受控业务工具（方案 7.1 节白名单）。

- 精确筛选、统计、时间截取、引用解析一律由本层完成，不让模型替代算数与查询。
- 每个工具接收 ToolContext（身份/地区/快照/允许工具），权限检查在工具内完成。
- 首版不开放任意 SQL 与任意网址抓取。
"""
from __future__ import annotations

import json
from functools import lru_cache

import pandas as pd

from . import logic, products, runtime
from .schemas import (compare_ref, ev_ref, metric_ref, product_ref)

# 对比上限（项目配置，不是平台额度声明）
MAX_COMPARE = 3

DIRECTION_CN = products.DIRECTION_CN

TOOL_REGISTRY = {}


def register(name, description, input_schema):
    def deco(fn):
        TOOL_REGISTRY[name] = {"name": name, "description": description,
                               "input_schema": input_schema, "handler": fn}
        return fn
    return deco


def ok(data: dict) -> dict:
    data.setdefault("ok", True)
    return data


def fail(message: str, code: str = "tool_error") -> dict:
    return {"ok": False, "error": message, "code": code}


# ---------------- 文本版本映射（稳定引用用） ----------------

@lru_cache(maxsize=1)
def _chunk_text_versions() -> dict:
    con = logic._conn()
    return {str(r[0]): runtime.text_version(r[1])
            for r in con.execute("SELECT chunk_id, text_clean FROM chunks")}


# ---------------- 工具实现 ----------------

@register("resolve_company",
          "按名称/代码检索企业候选及稳定ID",
          {"query": "string", "visible_scodes": "string[]?"})
def resolve_company(ctx, query: str, visible_scodes=None):
    """名称/代码 → 候选企业（稳定 scode）。代码精确匹配优先，名称子串匹配。"""
    if not query or not query.strip():
        return fail("query 不能为空", "bad_input")
    q = query.strip()
    names = logic._coname_map()
    candidates: list[dict] = []

    code = q.replace(".SZ", "").replace(".SH", "").replace(".BJ", "").strip()
    if code.isdigit() and len(code) <= 6:
        scode = code.zfill(6)
        if scode in names:
            candidates.append({"scode": scode, "coname": names[scode],
                               "match": "code_exact"})
    if not candidates:
        for scode, coname in names.items():
            if q.lower() in coname.lower():
                candidates.append({"scode": scode, "coname": coname,
                                   "match": "name_substring"})
    if visible_scodes is not None:
        allowed = set(str(s).zfill(6) for s in visible_scodes)
        candidates = [c for c in candidates if c["scode"] in allowed]

    agg = logic.agg()
    pv = set(logic.industry_tags()["pv"])
    g = agg[agg["scode"].isin([c["scode"] for c in candidates])]
    years_by_code = {s: sorted(g[g["scode"] == s]["year"].unique().tolist(), reverse=True)
                     for s in {c["scode"] for c in candidates}}
    prov_by_code = {}
    panel = logic._panel()
    for s in {c["scode"] for c in candidates}:
        pr = panel[panel["scode"] == s]
        prov_by_code[s] = (str(pr.iloc[0]["province"])
                           if not pr.empty and pd.notna(pr.iloc[0]["province"]) else "待核实")

    matches = [{
        "scode": c["scode"], "coname": c["coname"], "match": c["match"],
        "province": prov_by_code.get(c["scode"], "待核实"),
        "industry": logic.segment_of(c["scode"]),
        "years": years_by_code.get(c["scode"], []),
    } for c in candidates[:10]]

    if not matches:
        return ok({"query": q, "matches": [], "note":
                   f"未在 317 家电气设备样本中找到“{q}”。样本范围外企业不在本期能力内。"})
    if len(matches) > 1:
        return ok({"query": q, "matches": matches, "ambiguous": True, "note":
                   f"找到 {len(matches)} 家候选企业，请确认后再继续。"})
    return ok({"query": q, "matches": matches, "ambiguous": False})


@register("search_companies",
          "按地区/年份/产业/方向筛选企业（真实总数与分页）",
          {"province": "string?", "industry": "string?", "year": "int?",
           "direction": "string?", "page": "int", "page_size": "int",
           "sort": "window|score"})
def search_companies(ctx, province=None, industry=None, year=None,
                     direction=None, page=1, page_size=20, sort="window"):
    """企业筛选：返回真实 total、items 与筛选解释；“最近”=最新可用数据年度。"""
    g = logic.agg()
    g = g[g["window_type"].notna()].copy()
    explanation = {"sample": "317 家电气设备样本（2018-2023），光伏为重叠标签",
                   "year_note": "“最近”按最新可用数据年度解释，不擅称实时数据。"}
    g = logic.filter_industry(g, industry)
    if industry:
        explanation["industry"] = industry
    if province:
        g = g[g["province"] == province]
        explanation["province"] = province
    if year is not None:
        g = g[g["year"] == int(year)]
        explanation["year"] = int(year)
    if direction:
        g = g[g["directions"].map(lambda ds: direction in ds)]
        explanation["direction"] = DIRECTION_CN.get(direction, direction)

    w_order = {"first": 0, "new_country": 1, "expansion": 2, "layout_unknown": 3, "label_incomplete": 4}
    s_order = {"landing": 0, "prep": 1}
    g["_w"] = g["window_type"].map(w_order)
    g["_s"] = g["stage_layer"].map(s_order)
    if sort == "score":
        g = g.sort_values(["score", "_w", "_s", "year"],
                          ascending=[False, True, True, False])
    else:
        g = g.sort_values(["_w", "_s", "score", "year"],
                          ascending=[True, True, False, False])

    total = int(len(g))
    page = max(1, int(page or 1))
    page_size = max(1, min(100, int(page_size or 20)))
    start = (page - 1) * page_size
    names = logic._coname_map()
    chains = logic.rules()["chains"]
    pv = set(logic.industry_tags()["pv"])
    items = []
    for _, r in g.iloc[start:start + page_size].iterrows():
        items.append({
            "scode": r["scode"],
            "coname": names.get(r["scode"], ""),
            "province": r["province"] if pd.notna(r["province"]) else "待核实",
            "industry": logic.segment_of(r["scode"]),
            "year": int(r["year"]),
            "window_type": r["window_type"],
            "window_label": chains["window_label"][r["window_type"]],
            "stage_layer": r["stage_layer"],
            "stage_label": chains["stage_label"][r["stage_layer"]],
            "directions": r["directions"],
            "countries": r["countries"],
            "regions": r["regions"],
            "score": int(r["score"]),
            "n_deploy": int(r["n_deploy"]),
            "n_intent": int(r["n_intent"]),
        })
    return ok({
        "total": total, "page": page, "page_size": page_size,
        "items": items, "filter_explanation": explanation,
    })


def _signal_refs(d) -> list[dict]:
    tv = _chunk_text_versions()
    refs = []
    for c in d.get("signals", [])[:6]:
        refs.append({
            "signal_id": c["signal_id"],
            "evidence_ref": ev_ref(c["chunk_id"],
                                   c["signal_id"].rsplit("#", 1)[-1],
                                   tv.get(c["chunk_id"], "")),
            "quote": (c.get("evidence_quote") or "")[:160],
            "year": c["year"],
            "direction": c["direction"],
        })
    return refs


@register("get_company_context",
          "企业画像+信号+供应链摘要+规则候选（统一年度上下文）",
          {"scode": "string", "year": "int?", "snapshot_id": "string?"})
def get_company_context(ctx, scode, year=None, snapshot_id=None):
    """企业上下文包：同一年度口径，缺失明确标注，不回退未来年份。"""
    scode = str(scode).zfill(6)
    d = logic.company_detail(scode, year, strict_year=True)
    if not d:
        return fail(f"企业 {scode} 不在 317 家样本内", "not_found")
    ch = logic.chain(scode, year)
    sc = logic.supply_chain(scode, year)

    candidates = []
    for s in ch["steps"] if ch else []:
        if s.get("key") != "product":
            continue
        for p in s.get("products", []):
            card = products.get_card(p["key"])
            candidates.append({
                "key": p["key"], "name": p["name"], "category": p["category"],
                "reason": p["reason"], "rule_id": p["rule_id"],
                "signal_id": p.get("signal_id"), "evidence_id": p.get("evidence_id"),
                "product_ref": product_ref(p["key"]),
                "card_status": card["status"] if card else "unknown",
            })

    refs = _signal_refs(d)
    panel_missing = (d.get("data_completeness") or {}).get("missing", [])
    firm_age = d.get("firm_age")
    sub_count = d.get("overseas_sub_count")
    return ok({
        "scode": scode, "coname": d["coname"], "year": d["year"],
        "requested_year": int(year) if year is not None else None,
        "snapshot_id": runtime.get_snapshot(),
        "industry": d["industry"],
        "has_year_data": bool(d["signals"]) or d.get("panel_status") == "full",
        "window": d.get("window") or {},
        "panel": {
            "status": d.get("panel_status"),
            "province": d.get("province"),
            "assets": d.get("assets"), "roa": d.get("roa"),
            "leverage": d.get("leverage"), "rd_intensity": d.get("rd_intensity"),
            # 规格声明为 integer，必须输出整数（旧实现返回 20.0 会被 Coze 校验拒绝）
            "overseas_sub_count": int(sub_count) if sub_count is not None else None,
            "overseas_rev_share": d.get("overseas_rev_share"),
            "soe": d.get("soe"),
            "firm_age": int(firm_age) if firm_age is not None else None,
            "missing": panel_missing,
        },
        "sc": {
            "customer_concentration": d.get("customer_concentration"),
            "supplier_concentration": d.get("supplier_concentration"),
            "overseas_customer_share": d.get("overseas_customer_share"),
            "structured_customers": len(sc.get("detail", {}).get("customers", [])),
            "structured_suppliers": len(sc.get("detail", {}).get("suppliers", [])),
            "two_hop_count": len(sc.get("detail", {}).get("two_hop", [])),
        },
        "capability": d.get("capability"),
        "signals": d.get("signals", [])[:12],
        "history_count": (d.get("history") or {}).get("count", 0),
        "signal_refs": refs,
        "rule_candidates": candidates,
        "metric_refs": {
            "customer_concentration": metric_ref("concentration", scode, d["year"], "CustomerConcentration"),
            "supplier_concentration": metric_ref("concentration", scode, d["year"], "PurchaseConcentration"),
        },
        "coverage": {
            "panel": d.get("panel_status", "text_only"),
            "claims_selected_year": len(d.get("signals", [])),
            "chain": ch is not None,
            "sc_structured": bool(sc.get("detail", {}).get("customers") or
                                  sc.get("detail", {}).get("suppliers")),
            "note": ("统计结果附单位、时间范围与缺失数；"
                     "同时检索不到企业证据和产品资料时不生成确定的服务适配结论。"),
        },
    })


@register("get_evidence",
          "按 evidence_ref 读取原文/引文/偏移/来源/版本",
          {"evidence_ref": "string"})
def get_evidence(ctx, evidence_ref):
    """原文引用：绑定 snapshot_id+chunk_id+claim_number+text_version+start/end。"""
    from .schemas import parse_ref
    parsed = parse_ref(evidence_ref)
    if not parsed or parsed[0] != "evidence" or len(parsed[1]) != 3:
        return fail(f"非法证据引用：{evidence_ref}", "bad_ref")
    chunk_id, claim_number, tv = parsed[1]
    try:
        claim_number = int(claim_number)
    except ValueError:
        return fail(f"非法证据引用：{evidence_ref}", "bad_ref")

    con = logic._conn()
    row = con.execute(
        "SELECT chunk_id, scode, coname, year, section_canonical, program_label, text_clean "
        "FROM chunks WHERE chunk_id=?", (chunk_id,)).fetchone()
    if not row:
        return fail(f"证据块不存在：{chunk_id}", "not_found")
    text = row[6] or ""
    current_tv = runtime.text_version(text)
    spans = []
    for c in con.execute(
            "SELECT claim_number, program_label, direction, evidence_start, evidence_end,"
            " evidence_quote FROM claims WHERE chunk_id=? AND claim_number=?",
            (chunk_id, claim_number)):
        spans.append({"claim_number": int(c[0]), "program_label": c[1],
                      "direction": c[2], "start": int(c[3]), "end": int(c[4]),
                      "quote": c[5]})
    status = "ok"
    warning = None
    if tv and tv != current_tv:
        status = "stale_text"
        warning = "文本版本与快照不一致，定位待复核（不伪造高亮）。"
    return ok({
        "ref_id": evidence_ref,
        "chunk_id": chunk_id, "claim_number": claim_number,
        "scode": str(row[1]).zfill(6), "coname": row[2], "year": int(row[3]),
        "section": row[4], "program_label": row[5],
        "text": text, "text_version": current_tv, "spans": spans,
        "source": {"snapshot_id": runtime.get_snapshot(), "kb_version": "kb-2023"},
        "status": status, "warning": warning,
    })


@register("compare_companies",
          "同一年度多企业确定性对比表及参考范围",
          {"scodes": "string[]", "year": "int", "fields": "string[]?"})
def compare_companies(ctx, scodes, year, fields=None):
    """企业对比：同一年度、缺失明确标识；数量受 AI_MAX_COMPARE_COMPANIES 限制。"""
    example = '["002860", "300670"]'
    if not isinstance(scodes, list) or not scodes:
        return fail(f"scodes 不能为空。请在 scodes 数组中填入 2—3 个 6 位企业代码，例如 {example}。",
                    "bad_input")
    if year is None:
        return fail("对比必须指定统一年份（同年度口径）。请在 year 字段填入年份，例如 2023。",
                    "bad_input")
    raw = [str(s).strip() for s in scodes]
    scodes = list(dict.fromkeys(s.zfill(6) for s in raw if s))[:MAX_COMPARE]
    if len(scodes) < 2:
        return fail(f"对比至少需要两家企业（当前收到 {len(raw)} 个值：{raw}）。"
                    f"请在 scodes 数组里补足两家企业的 6 位代码，例如 {example}。",
                    "bad_input")

    panel = logic._panel()
    rows, missing = [], []
    numeric_cols = ["assets", "roa", "leverage", "rd_intensity",
                    "overseas_rev_share", "overseas_sub_count"]

    for scode in scodes:
        d = logic.company_detail(scode, year, strict_year=True)
        if not d:
            return fail(f"企业 {scode} 不在样本内", "not_found")
        countries = sorted({c for s in d.get("signals", [])
                            for c in s.get("countries", [])})
        regions = sorted({c for s in d.get("signals", [])
                          for c in s.get("regions", [])})
        r = {
            "scode": scode, "coname": d.get("coname"),
            "province": d.get("province"), "industry": d.get("industry"),
            "year": int(year),
            "window": d.get("window") or {},
            "directions": sorted({s["direction"] for s in d.get("signals", [])}),
            "countries": countries,
            "regions": regions,
            "capability": {"grade": d["capability"]["grade"],
                           "score": d["capability"]["score"],
                           "completeness": d["capability"].get("completeness", {})},
            "panel": {f: d.get(f) for f in numeric_cols},
            "customer_concentration": d.get("customer_concentration"),
            "supplier_concentration": d.get("supplier_concentration"),
            "overseas_customer_share": d.get("overseas_customer_share"),
            "panel_status": d.get("panel_status"),
            "signal_count": len(d.get("signals", [])),
        }
        miss = [f for f in ["assets", "roa", "leverage", "rd_intensity",
                            "overseas_rev_share", "customer_concentration",
                            "supplier_concentration"] if d.get(f) is None]
        if miss:
            missing.append({"scode": scode, "missing": miss,
                            "note": "缺失项按“待核实”处理，不补 0、不取其他年度。",
                            "year_data_note": "所选年度无该字段记录"})
        rows.append(r)

    # 参考范围：样本中位数与四分位（同年度口径）
    sub = panel[panel["year"] == int(year)]
    reference = {}
    for f in ["assets", "roa", "leverage", "rd_intensity"]:
        col = sub[f].dropna()
        if col.empty:
            continue
        reference[f] = {"median": round(float(col.median()), 4),
                        "q1": round(float(col.quantile(.25)), 4),
                        "q3": round(float(col.quantile(.75)), 4),
                        "n": int(len(col))}
    conc = logic.scdata.concentration()
    csub = conc[conc["year"] == int(year)]
    for f in ["CustomerConcentration", "PurchaseConcentration"]:
        col = csub[f].dropna()
        if col.empty:
            continue
        reference[f] = {"median": round(float(col.median()), 2),
                        "q1": round(float(col.quantile(.25)), 2),
                        "q3": round(float(col.quantile(.75)), 2),
                        "n": int(len(col))}

    comparison_id = runtime.new_id("cmp")
    payload = {"comparison_id": comparison_id, "year": int(year),
               "companies": rows, "reference": reference, "missing": missing}
    con = runtime.get_conn()
    con.execute("INSERT INTO comparisons(comparison_id,user_id,payload,created_at)"
                " VALUES(?,?,?,?)",
                (comparison_id, ctx["user_id"],
                 json.dumps(payload, ensure_ascii=False), runtime._now()))
    con.commit()
    return ok({**payload, "compare_ref": compare_ref(comparison_id),
               "note": "同年度横向对比；参考范围=样本中位数/四分位；不声称转化概率更高，资料不足列出缺项。"})


@register("get_rule_candidates",
          "规则候选服务（推理链产品步，可限定行动方向）",
          {"scode": "string", "year": "int?", "directions": "string[]?"})
def get_rule_candidates(ctx, scode, year=None, directions=None):
    scode = str(scode).zfill(6)
    ch = logic.chain(scode, year)
    if not ch:
        return ok({"scode": scode, "year": year, "candidates": [], "coverage":
                   {"note": "所选年度无需求信号，无规则候选。"}})
    step = next((s for s in ch["steps"] if s.get("key") == "product"), {})
    recs = []
    for p in step.get("products", []):
        if directions:
            if not any(p["rule_id"] == f"RULE_DIR_{d}" for d in directions):
                continue
        card = products.get_card(p["key"])
        recs.append({
            "key": p["key"], "name": p["name"], "category": p["category"],
            "reason": p["reason"], "rule_id": p["rule_id"],
            "signal_id": p.get("signal_id"), "evidence_id": p.get("evidence_id"),
            "quote": p.get("quote", ""),
            "product_ref": product_ref(p["key"]),
            "card_status": card["status"] if card else "unknown",
        })
    return ok({
        "scode": scode, "year": ch["year"], "directions_filter": directions,
        "candidates": recs,
        "coverage": {"note": f"仅使用 {ch['year']} 年度信号；历史信号不参与推荐。"
                             "限定方向时仅保留方向规则命中项。"},
    })


@register("search_product_knowledge",
          "产品卡/文档段落检索（行动、服务偏好）",
          {"actions": "string[]?", "country": "string?", "service_focus": "string[]?",
           "as_of": "string?"})
def search_product_knowledge(ctx, actions=None, country=None,
                             service_focus=None, as_of=None):
    r = products.search_product_knowledge(actions=actions,
                                          service_focus=service_focus, as_of=as_of)
    if country:
        r["coverage"]["country"] = country
        r["coverage"]["country_note"] = ("清算行覆盖与避险方案需人工核实目标国后叠加；"
                                         "区域表述不冒充具体国家。")
    return ok(r)


@register("search_regional_knowledge",
          "地区授权资料检索（权限=服务端地区绑定）",
          {"query": "string", "allowed_source_ids": "string[]?"})
def search_regional_knowledge(ctx, query=None, allowed_source_ids=None):
    from . import extensions
    return ok(extensions.search_regional(query or "", ctx["user_id"],
                                         ctx["regions"], allowed_source_ids))


# ---------------- 工具上下文与调度 ----------------

def build_context(user: dict, allowed_tools: list[str] | None = None) -> dict:
    return {
        "user_id": user["user_id"],
        "display_name": user["display_name"],
        "regions": list(user["regions"]),
        "identity_mode": user["identity_mode"],
        "snapshot_id": runtime.get_snapshot(),
        "allowed_tools": allowed_tools,
    }


def prune_nulls(obj):
    """递归移除值为 None 的键与列表元素（保留结构）。

    响应契约：OpenAPI 规格里声明了具体类型的字段，缺失时**不出现**（而不是出现 null）；
    缺失信息由随附的 `missing` / `coverage` 字段表达（方案 12.1：不把缺失解释为 0）。
    Coze 插件会按规格逐字段校验类型，null 会被判为类型不符，故统一在此裁剪。
    """
    if isinstance(obj, dict):
        return {k: prune_nulls(v) for k, v in obj.items() if v is not None}
    if isinstance(obj, list):
        return [prune_nulls(v) for v in obj if v is not None]
    return obj


def call_tool(name: str, ctx: dict, params: dict) -> dict:
    """受控调用：白名单 + 权限检查 + 统一异常封装 + 响应空值裁剪。"""
    entry = TOOL_REGISTRY.get(name)
    if not entry:
        return fail(f"未知工具：{name}", "unknown_tool")
    allowed = ctx.get("allowed_tools")
    if allowed is not None and name not in allowed:
        return fail(f"工具 {name} 不在本轮允许清单内", "forbidden")
    try:
        out = entry["handler"](ctx, **params)
        if not isinstance(out, dict):
            out = ok({"result": out})
        return prune_nulls(out)
    except TypeError as e:
        return fail(f"工具参数错误：{e}", "bad_input")
    except Exception as e:  # 兜底，避免工具内部异常泄漏给模型
        return fail(f"工具执行失败：{type(e).__name__}", "internal_error")
