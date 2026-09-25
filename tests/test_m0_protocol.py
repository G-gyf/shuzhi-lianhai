# -*- coding: utf-8 -*-
"""M0 验收：年份/缺失/总数口径 + 协议冻结（方案 14 章 M0、15.1 用例 1/4）。"""
import unittest

from server import logic, runtime, tools
from server.schemas import parse_ref


class TestM0Protocol(unittest.TestCase):

    def setUp(self):
        runtime.init_runtime()

    def test_snapshot_stable(self):
        self.assertEqual(runtime.get_snapshot(), runtime.get_snapshot())
        self.assertTrue(runtime.get_snapshot().startswith("kb-2023@"))

    def test_text_version_stable(self):
        self.assertEqual(runtime.text_version("同一段文本"), runtime.text_version("同一段文本"))
        self.assertNotEqual(runtime.text_version("A"), runtime.text_version("B"))

    def test_meta_has_snapshot(self):
        from server.main import api_meta
        m = api_meta()
        self.assertEqual(m["snapshot_id"], runtime.get_snapshot())
        self.assertTrue(m["years"])

    def test_search_total_real_and_paged(self):
        ctx = tools.build_context({"user_id": "t", "display_name": "t",
                                   "regions": [], "identity_mode": "demo"})
        r = tools.search_companies(ctx, province="江苏省", industry="光伏",
                                   direction="capacity_production")
        self.assertTrue(r["ok"])
        self.assertGreater(r["total"], 0)
        self.assertLessEqual(len(r["items"]), 20)
        self.assertIn("direction", r["filter_explanation"])

    def test_strict_year_no_fallback(self):
        """无该年度数据时不回退未来年份（验收用例 4）。"""
        d = logic.company_detail("002860", 2000, strict_year=True)
        self.assertEqual(d["year"], 2000)
        self.assertEqual(d["signals"], [])
        self.assertEqual(d["panel_status"], "text_only")
        self.assertEqual(d["capability"]["grade"], "待核实")

    def test_ref_parse_aliases(self):
        self.assertEqual(parse_ref("ev:abc:1:tv12")[0], "evidence")
        self.assertEqual(parse_ref("product:settlement")[0], "product")
        self.assertIsNone(parse_ref("bad"))
        self.assertIsNone(parse_ref("sql:select"))


if __name__ == "__main__":
    unittest.main()
