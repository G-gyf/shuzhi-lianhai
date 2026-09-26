"""N02 意图与参数节点"""
import os
import json
from jinja2 import Template
from typing import Optional
from langchain_core.runnables import RunnableConfig
from langchain_core.messages import SystemMessage, HumanMessage
from langgraph.runtime import Runtime
from coze_coding_utils.runtime_ctx.context import Context
from coze_coding_dev_sdk import LLMClient
from graphs.state import IntentInput, IntentOutput
from utils.llm_utils import get_text_content, extract_json_object


def intent_node(state: IntentInput, config: RunnableConfig, runtime: Runtime[Context]) -> IntentOutput:
    """
    title: N02 意图与参数
    desc: 大模型判断用户想做什么，并抽取企业与年份等参数（意图只能为 search/explain/compare/plan/clarify/general）
    integrations: 大语言模型
    """
    ctx = runtime.context
    cfg_file = os.path.join(os.getenv("COZE_WORKSPACE_PATH", ""), config["metadata"]["llm_cfg"])
    with open(cfg_file, "r", encoding="utf-8") as fd:
        _cfg = json.load(fd)
    llm_config = _cfg.get("config", {})
    sp = _cfg.get("sp", "")
    up = _cfg.get("up", "")

    up_tpl = Template(up)
    user_prompt = up_tpl.render({
        "message": state.message,
        "page_context": json.dumps(state.page_context, ensure_ascii=False) if state.page_context else "无",
        "history_summary": state.history_summary or "无",
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

    companies = data.get("companies")
    if not isinstance(companies, list):
        companies = None

    filters = data.get("filters")
    if not isinstance(filters, dict):
        filters = None

    service_prefs = data.get("service_preferences")
    if not isinstance(service_prefs, dict):
        service_prefs = None

    year_raw = data.get("year")
    year: Optional[int] = int(year_raw) if isinstance(year_raw, (int, float)) else None

    import re
    explicit_year = re.search(r"(?<!\d)20\d{2}(?!\d)", state.message)
    if explicit_year:
        year = int(explicit_year.group())
    filters = filters or {}
    for word, stage in [("筹备", "T0"), ("落地", "T1"), ("存量", "T2")]:
        if word in state.message:
            filters["stage"] = stage
            break

    return IntentOutput(
        intent=data.get("intent", "general"),
        companies=companies,
        year=year,
        filters=filters,
        service_preferences=service_prefs,
    )