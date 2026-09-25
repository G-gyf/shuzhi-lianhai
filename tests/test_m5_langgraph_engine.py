# -*- coding: utf-8 -*-
"""LangGraph 引擎适配验收：本地桩服务模拟扣子编程引擎，验证接入与降级。

覆盖：
1. 引擎可用时：走 langgraph，入参 11 个变量同名，返回草稿被校验后入库；
2. 引擎返回 500 / 连不上：自动降级 rules-demo，并在 warnings 里说明原因；
3. 引擎返回纯文本（澄清话术）：作为 note 块呈现；
4. normalize_draft：补 context / provenance / 空数组字段；
5. 真实 evidence_ref 经引擎往返后仍能通过后端校验（引用保留）。
"""
import json
import os
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from server import analysis_service, langgraph_client, runtime, tools
from server.schemas import SCHEMA_VERSION

STATE = {"status": 200, "response": {}, "last_request": None, "requests": 0,
         "get_status": 200, "get_body": None}


class _Handler(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        n = int(self.headers.get("Content-Length", 0) or 0)
        body = self.rfile.read(n) if n else b"{}"
        try:
            STATE["last_request"] = json.loads(body.decode("utf-8"))
        except ValueError:
            STATE["last_request"] = None
        STATE["requests"] += 1
        data = json.dumps(STATE["response"], ensure_ascii=False).encode("utf-8")
        self.send_response(STATE["status"])
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):  # noqa: N802
        status = STATE.get("get_status", 200)
        body = STATE.get("get_body") or '{"status":"ok"}'
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):  # 静音
        pass


class TestLangGraphEngine(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        runtime.init_runtime()
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.port}"
        cls.user = runtime.authenticate("Bearer demo-token-region-a")

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def setUp(self):
        self._env = {k: os.environ.get(k) for k in
                     ("AI_ENGINE", "LANGGRAPH_BASE_URL", "AI_ENABLED",
                      "TOOL_CONTEXT_SECRET", "COZE_WORKFLOW_ID")}
        os.environ["AI_ENGINE"] = "langgraph"
        os.environ["LANGGRAPH_BASE_URL"] = self.base
        os.environ["AI_ENABLED"] = "1"
        os.environ["TOOL_CONTEXT_SECRET"] = "unit-test-secret"
        os.environ.pop("COZE_WORKFLOW_ID", None)
        STATE.update({"status": 200, "response": {}, "last_request": None, "requests": 0,
                      "get_status": 200, "get_body": None})
        # 探活结果有 60 秒 TTL 缓存，逐例清空以免相互污染
        analysis_service.reset_engine_probe_cache()

    def tearDown(self):
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def _draft(self, **extra) -> dict:
        draft = {
            "answer_blocks": [
                {"kind": "fact", "text": "星帅尔（002860）在 2023 年度处于出海扩张期。", "refs": []},
                {"kind": "hypothesis", "text": "若其市场开拓方向落地，预计产生开户与结算需求。", "refs": []},
            ],
            "recommendations": [{
                "id": "rec_settlement", "product_ref": "product:settlement",
                "priority": "discussion_first", "reason": "规则命中：方向「市场开拓」",
                "evidence_refs": [], "product_source_refs": ["product:settlement"],
                "eligibility": "unknown", "missing_conditions": ["结算账户是否已开立"],
            }],
            "questions": [{"text": "贵司人民币结算账户是否已开立？",
                           "related_recommendation": "rec_settlement"}],
            "warnings": [],
        }
        draft.update(extra)
        return draft

    # ---- 1) 正常路径 ----
    def test_langgraph_engine_happy_path(self):
        STATE["response"] = {"result": json.dumps(self._draft(), ensure_ascii=False)}
        res = analysis_service.prepare_analysis(
            "这家公司值得关注什么", self.user, {"scode": "002860", "year": 2023},
            runtime.get_preferences(self.user["user_id"]), [], {}, "t_lg_1")
        self.assertFalse(res.get("clarify"))
        a = res["analysis"]
        self.assertEqual(res["engine"], "langgraph")
        self.assertEqual(a["status"], "validated")
        self.assertTrue(a["analysis_id"].startswith("an_"))
        self.assertEqual(a["context"]["scode"], "002860")
        self.assertEqual(a["context"]["snapshot_id"], runtime.get_snapshot())
        self.assertEqual(a["recommendations"][0]["product_ref"], "product:settlement")
        self.assertTrue(any(o["kind"] == "product" for o in a["orbs"]) or a["orbs"] == [])
        # 入参契约：11 个变量同名，且令牌非空
        req = STATE["last_request"]
        for key in ("message", "context_token", "page_context", "history_summary",
                    "preferences", "data_snapshot", "product_version",
                    "tools_base_url", "allowed_tools", "max_tool_calls",
                    "max_compare_companies"):
            self.assertIn(key, req, f"入参缺 {key}")
        self.assertTrue(req["context_token"])
        self.assertEqual(req["page_context"]["scode"], "002860")
        # 引擎标识写进运行记录
        back = analysis_service.get_analysis(a["analysis_id"], self.user)
        self.assertEqual(back["engine"], "langgraph")
        self.assertEqual(back["workflow_version"], self.base)

    # ---- 2) 引擎 500 → 降级 ----
    def test_fallback_to_rules_when_engine_fails(self):
        STATE["status"] = 500
        STATE["response"] = {"detail": "boom"}
        res = analysis_service.prepare_analysis(
            "这家公司值得关注什么", self.user, {"scode": "002860", "year": 2023},
            runtime.get_preferences(self.user["user_id"]), [], {}, "t_lg_2")
        self.assertEqual(res["engine"], "rules-demo")
        a = res["analysis"]
        self.assertTrue(any("LangGraph" in w for w in a["warnings"]),
                        f"降级原因未注明：{a['warnings']}")
        self.assertTrue(a["answer_blocks"])

    def test_fallback_when_engine_unreachable(self):
        os.environ["LANGGRAPH_BASE_URL"] = "http://127.0.0.1:1"   # 必然连不上
        res = analysis_service.prepare_analysis(
            "分析一下", self.user, {"scode": "002860", "year": 2023},
            runtime.get_preferences(self.user["user_id"]), [], {}, "t_lg_3")
        self.assertEqual(res["engine"], "rules-demo")
        self.assertTrue(any("LangGraph" in w for w in res["analysis"]["warnings"]))

    # ---- 3) 引擎返回纯文本（澄清） ----
    def test_text_output_becomes_note_block(self):
        STATE["response"] = {"result": "请选择要分析的企业：（1）星帅尔 002860"}
        res = analysis_service.prepare_analysis(
            "这家公司如何", self.user, {}, runtime.get_preferences(self.user["user_id"]),
            [], {}, "t_lg_4")
        a = res["analysis"]
        self.assertEqual(res["engine"], "langgraph")
        self.assertEqual(a["answer_blocks"][0]["kind"], "note")
        self.assertIn("请选择要分析的企业", a["answer_blocks"][0]["text"])
        self.assertTrue(any("澄清话术" in w for w in a["warnings"]))

    # ---- 4) normalize_draft 规整 ----
    def test_normalize_draft_fills_context_and_provenance(self):
        payload = {"result": json.dumps({"answer_blocks": [{"kind": "fact", "text": "x"}]},
                                       ensure_ascii=False)}
        draft = langgraph_client.normalize_draft(payload, {"scode": "002860", "year": 2023},
                                                runtime.get_snapshot(), "product-cards-v1")
        self.assertEqual(draft["schema_version"], SCHEMA_VERSION)
        self.assertEqual(draft["context"]["scode"], "002860")
        self.assertEqual(draft["context"]["year"], 2023)
        self.assertEqual(draft["context"]["product_version"], "product-cards-v1")
        self.assertEqual(draft["recommendations"], [])
        self.assertEqual(draft["provenance"]["engine"], "langgraph")

    def test_normalize_draft_rejects_empty(self):
        with self.assertRaises(langgraph_client.LangGraphError):
            langgraph_client.normalize_draft({}, {}, "kb-2023@x", "v1")

    # ---- 5) 真实引用经引擎往返后仍被保留 ----
    def test_real_refs_survive_roundtrip(self):
        ctx = tools.build_context(self.user)
        pkg = tools.call_tool("get_company_context", ctx, {"scode": "002860", "year": 2023})
        ref = pkg["signal_refs"][0]["evidence_ref"]
        draft = self._draft()
        draft["answer_blocks"][0]["refs"] = [ref]
        draft["recommendations"][0]["evidence_refs"] = [ref]
        STATE["response"] = {"result": json.dumps(draft, ensure_ascii=False)}
        res = analysis_service.prepare_analysis(
            "这家公司为何入选", self.user, {"scode": "002860", "year": 2023},
            runtime.get_preferences(self.user["user_id"]), [], {}, "t_lg_5")
        a = res["analysis"]
        self.assertEqual(a["answer_blocks"][0]["refs"], [ref], "合法引用不应被裁掉")
        self.assertTrue(any(o["kind"] == "evidence" and o["ref_id"] == ref
                            for o in a["orbs"]), "应生成原文球")

    # ---- 7) 地址归一化与错误自解释（对应线上 InvalidURL 事故） ----
    def test_base_url_with_whitespace_is_trimmed(self):
        """环境变量面板复制粘贴常带空格/换行 —— 必须自动清理而不是报 InvalidURL。"""
        os.environ["LANGGRAPH_BASE_URL"] = f"  {self.base}\n"
        STATE["response"] = {"result": json.dumps(self._draft(), ensure_ascii=False)}
        res = analysis_service.prepare_analysis(
            "这家公司值得关注什么", self.user, {"scode": "002860", "year": 2023},
            runtime.get_preferences(self.user["user_id"]), [], {}, "t_lg_6")
        self.assertEqual(res["engine"], "langgraph")

    def test_base_url_without_scheme_gives_clear_error(self):
        os.environ["LANGGRAPH_BASE_URL"] = "code.coze.cn/run"
        with self.assertRaises(langgraph_client.LangGraphError) as cm:
            langgraph_client.run({"message": "x"})
        self.assertEqual(cm.exception.code, "bad_base_url")
        self.assertIn("http://", cm.exception.message)

    def test_editor_page_url_detected(self):
        """把扣子编程编辑器/预览页面地址当接口地址时，要说清哪里不对。"""
        os.environ["LANGGRAPH_BASE_URL"] = \
            "https://code.coze.cn/p/7689288574650433551/preview?link_share=true"
        with self.assertRaises(langgraph_client.LangGraphError) as cm:
            langgraph_client.run({"message": "x"})
        self.assertEqual(cm.exception.code, "not_api_url")
        self.assertIn("不是引擎的接口地址", cm.exception.message)

    def test_health_reports_clear_error_for_bad_url(self):
        os.environ["LANGGRAPH_BASE_URL"] = "not-a-url"
        h = langgraph_client.health()
        self.assertFalse(h["ok"])
        self.assertIn("bad_base_url", h["error"])

    def test_fallback_warning_names_the_problem(self):
        """线上事故回归：地址不合法时，降级告警必须点明原因与修复方向。"""
        os.environ["LANGGRAPH_BASE_URL"] = "not-a-url"
        res = analysis_service.prepare_analysis(
            "分析一下", self.user, {"scode": "002860", "year": 2023},
            runtime.get_preferences(self.user["user_id"]), [], {}, "t_lg_7")
        self.assertEqual(res["engine"], "rules-demo")
        joined = " ".join(res["analysis"]["warnings"])
        self.assertIn("LangGraph", joined)
        self.assertIn("http://", joined, "告警里应给出可执行的修复提示")
    def test_engine_status_reports_langgraph(self):
        st = analysis_service.engine_status()
        self.assertEqual(st["effective_engine"], "langgraph")
        self.assertTrue(st["langgraph_configured"])
        health = langgraph_client.health()
        self.assertTrue(health["ok"])

    def test_rules_demo_when_nothing_configured(self):
        os.environ.pop("LANGGRAPH_BASE_URL", None)
        os.environ.pop("AI_ENABLED", None)
        self.assertEqual(analysis_service.engine_status()["effective_engine"], "rules-demo")

    # ---- 6) 非正则措辞：必须交给 AI 引擎，而不是被本地规则引擎"接住" ----
    def test_non_regex_phrasing_still_reaches_engine(self):
        """回归：演示中的自然语言若不在本地正则覆盖内，也必须走引擎。

        local_engine.detect_intent 只认「比较/对比/哪个更/优先拜访谁/区别」，
        并不认识「相比」。若链路正确，这类问题仍应原样送进 AI 引擎并以其输出为准——
        否则"像自然语言"只是正则命中的假象。
        """
        from server import local_engine
        q = "上能电气和中信博相比，谁更适合先谈跨境资金池？为什么？"
        self.assertNotEqual(
            local_engine.detect_intent(q, {}, []), "compare",
            "该措辞本就不在本地正则覆盖内，正是需要 AI 引擎的场景")

        STATE["response"] = {"result": json.dumps(self._draft(), ensure_ascii=False)}
        res = analysis_service.prepare_analysis(
            q, self.user, {"year": 2023},
            runtime.get_preferences(self.user["user_id"]), [], {}, "t_lg_phrase")
        self.assertEqual(res["engine"], "langgraph")
        self.assertEqual(STATE["last_request"]["message"], q,
                         "原始问句必须原样传给引擎，不能被本地规则改写")

    # ---- 7) planned_engine 与尝试顺序一致（供 request_started 使用） ----
    def test_planned_engine_follows_configured_order(self):
        self.assertEqual(analysis_service.planned_engine(), "langgraph")
        os.environ.pop("LANGGRAPH_BASE_URL", None)
        os.environ.pop("AI_ENABLED", None)
        os.environ.pop("AI_ENGINE", None)
        self.assertEqual(analysis_service.planned_engine(), "rules-demo")
        self.assertEqual(analysis_service.engine_status()["planned_engine"], "rules-demo")

    # ---- 8) 探活必须能识别"实例被回收"（线上事故回归） ----
    def test_probe_detects_recycled_instance(self):
        STATE.update({"get_status": 404,
                      "get_body": '{"error_code":"instance_not_found",'
                                  '"error_message":"user specified instance xxx-sandbox not found"}'})
        p = langgraph_client.probe(timeout=5)
        self.assertFalse(p["reachable"], "实例被回收必须判为不可用，不能报绿")
        self.assertEqual(p["error_code"], "instance_gone")

    # ---- 9) 鉴权失败 ≠ 服务不可用 ----
    def test_probe_separates_auth_failure_from_down(self):
        STATE.update({"get_status": 401,
                      "get_body": '{"msg":"Missing authorization header."}'})
        p = langgraph_client.probe(timeout=5)
        self.assertTrue(p["reachable"], "鉴权失败说明服务活着，不应判为不可用")
        self.assertFalse(p["auth_ok"])
        self.assertEqual(p["error_code"], "unauthorized")

    # ---- 10) engine_status(probe=True) 暴露可用性，而非只看配置 ----
    def test_engine_status_probe_exposes_reachability(self):
        STATE.update({"get_status": 200, "get_body": '{"status":"ok"}'})
        st = analysis_service.engine_status(probe=True)
        self.assertEqual(st["effective_engine"], "langgraph")
        self.assertEqual(st["planned_engine"], "langgraph")
        self.assertTrue(st["reachable"])
        self.assertEqual(st["probed_engine"], "langgraph")
        # 实例被回收后，同一接口必须转为不可用
        STATE.update({"get_status": 404, "get_body": '{"error_code":"instance_not_found"}'})
        analysis_service.reset_engine_probe_cache()
        self.assertFalse(analysis_service.engine_status(probe=True)["reachable"])


if __name__ == "__main__":
    unittest.main()
