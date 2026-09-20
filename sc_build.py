# -*- coding: utf-8 -*-
"""构建供应链快照 kb-sc-2023.sqlite（CSMAR 供应链系列表，317 家样本 2018-2023）。

来源：<workspace>/供应链相关数据/CSMAR
表：
  top5_sale     前五大客户销售信息（合并报表，rank 1-5 与合计 6）
  top5_purchase 前五大供应商采购信息
  concentration 供应链集中度
  distance      供应链地理距离
  network       供应链网络关系（A→B→C 二跳）
口径：
  - 仅保留 317 家样本（rules/segment_map.json 的 scode），年度 2018-2023，合并报表
  - scode 归一：从 Symbol 中取样本内 6 位代码（兼容 "000725;200725" 多代码格式）
  - 比例/集中度字段均为百分比数值
"""
import io
import json
import re
import sqlite3
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
import pandas as pd

ROOT = Path(__file__).resolve().parent
SC_DIR = ROOT.parent / "供应链相关数据" / "CSMAR"
KB_DIR = ROOT / "kb"
DB = KB_DIR / "kb-sc-2023.sqlite"

SAMPLE = set(json.loads((ROOT / "rules" / "segment_map.json").read_text(encoding="utf-8")).keys())
YEARS = (2018, 2023)

SALE_COLS = ["Symbol", "EndDate", "StateTypeCode", "Rank", "InstitutionName",
             "IsListed", "BusinessSymbol", "IsRelatedCompany", "SalesAmount",
             "ProportionOfTotalValue", "CurrencyCode"]
PUR_COLS = ["Symbol", "EndDate", "StateTypeCode", "Rank", "InstitutionName",
            "IsListed", "BusinessSymbol", "IsRelatedCompany", "PurchaseAmount",
            "ProportionOfTotalValue", "CurrencyCode"]
CONC_COLS = ["Symbol", "EndDate", "StateTypeCode", "TopSalesAmount",
             "TopFiveSalesAmount", "TopPurchaseAmount", "TopFivePurchaseAmount",
             "GrossRevenue", "TopCustomerToTotalRatio", "TopPurchaseToTotalRatio",
             "CustomerConcentration", "PurchaseConcentration",
             "CustomerConcentrationHHI", "PurchaseConcentrationHHI",
             "SupplyChainConcentration"]
DIST_COLS = ["Symbol", "EndDate", "StateTypeCode", "BusinessRelations", "Rank",
             "InstitutionName", "GgrphclPrxmtySigns", "SpatialDistance",
             "Distance", "IsSameProvince", "IsSameCity"]
NET_COLS = ["Symbol", "EndDate", "StateTypeCode", "PSCBusinessRelation",
            "PSCSymbol", "SSCBusinessRelation", "SSCSymbol"]

# 表名 → CSMAR 中文文件夹名
DIR_MAP = {
    "SC_TopFiveSaleInfo": "前五大客户销售信息表",
    "SC_TopFivePurchaseInfo": "前五大供应商采购信息表",
    "SC_ConcentrationIndex": "供应链集中度指标表",
    "SC_GgrphclDistanceIndex": "供应链地理距离指标表",
    "SC_NetworkRelationsIndex": "供应链网络关系指标表",
}


def load_dta(name, cols):
    folder = DIR_MAP[name]
    df = pd.read_stata(SC_DIR / folder / f"{name}.dta", columns=cols)
    df["Symbol"] = df["Symbol"].astype(str).str.strip()
    df["year"] = df["EndDate"].astype(str).str[:4].astype(int)
    df = df[(df["year"] >= YEARS[0]) & (df["year"] <= YEARS[1])]
    df = df[df["StateTypeCode"].astype(float).astype(int) == 1]
    return df


def norm_scode(sym):
    """Symbol → 样本内 scode（支持 "000725;200725" 多代码）。"""
    for m in re.findall(r"\d{6}", str(sym)):
        if m in SAMPLE:
            return m
    return None


def apply_sample(df):
    df = df.copy()
    df["scode"] = df["Symbol"].map(norm_scode)
    df = df[df["scode"].notna()]
    return df


def main():
    print("[1/5] 前五大客户销售信息 ...")
    sale = apply_sample(load_dta("SC_TopFiveSaleInfo", SALE_COLS))
    sale = sale.rename(columns={"InstitutionName": "name", "SalesAmount": "amount",
                                "ProportionOfTotalValue": "proportion",
                                "IsListed": "is_listed", "BusinessSymbol": "biz_symbol",
                                "IsRelatedCompany": "is_related",
                                "CurrencyCode": "currency", "Rank": "rank"})
    sale = sale[["scode", "year", "rank", "name", "is_listed", "biz_symbol",
                 "is_related", "amount", "proportion", "currency"]]

    print("[2/5] 前五大供应商采购信息 ...")
    pur = apply_sample(load_dta("SC_TopFivePurchaseInfo", PUR_COLS))
    pur = pur.rename(columns={"InstitutionName": "name", "PurchaseAmount": "amount",
                              "ProportionOfTotalValue": "proportion",
                              "IsListed": "is_listed", "BusinessSymbol": "biz_symbol",
                              "IsRelatedCompany": "is_related",
                              "CurrencyCode": "currency", "Rank": "rank"})
    pur = pur[["scode", "year", "rank", "name", "is_listed", "biz_symbol",
               "is_related", "amount", "proportion", "currency"]]

    print("[3/5] 供应链集中度 ...")
    conc = apply_sample(load_dta("SC_ConcentrationIndex", CONC_COLS))
    conc = conc[["scode", "year", "TopCustomerToTotalRatio", "TopPurchaseToTotalRatio",
                 "CustomerConcentration", "PurchaseConcentration",
                 "CustomerConcentrationHHI", "PurchaseConcentrationHHI",
                 "SupplyChainConcentration"]]

    print("[4/5] 供应链地理距离 ...")
    dist = apply_sample(load_dta("SC_GgrphclDistanceIndex", DIST_COLS))
    dist = dist.rename(columns={"InstitutionName": "name",
                                "BusinessRelations": "relation",
                                "GgrphclPrxmtySigns": "near_100km",
                                "SpatialDistance": "distance_km",
                                "IsSameProvince": "same_province",
                                "IsSameCity": "same_city", "Rank": "rank"})
    dist = dist[["scode", "year", "relation", "rank", "name", "near_100km",
                 "distance_km", "Distance", "same_province", "same_city"]]

    print("[5/5] 供应链网络关系（二跳） ...")
    net = apply_sample(load_dta("SC_NetworkRelationsIndex", NET_COLS))
    net = net.rename(columns={"PSCBusinessRelation": "psc_relation",
                              "PSCSymbol": "psc_symbol",
                              "SSCBusinessRelation": "ssc_relation",
                              "SSCSymbol": "ssc_symbol"})
    net = net[["scode", "year", "psc_relation", "psc_symbol", "ssc_relation", "ssc_symbol"]]

    KB_DIR.mkdir(parents=True, exist_ok=True)
    if DB.exists():
        DB.unlink()
    con = sqlite3.connect(DB)
    sale.to_sql("top5_sale", con, index=False, if_exists="replace")
    pur.to_sql("top5_purchase", con, index=False, if_exists="replace")
    conc.to_sql("concentration", con, index=False, if_exists="replace")
    dist.to_sql("distance", con, index=False, if_exists="replace")
    net.to_sql("network", con, index=False, if_exists="replace")
    con.commit()

    print("\n== 覆盖统计（317 家样本，2018-2023，合并报表）==")
    for t in ["top5_sale", "top5_purchase", "concentration", "distance", "network"]:
        df = pd.read_sql(f"SELECT * FROM {t}", con)
        print(f"  {t:15s} 行 {len(df):6d} / 企业 {df['scode'].nunique():4d}")
    print(f"\nwritten -> {DB}")


if __name__ == "__main__":
    main()
