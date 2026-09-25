# -*- coding: utf-8 -*-
"""M1 验收：企业工具、产品卡、证据包（方案 14 章 M1、15.1 用例 2/3/5/8）。"""
import unittest

from server import products, runtime, tools


def ctx_a():
    return tools.build_context(runtime.authenticate("Bearer demo-token-region-a"))


class TestM1Tools(unittest.TestCase):

    def setUp(self):
        runtime.init_runtime()

    def test_resolve_company_code_and_name(self):
        ctx = ctx_a()
        r1 = tools.resolve_company(ctx, "002860")
        self.assertTrue(r1["ok"] and not r1["ambiguous"])
        self.assertEqual(r1["matches"][0]["coname"], "星帅尔")
        r2 = tools.resolve_company(ctx, "星帅尔")
        self.assertEqual(r2["matches"][0]["scode"], "002860")
        r3 = tools.resolve_company(ctx, "不存在的企业名XYZ")
        self.assertEqual(r3["matches"], [])

    def test_company_context_same_year_pack(self):
        """验收用例 3：从企业详情提问，不重复输入代码；年份一致。"""
        ctx = ctx_a()
        r = tools.get_company_context(ctx, "002860", 2023)
        self.assertTrue(r["ok"])
        self.assertEqual(r["year"], 2023)
        self.assertEqual(r["requested_year"], 2023)
        self.assertTrue(r["signal_refs"])
        self.assertTrue(r["rule_candidates"])
        for ref in r["signal_refs"]:
            self.assertTrue(ref["evidence_ref"].startswith("ev:"))

    def test_evidence_ref_roundtrip(self):
        """验收用例 8：原文球按指定文本版本高亮。"""
        ctx = ctx_a()
        pkg = tools.get_company_context(ctx, "002860", 2023)
        ref = pkg["signal_refs"][0]["evidence_ref"]
        ev = tools.get_evidence(ctx, ref)
        self.assertTrue(ev["ok"])
        self.assertEqual(ev["status"], "ok")
        self.assertEqual(len(ev["spans"]), 1)
        span = ev["spans"][0]
        self.assertIn(ev["text"][span["start"]:span["end"]], ev["text"])
        # 文本版本可还原
        self.assertEqual(runtime.text_version(ev["text"]), ev["text_version"])

    def test_compare_same_year_and_missing(self):
        """验收用例 5：两家企业比较使用同一年度和清楚的缺失标识。"""
        ctx = ctx_a()
        r = tools.compare_companies(ctx, ["002860", "300670"], 2023)
        self.assertTrue(r["ok"])
        self.assertEqual(len(r["companies"]), 2)
        self.assertTrue(all(c["year"] == 2023 for c in r["companies"]))
        self.assertIn("reference", r)
        self.assertEqual(r["compare_ref"].split(":")[0], "compare")

    def test_compare_caps_at_three(self):
        ctx = ctx_a()
        items = tools.search_companies(ctx, province="江苏省", industry="光伏")["items"]
        codes = [i["scode"] for i in items[:4]]
        if len(codes) < 2:
            self.skipTest("样本不足")
        r = tools.compare_companies(ctx, codes, 2023)
        if r["ok"]:
            self.assertLessEqual(len(r["companies"]), 3)

    def test_rule_candidates_direction_filter(self):
        ctx = ctx_a()
        r = tools.get_rule_candidates(ctx, "002860", 2023,
                                      directions=["market_expansion"])
        self.assertTrue(r["ok"])
        for c in r["candidates"]:
            self.assertEqual(c["rule_id"], "RULE_DIR_market_expansion")

    def test_product_cards_complete(self):
        self.assertGreaterEqual(len(products.all_cards()), 8)
        self.assertEqual(products.check_conflicts(), [])
        verified = [c for c in products.all_cards() if c["status"] == "verified"]
        self.assertGreaterEqual(len(verified), 5)
        for c in products.all_cards():
            self.assertTrue(c["source"] and c["source_date"])

    def test_product_search_focus(self):
        r = products.search_product_knowledge(service_focus=["settlement"])
        self.assertGreater(r["total"], 0)
        for c in r["cards"]:
            self.assertTrue(c["ref_id"].startswith("product:"))

    def test_no_financing_when_excluded(self):
        """偏好排除融资：候选不含出海金融类（验收用例 6 后端口径）。"""
        from server import local_engine
        ctx = ctx_a()
        d = tools.get_company_context(ctx, "002860", 2023)
        prefs = {"service_focus": ["settlement"], "exclude_financing": True}
        recs, _, _ = local_engine._recs_for(d, prefs, ctx, None)
        self.assertNotIn("出海金融", [r.get("_category") for r in recs])


if __name__ == "__main__":
    unittest.main()
