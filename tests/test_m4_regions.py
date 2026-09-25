# -*- coding: utf-8 -*-
"""M4 验收：偏好、地区资料隔离、数据源生命周期、导入预览（方案 11 章、15.1 用例 12/13/14）。"""
import json
import unittest

from fastapi.testclient import TestClient

from server import extensions, runtime
from server.main import app

A = {"Authorization": "Bearer demo-token-region-a"}
B = {"Authorization": "Bearer demo-token-region-b"}


class TestM4Regions(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        runtime.init_runtime()
        extensions._seed()

    def setUp(self):
        self.client = TestClient(app)
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        extensions._seed()  # 复位演示源状态

    def _purge_source(self, source_id):
        con = runtime.get_conn()
        con.execute("DELETE FROM source_documents WHERE source_id=?", (source_id,))
        con.execute("DELETE FROM import_jobs WHERE source_id=?", (source_id,))
        con.execute("DELETE FROM data_sources WHERE source_id=?", (source_id,))
        con.commit()

    def test_preferences_roundtrip(self):
        r = self.client.get("/api/v1/me/preferences", headers=A)
        self.assertEqual(r.status_code, 200)
        prefs = r.json()["preferences"]
        r2 = self.client.patch("/api/v1/me/preferences",
                               json={"service_focus": ["settlement"],
                                     "exclude_financing": True}, headers=A)
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r2.json()["preferences"]["service_focus"], ["settlement"])
        self.assertTrue(r2.json()["preferences"]["exclude_financing"])

    def test_region_a_can_read_demo_source(self):
        """验收用例 12：地区A的资料可检索并打开。"""
        ua = runtime.authenticate("Bearer demo-token-region-a")
        r = extensions.search_regional("结算", ua["user_id"], ua["regions"])
        self.assertGreater(r["total"], 0)
        first = r["snippets"][0]
        detail = extensions.read_regional_doc(first["source_id"], first["doc_id"],
                                              ua["regions"])
        self.assertTrue(detail["ok"])

    def test_region_b_cannot_search_or_read(self):
        """验收用例 12：地区B不能检索或直接按ID打开A区资料。"""
        ub = runtime.authenticate("Bearer demo-token-region-b")
        r = extensions.search_regional("结算", ub["user_id"], ub["regions"])
        self.assertEqual(r["total"], 0)
        detail = extensions.read_regional_doc("region_demo_service_notes",
                                              "doc_a_001", ub["regions"])
        self.assertFalse(detail["ok"])
        self.assertEqual(detail["code"], "forbidden")
        # HTTP 通道同样隔离
        resp = self.client.get("/api/v1/references/regional%3Aregion_demo_service_notes%3Adoc_a_001",
                               headers=B)
        self.assertEqual(resp.status_code, 403)

    def test_disable_source_stops_new_requests(self):
        """验收用例 13：停用资料源后，新请求不能继续引用。"""
        r = self.client.post("/api/v1/data-sources/region_demo_service_notes/disable", headers=A)
        self.assertEqual(r.status_code, 200)
        ua = runtime.authenticate("Bearer demo-token-region-a")
        r2 = extensions.search_regional("结算", ua["user_id"], ua["regions"])
        self.assertEqual(r2["total"], 0)
        detail = extensions.read_regional_doc("region_demo_service_notes",
                                              "doc_a_001", ua["regions"])
        self.assertFalse(detail["ok"])

    def test_source_region_must_belong_to_manager(self):
        """登记数据源：region_id 以服务器权限校验后的值为准。"""
        body = {"source_id": "test_src_bad_region", "name": "越权资料",
                "scope": "region", "region_id": "region_b",
                "kind": "document_collection", "adapter_id": "document_reader_v1"}
        r = self.client.post("/api/v1/data-sources", json=body, headers=A)
        self.assertEqual(r.status_code, 400)

    def test_source_lifecycle_validate_activate(self):
        """登记→上传→质量检查→预览→激活（验收用例 14）。"""
        self._purge_source("test_src_a")
        body = {"source_id": "test_src_a", "name": "A区测试资料",
                "scope": "region", "region_id": "region_a",
                "kind": "document_collection", "adapter_id": "document_reader_v1"}
        r = self.client.post("/api/v1/data-sources", json=body, headers=A)
        self.assertEqual(r.status_code, 200)
        doc = {"documents": [{"doc_id": "t1", "title": "测试资料",
                              "body": "结算服务补充说明（合成）",
                              "effective_from": "2026-09-01"}]}
        r = self.client.post("/api/v1/data-sources/test_src_a/validate",
                             json=doc, headers=A)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["valid_rows"], 1)
        r = self.client.post("/api/v1/data-sources/test_src_a/activate", headers=A)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["status"], "active")

    def test_table_import_issues(self):
        """上传含无效企业代码/年度的数据，能预览错误并阻止错误绑定。"""
        self._purge_source("test_src_table")
        body = {"source_id": "test_src_table", "name": "A区表格",
                "scope": "region", "region_id": "region_a", "kind": "table",
                "adapter_id": "table_reader_v1"}
        r = self.client.post("/api/v1/data-sources", json=body, headers=A)
        self.assertEqual(r.status_code, 200)
        csv_text = ("scode,year,amount,unit,note\n"
                    "002860,2023,100,万元,ok\n"
                    "999999,2023,50,万元,invalid-code\n"
                    "002860,2050,30,万元,invalid-year\n"
                    "300670,2023,abc,万元,not-number\n"
                    "300670,2023,70,万元,dup-key\n")
        r = self.client.post("/api/v1/data-sources/test_src_table/validate",
                             content=csv_text.encode("utf-8"),
                             headers={**A, "Content-Type": "text/csv"})
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data["valid_rows"], 2)
        issues = data["issues"]
        self.assertTrue(any("不在 317 家样本" in i["issue"] for i in issues))
        self.assertTrue(any("无效" in i["issue"] for i in issues))
        self.assertTrue(any("非数值" in i["issue"] for i in issues))
        self.assertTrue(any("重复键" in i["issue"] for i in issues))

    def test_extension_catalog_and_binding(self):
        r = self.client.get("/api/v1/extensions", headers=A)
        self.assertEqual(r.status_code, 200)
        ext = next((e for e in r.json()["extensions"]
                    if e["extension_id"] == "region_document_search"), None)
        self.assertIsNotNone(ext)
        self.assertTrue(ext["enabled_for_me"])
        # B 区未启用
        r2 = self.client.get("/api/v1/extensions", headers=B)
        ext_b = next((e for e in r2.json()["extensions"]
                      if e["extension_id"] == "region_document_search"), None)
        self.assertFalse(ext_b["enabled_for_me"])


if __name__ == "__main__":
    unittest.main()
