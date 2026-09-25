# -*- coding: utf-8 -*-
"""协议冻结层：请求 / 结果 / 引用 / SSE 事件的数据结构与常量（方案第 7、8、9 章）。

说明：
- 本模块中的 `/api/v1/*` 路径、事件名与数据结构为项目内部协议（v1），
  不是 Coze 官方原生字段，也不是当前已有接口。
- 变更需同步 `coze/examples/`、`coze/tool_openapi.yaml` 与 `web/assets/` 前端。
"""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

SCHEMA_VERSION = "1.0"

# ---------------- SSE 事件名（网关协议，不直接暴露 Coze 原始事件） ----------------
EV_REQUEST_STARTED = "request_started"
EV_STATUS = "status"
EV_CLARIFICATION = "clarification"
EV_ANSWER_DELTA = "answer_delta"
EV_ORBS_READY = "orbs_ready"
EV_ANALYSIS_READY = "analysis_ready"
EV_ERROR = "error"
EV_DONE = "done"

# ---------------- 状态阶段（真实节点状态，不做虚假百分比） ----------------
PHASE_QUERYING = "querying"      # 查询中：受控工具检索事实
PHASE_ANALYZING = "analyzing"    # 分析中：模型/规则引擎形成分析草稿
PHASE_VALIDATING = "validating"  # 校验中：后端引用与口径检查
PHASE_ANSWERED = "answered"      # 回答呈现完成

# ---------------- 光球类型 ----------------
ORB_KINDS = (
    "company",      # 企业球
    "evidence",     # 原文球
    "profile",      # 画像球
    "product",      # 产品依据球
    "compare",      # 对比球
    "analysis",     # AI 方案球（标注为推断/方案，不冒充事实）
    "checklist",    # 待核实事项球
)

# ---------------- 引用类型 ----------------
REF_KINDS = (
    "evidence",     # ev:<chunk_id>:<claim_number>:<text_version>
    "metric",       # metric:<table>:<scode>:<year>:<field>
    "product",      # product:<product_id>
    "analysis",     # analysis:<analysis_id>:<recommendation_id>
    "compare",      # compare:<comparison_id>
    "regional",     # regional:<source_id>:<doc_id>
    "company",      # company:<scode>:<year>（企业球，打开确定性企业详情）
)

# 回答块类型
BlockKind = Literal["fact", "hypothesis", "product", "checklist", "note"]

# 推荐优先级
Priority = Literal["discussion_first", "standard", "later", "not_applicable"]

# 资格状态：eligible 已满足 / not_eligible 明确不适用 / unknown 待确认
Eligibility = Literal["eligible", "not_eligible", "unknown"]


class PageContext(BaseModel):
    """页面上下文：由前端随消息上报；后端仍以服务端会话状态为准。"""
    scode: Optional[str] = None
    year: Optional[int] = None
    snapshot_id: Optional[str] = None
    view: Optional[str] = None


class Preferences(BaseModel):
    """经理偏好：服务方向、行业、地区、方案长度与关注名单。"""
    service_focus: list[str] = Field(default_factory=list)
    exclude_financing: bool = False
    default_region: Optional[str] = None
    focus_industries: list[str] = Field(default_factory=list)
    plan_length: Literal["brief", "standard", "detailed"] = "brief"
    watchlist: list[str] = Field(default_factory=list)


class ChatRequest(BaseModel):
    """POST /api/v1/chat/stream 请求体。

    经理身份、地区权限由服务器根据 Authorization 头注入，
    不能由本 JSON 自报（见方案 7.3 节）。
    """
    session_id: Optional[str] = None
    client_request_id: str = Field(min_length=1, max_length=64)
    message: str = Field(min_length=1, max_length=4000)
    page_context: Optional[PageContext] = None
    preferences: Optional[Preferences] = None


class AnswerBlock(BaseModel):
    kind: BlockKind = "fact"
    text: str
    refs: list[str] = Field(default_factory=list)


class Recommendation(BaseModel):
    id: str
    product_ref: Optional[str] = None
    priority: Priority = "standard"
    reason: str
    evidence_refs: list[str] = Field(default_factory=list)
    product_source_refs: list[str] = Field(default_factory=list)
    eligibility: Eligibility = "unknown"
    missing_conditions: list[str] = Field(default_factory=list)


class Question(BaseModel):
    text: str
    related_recommendation: Optional[str] = None


class Orb(BaseModel):
    id: str
    kind: str
    label: str
    summary: str = ""
    ref_id: Optional[str] = None
    state: Literal["ready", "pending", "blocked"] = "ready"


class AnalysisContext(BaseModel):
    scode: Optional[str] = None
    coname: Optional[str] = None
    year: Optional[int] = None
    snapshot_id: Optional[str] = None
    product_version: Optional[str] = None


class Provenance(BaseModel):
    engine: str = "unknown"           # coze | rules-demo
    workflow_version: str = ""
    generated_at: str = ""
    request_id: str = ""


class AnalysisDraft(BaseModel):
    """Coze 草稿与后端正式结果分离：模型输出事实引用/分析/候选产品/问题，
    后端生成 analysis_id、检查引用后构建光球（方案 8.1 节）。"""
    schema_version: str = SCHEMA_VERSION
    context: AnalysisContext = Field(default_factory=AnalysisContext)
    status: str = "draft"             # draft -> validated -> partial
    answer_blocks: list[AnswerBlock] = Field(default_factory=list)
    recommendations: list[Recommendation] = Field(default_factory=list)
    questions: list[Question] = Field(default_factory=list)
    orbs: list[Orb] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    provenance: Provenance = Field(default_factory=Provenance)


class BriefingRequest(BaseModel):
    """POST /api/v1/briefings：从已保存 analysis_id 生成/编辑简报，不重新计算事实。"""
    analysis_id: str
    title: Optional[str] = None
    edits: list[dict[str, Any]] = Field(default_factory=list)


class DataSourceSpec(BaseModel):
    """数据源登记（方案 11.3 节示例）。region_id 由服务器权限校验后覆盖。"""
    source_id: str = Field(min_length=1, max_length=64)
    name: str
    scope: Literal["region", "branch", "personal", "global"] = "region"
    region_id: Optional[str] = None
    kind: Literal["document_collection", "table", "external_readonly"] = "document_collection"
    adapter_id: str = "document_reader_v1"
    entity_key: Optional[str] = None
    time_field: Optional[str] = None
    version: str = "v1"
    allowed_capabilities: list[str] = Field(default_factory=lambda: ["search", "read_reference"])
    status: Literal["draft", "validated", "active", "disabled"] = "draft"
    description: str = ""


# ---------------- 引用编码（稳定字符串，可解析、可校验） ----------------

def ev_ref(chunk_id, claim_number, text_version):
    return f"ev:{chunk_id}:{int(claim_number)}:{text_version}"


def metric_ref(table, scode, year, field):
    return f"metric:{table}:{scode}:{int(year)}:{field}"


def product_ref(product_id):
    return f"product:{product_id}"


def analysis_ref(analysis_id, recommendation_id):
    return f"analysis:{analysis_id}:{recommendation_id}"


def compare_ref(comparison_id):
    return f"compare:{comparison_id}"


def regional_ref(source_id, doc_id):
    return f"regional:{source_id}:{doc_id}"


# 引用前缀 → 类型归一（ev: 与 evidence 等价）
REF_ALIASES = {"ev": "evidence", "pr": "product", "an": "analysis",
               "cmp": "compare", "rg": "regional", "co": "company"}


def parse_ref(ref_id: str) -> Optional[tuple]:
    """按 `kind:parts...` 解析；非法返回 None。返回的 kind 为归一化类型名。"""
    if not isinstance(ref_id, str) or ":" not in ref_id:
        return None
    kind, _, rest = ref_id.partition(":")
    kind = REF_ALIASES.get(kind, kind)
    if kind not in REF_KINDS:
        return None
    return (kind, rest.split(":"))
