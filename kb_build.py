# -*- coding: utf-8 -*-
"""从冻结研究输出构建现有电气样本；光伏等细分使用规则标签，不扩样。
未解决块从有效文本排除，留存在 excluded_chunks；年度缺失标签不填0。
写临时库并验证后原子替换，不先删除可用库。
"""
import json
import sqlite3
from datetime import datetime
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parent
UP = ROOT.parent / "技术链" / "出海预测"
EL = UP / "outputs/01_demand_construction/02_full_text_label_run"
PANEL = UP / "outputs/02_demand_validation/measurement_panel_validation"
DB = ROOT / "kb/kb-2023.sqlite"
CHUNK_COLS = ["chunk_id", "scode", "coname", "year", "section_canonical", "program_label", "claim_count", "text_clean", "industry"]
CLAIM_COLS = ["chunk_id", "scode", "year", "claim_number", "program_label", "evidence_start", "evidence_end", "evidence_quote", "actor", "time_state", "direction", "execution_anchor_type", "execution_anchor", "country_hits", "industry"]


def main():
    from server.geo import geo_extract
    ch = pd.read_csv(EL / "classified_all.csv", dtype={"scode": str}, low_memory=False)
    ch["scode"] = ch["scode"].str.zfill(6)
    ch["industry"] = "电气设备"
    excluded = ch[ch["program_label"] == "unresolved"].copy()
    ch = ch[ch["program_label"] != "unresolved"].copy()
    cl = pd.read_csv(EL / "extracted_claims.csv")
    cl = cl.merge(ch[["chunk_id", "scode", "year"]], on="chunk_id", how="inner", validate="many_to_one")
    cl["industry"] = "电气设备"
    cl["country_hits"] = cl["execution_anchor"].fillna("").map(lambda x: json.dumps(geo_extract(x)["countries"], ensure_ascii=False))
    p = pd.read_csv(PANEL / "intent_measurement_panel_raw.csv", dtype={"scode": str})
    sub = pd.read_csv(PANEL / "overseas_subsidiary_country_counts.csv", dtype={"scode": str})
    for frame in (p, sub):
        frame["scode"] = frame["scode"].str.zfill(6)
    meta = {"kb_version": "kb-2023", "built_at": datetime.now().isoformat(timespec="seconds"), "chunks": len(ch), "claims": len(cl), "firm_years": len(p), "firms_el": ch.scode.nunique(), "firms_pv_text": 0, "pv_overlap_with_panel": 37, "years": "2018-2023", "industries": "电气设备现有样本细分；不扩样", "source": "出海预测/outputs（冻结语料；排除未解决块）"}
    DB.parent.mkdir(exist_ok=True)
    temp = DB.with_suffix(".building.sqlite")
    with sqlite3.connect(temp) as con:
        for name, frame in [("chunks", ch[CHUNK_COLS]), ("claims", cl[CLAIM_COLS]), ("excluded_chunks", excluded[CHUNK_COLS]), ("firm_year", p), ("subs_country", sub), ("meta", pd.DataFrame([meta]))]:
            frame.to_sql(name, con, if_exists="replace", index=False)
        con.execute("CREATE INDEX IF NOT EXISTS idx_chunks_scode ON chunks(scode)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_claims_scode ON claims(scode)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_claims_chunk ON claims(chunk_id)")
        assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    con.close()  # Windows 文件替换前必须释放 SQLite 句柄
    temp.replace(DB)
    print(json.dumps(meta, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
