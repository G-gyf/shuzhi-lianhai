> 当前口径以 [本次更新说明](docs/当前口径与实施更新_20260925.md) 为准。云端接入已打通；本次新增独立分析工作台，交互与发布说明见 [AI工作台交互改版](docs/AI工作台交互改版.md)。实际引擎由部署环境配置决定。
>
> **系统框架文档（出海全周期三阶段口径）**：仓库内 [docs/工行杯选题_数智链海_系统框架_v1.4.html](docs/工行杯选题_数智链海_系统框架_v1.4.html)；
> 工作区根目录的同名文件 `工行杯选题_数智链海_系统框架_v1.4.html` 为对外交付副本（内容一致）。
> 旧版 v1.3（窗口期二分／筹备层·落地层／底层抽取标签口径）已随 2026-09-25 归档移至
> `归档/2026-09-25_旧版材料/工行杯选题_数智链海_系统框架_v1.3_旧口径.html`，**项目书请勿再引旧版**。

# 数智链海 · 最小闭环（MVP）

企业出海金融需求雷达与对公跨境营销助手 —— 系统框架 v1.2 的最小可运行实现，
已扩展 **Coze 对话工作台（v2.0）**：可对话、可分析、可核查、可扩展（设计与实施说明见
[归档/2026-09-25_旧版材料/数智链海/docs](../归档/2026-09-25_旧版材料/数智链海/docs/)，其中
`Coze对话工作台_实施说明.md`、`Coze智能体与光球交互_完整实施方案.md` 已于 2026-09-25 归档）。

## 启动

```bash
# 方式一：双击 start.bat（推荐，自动打开浏览器）
# 方式二：命令行
cd 数智链海
python kb_build.py                        # 构建知识库快照（已构建，无需重复）
python -m uvicorn server.main:app --host 127.0.0.1 --port 8000
```

浏览器打开 http://127.0.0.1:8000 → 顶部「AI 工作台」或右下角「AI 分析工作台」进入独立工作区。

对话工作台要点：

- 在**企业详情页**直接提问（“这家公司值得关注什么？”），上下文自动携带当前企业与年度；
- 回答下方**光球**可点击：原文依据 / 产品依据 / 对比 / AI 方案 / 待核实事项 → 右侧抽屉核查；
- 多轮指代（“第二家”“比较前两家”）绑定上一条结果集稳定 ID；
- 右上角可切换**演示身份**（A 区 / B 区，用于地区资料隔离验收）；`/api/v1/*` 需要
  `Authorization: Bearer <token>`（演示令牌：`demo-token-region-a` / `demo-token-region-b`）。

线上已接入**生成式引擎**（扣子编程项目 LangGraph 版，`https://kmj3bsz4kj.coze.site`），
回答由模型生成、事实引用仍来自确定性数据库，不再标注「规则演示」。
引擎不可用时**自动降级**为本地规则分析引擎（降级路径，回答标注「规则演示」）。
本地未配置环境变量时即为该降级路径。

## AI 引擎（三选一，失败自动降级）

对话里的「分析」由哪套引擎生成，由环境变量决定；按顺序尝试：

| 引擎 | 触发条件 | 说明 |
|---|---|---|
| `langgraph` | `LANGGRAPH_BASE_URL` 有值（且 `AI_ENABLED=1`，或显式 `AI_ENGINE=langgraph`） | **扣子编程项目**（LangGraph 版 N01–N09）通过 HTTP `/run` 调用；入参 11 个变量与文档一致 |
| `coze` | `AI_ENABLED=1` 且 `COZE_WORKFLOW_ID` 有值 | Coze 云端工作流（`/v1/workflow/stream_run`） |
| `rules-demo` | 以上不可用或调用失败 | 本地规则引擎，**永远可用**，答案标注「规则演示」 |

```
AI_ENABLED=1
AI_ENGINE=langgraph                       # 可选：coze | langgraph（留空=自动取有配置的那个）
LANGGRAPH_BASE_URL=https://<引擎地址>      # 扣子项目部署地址，或 http://127.0.0.1:5000
LANGGRAPH_TOKEN=<可选，Bearer 令牌>        # 引擎需要鉴权时填
TOOL_CONTEXT_SECRET=<密钥>                 # 每轮签发 context_token（工具接口鉴权）
TOOLS_BASE_URL=https://<工具服务地址>       # 引擎回调受控工具服务用
```

### 冷启动容错（重要，直接影响演示可用性）

扣子编程部署在**无访问流量时会缩容至 0 个实例**（官方文档明示）。缩容后首次访问要等
实例重新拉起，会把「引擎在用」变成「引擎像坏了」。为此本项目做了四层防护：

| 防护 | 机制 | 相关配置 |
|---|---|---|
| 保活 | 后端启动后周期探活，使实例不缩容到 0 | `ENGINE_KEEPALIVE=1`、`ENGINE_KEEPALIVE_INTERVAL=240`、`ENGINE_KEEPALIVE_INITIAL_DELAY=5` |
| 页面预热 | 网页一打开就后台探活一次，把冷启动藏在浏览时间里 | 前端 `warmEngine()`，无需配置 |
| 冷启动识别 | 探活超时判为 `warming`（未就绪），不再报成「引擎不可用」 | `ENGINE_PROBE_TIMEOUT_SECONDS=20` |
| 调用重试 | 瞬时类错误（超时/网络/5xx/实例回收）自动重试一次再降级 | `ENGINE_COLD_START_RETRIES=1`、`ENGINE_COLD_START_RETRY_DELAY=3` |

据此，`GET /api/health` 的判读方式为：

- `engine_ready=true` → 引擎此刻真的可连通；
- `engine_warming=true` → 引擎正在冷启动（**暂时未就绪，不是故障**），稍后自动恢复；
- 两者都为 false 且非 warming → 配置错误或实例被回收，需人工处理。

降级文案也据此分两类：瞬时故障用中性表述（「尚未就绪……已自动切换至本地分析引擎」），
配置错误保留原因与可执行修复提示。**不要把「引擎不可用」这类字眼写进回答正文**——
演示时会被读成「系统坏了」。

> 平台侧限制（无法用代码解决，需在扣子后台确认）：
> 「个人进阶版」不支持部署扩容，**不能把最小实例数固定为 1**，因此保活是当前套餐下
> 唯一能压制缩容的手段。长期方案是把引擎自建部署（见 `project_20260925_202405/`，
> 该 LangGraph 工程除 3 个节点的大模型客户端外与扣子运行时无耦合）。

没有真实引擎时也可联调链路：`python -X utf8 scripts/stub_engine.py --port 5001`，
再配 `LANGGRAPH_BASE_URL=http://127.0.0.1:5001`，即可看到完整 SSE + 光球效果。
引擎状态见 `GET /api/health`：其中 `engine.effective_engine` / `engine.planned_engine`
**只按配置推断，不代表可连通**——是否此刻真的能用请看 **`engine.reachable`**（以及顶层
`engine_ready`）。该接口默认对「将优先尝试的引擎」做**真实探活**（带 `LANGGRAPH_TOKEN`，
60 秒缓存；加 `?probe=0` 可跳过探活，仅回配置）。

对话流中 `request_started.engine` 是「本轮将尝试的引擎」（附 `engine_resolved=false`），
**真实生效引擎**见 `analysis_ready.engine` 与落库记录的 `engine` / `workflow_version` 字段。

## API 调用示例

前端（web/index.html）已通过同源 `/api/*` 连好，直接浏览器使用即可。
从其他程序调用（服务已开 CORS 全放行）：

```bash
# curl
curl "http://127.0.0.1:8000/api/radar?province=江苏省&year=2023&limit=10"
curl "http://127.0.0.1:8000/api/company/002860/chain"
```

```python
# python
import requests
r = requests.get("http://127.0.0.1:8000/api/radar",
                 params={"province": "江苏省", "limit": 10})
for item in r.json()["items"]:
    print(item["coname"], item["window_label"], item["stage_label"], item["score"])
```

```js
// 若前端部署在其他域名：把 app.js 顶部 const API = "" 改为
const API = "http://127.0.0.1:8000";
```

## 目录

```
数智链海/
├─ kb_build.py          # 从 技术链/出海预测/outputs 构建知识库快照
├─ kb/kb-2023.sqlite    # 快照：chunks 37,946 / claims 23,718 / firm_year 1,594
├─ kb/kb-sc-2023.sqlite # CSMAR 供应链：前五大客户/供应商 + 集中度（单跳画像）
├─ rules/               # 规则库（金融队员维护，JSON）
│  ├─ stages.json       # ★ 出海全周期三阶段：定义 + 判别规则 + 窗口期界定（单一事实来源）
│  ├─ products.json     # 五位一体产品目录 + 方向×锚点×窗口 匹配规则 + 前置条件
│  ├─ scoring.json      # 能力评分卡（6 维度 + 分级）
│  ├─ chains.json       # 推理链步骤模板与阶段标签
│  └─ countries.json    # 国别卡片（占位：清算/司库待行内产品库）
├─ knowledge/
│  ├─ products/product_cards.json       # 15 产品卡（8 张 verified，含来源与核实状态）
│  └─ regional/demo_region_a_notes.json # 合成示范地区资料（A 区可见，非真实分行数据）
├─ coze/                # Coze 工作流配套：节点设计/OpenAPI 插件协议/提示词/合成样例
├─ server/
│  ├─ main.py           # FastAPI：/api/* + /api/v1/* + 静态前端
│  ├─ logic.py          # 规则引擎：三阶段/布局细分/强度/评分/推理链/简报/存量挖转
│  ├─ graph.py          # SQLite 证据子图；Neo4j 仅银行数据扩展设计
│  ├─ schemas.py        # 协议冻结：请求/结果/引用/SSE 事件（项目内部协议）
│  ├─ runtime.py        # app_runtime.sqlite：会话/分析/偏好/资料源 + 快照ID + 演示身份
│  ├─ tools.py          # 8 个受控业务工具（Coze 白名单）
│  ├─ products.py       # 产品卡检索与冲突检查
│  ├─ local_engine.py   # 本地规则分析引擎（Coze 未接入/失败时的降级路径）
│  ├─ coze_client.py    # Coze 工作流流式调用（stream_run）
│  ├─ analysis_service.py # 校验/保存/光球/简报复用/编排
│  ├─ references.py     # 稳定引用解析（证据/指标/产品/分析/对比/地区/企业）
│  ├─ chat.py           # 对话网关：会话/请求/SSE 八事件
│  ├─ tool_api.py       # 受控工具 HTTP（context_token 鉴权，供 Coze 云端调用）
│  ├─ profiles.py       # 经理偏好与能力
│  ├─ extensions.py     # 数据源/功能扩展注册 + 导入校验/激活/停用
│  └─ adapters/         # document_reader_v1 / table_reader_v1（导入适配器）
├─ tests/               # 验收测试（unittest，150 用例：三阶段口径/工具/分析/对话/地区隔离/国别与供应链/冷启动容错回归）
├─ runtime/             # 运行库 app_runtime.sqlite（不入库）
└─ web/                 # 前端（零外部依赖，SVG 手绘雷达图/关系图）
   ├─ index.html        # 雷达名单 / 企业详情 / 访前简报 + 证据高亮弹窗 + 对话台/抽屉
   └─ assets/           # app.js / style.css / chat.js / orbs.js / drawer.js / chat.css
```

## 出海全周期三阶段（全系统统一口径）

**唯一定义与判别规则在 `rules/stages.json`**，下文与界面、接口一律按此表述。

| 阶段 | 归属 | 判别规则 | 营销动作 |
|---|---|---|---|
| **T0 筹备期** | 出海前窗口期 | 当年有出海需求信号，且**不含任何落点类信号** | 先于同业建立关系，锁定结算与保函 |
| **T1 落地期** | 出海前窗口期 | 当年有出海需求信号，且**至少 1 条为落点类信号** | 融资与保函切入，额度投放精准对象 |
| **T2 存量期** | **不属于窗口期** | 已形成海外布局：海外子公司数 > 0 或海外收入占比 > 0 | 从存量中寻找结算融资不在工行的挖转机会 |

- **「出海前窗口期」仅含 T0 与 T1**——即企业首次在公开披露中表达出海部署或意图（事前），到实际完成落地动作（事后）之间的时段。
- **窗口期企业＝尚未出海或布局未成熟的企业；存量企业＝已出海但结算融资不在工行的挖转对象。**
- **落点类信号**（区分 T0/T1 的唯一判据，命中任一即成立）：需求方向 ∈ {产能建设, 投资并购}，或执行锚点类型 ∈ {项目/基地, 产能/设施, 境外主体, 投资/合同}。
- 窗口期内的**布局细分**（`first` / `new_country` / `expansion` / `layout_unknown` / `label_incomplete`）与三阶段**正交**：阶段回答「走到哪一步」，布局细分回答「既有布局到什么程度」。
- T2 有**单独入口**（`/api/stock`、页面「存量挖转」），与窗口期名单**互斥不重复计数**：当年仍有新增出海需求的企业归入 T0/T1。

> ⚠️ 三阶段按**落点**判，不是按底层抽取标签判。两者并不等价（约 28% 的需求信号会被误分），
> 因此严禁把某个抽取标签直接等同于某个阶段。底层标签只是内部筛选依据，不出现在任何对外口径中。

## 核心判定口径（规则引擎，全部确定性计算）

| 概念 | 规则 |
|---|---|
| 出海阶段 | T0 筹备期 / T1 落地期 / T2 存量期，判据见上表与 `rules/stages.json` |
| 窗口布局细分 | `first`（当期未见布局）→ `new_country`（锚点国家 ∉ 已进入国集合）→ `expansion`（已有布局的其余）；缺失单列 layout_unknown / label_incomplete |
| 强度分 | `2×T1信号 + 1×T0信号 + 硬锚点数 + min(方向数,3) − 1` |
| 名单排序 | 窗口布局细分（first 优先）→ 阶段（落地期优先）→ 强度分 → 年份 |
| 存量名单排序 | 海外国别数 → 海外收入占比 |
| 能力评分卡 | 国际化基础/规模/盈利/研发/财务安全/客户依赖 六维，同年度样本内分位归一化加权 → 就绪/蓄力/薄弱 |

## API

```
GET /api/meta                      知识库版本、省份、年份、快照ID、三阶段口径
GET /api/radar?province=&year=     辖区出海线索排行（窗口期名单，仅 T0/T1）
GET /api/stock?province=&year=     T2 存量期挖转名单（不属于窗口期，单独入口）
GET /api/segments?year=            七个细分行业统计
GET /api/company/{scode}           企业详情（画像+阶段+评分+信号）
GET /api/company/{scode}/graph     企业-信号-阶段-方向-国别子图
GET /api/company/{scode}/supply-chain  CSMAR 前五大客户/供应商 + 集中度（单跳画像，不含多跳）
GET /api/company/{scode}/chain     营销方案推理链（4 步结构化，首步为出海阶段判定）
GET /api/company/{scode}/briefing  访前简报（4 段模板）
GET /api/evidence/{chunk_id}       原文片段 + 证据锚点区间（每条主张标注所属阶段）
GET /api/country/{name}            国别卡片（占位）
GET /api/health                    健康检查

# /api/v1 对话工作台（Bearer 令牌鉴权，项目内部协议）
POST /api/v1/chat/stream                   SSE 对话（request_started→status→answer_delta→orbs_ready→analysis_ready→done）
POST /api/v1/chat/requests/{id}/cancel     取消请求
GET  /api/v1/chat/sessions/{id}            恢复会话
GET  /api/v1/analyses/{analysis_id}        已保存结构化分析
GET  /api/v1/references/{ref_id}           确定性详情（证据/产品/指标/分析/对比/地区/企业）
POST /api/v1/briefings                     从 analysis_id 生成简报（不重算事实）
GET/PATCH /api/v1/me/preferences           经理偏好
GET  /api/v1/me/capabilities               功能与资料源
POST /api/v1/tools/{tool}                  Coze 调用受控工具（X-Context-Token）
POST /api/v1/data-sources ...              资料源登记/校验/激活/停用
GET  /api/v1/extensions ...                扩展目录与绑定
POST /api/v1/feedback                      经理反馈
```

## 测试与验收

数字以命令实际输出为准（本节数字即由下面两条命令产出）：

```bash
python -m unittest discover -s tests -t .   # 单元/验收测试：150 项通过
python smoke_test.py                        # 冒烟测试：60 项通过
```

- 单测覆盖：**三阶段口径**与年份、工具与产品卡、分析校验与保存、SSE 对话网关、地区隔离与资料源、
  国别与供应链回归、N08 引用白名单、LangGraph 引擎适配与冷启动容错。
- `tests/test_stages.py` 专门锁死三阶段口径：**按落点判别**（非按内部标签）、T0/T1 与 T2 互斥、
  强度分与阶段一致，以及**对外输出不得再出现旧抽取标签与旧分层字样**（口径回退即测试失败）。
- `smoke_test.py` 面向数据与业务口径（知识库规模、评分卡、供应链、国别识别等），与单测互补，**不重复计数**。
- 本轮之前的历史文档曾同时出现 76／92／115 三种测试数，均属旧口径；**以后统一以本节为准**，
  改动测试后请同步更新此处数字。

## 演示提示

- 供应链示例企业：**002860 星帅尔**（浙江，窗口期，客户：松下/夏普/惠而浦/三星/LG/美的/格兰仕等，来自年报具名客户锚点）。
  其他企业无具名客户时显示引导跳转。
- 证据链：名单 → 企业详情 → 信号卡片 →「查看原文证据」→ 弹窗内黄色高亮为证据区间（描边为重点片段）。
- 简报页支持浏览器打印/导出 PDF。
- 名单页含两张表：**辖区出海线索名单（窗口期，T0/T1）** 与 **存量挖转名单（T2 存量期）**，
  顶部筛选条件对两张表同时生效。
- 对话工作台演示路径（右下角「AI 助手」）：
  企业详情页问“这家公司值得关注什么？”→ 点光球核查原文/产品依据 →
  “找江苏有产能部署的光伏企业”→“第二家为何入选？”→“比较前两家”→“重点谈结算，不考虑融资”→“做一页简报和五个问题”。
  回答标注“规则演示”为本地降级引擎输出；配置 Coze 后由工作流生成并标注工作流版本。

## 数据口径与边界

- 数据：电气设备行业 2018-2023 全量 317 家（1,594 公司-年），冻结语料来自
  `技术链/出海预测/outputs`，全部抽取主张 23,718 条，其中出海需求信号 4,067 条；
  这些信号按三阶段归类后，窗口期（T0/T1）覆盖 983 个企业-年（T0 筹备期 591、T1 落地期 392）；不宣称逐条人工验证。
- 底层文本抽取的内部标签只用于筛选出海需求信号，**不作为对外口径**；对外一律表述为 T0/T1/T2 三阶段。
- 已接入匿名前五大客户/供应商及集中度，**只做法定单跳画像**。匿名对象不跨企业拼接；有限来源不代表全量供应链。**多跳关联查询、银行实名关系与 Neo4j 均为设计预留，本项目不实现**。
- 交易对手的境外标记按**名称专用**规则识别（只认名称开头或分隔符片段内的国别词），避免「上海顺斯德国际贸易有限公司 → 德国」这类中文字串误命中；该标记表示名称中的国别线索，正式境外属性仍需证据核实。
- 国别信息为**占位数据**（公开区域信息 + 银行内部规则占位），不构成行内产品事实。
- 能力分级为**辅助判断**，不替代人工尽调。

## 增量路线（未在本闭环）

1. Coze 工作流发布：`coze/` 工件已备齐，待 Coze 工作空间与 API 授权后按 `coze/workflow_design.md` 搭建发布；
2. 现有317家样本按现有产业链字典细分，不增加行业或企业；
3. 动因（motive）字段抽取 → Layer2 动因→方案路径（2-3 天）；
4. 方向验证（400 条人工标注 + 判别效度 + 双模型一致性）；
5. Neo4j：系统设计预留——银行提供有权限的实名交易关系后，可经适配接口映射统一企业 ID、关系类型、年度/有效期、金额、来源与授权范围，再接入做**多跳关联检索**；本项目不实现；
6. 匿名供应链只作局部结构画像，不建设全量供应链；
7. 正式身份系统：**不属本项目实现目标**——现用演示身份（`demo-token-region-a/b`）与合成示范资料；`users.identity_mode` 与 `authenticate()` 已留出行内身份接入位，投产时由行内统一认证替换（本项目只描述此接入点）。
