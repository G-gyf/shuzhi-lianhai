# -*- coding: utf-8 -*-
"""工具 HTTP 接口验收：三种传参形态、dispatch、鉴权与快照保护（方案 5.2 节）。"""
import json
import os
import unittest

from fastapi.testclient import TestClient

from server import context_token, runtime
from server.main import app


class TestToolApi(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        runtime.init_runtime()

    def setUp(self):
        self.client = TestClient(app)
        self.client.__enter__()
        self.secret = "test-secret-tool-api"
        self._old = os.environ.get("TOOL_CONTEXT_SECRET")
        os.environ["TOOL_CONTEXT_SECRET"] = self.secret
        self.snap = runtime.get_snapshot()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        if self._old is None:
            os.environ.pop("TOOL_CONTEXT_SECRET", None)
        else:
            os.environ["TOOL_CONTEXT_SECRET"] = self._old

    def _token(self, tools_allowed=None, snapshot=None):
        return context_token.sign_context_token(
            {"user_id": "u_demo_a", "display_name": "演示经理", "regions": ["region_a"],
             "snapshot_id": snapshot or self.snap,
             "allowed_tools": tools_allowed}, self.secret, 300)

    def _post(self, path, payload, token):
        return self.client.post(path, json=payload,
                                headers={"X-Context-Token": token})

    def test_flat_params(self):
        """扁平传参（Coze 插件默认形态）。"""
        r = self._post("/api/v1/tools/get_company_context",
                       {"scode": "002860", "year": 2023},
                       self._token(["get_company_context"]))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["coname"], "星帅尔")
        self.assertEqual(r.json()["year"], 2023)

    def test_nested_params(self):
        """嵌套 parameters 形态（向后兼容）。"""
        r = self._post("/api/v1/tools/resolve_company",
                       {"parameters": {"query": "002860"}},
                       self._token(["resolve_company"]))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["matches"][0]["coname"], "星帅尔")

    def test_dispatch_with_parameters_json(self):
        """统一分发 + JSON 字符串传参（最小可导入版插件的形态）。"""
        r = self._post("/api/v1/tools/dispatch",
                       {"tool": "get_company_context",
                        "parameters_json": json.dumps({"scode": "002860", "year": 2023})},
                       self._token(["get_company_context"]))
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["tool"], "get_company_context")
        self.assertEqual(body["result"]["coname"], "星帅尔")

    def test_dispatch_with_object_params(self):
        r = self._post("/api/v1/tools/dispatch",
                       {"tool": "search_companies", "parameters": {"province": "江苏省",
                                                                   "page_size": 3}},
                       self._token(["search_companies"]))
        self.assertEqual(r.status_code, 200)
        self.assertGreater(r.json()["result"]["total"], 0)

    def test_dispatch_bad_tool(self):
        r = self._post("/api/v1/tools/dispatch", {"tool": "drop_tables"},
                       self._token(["get_company_context"]))
        self.assertEqual(r.status_code, 400)

    def test_dispatch_bad_json_string(self):
        r = self._post("/api/v1/tools/dispatch",
                       {"tool": "get_company_context", "parameters_json": "{not json}"},
                       self._token(["get_company_context"]))
        self.assertEqual(r.status_code, 400)

    def test_dispatch_bare_value_hint(self):
        """把单个值（如企业代码）填进 parameters_json 时，提示要给出正确示例。"""
        r = self._post("/api/v1/tools/dispatch",
                       {"tool": "get_company_context", "parameters_json": "002860"},
                       self._token(["get_company_context"]))
        self.assertEqual(r.status_code, 400)
        detail = r.json()["detail"]
        self.assertIn("scode", detail)
        self.assertIn("002860", detail)

    def test_tool_not_in_allow_list(self):
        """token 的 allowed_tools 收窄：越权工具 403。"""
        r = self._post("/api/v1/tools/compare_companies",
                       {"scodes": ["002860", "300670"], "year": 2023},
                       self._token(["get_company_context"]))
        self.assertEqual(r.status_code, 403)

    def test_forged_token_rejected(self):
        r = self._post("/api/v1/tools/resolve_company", {"query": "002860"}, "forged.tok")
        self.assertEqual(r.status_code, 403)

    def test_snapshot_drift_rejected(self):
        r = self._post("/api/v1/tools/resolve_company", {"query": "002860"},
                       self._token(["resolve_company"], snapshot="kb-2023@deadbeef0000"))
        self.assertEqual(r.status_code, 409)

    def test_missing_secret_returns_503(self):
        os.environ.pop("TOOL_CONTEXT_SECRET", None)
        r = self._post("/api/v1/tools/resolve_company", {"query": "002860"}, "any.tok")
        self.assertEqual(r.status_code, 503)

    def test_static_debug_token_off_by_default(self):
        """默认关闭静态调试密钥：把密钥本身当 token 用必须 403，且提示如何开启。"""
        os.environ.pop("ALLOW_STATIC_DEBUG_TOKEN", None)
        r = self._post("/api/v1/tools/resolve_company", {"query": "002860"}, self.secret)
        self.assertEqual(r.status_code, 403)
        self.assertIn("ALLOW_STATIC_DEBUG_TOKEN", r.json()["detail"])

    def test_403_message_contains_troubleshooting(self):
        """错误提示要能自解释（用户不再需要猜缺哪一步）。"""
        os.environ.pop("ALLOW_STATIC_DEBUG_TOKEN", None)
        r = self._post("/api/v1/tools/resolve_company", {"query": "002860"}, "wrong-value")
        self.assertEqual(r.status_code, 403)
        detail = r.json()["detail"]
        self.assertIn("TOOL_CONTEXT_SECRET", detail)
        self.assertIn("ALLOW_STATIC_DEBUG_TOKEN", detail)

    def test_503_message_guides_setup(self):
        os.environ.pop("TOOL_CONTEXT_SECRET", None)
        r = self._post("/api/v1/tools/resolve_company", {"query": "002860"}, "any")
        self.assertEqual(r.status_code, 503)
        self.assertIn("TOOL_CONTEXT_SECRET", r.json()["detail"])

    # ---- Coze 试运行面板的实际传参形态（截图暴露的三个坑） ----

    def test_token_in_body_accepted(self):
        """Coze 试运行把 Header 参数放进 JSON 体时也要能通过。"""
        os.environ["ALLOW_STATIC_DEBUG_TOKEN"] = "1"
        try:
            r = self.client.post("/api/v1/tools/resolve_company",
                                 json={"X-Context-Token": self.secret, "query": "002860"})
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.json()["matches"][0]["coname"], "星帅尔")
        finally:
            os.environ.pop("ALLOW_STATIC_DEBUG_TOKEN", None)

    def test_empty_body_tolerated(self):
        """无必填参数的工具（Coze 可能不发 body）不能报错。"""
        os.environ["ALLOW_STATIC_DEBUG_TOKEN"] = "1"
        try:
            r = self.client.post("/api/v1/tools/search_product_knowledge",
                                 headers={"X-Context-Token": self.secret})
            self.assertEqual(r.status_code, 200)
            self.assertTrue(r.json()["ok"])
        finally:
            os.environ.pop("ALLOW_STATIC_DEBUG_TOKEN", None)

    def test_unknown_body_keys_ignored_not_fatal(self):
        """请求体里多出的键（如被塞进 body 的 header）不应导致工具调用失败。"""
        os.environ["ALLOW_STATIC_DEBUG_TOKEN"] = "1"
        try:
            r = self.client.post("/api/v1/tools/resolve_company",
                                 json={"X-Context-Token": self.secret,
                                       "query": "002860",
                                       "headers": {"foo": "bar"}})
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.json()["matches"][0]["coname"], "星帅尔")
            self.assertIn("headers", r.json()["ignored_params"])
        finally:
            os.environ.pop("ALLOW_STATIC_DEBUG_TOKEN", None)

    def test_static_debug_token_when_enabled(self):
        """打开 ALLOW_STATIC_DEBUG_TOKEN=1 后，密钥本身即可作为试跑 token。"""
        os.environ["ALLOW_STATIC_DEBUG_TOKEN"] = "1"
        try:
            r = self._post("/api/v1/tools/resolve_company", {"query": "002860"}, self.secret)
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.json()["matches"][0]["coname"], "星帅尔")
            # 错误值仍被拒
            r2 = self._post("/api/v1/tools/resolve_company", {"query": "002860"}, "wrong")
            self.assertEqual(r2.status_code, 403)
            # 调试模式下工具全放行（含地区资料检索）
            r3 = self._post("/api/v1/tools/search_regional_knowledge", {"query": "结算"},
                            self.secret)
            self.assertEqual(r3.status_code, 200)
        finally:
            os.environ.pop("ALLOW_STATIC_DEBUG_TOKEN", None)


if __name__ == "__main__":
    unittest.main()
