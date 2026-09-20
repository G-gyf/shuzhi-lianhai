# -*- coding: utf-8 -*-
"""v1.3 规则引擎优化冒烟测试（本地验证用）：python smoke_test.py"""
import io
import sys
from collections import Counter

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, ".")

from server import graph, logic  # noqa: E402
from server.geo import geo_extract, normalize_name  # noqa: E402

OK, FAIL = 0, 0


def check(name, cond, extra=""):
    global OK, FAIL
    if cond:
        OK += 1
        print(f"  [PASS] {name} {extra}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name} {extra}")


print("== 1. geo 层单元 ==")
check("印度尼西亚+越南", geo_extract("在印度尼西亚和越南设立生产基地")["countries"] == ["印度尼西亚", "越南"])
check("印度洋误匹配排除", geo_extract("打通印度洋航线")["countries"] == [])
check("东南亚区域", geo_extract("开拓东南亚市场")["regions"] == ["东南亚"])
check("内蒙古误匹配排除", "蒙古" not in geo_extract("内蒙古基地投产")["countries"])
check("沙特阿拉伯归一", geo_extract("沙特阿拉伯项目")["countries"] == ["沙特"])
check("澳洲别名", geo_extract("澳洲子公司")["countries"] == ["澳大利亚"])
check("印尼归一", normalize_name("印尼") == "印度尼西亚")

print("== 2. 聚合与窗口分布（as-of 新国别口径）==")
g = logic.agg()
wdist = Counter(g["window_type"].dropna())
print("   window_type 分布:", dict(wdist))
subs = logic._sub_countries()
entered_full = subs.groupby("scode")["country_canon"].apply(lambda s: set(s.dropna())).to_dict()


def old_win(row):
    import pandas as pd
    if pd.isna(row["overseas_demand"]):
        return "pv_text"
    if row["overseas_demand"] != 1:
        return None
    if (row["overseas_sub_count"] or 0) == 0 and (row["overseas_rev_share"] or 0) <= 0:
        return "first"
    ec = entered_full.get(row["scode"], set())
    if any(c not in ec for c in row["countries"]):
        return "new_country"
    return "expansion"


g2 = g.copy()
g2["old_win"] = g2.apply(old_win, axis=1)
old_nc = int((g2["old_win"] == "new_country").sum())
new_nc = wdist.get("new_country", 0)
print(f"   旧全期口径 new_country={old_nc} → 新 as-of 口径 new_country={new_nc}")
check("as-of 口径将倒灌年份重分类为 new_country", new_nc > old_nc)
check("first 口径不受国别集合影响", wdist.get("first", 0) == int((g2["old_win"] == "first").sum()))
check("窗口企业-年 > 0", sum(wdist.values()) > 0)

print("== 3. 年份上下文贯穿 ==")
d18 = logic.company_detail("002860", 2018)
d23 = logic.company_detail("002860", 2023)
check("2018 详情上下文为 2018", d18["year"] == 2018, f"year={d18['year']}")
check("2023 详情上下文为 2023", d23["year"] == 2023, f"year={d23['year']}")
ch18 = logic.chain("002860", 2018)
check("2018 推理链年份一致", ch18 is not None and ch18["year"] == 2018)
bf23 = logic.briefing("002860", 2023)
check("2023 简报年份一致", bf23 is not None and bf23["year"] == 2023, bf23["title"] if bf23 else "")

print("== 4. 当前/历史信号分离 ==")
d = logic.company_detail("002860", 2023)
sig_years = {s["year"] for s in d["signals"]}
check("当前信号全部来自所选年度", sig_years == {2023} or not sig_years, f"{sig_years}")
check("历史信号归档且不混入", all(s["year"] != 2023 for s in d["history"]["items"]),
      f"count={d['history']['count']}")

print("== 5. 证据绑定 ==")
ch = logic.chain("002860", 2023)
prods = ch["steps"][2]["products"]
check("产品步骤含产品列表", len(prods) > 0)
check("每条产品建议绑定三ID", all(p.get("rule_id") and p.get("signal_id") and p.get("evidence_id") for p in prods))
for p in prods[:5]:
    print(f"   - {p['name']} | {p['rule_id']} | {p['signal_id']}")
check("窗口步骤绑定 rule_id", bool(ch["steps"][0].get("rule_id")))
check("方向步骤含 sources", len(ch["steps"][1].get("sources", [])) > 0)

print("== 6. 产品触发细化（语境守卫）==")
# 找一条 investment_or_contract 且方向非 investment_ma 的当年信号，确认不触发 ma_loan
cl = logic._claims()
guards_ok, guards_total = 0, 0
for _, c in cl[cl["scode"] == "002860"].iterrows():
    if c["execution_anchor_type"] == "investment_or_contract" and c["year"] == 2023:
        guards_total += 1
        if c["direction"] == "investment_ma":
            guards_ok += 1
print(f"   002860 2023 年 investment_or_contract 信号 {guards_total} 条（其中并购方向 {guards_ok} 条）")
check("锚点触发规则带 if_directions 守卫", all("if_directions" in t for ts in logic.rules()["products"]["anchor_extra"].values() for t in ts))

print("== 7. 缺失值待核实 ==")
cap = logic.company_detail("002860", 2023)["capability"]
check("能力评分含数据完整度", "completeness" in cap and cap["completeness"]["total"] == 5)
dims = cap["dims"]
null_dims = [x["label"] for x in dims if x["value"] is None]
print(f"   缺失维度（value=None 待核实）: {null_dims if null_dims else '无'}")
check("无面板企业返回待核实", logic.capability_score("999999")["grade"] == "待核实")

print("== 8. 首次出海口径措辞 ==")
wl = logic.rules()["chains"]["window_label"]["first"]
check("first 措辞不再断言“首次出海”", "首次出海" not in wl, f"label={wl}")
wn = logic.rules()["chains"]["window_note"]["first"]
check("first 口径注记存在", "无已知布局线索" in wn)

print("== 9. 国别卡片 / 区域区分 ==")
cc = graph.country_card("印尼")
check("别名归一至 canonical", cc["type"] == "country" and cc["country"] == "印度尼西亚")
rc = graph.country_card("东南亚")
check("区域级表述单独提示", rc["type"] == "region", rc["clearing"])
uc = graph.country_card("阿兹特克")
check("未识别国别待核实", uc["type"] == "unknown")

print("== 10. 供应链 as-of ==")
sc18 = logic.supply_chain("002860", 2018)
sc23 = logic.supply_chain("002860", 2023)
check("供应链国别边 as-of 口径", len(sc18["edges"]) <= len(sc23["edges"]),
      f"2018 edges={len(sc18['edges'])} vs 2023 edges={len(sc23['edges'])}")

print("== 11. 子图与名单 ==")
gph = graph.get_company_graph("002860", 2023)
check("子图返回节点", len(gph["nodes"]) > 0)
radar = logic.radar(limit=5)
check("radar 含国别+区域字段", all("countries" in r and "regions" in r for r in radar))

print(f"\n结果：{OK} 通过 / {FAIL} 失败")
sys.exit(1 if FAIL else 0)
