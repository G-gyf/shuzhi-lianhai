# -*- coding: utf-8 -*-
"""文档集合读取器 v1：JSON 文档集合校验与预览。

输入结构：{"documents": [{"doc_id","title","body","locator","effective_from"}]}
文档检查：标题、来源、日期及可见范围（方案 11.4 节）。
"""
import json


def validate(text: str) -> dict:
    try:
        data = json.loads(text)
    except ValueError as e:
        return {"total_rows": 0, "valid_rows": 0, "issues": [],
                "fatal": f"JSON 解析失败：{e}", "preview": []}
    docs = data.get("documents", [])
    if not isinstance(docs, list):
        return {"total_rows": 0, "valid_rows": 0, "issues": [],
                "fatal": "缺少 documents 数组", "preview": []}
    issues, preview = [], []
    for i, d in enumerate(docs, start=1):
        if not d.get("doc_id"):
            issues.append({"row": i, "field": "doc_id", "issue": "缺少 doc_id"})
        if not d.get("title"):
            issues.append({"row": i, "field": "title", "issue": "缺少标题"})
        if not d.get("body"):
            issues.append({"row": i, "field": "body", "issue": "正文为空"})
        if not d.get("effective_from"):
            issues.append({"row": i, "field": "effective_from", "issue": "缺少资料日期"})
        ok_row = all(d.get(k) for k in ("doc_id", "title", "body"))
        preview.append({"doc_id": d.get("doc_id"), "title": d.get("title"),
                        "effective_from": d.get("effective_from"),
                        "status": "valid" if ok_row else "pending"})
    return {"total_rows": len(docs),
            "valid_rows": sum(1 for p in preview if p["status"] == "valid"),
            "issues": issues, "fatal": None, "preview": preview[:20]}
