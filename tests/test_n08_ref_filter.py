# -*- coding: utf-8 -*-
"""N08 引用白名单过滤的单元测试。

被测算子 `coze/n08_ref_filter.py` 是**扣子编程侧**（LangGraph 项目 N08 节点）的
配套代码，放在本仓库以便版本化与回归——它不参与本项目运行时。
"""
import importlib.util
import unittest
from pathlib import Path

_PATH = Path(__file__).resolve().parents[1] / "coze" / "n08_ref_filter.py"
_spec = importlib.util.spec_from_file_location("n08_ref_filter", _PATH)
n08 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(n08)

TV = "3f9a1c2e"
EV_OK = f"ev:v21_c00020485:3:{TV}"


class TestN08RefFilter(unittest.TestCase):

    def _seen(self):
        return n08.collect_refs({
            "signal_refs": [{"evidence_ref": EV_OK}],
            "rule_candidates": [{"product_ref": "product:settlement"}],
            "metric_refs": {"customer_concentration":
                            "metric:concentration:300827:2023:CustomerConcentration"},
            # 工具响应中的**键名**与业务字段不得被当作引用
            "filter_explanation": "2023年 · 光伏主链 · 落地层",
            "items": [{"scode": "300827", "coname": "上能电气"}],
        })

    def test_collect_refs_only_takes_values_not_keys(self):
        seen = self._seen()
        self.assertEqual(len(seen), 3)
        self.assertIn(EV_OK, seen)
        self.assertNotIn("ev:filter_explanation", seen)
        self.assertFalse(any("item" in s for s in seen))

    def test_fabricated_refs_are_dropped(self):
        draft = {
            "answer_blocks": [{"refs": [EV_OK, "ev:item:300827", "ev:filter_explanation"]}],
            "recommendations": [], "orbs": [],
        }
        clean, dropped = n08.filter_draft_refs(draft, self._seen())
        self.assertEqual(clean["answer_blocks"][0]["refs"], [EV_OK])
        self.assertIn("ev:item:300827", dropped)
        self.assertIn("ev:filter_explanation", dropped)

    def test_illegal_product_ref_is_nulled(self):
        """非法 product_ref 在后端是 block 级问题，会把整次分析降级为 partial。"""
        draft = {
            "answer_blocks": [], "orbs": [],
            "recommendations": [
                {"id": "r1", "product_ref": "product:settlement", "evidence_refs": []},
                {"id": "r2", "product_ref": "product:fake", "evidence_refs": []},
            ],
        }
        clean, dropped = n08.filter_draft_refs(draft, self._seen())
        self.assertEqual(clean["recommendations"][0]["product_ref"], "product:settlement")
        self.assertIsNone(clean["recommendations"][1]["product_ref"])
        self.assertIn("product:fake", dropped)

    def test_partial_orbs_are_cleared_for_backend_fallback(self):
        """只给 product 光球会阻止后端 _default_orbs 兜底 → 必须整段清空。"""
        draft = {
            "answer_blocks": [{"refs": [EV_OK]}], "recommendations": [],
            "orbs": [{"id": "o1", "kind": "product", "ref_id": "product:settlement"}],
        }
        clean, _ = n08.filter_draft_refs(draft, self._seen())
        self.assertEqual(clean["orbs"], [])

    def test_complete_orbs_with_evidence_survive(self):
        draft = {
            "answer_blocks": [{"refs": [EV_OK]}], "recommendations": [],
            "orbs": [{"id": "o1", "kind": "evidence", "ref_id": EV_OK},
                     {"id": "o2", "kind": "product", "ref_id": "product:settlement"}],
        }
        clean, _ = n08.filter_draft_refs(draft, self._seen())
        self.assertEqual(len(clean["orbs"]), 2)

    def test_bad_orb_kind_is_dropped(self):
        draft = {
            "answer_blocks": [], "recommendations": [],
            "orbs": [{"id": "o1", "kind": "evidence", "ref_id": EV_OK},
                     {"id": "o2", "kind": "magic", "ref_id": EV_OK}],
        }
        clean, dropped = n08.filter_draft_refs(draft, self._seen())
        self.assertEqual([o["id"] for o in clean["orbs"]], ["o1"])
        self.assertIn("orb_kind:magic", dropped)

    def test_evidence_must_have_four_segments(self):
        seen = self._seen() | {"ev:onlytwo", "ev:chunk:notanumber:tv"}
        draft = {"answer_blocks": [{"refs": ["ev:onlytwo", "ev:chunk:notanumber:tv", EV_OK]}],
                 "recommendations": [], "orbs": []}
        clean, _ = n08.filter_draft_refs(draft, seen)
        self.assertEqual(clean["answer_blocks"][0]["refs"], [EV_OK],
                         "即使出现在白名单里，格式不合法的 evidence 引用也应剔除")

    def test_selfcheck_never_raises(self):
        st = n08.n08_selfcheck({"draft": None, "seen_refs": None})
        self.assertIsInstance(st, dict)

    def test_selfcheck_records_warning(self):
        state = {"draft": {"answer_blocks": [{"refs": ["ev:item:300827"]}],
                           "recommendations": [], "orbs": []},
                 "seen_refs": self._seen()}
        out = n08.n08_selfcheck(state)
        self.assertEqual(out["draft"]["answer_blocks"][0]["refs"], [])
        self.assertTrue(any("剔除" in w for w in out["draft"]["warnings"]))

    def test_module_self_test_passes(self):
        self.assertEqual(n08._self_test(), 0)


if __name__ == "__main__":
    unittest.main()
