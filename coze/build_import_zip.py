# -*- coding: utf-8 -*-
"""生成 coze.cn 可导入的工作流 ZIP 包。

用途：把「数智链海出海助手」工作流的骨架（开始节点变量、三个大模型节点提示词、
两个插件节点参数、结束节点输出）打包成 coze.cn「导入工作流」能识别的 ZIP，
省去在界面上逐个建节点、逐个粘提示词的工作。

格式依据（公开资料核对于 2026-09-25）：
- ZIP 目录契约：`Workflow-<NAME>-draft-<DIGITS>/MANIFEST.yml` + `workflow/<NAME>-draft.yaml`
- ZIP 字节需模仿 Go archive/zip 流式输出：无目录条目、local header flags=0x08
  （data descriptor 模式）、local/CD 的 time/date 全 0、CD 的 vmade=20、external_attr=0
- 工作流 YAML：`schema_version: 1.0.0` + `nodes` + `edges`，4 空格缩进，
  ID 用双引号字符串；节点间引用形如 `{path: <输出名>, ref_node: "<节点ID>"}`

导入后仍需在界面手工完成两件事（无法在文件中预置，因为 ID 属于各自空间）：
1. 给插件节点选择工作空间里的插件与工具；
2. 给大模型节点选择模型。
其余（变量、提示词、连线、变量引用、输出）已预置。

用法：
    python -X utf8 coze/build_import_zip.py            # 生成到 coze/import/
    python -X utf8 coze/build_import_zip.py --check    # 生成后校验结构与字节
"""
from __future__ import annotations

import argparse
import json
import struct
import sys
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROMPTS = ROOT / "coze" / "prompts"
OUT_DIR = ROOT / "coze" / "import"

NAME = "shuzhi_lianhai"
WORKFLOW_ID = "7585079438426600001"     # 占位；导入后台端会分配/覆盖
DESC = ("客户经理提问后，自动判断意图、查询企业事实与产品资料，输出带依据的分析与推荐。"
        "企业名称、数字与原文均来自受控数据库，不编造。")

ICON_START = ("https://lf3-static.bytednsdoc.com/obj/eden-cn/dvsmryvd_avi_dvsm/"
              "ljhwZthlaukjlkulzlp/icon/icon-Start-v2.jpg")
ICON_LLM = ("https://lf3-static.bytednsdoc.com/obj/eden-cn/dvsmryvd_avi_dvsm/"
            "ljhwZthlaukjlkulzlp/icon/icon-LLM-v2.jpg")
ICON_END = ("https://lf3-static.bytednsdoc.com/obj/eden-cn/dvsmryvd_avi_dvsm/"
            "ljhwZthlaukjlkulzlp/icon/icon-End-v2.jpg")
ICON_PLUGIN = ("https://lf3-static.bytednsdoc.com/obj/eden-cn/dvsmryvd_avi_dvsm/"
               "ljhwZthlaukjlkulzlp/icon/icon-Plugin-v2.jpg")


# ---------------- 工具函数 ----------------

def q(text: str) -> str:
    """YAML 双引号字符串转义。"""
    return '"' + str(text).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'


def load_prompt(filename: str) -> str:
    p = PROMPTS / filename
    if not p.exists():
        return ""
    return p.read_text(encoding="utf-8").strip()


# ---------------- 节点模板 ----------------

def start_node() -> str:
    """开始节点：11 个输入变量（2 个必填、9 个可选），名称与后端入参一致。"""
    required = {"message": "string", "context_token": "string"}
    optional = {
        "page_context": "object",
        "history_summary": "string",
        "preferences": "object",
        "data_snapshot": "string",
        "product_version": "string",
        "tools_base_url": "string",
        "allowed_tools": "list",
        "max_tool_calls": "integer",
        "max_compare_companies": "integer",
    }
    lines = [
        '    - id: "100001"',
        "      type: start",
        "      title: 开始",
        f"      icon: {ICON_START}",
        f'      description: {q("工作流起始节点：接收调用方传入的用户问题与上下文")}',
        "      position:",
        "        x: -1810",
        "        y: 0",
        "      parameters:",
        "        node_outputs:",
    ]
    for name, vtype in {**required, **optional}.items():
        lines += [
            f"            {name}:",
            f"                type: {vtype}",
            f"                required: {'true' if name in required else 'false'}",
            "                value: null",
        ]
    return "\n".join(lines)


def llm_node(nid: str, title: str, system_prompt: str, user_prompt: str,
             inputs: list[tuple[str, str, str]], x: int, y: int,
             description: str = "调用大语言模型,使用变量和提示词生成回复") -> str:
    """大模型节点。inputs: [(输入变量名, 引用节点ID, 引用输出名), ...]"""
    lines = [
        f'    - id: "{nid}"',
        "      type: llm",
        f"      title: {title}",
        f"      icon: {ICON_LLM}",
        f"      description: {q(description)}",
        '      version: "3"',
        "      position:",
        f"        x: {x}",
        f"        y: {y}",
        "      parameters:",
        "        fcParamVar:",
        "            knowledgeFCParam: {}",
        "        llmParam:",
    ]
    for name, itype, value in [
        ("apiMode", "integer", '"0"'),
        ("maxTokens", "integer", '"4096"'),
        ("spCurrentTime", "boolean", "false"),
        ("spAntiLeak", "boolean", "false"),
        ("responseFormat", "integer", '"2"'),   # 2 = JSON 输出
        ("modelName", "string", q("__请选择模型__")),
        ("modelType", "integer", '"0"'),
        ("generationDiversity", "string", "balance"),
        ("parameters", "object", "null"),
        ("prompt", "string", q(user_prompt)),
        ("enableChatHistory", "boolean", "false"),
        ("chatHistoryRound", "integer", '"3"'),
        ("systemPrompt", "string", q(system_prompt)),
        ("stableSystemPrompt", "string", '""'),
        ("canContinue", "boolean", "false"),
        ("loopPromptVersion", "string", '""'),
        ("loopPromptName", "string", '""'),
        ("loopPromptId", "string", '""'),
    ]:
        lines += [
            f"            - name: {name}",
            "              input:",
            f"                type: {itype}",
            f"                value: {value}",
        ]
    lines.append("        node_inputs:")
    for iname, ref_node, ref_path in inputs:
        lines += [
            f"            - name: {iname}",
            "              input:",
            "                type: string",
            "                value:",
            f"                    path: {ref_path}",
            f'                    ref_node: "{ref_node}"',
        ]
    lines += [
        "        node_outputs:",
        "            output:",
        "                type: string",
        "                value: null",
        "        settingOnError:",
        "            processType: 1",
        "            retryTimes: 0",
        "            switch: false",
        "            timeoutMs: 180000",
    ]
    return "\n".join(lines)


def plugin_node(nid: str, title: str, inputs: list[tuple[str, str, str | None]],
                x: int, y: int, description: str = "调用插件") -> str:
    """插件节点。inputs: [(参数名, 引用节点ID, 引用输出名或 None=空)]。

    插件 ID / 工具 ID 属于各自工作空间，无法预置 —— 导入后需在界面重新选择插件。
    """
    lines = [
        f'    - id: "{nid}"',
        "      type: plugin",
        f"      title: {title}",
        f"      icon: {ICON_PLUGIN}",
        f"      description: {q(description)}",
        "      position:",
        f"        x: {x}",
        f"        y: {y}",
        "      parameters:",
        "        apiParam:",
        "            - name: pluginID",
        "              input:",
        "                type: string",
        '                value: ""',
        "            - name: apiID",
        "              input:",
        "                type: string",
        '                value: ""',
        "            - name: pluginVersion",
        "              input:",
        "                type: string",
        '                value: ""',
        "        node_inputs:",
    ]
    for iname, ref_node, ref_path in inputs:
        lines += [
            f"            - name: {iname}",
            "              input:",
            "                type: string",
            "                value:",
        ]
        if ref_path is None:
            lines += ["                    content: \"\""]
        else:
            lines += [
                f"                    path: {ref_path}",
                f'                    ref_node: "{ref_node}"',
            ]
    lines += [
        "        node_outputs:",
        "            output:",
        "                type: object",
        "                value: null",
        "        settingOnError:",
        "            processType: 1",
        "            retryTimes: 0",
        "            switch: false",
        "            timeoutMs: 180000",
    ]
    return "\n".join(lines)


def end_node(ref_node: str, x: int = 2400, y: int = 0) -> str:
    return "\n".join([
        '    - id: "900001"',
        "      type: end",
        "      title: 结束",
        f"      icon: {ICON_END}",
        f'      description: {q("工作流结束节点：返回结构化 JSON 结果，交给后端校验与发布")}',
        "      position:",
        f"        x: {x}",
        f"        y: {y}",
        "      parameters:",
        "        node_inputs:",
        "            - name: output",
        "              input:",
        "                value:",
        "                    path: output",
        f'                    ref_node: "{ref_node}"',
        "        terminatePlan: returnVariables",
    ])


# ---------------- 工作流组装 ----------------

def build_workflow_yaml() -> str:
    """start → N02 意图 → N03 上下文 → N05 事实检索 → N06 资料检索 → N07 分析 → end"""
    nodes = [
        start_node(),
        llm_node(
            "200001", "N02-意图与参数",
            load_prompt("intent.md"),
            "用户问题：{{message}}\n当前页面上下文：{{page_context}}\n前几轮对话摘要：{{history_summary}}",
            [("message", "100001", "message"),
             ("page_context", "100001", "page_context"),
             ("history_summary", "100001", "history_summary")],
            x=-1400, y=-200),
        llm_node(
            "200002", "N03-上下文决议",
            load_prompt("clarify.md"),
            "意图与参数识别结果：{{intent_result}}\n当前页面上下文：{{page_context}}",
            [("intent_result", "200001", "output"),
             ("page_context", "100001", "page_context")],
            x=-1000, y=-200),
        plugin_node(
            "500001", "N05-事实检索(get_company_context)",
            [("X-Context-Token", "100001", "context_token"),
             ("scode", "200002", "scode"),
             ("year", "200002", "year")],
            x=-600, y=-200,
            description="查询企业画像、当年披露原文、客户集中度、规则候选服务与证据引用"),
        plugin_node(
            "500002", "N06-资料检索(search_product_knowledge)",
            [("X-Context-Token", "100001", "context_token"),
             ("service_focus", "100001", "preferences"),
             ("as_of", "100001", "data_snapshot")],
            x=-200, y=-200,
            description="查询产品卡与适用条件；地区资料可另加 search_regional_knowledge 节点"),
        llm_node(
            "700001", "N07-AI分析",
            load_prompt("analyze.md") + "\n\n" + load_prompt("plan.md"),
            "用户问题：{{message}}\n\n事实包：{{facts}}\n\n产品资料：{{products}}\n\n经理偏好：{{preferences}}",
            [("facts", "500001", "output"),
             ("products", "500002", "output"),
             ("message", "100001", "message"),
             ("preferences", "100001", "preferences")],
            x=400, y=-200),
        end_node("700001"),
    ]
    edges = [
        ('    - source_node: "100001"\n      target_node: "200001"'),
        ('    - source_node: "200001"\n      target_node: "200002"'),
        ('    - source_node: "200002"\n      target_node: "500001"'),
        ('    - source_node: "500001"\n      target_node: "500002"'),
        ('    - source_node: "500002"\n      target_node: "700001"'),
        ('    - source_node: "700001"\n      target_node: "900001"'),
    ]
    return (
        "schema_version: 1.0.0\n"
        f"name: {NAME}\n"
        f"id: {WORKFLOW_ID}\n"
        f"description: {q(DESC)}\n"
        "mode: workflow\n"
        "icon: plugin_icon/workflow.png\n"
        "nodes:\n" + "\n".join(nodes) + "\n"
        "edges:\n" + "\n".join(edges) + "\n"
    )


def build_manifest() -> str:
    return (
        "type: Workflow\n"
        "version: 1.0.0\n"
        "main:\n"
        f"    id: {WORKFLOW_ID}\n"
        f"    name: {NAME}\n"
        f"    desc: {DESC}\n"
        "    icon: plugin_icon/workflow.png\n"
        '    version: ""\n'
        "    flowMode: 0\n"
        '    commitId: ""\n'
        "sub: []\n"
    )


# ---------------- ZIP（Go archive/zip 流式格式） ----------------

def _dos_time_date() -> tuple[int, int]:
    return 0, 0        # 按契约：time/date 全 0


def _raw_deflate(data: bytes) -> bytes:
    comp = zlib.compressobj(9, zlib.DEFLATED, -15)   # -15 = raw deflate
    return comp.compress(data) + comp.flush()


def write_zip(path: Path, entries: list[tuple[str, bytes]]):
    """按契约写出 ZIP：无目录条目、flags=0x08、time/date=0、vmade=20、external_attr=0。"""
    out = bytearray()
    central = bytearray()
    for name, data in entries:
        name_b = name.encode("utf-8")
        comp = _raw_deflate(data)
        crc = zlib.crc32(data) & 0xFFFFFFFF
        offset = len(out)
        # local file header（crc/size 置 0，真实值放 data descriptor）
        out += struct.pack("<IHHHHHIIIHH", 0x04034B50, 20, 0x0008, 8,
                           *_dos_time_date(), 0, 0, 0, len(name_b), 0)
        out += name_b + comp
        out += struct.pack("<IIII", 0x08074B50, crc, len(comp), len(data))
        central += struct.pack("<IHHHHHHIIIHHHHHII", 0x02014B50, 20, 20, 0x0008, 8,
                               *_dos_time_date(), crc, len(comp), len(data),
                               len(name_b), 0, 0, 0, 0, 0, offset)
        central += name_b
    cd_offset = len(out)
    out += central
    out += struct.pack("<IHHHHIIH", 0x06054B50, 0, 0, len(entries), len(entries),
                       len(central), cd_offset, 0)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(bytes(out))


# ---------------- 校验 ----------------

def check_zip(path: Path, yaml_body: str) -> list[str]:
    """结构 + 字节契约校验，返回问题列表（空 = 通过）。"""
    import zipfile
    issues = []
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        expect_root = f"Workflow-{NAME}-draft-0001"
        if names[0] != f"{expect_root}/MANIFEST.yml":
            issues.append(f"第一个条目必须是 MANIFEST.yml，实际：{names[0]}")
        if len(names) != 2:
            issues.append(f"应只有 2 个条目（不含目录条目），实际：{names}")
        if f"{expect_root}/workflow/{NAME}-draft.yaml" not in names:
            issues.append(f"缺少工作流 YAML：{names}")
        if z.read(names[0]).decode() != build_manifest():
            issues.append("MANIFEST 内容与预期不一致")
        if z.read(names[1]).decode() != yaml_body:
            issues.append("工作流 YAML 内容与预期不一致")
    raw = path.read_bytes()
    off = 0
    while True:
        idx = raw.find(b"PK\x03\x04", off)
        if idx == -1:
            break
        flags = struct.unpack_from("<H", raw, idx + 6)[0]
        t, d = struct.unpack_from("<HH", raw, idx + 10)
        if flags != 0x0008:
            issues.append(f"local flags 应为 0x08，实际 0x{flags:04x}")
        if (t, d) != (0, 0):
            issues.append(f"local time/date 应为 0，实际 {t}/{d}")
        fnlen = struct.unpack_from("<H", raw, idx + 26)[0]
        off = idx + 30 + fnlen
    while True:
        idx = raw.find(b"PK\x01\x02", off)
        if idx == -1:
            break
        vmade = struct.unpack_from("<H", raw, idx + 4)[0]
        extattr = struct.unpack_from("<I", raw, idx + 38)[0]
        if vmade != 20:
            issues.append(f"CD vmade 应为 20，实际 {vmade}")
        if extattr != 0:
            issues.append(f"CD external_attr 应为 0，实际 {extattr}")
        fnlen = struct.unpack_from("<H", raw, idx + 28)[0]
        off = idx + 46 + fnlen
    try:
        import yaml
        data = yaml.safe_load(yaml_body)
        if data.get("schema_version") != "1.0.0":
            issues.append("schema_version 必须是 1.0.0")
        ids = [n["id"] for n in data["nodes"]]
        if len(ids) != len(set(ids)):
            issues.append("节点 ID 有重复")
        for e in data["edges"]:
            if e["source_node"] not in ids or e["target_node"] not in ids:
                issues.append(f"边引用了不存在的节点：{e}")
    except ImportError:
        issues.append("（未安装 PyYAML，跳过 YAML 校验）")
    return issues


def main() -> int:
    ap = argparse.ArgumentParser(description="生成 coze.cn 可导入的工作流 ZIP")
    ap.add_argument("--check", action="store_true", help="生成后校验结构与字节契约")
    ap.add_argument("--out", default=str(OUT_DIR / f"Workflow-{NAME}-draft-0001.zip"))
    args = ap.parse_args()

    yaml_body = build_workflow_yaml()
    out = Path(args.out)
    write_zip(out, [
        (f"Workflow-{NAME}-draft-0001/MANIFEST.yml", build_manifest().encode("utf-8")),
        (f"Workflow-{NAME}-draft-0001/workflow/{NAME}-draft.yaml", yaml_body.encode("utf-8")),
    ])
    print(f"[生成] {out}  ({out.stat().st_size} 字节)")

    # 同时落一份明文 YAML，便于人工核对与手工粘贴
    plain = out.with_suffix(".yaml")
    plain.write_text(yaml_body, encoding="utf-8")
    print(f"[生成] {plain}  ({len(yaml_body)} 字符)")

    if args.check:
        issues = check_zip(out, yaml_body)
        if issues:
            print("[校验] ❌ 发现问题：")
            for i in issues:
                print("   -", i)
            return 1
        print("[校验] ✅ 结构与字节契约通过（MANIFEST 在前、无目录条目、flags=0x08、time=0、vmade=20）")
    # 统计节点
    import yaml
    data = yaml.safe_load(yaml_body)
    kinds = {}
    for n in data["nodes"]:
        kinds[n["type"]] = kinds.get(n["type"], 0) + 1
    print(f"[摘要] 节点 {len(data['nodes'])} 个 {json.dumps(kinds, ensure_ascii=False)}，"
          f"连线 {len(data['edges'])} 条")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
