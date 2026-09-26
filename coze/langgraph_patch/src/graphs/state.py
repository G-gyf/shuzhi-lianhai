"""数智链海出海助手 - 工作流状态定义"""
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


class GlobalState(BaseModel):
    """全局过程状态（LangGraph 自动合并各节点输出到此）"""
    # ---------------------- 工作流输入（N01）--------------------
    message: str = Field(..., description="用户问题")
    context_token: str = Field(..., description="短期上下文令牌（后端每轮签发）")
    page_context: Optional[Dict[str, Any]] = Field(default=None, description="页面上下文（scode/year/view）")
    history_summary: Optional[str] = Field(default=None, description="前几轮对话摘要")
    preferences: Optional[Dict[str, Any]] = Field(default=None, description="客户经理偏好（service_focus/exclude_financing）")
    data_snapshot: Optional[str] = Field(default=None, description="数据快照 ID")
    product_version: Optional[str] = Field(default=None, description="产品资料版本")
    tools_base_url: Optional[str] = Field(default=None, description="工具服务地址")
    allowed_tools: Optional[List[str]] = Field(default=None, description="允许调用的工具清单")
    max_tool_calls: Optional[int] = Field(default=None, description="工具调用上限")
    max_compare_companies: Optional[int] = Field(default=None, description="对比企业数上限")
    # ---------------------- N02 意图与参数 --------------------
    intent: Optional[str] = Field(default=None, description="意图分类")
    companies: Optional[List[Dict[str, Any]]] = Field(default=None, description="企业代码列表")
    year: Optional[int] = Field(default=None, description="用户提到的年份")
    filters: Optional[Dict[str, Any]] = Field(default=None, description="筛选条件（province/industry/direction/stage）")
    service_preferences: Optional[Dict[str, Any]] = Field(default=None, description="服务偏好")
    # ---------------------- N03 上下文决议 --------------------
    scode: Optional[str] = Field(default=None, description="已确认的 6 位企业代码")
    need_clarify: Optional[bool] = Field(default=False, description="是否需要反问用户")
    clarify_message: Optional[str] = Field(default=None, description="反问话术")
    # ---------------------- N05 / N06 检索 --------------------
    tool_used: Optional[str] = Field(default=None, description="N05 实际使用的工具名")
    facts: Optional[Dict[str, Any]] = Field(default=None, description="事实检索结果")
    products: Optional[Dict[str, Any]] = Field(default=None, description="资料检索结果")
    seen_refs: Optional[List[str]] = Field(default=None, description="本轮工具响应中真实出现过的引用白名单（N05/N06 累积）")
    # ---------------------- N07 分析 / N08 自检 --------------------
    draft: Optional[str] = Field(default=None, description="N07 输出的 JSON 字符串")
    valid: Optional[bool] = Field(default=False, description="N08 格式是否合规")
    issues: Optional[str] = Field(default="", description="N08 问题摘要")
    clean_draft: Optional[str] = Field(default=None, description="N08 整理后的 JSON 字符串")
    # ---------------------- N09 结束输出 --------------------
    result: Optional[str] = Field(default=None, description="最终输出内容（分析 JSON 或澄清消息）")


class GraphInput(BaseModel):
    """工作流输入（N01 开始节点变量）"""
    message: str = Field(..., description="用户这一句话")
    context_token: str = Field(..., description="通行证，由后端每轮自动签发")
    page_context: Optional[Dict[str, Any]] = Field(default=None, description="页面上下文：scode/year/view")
    history_summary: Optional[str] = Field(default=None, description="前几轮对话摘要")
    preferences: Optional[Dict[str, Any]] = Field(default=None, description="经理偏好：service_focus/exclude_financing")
    data_snapshot: Optional[str] = Field(default=None, description="数据快照 ID")
    product_version: Optional[str] = Field(default=None, description="产品资料版本")
    tools_base_url: Optional[str] = Field(default=None, description="工具服务地址")
    allowed_tools: Optional[List[str]] = Field(default=None, description="允许调用的工具清单")
    max_tool_calls: Optional[int] = Field(default=None, description="工具调用上限（默认 6）")
    max_compare_companies: Optional[int] = Field(default=None, description="对比企业数上限（默认 3）")


class GraphOutput(BaseModel):
    """工作流输出（N09 结束输出）"""
    result: str = Field(default="", description="最终输出内容（分析 JSON 或澄清消息）")


# ======================== N02 意图与参数 ========================
class IntentInput(BaseModel):
    """N02 意图与参数节点输入"""
    message: str = Field(..., description="用户问题")
    page_context: Optional[Dict[str, Any]] = Field(default=None, description="页面上下文")
    history_summary: Optional[str] = Field(default=None, description="前几轮对话摘要")


class IntentOutput(BaseModel):
    """N02 意图与参数节点输出"""
    intent: str = Field(..., description="意图：search/explain/compare/plan/clarify/general")
    companies: Optional[List[Dict[str, Any]]] = Field(default=None, description="企业代码列表")
    year: Optional[int] = Field(default=None, description="用户提到的年份")
    filters: Optional[Dict[str, Any]] = Field(default=None, description="筛选条件")
    service_preferences: Optional[Dict[str, Any]] = Field(default=None, description="服务偏好")


# ======================== N03 上下文决议 ========================
class ClarifyInput(BaseModel):
    """N03 上下文决议节点输入"""
    intent: str = Field(..., description="N02 输出的意图")
    companies: Optional[List[Dict[str, Any]]] = Field(default=None, description="N02 输出的企业代码列表")
    year: Optional[int] = Field(default=None, description="N02 输出的年份")
    page_context: Optional[Dict[str, Any]] = Field(default=None, description="页面默认上下文（用户本轮明确要求优先）")


class ClarifyOutput(BaseModel):
    """N03 上下文决议节点输出"""
    scode: Optional[str] = Field(default=None, description="已确认的 6 位企业代码")
    year: Optional[int] = Field(default=None, description="已确认的年度")
    need_clarify: bool = Field(..., description="是否需要反问用户")
    clarify_message: Optional[str] = Field(default=None, description="反问的话")


# ======================== N05 事实检索 ========================
class FactRetrievalInput(BaseModel):
    """N05 事实检索节点输入"""
    intent: str = Field(..., description="意图，决定调用哪个工具")
    scode: Optional[str] = Field(default=None, description="企业代码")
    year: Optional[int] = Field(default=None, description="年度")
    companies: Optional[List[Dict[str, Any]]] = Field(default=None, description="企业代码列表（对比用）")
    filters: Optional[Dict[str, Any]] = Field(default=None, description="筛选条件")
    context_token: str = Field(..., description="短期上下文令牌")
    tools_base_url: Optional[str] = Field(default=None, description="工具服务地址")
    data_snapshot: Optional[str] = Field(default=None, description="数据快照 ID")


class FactRetrievalOutput(BaseModel):
    """N05 事实检索节点输出"""
    tool_used: Optional[str] = Field(default=None, description="实际使用的工具名")
    facts: Dict[str, Any] = Field(..., description="事实检索结果对象")
    seen_refs: Optional[List[str]] = Field(default=None, description="本轮事实响应中真实出现过的引用白名单")


# ======================== N06 资料检索 ========================
class ProductRetrievalInput(BaseModel):
    """N06 资料检索节点输入"""
    context_token: str = Field(..., description="短期上下文令牌")
    tools_base_url: Optional[str] = Field(default=None, description="工具服务地址")
    service_preferences: Optional[Dict[str, Any]] = Field(default=None, description="服务偏好")
    filters: Optional[Dict[str, Any]] = Field(default=None, description="筛选条件（direction）")
    message: Optional[str] = Field(default=None, description="用户问题")
    data_snapshot: Optional[str] = Field(default=None, description="数据快照 ID")
    seen_refs: Optional[List[str]] = Field(default=None, description="N05 累积的引用白名单（继续向其中追加）")


class ProductRetrievalOutput(BaseModel):
    """N06 资料检索节点输出"""
    products: Dict[str, Any] = Field(..., description="资料检索结果对象")
    seen_refs: Optional[List[str]] = Field(default=None, description="N05+N06 累积后的引用白名单")


# ======================== N07 AI 分析 ========================
class AnalysisInput(BaseModel):
    """N07 AI 分析节点输入"""
    facts: Dict[str, Any] = Field(..., description="N05 事实检索输出")
    products: Dict[str, Any] = Field(..., description="N06 资料检索输出")
    message: str = Field(..., description="用户问题")
    preferences: Optional[Dict[str, Any]] = Field(default=None, description="经理偏好")
    intent: str = Field(..., description="意图")


class AnalysisOutput(BaseModel):
    """N07 AI 分析节点输出"""
    draft: str = Field(..., description="分析结果的 JSON 字符串")


# ======================== N08 自检整理 ========================
class CheckInput(BaseModel):
    """N08 自检整理节点输入"""
    draft: str = Field(..., description="N07 的整个输出（JSON 字符串）")
    facts: Optional[Dict[str, Any]] = Field(default=None, description="N05 事实检索结果，用于 evidence 引用存在性白名单")
    products: Optional[Dict[str, Any]] = Field(default=None, description="N06 资料检索结果，用于 product 引用存在性白名单")
    seen_refs: Optional[List[str]] = Field(default=None, description="N05/N06 累积的本轮工具引用白名单")


class CheckOutput(BaseModel):
    """N08 自检整理节点输出"""
    valid: bool = Field(..., description="格式是否合规")
    issues: str = Field(default="", description="问题摘要，无问题为空字符串")
    clean_draft: str = Field(..., description="整理后的 JSON 字符串")


# ======================== N09 结束输出 ========================
class OutputInput(BaseModel):
    """N09 结束输出节点输入"""
    clean_draft: Optional[str] = Field(default=None, description="N08 整理后的 JSON 字符串")
    need_clarify: bool = Field(default=False, description="是否需要反问用户")
    clarify_message: Optional[str] = Field(default=None, description="反问的话")


class OutputOutput(BaseModel):
    """N09 结束输出节点输出"""
    result: str = Field(..., description="最终输出内容")


# ======================== N04 路由入参 ========================
class RouteInput(BaseModel):
    """N04 工具路由条件分支输入"""
    intent: Optional[str] = Field(default=None, description="N02 意图")
    need_clarify: Optional[bool] = Field(default=False, description="N03 是否需要澄清")