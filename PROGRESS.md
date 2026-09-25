> 当前状态：见 [20260925更新说明](docs/当前口径与实施更新_20260925.md)。下方版本记录保留历史，不代表所有云端能力已经上线。

# 数智链海 · 实施进度清单（截至 kb-2023 最小闭环 + 线上部署）

## 一、已完成（文件级明细）

### 数据层
| 项 | 文件 | 内容 |
|---|---|---|
| 知识库构建脚本 | `kb_build.py` | 从 技术链/出海预测/outputs 读 4 个源文件 → SQLite 快照 |
| 知识库快照 | `kb/kb-2023.sqlite` | 37,946 chunks / 23,718 claims（含 country_hits 国别词提取）/ 1,594 firm_year / 317 家 / 子公司国家表 / meta 表 |

### 规则库（金融队员可直接改 JSON）
| 项 | 文件 | 内容 |
|---|---|---|
| 产品与匹配规则 | `rules/products.json` | 15 产品目录（五位一体+前置服务）、direction_map（6 方向→模式+产品）、anchor_extra（7 类锚点补充）、window_extra（3 窗口类型补充）、country_extra、10 条前置条件 |
| 能力评分卡 | `rules/scoring.json` | 6 维度（国际化基础/规模/盈利/研发/财务安全/客户依赖）+ 同年度样本内分位归一 + 3 级分级（就绪/蓄力/薄弱） |
| 推理链模板 | `rules/chains.json` | 4 步顺序（窗口期/方向模式/产品匹配/前置条件）+ 窗口与分层标签 |
| 国别占位卡 | `rules/countries.json` | 102个规范国家/地区词条归属 + 清算/司库/避险占位文案 |

### 服务层
| 项 | 文件 | 内容 |
|---|---|---|
| 规则引擎 | `server/logic.py` | 窗口分类（当期未见布局/新国别/扩张/布局未知/标签不完整）、筹备-落地分层、强度分公式、radar 双排序模式（window/score）、能力评分、4 步推理链、4 段简报、证据查询、供应链示例（named_customer 客户边+子公司国家边，sample 标记） |
| 图适配层 | `server/graph.py` | SQLite 证据子图；Neo4j仅银行实名数据扩展设计，本项目不实现+ 国别卡片 |
| API | `server/main.py` | 网页及v1对话/扩展接口，以docs/当前接口清单.md实际路由导出为准；radar返回真实total，segments支持年度等筛选 |

### 展示层（零外部依赖，SVG 手绘）
| 项 | 文件 | 内容 |
|---|---|---|
| 前端 | `web/index.html` + `web/assets/app.js` + `style.css` | 三视图（雷达名单/企业详情/访前简报）+ 证据高亮弹窗 + SVG 能力雷达图 + SVG 关系图 + 供应链 tab + 国别卡 + 排序切换 + 打印简报 |
| 部署配置 | `web/config.js` | API 地址开关（本地同源 / 线上 Railway 域名） |

### 部署
| 项 | 文件 | 状态 |
|---|---|---|
| 容器化 | `Dockerfile` + `requirements.txt`（锁 numpy==1.26.4 修复二进制不兼容） | ✅ |
| Pages 自动部署 | `.github/workflows/pages.yml`（含自动启用 Pages） | ✅ |
| 一键启动/推送 | `start.bat` / `push.bat` | ✅ |
| 部署手册 | `DEPLOY.md` | ✅ |
| GitHub 仓库 | github.com/G-gyf/shuzhi-lianhai | ✅ 已推送 |
| Railway 后端 | shuzhi-lianhai-production.up.railway.app | ✅ 已部署 |
| GitHub Pages 前端 | g-gyf.github.io/shuzhi-lianhai | ✅ 已上线（待最终验证） |

## 二、未完成（对照清单）

| # | 项 | 框架位置 | 状态/计划 |
|---|---|---|---|
| 1 | **Coze 工作流 / 自然语言助手** | 应用层 | 待实施：Coze云端工作流未发布联调；网页对话/光球/网关及本地规则接入基础已实现 |
| 2 | 现有样本细分 | 标签层 | 已按七个细分标注；不扩样 |
| 3 | 动因字段抽取 | 信号层 Layer2 | ❌ 提示词加 motive 字段+增量标注（2-3 天） |
| 4 | 方向验证 | 验证层 | ❌ 400 条人工标注+判别效度+双模型一致性（约 3 天） |
| 5 | 国别归一化 | 信号层 | ✅ v1.3 完成：geo 层最长匹配+别名归一+区域分列+排除误匹配；抽检报告 `audit/geo_audit.txt` |
| 6 | Neo4j | 系统设计 | 银行实名数据扩展预留，本项目不实现 |
| 7 | 实控人边 / 全量供应链边 | P1/P2 扩展 | ⚠️ v1.4 已接入 CSMAR 前五大客户/供应商量化边 + 二跳链（36 家）；银行授权实名关联仅为设计预留，不属本项目实施范围 |
| 8 | 供应链示例真实性核查 | 示例库 | ✅ v1.4：量化边来自 CSMAR 结构化数据（前五大+金额+占比）；具名客户多为"客户一~五"匿名，境外具名客户 3 家示例已识别（汇源通信-丹麦、通达股份-巴基斯坦/秘鲁、康平科技-越南） |
| 9 | 线上端到端验证 | 部署 | ✅ 2026-09-25 复验：线上快照与本地一致（kb-2023@c080c94c0e56），生成式引擎可用；详见「八、线上现状」 |
| 10 | 演示故事线打磨 | 展示层 | ❌ 3-5 家明星企业案例包装 |

## 三、已知口径提醒（对外材料前必查）

- 强度分默认排序键 = 窗口类型 → 分层 → 强度分（业务口径）；前端已提供"强度分优先"切换。
- 已接入匿名前五大客户及供应商；匿名排名不作为跨企业实体标识。
- 国别卡片为占位文案，不构成行内产品事实。
- 能力分级为辅助判断，不替代人工尽调。

## 四、v1.3 规则引擎九项优化（2026-10 实施，smoke_test.py 31/31 通过）

| # | 优化点 | 落地方式 | 验证结果 |
|---|---|---|---|
| 1 | 统一年份上下文 | 5 个接口加 `?year=`（company/graph/supply-chain/chain/briefing）；前端点击名单行即按该行年度打开详情 | 002860 以 2018/2023 打开，详情·推理链·简报年份全部一致 |
| 2 | 区分当前与历史信号 | 产品推荐只消费所选年度信号；`history` 字段单独归档并注明"不参与推荐" | 2023 详情 signals=2（当年）/ history=15（存档） |
| 3 | 修正新国别判断 | 子公司国别集合改为 as-of（year < t），不再用全期集合 | 重分类矩阵：expansion 780→710，new_country 113→183（70 个企业-年倒灌修正），first 不受影响 |
| 4 | 国别名称标准化 | `server/geo.py`：最长匹配优先、别名归一、排除印度洋/内蒙古等误匹配 | 抽检：香港97→区域、印尼95→印度尼西亚、印度18 重复命中消除、"北美+国"跨界误命中 1 例消除；`audit/geo_audit.txt` 供人工抽检 |
| 5 | 区分国家/地区/市场区域 | geo 层输出 countries（canonical）/regions（区域标签）分列；区域不再冒充国家 | 东南亚475/全球1314/海外1561 等区域单独展示；国别卡对区域返回 type=region 提示 |
| 6 | 缺失值明确为未知 | 面板缺失字段输出 None→前端"待核实"；能力分按可得维度重新归一+数据完整度 x/5；雷达图缺失维度不画顶点 | 无面板企业返回 grade=待核实 |
| 7 | 明确首次出海口径 | 窗口标签改为"出海线索首现期"，附口径注记（无已知布局线索，历史待人工核实） | 不再断言"首次出海" |
| 8 | 修正产品触发条件 | anchor_extra 改为条件触发（if_directions 语境守卫+reason），并购融资仅限投资并购方向 | 如"投资或合同"锚点在非并购方向不再触发 ma_loan |
| 9 | 建议绑定对应证据 | 推理链/简报每条建议携带 rule_id / signal_id（chunk#claim）/ evidence_id，前端展示并可跳原文 | 产品步骤逐条显示规则ID·信号ID·证据引文 |

改动文件：`server/geo.py`（新增）、`rules/countries.json`（当时72词条；现有102个规范国家/地区词条+别名+区域+排除）、`rules/products.json`（条件锚点触发）、`rules/chains.json`（标签+口径注记）、`server/logic.py`（重写核心）、`server/graph.py`、`server/main.py`、`web/assets/app.js`、`web/assets/style.css`（新增 .rc/.prod/.tiny/.hist-note，桌面原样式未动）、`audit_geo.py`（新增）、`smoke_test.py`（新增）。

## 五、v1.3.1 交互与口径修正（smoke_test.py 34/34 通过）

- **历史信号口径**：仅收录所选年度**以前**的披露（选 2018 年时历史为空，不再把 2019-2023 冒充"历史依据"）。
- **产品匹配紧凑化**：推理链产品步骤标题改为"匹配 N 款产品"，产品明细收进可点击展开的卡片（`<details>`：依据 + 规则ID + 信号ID + 证据按钮），默认只列产品名。
- **前置条件列表化**：prereq 步骤新增 `items` 字段，前端以列表逐条渲染，不再是一长段文字。
- **证据跳转修复**：全站证据跳转改为事件委托（`data-ev` 按钮 + `bindEvidence`），信号列表与推理链统一通道；加载失败时显式提示，不再静默无响应。`/api/evidence/{chunk_id}` 已验证 200。

## 六、v1.4 供应链数据接入（smoke_test.py 47/47 通过）

- **建库**：`sc_build.py` 从 `供应链相关数据/CSMAR` 抽 317 家样本 2018-2023（合并报表）→ `kb/kb-sc-2023.sqlite`：
  top5_sale 7,504 行 / top5_purchase 7,448 行 / concentration 1,594 行（均 317 家全覆盖）/ distance 1,187 行（77 家）/ network 95 行（36 家）。
- **访问层**：`server/sc.py`（`top5_sale/top5_purchase/concentration/network` + `sc_of()` 画像 + 海外客户识别）。
- **供应链接口升级**：`supply_chain()` 输出结构化量化边（CSMAR 前五大：名称+排名+金额+占比，BUYS_FROM 供应商边自 v1.4 起为真实数据）+ 文本具名锚点边 + 子公司国家边（as-of）+ 二跳链；前端供应链卡新增"前五大明细+集中度+二跳传导链"列表。
- **评分卡第 6 维**：`客户依赖（反向）`（前五大客户销售占比，table=sc，按样本分位归一）；简报"一、能力就绪度"追加客户依赖风险句、"二、出海需求判断"追加结构化供应链验证句。
- **海外客户识别**：名称经 geo 层提取 canonical 国别（排除内蒙古等误匹配），命中 10 行 / 3 家示例：
  汇源通信（HF公司-丹麦 3.7-4.8%）、通达股份（巴基斯坦 NTDC 7.85%、秘鲁 PROYECTOS 10.27%）、康平科技（荣宝雨-越南 2.6-4.8%）。
- **雷达新列**："海外客户占比"（top5 中境外客户销售占比之和）。
- **二跳链示例**（network 表，2019）：000922→(客户)002598→(客户)600388；002471→(客户)920167→(供应商)000630。
- 验证：47/47 smoke 通过；`app.js` 语法通过；Dockerfile `COPY . .` 自动携带新库。

## 七、v2.0 Coze 对话工作台（本地接入基础已实现；Coze云托管待实施；历史测试38/38，2026-09-25）

> 生成式引擎已于 2026-09-25 经 **扣子编程（LangGraph 路径）**上线，见第八节。
> 本节所称「Coze 云端工作流」指 coze.cn 低代码工作流的另一条接入路径，仍未发布。

依据 `docs/Coze智能体与光球交互_完整实施方案.md` 实施；详见 `docs/Coze对话工作台_实施说明.md`。

| 阶段 | 关键交付 |
|---|---|
| M0 口径修复/协议冻结 | `server/schemas.py`（请求/结果/引用/SSE 事件协议）、快照ID（kb 内容哈希）、文本版本（稳定引用）、严格年度（无数据不回退未来年份）、真实总数与分页 |
| M1 工具与产品卡 | `server/tools.py` 8 个受控工具（resolve/search/get_company_context/get_evidence/compare/rule_candidates/product/regional）、`knowledge/products/product_cards.json`（15 卡 · 8 张 verified）、证据包 evidence_ref 可还原 |
| M2 Coze 与分析网关 | `coze/`（workflow_design.md / tool_openapi.yaml / prompts×4 / 合成样例×2）、`server/coze_client.py`（stream_run/超时/错误映射）、`server/local_engine.py`（降级规则引擎：意图/指代/偏好/资格判定）、`server/analysis_service.py`（硬性校验/持久化/光球/简报复用）、`server/tool_api.py` + `server/context_token.py`（Coze 云端调用受控工具：HMAC 短期令牌/允许工具/快照漂移保护） |
| M3 网页对话/光球/抽屉 | `web/assets/chat.js`（SSE 消费/取消/会话恢复/上下文代际防串台）、`orbs.js`（类型光球/点亮/悬停/引用高亮）、`drawer.js`（七类引用详情/失败重试/Esc/滚动恢复）、`chat.css`、`server/chat.py`（SSE 网关 8 事件）、`server/references.py` |
| M4 偏好与地区扩展 | `server/profiles.py`（偏好 GET/PATCH、capabilities）、`server/extensions.py` + `server/adapters/`（document_reader_v1/table_reader_v1：登记→校验→预览→激活→停用）、`runtime/app_runtime.sqlite`（方案 11.2 全部元数据表）、合成示范地区资料（A 区可检索/B 区 403） |
| M5 测试与文档 | `tests/`（M0—M4 五个文件 38 用例全通过）、本说明、README 更新 |

### 模式与边界

- **默认**：`AI_ENABLED` 未配置 → 本地规则分析引擎（回答标注“规则演示”，事实引用确定性数据库）；Coze 配置后走工作流流式接口，失败自动降级（方案 12.3）。
- **演示身份**：`demo-token-region-a` / `demo-token-region-b`（Bearer 令牌，服务端解析辖区）；正式多人使用前必须替换为行内身份系统。
- Coze 工作流本身为**待实施配置**：`coze/` 提供全部节点配置、提示词与 OpenAPI 插件协议；发布需 Coze 工作空间与 API 授权（方案 16 章输入）。

## 八、线上现状（2026-09-25 复验）

| 项 | 状态 |
|---|---|
| 后端 | `https://shuzhi-lianhai-production.up.railway.app`（HTTP 200） |
| 前端 | `https://g-gyf.github.io/shuzhi-lianhai`（HTTP 200，含 AI 工作台改版） |
| 知识库快照 | `kb-2023@c080c94c0e56`，active 37,946 / excluded 3，**与本地一致** |
| **生成式引擎** | ✅ **已上线**：落库 `engine=langgraph`、`workflow_version=https://kmj3bsz4kj.coze.site`；单轮响应 28—37 秒；`provenance` 完整（engine / workflow_version / generated_at） |
| 降级路径 | langgraph 调用失败（如 `http_404 instance_not_found`）时自动回退 `rules-demo`，并在 `warnings` 首条明示原因 |
| 探活 | `/api/health` 默认对「将优先尝试的引擎」**真实探活**（带 `LANGGRAPH_TOKEN`，60 秒缓存；`?probe=0` 跳过）。判据为 `engine.reachable` / 顶层 `engine_ready` |
| 单元测试 | 92 项通过；`smoke_test.py` 46 通过 / 1 项断言待随口径同步 |

### 本轮修复的两处线上缺陷（回归项）

1. **`/api/health` 假绿灯**：原实现只判断 `LANGGRAPH_BASE_URL` 是否存在，不发探活请求，因此引擎实例被回收（404 `instance_not_found`）期间仍显示 `effective_engine=langgraph`。现改为真实探活，并把 `effective_engine`/`planned_engine`（按配置）与 `reachable`（按探活）分开表述。
   技术要点：扣子编程**部署后**的服务网关对**所有路径**统一鉴权，不带 Bearer 一律 401，因此探活必须带 `LANGGRAPH_TOKEN`（原 `langgraph_client.health()` 不带令牌，线上必然失败）。
2. **`request_started.engine` 误报**：原为 `"coze" if ai_enabled else "rules-demo"` 写死值，且在引擎决议前发出——降级到规则引擎时它报 `coze`，实际走 langgraph 时它也报 `coze`。现改为回报 `planned_engine()` 并附 `engine_resolved=false`；真实生效引擎见 `analysis_ready.engine` 与落库记录。

### 已知待办

- `smoke_test.py` 中 first 口径注记断言与现行 `rules/chains.json` 措辞不一致（测试侧待同步）；
- 建议在 `tests/` 增补一条**非正则措辞**用例（如「A 和 B 相比，谁更适合先谈跨境资金池？」），用于证明引擎在做推理而非命中正则；
- Railway 容器文件系统为临时：`runtime/app_runtime.sqlite`（会话/分析）在**重新部署后重置**，`#analysis=` 深链会失效——演示当天不要重新部署；
- 扣子沙箱实例长时间（约 1 小时）无请求可能被回收，演示前建议先发一次预热请求。
