"""N05 事实检索节点 - 调用公网受控工具服务"""
import requests
from langchain_core.runnables import RunnableConfig
from langgraph.runtime import Runtime
from coze_coding_utils.runtime_ctx.context import Context
from graphs.state import FactRetrievalInput, FactRetrievalOutput
from graphs.nodes.n08_ref_filter import collect_refs

_DEFAULT_TOOLS_BASE = "https://shuzhi-lianhai-production.up.railway.app"
# 名单/对比类问题最多补取几家的上下文包（控制工具调用次数，建议 2—3）
_DISCUSS_LIMIT = 3


def _dedup_params(params: dict) -> dict:
    """剔除值为 None 的参数"""
    return {k: v for k, v in params.items() if v is not None}


def _call_tool(base_url: str, tool: str, params: dict, token: str):
    """调用受控工具，返回 (data, error)。error 非空表示失败，绝不伪造数据。"""
    url = f"{base_url}/api/v1/tools/{tool}"
    headers = {"X-Context-Token": token, "Content-Type": "application/json"}
    try:
        resp = requests.post(url, json=params, headers=headers, timeout=(5, 60))
        if resp.status_code != 200:
            text = resp.text if resp.text else f"HTTP {resp.status_code}"
            return None, {"error": f"工具调用失败：{text}",
                          "http_status": resp.status_code, "tool": tool}
        try:
            return resp.json(), None
        except Exception:  # noqa: BLE001
            return {"raw": resp.text}, None
    except Exception as e:  # noqa: BLE001
        return None, {"error": f"工具调用异常：{e}", "tool": tool}


def _scodes_from(data, limit: int) -> list:
    """从 search_companies / compare_companies 的响应里取出要讨论的企业代码。"""
    out, seen = [], set()
    if not isinstance(data, dict):
        return out
    for key in ("items", "companies"):
        for it in (data.get(key) or []):
            if not isinstance(it, dict):
                continue
            code = it.get("scode") or it.get("code")
            if not code:
                continue
            code = str(code).zfill(6)
            if code not in seen:
                seen.add(code)
                out.append(code)
    return out[:limit]


def fact_retrieval_node(state: FactRetrievalInput, config: RunnableConfig, runtime: Runtime[Context]) -> FactRetrievalOutput:
    """
    title: N05 事实检索
    desc: 按意图调用受控工具（search_companies / get_company_context / compare_companies）检索企业事实；名单与对比场景额外补取被讨论企业的可引用证据
    """
    ctx = runtime.context
    base_url = (state.tools_base_url or _DEFAULT_TOOLS_BASE).rstrip("/")
    token = state.context_token
    intent = state.intent or "explain"

    tool: str = ""
    params: dict = {}
    if intent == "search":
        tool = "search_companies"
        filters = state.filters if isinstance(state.filters, dict) else {}
        params = _dedup_params({
            "province": filters.get("province"),
            "industry": filters.get("industry"),
            "direction": filters.get("direction"),
            "stage": filters.get("stage"),
            "year": state.year,
            "page_size": 5,
        })
    elif intent == "compare":
        tool = "compare_companies"
        scodes = [c.get("scode") for c in (state.companies or [])
                  if isinstance(c, dict) and c.get("scode")]
        params = _dedup_params({"scodes": scodes, "year": state.year})
    else:  # explain / plan / general（走具体企业）
        tool = "get_company_context"
        params = _dedup_params({
            "scode": state.scode,
            "year": state.year,
            "snapshot_id": state.data_snapshot if state.data_snapshot else None,
        })

    data, error = _call_tool(base_url, tool, params, token)
    if error:
        # 真实失败：记录真实错误状态，不伪造数据（由下游处理降级）
        return FactRetrievalOutput(tool_used=tool, facts=error)

    seen = collect_refs(data)

    # ---- 补取「被讨论企业」的可引用证据（search / compare 场景必需）----
    # 原因：search_companies 响应里没有任何引用字段、compare_companies 只有 compare_ref，
    # 若不再补取，N07 手里根本没有 ev: 可引用 → 正文没有依据按钮、页面没有原文球。
    if intent in ("search", "compare"):
        discussed = []
        for code in _scodes_from(data, _DISCUSS_LIMIT):
            one, err = _call_tool(
                base_url, "get_company_context",
                _dedup_params({"scode": code, "year": state.year}), token)
            if err or not isinstance(one, dict):
                continue
            discussed.append(one)
            seen |= collect_refs(one)
        if discussed:
            data = dict(data)
            # 塞进 facts 即可：N07 的 up 模板是 {{facts}}，整个 JSON 会原样给到模型
            data["discussed_companies"] = discussed
            data["discussed_note"] = (
                "discussed_companies 为名单/对比中被讨论企业的上下文包，"
                "其中 signal_refs[].evidence_ref 是可引用的原文证据，请优先引用。")

    return FactRetrievalOutput(tool_used=tool, facts=data, seen_refs=sorted(seen))
