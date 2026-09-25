# -*- coding: utf-8 -*-
"""本地桩引擎（开发联调用）：模拟扣子编程 LangGraph 引擎的 /run 接口。

用途：在没有扣子环境（或那个项目还没部署）时，先把数智链海的「AI 引擎」链路联调通。
用法：
    python -X utf8 scripts/stub_engine.py --port 5001
    # 然后在数智链海侧配置：
    #   AI_ENGINE=langgraph
    #   LANGGRAPH_BASE_URL=http://127.0.0.1:5001
    #   AI_ENABLED=1

行为：POST /run 收到入参后，回一个符合 analysis_draft 契约的草稿（含 message 与
page_context 回显，便于确认参数确实透传到了引擎）；GET /health 返回 ok。
"""
from __future__ import annotations

import argparse
import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def _draft(params: dict) -> dict:
    page = params.get("page_context") or {}
    scode = page.get("scode") or "（未指定企业）"
    year = page.get("year") or "（未指定年度）"
    message = params.get("message", "")
    prefs = params.get("preferences") or {}
    focus = "、".join(prefs.get("service_focus") or []) or "全量"
    return {
        "schema_version": "1.0",
        "answer_blocks": [
            {"kind": "fact",
             "text": f"【桩引擎】企业 {scode} 在 {year} 年度处于出海扩张期（筹备层）。"
                     f"（这里回显你的问题：{message}）",
             "refs": []},
            {"kind": "hypothesis",
             "text": f"【桩引擎】按偏好「{focus}」推断，若其市场开拓方向落地，"
                     "预计产生开户与结算类需求；需与客户确认。",
             "refs": []},
            {"kind": "note",
             "text": "以上内容由本地桩引擎生成，仅用于验证链路；接上真实引擎后会被真实分析替换。",
             "refs": []},
        ],
        "recommendations": [{
            "id": "rec_settlement", "product_ref": "product:settlement",
            "priority": "discussion_first",
            "reason": "桩引擎示例理由：方向「市场开拓」命中结算类服务",
            "evidence_refs": [], "product_source_refs": ["product:settlement"],
            "eligibility": "unknown", "missing_conditions": ["跨境人民币结算账户是否已开立"],
        }],
        "questions": [{"text": "贵司人民币结算账户是否已开立？",
                       "related_recommendation": "rec_settlement"}],
        "warnings": ["桩引擎：非真实分析结果，仅用于联调。"],
        "context": {"scode": page.get("scode"), "year": page.get("year")},
        "provenance": {"engine": "stub", "workflow_version": "stub-1.0",
                       "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")},
    }


class Handler(BaseHTTPRequestHandler):
    def _send(self, payload: dict, status: int = 200):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):  # noqa: N802
        n = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(n) if n else b"{}"
        try:
            params = json.loads(raw.decode("utf-8"))
        except ValueError:
            self._send({"detail": "invalid json"}, 400)
            return
        print(f"[stub] /run message={params.get('message')!r} "
              f"page_context={params.get('page_context')} "
              f"token={'有' if params.get('context_token') else '无'}", flush=True)
        self._send({"result": json.dumps(_draft(params), ensure_ascii=False)})

    def do_GET(self):  # noqa: N802
        self._send({"status": "ok", "engine": "stub"})

    def log_message(self, *args):
        pass


def main() -> int:
    ap = argparse.ArgumentParser(description="本地桩引擎（联调用）")
    ap.add_argument("--port", type=int, default=5001)
    args = ap.parse_args()
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"[stub] 桩引擎已启动：http://127.0.0.1:{args.port}/run  （Ctrl+C 停止）", flush=True)
    srv.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
