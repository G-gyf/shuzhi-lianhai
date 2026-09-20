# -*- coding: utf-8 -*-
"""供应链数据访问层（kb-sc-2023.sqlite，CSMAR 供应链系列）。

口径：
- 全部为 317 家样本、2018-2023、合并报表（构建时已过滤）
- 比例与集中度字段均为百分比数值
- 海外客户/供应商识别：名称经 geo 层提取 canonical 国别
  （排除 内蒙古/印度洋 等误匹配；纯境内名称如"中芯国际(天津)"不会命中）
"""
import sqlite3
from functools import lru_cache
from pathlib import Path

import pandas as pd

from .geo import geo_extract

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "kb" / "kb-sc-2023.sqlite"


@lru_cache(maxsize=1)
def _conn():
    con = sqlite3.connect(DB, check_same_thread=False)
    return con


def _code(x):
    """Stata 数值型股票代码 → 6 位字符串。"""
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return None
    s = str(x).strip()
    if s.endswith(".0"):
        s = s[:-2]
    return s


@lru_cache(maxsize=1)
def top5_sale():
    df = pd.read_sql("SELECT * FROM top5_sale", _conn())
    df["scode"] = df["scode"].astype(str).str.zfill(6)
    geo = df["name"].map(geo_extract)
    df["overseas"] = geo.map(lambda g: len(g["countries"]) > 0)
    df["geo_countries"] = geo.map(lambda g: g["countries"])
    return df


@lru_cache(maxsize=1)
def top5_purchase():
    df = pd.read_sql("SELECT * FROM top5_purchase", _conn())
    df["scode"] = df["scode"].astype(str).str.zfill(6)
    geo = df["name"].map(geo_extract)
    df["overseas"] = geo.map(lambda g: len(g["countries"]) > 0)
    df["geo_countries"] = geo.map(lambda g: g["countries"])
    return df


@lru_cache(maxsize=1)
def concentration():
    df = pd.read_sql("SELECT * FROM concentration", _conn())
    df["scode"] = df["scode"].astype(str).str.zfill(6)
    return df


@lru_cache(maxsize=1)
def network():
    df = pd.read_sql("SELECT * FROM network", _conn())
    df["scode"] = df["scode"].astype(str).str.zfill(6)
    return df


def _year_slice(df, scode, year):
    s = df[df["scode"] == scode]
    if year is not None:
        s = s[s["year"] == int(year)]
    elif not s.empty:
        s = s[s["year"] == s["year"].max()]
    return s


def customer_concentration(scode, year=None):
    """前五大客户销售占比（%）。year=None 取最新可得年度；缺失返回 None。"""
    c = _year_slice(concentration(), scode, year)
    if c.empty or pd.isna(c.iloc[0]["CustomerConcentration"]):
        return None
    return float(c.iloc[0]["CustomerConcentration"])


def supplier_concentration(scode, year=None):
    """前五大供应商采购占比（%）。year=None 取最新可得年度；缺失返回 None。"""
    c = _year_slice(concentration(), scode, year)
    if c.empty or pd.isna(c.iloc[0]["PurchaseConcentration"]):
        return None
    return float(c.iloc[0]["PurchaseConcentration"])


def overseas_customer_share(scode, year):
    """该年度前五大客户中海外客户的销售占比之和（%）；无海外客户返回 None。"""
    if year is None:
        return None
    sale = top5_sale()
    s = sale[(sale["scode"] == scode) & (sale["year"] == int(year)) & (sale["rank"] <= 5)]
    if s.empty or not s["overseas"].any():
        return None
    return round(float(s[s["overseas"]]["proportion"].sum()), 2)


def sc_of(scode, year=None):
    """企业-年供应链画像：客户/供应商（结构化 top5）/集中度/二跳链。"""
    out = {"customers": [], "suppliers": [], "concentration": None, "two_hop": []}

    s = _year_slice(top5_sale(), scode, year)
    for _, r in s[s["rank"] <= 5].sort_values("rank").iterrows():
        out["customers"].append({
            "rank": int(r["rank"]),
            "name": r["name"],
            "amount": float(r["amount"]) if pd.notna(r["amount"]) else None,
            "proportion": float(r["proportion"]) if pd.notna(r["proportion"]) else None,
            "overseas": bool(r["overseas"]),
            "year": int(r["year"]),
        })

    p = _year_slice(top5_purchase(), scode, year)
    for _, r in p[p["rank"] <= 5].sort_values("rank").iterrows():
        out["suppliers"].append({
            "rank": int(r["rank"]),
            "name": r["name"],
            "amount": float(r["amount"]) if pd.notna(r["amount"]) else None,
            "proportion": float(r["proportion"]) if pd.notna(r["proportion"]) else None,
            "overseas": bool(r["overseas"]),
            "year": int(r["year"]),
        })

    c = _year_slice(concentration(), scode, year)
    if not c.empty:
        r = c.iloc[0]
        out["concentration"] = {
            "year": int(r["year"]),
            "customer": float(r["CustomerConcentration"]) if pd.notna(r["CustomerConcentration"]) else None,
            "purchase": float(r["PurchaseConcentration"]) if pd.notna(r["PurchaseConcentration"]) else None,
            "customer_hhi": float(r["CustomerConcentrationHHI"]) if pd.notna(r["CustomerConcentrationHHI"]) else None,
            "purchase_hhi": float(r["PurchaseConcentrationHHI"]) if pd.notna(r["PurchaseConcentrationHHI"]) else None,
        }

    n = _year_slice(network(), scode, year)
    for _, r in n.iterrows():
        out["two_hop"].append({
            "year": int(r["year"]),
            "rel1": "客户" if int(r["psc_relation"]) == 1 else "供应商",
            "b": _code(r["psc_symbol"]),
            "rel2": "客户" if int(r["ssc_relation"]) == 1 else "供应商",
            "c": _code(r["ssc_symbol"]),
        })
    return out
