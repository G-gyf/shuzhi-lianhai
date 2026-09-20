# -*- coding: utf-8 -*-
"""国别识别人工抽检：旧规则（kb_build 字符串包含） vs 新 geo 层。

输出 audit/geo_audit.txt：
1) 旧 country_hits 原始值分布（含误匹配线索）
2) 新 geo 层 canonical 国别分布
3) 区域表述分布
4) 差异样本：旧有国别、新无（子串重复/误匹配候选，附锚点例句）
5) 别名归一明细（如 印尼→印度尼西亚）
6) 子公司国家表原始值分布与未归一清单

运行：python audit_geo.py
"""
import io
import sys
from collections import Counter
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from server.geo import normalize_name          # noqa: E402
from server.logic import _claims, _sub_countries  # noqa: E402


def main():
    cl = _claims()
    lines = []

    def w(s=""):
        lines.append(s)
        print(s)

    w("=" * 64)
    w("1) 旧 country_hits 原始值分布（Top 40）")
    old = Counter(h for xs in cl["country_hits"] for h in xs)
    for k, v in old.most_common(40):
        w(f"  {v:6d}  {k}")

    w("=" * 64)
    w("2) 新 geo 层 canonical 国别分布（Top 40）")
    new = Counter(c for xs in cl["geo_countries"] for c in xs)
    for k, v in new.most_common(40):
        w(f"  {v:6d}  {k}")

    w("=" * 64)
    w("3) 区域表述分布（Top 30）")
    reg = Counter(r for xs in cl["geo_regions"] for r in xs)
    for k, v in reg.most_common(30):
        w(f"  {v:6d}  {k}")

    w("=" * 64)
    w("4) 差异样本：旧有国别、新无（子串重复/误匹配候选，Top 20）")
    diff = Counter()
    samples = {}
    for _, c in cl.iterrows():
        oldset = set(c["country_hits"])
        newset = set(c["geo_countries"])
        for h in oldset - newset:
            diff[h] += 1
            samples.setdefault(h, c["execution_anchor"])
    for k, v in diff.most_common(20):
        w(f"  {v:6d}  {k}  例：「{samples[k]}」")

    w("=" * 64)
    w("5) 别名归一明细（旧值→canonical，Top 30）")
    pairs = Counter()
    for h, v in old.items():
        canon = normalize_name(h)
        if canon and canon != h:
            pairs[(h, canon)] += v
    for (h, canon), v in pairs.most_common(30):
        w(f"  {v:6d}  {h} -> {canon}")

    w("=" * 64)
    w("6) 子公司国家表：原始值分布（Top 60）")
    subs = _sub_countries()
    sc = Counter(subs["country"].dropna())
    for k, v in sc.most_common(60):
        w(f"  {v:6d}  {k}")

    w("7) 子公司国家表：未归一值")
    unm = sorted(set(subs[subs["country_canon"].isna()]["country"].dropna()))
    w("  " + ("；".join(unm) if unm else "（全部归一）"))

    out = ROOT / "audit" / "geo_audit.txt"
    out.parent.mkdir(exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nsaved -> {out}")


if __name__ == "__main__":
    main()
