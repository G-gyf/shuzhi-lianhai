# -*- coding: utf-8 -*-
"""分析服务：校验、保存、降级（方案第 8、12 章）。

- Coze 草稿与后端正式结果分开：后端生成 analysis_id、检查引用后构建光球。
- 硬性校验：schema、引用存在与权限、年度一致、产品资格标注；非法引用不生成光球。
- 引用存在不等于推断成立；修复失败时返回可核实部分（partial）或回退规则简报。
"""
from __future__ import annotations

import json
import time

from . import coze_client, local_engine, products, runtime, tools
from .schemas import ORB_KINDS, SCHEMA_VERSION, parse_ref

MAX_MAIN_ORBS = 5


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


# ---------------- 校验 ----------------

def validate_draft(draft: dict, ctx: dict, page: dict) -> tuple[dict, list[dict]]:
    """返回 (clean_draft, issues)。非法引用不生成光球；问题分级 block/warn。"""
    issues: list[dict] = []
    clean = dict(draft)
    clean["warnings"] = list(draft.get("warnings") or [])

    if draft.get("schema_version") != SCHEMA_VERSION:
        issues.append({"level": "warn", "code": "schema_version",
                       "message": f"schema_version={draft.get('schema_version')}，按 {SCHEMA_VERSION} 处理。"})

    for key in ("answer_blocks", "recommendations", "questions", "orbs"):
        if not isinstance(draft.get(key), list):
            issues.append({"level": "block", "code": f"{key}_type",
                           "message": f"{key} 必须是数组。"})
            clean[key] = []

    # 年度一致性：上下文中年度与页面上下文一致；历史/未来年度问题显式标注
    c = draft.get("context") or {}
    if c.get("scode"):
        c["scode"] = str(c["scode"]).zfill(6)
    if page.get("year") and c.get("year") and int(c["year"]) != int(page["year"]):
        issues.append({"level": "warn", "code": "year_mismatch",
                       "message": f"分析年度 {c['year']} 与页面上下文 {page['year']} 不一致，回答中应确认采用范围。"})
    if c.get("scode") and page.get("scode") and c["scode"] != page["scode"]:
        c["scode"] = page["scode"]
        issues.append({"level": "warn", "code": "scode_mismatch",
                       "message": "分析企业与页面上下文不一致，已按页面上下文校正。"})

    allowed_refs = _collect_valid_refs(draft, ctx)
    # 逐引用校验：非法引用从块/建议/光球中移除
    for kind in ("answer_blocks",):
        for b in clean.get(kind, []):
            b["refs"] = [r for r in (b.get("refs") or []) if r in allowed_refs
                         or _log_bad_ref(r, issues)]
    for r in clean.get("recommendations", []):
        r["evidence_refs"] = [x for x in (r.get("evidence_refs") or [])
                              if x in allowed_refs or _log_bad_ref(x, issues)]
        r["product_source_refs"] = [x for x in (r.get("product_source_refs") or [])
                                    if x in allowed_refs or _log_bad_ref(x, issues)]
        if r.get("product_ref") and r["product_ref"] not in allowed_refs:
            issues.append({"level": "block", "code": "bad_product_ref",
                           "message": f"推荐 {r.get('id')} 的产品引用非法：{r['product_ref']}"})
            r["product_ref"] = None
        if r.get("product_ref"):
            _check_eligibility(r, issues)

    clean_orbs = []
    for orb in clean.get("orbs", []):
        if orb.get("kind") not in ORB_KINDS:
            issues.append({"level": "warn", "code": "bad_orb_kind",
                           "message": f"光球类型非法：{orb.get('kind')}，已丢弃。"})
            continue
        if orb.get("ref_id"):
            if orb["ref_id"] in allowed_refs:
                clean_orbs.append(orb)
            else:
                issues.append({"level": "warn", "code": "bad_orb_ref",
                               "message": f"光球 {orb.get('id')} 引用非法，不生成该光球：{orb['ref_id']}"})
        else:
            clean_orbs.append(orb)
    clean["orbs"] = clean_orbs[:12]

    if not any(b.get("text") for b in clean.get("answer_blocks", [])):
        issues.append({"level": "block", "code": "empty_answer",
                       "message": "回答块为空。"})

    has_block = any(i["level"] == "block" for i in issues)
    clean["status"] = "partial" if has_block else "validated"
    return clean, issues


def _log_bad_ref(ref, issues) -> bool:
    issues.append({"level": "warn", "code": "bad_ref",
                   "message": f"引用不存在或无权访问，已移除：{ref}"})
    return False


def _check_eligibility(r: dict, issues: list):
    """产品资格硬性检查：placeholder 卡或条件不明时不得标 eligible。"""
    pid = (r.get("product_ref") or "").split(":", 1)[-1]
    card = products.get_card(pid)
    if not card:
        return
    if card["status"] == "placeholder" and r.get("eligibility") == "eligible":
        r["eligibility"] = "unknown"
        r["missing_conditions"] = list(dict.fromkeys(
            list(r.get("missing_conditions") or []) +
            [f"{card['name']} 产品卡未经资料核实（placeholder），不能标为已适配"]))
        issues.append({"level": "warn", "code": "placeholder_eligible",
                       "message": f"{r.get('id')} 将未核实产品卡标为 eligible，已降级为 unknown。"})


def _collect_valid_refs(draft: dict, ctx: dict) -> set:
    """收集所有合法引用（存在的、有权访问的）。"""
    valid: set[str] = set()
    all_refs: set[str] = set()
    for b in draft.get("answer_blocks", []):
        all_refs.update(b.get("refs") or [])
    for r in draft.get("recommendations", []):
        all_refs.update(r.get("evidence_refs") or [])
        all_refs.update(r.get("product_source_refs") or [])
        if r.get("product_ref"):
            all_refs.add(r["product_ref"])
    for o in draft.get("orbs", []):
        if o.get("ref_id"):
            all_refs.add(o["ref_id"])
    for ref in all_refs:
        if _ref_ok(ref, ctx):
            valid.add(ref)
    return valid


def _ref_ok(ref: str, ctx: dict) -> bool:
    parsed = parse_ref(ref)
    if not parsed:
        return False
    kind, parts = parsed
    try:
        if kind == "evidence":
            return tools.get_evidence(ctx, ref).get("ok")
        if kind == "product":
            return products.get_card(parts[0]) is not None
        if kind == "metric":
            table, scode, year, field = parts
            if table != "concentration" or field not in (
                    "CustomerConcentration", "PurchaseConcentration"):
                return False
            from . import sc as scdata
            val = scdata.concentration()
            sub = val[(val["scode"] == scode) & (val["year"] == int(year))]
            return not sub.empty
        if kind == "compare":
            con = runtime.get_conn()
            return con.execute("SELECT 1 FROM comparisons WHERE comparison_id=?",
                               (parts[0],)).fetchone() is not None
        if kind == "analysis":
            con = runtime.get_conn()
            return con.execute("SELECT 1 FROM analyses WHERE analysis_id=?",
                               (parts[0],)).fetchone() is not None
        if kind == "regional":
            from . import extensions
            return extensions.read_regional_doc(parts[0], parts[1],
                                                ctx["regions"]).get("ok")
        if kind == "company":
            from . import logic
            return str(parts[0]).zfill(6) in logic._coname_map()
    except Exception:
        return False
    return False


# ---------------- 持久化 ----------------

def persist(draft: dict, user: dict, request_id: str, session_id: str | None,
            engine: str, workflow_version: str, status: str | None = None) -> str:
    con = runtime.get_conn()
    analysis_id = runtime.new_id("an")
    c = draft.get("context") or {}
    refs: dict[str, dict] = {}
    seen: set[str] = set()
    for b in draft.get("answer_blocks", []):
        for r in b.get("refs") or []:
            seen.add(r)
    for r in draft.get("recommendations", []):
        seen.update(r.get("evidence_refs") or [])
        seen.update(r.get("product_source_refs") or [])
        if r.get("product_ref"):
            seen.add(r["product_ref"])
    for r in seen:
        kind = r.split(":", 1)[0]
        refs[r] = {"kind": kind}
    con.execute(
        "INSERT INTO analyses(analysis_id,user_id,request_id,session_id,scode,year,"
        " snapshot_id,product_version,engine,workflow_version,draft,status,created_at)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (analysis_id, user["user_id"], request_id, session_id,
         c.get("scode"), c.get("year"), runtime.get_snapshot(),
         products.product_version(), engine, workflow_version,
         json.dumps(draft, ensure_ascii=False), status or draft.get("status", "validated"),
         _now()))
    for ref, meta in refs.items():
        con.execute(
            "INSERT INTO analysis_refs(ref_id,analysis_id,kind,payload)"
            " VALUES(?,?,?,?)",
            (ref, analysis_id, meta["kind"], json.dumps({}, ensure_ascii=False)))
    con.commit()
    return analysis_id


def get_analysis(analysis_id: str, user: dict) -> dict | None:
    con = runtime.get_conn()
    row = con.execute(
        "SELECT draft, status, scode, year, snapshot_id, engine, workflow_version"
        " FROM analyses WHERE analysis_id=? AND user_id=?",
        (analysis_id, user["user_id"])).fetchone()
    if not row:
        return None
    draft = json.loads(row[0])
    return {"analysis_id": analysis_id, "status": row[1], "scode": row[2],
            "year": row[3], "snapshot_id": row[4], "engine": row[5],
            "workflow_version": row[6], "draft": draft}


def get_recommendation(analysis_id: str, recommendation_id: str,
                       user: dict) -> dict | None:
    a = get_analysis(analysis_id, user)
    if not a:
        return None
    for r in a["draft"].get("recommendations", []):
        if r.get("id") == recommendation_id:
            return {"analysis_id": analysis_id, "recommendation": r,
                    "context": a["draft"].get("context"),
                    "engine": a["engine"], "status": a["status"]}
    return None


def build_briefing(analysis_id: str, user: dict, title: str | None = None) -> dict:
    """从已保存 analysis_id 生成简报，不重新计算事实（验收用例 15）。"""
    a = get_analysis(analysis_id, user)
    if not a:
        return None
    d = a["draft"]
    c = d.get("context") or {}
    base_title = (f"{c.get('coname') or c.get('scode') or '企业'} 访前简报"
                  f"（{c.get('year')} 年度 · 对话分析）")
    sections = []
    facts = [b["text"] for b in d.get("answer_blocks", []) if b.get("kind") == "fact"]
    hyps = [b["text"] for b in d.get("answer_blocks", []) if b.get("kind") == "hypothesis"]
    prods = [b["text"] for b in d.get("answer_blocks", []) if b.get("kind") == "product"]
    checks = [b["text"] for b in d.get("answer_blocks", []) if b.get("kind") == "checklist"]
    if facts:
        sections.append({"heading": "一、企业事实依据", "body": "\n".join(facts),
                         "refs": [r for b in d.get("answer_blocks", [])
                                  if b.get("kind") == "fact" for r in b.get("refs", [])]})
    if hyps:
        sections.append({"heading": "二、需求假设（待与客户确认）", "body": "\n".join(hyps),
                         "refs": []})
    rec_lines = []
    rec_refs = []
    for r in d.get("recommendations", []):
        pid = (r.get("product_ref") or "").split(":", 1)[-1]
        card = products.get_card(pid) or {}
        name = card.get("name") or (r.get("id") or "建议")
        state = {"eligible": "条件已满足", "not_eligible": "不适用",
                 "unknown": "待确认"}.get(r.get("eligibility"), "待确认")
        line = f"{name}：{r.get('reason', '')}（{state}"
        if r.get("missing_conditions"):
            line += f"；待核实：{'、'.join(r['missing_conditions'])}"
        line += "）"
        rec_lines.append(line)
        rec_refs += r.get("product_source_refs", [])
    if rec_lines:
        sections.append({"heading": "三、候选服务与理由", "body": "\n".join(rec_lines),
                         "refs": rec_refs})
    if checks:
        sections.append({"heading": "四、待核实事项", "body": "\n".join(checks),
                         "refs": []})
    q_lines = [q["text"] for q in d.get("questions", [])]
    if q_lines:
        sections.append({"heading": "五、拜访问题清单",
                         "body": "\n".join(f"{i + 1}. {t}" for i, t in enumerate(q_lines)),
                         "refs": []})
    if d.get("warnings"):
        sections.append({"heading": "附、口径与演示说明",
                         "body": "\n".join(d["warnings"]), "refs": []})
    briefing = {
        "briefing_id": runtime.new_id("br"),
        "analysis_id": analysis_id,
        "title": title or base_title,
        "engine": a["engine"],
        "context": c,
        "sections": sections,
    }
    con = runtime.get_conn()
    con.execute(
        "INSERT INTO briefings(briefing_id,analysis_id,user_id,title,sections,created_at)"
        " VALUES(?,?,?,?,?,?)",
        (briefing["briefing_id"], analysis_id, user["user_id"], briefing["title"],
         json.dumps(sections, ensure_ascii=False), _now()))
    con.commit()
    return briefing


# ---------------- 编排 ----------------

def build_workflow_parameters(message: str, user: dict, page: dict, prefs: dict,
                              history: list[dict], cfg: dict) -> tuple[dict, str | None]:
    """组装传给 Coze 工作流的开始节点入参（方案 6 章 N01）。

    关键：每轮签发短期 context_token（绑定用户、地区、数据版本、允许工具），
    由工作流变量原样透传给插件请求，**不拼入模型提示词**（方案 5.2）。
    返回 (params, warning)。
    """
    from .context_token import sign_context_token

    warning = None
    snapshot = runtime.get_snapshot()
    allowed_tools = list(tools.TOOL_REGISTRY.keys())
    token = ""
    secret = cfg.get("tool_context_secret") or ""
    if secret:
        token = sign_context_token({
            "user_id": user["user_id"],
            "display_name": user.get("display_name", ""),
            "regions": list(user["regions"]),
            "snapshot_id": snapshot,
            "allowed_tools": allowed_tools,
            "request_id": "",
        }, secret, ttl_seconds=600)
    else:
        warning = ("未配置 TOOL_CONTEXT_SECRET，本轮 context_token 为空，"
                   "工作流插件调用将返回 503/403。")
    params = {
        "message": message,
        "page_context": {k: v for k, v in page.items() if v is not None},
        "history_summary": local_engine._history_summary(history),
        "preferences": prefs,
        "data_snapshot": snapshot,
        "product_version": products.product_version(),
        "max_tool_calls": cfg["max_tool_calls"],
        "max_compare_companies": cfg["max_compare_companies"],
        # 工作流开始节点需声明同名输入变量，插件 Header 引用它
        "context_token": token,
        "tools_base_url": cfg.get("tools_base_url") or "",
        "allowed_tools": allowed_tools,
    }
    return params, warning


def prepare_analysis(message: str, user: dict, page: dict, prefs: dict,
                     history: list[dict], state: dict, request_id: str) -> dict:
    """编排一次分析：Coze（若启用）或本地规则引擎 → 校验 → 持久化。

    返回 {"clarify": ...} 或 {"analysis": {...}, "issues": [...]}。
    """
    ctx = tools.build_context(user)
    cfg = coze_client.config()
    draft: dict | None = None
    engine, workflow_version, fallback_note = "rules-demo", "local-rules-v1", None

    if cfg["ai_enabled"]:
        try:
            params, token_warning = build_workflow_parameters(
                message, user, page, prefs, history, cfg)
            if token_warning:
                fallback_note = token_warning
            events = coze_client.stream_run(params, request_id)
            err = coze_client.extract_error(events)
            if err:
                raise coze_client.CozeError(err["code"], err["message"])
            out = coze_client.extract_workflow_output(events)
            if out:
                draft = out
                engine = "coze"
                workflow_version = cfg["workflow_id"]
        except coze_client.CozeError as e:
            fallback_note = f"Coze 工作流不可用（{e.code}：{e.message}），已降级为本地规则引擎演示输出。"
        except Exception as e:
            fallback_note = f"Coze 调用异常（{type(e).__name__}），已降级为本地规则引擎演示输出。"

    if draft is None:
        draft = local_engine.run(message, ctx, page, prefs, history, state, request_id)
        engine, workflow_version = "rules-demo", "local-rules-v1"

    if draft.get("clarify"):
        return {"clarify": True, "options": draft.get("options") or [],
                "message": draft.get("message", "请补充信息。")}

    # 移除引擎内部字段
    inner_state = draft.pop("_state", None)
    for b in draft.get("answer_blocks", []):
        b.pop("_refs_extra", None)
    clean, issues = validate_draft(draft, ctx, page)
    if fallback_note:
        clean["warnings"].insert(0, fallback_note)

    if not clean.get("orbs"):
        clean["orbs"] = _default_orbs(clean)
    clean["orbs"] = _mark_main_orbs(clean["orbs"])

    analysis_id = persist(clean, user, request_id, None, engine, workflow_version)
    clean["analysis_id"] = analysis_id
    return {"analysis": clean, "issues": issues, "engine": engine,
            "state": inner_state, "analysis_id": analysis_id}


def _default_orbs(draft: dict) -> list[dict]:
    """草稿未带光球时按合法引用补建（证据→产品→分析）。"""
    orbs = []
    evs = sorted({r for b in draft.get("answer_blocks", [])
                  for r in b.get("refs", []) if r.startswith("ev:")})
    for ev in evs[:3]:
        orbs.append({"id": f"orb_ev_{len(orbs)}", "kind": "evidence",
                     "label": "原文依据", "summary": "披露记录",
                     "ref_id": ev, "state": "ready"})
    for r in draft.get("recommendations", []):
        if r.get("product_ref"):
            orbs.append({"id": f"orb_pr_{r['id']}", "kind": "product",
                         "label": r["product_ref"].split(":", 1)[-1],
                         "summary": "产品依据", "ref_id": r["product_ref"],
                         "state": "ready"})
            if len(orbs) >= 5:
                break
    return orbs


def _mark_main_orbs(orbs: list[dict]) -> list[dict]:
    for i, o in enumerate(orbs):
        o["main"] = i < MAX_MAIN_ORBS
    return orbs
