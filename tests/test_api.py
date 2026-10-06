import unittest
from unittest.mock import Mock, patch
import requests
from xuanyi.api import ChatTranslationAPI, TranslationError, completion_url, protect_api_key, unprotect_api_key

OPTIONS={'chat_translation_enabled':True,'chat_translation_api_url':'https://api.deepseek.com','chat_translation_model':'deepseek-flash','chat_translation_api_key_protected':'encrypted-test-only'}

class TranslationAPITests(unittest.TestCase):
    def make_api(self, options=None):
        with patch('xuanyi.api.unprotect_api_key', return_value='test-key-not-real'):
            return ChatTranslationAPI(options or OPTIONS)

    def response(self, status=200, data=None):
        response = Mock(status_code=status)
        response.json.return_value = data if data is not None else {
            'choices': [{'message': {'content': '你好'}}]}
        return response

    def test_base_versioned_and_complete_https_urls(self):
        for value, expected in (
                ('https://api.deepseek.com', 'https://api.deepseek.com/chat/completions'),
                ('https://example.com/v1/', 'https://example.com/v1/chat/completions'),
                ('https://example.com/v1/chat/completions/', 'https://example.com/v1/chat/completions')):
            self.assertEqual(completion_url(value), expected)

    def test_invalid_and_credential_bearing_urls_rejected(self):
        for value in ('http://example.com', 'https://u:p@example.com', 'https://@example.com',
                      'https://example.com?q=1', 'https://example.com?', 'https://example.com#',
                      'https://example.com:bad', 'https://example .com', '', None):
            with self.subTest(value=value), self.assertRaises(TranslationError):
                completion_url(value)

    def test_payload_only_contains_body_and_correct_auth_no_redirect_retry(self):
        response = self.response()
        api = self.make_api()
        with patch('xuanyi.api.requests.post', return_value=response) as post:
            self.assertEqual(api.translate('Hello'), '你好')
        post.assert_called_once()
        args, kwargs = post.call_args
        self.assertEqual(args, ('https://api.deepseek.com/chat/completions',))
        self.assertEqual(kwargs['headers'], {'Authorization': 'Bearer test-key-not-real'})
        self.assertFalse(kwargs['allow_redirects'])
        self.assertEqual(kwargs['timeout'], (5, 20))
        self.assertEqual(kwargs['json']['messages'][1], {'role': 'user', 'content': 'Hello'})
        self.assertEqual(kwargs['json']['thinking'], {'type': 'disabled'})
        self.assertIn('Chinese', kwargs['json']['messages'][0]['content'])
        self.assertIn('English', kwargs['json']['messages'][0]['content'])
        self.assertFalse(kwargs['json']['stream'])
        response.close.assert_called_once()

    def test_custom_openai_compatible_model_omits_deepseek_extension(self):
        api = self.make_api({**OPTIONS, 'chat_translation_api_url': 'https://example.com/v1',
                             'chat_translation_model': 'custom-model'})
        with patch('xuanyi.api.requests.post', return_value=self.response()) as post:
            api.translate('hello')
        self.assertEqual(post.call_args.kwargs['json']['model'], 'custom-model')
        self.assertNotIn('thinking', post.call_args.kwargs['json'])

    def test_outgoing_target_language_forces_english_without_changing_receive_prompt(self):
        api = self.make_api()
        with patch('xuanyi.api.requests.post', return_value=self.response(
                data={'choices': [{'message': {'content': 'Who am I?'}}]})) as post:
            self.assertEqual(api.translate('我是谁', target_language='en'), 'Who am I?')
        prompt = post.call_args.kwargs['json']['messages'][0]['content']
        self.assertIn('into natural English', prompt)
        self.assertNotIn('otherwise translate', prompt)
        self.assertEqual(post.call_args.kwargs['json']['messages'][1]['content'], '我是谁')

    def test_http_errors_timeouts_and_malformed_responses_are_safe_single_attempt(self):
        for status in (301, 401, 429, 500):
            response = self.response(status, {'error': 'secret test-key-not-real'})
            with self.subTest(status=status), patch('xuanyi.api.requests.post',
                                                  return_value=response) as post:
                with self.assertRaises(TranslationError) as error:
                    self.make_api().translate('hello')
                self.assertNotIn('test-key-not-real', str(error.exception))
                post.assert_called_once()
                response.json.assert_not_called()
        for error in (requests.Timeout('secret test-key-not-real'),
                      requests.ConnectionError('Authorization: Bearer test-key-not-real')):
            with patch('xuanyi.api.requests.post', side_effect=error) as post:
                with self.assertRaises(TranslationError) as safe:
                    self.make_api().translate('hello')
                self.assertNotIn('test-key-not-real', str(safe.exception))
                post.assert_called_once()
        for data in ({}, {'choices': []}, {'choices': [{'message': {'content': ''}}]},
                     {'choices': [{'message': {'content': None}}]}):
            with patch('xuanyi.api.requests.post', return_value=self.response(data=data)):
                with self.assertRaises(TranslationError):
                    self.make_api().translate('hello')

    def test_invalid_messages_do_not_request(self):
        with patch('xuanyi.api.requests.post') as post:
            for value in ('', 'a' * 4001, None):
                with self.assertRaises(TranslationError):
                    self.make_api().translate(value)
            post.assert_not_called()

    def test_bad_credentials_are_rejected_without_echo(self):
        for key in ('', 'bad key', 'x\ny', 'x' * 2049):
            with self.assertRaises(TranslationError):
                protect_api_key(key)
        with self.assertRaises(TranslationError) as error:
            unprotect_api_key('not-a-real-encrypted-secret')
        self.assertNotIn('not-a-real-encrypted-secret', str(error.exception))
