# -*- coding: utf-8 -*-
"""Compute chain-segment overseas demand profile + export scode->segment map."""
import io
import json
import sqlite3
import sys
from collections import Counter, defaultdict

import xlrd

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

XLS = r"C:\Users\lenovo\Desktop\工行杯\StockClassifyUse_stock.xls"
DB = r"C:\Users\lenovo\Desktop\工行杯\数智链海\kb\kb-2023.sqlite"
CHAIN = json.load(open(r"C:\Users\lenovo\Desktop\工行杯\数智链海\rules\chain_map.json",
                        encoding="utf-8"))
MAP_OUT = r"C:\Users\lenovo\Desktop\工行杯\数智链海\rules\segment_map.json"

# --- sw latest codes ---
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


def segment_of(scode):
    if scode not in latest:
        return "其他"
    _, ind = latest[scode]
    l2 = ind[:4]
    for seg, cfg in CHAIN["segments"].items():
        if l2 in cfg["sw2"]:
            return seg
    return "其他"


def pv_stage_of(scode):
    if scode not in latest:
        return None
    _, ind = latest[scode]
    return CHAIN["pv_stage"].get(ind[:6])


con = sqlite3.connect(DB)
sample = {c for (c,) in con.execute("SELECT DISTINCT scode FROM chunks").fetchall()}
dem = {}
for scode, year, label, direction in con.execute(
        "SELECT scode, year, program_label, direction FROM claims "
        "WHERE program_label IN ('经营部署','战略意图')"):
    dem.setdefault(scode, []).append((year, label, direction))

print(f"{'环节':<10} {'企业数':>5} {'有需求企业':>7} {'需求占比':>7} {'部署条':>5} {'意图条':>5} {'主要方向'}")
print("-" * 80)
seg_stats = defaultdict(lambda: {"firms": set(), "dem_firms": set(),
                                 "deploy": 0, "intent": 0, "dirs": Counter(),
                                 "countries": Counter()})
for c in sorted(sample):
    seg = segment_of(c)
    seg_stats[seg]["firms"].add(c)
    if c in dem:
        seg_stats[seg]["dem_firms"].add(c)
        for _, label, direction in dem[c]:
            seg_stats[seg]["deploy" if label == "经营部署" else "intent"] += 1
            if direction and direction != "null":
                seg_stats[seg]["dirs"][direction] += 1

for seg, st in sorted(seg_stats.items(),
                      key=lambda kv: -len(kv[1]["dem_firms"])):
    n = len(st["firms"])
    nd = len(st["dem_firms"])
    top_dir = st["dirs"].most_common(1)[0][0] if st["dirs"] else "—"
    print(f"{seg:<10} {n:>5} {nd:>7} {nd/max(n,1):>7.0%} {st['deploy']:>5} {st['intent']:>5} {top_dir}")

print()
print("=== 光伏 37 家的环节内分布 ===")
pv_stage = Counter(pv_stage_of(c) for c in sample
                   if segment_of(c) == "光伏主链")
for k, v in sorted(pv_stage.items(), key=lambda kv: -kv[1]):
    print(f"  {k}: {v} 家")

# --- export scode -> segment map (server 侧零依赖读取) ---
seg_map = {}
for c in sorted(sample):
    seg = segment_of(c)
    stage = pv_stage_of(c)
    seg_map[c] = {"segment": seg, "pv_stage": stage,
                  "sw": latest.get(c, (0, ""))[1]}
with open(MAP_OUT, "w", encoding="utf-8") as f:
    json.dump(seg_map, f, ensure_ascii=False, indent=1)
print()
print(f"exported segment_map: {len(seg_map)} firms -> {MAP_OUT}")
