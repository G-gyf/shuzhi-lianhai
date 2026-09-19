# 数智链海 · 最小闭环（MVP）

企业出海金融需求雷达与对公跨境营销助手 —— 系统框架 v1.2 的最小可运行实现。

## 启动

```bash
# 方式一：双击 start.bat（推荐，自动打开浏览器）
# 方式二：命令行
cd 数智链海
python kb_build.py                        # 构建知识库快照（已构建，无需重复）
python -m uvicorn server.main:app --host 127.0.0.1 --port 8000
```

浏览器打开 http://127.0.0.1:8000

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
├─ rules/               # 规则库（金融队员维护，JSON）
│  ├─ products.json     # 五位一体产品目录 + 方向×锚点×窗口 匹配规则 + 前置条件
│  ├─ scoring.json      # 能力评分卡（5 维度 + 分级）
│  ├─ chains.json       # 推理链步骤模板与标签
│  └─ countries.json    # 国别卡片（占位：清算/司库待行内产品库）
├─ server/
│  ├─ main.py           # FastAPI：/api/* 接口 + 静态前端
│  ├─ logic.py          # 规则引擎：窗口期/分层/强度/评分/推理链/简报/供应链示例
│  └─ graph.py          # 图适配层：默认 SQLite 子图；设 NEO4J_URI 后切换 Neo4j
└─ web/                 # 前端三页（零外部依赖，SVG 手绘雷达图/关系图）
   ├─ index.html        # 雷达名单 / 企业详情 / 访前简报 + 证据高亮弹窗
   └─ assets/           # app.js / style.css
```

## 核心判定口径（规则引擎，全部确定性计算）

| 概念 | 规则 |
|---|---|
| 窗口期二分 | 当年有需求（≥1 条部署/意图 claim）且 无海外子公司 且 海外收入=0 |
| 窗口全谱系 | `first`（首次出海）→ `new_country`（锚点国家 ∉ 已进入国集合）→ `expansion`（其余） |
| 筹备/落地分层 | 含落地类信号（产能/并购方向 或 项目/产能/主体/投资锚点）→ 落地层；否则筹备层 |
| 强度分 | `2×经营部署 + 1×战略意图 + 硬锚点数 + min(方向数,3) − 1` |
| 名单排序 | 窗口类型（first 优先）→ 分层（落地优先）→ 强度分 → 年份 |
| 能力评分卡 | 国际化基础/规模/盈利/研发/财务安全 五维，行业内分位归一化加权 → 就绪/蓄力/薄弱 |

## API

```
GET /api/meta                      知识库版本、省份、年份
GET /api/radar?province=&year=     辖区意图强度排行
GET /api/company/{scode}           企业详情（画像+评分+信号）
GET /api/company/{scode}/graph     企业-信号-方向-国别子图
GET /api/company/{scode}/supply-chain  供应链示例（sample 边）
GET /api/company/{scode}/chain     营销方案推理链（4 步结构化）
GET /api/company/{scode}/briefing  访前简报（4 段模板）
GET /api/evidence/{chunk_id}       原文片段 + 证据锚点区间
GET /api/country/{name}            国别卡片（占位）
GET /api/health                    健康检查
```

## 演示提示

- 供应链示例企业：**002860 星帅尔**（浙江，窗口期，客户：松下/夏普/惠而浦/三星/LG/美的/格兰仕等，来自年报具名客户锚点）。
  其他企业无具名客户时显示引导跳转。
- 证据链：名单 → 企业详情 → 信号卡片 →「查看原文证据」→ 弹窗内黄色高亮为证据区间（描边为重点片段）。
- 简报页支持浏览器打印/导出 PDF。

## 数据口径与边界

- 数据：电气设备行业 2018-2023 全量 317 家（1,594 公司-年），冻结语料来自
  `技术链/出海预测/outputs`，信号 23,718 条已通过人工一致性验证（Kappa 0.847）。
- 供应链边为**演示样例**（`sample=true`），供应商边为 P2 扩展位；全量接入后激活多跳。
- 国别信息为**占位数据**（公开区域信息 + 银行内部规则占位），不构成行内产品事实。
- 能力分级为**辅助判断**，不替代人工尽调。

## 增量路线（未在本闭环）

1. 光伏行业接入（industry 字段已预留，管线复跑 1-1.5 周）；
2. 动因（motive）字段抽取 → Layer2 动因→方案路径（2-3 天）；
3. 方向验证（400 条人工标注 + 判别效度 + 双模型一致性）；
4. Neo4j 接入（设 NEO4J_URI/NEO4J_USER/NEO4J_PASSWORD 即切换，kg_api 同款参数）；
5. 实控人边（P1）与全量供应链边（P2）。
