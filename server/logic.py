# -*- coding: utf-8 -*-
"""核心计算层：窗口期 / 分层 / 强度 / 能力评分 / 推理链 / 简报 / 供应链示例。

所有判定均为确定性规则（规则引擎），LLM 不参与计算。
"""
import json
import sqlite3
from functools import lru_cache
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "kb" / "kb-2023.sqlite"
RULES_DIR = ROOT / "rules"

LANDING_DIRECTIONS = {"capacity_production", "investment_ma"}
LANDING_ANCHORS = {"project_or_base", "capacity_or_facility",
                   "overseas_entity", "investment_or_contract"}
DEMAND_LABELS = ("经营部署", "战略意图")


def _load_json(name):
    with open(RULES_DIR / name, encoding="utf-8") as f:
        return json.load(f)


@lru_cache(maxsize=1)
def rules():
    return {
        "products": _load_json("products.json"),
        "scoring": _load_json("scoring.json"),
        "chains": _load_json("chains.json"),
        "countries": _load_json("countries.json"),
        "pv_list": _load_json("pv_list.json"),
    }


@lru_cache(maxsize=1)
def industry_tags():
    """多标签：电气设备（全部 317 家）+ 光伏（申万 6305xx 重叠部分）。

    增量光伏企业（new_shsz/new_bse）尚未入样本，标注后并入。
    """
    pv = rules()["pv_list"]
    pv_codes = set(pv["overlap"]) | set(pv["new_shsz"]) | set(pv["new_bse"])
    con = _conn()
    all_codes = {r[0] for r in con.execute("SELECT DISTINCT scode FROM chunks")}
    return {
        "all": sorted(all_codes),
        "pv": sorted(pv_codes & all_codes),   # 当前样本内可标光伏的企业
        "pv_full": sorted(pv_codes),          # 申万口径全量（含待补标）
    }


@lru_cache(maxsize=1)
def _conn():
    con = sqlite3.connect(DB, check_same_thread=False)
    return con


def meta():
    con = _conn()
    cur = con.execute("SELECT * FROM meta")
    cols = [d[0] for d in cur.description]
    return dict(zip(cols, cur.fetchone()))


def _panel():
    con = _conn()
    df = pd.read_sql("SELECT * FROM firm_year", con)
    df["scode"] = df["scode"].astype(str).str.zfill(6)
    return df


def _claims():
    con = _conn()
    df = pd.read_sql("SELECT * FROM claims", con)
    df["scode"] = df["scode"].astype(str).str.zfill(6)
    df["country_hits"] = df["country_hits"].map(
        lambda s: json.loads(s) if isinstance(s, str) and s else [])
    return df


def _coname_map():
    con = _conn()
    df = pd.read_sql("SELECT DISTINCT scode, coname FROM chunks", con)
    df["scode"] = df["scode"].astype(str).str.zfill(6)
    return dict(zip(df["scode"], df["coname"]))


def _sub_countries():
    con = _conn()
    df = pd.read_sql("SELECT scode, year, country, overseas_sub_count FROM subs_country", con)
    df["scode"] = df["scode"].astype(str).str.zfill(6)
    return df


@lru_cache(maxsize=1)
def agg():
    """企业-年信号聚合：窗口类型 / 分层 / 强度分。"""
    cl = _claims()
    dem = cl[cl["program_label"].isin(DEMAND_LABELS)].copy()
    dem["is_landing"] = dem["direction"].isin(LANDING_DIRECTIONS) | \
        dem["execution_anchor_type"].isin(LANDING_ANCHORS)
    dem["is_hard"] = dem["execution_anchor_type"] != "none"
    g = dem.groupby(["scode", "year"]).agg(
        n_deploy=("program_label", lambda s: int((s == "经营部署").sum())),
        n_intent=("program_label", lambda s: int((s == "战略意图").sum())),
        n_landing=("is_landing", "sum"),
        n_claims=("is_landing", "size"),
        n_hard=("is_hard", "sum"),
        directions=("direction", lambda s: sorted(set(s) - {"null", ""})),
        countries=("country_hits", lambda s: sorted({c for xs in s for c in xs})),
        top_quote=("evidence_quote", "first"),
    ).reset_index()
    g["n_landing"] = g["n_landing"].astype(int)
    g["n_hard"] = g["n_hard"].astype(int)

    p = _panel()[["scode", "year", "overseas_demand", "overseas_sub_count",
                  "overseas_rev_share", "province"]].copy()
    g = g.merge(p, on=["scode", "year"], how="inner")

    # 已进入国家集合（全期口径）
    subs = _sub_countries()
    entered = subs.groupby("scode")["country"].apply(set).to_dict()

    def window_type(row):
        if row["overseas_demand"] != 1:
            return None
        if (row["overseas_sub_count"] or 0) == 0 and (row["overseas_rev_share"] or 0) <= 0:
            return "first"
        entered_c = entered.get(row["scode"], set())
        if any(c not in entered_c for c in row["countries"]):
            return "new_country"
        return "expansion"

    g["window_type"] = g.apply(window_type, axis=1)
    g["stage_layer"] = g.apply(
        lambda r: "landing" if r["n_landing"] > 0 else "prep", axis=1)
    g["score"] = (2 * g["n_deploy"] + g["n_intent"] + g["n_hard"]
                  + g["directions"].map(len).clip(upper=3) - 1)
    return g


def radar(province=None, industry=None, year=None, limit=200, sort_mode="window"):
    """辖区意图强度排行。industry 参数保留（当前仅电气设备）。

    sort_mode:
      window — 窗口类型优先（first > new_country > expansion）→ 分层（落地 > 筹备）
               → 强度分 → 年份（业务口径：首次出海账户首绑价值最高）
      score  — 纯强度分降序 → 窗口类型 → 分层
    """
    g = agg()
    g = g[g["window_type"].notna()].copy()
    if industry == "光伏":
        pv = set(industry_tags()["pv"])
        g = g[g["scode"].isin(pv)]
    elif industry == "电气设备":
        pv = set(industry_tags()["pv"])
        g = g[~g["scode"].isin(pv)]
    if province:
        g = g[g["province"] == province]
    if year:
        g = g[g["year"] == int(year)]
    w_order = {"first": 0, "new_country": 1, "expansion": 2}
    s_order = {"landing": 0, "prep": 1}
    g["_w"] = g["window_type"].map(w_order)
    g["_s"] = g["stage_layer"].map(s_order)
    if sort_mode == "score":
        g = g.sort_values(["score", "_w", "_s", "year"],
                          ascending=[False, True, True, False])
    else:
        g = g.sort_values(["_w", "_s", "score", "year"],
                          ascending=[True, True, False, False])
    names = _coname_map()
    chain_rules = rules()["chains"]
    pv = set(industry_tags()["pv"])
    out = []
    for _, r in g.head(limit).iterrows():
        out.append({
            "scode": r["scode"],
            "coname": names.get(r["scode"], ""),
            "province": r["province"],
            "industry": "光伏" if r["scode"] in pv else "电气设备",
            "industry_tags": (["电气设备", "光伏"] if r["scode"] in pv else ["电气设备"]),
            "year": int(r["year"]),
            "window_type": r["window_type"],
            "window_label": chain_rules["window_label"][r["window_type"]],
            "stage_layer": r["stage_layer"],
            "stage_label": chain_rules["stage_label"][r["stage_layer"]],
            "n_deploy": int(r["n_deploy"]),
            "n_intent": int(r["n_intent"]),
            "directions": r["directions"],
            "countries": r["countries"],
            "score": int(r["score"]),
            "top_quote": (r["top_quote"] or "")[:120],
        })
    return out


def provinces():
    return sorted(agg()["province"].dropna().unique().tolist())


def years():
    return sorted(agg()["year"].unique().tolist())


# ---------------- 企业详情 ----------------

def company_detail(scode):
    con = _conn()
    cl = _claims()
    names = _coname_map()
    p = _panel()
    row = p[p["scode"] == scode]
    if row.empty:
        return None
    row = row.sort_values("year", ascending=False).iloc[0]
    g = agg()
    gy = g[(g["scode"] == scode)].sort_values("year", ascending=False)
    sigs = cl[(cl["scode"] == scode) &
              (cl["program_label"].isin(DEMAND_LABELS))].sort_values("year", ascending=False)

    cap = capability_score(scode)

    claims_out = []
    for _, c in sigs.head(60).iterrows():
        claims_out.append({
            "chunk_id": c["chunk_id"],
            "year": int(c["year"]),
            "program_label": c["program_label"],
            "time_state": c["time_state"],
            "direction": c["direction"],
            "anchor_type": c["execution_anchor_type"],
            "anchor": c["execution_anchor"],
            "evidence_start": int(c["evidence_start"]),
            "evidence_end": int(c["evidence_end"]),
            "evidence_quote": (c["evidence_quote"] or "")[:200],
        })

    return {
        "scode": scode,
        "coname": names.get(scode, ""),
        "province": row["province"],
        "industry": "光伏" if scode in set(industry_tags()["pv"]) else "电气设备",
        "year": int(row["year"]),
        "assets": float(row["assets"]) if pd.notna(row["assets"]) else None,
        "roa": float(row["roa"]) if pd.notna(row["roa"]) else None,
        "leverage": float(row["leverage"]) if pd.notna(row["leverage"]) else None,
        "rd_intensity": float(row["rd_intensity"]) if pd.notna(row["rd_intensity"]) else None,
        "overseas_sub_count": int(row["overseas_sub_count"]) if pd.notna(row["overseas_sub_count"]) else 0,
        "overseas_rev_share": float(row["overseas_rev_share"]) if pd.notna(row["overseas_rev_share"]) else 0,
        "overseas_demand": int(row["overseas_demand"]) if pd.notna(row["overseas_demand"]) else 0,
        "soe": int(row["soe"]) if pd.notna(row["soe"]) else 0,
        "firm_age": float(row["firm_age"]) if pd.notna(row["firm_age"]) else None,
        "window": {
            "year": int(gy.iloc[0]["year"]),
            "window_type": gy.iloc[0]["window_type"],
            "window_label": rules()["chains"]["window_label"].get(gy.iloc[0]["window_type"]),
            "stage_layer": gy.iloc[0]["stage_layer"],
            "stage_label": rules()["chains"]["stage_label"][gy.iloc[0]["stage_layer"]],
            "score": int(gy.iloc[0]["score"]),
        } if not gy.empty and gy.iloc[0]["window_type"] else None,
        "capability": cap,
        "claims": claims_out,
    }


def capability_score(scode):
    """能力评分卡：行业分位归一 + 加权。"""
    sc_rules = rules()["scoring"]
    p = _panel()
    def pct(s):
        if s is None or pd.isna(s):
            return 0.5
        return float((p[p[field].notna()][field] <= s).mean()) if p[field].notna().any() else 0.5

    row = p[p["scode"] == scode].sort_values("year", ascending=False).iloc[0]
    dims = []
    total = 0.0
    for d in sc_rules["dimensions"]:
        field = d["field"]
        raw = row[field] if field in row.index else None
        if pd.isna(raw):
            raw = None
        pv = pct(raw)
        if d["direction"] == -1:
            pv = 1 - pv
        total += pv * d["weight"]
        dims.append({"key": d["key"], "label": d["label"],
                     "value": round(pv, 3),
                     "raw": round(float(raw), 3) if raw is not None else None})
    total = round(total, 3)
    grade = next((g for g in sc_rules["grades"] if total >= g["min"]), sc_rules["grades"][-1])
    return {"score": total, "grade": grade["label"], "desc": grade["desc"], "dims": dims}


# ---------------- 推理链 ----------------

def chain(scode):
    r = rules()
    products = r["products"]
    chains = r["chains"]
    g = agg()
    gy = g[(g["scode"] == scode)].sort_values("year", ascending=False)
    if gy.empty or gy.iloc[0]["window_type"] is None:
        return None
    top = gy.iloc[0]
    cl = _claims()
    dem = cl[(cl["scode"] == scode) &
             (cl["program_label"].isin(DEMAND_LABELS))].sort_values("year", ascending=False)

    steps = []
    # step 1 窗口期
    steps.append({
        "key": "window",
        "label": chains["step_order"][0]["label"],
        "title": f"{chains['window_label'][top['window_type']]} · {chains['stage_label'][top['stage_layer']]}",
        "detail": (f"当年披露 {int(top['n_deploy'])} 条经营部署、{int(top['n_intent'])} 条战略意图；"
                   f"窗口类型「{chains['window_label'][top['window_type']]}」，分层「{chains['stage_label'][top['stage_layer']]}」。"),
        "evidence": dem.iloc[0]["evidence_quote"][:160] if len(dem) else "",
    })
    # step 2 方向与模式
    dirs = top["directions"]
    mode_desc = "、".join(
        f"{d}（{products['direction_map'].get(d, {}).get('mode', '—')}）" for d in dirs) or "—"
    steps.append({
        "key": "direction",
        "label": chains["step_order"][1]["label"],
        "title": mode_desc,
        "detail": f"识别到的出海方向：{'、'.join(dirs) if dirs else '未分类'}；"
                  f"硬锚点 {int(top['n_hard'])} 条。",
        "evidence": dem.iloc[0]["evidence_quote"][:160] if len(dem) else "",
    })
    # step 3 产品匹配
    prod_keys, extras = [], []
    for d in dirs:
        for k in products["direction_map"].get(d, {}).get("products", []):
            if k not in prod_keys:
                prod_keys.append(k)
    anchors = dem["execution_anchor_type"].dropna().unique().tolist()
    for a in anchors:
        for k in products["anchor_extra"].get(a, []):
            if k not in prod_keys:
                prod_keys.append(k)
                extras.append(k)
    for k in products["window_extra"].get(top["window_type"], []):
        if k not in prod_keys:
            prod_keys.append(k)
    has_country = bool(top["countries"])
    for k in products["country_extra"]:
        if has_country and k not in prod_keys:
            prod_keys.append(k)
    prod_names = [f"{products['catalog'][k]['name']}（{products['catalog'][k]['category']}）"
                  for k in prod_keys if k in products["catalog"]]
    steps.append({
        "key": "product",
        "label": chains["step_order"][2]["label"],
        "title": "；".join(prod_names) or "—",
        "detail": (f"匹配依据：方向规则命中 {[d for d in dirs]}；"
                   + (f"锚点补充 {extras}；" if extras else "")
                   + f"窗口类型补充 {products['window_extra'].get(top['window_type'], [])}；"
                   + ("含国别锚点，叠加清算/避险建议。" if has_country else "无国别锚点，不叠加清算建议。")),
        "evidence": "",
    })
    # step 4 前置条件
    prereqs = []
    for k in prod_keys:
        if k in products["prereq"]:
            prereqs.append(f"{products['catalog'][k]['name']}：{products['prereq'][k]}")
    steps.append({
        "key": "prereq",
        "label": chains["step_order"][3]["label"],
        "title": "；".join(prereqs) or "无额外前置条件",
        "detail": "前置条件由产品规则库定义，落地时可替换为行内产品库。",
        "evidence": "",
    })
    return {
        "scode": scode,
        "year": int(top["year"]),
        "countries": top["countries"],
        "steps": steps,
    }


def briefing(scode):
    d = company_detail(scode)
    ch = chain(scode)
    if not d or not ch:
        return None
    cap = d["capability"]
    w = d["window"]
    prod_step = next(s for s in ch["steps"] if s["key"] == "product")
    prereq_step = next(s for s in ch["steps"] if s["key"] == "prereq")
    return {
        "scode": scode,
        "coname": d["coname"],
        "title": f"{d['coname']} 访前简报",
        "sections": [
            {"heading": "一、能力就绪度",
             "body": (f"能力评分 {cap['score']}，分级「{cap['grade']}」——{cap['desc']}。"
                      f"关键维度："
                      + "；".join(f"{x['label']} 分位 {x['value']:.0%}" for x in cap["dims"])
                      + "。本项为辅助判断，不替代人工尽调。")},
            {"heading": "二、出海需求判断",
             "body": (f"{w['window_label']}（{w['stage_label']}），"
                      f"强度分 {w['score']}。{ch['steps'][1]['title']}。"
                      f"证据示例：「{ch['steps'][0]['evidence']}」。")},
            {"heading": "三、产品组合建议",
             "body": prod_step["title"] + "。"},
            {"heading": "四、前置条件与触达要点",
             "body": (prereq_step["title"] + "。"
                      f"目标国别：{'、'.join(ch['countries']) if ch['countries'] else '未披露明确国别'}。"
                      "触达要点：以账户方案与保函预授信为敲门砖，融资需求后置于行内授信流程。")},
        ],
    }


# ---------------- 证据 / 供应链示例 ----------------

def evidence(chunk_id):
    con = _conn()
    row = con.execute(
        "SELECT chunk_id, scode, coname, year, section_canonical, program_label, text_clean "
        "FROM chunks WHERE chunk_id=?", (chunk_id,)).fetchone()
    if not row:
        return None
    cl = pd.read_sql("SELECT * FROM claims WHERE chunk_id=?", con, params=(chunk_id,))
    spans = []
    for _, c in cl.iterrows():
        spans.append({
            "claim_number": int(c["claim_number"]),
            "program_label": c["program_label"],
            "direction": c["direction"],
            "start": int(c["evidence_start"]),
            "end": int(c["evidence_end"]),
            "quote": c["evidence_quote"],
        })
    return {
        "chunk_id": chunk_id,
        "scode": str(row[1]).zfill(6),
        "coname": row[2],
        "year": int(row[3]),
        "section": row[4],
        "program_label": row[5],
        "text": row[6],
        "spans": spans,
    }


def supply_chain(scode):
    """供应链示例（sample）：客户边来自年报披露的 named_customer 锚点，
    国家边来自子公司国家表；供应商边为 schema 占位（P2）。"""
    cl = _claims()
    subs = _sub_countries()
    names = _coname_map()
    cust = cl[(cl["scode"] == scode) &
              (cl["execution_anchor_type"] == "named_customer")]
    customers = []
    for _, c in cust.drop_duplicates("execution_anchor").head(6).iterrows():
        customers.append({"name": c["execution_anchor"],
                          "evidence": (c["evidence_quote"] or "")[:100]})
    sub_c = subs[subs["scode"] == scode].sort_values("year", ascending=False)
    countries = sorted(set(sub_c["country"].tolist()))
    nodes = [{"id": "self", "label": names.get(scode, scode), "type": "企业"}]
    edges = []
    for i, c in enumerate(customers):
        nodes.append({"id": f"cust{i}", "label": c["name"], "type": "客户"})
        edges.append({"source": "self", "target": f"cust{i}",
                      "rel": "SELLS_TO", "note": c["evidence"]})
    for i, c in enumerate(countries):
        nodes.append({"id": f"c{i}", "label": c, "type": "国家"})
        edges.append({"source": "self", "target": f"c{i}",
                      "rel": "OWNS_SUB_IN", "note": "子公司所在国"})
    return {
        "scode": scode,
        "sample": True,
        "note": "演示样例：客户边来自年报披露锚点，国家边来自子公司数据；供应商边（SUPPLY_FROM）为 P2 扩展位，全量供应链数据接入后激活。",
        "nodes": nodes,
        "edges": edges,
    }
