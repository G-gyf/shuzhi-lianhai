# -*- coding: utf-8 -*-
"""Build knowledge-base snapshot kb-2023.sqlite from 出海预测 outputs.

Usage:  python kb_build.py
Output: kb/kb-2023.sqlite
"""
import json
import sqlite3
import sys
import io
from datetime import datetime
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
import pandas as pd

ROOT = Path(__file__).resolve().parent
UP = ROOT.parent / "技术链" / "出海预测"
OUT1 = UP / "outputs" / "01_demand_construction" / "02_full_text_label_run"
OUT2 = UP / "outputs" / "02_demand_validation" / "measurement_panel_validation"
KB_DIR = ROOT / "kb"
DB = KB_DIR / "kb-2023.sqlite"

# country lexicon for anchor extraction (词典型口径，归一化待做)
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


def main():
    KB_DIR.mkdir(parents=True, exist_ok=True)
    print("[1/4] reading chunk table ...")
    ch = pd.read_csv(
        OUT1 / "classified_all.csv", encoding="utf-8",
        usecols=["chunk_id", "scode", "coname", "year", "section_canonical",
                 "program_label", "claim_count", "text_clean"],
        dtype={"scode": str})
    ch["scode"] = ch["scode"].str.zfill(6)
    ch = ch[ch["program_label"] != "unresolved"]

    print("[2/4] reading claims ...")
    cl = pd.read_csv(OUT1 / "extracted_claims.csv", encoding="utf-8")
    cl = cl.merge(ch[["chunk_id", "scode", "year"]], on="chunk_id", how="left")
    cl["scode"] = cl["scode"].str.zfill(6)
    cl["country_hits"] = cl["execution_anchor"].map(hit_countries).map(json.dumps)

    print("[3/4] reading panel & subsidiary countries ...")
    p = pd.read_csv(OUT2 / "intent_measurement_panel_raw.csv", encoding="utf-8",
                    dtype={"scode": str})
    p["scode"] = p["scode"].str.zfill(6)
    sub = pd.read_csv(OUT2 / "overseas_subsidiary_country_counts.csv", encoding="utf-8",
                      dtype={"scode": str})
    sub["scode"] = sub["scode"].str.zfill(6)

    print("[4/4] writing sqlite ...")
    if DB.exists():
        DB.unlink()
    con = sqlite3.connect(DB)
    ch[["chunk_id", "scode", "coname", "year", "section_canonical",
        "program_label", "claim_count", "text_clean"]].to_sql(
        "chunks", con, if_exists="replace", index=False)
    cl[[c for c in ["chunk_id", "scode", "year", "claim_number", "program_label",
                    "evidence_start", "evidence_end", "evidence_quote", "actor",
                    "time_state", "direction", "execution_anchor_type",
                    "execution_anchor", "country_hits"] if c in cl.columns]].to_sql(
        "claims", con, if_exists="replace", index=False)
    p.to_sql("firm_year", con, if_exists="replace", index=False)
    sub.to_sql("subs_country", con, if_exists="replace", index=False)
    meta = {
        "kb_version": "kb-2023",
        "built_at": datetime.now().isoformat(timespec="seconds"),
        "chunks": int(len(ch)),
        "claims": int(len(cl)),
        "firm_years": int(len(p)),
        "firms": int(p["scode"].nunique()),
        "years": "2018-2023",
        "industry": "电气设备",
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
