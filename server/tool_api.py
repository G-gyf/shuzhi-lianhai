# -*- coding: utf-8 -*-
"""受控工具 HTTP 接口（方案 5.2 节：供 Coze 工作流调用）。

- Coze 云端无法访问本机 127.0.0.1；线上部署时 TOOLS_BASE_URL 指向本项目 HTTPS 地址。
- 每轮由对话网关签发短期 context_token（绑定用户、地区、数据版本、允许工具），
  工作流通过变量直接传给本接口；不拼入模型提示词。
- 工具接口验证 token；不信任模型传来的地区ID作为权限依据。
- 本地降级模式下不依赖本接口（网关进程内直调 tools.call_tool）。

为兼容 Coze 插件实际发出的各种请求形态，本模块刻意做了三处容错：
  1. token 既可从 Header `X-Context-Token` 读取，也可从请求体同名字段读取
     （Coze 试运行面板会把 Header 参数显示/放进 JSON 体）；
  2. 请求体为空或缺省时不报错（无必填参数的工具，Coze 可能不发 body）；
  3. 请求体里多出的非工具参数会被忽略并在响应里回报，不会让工具调用失败。
"""
from __future__ import annotations

import hmac
import inspect
import json
import os

from fastapi import APIRouter, HTTPException, Request

from . import context_token, runtime, tools

router = APIRouter(prefix="/api/v1")

# token 在请求体中的可接受键名（Coze 试运行面板的形态）
TOKEN_BODY_KEYS = ("X-Context-Token", "x-context-token", "context_token",
                   "X-Context-Token ".strip())

# 非参数键：出现在请求体中时不应作为工具参数传递
NON_PARAM_KEYS = {"parameters", "parameters_json", "tool"} | set(TOKEN_BODY_KEYS)

# 静态调试密钥模式（仅调试用；默认关闭）
# 打开后，X-Context-Token 可以直接填 TOOL_CONTEXT_SECRET 的值本身，
# 便于 Coze 插件页「试运行」时手工粘贴；生产环境必须保持关闭并使用每轮签发的 context_token。
DEBUG_FLAG = "ALLOW_STATIC_DEBUG_TOKEN"


def _secret() -> str:
    return os.environ.get("TOOL_CONTEXT_SECRET", "")


def _debug_regions() -> list[str]:
    raw = os.environ.get("DEBUG_TOKEN_REGIONS", "region_a")
    return [r.strip() for r in raw.split(",") if r.strip()]


async def read_body(request: Request) -> dict:
    """容错读取请求体：空体 / 非 JSON → 返回 {}（不因 Coze 不发 body 而失败）。"""
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001 — 空体或非法 JSON 一律按空参数处理
        return {}
    return body if isinstance(body, dict) else {}


def _header_token(request: Request, body: dict) -> str:
    token = request.headers.get("x-context-token") or ""
    if token:
        return token
    for key in TOKEN_BODY_KEYS:
        val = body.get(key)
        if isinstance(val, str) and val:
            return val
    return ""


def _verify(request: Request, body: dict) -> dict:
    secret = _secret()
    if not secret:
        raise HTTPException(503, "本服务未配置 TOOL_CONTEXT_SECRET，工具接口不可用。"
                                 "请在部署平台的环境变量中添加该密钥并重启。")
    token = _header_token(request, body)
    debug_on = os.environ.get(DEBUG_FLAG) == "1"
    if token and hmac.compare_digest(token, secret):
        if debug_on:
            # 静态调试密钥：全工具放行、身份固定为演示经理
            return {"user_id": "u_demo_a", "display_name": "静态调试密钥（试运行）",
                    "regions": _debug_regions(), "snapshot_id": runtime.get_snapshot(),
                    "allowed_tools": None, "debug_static": True}
        raise HTTPException(403, "该值与本服务的 TOOL_CONTEXT_SECRET 相同，但静态调试模式未开启。"
                                 "手工试跑请先设置环境变量 ALLOW_STATIC_DEBUG_TOKEN=1 并重新部署；"
                                 "或改用 scripts/make_token.py 生成的正式令牌"
                                 "（工作流运行时由后端每轮自动传入，不需要手工填写）。")
    payload = context_token.verify_context_token(token, secret)
    if not payload:
        raise HTTPException(403, "context_token 无效或已过期。请依次排查："
                                 "① X-Context-Token 是否与本服务 TOOL_CONTEXT_SECRET 完全一致"
                                 "（插件试跑需同时开启 ALLOW_STATIC_DEBUG_TOKEN=1 并填密钥原值）；"
                                 "② 正式令牌是否已过期（默认 10 分钟，可用 scripts/make_token.py 重签）；"
                                 "③ 令牌签名密钥是否与部署侧一致；"
                                 "④ 若提示的是 409，则是数据快照版本不一致（非本条错误）。")
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


def _accepted_params(tool_name: str) -> set[str]:
    handler = tools.TOOL_REGISTRY[tool_name]["handler"]
    return set(inspect.signature(handler).parameters) - {"ctx"}


def _run(tool_name: str, payload: dict, params: dict) -> dict:
    accepted = _accepted_params(tool_name)
    clean = {k: v for k, v in params.items() if k in accepted}
    ignored = sorted(k for k in params if k not in accepted)
    result = tools.call_tool(tool_name, _ctx(payload), clean)
    if not result.get("ok"):
        code = result.get("code")
        status = 400 if code in ("bad_input", "bad_ref") else 403
        raise HTTPException(status, result.get("error", "工具执行失败"))
    if ignored:
        # 多余参数不阻断调用，但在响应里回报，便于排查 Coze 传参形态
        result["ignored_params"] = ignored
    return result


@router.post("/tools/dispatch")
async def dispatch_tool(request: Request):
    """统一工具分发（备选插件形态：单个 operation，响应顶层恒为 object）。

    请求：{"tool": "get_company_context", "parameters_json": "{\"scode\":\"002860\"}"}
    响应：{"ok": true, "tool": "...", "result": {目标工具返回体}}
    """
    body = await read_body(request)
    payload = _verify(request, body)
    tool_name = str(body.get("tool") or "").strip()
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
    body = await read_body(request)
    payload = _verify(request, body)
    params = _extract_params(body)
    _check_snapshot(payload)
    return _run(tool_name, payload, params)
