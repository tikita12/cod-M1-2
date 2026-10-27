"""In-process API tests with an explicit test double, not real Firestore."""
import copy
import os
import unittest
from datetime import date
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient
from google.api_core.exceptions import AlreadyExists, NotFound, ServiceUnavailable, ResourceExhausted
from google.auth.credentials import AnonymousCredentials
from google.cloud import firestore

from app.config import Settings
from app.errors import RecordConflict, RecordNotFound, StoreUnavailable, TooManyRecords
from app.main import create_app
from app.repositories.firestore import FirestoreRepository, unavailable


class TestStore:
    def __init__(self):
        self.rows = {}
        self.analysis_cache = None
        self.revision = 0

    def create(self, key, data):
        if key in self.rows:
            raise RecordConflict()
        self.rows[key] = {**copy.deepcopy(data), 'id': key}
        return self.get(key)

    def get(self, key):
        if key not in self.rows:
            raise RecordNotFound()
        return copy.deepcopy(self.rows[key])

    def update(self, key, changes):
        self.get(key)
        self.rows[key].update(changes)
        return self.get(key)

    def delete(self, key):
        self.get(key)
        del self.rows[key]

    def list_page(self, limit, cursor=None, item_name=None):
        rows = sorted((self.get(key) for key in self.rows
                       if not item_name or self.rows[key]['item_name'] == item_name),
                      key=lambda row: (row['year_month'], row['id']), reverse=True)
        if cursor:
            boundary = tuple(cursor.split(':', 1))
            rows = [row for row in rows if (row['year_month'], row['id']) < boundary]
        more = len(rows) > limit
        return {'items': rows[:limit], 'has_more': more,
                'next_cursor': f"{rows[limit - 1]['year_month']}:{rows[limit - 1]['id']}" if more else None}

    def analysis_records(self, first_month, last_month, max_records):
        rows = [self.get(key) for key in sorted(self.rows) if first_month <= self.rows[key]['year_month'] <= last_month]
        if len(rows) > max_records:
            raise TooManyRecords()
        return rows

    def probe(self):
        return None

    def mark_analysis_stale(self):
        self.revision += 1

    def analysis_revision(self):
        return self.revision

    def read_analysis_cache(self, revision, start_year, end_year, min_years):
        if not self.analysis_cache:
            return None
        saved_revision, saved_start, saved_end, saved_min, data = self.analysis_cache
        return copy.deepcopy(data) if (revision, start_year, end_year, min_years) == (saved_revision, saved_start, saved_end, saved_min) else None

    def write_analysis_cache(self, revision, start_year, end_year, min_years, data):
        self.analysis_cache = (revision, start_year, end_year, min_years, copy.deepcopy(data))


def price(period='2024-11', **changes):
    return {'year_month': period, 'item_name': '감자', 'variety_name': '수미', 'grade_name': '상품',
            'quantity': 1, 'unit': 'kg', 'average_price': 80, **changes}


class PriceApiTests(unittest.TestCase):
    def setUp(self):
        self.store = TestStore()
        self.client = TestClient(create_app(Settings(admin_api_key='test-key', analysis_start_year=2023,
                                                      analysis_end_year=2024, analysis_min_years=2), self.store))
        self.headers = {'X-Admin-Key': 'test-key'}

    def tearDown(self):
        self.client.close()

    def add(self, body):
        response = self.client.post('/api/data', json=body, headers=self.headers)
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def test_full_crud_and_duplicate_protection(self):
        created = self.add(price())
        key = created['id']
        self.assertEqual(self.client.get('/api/data').json()['items'][0]['id'], key)
        self.assertEqual(self.client.post('/api/data', json=price(), headers=self.headers).status_code, 409)
        self.assertEqual(self.client.get('/api/data/'+key).status_code, 200)
        edited = self.client.patch('/api/data/'+key, json={'average_price': 75, 'note': '가격 정정'}, headers=self.headers)
        self.assertEqual(edited.status_code, 200)
        self.assertEqual(edited.json()['id'], key)
        self.assertEqual(edited.json()['average_price'], '75')
        self.assertEqual(edited.json()['created_at'], created['created_at'])
        self.assertEqual(self.client.delete('/api/data/'+key, headers=self.headers).status_code, 204)
        self.assertEqual(self.client.get('/api/data/'+key).status_code, 404)
        self.assertEqual(self.client.patch('/api/data/'+key, json={'average_price': 75}, headers=self.headers).status_code, 404)
        self.assertEqual(self.client.delete('/api/data/'+key, headers=self.headers).status_code, 404)

    def test_summary_reflects_creates_edits_and_deletes(self):
        self.assertEqual(self.client.get('/api/data/summary?month=11').json()['candidate_count'], 0)
        for year in [2023, 2024]:
            self.add(price(f'{year}-10', average_price=100))
            item = self.add(price(f'{year}-11'))
        result = self.client.get('/api/data/summary?month=11').json()
        self.assertEqual(result['candidates'][0]['median_change_pct'], -20)
        self.assertEqual(result['metadata']['selected_record_count'], 4)
        key = item['id']
        self.client.patch('/api/data/'+key, json={'average_price': 120}, headers=self.headers)
        self.assertEqual(self.client.get('/api/data/summary?month=11').json()['candidate_count'], 0)
        self.client.delete('/api/data/'+key, headers=self.headers)
        self.assertEqual(self.client.get('/api/data/summary?month=11').json()['metadata']['selected_record_count'], 3)

    def test_equivalent_units_collide(self):
        self.add(price(quantity=100, unit='g'))
        response = self.client.post('/api/data', json=price(quantity='0.1'), headers=self.headers)
        self.assertEqual(response.status_code, 409)

    def test_invalid_input_and_unknown_fields_are_rejected(self):
        for changes in [{'average_price': 0}, {'average_price': -1}, {'average_price': 'NaN'},
                        {'year_month': '2024-13'}, {'year_month': date.today().strftime('%Y-%m')},
                        {'variety_name': '<script>x</script>'}, {'item_name': '없는품목'},
                        {'quantity': 0}, {'grade_name': '데이터 미집계'}, {'source': 'csv'}]:
            response = self.client.post('/api/data', json=price(**changes), headers=self.headers)
            self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(self.store.rows, {})

    def test_write_authentication_and_pagination(self):
        self.assertEqual(self.client.post('/api/data', json=price()).status_code, 401)
        self.assertEqual(self.client.post('/api/data', json=price(), headers={'X-Admin-Key': 'wrong'}).status_code, 401)
        for month in [9, 10, 11]:
            self.add(price(f'2024-{month:02d}'))
        first = self.client.get('/api/data?limit=2').json()
        second = self.client.get('/api/data', params={'limit': 2, 'cursor': first['next_cursor']}).json()
        self.assertTrue(first['has_more'])
        self.assertFalse(second['has_more'])
        self.assertEqual(len({r['id'] for r in first['items']+second['items']}), 3)
        self.assertEqual([r['year_month'] for r in first['items']+second['items']],
                         ['2024-11', '2024-10', '2024-09'])
        self.assertEqual(self.client.get('/api/data?limit=101').status_code, 422)

    def test_latest_month_order_across_pages_and_search(self):
        # Insert older data last so creation order cannot satisfy the assertions.
        created = [self.add(price(period, quantity=quantity, item_name=item))
                   for period, quantity, item in [
                       ('2024-11', 1, '감자'), ('2024-12', 1, '감자'),
                       ('2024-12', 2, '감자'), ('2024-12', 3, '감자'),
                       ('2024-12', 1, '배추'), ('2023-01', 1, '감자')]]
        for item_name in [None, '감자', '배추', '없는품목']:
            with self.subTest(item_name=item_name):
                params = {'limit': 2}
                if item_name:
                    params['item_name'] = item_name
                actual = []
                for _ in range(len(created) + 1):
                    response = self.client.get('/api/data', params=params)
                    self.assertEqual(response.status_code, 200, response.text)
                    page = response.json()
                    actual.extend(page['items'])
                    if not page['has_more']:
                        self.assertIsNone(page['next_cursor'])
                        break
                    params['cursor'] = page['next_cursor']
                else:
                    self.fail('Pagination did not terminate')
                expected = sorted((r for r in created if not item_name or r['item_name'] == item_name),
                                  key=lambda r: (r['year_month'], r['id']), reverse=True)
                self.assertEqual([r['id'] for r in actual], [r['id'] for r in expected])

    def test_deleted_cursor_record_and_invalid_cursor(self):
        for month in [9, 10, 11]:
            self.add(price(f'2024-{month:02d}'))
        first = self.client.get('/api/data?limit=1').json()
        self.client.delete('/api/data/' + first['items'][0]['id'], headers=self.headers)
        following = self.client.get('/api/data', params={'cursor': first['next_cursor']}).json()
        self.assertEqual([r['year_month'] for r in following['items']], ['2024-10', '2024-09'])
        for cursor in ['a' * 64, '2024-13:' + 'a' * 64, '2024-11:bad']:
            self.assertEqual(self.client.get('/api/data', params={'cursor': cursor}).status_code, 422)

    def test_cors_and_swagger(self):
        response = self.client.options('/api/data', headers={'Origin': 'http://localhost:5173',
            'Access-Control-Request-Method': 'POST', 'Access-Control-Request-Headers': 'Content-Type,X-Admin-Key'})
        self.assertEqual(response.headers['access-control-allow-origin'], 'http://localhost:5173')
        denied = self.client.options('/api/data', headers={'Origin': 'https://untrusted.example',
            'Access-Control-Request-Method': 'POST'})
        self.assertNotIn('access-control-allow-origin', denied.headers)
        self.assertEqual(self.client.get('/docs').status_code, 200)
        schema = self.client.get('/openapi.json').json()
        self.assertIn('/api/data/summary', schema['paths'])
        self.assertEqual(schema['components']['securitySchemes']['APIKeyHeader']['name'], 'X-Admin-Key')

    def test_frontend_assets_and_secret_isolation(self):
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        self.assertIn('제철한끼', response.text)
        for asset in ['/app.js', '/styles.css', '/config.js', '/sample/seasonal_rankings.json']:
            self.assertEqual(self.client.get(asset).status_code, 200)
        self.assertEqual(self.client.get('/.env').status_code, 404)
        self.assertEqual(self.client.get('/data/raw').status_code, 404)

    def test_missing_firestore_does_not_fall_back_to_memory(self):
        with TestClient(create_app(Settings())) as client:
            self.assertEqual(client.get('/health').status_code, 200)
            self.assertFalse(client.get('/health').json()['firestore_configured'])
            self.assertEqual(client.get('/health/ready').status_code, 503)
            self.assertEqual(client.get('/api/data').status_code, 503)
            self.assertEqual(client.get('/api/data/summary').status_code, 503)


class FirestoreAdapterTests(unittest.TestCase):
    def test_list_query_sorts_before_limit_and_uses_both_cursor_fields(self):
        client = firestore.Client(project='offline-tests', credentials=AnonymousCredentials())
        self.repo.collection = client.collection('data')
        ids = ['c' * 64, 'b' * 64, 'a' * 64]
        docs = [Mock(id=key, to_dict=Mock(return_value={'year_month': '2024-11'})) for key in ids]
        queries = []

        def stream(query, **kwargs):
            queries.append(query._to_protobuf())
            return iter(docs)

        try:
            with patch.object(firestore.Query, 'stream', stream):
                for item_name in [None, '감자']:
                    result = self.repo.list_page(2, '2024-12:' + 'd' * 64, item_name)
                    query = queries[-1]
                    self.assertEqual([(order.field.field_path, order.direction) for order in query.order_by],
                                     [('year_month', 2), ('__name__', 2)])
                    self.assertEqual(query.limit, 3)
                    self.assertEqual(query.start_at.values[0].string_value, '2024-12')
                    self.assertTrue(query.start_at.values[1].reference_value.endswith('/data/' + 'd' * 64))
                    self.assertFalse(query.start_at.before)
                    if item_name:
                        self.assertEqual(query.where.field_filter.field.field_path, 'item_name')
                        self.assertEqual(query.where.field_filter.value.string_value, item_name)
                    self.assertEqual([row['id'] for row in result['items']], ids[:2])
                    self.assertTrue(result['has_more'])
                    self.assertEqual(result['next_cursor'], '2024-11:' + ids[1])
        finally:
            client.close()

    def test_quota_error_is_distinct_and_does_not_expose_sdk_details(self):
        store = TestStore()
        store.analysis_records = Mock(side_effect=unavailable('analysis query', ResourceExhausted('private diagnostic')))
        with TestClient(create_app(Settings(), store)) as client:
            response = client.get('/api/data/summary?month=11')
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()['code'], 'firestore_quota_exceeded')
        self.assertNotIn('private diagnostic', response.text)

    def setUp(self):
        self.repo = object.__new__(FirestoreRepository)
        self.repo.collection = Mock()

    def test_create_translates_duplicate_and_connection_failures(self):
        doc = self.repo.collection.document.return_value
        doc.create.side_effect = AlreadyExists('duplicate')
        with self.assertRaises(RecordConflict):
            self.repo.create('x', {})
        doc.create.side_effect = ServiceUnavailable('offline')
        with self.assertRaises(StoreUnavailable):
            self.repo.create('x', {})

    def test_update_does_not_upsert_missing_record(self):
        self.repo.collection.document.return_value.update.side_effect = NotFound('missing')
        with self.assertRaises(RecordNotFound):
            self.repo.update('x', {'average_price': '20'})

    def test_empty_emulator_setting_uses_cloud_endpoint(self):
        with patch.dict(os.environ, {'FIRESTORE_EMULATOR_HOST': ''}):
            settings = Settings.from_env()
            self.assertEqual(settings.firestore_emulator_host, '')
            self.assertNotIn('FIRESTORE_EMULATOR_HOST', os.environ)


if __name__ == '__main__':
    unittest.main()
