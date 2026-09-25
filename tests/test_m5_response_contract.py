# -*- coding: utf-8 -*-
"""响应类型契约测试：工具返回值必须符合 Coze 插件规格声明的类型。

背景（真实事故）：
    Coze 插件会按 OpenAPI 规格逐字段校验响应。规格把 `panel.firm_age` 声明为 integer，
    而工具实际返回 20.0（浮点）→ 试运行报
        [Root Item].panel. param firm_age is not Integer
    本测试用同一份规格反向校验所有工具的响应，防止此类"规格—实现"漂移再次发生。

约定（与 server/tools.py::prune_nulls 一致）：
    - 声明了具体类型的字段，缺失时**不出现**（而不是出现 null）；
    - 缺失信息由随附的 missing / coverage 字段表达，不把缺失解释为 0。
"""
import unittest
from pathlib import Path

from server import runtime, tools

ROOT = Path(__file__).resolve().parent.parent
SPEC = ROOT / "coze" / "tool_openapi.yaml"

try:
    import yaml
    HAS_YAML = True
except ImportError:  # pragma: no cover
    HAS_YAML = False


def _type_errors(value, schema, path, out):
    """按 schema 递归检查 value 的类型（只校验已声明的字段）。"""
    if not isinstance(schema, dict):
        return
    t = schema.get("type")
    if t == "object":
        if not isinstance(value, dict):
            out.append(f"{path}: 期望 object，实际 {type(value).__name__}")
            return
        props = schema.get("properties") or {}
        for key in schema.get("required") or []:
            if key not in value:
                out.append(f"{path}.{key}: required 字段缺失")
        for k, v in value.items():
            if k in props:
                _type_errors(v, props[k], f"{path}.{k}", out)
    elif t == "array":
        if not isinstance(value, list):
            out.append(f"{path}: 期望 array，实际 {type(value).__name__}")
            return
        for i, item in enumerate(value[:5]):
            _type_errors(item, schema.get("items") or {}, f"{path}[{i}]", out)
    elif t == "string":
        if not isinstance(value, str):
            out.append(f"{path}: 期望 string，实际 {type(value).__name__}（{value!r}）")
    elif t == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            out.append(f"{path}: 期望 integer，实际 {type(value).__name__}（{value!r}）")
    elif t == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            out.append(f"{path}: 期望 number，实际 {type(value).__name__}（{value!r}）")
    elif t == "boolean":
        if not isinstance(value, bool):
            out.append(f"{path}: 期望 boolean，实际 {type(value).__name__}（{value!r}）")


@unittest.skipUnless(HAS_YAML, "未安装 PyYAML，跳过响应契约校验")
class TestResponseContract(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        runtime.init_runtime()
        with open(SPEC, encoding="utf-8") as f:
            cls.spec = yaml.safe_load(f)
        cls.ctx = tools.build_context(
            runtime.authenticate("Bearer demo-token-region-a"))
        # 先取一个真实 evidence_ref，供 get_evidence 使用
        pkg = tools.call_tool("get_company_context", cls.ctx,
                              {"scode": "002860", "year": 2023})
        cls.ev_ref = (pkg.get("signal_refs") or [{}])[0].get("evidence_ref", "")

    # 工具 → 代表参数（覆盖"数据齐全"与"数据缺失"两类输入）
    CASES = [
        ("resolve_company", {"query": "002860"}),
        ("resolve_company", {"query": "不存在的企业名"}),
        ("search_companies", {"province": "江苏省", "page_size": 3}),
        ("search_companies", {"province": "不存在的省", "page_size": 3}),
        ("get_company_context", {"scode": "002860", "year": 2023}),
        ("get_company_context", {"scode": "002860", "year": 2000}),   # 无该年度数据
        ("compare_companies", {"scodes": ["002860", "300670"], "year": 2023}),
        ("compare_companies", {"scodes": ["002860", "300670"], "year": 2019}),
        ("get_rule_candidates", {"scode": "002860", "year": 2023}),
        ("get_rule_candidates", {"scode": "002860", "year": 2000}),   # 无候选
        ("search_product_knowledge", {"service_focus": ["settlement"]}),
        ("search_product_knowledge", {}),
        ("search_regional_knowledge", {"query": "结算"}),
        ("search_regional_knowledge", {}),
        ("get_evidence", None),      # 运行时填充真实 ref
        ("tools_dispatch", None),    # 单独走 HTTP 层，见 test_m5_tool_api
    ]

    def _schema_for(self, tool_name):
        for path, ops in self.spec["paths"].items():
            for method, op in ops.items():
                if method == "post" and op.get("operationId") == tool_name:
                    return op["responses"]["200"]["content"]["application/json"]["schema"]
        return None

    def test_all_tool_responses_match_declared_types(self):
        failures = []
        for tool_name, params in self.CASES:
            if tool_name == "tools_dispatch":
                continue
            if tool_name == "get_evidence":
                if not self.ev_ref:
                    continue
                params = {"evidence_ref": self.ev_ref}
            schema = self._schema_for(tool_name)
            if schema is None:
                failures.append(f"{tool_name}: 规格中找不到 operation")
                continue
            result = tools.call_tool(tool_name, self.ctx, params)
            errors = []
            _type_errors(result, schema, f"{tool_name}{params}", errors)
            if errors:
                failures.extend(errors)
        self.assertEqual(failures, [], "响应类型与规格不符：\n" + "\n".join(failures))

    def test_missing_values_are_omitted_not_null(self):
        """缺失值必须以"键不存在"表达（null 会被 Coze 判为类型不符）。"""
        # 不指定 year → requested_year 为 None，应被裁剪
        r = tools.call_tool("get_company_context", self.ctx, {"scode": "002860"})
        self.assertTrue(r["ok"])
        self.assertNotIn("requested_year", r, "None 值应被裁剪，而不是输出 null")
        # 指定无数据年度 → 面板缺失，window 为空对象而非 null
        r2 = tools.call_tool("get_company_context", self.ctx,
                             {"scode": "002860", "year": 2000})
        self.assertEqual(r2["window"], {}, "无窗口时应为空对象，而非 null")
        for k, v in r2["panel"].items():
            self.assertIsNotNone(v, f"panel.{k} 不应为 null")
        self.assertIn(r2["panel"]["status"], ("full", "text_only"))
        self.assertTrue(r2["panel"]["missing"], "缺失字段应列在 missing 中")

    def test_firm_age_is_integer(self):
        """回归：firm_age 曾以浮点返回，被 Coze 判为 is not Integer。"""
        r = tools.call_tool("get_company_context", self.ctx,
                            {"scode": "002860", "year": 2023})
        if "firm_age" in r["panel"]:
            self.assertIsInstance(r["panel"]["firm_age"], int)
            self.assertNotIsInstance(r["panel"]["firm_age"], bool)

    def test_prune_nulls_helper(self):
        data = {"a": 1, "b": None, "c": {"d": None, "e": [1, None, {"f": None}]}}
        self.assertEqual(tools.prune_nulls(data), {"a": 1, "c": {"e": [1, {}]}})

if __name__ == "__main__":
    unittest.main()
