# -*- coding: utf-8 -*-
"""生成式引擎冷启动容错验收。

背景（线上真实故障）：扣子编程部署在**无访问流量时会把服务缩容至 0 个实例**
（官方文档明示）。缩容后首次访问要等实例重新拉起，导致：

1. `/api/health` 的探活（当时超时上限只有 5 秒）超时，被报成「引擎不可用」，
   演示前给出**假红灯**；
2. 首次真实提问撞上冷启动而**立刻降级**，回答正文里插入
   「LangGraph 引擎不可用（timeout…）」——评委一眼就读成「系统坏了」。

本文件锁住修复后的行为：

- 超时判为 `warming`（冷启动中），与「配置错误」「实例被回收」区分开；
- 瞬时类错误自动重试一次，冷启动不再直接降级；
- 降级文案中性化，不把技术故障写进回答正文；
- 配置类错误**仍然**给出可执行的修复提示（不能被中性化吞掉）；
- 保活任务确实会周期性唤醒引擎，从根上避免缩容到 0。
"""
import asyncio
import json
import os
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from server import analysis_service, langgraph_client, runtime

STATE = {
    "get_delay": 0.0,        # GET（探活）前故意拖多久，用来模拟网关等待实例唤醒
    "get_status": 200,
    "get_body": '{"status":"ok"}',
    "get_count": 0,
    "post_script": None,     # 依次消费的状态码列表；None 表示固定用 post_status
    "post_status": 200,
    "post_count": 0,
    "post_body": {},
}


def _draft() -> dict:
    return {
        "answer_blocks": [
            {"kind": "fact", "text": "星帅尔（002860）2023 年度处于出海扩张期。", "refs": []},
        ],
        "recommendations": [],
        "questions": [],
        "warnings": [],
    }


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        STATE["get_count"] += 1
        delay = STATE.get("get_delay") or 0.0
        if delay:
            time.sleep(delay)          # 模拟冷启动：网关挂住请求等实例拉起
        body = (STATE.get("get_body") or '{"status":"ok"}').encode("utf-8")
        try:
            self.send_response(STATE.get("get_status", 200))
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            # 客户端已因探活超时断开——这正是被测场景，不是错误
            pass

    def do_POST(self):  # noqa: N802
        n = int(self.headers.get("Content-Length", 0) or 0)
        if n:
            self.rfile.read(n)
        STATE["post_count"] += 1
        script = STATE.get("post_script")
        if script:
            status = script.pop(0)
        else:
            status = STATE.get("post_status", 200)
        if status == 200:
            payload = STATE.get("post_body") or {"result": json.dumps(_draft(), ensure_ascii=False)}
        else:
            payload = {"error_code": "instance_not_found", "error_message": "sandbox waking up"}
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


class TestEngineColdStart(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        runtime.init_runtime()
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.port}"
        cls.user = runtime.authenticate("Bearer demo-token-region-a")

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def setUp(self):
        self._env = {k: os.environ.get(k) for k in
                     ("AI_ENGINE", "LANGGRAPH_BASE_URL", "AI_ENABLED",
                      "TOOL_CONTEXT_SECRET", "COZE_WORKFLOW_ID")}
        self._retry_delay = analysis_service.COLD_START_RETRY_DELAY_SECONDS
        os.environ["AI_ENGINE"] = "langgraph"
        os.environ["LANGGRAPH_BASE_URL"] = self.base
        os.environ["AI_ENABLED"] = "1"
        os.environ["TOOL_CONTEXT_SECRET"] = "unit-test-secret"
        os.environ.pop("COZE_WORKFLOW_ID", None)
        analysis_service.COLD_START_RETRY_DELAY_SECONDS = 0     # 测试不真等
        STATE.update({"get_delay": 0.0, "get_status": 200, "get_body": '{"status":"ok"}',
                      "get_count": 0, "post_script": None, "post_status": 200,
                      "post_count": 0, "post_body": {}})
        analysis_service.reset_engine_probe_cache()

    def tearDown(self):
        analysis_service.COLD_START_RETRY_DELAY_SECONDS = self._retry_delay
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def _analyze(self, req="这家公司值得关注什么"):
        return analysis_service.prepare_analysis(
            req, self.user, {"scode": "002860", "year": 2023},
            runtime.get_preferences(self.user["user_id"]), [], {}, "t_cold")

    # ---- 1) 超时 = 冷启动，不再等于「引擎坏了」 ----
    def test_probe_timeout_reports_warming_not_broken(self):
        STATE["get_delay"] = 2.0            # 网关挂住 > 探活超时
        p = langgraph_client.probe(timeout=1)
        self.assertTrue(p["warming"], "超时必须判为冷启动 warming")
        self.assertEqual(p["error_code"], "warming")
        self.assertFalse(p["reachable"], "此刻确实不可用，reachable 不应报绿")
        self.assertIn("冷启动", p["detail"])
        self.assertNotIn("不可用", p["detail"], "冷启动文案不应让读者以为服务坏了")

    def test_probe_engine_surfaces_warming_flag(self):
        STATE["get_delay"] = 2.0
        st = analysis_service.probe_engine("langgraph", ttl_seconds=0, timeout=1)
        self.assertTrue(st["warming"])
        self.assertEqual(st["probe_error"], "warming")

    def test_auth_failure_is_not_warming(self):
        """鉴权失败说明服务活着，不能混进冷启动语义。"""
        STATE.update({"get_status": 401, "get_body": '{"msg":"Missing authorization header."}'})
        p = langgraph_client.probe(timeout=5)
        self.assertFalse(p["warming"])
        self.assertTrue(p["reachable"])
        self.assertFalse(p["auth_ok"])

    def test_recycled_instance_is_not_warming(self):
        """实例被回收（instance_not_found）是另一类故障，不能报成 warming。"""
        STATE.update({"get_status": 404,
                      "get_body": '{"error_code":"instance_not_found"}'})
        p = langgraph_client.probe(timeout=5)
        self.assertFalse(p["warming"])
        self.assertFalse(p["reachable"])
        self.assertEqual(p["error_code"], "instance_gone")

    # ---- 2) 冷启动自动重试：首次失败不再直接降级 ----
    def test_cold_start_retry_recovers_without_degrading(self):
        """第一次调用撞冷启动（503），重试命中热实例 → 仍走生成式引擎。"""
        STATE["post_script"] = [503, 200]
        res = self._analyze()
        self.assertEqual(res["engine"], "langgraph",
                         "冷启动后重试成功，不应降级到 rules-demo")
        self.assertEqual(STATE["post_count"], 2, "应恰好重试一次")
        warns = res["analysis"]["warnings"]
        self.assertFalse(any("不可用" in w for w in warns),
                         f"重试成功后不应残留降级告警：{warns}")

    def test_retry_happens_on_5xx_and_network_class_errors(self):
        """瞬时类错误码必须覆盖 5xx 与实例回收，冷启动才兜得住。"""
        for code in ("warming", "timeout", "network_error",
                     "instance_gone", "http_502", "http_503", "http_504"):
            self.assertIn(code, langgraph_client.COLD_START_ERROR_CODES,
                          f"{code} 应判为瞬时错误并触发重试")
        # 配置类错误不重试（重试无意义，还会掩盖真实问题）
        for code in ("bad_base_url", "not_api_url", "no_base_url", "http_500"):
            self.assertNotIn(code, langgraph_client.COLD_START_ERROR_CODES)

    # ---- 3) 重试仍失败 → 中性文案，不吓到评委 ----
    def test_persistent_transient_failure_uses_neutral_note(self):
        STATE["post_status"] = 503
        res = self._analyze()
        self.assertEqual(res["engine"], "rules-demo")
        self.assertEqual(STATE["post_count"], 2, "应重试一次后才降级")
        warns = res["analysis"]["warnings"]
        joined = " ".join(warns)
        self.assertIn("LangGraph", joined, "告警仍需保留引擎名，便于运维定位")
        self.assertIn("尚未就绪", joined, "应使用中性表述")
        self.assertNotIn("不可用", joined, "不得把「不可用」写进回答正文")
        self.assertTrue(res["analysis"]["answer_blocks"], "降级后仍须给出可用回答")

    # ---- 4) 配置类错误仍要给出可执行提示（不能被中性化吞掉） ----
    def test_config_error_keeps_actionable_hint(self):
        os.environ["LANGGRAPH_BASE_URL"] = "not-a-url"
        res = self._analyze()
        self.assertEqual(res["engine"], "rules-demo")
        joined = " ".join(res["analysis"]["warnings"])
        self.assertIn("LangGraph", joined)
        self.assertIn("http://", joined, "配置错误必须给出可执行的修复提示")

    def test_config_error_is_not_retried(self):
        os.environ["LANGGRAPH_BASE_URL"] = "not-a-url"
        self._analyze()
        self.assertEqual(STATE["post_count"], 0, "地址不合法不应发起任何请求")

    # ---- 5) 保活任务确实周期性唤醒引擎（根治缩容到 0） ----
    def test_keepalive_loop_repeatedly_pings_engine(self):
        from server import main as srv_main
        srv_main.KEEPALIVE_INITIAL_DELAY_SECONDS = 0.05
        srv_main.KEEPALIVE_INTERVAL_SECONDS = 0.2

        async def run_briefly():
            task = asyncio.create_task(srv_main._engine_keepalive_loop())
            await asyncio.sleep(0.8)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        asyncio.run(run_briefly())
        self.assertGreaterEqual(STATE["get_count"], 2,
                                "保活任务应发出多次探活，避免实例缩容到 0")

    def test_keepalive_skips_when_no_engine_configured(self):
        """未配置生成式引擎（纯本地规则）时不该空跑保活。"""
        from server import main as srv_main
        os.environ.pop("LANGGRAPH_BASE_URL", None)
        os.environ.pop("AI_ENABLED", None)
        os.environ.pop("AI_ENGINE", None)
        srv_main.KEEPALIVE_INITIAL_DELAY_SECONDS = 0.05
        srv_main.KEEPALIVE_INTERVAL_SECONDS = 0.2

        async def run_briefly():
            task = asyncio.create_task(srv_main._engine_keepalive_loop())
            await asyncio.sleep(0.6)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        asyncio.run(run_briefly())
        self.assertEqual(STATE["get_count"], 0, "无引擎配置时不应发探活请求")

    # ---- 6) 配置笔误不能让服务起不来 ----
    def test_bad_env_number_falls_back_to_default(self):
        """数值型环境变量被写成 "5m" 之类时，必须退回默认值而不是让 import 抛异常。"""
        from server import main as srv_main
        os.environ["ENGINE_KEEPALIVE_INTERVAL"] = "5m"
        try:
            self.assertEqual(srv_main._env_number("ENGINE_KEEPALIVE_INTERVAL", 240.0), 240.0)
            self.assertEqual(analysis_service._env_number(
                "ENGINE_KEEPALIVE_INTERVAL", 20, int), 20)
        finally:
            os.environ.pop("ENGINE_KEEPALIVE_INTERVAL", None)

    def test_blank_env_number_uses_default(self):
        from server import main as srv_main
        for blank in ("", "   "):
            os.environ["ENGINE_KEEPALIVE_INTERVAL"] = blank
            try:
                self.assertEqual(srv_main._env_number("ENGINE_KEEPALIVE_INTERVAL", 240.0), 240.0)
            finally:
                os.environ.pop("ENGINE_KEEPALIVE_INTERVAL", None)

    def test_valid_env_number_is_honoured(self):
        from server import main as srv_main
        os.environ["ENGINE_KEEPALIVE_INTERVAL"] = " 120 "
        try:
            self.assertEqual(srv_main._env_number("ENGINE_KEEPALIVE_INTERVAL", 240.0), 120.0)
        finally:
            os.environ.pop("ENGINE_KEEPALIVE_INTERVAL", None)


if __name__ == "__main__":
    unittest.main()
