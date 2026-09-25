# -*- coding: utf-8 -*-
"""经理偏好与能力（方案 7.2、11.1 节）。

- 个人偏好：保存、修改并在对话中生效；不允许个人配置覆盖基础事实或跨越数据权限。
- 能力清单：当前用户可使用的功能与资料源，带身份模式标注。
"""
from __future__ import annotations

from . import extensions, runtime


def get_preferences(user: dict) -> dict:
    return runtime.get_preferences(user["user_id"])


def patch_preferences(user: dict, patch: dict) -> dict:
    """允许字段白名单合并；未知字段忽略。"""
    allowed = {"service_focus", "exclude_financing", "default_region",
               "focus_industries", "plan_length", "watchlist"}
    clean = {k: v for k, v in (patch or {}).items() if k in allowed and v is not None}
    if "service_focus" in clean and not isinstance(clean["service_focus"], list):
        del clean["service_focus"]
    if "plan_length" in clean and clean["plan_length"] not in ("brief", "standard", "detailed"):
        del clean["plan_length"]
    return runtime.set_preferences(user["user_id"], clean)


def capabilities(user: dict) -> dict:
    """当前用户可使用的功能与资料源。"""
    sources = [s for s in extensions.list_sources()
               if s["status"] == "active" and
               (s["scope"] != "region" or s["region_id"] in user["regions"])]
    ext = extensions.extension_catalog(user["regions"])
    enabled_ext = [e["extension_id"] for e in ext["extensions"] if e["enabled_for_me"]]
    return {
        "identity": {
            "user_id": user["user_id"],
            "display_name": user["display_name"],
            "mode": user["identity_mode"],
            "regions": user["regions"],
            "note": ("本地演示身份：演示令牌仅用于验收；正式多人使用前必须以服务端身份完成隔离，"
                     "不能只在前端隐藏他区资料。"),
        },
        "capabilities": {
            "chat": True,
            "search_companies": True,
            "compare_companies": True,
            "product_knowledge": True,
            "regional_knowledge": bool(enabled_ext and any(
                s["kind"] == "document_collection" for s in sources)),
            "briefings": True,
            "data_sources": True,
        },
        "extensions_enabled": enabled_ext,
        "data_sources": [{
            "source_id": s["source_id"], "name": s["name"], "scope": s["scope"],
            "region_id": s["region_id"], "kind": s["kind"], "version": s["version"],
            "status": s["status"],
        } for s in sources],
        "snapshot_id": runtime.get_snapshot(),
    }
