"""Offline checks: no paid AI requests or Firestore quota usage."""
import unittest
from unittest.mock import Mock, patch

import httpx

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
            post.return_value.json.return_value = {'choices': [
                {'finish_reason': 'stop', 'message': {'content': '  Cabbage soup  '}}]}
            result = self.service.answer(self.payload)
            body = post.call_args.kwargs['json']
        self.assertEqual(post.call_args.args[0], 'https://copa.codyssey.kr/v1/chat/completions')
        self.assertEqual(post.call_args.kwargs['headers']['Authorization'], 'Bearer test')
        self.assertEqual(body['model'], 'gpt-5-mini')
        self.assertEqual(body['messages'][0]['role'], 'system')
        self.assertIn('-24.6', body['messages'][0]['content'])
        self.assertEqual(body['messages'][1], {'role': 'user', 'content': 'No meat'})
        self.assertEqual(body['messages'][-1]['content'], self.payload.message)
        self.assertNotIn('input', body)
        self.assertNotIn('instructions', body)
        self.prices.summary.assert_called_once_with(11, 8)
        self.assertFalse(body['store'])
        self.repo.get_conversation.assert_called_once_with(self.payload.conversation_id, self.payload.owner_id)
        args = self.repo.append_conversation.call_args.args
        self.assertEqual(args[2]['role'], 'user')
        self.assertEqual(args[3]['content'], 'Cabbage soup')
        self.assertEqual(result['conversation_id'], 'saved')

    def test_failed_or_incomplete_response_never_saved(self):
        for http_error, reason in [(True, 'stop'), (False, 'length'), (False, 'content_filter')]:
            with self.subTest(http_error=http_error, reason=reason), patch('app.services.chat.httpx.Client') as provider:
                response = provider.return_value.__enter__.return_value.post.return_value
                response.is_error = http_error
                response.json.return_value = {'choices': [
                    {'finish_reason': reason, 'message': {'content': 'Partial recipe'}}]}
                with self.assertRaises(AIUnavailable):
                    self.service.answer(self.payload)
        self.repo.append_conversation.assert_not_called()

    def test_empty_or_malformed_response_never_saved(self):
        results = [None, {}, {'choices': []}, {'choices': None}, {'choices': [None]},
                   {'choices': [{'finish_reason': 'stop'}]}]
        results.extend({'choices': [{'finish_reason': 'stop', 'message': {'content': content}}]}
                       for content in [None, '', '   ', [], 123])
        for result in results:
            with self.subTest(result=result), patch('app.services.chat.httpx.Client') as provider:
                response = provider.return_value.__enter__.return_value.post.return_value
                response.is_error = False
                response.json.return_value = result
                with self.assertRaises(AIUnavailable):
                    self.service.answer(self.payload)
        self.repo.append_conversation.assert_not_called()

    def test_connection_and_json_errors_never_saved(self):
        for error in [httpx.ReadTimeout('timeout'), ValueError('invalid JSON')]:
            with self.subTest(error=type(error).__name__), patch('app.services.chat.httpx.Client') as provider:
                post = provider.return_value.__enter__.return_value.post
                if isinstance(error, httpx.HTTPError):
                    post.side_effect = error
                else:
                    post.return_value.is_error = False
                    post.return_value.json.side_effect = error
                with self.assertRaises(AIUnavailable):
                    self.service.answer(self.payload)
        self.repo.append_conversation.assert_not_called()

    def test_month_changes_reuse_analysis_until_invalidated(self):
        self.repo.read_analysis_cache.return_value = None
        self.repo.analysis_records.return_value = []
        service = PriceService(self.repo, Settings())
        for month in range(1, 13):
            service.summary(month, 8)
        self.assertEqual(self.repo.analysis_records.call_count, 1)
        service.invalidate_analysis()
        service.summary(11, 8)
        self.assertEqual(self.repo.analysis_records.call_count, 2)
