# -*- coding: utf-8 -*-
"""数据源与功能扩展注册（方案第 11 章）。

- 数据源登记 → 上传/试连接 → 字段映射 → 质量检查 → 预览 → 激活。
- 地区隔离：检索与引用读取时双重检查 scope/region 权限（验收用例 12/13）。
- 核心历史快照保持只读；地区资料入独立存储 source_documents。
- 首版示范适配器：document_reader_v1（JSON 文档集合）、table_reader_v1（CSV 表格）。
- 外部数据库连接配置使用凭证引用 credential_ref（不落密钥），本期仅保留协议字段。
"""
from __future__ import annotations

import json
from pathlib import Path

from . import runtime
from .schemas import regional_ref

ROOT = Path(__file__).resolve().parent.parent
DEMO_DOCS_PATH = ROOT / "knowledge" / "regional" / "demo_region_a_notes.json"

# 注册过的适配器（文档/表格/外部只读数据源；外部连接本期为协议占位）
ADAPTERS = {
    "document_reader_v1": {
        "name": "文档集合读取器 v1",
        "kinds": ["document_collection"],
        "description": "读取 JSON 文档集合（doc_id/title/body/locator/effective_from）。",
    },
    "table_reader_v1": {
        "name": "表格读取器 v1",
        "kinds": ["table"],
        "description": "读取 CSV/JSON 表格，校验企业代码、年度、金额单位、重复键与空值。",
    },
    "external_readonly_v1": {
        "name": "外部只读数据源适配器 v1（协议占位）",
        "kinds": ["external_readonly"],
        "description": "外部数据库只读接入协议：credential_ref + 声明表/字段/只读查询模板；本期未接真实外部库。",
    },
}

# 功能注册目录（模型只能看到已启用工具，后端仍逐次执行权限检查）
EXTENSION_REGISTRY_SEED = [
    {
        "extension_id": "region_document_search",
        "display_name": "地区资料检索",
        "description": "在授权地区资料集内检索并读取来源片段（演示：A区合成资料）。",
        "input_schema": {"query": "string"},
        "output_schema": {"snippets": "array"},
        "allowed_roles": ["manager"],
        "available_regions": ["region_a", "region_b"],
        "timeout_seconds": 10,
        "version": "v1",
        "rate_limit_per_hour": 200,
        "handler": "tools.search_regional_knowledge",
    },
]


def _now():
    return runtime._now()


def _seed():
    """幂等种子：演示地区资料源（合成示范，不冒称真实分行数据）+ 功能注册目录。"""
    con = runtime.get_conn()
    demo = {
        "source_id": "region_demo_service_notes",
        "name": "地区服务补充资料（合成示范）",
        "scope": "region",
        "region_id": "region_a",
        "kind": "document_collection",
        "adapter_id": "document_reader_v1",
        "entity_key": None,
        "time_field": "effective_from",
        "version": "v1",
        "allowed_capabilities": ["search", "read_reference"],
        "status": "active",
        "description": "仅用于地区扩展验收的合成示范资料；A 区可检索并出现来源光球，B 区不可检索或打开。非真实分行数据。",
        "owner_user_id": "u_demo_a",
    }
    upsert_source(con, demo, seed=True)
    docs = load_demo_documents()
    if docs:
        for d in docs:
            con.execute(
                "INSERT OR REPLACE INTO source_documents"
                "(doc_id,source_id,title,body,locator,effective_from,version,region_id)"
                " VALUES(?,?,?,?,?,?,?,?)",
                (d["doc_id"], demo["source_id"], d["title"], d["body"],
                 d.get("locator", ""), d.get("effective_from"),
                 demo["version"], demo["region_id"]))
    for ext in EXTENSION_REGISTRY_SEED:
        con.execute(
            "INSERT OR REPLACE INTO extension_registry"
            "(extension_id,display_name,description,input_schema,output_schema,"
            " allowed_roles,available_regions,timeout_seconds,version,rate_limit_per_hour,handler)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (ext["extension_id"], ext["display_name"], ext["description"],
             json.dumps(ext["input_schema"], ensure_ascii=False),
             json.dumps(ext["output_schema"], ensure_ascii=False),
             json.dumps(ext["allowed_roles"]),
             json.dumps(ext["available_regions"]),
             ext["timeout_seconds"], ext["version"],
             ext["rate_limit_per_hour"], ext["handler"]))
        # 默认绑定：A 区启用，B 区未启用（验收：停用后新请求不能继续引用）
        con.execute(
            "INSERT OR IGNORE INTO extension_bindings(extension_id,region_id,enabled)"
            " VALUES(?,?,?)", (ext["extension_id"], "region_a", 1))
    con.commit()


def upsert_source(con, spec: dict, seed: bool = False):
    con.execute(
        "INSERT OR REPLACE INTO data_sources"
        "(source_id,name,scope,region_id,kind,adapter_id,entity_key,time_field,"
        " version,allowed_capabilities,status,description,owner_user_id,created_at,updated_at)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (spec["source_id"], spec["name"], spec["scope"], spec.get("region_id"),
         spec["kind"], spec["adapter_id"], spec.get("entity_key"),
         spec.get("time_field"), spec.get("version", "v1"),
         json.dumps(spec.get("allowed_capabilities", ["search", "read_reference"])),
         spec.get("status", "draft"), spec.get("description", ""),
         spec.get("owner_user_id", ""), _now(), _now()))


def load_demo_documents() -> list[dict]:
    if not DEMO_DOCS_PATH.exists():
        return []
    with open(DEMO_DOCS_PATH, encoding="utf-8") as f:
        data = json.load(f)
    return data.get("documents", [])


def list_sources() -> list[dict]:
    con = runtime.get_conn()
    rows = con.execute("SELECT * FROM data_sources ORDER BY created_at DESC").fetchall()
    cols = [d[0] for d in con.execute("SELECT * FROM data_sources LIMIT 0").description]
    out = []
    for r in rows:
        d = dict(zip(cols, r))
        d["allowed_capabilities"] = json.loads(d["allowed_capabilities"] or "[]")
        out.append(d)
    return out


def get_source(source_id: str) -> dict | None:
    con = runtime.get_conn()
    row = con.execute("SELECT * FROM data_sources WHERE source_id=?",
                      (source_id,)).fetchone()
    if not row:
        return None
    cols = [d[0] for d in con.execute("SELECT * FROM data_sources LIMIT 0").description]
    d = dict(zip(cols, row))
    d["allowed_capabilities"] = json.loads(d["allowed_capabilities"] or "[]")
    return d


def create_source(user: dict, spec: dict) -> tuple[dict, str | None]:
    """登记数据源。region_id 以服务器权限校验后的值为准，不信任自报值。"""
    source_id = (spec.get("source_id") or "").strip()
    if not source_id:
        return {}, "source_id 不能为空"
    if get_source(source_id):
        return {}, f"source_id 已存在：{source_id}"
    kind = spec.get("kind") or "document_collection"
    adapter_id = spec.get("adapter_id") or ("table_reader_v1" if kind == "table"
                                            else "document_reader_v1")
    if adapter_id not in ADAPTERS:
        return {}, f"未知适配器：{adapter_id}"
    if kind not in ADAPTERS[adapter_id]["kinds"] and kind != "external_readonly":
        return {}, f"适配器 {adapter_id} 不支持 kind={kind}"
    scope = spec.get("scope") or "region"
    region_id = None
    if scope == "region":
        region_id = (spec.get("region_id") or "").strip()
        if region_id not in user["regions"]:
            return {}, f"region_id 必须属于当前经理辖区（服务端校验）：{region_id}"
    record = {
        "source_id": source_id,
        "name": spec.get("name") or source_id,
        "scope": scope,
        "region_id": region_id,
        "kind": kind,
        "adapter_id": adapter_id,
        "entity_key": spec.get("entity_key"),
        "time_field": spec.get("time_field"),
        "version": spec.get("version") or "v1",
        "allowed_capabilities": spec.get("allowed_capabilities") or ["search", "read_reference"],
        "status": "draft",
        "description": spec.get("description", ""),
        "owner_user_id": user["user_id"],
    }
    con = runtime.get_conn()
    upsert_source(con, record)
    con.commit()
    return get_source(source_id), None


def _run_adapter(src: dict, content: str) -> dict:
    """按适配器执行校验与导入预览。"""
    from .adapters import document_reader_v1, table_reader_v1
    if src["kind"] == "table":
        return table_reader_v1.validate(content)
    return document_reader_v1.validate(content)


def validate_source(source_id: str, user: dict, content: str, filename: str = "") -> dict:
    """试读、字段检查与导入预览；缺少企业匹配的行保留待处理状态。"""
    src = get_source(source_id)
    if not src:
        return {"ok": False, "error": "资料源不存在", "code": "not_found"}
    if src["owner_user_id"] != user["user_id"]:
        return {"ok": False, "error": "无权限校验该资料源", "code": "forbidden"}
    result = _run_adapter(src, content)
    con = runtime.get_conn()
    job_id = runtime.new_id("imp")
    con.execute(
        "INSERT INTO import_jobs(job_id,source_id,user_id,created_at,total_rows,valid_rows,issues,preview,status)"
        " VALUES(?,?,?,?,?,?,?,?,?)",
        (job_id, source_id, user["user_id"], _now(),
         result["total_rows"], result["valid_rows"],
         json.dumps(result["issues"], ensure_ascii=False),
         json.dumps(result["preview"], ensure_ascii=False),
         "failed" if result.get("fatal") else "done"))
    for issue in result["issues"]:
        con.execute(
            "INSERT INTO validation_issues(job_id,row,field,issue) VALUES(?,?,?,?)",
            (job_id, issue.get("row"), issue.get("field"), issue["issue"]))
    if not result.get("fatal"):
        con.execute("UPDATE data_sources SET status='validated', updated_at=? WHERE source_id=?",
                    (_now(), source_id))
    con.commit()
    return {"ok": True, "job_id": job_id, "source_id": source_id,
            "filename": filename, **result}


def activate_source(source_id: str, user: dict) -> dict:
    """激活通过验证的资料源：载入文档到 source_documents。"""
    src = get_source(source_id)
    if not src:
        return {"ok": False, "error": "资料源不存在", "code": "not_found"}
    if src["owner_user_id"] != user["user_id"]:
        return {"ok": False, "error": "无权限激活该资料源", "code": "forbidden"}
    if src["status"] != "validated":
        return {"ok": False, "error": f"资料源未通过验证（当前 {src['status']}），不能激活",
                "code": "not_validated"}
    con = runtime.get_conn()
    con.execute("UPDATE data_sources SET status='active', updated_at=? WHERE source_id=?",
                (_now(), source_id))
    con.commit()
    return {"ok": True, "source_id": source_id, "status": "active"}


def disable_source(source_id: str, user: dict) -> dict:
    """停用资料源：后续请求不能继续引用（缓存键包含 scope 和版本）。"""
    src = get_source(source_id)
    if not src:
        return {"ok": False, "error": "资料源不存在", "code": "not_found"}
    if src["owner_user_id"] != user["user_id"]:
        return {"ok": False, "error": "无权限停用该资料源", "code": "forbidden"}
    con = runtime.get_conn()
    con.execute("UPDATE data_sources SET status='disabled', updated_at=? WHERE source_id=?",
                (_now(), source_id))
    con.commit()
    return {"ok": True, "source_id": source_id, "status": "disabled"}


def _visible_sources(user_regions: list[str], allowed_source_ids=None) -> list[dict]:
    """检索范围 = 用户地区 ∩ 资料源地区；allowed_source_ids 仅作进一步收窄。"""
    out = []
    for s in list_sources():
        if s["status"] != "active":
            continue
        if s["scope"] == "region":
            if s["region_id"] not in user_regions:
                continue
        if allowed_source_ids is not None and s["source_id"] not in allowed_source_ids:
            continue
        out.append(s)
    return out


def search_regional(query: str, user_id: str, user_regions: list[str],
                    allowed_source_ids=None) -> dict:
    """地区资料检索：命中片段带 source_id/scope/版本；引用详情读取时再次检查权限。"""
    sources = _visible_sources(user_regions, allowed_source_ids)
    if not sources:
        return {"total": 0, "snippets": [], "coverage": {
            "user_regions": user_regions,
            "note": "当前辖区无已激活的授权资料源（或已停用）。"}}
    con = runtime.get_conn()
    snippets = []
    q = query.lower()
    for s in sources:
        if s["kind"] != "document_collection":
            continue
        for r in con.execute(
                "SELECT doc_id, source_id, title, body, locator, effective_from, version, region_id"
                " FROM source_documents WHERE source_id=?", (s["source_id"],)):
            body = r[3] or ""
            if q and q not in (r[2] or "").lower() and q not in body.lower():
                continue
            snippet = body[:260]
            snippets.append({
                "ref_id": regional_ref(r[1], r[0]),
                "source_id": r[1], "doc_id": r[0], "title": r[2],
                "snippet": snippet, "locator": r[4],
                "effective_from": r[5], "version": r[6], "scope": s["scope"],
                "source_name": s["name"],
            })
    snippets.sort(key=lambda x: (x["source_id"], x["doc_id"]))
    return {"total": len(snippets), "snippets": snippets[:10], "coverage": {
        "user_regions": user_regions,
        "note": "地区资料检索范围=授权辖区内的已激活资料源；引用详情读取时再次检查权限。"}}


def read_regional_doc(source_id: str, doc_id: str, user_regions: list[str]) -> dict:
    """引用详情读取：再次检查权限（验收用例 12：B 区不能直接按 ID 打开）。"""
    src = get_source(source_id)
    if not src or src["status"] != "active":
        return {"ok": False, "error": "资料源不存在或未激活", "code": "not_found"}
    if src["scope"] == "region" and src["region_id"] not in user_regions:
        return {"ok": False, "error": "该资料不在当前经理辖区可见范围内",
                "code": "forbidden"}
    con = runtime.get_conn()
    row = con.execute(
        "SELECT doc_id, source_id, title, body, locator, effective_from, version, region_id"
        " FROM source_documents WHERE source_id=? AND doc_id=?", (source_id, doc_id)).fetchone()
    if not row:
        return {"ok": False, "error": "文档不存在", "code": "not_found"}
    return {"ok": True, "doc_id": row[0], "source_id": row[1], "title": row[2],
            "body": row[3], "locator": row[4], "effective_from": row[5],
            "version": row[6], "region_id": row[7], "source_name": src["name"],
            "scope": src["scope"], "status": src["status"]}


def extension_catalog(user_regions: list[str]) -> dict:
    con = runtime.get_conn()
    out = []
    for r in con.execute("SELECT * FROM extension_registry"):
        cols = [d[0] for d in con.execute("SELECT * FROM extension_registry LIMIT 0").description]
        ext = dict(zip(cols, r))
        bindings = {}
        for b in con.execute("SELECT region_id, enabled FROM extension_bindings"
                             " WHERE extension_id=?", (ext["extension_id"],)):
            bindings[b[0]] = bool(b[1])
        enabled_here = any(bindings.get(reg) for reg in user_regions)
        out.append({
            "extension_id": ext["extension_id"], "display_name": ext["display_name"],
            "description": ext["description"],
            "input_schema": json.loads(ext["input_schema"]),
            "output_schema": json.loads(ext["output_schema"]),
            "allowed_roles": json.loads(ext["allowed_roles"]),
            "available_regions": json.loads(ext["available_regions"]),
            "timeout_seconds": ext["timeout_seconds"], "version": ext["version"],
            "rate_limit_per_hour": ext["rate_limit_per_hour"],
            "bindings": bindings, "enabled_for_me": enabled_here,
        })
    return {"extensions": out, "note": "模型只能看到已启用工具；后端仍逐次执行权限检查。"}


def set_extension_binding(extension_id: str, region_id: str, enabled: bool,
                          user_regions: list[str]) -> dict:
    """经理从有权限的目录启用/停用扩展（仅限本辖区）。"""
    if region_id not in user_regions:
        return {"ok": False, "error": "region 不在当前经理辖区", "code": "forbidden"}
    con = runtime.get_conn()
    row = con.execute("SELECT 1 FROM extension_registry WHERE extension_id=?",
                      (extension_id,)).fetchone()
    if not row:
        return {"ok": False, "error": "扩展不存在", "code": "not_found"}
    con.execute(
        "INSERT INTO extension_bindings(extension_id,region_id,enabled) VALUES(?,?,?)"
        " ON CONFLICT(extension_id,region_id) DO UPDATE SET enabled=excluded.enabled",
        (extension_id, region_id, 1 if enabled else 0))
    con.commit()
    return {"ok": True, "extension_id": extension_id, "region_id": region_id,
            "enabled": bool(enabled)}


# ---------------- HTTP 接口（方案 7.2：数据源登记/校验/激活、扩展目录） ----------------
from fastapi import APIRouter, HTTPException, Request  # noqa: E402
from pydantic import BaseModel  # noqa: E402

router = APIRouter(prefix="/api/v1")


class DataSourceBody(BaseModel):
    source_id: str
    name: str = ""
    scope: str = "region"
    region_id: str | None = None
    kind: str = "document_collection"
    adapter_id: str = ""
    entity_key: str | None = None
    time_field: str | None = None
    version: str = "v1"
    allowed_capabilities: list[str] | None = None
    description: str = ""


class BindingBody(BaseModel):
    enabled: bool = True


def _user(request: Request) -> dict:
    from . import runtime as rt
    user = rt.authenticate(request.headers.get("authorization"))
    if not user:
        raise HTTPException(401, "需要 Authorization: Bearer <token>")
    return user


@router.get("/extensions")
def list_extensions(request: Request):
    user = _user(request)
    return extension_catalog(user["regions"])


@router.post("/extensions/{extension_id}/bindings/{region_id}")
def bind_extension(extension_id: str, region_id: str, body: BindingBody,
                   request: Request):
    user = _user(request)
    r = set_extension_binding(extension_id, region_id, body.enabled, user["regions"])
    if not r.get("ok"):
        raise HTTPException(403, r.get("error", "操作失败"))
    return r


@router.get("/data-sources")
def list_data_sources(request: Request):
    user = _user(request)
    return {"items": [s for s in list_sources() if s["owner_user_id"] == user["user_id"]
                      or s["scope"] != "region" or s["region_id"] in user["regions"]]}


@router.post("/data-sources")
def create_data_source(body: DataSourceBody, request: Request):
    user = _user(request)
    record, err = create_source(user, body.model_dump(exclude_none=True))
    if err:
        raise HTTPException(400, err)
    return {"ok": True, "source": record}


@router.post("/data-sources/{source_id}/validate")
async def validate_data_source(source_id: str, request: Request):
    """试读、字段检查与导入预览。内容从请求体直接传入（演示上传路径）。"""
    user = _user(request)
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        data = await request.json()
        content = json.dumps(data, ensure_ascii=False)
    else:
        raw = await request.body()
        try:
            content = raw.decode("utf-8")
        except UnicodeDecodeError:
            raise HTTPException(400, "文件必须为 UTF-8 文本（JSON 文档集合或 CSV 表格）")
    r = validate_source(source_id, user, content)
    if not r.get("ok"):
        raise HTTPException(404 if r.get("code") == "not_found" else 403,
                            r.get("error", "校验失败"))
    return r


@router.post("/data-sources/{source_id}/activate")
def activate_data_source(source_id: str, request: Request):
    user = _user(request)
    r = activate_source(source_id, user)
    if not r.get("ok"):
        code = r.get("code", "")
        status = 404 if code == "not_found" else (403 if code == "forbidden" else 400)
        raise HTTPException(status, r.get("error", "激活失败"))
    return r


@router.post("/data-sources/{source_id}/disable")
def disable_data_source(source_id: str, request: Request):
    user = _user(request)
    r = disable_source(source_id, user)
    if not r.get("ok"):
        raise HTTPException(404 if r.get("code") == "not_found" else 403,
                            r.get("error", "停用失败"))
    return r
