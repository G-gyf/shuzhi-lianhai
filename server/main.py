# -*- coding: utf-8 -*-
"""数智链海 · 服务层（FastAPI 单服务）

既有接口（/api/*）：
  GET  /api/meta                    知识库版本与可选项
  GET  /api/radar                   辖区意图强度排行（province/industry/year）
  GET  /api/company/{scode}         企业详情（?year= 选定年度，缺省取企业最新可用数据年度）
  GET  /api/company/{scode}/graph   企业-信号-方向-国别子图（?year=）
  GET  /api/company/{scode}/supply-chain  供应链示例（?year=，国别边 as-of）
  GET  /api/company/{scode}/chain   营销方案推理链（?year=，仅当年信号参与推荐）
  GET  /api/company/{scode}/briefing 访前简报（?year=）
  GET  /api/evidence/{chunk_id}     原文片段 + 证据锚点区间
  GET  /api/country/{name}          国别卡片（别名归一；区域级表述单独提示）
  GET  /api/health                  健康检查

新增接口（/api/v1/*，Coze 对话工作台，项目内部协议）：
  POST /api/v1/chat/stream                   创建本轮请求并以 SSE 返回状态与结果
  POST /api/v1/chat/requests/{id}/cancel     取消显示与本地编排
  GET  /api/v1/chat/sessions/{id}            恢复本用户会话
  GET  /api/v1/analyses/{analysis_id}        读取已保存结构化分析
  GET  /api/v1/references/{ref_id}           按权限解析确定性详情
  POST /api/v1/briefings                     从 analysis_id 生成简报，不重新计算事实
  GET/PATCH /api/v1/me/preferences           经理偏好
  GET  /api/v1/me/capabilities               当前用户可使用的功能与资料源
  POST /api/v1/tools/{tool}                  受控业务工具（context_token 鉴权，供 Coze 调用）
  POST /api/v1/data-sources …                资料源登记/校验/激活/停用
  GET  /api/v1/extensions …                  扩展目录与启用
  POST /api/v1/feedback                      经理反馈
"""
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from . import chat, extensions, graph, logic, runtime, tool_api

ROOT = Path(__file__).resolve().parent.parent
app = FastAPI(title="数智链海 · 服务层", version="2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)


@app.on_event("startup")
def _startup():
    runtime.init_runtime()
    extensions._seed()


@app.get("/api/meta")
def api_meta():
    return {
        "kb_version": "kb-2023",
        "snapshot_id": runtime.get_snapshot(),
        "industries": ["全部"] + list(logic.rules()["chain_map"]["segments"]),
        "capability_dimensions": len(logic.rules()["scoring"]["dimensions"]),
        "country_dictionary_count": len(logic.rules()["countries"]["countries"]),
        "claim_counts": {"all": len(logic._claims()), "demand": int(logic._claims()["program_label"].isin(logic.DEMAND_LABELS).sum())},
        "text_counts": {"active": logic._conn().execute("SELECT COUNT(*) FROM chunks").fetchone()[0],
                        "excluded": logic._conn().execute("SELECT COUNT(*) FROM excluded_chunks").fetchone()[0]},
        "pv_overlap": len(logic.industry_tags()["pv"]),
        "pv_full": len(logic.industry_tags()["pv_full"]),
        "provinces": logic.provinces(),
        "years": logic.years(),
        "note": "现有电气设备样本按细分行业标注；光伏37为样本与外部74家名单交集，非建设完成率；本期不扩样。",
    }


@app.get("/api/radar")
def api_radar(province: str | None = None, industry: str | None = None,
              year: int | None = None, limit: int = 200,
              sort: str = Query("window", pattern="^(window|score)$"),
              segment: str | None = None):
    items = logic.radar(province, industry, year, len(logic.agg()), sort, segment)
    return {"items": items[:max(0, min(limit, 2000))], "total": len(items), "unit": "企业-年"}


@app.get("/api/segments")
def api_segments(year: int | None = None, province: str | None = None, industry: str | None = None):
    return {"items": logic.segments(year, province, industry), "year": year,
            "scope": "所选年度" if year is not None else "2018—2023全期去重企业"}


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
    return {"status": "ok", "kb": "kb-2023",
            "snapshot_id": runtime.get_snapshot()}


# ---------------- /api/v1 对话工作台 ----------------
app.include_router(chat.router)
app.include_router(tool_api.router)
app.include_router(extensions.router)

app.mount("/", StaticFiles(directory=ROOT / "web", html=True), name="web")
