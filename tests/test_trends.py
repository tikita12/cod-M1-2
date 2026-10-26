import unittest
from unittest.mock import Mock

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.services.trends import build_trends
from test_api import TestStore, price


class TrendTests(unittest.TestCase):
    def test_series_keep_conditions_separate_and_gaps_empty(self):
        base = dict(item_name='cabbage', variety_name='fall', grade_name='high',
                    comparison_quantity='0.6', comparison_unit='kg')
        rows = [{**base, 'year_month': '2023-11', 'average_price': '900'},
                {**base, 'year_month': '2024-09', 'average_price': '4200'},
                {**base, 'year_month': '2024-11', 'average_price': '2600'},
                {**base, 'grade_name': 'medium', 'year_month': '2024-11', 'average_price': '1800'},
                {**base, 'comparison_quantity': '1', 'year_month': '2024-11', 'average_price': '3900'}]
        result = build_trends(rows)['cabbage']
        self.assertEqual(len(result), 3)
        series = next(s for s in result if s['grade_name'] == 'high' and s['quantity'] == '0.6')
        self.assertEqual(series['year'], 2024)
        self.assertEqual(series['points'][8]['price'], 4200)
        self.assertIsNone(series['points'][9]['price'])
        self.assertEqual(series['points'][10]['price'], 2600)
        novembers = [p for p in series['history'] if p['month'] == 11]
        self.assertEqual(novembers, [{'year': 2023, 'month': 11, 'price': 900},
                                    {'year': 2024, 'month': 11, 'price': 2600}])

    def test_trend_reuses_summary_cache_and_refreshes_after_crud(self):
        store = TestStore()
        store.analysis_records = Mock(wraps=store.analysis_records)
        with TestClient(create_app(Settings(admin_api_key='test-key'), store)) as client:
            headers = {'X-Admin-Key': 'test-key'}
            added = client.post('/api/data', json=price(), headers=headers).json()
            self.assertEqual(client.get('/api/data/summary?month=11').status_code, 200)
            trend = client.get('/api/data/trend', params={'item_name': '감자'})
            self.assertEqual(trend.status_code, 200, trend.text)
            self.assertEqual(trend.json()['series'][0]['points'][10]['price'], 80)
            self.assertEqual(store.analysis_records.call_count, 1)
            client.patch('/api/data/'+added['id'], json={'average_price': 75}, headers=headers)
            updated = client.get('/api/data/trend', params={'item_name': '감자'}).json()
            self.assertEqual(updated['series'][0]['points'][10]['price'], 75)
            self.assertEqual(updated['series'][0]['history'][0]['price'], 75)
            self.assertEqual(store.analysis_records.call_count, 2)
            client.delete('/api/data/'+added['id'], headers=headers)
            self.assertEqual(client.get('/api/data/trend', params={'item_name': '감자'}).json()['series'], [])
            self.assertEqual(client.get('/api/data/trend', params={'item_name': ''}).status_code, 422)
