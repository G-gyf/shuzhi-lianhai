# -*- coding: utf-8 -*-
"""Match SW-2021 PV (630500) constituents against existing 317-firm sample."""
import io
import sys
import sqlite3

import xlrd

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

XLS = r"C:\Users\lenovo\Desktop\工行杯\StockClassifyUse_stock.xls"
DB = r"C:\Users\lenovo\Desktop\工行杯\数智链海\kb\kb-2023.sqlite"

wb = xlrd.open_workbook(XLS)
sh = wb.sheet_by_index(0)
rows = []
for r in range(1, sh.nrows):
    code = str(sh.cell_value(r, 0)).strip().split(".")[0].zfill(6)
    ind = str(sh.cell_value(r, 2)).strip()
    try:
        date = float(sh.cell_value(r, 1))
    except ValueError:
        date = 0.0
    rows.append((code, ind, date))

# keep latest record per stock (max 计入日期)
latest = {}
for code, ind, date in rows:
    if code not in latest or date > latest[code][1]:
        latest[code] = (ind, date)

pv = {c for c, (i, _) in latest.items() if i.startswith("6305")}
print("申万 6305xx（光伏设备二级）成分数:", len(pv))

con = sqlite3.connect(DB)
sample = {c for (c,) in con.execute("SELECT DISTINCT scode FROM chunks").fetchall()}
overlap = sorted(pv & sample)
new = sorted(pv - sample)
print(f"与 317 家样本重叠（已标注，打双标签即可）: {len(overlap)}")
print(f"增量（需新采年报补标）: {len(new)}")
print()
print("=== 重叠清单 ===")
for c in overlap:
    name = con.execute("SELECT coname FROM chunks WHERE scode=? LIMIT 1", (c,)).fetchone()
    print(" ", c, name[0] if name else "")
print()
print("=== 增量清单 ===")
for c in new:
    print(" ", c)

# 顺带看 630500 二级下的三级构成
sub = {}
for c, (i, _) in latest.items():
    if i.startswith("6305"):
        sub[i] = sub.get(i, 0) + 1
print()
print("6305xx 三级构成:", sub)
