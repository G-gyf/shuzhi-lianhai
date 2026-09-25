# -*- coding: utf-8 -*-
"""LangGraph 引擎客户端（对接扣子编程项目「数智链海出海助手」）。

背景：团队另有一个扣子编程（code.coze.cn）项目，用 LangGraph 实现了 N01—N09 的
等价流程（意图 → 上下文决议 → 工具路由 → 事实/资料检索 → AI 分析 → 自检 → 输出），
节点直接调用本项目的受控工具接口。本模块把这套引擎接进数智链海的对话网关，
作为「AI 引擎」之一（与 Coze 低代码工作流并列，失败自动降级到本地规则引擎）。

契约（与 coze/workflow_design.md、HTML 方案 STEP 13 完全一致）：
    入参 11 个变量同名：
      message / context_token / page_context / history_summary / preferences /
      data_snapshot / product_version / tools_base_url / allowed_tools /
      max_tool_calls / max_compare_companies
    出参：{"result": "<analysis_draft JSON 字符串>"}（也兼容直接返回草稿对象）

环境变量：
    AI_ENGINE=langgraph      显式指定优先使用本引擎
    LANGGRAPH_BASE_URL       引擎地址，例如 https://<扣子编程部署地址> 或 http://127.0.0.1:5000
    LANGGRAPH_RUN_PATH       调用路径，默认 /run
    LANGGRAPH_TOKEN          可选；存在时以 Authorization: Bearer 发送
    AI_TIMEOUT_SECONDS       超时秒数（与 Coze 共用，默认 60）
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

from .schemas import SCHEMA_VERSION


class LangGraphError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def config() -> dict:
    return {
        "base_url": (os.environ.get("LANGGRAPH_BASE_URL", "") or "").rstrip("/"),
        "run_path": os.environ.get("LANGGRAPH_RUN_PATH", "/run") or "/run",
        "token": os.environ.get("LANGGRAPH_TOKEN", ""),
        "timeout_seconds": int(os.environ.get("AI_TIMEOUT_SECONDS", "60")),
        "health_path": os.environ.get("LANGGRAPH_HEALTH_PATH", "/health") or "/health",
    }


def enabled() -> bool:
    return bool(config()["base_url"])


def run(params: dict, base_url: str | None = None, token: str | None = None,
        timeout: int | None = None) -> dict:
    """调用引擎的 /run，返回其响应字典。失败抛 LangGraphError。"""
    cfg = config()
    base = (base_url or cfg["base_url"]).rstrip("/")
    if not base:
        raise LangGraphError("no_base_url", "未配置 LANGGRAPH_BASE_URL。")
    url = base + cfg["run_path"]
    headers = {"Content-Type": "application/json"}
    tok = token if token is not None else cfg["token"]
    if tok:
        headers["Authorization"] = f"Bearer {tok}"
    req = urllib.request.Request(
        url, data=json.dumps(params, ensure_ascii=False).encode("utf-8"),
        headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout or cfg["timeout_seconds"]) as resp:
            body = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", "replace")[:400]
        except Exception:
            pass
        raise LangGraphError(f"http_{e.code}", f"引擎返回 {e.code}：{detail}")
    except urllib.error.URLError as e:
        raise LangGraphError("network_error", f"无法连接引擎：{e.reason}")
    except TimeoutError:
        raise LangGraphError("timeout", "引擎响应超时。")
    try:
        data = json.loads(body)
    except ValueError:
        raise LangGraphError("bad_response", f"引擎返回的不是 JSON：{body[:200]}")
    if not isinstance(data, dict):
        raise LangGraphError("bad_response", "引擎返回的不是 JSON 对象。")
    return data


def health(base_url: str | None = None, timeout: int = 10) -> dict:
    cfg = config()
    base = (base_url or cfg["base_url"]).rstrip("/")
    try:
        with urllib.request.urlopen(base + cfg["health_path"], timeout=timeout) as resp:
            return {"ok": True, "status": resp.status,
                    "body": resp.read().decode("utf-8", "replace")[:200]}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def _try_json(text: str) -> dict | None:
    """从引擎输出里提取 JSON 对象（可能是纯 JSON，也可能夹在文字里）。"""
    if not isinstance(text, str) or not text.strip():
        return None
    s = text.strip()
    try:
        data = json.loads(s)
        if isinstance(data, dict):
            return data
    except ValueError:
        pass
    depth, start = 0, -1
    for i, ch in enumerate(s):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start != -1:
                data = _try_json(s[start:i + 1])
                if data is not None:
                    return data
    return None


def normalize_draft(payload: dict, page: dict | None, snapshot: str,
                    product_version: str) -> dict:
    """把引擎响应规整成后端可校验的 analysis_draft。

    - 引擎返回 {"result": "<json 字符串>"} → 解析后即草稿；
    - 返回澄清话术等纯文本 → 包成一个 note 块（前端照常显示）；
    - 补全 context / provenance / schema_version / 空数组字段。
    """
    warnings: list[str] = []
    raw = payload.get("result") if isinstance(payload, dict) else None
    if raw is None and isinstance(payload, dict):
        raw = payload          # 引擎直接返回整图状态：从里面找草稿字段
        if not any(k in payload for k in ("answer_blocks", "recommendations")):
            raw = None

    draft: dict | None = None
    if isinstance(raw, dict):
        draft = dict(raw)
    elif isinstance(raw, str):
        draft = _try_json(raw)
        if draft is None:
            draft = {"answer_blocks": [{"kind": "note", "text": raw.strip(), "refs": []}],
                     "recommendations": [], "questions": [], "orbs": []}
            warnings.append("引擎返回的是文本（可能是澄清话术），已作为说明块呈现。")

    if draft is None:
        # 兜底：从整图状态里挑出可用的草稿，或如实报错
        for key in ("clean_draft", "draft"):
            cand = payload.get(key) if isinstance(payload, dict) else None
            if isinstance(cand, dict):
                draft = dict(cand)
                break
            if isinstance(cand, str):
                draft = _try_json(cand)
                if draft is not None:
                    break
    if draft is None:
        raise LangGraphError("empty_draft",
                            "引擎输出里找不到可解析的分析草稿（result/clean_draft 均为空）。")

    for key in ("answer_blocks", "recommendations", "questions", "orbs"):
        if not isinstance(draft.get(key), list):
            draft[key] = []
    draft["schema_version"] = draft.get("schema_version") or SCHEMA_VERSION
    draft.setdefault("status", "draft")
    draft["warnings"] = list(draft.get("warnings") or []) + warnings

    ctx = dict(draft.get("context") or {})
    page = page or {}
    if ctx.get("scode") is None and page.get("scode"):
        ctx["scode"] = page["scode"]
    if ctx.get("year") is None and page.get("year"):
        ctx["year"] = page["year"]
    ctx["snapshot_id"] = ctx.get("snapshot_id") or snapshot
    ctx["product_version"] = ctx.get("product_version") or product_version
    draft["context"] = {k: v for k, v in ctx.items() if v is not None}

    prov = dict(draft.get("provenance") or {})
    prov.setdefault("engine", "langgraph")
    prov.setdefault("workflow_version", config()["base_url"])
    prov.setdefault("generated_at", time.strftime("%Y-%m-%dT%H:%M:%S%z"))
    draft["provenance"] = prov
    return draft
