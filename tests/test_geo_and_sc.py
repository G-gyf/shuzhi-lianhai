# -*- coding: utf-8 -*-
"""回归：国别名称误命中修复 + 供应链单跳画像（移除多跳/修复 500）。

背景：
1. 名称场景沿用整串子串匹配，会把「上海顺斯德国际贸易有限公司」误判为「德国」。
   现改为名称专用判定（只认名称开头或分隔符片段内的国别词）。
2. `sc_of()` 在多跳行第二跳缺失时对 NaN 做 int()，导致 16 家企业的
   `/api/company/{scode}/supply-chain` 返回 500。多跳已按 Neo4j 扩展设计从本期能力移除。
"""
import unittest

from server import logic, sc
from server.geo import geo_extract, geo_extract_name

# 曾因多跳行第二跳缺失而 500 的企业
PREVIOUSLY_FAILING = [
    "000586", "002296", "002498", "003023", "300048", "300080", "300105",
    "300274", "300447", "300907", "600268", "600312", "600577", "601179",
    "603031", "688330",
]


class TestGeoName(unittest.TestCase):

    def test_legit_names_still_detected(self):
        """名称开头或括号片段内的国别词仍然命中。"""
        cases = {
            "HF公司(丹麦)": ["丹麦"],
            "荣宝雨(越南)有限公司": ["越南"],
            "越南荣宝雨": ["越南"],
            "巴基斯坦-National Transmission&Despatch CO.LTD.(巴基斯坦))": ["巴基斯坦"],
            "PROYECTOS DE INFRAESTRUCTURA DEL PERU S.A.C.(秘鲁)": ["秘鲁"],
        }
        for name, want in cases.items():
            self.assertEqual(geo_extract_name(name)["countries"], want, name)

    def test_chinese_substring_false_positive_rejected(self):
        """中文字串中间出现的国别词不再误命中（本次修复的缺陷）。"""
        fp = "上海顺斯德国际贸易有限公司"      # 「…斯德国际…」含「德国」
        self.assertEqual(geo_extract(fp)["countries"], ["德国"])       # 旧行为仍在（正文场景）
        self.assertEqual(geo_extract_name(fp)["countries"], [])         # 名称场景已修正
        for name in ("深圳市顺络电子股份有限公司", "内蒙古第一机械集团", "中芯国际(天津)"):
            self.assertEqual(geo_extract_name(name)["countries"], [], name)

    def test_prose_scenario_unchanged(self):
        """正文场景仍用子串匹配，不因名称修复而丢失召回。"""
        self.assertEqual(geo_extract("在印度尼西亚和越南设立生产基地")["countries"],
                         ["印度尼西亚", "越南"])
        self.assertEqual(geo_extract("打通印度洋航线")["countries"], [])


class TestSupplyChainSingleHop(unittest.TestCase):

    def test_no_exception_for_network_firms(self):
        """原先 500 的 16 家企业在同一调用路径下不再抛异常。"""
        for code in PREVIOUSLY_FAILING:
            with self.subTest(scode=code):
                out = logic.supply_chain(code)
                self.assertEqual(out["scode"], code)
                self.assertIsInstance(out["nodes"], list)

    def test_two_hop_removed_from_payload(self):
        """多跳不再作为本期能力输出（含曾有两跳数据的 000922/002471）。"""
        for code in ("000922", "002471", "002860"):
            with self.subTest(scode=code):
                detail = logic.supply_chain(code)["detail"]
                self.assertNotIn("two_hop", detail)
                self.assertNotIn("two_hop", sc.sc_of(code))

    def test_counterparty_name_not_falsely_overseas(self):
        """交易对手名称的境外标记与名称专用判定一致。"""
        purchase = sc.top5_purchase()
        hit = purchase[purchase["name"] == "上海顺斯德国际贸易有限公司"]
        if not hit.empty:
            self.assertFalse(bool(hit["overseas"].any()))
        sale = sc.top5_sale()
        self.assertEqual(int(sale["overseas"].sum()), 10)   # 5 家具名客户，召回不变


if __name__ == "__main__":
    unittest.main()
