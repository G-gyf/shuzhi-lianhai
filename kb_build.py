# -*- coding: utf-8 -*-
"""Build knowledge-base snapshot kb-2023.sqlite (dual industry).

电气设备: 01_demand_construction/02_full_text_label_run
光伏:     01_demand_construction/03_photovoltaic_text_label_run
  - 光伏 chunk_id 与电气冲突（同一 v21 序列），入库统一加 "pv_" 前缀
  - 光伏 classified 无 text_clean，从 cleaned/narrative_chunks_cleaned.csv join
  - industry 列: 电气设备 / 光伏
"""
import io
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
import pandas as pd

ROOT = Path(__file__).resolve().parent
UP = ROOT.parent / "技术链" / "出海预测"
DC = UP / "outputs" / "01_demand_construction"
EL = DC / "02_full_text_label_run"
PV = DC / "03_photovoltaic_text_label_run"
PV_CLEAN = (UP / "outputs" / "00_source_text_corpus"
            / "annual_report_narratives_photovoltaic_2018_2023"
            / "cleaned" / "narrative_chunks_cleaned.csv")
PANEL = UP / "outputs" / "02_demand_validation" / "measurement_panel_validation"
KB_DIR = ROOT / "kb"
DB = KB_DIR / "kb-2023.sqlite"

COUNTRIES = [
    "越南", "印度尼西亚", "印尼", "印度", "泰国", "马来西亚", "新加坡", "日本", "韩国",
    "美国", "加拿大", "墨西哥", "巴西", "智利", "德国", "法国", "英国", "意大利",
    "西班牙", "波兰", "匈牙利", "俄罗斯", "澳大利亚", "南非", "埃及", "阿联酋",
    "沙特", "土耳其", "菲律宾", "荷兰", "瑞士", "香港",
]


def hit_countries(text):
    if not isinstance(text, str):
        return []
    return [c for c in COUNTRIES if c in text]


CHUNK_COLS = ["chunk_id", "scode", "coname", "year", "section_canonical",
              "program_label", "claim_count", "text_clean"]
CLAIM_COLS = ["chunk_id", "scode", "year", "claim_number", "program_label",
              "evidence_start", "evidence_end", "evidence_quote", "actor",
              "time_state", "direction", "execution_anchor_type",
              "execution_anchor", "country_hits"]


def load_chunks_el():
    ch = pd.read_csv(EL / "classified_all.csv", encoding="utf-8",
                     usecols=["chunk_id", "scode", "coname", "year",
                              "section_canonical", "program_label",
                              "claim_count", "text_clean"],
                     dtype={"scode": str})
    ch["scode"] = ch["scode"].str.zfill(6)
    ch["industry"] = "电气设备"
    return ch


def load_chunks_pv(el_scodes):
    lab = pd.read_csv(PV / "classified_all.csv", encoding="utf-8",
                      usecols=["chunk_id", "scode", "coname", "year",
                               "section_canonical", "program_label",
                               "claim_count"],
                      dtype={"scode": str})
    txt = pd.read_csv(PV_CLEAN, encoding="utf-8",
                      usecols=["chunk_id", "text_clean"], dtype=str)
    ch = lab.merge(txt, on="chunk_id", how="left")
    ch["scode"] = ch["scode"].str.zfill(6)
    # 去重：与电气样本重叠的企业-年已在电气版覆盖（含面板联动），光伏版丢弃
    ch = ch[~ch["scode"].isin(el_scodes)]
    ch["chunk_id"] = "pv_" + ch["chunk_id"]
    ch["industry"] = "光伏"
    return ch


def load_claims_el():
    cl = pd.read_csv(EL / "extracted_claims.csv", encoding="utf-8")
    ch = pd.read_csv(EL / "classified_all.csv", encoding="utf-8",
                     usecols=["chunk_id", "scode", "year"], dtype={"scode": str})
    cl = cl.merge(ch, on="chunk_id", how="left")
    cl["scode"] = cl["scode"].str.zfill(6)
    cl["industry"] = "电气设备"
    return cl


def load_claims_pv(el_scodes):
    cl = pd.read_csv(PV / "extracted_claims.csv", encoding="utf-8")
    lab = pd.read_csv(PV / "classified_all.csv", encoding="utf-8",
                      usecols=["chunk_id", "scode", "year"], dtype={"scode": str})
    cl = cl.merge(lab, on="chunk_id", how="left")
    cl["scode"] = cl["scode"].str.zfill(6)
    cl = cl[~cl["scode"].isin(el_scodes)]
    cl["chunk_id"] = "pv_" + cl["chunk_id"]
    cl["industry"] = "光伏"
    return cl


def main():
    KB_DIR.mkdir(parents=True, exist_ok=True)
    print("[1/5] 电气设备 chunks/claims ...")
    ch_el = load_chunks_el()
    cl_el = load_claims_el()
    el_scodes = set(ch_el["scode"].unique())
    print("[2/5] 光伏 chunks/claims（去重：与电气重叠企业-年保留电气版）...")
    ch_pv = load_chunks_pv(el_scodes)
    cl_pv = load_claims_pv(el_scodes)
    print("[3/5] 合并 + 国别提取 ...")
    ch = pd.concat([ch_el, ch_pv], ignore_index=True)
    cl = pd.concat([cl_el, cl_pv], ignore_index=True)
    cl["country_hits"] = cl["execution_anchor"].map(hit_countries).map(json.dumps)
    print("[4/5] 面板 + 子公司国家 ...")
    p = pd.read_csv(PANEL / "intent_measurement_panel_raw.csv", encoding="utf-8",
                    dtype={"scode": str})
    p["scode"] = p["scode"].str.zfill(6)
    sub = pd.read_csv(PANEL / "overseas_subsidiary_country_counts.csv", encoding="utf-8",
                      dtype={"scode": str})
    sub["scode"] = sub["scode"].str.zfill(6)
    print("[5/5] 写 SQLite ...")
    if DB.exists():
        DB.unlink()
    con = sqlite3.connect(DB)
    ch[CHUNK_COLS + ["industry"]].to_sql("chunks", con, if_exists="replace", index=False)
    cl[CLAIM_COLS + ["industry"]].to_sql("claims", con, if_exists="replace", index=False)
    p.to_sql("firm_year", con, if_exists="replace", index=False)
    sub.to_sql("subs_country", con, if_exists="replace", index=False)
    pv_overlap = sorted(set(ch_pv["scode"]) & set(p["scode"].unique()))
    meta = {
        "kb_version": "kb-2023",
        "built_at": datetime.now().isoformat(timespec="seconds"),
        "chunks": int(len(ch)),
        "claims": int(len(cl)),
        "firm_years": int(len(p)),
        "firms_el": int(ch_el["scode"].nunique()),
        "firms_pv_text": int(ch_pv["scode"].nunique()),
        "pv_overlap_with_panel": len(pv_overlap),
        "years": "2018-2023",
        "industries": "电气设备 + 光伏（申万6305xx，文本信号全量；面板仅重叠37家）",
        "source": "出海预测/outputs（冻结语料）",
    }
    pd.DataFrame([meta]).to_sql("meta", con, if_exists="replace", index=False)
    con.execute("CREATE INDEX IF NOT EXISTS idx_chunks_scode ON chunks(scode)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_claims_scode ON claims(scode)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_claims_chunk ON claims(chunk_id)")
    con.commit()
    con.close()
    print("saved:", DB)
    print(json.dumps(meta, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
