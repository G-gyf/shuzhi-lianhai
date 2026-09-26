"""N03 上下文决议节点"""
import os
import json
from typing import Optional
from jinja2 import Template
from langchain_core.runnables import RunnableConfig
from langchain_core.messages import SystemMessage, HumanMessage
from langgraph.runtime import Runtime
from coze_coding_utils.runtime_ctx.context import Context
from coze_coding_dev_sdk import LLMClient
from graphs.state import ClarifyInput, ClarifyOutput
from utils.llm_utils import get_text_content, extract_json_object


def clarify_node(state: ClarifyInput, config: RunnableConfig, runtime: Runtime[Context]) -> ClarifyOutput:
    """
    title: N03 上下文决议
    desc: 确定\"是哪家企业、哪一年\"，无法确认时设置 need_clarify 并给出反问话术
    integrations: 大语言模型
    """
    if state.intent == "search":
        page = state.page_context or {}
        return ClarifyOutput(scode=None, year=state.year if state.year is not None else page.get("year"),
                             need_clarify=False, clarify_message=None)
    ctx = runtime.context
    cfg_file = os.path.join(os.getenv("COZE_WORKSPACE_PATH", ""), config["metadata"]["llm_cfg"])
    with open(cfg_file, "r", encoding="utf-8") as fd:
        _cfg = json.load(fd)
    llm_config = _cfg.get("config", {})
    sp = _cfg.get("sp", "")
    up = _cfg.get("up", "")

    intent_result = {"intent": state.intent, "companies": state.companies, "year": state.year}
    up_tpl = Template(up)
    user_prompt = up_tpl.render({
        "intent_result": json.dumps(intent_result, ensure_ascii=False),
        "page_context": json.dumps(state.page_context, ensure_ascii=False) if state.page_context else "无",
    })

    client = LLMClient(ctx=ctx)
    resp = client.invoke(
        messages=[
            SystemMessage(content=sp),
            HumanMessage(content=user_prompt),
        ],
        model=llm_config.get("model", "doubao-seed-2-0-pro-260215"),
        temperature=llm_config.get("temperature", 0.1),
        top_p=llm_config.get("top_p", 0.3),
        max_completion_tokens=llm_config.get("max_completion_tokens", 2000),
        thinking=llm_config.get("thinking", "disabled"),
    )

    text = get_text_content(resp.content)
    data = extract_json_object(text)

    need_clarify = bool(data.get("need_clarify", False))
    scode_raw = data.get("scode")
    scode: Optional[str] = str(scode_raw) if scode_raw else None
    year_raw = data.get("year")
    year: Optional[int] = int(year_raw) if isinstance(year_raw, (int, float)) else None
    if state.year is not None:
        year = state.year
    explicit = [c.get("scode") for c in (state.companies or []) if isinstance(c, dict) and c.get("scode")]
    if state.intent in ("explain", "plan") and len(explicit) == 1:
        scode = str(explicit[0]).zfill(6)
        need_clarify = False
    clarify_message = data.get("clarify_message")

    return ClarifyOutput(
        scode=scode,
        year=year,
        need_clarify=need_clarify,
        clarify_message=clarify_message,
    )