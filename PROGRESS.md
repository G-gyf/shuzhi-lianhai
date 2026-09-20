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
| 能力评分卡 | `rules/scoring.json` | 5 维度（国际化基础/规模/盈利/研发/财务安全）+ 行业内分位归一 + 3 级分级（就绪/蓄力/薄弱） |
| 推理链模板 | `rules/chains.json` | 4 步顺序（窗口期/方向模式/产品匹配/前置条件）+ 窗口与分层标签 |
| 国别占位卡 | `rules/countries.json` | 20 国区域归属 + 清算/司库/避险占位文案 |

### 服务层
| 项 | 文件 | 内容 |
|---|---|---|
| 规则引擎 | `server/logic.py` | 窗口期三分口径（first 首次/new_country 新国别/expansion 扩张）、筹备-落地分层、强度分公式、radar 双排序模式（window/score）、能力评分、4 步推理链、4 段简报、证据查询、供应链示例（named_customer 客户边+子公司国家边，sample 标记） |
| 图适配层 | `server/graph.py` | SQLite 子图实现 + Neo4j 双实现预留（NEO4J_URI 环境变量切换）+ 国别卡片 |
| API | `server/main.py` | 10 接口：meta / radar（province,industry,year,sort）/ company / graph / supply-chain / chain / briefing / evidence / country / health；CORS 全放行；静态挂载 web |

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
| 1 | **Coze 工作流 / 自然语言助手** | 应用层 | ❌ 暂缓（用户决定）；定位=同一中台的第二个触点（NL→调 API→生成式输出+产品手册 RAG） |
| 2 | 光伏行业接入 | 数据接入层 | ❌ industry 参数已预留；需语料采集+标注+面板（1-1.5 周） |
| 3 | 动因字段抽取 | 信号层 Layer2 | ❌ 提示词加 motive 字段+增量标注（2-3 天） |
| 4 | 方向验证 | 验证层 | ❌ 400 条人工标注+判别效度+双模型一致性（约 3 天） |
| 5 | 国别归一化 | 信号层 | ✅ v1.3 完成：geo 层最长匹配+别名归一+区域分列+排除误匹配；抽检报告 `audit/geo_audit.txt` |
| 6 | Neo4j 实库切换 | 图存储层 | ❌ 适配层已写好，设 NEO4J_URI 即切；待数据规模 |
| 7 | 实控人边 / 全量供应链边 | P1/P2 扩展 | ⚠️ v1.4 已接入 CSMAR 前五大客户/供应商量化边 + 二跳链（36 家）；实控人边与全量供应链仍为扩展位 |
| 8 | 供应链示例真实性核查 | 示例库 | ✅ v1.4：量化边来自 CSMAR 结构化数据（前五大+金额+占比）；具名客户多为"客户一~五"匿名，境外具名客户 3 家示例已识别（汇源通信-丹麦、通达股份-巴基斯坦/秘鲁、康平科技-越南） |
| 9 | 线上端到端验证 | 部署 | ✅ 已完成（2026-09-19：health + Pages 全链路通过） |
| 10 | 演示故事线打磨 | 展示层 | ❌ 3-5 家明星企业案例包装 |

## 三、已知口径提醒（对外材料前必查）

- 强度分默认排序键 = 窗口类型 → 分层 → 强度分（业务口径）；前端已提供"强度分优先"切换。
- 供应链示例仅 002860 等具名客户企业有数据；供应商边为 P2 占位。
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

改动文件：`server/geo.py`（新增）、`rules/countries.json`（72 国+别名+区域+排除）、`rules/products.json`（条件锚点触发）、`rules/chains.json`（标签+口径注记）、`server/logic.py`（重写核心）、`server/graph.py`、`server/main.py`、`web/assets/app.js`、`web/assets/style.css`（新增 .rc/.prod/.tiny/.hist-note，桌面原样式未动）、`audit_geo.py`（新增）、`smoke_test.py`（新增）。

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
