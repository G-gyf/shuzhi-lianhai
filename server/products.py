# -*- coding: utf-8 -*-
"""产品卡与资料检索（方案第 10 章）。

- 条件、名称、ID 用结构化表保存；程序可检查已知冲突（见 `check_conflicts`）。
- 首版产品少，精确读取相关卡片，不建设复杂向量库。
- 卡片可选带 `status`：`verified` 表示已核实演示卡；未标注 `status` 的卡片不做标注，
  检索结果照常带出该字段（可能为 null）。
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from .schemas import product_ref

ROOT = Path(__file__).resolve().parent.parent
CARDS_PATH = ROOT / "knowledge" / "products" / "product_cards.json"

# 服务方向中文（与 web/assets/app.js DIR_CN 一致）
DIRECTION_CN = {
    "market_expansion": "市场开拓",
    "capacity_production": "产能出海",
    "channel_supply_chain": "渠道供应链",
    "local_organization_readiness": "本地准备",
    "rd_localization": "研发本地化",
    "investment_ma": "投资并购",
}

# 服务关注点关键词（用户偏好 service_focus → 产品 key 检索）
FOCUS_KEYWORDS = {
    "settlement": ["结算", "人民币结算", "清算", "账户", "收付款", "跨境e企通"],
    "account": ["账户", "开户", "离岸账户"],
    "guarantee": ["保函", "担保"],
    "hedging": ["汇率", "避险", "远期", "期权"],
    "treasury": ["司库", "资金池", "现金管理"],
    "financing": ["贷款", "融资", "并购", "内保外贷"],
}


@lru_cache(maxsize=1)
def _catalog():
    with open(CARDS_PATH, encoding="utf-8") as f:
        return json.load(f)


def product_version() -> str:
    return _catalog()["version"]


def get_card(product_id: str) -> dict | None:
    for c in _catalog()["cards"]:
        if c["product_id"] == product_id:
            return c
    return None


def card_ref(card: dict) -> dict:
    """产品引用：绑定产品ID、版本、来源与状态。"""
    return {
        "ref_id": product_ref(card["product_id"]),
        "product_id": card["product_id"],
        "name": card["name"],
        "category": card["category"],
        "status": card.get("status"),
        "product_version": product_version(),
        "source": card["source"],
        "source_date": card["source_date"],
    }


def all_cards() -> list[dict]:
    return _catalog()["cards"]


def search_product_knowledge(actions: list[str] | None = None,
                             service_focus: list[str] | None = None,
                             as_of: str | None = None) -> dict:
    """按 行动方向 / 服务偏好 检索产品卡。

    返回：
      cards: 产品卡（含 ref）列表
      coverage: 检索命中说明（口径、命中来源）
    原则：同时检索不到企业证据和产品资料时不生成确定的服务适配结论。
    """
    cards = all_cards()
    direction_words = [DIRECTION_CN.get(a, a) for a in (actions or [])]
    focus_words: list[str] = []
    for f in (service_focus or []):
        focus_words += FOCUS_KEYWORDS.get(f, [f])

    def match(c):
        text = " ".join([c["name"], c["category"], c["summary"],
                         " ".join(c["scenarios"]), " ".join(c["keywords"])])
        if direction_words:
            # 行动方向映射到触发规则 RULE_DIR_*
            if not any(f"RULE_DIR_{a}" in c["trigger_rules"] for a in (actions or [])):
                return False
        if focus_words and not any(w in text for w in focus_words):
            return False
        return True

    hits = [c for c in cards if match(c)]
    out = {
        "total": len(hits),
        "cards": [card_ref(c) for c in hits],
        "detail": [{**c, "ref_id": product_ref(c["product_id"])} for c in hits],
        "coverage": {
            "product_version": product_version(),
            "as_of": as_of,
            "actions": actions or [],
            "service_focus": service_focus or [],
            "note": ("演示产品卡口径：status=verified 的卡片经公开来源整理；未标注 status 的卡片不做标注。"
                     "具体产品名称、条件与收费以行内最新产品手册为准。"),
        },
    }
    return out


def check_conflicts() -> list[str]:
    """程序化检查已知冲突：重复 product_id / 缺失必要字段。"""
    issues = []
    cards = all_cards()
    seen = set()
    required = ["product_id", "name", "category", "summary",
                "scenarios", "conditions", "source", "source_date", "version"]
    for c in cards:
        if c["product_id"] in seen:
            issues.append(f"重复 product_id: {c['product_id']}")
        seen.add(c["product_id"])
        for f in required:
            if f not in c or c[f] in (None, "", []):
                issues.append(f"{c.get('product_id', '?')} 缺失字段 {f}")
    return issues
