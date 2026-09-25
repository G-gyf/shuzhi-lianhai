# -*- coding: utf-8 -*-
"""受控工具 HTTP 接口（方案 5.2 节：供 Coze 工作流调用）。

- Coze 云端无法访问本机 127.0.0.1；线上部署时 TOOLS_BASE_URL 指向本项目 HTTPS 地址。
- 每轮由对话网关签发短期 context_token（绑定用户、地区、数据版本、允许工具），
  工作流通过变量直接传给本接口；不拼入模型提示词。
- 工具接口验证 token；不信任模型传来的地区ID作为权限依据。
- 本地降级模式下不依赖本接口（网关进程内直调 tools.call_tool）。

参数形态兼容（便于 Coze 插件工作流传参）：
  1. 扁平：        {"scode": "002860", "year": 2023}
  2. 嵌套：        {"parameters": {...}}
  3. 字符串（dispatch）：{"tool": "...", "parameters_json": "{\"scode\":\"002860\"}"}
"""
from __future__ import annotations

import hmac
import json
import os

from fastapi import APIRouter, HTTPException, Request

from . import context_token, runtime, tools

router = APIRouter(prefix="/api/v1")

# 非参数键：出现在扁平请求体中时不应作为工具参数传递
NON_PARAM_KEYS = {"parameters", "parameters_json", "tool"}

# 静态调试密钥模式（仅调试用；默认关闭）
# 打开后，X-Context-Token 可以直接填 TOOL_CONTEXT_SECRET 的值本身，
# 便于 Coze 插件页「试运行」时手工粘贴；生产环境必须保持关闭并使用每轮签发的 context_token。
DEBUG_FLAG = "ALLOW_STATIC_DEBUG_TOKEN"


def _secret() -> str:
    return os.environ.get("TOOL_CONTEXT_SECRET", "")


def _debug_regions() -> list[str]:
    raw = os.environ.get("DEBUG_TOKEN_REGIONS", "region_a")
    return [r.strip() for r in raw.split(",") if r.strip()]


def _verify(request: Request) -> dict:
    secret = _secret()
    if not secret:
        raise HTTPException(503, "未配置 TOOL_CONTEXT_SECRET，工具 HTTP 接口不可用。")
    token = request.headers.get("x-context-token")
    if (token and os.environ.get(DEBUG_FLAG) == "1"
            and hmac.compare_digest(token, secret)):
        # 静态调试密钥：全工具放行、身份固定为演示经理；响应头标注，便于排查
        return {"user_id": "u_demo_a", "display_name": "静态调试密钥（试运行）",
                "regions": _debug_regions(), "snapshot_id": runtime.get_snapshot(),
                "allowed_tools": None, "debug_static": True}
    payload = context_token.verify_context_token(token, secret)
    if not payload:
        raise HTTPException(403, "context_token 无效或已过期。")
    return payload


def _ctx(payload: dict) -> dict:
    return tools.build_context({
        "user_id": payload.get("user_id", "coze-worker"),
        "display_name": payload.get("display_name", "Coze 工作流"),
        "regions": payload.get("regions") or [],
        "identity_mode": "workflow",
    }, allowed_tools=payload.get("allowed_tools"))


def _check_snapshot(payload: dict):
    """快照绑定：token 中的数据版本与当前运行快照不一致时拒绝（数据版本漂移保护）。"""
    if payload.get("snapshot_id") and payload["snapshot_id"] != runtime.get_snapshot():
        raise HTTPException(409, "数据快照版本已变化，请重新发起对话获取新 token。")


def _extract_params(body: dict) -> dict:
    """支持扁平 / 嵌套 / JSON 字符串三种传参形态。"""
    if not isinstance(body, dict):
        raise HTTPException(400, "请求体必须是 JSON 对象。")
    raw_json = body.get("parameters_json")
    if isinstance(raw_json, str) and raw_json.strip():
        try:
            parsed = json.loads(raw_json)
        except ValueError:
            raise HTTPException(400, "parameters_json 不是合法 JSON 字符串。")
        if not isinstance(parsed, dict):
            raise HTTPException(400, "parameters_json 解析后必须是对象。")
        return parsed
    nested = body.get("parameters")
    if isinstance(nested, dict):
        return nested
    return {k: v for k, v in body.items() if k not in NON_PARAM_KEYS}


def _run(tool_name: str, payload: dict, params: dict) -> dict:
    result = tools.call_tool(tool_name, _ctx(payload), params)
    if not result.get("ok"):
        code = result.get("code")
        status = 400 if code in ("bad_input", "bad_ref") else 403
        raise HTTPException(status, result.get("error", "工具执行失败"))
    return result


@router.post("/tools/dispatch")
async def dispatch_tool(request: Request):
    """统一工具分发（备选插件形态：单个 operation，响应顶层恒为 object）。

    请求：{"tool": "get_company_context", "parameters_json": "{\"scode\":\"002860\"}"}
    响应：{"ok": true, "tool": "...", "result": {目标工具返回体}}
    """
    payload = _verify(request)
    body = await request.json()
    tool_name = (body.get("tool") or "").strip() if isinstance(body, dict) else ""
    if not tool_name:
        raise HTTPException(400, "缺少 tool 参数（目标工具名）。")
    if tool_name not in tools.TOOL_REGISTRY:
        raise HTTPException(400, f"未知工具：{tool_name}")
    params = _extract_params(body)
    _check_snapshot(payload)
    result = _run(tool_name, payload, params)
    return {"ok": True, "tool": tool_name, "result": result}


@router.post("/tools/{tool_name}")
async def call_http_tool(tool_name: str, request: Request):
    if tool_name == "dispatch":
        raise HTTPException(400, "请直接调用 /api/v1/tools/dispatch。")
    payload = _verify(request)
    body = await request.json()
    params = _extract_params(body)
    _check_snapshot(payload)
    return _run(tool_name, payload, params)
