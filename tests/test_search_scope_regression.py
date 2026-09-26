import unittest
from unittest.mock import patch
from server import analysis_service, runtime, tools

class SearchScopeRegression(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        runtime.init_runtime()

    def test_explicit_search_overrides_company_and_year(self):
        user = runtime.authenticate('Bearer demo-token-region-a')
        with patch.object(analysis_service.langgraph_client, 'run', side_effect=AssertionError('List query must use database')):
            result = analysis_service.prepare_analysis('我想知道2019年光伏产业哪些企业正在筹备', user,
                {'scode':'688223','year':2021}, {}, [], {}, 'reg_search_scope')
        analysis = result['analysis']
        self.assertIsNone(analysis['context']['scode'])
        self.assertEqual(analysis['context']['year'], 2019)
        self.assertIn('共 6 个', analysis['answer_blocks'][0]['text'])
        self.assertFalse(any(o['kind']=='evidence' for o in analysis['orbs']))
        self.assertTrue(all(x['stage']=='T0' and x['year']==2019 for x in result['state']['last_search']['items']))

    def test_empty_search_does_not_attach_old_evidence(self):
        user = runtime.authenticate('Bearer demo-token-region-a')
        result = analysis_service.prepare_analysis('找2030年光伏筹备企业', user,
            {'scode':'688223','year':2021}, {}, [], {}, 'reg_empty_search')
        self.assertEqual(result['analysis']['context']['year'], 2030)
        self.assertEqual(result['state']['last_search']['total'], 0)
        self.assertFalse(any(o['kind']=='evidence' for o in result['analysis']['orbs']))

    def test_stage_filter_matches_independent_aggregation(self):
        from server import logic
        frame = logic.filter_industry(logic.agg(), '光伏')
        expected = frame[(frame.year==2019)&(frame.stage=='T0')&frame.window_type.notna()]
        actual = tools.search_companies({},industry='光伏',year=2019,stage='筹备期')
        self.assertEqual(actual['total'],len(expected))
        self.assertEqual({x['scode'] for x in actual['items']},set(expected.scode))
