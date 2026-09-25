# -*- coding: utf-8 -*-
"""受控工具 HTTP 接口（方案 5.2 节：供 Coze 工作流调用）。

- Coze 云端无法访问本机 127.0.0.1；线上部署时 TOOLS_BASE_URL 指向本项目 HTTPS 地址。
- 每轮由对话网关签发短期 context_token（绑定用户、地区、数据版本、允许工具），
  工作流通过变量直接传给本接口；不拼入模型提示词。
- 工具接口验证 token；不信任模型传来的地区ID作为权限依据。
- 本地降级模式下不依赖本接口（网关进程内直调 tools.call_tool）。
"""
from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException, Request

from . import context_token, runtime, tools

router = APIRouter(prefix="/api/v1")


def _secret() -> str:
    return os.environ.get("TOOL_CONTEXT_SECRET", "")


def _verify(request: Request) -> dict:
    secret = _secret()
    if not secret:
        raise HTTPException(503, "未配置 TOOL_CONTEXT_SECRET，工具 HTTP 接口不可用。")
    payload = context_token.verify_context_token(
        request.headers.get("x-context-token"), secret)
    if not payload:
        raise HTTPException(403, "context_token 无效或已过期。")
    return payload


@router.post("/tools/{tool_name}")
async def call_http_tool(tool_name: str, request: Request):
    payload = _verify(request)
    body = await request.json()
    params = body.get("parameters") if isinstance(body, dict) else {}
    if not isinstance(params, dict):
        raise HTTPException(400, "parameters 必须是对象。")
    ctx = tools.build_context({
        "user_id": payload.get("user_id", "coze-worker"),
        "display_name": payload.get("display_name", "Coze 工作流"),
        "regions": payload.get("regions") or [],
        "identity_mode": "workflow",
    }, allowed_tools=payload.get("allowed_tools"))
    # 快照绑定：token 中的数据版本与当前运行快照不一致时拒绝（数据版本漂移保护）
    if payload.get("snapshot_id") and payload["snapshot_id"] != runtime.get_snapshot():
        raise HTTPException(409, "数据快照版本已变化，请重新发起对话获取新 token。")
    result = tools.call_tool(tool_name, ctx, params)
    if not result.get("ok"):
        status = 400 if result.get("code") in ("bad_input", "bad_ref") else 403
        raise HTTPException(status, result.get("error", "工具执行失败"))
    return result
