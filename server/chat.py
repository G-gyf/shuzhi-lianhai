# -*- coding: utf-8 -*-
"""对话网关：会话、请求、SSE（方案 5.1、7.2、9.3 节）。

事件流（项目自定义协议，不直接暴露 Coze 原始事件）：
  request_started → status(querying) → status(analyzing) → status(validating)
  → answer_delta* → orbs_ready → analysis_ready → done
  异常/取消 → error
先校验内容，再逐段呈现：answer_delta 只下发已通过后端校验的块。
"""
from __future__ import annotations

import json
import threading
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from . import analysis_service, logic, profiles, runtime
from .schemas import (ChatRequest, EV_ANSWER_DELTA, EV_ANALYSIS_READY,
                      EV_CLARIFICATION, EV_DONE, EV_ERROR, EV_ORBS_READY,
                      EV_REQUEST_STARTED, EV_STATUS)

router = APIRouter(prefix="/api/v1")

# 活动请求（取消标志）：进程内状态，重启即失效（可接受，不影响已保存分析）
ACTIVE_REQUESTS: dict[str, dict] = {}
_lock = threading.Lock()


def _set_cancel(request_id: str):
    with _lock:
        ACTIVE_REQUESTS[request_id] = {"cancelled": True}


def _is_cancelled(request_id: str) -> bool:
    with _lock:
        return bool(ACTIVE_REQUESTS.get(request_id, {}).get("cancelled"))


def _sse(name: str, payload: dict, request_id: str) -> str:
    payload = dict(payload)
    payload["request_id"] = request_id
    return f"event: {name}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _user(request: Request) -> dict:
    user = runtime.authenticate(request.headers.get("authorization"))
    if not user:
        raise HTTPException(401, "需要 Authorization: Bearer <token>（演示令牌见文档）")
    return user


# ---------------- 会话存取 ----------------

def _session_row(session_id: str, user: dict) -> dict | None:
    con = runtime.get_conn()
    row = con.execute("SELECT * FROM sessions WHERE session_id=? AND user_id=?",
                      (session_id, user["user_id"])).fetchone()
    if not row:
        return None
    cols = [d[0] for d in con.execute("SELECT * FROM sessions LIMIT 0").description]
    return dict(zip(cols, row))


def _get_or_create_session(user: dict, session_id: str | None) -> dict:
    con = runtime.get_conn()
    if session_id:
        s = _session_row(session_id, user)
        if s:
            return s
    sid = runtime.new_id("ses")
    con.execute(
        "INSERT INTO sessions(session_id,user_id,created_at,updated_at,"
        " current_scode,current_year,context_version,state)"
        " VALUES(?,?,?,?,?,?,0,'{}')",
        (sid, user["user_id"], runtime._now(), runtime._now(), None, None))
    con.commit()
    return _session_row(sid, user)


def _update_context(session: dict, page: dict | None) -> dict:
    """页面上下文只接受服务端可验证的值；无该年度数据不静默换年。"""
    con = runtime.get_conn()
    scode, year = session.get("current_scode"), session.get("current_year")
    if page:
        if "scode" in page and page["scode"] is None:
            scode = None
        if "year" in page and page["year"] is None:
            year = None
        if page.get("scode"):
            s = str(page["scode"]).zfill(6)
            if s in logic._coname_map():
                scode = s
        if page.get("year") is not None:
            try:
                y = int(page["year"])
                if y in logic.years():
                    year = y
            except (TypeError, ValueError):
                pass
    con.execute(
        "UPDATE sessions SET current_scode=?, current_year=?, updated_at=?,"
        " context_version=context_version+1 WHERE session_id=?",
        (scode, year, runtime._now(), session["session_id"]))
    con.commit()
    return {"scode": scode, "year": year, "snapshot_id": runtime.get_snapshot()}


def _load_history(session: dict, limit: int = 12) -> list[dict]:
    con = runtime.get_conn()
    rows = con.execute(
        "SELECT role, content, intent, request_id FROM messages WHERE session_id=?"
        " ORDER BY seq DESC LIMIT ?", (session["session_id"], limit)).fetchall()
    return [{"role": r[0], "content": r[1], "intent": r[2], "request_id": r[3]}
            for r in reversed(rows)]


def _load_state(session: dict) -> dict:
    con = runtime.get_conn()
    row = con.execute("SELECT state FROM sessions WHERE session_id=?",
                      (session["session_id"],)).fetchone()
    try:
        return json.loads(row[0]) if row and row[0] else {}
    except ValueError:
        return {}


def _save_state(session_id: str, state: dict):
    con = runtime.get_conn()
    con.execute("UPDATE sessions SET state=? WHERE session_id=?",
                (json.dumps(state or {}, ensure_ascii=False), session_id))
    con.commit()


def _append_message(session_id: str, request_id: str, role: str,
                    content: str, intent: str | None = None):
    con = runtime.get_conn()
    con.execute(
        "INSERT INTO messages(session_id,request_id,role,content,intent,created_at)"
        " VALUES(?,?,?,?,?,?)",
        (session_id, request_id, role, content[:2000], intent, runtime._now()))
    con.commit()


# ---------------- SSE 主流程 ----------------

def _chat_stream(user: dict, body: dict):
    request_id = runtime.new_id("req")
    _lock.acquire()
    ACTIVE_REQUESTS[request_id] = {"cancelled": False}
    _lock.release()

    session = _get_or_create_session(user, body.get("session_id"))
    session_id = session["session_id"]
    page = _update_context(session, body.get("page_context"))
    message = (body.get("message") or "").strip()[:4000]
    client_request_id = body.get("client_request_id") or request_id
    prefs = runtime.get_preferences(user["user_id"])
    if body.get("preferences"):
        prefs = {**prefs, **{k: v for k, v in body["preferences"].items() if v is not None}}

    yield _sse(EV_REQUEST_STARTED, {
        "session_id": session_id, "client_request_id": client_request_id,
        "context": page,
        # 引擎在分析阶段才真正决议：这里只回报「将优先尝试的引擎」（仅按配置推断）。
        # 此前该字段写死为 "coze"，导致降级到规则引擎、或实际走 langgraph 时都会误报。
        # 真实生效引擎请看 analysis_ready.engine 与持久化记录的 engine 字段。
        "engine": analysis_service.planned_engine(),
        "engine_resolved": False,
    }, request_id)

    try:
        yield _sse(EV_STATUS, {"phase": "querying", "text": "查询中：受控工具检索事实与证据"}, request_id)
        if _is_cancelled(request_id):
            yield _sse(EV_ERROR, {"code": "cancelled", "message": "请求已取消"}, request_id)
            return
        history = _load_history(session)
        state = _load_state(session)
        yield _sse(EV_STATUS, {"phase": "analyzing",
                               "text": "分析中：结合企业证据包与产品资料形成分析草稿"}, request_id)
        result = analysis_service.prepare_analysis(
            message, user, page, prefs, history, state, request_id)

        if result.get("clarify"):
            _append_message(session_id, request_id, "user", message, "clarify")
            _append_message(session_id, request_id, "assistant", result["message"], "clarify")
            yield _sse(EV_CLARIFICATION, {"options": result.get("options"),
                                          "message": result["message"],
                                          "context": page}, request_id)
            yield _sse(EV_DONE, {"analysis_id": None}, request_id)
            return

        if _is_cancelled(request_id):
            yield _sse(EV_ERROR, {"code": "cancelled", "message": "请求已取消（上游可能仍计费）"}, request_id)
            return

        analysis = result["analysis"]
        analysis_id = analysis["analysis_id"]
        _update_context(session, analysis.get("context"))
        yield _sse(EV_STATUS, {"phase": "validating",
                               "text": "校验中：引用、年度与产品资格检查"}, request_id)
        if result.get("issues"):
            warnings = list(analysis.get("warnings") or [])
            warnings.append("后端校验注记：" + "；".join(
                f"[{i['code']}] {i['message']}" for i in result["issues"][:4]))
            analysis["warnings"] = warnings

        # 逐段呈现（已校验内容）
        for i, block in enumerate(analysis.get("answer_blocks", [])):
            if _is_cancelled(request_id):
                yield _sse(EV_ERROR, {"code": "cancelled", "message": "请求已取消"}, request_id)
                return
            yield _sse(EV_ANSWER_DELTA, {
                "index": i, "kind": block.get("kind", "fact"),
                "text": block.get("text", ""), "refs": block.get("refs", []),
            }, request_id)

        yield _sse(EV_ORBS_READY, {
            "orbs": analysis.get("orbs", []),
            "context": analysis.get("context"),
        }, request_id)

        yield _sse(EV_ANALYSIS_READY, {
            "analysis_id": analysis_id,
            "status": analysis.get("status"),
            "recommendations": analysis.get("recommendations", []),
            "questions": analysis.get("questions", []),
            "warnings": analysis.get("warnings", []),
            "engine": result.get("engine"),
            "context": analysis.get("context"),
        }, request_id)

        _append_message(session_id, request_id, "user", message)
        summary = (analysis.get("answer_blocks") or [{}])[0].get("text", "")[:600]
        _append_message(session_id, request_id, "assistant", summary)
        if result.get("state"):
            _save_state(session_id, result["state"])
        yield _sse(EV_DONE, {"analysis_id": analysis_id}, request_id)
    except Exception as e:  # 网关兜底：不让对话静默消失
        yield _sse(EV_ERROR, {"code": "gateway_error",
                              "message": f"处理失败：{type(e).__name__}",
                              "retryable": True}, request_id)


# ---------------- 接口 ----------------

@router.post("/chat/stream")
async def chat_stream(request: Request):
    user = _user(request)
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "请求体必须是 JSON（见 /api/v1 协议样例）")
    if not body.get("message") or not body.get("client_request_id"):
        raise HTTPException(400, "message 与 client_request_id 必填")
    return StreamingResponse(
        _chat_stream(user, body),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no",
                 "Connection": "keep-alive"})


@router.post("/chat/requests/{request_id}/cancel")
def cancel_request(request_id: str, request: Request):
    user = _user(request)
    _set_cancel(request_id)
    return {"ok": True, "request_id": request_id,
            "note": "取消显示与本地编排；上游不支持取消时只丢弃后续结果，可能仍计费。"}


@router.get("/chat/sessions/{session_id}")
def get_session(session_id: str, request: Request):
    user = _user(request)
    s = _session_row(session_id, user)
    if not s:
        raise HTTPException(404, "会话不存在或不属于当前用户")
    messages = _load_history(s, limit=50)
    con = runtime.get_conn()
    for message in messages:
        if message['role'] != 'assistant':
            continue
        row = con.execute(
            "SELECT analysis_id FROM analyses WHERE request_id=? AND user_id=? ORDER BY created_at DESC LIMIT 1",
            (message['request_id'], user['user_id'])).fetchone()
        question = con.execute(
            "SELECT content FROM messages WHERE session_id=? AND request_id=? AND role='user' ORDER BY seq LIMIT 1",
            (session_id, message['request_id'])).fetchone()
        if row:
            message['analysis_id'] = row[0]
            message['question'] = question[0] if question else ''
    return {
        "session_id": s["session_id"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "context": {"scode": s["current_scode"], "year": s["current_year"],
                    "snapshot_id": runtime.get_snapshot()},
        "context_version": s["context_version"],
        "messages": messages,
    }


@router.get("/analyses/{analysis_id}")
def get_analysis(analysis_id: str, request: Request):
    user = _user(request)
    a = analysis_service.get_analysis(analysis_id, user)
    if not a:
        raise HTTPException(404, "分析不存在或不属于当前用户")
    return {"analysis_id": a["analysis_id"], "status": a["status"],
            "scode": a["scode"], "year": a["year"],
            "snapshot_id": a["snapshot_id"], "engine": a["engine"],
            "workflow_version": a["workflow_version"], "draft": a["draft"],
            "question": a.get("question", "")}


@router.get("/references/{ref_id}")
def get_reference(ref_id: str, request: Request):
    user = _user(request)
    from . import references
    r = references.resolve_ref(ref_id, user)
    if not r.get("ok"):
        status = 403 if r.get("code") == "forbidden" else 404
        raise HTTPException(status, r.get("error", "引用不可用"))
    return r


class BriefingBody(BaseModel):
    analysis_id: str
    title: Optional[str] = None


@router.post("/briefings")
def post_briefing(body: BriefingBody, request: Request):
    user = _user(request)
    b = analysis_service.build_briefing(body.analysis_id, user, body.title)
    if not b:
        raise HTTPException(404, "分析不存在或不属于当前用户")
    return b


@router.get("/me/preferences")
def get_preferences(request: Request):
    user = _user(request)
    return {"preferences": profiles.get_preferences(user),
            "note": "偏好只影响候选服务与方案长度，不改写企业事实、不跨越数据权限。"}


@router.patch("/me/preferences")
async def patch_preferences(request: Request):
    user = _user(request)
    patch = await request.json()
    return {"preferences": profiles.patch_preferences(user, patch)}


@router.get("/me/capabilities")
def get_capabilities(request: Request):
    user = _user(request)
    return profiles.capabilities(user)


class FeedbackBody(BaseModel):
    analysis_id: Optional[str] = None
    request_id: Optional[str] = None
    category: str
    comment: str


@router.post("/feedback")
def post_feedback(body: FeedbackBody, request: Request):
    user = _user(request)
    if body.category not in ("data_error", "unreasonable", "outdated_material", "ux"):
        raise HTTPException(400, "category 必须是 data_error|unreasonable|outdated_material|ux")
    con = runtime.get_conn()
    con.execute(
        "INSERT INTO feedback(user_id,analysis_id,request_id,category,comment,created_at)"
        " VALUES(?,?,?,?,?,?)",
        (user["user_id"], body.analysis_id, body.request_id, body.category,
         body.comment[:1000], runtime._now()))
    con.commit()
    return {"ok": True, "note": "反馈已记录（数据错误/分析不合理/资料过时/体验问题分类）。"}
