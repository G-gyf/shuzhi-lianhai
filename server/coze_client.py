# -*- coding: utf-8 -*-
"""Coze 平台调用客户端（方案 5.1/5.3 节）。

- 主调用：POST {COZE_API_BASE}/v1/workflow/stream_run（工作流需已发布）。
- 仅做平台调用与事件解析；业务事件转换由 chat.py 网关完成，
  不假设平台原生输出项目自定义光球事件。
- 未配置凭证（AI_ENABLED!=1）时，chat 网关走本地规则分析引擎（降级路径，方案 12.3）。
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request


def env(name, default=None):
    return os.environ.get(name, default)


def config() -> dict:
    return {
        "ai_enabled": env("AI_ENABLED", "") == "1",
        "api_base": env("COZE_API_BASE", "https://api.coze.cn").rstrip("/"),
        "workflow_id": env("COZE_WORKFLOW_ID", ""),
        "bot_id": env("COZE_BOT_ID", ""),
        "app_id": env("COZE_APP_ID", ""),
        "access_token": env("COZE_ACCESS_TOKEN", ""),
        "timeout_seconds": int(env("AI_TIMEOUT_SECONDS", "60")),
        "max_tool_calls": int(env("AI_MAX_TOOL_CALLS", "6")),
        "max_compare_companies": int(env("AI_MAX_COMPARE_COMPANIES", "3")),
        "tools_base_url": env("TOOLS_BASE_URL", ""),
        "tool_context_secret": env("TOOL_CONTEXT_SECRET", ""),
    }


class CozeError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _check_enabled(cfg: dict):
    if not cfg["ai_enabled"]:
        raise CozeError("ai_disabled", "AI 未启用（AI_ENABLED!=1），使用本地规则引擎降级路径。")
    if not cfg["access_token"]:
        raise CozeError("no_token", "未配置 COZE_ACCESS_TOKEN。")
    if not cfg["workflow_id"]:
        raise CozeError("no_workflow", "未配置 COZE_WORKFLOW_ID。")


def stream_run(parameters: dict, request_id: str = "") -> "list[tuple[str, dict]]":
    """调用工作流流式接口，返回原始 SSE 事件列表 [(event_name, data_dict)]。

    按已发布方式选用 bot 或 app（方案 5.3：不混用工作流ID/智能体ID/应用ID）。
    超时抛 CozeError("timeout")。
    """
    cfg = config()
    _check_enabled(cfg)
    url = f"{cfg['api_base']}/v1/workflow/stream_run"
    body = {
        "workflow_id": cfg["workflow_id"],
        "parameters": parameters,
    }
    headers = {
        "Authorization": f"Bearer {cfg['access_token']}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
    }
    if cfg["app_id"]:
        body["app_id"] = cfg["app_id"]
    req = urllib.request.Request(url, data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
                                 headers=headers, method="POST")
    deadline = time.time() + cfg["timeout_seconds"]
    try:
        resp = urllib.request.urlopen(req, timeout=cfg["timeout_seconds"])
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", "replace")[:500]
        except Exception:
            pass
        raise CozeError(f"http_{e.code}", f"Coze 接口返回 {e.code}：{detail}")
    except urllib.error.URLError as e:
        raise CozeError("network_error", f"无法连接 Coze：{e.reason}")

    events: list[tuple[str, dict]] = []
    event_name, data_lines = "", []
    try:
        for raw in resp:
            if time.time() > deadline:
                raise CozeError("timeout", "Coze 工作流响应超时。")
            line = raw.decode("utf-8", "replace").rstrip("\r\n")
            if line == "":
                if data_lines:
                    data_text = "\n".join(data_lines)
                    data = {}
                    try:
                        data = json.loads(data_text)
                    except ValueError:
                        data = {"raw": data_text}
                    events.append((event_name or "message", data))
                event_name, data_lines = "", []
                continue
            if line.startswith("event:"):
                event_name = line[6:].strip()
            elif line.startswith("data:"):
                data_lines.append(line[5:].strip())
            elif line.startswith(":"):  # 注释行（心跳）
                continue
    finally:
        try:
            resp.close()
        except Exception:
            pass
    if not events:
        raise CozeError("empty_stream", "Coze 工作流未返回任何事件。")
    return events


def extract_workflow_output(events: "list[tuple[str, dict]]") -> dict | None:
    """从 Coze 原始事件中提取工作流结束输出（result JSON 字符串）。"""
    for name, data in events:
        if name in ("WorkflowFinish", "finish", "message") and isinstance(data, dict):
            if data.get("result") is not None:
                result = data["result"]
                if isinstance(result, str):
                    try:
                        return json.loads(result)
                    except ValueError:
                        return {"raw_result": result}
                if isinstance(result, dict):
                    return result
    # 兼容：事件流末尾的 data 直接是协议对象
    for name, data in events:
        if isinstance(data, dict) and ("answer_blocks" in data or "recommendations" in data):
            return data
    return None


def extract_error(events: "list[tuple[str, dict]]") -> dict | None:
    for name, data in events:
        if name in ("Error", "error") and isinstance(data, dict):
            return {"code": str(data.get("code", "workflow_error")),
                    "message": str(data.get("msg", data.get("message", "Coze 工作流执行失败")))}
        if isinstance(data, dict) and data.get("error"):
            return {"code": "workflow_error", "message": str(data["error"])}
    return None
