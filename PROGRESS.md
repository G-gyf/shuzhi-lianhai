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
| 1 | **Coze 工作流 / 自然语言助手** | 应用层 | ❌ 暂缓（用户决定）；用途=对话式查询入口，替代方案=本地 /ask 接口 |
| 2 | 光伏行业接入 | 数据接入层 | ❌ industry 参数已预留；需语料采集+标注+面板（1-1.5 周） |
| 3 | 动因字段抽取 | 信号层 Layer2 | ❌ 提示词加 motive 字段+增量标注（2-3 天） |
| 4 | 方向验证 | 验证层 | ❌ 400 条人工标注+判别效度+双模型一致性（约 3 天） |
| 5 | 国别归一化 | 信号层 | ❌ 词典型口径已知假阳性；别名+剔区域词+剔历史句（2-3 天） |
| 6 | Neo4j 实库切换 | 图存储层 | ❌ 适配层已写好，设 NEO4J_URI 即切；待数据规模 |
| 7 | 实控人边 / 全量供应链边 | P1/P2 扩展 | ❌ 图谱多跳激活条件 |
| 8 | 供应链示例真实性核查 | 示例库 | ⚠️ named_customer 边来自年报锚点（真实），未逐条人工核对 |
| 9 | 线上端到端验证 | 部署 | ✅ 已完成（2026-09-19：health + Pages 全链路通过） |
| 10 | 演示故事线打磨 | 展示层 | ❌ 3-5 家明星企业案例包装 |

## 三、已知口径提醒（对外材料前必查）

- 强度分默认排序键 = 窗口类型 → 分层 → 强度分（业务口径）；前端已提供"强度分优先"切换。
- 供应链示例仅 002860 等具名客户企业有数据；供应商边为 P2 占位。
- 国别卡片为占位文案，不构成行内产品事实。
- 能力分级为辅助判断，不替代人工尽调。
