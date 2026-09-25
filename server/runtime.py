# -*- coding: utf-8 -*-
"""运行库（app_runtime.sqlite）与数据快照管理。

职责：
- 会话 / 消息 / 分析 / 引用 / 偏好 / 资料源 / 扩展注册等运行数据（方案 11.2 节）。
- 核心历史快照（kb/*.sqlite）保持只读，运行数据一律不入核心库。
- 快照 ID：`kb-2023@<内容哈希>`；文本版本 = 单块文本哈希，用于稳定引用定位。
- 演示身份：最小令牌登录 + 用户—地区绑定。正式多人使用前必须替换为行内身份系统，
  前端不能以自报地区代替服务端权限（方案 7.3 节）。
"""
from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KB_DIR = ROOT / "kb"
RUNTIME_DIR = ROOT / "runtime"
DB_PATH = RUNTIME_DIR / "app_runtime.sqlite"

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None

# 快照内容哈希由启动时计算（核心库文件只读）
SNAPSHOT_SOURCES = ["kb-2023.sqlite", "kb-sc-2023.sqlite"]


def _sha12(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()[:12]


def snapshot_id() -> str:
    """内容哈希快照 ID：kb-2023@<12位哈希>；库文件变化即变化。"""
    parts = []
    for name in SNAPSHOT_SOURCES:
        p = KB_DIR / name
        parts.append(_sha12(p.read_bytes()) if p.exists() else "missing")
    return "kb-2023@" + _sha12("|".join(parts).encode("utf-8"))


def text_version(text: str | None) -> str:
    """单块文本版本：文本内容哈希。用于 evidence 引用在对应版本按偏移还原。"""
    return _sha12((text or "").encode("utf-8"))


_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  user_id TEXT PRIMARY KEY,
  display_name TEXT NOT NULL,
  token_hash TEXT NOT NULL UNIQUE,
  identity_mode TEXT NOT NULL DEFAULT 'demo',   -- demo | production
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS regions (
  region_id TEXT PRIMARY KEY,
  label TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS memberships (
  user_id TEXT NOT NULL REFERENCES users(user_id),
  region_id TEXT NOT NULL REFERENCES regions(region_id),
  PRIMARY KEY (user_id, region_id)
);
CREATE TABLE IF NOT EXISTS manager_profiles (
  user_id TEXT PRIMARY KEY REFERENCES users(user_id),
  preferences TEXT NOT NULL,
  version INTEGER NOT NULL DEFAULT 1,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
  session_id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(user_id),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  current_scode TEXT,
  current_year INTEGER,
  context_version INTEGER NOT NULL DEFAULT 0,
  state TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS messages (
  seq INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id TEXT NOT NULL REFERENCES sessions(session_id),
  request_id TEXT NOT NULL,
  role TEXT NOT NULL,               -- user | assistant
  content TEXT NOT NULL,
  intent TEXT,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS analyses (
  analysis_id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  request_id TEXT NOT NULL,
  session_id TEXT,
  scode TEXT,
  year INTEGER,
  snapshot_id TEXT NOT NULL,
  product_version TEXT,
  engine TEXT NOT NULL,
  workflow_version TEXT,
  draft TEXT NOT NULL,              -- 已校验 analysis_draft JSON
  status TEXT NOT NULL,             -- validated | partial | fallback
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS analysis_refs (
  ref_id TEXT NOT NULL,
  analysis_id TEXT NOT NULL REFERENCES analyses(analysis_id),
  kind TEXT NOT NULL,
  payload TEXT NOT NULL,
  PRIMARY KEY (ref_id, analysis_id)
);
CREATE TABLE IF NOT EXISTS comparisons (
  comparison_id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  payload TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS briefings (
  briefing_id TEXT PRIMARY KEY,
  analysis_id TEXT NOT NULL REFERENCES analyses(analysis_id),
  user_id TEXT NOT NULL,
  title TEXT NOT NULL,
  sections TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS data_sources (
  source_id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  scope TEXT NOT NULL,
  region_id TEXT,
  kind TEXT NOT NULL,
  adapter_id TEXT NOT NULL,
  entity_key TEXT,
  time_field TEXT,
  version TEXT NOT NULL,
  allowed_capabilities TEXT NOT NULL,   -- JSON 数组
  status TEXT NOT NULL DEFAULT 'draft', -- draft | validated | active | disabled
  description TEXT NOT NULL DEFAULT '',
  owner_user_id TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS source_documents (
  doc_id TEXT PRIMARY KEY,
  source_id TEXT NOT NULL REFERENCES data_sources(source_id),
  title TEXT NOT NULL,
  body TEXT NOT NULL,
  locator TEXT NOT NULL DEFAULT '',
  effective_from TEXT,
  version TEXT NOT NULL,
  region_id TEXT
);
CREATE TABLE IF NOT EXISTS extension_registry (
  extension_id TEXT PRIMARY KEY,
  display_name TEXT NOT NULL,
  description TEXT NOT NULL,
  input_schema TEXT NOT NULL,      -- JSON
  output_schema TEXT NOT NULL,     -- JSON
  allowed_roles TEXT NOT NULL,     -- JSON 数组
  available_regions TEXT NOT NULL, -- JSON 数组；空=全部
  timeout_seconds INTEGER NOT NULL,
  version TEXT NOT NULL,
  rate_limit_per_hour INTEGER NOT NULL,
  handler TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS extension_bindings (
  extension_id TEXT NOT NULL REFERENCES extension_registry(extension_id),
  region_id TEXT NOT NULL,
  enabled INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (extension_id, region_id)
);
CREATE TABLE IF NOT EXISTS import_jobs (
  job_id TEXT PRIMARY KEY,
  source_id TEXT NOT NULL,
  user_id TEXT NOT NULL,
  created_at TEXT NOT NULL,
  total_rows INTEGER,
  valid_rows INTEGER,
  issues TEXT NOT NULL,            -- JSON 数组
  preview TEXT NOT NULL,           -- JSON 数组
  status TEXT NOT NULL             -- pending | done | failed
);
CREATE TABLE IF NOT EXISTS validation_issues (
  issue_id INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id TEXT NOT NULL REFERENCES import_jobs(job_id),
  row INTEGER,
  field TEXT,
  issue TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS feedback (
  feedback_id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id TEXT NOT NULL,
  analysis_id TEXT,
  request_id TEXT,
  category TEXT NOT NULL,          -- data_error | unreasonable | outdated_material | ux
  comment TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS runtime_meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
"""

# 演示身份（明确标注为演示；正式环境由行内身份系统替代）
DEMO_USERS = {
    "demo-token-region-a": ("u_demo_a", "演示经理·A区（合成身份）", "region_a", "华东演示辖区"),
    "demo-token-region-b": ("u_demo_b", "演示经理·B区（合成身份）", "region_b", "华南演示辖区"),
}


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def init_runtime():
    """建库 + 种子数据（幂等）。"""
    global _conn
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH, check_same_thread=False)
    con.executescript(_SCHEMA)
    # 迁移：旧库补充 sessions.state 列
    cols = [c[1] for c in con.execute("PRAGMA table_info(sessions)")]
    if "state" not in cols:
        con.execute("ALTER TABLE sessions ADD COLUMN state TEXT NOT NULL DEFAULT '{}'")
    con.execute(
        "INSERT OR REPLACE INTO runtime_meta(key,value) VALUES('snapshot_id',?)",
        (snapshot_id(),))
    for token, (uid, name, region, region_label) in DEMO_USERS.items():
        con.execute(
            "INSERT OR REPLACE INTO users(user_id,display_name,token_hash,identity_mode,created_at)"
            " VALUES(?,?,?,?,?)", (uid, name, _hash_token(token), "demo", _now()))
        con.execute(
            "INSERT OR REPLACE INTO regions(region_id,label) VALUES(?,?)",
            (region, region_label))
        con.execute(
            "INSERT OR REPLACE INTO memberships(user_id,region_id) VALUES(?,?)",
            (uid, region))
        con.execute(
            "INSERT INTO manager_profiles(user_id,preferences,version,updated_at)"
            " VALUES(?,?,1,?) ON CONFLICT(user_id) DO NOTHING",
            (uid, json.dumps({"service_focus": [], "exclude_financing": False,
                              "default_region": region, "focus_industries": [],
                              "plan_length": "brief", "watchlist": []}), _now()))
    con.commit()
    _conn = con
    return con


def get_conn() -> sqlite3.Connection:
    global _conn
    with _lock:
        if _conn is None:
            _conn = init_runtime()
        return _conn


def authenticate(authorization: str | None) -> dict | None:
    """最小令牌登录：`Authorization: Bearer <token>` → 用户+地区。
    令牌哈希存储，不落明文。演示令牌见 DEMO_USERS。"""
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    token = authorization[7:].strip()
    if not token:
        return None
    con = get_conn()
    row = con.execute(
        "SELECT user_id, display_name, identity_mode FROM users WHERE token_hash=?",
        (_hash_token(token),)).fetchone()
    if not row:
        return None
    regions = [r[0] for r in con.execute(
        "SELECT region_id FROM memberships WHERE user_id=?", (row[0],))]
    return {"user_id": row[0], "display_name": row[1],
            "identity_mode": row[2], "regions": sorted(regions)}


def get_user_regions(user_id: str) -> list[str]:
    con = get_conn()
    return [r[0] for r in con.execute(
        "SELECT region_id FROM memberships WHERE user_id=?", (user_id,))]


def get_preferences(user_id: str) -> dict:
    con = get_conn()
    row = con.execute(
        "SELECT preferences FROM manager_profiles WHERE user_id=?", (user_id,)).fetchone()
    if not row:
        return {"service_focus": [], "exclude_financing": False,
                "default_region": None, "focus_industries": [],
                "plan_length": "brief", "watchlist": []}
    return json.loads(row[0])


def set_preferences(user_id: str, prefs: dict) -> dict:
    con = get_conn()
    merged = get_preferences(user_id)
    merged.update({k: v for k, v in prefs.items() if v is not None})
    con.execute(
        "INSERT INTO manager_profiles(user_id,preferences,version,updated_at)"
        " VALUES(?,?,1,?) ON CONFLICT(user_id) DO UPDATE SET preferences=excluded.preferences,"
        " version=manager_profiles.version+1, updated_at=excluded.updated_at",
        (user_id, json.dumps(merged, ensure_ascii=False), _now()))
    con.commit()
    return merged


def new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(6)}"


def get_snapshot() -> str:
    return snapshot_id()
