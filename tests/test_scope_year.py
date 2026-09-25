"""回归检查：防止跨年泄漏、缺失值误判和全量/截断混用。"""
import unittest
from unittest.mock import patch
import pandas as pd
from server import logic, graph
from server.main import api_radar, api_segments


class TestScopeYear(unittest.TestCase):
    def test_missing_is_not_zero(self):
        for a, b in [(None, 0), (0, float('nan')), (None, None)]:
            self.assertEqual(logic.layout_status(a, b), 'unknown')
        self.assertEqual(logic.layout_status(0, 0), 'none')
        self.assertEqual(logic.layout_status(None, .1), 'existing')
        self.assertEqual(logic.layout_status(2, None), 'existing')

    def test_default_year_shared(self):
        for code in ['002860', '600690', '688223']:
            year = logic.resolve_year(code)
            self.assertEqual(logic.company_detail(code)['year'], year)
            self.assertEqual(logic.supply_chain(code)['year'], year)
            self.assertEqual(graph.get_company_graph(code)['year'], year)
            chain = logic.chain(code)
            if chain:
                self.assertEqual(chain['year'], year)

    def test_public_detail_never_falls_back(self):
        d = logic.company_detail('002860', 2000, strict_year=False)
        self.assertEqual(d['year'], 2000)
        self.assertIsNone(d['assets'])
        self.assertEqual(d['signals'], [])
        self.assertEqual(d['history']['count'], 0)
        self.assertIsNone(logic.chain('002860', 2000))
        self.assertEqual(len(graph.get_company_graph('002860', 2000)['nodes']), 1)

    def test_future_customer_never_leaks(self):
        claims = pd.DataFrame([{'scode':'002860', 'year':2023, 'execution_anchor_type':'named_customer',
                               'execution_anchor':'FUTURE_CUSTOMER', 'evidence_quote':'future', 'time_state':'future'}])
        with patch.object(logic, '_claims', return_value=claims):
            result = logic.supply_chain('002860', 2018)
        self.assertNotIn('FUTURE_CUSTOMER', str(result))

    def test_score_uses_same_year_reference(self):
        cap = logic.capability_score('002860', 2020)
        p = logic._panel()
        row = p[(p.scode == '002860') & (p.year == 2020)].iloc[0]
        ref = p[p.year == 2020].assets.dropna()
        expected = round(float((ref <= row.assets).mean()), 3)
        size = next(x for x in cap['dims'] if x['key'] == 'size')
        self.assertEqual(size['value'], expected)
        self.assertEqual(cap['reference_year'], 2020)
        self.assertEqual(len(cap['dims']), 6)

    def test_radar_total_not_page_length(self):
        result = api_radar(limit=1, sort='window')
        self.assertEqual(len(result['items']), 1)
        self.assertEqual(result['total'], len(logic.agg()))

    def test_segment_year_counts(self):
        result = api_segments(year=2018)
        self.assertEqual(sum(x['firms'] for x in result['items']), int(logic._panel().query('year == 2018').scode.nunique()))
        self.assertEqual(sum(x['deploy'] + x['intent'] for x in result['items']), len(logic._claims().query('year == 2018').loc[lambda d:d.program_label.isin(logic.DEMAND_LABELS)]))

    def test_all_segments_and_no_unresolved(self):
        self.assertEqual(logic.segment_of('300750'), '储能与电源')
        self.assertEqual(logic.segment_of('688063'), '储能与电源')
        self.assertEqual(logic.segment_of('301155'), '风电设备')
        self.assertEqual(len(logic.radar(industry='电气设备', limit=2000)), len(logic.radar(limit=2000)))
        rows = logic.radar(industry='风电设备', limit=2000)
        self.assertTrue(rows)
        for row in rows:
            self.assertEqual(row['segment'], '风电设备')
        self.assertEqual(logic._conn().execute("SELECT COUNT(*) FROM chunks WHERE program_label='unresolved'").fetchone()[0], 0)
        self.assertNotIn('pv_text', set(logic.agg().window_type))


if __name__ == '__main__':
    unittest.main()
