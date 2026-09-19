# -*- coding: utf-8 -*-
"""Match SW-2021 industry codes to the 317-firm sample and profile the chain."""
import io
import sqlite3
import sys
from collections import Counter

import xlrd

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

XLS = r"C:\Users\lenovo\Desktop\工行杯\StockClassifyUse_stock.xls"
DB = r"C:\Users\lenovo\Desktop\工行杯\数智链海\kb\kb-2023.sqlite"

wb = xlrd.open_workbook(XLS)
sh = wb.sheet_by_index(0)
latest = {}
for r in range(1, sh.nrows):
    code = str(sh.cell_value(r, 0)).strip().split(".")[0].zfill(6)
    ind = str(sh.cell_value(r, 2)).strip()
    try:
        date = float(sh.cell_value(r, 1))
    except ValueError:
        date = 0.0
    if code not in latest or date > latest[code][0]:
        latest[code] = (date, ind)

# SW names (2021, 二级/三级常用口径)
SW2 = {
    "6101": "半导体", "6205": "消费电子", "6301": "电池", "6305": "光伏设备",
    "6307": "风电设备", "6309": "电网设备", "6401": "工程机械", "7101": "通用设备",
    "7201": "专用设备", "7301": "汽车零部件", "7305": "乘用车", "8201": "化学制品",
    "2301": "建材", "4501": "电力", "2801": "煤炭", "3101": "钢铁", "3201": "有色",
}
SW3_PV = {
    "630501": "硅料硅片", "630502": "光伏电池组件", "630503": "逆变器",
    "630504": "光伏辅材", "630505": "光伏加工设备",
}
SW3 = {
    "630601": "电池化学品", "630602": "锂电池", "630701": "风电整机", "630702": "风电零部件",
    "630901": "输变电设备", "630902": "配电设备", "630903": "电力自动化", "630904": "电工仪器仪表",
    "730101": "车身附件及饰件", "730102": "底盘与发动机系统", "730103": "轮胎轮毂", "730104": "其他汽车零部件",
}

con = sqlite3.connect(DB)
sample = {c for (c,) in con.execute("SELECT DISTINCT scode FROM chunks").fetchall()}

def sw_of(scode):
    if scode not in latest:
        return None, None
    _, ind = latest[scode]
    l2 = ind[:4] if len(ind) >= 4 else ind
    l3 = ind[:6] if len(ind) >= 6 else ind
    return l2, l3

l2_counter = Counter()
l3_counter = Counter()
pv_l3 = Counter()
mapped, unmapped = 0, []
for c in sorted(sample):
    l2, l3 = sw_of(c)
    if l2 is None:
        unmapped.append(c)
        continue
    mapped += 1
    l2_counter[l2] += 1
    l3_counter[l3] += 1
    if l2 == "6305":
        pv_l3[l3] += 1

print(f"样本 317 家 / 申万匹配 {mapped} 家 / 未匹配 {len(unmapped)} 家: {unmapped}")
print()
print("=== 样本内申万二级行业分布（top20） ===")
for ind, n in l2_counter.most_common(20):
    name = SW2.get(ind, "")
    print(f"  {ind} {name}: {n} 家")
print()
print("=== 光伏 6305 三级环节分布（37家双标签） ===")
for ind, n in sorted(pv_l3.items()):
    name = SW3_PV.get(ind, ind)
    print(f"  {ind} {name}: {n} 家")
print()
print("=== 样本内其他申万三级（top15，光伏除外） ===")
for ind, n in l3_counter.most_common(15):
    if ind.startswith("6305"):
        continue
    name = SW3.get(ind, "")
    print(f"  {ind} {name}: {n} 家")
