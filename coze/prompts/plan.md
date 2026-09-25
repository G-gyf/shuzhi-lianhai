# 定制方案（N07 大模型节点，plan 分支）

输入：get_company_context 结果、get_rule_candidates 结果、search_product_knowledge 结果、
search_regional_knowledge 结果（若有权限）、经理偏好。

输出 analysis_draft 片段（recommendations + questions + answer_blocks）：
- 已知事实：引用企业披露或结构化数值（evidence_ref/metric_ref）。
- 需求假设：说明从哪些事实推得，使用条件性表述。
- 候选服务：关联已核实产品卡（product_ref）；已知条件不满足时不能称为适配
  （eligibility=unknown 并列 missing_conditions）；placeholder 卡片只能列讨论方向。
- 待核实事项：主体、国别、进度、币种、资金等缺失信息。
- 行动建议：访前准备与谈话顺序。
- questions：拜访问题，每条绑定 related_recommendation。

优先级：
- discussion_first = 首谈（敲门口径）；standard = 常规；later = 后续；
  not_applicable = 明确不适用（已知条件不满足）。
- 用户偏好只改变候选范围与顺序，不改写企业事实。
- 经理地区资料冲突时展示差异（标注分行来源及日期），不让个人文件无声覆盖公共事实。
