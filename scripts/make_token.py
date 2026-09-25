# -*- coding: utf-8 -*-
"""生成 Coze 插件试跑用的 context_token（调试工具，不用于生产）。

为什么需要它：
    插件页的「试运行」是绕过工作流直接调用插件，没有开始节点变量可以引用，
    因此 X-Context-Token 必须手工粘贴一个真实可用的 token 值。
    工作流正式运行时则相反——由开始节点的 context_token 变量自动传入，
    不需要（也不应该）手工粘贴。

用法（Windows PowerShell）：
    $env:TOOL_CONTEXT_SECRET='与 Railway 一致的值'
    python -X utf8 scripts/make_token.py                                    # 默认 7 天、全部工具
    python -X utf8 scripts/make_token.py --tools resolve_company,get_company_context
    python -X utf8 scripts/make_token.py --base-url https://<你的域名>        # 顺便冒烟验证

说明：
    - 生产环境的 token 由后端每轮签发（TTL 600 秒）；本脚本 TTL 可自定义，仅用于调试。
    - token 携带 snapshot_id：若与线上运行快照不一致，会返回 409（数据版本漂移保护）。
    - token 携带 allowed_tools：不在清单内的工具返回 403。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import context_token, runtime, tools  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="生成插件试跑用的 context_token")
    ap.add_argument("--secret", default=os.environ.get("TOOL_CONTEXT_SECRET", ""),
                    help="签名密钥，默认取环境变量 TOOL_CONTEXT_SECRET（须与服务端一致）")
    ap.add_argument("--tools", default=",".join(tools.TOOL_REGISTRY.keys()),
                    help="允许的工具名，逗号分隔；默认全部")
    ap.add_argument("--regions", default="region_a",
                    help="绑定辖区，逗号分隔；决定地区资料可见范围")
    ap.add_argument("--user", default="u_demo_a", help="绑定的用户ID（演示身份）")
    ap.add_argument("--ttl", type=int, default=7 * 24 * 3600,
                    help="有效期秒数，默认 604800（7天，仅为调试方便；生产用 600）")
    ap.add_argument("--snapshot", default=None,
                    help="覆盖数据快照ID，默认取本地 kb 内容哈希（须与线上一致）")
    ap.add_argument("--from-url", default=None,
                    help="从该服务的 /api/health 取 snapshot_id（推荐：避免与线上快照不一致导致 409）")
    ap.add_argument("--base-url", default=None,
                    help="可选：给定服务地址后立即用该 token 冒烟调用一次")
    args = ap.parse_args()

    if not args.secret:
        print("[错误] 未提供密钥。请设置环境变量 TOOL_CONTEXT_SECRET 或用 --secret 指定。",
              file=sys.stderr)
        print("       该值必须与部署侧（Railway Variables）完全一致，否则一律 403。",
              file=sys.stderr)
        return 2

    allowed = [t.strip() for t in args.tools.split(",") if t.strip()]
    unknown = [t for t in allowed if t not in tools.TOOL_REGISTRY]
    if unknown:
        print(f"[错误] 未知工具：{unknown}\n可用：{sorted(tools.TOOL_REGISTRY)}", file=sys.stderr)
        return 2

    regions = [r.strip() for r in args.regions.split(",") if r.strip()]
    live_url = args.from_url or args.base_url
    snapshot = args.snapshot
    snapshot_src = "命令行指定"
    if not snapshot and live_url:
        try:
            # probe=0：本脚本只需要 snapshot_id，跳过 /api/health 的引擎真实探活，
            # 避免把脚本耗时与引擎可用性绑定。
            with urllib.request.urlopen(
                    live_url.rstrip("/") + "/api/health?probe=0", timeout=20) as r:
                snapshot = json.loads(r.read()).get("snapshot_id")
            snapshot_src = f"取自 {live_url} 的 /api/health"
        except Exception as e:  # noqa: BLE001
            print(f"[警告] 无法从 {live_url} 读取快照（{e}），改用本地快照。", file=sys.stderr)
    if not snapshot:
        snapshot = runtime.get_snapshot()
        snapshot_src = "本地 kb 内容哈希（若与线上不一致会返回 409）"
    token = context_token.sign_context_token({
        "user_id": args.user,
        "display_name": "插件试跑（调试令牌）",
        "regions": regions,
        "snapshot_id": snapshot,
        "allowed_tools": allowed,
    }, args.secret, ttl_seconds=args.ttl)

    print("=" * 72)
    print("X-Context-Token（复制整行，粘进插件试跑的参数框）")
    print("=" * 72)
    print(token)
    print("-" * 72)
    print(f"用户        : {args.user}")
    print(f"辖区        : {regions}")
    print(f"数据快照    : {snapshot}")
    print(f"快照来源    : {snapshot_src}")
    print(f"允许工具    : {', '.join(allowed)}")
    print(f"有效期      : {args.ttl} 秒（约 {args.ttl / 3600:.1f} 小时）")
    print("-" * 72)
    print("curl 自测（把 <域名> 换成你的服务地址）：")
    print(f"""curl -s -X POST https://<域名>/api/v1/tools/resolve_company \\
  -H "X-Context-Token: {token[:32]}..." \\
  -H "Content-Type: application/json" \\
  -d '{{"query":"002860"}}'""")
    print("=" * 72)

    if args.base_url:
        base = args.base_url.rstrip("/")
        print(f"[冒烟] 调用 {base}/api/v1/tools/resolve_company ...")
        body = json.dumps({"query": "002860"}).encode("utf-8")
        req = urllib.request.Request(
            base + "/api/v1/tools/resolve_company", data=body,
            headers={"X-Context-Token": token, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                data = json.loads(r.read())
            print("[冒烟] ✅ 成功：", data.get("matches", [{}])[0].get("coname"))
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:200]
            print(f"[冒烟] ❌ HTTP {e.code}：{detail}")
            if e.code == 403:
                print("        → 密钥不一致、token 过期，或工具不在 allowed_tools 清单内")
            elif e.code == 409:
                print("        → snapshot_id 与线上不一致（两侧 kb 文件不同版本）")
            elif e.code == 503:
                print("        → 服务端未配置 TOOL_CONTEXT_SECRET")
            return 1
        except Exception as e:  # noqa: BLE001
            print(f"[冒烟] ❌ 无法连接：{e}")
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
