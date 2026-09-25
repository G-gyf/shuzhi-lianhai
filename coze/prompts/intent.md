# 意图与参数识别（N02 大模型节点）

输入：用户消息、page_context、history_summary（最近若干轮，仅供理解，不作事实来源）。

输出 JSON（只输出对象，无多余文字）：
{
  "intent": "search | explain | compare | plan | clarify | general",
  "companies": [{"scode": "002860"}],
  "year": 2023,
  "filters": {"province": "江苏省", "industry": "光伏", "direction": "capacity_production"},
  "service_preferences": {"service_focus": ["settlement"], "exclude_financing": true},
  "clarify_options": ["候选1", "候选2"]
}

规则：
- “最近”解释为最新可用数据年度，不擅称实时。
- “前两家”“第二家”“这家”等指代只绑定上一条工具结果集的稳定ID（后端会给出），
  不得按当前重新排序后的名单猜测。
- 企业不明确且没有页面上下文时，intent=clarify 并提供选项。
- intent=general 时不为企业问题调用企业分析。
- 若信息不足以识别，宁可 clarify，不要编造参数。
