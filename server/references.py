# -*- coding: utf-8 -*-
"""稳定引用解析（方案 7.2 / 8.2 节）。

按权限解析确定性详情：原文证据（按文本版本还原偏移）、结构化指标、
产品依据、已保存分析、对比、地区资料（读取时再次检查权限）。
"""
from __future__ import annotations

from . import analysis_service, extensions, products, runtime, tools
from .schemas import parse_ref

# 指标白名单：仅开放 concentration 表的两个字段（方案 7.1：不开放任意 SQL）
METRIC_FIELDS = {"CustomerConcentration": {"label": "前五大客户集中度", "unit": "%"},
                 "PurchaseConcentration": {"label": "前五大供应商集中度", "unit": "%"}}


def resolve_ref(ref_id: str, user: dict) -> dict:
    """按权限解析引用详情。返回 {"ok": bool, "kind", "detail" | "error"}。"""
    parsed = parse_ref(ref_id)
    if not parsed:
        return {"ok": False, "code": "bad_ref", "error": f"非法引用：{ref_id}"}
    kind, parts = parsed
    ctx = tools.build_context(user)

    if kind == "evidence":
        r = tools.get_evidence(ctx, ref_id)
        if not r.get("ok"):
            return {"ok": False, "code": r.get("code", "not_found"),
                    "error": r.get("error", "证据不存在")}
        return {"ok": True, "kind": "evidence", "detail": r}

    if kind == "product":
        card = products.get_card(parts[0])
        if not card:
            return {"ok": False, "code": "not_found", "error": "产品卡不存在"}
        return {"ok": True, "kind": "product", "detail": {
            **card, "ref_id": ref_id, "product_version": products.product_version(),
            "sources_index": products._catalog()["sources_index"],
        }}

    if kind == "metric":
        table, scode, year, field = parts
        if table != "concentration" or field not in METRIC_FIELDS:
            return {"ok": False, "code": "bad_ref", "error": "指标引用不在白名单"}
        from . import sc as scdata
        df = scdata.concentration()
        sub = df[(df["scode"] == scode) & (df["year"] == int(year))]
        if sub.empty:
            return {"ok": False, "code": "not_found", "error": "该年度无该指标记录"}
        value = float(sub.iloc[0][field])
        col = df[field].dropna()
        return {"ok": True, "kind": "metric", "detail": {
            "ref_id": ref_id, "table": table, "scode": scode, "year": int(year),
            "field": field, "label": METRIC_FIELDS[field]["label"],
            "unit": METRIC_FIELDS[field]["unit"], "value": value,
            "sample_median": round(float(col.median()), 2) if not col.empty else None,
            "sample_n": int(len(col)),
            "note": "指标=该企业该年度结构化记录；样本范围=317 家电气设备 2018-2023。"}}

    if kind == "compare":
        con = runtime.get_conn()
        row = con.execute("SELECT payload FROM comparisons WHERE comparison_id=?",
                          (parts[0],)).fetchone()
        if not row:
            return {"ok": False, "code": "not_found", "error": "对比记录不存在"}
        import json
        return {"ok": True, "kind": "compare", "detail": json.loads(row[0])}

    if kind == "analysis":
        rec = analysis_service.get_recommendation(parts[0], parts[1], user) \
            if len(parts) >= 2 else None
        if not rec:
            a = analysis_service.get_analysis(parts[0], user)
            if not a:
                return {"ok": False, "code": "not_found", "error": "分析不存在"}
            return {"ok": True, "kind": "analysis", "detail": {
                "analysis_id": parts[0], "summary": a["draft"].get("answer_blocks", []),
                "recommendations": a["draft"].get("recommendations", []),
                "questions": a["draft"].get("questions", []),
                "warnings": a["draft"].get("warnings", []),
                "context": a["draft"].get("context"), "engine": a["engine"],
                "status": a["status"]}}
        return {"ok": True, "kind": "analysis", "detail": rec,
                "note": "AI 方案引用：绑定 analysis_id 与 recommendation_id，"
                        "标注为分析结果，不冒充原文。"}

    if kind == "regional":
        r = extensions.read_regional_doc(parts[0], parts[1], user["regions"])
        if not r.get("ok"):
            return {"ok": False, "code": r.get("code", "not_found"),
                    "error": r.get("error", "地区资料不可用")}
        return {"ok": True, "kind": "regional", "detail": {
            **r, "ref_id": ref_id,
            "note": "地区资料引用：带 source_id、scope、版本；详情读取已再次检查权限。"}}

    if kind == "company":
        from . import logic
        scode = str(parts[0]).zfill(6)
        year = int(parts[1]) if len(parts) > 1 and str(parts[1]).isdigit() else None
        if scode not in logic._coname_map():
            return {"ok": False, "code": "not_found", "error": "企业不在样本内"}
        return {"ok": True, "kind": "company",
                "detail": {"scode": scode, "year": year,
                           "coname": logic._coname_map()[scode]}}

    return {"ok": False, "code": "bad_ref", "error": f"不支持的引用类型：{kind}"}
