# -*- coding: utf-8 -*-
"""数智链海 · 服务层（FastAPI 单服务）

接口（/api/*）：
  GET  /api/meta                    知识库版本与可选项
  GET  /api/radar                   辖区意图强度排行（province/industry/year）
  GET  /api/company/{scode}         企业详情（?year= 选定年度，缺省取最新窗口年度）
  GET  /api/company/{scode}/graph   企业-信号-方向-国别子图（?year=）
  GET  /api/company/{scode}/supply-chain  供应链示例（?year=，国别边 as-of）
  GET  /api/company/{scode}/chain   营销方案推理链（?year=，仅当年信号参与推荐）
  GET  /api/company/{scode}/briefing 访前简报（?year=）
  GET  /api/evidence/{chunk_id}     原文片段 + 证据锚点区间
  GET  /api/country/{name}          国别卡片（别名归一；区域级表述单独提示）
  GET  /api/health                  健康检查
"""
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from . import graph, logic

ROOT = Path(__file__).resolve().parent.parent
app = FastAPI(title="数智链海 · 服务层", version="1.3")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)


@app.get("/api/meta")
def api_meta():
    return {
        "kb_version": "kb-2023",
        "industries": ["全部", "电气设备", "光伏"],
        "pv_overlap": len(logic.industry_tags()["pv"]),
        "pv_full": len(logic.industry_tags()["pv_full"]),
        "provinces": logic.provinces(),
        "years": logic.years(),
        "note": "光伏=申万2021 6305xx 成分；重叠企业双标签复用，沪深增量待补标，北交所待第二轮。",
    }


@app.get("/api/radar")
def api_radar(province: str | None = None, industry: str | None = None,
              year: int | None = None, limit: int = 200,
              sort: str = Query("window", pattern="^(window|score)$"),
              segment: str | None = None):
    return {"items": logic.radar(province, industry, year, limit, sort, segment)}


@app.get("/api/segments")
def api_segments():
    return {"items": logic.segments()}


@app.get("/api/company/{scode}")
def api_company(scode: str, year: int | None = None):
    d = logic.company_detail(scode, year)
    if not d:
        raise HTTPException(404, "company not found")
    return d


@app.get("/api/company/{scode}/graph")
def api_company_graph(scode: str, year: int | None = None):
    return graph.get_company_graph(scode, year)


@app.get("/api/company/{scode}/supply-chain")
def api_supply_chain(scode: str, year: int | None = None):
    return logic.supply_chain(scode, year)


@app.get("/api/company/{scode}/chain")
def api_chain(scode: str, year: int | None = None):
    ch = logic.chain(scode, year)
    if not ch:
        raise HTTPException(404, "no demand chain for this company")
    return ch


@app.get("/api/company/{scode}/briefing")
def api_briefing(scode: str, year: int | None = None):
    b = logic.briefing(scode, year)
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
