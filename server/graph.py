# -*- coding: utf-8 -*-
"""SQLite 证据子图；银行实名关系与 Neo4j 仅为系统设计，本项目不实现。"""
import os

import pandas as pd

from .geo import is_region, normalize_name
from .logic import _claims, _coname_map, rules

def get_company_graph(scode, year=None):
    """本项目仅运行 SQLite 证据子图；Neo4j 为银行实名数据预留设计。"""
    from .logic import resolve_year
    return _sqlite_graph(scode, resolve_year(scode, year))


def _sqlite_graph(scode, year=None):
    cl = _claims()
    names = _coname_map()
    dem = cl[(cl["scode"] == scode) &
             (cl["program_label"].isin(("经营部署", "战略意图")))].copy()
    if year is not None:
        dem = dem[dem["year"] == int(year)]
    dem = dem.sort_values("year", ascending=False).head(30)
    nodes = [{"id": "self", "label": names.get(scode, scode), "type": "企业"}]
    edges = []
    seen_dir, seen_ctry = set(), set()
    for _, c in dem.iterrows():
        sid = f"s{c['chunk_id']}_{c['claim_number']}"
        nodes.append({"id": sid, "label": f"{c['direction']} · {c['program_label']}",
                      "type": "信号", "year": int(c["year"])})
        edges.append({"source": "self", "target": sid, "rel": "DISCLOSED"})
        d = c["direction"]
        if d and d not in ("null", ""):
            if d not in seen_dir:
                seen_dir.add(d)
                nodes.append({"id": f"d{d}", "label": d, "type": "方向"})
            edges.append({"source": sid, "target": f"d{d}", "rel": "HAS_DIRECTION"})
        for country in c["geo_countries"]:
            if country not in seen_ctry:
                seen_ctry.add(country)
                nodes.append({"id": f"c{country}", "label": country, "type": "国别"})
            edges.append({"source": sid, "target": f"c{country}", "rel": "TARGETS"})
    return {"scode": scode, "year": year, "nodes": nodes, "edges": edges}


def country_card(country):
    """国别卡片：别名归一 → canonical；区域级表述单独提示，不冒充具体国家。"""
    cr = rules()["countries"]
    canon = normalize_name(country) if country else None
    if canon:
        info = cr["countries"].get(canon, {})
        base = cr["default"]
        return {
            "country": canon, "raw": country, "type": "country",
            "region": info.get("region", "—"),
            "clearing": info.get("clearing_note", base["clearing"]),
            "treasury": base["treasury"],
            "hedging": base["hedging"],
            "note": cr["note"],
        }
    if is_region(country):
        return {
            "country": country, "raw": country, "type": "region",
            "region": "区域市场",
            "clearing": "区域级表述未绑定具体国家，建议人工核实目标国后叠加清算/避险建议。",
            "treasury": cr["default"]["treasury"],
            "hedging": cr["default"]["hedging"],
            "note": cr["note"],
        }
    return {
        "country": country or "", "raw": country, "type": "unknown",
        "region": "—", "clearing": "未识别国别，待人工核实。",
        "treasury": "—", "hedging": "—", "note": cr["note"],
    }
