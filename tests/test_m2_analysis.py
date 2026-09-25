# -*- coding: utf-8 -*-
"""M2 验收：分析编排、校验、保存、降级（方案 12 章、15.1 用例 6/7/9/10）。"""
import unittest

from server import analysis_service, runtime, tools


def user_a():
    return runtime.authenticate("Bearer demo-token-region-a")


class TestM2Analysis(unittest.TestCase):

    def setUp(self):
        runtime.init_runtime()

    def test_local_engine_plan_flow(self):
        """查企业→分析→方案连续完成；偏好调整方案、证据保留（用例 6）。"""
        u = user_a()
        page = {"scode": "002860", "year": 2023}
        res = analysis_service.prepare_analysis(
            "重点谈结算，不考虑融资", u, page,
            runtime.get_preferences(u["user_id"]), [], {}, "t_plan")
        self.assertFalse(res.get("clarify"))
        a = res["analysis"]
        self.assertEqual(a["status"], "validated")
        self.assertTrue(a["analysis_id"].startswith("an_"))
        self.assertTrue(a["recommendations"])
        # 排除融资
        self.assertNotIn("出海金融",
                         [r["product_ref"].split(":")[-1] and
                          tools.products.get_card(r["product_ref"].split(":")[-1])["category"]
                          for r in a["recommendations"] if r["product_ref"]])
        # 每个建议有理由且证据引用合法
        for r in a["recommendations"]:
            self.assertTrue(r["reason"])
        self.assertGreaterEqual(len(a["questions"]), 3)

    def test_validation_drops_illegal_ref(self):
        """非法引用不生成光球（用例 9 后端口径）。"""
        u = user_a()
        draft = {
            "schema_version": "1.0",
            "context": {"scode": "002860", "year": 2023},
            "status": "draft",
            "answer_blocks": [{"kind": "fact", "text": "正常文本",
                               "refs": ["ev:notexist:1:ffff"]},
                              {"kind": "fact", "text": "正常文本2", "refs": []}],
            "recommendations": [],
            "questions": [],
            "orbs": [{"id": "bad_orb", "kind": "evidence", "label": "坏球",
                      "ref_id": "ev:notexist:1:ffff", "state": "ready"}],
            "warnings": [],
            "provenance": {"engine": "test"},
        }
        ctx = tools.build_context(u)
        clean, issues = analysis_service.validate_draft(draft, ctx, {"scode": "002860"})
        self.assertEqual(clean["answer_blocks"][0]["refs"], [])
        self.assertEqual(clean["orbs"], [])
        self.assertTrue(any(i["code"] == "bad_ref" for i in issues))

    def test_unmarked_card_not_downgraded(self):
        """产品卡只在 status=verified 时标注；未标注卡片不做标记，资格不因标注状态被降级。"""
        u = user_a()
        draft = {
            "schema_version": "1.0",
            "context": {"scode": "002860", "year": 2023},
            "status": "draft",
            "answer_blocks": [{"kind": "fact", "text": "x", "refs": []}],
            "recommendations": [{
                "id": "rec_x", "product_ref": "product:ma_loan",
                "priority": "discussion_first", "reason": "test",
                "evidence_refs": [], "product_source_refs": ["product:ma_loan"],
                "eligibility": "eligible", "missing_conditions": [],
            }],
            "questions": [], "orbs": [], "warnings": [],
            "provenance": {"engine": "test"},
        }
        clean, issues = analysis_service.validate_draft(draft, tools.build_context(u), {})
        self.assertEqual(clean["recommendations"][0]["eligibility"], "eligible")
        self.assertFalse(any(i["code"] == "placeholder_eligible" for i in issues))

    def test_persist_and_read_back(self):
        u = user_a()
        res = analysis_service.prepare_analysis(
            "这家公司值得关注什么", u, {"scode": "002860", "year": 2023},
            runtime.get_preferences(u["user_id"]), [], {}, "t_persist")
        aid = res["analysis"]["analysis_id"]
        back = analysis_service.get_analysis(aid, u)
        self.assertIsNotNone(back)
        self.assertEqual(back["snapshot_id"], runtime.get_snapshot())
        self.assertEqual(back["engine"], "rules-demo")

    def test_briefing_consistent_with_analysis(self):
        """验收用例 15：同一 analysis_id 的对话、详情方案和简报内容一致。"""
        u = user_a()
        res = analysis_service.prepare_analysis(
            "结合客户集中度做拜访方案", u, {"scode": "002860", "year": 2023},
            runtime.get_preferences(u["user_id"]), [], {}, "t_brief")
        aid = res["analysis"]["analysis_id"]
        back = analysis_service.get_analysis(aid, u)
        briefing = analysis_service.build_briefing(aid, u)
        fact_texts = [b["text"] for b in back["draft"]["answer_blocks"]
                      if b["kind"] == "fact"]
        self.assertTrue(any(t in briefing["sections"][0]["body"] for t in fact_texts))
        q_texts = [q["text"] for q in back["draft"]["questions"]]
        body_all = "\n".join(s["body"] for s in briefing["sections"])
        self.assertTrue(all(q.split("：")[1].split("是否")[0] in body_all
                           for q in q_texts if "：" in q))

    def test_historical_year_noted(self):
        """历史年度：注明采用当前服务资料的演示建议（方案 1.1）。"""
        u = user_a()
        res = analysis_service.prepare_analysis(
            "这家公司为何入选？", u, {"scode": "002860", "year": 2018},
            runtime.get_preferences(u["user_id"]), [], {}, "t_hist")
        a = res["analysis"]
        self.assertTrue(any("历史企业资料" in w for w in a["warnings"]))

    def test_workflow_parameters_include_verifiable_context_token(self):
        """发给 Coze 工作流的入参必须带每轮签发的 context_token（方案 5.2）。

        工作流开始节点声明同名变量 `context_token`，插件 Header 引用它。
        """
        from server import context_token
        u = user_a()
        cfg = {"tool_context_secret": "unit-test-secret", "max_tool_calls": 6,
               "max_compare_companies": 3,
               "tools_base_url": "https://example.up.railway.app"}
        params, warning = analysis_service.build_workflow_parameters(
            "这家公司值得关注什么", u, {"scode": "002860", "year": 2023},
            runtime.get_preferences(u["user_id"]), [], cfg)
        self.assertIsNone(warning)
        self.assertTrue(params["context_token"])
        payload = context_token.verify_context_token(params["context_token"],
                                                    "unit-test-secret")
        self.assertIsNotNone(payload, "context_token 应能用同一密钥验签")
        self.assertEqual(payload["user_id"], u["user_id"])
        self.assertEqual(payload["regions"], u["regions"])
        self.assertEqual(payload["snapshot_id"], runtime.get_snapshot())
        self.assertIn("get_company_context", payload["allowed_tools"])
        self.assertEqual(params["tools_base_url"], cfg["tools_base_url"])
        self.assertEqual(params["data_snapshot"], runtime.get_snapshot())
        # 错误密钥验签失败（防伪造）
        self.assertIsNone(context_token.verify_context_token(
            params["context_token"], "wrong-secret"))

    def test_workflow_parameters_without_secret_warns(self):
        """未配置 TOOL_CONTEXT_SECRET 时如实告警（不静默发出空 token）。"""
        u = user_a()
        cfg = {"tool_context_secret": "", "max_tool_calls": 6,
               "max_compare_companies": 3, "tools_base_url": ""}
        params, warning = analysis_service.build_workflow_parameters(
            "分析一下", u, {}, {}, [], cfg)
        self.assertEqual(params["context_token"], "")
        self.assertIn("TOOL_CONTEXT_SECRET", warning)


if __name__ == "__main__":
    unittest.main()
