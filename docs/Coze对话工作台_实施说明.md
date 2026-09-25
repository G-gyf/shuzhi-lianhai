> 2026-09-25现行状态更新：以[当前口径与实施更新](当前口径与实施更新_20260925.md)为准。Coze云端待实施；现有网页/网关/光球/本地规则已具备接入基础。Neo4j仅银行实名数据扩展设计，本项目不实现；不扩大现有行业样本。此前统计按本文写作时快照理解。

# 数智链海 · Coze 对话工作台实施说明（v2.0）

日期：2026-09-25｜依据：《Coze智能体与光球交互_完整实施方案.md》（设计稿 v1.0）

## 一、已交付范围（M0—M5 对照）

| 阶段 | 交付内容 | 验收方式 |
|---|---|---|
| M0 口径修复与协议冻结 | 快照ID（内容哈希）、文本版本（稳定引用）、严格年度（无数据不回退未来年份）、真实总数与分页、`server/schemas.py` 协议常量 | `tests/test_m0_protocol.py` |
| M1 企业工具与产品卡 | `server/tools.py` 8 个受控工具、`knowledge/products/product_cards.json`（15 卡，8 张 verified）、证据包（evidence_ref 可还原） | `tests/test_m1_tools.py` |
| M2 Coze 工作流与分析网关 | `coze/`（workflow_design / tool_openapi / prompts / examples）、`server/coze_client.py`、`server/local_engine.py` 降级引擎、`server/analysis_service.py` 校验与保存 | `tests/test_m2_analysis.py` |
| M3 网页对话/光球/抽屉 | `web/assets/chat.js`、`orbs.js`、`drawer.js`、`chat.css`；SSE 网关 `server/chat.py`、引用解析 `server/references.py`、工具 HTTP `server/tool_api.py` | `tests/test_m3_chat.py` |
| M4 偏好与地区扩展 | `server/profiles.py`、`server/extensions.py`、`server/adapters/`（document_reader_v1 / table_reader_v1）、`runtime/app_runtime.sqlite`、合成示范地区资料 | `tests/test_m4_regions.py` |
| M5 测试与文档 | `tests/` 38 用例全通过；本说明；PROGRESS/README 更新 | `python -m unittest discover -s tests` |

## 二、当前模式与降级路径（重要）

- **默认模式**：`AI_ENABLED` 未配置 → 对话由**本地规则分析引擎**（`server/local_engine.py`）确定性生成，
  回答与方案光球中明确标注「规则演示」；事实引用来自确定性数据库，分析组合由规则生成。
- **Coze 模式**：配置环境变量后走 `POST {COZE_API_BASE}/v1/workflow/stream_run`，后端校验后发布；
  Coze 不可用时自动降级为本地引擎并注明原因（方案 12.3 节）。
- 工具 HTTP 接口（`/api/v1/tools/*`）供 Coze 云端通过短期 `context_token` 调用；
  本地降级模式不依赖该接口（网关进程内直调）。

启用 Coze 的环境变量（详见 `coze/workflow_design.md` 第 4 节）：

```
AI_ENABLED=1
COZE_API_BASE=https://api.coze.cn
COZE_ACCESS_TOKEN=<PAT>
COZE_WORKFLOW_ID=<已发布工作流ID>
COZE_APP_ID=<可选>
TOOLS_BASE_URL=https://<项目后端域名>
TOOL_CONTEXT_SECRET=<与部署侧一致>
AI_TIMEOUT_SECONDS=60
AI_MAX_TOOL_CALLS=6
AI_MAX_COMPARE_COMPANIES=3
```

## 三、演示身份与地区隔离

- `/api/v1/*` 一律要求 `Authorization: Bearer <token>`；服务端按令牌哈希解析用户与辖区。
- 演示令牌：`demo-token-region-a`（A区，可见合成示范地区资料）、`demo-token-region-b`（B区，不可见）。
  前端对话台右上角可切换演示身份，切换即换会话。
- 身份为**明确标注的演示身份**；正式多人使用前必须以服务端身份完成隔离，
  不能只在前端隐藏他区资料（方案 7.3 节）。
- 地区资料为**合成示范**（`knowledge/regional/demo_region_a_notes.json`），非真实分行数据；
  A 区可检索并出现来源光球，B 区不可检索或按 ID 打开（验收用例 12）；
  停用后新请求不能继续引用（验收用例 13）。

## 四、接口清单（/api/v1/*，项目内部协议）

| 方法与路径 | 用途 |
|---|---|
| `POST /api/v1/chat/stream` | 创建本轮请求并以 SSE 返回状态与结果 |
| `POST /api/v1/chat/requests/{id}/cancel` | 取消显示与本地编排（上游可能仍计费） |
| `GET /api/v1/chat/sessions/{id}` | 恢复本用户会话 |
| `GET /api/v1/analyses/{analysis_id}` | 读取已保存结构化分析 |
| `GET /api/v1/references/{ref_id}` | 按权限解析确定性详情 |
| `POST /api/v1/briefings` | 从 analysis_id 生成简报，不重新计算事实 |
| `GET/PATCH /api/v1/me/preferences` | 经理偏好 |
| `GET /api/v1/me/capabilities` | 当前用户可使用的功能与资料源 |
| `POST /api/v1/tools/{tool}` | 受控业务工具（X-Context-Token 鉴权，供 Coze 调用） |
| `POST /api/v1/data-sources` | 创建资料源配置（region 由服务端校验） |
| `POST /api/v1/data-sources/{id}/validate` | 试读、字段检查与导入预览 |
| `POST /api/v1/data-sources/{id}/activate` | 激活通过验证的资料源 |
| `POST /api/v1/data-sources/{id}/disable` | 停用资料源 |
| `GET /api/v1/extensions` | 列出可启用扩展及所需权限 |
| `POST /api/v1/extensions/{id}/bindings/{region}` | 启用/停用扩展绑定 |
| `POST /api/v1/feedback` | 经理反馈（数据错误/分析不合理/资料过时/体验） |

SSE 事件（网关协议，不直接暴露 Coze 原始事件）：
`request_started → status(查询中→分析中→校验中) → answer_delta* → orbs_ready → analysis_ready → done`；
歧义走 `clarification`；异常/取消走 `error`。每个事件携带 `request_id`，防重连重复渲染。

## 五、引用编码（方案 8.2 节）

```
evidence  ev:<chunk_id>:<claim_number>:<text_version>     原文引用（按文本版本还原偏移）
metric    metric:concentration:<scode>:<year>:<field>     结构化指标（白名单）
product   product:<product_id>                            产品依据（卡带 status：verified/placeholder）
analysis  analysis:<analysis_id>:<recommendation_id>      AI 方案（标为分析结果）
compare   compare:<comparison_id>                         对比（同一年度）
regional  regional:<source_id>:<doc_id>                   地区资料（读取再查权限）
company   company:<scode>:<year>                          企业球（打开确定性详情）
```

## 六、目录结构（新增部分）

```text
数智链海/
  server/
    schemas.py        # 协议冻结（请求/结果/引用/SSE 事件）
    runtime.py        # app_runtime.sqlite + 快照ID/文本版本 + 演示身份
    context_token.py  # 短期上下文令牌（HMAC，工具接口用）
    tools.py          # 8 个受控业务工具（白名单）
    products.py       # 产品卡检索与冲突检查
    local_engine.py   # 本地规则分析引擎（降级/演示路径）
    coze_client.py    # Coze 工作流流式调用
    analysis_service.py # 校验/保存/光球/简报复用/编排
    references.py     # 稳定引用解析
    chat.py           # 会话/请求/SSE 网关
    tool_api.py       # 受控工具 HTTP（context_token）
    profiles.py       # 经理偏好与能力
    extensions.py     # 数据源/扩展注册 + API
    adapters/         # document_reader_v1 / table_reader_v1
  knowledge/
    products/product_cards.json       # 15 产品卡（8 verified）
    regional/demo_region_a_notes.json # 合成示范地区资料
  coze/               # 工作流设计/OpenAPI/提示词/合成样例
  tests/              # 38 个验收用例（unittest）
  runtime/            # 运行库（不入库）
  web/assets/         # chat.js / orbs.js / drawer.js / chat.css
```

## 七、运行与验证

```bash
cd 数智链海
python -X utf8 -m uvicorn server.main:app --host 127.0.0.1 --port 8000
# 打开 http://127.0.0.1:8000 ，右下角「AI 助手」

python -X utf8 -m unittest discover -s tests   # 38/38
```

页面验证路径：名单/企业详情打开对话台 →
“这家公司值得关注什么？”（解释+原文/产品/待核实/方案光球，点击开抽屉）→
“找江苏有产能部署的光伏企业”（企业球，点击跳详情）→“比较前两家，优先拜访谁？”→
“重点谈结算，不考虑融资”（偏好收窄）→“做一页简报和五个问题”（复用 analysis_id 生成简报）。

## 八、边界与未做事项（如实声明）

- 本期未接真实 Coze 工作空间：所有 `coze/` 工件为**待实施配置**；线上运行需发布工作流并配置凭证。
- 演示身份与合成地区资料仅用于验收；行内身份系统与真实分行资料需另行接入。
- 供应链以集中度、依赖度和有限来源信息为主；不构建全量实名供应链，不以 Neo4j 为前置依赖。
- 首版“方案”为访前服务讨论方案，不自动执行联系客户、业务申请或授信审批。
- placeholder 产品卡（7 张）仅列讨论方向，不构成正式适配建议。
- 历史样本模式：分析历史年度时注明“基于历史企业资料、采用当前服务资料的演示建议”。
