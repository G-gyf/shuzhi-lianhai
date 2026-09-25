# -*- coding: utf-8 -*-
"""短期上下文令牌（方案 5.2 节）。

- 每轮生成短期 context_token：绑定用户、地区、数据版本和允许工具；
  由工作流变量直接传给工具请求，不拼入模型提示词。
- 工具接口验证 token；不信任模型传来的地区ID作为权限依据。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time


def sign_context_token(payload: dict, secret: str, ttl_seconds: int = 600) -> str:
    """payload + exp + HMAC(secret)。secret 仅存服务端，不进提示词、不入日志。"""
    body = dict(payload)
    body["exp"] = int(time.time()) + ttl_seconds
    raw = base64.urlsafe_b64encode(
        json.dumps(body, ensure_ascii=False, sort_keys=True).encode("utf-8")).decode("ascii")
    sig = hmac.new(secret.encode("utf-8"), raw.encode("ascii"),
                   hashlib.sha256).hexdigest()[:32]
    return f"{raw}.{sig}"


def verify_context_token(token: str | None, secret: str) -> dict | None:
    """校验签名与有效期；失败返回 None。"""
    if not token or not secret or "." not in token:
        return None
    raw, _, sig = token.rpartition(".")
    expect = hmac.new(secret.encode("utf-8"), raw.encode("ascii"),
                      hashlib.sha256).hexdigest()[:32]
    if not hmac.compare_digest(expect, sig):
        return None
    try:
        pad = "=" * (-len(raw) % 4)
        body = json.loads(base64.urlsafe_b64decode(raw + pad).decode("utf-8"))
    except Exception:
        return None
    if int(body.get("exp", 0)) < time.time():
        return None
    return body
