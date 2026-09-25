"""本次口径迁移：可重复运行，隔离未解决文本，保留原始研究资料。"""
from pathlib import Path
import hashlib
import json
import sqlite3

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent


def quarantine(db):
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    rows = [dict(r) for r in con.execute("SELECT * FROM chunks WHERE program_label='unresolved'")]
    if rows:
        assert len(rows) == 3, "未解决范围发生变化，停止迁移"
        assert not con.execute("SELECT 1 FROM claims WHERE chunk_id IN (SELECT chunk_id FROM chunks WHERE program_label='unresolved') LIMIT 1").fetchone()
        archive = OUT / "excluded_chunks.json"
        if not archive.exists():
            archive.write_text(json.dumps({"source_sha256": hashlib.sha256(Path(db).read_bytes()).hexdigest(),
                "policy": "从应用有效文本中排除；不填造负标签；原始研究输出不变",
                "rows": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
        with con:
            con.execute("CREATE TABLE IF NOT EXISTS excluded_chunks AS SELECT * FROM chunks WHERE 0")
            con.execute("INSERT INTO excluded_chunks SELECT * FROM chunks WHERE program_label='unresolved'")
            con.execute("DELETE FROM chunks WHERE program_label='unresolved'")
            con.execute("UPDATE meta SET chunks=(SELECT COUNT(*) FROM chunks), industries=?",
                        ("电气设备现有样本细分；不扩样",))
    with con:
        con.execute("UPDATE meta SET pv_overlap_with_panel=37, firms_pv_text=0")
    con.close()


if __name__ == "__main__":
    quarantine(ROOT / "kb/kb-2023.sqlite")
