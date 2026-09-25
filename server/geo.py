# -*- coding: utf-8 -*-
"""国别 / 地区 / 市场区域识别与归一化（geo 层）。

- 从原文锚点文本识别国别（canonical）、地区（东南亚等）、市场区域（海外/全球等）
- 最长匹配优先：解决「印度 ⊂ 印度尼西亚」子串重复命中
- 排除误匹配：印度洋、内蒙古 等
- 别名归一：印尼→印度尼西亚、澳洲→澳大利亚、沙特阿拉伯→沙特 等
- 与旧规则（kb_build 的字符串包含）输出可对比，供 audit_geo.py 人工抽检
- 名称场景（交易对手、机构名）另用 `geo_extract_name`：只认高置信位置，避免
  「上海顺斯德国际贸易有限公司」这类中文字串误命中「德国」
"""
import json
import re
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RULES_DIR = ROOT / "rules"


@lru_cache(maxsize=1)
def _geo_rules():
    cr = json.loads((RULES_DIR / "countries.json").read_text(encoding="utf-8"))
    terms = []
    for canon, _cfg in cr["countries"].items():
        for t in [canon] + cr["aliases"].get(canon, []):
            terms.append((t, "country", canon))
    for label, raws in cr["regions"].items():
        for t in [label] + raws:
            terms.append((t, "region", label))
    for ex, _target in cr["exclusions"].items():
        terms.append((ex, "exclude", None))
    terms.sort(key=lambda x: -len(x[0]))
    return cr, terms


def geo_extract(text):
    """从一段文本识别国别与区域。返回 {'countries': [canonical], 'regions': [label]}。"""
    if not isinstance(text, str) or not text.strip():
        return {"countries": [], "regions": []}
    _cr, terms = _geo_rules()
    matches = []
    for term, kind, canon in terms:
        start = 0
        while True:
            i = text.find(term, start)
            if i < 0:
                break
            matches.append((i, len(term), kind, canon))
            start = i + 1
    # 最长匹配优先：按起点升序、同起点按长度降序，重叠即弃
    matches.sort(key=lambda m: (m[0], -m[1]))
    countries, regions = [], []
    last_end = -1
    for i, ln, kind, canon in matches:
        if i < last_end:
            continue
        last_end = i + ln
        if kind == "country":
            countries.append(canon)
        elif kind == "region":
            regions.append(canon)
    return {"countries": sorted(set(countries)), "regions": sorted(set(regions))}


# 名称类文本的分隔符：括号、连字符、点号、空格、顿号等
_NAME_SPLIT = re.compile(r"[（）()\[\]【】{}<>《》,，、;；:：/\\|\-–—_·・\s.]+")


def geo_extract_name(name):
    """企业/机构/交易对手**名称**中的国别线索识别（高置信位置优先）。

    名称与正文的判定标准不同：正文里「…斯德国际…」包含「德国」字串属于误命中，
    若沿用整串子串匹配，会把境内公司误判为境外主体（如
    「上海顺斯德国际贸易有限公司」→ 德国）。因此名称场景只接受两种位置：

      1) 名称开头，如「越南荣宝雨」「丹麦XX有限公司」；
      2) 由分隔符切出的独立片段（括号、连字符、空格等），如
         「荣宝雨(越南)有限公司」「巴基斯坦-National Transmission…」。

    即国别词必须是所在片段的**前缀**（含整段相等）；出现在中文字串中间一律不计。
    这会牺牲「XX美国分公司」这类中置写法（改由人工核实），换取名称判定的精确性。
    """
    if not isinstance(name, str) or not name.strip():
        return {"countries": [], "regions": []}
    _cr, terms = _geo_rules()
    exclusions = [t for t, kind, _c in terms if kind == "exclude"]
    countries, regions = set(), set()
    for tok in _NAME_SPLIT.split(name):
        if not tok:
            continue
        if any(ex in tok for ex in exclusions):
            continue
        best_c = best_r = None
        for term, kind, canon in terms:
            if kind == "exclude" or not tok.startswith(term):
                continue
            if kind == "country" and (best_c is None or len(term) > len(best_c[0])):
                best_c = (term, canon)
            elif kind == "region" and (best_r is None or len(term) > len(best_r[0])):
                best_r = (term, canon)
        if best_c:
            countries.add(best_c[1])
        if best_r:
            regions.add(best_r[1])
    return {"countries": sorted(countries), "regions": sorted(regions)}


@lru_cache(maxsize=4096)
def normalize_name(name):
    """单名归一（子公司国家表 / 国别卡片入参）：完整名优先、别名次之、子串兜底。"""
    if not isinstance(name, str) or not name.strip():
        return None
    name = name.strip()
    cr, terms = _geo_rules()
    if name in cr["countries"]:
        return name
    for canon, aliases in cr["aliases"].items():
        if name == canon or name in aliases:
            return canon
    hits = []
    for term, kind, canon in terms:
        if kind == "country" and term in name:
            hits.append((len(term), canon))
    if hits:
        hits.sort(reverse=True)
        return hits[0][1]
    return None


@lru_cache(maxsize=4096)
def is_region(name):
    cr, _terms = _geo_rules()
    return bool(name) and name in cr["regions"]
