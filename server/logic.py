# -*- coding: utf-8 -*-
"""核心计算层：窗口期 / 分层 / 强度 / 能力评分 / 推理链 / 简报 / 供应链示例。

所有判定均为确定性规则（规则引擎），LLM 不参与计算。

v1.3 口径原则：
- 年份上下文：企业详情/推理链/简报/子图均以选定年度为准，未选时取最新窗口年度。
- 当前与历史分离：产品推荐只消费所选年度信号；历史信号仅存档展示。
- 新国别：以“截至所选年度之前”的子公司国别集合为基准（as-of 口径）。
- 国别归一：geo 层统一 canonical（国家）/region（区域），完整名优先、别名归一。
- 缺失值：一律输出 None（前端显示“待核实”），不臆造 0 或中等分。
- 证据绑定：推理链与简报的每条建议携带 rule_id / signal_id / evidence_id。
"""
import json
import sqlite3
from functools import lru_cache
from pathlib import Path

import pandas as pd

from . import sc as scdata
from .geo import geo_extract, normalize_name

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "kb" / "kb-2023.sqlite"
RULES_DIR = ROOT / "rules"

LANDING_DIRECTIONS = {"capacity_production", "investment_ma"}
LANDING_ANCHORS = {"project_or_base", "capacity_or_facility",
                   "overseas_entity", "investment_or_contract"}
DEMAND_LABELS = ("经营部署", "战略意图")

# 面板展示字段与中文标签（数据完整度统计口径）
PANEL_LABELS = [
    ("assets", "总资产"), ("roa", "盈利能力"), ("leverage", "杠杆率"),
    ("rd_intensity", "研发强度"), ("overseas_sub_count", "海外子公司数"),
    ("overseas_rev_share", "海外收入占比"), ("overseas_demand", "出海需求标注"),
    ("soe", "产权性质"), ("firm_age", "企业年龄"),
]

RULE_IDS = {
    "window": {"first": "RULE_WINDOW_FIRST", "new_country": "RULE_WINDOW_NEW_COUNTRY",
               "expansion": "RULE_WINDOW_EXPANSION", "pv_text": "RULE_WINDOW_PV_TEXT"},
}


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
        "chain_map": _load_json("chain_map.json"),
        "segment_map": _load_json("segment_map.json"),
    }


def segment_of(scode):
    m = rules()["segment_map"].get(scode, {})
    return m.get("segment", "其他")


@lru_cache(maxsize=1)
def industry_tags():
    """多标签：电气设备（全部 317 家）+ 光伏（申万 6305xx 重叠部分）。"""
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


@lru_cache(maxsize=1)
def _panel():
    con = _conn()
    df = pd.read_sql("SELECT * FROM firm_year", con)
    df["scode"] = df["scode"].astype(str).str.zfill(6)
    return df


@lru_cache(maxsize=1)
def _claims():
    con = _conn()
    df = pd.read_sql("SELECT * FROM claims", con)
    df["scode"] = df["scode"].astype(str).str.zfill(6)
    df["chunk_id"] = df["chunk_id"].astype(str)
    df["claim_number"] = df["claim_number"].astype(int)
    df["country_hits"] = df["country_hits"].map(
        lambda s: json.loads(s) if isinstance(s, str) and s else [])
    geo = df["execution_anchor"].map(geo_extract)
    df["geo_countries"] = geo.map(lambda g: g["countries"])
    df["geo_regions"] = geo.map(lambda g: g["regions"])
    df["signal_id"] = df["chunk_id"] + "#" + df["claim_number"].astype(str)
    return df


@lru_cache(maxsize=1)
def _coname_map():
    con = _conn()
    df = pd.read_sql("SELECT DISTINCT scode, coname FROM chunks", con)
    df["scode"] = df["scode"].astype(str).str.zfill(6)
    return dict(zip(df["scode"], df["coname"]))


@lru_cache(maxsize=1)
def _sub_countries():
    con = _conn()
    df = pd.read_sql("SELECT scode, year, country, overseas_sub_count FROM subs_country", con)
    df["scode"] = df["scode"].astype(str).str.zfill(6)
    df["country_canon"] = df["country"].map(normalize_name)
    return df


@lru_cache(maxsize=1)
def agg():
    """企业-年信号聚合：窗口类型 / 分层 / 强度分。

    新国别判定（as-of）：以“截至该年度之前”的子公司国别集合为基准，
    避免后续年度布局倒灌影响早年分类。
    """
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
        countries=("geo_countries", lambda s: sorted({c for xs in s for c in xs})),
        regions=("geo_regions", lambda s: sorted({r for xs in s for r in xs})),
        top_signal=("signal_id", "first"),
        top_chunk=("chunk_id", "first"),
        top_quote=("evidence_quote", "first"),
    ).reset_index()
    g["n_landing"] = g["n_landing"].astype(int)
    g["n_hard"] = g["n_hard"].astype(int)

    p = _panel()[["scode", "year", "overseas_demand", "overseas_sub_count",
                  "overseas_rev_share", "province"]].copy()
    g = g.merge(p, on=["scode", "year"], how="left")

    subs = _sub_countries()

    def entered_before(scode, year):
        """截至所选年度之前（year < t）已进入的国别集合。"""
        return set(subs[(subs["scode"] == scode) & (subs["year"] < int(year))]
                   ["country_canon"].dropna())

    def window_type(row):
        if pd.isna(row["overseas_demand"]):
            return "pv_text"   # 光伏新增企业：结构数据待补，仅文本信号
        if row["overseas_demand"] != 1:
            return None
        if (row["overseas_sub_count"] or 0) == 0 and (row["overseas_rev_share"] or 0) <= 0:
            return "first"
        if any(c not in entered_before(row["scode"], row["year"]) for c in row["countries"]):
            return "new_country"
        return "expansion"

    g["window_type"] = g.apply(window_type, axis=1)
    g["stage_layer"] = g.apply(
        lambda r: "landing" if r["n_landing"] > 0 else "prep", axis=1)
    g["score"] = (2 * g["n_deploy"] + g["n_intent"] + g["n_hard"]
                  + g["directions"].map(len).clip(upper=3) - 1)
    return g


def radar(province=None, industry=None, year=None, limit=200, sort_mode="window",
          segment=None):
    """辖区意图强度排行。

    sort_mode:
      window — 窗口类型优先（first > new_country > expansion）→ 分层（落地 > 筹备）
               → 强度分 → 年份
      score  — 纯强度分降序 → 窗口类型 → 分层
    segment — 电力产业链环节筛选（光伏主链/风电设备/…，见 chain_map.json）
    """
    g = agg()
    g = g[g["window_type"].notna()].copy()
    if segment:
        g = g[g["scode"].map(segment_of) == segment]
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
    w_order = {"first": 0, "new_country": 1, "expansion": 2, "pv_text": 3}
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
            "province": r["province"] if pd.notna(r["province"]) else "待核实",
            "industry": "光伏" if r["scode"] in pv else "电气设备",
            "industry_tags": (["电气设备", "光伏"] if r["scode"] in pv else ["电气设备"]),
            "segment": segment_of(r["scode"]),
            "year": int(r["year"]),
            "window_type": r["window_type"],
            "window_label": chain_rules["window_label"][r["window_type"]],
            "stage_layer": r["stage_layer"],
            "stage_label": chain_rules["stage_label"][r["stage_layer"]],
            "n_deploy": int(r["n_deploy"]),
            "n_intent": int(r["n_intent"]),
            "directions": r["directions"],
            "countries": r["countries"],
            "regions": r["regions"],
            "score": int(r["score"]),
            "top_signal": r["top_signal"],
            "top_chunk": r["top_chunk"],
            "top_quote": (r["top_quote"] or "")[:120],
            "overseas_cust_share": scdata.overseas_customer_share(r["scode"], int(r["year"])),
        })
    return out


def provinces():
    return sorted(agg()["province"].dropna().unique().tolist())


def segments():
    """产业链环节出海需求统计（电力全链，claims 口径）。"""
    chain = rules()["chain_map"]["segments"]
    cl = _claims()
    dem = cl[cl["program_label"].isin(DEMAND_LABELS)]
    all_codes = set(rules()["segment_map"].keys())
    out = []
    for seg, cfg in chain.items():
        codes = {c for c in all_codes if segment_of(c) == seg}
        dem_codes = {c for c in codes if c in set(dem["scode"])}
        sub = dem[dem["scode"].map(segment_of) == seg]
        out.append({
            "segment": seg,
            "desc": cfg.get("desc", ""),
            "firms": len(codes),
            "demand_firms": len(dem_codes),
            "ratio": round(len(dem_codes) / max(len(codes), 1), 3),
            "deploy": int((sub["program_label"] == "经营部署").sum()),
            "intent": int((sub["program_label"] == "战略意图").sum()),
        })
    out.sort(key=lambda x: (-x["ratio"], -x["demand_firms"]))
    return out


def years():
    return sorted(agg()["year"].unique().tolist())


# ---------------- 企业详情 ----------------

def _claim_out(c):
    return {
        "signal_id": c["signal_id"],
        "chunk_id": c["chunk_id"],
        "year": int(c["year"]),
        "program_label": c["program_label"],
        "time_state": c["time_state"],
        "direction": c["direction"],
        "anchor_type": c["execution_anchor_type"],
        "anchor": c["execution_anchor"],
        "countries": c["geo_countries"],
        "regions": c["geo_regions"],
        "evidence_start": int(c["evidence_start"]),
        "evidence_end": int(c["evidence_end"]),
        "evidence_quote": (c["evidence_quote"] or "")[:200],
    }


def company_detail(scode, year=None):
    """企业详情：以选定年度为上下文；历史信号单独归档，不参与当年推荐。"""
    names = _coname_map()
    if scode not in names:
        return None
    g = agg()
    gy = g[g["scode"] == scode]
    p = _panel()
    prow = p[p["scode"] == scode]

    if year is not None:
        top = gy[gy["year"] == int(year)]
        top = top.iloc[0] if not top.empty else None
    else:
        gyw = gy[gy["window_type"].notna()].sort_values("year", ascending=False)
        if not gyw.empty:
            top = gyw.iloc[0]
        else:
            top = gy.sort_values("year", ascending=False).iloc[0] if not gy.empty else None
    top_year = int(top["year"]) if top is not None else (int(year) if year is not None else None)

    row_sel = prow[prow["year"] == top_year] if top_year is not None else prow
    if row_sel.empty:
        row_sel = prow.sort_values("year", ascending=False)
    has_panel = not row_sel.empty
    row = row_sel.iloc[0] if has_panel else None

    cl = _claims()
    dem = cl[(cl["scode"] == scode) & (cl["program_label"].isin(DEMAND_LABELS))]
    cur = dem[dem["year"] == top_year] if top_year is not None else dem
    # 历史信号口径：仅所选年度以前（未来的披露不冒充"历史依据"）
    hist = dem[dem["year"] < top_year] if top_year is not None else dem.iloc[0:0]
    cur = cur.sort_values(["evidence_start"], kind="stable")
    hist = hist.sort_values("year", ascending=False)

    cap = capability_score(scode, top_year)

    def gv(field, to_type=float):
        if not has_panel or row is None or field not in row.index or pd.isna(row[field]):
            return None
        return to_type(row[field])

    missing = [label for field, label in PANEL_LABELS if gv(field) is None]

    window = None
    if top is not None and top["window_type"]:
        window = {
            "year": int(top["year"]),
            "window_type": top["window_type"],
            "window_label": rules()["chains"]["window_label"].get(top["window_type"]),
            "window_note": rules()["chains"].get("window_note", {}).get(top["window_type"], ""),
            "stage_layer": top["stage_layer"],
            "stage_label": rules()["chains"]["stage_label"][top["stage_layer"]],
            "score": int(top["score"]),
        }

    sub_count = gv("overseas_sub_count")
    return {
        "scode": scode,
        "coname": names.get(scode, ""),
        "province": str(row["province"]) if has_panel and pd.notna(row["province"]) else "待核实",
        "industry": "光伏" if scode in set(industry_tags()["pv"]) else "电气设备",
        "year": top_year,
        "years": sorted(gy["year"].unique().tolist()),
        "window": window,
        "panel_status": "full" if has_panel else "text_only",
        "data_completeness": {
            "checked": len(PANEL_LABELS),
            "available": len(PANEL_LABELS) - len(missing),
            "missing": missing,
        },
        "assets": gv("assets"),
        "roa": gv("roa"),
        "leverage": gv("leverage"),
        "rd_intensity": gv("rd_intensity"),
        "overseas_sub_count": int(sub_count) if sub_count is not None else None,
        "overseas_rev_share": gv("overseas_rev_share"),
        "overseas_demand": gv("overseas_demand"),
        "soe": gv("soe"),
        "firm_age": gv("firm_age"),
        "customer_concentration": scdata.customer_concentration(scode, top_year),
        "supplier_concentration": scdata.supplier_concentration(scode, top_year),
        "overseas_customer_share": (scdata.overseas_customer_share(scode, top_year)
                                    if top_year is not None else None),
        "capability": cap,
        "signals": [_claim_out(c) for _, c in cur.head(60).iterrows()],
        "history": {
            "note": "历史信号口径：仅收录所选年度以前的披露，仅存档与展示，不参与所选年度产品推荐。",
            "count": int(len(hist)),
            "years": sorted(hist["year"].unique().tolist()),
            "items": [_claim_out(c) for _, c in hist.head(8).iterrows()],
        },
    }


def capability_score(scode, year=None):
    """能力评分卡：行业分位归一 + 加权。缺失维度输出 None（待核实），
    总分按可得维度重新归一，并给出数据完整度。"""
    sc_rules = rules()["scoring"]
    p = _panel()
    sub = p[p["scode"] == scode]
    if year is not None:
        sub = sub[sub["year"] == int(year)]

    def empty_result():
        dims = [{"key": d["key"], "label": d["label"], "value": None,
                 "raw": None, "missing": True} for d in sc_rules["dimensions"]]
        labels = [d["label"] for d in dims]
        return {"score": None, "grade": "待核实", "desc": "结构化数据缺失（该年度无面板记录），请人工核实。",
                "completeness": {"available": 0, "total": len(dims), "missing": labels},
                "dims": dims}

    if sub.empty:
        return empty_result()

    row = sub.sort_values("year", ascending=False).iloc[0]

    def pct(field, s):
        col = p[field].dropna()
        if s is None or pd.isna(s) or col.empty:
            return None
        return float((col <= s).mean())

    dims, score, avail_w = [], 0.0, 0.0
    for d in sc_rules["dimensions"]:
        field = d["field"]
        if d.get("table") == "sc":
            # 供应链维度：来自 kb-sc（客户依赖等），按样本分位归一
            raw = scdata.customer_concentration(scode, year)
            pv = None
            if raw is not None:
                col = scdata.concentration()["CustomerConcentration"].dropna()
                if not col.empty:
                    pv = float((col <= raw).mean())
        else:
            raw = row[field] if field in row.index else None
            if raw is not None and pd.isna(raw):
                raw = None
            pv = pct(field, raw)
        if pv is None:
            dims.append({"key": d["key"], "label": d["label"], "value": None,
                         "raw": None, "missing": True})
            continue
        if d["direction"] == -1:
            pv = 1 - pv
        dims.append({"key": d["key"], "label": d["label"],
                     "value": round(float(pv), 3),
                     "raw": round(float(raw), 3), "missing": False})
        score += pv * d["weight"]
        avail_w += d["weight"]

    missing_labels = [x["label"] for x in dims if x["missing"]]
    completeness = {"available": len(dims) - len(missing_labels),
                    "total": len(dims), "missing": missing_labels}
    if avail_w <= 0:
        return {"score": None, "grade": "待核实", "desc": "该年度关键维度全部缺失，请人工核实。",
                "completeness": completeness, "dims": dims}
    score = round(score / avail_w, 3)
    grade = next((g for g in sc_rules["grades"] if score >= g["min"]), sc_rules["grades"][-1])
    desc = grade["desc"]
    if missing_labels:
        desc += f"（{len(missing_labels)} 个维度缺失：{'、'.join(missing_labels)}，待核实）"
    return {"score": score, "grade": grade["label"], "desc": desc,
            "completeness": completeness, "dims": dims}


# ---------------- 推理链 ----------------

def _chain_top(scode, year):
    g = agg()
    gy = g[g["scode"] == scode]
    if gy.empty:
        return None, None
    if year is not None:
        sel = gy[gy["year"] == int(year)]
        if sel.empty or not sel.iloc[0]["window_type"]:
            return None, None
        return sel.iloc[0], int(year)
    gyw = gy[gy["window_type"].notna()]
    if gyw.empty:
        return None, None
    top = gyw.sort_values("year", ascending=False).iloc[0]
    return top, int(top["year"])


def chain(scode, year=None):
    """营销方案推理链：全部判定基于所选年度信号（历史信号不参与推荐），
    每条建议绑定 rule_id / signal_id / evidence_id。"""
    r = rules()
    products = r["products"]
    chains = r["chains"]
    top, y = _chain_top(scode, year)
    if top is None:
        return None

    cl = _claims()
    cur = cl[(cl["scode"] == scode) & (cl["year"] == y) &
             (cl["program_label"].isin(DEMAND_LABELS))].copy()
    cur = cur.sort_values(["evidence_start"], kind="stable")
    top_c = cur.iloc[0] if len(cur) else None

    def step_ev(c):
        if c is None:
            return None
        return {"quote": (c["evidence_quote"] or "")[:160],
                "signal_id": c["signal_id"], "evidence_id": c["chunk_id"]}

    steps = []
    wt = top["window_type"]
    wl = chains["window_label"].get(wt, wt)
    sl = chains["stage_label"][top["stage_layer"]]
    wn = chains.get("window_note", {}).get(wt, "")

    # step 1 窗口期
    steps.append({
        "key": "window",
        "label": chains["step_order"][0]["label"],
        "title": f"{wl} · {sl}",
        "detail": (f"所选年度 {y} 披露 {int(top['n_deploy'])} 条经营部署、{int(top['n_intent'])} 条战略意图；"
                   f"窗口类型「{wl}」，分层「{sl}」。" + (f" {wn}" if wn else "")),
        "rule_id": RULE_IDS["window"].get(wt, "RULE_WINDOW_OTHER"),
        "evidence": step_ev(top_c),
    })

    # step 2 方向与模式
    dirs = top["directions"]
    dir_sources = []
    for d in dirs:
        dcl = cur[cur["direction"] == d]
        c0 = dcl.iloc[0] if len(dcl) else top_c
        mode = products["direction_map"].get(d, {}).get("mode", "—")
        dir_sources.append({"direction": d, "mode": mode,
                            "rule_id": f"RULE_DIR_{d}",
                            "signal_id": c0["signal_id"] if c0 is not None else None,
                            "evidence_id": c0["chunk_id"] if c0 is not None else None})
    mode_desc = "、".join(f"{s['direction']}（{s['mode']}）" for s in dir_sources) or "—"
    steps.append({
        "key": "direction",
        "label": chains["step_order"][1]["label"],
        "title": mode_desc,
        "detail": f"识别到的出海方向：{'、'.join(dirs) if dirs else '未分类'}；硬锚点 {int(top['n_hard'])} 条。",
        "evidence": step_ev(top_c),
        "sources": dir_sources,
    })

    # step 3 产品匹配（仅当年信号；锚点触发按 方向 语境细化）
    recs, seen = [], {}

    def add_rec(key, reason, rule_id, c):
        if c is None:
            return
        info = products["catalog"].get(key)
        if not info:
            return
        if key in seen:
            seen[key]["n_signals"] += 1
            return
        rec = {"key": key, "name": info["name"], "category": info["category"],
               "reason": reason, "rule_id": rule_id, "n_signals": 1,
               "signal_id": c["signal_id"], "evidence_id": c["chunk_id"],
               "quote": (c["evidence_quote"] or "")[:120]}
        seen[key] = rec
        recs.append(rec)

    for d in dirs:
        dcl = cur[cur["direction"] == d]
        c0 = dcl.iloc[0] if len(dcl) else top_c
        for k in products["direction_map"].get(d, {}).get("products", []):
            add_rec(k, f"方向「{d}」命中方向规则", f"RULE_DIR_{d}", c0)

    for _, c in cur.iterrows():
        a = c["execution_anchor_type"]
        d = c["direction"]
        for t in products["anchor_extra"].get(a, []):
            if "if_directions" in t and d not in t["if_directions"]:
                continue   # 语境守卫：同一锚点按方向区分业务，防止过度推荐
            add_rec(t["product"],
                    f"{t['reason']}（锚点「{a}」，方向「{d}」）",
                    f"RULE_ANCHOR_{a}_{t['product']}", c)

    for k in products["window_extra"].get(wt, []):
        add_rec(k, f"窗口类型「{wl}」阶段配套", f"RULE_WINDOW_{wt}", top_c)

    if top["countries"]:
        ccl = cur[cur["geo_countries"].map(lambda xs: len(xs) > 0)]
        c0 = ccl.iloc[0] if len(ccl) else top_c
        for k in products["country_extra"]:
            add_rec(k, f"披露明确国别（{'、'.join(top['countries'])}），叠加清算与避险服务",
                    "RULE_COUNTRY_CLEARING", c0)

    n_dir = sum(1 for x in recs if x["rule_id"].startswith("RULE_DIR_"))
    n_anchor = sum(1 for x in recs if x["rule_id"].startswith("RULE_ANCHOR_"))
    n_window = sum(1 for x in recs if x["rule_id"].startswith("RULE_WINDOW_"))
    n_country = sum(1 for x in recs if x["rule_id"] == "RULE_COUNTRY_CLEARING")
    prod_names = [f"{x['name']}（{x['category']}）" for x in recs]
    steps.append({
        "key": "product",
        "label": chains["step_order"][2]["label"],
        "title": f"匹配 {len(recs)} 款产品" if recs else "—",
        "detail": (f"匹配依据（仅使用 {y} 年度信号，历史信号不参与）："
                   f"方向规则 {n_dir} 条、锚点触发 {n_anchor} 条、"
                   f"窗口配套 {n_window} 条、国别叠加 {n_country} 条。"
                   f"产品明细可点击展开查看依据与证据。"),
        "evidence": None,
        "products": recs,
    })

    # step 4 前置条件
    prereqs = []
    for k in [x["key"] for x in recs]:
        if k in products["prereq"]:
            prereqs.append(f"{products['catalog'][k]['name']}：{products['prereq'][k]}")
    steps.append({
        "key": "prereq",
        "label": chains["step_order"][3]["label"],
        "title": f"共 {len(prereqs)} 项前置条件" if prereqs else "无额外前置条件",
        "items": prereqs or ["无额外前置条件"],
        "detail": "前置条件由产品规则库定义，落地时可替换为行内产品库。",
        "rule_id": "RULE_PREREQ",
        "evidence": None,
    })

    return {
        "scode": scode,
        "year": y,
        "countries": top["countries"],
        "regions": top["regions"],
        "steps": steps,
        "as_of": f"全部判定基于 {y} 年度信号；历史信号仅存档展示，不参与推荐。",
    }


def briefing(scode, year=None):
    d = company_detail(scode, year)
    ch = chain(scode, year)
    if not d or not ch or not d["window"]:
        return None
    cap = d["capability"]
    w = d["window"]
    prod_step = next(s for s in ch["steps"] if s["key"] == "product")
    prereq_step = next(s for s in ch["steps"] if s["key"] == "prereq")
    win_step = ch["steps"][0]

    if cap["score"] is None:
        cap_line = (f"能力评分待核实（数据完整度 {cap['completeness']['available']}/{cap['completeness']['total']}）"
                    f"——{cap['desc']}")
    else:
        dims_txt = "；".join(
            f"{x['label']} 分位 {x['value']:.0%}" if x["value"] is not None
            else f"{x['label']} 待核实" for x in cap["dims"])
        cap_line = (f"能力评分 {cap['score']:.2f}，分级「{cap['grade']}」——{cap['desc']}。"
                    f"关键维度：{dims_txt}。本项为辅助判断，不替代人工尽调。")
    conc = d.get("customer_concentration")
    if conc is not None:
        cap_line += (f" 客户依赖：前五大客户集中度 {conc:.0f}%（样本中位 32%），"
                     + ("偏高，建议关注订单稳定性。" if conc > 50 else "可控。"))

    win_ev = win_step.get("evidence") or {}
    ev_txt = f"证据：「{win_ev.get('quote', '')}」" if win_ev.get("quote") else "证据：待核实"
    osc = d.get("overseas_customer_share")
    osc_txt = (f"结构化供应链验证：该年度前五大客户中境外主体销售占比 {osc:.1f}%。"
               if osc is not None
               else "结构化供应链数据未见境外客户（名称口径），以文本信号为准。")

    prod_lines = [f"{x['name']}（{x['reason']}）" for x in prod_step.get("products", [])]
    prod_body = "；".join(prod_lines) if prod_lines else prod_step["title"]

    sections = [
        {"heading": "一、能力就绪度",
         "body": cap_line,
         "rule_ids": ["RULE_CAPABILITY", "RULE_SC_CONC"],
         "signal_ids": [], "evidence_ids": []},
        {"heading": "二、出海需求判断",
         "body": (f"{w['window_label']}（{w['stage_label']}），强度分 {w['score']}。"
                  f"{ch['steps'][1]['title']}。{ev_txt} {osc_txt}"
                  + (f" {w['window_note']}" if w.get("window_note") else "")),
         "rule_ids": [win_step.get("rule_id"), "RULE_SC_OVERSEAS"] +
                     [s["rule_id"] for s in ch["steps"][1].get("sources", [])],
         "signal_ids": [win_ev["signal_id"]] if win_ev.get("signal_id") else [],
         "evidence_ids": [win_ev["evidence_id"]] if win_ev.get("evidence_id") else []},
        {"heading": "三、产品组合建议",
         "body": prod_body,
         "rule_ids": [x["rule_id"] for x in prod_step.get("products", [])],
         "signal_ids": [x["signal_id"] for x in prod_step.get("products", []) if x.get("signal_id")],
         "evidence_ids": [x["evidence_id"] for x in prod_step.get("products", []) if x.get("evidence_id")]},
        {"heading": "四、前置条件与触达要点",
         "body": ("；".join(prereq_step.get("items", []) or [prereq_step["title"]]) + "。"
                  f"目标国别：{'、'.join(ch['countries']) if ch['countries'] else '未披露明确国别'}。"
                  + (f"区域表述：{'、'.join(ch['regions'])}。" if ch["regions"] else "")
                  + "触达要点：以账户方案与保函预授信为敲门砖，融资需求后置于行内授信流程。"),
         "rule_ids": ["RULE_PREREQ", "RULE_COUNTRY_CLEARING"],
         "signal_ids": [], "evidence_ids": []},
    ]
    return {
        "scode": scode,
        "coname": d["coname"],
        "title": f"{d['coname']} 访前简报（{ch['year']} 年度）",
        "year": ch["year"],
        "sections": sections,
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


def supply_chain(scode, year=None):
    """供应链示例：结构化边（CSMAR 前五大客户/供应商，量化）+ 文本具名锚点
    + 子公司国家边（as-of）+ 二跳链；供应商边自 v1.4 起为真实数据。"""
    cl = _claims()
    subs = _sub_countries()
    names = _coname_map()
    scinfo = scdata.sc_of(scode, year)

    customers = []
    for c in scinfo["customers"][:3]:
        customers.append({
            "name": c["name"], "rank": c["rank"], "proportion": c["proportion"],
            "overseas": c["overseas"], "source": "structured",
            "note": f"第 {c['rank']} 大客户 · 销售占比 {c['proportion']}%"
                    + (" · 境外主体" if c["overseas"] else ""),
        })
    text_cust = cl[(cl["scode"] == scode) &
                   (cl["execution_anchor_type"] == "named_customer")]
    for _, c in text_cust.drop_duplicates("execution_anchor").head(3).iterrows():
        if any(x["name"] == c["execution_anchor"] for x in customers):
            continue
        customers.append({
            "name": c["execution_anchor"], "rank": None, "proportion": None,
            "overseas": None, "source": "text",
            "note": (c["evidence_quote"] or "")[:80],
        })

    suppliers = []
    for c in scinfo["suppliers"][:3]:
        suppliers.append({
            "name": c["name"], "rank": c["rank"], "proportion": c["proportion"],
            "overseas": c["overseas"], "source": "structured",
            "note": f"第 {c['rank']} 大供应商 · 采购占比 {c['proportion']}%"
                    + (" · 境外主体" if c["overseas"] else ""),
        })

    sub_c = subs[subs["scode"] == scode]
    if year is not None:
        sub_c = sub_c[sub_c["year"] <= int(year)]
    countries = sorted(set(sub_c["country_canon"].dropna()))
    as_of = f"截至 {int(year)} 年度" if year is not None else "全期口径"

    nodes = [{"id": "self", "label": names.get(scode, scode), "type": "企业"}]
    edges = []
    for i, c in enumerate(customers):
        nodes.append({"id": f"cust{i}", "label": c["name"], "type": "客户"})
        edges.append({"source": "self", "target": f"cust{i}",
                      "rel": "SELLS_TO", "note": c["note"]})
    for i, c in enumerate(suppliers):
        nodes.append({"id": f"sup{i}", "label": c["name"], "type": "供应商"})
        edges.append({"source": "self", "target": f"sup{i}",
                      "rel": "BUYS_FROM", "note": c["note"]})
    for i, c in enumerate(countries):
        nodes.append({"id": f"c{i}", "label": c, "type": "国家"})
        edges.append({"source": "self", "target": f"c{i}",
                      "rel": "OWNS_SUB_IN", "note": "子公司所在国"})

    return {
        "scode": scode,
        "sample": bool(scinfo["customers"]),
        "note": f"演示样例（{as_of}）：客户/供应商边来自 CSMAR 前五大明细（结构化量化），"
                "具名锚点来自年报文本，国家边来自子公司数据；全量供应链为 P2 扩展。",
        "nodes": nodes,
        "edges": edges,
        "detail": scinfo,
    }
