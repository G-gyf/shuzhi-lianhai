# Coze 工作流节点配置与发布说明（出海业务，新建流程）

版本：设计稿 v1.0｜日期：2026-09-25｜性质：待实施配置说明。

> 说明：本项目的 `/api/v1/*` 路径、事件名与数据结构为**项目内部协议**，
> 不是 Coze 官方原生字段。本项目为出海业务**新建**流程，不直接复用既有智能体。

## 1. 发布前输入（方案第 16 章）

- 可用 Coze 工作空间、API 授权（Personal Access Token）。
- 可供 Coze 访问的受控业务工具服务地址（HTTPS，线上部署后为项目后端域名）。
- 5—8 张重点服务资料卡及来源（`knowledge/products/product_cards.json`）。
- 后端环境变量：`TOOLS_BASE_URL`、`TOOL_CONTEXT_SECRET`（与部署侧一致）。

## 2. 工作流整体结构

按方案第 6 章单一主流程组织，不引入多个自治智能体作为首版依赖。

| 节点 | 输入 | 处理 | 输出 |
|---|---|---|---|
| N01 开始 | message、page_context、history_summary、preferences、data_snapshot、product_version、context_token | 验证必要参数 | 本轮任务上下文 |
| N02 意图与参数（大模型节点） | 用户消息、有效上下文 | intent、企业指代、年份、筛选与方案偏好 | 结构化任务（不作业务结论） |
| N03 上下文决议（大模型节点） | N02 + 后端会话状态 | 明确企业、年份；歧义走澄清分支 | task_context |
| N04 工具路由（条件分支） | intent | search / explain / compare / plan / clarify | 数据请求 |
| N05 事实检索（插件节点） | 参数 + context_token | 调用 `/api/v1/tools/*` | facts、evidence_refs、coverage |
| N06 资料检索（插件节点） | 行动与服务范围 | 调用产品/地区检索工具 | product_refs、适用条件 |
| N07 AI 分析（大模型节点） | N05、N06、偏好 | 综合行动、画像、产品条件，形成假设与方案 | 结构化分析草稿 |
| N08 自检/格式整理（代码节点+大模型节点） | 草稿 | 检查事实引用、未知字段、类型格式 | analysis_draft |
| N09 结束（文本输出） | 标准结果 | 返回完整 JSON 结果包 | 交给后端校验与发布 |

## 3. 关键节点配置

### N01 开始节点
变量：`message`(string, 必填)、`page_context`(object)、`history_summary`(string)、
`preferences`(object)、`context_token`(string)、`data_snapshot`(string)、
`product_version`(string)。开始节点不做业务校验，仅透传。

### N02 意图与参数（大模型节点）
- 输入：message、page_context、history_summary。
- 提示词：`prompts/intent.md`。
- 输出 JSON（作为变量）：
```json
{"intent": "search|explain|compare|plan|clarify|general",
 "companies": [{"scode": "002860"}], "year": 2023,
 "filters": {"province": "江苏省", "industry": "光伏", "direction": "capacity_production"},
 "service_preferences": {"service_focus": ["settlement"], "exclude_financing": true}}
```

### N03 上下文决议（大模型节点）
- 规则：页面上下文（后端会话注入）优先于历史默认值；用户本轮明确要求优先于页面上下文；
  冲突时在回答中确认采用了哪个范围。
- 企业指代（“前两家”“第二家”）只允许绑定后端传来的上一条结果集（N05 工具输出），
  不按当前重新排序后的名单猜测。

### N04 工具路由（条件分支）
按 `intent` 分发；`clarify` 直接输出澄清选项，不提前生成方案。

### N05/N06 工具调用（插件节点）
- 导入 `tool_openapi.yaml` 后生成插件；调用时在 Header 传 `X-Context-Token: {{context_token}}`。
- 工具输入由 N04 的参数变量填充；`context_token` 每轮由后端签发（10 分钟有效），
  **不拼入模型提示词**。
- 后端工具接口验证 token；模型传来的地区ID不作为权限依据。
- **导入报错处理**：Coze 插件解析器要求「每个响应体必须声明 `application/json` 且 schema 顶层为
  object/array」，否则报 `API response schema must be json object/array`。
  `coze/tool_openapi.yaml`（v1.1.0 起）已为全部 operation 补齐响应 schema；
  若仍导入失败，改用 `coze/tool_openapi.min.yaml`（单 `dispatch` 工具，参数以 JSON 字符串传入），
  对应后端 `/api/v1/tools/dispatch`（已实现，支持扁平/嵌套/JSON 字符串三种传参）。

### N07 AI 分析（大模型节点）
- 提示词：`prompts/analyze.md`。
- 必须输出五类分区：已知事实 / 需求假设 / 候选服务 / 待核实事项 / 行动建议（方案 6.2 节）。
- 只引用本轮允许的 evidence_ref、metric_ref、product_ref；不输出 URL、HTML 或脚本。

### N08 自检/格式整理
- 代码节点（或大模型节点）按 `examples/analysis_draft.example.json` 校验字段；
- 未知字段剔除；事实引用与 N05/N06 结果核对；
- 产品库之外的服务概念最多列为“需补充资料的讨论方向”，不能伪造产品ID。

### N09 结束输出
输出为**文本**（JSON 字符串），后端 `extract_workflow_output` 解析后校验、生成
analysis_id 并构建光球。模型不能决定网页路由或拼接外部 URL。

## 4. 发布

1. 在 Coze 工作空间新建“数智链海出海助手工作流”，按上文搭建节点；
2. 上传 `tool_openapi.yaml` 为插件（认证方式：API Key 传入自定义 Header `X-Context-Token`，
   值绑定工作流变量 `{{context_token}}`）；
3. 试运行：使用 `examples/` 中合成样例（明确非真实案例）验证节点连通；
4. 发布工作流，记录版本号（`pinned_version`），后端记录
   `workflow_version = COZE_WORKFLOW_ID`（见方案 12.2 运行记录）；
5. 后端配置：
```
AI_ENABLED=1
COZE_API_BASE=https://api.coze.cn
COZE_ACCESS_TOKEN=<PAT 或 SAT>
COZE_WORKFLOW_ID=<发布后的工作流ID>
COZE_APP_ID=<可选，按发布方式选用>
TOOLS_BASE_URL=https://<项目后端域名>
TOOL_CONTEXT_SECRET=<与服务端一致>
AI_TIMEOUT_SECONDS=60
AI_MAX_TOOL_CALLS=6
AI_MAX_COMPARE_COMPANIES=3
```
6. 浏览器不保存 Coze 长期令牌；Coze 只能通过 context_token 访问受控工具。

### 4.1 令牌从哪来（官方入口，2026-09 核对）

| 令牌 | 适用场景 | 有效期 | 入口 |
|---|---|---|---|
| 个人访问令牌 PAT | 测试、调试（官方明确不建议用于生产） | 1—30 天，到期须重签 | 扣子编程 [code.coze.cn/home](https://code.coze.cn/home) → 左栏 **API & SDK** → **授权 > 个人访问令牌** → 添加 |
| 服务访问令牌 SAT | 服务/应用间长期调用（**本项目后端推荐**） | 可长期有效，可修改 | 扣子编程 → **API & SDK** → **授权 > 服务身份凭证** → 添加 |

要点：
- 入口在**扣子编程（code.coze.cn）**，不在 coze.cn 的「设置」里 —— 这是常见找不到的原因。
- 权限须包含工作流调用，否则报错 **4101**；个人版只能选择**自己作为空间所有者**的工作空间。
- 令牌只在创建时显示一次，立即复制到 Railway Variables。
- 企业版创建 SAT 需组织超管/管理员；一个企业最多 100 个 SAT，个人版每人最多 10 个。

## 5. 常见坑

- 工作流 ID / 智能体 ID / 应用 ID / 会话 ID 不可混用（方案 5.1）。
- 流式事件为 Coze 平台事件；项目 SSE 事件（answer_delta 等）由网关转换。
- 首版“先校验内容，再逐段呈现”：后端收齐结构化结果并校验后才下发 answer_delta。
- 未接通外网工具服务时，后端可预取当前企业证据包传给工作流（`get_company_context` 结果），
  此模式标明功能限制，不假装可查询所有企业。
