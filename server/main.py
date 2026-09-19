# -*- coding: utf-8 -*-
"""数智链海 · 服务层（FastAPI 单服务）

接口（/api/*）：
  GET  /api/meta                    知识库版本与可选项
  GET  /api/radar                   辖区意图强度排行（province/industry/year）
  GET  /api/company/{scode}         企业详情（画像+评分+信号）
  GET  /api/company/{scode}/graph   企业-信号-方向-国别子图
  GET  /api/company/{scode}/supply-chain  供应链示例
  GET  /api/company/{scode}/chain   营销方案推理链
  GET  /api/company/{scode}/briefing 访前简报
  GET  /api/evidence/{chunk_id}     原文片段 + 证据锚点区间
  GET  /api/country/{name}          国别卡片（占位）
  GET  /api/health                  健康检查
"""
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from . import graph, logic

ROOT = Path(__file__).resolve().parent.parent
app = FastAPI(title="数智链海 · 服务层", version="1.2")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)


@app.get("/api/meta")
def api_meta():
    return {
        "kb_version": "kb-2023",
        "industry": "电气设备（双行业扩展中）",
        "provinces": logic.provinces(),
        "years": logic.years(),
        "note": "最小闭环：单行业冻结快照；光伏为增量接入。",
    }


@app.get("/api/radar")
def api_radar(province: str | None = None, industry: str | None = None,
              year: int | None = None, limit: int = 200):
    return {"items": logic.radar(province, industry, year, limit)}


@app.get("/api/company/{scode}")
def api_company(scode: str):
    d = logic.company_detail(scode)
    if not d:
        raise HTTPException(404, "company not found")
    return d


@app.get("/api/company/{scode}/graph")
def api_company_graph(scode: str):
    return graph.get_company_graph(scode)


@app.get("/api/company/{scode}/supply-chain")
def api_supply_chain(scode: str):
    return graph_placeholder(scode)


def graph_placeholder(scode: str):
    return logic.supply_chain(scode)


@app.get("/api/company/{scode}/chain")
def api_chain(scode: str):
    ch = logic.chain(scode)
    if not ch:
        raise HTTPException(404, "no demand chain for this company")
    return ch


@app.get("/api/company/{scode}/briefing")
def api_briefing(scode: str):
    b = logic.briefing(scode)
    if not b:
        raise HTTPException(404, "briefing unavailable")
    return b


@app.get("/api/evidence/{chunk_id}")
def api_evidence(chunk_id: str):
    e = logic.evidence(chunk_id)
    if not e:
        raise HTTPException(404, "chunk not found")
    return e


@app.get("/api/country/{name}")
def api_country(name: str):
    return graph.country_card(name)


@app.get("/api/health")
def api_health():
    return {"status": "ok", "kb": "kb-2023"}


app.mount("/", StaticFiles(directory=ROOT / "web", html=True), name="web")
