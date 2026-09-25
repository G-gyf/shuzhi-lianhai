# -*- coding: utf-8 -*-
"""Coze 插件 OpenAPI 规格合规性测试。

复现并防止用户实际遇到的导入报错：
    API response schema must be json object/array

规则（Coze 插件解析器较保守）：
- 每个 operation 必须有 responses，且响应体声明 application/json 且 schema 顶层 type 为 object/array；
- 请求体必须是 object；
- 不使用 oneOf/anyOf/allOf 与字符串型响应体；
- operationId 唯一；servers.url 为 https；
- 规格中声明的工具名必须与 server/tools.py 注册表一致（防止代码与规格漂移）。

未安装 PyYAML 时跳过（本地验收环境已装：pyyaml 6.0.2）。
"""
import json
import unittest
from pathlib import Path

from server import tools

ROOT = Path(__file__).resolve().parent.parent
SPECS = [ROOT / "coze" / "tool_openapi.yaml", ROOT / "coze" / "tool_openapi.min.yaml"]

try:
    import yaml
    HAS_YAML = True
except ImportError:  # pragma: no cover
    HAS_YAML = False

FORBIDDEN_KEYS = ("oneOf", "anyOf", "allOf", "not")


def _load(path):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _walk(node, hits):
    if isinstance(node, dict):
        for k, v in node.items():
            if k in FORBIDDEN_KEYS:
                hits.append(k)
            _walk(v, hits)
    elif isinstance(node, list):
        for v in node:
            _walk(v, hits)


@unittest.skipUnless(HAS_YAML, "未安装 PyYAML，跳过 OpenAPI 规格校验")
class TestOpenApiSpec(unittest.TestCase):

    def test_specs_parse(self):
        for p in SPECS:
            self.assertTrue(p.exists(), f"缺少规格文件：{p.name}")
            spec = _load(p)
            self.assertEqual(spec["openapi"], "3.0.3")
            self.assertTrue(spec["paths"])

    def test_every_response_declares_json_object_or_array(self):
        """核心回归：响应体必须声明 application/json 且顶层为 object/array。"""
        for p in SPECS:
            spec = _load(p)
            for path, ops in spec["paths"].items():
                for method, op in ops.items():
                    if method not in ("get", "post", "put", "patch", "delete"):
                        continue
                    self.assertIn("responses", op, f"{p.name} {path} 缺少 responses")
                    for code, resp in op["responses"].items():
                        if not str(code).startswith("2"):
                            continue
                        self.assertIn("content", resp,
                                      f"{p.name} {path} {code} 响应缺少 content（Coze 报错原因）")
                        self.assertIn("application/json", resp["content"],
                                      f"{p.name} {path} {code} 响应缺少 application/json")
                        schema = resp["content"]["application/json"].get("schema")
                        self.assertIsInstance(schema, dict,
                                              f"{p.name} {path} {code} 响应缺少 schema")
                        self.assertIn(schema.get("type"), ("object", "array"),
                                      f"{p.name} {path} {code} 响应 schema 必须是 object/array")

    def test_request_bodies_are_objects(self):
        for p in SPECS:
            spec = _load(p)
            for path, ops in spec["paths"].items():
                for method, op in ops.items():
                    if method not in ("post", "put", "patch"):
                        continue
                    schema = op["requestBody"]["content"]["application/json"]["schema"]
                    self.assertEqual(schema.get("type"), "object",
                                     f"{p.name} {path} 请求体必须是 object")

    def test_no_composition_keywords(self):
        for p in SPECS:
            hits = []
            _walk(_load(p), hits)
            self.assertEqual(hits, [], f"{p.name} 使用了 Coze 不支持的组合关键字：{set(hits)}")

    def test_operation_ids_unique_and_https_server(self):
        for p in SPECS:
            spec = _load(p)
            ids = []
            for ops in spec["paths"].values():
                for method, op in ops.items():
                    if method in ("get", "post", "put", "patch", "delete"):
                        ids.append(op["operationId"])
            self.assertEqual(len(ids), len(set(ids)), f"{p.name} operationId 重复")
            for srv in spec["servers"]:
                self.assertTrue(srv["url"].startswith("https://"),
                                f"{p.name} server 必须是 https")

    def test_spec_tools_match_registry(self):
        """规格声明的工具与后端注册表一致（代码—规格漂移防护）。"""
        spec = _load(SPECS[0])
        declared = set()
        for path, ops in spec["paths"].items():
            for method, op in ops.items():
                if method in ("get", "post", "put", "patch", "delete"):
                    declared.add(op["operationId"])
        registry = set(tools.TOOL_REGISTRY)
        missing = registry - declared
        self.assertEqual(missing, set(),
                         f"工具注册表中有规格未声明的工具：{sorted(missing)}")
        extra = declared - registry - {"tools_dispatch"}
        self.assertEqual(extra, set(),
                         f"规格声明了后端未注册的工具：{sorted(extra)}")

    def test_dispatch_enum_matches_registry(self):
        spec = _load(SPECS[1])
        schema = spec["paths"]["/api/v1/tools/dispatch"]["post"]["requestBody"][
            "content"]["application/json"]["schema"]
        enum = set(schema["properties"]["tool"]["enum"])
        self.assertEqual(enum, set(tools.TOOL_REGISTRY),
                         "最小版 dispatch 的 tool 枚举与工具注册表不一致")


if __name__ == "__main__":
    unittest.main()
