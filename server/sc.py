# -*- coding: utf-8 -*-
"""供应链数据访问层（kb-sc-2023.sqlite，CSMAR 供应链系列）。

口径：
- 全部为 317 家样本、2018-2023、合并报表（构建时已过滤）
- 比例与集中度字段均为百分比数值
- 海外客户/供应商识别：名称经 geo 层的**名称专用**判定
  （`geo_extract_name`，只认名称开头或分隔符片段内的国别词）识别 canonical 国别，
  避免「上海顺斯德国际贸易有限公司 → 德国」这类中文字串误命中
- 多跳关联查询（企业→交易对手→下一跳）属于 Neo4j 扩展设计，不在本期实现，
  本模块只提供单跳的前五大客户/供应商与集中度画像
"""
import sqlite3
from functools import lru_cache
from pathlib import Path

import pandas as pd

from .geo import geo_extract_name

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "kb" / "kb-sc-2023.sqlite"


@lru_cache(maxsize=1)
def _conn():
    con = sqlite3.connect(DB, check_same_thread=False)
    return con


@lru_cache(maxsize=1)
def top5_sale():
    df = pd.read_sql("SELECT * FROM top5_sale", _conn())
    df["scode"] = df["scode"].astype(str).str.zfill(6)
    geo = df["name"].map(geo_extract_name)
    df["overseas"] = geo.map(lambda g: len(g["countries"]) > 0)
    df["geo_countries"] = geo.map(lambda g: g["countries"])
    return df


@lru_cache(maxsize=1)
def top5_purchase():
    df = pd.read_sql("SELECT * FROM top5_purchase", _conn())
    df["scode"] = df["scode"].astype(str).str.zfill(6)
    geo = df["name"].map(geo_extract_name)
    df["overseas"] = geo.map(lambda g: len(g["countries"]) > 0)
    df["geo_countries"] = geo.map(lambda g: g["countries"])
    return df


@lru_cache(maxsize=1)
def concentration():
    df = pd.read_sql("SELECT * FROM concentration", _conn())
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
    """企业-年供应链画像：前五大客户/供应商（结构化）+ 集中度。

    多跳关联查询不在本期：本函数只输出单跳画像，不推导「传导」结论。
    """
    out = {"customers": [], "suppliers": [], "concentration": None}

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
    return out
