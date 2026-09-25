# -*- coding: utf-8 -*-
"""N08 引用白名单：只保留本轮工具响应中真实出现过的引用。

用途：扣子编程项目（LangGraph 版 N01—N09）的 N08「自检/格式整理」节点。
配套说明见 `docs/N08引用白名单与提示词增补.md`。

为什么需要它（线上事故回归）：
    N07 模型会把工具响应里的**字段名**或业务字段臆造成引用，例如
    `ev:filter_explanation`、`ev:item:300827`。后端会正确剥离这些非法引用
    （`server/analysis_service.py::_collect_valid_refs`），但结果是
    `answer_blocks[].refs` 全部为空 → 页面上「原文依据」光球消失。
    本模块在引擎侧做一次**确定性白名单过滤**，不依赖模型是否听话。

设计要点：
1. 不按字段名硬编码，递归扫描整个工具响应，避免工具增字段后失效；
2. 只做"存在性白名单"，不判断业务对错（业务校验仍由后端负责）；
3. 过滤是纯函数、确定性、可单测；
4. 不抛异常：任何异常都退化为"原样返回"，绝不因为自检节点导致整轮失败。

自测：
    python -X utf8 coze/n08_ref_filter.py
"""
from __future__ import annotations

import re

# 规范前缀 + 全部别名（与后端 server/schemas.py 的 REF_ALIASES 对齐）
REF_KINDS = ("ev", "evidence", "metric", "product", "pr",
             "analysis", "an", "compare", "cmp",
             "regional", "rg", "company", "co")

_REF_RE = re.compile(r"^(?:" + "|".join(REF_KINDS) + r"):\S+$")
# evidence 必须四段，且 claim_number 为数字
_EV_RE = re.compile(r"^(?:ev|evidence):[^:]+:\d+:[^:]+$")

# 光球类型（与 server/schemas.py::ORB_KINDS 对齐）
ORB_KINDS = ("company", "evidence", "profile", "product",
             "compare", "analysis", "checklist")

MAX_ORBS = 12


def collect_refs(obj, out: set | None = None) -> set:
    """递归收集任意工具响应中所有形如引用的**字符串值**（不含键名）。"""
    if out is None:
        out = set()
    if isinstance(obj, str):
        s = obj.strip()
        if " " not in s and _REF_RE.match(s):
            out.add(s)
    elif isinstance(obj, dict):
        for v in obj.values():
            collect_refs(v, out)
    elif isinstance(obj, (list, tuple, set)):
        for v in obj:
            collect_refs(v, out)
    return out


def _clean_refs(refs, seen: set) -> list:
    """保留白名单内、且 evidence 格式合法的引用；保持原顺序、去重。"""
    out, used = [], set()
    for r in refs or []:
        if not isinstance(r, str):
            continue
        r = r.strip()
        if not r or r in used or r not in seen:
            continue
        if r.startswith(("ev:", "evidence:")) and not _EV_RE.match(r):
            continue
        used.add(r)
        out.append(r)
    return out


def filter_draft_refs(draft: dict, seen: set) -> tuple[dict, list]:
    """按白名单过滤草稿全部引用。

    返回 (过滤后的草稿, 被剔除的引用列表)。被剔除项请写入 draft["warnings"]，
    便于线上排查；**不要**因此判定整轮失败。
    """
    dropped: list[str] = []

    if not isinstance(draft, dict):
        return draft, dropped
    seen = set(seen or set())

    # 1) 回答块
    for b in draft.get("answer_blocks") or []:
        if not isinstance(b, dict):
            continue
        before = list(b.get("refs") or [])
        b["refs"] = _clean_refs(before, seen)
        dropped.extend([x for x in before if x not in b["refs"]])

    # 2) 推荐：product_ref 非法在后端是 block 级问题，会把整次分析降级为
    #    partial，必须一并过滤（比 evidence_refs 为空更严重）。
    for r in draft.get("recommendations") or []:
        if not isinstance(r, dict):
            continue
        for key in ("evidence_refs", "product_source_refs"):
            before = list(r.get(key) or [])
            r[key] = _clean_refs(before, seen)
            dropped.extend([x for x in before if x not in r[key]])
        pref = r.get("product_ref")
        if pref and pref not in seen:
            r["product_ref"] = None
            dropped.append(pref)

    # 3) 光球：过滤非法 ref_id + 丢弃非法 kind
    orbs = draft.get("orbs")
    if isinstance(orbs, list) and orbs:
        kept = []
        for o in orbs:
            if not isinstance(o, dict):
                continue
            if o.get("kind") not in ORB_KINDS:
                dropped.append(f"orb_kind:{o.get('kind')}")
                continue
            rid = o.get("ref_id")
            if rid and rid not in seen:
                dropped.append(rid)
                continue
            kept.append(o)
        draft["orbs"] = kept[:MAX_ORBS]
        # 关键：不要留"半套"光球。只给 product 球会让后端跳过
        # _default_orbs 兜底（analysis_service.py:537），页面上就没有原文球了。
        if not any(o.get("kind") == "evidence" for o in draft["orbs"]):
            draft["orbs"] = []

    return draft, dropped


def n08_selfcheck(state: dict) -> dict:
    """LangGraph 节点包装：从 state 取 draft 与 seen_refs，过滤后写回。

    state 约定：
      state["draft"]       必填，N07 产出的 analysis_draft
      state["seen_refs"]   必填，N05/N06 累积的本轮工具引用白名单
      state["clean_draft"] 输出，供 N09 输出
    """
    try:
        draft = state.get("draft") or {}
        seen = state.get("seen_refs") or set()
        draft, dropped = filter_draft_refs(draft, seen)
        if dropped:
            draft.setdefault("warnings", []).append(
                "已剔除 %d 条无法在工具响应中核对的引用（未采纳模型自造的引用）。"
                % len(dropped))
        state["draft"] = draft
        state["clean_draft"] = draft
    except Exception as e:  # noqa: BLE001  自检节点绝不阻断主流程
        state.setdefault("warnings", []).append(f"引用自检跳过（{type(e).__name__}）。")
    return state


# ---------------- 自测 ----------------

def _self_test() -> int:
    tv = "3f9a1c2e"
    seen = collect_refs({
        "signal_refs": [{"evidence_ref": f"ev:v21_c00020485:3:{tv}"}],
        "rule_candidates": [{"product_ref": "product:settlement"}],
        "metric_refs": {"customer_concentration":
                        "metric:concentration:300827:2023:CustomerConcentration"},
        # 工具响应里的**键名**不得被当作引用
        "filter_explanation": "2023年 · 光伏主链 · T1 落地期",
        "items": [{"scode": "300827", "coname": "上能电气"}],
    })
    fails = []
    checks = []

    def chk(name, cond):
        checks.append(name)
        print(("  [PASS] " if cond else "  [FAIL] ") + name)
        if not cond:
            fails.append(name)

    chk("白名单收集到 3 条真实引用", len(seen) == 3)
    chk("字段名 filter_explanation 未被收集", "ev:filter_explanation" not in seen)
    chk("股票代码未被拼成引用", not any("item" in x for x in seen))

    draft = {
        "answer_blocks": [{"kind": "fact", "text": "…",
                           "refs": [f"ev:v21_c00020485:3:{tv}",
                                    "ev:item:300827", "ev:filter_explanation"]}],
        "recommendations": [{"id": "r1", "product_ref": "product:settlement",
                             "evidence_refs": ["ev:item:002150"],
                             "product_source_refs": ["product:settlement"]},
                            {"id": "r2", "product_ref": "product:fake",
                             "evidence_refs": [], "product_source_refs": []}],
        "orbs": [{"id": "o1", "kind": "product", "ref_id": "product:settlement"},
                 {"id": "o2", "kind": "product", "ref_id": "product:fake"}],
    }
    clean, dropped = filter_draft_refs(draft, seen)

    chk("合法证据引用被保留",
        clean["answer_blocks"][0]["refs"] == [f"ev:v21_c00020485:3:{tv}"])
    chk("自造证据引用被剔除",
        "ev:item:300827" in dropped and "ev:filter_explanation" in dropped)
    chk("非法 product_ref 被置空（避免后端降级 partial）",
        clean["recommendations"][1]["product_ref"] is None)
    chk("合法 product_ref 保留",
        clean["recommendations"][0]["product_ref"] == "product:settlement")
    chk("半套光球被清空，交回后端兜底", clean["orbs"] == [])

    # 含证据球的完整光球列表应被保留
    draft2 = {
        "answer_blocks": [{"refs": [f"ev:v21_c00020485:3:{tv}"]}],
        "recommendations": [],
        "orbs": [{"id": "o1", "kind": "evidence",
                  "ref_id": f"ev:v21_c00020485:3:{tv}"},
                 {"id": "o2", "kind": "product", "ref_id": "product:settlement"}],
    }
    clean2, _ = filter_draft_refs(draft2, seen)
    chk("完整光球（含证据球）被保留", len(clean2["orbs"]) == 2)

    # 异常不得抛出
    st = n08_selfcheck({"draft": None, "seen_refs": None})
    chk("异常输入不抛异常", isinstance(st, dict))

    print("\n%d/%d passed" % (len(checks) - len(fails), len(checks)))
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(_self_test())
