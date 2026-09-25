# -*- coding: utf-8 -*-
"""表格读取器 v1：CSV 表格校验与导入预览。

表格检查：企业代码（317 家样本内）、年度（2018-2023）、金额单位、
重复键、空值；缺少企业匹配的行保留待处理状态（方案 11.4 节）。
列约定（首版固定列名）：scode, year, amount, unit, note。
"""
import csv
import io


def validate(text: str) -> dict:
    issues, rows, seen_keys = [], [], set()
    reader = csv.DictReader(io.StringIO(text))
    if (not reader.fieldnames or "scode" not in reader.fieldnames
            or "year" not in reader.fieldnames):
        return {"total_rows": 0, "valid_rows": 0, "issues": [],
                "fatal": "表格必须包含 scode 与 year 列（首版字段映射固定为列名）",
                "preview": []}
    from .. import logic
    valid_scodes = set(logic._coname_map().keys())
    for i, row in enumerate(reader, start=2):
        scode = (row.get("scode") or "").strip()
        year = (row.get("year") or "").strip()
        if not scode:
            issues.append({"row": i, "field": "scode", "issue": "企业代码为空"})
            continue
        scode = scode.zfill(6)
        if scode not in valid_scodes:
            issues.append({"row": i, "field": "scode",
                           "issue": f"企业代码 {scode} 不在 317 家样本内，行保留待处理状态"})
            rows.append({"row": i, "status": "pending", "scode": scode, "year": year})
            continue
        if not year.isdigit() or not (2018 <= int(year) <= 2023):
            issues.append({"row": i, "field": "year",
                           "issue": f"年度 {year or '空'} 无效（样本年度 2018-2023）"})
            rows.append({"row": i, "status": "pending", "scode": scode, "year": year})
            continue
        key = (scode, int(year))
        if key in seen_keys:
            issues.append({"row": i, "field": "scode+year",
                           "issue": f"重复键 {scode}/{year}，保留待处理状态"})
            rows.append({"row": i, "status": "pending", "scode": scode, "year": year})
            continue
        seen_keys.add(key)
        for f in ("amount", "value"):
            v = row.get(f)
            if v is not None and v != "":
                try:
                    float(str(v).replace(",", ""))
                except ValueError:
                    issues.append({"row": i, "field": f,
                                   "issue": f"金额字段非数值：{v}（请检查单位）"})
        rows.append({"row": i, "status": "valid", "scode": scode, "year": year,
                     "payload": {k: row.get(k) for k in ("amount", "value", "unit", "note")
                                 if row.get(k)}})
    return {"total_rows": len(rows), "valid_rows": sum(1 for r in rows if r["status"] == "valid"),
            "issues": issues, "fatal": None, "preview": rows[:20]}
