"""Offline checks: no paid AI requests or Firestore quota usage."""
import unittest
from unittest.mock import Mock, patch

from app.config import Settings
from app.errors import AIUnavailable
from app.schemas import ChatRequest
from app.services.chat import ChatService
from app.services.prices import PriceService


class ChatTests(unittest.TestCase):
    def setUp(self):
        self.repo = Mock()
        self.prices = Mock()
        self.prices.summary.return_value = {
            'target_month': 11, 'previous_month': 10,
            'metadata': {'start_year': 2015, 'end_year': 2024,
                         'interpretation': 'Historical tendency'},
            'candidates': [{'item_name': 'cabbage', 'category': 'vegetable',
                            'median_change_pct': -24.6, 'sample_year_count': 10,
                            'drop_year_count': 10, 'drop_frequency_pct': 100}]}
        self.payload = ChatRequest(message='Recommend soup', month=11,
                                   owner_id='11111111-1111-4111-8111-111111111111')
        self.service = ChatService(self.repo, self.prices, Settings(openai_api_key='test'))
        self.repo.append_conversation.return_value = ({'id': 'saved'}, True)

    def test_missing_key_does_not_read_or_send(self):
        self.service.settings = Settings(openai_api_key='')
        with patch('app.services.chat.httpx.Client') as provider:
            with self.assertRaises(AIUnavailable):
                self.service.answer(self.payload)
            provider.assert_not_called()
        self.prices.summary.assert_not_called()
        self.repo.append_conversation.assert_not_called()

    def test_summary_and_history_are_sent_and_pair_saved(self):
        self.payload.conversation_id = '22222222-2222-4222-8222-222222222222'
        self.repo.get_conversation.return_value = {
            'messages': [{'role': 'user', 'content': 'No meat'}]}
        with patch('app.services.chat.httpx.Client') as provider:
            post = provider.return_value.__enter__.return_value.post
            post.return_value.is_error = False
            post.return_value.json.return_value = {'status': 'completed', 'output': [
                {'type': 'reasoning', 'content': None},
                {'content': [{'type': 'output_text', 'text': 'Cabbage soup'}]}]}
            result = self.service.answer(self.payload)
            body = post.call_args.kwargs['json']
        self.assertIn('-24.6', body['instructions'])
        self.assertEqual(body['input'][0]['content'], 'No meat')
        self.assertEqual(body['input'][-1]['content'], self.payload.message)
        self.assertFalse(body['store'])
        self.repo.get_conversation.assert_called_once_with(self.payload.conversation_id, self.payload.owner_id)
        args = self.repo.append_conversation.call_args.args
        self.assertEqual(args[2]['role'], 'user')
        self.assertEqual(args[3]['content'], 'Cabbage soup')
        self.assertEqual(result['conversation_id'], 'saved')

    def test_failed_or_incomplete_response_never_saved(self):
        for http_error, status in [(True, 'failed'), (False, 'incomplete')]:
            with self.subTest(status=status), patch('app.services.chat.httpx.Client') as provider:
                response = provider.return_value.__enter__.return_value.post.return_value
                response.is_error = http_error
                response.json.return_value = {'status': status, 'output_text': 'Partial recipe'}
                with self.assertRaises(AIUnavailable):
                    self.service.answer(self.payload)
        self.repo.append_conversation.assert_not_called()

    def test_month_changes_reuse_analysis_until_invalidated(self):
        self.repo.analysis_records.return_value = []
        service = PriceService(self.repo, Settings())
        for month in range(1, 13):
            service.summary(month, 8)
        self.assertEqual(self.repo.analysis_records.call_count, 1)
        service.invalidate_analysis()
        service.summary(11, 8)
        self.assertEqual(self.repo.analysis_records.call_count, 2)
