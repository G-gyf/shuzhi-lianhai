# -*- coding: utf-8 -*-
"""出海全周期三阶段口径验收。

口径定义见 rules/stages.json：
  T0 筹备期 — 当年有出海需求信号，且不含任何「落点类信号」
  T1 落地期 — 当年有出海需求信号，且至少 1 条为「落点类信号」
  T2 存量期 — 已形成海外布局（海外子公司>0 或海外收入占比>0）
「出海前窗口期」仅含 T0 与 T1；T2 不属于窗口期，走单独入口（/api/stock）。

本文件锁住四件事：
1. 三阶段按「落点」判，**不是**按内部抽取标签判（两者不等价，误用会错分约 28% 的需求信号）；
2. 窗口期名单只出 T0/T1，T2 存量名单与窗口期名单互斥、不重复计数；
3. 强度分与三阶段口径一致：2×T1信号 + 1×T0信号 + 硬锚点数 + min(方向数,3) − 1；
4. **对外输出不得再出现旧五类标签与「筹备层/落地层」字样**（口径回退即失败）。
"""
import json
import os
import re
import unittest

from server import logic, runtime
from server.logic import (LANDING_ANCHORS, LANDING_DIRECTIONS,
                          STAGE_T0, STAGE_T1, STAGE_T2, WINDOW_STAGES)

# 旧口径禁用词：五类抽取标签 + 旧分层名
BANNED = ("经营部署", "战略意图", "已有出海行为", "出海口号", "出海无关",
          "筹备层", "落地层")


def _strip_internal(obj):
    """递归序列化为文本，用于扫描对外口径里是否出现禁用词。"""
    return json.dumps(obj, ensure_ascii=False, default=str)


class TestStageTaxonomy(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        runtime.init_runtime()

    # ---- 1) 口径单一来源与内部一致性 ----
    def test_stages_json_is_wellformed(self):
        st = logic.rules()["stages"]
        self.assertEqual(st["window"]["stages"], [STAGE_T0, STAGE_T1],
                         "出海前窗口期只能含 T0 与 T1")
        self.assertTrue(st["stages"]["T0"]["in_window"])
        self.assertTrue(st["stages"]["T1"]["in_window"])
        self.assertFalse(st["stages"]["T2"]["in_window"],
                         "T2 存量期不属于窗口期")

    def test_window_firm_definition_matches_requirement(self):
        w = logic.rules()["stages"]["window"]
        self.assertIn("尚未出海或布局未成熟", w["firm_definition"])
        self.assertIn("已出海但结算融资不在工行", w["stock_definition"])

    def test_chains_stage_label_consistent_with_stages(self):
        """chains.json 的 stage_label 必须与 stages.json 的 name 一致（防两处漂移）。"""
        cl = logic.rules()["chains"]["stage_label"]
        sd = logic.rules()["stages"]["stages"]
        for k in (STAGE_T0, STAGE_T1, STAGE_T2):
            self.assertEqual(cl[k], sd[k]["name"], f"{k} 标签不一致")

    # ---- 2) 三阶段按「落点」判，不是按内部标签判 ----
    def test_stage_uses_landing_anchor_not_internal_label(self):
        """含落点类锚点 → T1；不含 → T0，与内部抽取标签无关。"""
        # 锚点在落点集合内 → T1
        self.assertEqual(logic._claim_stage("market_expansion", "overseas_entity"), STAGE_T1)
        self.assertEqual(logic._claim_stage("null", "project_or_base"), STAGE_T1)
        # 方向在落点集合内 → T1
        self.assertEqual(logic._claim_stage("capacity_production", "none"), STAGE_T1)
        self.assertEqual(logic._claim_stage("investment_ma", "none"), STAGE_T1)
        # 两者都不在 → T0
        self.assertEqual(logic._claim_stage("market_expansion", "region"), STAGE_T0)
        self.assertEqual(logic._claim_stage("channel_supply_chain", "named_customer"), STAGE_T0)

    def test_landing_rule_sets_match_stages_json(self):
        lr = logic.rules()["stages"]["landing_rule"]
        self.assertEqual(set(lr["directions"]), LANDING_DIRECTIONS)
        self.assertEqual(set(lr["anchor_types"]), LANDING_ANCHORS)

    def test_agg_stage_matches_n_t1(self):
        g = logic.agg()
        for _, r in g.iterrows():
            expect = STAGE_T1 if r["n_t1"] > 0 else STAGE_T0
            self.assertEqual(r["stage"], expect)
            self.assertEqual(int(r["n_t0"] + r["n_t1"]), int(r["n_claims"]))

    def test_intensity_formula_matches_three_stages(self):
        """强度分＝2×T1信号 + 1×T0信号 + 硬锚点数 + min(方向数,3) − 1。"""
        g = logic.agg().head(200)
        for _, r in g.iterrows():
            expect = (2 * int(r["n_t1"]) + int(r["n_t0"]) + int(r["n_hard"])
                      + min(len(r["directions"]), 3) - 1)
            self.assertEqual(int(r["score"]), expect)

    # ---- 3) 窗口期名单只出 T0/T1；T2 互斥 ----
    def test_radar_only_contains_window_stages(self):
        rows = logic.radar(limit=5000)
        self.assertTrue(rows)
        stages = {r["stage"] for r in rows}
        self.assertTrue(stages <= set(WINDOW_STAGES),
                        f"窗口期名单出现了非窗口期阶段：{stages - set(WINDOW_STAGES)}")
        for r in rows:
            self.assertTrue(r["stage_in_window"])
            self.assertIn("筹备期" if r["stage"] == STAGE_T0 else "落地期", r["stage_full"])

    def test_stage_filter_uses_landing_anchor_not_label(self):
        """阶段划分必须能推出对应的落点证据：T1 必含落点信号，T0 必不含。"""
        cl = logic._claims()
        for r in logic.radar(limit=300):
            cur = cl[(cl["scode"] == r["scode"]) & (cl["year"] == r["year"])
                     & cl["program_label"].isin(logic.DEMAND_SIGNAL_LABELS)]
            landing = (cur["direction"].isin(LANDING_DIRECTIONS)
                       | cur["execution_anchor_type"].isin(LANDING_ANCHORS)).sum()
            if r["stage"] == STAGE_T1:
                self.assertGreater(int(landing), 0, f"{r['scode']} 判 T1 但无落点信号")
            else:
                self.assertEqual(int(landing), 0, f"{r['scode']} 判 T0 但有落点信号")

    def test_stock_and_window_are_mutually_exclusive(self):
        window = {(r["scode"], r["year"]) for r in logic.radar(limit=5000)}
        stock = {(r["scode"], r["year"]) for r in logic.stock_radar(limit=5000)}
        overlap = window & stock
        self.assertEqual(overlap, set(),
                         f"窗口期名单与存量名单重复计数：{list(overlap)[:5]}")

    def test_stock_rows_satisfy_layout_rule(self):
        rows = logic.stock_radar(limit=5000)
        self.assertTrue(rows, "存量名单不应为空")
        for r in rows:
            self.assertEqual(r["stage"], STAGE_T2)
            self.assertFalse(r["stage_in_window"])
            subs = r["overseas_sub_count"]
            rev = r["overseas_rev_share"]
            self.assertTrue((subs is not None and subs > 0) or (rev is not None and rev > 0),
                            f"{r['scode']} 无海外布局依据却被判为存量期")

    # ---- 4) 对外口径不得出现旧五类与旧分层名 ----
    def test_no_banned_terms_in_radar_output(self):
        blob = _strip_internal(logic.radar(limit=50))
        for w in BANNED:
            self.assertNotIn(w, blob, f"窗口期名单对外输出仍出现旧口径「{w}」")

    def test_no_banned_terms_in_stock_output(self):
        blob = _strip_internal(logic.stock_radar(limit=50))
        for w in BANNED:
            self.assertNotIn(w, blob, f"存量名单对外输出仍出现旧口径「{w}」")

    def test_no_banned_terms_in_company_detail_and_chain(self):
        rows = logic.radar(limit=1)
        scode, year = rows[0]["scode"], rows[0]["year"]
        for obj, name in ((logic.company_detail(scode, year), "company_detail"),
                          (logic.chain(scode, year), "chain"),
                          (logic.segments(year=year), "segments"),
                          (logic.evidence(rows[0]["top_chunk"]), "evidence")):
            blob = _strip_internal(obj)
            for w in BANNED:
                self.assertNotIn(w, blob, f"{name} 输出仍出现旧口径「{w}」")

    def test_no_banned_terms_in_briefing(self):
        rows = logic.radar(limit=200)
        checked = 0
        for r in rows:
            b = logic.briefing(r["scode"], r["year"])
            if not b:
                continue
            blob = _strip_internal(b)
            for w in BANNED:
                self.assertNotIn(w, blob, f"briefing 输出仍出现旧口径「{w}」")
            checked += 1
            if checked >= 5:
                break
        self.assertGreater(checked, 0, "未取到可用于验证的简报样本")

    def test_old_terms_only_remain_as_internal_db_mapping(self):
        """旧五类名只允许存在于「内部标签常量 + 建库脚本」两处，不得散落在业务代码里。"""
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        offenders = []
        for dp, dns, fns in os.walk(root):
            dns[:] = [d for d in dns if d not in
                      ("__pycache__", ".git", "kb", "runtime", "tests", "docs", "coze")]
            for fn in fns:
                if not fn.endswith(".py"):
                    continue
                p = os.path.join(dp, fn)
                rel = os.path.relpath(p, root).replace("\\", "/")
                if rel in ("server/logic.py", "kb_build.py", "profile_chain.py"):
                    continue          # 内部标签定义与建库脚本：允许
                txt = open(p, encoding="utf-8", errors="replace").read()
                for w in ("经营部署", "战略意图", "已有出海行为", "出海口号", "出海无关"):
                    if w in txt:
                        offenders.append((rel, w))
        self.assertEqual(offenders, [],
                         f"旧五类标签散落在业务代码中，应改用三阶段口径：{offenders}")

    # ---- 5) 接口与 meta 口径 ----
    def test_meta_exposes_lifecycle(self):
        from server.main import api_meta
        m = api_meta()
        lc = m["lifecycle"]
        self.assertEqual(lc["window"]["stages"], [STAGE_T0, STAGE_T1])
        self.assertEqual([s["key"] for s in lc["stages"]], [STAGE_T0, STAGE_T1, STAGE_T2])
        self.assertIn("落地期信号", lc["score_formula"])

    def test_radar_route_declares_window_scope(self):
        from server.main import api_radar
        d = api_radar(province="江苏省", year=2023, limit=5)
        self.assertEqual(d["scope"], "window")
        self.assertEqual(d["stages"], [STAGE_T0, STAGE_T1])
        self.assertIn("T2", d["note"])

    def test_stock_route_separate_entry(self):
        from server.main import api_stock
        d = api_stock(year=2023, limit=5)
        self.assertEqual(d["stage"], STAGE_T2)
        self.assertIn("挖转", d["note"])
        self.assertEqual(len(d["items"]), min(5, d["total"]))
        self.assertGreater(d["total"], 0)

    # ---- 6) 阶段在企业详情/推理链里可核验 ----
    def test_company_detail_carries_stage_rule(self):
        rows = logic.radar(limit=200)
        seen = set()
        for r in rows:
            d = logic.company_detail(r["scode"], r["year"])
            w = d.get("window")
            if not w:
                continue
            self.assertEqual(w["stage"], r["stage"])
            self.assertTrue(w["stage_rule"])
            self.assertFalse(w["stage_in_window"] is None)
            seen.add(w["stage"])
        self.assertEqual(seen, {STAGE_T0, STAGE_T1}, "样本应同时覆盖 T0 与 T1")

    def test_chain_first_step_is_stage_judgement(self):
        rows = logic.radar(limit=50)
        for r in rows:
            ch = logic.chain(r["scode"], r["year"])
            if not ch:
                continue
            s0 = ch["steps"][0]
            self.assertEqual(s0["key"], "window")
            self.assertEqual(s0["stage"], r["stage"])
            self.assertIn("筹备期" if r["stage"] == STAGE_T0 else "落地期", s0["title"])
            self.assertRegex(s0["detail"], r"筹备期（T0）\d+ 条、落地期（T1）\d+ 条")
            return
        self.fail("未取到推理链样本")


if __name__ == "__main__":
    unittest.main()
