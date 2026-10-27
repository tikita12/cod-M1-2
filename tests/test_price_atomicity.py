"""Exercise real SDK write construction and stream errors with RPCs mocked out."""
import unittest
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient
from google.api_core.exceptions import AlreadyExists, DeadlineExceeded, ResourceExhausted
from google.auth.credentials import AnonymousCredentials
from google.cloud import firestore
from google.cloud.firestore_v1.types import CommitResponse, BeginTransactionResponse

from app.config import Settings
from app.errors import RecordConflict, RecordNotFound, StoreQuotaExceeded, StoreTimeout, TooManyRecords
from app.main import create_app
from app.repositories.firestore import FirestoreRepository
from app.schemas import PriceCreate, PriceUpdate
from app.services.prices import PriceService, document_for_price


class AtomicPriceTests(unittest.TestCase):
    def setUp(self):
        self.client = firestore.Client(project='offline-tests', credentials=AnonymousCredentials())
        self.addCleanup(self.client.close)
        # Never construct a transport: every SDK RPC goes to this mock.
        self.rpc = Mock()
        self.client._firestore_api_internal = self.rpc
        self.rpc.begin_transaction.return_value = BeginTransactionResponse(transaction=b'test')
        self.rpc.commit.return_value = CommitResponse()
        self.repo = object.__new__(FirestoreRepository)
        self.repo.client = self.client
        self.repo.collection = self.client.collection('data')
        self.repo.analysis_cache = self.client.collection('analysis_cache')
        self.repo.conversations = self.client.collection('conversations')
        self.service = PriceService(self.repo, Settings())
        self.payload = PriceCreate(year_month='2024-11', item_name='감자', variety_name='수미',
                                   grade_name='상품', quantity=1, unit='kg', average_price=80)
        self.key, self.data = document_for_price(self.payload)
        self.cached = {'saved': 'revision six'}
        self.service._analysis = self.cached
        self.service._analysis_revision = 6
        self.snapshot = Mock(id=self.key, exists=True, to_dict=Mock(return_value=self.data))
        self.read = self.enterContext(patch.object(firestore.DocumentReference, 'get', return_value=self.snapshot))

    def mutate(self, operation):
        if operation == 'create':
            return self.service.create(self.payload)
        if operation == 'update':
            return self.service.update(self.key, PriceUpdate(average_price=75))
        return self.service.delete(self.key)

    def assert_atomic_commit(self, operation):
        self.rpc.commit.assert_called_once()
        writes = self.rpc.commit.call_args.kwargs['request']['writes']
        self.assertEqual(len(writes), 2)
        price_write, revision_write = writes
        self.assertTrue((price_write.delete if operation == 'delete' else price_write.update.name)
                        .endswith('/data/' + self.key))
        self.assertTrue(revision_write.update.name.endswith('/analysis_cache/revision'))
        transform = revision_write.update_transforms[0]
        self.assertEqual(transform.field_path, 'revision')
        self.assertEqual(transform.increment.integer_value, 1)
        if operation == 'create':
            self.assertFalse(price_write.current_document.exists)
        if operation == 'update':
            self.assertTrue(price_write.current_document.exists)

    def test_success_atomically_increments_revision_and_invalidates_memory(self):
        for operation in ('create', 'update', 'delete'):
            with self.subTest(operation=operation):
                self.rpc.commit.reset_mock()
                self.read.reset_mock()
                self.service._analysis = self.cached
                self.service._analysis_revision = 6
                result = self.mutate(operation)
                self.assert_atomic_commit(operation)
                self.assertIsNone(self.service._analysis)
                self.assertIsNone(self.service._analysis_revision)
                if operation == 'update':
                    self.assertEqual(result['average_price'], '75')
                    self.assertEqual(result['created_at'], self.data['created_at'])
                    self.read.assert_called_once()  # No read after successful commit.

    def test_failed_commit_keeps_revision_six_cache_and_has_no_separate_write(self):
        for operation in ('create', 'update', 'delete'):
            with self.subTest(operation=operation):
                self.rpc.commit.reset_mock()
                self.rpc.commit.side_effect = ResourceExhausted('quota')
                with self.assertRaises(StoreQuotaExceeded):
                    self.mutate(operation)
                self.assert_atomic_commit(operation)
                self.assertIs(self.service._analysis, self.cached)
                self.assertEqual(self.service._analysis_revision, 6)
                with patch.object(self.repo, 'analysis_records') as scan:
                    self.assertIs(self.service._get_analysis(), self.cached)
                    scan.assert_not_called()

    def test_duplicate_and_missing_mutations_preserve_cache(self):
        self.rpc.commit.side_effect = AlreadyExists('duplicate')
        with self.assertRaises(RecordConflict):
            self.mutate('create')
        self.rpc.commit.reset_mock()
        self.snapshot.exists = False
        for operation in ('update', 'delete'):
            with self.assertRaises(RecordNotFound):
                self.mutate(operation)
        self.rpc.commit.assert_not_called()
        self.assertIs(self.service._analysis, self.cached)
        self.assertEqual(self.service._analysis_revision, 6)

    def test_real_sdk_stream_deadline_is_translated_without_retry_or_attribute_error(self):
        def expired_stream(*args, **kwargs):
            def responses():
                raise DeadlineExceeded('private diagnostic')
                yield
            return responses()

        self.rpc.run_query.side_effect = expired_stream
        operations = [lambda: self.repo.analysis_records('2014-12', '2024-12', 20000),
                      lambda: self.repo.list_page(10), self.repo.probe,
                      lambda: self.repo.list_conversations('owner')]
        for operation in operations:
            with self.subTest(operation=operation):
                self.rpc.run_query.reset_mock()
                with self.assertRaises(StoreTimeout):
                    operation()
                self.rpc.run_query.assert_called_once()

    def test_timeout_api_response_and_failed_analysis_does_not_persist_cache(self):
        self.service._analysis = None
        self.service._analysis_revision = None
        def expired_stream(*args, **kwargs):
            raise DeadlineExceeded('private diagnostic')
            yield
        self.rpc.run_query.side_effect = expired_stream
        with patch.object(self.repo, 'analysis_revision', return_value=6), \
             patch.object(self.repo, 'read_analysis_cache', return_value=None), \
             patch.object(self.repo, 'write_analysis_cache') as persist, \
             TestClient(create_app(Settings(), self.repo)) as client:
            response = client.get('/api/data/summary?month=11')
            self.assertEqual(response.status_code, 503)
            self.assertEqual(response.json()['code'], 'firestore_timeout')
            self.assertNotIn('private diagnostic', response.text)
            self.assertIsNone(client.app.state.price_service._analysis)
            persist.assert_not_called()
        self.rpc.commit.assert_not_called()

    def test_analysis_paginates_without_duplicates_and_bounds_reads(self):
        docs = [Mock(id=str(i), to_dict=Mock(return_value={'year_month': '2024-11'}))
                for i in range(503)]
        query = Mock()
        query.where.return_value = query
        query.order_by.return_value = query
        query.limit.return_value = query
        query.start_after.return_value = query
        self.repo.collection = query
        query.stream.side_effect = [iter(docs[:500]), iter(docs[500:])]
        rows = self.repo.analysis_records('2014-12', '2024-12', 1000)
        self.assertEqual([row['id'] for row in rows], [str(i) for i in range(503)])
        query.start_after.assert_called_once_with(docs[499])
        self.assertEqual([call.args[0] for call in query.limit.call_args_list], [500, 500])
        query.limit.reset_mock()
        query.stream.side_effect = [iter(docs[:500]), iter(docs[500:502])]
        with self.assertRaises(TooManyRecords):
            self.repo.analysis_records('2014-12', '2024-12', 501)
        self.assertEqual([call.args[0] for call in query.limit.call_args_list], [500, 2])

    def test_analysis_later_page_timeout_returns_no_partial_result(self):
        query = Mock()
        query.where.return_value = query
        query.order_by.return_value = query
        query.limit.return_value = query
        query.start_after.return_value = query
        self.repo.collection = query
        query.stream.side_effect = [iter([self.snapshot] * 500), DeadlineExceeded('timeout')]
        with self.assertRaises(StoreTimeout):
            self.repo.analysis_records('2014-12', '2024-12', 1000)
        self.assertEqual(query.stream.call_count, 2)


if __name__ == '__main__':
    unittest.main()
