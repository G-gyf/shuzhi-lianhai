# -*- coding: utf-8 -*-
"""图适配层。

最小闭环默认使用 SQLite 构建子图 JSON（与 Neo4j 返回结构一致）。
若设置 NEO4J_URI 环境变量且 neo4j 驱动可用，则切换到 Neo4j 查询
（kg_api 模式，连接参数与 kg_api 相同）。前端不感知实现差异。
"""
import json
import os

import pandas as pd

from .logic import _conn, _claims, _coname_map, rules

NEO4J_URI = os.getenv("NEO4J_URI")


def _neo4j_driver():
    if not NEO4J_URI:
        return None
    try:
        from neo4j import GraphDatabase
    except ImportError:
        return None
    driver = GraphDatabase.driver(
        NEO4J_URI,
        auth=(os.getenv("NEO4J_USER", "neo4j"),
              os.getenv("NEO4J_PASSWORD", "")),
    )
    return driver


def get_company_graph(scode):
    """企业-信号-方向-国别 子图（演示可视化用）。"""
    driver = _neo4j_driver()
    if driver is not None:
        return _neo4j_graph(driver, scode)
    return _sqlite_graph(scode)


def _sqlite_graph(scode):
    cl = _claims()
    names = _coname_map()
    dem = cl[(cl["scode"] == scode) &
             (cl["program_label"].isin(("经营部署", "战略意图")))].copy()
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
        for country in c["country_hits"]:
            if country not in seen_ctry:
                seen_ctry.add(country)
                nodes.append({"id": f"c{country}", "label": country, "type": "国别"})
            edges.append({"source": sid, "target": f"c{country}", "rel": "TARGETS"})
    return {"scode": scode, "nodes": nodes, "edges": edges}


def _neo4j_graph(driver, scode):
    """Neo4j 实现：结构与 SQLite 版一致。当前骨架数据入图后启用。"""
    with driver.session() as s:
        recs = s.run(
            "MATCH (c:Company {scode:$scode})-[:DISCLOSED]->(s:Signal) "
            "OPTIONAL MATCH (s)-[:HAS_DIRECTION]->(d:Direction) "
            "OPTIONAL MATCH (s)-[:TARGETS]->(t:Country) "
            "RETURN c, s, d, t LIMIT 200", scode=scode)
        nodes, edges, seen = [], [], set()

        def nid(lbl, key):
            return f"{lbl}{key}"

        for r in recs:
            c, s, d, t = r["c"], r["s"], r["d"], r["t"]
            if nid("c", c["scode"]) not in seen:
                seen.add(nid("c", c["scode"]))
                nodes.append({"id": nid("c", c["scode"]), "label": c.get("coname", c["scode"]), "type": "企业"})
            sid = nid("s", f"{s['chunk_id']}_{s['claim_number']}")
            if sid not in seen:
                seen.add(sid)
                nodes.append({"id": sid, "label": s.get("direction", ""), "type": "信号"})
            edges.append({"source": nid("c", c["scode"]), "target": sid, "rel": "DISCLOSED"})
            if d is not None:
                did = nid("d", d["name"])
                if did not in seen:
                    seen.add(did)
                    nodes.append({"id": did, "label": d["name"], "type": "方向"})
                edges.append({"source": sid, "target": did, "rel": "HAS_DIRECTION"})
            if t is not None:
                tid = nid("t", t["name"])
                if tid not in seen:
                    seen.add(tid)
                    nodes.append({"id": tid, "label": t["name"], "type": "国别"})
                edges.append({"source": sid, "target": tid, "rel": "TARGETS"})
    return {"scode": scode, "nodes": nodes, "edges": edges}


def country_card(country):
    """国别卡片（占位）：公开区域信息 + 银行内部规则占位。"""
    cr = rules()["countries"]
    info = cr["countries"].get(country, {})
    base = cr["default"]
    return {
        "country": country,
        "region": info.get("region", "—"),
        "clearing": info.get("clearing_note", base["clearing"]),
        "treasury": base["treasury"],
        "hedging": base["hedging"],
        "note": cr["note"],
    }
